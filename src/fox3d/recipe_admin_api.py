"""Recipe workbench routes for the existing local admin application."""
from __future__ import annotations

import json
import re
from pydantic import BaseModel, ConfigDict, Field
from pathlib import Path
from threading import RLock

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from fox3d.catalog_recipes import FAMILIES
from fox3d.recipe_workbench import DEFAULT_CATALOG, FIELD_LABELS, DraftConflict, RecipeWorkbench, SaveDraft, field_unit

class GeneratePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expectedRevision: int = Field(ge=0)
    planHash: str
    assumptionsAccepted: bool


class CancelPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    taskId: str


STATIC = Path(__file__).with_name("static")


def recipe_router(provider, *, catalog: Path = DEFAULT_CATALOG):
    router = APIRouter()
    from fox3d.golden_api import golden_router
    router.include_router(golden_router(provider))
    from fox3d.print_api import print_router
    router.include_router(print_router(provider))
    from fox3d.product_models_api import product_models_router
    router.include_router(product_models_router(provider))
    stores = {}
    services = {}
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
        if name not in {"recipe-library.css", "recipe-library.js", "recipe-viewer.js", "golden-product.js", "golden-product.css", "print-workspace.js", "print-workspace.css", "printfox-bridge.js", "printfox-bridge.css", "product-models.css", "product-models.js", "model-compositions.js", "model-batches.js"}:
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

    def service():
        from fox3d.recipe_preview_service import RecipePreviewService
        obj = provider()
        with lock:
            if obj.root not in services:
                services[obj.root] = RecipePreviewService(obj)
            return services[obj.root]

    def available():
        obj = provider()
        return bool(not getattr(obj, "mock_blender", True) and getattr(obj, "runtime", None) and obj.runtime.available())

    @router.get("/api/recipe-library/health")
    def health():
        return {"service": "sonaqueen-recipe-studio", "blenderAvailable": available()}

    @router.get("/api/recipe-library/products/{sku}/3d/plan")
    def plan_3d(sku: str, x_tenant_id: str | None = Header(default=None)):
        from fox3d.recipe_3d import build_recipe_spec, input_hash
        tid = tenant(x_tenant_id)
        item = call(store().get, tid, sku)
        result = {"revision": item["revision"], "planHash": input_hash(item["draft"]),
                  "blenderAvailable": available(), "ready": False}
        try:
            spec = build_recipe_spec(item["draft"], tenant_id=tid)
            result.update(ready=True, spec=spec, assumptions=spec["previewAssumptions"])
        except ValueError as exc:
            result["error"] = str(exc)
        return result

    @router.post("/api/recipe-library/products/{sku}/3d/generate", status_code=202)
    def generate_3d(sku: str, body: GeneratePreview, x_tenant_id: str | None = Header(default=None)):
        from fox3d.recipe_3d import build_recipe_spec, input_hash
        tid = tenant(x_tenant_id)
        item = call(store().get, tid, sku)
        if body.expectedRevision != item["revision"] or body.planHash != input_hash(item["draft"]):
            raise HTTPException(409, "商品設定已變更，請重新整理並確認生成設定")
        if not body.assumptionsAccepted:
            raise HTTPException(422, "請先確認畫面上的預覽假設")
        call(build_recipe_spec, item["draft"], tenant_id=tid)
        if not available():
            raise HTTPException(503, "找不到可用的 Blender，請安裝後重新啟動工作台")
        try:
            return service().submit(tid, sku, item)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/recipe-library/products/{sku}/3d/status")
    def status_3d(sku: str, x_tenant_id: str | None = Header(default=None)):
        tid = tenant(x_tenant_id)
        item = call(store().get, tid, sku)
        return service().status(tid, sku, item["draft"])

    @router.post("/api/recipe-library/products/{sku}/3d/cancel")
    def cancel_3d(sku: str, body: CancelPreview, x_tenant_id: str | None = Header(default=None)):
        tid = tenant(x_tenant_id)
        call(store().get, tid, sku)
        return call(service().cancel, tid, sku, body.taskId)

    def asset(sku, tid, fmt, generation):
        from fox3d.recipe_3d import get_recipe_3d_dir, read_json, verified_assets, FILES
        call(store().get, tid, sku)
        base = get_recipe_3d_dir(provider().root, tid, sku)
        gid = generation or read_json(base / "meta.json").get("generationId", "")
        if not re.fullmatch(r"[a-f0-9-]{36}", gid):
            raise HTTPException(404, "尚無可下載的生成成果")
        folder = base / "generations" / gid
        meta = read_json(folder / "meta.json")
        info = meta.get("renderInfo", {})
        if (meta.get("sku") != sku or meta.get("tenantId") != tid or not info.get("realBlender")
                or info.get("usedMock") or not all(verified_assets(folder, meta).values())):
            raise HTTPException(404, "成果不存在或檔案驗證失敗，請重新生成")
        return folder / FILES[fmt]

    @router.get("/api/recipe-library/products/{sku}/3d/render")
    def render_image_3d(sku: str, x_tenant_id: str | None = Header(default=None), workspace: str | None = Query(default=None), generation: str | None = None):
        target = asset(sku, tenant(x_tenant_id or workspace), "png", generation)
        return FileResponse(target, media_type="image/png", headers={"Cache-Control": "no-store"})

    @router.get("/api/recipe-library/products/{sku}/3d/download/{fmt}")
    def download_3d_asset(sku: str, fmt: str, x_tenant_id: str | None = Header(default=None), workspace: str | None = Query(default=None), generation: str | None = None):
        media = {"blend": "application/x-blender", "glb": "model/gltf-binary", "png": "image/png"}
        if fmt not in media:
            raise HTTPException(400, "支援的下載格式：blend、glb、png")
        target = asset(sku, tenant(x_tenant_id or workspace), fmt, generation)
        return FileResponse(target, media_type=media[fmt], filename=f"{sku}_preview.{fmt}",
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return router
