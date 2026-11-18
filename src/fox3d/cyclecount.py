"""Manual cycle count. Variance waits human approval. Not ERP valuation."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import emit
from fox3d.operator import require_confirm

BOOK_CHANGED_MSG = "帳面已變動，請重新盤點"


class CycleCountConflict(PermissionError):
    """Snapshot stale or invalid state transition for cycle count approval."""


def _now() -> str:
    return utcnow().isoformat()


class CycleCountService:
    def __init__(self, lots: Any, root: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.lots = lots
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.counts: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, str] = {}
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
        with self._lock:
            key = f"{tenant_id}::cc::{idempotency_key or lot_id}:{counted}:{reason}"
            if key in self._idem:
                existing = self.counts[self._idem[key]]
                if existing.get("tenantId") != tenant_id:
                    raise PermissionError("tenant isolation: cycle count")
                return existing
            q = self.lots.quantities(lot_id, tenant_id=tenant_id)
            rec: dict[str, Any] = {
                "cycleCountId": new_id(),
                "tenantId": tenant_id,
                "lotId": lot_id,
                "systemAvailable": int(q["available"]),
                "systemReserved": int(q["reserved"]),
                "systemConsumed": int(q["consumed"]),
                "systemSheetCount": int(q["sheetCount"]),
                "counted": int(counted),
                "variance": int(counted) - int(q["available"]),
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
            return rec

    def _book_matches_snapshot(self, rec: dict[str, Any], *, tenant_id: str) -> bool:
        before = self.lots.quantities(rec["lotId"], tenant_id=tenant_id)
        return (
            int(before["available"]) == int(rec["systemAvailable"])
            and int(before["reserved"]) == int(rec["systemReserved"])
            and int(before["consumed"]) == int(rec["systemConsumed"])
        )

    def approve(self, cycle_count_id: str, *, tenant_id: str, actor: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            require_confirm(payload, action="cycle_count_adjust")
            rec = self._get(cycle_count_id, tenant_id=tenant_id)
            if rec.get("applied"):
                return rec
            status = rec.get("status")
            if status in {"REJECTED", "CANCELLED"}:
                raise PermissionError(rec["status"])
            if not self._book_matches_snapshot(rec, tenant_id=tenant_id):
                raise CycleCountConflict(BOOK_CHANGED_MSG)
            before = self.lots.quantities(rec["lotId"], tenant_id=tenant_id)
            lot = self.lots.apply_counted_available(
                rec["lotId"], tenant_id=tenant_id, counted=int(rec["counted"]), actor=actor, reason=rec["reason"]
            )
            after = self.lots.quantities(rec["lotId"], tenant_id=tenant_id)
            rec["applied"] = True
            rec["status"] = "APPLIED"
            rec["approvedBy"] = actor
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
                actor=actor,
                payload={"lotId": rec["lotId"], "before": before, "after": after},
                semantic_key=f"{tenant_id}::cc-approve::{cycle_count_id}",
            )
            _ = lot
            return rec

    def reject(self, cycle_count_id: str, *, tenant_id: str, actor: str) -> dict[str, Any]:
        with self._lock:
            rec = self._get(cycle_count_id, tenant_id=tenant_id)
            if rec.get("applied"):
                raise PermissionError("cannot reject applied cycle count")
            if rec.get("status") == "REJECTED":
                # Idempotent like approve(): never overwrite the first rejection's audit fields.
                return rec
            rec["status"] = "REJECTED"
            rec["rejectedBy"] = actor
            self.persist()
            return rec