"""HTTP API — FastAPI. Admin UI talks to this, never to a Blender GUI."""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone

from pathlib import Path
from typing import Any, NoReturn

from fastapi import Body, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import ValidationError

from fox3d.journal import JournalCommitError, SemanticKeyConflictError
from fox3d.admin import render_admin
from fox3d.admin_pages import page_routers
from fox3d.commerce import ImportValidationError, ProviderDisconnectedError
from fox3d.contracts import (
    ALLOWED_SOURCES,
    SCHEMA_ADJUST,
    SCHEMA_CARRIER,
    SCHEMA_RECEIPT,
    SCHEMA_SUPPLIER,
)
from fox3d.features import feature_index
from fox3d.infra import utcnow, validate_tenant_id
from fox3d.release import MAX_EVENTS_PER_TENANT
from fox3d.operator import make_token, require_confirm
from fox3d.pilot_packing_api import pilot_packing_router
from fox3d.pilot_batch_api import pilot_batch_router
from fox3d.pilot_qc_api import pilot_qc_router
from fox3d.pilot_shipping_api import pilot_shipping_router
from fox3d.platform import Platform
from fox3d.product_rd_store import (
    ProductRDIdempotencyConflict,
    validate_optional_idempotency_key,
    validate_rd_actor,
    validate_rd_text,
    validate_rd_variant_count,
)
from fox3d.recovery import ExceptionStateError, PilotException
from fox3d.cyclecount_api import cyclecount_router
from fox3d.materials_lot_ops_api import materials_lot_ops_router
from fox3d.recipe_admin_api import recipe_router
from fox3d.station import ADMIN_STATION_STATUSES, STATION_CAPS


def _dimensions(value: Any) -> None:
    from fox3d.safety import _positive_finite_dimension

    if not isinstance(value, dict):
        raise HTTPException(422, "尺寸欄位必須是物件")
    for key, item in value.items():
        if key in {"width", "height", "depth", "length", "thickness"}:
            if _positive_finite_dimension(item) is None:
                raise HTTPException(422, f"無效尺寸: {key}")
        elif key == "dimensions":
            _dimensions(item)
        elif isinstance(item, dict):
            _dimensions(item)
        elif isinstance(item, list):
            for child in item:
                if isinstance(child, dict):
                    _dimensions(child)


def _choice(value: Any, choices: Any, field: str) -> None:
    if not isinstance(value, str) or value not in choices:
        raise HTTPException(422, f"{field} 可用值: {', '.join(sorted(choices))}")


_MAX_REMNANT_LEASE_SECONDS = 7 * 86400.0
_MAX_REMNANT_BY_LEN = 120


def _validate_remnant_reserve(body: dict[str, Any]) -> tuple[str, int, float | None, str | None]:
    raw_by = body.get("by")
    if not isinstance(raw_by, str):
        raise HTTPException(422, "by 必須是非空字串且長度不超過 120")
    by = raw_by.strip()
    if not by or len(raw_by) > _MAX_REMNANT_BY_LEN:
        raise HTTPException(422, "by 必須是非空字串且長度不超過 120")

    raw_version = body.get("version")
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 1:
        raise HTTPException(422, "version 必須是正整數")

    lease_seconds: float | None = None
    if "leaseSeconds" in body:
        raw_lease = body.get("leaseSeconds")
        if isinstance(raw_lease, bool) or not isinstance(raw_lease, (int, float)):
            raise HTTPException(422, "leaseSeconds 必須在 1 至 604800 秒（1–7 天）範圍內")
        try:
            lease_val = float(raw_lease)
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(422, "leaseSeconds 必須在 1 至 604800 秒（1–7 天）範圍內") from None
        if not math.isfinite(lease_val) or not (1.0 <= lease_val <= _MAX_REMNANT_LEASE_SECONDS):
            raise HTTPException(422, "leaseSeconds 必須在 1 至 604800 秒（1–7 天）範圍內")
        lease_seconds = lease_val

    raw_idem = body.get("idempotencyKey")
    if raw_idem is not None and (not isinstance(raw_idem, str) or len(raw_idem) > 200):
        raise HTTPException(422, "idempotencyKey 格式錯誤")
    idem = raw_idem.strip() if isinstance(raw_idem, str) and raw_idem.strip() else None
    return by, raw_version, lease_seconds, idem


_MAX_SKU_CHARS = 128
_MAX_SKU_UTF8_BYTES = 200


def _require_valid_sku(sku: Any, *, allow_separators: bool = False) -> str:
    """SKU limits shared by JSON create and multipart upload (422, never 500).

    Both enforce the same character and UTF-8 byte limits. Upload keeps its
    existing contract of accepting ``/``, ``\\`` and control characters, which
    ``safe_path_component`` encodes; JSON create rejects them.
    """
    if not isinstance(sku, str) or not sku or len(sku) > _MAX_SKU_CHARS:
        raise HTTPException(422, "sku 格式錯誤")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in sku) or len(sku.encode("utf-8", "surrogatepass")) > _MAX_SKU_UTF8_BYTES:
        raise HTTPException(422, "sku 格式錯誤")
    if not allow_separators and any(ord(c) < 32 or c in "/\\" for c in sku):
        raise HTTPException(422, "sku 格式錯誤")
    return sku


def _entity_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise HTTPException(422, "entityId 格式錯誤")
    return value


_SNAPSHOT_KINDS = ("material", "hardware", "packaging", "logistics", "fx")
_MAX_COMMERCE_SNAPSHOT_PAGE = 100
_SNAPSHOT_AT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?$"
)


def _snapshot_at(raw: str | None) -> str:
    if raw is None:
        return utcnow().isoformat()
    if not isinstance(raw, str) or not _SNAPSHOT_AT_RE.fullmatch(raw):
        raise HTTPException(422, "at 格式錯誤")
    try:
        if "T" in raw or " " in raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed.astimezone(timezone.utc)
        else:
            datetime.strptime(raw, "%Y-%m-%d")
    except (ValueError, OverflowError):
        raise HTTPException(422, "at 格式錯誤") from None
    return raw


def _approval_stale(ledger: Any, approval: dict[str, Any], entity: dict[str, Any] | None) -> bool:
    """Read-only staleness. A stored stale flag wins; otherwise compare current hashes."""
    if approval.get("stale") is True:
        return True
    if entity is None:
        return False
    return bool(ledger.is_stale(approval, entity))


def _annotate_release_row(row: dict[str, Any]) -> None:
    """Mark released only when the row is an export approval that is not stale or blocked."""
    decision = row.get("decision")
    state = row.get("state")
    decision_s = decision if isinstance(decision, str) else ""
    state_s = state if isinstance(state, str) else ""
    stale = row.get("stale") is True or decision_s == "STALE" or state_s == "STALE"
    blocked = row.get("blocked") is True or decision_s == "BLOCKED" or state_s == "BLOCKED"
    approved = decision_s == "APPROVED_FOR_EXPORT" or state_s == "APPROVED_FOR_EXPORT"
    row["stale"] = stale
    row["blocked"] = blocked
    row["released"] = approved and not stale and not blocked and row.get("verificationAvailable") is not False


def _stamp_snapshot_tenant(rows: Any, tenant_id: str) -> Any:
    if not isinstance(rows, list):
        return rows
    stamped: list[Any] = []
    for row in rows:
        if isinstance(row, dict):
            rec = dict(row)
            rec["tenantId"] = tenant_id
            stamped.append(rec)
        else:
            stamped.append(row)
    return stamped


