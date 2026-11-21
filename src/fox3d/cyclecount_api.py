"""HTTP routes for manual material cycle counts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn

from fastapi import APIRouter, Header, HTTPException, Query

from fox3d.cyclecount import BOOK_CHANGED_MSG, CycleCountConflict, CycleCountService
from fox3d.infra import validate_tenant_id
from fox3d.operator import require_confirm


def _tenant_header(x_tenant_id: str | None) -> str:
    try:
        return validate_tenant_id(x_tenant_id or "")
    except ValueError as exc:
        raise HTTPException(400, "X-Tenant-Id 無效") from exc


def _non_negative_int(field: str, raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise HTTPException(422, f"{field} 須為非負整數")
    if raw < 0:
        raise HTTPException(422, f"{field} 須為非負整數")
    return raw


def _reason(raw: Any) -> str:
    if not isinstance(raw, str):
        raise HTTPException(422, "reason 格式錯誤")
    text = raw.strip()
    if not (1 <= len(text) <= 200):
        raise HTTPException(422, "reason 長度須為 1–200 字")
    return text


def _idempotency_key(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 200:
        raise HTTPException(422, "idempotencyKey 格式錯誤")
    return raw.strip()


def _map_cyclecount_error(exc: BaseException) -> NoReturn:
    if isinstance(exc, KeyError):
        raise HTTPException(404, "找不到盤點或批次") from exc
    if isinstance(exc, CycleCountConflict):
        raise HTTPException(409, str(exc) or BOOK_CHANGED_MSG) from exc
    if isinstance(exc, PermissionError):
        msg = str(exc)
        if msg.startswith("tenant isolation"):
            raise HTTPException(404, "找不到盤點或批次") from exc
        if "confirm" in msg:
            raise HTTPException(422, msg) from exc
        raise HTTPException(409, msg) from exc
    raise exc


def cyclecount_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    def svc() -> CycleCountService:
        return provider().pilot.cyclecounts

    @router.post("/api/materials/lots/{lot_id}/cycle-counts")
    def create_cycle_count(
        lot_id: str,
        payload: dict[str, Any],
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        counted = _non_negative_int("counted", payload.get("counted"))
        reason = _reason(payload.get("reason"))
        idem = _idempotency_key(payload.get("idempotencyKey"))
        actor = str(payload.get("actor") or "api")
        try:
            provider().lots.get(lot_id, tenant_id=tid)
        except KeyError as exc:
            raise HTTPException(404, "找不到盤點或批次") from exc
        except PermissionError as exc:
            raise HTTPException(404, "找不到盤點或批次") from exc
        try:
            return svc().create(
                tenant_id=tid,
                lot_id=lot_id,
                counted=counted,
                reason=reason,
                actor=actor,
                idempotency_key=idem,
            )
        except (KeyError, PermissionError, CycleCountConflict) as exc:
            _map_cyclecount_error(exc)

    @router.get("/api/materials/cycle-counts")
    def list_cycle_counts(
        x_tenant_id: str | None = Header(default=None),
        status: str | None = Query(default=None),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        return svc().list_for_tenant(tenant_id=tid, status=status, offset=offset, limit=limit)

    @router.post("/api/materials/cycle-counts/{cycle_count_id}/approve")
    def approve_cycle_count(
        cycle_count_id: str,
        payload: dict[str, Any] | None = None,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = payload or {}
        tid = _tenant_header(x_tenant_id)
        actor = str(body.get("actor") or "api")
        try:
            require_confirm(body, action="cycle_count_adjust")
        except PermissionError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            return svc().approve(cycle_count_id, tenant_id=tid, actor=actor, payload=body)
        except (KeyError, PermissionError, CycleCountConflict) as exc:
            _map_cyclecount_error(exc)

    @router.post("/api/materials/cycle-counts/{cycle_count_id}/reject")
    def reject_cycle_count(
        cycle_count_id: str,
        payload: dict[str, Any] | None = None,
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = payload or {}
        tid = _tenant_header(x_tenant_id)
        actor = str(body.get("actor") or "api")
        try:
            return svc().reject(cycle_count_id, tenant_id=tid, actor=actor)
        except (KeyError, PermissionError, CycleCountConflict) as exc:
            _map_cyclecount_error(exc)

    return router