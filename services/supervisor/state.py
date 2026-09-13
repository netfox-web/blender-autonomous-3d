"""Durable supervisor state and concurrency locking backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.supervisor.models import (
    ReviewDecision,
    ReviewRecord,
    SupervisorReviewOutput,
    SupervisorState,
    SupervisorStatus,
)


class StateManager:
    """Manages persistent supervisor state, locks, and idempotency."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._local_lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._local_lock, self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS seen_events (
                    delivery_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS delivery_lifecycle (
                    delivery_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    sender TEXT,
                    received_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS supervisor_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_seen_event_id TEXT,
                    last_reviewed_code_sha TEXT,
                    last_reviewed_docs_sha TEXT,
                    last_processed_instruction_sha TEXT,
                    active_review_id TEXT,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY,
                    code_sha TEXT NOT NULL,
                    evidence_generation_id TEXT NOT NULL,
                    decision TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    staged_commit_sha TEXT,
                    instruction_commit_sha TEXT,
                    instruction_remote_verified_at TEXT,
                    issue_comment_id TEXT,
                    issue_comment_posted_at TEXT,
                    review_write_stage TEXT DEFAULT 'NONE',
                    output_json TEXT,
                    error TEXT,
                    UNIQUE(code_sha, evidence_generation_id)
                );

                CREATE TABLE IF NOT EXISTS pending_queue (
                    code_sha TEXT PRIMARY KEY,
                    evidence_generation_id TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    enqueued_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS active_lock (
                    lock_id INTEGER PRIMARY KEY CHECK (lock_id = 1),
                    holder_review_id TEXT,
                    locked_code_sha TEXT,
                    locked_at TEXT
                );
                """
            )
            # Schema migration for existing DBs
            for col, col_type in [
                ("staged_commit_sha", "TEXT"),
                ("instruction_commit_sha", "TEXT"),
                ("instruction_remote_verified_at", "TEXT"),
                ("issue_comment_id", "TEXT"),
                ("issue_comment_posted_at", "TEXT"),
                ("review_write_stage", "TEXT DEFAULT 'NONE'"),
                ("intended_instruction_sha256", "TEXT"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE reviews ADD COLUMN {col} {col_type}")
                except Exception:
                    pass

            # Ensure singleton supervisor_state row exists
            cur = conn.cursor()
            cur.execute("SELECT id FROM supervisor_state WHERE id = 1")
            if not cur.fetchone():
                now_iso = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    """
                    INSERT INTO supervisor_state (
                        id, status, retry_count, started_at, completed_at
                    ) VALUES (1, ?, 0, ?, ?)
                    """,
                    (SupervisorStatus.IDLE.value, now_iso, now_iso),
                )
            conn.commit()

    # --- Delivery Lifecycle Management ---

    def evaluate_delivery(self, delivery_id: str) -> Tuple[bool, str]:
        """
        Check delivery lifecycle status.
        Returns: (can_process: bool, reason: str)
        """
        if not delivery_id:
            return True, "NO_DELIVERY_ID"

        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, updated_at FROM delivery_lifecycle WHERE delivery_id = ?", (delivery_id,))
            row = cur.fetchone()
            if not row:
                return True, "NEW"

            status = row["status"]
            if status in ("COMPLETED", "FAILED_TERMINAL"):
                return False, "IGNORED_DUPLICATE_DELIVERY"

            if status == "FAILED_RETRYABLE":
                return True, "RETRYABLE_FAILURE"

            if status in ("RECEIVED", "PROCESSING"):
                # Check for stale processing (> 10 minutes)
                try:
                    updated_at = datetime.fromisoformat(row["updated_at"])
                    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
                    if age_seconds > 600:
                        return True, "STALE_PROCESSING_RESUMED"
                except Exception:
                    pass
                return False, "PROCESSING_IN_FLIGHT"

            return False, f"STATUS_{status}"

    def record_delivery_received(self, delivery_id: str, event_type: str, sender: str = "") -> None:
        if not delivery_id:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO delivery_lifecycle (
                    delivery_id, status, event_type, sender, received_at, updated_at
                ) VALUES (?, 'RECEIVED', ?, ?, ?, ?)
                ON CONFLICT(delivery_id) DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (delivery_id, event_type, sender, now_iso, now_iso),
            )
            # Maintain backward compatibility seen_events
            conn.execute(
                "INSERT OR IGNORE INTO seen_events (delivery_id, event_type, received_at) VALUES (?, ?, ?)",
                (delivery_id, event_type, now_iso),
            )
            conn.commit()

    def set_delivery_status(self, delivery_id: str, status: str, error: str = "") -> None:
        if not delivery_id:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                UPDATE delivery_lifecycle
                SET status = ?,
                    error = COALESCE(NULLIF(?, ''), error),
                    updated_at = ?
                WHERE delivery_id = ?
                """,
                (status, error, now_iso, delivery_id),
            )
            conn.commit()

    def has_seen_delivery(self, delivery_id: str) -> bool:
        """Legacy helper matching seen_events or completed delivery."""
        can_proc, reason = self.evaluate_delivery(delivery_id)
        return not can_proc and reason == "IGNORED_DUPLICATE_DELIVERY"

    def record_delivery(self, delivery_id: str, event_type: str) -> None:
        self.record_delivery_received(delivery_id, event_type)

    # --- Idempotency & Reviews ---

    def is_already_reviewed(self, code_sha: str, evidence_generation_id: str) -> bool:
        """Idempotency check: code_sha + evidence_generation_id must only be reviewed once."""
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM reviews WHERE code_sha = ? AND evidence_generation_id = ? AND completed_at IS NOT NULL AND decision IS NOT NULL",
                (code_sha, evidence_generation_id),
            )
            return cur.fetchone() is not None

    def get_state(self) -> SupervisorState:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT last_seen_event_id, last_reviewed_code_sha, last_reviewed_docs_sha,
                       last_processed_instruction_sha, active_review_id, status,
                       retry_count, started_at, completed_at
                FROM supervisor_state WHERE id = 1
                """
            )
            row = cur.fetchone()
            if not row:
                return SupervisorState()
            return SupervisorState(
                last_seen_event_id=row["last_seen_event_id"],
                last_reviewed_code_sha=row["last_reviewed_code_sha"],
                last_reviewed_docs_sha=row["last_reviewed_docs_sha"],
                last_processed_instruction_sha=row["last_processed_instruction_sha"],
                active_review_id=row["active_review_id"],
                status=SupervisorStatus(row["status"]),
                retry_count=row["retry_count"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
            )

    def set_status(
        self,
        status: SupervisorStatus,
        active_review_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                UPDATE supervisor_state
                SET status = ?,
                    active_review_id = COALESCE(?, active_review_id),
                    last_seen_event_id = COALESCE(?, last_seen_event_id),
                    started_at = CASE WHEN ? = 'REVIEWING' THEN ? ELSE started_at END
                WHERE id = 1
                """,
                (status.value, active_review_id, event_id, status.value, now_iso),
            )
            conn.commit()

    def acquire_review_lock(
        self, review_id: str, code_sha: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to acquire durable review lock.
        Returns (acquired: bool, current_locked_code_sha: Optional[str]).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT holder_review_id, locked_code_sha FROM active_lock WHERE lock_id = 1")
            row = cur.fetchone()
            if row and row["holder_review_id"]:
                if row["holder_review_id"] == review_id:
                    return True, code_sha
                return False, row["locked_code_sha"]

            cur.execute(
                """
                INSERT INTO active_lock (lock_id, holder_review_id, locked_code_sha, locked_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(lock_id) DO UPDATE SET
                    holder_review_id = excluded.holder_review_id,
                    locked_code_sha = excluded.locked_code_sha,
                    locked_at = excluded.locked_at
                """,
                (review_id, code_sha, now_iso),
            )
            conn.commit()
            return True, code_sha

    def release_review_lock(self, review_id: str) -> None:
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                "UPDATE active_lock SET holder_review_id = NULL, locked_code_sha = NULL, locked_at = NULL WHERE lock_id = 1 AND holder_review_id = ?",
                (review_id,),
            )
            conn.commit()

    def enqueue_pending_evidence(
        self, code_sha: str, evidence_generation_id: str, contract_json: str
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO pending_queue (code_sha, evidence_generation_id, contract_json, enqueued_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(code_sha) DO UPDATE SET
                    evidence_generation_id = excluded.evidence_generation_id,
                    contract_json = excluded.contract_json,
                    enqueued_at = excluded.enqueued_at
                """,
                (code_sha, evidence_generation_id, contract_json, now_iso),
            )
            conn.commit()

    def pop_latest_pending(self) -> Optional[Dict[str, Any]]:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT code_sha, evidence_generation_id, contract_json, enqueued_at FROM pending_queue ORDER BY enqueued_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None
            data = dict(row)
            conn.execute("DELETE FROM pending_queue WHERE code_sha = ?", (row["code_sha"],))
            conn.commit()
            return data

    def start_review(
        self,
        review_id: str,
        code_sha: str,
        evidence_generation_id: str,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO reviews (review_id, code_sha, evidence_generation_id, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(code_sha, evidence_generation_id) DO NOTHING
                """,
                (review_id, code_sha, evidence_generation_id, now_iso),
            )
            conn.execute(
                """
                UPDATE supervisor_state
                SET active_review_id = ?,
                    status = ?,
                    started_at = ?
                WHERE id = 1
                """,
                (review_id, SupervisorStatus.REVIEWING.value, now_iso),
            )
            conn.commit()

    def set_review_staged_commit(self, review_id: str, staged_commit_sha: str) -> None:
        """Record the committed instruction SHA so crash recovery will not commit twice."""
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                "UPDATE reviews SET staged_commit_sha = ? WHERE review_id = ?",
                (staged_commit_sha, review_id),
            )
            conn.commit()

    def get_review_staged_commit(self, review_id: str) -> Optional[str]:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT staged_commit_sha FROM reviews WHERE review_id = ?", (review_id,))
            row = cur.fetchone()
            return row["staged_commit_sha"] if row else None

    def get_staged_commit(self, code_sha: str, evidence_generation_id: str) -> Optional[str]:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT staged_commit_sha FROM reviews WHERE code_sha = ? AND evidence_generation_id = ?",
                (code_sha, evidence_generation_id),
            )
            row = cur.fetchone()
            return row["staged_commit_sha"] if row and row["staged_commit_sha"] else None

    def set_intended_instruction(self, review_id: str, sha256_digest: str) -> None:
        """Durable persistence of intended instruction digest before write."""
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                "UPDATE reviews SET intended_instruction_sha256 = ? WHERE review_id = ?",
                (sha256_digest, review_id),
            )
            conn.commit()

    def get_intended_instruction_sha256(self, review_id: str) -> Optional[str]:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT intended_instruction_sha256 FROM reviews WHERE review_id = ?", (review_id,))
            row = cur.fetchone()
            return row["intended_instruction_sha256"] if row and row["intended_instruction_sha256"] else None

    def get_intended_instruction_sha256_by_contract(self, code_sha: str, evidence_generation_id: str) -> Optional[str]:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT intended_instruction_sha256 FROM reviews WHERE code_sha = ? AND evidence_generation_id = ?",
                (code_sha, evidence_generation_id),
            )
            row = cur.fetchone()
            return row["intended_instruction_sha256"] if row and row["intended_instruction_sha256"] else None

    def record_instruction_pushed(self, review_id: str, commit_sha: str, verified_at: Optional[str] = None) -> None:
        now_iso = verified_at or datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                UPDATE reviews
                SET instruction_commit_sha = ?,
                    staged_commit_sha = ?,
                    instruction_remote_verified_at = ?,
                    review_write_stage = 'INSTRUCTION_PUSHED'
                WHERE review_id = ?
                """,
                (commit_sha, commit_sha, now_iso, review_id),
            )
            conn.commit()

    def record_comment_posted(self, review_id: str, comment_id: str, posted_at: Optional[str] = None) -> None:
        now_iso = posted_at or datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                UPDATE reviews
                SET issue_comment_id = ?,
                    issue_comment_posted_at = ?,
                    review_write_stage = 'COMMENT_POSTED'
                WHERE review_id = ?
                """,
                (comment_id, now_iso, review_id),
            )
            conn.commit()

    def get_review_by_contract(self, code_sha: str, evidence_generation_id: str) -> Optional[Dict[str, Any]]:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM reviews WHERE code_sha = ? AND evidence_generation_id = ?",
                (code_sha, evidence_generation_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def complete_review(
        self,
        review_id: str,
        code_sha: str,
        docs_sha: str,
        instruction_sha: str,
        output: SupervisorReviewOutput,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        output_json = json.dumps(output.model_dump(), ensure_ascii=False)
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                UPDATE reviews
                SET decision = ?,
                    completed_at = ?,
                    review_write_stage = 'COMPLETED',
                    output_json = ?
                WHERE review_id = ?
                """,
                (output.decision.value, now_iso, output_json, review_id),
            )
            next_status = (
                SupervisorStatus.BLOCKED.value
                if output.decision == ReviewDecision.BLOCKED
                else SupervisorStatus.WAITING_AGENT.value
            )
            conn.execute(
                """
                UPDATE supervisor_state
                SET last_reviewed_code_sha = ?,
                    last_reviewed_docs_sha = ?,
                    last_processed_instruction_sha = ?,
                    active_review_id = NULL,
                    status = ?,
                    completed_at = ?
                WHERE id = 1
                """,
                (code_sha, docs_sha, instruction_sha, next_status, now_iso),
            )
            conn.commit()

    def fail_review(self, review_id: str, error_msg: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                """
                UPDATE reviews
                SET completed_at = ?,
                    error = ?
                WHERE review_id = ?
                """,
                (now_iso, error_msg, review_id),
            )
            conn.execute(
                """
                UPDATE supervisor_state
                SET active_review_id = NULL,
                    status = ?,
                    retry_count = retry_count + 1,
                    completed_at = ?
                WHERE id = 1
                """,
                (SupervisorStatus.FAILED.value, now_iso),
            )
            conn.commit()

    def list_reviews(self, limit: int = 20) -> List[ReviewRecord]:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT review_id, code_sha, evidence_generation_id, decision,
                       created_at, completed_at, instruction_commit_sha,
                       instruction_remote_verified_at, issue_comment_id,
                       issue_comment_posted_at, review_write_stage,
                       output_json, error
                FROM reviews ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            results: List[ReviewRecord] = []
            for row in cur.fetchall():
                out = None
                if row["output_json"]:
                    try:
                        out = SupervisorReviewOutput.model_validate_json(row["output_json"])
                    except Exception:
                        pass
                results.append(
                    ReviewRecord(
                        review_id=row["review_id"],
                        code_sha=row["code_sha"],
                        evidence_generation_id=row["evidence_generation_id"],
                        decision=ReviewDecision(row["decision"]) if row["decision"] else None,
                        created_at=row["created_at"],
                        completed_at=row["completed_at"],
                        instruction_commit_sha=row["instruction_commit_sha"],
                        instruction_remote_verified_at=row["instruction_remote_verified_at"],
                        issue_comment_id=row["issue_comment_id"],
                        issue_comment_posted_at=row["issue_comment_posted_at"],
                        review_write_stage=row["review_write_stage"] or "NONE",
                        output=out,
                        error=row["error"],
                    )
                )
            return results

    def get_review(self, review_id: str) -> Optional[ReviewRecord]:
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT review_id, code_sha, evidence_generation_id, decision,
                       created_at, completed_at, instruction_commit_sha,
                       instruction_remote_verified_at, issue_comment_id,
                       issue_comment_posted_at, review_write_stage,
                       output_json, error
                FROM reviews WHERE review_id = ?
                """,
                (review_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            out = None
            if row["output_json"]:
                try:
                    out = SupervisorReviewOutput.model_validate_json(row["output_json"])
                except Exception:
                    pass
            return ReviewRecord(
                review_id=row["review_id"],
                code_sha=row["code_sha"],
                evidence_generation_id=row["evidence_generation_id"],
                decision=ReviewDecision(row["decision"]) if row["decision"] else None,
                created_at=row["created_at"],
                completed_at=row["completed_at"],
                instruction_commit_sha=row["instruction_commit_sha"],
                instruction_remote_verified_at=row["instruction_remote_verified_at"],
                issue_comment_id=row["issue_comment_id"],
                issue_comment_posted_at=row["issue_comment_posted_at"],
                review_write_stage=row["review_write_stage"] or "NONE",
                output=out,
                error=row["error"],
            )
