"""Manual cycle count. Variance waits human approval. Not ERP valuation."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import emit
from fox3d.operator import require_confirm
from fox3d.storelock import FileLock

BOOK_CHANGED_MSG = "帳面已變動，請重新盤點"
IDEMPOTENCY_CONFLICT_MSG = "相同 idempotencyKey 已用於不同內容"


class CycleCountConflict(PermissionError):
    """Snapshot stale, or the same idempotency key was reused for different content."""


def _now() -> str:
    return utcnow().isoformat()


def _explicit_idem_key(tenant_id: str, idempotency_key: str) -> str:
    return f"{tenant_id}::cc-key::{idempotency_key}"


def _implicit_idem_key(tenant_id: str, lot_id: str, counted: int, reason: str) -> str:
    return f"{tenant_id}::cc::{lot_id}:{counted}:{reason}"


def _request_identity(
    *,
    lot_id: str,
    counted: int,
    reason: str,
    actor: str,
    operator_id: str | None,
    shift_id: str | None,
) -> dict[str, Any]:
    """Business fields of one create. Retries must match; derived snapshots must not."""
    return {
        "lotId": lot_id,
        "counted": int(counted),
        "reason": reason,
        "actor": actor,
        "operatorId": operator_id,
        "shiftId": shift_id,
    }


def _saved_identity(saved: dict[str, Any] | None, rec: dict[str, Any]) -> dict[str, Any]:
    source = saved if saved is not None else rec
    return {
        "lotId": source.get("lotId"),
        "counted": source.get("counted"),
        "reason": source.get("reason"),
        "actor": source.get("actor"),
        "operatorId": source.get("operatorId"),
        "shiftId": source.get("shiftId"),
    }


def _idem_target(entry: Any) -> tuple[str, dict[str, Any] | None]:
    """Return (cycleCountId, saved request). Legacy entries store only the id."""
    if isinstance(entry, str) and entry:
        return entry, None
    if isinstance(entry, dict):
        cycle_count_id = entry.get("cycleCountId")
        if isinstance(cycle_count_id, str) and cycle_count_id:
            return cycle_count_id, entry
    raise KeyError("cycle count")


class CycleCountService:
    def __init__(self, lots: Any, root: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.lots = lots
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.counts: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, Any] = {}
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "cyclecounts.json") or {}
        self.counts = {r["cycleCountId"]: r for r in payload.get("counts") or []}
        self._idem = dict(payload.get("idem") or {})

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(self.root / "cyclecounts.json", {"counts": list(self.counts.values()), "idem": self._idem})

    def _lock_path(self) -> Path | None:
        return (self.root / "cyclecounts.lock") if self.root else None

    @contextmanager
    def _durable(self) -> Iterator[None]:
        with self._lock:
            flock: FileLock | None = None
            if self.root:
                flock = FileLock(self._lock_path())  # type: ignore[arg-type]
                flock.acquire()
                self.load()
            try:
                yield
            finally:
                if flock is not None:
                    flock.release()

    def _get(self, cycle_count_id: str, *, tenant_id: str) -> dict[str, Any]:
        try:
            rec = self.counts[cycle_count_id]
        except KeyError:
            raise
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: cycle count")
        return rec

    def list_for_tenant(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        with self._lock:
            rows = [c for c in self.counts.values() if c.get("tenantId") == tenant_id]
            if status:
                want = str(status).strip()
                rows = [r for r in rows if r.get("status") == want]
            rows.sort(key=lambda r: (r.get("createdAt") or "", r.get("cycleCountId") or ""), reverse=True)
            total = len(rows)
            page = rows[offset : offset + limit]
            return {"items": page, "total": total, "offset": offset, "limit": limit}

    def create(
        self,
        *,
        tenant_id: str,
        lot_id: str,
        counted: int,
        reason: str,
        actor: str,
        operator_id: str | None = None,
        shift_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with self._durable():
            provided = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
            identity = _request_identity(
                lot_id=lot_id,
                counted=counted,
                reason=reason,
                actor=actor,
                operator_id=operator_id,
                shift_id=shift_id,
            )
            if provided:
                key = _explicit_idem_key(tenant_id, provided)
            else:
                key = _implicit_idem_key(tenant_id, lot_id, identity["counted"], reason)
            if key in self._idem:
                cycle_count_id, saved = _idem_target(self._idem[key])
                existing = self.counts[cycle_count_id]
                if existing.get("tenantId") != tenant_id:
                    raise PermissionError("tenant isolation: cycle count")
                if provided and _saved_identity(saved, existing) != identity:
                    raise CycleCountConflict(IDEMPOTENCY_CONFLICT_MSG)
                return existing
            q = self.lots.quantities(lot_id, tenant_id=tenant_id)
            counted_n = identity["counted"]
            rec: dict[str, Any] = {
                "cycleCountId": new_id(),
                "tenantId": tenant_id,
                "lotId": lot_id,
                "systemAvailable": int(q["available"]),
                "systemReserved": int(q["reserved"]),
                "systemConsumed": int(q["consumed"]),
                "systemSheetCount": int(q["sheetCount"]),
                "counted": counted_n,
                "variance": counted_n - int(q["available"]),
                "reason": reason,
                "status": "WAITING_HUMAN_APPROVAL",
                "applied": False,
                "actor": actor,
                "operatorId": operator_id,
                "shiftId": shift_id,
                "truthLabel": "REAL_LOGIC / MANUAL",
                "notAccounting": True,
                "createdAt": _now(),
            }
            rec["cycleCountHash"] = stable_hash({k: rec[k] for k in rec if k != "cycleCountHash"})
            self.counts[rec["cycleCountId"]] = rec
            if provided:
                self._idem[key] = {"cycleCountId": rec["cycleCountId"], **identity}
            else:
                self._idem[key] = rec["cycleCountId"]
            emit(
                self,
                "cyclecount.create",
                tenant_id=tenant_id,
                aggregate_type="CycleCount",
                aggregate_id=rec["cycleCountId"],
                actor=actor,
                payload={"lotId": lot_id, "variance": rec["variance"], "status": rec["status"]},
                semantic_key=key,
            )
            if self.journal is None:
                self.persist()
            return rec

    def approve(self, cycle_count_id: str, *, tenant_id: str, actor: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._durable():
            require_confirm(payload, action="cycle_count_adjust")
            rec = self._get(cycle_count_id, tenant_id=tenant_id)
            if rec.get("applied"):
                return rec
            status = rec.get("status")
            if status in {"REJECTED", "CANCELLED"}:
                raise PermissionError(rec["status"])
            before = {
                "available": int(rec["systemAvailable"]),
                "reserved": int(rec["systemReserved"]),
                "consumed": int(rec["systemConsumed"]),
                "sheetCount": int(rec["systemSheetCount"]),
            }
            lot = self.lots.apply_counted_available(
                rec["lotId"],
                tenant_id=tenant_id,
                counted=int(rec["counted"]),
                actor=actor,
                reason=rec["reason"],
                expect_available=int(rec["systemAvailable"]),
                expect_reserved=int(rec["systemReserved"]),
                expect_consumed=int(rec["systemConsumed"]),
                cycle_count_id=cycle_count_id,
            )
            adjustment = next(a for a in lot["adjustments"] if a.get("cycleCountId") == cycle_count_id)
            after = adjustment["after"]
            rec["applied"] = True
            rec["status"] = "APPLIED"
            rec["approvedBy"] = adjustment["actor"]
            rec["before"] = before
            rec["after"] = after
            rec["consumedUnchanged"] = before["consumed"] == after["consumed"]
            rec["reservedUnchanged"] = before["reserved"] == after["reserved"]
            rec["conserved"] = bool(after.get("conserved"))
            emit(
                self,
                "cyclecount.approve",
                tenant_id=tenant_id,
                aggregate_type="CycleCount",
                aggregate_id=cycle_count_id,
                actor=adjustment["actor"],
                payload={"lotId": rec["lotId"], "before": before, "after": after},
                semantic_key=f"{tenant_id}::cc-approve::{cycle_count_id}",
            )
            if self.journal is None:
                self.persist()
            _ = lot
            return rec

    def reject(self, cycle_count_id: str, *, tenant_id: str, actor: str) -> dict[str, Any]:
        with self._durable():
            rec = self._get(cycle_count_id, tenant_id=tenant_id)
            # A committed inventory adjustment must be recovered by approval, never rejected.
            with self.lots._transaction():
                lot = self.lots.get(rec["lotId"], tenant_id=tenant_id)
                committed = any(a.get("cycleCountId") == cycle_count_id for a in lot.get("adjustments", []))
            if rec.get("applied") or committed:
                raise PermissionError("cannot reject applied cycle count")
            if rec.get("status") == "REJECTED":
                # Idempotent like approve(): never overwrite the first rejection's audit fields.
                return rec
            rec["status"] = "REJECTED"
            rec["rejectedBy"] = actor
            self.persist()
            return rec