"""Operator identity and shift sessions. MANUAL_IDENTITY, not production IAM."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import emit


def _now() -> str:
    return utcnow().isoformat()


class OperatorShiftService:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.operators: dict[str, dict[str, Any]] = {}
        self.shifts: dict[str, dict[str, Any]] = {}
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "identity.json") or {}
        self.operators = {r["operatorId"]: r for r in payload.get("operators") or []}
        self.shifts = {r["shiftId"]: r for r in payload.get("shifts") or []}

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(
            self.root / "identity.json",
            {"operators": list(self.operators.values()), "shifts": list(self.shifts.values()), "truthLabel": "MANUAL_IDENTITY"},
        )

    def register_operator(
        self,
        *,
        tenant_id: str,
        display_name: str,
        capabilities: list[str] | None = None,
        operator_id: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        rec = {
            "operatorId": operator_id or new_id(),
            "tenantId": tenant_id,
            "displayName": display_name,
            "enabled": bool(enabled),
            "capabilities": list(capabilities or []),
            "auth": "MANUAL_IDENTITY",
            "passwordClaim": False,
            "truthLabel": "REAL_LOGIC / MANUAL_IDENTITY",
            "createdAt": _now(),
        }
        rec["operatorHash"] = stable_hash({k: rec[k] for k in rec if k != "operatorHash"})
        with self._lock:
            self.operators[rec["operatorId"]] = rec
            self.persist()
        emit(
            self,
            "identity.operator_register",
            tenant_id=tenant_id,
            aggregate_type="Operator",
            aggregate_id=rec["operatorId"],
            actor=display_name,
            payload={"enabled": rec["enabled"]},
            semantic_key=f"{tenant_id}::operator::{rec['operatorId']}",
        )
        return rec

    def set_enabled(self, operator_id: str, *, tenant_id: str, enabled: bool) -> dict[str, Any]:
        rec = self.get_operator(operator_id, tenant_id=tenant_id)
        rec["enabled"] = bool(enabled)
        self.persist()
        return rec

    def get_operator(self, operator_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.operators[operator_id]
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: operator")
        return rec

    def open_shift(self, *, tenant_id: str, operator_id: str, station_id: str) -> dict[str, Any]:
        op = self.get_operator(operator_id, tenant_id=tenant_id)
        if not op.get("enabled"):
            raise PermissionError("disabled operator")
        rec = {
            "shiftId": new_id(),
            "tenantId": tenant_id,
            "operatorId": operator_id,
            "stationId": station_id,
            "status": "OPEN",
            "openedAt": _now(),
            "closedAt": None,
            "truthLabel": "MANUAL_IDENTITY",
        }
        rec["shiftHash"] = stable_hash({k: rec[k] for k in rec if k != "shiftHash"})
        with self._lock:
            self.shifts[rec["shiftId"]] = rec
            self.persist()
        emit(
            self,
            "identity.shift_open",
            tenant_id=tenant_id,
            aggregate_type="Shift",
            aggregate_id=rec["shiftId"],
            actor=operator_id,
            payload={"stationId": station_id},
            semantic_key=f"{tenant_id}::shift::{rec['shiftId']}",
        )
        return rec

    def close_shift(self, shift_id: str, *, tenant_id: str, operator_id: str) -> dict[str, Any]:
        rec = self.get_shift(shift_id, tenant_id=tenant_id)
        if rec.get("operatorId") != operator_id:
            raise PermissionError("shift operator mismatch")
        if rec.get("status") == "CLOSED":
            return rec
        rec["status"] = "CLOSED"
        rec["closedAt"] = _now()
        emit(
            self,
            "identity.shift_close",
            tenant_id=tenant_id,
            aggregate_type="Shift",
            aggregate_id=shift_id,
            actor=operator_id,
            payload={"status": "CLOSED"},
            semantic_key=f"{tenant_id}::shift-close::{shift_id}",
        )
        return rec

    def get_shift(self, shift_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.shifts[shift_id]
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: shift")
        return rec

    def require_active(
        self,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        capability: str | None = None,
    ) -> dict[str, Any]:
        op = self.get_operator(operator_id, tenant_id=tenant_id)
        if not op.get("enabled"):
            raise PermissionError("disabled operator")
        shift = self.get_shift(shift_id, tenant_id=tenant_id)
        if shift.get("status") != "OPEN":
            raise PermissionError("closed shift")
        if shift.get("operatorId") != operator_id:
            raise PermissionError("shift operator mismatch")
        if capability and op.get("capabilities") and capability not in op["capabilities"]:
            raise PermissionError("operator missing capability")
        return {"operator": op, "shift": shift, "truthLabel": "MANUAL_IDENTITY"}
