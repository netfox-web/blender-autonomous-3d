"""Tenant-scoped pilot quality control API."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from fox3d.ids import stable_hash
from fox3d.operator import require_confirm
from fox3d.pilot_packing_api import (
    _require_body_dict, _require_finite_number, _require_idempotency_key,
    _require_tenant, _require_wo,
)
from fox3d.qc import DEFECT_CODES, DISPOSITIONS

_ALLOWED_QC_STAGES = frozenset({"INCOMING", "IN_PROCESS", "FINAL"})
_ALLOWED_QC_SOURCES = frozenset({"MANUAL", "IMPORTED"})
_QC_OPEN_STATES_REJECTED = frozenset({"DRAFT", "RELEASED_FOR_MANUAL_EXECUTION"})


def pilot_qc_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()
    @router.get("/api/pilot/work-orders/{work_order_id}/qc")
    def get_work_order_qc(
        work_order_id: str,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        pilot = provider().pilot
        wo = _require_wo(pilot, work_order_id, tid)
        family = str(wo.get("productFamily") or "KD_FURNITURE")
        plan = list(wo.get("qcPlan") or pilot.qc.schema(family))
        checks = [
            c
            for c in pilot.qc.checks.values()
            if c.get("workOrderId") == work_order_id and c.get("tenantId") == tid
        ]
        defects = [
            d
            for d in pilot.qc.defects.values()
            if d.get("workOrderId") == work_order_id and d.get("tenantId") == tid
        ]
        req_ok = pilot.qc.required_final_ok(work_order_id, family, tenant_id=tid, plan=plan)
        return {
            "workOrderId": work_order_id,
            "tenantId": tid,
            "productFamily": family,
            "plan": plan,
            "qcPlan": plan,
            "checks": checks,
            "requiredFinalOk": req_ok,
            "required_final_ok": req_ok,
            "defects": defects,
        }

    @router.post("/api/pilot/work-orders/{work_order_id}/qc")
    def record_work_order_qc(
        work_order_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        pilot = provider().pilot
        wo = _require_wo(pilot, work_order_id, tid)

        stage = body.get("stage", "FINAL")
        if not isinstance(stage, str) or stage not in _ALLOWED_QC_STAGES:
            raise HTTPException(422, "stage 須為 INCOMING、IN_PROCESS 或 FINAL")

        family = str(wo.get("productFamily") or "KD_FURNITURE")
        plan = list(wo.get("qcPlan") or pilot.qc.schema(family))
        plan_by_id = {str(item.get("checkId")): item for item in plan if item.get("checkId")}
        check_id = body.get("checkId")
        if not isinstance(check_id, str) or check_id not in plan_by_id:
            raise HTTPException(422, "checkId 不在工單 QC 計畫內")

        spec = plan_by_id[check_id]
        measured = _require_finite_number(body.get("measured"), "measured")
        raw_nom = spec.get("nominal") if spec.get("nominal") is not None else body.get("nominal")
        nominal = _require_finite_number(raw_nom, "nominal")
        raw_tol = spec.get("tol") if spec.get("tol") is not None else body.get("tol")
        tol = _require_finite_number(raw_tol, "tol")
        if tol < 0:
            raise HTTPException(422, "tol 須為非負數")
        unit = str(spec.get("unit") or body.get("unit") or "mm")

        raw_source = body.get("source", "MANUAL")
        if not isinstance(raw_source, str) or raw_source not in _ALLOWED_QC_SOURCES:
            raise HTTPException(422, "source 須為 MANUAL 或 IMPORTED")

        idem_key = _require_idempotency_key(body)
        operator = str(body.get("operator") or body.get("actor") or "qc")
        sig = stable_hash(body)
        store_key = f"{tid}::qc-idem::{work_order_id}::{idem_key}"

        with pilot.workorders._lock:
            wo = _require_wo(pilot, work_order_id, tid)
            prev = pilot.qc.idem.get(store_key)
            if prev is not None:
                if prev.get("sig") != sig:
                    raise HTTPException(409, "idempotencyKey 衝突")
                prev_rec = pilot.qc.checks.get(str(prev.get("qcId")))
                if prev_rec is not None:
                    return dict(prev_rec)
            if wo.get("state") in _QC_OPEN_STATES_REJECTED:
                raise HTTPException(409, "工單尚未預留材料，無法記錄品檢")
            if wo.get("state") in {"COMPLETED", "REJECTED", "CANCELLED"}:
                raise HTTPException(409, "工單已結束，無法記錄品檢")
            try:
                rec = pilot.qc.record(
                    tenant_id=tid,
                    work_order_id=work_order_id,
                    stage=stage,
                    check_id=check_id,
                    measured=measured,
                    nominal=nominal,
                    tol=tol,
                    unit=unit,
                    operator=operator,
                    required_final=bool(spec.get("requiredFinal")),
                    source=raw_source,
                )
            except PermissionError as exc:
                raise HTTPException(409, str(exc)) from exc
            pilot.qc.idem[store_key] = {"sig": sig, "qcId": str(rec["qcId"])}
            pilot.qc.persist()
            pilot.workorders.persist()
            return dict(rec)

    @router.post("/api/pilot/work-orders/{work_order_id}/qc/release-hold")
    def release_work_order_qc_hold(
        work_order_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        pilot = provider().pilot
        _require_wo(pilot, work_order_id, tid)
        try:
            require_confirm(body, action="release_hold")
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

        with pilot.workorders._lock:
            wo = _require_wo(pilot, work_order_id, tid)
            if wo.get("state") in _QC_OPEN_STATES_REJECTED:
                raise HTTPException(409, "工單尚未預留材料，無 QC_HOLD 可解除")
            family = str(wo.get("productFamily") or "KD_FURNITURE")
            req_ok = pilot.qc.required_final_ok(
                work_order_id, family, tenant_id=tid, plan=wo.get("qcPlan")
            )
            if not req_ok.get("ok"):
                raise HTTPException(409, "required final QC 尚未全部通過，無法解除 QC_HOLD")
            actor = str(body.get("actor") or "qc")[:120]
            if wo.get("state") not in {"QC_HOLD", "IN_PROGRESS"}:
                raise HTTPException(409, "工單狀態無法解除 QC_HOLD")
            if wo.get("state") == "QC_HOLD":
                other_holds = [h for h in wo.get("holds") or [] if h.get("open") and h.get("blocking")]
                if other_holds:
                    reasons = sorted({str(h.get("reason") or "") for h in other_holds})
                    raise HTTPException(409, f"仍有未結的 blocking hold（{', '.join(reasons)}），QC 無法解除")
                pilot.workorders._transition(wo, "IN_PROGRESS", actor=actor, reason="qc-release-hold")
                pilot.workorders.persist()
            return wo

    @router.post("/api/pilot/work-orders/{work_order_id}/defects")
    def record_defect(work_order_id: str, payload: Any = Body(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        pilot = provider().pilot
        _require_wo(pilot, work_order_id, tid)
        try:
            require_confirm(body, action="defect")
        except PermissionError as exc:
            raise HTTPException(403, "需要確認") from exc
        code, disposition = body.get("code"), body.get("disposition")
        if not isinstance(code, str) or code not in DEFECT_CODES or not isinstance(disposition, str) or disposition not in DISPOSITIONS:
            raise HTTPException(422, "無效的瑕疵代碼或處置")
        key = _require_idempotency_key(body)
        signature = stable_hash(body)
        store_key = f"{tid}::defect::{work_order_id}::{key}"
        with pilot.workorders._lock:
            _require_wo(pilot, work_order_id, tid)
            previous = pilot.qc.idem.get(store_key)
            if previous:
                if previous["sig"] != signature:
                    raise HTTPException(409, "idempotencyKey 衝突")
                return dict(pilot.qc.defects[previous["qcId"]])
            try:
                rec = pilot.qc.defect(tenant_id=tid, work_order_id=work_order_id, code=code, disposition=disposition, actor=str(body.get("actor") or "qc"), note=str(body.get("note") or ""))
            except PermissionError as exc:
                raise HTTPException(409, "工單狀態不允許此處置") from exc
            pilot.qc.idem[store_key] = {"sig": signature, "qcId": str(rec["defectId"])}
            pilot.qc.persist()
            return dict(rec)

    return router
