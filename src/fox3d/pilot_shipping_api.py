"""Pilot shipping, pallet planning, carrier quotes, carton label, and handoff HTTP API.

Exposes tenant-scoped pallet planning, shipment draft creation, paginated shipment
listing by createdAt with status filter, shipment detail, idempotent manual handoff,
manual/file (JSON/CSV) carrier quote import with quote_stale flagging, and carton
label payload queries. Never connects to or calls any live carrier provider.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request

from fox3d.journal import SemanticKeyConflictError
from fox3d.logistics import ALLOWED_SOURCES, DIM_DIVISOR, _parse_valid_until_date
from fox3d.pilot_packing_api import (
    _optional_idempotency_key,
    _require_body_dict,
    _require_positive_finite,
    _require_tenant,
    _serialize_carton,
)

_ALLOWED_SHIPMENT_STATUSES = frozenset({"SHIPMENT_DRAFT", "HANDED_OFF_MANUAL"})
_MAX_TEXT_LEN = 200
_MAX_CARTONS_PER_REQ = 500


def _require_non_empty_str(raw: Any, field: str, *, max_len: int = _MAX_TEXT_LEN) -> str:
    if not isinstance(raw, str):
        raise HTTPException(422, f"{field} 必填且須為字串")
    val = raw.strip()
    if not val or len(raw) > max_len:
        raise HTTPException(422, f"{field} 須為 1 至 {max_len} 字的非空字串")
    return val


def _optional_str(raw: Any, field: str, *, default: str, max_len: int = _MAX_TEXT_LEN) -> str:
    if raw is None or raw == "":
        return default
    if not isinstance(raw, str):
        raise HTTPException(422, f"{field} 須為字串")
    val = raw.strip()
    if not val or len(raw) > max_len:
        raise HTTPException(422, f"{field} 須為 1 至 {max_len} 字的非空字串")
    return val


def _require_carton_ids(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("cartonIds")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(422, "cartonIds 須為非空陣列")
    if len(raw) > _MAX_CARTONS_PER_REQ:
        raise HTTPException(422, f"cartonIds 數量不可超過 {_MAX_CARTONS_PER_REQ}")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip() or len(item) > _MAX_TEXT_LEN:
            raise HTTPException(422, "cartonIds 內每個項目須為非空字串")
        out.append(item.strip())
    if len(out) != len(set(out)):
        raise HTTPException(422, "cartonIds 不可重複")
    return out


def _verify_tenant_cartons(logistics: Any, carton_ids: list[str], tid: str) -> list[dict[str, Any]]:
    """Every cartonId must exist and belong to the caller's tenant; otherwise fail the whole batch with 404."""
    found: list[dict[str, Any]] = []
    for cid in carton_ids:
        carton = logistics.cartons.get(cid)
        if carton is None or carton.get("tenantId") != tid:
            raise HTTPException(404, "找不到紙箱")
        found.append(carton)
    return found


def _visible_quotes(logistics: Any, tid: str) -> list[dict[str, Any]]:
    rows = [
        q
        for q in logistics.carrier_quotes.values()
        if q.get("tenantId") in (None, tid)
    ]
    rows.sort(key=lambda q: (str(q.get("importedAt") or ""), str(q.get("quoteId") or "")), reverse=True)
    return rows


def _serialize_quote(
    logistics: Any,
    quote: dict[str, Any],
    *,
    target_service: str | None = None,
    target_dim_divisor: float | None = None,
) -> dict[str, Any]:
    eff_service = target_service if target_service is not None else str(quote.get("service") or "ground")
    eff_divisor = target_dim_divisor if target_dim_divisor is not None else float(quote.get("dimDivisor") or DIM_DIVISOR)
    is_stale = bool(logistics.quote_stale(quote, service=eff_service, dim_divisor=eff_divisor))
    out = dict(quote)
    out["stale"] = is_stale
    out["quoteStale"] = is_stale
    out["usable"] = not is_stale
    out["available"] = not is_stale
    out["status"] = "QUOTE_STALE" if is_stale else "VALID_REFERENCE"
    out["statusLabel"] = "報價已過期（quote_stale，不可用）" if is_stale else "僅供試算參考（手動／匯入，未連線物流商）"
    return out


