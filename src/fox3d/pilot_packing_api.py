"""Pilot work order packing & carton measurement HTTP API.

Exposes carton instantiation + work order binding, tenant-scoped carton listing,
measured dimension/weight recording, and packing checklist generation.
"""

from __future__ import annotations

import importlib.util
import math
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from fox3d.infra import validate_tenant_id
from fox3d.journal import SemanticKeyConflictError
from fox3d.logistics import _measured_snapshot_equal
from fox3d.operator import require_confirm

_ALLOWED_MEASURE_SOURCES = frozenset({"MANUAL", "IMPORTED", "MEASURED"})
_ALLOWED_QC_STAGES = frozenset({"INCOMING", "IN_PROCESS", "FINAL"})
_ALLOWED_QC_SOURCES = frozenset({"MANUAL", "IMPORTED"})
_MAX_KEY_LEN = 200


def _tenant(x_tenant_id: str | None) -> str:
    try:
        return validate_tenant_id(x_tenant_id or "")
    except ValueError as exc:
        raise HTTPException(400, "X-Tenant-Id 無效") from exc


def _require_tenant(x_tenant_id: str | None, payload: dict[str, Any] | None = None) -> str:
    header = _tenant(x_tenant_id)
    body_tid = (payload or {}).get("tenantId")
    if body_tid is None or body_tid == "":
        return header
    if not isinstance(body_tid, str):
        raise HTTPException(422, "body tenantId must be a string")
    if body_tid != header:
        raise HTTPException(403, "body tenantId does not match X-Tenant-Id")
    return header


def _require_body_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "請求內容須為 JSON 物件")
    return payload


def _require_wo(pilot: Any, work_order_id: str, tid: str) -> dict[str, Any]:
    wo = pilot.workorders.orders.get(work_order_id)
    if wo is None or wo.get("tenantId") != tid:
        raise HTTPException(404, "找不到工單")
    return wo


def _require_carton(pilot: Any, carton_id: str, tid: str) -> dict[str, Any]:
    carton = pilot.logistics.cartons.get(carton_id)
    if carton is None or carton.get("tenantId") != tid:
        raise HTTPException(404, "找不到紙箱")
    return carton


def _require_carton_quantity(payload: dict[str, Any]) -> int:
    raw = payload.get("quantity")
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise HTTPException(422, "quantity 須為 1 至 50 的整數")
    if not 1 <= raw <= 50:
        raise HTTPException(422, "quantity 須為 1 至 50 的整數")
    return raw


def _require_idempotency_key(payload: dict[str, Any]) -> str:
    raw = payload.get("idempotencyKey")
    if not isinstance(raw, str):
        raise HTTPException(422, "idempotencyKey 必填且須為字串")
    key = raw.strip()
    if not key or len(raw) > _MAX_KEY_LEN:
        raise HTTPException(422, "idempotencyKey 須為 1 至 200 字的非空字串")
    return key


def _optional_idempotency_key(payload: dict[str, Any], field: str = "idempotencyKey") -> str | None:
    if field not in payload or payload[field] is None or payload[field] == "":
        return None
    raw = payload[field]
    if not isinstance(raw, str):
        raise HTTPException(422, f"{field} 格式錯誤")
    key = raw.strip()
    if not key or len(raw) > _MAX_KEY_LEN:
        raise HTTPException(422, f"{field} 格式錯誤")
    return key


def _require_positive_finite(raw: Any, field: str) -> float:
    if raw is None or isinstance(raw, (bool, str, list, dict)) or not isinstance(raw, (int, float)):
        raise HTTPException(422, f"{field} 必須是有限正數")
    try:
        val = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(422, f"{field} 必須是有限正數") from None
    if not math.isfinite(val) or val <= 0:
        raise HTTPException(422, f"{field} 必須是有限正數")
    return val


def _require_finite_number(raw: Any, field: str) -> float:
    if raw is None or isinstance(raw, (bool, str, list, dict)) or not isinstance(raw, (int, float)):
        raise HTTPException(422, f"{field} 必須是有限數值")
    try:
        val = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(422, f"{field} 必須是有限數值") from None
    if not math.isfinite(val):
        raise HTTPException(422, f"{field} 必須是有限數值")
    return val


