"""Golden product routes in the existing local admin application."""
import re
from pathlib import Path
from threading import RLock

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict

from fox3d import golden_preview as preview
from fox3d.golden_product import SKUS, VERSIONS, RECIPE_ID
from fox3d.recipe_preview_service import RecipePreviewService
from fox3d.recipe_3d import read_json
from fox3d.ids import sha256_bytes


class GenerateGolden(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    version: str
    planHash: str
    assumptionsAccepted: bool


class CancelGolden(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    taskId: str


def golden_router(provider):
    router=APIRouter()
    services={}
    lock=RLock()
    def identity(sku,tenant):
        if sku not in SKUS:
            raise HTTPException(404,"找不到 Golden SKU")
        if not tenant or tenant!=tenant.strip() or tenant=="system" or len(tenant)>120:
            raise HTTPException(400,"請提供有效工作區")
        return tenant
    def selected(sku,version):
        try:
            return preview.plan(sku,version)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
    def available():
        platform=provider()
        return not platform.mock_blender and platform.runtime.available()
    def service():
        platform=provider()
        with lock:
            if platform.root not in services:
                services[platform.root]=RecipePreviewService(platform,folder_fn=preview.folder_for,status_fn=preview.status,generate_fn=preview.generate)
            return services[platform.root]

    @router.get("/admin/recipes/golden",response_class=HTMLResponse)
    def page():
        return HTMLResponse((Path(__file__).with_name("static")/"golden-product.html").read_text(encoding="utf-8"),
            headers={"Content-Security-Policy":"default-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"})

    @router.get("/api/recipe-library/golden")
    def catalog():
        return {"recipeId":RECIPE_ID,"skus":list(SKUS),"versions":[
            {"id":"HISTORICAL_PENDING","label":"歷史原稿 · 尚待提供","truth":"BLOCKED"},
            {"id":"FIXTURE_MASTER_V1","label":"三門連續校驗圖 v1 · 非原稿","truth":"FIXTURE"},
            {"id":"FIXTURE_SINGLE_V1","label":"三門獨立校驗圖 v1 · 非原稿","truth":"FIXTURE"}]}

    @router.get("/api/recipe-library/golden/{sku}/plan")
    def plan(sku:str,version:str="HISTORICAL_PENDING",x_tenant_id:str|None=Header(default=None)):
        identity(sku,x_tenant_id)
        return {**selected(sku,version),"blenderAvailable":available()}

    @router.post("/api/recipe-library/golden/{sku}/generate",status_code=202)
    def generate(sku:str,body:GenerateGolden,x_tenant_id:str|None=Header(default=None)):
        tenant=identity(sku,x_tenant_id)
        plan=selected(sku,body.version)
        if not plan["ready"]:
            raise HTTPException(422,"原始 Artwork 尚未提供；可選擇標示 FIXTURE 的校驗圖")
        if not body.assumptionsAccepted or body.planHash!=plan["planHash"]:
            raise HTTPException(409,"請重新確認設定及預覽假設")
        if not available():
            raise HTTPException(503,"真實 Blender 不可用")
        try:
            return service().submit(tenant,sku,{"draft":plan["draft"],"revision":0})
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from exc

    @router.get("/api/recipe-library/golden/{sku}/status")
    def status(sku:str,version:str="HISTORICAL_PENDING",x_tenant_id:str|None=Header(default=None)):
        tenant=identity(sku,x_tenant_id)
        return service().status(tenant,sku,selected(sku,version)["draft"])

    @router.post("/api/recipe-library/golden/{sku}/cancel")
    def cancel(sku:str,body:CancelGolden,x_tenant_id:str|None=Header(default=None)):
        tenant=identity(sku,x_tenant_id)
        try:
            return service().cancel(tenant,sku,body.taskId)
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from exc

    @router.get("/api/recipe-library/golden/{sku}/download/{format}")
    def download(sku:str,format:str,generation:str=Query(...),workspace:str=Query(...),inline:bool=False):
        tenant=identity(sku,workspace)
        if format not in preview.DOWNLOADS or not re.fullmatch(r"[a-f0-9-]{36}",generation):
            raise HTTPException(404,"找不到成果")
        folder=preview.folder_for(provider().root,tenant,sku)/"generations"/generation
        meta=read_json(folder/"meta.json")
        try:
            if meta.get("sku")!=sku or meta.get("tenantId")!=tenant or meta.get("generationId")!=generation:
                raise ValueError("Generation identity mismatch")
            if sha256_bytes((folder/"manifest.json").read_bytes())!=meta["manifestSha256"]:
                raise ValueError("Manifest changed")
            preview.validate_generation(folder,sku,meta["version"])
        except (OSError,ValueError,KeyError,TypeError) as exc:
            raise HTTPException(409,"成果驗證失敗，請重新生成") from exc
        name=preview.DOWNLOADS[format]
        return FileResponse(folder/name,filename=None if inline and name.endswith(".png") else sku+"-"+name,
            headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})
    return router