def _serialize_shipment(
    logistics: Any,
    rec: dict[str, Any],
    tid: str,
    *,
    quote_id_override: str | None = None,
    dim_divisor_override: float | None = None,
) -> dict[str, Any]:
    out = dict(rec)
    ship_service = str(out.get("service") or "ground")
    raw_div = dim_divisor_override if dim_divisor_override is not None else out.get("dimDivisor")
    eff_divisor = float(raw_div) if raw_div is not None else DIM_DIVISOR

    all_quotes = [
        _serialize_quote(logistics, q, target_service=ship_service, target_dim_divisor=eff_divisor)
        for q in _visible_quotes(logistics, tid)
    ]
    out["carrierQuotes"] = all_quotes

    target_qid = quote_id_override if quote_id_override is not None else out.get("quoteId")
    selected_quote: dict[str, Any] | None = None
    if isinstance(target_qid, str) and target_qid:
        raw_q = logistics.carrier_quotes.get(target_qid)
        if raw_q is not None and raw_q.get("tenantId") in (None, tid):
            selected_quote = _serialize_quote(
                logistics, raw_q, target_service=ship_service, target_dim_divisor=eff_divisor
            )
    elif all_quotes:
        # Prefer a non-stale quote if one exists; otherwise surface the stale quote so the caller sees quoteStale=True.
        usable_quotes = [q for q in all_quotes if not q["stale"]]
        selected_quote = usable_quotes[0] if usable_quotes else all_quotes[0]

    if selected_quote is not None:
        is_stale = bool(selected_quote["stale"])
        out["quoteId"] = selected_quote["quoteId"]
        out["quote"] = selected_quote
        out["quoteStale"] = is_stale
        out["quoteUsable"] = not is_stale
        out["quoteStatus"] = selected_quote["status"]
        out["quoteStatusLabel"] = selected_quote["statusLabel"]
    else:
        out["quote"] = None
        out["quoteStale"] = False
        out["quoteUsable"] = False
        out["quoteStatus"] = "NO_QUOTE"
        out["quoteStatusLabel"] = "尚未綁定運費報價"
    out["hasStaleQuotes"] = any(q["stale"] for q in all_quotes)
    return out


def _parse_positive_number(raw: Any, field: str, row_index: int | None = None) -> float:
    prefix = f"rows[{row_index}] " if row_index is not None else ""
    if raw is None or raw == "" or isinstance(raw, (bool, list, dict)):
        raise HTTPException(422, f"{prefix}{field} 必須是有限正數")
    if isinstance(raw, (int, float)):
        val = float(raw)
    elif isinstance(raw, str):
        try:
            val = float(raw.strip())
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(422, f"{prefix}{field} 必須是有限正數") from None
    else:
        raise HTTPException(422, f"{prefix}{field} 必須是有限正數")
    if not math.isfinite(val) or val <= 0:
        raise HTTPException(422, f"{prefix}{field} 必須是有限正數")
    return val


