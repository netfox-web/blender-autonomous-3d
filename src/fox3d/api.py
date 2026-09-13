"""HTTP API — FastAPI. Admin UI talks to this, never to a Blender GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from fox3d.admin import render_admin
from fox3d.operator import make_token, require_confirm
from fox3d.platform import Platform
from fox3d.recovery import PilotException
from fox3d.recipe_admin_api import recipe_router

_PLATFORM: Platform | None = None


def get_platform() -> Platform:
    global _PLATFORM
    if _PLATFORM is None:
        _PLATFORM = Platform(mock_blender=False)
        _PLATFORM.register_detected_workers()
    return _PLATFORM


def create_app(platform: Platform | None = None) -> FastAPI:
    app = FastAPI(title="Blender Autonomous 3D / Product R&D Engine", version="0.1.0")
    if platform is not None:
        global _PLATFORM
        _PLATFORM = platform

    def tenant(x_tenant_id: str | None) -> str:
        if not x_tenant_id:
            raise HTTPException(400, "X-Tenant-Id required")
        return x_tenant_id

    def require_tenant(x_tenant_id: str | None, payload: dict[str, Any] | None = None) -> str:
        header = tenant(x_tenant_id)
        body_tid = (payload or {}).get("tenantId")
        if body_tid not in {None, "", header}:
            raise HTTPException(403, "body tenantId does not match X-Tenant-Id")
        return header

    @app.get("/health")
    def health() -> dict[str, Any]:
        plat = get_platform()
        probe = plat.probe.to_dict() if plat.probe else {}
        return {"status": "ok", "probe": probe, "mock": plat.mock_blender}

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/admin")

    @app.get("/api/probe")
    def probe() -> dict[str, Any]:
        plat = get_platform()
        if plat.probe is None:
            plat.register_detected_workers()
        return plat.probe.to_dict() if plat.probe else {}

    @app.post("/api/3d/jobs")
    def create_job(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = payload.get("tenantId") or tenant(x_tenant_id)
        payload["tenantId"] = tid
        return get_platform().submit_job(payload)

    @app.get("/api/3d/jobs")
    def list_jobs(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        plat = get_platform()
        tid = x_tenant_id
        return {"items": plat.queue.list(tenant_id=tid) if tid else plat.queue.list()}

    @app.get("/api/3d/jobs/{job_id}")
    def read_job(job_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return get_platform().get_job(job_id, tenant_id=tenant(x_tenant_id))
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/3d/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return get_platform().cancel_job(job_id, tenant_id=tenant(x_tenant_id))
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/assets/{asset_id}")
    def read_asset(asset_id: str, x_tenant_id: str | None = Header(default=None)) -> FileResponse:
        plat = get_platform()
        try:
            if x_tenant_id:
                obj = plat.dam.get(asset_id, tenant_id=x_tenant_id)
            else:
                obj = plat.dam.get_unchecked(asset_id)
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, str(exc)) from exc
        path = Path(obj.path)
        media = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
        return FileResponse(path, media_type=media)

    @app.post("/api/digital-twins")
    def create_twin(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        payload["tenantId"] = payload.get("tenantId") or tenant(x_tenant_id)
        return get_platform().create_twin(payload)

    @app.post("/api/digital-twins/upload")
    async def upload_twin(
        sku: str = Form(...),
        file: UploadFile = File(...),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        data = await file.read()
        return get_platform().product_e2e(tenant_id=tid, sku=sku, glb_bytes=data)

    @app.get("/api/digital-twins/{twin_id}")
    def read_twin(twin_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return get_platform().get_twin(twin_id, tenant_id=tenant(x_tenant_id))
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/digital-twins/{twin_id}/preview")
    def twin_preview(twin_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        plat = get_platform()
        twin = plat.get_twin(twin_id, tenant_id=tenant(x_tenant_id))
        return plat.product_e2e(tenant_id=twin["tenantId"], sku=twin["sku"], glb_path=twin.get("glb"))

    @app.post("/api/digital-twins/{twin_id}/360")
    def twin_360(twin_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return get_platform().product_360_e2e(tenant_id=tenant(x_tenant_id), twin_id=twin_id, frames=36)

    @app.post("/api/parametric/products")
    def create_parametric(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        payload["tenantId"] = payload.get("tenantId") or tenant(x_tenant_id)
        plat = get_platform()
        created = plat.create_parametric(payload)
        if payload.get("render"):
            created["render"] = plat.render_parametric(created["spec"]["productId"], tenant_id=payload["tenantId"])
        return created

    @app.post("/api/parametric/products/{product_id}/resize")
    def resize_parametric(product_id: str, payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        plat = get_platform()
        resized = plat.resize_parametric(product_id, tenant_id=tenant(x_tenant_id), **{k: v for k, v in payload.items() if k in {"width", "height", "depth"}})
        if payload.get("render", True):
            resized["render"] = plat.render_parametric(resized["spec"]["productId"], tenant_id=resized["spec"]["tenantId"])
        return resized

    @app.post("/api/parametric/products/{product_id}/variants")
    def variants(product_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        return get_platform().rd.run(
            tenant_id=body.get("tenantId") or tenant(x_tenant_id),
            text=body.get("text") or f"variants for {product_id}",
            variant_count=int(body.get("count") or 12),
        )

    @app.post("/api/render/preview")
    def preview(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        payload["tenantId"] = payload.get("tenantId") or tenant(x_tenant_id)
        return get_platform().preview(payload)

    @app.post("/api/render/final")
    def final_render(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        payload["tenantId"] = payload.get("tenantId") or tenant(x_tenant_id)
        return get_platform().final_render(payload)

    @app.post("/api/product-rd/generate")
    def product_rd(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = payload.get("tenantId") or tenant(x_tenant_id)
        plat = get_platform()
        rd = plat.product_rd(tenant_id=tid, text=payload.get("text") or "", variant_count=int(payload.get("variantCount") or 12))
        if rd.get("baseSpec") and not plat._production_gate():
            stored = plat.create_parametric({**rd["baseSpec"], "tenantId": tid, "kind": rd["baseSpec"].get("kind")})
            rd["parametricRender"] = plat.render_parametric(stored["spec"]["productId"], tenant_id=tid)
        return rd

    @app.post("/api/e2e/smoke")
    def e2e_smoke() -> dict[str, Any]:
        return get_platform().real_smoke_test()

    @app.get("/api/factory/product-types")
    def factory_types() -> dict[str, Any]:
        return {"items": get_platform().factory.types.list()}

    @app.post("/api/factory/spaces")
    def factory_space(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        payload["tenantId"] = payload.get("tenantId") or tenant(x_tenant_id)
        return get_platform().factory.create_space(payload).model_dump(mode="json")

    @app.post("/api/factory/run")
    def factory_run(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = payload.get("tenantId") or tenant(x_tenant_id)
        return get_platform().furniture_factory_run(
            tenant_id=tid,
            space=payload.get("space"),
            wall_name=payload.get("wallName") or "N",
            product_types=payload.get("productTypes"),
            text=payload.get("text"),
            render=bool(payload.get("render")),
        )

    @app.get("/api/factory/quotes/{quote_id}")
    def factory_quote(quote_id: str) -> dict[str, Any]:
        rec = get_platform().factory.quotes.get(quote_id)
        if not rec:
            raise HTTPException(404, quote_id)
        return rec

    @app.post("/api/factory/quotes/{quote_id}/approve")
    def factory_quote_approve(quote_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        plat = get_platform()
        body = payload or {}
        for run_id, run in plat.factory.runs.items():
            if (run.get("quote") or {}).get("quoteId") == quote_id:
                return plat.factory.approve(run_id, actor=str(body.get("actor") or "human"))
        raise HTTPException(404, quote_id)

    @app.post("/api/factory/products/{product_id}/revise")
    def factory_revise(product_id: str, payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return get_platform().factory.revise_cabinet(product_id, tenant_id=tenant(x_tenant_id), **{k: v for k, v in payload.items() if k != "tenantId"})

    @app.get("/api/kd/product-types")
    def kd_types() -> dict[str, Any]:
        from fox3d.kd import FLATPACK_PRODUCT_TYPES

        return {"items": list(FLATPACK_PRODUCT_TYPES)}

    @app.post("/api/kd/skus")
    def kd_sku(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = payload.get("tenantId") or tenant(x_tenant_id)
        return get_platform().kd.build_sku(tenant_id=tid, kind=str(payload.get("kind") or "BEDSIDE_CABINET"), render=bool(payload.get("render")), **{k: v for k, v in payload.items() if k not in {"tenantId", "kind", "render"}})

    @app.post("/api/kd/catalog")
    def kd_catalog(payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        return get_platform().kd.generate_candidates(tenant_id=body.get("tenantId") or tenant(x_tenant_id), count=int(body.get("count") or 24), render=bool(body.get("render")))

    @app.get("/api/kd/readiness")
    def kd_readiness() -> dict[str, Any]:
        return get_platform().kd.readiness()

    @app.get("/api/materials")
    def materials(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        plat = get_platform()
        from fox3d.acrylic import ACRYLIC_SHEETS
        from fox3d.manufacturing import SheetMaterialRegistry
        from fox3d.packaging import PAPERBOARD_SHEETS

        lots = plat.lots.list(tenant_id=tenant(x_tenant_id)) if x_tenant_id else list(plat.lots.lots.values())
        return {
            "sheets": SheetMaterialRegistry().list(),
            "acrylic": list(ACRYLIC_SHEETS),
            "paperboard": list(PAPERBOARD_SHEETS),
            "lots": lots,
            "costSource": "CONFIG",
        }

    @app.post("/api/materials/lots")
    def create_lot(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        if str(payload.get("allocationPolicy") or "") == "FIXTURE_AUTO_SEED":
            raise HTTPException(403, "FIXTURE_AUTO_SEED is not available on the production/manual API")
        return get_platform().pilot.receiving.import_receipt(
            {
                "material": str(payload.get("material") or "WOOD_WHITE"),
                "thickness": float(payload.get("thickness") or 18),
                "quantity": int(payload.get("sheetCount") or payload.get("quantity") or 1),
                "supplierLot": payload.get("supplierLot"),
                "supplierId": payload.get("supplierId"),
                "unitCost": payload.get("costPerSheet") or payload.get("unitCost"),
            },
            tenant_id=tid,
            actor=str(payload.get("actor") or "api"),
            source=str(payload.get("source") or "MANUAL"),
            idempotency_key=payload.get("idempotencyKey"),
        )

    @app.get("/api/remnants")
    def remnants(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = tenant(x_tenant_id)
        return get_platform().remnants.snapshot(tenant_id=tid)

    @app.post("/api/remnants/{remnant_id}/reserve")
    def remnant_reserve(remnant_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        try:
            return get_platform().remnants.reserve(remnant_id, by=str(body.get("by") or "api"), version=body.get("version"), lease_seconds=body.get("leaseSeconds"), tenant_id=tenant(x_tenant_id))
        except (KeyError, PermissionError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/nesting/benchmarks")
    def nesting_benchmarks(payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        from fox3d.nesting_v3 import run_benchmark

        body = payload or {}
        plat = get_platform()
        result = run_benchmark(plat, tenant_id=body.get("tenantId") or tenant(x_tenant_id))
        plat.physical.benchmarks.append(result)
        return result

    @app.post("/api/kd/candidates")
    def kd_candidates(payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        return get_platform().physical.kd_optimized_board(tenant_id=body.get("tenantId") or tenant(x_tenant_id), count=int(body.get("count") or 10))

    @app.post("/api/retail/fixtures")
    def retail_fixtures(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = payload.get("tenantId") or tenant(x_tenant_id)
        return get_platform().physical.retail.build(
            tenant_id=tid,
            family=str(payload.get("family") or "COUNTER_DISPLAY"),
            product=payload.get("product"),
            facing=int(payload.get("facing") or 2),
            render=bool(payload.get("render")),
        )

    @app.post("/api/packaging/structures")
    def packaging_structures(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = payload.get("tenantId") or tenant(x_tenant_id)
        dims = payload.get("productDims") or payload.get("dimensions") or {"width": 120, "height": 80, "depth": 40}
        return get_platform().physical.packaging.build(
            tenant_id=tid,
            family=str(payload.get("family") or "RSC_CARTON"),
            product_dims=dims,
            render=bool(payload.get("render")),
        )

    @app.post("/api/acrylic/products")
    def acrylic_products(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = payload.get("tenantId") or tenant(x_tenant_id)
        return get_platform().physical.acrylic.build(
            tenant_id=tid,
            kind=str(payload.get("kind") or "MENU_STAND"),
            sheet_sku=str(payload.get("sheetSku") or "ACR_CLEAR_5"),
            render=bool(payload.get("render")),
        )

    @app.post("/api/physical-os/approve")
    def physical_approve(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        _ = tenant(x_tenant_id)
        return get_platform().physical.approve(entity_id=str(payload.get("entityId") or payload.get("productId")), actor=str(payload.get("actor") or "human"), kind=str(payload.get("kind") or "product"))

    @app.get("/api/physical-os/families")
    def physical_families() -> dict[str, Any]:
        reg = get_platform().physical.families
        return {"items": [reg.get(name) for name in reg.list()]}

    @app.get("/api/physical-os/readiness")
    def physical_readiness() -> dict[str, Any]:
        return get_platform().physical.readiness()

    @app.get("/api/readiness")
    def scoped_ready() -> dict[str, Any]:
        from fox3d.readiness import scoped_readiness

        return scoped_readiness()

    @app.post("/api/evidence/verify")
    def evidence_verify(payload: dict[str, Any]) -> dict[str, Any]:
        from fox3d.evidence import verify_bundle

        return verify_bundle(payload.get("bundle") or payload)

    @app.post("/api/release/advance")
    def release_advance(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        _ = tenant(x_tenant_id)
        plat = get_platform()
        try:
            return plat.release.advance(
                str(payload.get("entityId")),
                target=str(payload.get("target") or "WAITING_APPROVAL"),
                actor=str(payload.get("actor") or "human"),
                entity=payload.get("entity") or {},
                evidence_ok=bool(payload.get("evidenceOk")),
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/commerce/import")
    def commerce_import(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        _ = tenant(x_tenant_id)
        plat = get_platform()
        kind = str(payload.get("kind") or "material")
        store = getattr(plat.providers, kind)
        source = str(payload.get("source") or "MANUAL")
        rows = payload.get("rows") or []
        return {"items": plat.providers.import_rows(store, rows, source=source), "liveProviderReady": False}

    @app.post("/api/safety/evaluate")
    def safety_eval(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        _ = tenant(x_tenant_id)
        from fox3d.safety import evaluate_product

        return evaluate_product(str(payload.get("kind") or "KD"), payload.get("record") or payload)

    @app.get("/api/kpi")
    def kpi() -> dict[str, Any]:
        from fox3d.rdloop import kpi_read_model

        return kpi_read_model(get_platform())

    @app.get("/api/pilot/console")
    def pilot_console(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return get_platform().pilot.console(tenant_id=require_tenant(x_tenant_id))

    @app.get("/api/pilot/work-orders")
    def pilot_work_orders(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        items = [wo for wo in get_platform().pilot.workorders.orders.values() if wo.get("tenantId") == tid]
        return {"items": items, "liveMachineControl": False}

    @app.get("/api/pilot/batches")
    def pilot_batches(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        items = [b for b in get_platform().pilot_batch.batches.values() if b.get("tenantId") == tid]
        return {"items": items, "liveMachineControl": False, "physicalPilotBatchValidated": False}

    @app.get("/api/pilot/batches/board")
    def pilot_batch_board(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        return get_platform().pilot_batch.decision_board(tenant_id=tid)

    @app.post("/api/pilot/work-orders/{work_order_id}/reserve")
    def pilot_reserve(work_order_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        if str(body.get("allocationPolicy") or "") == "FIXTURE_AUTO_SEED":
            raise HTTPException(403, "FIXTURE_AUTO_SEED is not available on the production/manual API")
        try:
            return get_platform().pilot.workorders.reserve_materials(
                work_order_id,
                actor=str(body.get("actor") or "api"),
                tenant_id=tid,
                allocation_policy="STRICT_STOCK",
            )
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/pilot/receipts")
    def pilot_receipt(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        return get_platform().pilot.receiving.import_receipt(
            payload,
            tenant_id=tid,
            actor=str(payload.get("actor") or "api"),
            source=str(payload.get("source") or "IMPORTED"),
            idempotency_key=payload.get("idempotencyKey"),
        )

    @app.post("/api/pilot/purchase-requests")
    def pilot_pr(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        return get_platform().pilot.receiving.draft_purchase_request(
            tenant_id=tid,
            material=str(payload.get("material") or "PB_18_WHITE"),
            quantity=int(payload.get("quantity") or 1),
            actor=str(payload.get("actor") or "api"),
            shortage=payload.get("shortage"),
            release_hash=payload.get("releaseHash"),
        )

    @app.get("/api/pilot/health")
    def pilot_health_ep(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return get_platform().pilot.health(tenant_id=require_tenant(x_tenant_id))

    @app.get("/api/pilot/operator")
    def pilot_operator(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return get_platform().pilot.operator(tenant_id=require_tenant(x_tenant_id))

    @app.post("/api/pilot/scan")
    def pilot_scan(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        try:
            return get_platform().pilot.scan(str(payload.get("token") or ""), tenant_id=tid)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/pilot/stations")
    def pilot_station(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        return get_platform().pilot.stations.register(
            tenant_id=tid,
            capabilities=list(payload.get("capabilities") or []),
            station_id=payload.get("stationId"),
            actor=str(payload.get("actor") or "api"),
            status=str(payload.get("status") or "ONLINE"),
        )

    @app.post("/api/pilot/stations/{station_id}/heartbeat")
    def pilot_station_hb(station_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        try:
            return get_platform().pilot.stations.heartbeat(station_id, tenant_id=tid, actor=body.get("actor"))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/pilot/dispatch")
    def pilot_dispatch(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        try:
            return get_platform().pilot.dispatcher.dispatch(
                tenant_id=tid,
                work_order_id=str(payload["workOrderId"]),
                operation=str(payload["operation"]),
                station_id=str(payload["stationId"]),
                actor=str(payload.get("actor") or "api"),
            )
        except PilotException as exc:
            raise HTTPException(409, exc.code) from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/pilot/leases/{lease_id}/ack")
    def pilot_ack(lease_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        return get_platform().pilot.dispatcher.ack(lease_id, tenant_id=tid, actor=str(body.get("actor") or "api"))

    @app.post("/api/pilot/leases/{lease_id}/start")
    def pilot_start(lease_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        return get_platform().pilot.dispatcher.start(lease_id, tenant_id=tid, actor=str(body.get("actor") or "api"))

    @app.post("/api/pilot/leases/{lease_id}/complete")
    def pilot_lease_complete(lease_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        try:
            require_confirm(body, action="complete_operation")
            return get_platform().pilot.dispatcher.complete(lease_id, tenant_id=tid, actor=str(body.get("actor") or "api"), confirm=True)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/api/pilot/exceptions")
    def pilot_exceptions(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        return {"items": get_platform().pilot.inbox.list(tenant_id=tid)}

    @app.post("/api/pilot/import")
    def pilot_import(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id, payload)
        return get_platform().pilot.contracts.import_bundle(
            payload,
            tenant_id=tid,
            actor=str(payload.get("actor") or "api"),
            source=str(payload.get("source") or "IMPORTED"),
            idempotency_key=payload.get("idempotencyKey"),
        )

    @app.get("/api/pilot/export")
    def pilot_export(releaseHash: str | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = require_tenant(x_tenant_id)
        return get_platform().pilot.contracts.export_bundle(tenant_id=tid, release_hash=releaseHash)

    @app.post("/api/pilot/work-orders/{work_order_id}/consume")
    def pilot_consume(work_order_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        try:
            return get_platform().pilot.confirm_action(
                tenant_id=tid,
                action="consume",
                work_order_id=work_order_id,
                actor=str(body.get("actor") or "api"),
                payload=body,
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/pilot/work-orders/{work_order_id}/complete")
    def pilot_complete_wo(work_order_id: str, payload: dict[str, Any] | None = None, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = payload or {}
        tid = require_tenant(x_tenant_id, body)
        try:
            return get_platform().pilot.confirm_action(
                tenant_id=tid,
                action="complete_wo",
                work_order_id=work_order_id,
                actor=str(body.get("actor") or "api"),
                payload=body,
            )
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/pilot/scan-token/{kind}/{object_id}")
    def pilot_token(kind: str, object_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        _ = require_tenant(x_tenant_id)
        return {"token": make_token(kind, object_id), "barcodeHardware": "PARTIAL"}

    @app.get("/admin", response_class=HTMLResponse)
    def admin() -> str:
        return render_admin(get_platform())

    app.include_router(recipe_router(lambda: platform if platform is not None else get_platform()))
    return app


def main() -> None:
    import uvicorn

    print("Autonomous 3D Admin: http://127.0.0.1:8788/admin")
    print("Health:               http://127.0.0.1:8788/health")
    uvicorn.run(create_app(), host="127.0.0.1", port=8788, log_level="info")


if __name__ == "__main__":
    main()
