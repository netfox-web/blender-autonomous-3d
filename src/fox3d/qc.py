"""Quality control and traceability V1. Engineering rules remain authority.

QC photos reference existing DAM. Not a second media store.
"""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow

DISPOSITIONS = ("REWORK", "SCRAP", "USE_AS_IS_WITH_APPROVAL", "REJECT")
DEFECT_CODES = {
    "DEF_THICKNESS": {"severity": "MAJOR", "family": "*"},
    "DEF_SIZE": {"severity": "MAJOR", "family": "*"},
    "DEF_FINISH": {"severity": "MINOR", "family": "*"},
    "DEF_VISIBLE": {"severity": "MINOR", "family": "*"},
    "DEF_HOLE": {"severity": "MAJOR", "family": "KD_FURNITURE"},
    "DEF_EDGE": {"severity": "MINOR", "family": "KD_FURNITURE"},
    "DEF_BEND": {"severity": "MAJOR", "family": "ACRYLIC_SHEET"},
    "DEF_PACK": {"severity": "MINOR", "family": "PACKAGING_STRUCTURE"},
    "DEF_SCRATCH": {"severity": "MINOR", "family": "*"},
    "DEF_SLOT": {"severity": "MAJOR", "family": "RETAIL_FIXTURE"},
}

FAMILY_TOLERANCES: dict[str, list[dict[str, Any]]] = {
    "KD_FURNITURE": [
        {"checkId": "THICKNESS", "nominal": 18.0, "tol": 0.5, "unit": "mm", "requiredFinal": True},
        {"checkId": "PANEL_LENGTH", "nominal": None, "tol": 1.0, "unit": "mm", "requiredFinal": True},
        {"checkId": "HOLE_DIA", "nominal": 8.0, "tol": 0.2, "unit": "mm", "requiredFinal": False},
    ],
    "RETAIL_FIXTURE": [
        {"checkId": "THICKNESS", "nominal": 18.0, "tol": 0.5, "unit": "mm", "requiredFinal": True},
        {"checkId": "SLOT_WIDTH", "nominal": None, "tol": 1.0, "unit": "mm", "requiredFinal": True},
        {"checkId": "LOAD_LABEL", "nominal": 1.0, "tol": 0.0, "unit": "present", "requiredFinal": True},
    ],
    "PACKAGING_STRUCTURE": [
        {"checkId": "INNER_L", "nominal": None, "tol": 2.0, "unit": "mm", "requiredFinal": True},
        {"checkId": "CALIPER", "nominal": 3.0, "tol": 0.2, "unit": "mm", "requiredFinal": True},
    ],
    "ACRYLIC_SHEET": [
        {"checkId": "THICKNESS", "nominal": 5.0, "tol": 0.2, "unit": "mm", "requiredFinal": True},
        {"checkId": "CUT", "nominal": None, "tol": 0.5, "unit": "mm", "requiredFinal": True},
        {"checkId": "BEND_ANGLE", "nominal": 80.0, "tol": 2.0, "unit": "deg", "requiredFinal": False},
    ],
}


def _now() -> str:
    return utcnow().isoformat()


def in_tolerance(*, measured: float, nominal: float, tol: float) -> bool:
    return abs(float(measured) - float(nominal)) <= float(tol) + 1e-9