def _validate_and_normalize_quote_row(
    row: Any,
    *,
    default_source: str,
    row_index: int | None = None,
) -> tuple[dict[str, Any], str]:
    prefix = f"rows[{row_index}] " if row_index is not None else ""
    if not isinstance(row, dict):
        raise HTTPException(422, f"{prefix}報價資料須為 JSON 物件")

    if row.get("liveProvider") not in (None, False, "", "false", "False", 0, "0"):
        raise HTTPException(422, f"{prefix}不支援即時物流商連線（liveProvider 須為 false）")

    raw_source = row.get("source")
    if raw_source in (None, ""):
        src = default_source
    elif not isinstance(raw_source, str) or raw_source.strip() not in ALLOWED_SOURCES:
        raise HTTPException(422, f"{prefix}source 須為 MANUAL 或 IMPORTED，不呼叫真實物流商")
    else:
        src = raw_source.strip()

    raw_carrier = row.get("carrier")
    if not isinstance(raw_carrier, str) or not raw_carrier.strip() or len(raw_carrier) > _MAX_TEXT_LEN:
        raise HTTPException(422, f"{prefix}carrier 必填且須為非空字串")
    carrier = raw_carrier.strip()

    has_charge = "charge" in row and row.get("charge") not in (None, "")
    has_amount = "amount" in row and row.get("amount") not in (None, "")
    if not has_charge and not has_amount:
        raise HTTPException(422, f"{prefix}charge 必填且須為有限正數")
    raw_charge = row.get("charge") if has_charge else row.get("amount")
    charge = _parse_positive_number(raw_charge, "charge" if has_charge else "amount", row_index)

    raw_divisor = row.get("dimDivisor")
    if raw_divisor in (None, ""):
        dim_divisor = DIM_DIVISOR
    else:
        dim_divisor = _parse_positive_number(raw_divisor, "dimDivisor", row_index)

    raw_service = row.get("service")
    if raw_service in (None, ""):
        service = "ground"
    elif not isinstance(raw_service, str) or not raw_service.strip() or len(raw_service) > 100:
        raise HTTPException(422, f"{prefix}service 須為非空字串")
    else:
        service = raw_service.strip()

    raw_currency = row.get("currency")
    if raw_currency in (None, ""):
        currency = "TWD"
    elif not isinstance(raw_currency, str) or not raw_currency.strip() or len(raw_currency) > 16:
        raise HTTPException(422, f"{prefix}currency 須為非空字串")
    else:
        currency = raw_currency.strip().upper()

    raw_valid_until = row.get("validUntil")
    if raw_valid_until in (None, ""):
        valid_until = "9999-12-31"
    else:
        try:
            valid_until = _parse_valid_until_date(raw_valid_until).isoformat()
        except ValueError as exc:
            raise HTTPException(
                422,
                f"{prefix}validUntil 日期格式錯誤（須為有效的 YYYY-MM-DD 日曆日期）",
            ) from exc

    raw_qid = row.get("quoteId")
    quote_id: str | None = None
    if raw_qid not in (None, ""):
        if not isinstance(raw_qid, str) or not raw_qid.strip() or len(raw_qid) > _MAX_TEXT_LEN:
            raise HTTPException(422, f"{prefix}quoteId 須為非空字串")
        quote_id = raw_qid.strip()

    normalized: dict[str, Any] = {
        "carrier": carrier,
        "service": service,
        "charge": charge,
        "currency": currency,
        "dimDivisor": dim_divisor,
        "validUntil": valid_until,
    }
    if quote_id is not None:
        normalized["quoteId"] = quote_id
    return normalized, src


def _parse_csv_rows(text: str) -> list[dict[str, Any]]:
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(422, "CSV 內容不可為空")
    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        raise HTTPException(422, "CSV 缺少標題列")
    rows: list[dict[str, Any]] = []
    for r in reader:
        if None in r:
            raise HTTPException(422, "CSV 欄位數量與標題列不符")
        cleaned = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k is not None}
        if any(v != "" and v is not None for v in cleaned.values()):
            rows.append(cleaned)
    if not rows:
        raise HTTPException(422, "CSV 至少須包含一筆報價資料")
    return rows


