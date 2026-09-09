"""Pilot exception / recovery catalog. Fail-closed, journaled, not a parallel engine."""

from __future__ import annotations

import threading
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.journal import emit

CATALOG: dict[str, dict[str, Any]] = {
    "MATERIAL_SHORTAGE": {
        "errorCode": "MATERIAL_SHORTAGE",
        "retrySafe": True,
        "humanRequired": True,
        "allowedNextStates": ["RELEASED_FOR_MANUAL_EXECUTION"],
        "eventType": "exception.material_shortage",
        "lineageValid": True,
    },
    "WRONG_MATERIAL": {
        "errorCode": "WRONG_MATERIAL",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["RELEASED_FOR_MANUAL_EXECUTION", "QC_HOLD"],
        "eventType": "exception.wrong_material",
        "lineageValid": True,
    },
    "QUARANTINED_RECEIPT": {
        "errorCode": "QUARANTINED_RECEIPT",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["DRAFT", "RELEASED_FOR_MANUAL_EXECUTION"],
        "eventType": "exception.quarantined_receipt",
        "lineageValid": True,
    },
    "STALE_RELEASE": {
        "errorCode": "STALE_RELEASE",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["CANCELLED"],
        "eventType": "exception.stale_release",
        "lineageValid": False,
    },
    "QC_FINAL_FAIL": {
        "errorCode": "QC_FINAL_FAIL",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["QC_HOLD", "IN_PROGRESS"],
        "eventType": "exception.qc_final_fail",
        "lineageValid": True,
    },
    "REWORK_REQUIRED": {
        "errorCode": "REWORK_REQUIRED",
        "retrySafe": True,
        "humanRequired": True,
        "allowedNextStates": ["IN_PROGRESS", "QC_HOLD"],
        "eventType": "exception.rework_required",
        "lineageValid": True,
    },
    "DUPLICATE_SCAN": {
        "errorCode": "DUPLICATE_SCAN",
        "retrySafe": True,
        "humanRequired": False,
        "allowedNextStates": ["IN_PROGRESS", "MATERIAL_RESERVED", "PACKING", "COMPLETED"],
        "eventType": "exception.duplicate_scan",
        "lineageValid": True,
    },
    "STATION_OFFLINE": {
        "errorCode": "STATION_OFFLINE",
        "retrySafe": True,
        "humanRequired": True,
        "allowedNextStates": ["MATERIAL_RESERVED", "IN_PROGRESS"],
        "eventType": "exception.station_offline",
        "lineageValid": True,
    },
    "LEASE_EXPIRED": {
        "errorCode": "LEASE_EXPIRED",
        "retrySafe": True,
        "humanRequired": True,
        "allowedNextStates": ["IN_PROGRESS", "MATERIAL_RESERVED"],
        "eventType": "exception.lease_expired",
        "lineageValid": True,
    },
    "PACKING_MISMATCH": {
        "errorCode": "PACKING_MISMATCH",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["PACKING", "QC_HOLD"],
        "eventType": "exception.packing_mismatch",
        "lineageValid": True,
    },
    "PROCESS_RESTART": {
        "errorCode": "PROCESS_RESTART",
        "retrySafe": True,
        "humanRequired": False,
        "allowedNextStates": ["MATERIAL_RESERVED", "IN_PROGRESS", "RELEASED_FOR_MANUAL_EXECUTION"],
        "eventType": "exception.process_restart",
        "lineageValid": True,
    },
}


class PilotException(PermissionError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        spec = CATALOG.get(code) or {"errorCode": code, "retrySafe": False, "humanRequired": True}
        super().__init__(detail or code)
        self.code = code
        self.spec = spec
        self.silentSuccess = False


def catalog_entry(code: str) -> dict[str, Any]:
    if code not in CATALOG:
        raise KeyError(code)
    return dict(CATALOG[code])


class ExceptionInbox:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.journal: Any | None = None

    def record(
        self,
        *,
        tenant_id: str,
        code: str,
        work_order_id: str | None = None,
        release_hash: str | None = None,
        actor: str = "system",
        detail: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = catalog_entry(code) if code in CATALOG else {"errorCode": code, "retrySafe": False, "humanRequired": True, "eventType": f"exception.{code}", "lineageValid": True, "allowedNextStates": []}
        rec = {
            "exceptionId": new_id(),
            "tenantId": tenant_id,
            "errorCode": spec["errorCode"],
            "retrySafe": bool(spec.get("retrySafe")),
            "humanRequired": bool(spec.get("humanRequired")),
            "allowedNextStates": list(spec.get("allowedNextStates") or []),
            "lineageValid": bool(spec.get("lineageValid")),
            "workOrderId": work_order_id,
            "releaseHash": release_hash,
            "detail": detail or code,
            "payload": payload or {},
            "status": "OPEN",
            "silentSuccess": False,
            "actor": actor,
            "at": utcnow().isoformat(),
        }
        rec["exceptionHash"] = stable_hash({k: rec[k] for k in rec if k != "exceptionHash"})
        with self._lock:
            self.items[rec["exceptionId"]] = rec
        emit(
            self,
            str(spec.get("eventType") or "exception"),
            tenant_id=tenant_id,
            aggregate_type="PilotException",
            aggregate_id=rec["exceptionId"],
            actor=actor,
            payload={"errorCode": rec["errorCode"], "workOrderId": work_order_id, "detail": rec["detail"]},
            release_hash=release_hash,
            semantic_key=f"{tenant_id}::exc::{code}::{work_order_id or rec['exceptionId']}",
        )
        return rec

    def list(self, *, tenant_id: str) -> list[dict[str, Any]]:
        return [i for i in self.items.values() if i.get("tenantId") == tenant_id]

    def get(self, exception_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.items[exception_id]
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: exception")
        return rec
