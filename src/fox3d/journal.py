"""Durable append-only pilot event journal. Audit/recovery evidence, not event-sourcing."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.storelock import FileLock

GENESIS = "GENESIS"
SCHEMA = "fox3d.journal.v1"


class JournalCommitError(RuntimeError):
    """Required durable audit append could not be committed."""


class SemanticKeyConflictError(JournalCommitError, ValueError):
    """Same semantic_key reused with different eventType or payloadHash."""


def _validate_since_seq(since_seq: Any) -> int:
    if isinstance(since_seq, (bool, float)):
        raise ValueError("since_seq must be a non-negative integer")
    if isinstance(since_seq, int):
        seq = since_seq
    elif isinstance(since_seq, str):
        raw = since_seq.strip()
        if not raw:
            raise ValueError("since_seq must be a non-negative integer")
        try:
            seq = int(raw)
        except ValueError as exc:
            raise ValueError("since_seq must be a non-negative integer") from exc
    else:
        raise ValueError("since_seq must be a non-negative integer")
    if seq < 0:
        raise ValueError("since_seq must be a non-negative integer")
    return seq


def _maybe_crash(owner: Any, point: str) -> None:
    if getattr(owner, "_crash_mode", "") != point:
        return
    if getattr(owner, "_hard_crash", False):
        os._exit(1)
    from fox3d.storelock import CrashInjected

    raise CrashInjected(point)


def emit(
    owner: Any,
    event_type: str,
    *,
    tenant_id: str,
    aggregate_type: str,
    aggregate_id: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    release_hash: str | None = None,
    semantic_key: str | None = None,
    source: str | None = None,
) -> dict[str, Any] | None:
    """Persist business snapshot first when possible, then COMMITTED journal."""
    persist = getattr(owner, "persist", None)
    if getattr(owner, "_tx_depth", 0) == 0 and callable(persist):
        # Defer persist to the outbox path below so PREPARED exists first.
        pass
    event = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "actor": actor,
        "payload": payload or {},
        "release_hash": release_hash,
        "semantic_key": semantic_key,
        "source": source,
    }
    journal = getattr(owner, "journal", None)
    outbox = getattr(owner, "outbox", None) or getattr(journal, "outbox", None) if journal is not None else getattr(owner, "outbox", None)
    if journal is None:
        if getattr(owner, "_tx_depth", 0) == 0 and callable(persist):
            persist()
        return None
    if outbox is not None and callable(persist) and getattr(owner, "_tx_depth", 0) == 0:
        tx = outbox.prepare(event)
        _maybe_crash(owner, "after-outbox-prepare")
        persist()
        if hasattr(outbox, "mark_business_committed"):
            outbox.mark_business_committed(tx["txId"])
        _maybe_crash(owner, "after-business-persist")
        rec = journal.append(
            event_type,
            tenant_id=tenant_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor=actor,
            payload=payload or {},
            release_hash=release_hash,
            semantic_key=semantic_key,
            source=source,
        )
        outbox.complete(tx["txId"])
        _maybe_crash(owner, "after-outbox-complete")
        return rec
    if getattr(owner, "_tx_depth", 0) == 0 and callable(persist):
        persist()
    return journal.append(
        event_type,
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        actor=actor,
        payload=payload or {},
        release_hash=release_hash,
        semantic_key=semantic_key,
        source=source,
    )


class EventJournal:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._fail_next = False
        self.outbox: Any | None = None

    def _safe(self, tenant_id: str) -> str:
        return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in tenant_id)

    def _path(self, tenant_id: str) -> Path:
        return self.root / f"{self._safe(tenant_id)}.json"

    def _lock_path(self, tenant_id: str) -> Path:
        return self.root / f"{self._safe(tenant_id)}.lock"

    def _load(self, tenant_id: str) -> dict[str, Any]:
        payload = read_json(self._path(tenant_id)) or {}
        if not payload:
            return {"tenantId": tenant_id, "schemaVersion": SCHEMA, "headHash": GENESIS, "sequence": 0, "events": []}
        if payload.get("tenantId") not in {None, tenant_id}:
            raise PermissionError("tenant isolation: journal")
        payload.setdefault("events", [])
        payload.setdefault("headHash", GENESIS)
        payload.setdefault("sequence", 0)
        payload.setdefault("schemaVersion", SCHEMA)
        return payload

    def _event_hash(self, rec: dict[str, Any]) -> str:
        body = {k: rec[k] for k in rec if k != "eventHash"}
        return stable_hash(body)

    def append(
        self,
        event_type: str,
        *,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        actor: str,
        payload: dict[str, Any] | None = None,
        release_hash: str | None = None,
        semantic_key: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        if self._fail_next:
            self._fail_next = False
            raise JournalCommitError("injected journal failure")
        body = payload or {}
        payload_hash = stable_hash(body)
        with self._lock:
            with FileLock(self._lock_path(tenant_id)):
                data = self._load(tenant_id)
                if semantic_key:
                    for ev in data["events"]:
                        if ev.get("semanticKey") == semantic_key:
                            if ev.get("tenantId") != tenant_id:
                                raise PermissionError("tenant isolation: journal")
                            if ev.get("eventType") != event_type or ev.get("payloadHash") != payload_hash:
                                raise SemanticKeyConflictError(
                                    f"semantic_key conflict for {semantic_key}: eventType or payloadHash mismatch"
                                )
                            return ev
                seq = int(data.get("sequence") or 0) + 1
                rec = {
                    "eventId": new_id(),
                    "eventType": event_type,
                    "tenantId": tenant_id,
                    "aggregateType": aggregate_type,
                    "aggregateId": aggregate_id,
                    "sequence": seq,
                    "actor": actor,
                    "source": source or actor,
                    "at": utcnow().isoformat(),
                    "releaseHash": release_hash,
                    "payload": body,
                    "payloadHash": payload_hash,
                    "previousEventHash": data.get("headHash") or GENESIS,
                    "semanticKey": semantic_key,
                    "schemaVersion": SCHEMA,
                    "commitStatus": "COMMITTED",
                }
                rec["eventHash"] = self._event_hash(rec)
                data["events"].append(rec)
                data["sequence"] = seq
                data["headHash"] = rec["eventHash"]
                data["tenantId"] = tenant_id
                try:
                    atomic_write_json(self._path(tenant_id), data)
                except Exception as exc:
                    raise JournalCommitError(str(exc)) from exc
                return rec

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(ev) for ev in self._load(tenant_id).get("events") or [] if ev.get("tenantId") == tenant_id]

    def verify(self, tenant_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._load(tenant_id)
        events = data.get("events") or []
        prev = GENESIS
        for idx, ev in enumerate(events, start=1):
            if ev.get("tenantId") != tenant_id:
                return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "tenant-mix", "label": "BLOCKED_EVIDENCE"}
            if ev.get("previousEventHash") != prev:
                return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "chain-break", "label": "BLOCKED_EVIDENCE"}
            ev_seq = ev.get("sequence")
            if isinstance(ev_seq, bool) or ev_seq != idx:
                return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "sequence-gap", "label": "BLOCKED_EVIDENCE"}
            if self._event_hash(ev) != ev.get("eventHash"):
                return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "payload-tamper", "label": "BLOCKED_EVIDENCE"}
            prev = ev.get("eventHash")
        raw_seq = data.get("sequence", 0)
        if isinstance(raw_seq, bool) or not isinstance(raw_seq, int) or raw_seq < 0:
            return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "truncated", "label": "BLOCKED_EVIDENCE"}
        header_seq = raw_seq
        count = len(events)
        last_seq = events[-1].get("sequence") if events else 0
        if last_seq != header_seq or count != header_seq:
            return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "truncated", "label": "BLOCKED_EVIDENCE"}
        if (data.get("headHash") or GENESIS) != prev:
            return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "head-mismatch", "label": "BLOCKED_EVIDENCE"}
        open_tx = []
        if self.outbox is not None:
            open_tx = self.outbox.list_open(tenant_id=tenant_id)
        if open_tx:
            return {
                "ok": False,
                "status": "BLOCKED_EVIDENCE",
                "reason": "incomplete-tx",
                "label": "BLOCKED_EVIDENCE",
                "openTransactions": len(open_tx),
            }
        return {
            "ok": True,
            "status": "REAL",
            "label": "REAL",
            "count": count,
            "headHash": prev,
            "sequence": header_seq,
        }

    def export_slice(self, tenant_id: str, *, since_seq: int = 0) -> dict[str, Any]:
        min_seq = _validate_since_seq(since_seq)
        events = [e for e in self.list(tenant_id) if int(e.get("sequence") or 0) >= min_seq]
        integrity = self.verify(tenant_id)
        bundle = {
            "tenantId": tenant_id,
            "schemaVersion": SCHEMA,
            "exportedAt": utcnow().isoformat(),
            "events": events,
            "integrity": integrity,
            "truthLabel": "REAL" if integrity.get("ok") else "BLOCKED_EVIDENCE",
            "liveMachineControl": False,
        }
        bundle["contentHash"] = stable_hash({"events": events, "integrity": integrity})
        return bundle

    def tamper(self, tenant_id: str, index: int, **fields: Any) -> None:
        """Test helper: break the hash chain."""
        with self._lock:
            with FileLock(self._lock_path(tenant_id)):
                data = self._load(tenant_id)
                data["events"][index].update(fields)
                atomic_write_json(self._path(tenant_id), data)
