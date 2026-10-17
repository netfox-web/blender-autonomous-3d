"""Read-only Product DNA routes. Local preview contracts only; no external writes."""
from threading import RLock

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from fox3d.product_dna import (
    CONSUMERS, EXPORT_SKUS, FAMILY_ID, ProductDnaError, catalog, check_tenant, check_version,
    media_refs, project_manifest, project_twin, reconcile, ExportService,
)


class CreateExport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["FIXTURE_MASTER_V1", "FIXTURE_SINGLE_V1"] = "FIXTURE_MASTER_V1"
    skus: list[str] | None = None
    seal: bool = True


class DeclaredSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)
    system: Literal["ERP", "AI_PRINT_OS", "SPECPILOT_PRODUCT_DNA"]
    tenantId: str = Field(min_length=1, max_length=120)
    productFamilyId: str | None = None
    skuId: str | None = None
    masterProductId: str | None = None
    dieMoldId: str | None = None
    productDnaId: str | None = None
    engineeringVersion: str | None = None
    widthMm: float | None = None
    depthMm: float | None = None
    heightMm: float | None = None
    boardThicknessMm: float | None = None
    backThicknessMm: float | None = None
    doorThicknessMm: float | None = None
    doorGapMm: float | None = None
    engineeringHash: str | None = None
    bomHash: str | None = None
    artworkHash: str | None = None
    finalUvHash: str | None = None
    rightsScope: Literal["NONE", "FIXTURE_NON_IP", "LICENSED_ARTWORK"] | None = None
    processCode: str | None = None


def product_dna_router(provider):
    router = APIRouter()
    services = {}
    lock = RLock()

    def platform_root():
        return provider().root

    def service() -> ExportService:
        root = platform_root()
        with lock:
            if root not in services:
                services[root] = ExportService(root)
            return services[root]

    def run(fn):
        try:
            return fn()
        except ProductDnaError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @router.get("/api/product-dna/v1/catalog")
    def get_catalog():
        return catalog()

    @router.get("/api/product-dna/v1/families/{family_id}/manifest")
    def family_manifest(family_id: str, version: str = "FIXTURE_MASTER_V1", x_tenant_id: str | None = Header(default=None)):
        if family_id != FAMILY_ID:
            raise HTTPException(404, "找不到商品母版")
        return run(lambda: project_manifest(check_tenant(x_tenant_id), version=check_version(version), skus=EXPORT_SKUS))

    @router.get("/api/product-dna/v1/families/{family_id}/skus/{sku}/twin")
    def one_twin(family_id: str, sku: str, version: str = "FIXTURE_MASTER_V1", x_tenant_id: str | None = Header(default=None)):
        if family_id != FAMILY_ID:
            raise HTTPException(404, "找不到商品母版")
        return run(lambda: project_twin(check_tenant(x_tenant_id), sku, check_version(version)))

    @router.post("/api/product-dna/v1/reconcile")
    def reconcile_snapshot(body: DeclaredSnapshot, x_tenant_id: str | None = Header(default=None)):
        return run(lambda: reconcile(body.model_dump(), tenant_id=check_tenant(x_tenant_id)))

    @router.get("/api/product-dna/v1/media-refs")
    def get_media_refs(consumer: str, version: str = "FIXTURE_MASTER_V1", x_tenant_id: str | None = Header(default=None)):
        if consumer not in CONSUMERS:
            raise HTTPException(404, "未知的媒體讀取方")
        return run(lambda: media_refs(check_tenant(x_tenant_id), consumer, version=check_version(version)))

    @router.post("/api/product-dna/v1/exports", status_code=201)
    def create_export(body: CreateExport, x_tenant_id: str | None = Header(default=None)):
        return run(lambda: service().begin(check_tenant(x_tenant_id), version=body.version, skus=body.skus, seal=body.seal))

    @router.post("/api/product-dna/v1/exports/{export_id}/cancel")
    def cancel_export(export_id: str, x_tenant_id: str | None = Header(default=None)):
        return run(lambda: service().cancel(check_tenant(x_tenant_id), export_id))

    @router.post("/api/product-dna/v1/exports/{export_id}/retry")
    def retry_export(export_id: str, x_tenant_id: str | None = Header(default=None)):
        return run(lambda: service().retry(check_tenant(x_tenant_id), export_id))

    @router.get("/api/product-dna/v1/exports/{export_id}")
    def read_export(export_id: str, x_tenant_id: str | None = Header(default=None)):
        return run(lambda: service().read(check_tenant(x_tenant_id), export_id))

    return router