def _parse_json_text_rows(text: str) -> list[Any]:
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(422, "JSON 內容不可為空")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "JSON 格式錯誤") from exc
    if isinstance(parsed, list):
        if not parsed:
            raise HTTPException(422, "至少須提供一筆運費報價")
        return parsed
    if isinstance(parsed, dict):
        for key in ("rows", "items", "quotes"):
            if key in parsed:
                sub = parsed[key]
                if not isinstance(sub, list) or not sub:
                    raise HTTPException(422, f"{key} 須為非空陣列")
                return sub
        return [parsed]
    raise HTTPException(422, "JSON 報價內容須為物件或陣列")


def pilot_shipping_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/pilot/cartons")
    def list_tenant_cartons(
        workOrderId: str | None = Query(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=100),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            rows = [
                _serialize_carton(c)
                for c in logistics.cartons.values()
                if c.get("tenantId") == tid and (not workOrderId or c.get("workOrderId") == workOrderId)
            ]
            rows.sort(
                key=lambda c: (str(c.get("createdAt") or ""), int(c.get("index") or 0), str(c.get("cartonId") or "")),
                reverse=True,
            )
            total = len(rows)
            page = rows[offset : offset + limit]
            return {
                "tenantId": tid,
                "items": page,
                "cartons": page,
                "total": total,
                "offset": offset,
                "limit": limit,
            }

    @router.get("/api/pilot/cartons/{carton_id}/label")
    def get_carton_label(
        carton_id: str,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            carton = logistics.cartons.get(carton_id)
            if carton is None or carton.get("tenantId") != tid:
                raise HTTPException(404, "找不到紙箱")
            label = dict(logistics.label_payload(carton_id))
            label["tenantId"] = tid
            label["workOrderId"] = carton.get("workOrderId")
            label["truthLabel"] = "PARTIAL"
            return label

    @router.post("/api/pilot/pallets")
    def create_pallet_plan(
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        carton_ids = _require_carton_ids(body)
        idem_key = _optional_idempotency_key(body)

        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            _verify_tenant_cartons(logistics, carton_ids, tid)
            if idem_key is not None:
                store_key = f"{tid}::pallet::{idem_key}"
                if store_key in logistics._idem:
                    entry = logistics._idem[store_key]
                    if not isinstance(entry, dict) or entry.get("cartonIds") != carton_ids:
                        raise HTTPException(409, "idempotencyKey 衝突：相同冪等鍵不可用於不同紙箱組合")
                    existing = logistics.pallets.get(str(entry.get("palletPlanId") or ""))
                    if existing is None or existing.get("tenantId") != tid:
                        raise HTTPException(409, "idempotencyKey 衝突")
                    return dict(existing)
            try:
                plan = logistics.palletize(carton_ids)
            except PermissionError as exc:
                raise HTTPException(404, "找不到紙箱") from exc
            if idem_key is not None:
                logistics._idem[f"{tid}::pallet::{idem_key}"] = {
                    "palletPlanId": plan["palletPlanId"],
                    "cartonIds": list(carton_ids),
                }
                logistics.persist()
            return dict(plan)

    @router.get("/api/pilot/pallets")
    def list_pallet_plans(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=100),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            rows = [dict(p) for p in logistics.pallets.values() if p.get("tenantId") == tid]
            rows.sort(key=lambda p: str(p.get("palletPlanId") or ""), reverse=True)
            total = len(rows)
            page = rows[offset : offset + limit]
            return {
                "tenantId": tid,
                "items": page,
                "pallets": page,
                "total": total,
                "offset": offset,
                "limit": limit,
                "carrierCertification": False,
            }

    @router.post("/api/pilot/shipments")
    def create_shipment_draft(
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        origin = _require_non_empty_str(body.get("origin"), "origin")
        destination = _require_non_empty_str(body.get("destination"), "destination")
        carton_ids = _require_carton_ids(body)
        service = _optional_str(body.get("service"), "service", default="ground", max_len=100)
        idem_key = _optional_idempotency_key(body)

        dim_divisor: float | None = None
        if "dimDivisor" in body and body.get("dimDivisor") is not None and body.get("dimDivisor") != "":
            dim_divisor = _require_positive_finite(body.get("dimDivisor"), "dimDivisor")

        quote_id: str | None = None
        if "quoteId" in body and body.get("quoteId") is not None and body.get("quoteId") != "":
            quote_id = _require_non_empty_str(body.get("quoteId"), "quoteId")

        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            _verify_tenant_cartons(logistics, carton_ids, tid)
            if quote_id is not None:
                quote = logistics.carrier_quotes.get(quote_id)
                if quote is None or quote.get("tenantId") not in (None, tid):
                    raise HTTPException(404, "找不到運費報價")

            req_sig = {
                "origin": origin,
                "destination": destination,
                "cartonIds": sorted(carton_ids),
                "service": service,
                "quoteId": quote_id,
                "dimDivisor": dim_divisor,
            }
            if idem_key is not None:
                store_key = f"{tid}::shipment-key::{idem_key}"
                if store_key in logistics._idem:
                    entry = logistics._idem[store_key]
                    if not isinstance(entry, dict) or entry.get("sig") != req_sig:
                        raise HTTPException(409, "idempotencyKey 衝突：相同冪等鍵不可用於不同出貨參數")
                    existing = logistics.shipments.get(str(entry.get("shipmentId") or ""))
                    if existing is None or existing.get("tenantId") != tid:
                        raise HTTPException(409, "idempotencyKey 衝突")
                    if existing.get("status") == "HANDED_OFF_MANUAL" or existing.get("handoff") is not None:
                        raise HTTPException(409, "出貨單已人工交運，不可透過建立草稿改寫")
                    return _serialize_shipment(logistics, existing, tid)

            try:
                rec = logistics.shipment_draft(
                    origin=origin,
                    destination=destination,
                    carton_ids=carton_ids,
                    service=service,
                    quote_id=quote_id,
                    dim_divisor=dim_divisor,
                )
            except SemanticKeyConflictError as exc:
                raise HTTPException(409, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            except PermissionError as exc:
                raise HTTPException(404, "找不到紙箱") from exc

            if idem_key is not None:
                logistics._idem[f"{tid}::shipment-key::{idem_key}"] = {
                    "shipmentId": rec["shipmentId"],
                    "sig": req_sig,
                }
                logistics.persist()
            return _serialize_shipment(logistics, rec, tid)

    @router.get("/api/pilot/shipments")
    def list_shipments(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=100),
        status: str | None = Query(default=None),
        state: str | None = Query(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        raw_status = status if status is not None else state
        want_status: str | None = None
        if raw_status is not None and raw_status != "":
            want = raw_status.strip()
            if want not in _ALLOWED_SHIPMENT_STATUSES:
                raise HTTPException(422, "status 須為 SHIPMENT_DRAFT 或 HANDED_OFF_MANUAL")
            want_status = want

        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            rows = [
                r
                for r in logistics.shipments.values()
                if r.get("tenantId") == tid and (want_status is None or r.get("status") == want_status)
            ]
            rows.sort(
                key=lambda r: (str(r.get("createdAt") or ""), str(r.get("shipmentId") or "")),
                reverse=True,
            )
            total = len(rows)
            page = [_serialize_shipment(logistics, r, tid) for r in rows[offset : offset + limit]]
            return {
                "tenantId": tid,
                "items": page,
                "shipments": page,
                "total": total,
                "offset": offset,
                "limit": limit,
                "liveCarrier": False,
            }

    @router.get("/api/pilot/shipments/{shipment_id}")
    def get_shipment(
        shipment_id: str,
        quoteId: str | None = Query(default=None),
        dimDivisor: float | None = Query(default=None, gt=0),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            rec = logistics.shipments.get(shipment_id)
            if rec is None or rec.get("tenantId") != tid:
                raise HTTPException(404, "找不到出貨單")
            if quoteId is not None and quoteId != "":
                q = logistics.carrier_quotes.get(quoteId)
                if q is None or q.get("tenantId") not in (None, tid):
                    raise HTTPException(404, "找不到運費報價")
            return _serialize_shipment(
                logistics,
                rec,
                tid,
                quote_id_override=quoteId if quoteId else None,
                dim_divisor_override=dimDivisor,
            )

    @router.post("/api/pilot/shipments/{shipment_id}/handoff")
    def handoff_shipment(
        shipment_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body_dict(payload)
        tid = _require_tenant(x_tenant_id, body)
        if "confirm" in body and body.get("confirm") is False:
            raise HTTPException(422, "confirm 不可為 false")
        carrier = _require_non_empty_str(body.get("carrier"), "carrier")
        tracking = _require_non_empty_str(body.get("tracking"), "tracking")
        actor = _optional_str(body.get("actor"), "actor", default="ops", max_len=120)

        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            rec = logistics.shipments.get(shipment_id)
            if rec is None or rec.get("tenantId") != tid:
                raise HTTPException(404, "找不到出貨單")
            try:
                handed = logistics.shipment_handoff(
                    shipment_id,
                    tenant_id=tid,
                    carrier=carrier,
                    tracking=tracking,
                    actor=actor,
                )
            except SemanticKeyConflictError as exc:
                raise HTTPException(409, str(exc)) from exc
            except PermissionError as exc:
                if str(exc).startswith("tenant isolation"):
                    raise HTTPException(404, "找不到出貨單") from exc
                raise HTTPException(409, str(exc)) from exc
            return _serialize_shipment(logistics, handed, tid)

    @router.post("/api/pilot/carrier-quotes")
    async def import_carrier_quotes(
        request: Request,
        service: str | None = Query(default=None),
        dimDivisor: float | None = Query(default=None, gt=0),
        shipmentId: str | None = Query(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        content_type = (request.headers.get("content-type") or "").lower()
        default_source = "MANUAL"
        raw_rows: list[Any] = []
        body_dict: dict[str, Any] = {}

        if content_type.startswith("multipart/form-data"):
            tid = _require_tenant(x_tenant_id)
            form = await request.form()
            form_source = form.get("source")
            if isinstance(form_source, str) and form_source.strip():
                if form_source.strip() not in ALLOWED_SOURCES:
                    raise HTTPException(422, "source 須為 MANUAL 或 IMPORTED，不呼叫真實物流商")
                default_source = form_source.strip()
            else:
                default_source = "IMPORTED"
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(422, "請上傳 JSON 或 CSV 報價檔案")
            raw_bytes = await upload.read()  # type: ignore[misc]
            try:
                text = raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise HTTPException(422, "檔案編碼須為 UTF-8") from exc
            filename = (getattr(upload, "filename", "") or "").lower()
            fmt = str(form.get("format") or "").strip().lower()
            if fmt == "csv" or filename.endswith(".csv"):
                raw_rows = _parse_csv_rows(text)
            elif fmt == "json" or filename.endswith(".json") or text.lstrip().startswith(("[", "{")):
                raw_rows = _parse_json_text_rows(text)
            else:
                raw_rows = _parse_csv_rows(text)
        elif content_type.startswith("text/csv"):
            tid = _require_tenant(x_tenant_id)
            default_source = "IMPORTED"
            raw_bytes = await request.body()
            try:
                text = raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise HTTPException(422, "CSV 編碼須為 UTF-8") from exc
            raw_rows = _parse_csv_rows(text)
        else:
            raw_bytes = await request.body()
            if not raw_bytes or not raw_bytes.strip():
                _require_tenant(x_tenant_id)
                raise HTTPException(422, "請求內容不可為空")
            try:
                parsed = json.loads(raw_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                _require_tenant(x_tenant_id)
                raise HTTPException(422, "請求內容須為有效的 JSON") from exc

            if isinstance(parsed, list):
                tid = _require_tenant(x_tenant_id)
                if not parsed:
                    raise HTTPException(422, "至少須提供一筆運費報價")
                default_source = "IMPORTED"
                raw_rows = parsed
            elif isinstance(parsed, dict):
                body_dict = parsed
                tid = _require_tenant(x_tenant_id, body_dict)
                if body_dict.get("liveProvider") not in (None, False, "", "false", "False", 0, "0"):
                    raise HTTPException(422, "不支援即時物流商連線（liveProvider 須為 false）")
                top_source = body_dict.get("source")
                if top_source not in (None, ""):
                    if not isinstance(top_source, str) or top_source.strip() not in ALLOWED_SOURCES:
                        raise HTTPException(422, "source 須為 MANUAL 或 IMPORTED，不呼叫真實物流商")
                    default_source = top_source.strip()

                if "csv" in body_dict:
                    if top_source in (None, ""):
                        default_source = "IMPORTED"
                    if not isinstance(body_dict["csv"], str):
                        raise HTTPException(422, "csv 欄位須為字串")
                    raw_rows = _parse_csv_rows(body_dict["csv"])
                elif "json" in body_dict:
                    if top_source in (None, ""):
                        default_source = "IMPORTED"
                    if not isinstance(body_dict["json"], str):
                        raise HTTPException(422, "json 欄位須為字串")
                    raw_rows = _parse_json_text_rows(body_dict["json"])
                elif "content" in body_dict or "fileContent" in body_dict:
                    if top_source in (None, ""):
                        default_source = "IMPORTED"
                    raw_text = body_dict.get("content") if "content" in body_dict else body_dict.get("fileContent")
                    if not isinstance(raw_text, str):
                        raise HTTPException(422, "檔案內容須為字串")
                    fmt = str(body_dict.get("format") or "").strip().lower()
                    if fmt == "csv":
                        raw_rows = _parse_csv_rows(raw_text)
                    elif fmt == "json":
                        raw_rows = _parse_json_text_rows(raw_text)
                    elif raw_text.lstrip().startswith(("[", "{")):
                        raw_rows = _parse_json_text_rows(raw_text)
                    else:
                        raw_rows = _parse_csv_rows(raw_text)
                elif any(k in body_dict for k in ("rows", "items", "quotes")):
                    if top_source in (None, ""):
                        default_source = "IMPORTED"
                    for k in ("rows", "items", "quotes"):
                        if k in body_dict:
                            sub = body_dict[k]
                            if not isinstance(sub, list) or not sub:
                                raise HTTPException(422, f"{k} 須為非空陣列")
                            raw_rows = sub
                            break
                else:
                    raw_rows = [body_dict]
            else:
                _require_tenant(x_tenant_id)
                raise HTTPException(422, "請求內容須為 JSON 物件或陣列")

        is_batch = len(raw_rows) > 1 or any(
            k in body_dict for k in ("rows", "items", "quotes", "csv", "json", "content", "fileContent")
        )
        validated: list[tuple[dict[str, Any], str]] = []
        seen_qids: set[str] = set()
        for idx, row in enumerate(raw_rows):
            norm, src = _validate_and_normalize_quote_row(
                row,
                default_source=default_source,
                row_index=idx if is_batch else None,
            )
            qid = norm.get("quoteId")
            if isinstance(qid, str) and qid:
                if qid in seen_qids:
                    prefix = f"rows[{idx}] " if is_batch else ""
                    raise HTTPException(422, f"{prefix}批次報價中 quoteId 不可重複")
                seen_qids.add(qid)
            validated.append((norm, src))

        target_service = service
        if target_service is None:
            for key in ("targetService", "expectedService", "checkService"):
                val = body_dict.get(key)
                if isinstance(val, str) and val.strip():
                    target_service = val.strip()
                    break
            if target_service is None and is_batch and isinstance(body_dict.get("service"), str) and body_dict["service"].strip():
                target_service = body_dict["service"].strip()

        target_divisor = dimDivisor
        if target_divisor is None:
            for key in ("targetDimDivisor", "expectedDimDivisor", "checkDimDivisor"):
                if key in body_dict and body_dict.get(key) not in (None, ""):
                    target_divisor = _require_positive_finite(body_dict.get(key), key)
                    break
            if target_divisor is None and is_batch and body_dict.get("dimDivisor") not in (None, ""):
                target_divisor = _require_positive_finite(body_dict.get("dimDivisor"), "dimDivisor")

        eff_shipment_id = shipmentId or (
            str(body_dict["shipmentId"]).strip()
            if isinstance(body_dict.get("shipmentId"), str) and body_dict["shipmentId"].strip()
            else None
        )

        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            if eff_shipment_id is not None:
                ship = logistics.shipments.get(eff_shipment_id)
                if ship is None or ship.get("tenantId") != tid:
                    raise HTTPException(404, "找不到出貨單")
                if target_service is None:
                    target_service = str(ship.get("service") or "ground")
                if target_divisor is None:
                    target_divisor = float(ship.get("dimDivisor") or DIM_DIVISOR)

            for norm, _src in validated:
                qid = norm.get("quoteId")
                if isinstance(qid, str) and qid:
                    existing = logistics.carrier_quotes.get(qid)
                    if existing is not None and existing.get("tenantId") != tid:
                        raise HTTPException(409, "quoteId 衝突：該報價 ID 已由其他租戶持有")

            prev_quotes = dict(logistics.carrier_quotes)
            created: list[dict[str, Any]] = []
            try:
                for norm, src in validated:
                    row_with_tenant = {**norm, "tenantId": tid}
                    rec = logistics.import_carrier_quote(
                        row_with_tenant,
                        source=src,
                        tenant_id=tid,
                        persist=False,
                    )
                    created.append(
                        _serialize_quote(
                            logistics,
                            rec,
                            target_service=target_service,
                            target_dim_divisor=target_divisor,
                        )
                    )
                logistics.persist()
            except PermissionError as exc:
                logistics.carrier_quotes = prev_quotes
                raise HTTPException(409, "quoteId 衝突：該報價 ID 已由其他租戶持有") from exc
            except ValueError as exc:
                logistics.carrier_quotes = prev_quotes
                raise HTTPException(422, str(exc)) from exc
            except Exception:
                logistics.carrier_quotes = prev_quotes
                raise

        primary = created[0]
        return {
            **primary,
            "tenantId": tid,
            "items": created,
            "quotes": created,
            "count": len(created),
            "liveProvider": False,
        }

    @router.get("/api/pilot/carrier-quotes")
    def list_carrier_quotes(
        service: str | None = Query(default=None),
        dimDivisor: float | None = Query(default=None, gt=0),
        shipmentId: str | None = Query(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        logistics = provider().pilot.logistics
        with logistics._lock:
            logistics._sync_from_disk()
            target_service = service.strip() if isinstance(service, str) and service.strip() else None
            target_divisor = dimDivisor
            if shipmentId is not None and shipmentId.strip():
                ship = logistics.shipments.get(shipmentId.strip())
                if ship is None or ship.get("tenantId") != tid:
                    raise HTTPException(404, "找不到出貨單")
                if target_service is None:
                    target_service = str(ship.get("service") or "ground")
                if target_divisor is None:
                    target_divisor = float(ship.get("dimDivisor") or DIM_DIVISOR)

            items = [
                _serialize_quote(
                    logistics,
                    q,
                    target_service=target_service,
                    target_dim_divisor=target_divisor,
                )
                for q in _visible_quotes(logistics, tid)
            ]
            return {
                "tenantId": tid,
                "items": items,
                "quotes": items,
                "total": len(items),
                "hasStaleQuotes": any(q["stale"] for q in items),
                "liveProvider": False,
            }

    return router


router = pilot_shipping_router
