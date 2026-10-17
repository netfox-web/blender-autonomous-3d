"""FastAPI router for the E-Commerce Modular Cabinet & 3D Scene Studio workbench."""
from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response

from fox3d.ecommerce_scene_studio import EcommerceSceneStore

STATIC = Path(__file__).with_name("static")
CSP = "default-src 'self'; img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"


def ecommerce_scene_router(provider) -> APIRouter:
    router = APIRouter()
    stores: dict[Path, EcommerceSceneStore] = {}
    lock = RLock()

    def store() -> EcommerceSceneStore:
        plat = provider()
        root = Path(plat.root).resolve()
        with lock:
            if root not in stores:
                stores[root] = EcommerceSceneStore(plat)
            return stores[root]

    def tenant(x_tenant_id: str | None) -> str:
        val = (x_tenant_id or "sonaqueen-home").strip()
        if not val or val == "system" or len(val) > 120:
            raise HTTPException(400, "請提供有效的工作區 X-Tenant-Id")
        return val

    @router.get("/admin/recipes/scenes", response_class=HTMLResponse)
    def scene_studio_page() -> HTMLResponse:
        return HTMLResponse(
            (STATIC / "scene-studio.html").read_text(encoding="utf-8"),
            headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store"},
        )

    @router.get("/api/ecommerce-scenes/overview")
    def overview(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return store().overview(tenant(x_tenant_id))

    @router.post("/api/ecommerce-scenes/preview-plan")
    def preview_plan(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().preview_plan(tenant(x_tenant_id), payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/ecommerce-scenes/scenes", status_code=201)
    def save_scene(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().save_scene(tenant(x_tenant_id), payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.delete("/api/ecommerce-scenes/scenes/{scene_id}")
    def delete_scene(scene_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().delete_scene(tenant(x_tenant_id), scene_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/ecommerce-scenes/batches", status_code=202)
    def start_batch(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().start_matrix_batch(tenant(x_tenant_id), payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/api/ecommerce-scenes/batches/{batch_id}")
    def get_batch(batch_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().get_batch(tenant(x_tenant_id), batch_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/api/ecommerce-scenes/batches/{batch_id}/items/{item_id}/download/{fmt}")
    def download_item(
        batch_id: str,
        item_id: str,
        fmt: str,
        workspace: str | None = Query(default=None),
        inline: bool = Query(default=False),
        x_tenant_id: str | None = Header(default=None),
    ) -> FileResponse:
        tid = tenant(x_tenant_id or workspace)
        try:
            target = store().item_asset_path(tid, batch_id, item_id, fmt)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        media = {"png": "image/png", "glb": "model/gltf-binary", "blend": "application/x-blender"}[fmt]
        if inline and fmt == "png":
            return FileResponse(target, media_type=media, headers={"Cache-Control": "no-store"})
        return FileResponse(
            target,
            media_type=media,
            filename=f"{batch_id[:8]}_{item_id}.{fmt}",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/api/ecommerce-scenes/batches/{batch_id}/zip")
    def download_zip(
        batch_id: str,
        workspace: str | None = Query(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> Response:
        tid = tenant(x_tenant_id or workspace)
        try:
            data = store().build_batch_zip(tid, batch_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="ecommerce-matrix-{batch_id[:8]}.zip"',
                "Cache-Control": "no-store",
            },
        )

    return router
