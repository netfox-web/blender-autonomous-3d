"""HTTP routes for material lot detail, quarantine, and remnant release/consume."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn

from fastapi import APIRouter, Header, HTTPException

from fox3d.infra import validate_tenant_id
from fox3d.operator import require_confirm

_QUARANTINE_EVENTS = frozenset({"material.quarantine", "material.release_quarantine"})
_MAX_REMNANT_BY_LEN = 120


def _tenant_header(x_tenant_id: str | None) -> str:
    try:
        return validate_tenant_id(x_tenant_id or "")
    except ValueError as exc:
        raise HTTPException(400, "X-Tenant-Id 無效") from exc


def _reason(raw: Any) -> str:
    if not isinstance(raw, str):
        raise HTTPException(422, "reason 格式錯誤")
    text = raw.strip()
    if not (1 <= len(text) <= 200):
        raise HTTPException(422, "reason 長度須為 1–200 字")
    return text


def _expected_version(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise HTTPException(422, "expectedVersion 必須是正整數")
    return raw


def _idempotency_key(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 200:
        raise HTTPException(422, "idempotencyKey 格式錯誤")
    return raw.strip()


def _remnant_by(raw: Any) -> str:
    if not isinstance(raw, str):
        raise HTTPException(422, "by 必須是非空字串且長度不超過 120")
    by = raw.strip()
    if not by or len(raw) > _MAX_REMNANT_BY_LEN:
        raise HTTPException(422, "by 必須是非空字串且長度不超過 120")
    return by


def _remnant_version(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise HTTPException(422, "version 必須是正整數")
    return raw


def _map_lot_error(exc: BaseException) -> NoReturn:
    if isinstance(exc, KeyError):
        raise HTTPException(404, "找不到批次") from exc
    if isinstance(exc, PermissionError):
        msg = str(exc)
        if msg.startswith("tenant isolation"):
            raise HTTPException(404, "找不到批次") from exc
        if "confirm" in msg:
            raise HTTPException(422, msg) from exc
        if "stale lot version" in msg:
            raise HTTPException(409, msg) from exc
        raise HTTPException(409, msg) from exc
    raise exc


def _map_remnant_error(exc: BaseException) -> NoReturn:
    if isinstance(exc, KeyError):
        raise HTTPException(404, "找不到餘料") from exc
    if isinstance(exc, PermissionError):
        msg = str(exc)
        if msg.startswith("tenant isolation"):
            raise HTTPException(404, "找不到餘料") from exc
        if "stale remnant version" in msg:
            raise HTTPException(409, msg) from exc
        raise HTTPException(409, msg) from exc
    raise exc


def _source_receipt(platform: Any, *, tenant_id: str, lot_id: str) -> dict[str, Any] | None:
    for rec in platform.pilot.receiving.receipts.values():
        if rec.get("tenantId") == tenant_id and rec.get("lotId") == lot_id:
            return dict(rec)
    return None


def _quarantine_history(platform: Any, *, tenant_id: str, lot_id: str) -> list[dict[str, Any]]:
    journal = getattr(platform.lots, "journal", None) or getattr(platform.pilot, "journal", None)
    if journal is None:
        return []
    rows = []
    for ev in journal.list(tenant_id):
        if ev.get("aggregateId") != lot_id:
            continue
        if ev.get("eventType") not in _QUARANTINE_EVENTS:
            continue
        rows.append(
            {
                "eventType": ev.get("eventType"),
                "actor": ev.get("actor"),
                "at": ev.get("createdAt") or ev.get("timestamp"),
                "reason": (ev.get("payload") or {}).get("reason"),
                "eventId": ev.get("eventId"),
            }
        )
    return rows


def materials_lot_ops_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    def plat() -> Any:
        return provider()

    @router.get("/api/materials/lots/{lot_id}")
    def get_material_lot(lot_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        lots = plat().lots
        try:
            rec = lots.get(lot_id, tenant_id=tid)
        except (KeyError, PermissionError) as exc:
            _map_lot_error(exc)
        reservations = [dict(v) for v in (rec.get("reservations") or {}).values()]
        return {
            "lotId": lot_id,
            "lot": rec,
            "quantities": lots.quantities(lot_id, tenant_id=tid),
            "reservations": reservations,
            "sourceReceipt": _source_receipt(plat(), tenant_id=tid, lot_id=lot_id),
            "quarantineHistory": _quarantine_history(plat(), tenant_id=tid, lot_id=lot_id),
            "version": int(rec.get("version") or 1),
        }

    @router.post("/api/materials/lots/{lot_id}/quarantine")
    def quarantine_lot(
        lot_id: str,
        payload: dict[str, Any],
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        reason = _reason(payload.get("reason"))
        actor = str(payload.get("actor") or "api")
        expected = _expected_version(payload.get("expectedVersion"))
        try:
            require_confirm(payload, action="lot_quarantine")
        except PermissionError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            return plat().lots.quarantine(
                lot_id,
                tenant_id=tid,
                actor=actor,
                reason=reason,
                expected_version=expected,
            )
        except (KeyError, PermissionError) as exc:
            _map_lot_error(exc)

    @router.post("/api/materials/lots/{lot_id}/release-quarantine")
    def release_quarantine_lot(
        lot_id: str,
        payload: dict[str, Any],
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        reason = _reason(payload.get("reason"))
        actor = str(payload.get("actor") or "api")
        expected = _expected_version(payload.get("expectedVersion"))
        try:
            require_confirm(payload, action="lot_release_quarantine")
        except PermissionError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            return plat().lots.release_quarantine(
                lot_id,
                tenant_id=tid,
                actor=actor,
                reason=reason,
                expected_version=expected,
            )
        except (KeyError, PermissionError) as exc:
            _map_lot_error(exc)

    @router.post("/api/remnants/{remnant_id}/release-reservation")
    def remnant_release_reservation(
        remnant_id: str,
        payload: dict[str, Any] | None = None,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = payload or {}
        tid = _tenant_header(x_tenant_id)
        by = _remnant_by(body.get("by"))
        version = _remnant_version(body.get("version"))
        remnants_inv = plat().remnants
        with remnants_inv._transaction(tenant_id=tid):
            rec = remnants_inv.items.get(remnant_id)
            if rec is None or remnants_inv._owner(rec) != tid:
                raise HTTPException(404, "找不到餘料")
            try:
                return remnants_inv.release_reservation(
                    remnant_id,
                    by=by,
                    version=version,
                    tenant_id=tid,
                )
            except KeyError as exc:
                raise HTTPException(404, "找不到餘料") from exc
            except PermissionError as exc:
                _map_remnant_error(exc)

    @router.post("/api/remnants/{remnant_id}/consume")
    def remnant_consume(
        remnant_id: str,
        payload: dict[str, Any] | None = None,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = payload or {}
        tid = _tenant_header(x_tenant_id)
        by = _remnant_by(body.get("by"))
        version = _remnant_version(body.get("version"))
        idem = _idempotency_key(body.get("idempotencyKey"))
        raw_lease = body.get("leaseToken")
        lease_token = raw_lease.strip() if isinstance(raw_lease, str) and raw_lease.strip() else None
        remnants_inv = plat().remnants
        with remnants_inv._transaction(tenant_id=tid):
            rec = remnants_inv.items.get(remnant_id)
            if rec is None or remnants_inv._owner(rec) != tid:
                raise HTTPException(404, "找不到餘料")
            try:
                return remnants_inv.consume(
                    remnant_id,
                    by=by,
                    version=version,
                    lease_token=lease_token,
                    tenant_id=tid,
                    idempotency_key=idem,
                )
            except KeyError as exc:
                raise HTTPException(404, "找不到餘料") from exc
            except PermissionError as exc:
                _map_remnant_error(exc)

    return router