def _serialize_carton(carton: dict[str, Any]) -> dict[str, Any]:
    out = dict(carton)
    out["expected"] = carton.get("expected")
    out["measured"] = carton.get("measured")
    out["mismatch"] = bool(carton.get("mismatch"))
    return out


def _latest_matching_measure_op_id(carton: dict[str, Any], target_measured: dict[str, Any]) -> str | None:
    current = carton.get("measured")
    if not isinstance(current, dict) or not _measured_snapshot_equal(current, target_measured):
        return None
    ops = carton.get("measureOps")
    if not isinstance(ops, dict) or not ops:
        return None
    latest_seq = int(carton.get("measureSeq") or 0)
    for op_id, op_rec in ops.items():
        if isinstance(op_rec, dict) and int(op_rec.get("seq") or 0) == latest_seq:
            prior = op_rec.get("measured")
            if isinstance(prior, dict) and _measured_snapshot_equal(prior, target_measured):
                return str(op_id)
    return None


def _sync_wo_mismatch_hold(pilot: Any, work_order_id: str, tid: str) -> bool:
    wo = pilot.workorders.orders.get(work_order_id)
    if wo is None or wo.get("tenantId") != tid:
        return False
    wo_cartons = [
        c
        for c in pilot.logistics.cartons.values()
        if c.get("workOrderId") == work_order_id and c.get("tenantId") == tid
    ]
    hold = any(bool(c.get("mismatch")) for c in wo_cartons)
    if wo.get("mismatchHold") != hold:
        wo["mismatchHold"] = hold
        pilot.workorders.persist()
    return hold