# These services raise PermissionError for bad input. Handlers check fields first.
# A leftover PermissionError is 422 unless it is tenant isolation (403).
# PilotException subclasses PermissionError and is re-raised unchanged.
_IMPORT_SCHEMAS = frozenset({SCHEMA_RECEIPT, SCHEMA_SUPPLIER, SCHEMA_CARRIER, SCHEMA_ADJUST})
_DISPATCH_FIELDS = ("workOrderId", "operation", "stationId")
# import_receipt uses `value or default` for these, so "", 0, and other falsy values are absent.
_RECEIPT_OR_FLOATS = (
    ("thickness",),
    ("unitCost", "costPerSheet"),
)
# import_receipt converts these whenever they are not None, including "".
_RECEIPT_STRICT_FLOATS = (
    "length",
    "width",
    "expectedThickness",
    "expectedLength",
    "expectedWidth",
)


def _validation_detail(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc") or ()) or "body"
        if err.get("type") == "missing":
            parts.append(f"缺少 {loc}")
        else:
            parts.append(f"{loc} 格式錯誤")
    return "；".join(parts) or "輸入格式錯誤"


def _raise_permission(exc: PermissionError) -> NoReturn:
    message = str(exc)
    if message.startswith("tenant isolation"):
        raise HTTPException(403, message) from exc
    raise HTTPException(422, message) from exc


def _pilot_tenant_missing(exc: BaseException) -> bool:
    return isinstance(exc, (KeyError, PermissionError)) and (
        isinstance(exc, KeyError) or str(exc).startswith("tenant isolation")
    )


def _require_json_object(payload: Any, *, allow_none: bool = False) -> dict[str, Any]:
    if payload is None and allow_none:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "請求內容須為 JSON 物件")
    return payload


def _optional_str_field(payload: dict[str, Any], field: str) -> str | None:
    raw = payload.get(field)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HTTPException(422, f"{field} 格式錯誤")
    return raw


def _optional_key_field(payload: dict[str, Any], field: str) -> str | None:
    if field not in payload or payload[field] in (None, ""):
        return None
    raw = payload[field]
    if not isinstance(raw, str):
        raise HTTPException(422, f"{field} 格式錯誤")
    val = raw.strip()
    if not val or len(raw) > 200:
        raise HTTPException(422, f"{field} 格式錯誤")
    return val


