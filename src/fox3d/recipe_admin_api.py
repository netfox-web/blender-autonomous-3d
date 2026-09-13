"""Recipe workbench routes for the existing local admin application."""
from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from fox3d.catalog_recipes import FAMILIES
from fox3d.recipe_workbench import DEFAULT_CATALOG, FIELD_LABELS, DraftConflict, RecipeWorkbench, SaveDraft, field_unit

STATIC = Path(__file__).with_name("static")


def recipe_router(provider, *, catalog: Path = DEFAULT_CATALOG):
    router = APIRouter()
    stores = {}
    lock = RLock()

    def store():
        root = provider().root.resolve()
        with lock:
            if root not in stores:
                stores[root] = RecipeWorkbench(root, catalog)
        return stores[root]

    def tenant(value):
        if not value or value != value.strip() or value == "system" or len(value) > 120:
            raise HTTPException(400, "請提供有效的工作區 X-Tenant-Id")
        return value

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DraftConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, "找不到商品或圖片") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/admin/recipes", response_class=HTMLResponse)
    def page():
        return HTMLResponse((STATIC / "recipe-library.html").read_text(encoding="utf-8"),
                            headers={"Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"})

    @router.get("/admin/recipes/assets/{name}")
    def assets(name: str):
        if name not in {"recipe-library.css", "recipe-library.js"}:
            raise HTTPException(404)
        return FileResponse(STATIC / name, media_type="text/css" if name.endswith("css") else "application/javascript")

    @router.get("/api/recipe-library")
    def listing(x_tenant_id: str | None = Header(default=None)):
        tid = tenant(x_tenant_id)
        return {"items": call(store().list, tid), "families": FAMILIES,
                "fields": {key: {"label": label, "unit": field_unit(key)} for key, label in FIELD_LABELS.items()}}

    @router.get("/api/recipe-library/export")
    def export(sku: str | None = None, x_tenant_id: str | None = Header(default=None)):
        bundle = call(store().export, tenant(x_tenant_id), sku)
        return Response(json.dumps(bundle, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="sonaqueen-recipes.json"', "Cache-Control": "no-store"})

    @router.post("/api/recipe-library/import")
    async def import_file(request: Request, x_tenant_id: str | None = Header(default=None)):
        tid = tenant(x_tenant_id)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(413, "匯入檔上限為 8 MB")
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "請選擇有效的 UTF-8 JSON 檔") from exc
        return {"items": call(store().import_drafts, tid, payload)}

    @router.post("/api/recipe-library/products", status_code=201)
    def create(body: SaveDraft, x_tenant_id: str | None = Header(default=None)):
        return call(store().save, tenant(x_tenant_id), body, create=True)

    @router.get("/api/recipe-library/products/{sku}")
    def detail(sku: str, x_tenant_id: str | None = Header(default=None)):
        return call(store().get, tenant(x_tenant_id), sku)

    @router.put("/api/recipe-library/products/{sku}")
    def save(sku: str, body: SaveDraft, x_tenant_id: str | None = Header(default=None)):
        tid = tenant(x_tenant_id)
        if body.draft.sku != sku:
            raise HTTPException(422, "商品編號不一致")
        return call(store().save, tid, body)

    @router.post("/api/recipe-library/products/{sku}/validate")
    def validate(sku: str, x_tenant_id: str | None = Header(default=None)):
        return call(store().get, tenant(x_tenant_id), sku)["validation"]

    @router.post("/api/recipe-library/products/{sku}/images", status_code=201)
    async def upload(sku: str, file: UploadFile = File(...), x_tenant_id: str | None = Header(default=None)):
        tid = tenant(x_tenant_id)
        data = await file.read(8 * 1024 * 1024 + 1)
        return call(store().add_image, tid, sku, data, file.filename or "商品圖片")

    @router.get("/api/recipe-library/products/{sku}/images/{digest}")
    def image(sku: str, digest: str, workspace: str = Query(...)):
        path, mime = call(store().image, tenant(workspace), sku, digest)
        return FileResponse(path, media_type=mime, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @router.get("/api/recipe-library/sources/{sku}/{source_id}")
    def source(sku: str, source_id: str):
        # Only immutable public seed JPEGs are displayed. HTML snapshots never execute.
        seeds = call(store().seeds)
        seed = seeds.get(sku)
        source = next((s for s in seed.sources if s.sourceId == source_id and s.mediaType == "image/jpeg"), None) if seed else None
        if source is None:
            raise HTTPException(404, "找不到來源圖片")
        return FileResponse(catalog.parent / source.path, media_type="image/jpeg", headers={"X-Content-Type-Options": "nosniff"})

    def _get_platform():
        obj = provider()
        if hasattr(obj, "execute_job") and hasattr(obj, "dam"):
            return obj
        from fox3d.platform import Platform
        return Platform(root=getattr(obj, "root", Path.cwd() / ".fox3d-data"), mock_blender=True)

    @router.post("/api/recipe-library/products/{sku}/3d/generate")
    def generate_3d(sku: str, x_tenant_id: str | None = Header(default=None)):
        tid = tenant(x_tenant_id)
        item = call(store().get, tid, sku)
        from fox3d.recipe_3d import generate_recipe_3d_product
        plat = _get_platform()
        try:
            return generate_recipe_3d_product(plat, tid, sku, item["draft"])
        except Exception as exc:
            raise HTTPException(500, f"3D 生成失敗: {exc}") from exc

    @router.get("/api/recipe-library/products/{sku}/3d/status")
    def status_3d(sku: str, x_tenant_id: str | None = Header(default=None)):
        tid = tenant(x_tenant_id)
        from fox3d.recipe_3d import get_recipe_3d_status
        plat = _get_platform()
        return get_recipe_3d_status(plat.root, tid, sku)

    @router.get("/api/recipe-library/products/{sku}/3d/render")
    def render_image_3d(sku: str, x_tenant_id: str | None = Header(default=None), workspace: str | None = Query(default=None)):
        tid = tenant(x_tenant_id or workspace)
        from fox3d.recipe_3d import get_recipe_3d_dir
        plat = _get_platform()
        png_path = get_recipe_3d_dir(plat.root, tid, sku) / "beauty.png"
        if not png_path.exists():
            raise HTTPException(404, "尚未生成 3D 渲染圖")
        return FileResponse(png_path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @router.get("/api/recipe-library/products/{sku}/3d/download/{fmt}")
    def download_3d_asset(sku: str, fmt: str, x_tenant_id: str | None = Header(default=None), workspace: str | None = Query(default=None)):
        tid = tenant(x_tenant_id or workspace)
        from fox3d.recipe_3d import get_recipe_3d_dir
        plat = _get_platform()
        d = get_recipe_3d_dir(plat.root, tid, sku)
        if fmt == "blend":
            target = d / "model.blend"
            media = "application/x-blender"
            filename = f"{sku}_model.blend"
        elif fmt == "glb":
            target = d / "model.glb"
            media = "model/gltf-binary"
            filename = f"{sku}_model.glb"
        elif fmt == "png":
            target = d / "beauty.png"
            media = "image/png"
            filename = f"{sku}_render.png"
        else:
            raise HTTPException(400, "不支援的下載格式 (支援: blend, glb, png)")
        if not target.exists() or target.stat().st_size == 0:
            raise HTTPException(404, f"檔案不存在或尚未生成 ({fmt})")
        return FileResponse(target, media_type=media, filename=filename, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    return router