def pilot_packing_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()
    qc_idem_store: dict[str, tuple[str, dict[str, Any]]] = {}

    @router.post("/api/pilot/work-orders/{work_order_id}/cartons")
    def create_work_order_cartons(
        work_order_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        pilot = provider().pilot
        _require_wo(pilot, work_order_id, tid)
        qty = _require_carton_quantity(body)
        idem_key = _require_idempotency_key(body)

        with pilot.workorders._lock, pilot.logistics._lock:
            wo = _require_wo(pilot, work_order_id, tid)
            idem_store_key = f"{tid}::carton::{idem_key}"
            is_retry = idem_store_key in pilot.logistics._idem
            if not is_retry:
                if wo.get("state") in {"DRAFT", "RELEASED_FOR_MANUAL_EXECUTION"}:
                    raise HTTPException(409, "工單尚未預留材料，無法建立紙箱")
                if wo.get("state") in {"COMPLETED", "REJECTED", "CANCELLED"}:
                    raise HTTPException(409, "工單已結束，無法建立紙箱")
            rel = pilot.releases.releases.get(str(wo.get("releaseId") or "")) or {}
            snap = rel.get("snapshot") if isinstance(rel.get("snapshot"), dict) else {}
            packing = (snap or {}).get("packing")
            if not isinstance(packing, dict) or not packing:
                packing = {"length": 400, "width": 300, "height": 200}
            weight_info = (snap or {}).get("weight")
            if not isinstance(weight_info, dict):
                weight_info = {}
            expected_weight = float(packing.get("weightKg") or weight_info.get("grossKg") or 8.0)
            lot_ids = list((wo.get("lineage") or {}).get("materialLots") or [])
            try:
                cartons = pilot.logistics.instantiate_cartons(
                    tenant_id=tid,
                    work_order_id=work_order_id,
                    batch_id=str(wo.get("batchId") or ""),
                    plan=packing,
                    quantity=qty,
                    contents=[{"sku": str(wo.get("productId") or "product"), "qty": 1}],
                    expected_weight_kg=expected_weight,
                    idempotency_key=idem_key,
                    release_hash=str(wo.get("releaseHash") or ""),
                    product_version=wo.get("productVersion"),
                    lot_ids=lot_ids,
                )
            except SemanticKeyConflictError as exc:
                raise HTTPException(409, "idempotencyKey 衝突：相同冪等鍵不可使用不同數量或工單") from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            except PermissionError as exc:
                raise HTTPException(409, str(exc)) from exc

            carton_ids = [c["cartonId"] for c in cartons]
            try:
                wo = pilot.workorders.set_packing(work_order_id, carton_ids)
            except PermissionError as exc:
                raise HTTPException(409, str(exc)) from exc
            _sync_wo_mismatch_hold(pilot, work_order_id, tid)
            items = [_serialize_carton(c) for c in cartons]
            return {
                "workOrderId": work_order_id,
                "tenantId": tid,
                "batchId": wo.get("batchId"),
                "releaseHash": wo.get("releaseHash"),
                "quantity": len(items),
                "cartonCount": len(items),
                "cartonIds": carton_ids,
                "items": items,
                "cartons": items,
                "state": wo.get("state"),
            }

    @router.get("/api/pilot/work-orders/{work_order_id}/cartons")
    def list_work_order_cartons(
        work_order_id: str,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        pilot = provider().pilot
        with pilot.logistics._lock:
            wo = _require_wo(pilot, work_order_id, tid)
            raw_cartons = [
                c
                for c in pilot.logistics.cartons.values()
                if c.get("workOrderId") == work_order_id and c.get("tenantId") == tid
            ]
            raw_cartons.sort(key=lambda c: (int(c.get("index") or 0), str(c.get("cartonId") or "")))
            items = [_serialize_carton(c) for c in raw_cartons]
            return {
                "workOrderId": work_order_id,
                "tenantId": tid,
                "releaseHash": wo.get("releaseHash"),
                "cartonCount": len(items),
                "items": items,
                "cartons": items,
            }

    @router.post("/api/pilot/cartons/{carton_id}/measured")
    def record_carton_measured(
        carton_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        pilot = provider().pilot
        _require_carton(pilot, carton_id, tid)

        m_len = _require_positive_finite(body.get("length"), "length")
        m_wid = _require_positive_finite(body.get("width"), "width")
        m_hgt = _require_positive_finite(body.get("height"), "height")

        weight_val: float | None = None
        for wkey in ("weightKg", "weight_kg", "weight"):
            if wkey in body:
                v = _require_positive_finite(body.get(wkey), wkey)
                if weight_val is None:
                    weight_val = v
        if weight_val is None:
            raise HTTPException(422, "weightKg 必須是有限正數")

        raw_source = body.get("source")
        if raw_source in (None, ""):
            src = "MANUAL"
        elif not isinstance(raw_source, str) or raw_source not in _ALLOWED_MEASURE_SOURCES:
            raise HTTPException(422, "source 須為 MANUAL、IMPORTED 或 MEASURED")
        else:
            src = raw_source

        explicit_op_id = _optional_idempotency_key(body, "idempotencyKey") or _optional_idempotency_key(
            body, "measureOpId"
        )

        with pilot.workorders._lock, pilot.logistics._lock:
            carton = _require_carton(pilot, carton_id, tid)
            target_measured = {
                "length": m_len,
                "width": m_wid,
                "height": m_hgt,
                "weightKg": weight_val,
                "source": src,
                "truthLabel": "MEASURED",
            }
            op_id = explicit_op_id or _latest_matching_measure_op_id(carton, target_measured)
            try:
                updated = pilot.logistics.record_measured(
                    carton_id,
                    tenant_id=tid,
                    length=m_len,
                    width=m_wid,
                    height=m_hgt,
                    weight_kg=weight_val,
                    source=src,
                    measure_op_id=op_id,
                )
            except (ValueError, SemanticKeyConflictError) as exc:
                raise HTTPException(409, "idempotencyKey 衝突：相同冪等鍵不可回填不同實測值") from exc
            except PermissionError as exc:
                raise HTTPException(404, "找不到紙箱") from exc

            wo_id = str(updated.get("workOrderId") or "")
            mismatch_hold = _sync_wo_mismatch_hold(pilot, wo_id, tid)
            out = _serialize_carton(updated)
            out["mismatchHold"] = mismatch_hold
            out["statusMessage"] = "尺寸不符待人工確認" if out["mismatch"] else "實測尺寸符合預期"
            return out

    @router.post("/api/pilot/work-orders/{work_order_id}/packing-checklist")
    def create_packing_checklist(
        work_order_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        _ = _optional_idempotency_key(body, "idempotencyKey")
        pilot = provider().pilot
        _require_wo(pilot, work_order_id, tid)

        with pilot.workorders._lock, pilot.logistics._lock:
            wo = _require_wo(pilot, work_order_id, tid)
            rel_hash = str(wo.get("releaseHash") or "")
            cartons = [
                c
                for c in pilot.logistics.cartons.values()
                if c.get("workOrderId") == work_order_id and c.get("tenantId") == tid
            ]
            expected_items = [
                {
                    "cartonId": c["cartonId"],
                    "expected": c.get("expected"),
                    "measured": c.get("measured"),
                    "mismatch": bool(c.get("mismatch")),
                }
                for c in cartons
            ]
            expected_hold = any(bool(c.get("mismatch")) for c in cartons)
            expected_pinned = bool(cartons) and all(c.get("releaseHash") == rel_hash for c in cartons)
            existing = None
            for chk in reversed(list(pilot.logistics.checklists.values())):
                if chk.get("tenantId") == tid and chk.get("workOrderId") == work_order_id:
                    if (
                        chk.get("releaseHash") == rel_hash
                        and chk.get("items") == expected_items
                        and bool(chk.get("mismatchHold")) == expected_hold
                        and bool(chk.get("pinned")) == expected_pinned
                    ):
                        existing = chk
                    break
            if existing is not None:
                rec = dict(existing)
            else:
                rec = dict(
                    pilot.logistics.packing_checklist(
                        tenant_id=tid,
                        work_order_id=work_order_id,
                        release_hash=rel_hash,
                    )
                )
            wo["mismatchHold"] = bool(rec.get("mismatchHold"))
            pilot.workorders.persist()
            rec["carrierProvider"] = "BLOCKED/NOT_CONNECTED"
            rec["statusMessage"] = "尺寸不符待人工確認" if rec.get("mismatchHold") else "裝箱檢查通過"
            return rec

    if importlib.util.find_spec("fox3d.pilot_qc_api") is None:

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

            stage = body.get("stage") or "FINAL"
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
            raw_nom = body.get("nominal") if "nominal" in body and body.get("nominal") is not None else spec.get("nominal")
            nominal = _require_finite_number(raw_nom if raw_nom is not None else measured, "nominal")
            raw_tol = body.get("tol") if "tol" in body and body.get("tol") is not None else spec.get("tol")
            tol = _require_finite_number(raw_tol if raw_tol is not None else 0.0, "tol")
            unit = str(body.get("unit") or spec.get("unit") or "mm")

            raw_source = body.get("source") or "MANUAL"
            if not isinstance(raw_source, str) or raw_source not in _ALLOWED_QC_SOURCES:
                raise HTTPException(422, "source 須為 MANUAL 或 IMPORTED")

            idem_key = _require_idempotency_key(body)
            operator = str(body.get("operator") or body.get("actor") or "qc")
            sig = f"{work_order_id}:{stage}:{check_id}:{measured}:{nominal}:{tol}:{unit}:{raw_source}"
            store_key = f"{tid}::qc-idem::{work_order_id}::{idem_key}"

            with pilot.workorders._lock:
                _require_wo(pilot, work_order_id, tid)
                if store_key in qc_idem_store:
                    prev_sig, prev_rec = qc_idem_store[store_key]
                    if prev_sig != sig:
                        raise HTTPException(409, "idempotencyKey 衝突")
                    return prev_rec
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
                pilot.qc.persist()
                pilot.workorders.persist()
                qc_idem_store[store_key] = (sig, rec)
                return rec

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
                family = str(wo.get("productFamily") or "KD_FURNITURE")
                req_ok = pilot.qc.required_final_ok(
                    work_order_id, family, tenant_id=tid, plan=wo.get("qcPlan")
                )
                if not req_ok.get("ok"):
                    raise HTTPException(409, "required final QC 尚未全部通過，無法解除 QC_HOLD")
                actor = str(body.get("actor") or "qc")
                if wo.get("state") == "QC_HOLD":
                    for h in wo.get("holds") or []:
                        if h.get("open") and h.get("reason") != "PACKING_MISMATCH":
                            h["open"] = False
                            h["resolvedBy"] = actor
                    pilot.workorders._transition(wo, "IN_PROGRESS", actor=actor, reason="qc-release-hold")
                    pilot.workorders.persist()
                return wo

    return router


router = pilot_packing_router