def _paginate_list(
    request: Request,
    rows: list[dict[str, Any]],
    *,
    offset: int,
    limit: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(rows)
    base: dict[str, Any] = dict(extra or {})
    if "offset" not in request.query_params and "limit" not in request.query_params:
        return {**base, "items": rows, "total": total, "offset": 0, "limit": total}
    page = rows[offset : offset + limit]
    return {**base, "items": page, "total": total, "offset": offset, "limit": limit}


def _require_text_fields(payload: dict[str, Any], names: tuple[str, ...]) -> None:
    missing = [name for name in names if payload.get(name) in (None, "")]
    if missing:
        raise HTTPException(422, "缺少欄位：" + "、".join(missing))
    bad = [name for name in names if not isinstance(payload.get(name), str)]
    if bad:
        raise HTTPException(422, "欄位格式錯誤：" + "、".join(bad))


def _unprocessable(message: str, row_index: int | None = None) -> NoReturn:
    if row_index is not None:
        message = f"rows[{row_index}] {message}"
    raise HTTPException(422, message)


def _absent_quantity(raw: Any) -> bool:
    # False == 0, so exclude bool before the zero check. 0 / "" still fall through to sheetCount.
    return not isinstance(raw, bool) and raw in (None, "", 0, 0.0)


def _require_receipt_quantity(payload: dict[str, Any], row_index: int | None = None) -> int:
    # import_receipt treats 0 / "" as absent and falls through to sheetCount.
    # int() would truncate 1.9 to 1 and accept True as 1; both are refused here.
    raw = payload.get("quantity")
    if isinstance(raw, bool):
        _unprocessable("quantity 須為正整數", row_index)
    if _absent_quantity(raw):
        raw = payload.get("sheetCount")
        if isinstance(raw, bool):
            _unprocessable("quantity 須為正整數", row_index)
    if _absent_quantity(raw):
        _unprocessable("缺少 quantity", row_index)
    if isinstance(raw, float):
        _unprocessable("quantity 須為正整數", row_index)
    qty = _check_service_int(raw, "quantity", row_index)
    if qty <= 0:
        _unprocessable("quantity 須為正整數", row_index)
    return qty


def _require_purchase_quantity(payload: dict[str, Any]) -> int:
    raw = payload.get("quantity")
    if not isinstance(raw, bool) and raw in (None, ""):
        _unprocessable("缺少 quantity")
    if isinstance(raw, (bool, float)):
        _unprocessable("quantity 須為正整數")
    qty = _check_service_int(raw, "quantity")
    if qty < 1:
        _unprocessable("quantity 須為正整數")
    return qty


def _require_manual_source(payload: dict[str, Any]) -> None:
    source = payload.get("source")
    if source in (None, ""):
        return
    if not isinstance(source, str) or source not in ALLOWED_SOURCES:
        raise HTTPException(422, "source 須為 MANUAL 或 IMPORTED")


def _check_finite_float(raw: Any, field: str, row_index: int | None = None) -> None:
    if isinstance(raw, bool) or isinstance(raw, (list, dict)):
        _unprocessable(f"{field} 格式錯誤", row_index)
    try:
        number = float(raw)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a JSON integer such as 10**400 cannot become a float.
        _unprocessable(f"{field} 格式錯誤", row_index)
    if not math.isfinite(number):
        _unprocessable(f"{field} 格式錯誤", row_index)


def _check_service_int(raw: Any, field: str, row_index: int | None = None) -> int:
    # Matches int(value) without truncating floats or accepting bool (bool is an int subclass).
    if isinstance(raw, bool) or isinstance(raw, float):
        _unprocessable(f"{field} 格式錯誤", row_index)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            _unprocessable(f"{field} 格式錯誤", row_index)
    _unprocessable(f"{field} 格式錯誤", row_index)


def _first_or_value(payload: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, Any] | None:
    # Same short-circuit as `a or b or default`: falsy values are not converted.
    for key in keys:
        raw = payload.get(key)
        if not raw:
            continue
        return key, raw
    return None


def _validate_receipt_numbers(payload: dict[str, Any], row_index: int | None = None) -> None:
    for key in _RECEIPT_STRICT_FLOATS:
        if key not in payload or payload[key] is None:
            continue
        _check_finite_float(payload[key], key, row_index)
    for keys in _RECEIPT_OR_FLOATS:
        found = _first_or_value(payload, keys)
        if found is not None:
            _check_finite_float(found[1], found[0], row_index)
    if "expectedQuantity" in payload and payload["expectedQuantity"] is not None:
        _check_service_int(payload["expectedQuantity"], "expectedQuantity", row_index)


def _require_station_capabilities(payload: dict[str, Any]) -> None:
    raw = payload.get("capabilities")
    if not isinstance(raw, list) or not any(item in STATION_CAPS for item in raw):
        raise HTTPException(422, "capabilities 須包含至少一個 MANUAL 站別能力")


def _validate_supplier_row(row: dict[str, Any], row_index: int) -> None:
    # normalize() converts the first truthy field of each `or` chain.
    for keys in (
        ("material", "materialCost"),
        ("processing", "labor"),
        ("setup", "setupCost", "tooling", "toolingCost"),
        ("packaging", "packagingCost"),
        ("freight", "shipping"),
        ("leadTimeDays", "leadTime"),
    ):
        found = _first_or_value(row, keys)
        if found is not None:
            _check_finite_float(found[1], found[0], row_index)
    quantity = _first_or_value(row, ("quantity", "moq"))
    if quantity is not None:
        _check_service_int(quantity[1], quantity[0], row_index)
    # normalize() also does int(moq or 1), even when quantity was the value used above.
    moq = row.get("moq")
    if moq:
        _check_service_int(moq, "moq", row_index)


def _validate_carrier_row(row: dict[str, Any], row_index: int) -> None:
    for keys in (("charge", "amount"), ("dimDivisor",)):
        found = _first_or_value(row, keys)
        if found is not None:
            _check_finite_float(found[1], found[0], row_index)


def _reject_container_fields(row: dict[str, Any], names: tuple[str, ...], row_index: int) -> None:
    # Tuple membership treats a list or object as present. ContractService then hashes the
    # same value and raises TypeError after earlier rows have already been written.
    for name in names:
        if isinstance(row.get(name), (list, dict)):
            _unprocessable(f"{name} 格式錯誤", row_index)


def _validate_import_row(schema: str, row: dict[str, Any], row_index: int) -> None:
    # Rows missing required fields are rejected by ContractService before conversion.
    # Rows it would convert, and required fields that are lists or objects, are checked
    # here so a later bad row cannot 500 after earlier writes.
    if schema == SCHEMA_RECEIPT:
        _reject_container_fields(row, ("material", "quantity"), row_index)
        if row.get("material") in (None, "") or row.get("quantity") in (None, ""):
            return
        _require_receipt_quantity(row, row_index)
        _validate_receipt_numbers(row, row_index)
    elif schema == SCHEMA_SUPPLIER:
        _reject_container_fields(row, ("supplierId",), row_index)
        if row.get("supplierId") in (None, ""):
            return
        _validate_supplier_row(row, row_index)
    elif schema == SCHEMA_CARRIER:
        _reject_container_fields(row, ("carrier", "charge"), row_index)
        if row.get("carrier") in (None, "") or row.get("charge") in (None, ""):
            return
        _validate_carrier_row(row, row_index)
    elif schema == SCHEMA_ADJUST:
        _reject_container_fields(row, ("lotId", "quantity", "reason"), row_index)
        if any(row.get(name) in (None, "") for name in ("lotId", "quantity", "reason")):
            return
        _check_service_int(row.get("quantity"), "quantity", row_index)


def _require_import_contract(payload: dict[str, Any]) -> None:
    schema = payload.get("schemaVersion")
    # Membership against a set hashes the value; a list or object would raise TypeError.
    if not isinstance(schema, str) or schema not in _IMPORT_SCHEMAS:
        raise HTTPException(422, "schemaVersion 無效或缺少")
    _require_manual_source(payload)
    rows = payload.get("rows", [])
    if rows is None:
        return
    if not isinstance(rows, list):
        raise HTTPException(422, "rows 須為陣列")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise HTTPException(422, "rows 的每一列須為物件")
        _validate_import_row(schema, row, index)


_PLATFORM: Platform | None = None


def get_platform() -> Platform:
    global _PLATFORM
    if _PLATFORM is None:
        _PLATFORM = Platform(mock_blender=False)
        _PLATFORM.register_detected_workers()
    return _PLATFORM


def create_app(platform: Platform | None = None) -> FastAPI:
    app = FastAPI(title="Blender Autonomous 3D / Product R&D Engine", version="0.1.0")
    if platform is not None:
        global _PLATFORM
        _PLATFORM = platform

    def tenant(x_tenant_id: str | None) -> str:
        try:
            return validate_tenant_id(x_tenant_id or "")
        except ValueError as exc:
            raise HTTPException(400, "X-Tenant-Id 無效") from exc

    def require_tenant(x_tenant_id: str | None, payload: dict[str, Any] | None = None) -> str:
        header = tenant(x_tenant_id)
        body_tid = (payload or {}).get("tenantId")
        if body_tid is None or body_tid == "":
            return header
        if not isinstance(body_tid, str):
            raise HTTPException(422, "body tenantId must be a string")
        if body_tid != header:
            raise HTTPException(403, "body tenantId does not match X-Tenant-Id")
        return header

    def bounded_count(
        raw: Any, default: int, field: str = "count", *, max_value: int = 100
    ) -> int:
        if raw is None:
            n = default
        elif isinstance(raw, bool) or not isinstance(raw, int):
            raise HTTPException(422, f"{field} 須為 1 至 {max_value} 的整數")
        else:
            n = raw
        if not 1 <= n <= max_value:
            raise HTTPException(422, f"{field} 須為 1 至 {max_value} 的整數")
        return n

    @app.get("/health")
    def health() -> dict[str, Any]:
        plat = get_platform()
        probe = plat.probe.to_dict() if plat.probe else {}
        return {"status": "ok", "probe": probe, "mock": plat.mock_blender}

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/admin")

    @app.get("/api/probe")
    def probe() -> dict[str, Any]:
        plat = get_platform()
        if plat.probe is None:
            plat.register_detected_workers()
        return plat.probe.to_dict() if plat.probe else {}

    @app.post("/api/3d/jobs")
    def create_job(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        payload["tenantId"] = tid
        try:
            return get_platform().submit_job(payload)
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409 if str(exc) == "idempotency conflict" else 422, str(exc)) from exc

    @app.get("/api/3d/jobs")
    def list_jobs(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        plat = get_platform()
        tid = tenant(x_tenant_id)
        return {"items": plat.queue.list(tenant_id=tid)}

    @app.get("/api/3d/jobs/{job_id}")
    def read_job(job_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return get_platform().get_job(job_id, tenant_id=tenant(x_tenant_id))
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/3d/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return get_platform().cancel_job(job_id, tenant_id=tenant(x_tenant_id))
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/assets/{asset_id}")
    def read_asset(asset_id: str, x_tenant_id: str | None = Header(default=None)) -> FileResponse:
        tid = require_tenant(x_tenant_id)
        try:
            obj = get_platform().dam.get(asset_id, tenant_id=tid)
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, "Asset not found") from exc
        path = Path(obj.path)
        media = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
        # Tenant-scoped bytes keyed only by URL: without these headers a browser
        # may heuristically cache the response (ETag/Last-Modified) and serve it
        # to a later fetch that sends a different X-Tenant-Id (issue #292).
        return FileResponse(
            path,
            media_type=media,
            headers={"Cache-Control": "private, no-store", "Vary": "X-Tenant-Id", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/api/digital-twins")
    def create_twin(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        payload["tenantId"] = tid
        _require_valid_sku(payload.get("sku"))
        try:
            return get_platform().create_twin(payload)
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from exc

    @app.post("/api/digital-twins/upload")
    async def upload_twin(
        sku: str = Form(...),
        file: UploadFile = File(...),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        _require_valid_sku(sku, allow_separators=True)
        data = await file.read()
        return get_platform().product_e2e(tenant_id=tid, sku=sku, glb_bytes=data)

    @app.get("/api/digital-twins")
    def list_twins(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return {"items": [t.model_dump(mode="json") for t in get_platform().twins.list(tenant_id=tenant(x_tenant_id))]}

    @app.get("/api/digital-twins/{twin_id}")
    def read_twin(twin_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return get_platform().get_twin(twin_id, tenant_id=tenant(x_tenant_id))
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/digital-twins/{twin_id}/preview")
    def twin_preview(twin_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        plat = get_platform()
        try:
            twin = plat.get_twin(twin_id, tenant_id=tenant(x_tenant_id))
        except (KeyError, PermissionError):
            raise HTTPException(404, "找不到數位分身") from None
        return plat.product_e2e(tenant_id=twin["tenantId"], sku=twin["sku"], glb_path=twin.get("glb"))

    @app.post("/api/digital-twins/{twin_id}/360")
    def twin_360(twin_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return get_platform().product_360_e2e(tenant_id=tenant(x_tenant_id), twin_id=twin_id, frames=36)
        except (KeyError, PermissionError):
            raise HTTPException(404, "找不到數位分身") from None

    @app.get("/api/parametric/products")
    def list_parametrics(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        return {"items": [r for r in get_platform().parametrics.values() if r.get("spec", {}).get("tenantId") == tid]}

    @app.post("/api/parametric/products")
    def create_parametric(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        payload["tenantId"] = tid
        plat = get_platform()
        for field in ("width", "height", "depth", "thickness", "boardThickness", "backThickness", "doorCount", "shelfCount", "drawerCount"):
            if field in payload and payload[field] is None:
                raise HTTPException(422, f"{field} 格式錯誤")
        try:
            created = plat.create_parametric(payload)
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from None
        except (ValueError, TypeError):
            raise HTTPException(422, "商品欄位格式錯誤") from None
        if payload.get("render"):
            r_out = plat.render_parametric(created["spec"]["productId"], tenant_id=payload["tenantId"])
            created["render"] = {"job": r_out.get("job"), "preview": (r_out.get("job") or {}).get("output")}
        return created

    @app.post("/api/parametric/products/{product_id}/resize")
    def resize_parametric(product_id: str, payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        plat = get_platform()
        try:
            resized = plat.resize_parametric(product_id, tenant_id=require_tenant(x_tenant_id, payload), **{k: v for k, v in payload.items() if k in {"width", "height", "depth"}})
        except (KeyError, PermissionError):
            raise HTTPException(404, "找不到參數化商品") from None
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from None
        except (ValueError, TypeError):
            raise HTTPException(422, "尺寸欄位格式錯誤") from None
        if payload.get("render", True):
            r_out = plat.render_parametric(resized["spec"]["productId"], tenant_id=resized["spec"]["tenantId"])
            resized["render"] = {"job": r_out.get("job"), "preview": (r_out.get("job") or {}).get("output")}
        return resized

    @app.post("/api/parametric/products/{product_id}/variants")
    def variants(product_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        return get_platform().rd.run(
            tenant_id=tid,
            text=body.get("text") or f"variants for {product_id}",
            variant_count=bounded_count(body.get("count"), 12),
        )

    @app.post("/api/render/preview")
    def preview(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        payload["tenantId"] = tid
        try:
            return get_platform().preview(payload)
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from exc

    @app.post("/api/render/final")
    def final_render(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        payload["tenantId"] = tid
        try:
            return get_platform().final_render(payload)
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from exc

    @app.post("/api/product-rd/generate")
    def product_rd(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        plat = get_platform()
        try:
            text = validate_rd_text(payload.get("text"))
            variant_count = validate_rd_variant_count(payload.get("variantCount"))
            idem = validate_optional_idempotency_key(payload.get("idempotencyKey"))
            return plat.product_rd(
                tenant_id=tid,
                text=text,
                variant_count=variant_count,
                idempotency_key=idem,
                render_base=True,
            )
        except ProductRDIdempotencyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except (TypeError, OverflowError):
            raise HTTPException(422, "商品欄位格式錯誤") from None

    @app.get("/api/product-rd/results")
    def list_product_rd_results(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        try:
            return get_platform().list_product_rd_results(
                tenant_id=tid,
                offset=offset,
                limit=limit,
                cursor=cursor,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/api/product-rd/results/{result_id}")
    def read_product_rd_result(
        result_id: str,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        try:
            return get_platform().get_product_rd_result(result_id, tenant_id=tid)
        except KeyError:
            raise HTTPException(404, "找不到研發方案") from None

    @app.post("/api/product-rd/results/{result_id}/approve")
    def approve_product_rd_result(
        result_id: str,
        payload: dict[str, Any] | None = None,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        plat = get_platform()
        if not plat.rd_store.exists(tid, result_id):
            raise HTTPException(404, "找不到研發方案")
        try:
            actor = validate_rd_actor(body.get("actor"), default="human")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        try:
            return plat.approve_product_rd(
                result_id,
                tenant_id=tid,
                actor=actor,
                confirm=body.get("confirm"),
            )
        except KeyError:
            raise HTTPException(404, "找不到研發方案") from None
        except PermissionError as exc:
            raise HTTPException(422, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/e2e/smoke")
    def e2e_smoke() -> dict[str, Any]:
        platform = get_platform()
        result = platform.real_smoke_test()
        if platform.mock_blender:
            return {**result, "discoverySource": "MOCK", "usedMock": True, "realBlender": False}
        return result

    @app.get("/api/factory/product-types")
    def factory_types() -> dict[str, Any]:
        return {"items": get_platform().factory.types.list()}

    @app.post("/api/factory/spaces")
    def factory_space(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        payload["tenantId"] = tid
        _dimensions(payload)
        try:
            return get_platform().factory.create_space(payload).model_dump(mode="json")
        except (ValidationError, ValueError, TypeError, KeyError):
            raise HTTPException(422, "空間欄位格式錯誤") from None

    @app.post("/api/factory/run")
    def factory_run(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)  # body tenantId may not override the header
        space = payload.get("space")
        if space is not None:
            _dimensions(space)
            if space and not space.get("walls") and not (space.get("width") and space.get("depth")):
                raise HTTPException(422, "空間需要寬度與深度或牆面")
        types = payload.get("productTypes")
        choices = get_platform().factory.types.list()
        if types is not None:
            if not isinstance(types, list):
                raise HTTPException(422, f"productTypes 可用值: {', '.join(sorted(choices))}")
            for item in types:
                _choice(item, choices, "productTypes")
        try:
            return get_platform().furniture_factory_run(
                tenant_id=tid, space=space, wall_name=payload.get("wallName") or "N",
                product_types=types, text=payload.get("text"), render=bool(payload.get("render")),
            )
        except (ValidationError, ValueError, TypeError, KeyError):
            raise HTTPException(422, "工廠欄位格式錯誤") from None

    def _quote_run(quote_id: str, tid: str) -> str:
        """runId of the factory run that produced this quote for this tenant; 404 otherwise.

        Another tenant's quote answers 404 (not 403) so quote ids do not leak across tenants.
        """
        for run_id, run in get_platform().factory.runs.items():
            if (run.get("quote") or {}).get("quoteId") == quote_id and run.get("tenantId") == tid:
                return run_id
        raise HTTPException(404, quote_id)

    @app.get("/api/factory/quotes/{quote_id}")
    def factory_quote(quote_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        _quote_run(quote_id, tenant(x_tenant_id))
        rec = get_platform().factory.quotes.get(quote_id)
        if not rec:
            raise HTTPException(404, quote_id)
        return rec

    @app.post("/api/factory/quotes/{quote_id}/approve")
    def factory_quote_approve(quote_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        run_id = _quote_run(quote_id, tid)
        try:
            return get_platform().factory.approve(run_id, actor=str((payload or {}).get("actor") or "human"))
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/factory/products/{product_id}/revise")
    def factory_revise(product_id: str, payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        try:
            return get_platform().factory.revise_cabinet_changes(product_id, tid, {k: v for k, v in payload.items() if k != "tenantId"})
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (KeyError, PermissionError) as exc:
            # unknown product or another tenant's product: same 404, no cross-tenant probing
            raise HTTPException(404, product_id) from exc

    @app.get("/api/kd/product-types")
    def kd_types() -> dict[str, Any]:
        from fox3d.kd import FLATPACK_PRODUCT_TYPES

        return {"items": list(FLATPACK_PRODUCT_TYPES)}

    @app.post("/api/kd/skus")
    def kd_sku(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        try:
            return get_platform().kd.build_sku(tenant_id=tid, kind=str(payload.get("kind") or "BEDSIDE_CABINET"), render=bool(payload.get("render")), **{k: v for k, v in payload.items() if k not in {"tenantId", "kind", "render"}})
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from None
        except (ValueError, TypeError):
            raise HTTPException(422, "商品尺寸欄位格式錯誤") from None

    @app.post("/api/kd/catalog")
    def kd_catalog(payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        plat = get_platform()
        max_count = int(plat.kd.max_unapproved_per_tenant)
        if max_count < 1:
            raise HTTPException(422, "目前未開放未核准 KD 候選保留上限")
        count = bounded_count(body.get("count"), min(24, max_count), max_value=max_count)
        try:
            return plat.kd.generate_candidates(tenant_id=tid, count=count, render=bool(body.get("render")))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/api/kd/readiness")
    def kd_readiness() -> dict[str, Any]:
        return get_platform().kd.readiness()

    @app.get("/api/materials/catalog")
    def materials_catalog() -> dict[str, Any]:
        from fox3d.acrylic import ACRYLIC_SHEETS
        from fox3d.manufacturing import SheetMaterialRegistry
        from fox3d.packaging import PAPERBOARD_SHEETS

        return {
            "sheets": SheetMaterialRegistry().list(),
            "acrylic": list(ACRYLIC_SHEETS),
            "paperboard": list(PAPERBOARD_SHEETS),
            "costSource": "CONFIG",
        }

    @app.get("/api/materials")
    def materials(
        request: Request,
        x_tenant_id: str | None = Header(default=None),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        rows = get_platform().lots.list(tenant_id=tid)
        total = len(rows)
        if "offset" not in request.query_params and "limit" not in request.query_params:
            return {**materials_catalog(), "lots": rows, "total": total, "offset": 0, "limit": total}
        page = rows[offset : offset + limit]
        return {**materials_catalog(), "lots": page, "total": total, "offset": offset, "limit": limit}

    @app.post("/api/materials/lots")
    def create_lot(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        if str(payload.get("allocationPolicy") or "") == "FIXTURE_AUTO_SEED":
            raise HTTPException(403, "FIXTURE_AUTO_SEED is not available on the production/manual API")
        # This endpoint has always preferred sheetCount over quantity and costPerSheet over
        # unitCost, the reverse of import_receipt. Swap the aliases for the shared validators,
        # then forward only the fields this endpoint has always accepted.
        row = {
            **payload,
            "quantity": payload.get("sheetCount"),
            "sheetCount": payload.get("quantity"),
            "unitCost": payload.get("costPerSheet"),
            "costPerSheet": payload.get("unitCost"),
        }
        qty = _require_receipt_quantity(row)
        _require_manual_source(row)
        _validate_receipt_numbers(row)
        raw_idem = payload.get("idempotencyKey")
        if raw_idem is not None and (not isinstance(raw_idem, str) or len(raw_idem) > 200):
            raise HTTPException(422, "idempotencyKey 格式錯誤")
        idem = raw_idem.strip() if isinstance(raw_idem, str) and raw_idem.strip() else None
        try:
            return get_platform().pilot.receiving.import_receipt(
                {
                    "material": str(row.get("material") or "WOOD_WHITE"),
                    "thickness": float(row.get("thickness") or 18),
                    "quantity": qty,
                    "supplierLot": row.get("supplierLot"),
                    "supplierId": row.get("supplierId"),
                    "unitCost": row.get("unitCost") or row.get("costPerSheet"),
                },
                tenant_id=tid,
                actor=str(payload.get("actor") or "api"),
                source=str(payload.get("source") or "MANUAL"),
                idempotency_key=idem,
            )
        except PilotException:
            raise
        except PermissionError as exc:
            _raise_permission(exc)

    @app.get("/api/remnants")
    def remnants(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        return get_platform().remnants.snapshot(tenant_id=tid)

    @app.post("/api/remnants/{remnant_id}/reserve")
    def remnant_reserve(remnant_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        remnants_inv = get_platform().remnants
        with remnants_inv._transaction(tenant_id=tid):
            rec = remnants_inv.items.get(remnant_id)
            if rec is None or remnants_inv._owner(rec) != tid:
                raise HTTPException(404, "找不到餘料")
            by, version, lease_seconds, idem = _validate_remnant_reserve(body)
            try:
                return remnants_inv.reserve(
                    remnant_id,
                    by=by,
                    version=version,
                    lease_seconds=lease_seconds,
                    tenant_id=tid,
                    idempotency_key=idem,
                )
            except KeyError as exc:
                raise HTTPException(404, "找不到餘料") from exc
            except PermissionError as exc:
                if str(exc).startswith("tenant isolation"):
                    raise HTTPException(404, "找不到餘料") from exc
                raise HTTPException(409, str(exc)) from exc

    @app.post("/api/nesting/benchmarks")
    def nesting_benchmarks(payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        from fox3d.nesting_v3 import run_benchmark

        body = payload or {}
        plat = get_platform()
        tid = require_tenant(x_tenant_id, body)
        result = run_benchmark(plat, tenant_id=tid)
        return plat.physical.record_benchmark(result, tenant_id=tid)

    @app.get("/api/kd/candidates")
    def list_kd_candidates(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        items = get_platform().kd.list_candidates(tenant_id=tid)
        return {"items": items, "candidates": items}

    @app.post("/api/kd/candidates")
    def kd_candidates(payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        return get_platform().physical.kd_optimized_board(tenant_id=tid, count=bounded_count(body.get("count"), 10))

    @app.get("/api/retail/fixtures")
    def list_retail_fixtures(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        items = get_platform().physical.retail.list(tenant_id=tid)
        return {"items": items, "fixtures": items}

    @app.post("/api/retail/fixtures")
    def retail_fixtures(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        from fox3d.retail_fixture import FIXTURE_FAMILIES

        _choice(payload.get("family", "COUNTER_DISPLAY"), FIXTURE_FAMILIES, "family")
        if "product" in payload:
            _dimensions(payload["product"])
        try:
            return get_platform().physical.retail.build(
                tenant_id=tid,
                family=str(payload.get("family") or "COUNTER_DISPLAY"),
                product=payload.get("product"),
                facing=bounded_count(payload.get("facing"), 2, "facing"),
                render=bool(payload.get("render")),
            )
        except ValidationError as exc:
            raise HTTPException(422, _validation_detail(exc)) from None
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, "展示架欄位格式錯誤") from None

    @app.get("/api/packaging/structures")
    def list_packaging_structures(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        items = get_platform().physical.packaging.list(tenant_id=tid)
        return {"items": items, "structures": items}

    @app.post("/api/packaging/structures")
    def packaging_structures(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        from fox3d.packaging import BOX_FAMILIES

        family = payload.get("family", "RSC_CARTON")
        _choice(family, BOX_FAMILIES, "family")
        dims = payload.get("productDims", payload.get("dimensions", {"width": 120, "height": 80, "depth": 40}))
        _dimensions(dims)
        try:
            return get_platform().physical.packaging.build(tenant_id=tid, family=family, product_dims=dims, render=bool(payload.get("render")))
        except (ValidationError, ValueError, TypeError, KeyError):
            raise HTTPException(422, "包裝欄位格式錯誤") from None

    @app.get("/api/acrylic/products")
    def list_acrylic_products(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        items = get_platform().physical.acrylic.list(tenant_id=tid)
        return {"items": items, "products": items}

    @app.post("/api/acrylic/products")
    def acrylic_products(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        from fox3d.acrylic import ACRYLIC_FAMILIES, ACRYLIC_SHEETS

        tid = require_tenant(x_tenant_id, payload)
        kind = payload.get("kind", "MENU_STAND")
        sheet = payload.get("sheetSku", "ACR_CLEAR_5")
        _choice(kind, ACRYLIC_FAMILIES, "kind")
        _choice(sheet, ACRYLIC_SHEETS, "sheetSku")
        _dimensions(payload)
        try:
            return get_platform().physical.acrylic.build(tenant_id=tid, kind=kind, sheet_sku=sheet, render=bool(payload.get("render")))
        except (ValidationError, ValueError, TypeError, KeyError):
            raise HTTPException(422, "壓克力欄位格式錯誤") from None

    @app.post("/api/physical-os/approve")
    def physical_approve(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        entity_id = _entity_id(payload.get("entityId", payload.get("productId")))
        raw_actor = payload.get("actor")
        if raw_actor is not None and (not isinstance(raw_actor, str) or not raw_actor.strip()):
            raise HTTPException(422, "actor 格式錯誤")
        actor = raw_actor.strip() if isinstance(raw_actor, str) and raw_actor.strip() else "human"
        raw_kind = payload.get("kind")
        if raw_kind is not None and not isinstance(raw_kind, str):
            raise HTTPException(422, "kind 格式錯誤")
        kind = raw_kind.strip() if isinstance(raw_kind, str) and raw_kind.strip() else "product"
        physical = get_platform().physical
        try:
            return physical.approve(
                tenant_id=tid,
                entity_id=entity_id,
                actor=actor,
                kind=kind,
                entity=payload.get("entity") if isinstance(payload.get("entity"), dict) else None,
            )
        except KeyError as exc:
            raise HTTPException(404, "找不到商品") from exc

    @app.get("/api/physical-os/families")
    def physical_families() -> dict[str, Any]:
        reg = get_platform().physical.families
        return {"items": [reg.get(name) for name in reg.list()]}

    @app.get("/api/physical-os/readiness")
    def physical_readiness() -> dict[str, Any]:
        return (platform or get_platform()).physical.readiness()

    @app.get("/api/readiness")
    def scoped_ready() -> dict[str, Any]:
        from fox3d.readiness import scoped_readiness

        report = (platform or get_platform()).pilot.logistics.inspect_tenantless_carrier_quotes()
        tenantless_count = int(report.get("tenantlessCount") or 0)
        return scoped_readiness(evidence={"tenantlessCarrierQuotes": tenantless_count})

    @app.post("/api/evidence/verify")
    def evidence_verify(payload: dict[str, Any]) -> dict[str, Any]:
        from fox3d.evidence import verify_bundle

        return verify_bundle(payload.get("bundle") or payload)

    @app.post("/api/release/advance")
    def release_advance(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        entity_id = _entity_id(payload.get("entityId"))
        raw_actor = payload.get("actor")
        if raw_actor is not None and (not isinstance(raw_actor, str) or not raw_actor.strip()):
            raise HTTPException(422, "actor 格式錯誤")
        actor = raw_actor.strip() if isinstance(raw_actor, str) and raw_actor.strip() else "human"
        raw_target = payload.get("target")
        if raw_target is not None and (not isinstance(raw_target, str) or not raw_target.strip()):
            raise HTTPException(422, "target 格式錯誤")
        target = raw_target.strip() if isinstance(raw_target, str) and raw_target.strip() else "WAITING_APPROVAL"
        raw_entity = payload.get("entity")
        if raw_entity is not None and not isinstance(raw_entity, dict):
            raise HTTPException(422, "entity 必須是物件")
        if isinstance(raw_entity, dict):
            raw_spec = raw_entity.get("spec")
            ent_tid = raw_entity.get("tenantId") or (raw_spec.get("tenantId") if isinstance(raw_spec, dict) else None)
            if ent_tid not in (None, "", tid):
                raise HTTPException(404, "找不到商品")
        raw_ev_ok = payload.get("evidenceOk")
        if raw_ev_ok is not None and not isinstance(raw_ev_ok, bool):
            raise HTTPException(422, "evidenceOk 必須是布林值")
        plat = get_platform()
        if plat.physical.is_foreign_entity(entity_id, tenant_id=tid):
            raise HTTPException(404, "找不到商品")
        if "entity" in payload and raw_entity is not None:
            entity_obj = raw_entity
        else:
            found = plat.physical.find_entity(entity_id, tenant_id=tid)
            plat.release._sync_tenant(tid)
            prior = plat.release.approvals.get((tid, entity_id))
            if found is not None:
                entity_obj = dict(found)
                if prior and (prior.get("hashes") or {}).get("evidenceHash") and not entity_obj.get("evidenceHash"):
                    ev_hash = prior["hashes"]["evidenceHash"]
                    entity_obj["evidenceHash"] = ev_hash
                    entity_obj["lineage"] = {**(entity_obj.get("lineage") or {}), "evidenceHash": ev_hash}
            elif prior and prior.get("hashes"):
                entity_obj = {
                    "engineeringHash": prior["hashes"].get("engineeringHash"),
                    "evidenceHash": prior["hashes"].get("evidenceHash"),
                    "lineage": dict(prior["hashes"]),
                }
            else:
                entity_obj = {}
        try:
            advanced = plat.release.advance(
                entity_id,
                tenant_id=tid,
                target=target,
                actor=actor,
                entity=entity_obj,
                evidence_ok=bool(payload.get("evidenceOk")),
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if entity_id in plat.kd.candidates:
            cand = plat.kd.candidates.get(entity_id)
            if isinstance(cand, dict) and plat.kd._candidate_tenant(cand) == tid and not cand.get("physicalApproved"):
                updated_cand = dict(cand)
                updated_cand["physicalApproved"] = True
                plat.kd.candidates[entity_id] = updated_cand
                plat.kd._mark_or_persist(tid)
        return advanced

    @app.get("/api/release/events")
    def release_events(
        entityId: str | None = Query(default=None),
        limit: int = Query(default=MAX_EVENTS_PER_TENANT, ge=1, le=MAX_EVENTS_PER_TENANT),
        offset: int = Query(default=0, ge=0),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        entity_id = _entity_id(entityId) if entityId is not None else None
        plat = get_platform()
        try:
            page = plat.release.events_page(
                tid,
                entity_id=entity_id,
                limit=limit,
                offset=offset,
                include_archived=True,
            )
        except ValueError:
            raise HTTPException(422, "查詢參數超出範圍") from None
        items = page.get("items")
        if isinstance(items, list):
            for ev in items:
                if isinstance(ev, dict):
                    _annotate_release_row(ev)
        page["events"] = page.get("items")
        return page

    @app.get("/api/release/approvals")
    def release_approvals(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        plat = get_platform()
        try:
            records = plat.release.list_approvals(tid)
        except ValueError:
            raise HTTPException(422, "查詢參數超出範圍") from None
        items: list[dict[str, Any]] = []
        for rec in records:
            raw_id = rec.get("entityId")
            entity_id = raw_id if isinstance(raw_id, str) else ""
            entity = plat.physical.find_entity(entity_id, tenant_id=tid) if entity_id else None
            rec["verificationAvailable"] = isinstance(entity, dict)
            rec["stale"] = _approval_stale(plat.release, rec, entity if isinstance(entity, dict) else None)
            _annotate_release_row(rec)
            items.append(rec)
        return {"items": items, "total": len(items), "tenantId": tid}

    @app.post("/api/commerce/import")
    def commerce_import(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        plat = get_platform()
        kind = str(payload.get("kind") or "material")
        if kind not in {"material", "hardware", "packaging", "logistics", "fx"}:
            raise HTTPException(422, "未知的 provider kind")
        store = getattr(plat.providers, kind)
        source = str(payload.get("source") or "MANUAL")
        rows = _stamp_snapshot_tenant(payload.get("rows", []), tid)
        try:
            return {"items": plat.providers.import_rows(store, rows, source=source), "liveProviderReady": False}
        except (ProviderDisconnectedError, ImportValidationError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/commerce/snapshots")
    def commerce_snapshots(
        at: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=_MAX_COMMERCE_SNAPSHOT_PAGE),
        offset: int = Query(default=0, ge=0),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        moment = _snapshot_at(at)
        plat = get_platform()
        visible: list[dict[str, Any]] = []
        for kind in _SNAPSHOT_KINDS:
            store = getattr(plat.providers, kind)
            for row in store.active(at=moment):
                if not isinstance(row, dict) or row.get("tenantId") != tid:
                    continue
                visible.append(dict(row))
        visible.sort(
            key=lambda row: (
                str(row.get("kind") or ""),
                str(row.get("snapshotId") or ""),
                str(row.get("importedAt") or ""),
            )
        )
        total = len(visible)
        page = visible[offset : offset + limit]
        return {
            "items": page,
            "total": total,
            "limit": limit,
            "offset": offset,
            "hasMore": offset + len(page) < total,
            "at": moment,
        }

    @app.post("/api/safety/evaluate")
    def safety_eval(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        _ = tenant(x_tenant_id)
        from fox3d.safety import evaluate_product

        return evaluate_product(str(payload.get("kind") or "KD"), payload.get("record") or payload)

    @app.get("/api/kpi")
    def kpi() -> dict[str, Any]:
        from fox3d.rdloop import kpi_read_model

        return kpi_read_model(get_platform())

    @app.get("/api/pilot/console")
    def pilot_console(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return get_platform().pilot.console(tenant_id=require_tenant(x_tenant_id))

    @app.get("/api/pilot/work-orders")
    def pilot_work_orders(
        request: Request,
        x_tenant_id: str | None = Header(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=100),
    ) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        pilot = get_platform().pilot
        with pilot.workorders._lock:
            orders = [dict(wo) for wo in pilot.workorders.orders.values() if wo.get("tenantId") == tid]
        enriched = [
            {
                **wo,
                "qcHold": wo.get("state") == "QC_HOLD",
                "qcOk": pilot.qc.required_final_ok(
                    wo["workOrderId"],
                    str(wo.get("productFamily") or "KD_FURNITURE"),
                    tenant_id=tid,
                )["ok"],
            }
            for wo in orders
        ]
        total = len(enriched)
        if "offset" not in request.query_params and "limit" not in request.query_params:
            return {"items": enriched, "total": total, "offset": 0, "limit": total, "liveMachineControl": False}
        items = enriched[offset : offset + limit]
        return {"items": items, "total": total, "offset": offset, "limit": limit, "liveMachineControl": False}

    @app.get("/api/pilot/batches/board")
    def pilot_batch_board(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        return get_platform().pilot_batch.decision_board(tenant_id=tid)

    @app.post("/api/pilot/work-orders/{work_order_id}/reserve")
    def pilot_reserve(work_order_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        if str(body.get("allocationPolicy") or "") == "FIXTURE_AUTO_SEED":
            raise HTTPException(403, "FIXTURE_AUTO_SEED is not available on the production/manual API")
        try:
            return get_platform().pilot.workorders.reserve_materials(
                work_order_id,
                actor=str(body.get("actor") or "api"),
                tenant_id=tid,
                allocation_policy="STRICT_STOCK",
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            if str(exc).startswith("tenant isolation"):
                raise HTTPException(403, str(exc)) from exc
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/pilot/workorders/{work_order_id}/reject")
    def pilot_workorder_reject(work_order_id: str, payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        _require_text_fields(payload, ("reason",))
        service = get_platform().pilot.workorders
        try:
            service._require(work_order_id, tenant_id=tid)
            return service.reject(work_order_id, actor=str(payload.get("actor") or "api"), reason=str(payload["reason"]))
        except KeyError as exc:
            raise HTTPException(404, "resource not found") from exc
        except PermissionError as exc:
            raise HTTPException(403 if str(exc).startswith("tenant isolation") else 409, str(exc)) from exc

    @app.post("/api/pilot/receipts")
    def pilot_receipt(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        _require_receipt_quantity(payload)
        _require_manual_source(payload)
        _validate_receipt_numbers(payload)
        try:
            return get_platform().pilot.receiving.import_receipt(
                payload,
                tenant_id=tid,
                actor=str(payload.get("actor") or "api"),
                source=str(payload.get("source") or "IMPORTED"),
                idempotency_key=payload.get("idempotencyKey"),
            )
        except SemanticKeyConflictError as exc:
            raise HTTPException(409, "idempotency conflict") from exc
        except PilotException:
            raise
        except PermissionError as exc:
            _raise_permission(exc)

    @app.post("/api/pilot/purchase-requests")
    def pilot_pr(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        qty = _require_purchase_quantity(payload)
        return get_platform().pilot.receiving.draft_purchase_request(
            tenant_id=tid,
            material=str(payload.get("material") or "PB_18_WHITE"),
            quantity=qty,
            actor=str(payload.get("actor") or "api"),
            shortage=payload.get("shortage"),
            release_hash=payload.get("releaseHash"),
        )

    @app.get("/api/pilot/health")
    def pilot_health_ep(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return get_platform().pilot.health(tenant_id=require_tenant(x_tenant_id))

    @app.get("/api/pilot/operator")
    def pilot_operator(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return get_platform().pilot.operator(tenant_id=require_tenant(x_tenant_id))

    @app.post("/api/pilot/scan")
    def pilot_scan(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        try:
            return get_platform().pilot.scan(str(payload.get("token") or ""), tenant_id=tid)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/api/pilot/stations")
    def pilot_stations_list(
        request: Request,
        x_tenant_id: str | None = Header(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        rows = get_platform().pilot.stations.list(tenant_id=tid)
        return _paginate_list(request, rows, offset=offset, limit=limit)

    @app.put("/api/pilot/stations/{station_id}/status")
    def pilot_station_status(
        station_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_json_object(payload)
        tid = require_tenant(x_tenant_id, body)
        raw_status = body.get("status")
        if not isinstance(raw_status, str) or raw_status not in ADMIN_STATION_STATUSES:
            raise HTTPException(422, f"status 可用值: {', '.join(sorted(ADMIN_STATION_STATUSES))}")
        actor = (_optional_str_field(body, "actor") or "").strip() or "api"
        note = _optional_str_field(body, "note")
        t_key = _optional_key_field(body, "transitionId")
        i_key = _optional_key_field(body, "idempotencyKey")
        if t_key and i_key and t_key != i_key:
            raise HTTPException(422, "transitionId 與 idempotencyKey 不一致")
        try:
            return get_platform().pilot.stations.set_status(
                station_id,
                tenant_id=tid,
                status=raw_status,
                actor=actor,
                note=note,
                transition_id=t_key or i_key,
            )
        except KeyError as exc:
            raise HTTPException(404, "resource not found") from exc
        except PermissionError as exc:
            if _pilot_tenant_missing(exc):
                raise HTTPException(404, "resource not found") from exc
            _raise_permission(exc)
        except SemanticKeyConflictError as exc:
            raise HTTPException(409, "idempotency conflict") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except JournalCommitError as exc:
            raise HTTPException(503, "稽核日誌寫入失敗，請重試") from exc

    @app.get("/api/pilot/leases")
    def pilot_leases_list(
        request: Request,
        x_tenant_id: str | None = Header(default=None),
        stationId: str | None = None,
        status: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        rows = get_platform().pilot.dispatcher.list_leases(
            tenant_id=tid,
            station_id=stationId,
            status=status,
        )
        return _paginate_list(request, rows, offset=offset, limit=limit, extra={"liveMachineControl": False})

    @app.post("/api/pilot/stations")
    def pilot_station(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        _require_station_capabilities(payload)
        try:
            return get_platform().pilot.stations.register(
                tenant_id=tid,
                capabilities=list(payload.get("capabilities") or []),
                station_id=payload.get("stationId"),
                actor=str(payload.get("actor") or "api"),
                status=str(payload.get("status") or "ONLINE"),
            )
        except PilotException:
            raise
        except PermissionError as exc:
            _raise_permission(exc)

    @app.post("/api/pilot/stations/{station_id}/heartbeat")
    def pilot_station_hb(station_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        try:
            return get_platform().pilot.stations.heartbeat(station_id, tenant_id=tid, actor=body.get("actor"))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/pilot/dispatch")
    def pilot_dispatch(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        _require_text_fields(payload, _DISPATCH_FIELDS)
        try:
            return get_platform().pilot.dispatcher.dispatch(
                tenant_id=tid,
                work_order_id=str(payload["workOrderId"]),
                operation=str(payload["operation"]),
                station_id=str(payload["stationId"]),
                actor=str(payload.get("actor") or "api"),
            )
        except KeyError as exc:
            raise HTTPException(404, "resource not found") from exc
        except ValueError as exc:
            raise HTTPException(422, "invalid operation") from exc
        except PilotException as exc:
            raise HTTPException(409, exc.code) from exc
        except PermissionError as exc:
            raise HTTPException(403 if str(exc).startswith("tenant isolation") else 409, str(exc)) from exc

    @app.post("/api/pilot/leases/{lease_id}/ack")
    def pilot_ack(lease_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        try:
            return get_platform().pilot.dispatcher.ack(lease_id, tenant_id=tid, actor=str(body.get("actor") or "api"))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/pilot/leases/{lease_id}/start")
    def pilot_start(lease_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        try:
            return get_platform().pilot.dispatcher.start(lease_id, tenant_id=tid, actor=str(body.get("actor") or "api"))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/pilot/leases/{lease_id}/complete")
    def pilot_lease_complete(lease_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        dispatcher = get_platform().pilot.dispatcher
        try:
            dispatcher._lease(lease_id, tid)
            require_confirm(body, action="complete_operation")
            return dispatcher.complete(lease_id, tenant_id=tid, actor=str(body.get("actor") or "api"), confirm=True)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/api/pilot/exceptions")
    def pilot_exceptions(
        request: Request,
        x_tenant_id: str | None = Header(default=None),
        status: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        rows = get_platform().pilot.inbox.list(tenant_id=tid, status=status)
        return _paginate_list(request, rows, offset=offset, limit=limit)

    @app.post("/api/pilot/exceptions/{exception_id}/ack")
    def pilot_exception_ack(
        exception_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_json_object(payload, allow_none=True)
        tid = require_tenant(x_tenant_id, body)
        actor = (_optional_str_field(body, "actor") or "").strip() or "api"
        note = _optional_str_field(body, "note")
        try:
            return get_platform().pilot.inbox.acknowledge(
                exception_id,
                tenant_id=tid,
                actor=actor,
                note=note,
            )
        except KeyError as exc:
            raise HTTPException(404, "resource not found") from exc
        except ExceptionStateError as exc:
            raise HTTPException(409, str(exc)) from exc
        except PermissionError as exc:
            if _pilot_tenant_missing(exc):
                raise HTTPException(404, "resource not found") from exc
            _raise_permission(exc)
        except SemanticKeyConflictError as exc:
            raise HTTPException(409, "idempotency conflict") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except JournalCommitError as exc:
            raise HTTPException(503, "稽核日誌寫入失敗，請重試") from exc

    @app.post("/api/pilot/exceptions/{exception_id}/resolve")
    def pilot_exception_resolve(
        exception_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_json_object(payload, allow_none=True)
        tid = require_tenant(x_tenant_id, body)
        actor = (_optional_str_field(body, "actor") or "").strip() or "api"
        resolution = _optional_str_field(body, "resolution")
        try:
            return get_platform().pilot.inbox.resolve(
                exception_id,
                tenant_id=tid,
                actor=actor,
                resolution=resolution,
            )
        except KeyError as exc:
            raise HTTPException(404, "resource not found") from exc
        except PermissionError as exc:
            if _pilot_tenant_missing(exc):
                raise HTTPException(404, "resource not found") from exc
            _raise_permission(exc)
        except SemanticKeyConflictError as exc:
            raise HTTPException(409, "idempotency conflict") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except JournalCommitError as exc:
            raise HTTPException(503, "稽核日誌寫入失敗，請重試") from exc

    @app.post("/api/pilot/import")
    def pilot_import(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        _require_import_contract(payload)
        try:
            return get_platform().pilot.contracts.import_bundle(
                payload,
                tenant_id=tid,
                actor=str(payload.get("actor") or "api"),
                source=str(payload.get("source") or "IMPORTED"),
                idempotency_key=payload.get("idempotencyKey"),
            )
        except PilotException:
            raise
        except PermissionError as exc:
            _raise_permission(exc)

    @app.get("/api/pilot/export")
    def pilot_export(
        releaseHash: str | None = None,
        sinceSeq: str | None = None,
        since_seq: str | None = None,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        raw_seq: Any = since_seq if since_seq is not None else (sinceSeq if sinceSeq is not None else 0)
        try:
            return get_platform().pilot.contracts.export_bundle(
                tenant_id=tid, release_hash=releaseHash, since_seq=raw_seq
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/pilot/work-orders/{work_order_id}/consume")
    def pilot_consume(work_order_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        wo = get_platform().pilot.workorders.orders.get(work_order_id)
        if wo is None or wo.get("tenantId") != tid:
            raise HTTPException(404, "找不到工單")
        try:
            return get_platform().pilot.confirm_action(
                tenant_id=tid,
                action="consume",
                work_order_id=work_order_id,
                actor=str(body.get("actor") or "api"),
                payload=body,
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/pilot/work-orders/{work_order_id}/complete")
    def pilot_complete_wo(work_order_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        wo = get_platform().pilot.workorders.orders.get(work_order_id)
        if wo is None or wo.get("tenantId") != tid:
            raise HTTPException(404, "找不到工單")
        try:
            return get_platform().pilot.confirm_action(
                tenant_id=tid,
                action="complete_wo",
                work_order_id=work_order_id,
                actor=str(body.get("actor") or "api"),
                payload=body,
            )
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/pilot/scan-token/{kind}/{object_id}")
    def pilot_token(kind: str, object_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        _ = require_tenant(x_tenant_id)
        try:
            return {"token": make_token(kind, object_id), "barcodeHardware": "PARTIAL"}
        except PermissionError as exc:
            _raise_permission(exc)

    @app.get("/admin", response_class=HTMLResponse)
    def admin() -> str:
        return render_admin(get_platform())

    @app.get("/admin/asset-viewer", response_class=HTMLResponse)
    def admin_asset_viewer() -> HTMLResponse:
        return HTMLResponse(
            (Path(__file__).with_name("static") / "asset-viewer.html").read_text(encoding="utf-8"),
            headers={"Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src blob:; base-uri 'none'; frame-ancestors 'none'",
                     "Referrer-Policy": "no-referrer"},
        )

    @app.get("/admin/features", response_class=HTMLResponse)
    def admin_features() -> HTMLResponse:
        # One searchable directory of every page and API group (fox3d/features.py).
        return HTMLResponse(
            (Path(__file__).with_name("static") / "features.html").read_text(encoding="utf-8"),
            headers={"Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"},
        )

    @app.get("/api/admin/features")
    def admin_features_index(request: Request) -> dict[str, Any]:
        return feature_index(list(request.app.routes))

    platform_provider = lambda: platform if platform is not None else get_platform()
    app.include_router(recipe_router(platform_provider))
    app.include_router(pilot_packing_router(platform_provider))
    app.include_router(pilot_batch_router(platform_provider))
    app.include_router(pilot_qc_router(platform_provider))
    app.include_router(pilot_shipping_router(platform_provider))
    app.include_router(cyclecount_router(platform_provider))
    app.include_router(materials_lot_ops_router(platform_provider))
    for page in page_routers(lambda: platform if platform is not None else get_platform()):
        app.include_router(page)
    return app


def main() -> None:
    import uvicorn

    host = (os.environ.get("FOX3D_HOST") or "127.0.0.1").strip()
    port = int(os.environ.get("FOX3D_PORT") or 8788)
    os.environ.setdefault("FOX3D_BIND_HOST", host)
    os.environ.setdefault("FOX3D_BIND_PORT", str(port))
    print(f"Autonomous 3D Admin: http://127.0.0.1:{port}/admin")
    print(f"Health:               http://127.0.0.1:{port}/health")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
