"""PREPARED -> business commit -> COMMITTED audit outbox. Not event-sourcing."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.storelock import FileLock

PREPARED = "PREPARED"
BUSINESS_COMMITTED = "BUSINESS_COMMITTED"
ABORTED = "ABORTED"
COMMITTED = "COMMITTED"


class CommitOutbox:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._fail_prepare = False

    def _path(self, tx_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in tx_id)
        return self.root / f"{safe}.json"

    def prepare(self, event: dict[str, Any], *, expected_generation: int | None = None) -> dict[str, Any]:
        if self._fail_prepare:
            self._fail_prepare = False
            from fox3d.journal import JournalCommitError

            raise JournalCommitError("injected outbox prepare failure")
        rec = {
            "txId": new_id(),
            "status": PREPARED,
            "tenantId": event.get("tenant_id") or event.get("tenantId"),
            "semanticKey": event.get("semantic_key") or event.get("semanticKey"),
            "aggregateType": event.get("aggregate_type") or event.get("aggregateType"),
            "aggregateId": event.get("aggregate_id") or event.get("aggregateId"),
            "event": event,
            "expectedGeneration": expected_generation,
            "at": utcnow().isoformat(),
        }
        rec["txHash"] = stable_hash({k: rec[k] for k in rec if k != "txHash"})
        with self._lock:
            with FileLock(self.root / "outbox.lock"):
                atomic_write_json(self._path(rec["txId"]), rec)
        return rec

    def mark_business_committed(self, tx_id: str, *, observed_generation: int | None = None) -> dict[str, Any]:
        rec = self._read(tx_id)
        rec["status"] = BUSINESS_COMMITTED
        rec["observedGeneration"] = observed_generation
        rec["businessCommittedAt"] = utcnow().isoformat()
        with FileLock(self.root / "outbox.lock"):
            atomic_write_json(self._path(tx_id), rec)
        return rec

    def complete(self, tx_id: str) -> None:
        path = self._path(tx_id)
        if path.exists():
            path.unlink()

    def abort(self, tx_id: str) -> None:
        self.complete(tx_id)

    def _read(self, tx_id: str) -> dict[str, Any]:
        rec = read_json(self._path(tx_id)) or {}
        if not rec:
            raise KeyError(tx_id)
        return rec

    def list_open(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.root.glob("*.json")):
            rec = read_json(path) or {}
            if rec.get("status") in {PREPARED, BUSINESS_COMMITTED}:
                if tenant_id is None or rec.get("tenantId") == tenant_id:
                    rows.append(rec)
        return rows

    def reconcile(
        self,
        *,
        journal: Any,
        business_committed: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any]:
        """Deterministic recovery. PREPARED without business -> abort. Business without journal -> finalize."""
        finalized = 0
        aborted = 0
        for tx in self.list_open():
            ev = dict(tx.get("event") or {})
            tenant_id = tx.get("tenantId")
            semantic = tx.get("semanticKey")
            committed = False
            if journal is not None and semantic:
                existing = [e for e in journal.list(tenant_id) if e.get("semanticKey") == semantic]
                if existing:
                    self.complete(tx["txId"])
                    finalized += 1
                    continue
            try:
                committed = bool(business_committed(tx))
            except Exception:
                committed = False
            if committed or tx.get("status") == BUSINESS_COMMITTED:
                if journal is not None:
                    journal.append(
                        str(ev.get("event_type") or ev.get("eventType") or "reconcile"),
                        tenant_id=str(ev.get("tenant_id") or tenant_id),
                        aggregate_type=str(ev.get("aggregate_type") or tx.get("aggregateType") or "Unknown"),
                        aggregate_id=str(ev.get("aggregate_id") or tx.get("aggregateId") or tx["txId"]),
                        actor=str(ev.get("actor") or "reconcile"),
                        payload=dict(ev.get("payload") or {}),
                        release_hash=ev.get("release_hash") or ev.get("releaseHash"),
                        semantic_key=semantic,
                        source=str(ev.get("source") or "reconcile"),
                    )
                self.complete(tx["txId"])
                finalized += 1
            else:
                self.abort(tx["txId"])
                aborted += 1
        return {"finalized": finalized, "aborted": aborted, "open": len(self.list_open())}
