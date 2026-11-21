"""Tenant-scoped manufacturing releases for human execution."""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query

from fox3d.mfg_release import product_snapshot
from fox3d.operator import require_confirm
from fox3d.pilot_packing_api import _optional_idempotency_key, _require_body_dict, _require_tenant


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise HTTPException(422, f"{field} 必須是非空字串")
    return value.strip()


def _record(service: Any, release_id: str, tenant: str) -> dict[str, Any]:
    rec = service.releases.get(release_id)
    if rec is None or rec.get("tenantId") != tenant:
        raise HTTPException(404, "找不到放行包")
    return rec


def mfg_release_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/pilot/releases')
    def listing(status: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
                x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tenant = _require_tenant(x_tenant_id)
        service = provider().pilot.releases
        with service._lock:
            rows = [copy.deepcopy(r) for r in service.releases.values()
                    if r.get('tenantId') == tenant and (status is None or r.get('status') == status)]
            rows.sort(key=lambda r: (r.get('createdAt', ''), r['releaseId']), reverse=True)
            return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'limit': limit}

    @router.post('/api/pilot/releases')
    def create(payload: Any = Body(None), x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(422, "請求內容須為 JSON 物件")
        body = _require_body_dict(payload)
        tenant = _require_tenant(x_tenant_id, body)
        product_id = _text(body.get('productId'), 'productId')
        key = _optional_idempotency_key(body)
        if key is None:
            raise HTTPException(422, 'idempotencyKey 必填')
        actor = _text(body.get('actor', 'operator'), 'actor')
        platform = provider()
        with platform.kd._lock:
            platform.kd._sync_tenant(tenant)
            product = platform.kd.candidates.get(product_id)
            if product is None or platform.kd._candidate_tenant(product) != tenant:
                product = platform.parametrics.get(product_id)
                if not product or (product.get('spec') or {}).get('tenantId') != tenant:
                    raise HTTPException(404, '找不到商品')
            snap = product_snapshot(copy.deepcopy(product))
        service = platform.pilot.releases
        with service._lock:
            existing_id = service._idem.get(f'{tenant}::rel::{key}')
            if existing_id:
                existing = _record(service, existing_id, tenant)
                if existing.get('productId') != product_id:
                    raise HTTPException(409, 'idempotencyKey 衝突')
                return copy.deepcopy(existing)
            return copy.deepcopy(service.create(snap, tenant_id=tenant, created_by=actor, idempotency_key=key))

    @router.get('/api/pilot/releases/{release_id}/diff/{other_id}')
    def diff(release_id: str, other_id: str, x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tenant = _require_tenant(x_tenant_id)
        service = provider().pilot.releases
        with service._lock:
            return service.diff(_record(service, release_id, tenant), _record(service, other_id, tenant))

    @router.get('/api/pilot/releases/{release_id}/packet')
    def packet(release_id: str, x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tenant = _require_tenant(x_tenant_id)
        service = provider().pilot.releases
        with service._lock:
            _record(service, release_id, tenant)
            return copy.deepcopy(service.packet(release_id))

    @router.get('/api/pilot/releases/{release_id}/verify')
    def verify(release_id: str, x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tenant = _require_tenant(x_tenant_id)
        service = provider().pilot.releases
        with service._lock:
            _record(service, release_id, tenant)
            result = service.verify(release_id)
            result['verification'] = 'VALID' if result['ok'] else 'TAMPERED'
            return result

    @router.get('/api/pilot/releases/{release_id}')
    def detail(release_id: str, x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tenant = _require_tenant(x_tenant_id)
        service = provider().pilot.releases
        with service._lock:
            return copy.deepcopy(_record(service, release_id, tenant))

    @router.post('/api/pilot/releases/{release_id}/{action}')
    def transition(release_id: str, action: str, payload: Any = Body(None),
                   x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(422, "請求內容須為 JSON 物件")
        body = _require_body_dict(payload)
        tenant = _require_tenant(x_tenant_id, body)
        actor = _text(body.get('actor', 'operator'), 'actor')
        if action not in {'validate', 'submit', 'approve', 'release-manual', 'cancel'}:
            raise HTTPException(404, '找不到操作')
        expected = None
        if action == 'approve':
            expected = _text(body.get('expectedReleaseHash'), 'expectedReleaseHash')
            if not isinstance(body.get('confirm'), (bool, str, int)):
                raise HTTPException(422, 'confirm 格式錯誤')
            try:
                require_confirm(body, action='release_approve')
            except PermissionError as exc:
                raise HTTPException(403, '需要人工確認') from exc
        service = provider().pilot.releases
        with service._lock:
            rec = _record(service, release_id, tenant)
            target = {'validate': 'VALIDATED', 'submit': 'WAITING_APPROVAL',
                      'approve': 'APPROVED_FOR_MANUAL_RELEASE', 'release-manual': 'RELEASED_FOR_MANUAL_EXECUTION',
                      'cancel': 'CANCELLED'}[action]
            if rec['status'] == target:
                if action == 'approve' and rec.get('approvedReleaseHash') != expected:
                    raise HTTPException(409, '放行雜湊不符')
                return copy.deepcopy(rec)
            allowed = {'validate': {'DRAFT'}, 'submit': {'VALIDATED'}, 'approve': {'WAITING_APPROVAL'},
                       'release-manual': {'APPROVED_FOR_MANUAL_RELEASE'},
                       'cancel': {'DRAFT', 'VALIDATED', 'WAITING_APPROVAL', 'APPROVED_FOR_MANUAL_RELEASE', 'STALE'}}
            if rec['status'] not in allowed[action]:
                raise HTTPException(409, '目前狀態不允許此操作')
            try:
                if action == 'validate':
                    result = service.validate(release_id)
                elif action == 'submit':
                    result = service.submit_approval(release_id, actor=actor)
                elif action == 'approve':
                    result = service.approve(release_id, actor=actor, expected_release_hash=expected)
                elif action == 'release-manual':
                    result = service.release_for_manual_execution(release_id, actor=actor)
                else:
                    result = service.cancel(release_id, actor=actor)
            except (PermissionError, ValueError) as exc:
                raise HTTPException(409, '無法執行此操作') from exc
            return copy.deepcopy(result)
    return router
