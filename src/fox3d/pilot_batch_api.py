"""Tenant-scoped, read-only pilot batch queries."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from fox3d.infra import validate_tenant_id


def pilot_batch_router(platform_provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/pilot/batches")

    def tenant(value: str | None) -> str:
        try:
            return validate_tenant_id(value or "")
        except ValueError as exc:
            raise HTTPException(400, "X-Tenant-Id 無效") from exc

    def batch(factory: Any, batch_id: str, tid: str) -> dict[str, Any]:
        row = factory.batches.get(batch_id)
        if row is None or row.get("tenantId") != tid:
            raise HTTPException(404, "找不到批次")
        return row

    @router.get("")
    def list_batches(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), state: str | None = None, x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        rows = sorted((b for b in platform_provider().pilot_batch.batches.values() if b.get("tenantId") == tid and (state is None or b.get("state") == state)), key=lambda b: str(b.get("batchId", "")))
        return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit, "liveMachineControl": False, "physicalPilotBatchValidated": False}

    @router.get("/{batch_id}")
    def get_batch(batch_id: str, x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        return {**batch(platform_provider().pilot_batch, batch_id, tenant(x_tenant_id)), "liveMachineControl": False}

    @router.get("/{batch_id}/units")
    def get_units(batch_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        factory = platform_provider().pilot_batch
        batch(factory, batch_id, tid)
        rows = factory.units_for(batch_id, tenant_id=tid)
        items = []
        for unit in rows[offset:offset + limit]:
            qc = factory.qc.get(unit.get("qcId") or "")
            if qc and (qc.get("tenantId") != tid or qc.get("batchId") != batch_id or qc.get("unitExecutionId") != unit.get("unitExecutionId")):
                qc = None
            items.append({**unit, "qc": qc})
        return {"items": items, "total": len(rows), "offset": offset, "limit": limit, "liveMachineControl": False}

    @router.get("/{batch_id}/readiness")
    def get_readiness(batch_id: str, x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        factory = platform_provider().pilot_batch
        batch(factory, batch_id, tid)
        return factory.readiness_readonly(batch_id, tenant_id=tid)

    @router.get("/{batch_id}/genealogy")
    def get_genealogy(batch_id: str, x_tenant_id: str | None = Header(None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        factory = platform_provider().pilot_batch
        batch(factory, batch_id, tid)
        return {**factory.genealogy(batch_id, tenant_id=tid), "liveMachineControl": False}

    return router
