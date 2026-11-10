"""Admin page: 3D render jobs and digital twins."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from fox3d.admin_pages import page_response

FEATURES = {"jobs": "/admin/render", "twins": "/admin/render#twins"}


def router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/render")
    def render_admin_page() -> Any:
        return page_response("render")

    @router.get("/api/pages/render/twins")
    def list_twins(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = (x_tenant_id or "").strip()
        if not tid:
            raise HTTPException(400, "X-Tenant-Id required")
        plat = provider()
        items = [t.model_dump(mode="json") for t in plat.twins.list(tenant_id=tid)]
        return {"items": items}

    return router
