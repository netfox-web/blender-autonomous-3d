"""Quality control and traceability V1. Engineering rules remain authority.

QC photos reference existing DAM. Not a second media store.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import emit

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


def plan_for_family(family: str) -> list[dict[str, Any]]:
    return [dict(r) for r in FAMILY_TOLERANCES.get(family, [])]


def plan_hash(plan: list[dict[str, Any]] | None) -> str:
    return stable_hash(plan or [])


def _now() -> str:
    return utcnow().isoformat()


def in_tolerance(*, measured: float, nominal: float, tol: float) -> bool:
    return abs(float(measured) - float(nominal)) <= float(tol) + 1e-9


class QcService:
    def __init__(self, *, dam: Any | None = None, workorders: Any | None = None, root: Path | None = None) -> None:
        self.dam = dam
        self.workorders = workorders
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self.checks: dict[str, dict[str, Any]] = {}
        self.defects: dict[str, dict[str, Any]] = {}
        # (tenant, workOrderId, idempotencyKey) -> {"sig": request signature, "qcId": recorded check}
        self.idem: dict[str, dict[str, str]] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "qc.json") or {}
        self.pending = payload.get("pending") or {}
        self.checks = {r["qcId"]: r for r in payload.get("checks") or []}
        self.defects = {r["defectId"]: r for r in payload.get("defects") or []}
        self.idem = {
            str(k): {"sig": str(v.get("sig")), "qcId": str(v.get("qcId"))}
            for k, v in (payload.get("idem") or {}).items()
            if isinstance(v, dict)
        }

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(
            self.root / "qc.json",
            {"checks": list(self.checks.values()), "defects": list(self.defects.values()), "idem": self.idem, "pending": self.pending},
        )

    def schema(self, family: str) -> list[dict[str, Any]]:
        return plan_for_family(family)

    def pin_plan(self, family: str) -> dict[str, Any]:
        plan = self.schema(family)
        return {"qcPlan": plan, "qcPlanHash": plan_hash(plan)}

    @staticmethod
    def _pending_skip_marker(operation_id: str) -> str:
        return f"{operation_id}:skipped"

    @classmethod
    def _pending_already_applied(cls, applied: list[Any], operation_id: str) -> bool:
        marker = cls._pending_skip_marker(operation_id)
        return operation_id in applied or marker in applied

    def _record_pending_skip(self, wo: dict[str, Any], operation_id: str, rec: dict[str, Any], kind: str, reason: str) -> None:
        applied = wo.setdefault("qcAppliedOperations", [])
        marker = self._pending_skip_marker(operation_id)
        if marker not in applied and operation_id not in applied:
            applied.append(marker)
        audit_entry = {"actor": "system", "action": "recover_pending_skip", "reason": reason, "at": _now()}
        if kind == "defect":
            rec.setdefault("audit", []).append({**audit_entry, "disposition": rec.get("disposition")})
        else:
            rec.setdefault("audit", []).append(audit_entry)
        store = self.checks if kind == "check" else self.defects
        store_key = rec["qcId" if kind == "check" else "defectId"]
        store[store_key] = rec

    def is_pending(self, operation_id: str) -> bool:
        """True while the operation's work-order, event or QC commit is unfinished."""
        return str(operation_id) in self.pending

    def recover_pending(self, *, completing: str | None = None) -> None:
        # The work-order marker is committed in the same snapshot as the transition.
        # It prevents a crash before clearing pending from replaying an old action.
        # A failure of ``completing`` is re-raised only after every other pending
        # operation has been attempted, so one stuck work order never blocks others.
        completing_error: BaseException | None = None
        for operation_id in list(self.pending):
            op = self.pending[operation_id]
            rec = op["record"]
            kind = str(op["kind"])
            stalled = False
            if self.workorders is not None:
                wo = self.workorders.get(rec["workOrderId"])
                if wo.get("tenantId") != rec["tenantId"]:
                    logger.warning("recover_pending: tenant mismatch for %s", operation_id)
                    try:
                        emit(self, **op["event"])
                    except Exception as exc:
                        logger.warning("recover_pending: emit failed for %s: %s", operation_id, exc)
                        continue
                    del self.pending[operation_id]
                    try:
                        self.persist()
                    except Exception as exc:
                        self.pending[operation_id] = op
                        logger.warning("recover_pending: qc persist failed for %s: %s", operation_id, exc)
                    continue
                applied = wo.setdefault("qcAppliedOperations", [])
                if not self._pending_already_applied(applied, operation_id):
                    before = copy.deepcopy(wo)
                    try:
                        self._apply_work_order(wo, rec, kind)
                    except PermissionError as exc:
                        wo.clear()
                        wo.update(before)
                        self._record_pending_skip(wo, operation_id, rec, kind, str(exc))
                    else:
                        applied.append(operation_id)
                    try:
                        self.workorders.persist()
                    except Exception as exc:
                        wo.clear()
                        wo.update(before)
                        if operation_id == completing:
                            completing_error = exc
                            continue
                        logger.warning("recover_pending: workorder persist failed for %s: %s", operation_id, exc)
                        stalled = True
            if stalled:
                continue
            try:
                emit(self, **op["event"])
            except Exception as exc:
                if operation_id == completing:
                    completing_error = exc
                    continue
                logger.warning("recover_pending: emit failed for %s: %s", operation_id, exc)
                continue
            del self.pending[operation_id]
            try:
                self.persist()
            except Exception as exc:
                self.pending[operation_id] = op
                if operation_id == completing:
                    completing_error = exc
                    continue
                logger.warning("recover_pending: qc persist failed for %s: %s", operation_id, exc)
        if completing_error is not None:
            raise completing_error

    def _apply_work_order(self, wo: dict[str, Any], rec: dict[str, Any], kind: str) -> None:
        assert self.workorders is not None
        if kind == "check":
            lineage = wo.setdefault("lineage", {}).setdefault("qc", [])
            if rec["qcId"] not in lineage:
                lineage.append(rec["qcId"])
            if not rec["ok"] and wo.get("state") not in {"COMPLETED", "CANCELLED", "REJECTED", "QC_HOLD"}:
                self.workorders._transition(wo, "QC_HOLD", actor=rec["operator"], reason=f"qc-fail:{rec['checkId']}")
        else:
            disposition = rec["disposition"]
            if disposition == "REWORK" and wo.get("state") == "QC_HOLD":
                if any(h.get("open") and h.get("blocking") for h in wo.get("holds") or []):
                    raise PermissionError("blocking hold")
                self.workorders._transition(wo, "IN_PROGRESS", actor=rec["actor"], reason="defect-rework")
                wo["rework"] = True
            if disposition in {"SCRAP", "REJECT"}:
                self.workorders._transition(wo, "REJECTED", actor=rec["actor"], reason="defect-reject")

    def _commit_operation(self, rec: dict[str, Any], kind: str, event: dict[str, Any], idem_entry: tuple[str, str] | None) -> None:
        operation_id = rec["qcId" if kind == "check" else "defectId"]
        if self.workorders is not None:
            wo = self.workorders.get(rec["workOrderId"])
            if wo.get("tenantId") != rec["tenantId"]:
                raise PermissionError("tenant isolation: qc")
            # Validate all transitions before writing either the record or key.
            self._apply_work_order(copy.deepcopy(wo), rec, kind)
        (self.checks if kind == "check" else self.defects)[operation_id] = rec
        if idem_entry is not None:
            self.idem[idem_entry[0]] = {"sig": idem_entry[1], "qcId": operation_id}
        self.pending[operation_id] = {"kind": kind, "record": rec, "event": event}
        try:
            self.persist()
        except Exception:
            (self.checks if kind == "check" else self.defects).pop(operation_id, None)
            if idem_entry is not None:
                self.idem.pop(idem_entry[0], None)
            self.pending.pop(operation_id, None)
            raise
        self.recover_pending(completing=operation_id)

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
        idem_entry: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        if source not in {"TEST_DATA", "IMPORTED", "MANUAL", "DEVICE"}:
            source = "TEST_DATA"
        ok = in_tolerance(measured=measured, nominal=nominal, tol=tol)
        rec: dict[str, Any] = {
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
        hold_wo = False
        if self.workorders is not None:
            wo = self.workorders.get(work_order_id)
            if wo.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: qc")
            hold_wo = not ok and wo.get("state") not in {"COMPLETED", "CANCELLED", "REJECTED"}
            if hold_wo and wo.get("state") in {"DRAFT", "RELEASED_FOR_MANUAL_EXECUTION"}:
                raise PermissionError(f"work order in {wo.get('state')} cannot be put on QC_HOLD")
        release_hash = wo.get("releaseHash") if self.workorders is not None else None
        event = dict(
            event_type="qc.final" if stage == "FINAL" else "qc.record",
            tenant_id=tenant_id, aggregate_type="QC", aggregate_id=rec["qcId"], actor=operator,
            payload={"result": rec["result"], "stage": stage, "workOrderId": work_order_id, "checkId": check_id},
            release_hash=release_hash,
            semantic_key=f"{tenant_id}::qc::{work_order_id}::{stage}::{check_id}::{rec['qcId']}",
        )
        self._commit_operation(rec, "check", event, idem_entry)
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
        idem_entry: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        if code not in DEFECT_CODES:
            raise ValueError(code)
        if disposition not in DISPOSITIONS:
            raise ValueError(disposition)
        rec: dict[str, Any] = {
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
        event = dict(
            event_type="qc.defect", tenant_id=tenant_id, aggregate_type="QC",
            aggregate_id=rec["defectId"], actor=actor,
            payload={"workOrderId": work_order_id, "code": code, "disposition": disposition},
            semantic_key=f"{tenant_id}::defect::{rec['defectId']}",
        )
        self._commit_operation(rec, "defect", event, idem_entry)
        return rec

    def required_final_ok(
        self,
        work_order_id: str,
        family: str,
        *,
        tenant_id: str | None = None,
        plan: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if plan is None and self.workorders is not None:
            try:
                plan = self.workorders.get(work_order_id).get("qcPlan")
            except KeyError:
                plan = None
        schema = plan or self.schema(family)
        required = [c["checkId"] for c in schema if c.get("requiredFinal")]
        wo_tenant = tenant_id
        if wo_tenant is None and self.workorders is not None:
            try:
                wo_tenant = self.workorders.get(work_order_id).get("tenantId")
            except KeyError:
                wo_tenant = None
        rows = [
            c
            for c in list(self.checks.values())
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
        failed = [cid for cid, row in latest.items() if cid in required and not row["ok"]]
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
