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

    def has_seen_delivery(self, delivery_id: str) -> bool:
        """Check if webhook delivery ID was already received."""
        if not delivery_id:
            return False
        with self._local_lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM seen_events WHERE delivery_id = ?", (delivery_id,))
            return cur.fetchone() is not None

    def record_delivery(self, delivery_id: str, event_type: str) -> None:
        """Record delivery ID for replay protection."""
        if not delivery_id:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._local_lock, self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_events (delivery_id, event_type, received_at) VALUES (?, ?, ?)",
                (delivery_id, event_type, now_iso),
            )
            conn.commit()

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
                       created_at, completed_at, output_json, error
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
                       created_at, completed_at, output_json, error
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
                output=out,
                error=row["error"],
            )