class QcService:
    def __init__(self, *, dam: Any | None = None, workorders: Any | None = None) -> None:
        self.dam = dam
        self.workorders = workorders
        self.checks: dict[str, dict[str, Any]] = {}
        self.defects: dict[str, dict[str, Any]] = {}

    def schema(self, family: str) -> list[dict[str, Any]]:
        return [dict(r) for r in FAMILY_TOLERANCES.get(family, [])]

    def record(
        self,
        *,
        tenant_id: str,
        work_order_id: str,
        stage: str,
        check_id: str,
        measured: float,
        nominal: float,
        tol: float,
        unit: str,
        operator: str,
        required_final: bool = False,
        dam_asset_id: str | None = None,
        source: str = "TEST_DATA",
        lot_id: str | None = None,
        operation: str | None = None,
    ) -> dict[str, Any]:
        if source not in {"TEST_DATA", "IMPORTED", "MANUAL", "DEVICE"}:
            source = "TEST_DATA"
        ok = in_tolerance(measured=measured, nominal=nominal, tol=tol)
        rec = {
            "qcId": new_id(),
            "tenantId": tenant_id,
            "workOrderId": work_order_id,
            "stage": stage,
            "checkId": check_id,
            "measured": float(measured),
            "nominal": float(nominal),
            "tol": float(tol),
            "unit": unit,
            "ok": ok,
            "result": "PASS" if ok else "FAIL",
            "operator": operator,
            "requiredFinal": bool(required_final),
            "damAssetId": dam_asset_id,
            "source": source,
            "truthLabel": "IMPORTED" if source in {"IMPORTED", "MANUAL", "DEVICE"} else "TEST_DATA",
            "lotId": lot_id,
            "operation": operation,
            "at": _now(),
        }
        rec["qcHash"] = stable_hash({k: rec[k] for k in rec if k not in {"qcId", "qcHash"}})
        if dam_asset_id and self.dam is not None:
            self.dam.get(dam_asset_id, tenant_id=tenant_id)
        if self.workorders is not None:
            wo = self.workorders.get(work_order_id)
            if wo.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: qc")
        self.checks[rec["qcId"]] = rec
        if self.workorders is not None:
            wo = self.workorders.get(work_order_id)
            wo["lineage"]["qc"] = list(wo["lineage"].get("qc") or []) + [rec["qcId"]]
            if not ok and wo.get("state") not in {"COMPLETED", "CANCELLED", "REJECTED"}:
                wo["state"] = "QC_HOLD"
        return rec

    def incoming_material(self, **kwargs: Any) -> dict[str, Any]:
        return self.record(stage="INCOMING", **kwargs)

    def in_process(self, **kwargs: Any) -> dict[str, Any]:
        return self.record(stage="IN_PROCESS", **kwargs)

    def final(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("required_final", True)
        return self.record(stage="FINAL", **kwargs)

    def defect(
        self,
        *,
        tenant_id: str,
        work_order_id: str,
        code: str,
        disposition: str,
        actor: str,
        note: str = "",
        dam_asset_id: str | None = None,
    ) -> dict[str, Any]:
        if code not in DEFECT_CODES:
            raise ValueError(code)
        if disposition not in DISPOSITIONS:
            raise ValueError(disposition)
        rec = {
            "defectId": new_id(),
            "tenantId": tenant_id,
            "workOrderId": work_order_id,
            "code": code,
            "severity": DEFECT_CODES[code]["severity"],
            "disposition": disposition,
            "actor": actor,
            "note": note,
            "damAssetId": dam_asset_id,
            "at": _now(),
            "audit": [{"actor": actor, "disposition": disposition, "at": _now()}],
        }
        rec["defectHash"] = stable_hash({k: rec[k] for k in rec if k != "defectHash"})
        if dam_asset_id and self.dam is not None:
            self.dam.get(dam_asset_id, tenant_id=tenant_id)
        self.defects[rec["defectId"]] = rec
        if self.workorders is not None:
            wo = self.workorders.get(work_order_id)
            if disposition == "REWORK" and wo.get("state") == "QC_HOLD":
                wo["state"] = "IN_PROGRESS"
                wo["rework"] = True
            if disposition in {"SCRAP", "REJECT"}:
                wo["state"] = "REJECTED"
        return rec

    def required_final_ok(self, work_order_id: str, family: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        required = [c["checkId"] for c in self.schema(family) if c.get("requiredFinal")]
        wo_tenant = tenant_id
        if wo_tenant is None and self.workorders is not None:
            try:
                wo_tenant = self.workorders.get(work_order_id).get("tenantId")
            except KeyError:
                wo_tenant = None
        rows = [
            c
            for c in self.checks.values()
            if c["workOrderId"] == work_order_id
            and c["stage"] == "FINAL"
            and (wo_tenant is None or c.get("tenantId") == wo_tenant)
        ]
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            prev = latest.get(row["checkId"])
            if prev is None or str(row.get("at") or "") >= str(prev.get("at") or ""):
                latest[row["checkId"]] = row
        present = set(latest)
        missing = [cid for cid in required if cid not in present]
        failed = [cid for cid, row in latest.items() if not row["ok"]]
        return {"ok": not missing and not failed, "missing": missing, "failed": failed, "required": required}

    def completion_allowed(self, work_order_id: str, family: str, *, tenant_id: str | None = None) -> bool:
        return self.required_final_ok(work_order_id, family, tenant_id=tenant_id)["ok"]

    def trace(self, *, work_order_id: str | None = None, release_hash: str | None = None, product_id: str | None = None) -> dict[str, Any]:
        wo = None
        if work_order_id:
            wo = self.workorders.get(work_order_id) if self.workorders is not None else None
        elif self.workorders is not None:
            for rec in self.workorders.orders.values():
                if release_hash and rec.get("releaseHash") == release_hash:
                    wo = rec
                    break
                if product_id and rec.get("productId") == product_id:
                    wo = rec
                    break
        if wo is None:
            raise KeyError("work order not found")
        qc_rows = [self.checks[i] for i in wo.get("lineage", {}).get("qc") or [] if i in self.checks]
        return {
            "productVersion": wo.get("productVersion"),
            "productId": wo.get("productId"),
            "releaseHash": wo.get("releaseHash"),
            "bomHash": (wo.get("lineage") or {}).get("bomHash"),
            "materialLots": (wo.get("lineage") or {}).get("materialLots") or [],
            "remnants": (wo.get("lineage") or {}).get("remnants") or [],
            "workOrderId": wo.get("workOrderId"),
            "workOrderState": wo.get("state"),
            "operations": list(wo.get("ops") or []),
            "qc": qc_rows,
            "package": (wo.get("lineage") or {}).get("package"),
            "cartonIds": wo.get("cartonIds") or [],
            "tenantId": wo.get("tenantId"),
        }
