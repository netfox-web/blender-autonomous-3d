"""Pilot work order packing & carton measurement HTTP API.

Exposes carton instantiation + work order binding, tenant-scoped carton listing,
measured dimension/weight recording, and packing checklist generation.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from fox3d.ids import stable_hash
from fox3d.infra import validate_tenant_id
from fox3d.journal import SemanticKeyConflictError
from fox3d.logistics import _measured_snapshot_equal
from fox3d.operator import require_confirm

_ALLOWED_MEASURE_SOURCES = frozenset({"MANUAL", "IMPORTED", "MEASURED"})
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


def _sync_wo_mismatch_hold(pilot: Any, work_order_id: str, tid: str, *, actor: str = "pack") -> bool:
    wo = pilot.workorders.orders.get(work_order_id)
    if wo is None or wo.get("tenantId") != tid:
        return False
    return bool(pilot.workorders.sync_packing_mismatch(work_order_id, actor=actor))


def _snapshot_positive(raw: Any, field: str) -> float:
    """Release snapshot values must be finite positive numbers; never substitute a default."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise HTTPException(422, f"放行快照缺少有效的 {field}，無法建立紙箱")
    val = float(raw)
    if not math.isfinite(val) or val <= 0:
        raise HTTPException(422, f"放行快照缺少有效的 {field}，無法建立紙箱")
    return val


def _expected_packing_from_release(pilot: Any, wo: dict[str, Any]) -> tuple[dict[str, Any], float]:
    """Carton plan + expected gross weight from the release snapshot (product truth, no 8 kg default)."""
    rel = pilot.releases.releases.get(str(wo.get("releaseId") or "")) or {}
    raw_snap = rel.get("snapshot")
    snap: dict[str, Any] = raw_snap if isinstance(raw_snap, dict) else {}
    packing = snap.get("packing")
    if not isinstance(packing, dict):
        packing = {}
    plan = dict(packing)
    for dim in ("length", "width", "height"):
        plan[dim] = _snapshot_positive(packing.get(dim), f"packing.{dim}")
    weight_info = snap.get("weight")
    if not isinstance(weight_info, dict):
        weight_info = {}
    raw_weight = weight_info.get("grossKg")
    if raw_weight is None:
        raw_weight = packing.get("weightKg")
    return plan, _snapshot_positive(raw_weight, "weight.grossKg")


def _packing_status(mismatch: bool, mismatch_hold: bool, *, ok_text: str) -> str:
    if mismatch_hold:
        return "尺寸不符待人工確認"
    if mismatch:
        return "尺寸不符已人工確認"
    return ok_text


_QC_OPEN_STATES_REJECTED = frozenset({"DRAFT", "RELEASED_FOR_MANUAL_EXECUTION"})


def pilot_packing_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

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
            if not is_retry:
                bound = [
                    c
                    for c in pilot.logistics.cartons.values()
                    if c.get("workOrderId") == work_order_id and c.get("tenantId") == tid
                ]
                if bound or wo.get("cartonIds"):
                    raise HTTPException(409, "工單已有其他冪等鍵建立的紙箱，不可再建立新的一批")
                packing, expected_weight = _expected_packing_from_release(pilot, wo)
            else:
                packing, expected_weight = {}, 0.0  # replay: stored cartons are returned unchanged
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
                "mismatchHold": bool(wo.get("mismatchHold")),
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
            wo = _require_wo(pilot, str(carton.get("workOrderId") or ""), tid)
            if wo.get("state") in {"COMPLETED", "REJECTED", "CANCELLED"}:
                previous = (carton.get("measureOps") or {}).get(op_id) if op_id else None
                if previous is None or not _measured_snapshot_equal(previous["measured"], target_measured):
                    raise HTTPException(409, "工單已結束，無法回填實測值")
                out = _serialize_carton(carton)
                out["mismatchHold"] = bool(wo.get("mismatchHold"))
                out["statusMessage"] = _packing_status(out["mismatch"], out["mismatchHold"], ok_text="實測尺寸符合預期")
                return out
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
            out["statusMessage"] = _packing_status(out["mismatch"], mismatch_hold, ok_text="實測尺寸符合預期")
            return out

    @router.post("/api/pilot/work-orders/{work_order_id}/packing-checklist")
    def create_packing_checklist(
        work_order_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        idem_key = _optional_idempotency_key(body, "idempotencyKey")
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
            signature = stable_hash({"releaseHash": rel_hash, "items": expected_items})
            store_key = f"{tid}::checklist::{work_order_id}::{idem_key}" if idem_key else None
            previous = pilot.logistics._idem.get(store_key) if store_key else None
            if previous is not None:
                if previous["signature"] != signature:
                    raise HTTPException(409, "idempotencyKey 衝突")
                existing = pilot.logistics.checklists[previous["checklistId"]]
            else:
                existing = None
            for chk in reversed(list(pilot.logistics.checklists.values())) if existing is None else []:
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
            if store_key and previous is None:
                pilot.logistics._idem[store_key] = {"signature": signature, "checklistId": rec["checklistId"]}
            pilot.logistics.persist()
            mismatch_hold = _sync_wo_mismatch_hold(pilot, work_order_id, tid)
            rec["mismatch"] = bool(rec.get("mismatchHold"))
            rec["mismatchHold"] = mismatch_hold
            rec["carrierProvider"] = "BLOCKED/NOT_CONNECTED"
            rec["statusMessage"] = _packing_status(rec["mismatch"], mismatch_hold, ok_text="裝箱檢查通過")
            return rec

    @router.post("/api/pilot/work-orders/{work_order_id}/packing-mismatch/resolve")
    def resolve_packing_mismatch(
        work_order_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Human sign-off on out-of-tolerance cartons: closes the open PACKING_MISMATCH hold(s).

        Carton ``mismatch`` / ``autoOverride`` stay as recorded; only the work-order gate is lifted.
        """
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        pilot = provider().pilot
        _require_wo(pilot, work_order_id, tid)
        try:
            require_confirm(body, action="resolve_packing_mismatch")
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        actor = str(body.get("actor") or "pack")[:120]

        with pilot.workorders._lock, pilot.logistics._lock:
            wo = _require_wo(pilot, work_order_id, tid)
            # Bring legacy / not-yet-synced mismatches under a hold first so the sign-off covers them.
            _sync_wo_mismatch_hold(pilot, work_order_id, tid, actor=actor)
            open_pm = [
                h for h in wo.get("holds") or [] if h.get("open") and h.get("reason") == "PACKING_MISMATCH"
            ]
            try:
                for h in open_pm:
                    pilot.workorders.resolve_hold(work_order_id, h["holdId"], actor=actor)
            except PermissionError as exc:
                raise HTTPException(409, str(exc)) from exc
            mismatch_hold = _sync_wo_mismatch_hold(pilot, work_order_id, tid, actor=actor)
            pilot.workorders.persist()
            return {
                "workOrderId": work_order_id,
                "tenantId": tid,
                "state": wo.get("state"),
                "mismatchHold": mismatch_hold,
                "resolvedHoldIds": [h["holdId"] for h in open_pm],
                "holds": wo.get("holds") or [],
            }


    return router


router = pilot_packing_router
