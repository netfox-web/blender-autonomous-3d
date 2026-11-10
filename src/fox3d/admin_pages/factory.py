"""Admin page /admin/factory: 工廠報價與改版＋商品研發產生."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from fox3d.admin_pages import page_response

FEATURES: dict[str, str] = {
    "factory": "/admin/factory",
    "product-rd": "/admin/factory#rd",
}

PRODUCT_TYPE_LABELS: dict[str, str] = {
    "WARDROBE": "衣櫃",
    "SHOE_CABINET": "鞋櫃",
    "TV_CABINET": "電視櫃",
    "BOOKCASE": "書櫃",
    "STORAGE_CABINET": "收納櫃",
    "DISPLAY_CABINET": "展示櫃",
    "KITCHEN_BASE": "廚下櫃（地櫃）",
    "KITCHEN_WALL": "廚房吊櫃",
}


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(400, "X-Tenant-Id required")
    return x_tenant_id.strip()


def router(provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/factory")
    def factory_page() -> Any:
        return page_response("factory")

    @r.get("/api/pages/factory/state")
    def factory_state(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _require_tenant(x_tenant_id)
        plat = provider()
        fac = plat.factory

        product_types: list[dict[str, Any]] = []
        for code in fac.types.list():
            defaults = fac.types.defaults(code)
            product_types.append(
                {
                    **defaults,
                    "label": PRODUCT_TYPE_LABELS.get(code, code),
                }
            )

        spaces = [
            s.model_dump(mode="json")
            for s in fac.spaces.values()
            if getattr(s, "tenantId", None) == tid
        ]

        runs = [
            run
            for run in fac.runs.values()
            if run.get("tenantId") == tid
        ]

        quotes: list[dict[str, Any]] = []
        for run in runs:
            q = run.get("quote") or {}
            qid = q.get("quoteId")
            stored_q = fac.quotes.get(str(qid)) if qid else None
            base_q = dict(stored_q or q)
            if base_q:
                gate = run.get("gate") or {}
                space_info = run.get("space") or {}
                asm = run.get("assembly") or {}
                quotes.append(
                    {
                        **base_q,
                        "runId": run.get("runId"),
                        "gateStatus": gate.get("status") or "WAITING_APPROVAL",
                        "approvedActor": gate.get("actor"),
                        "liveMachineControl": bool(gate.get("liveMachineControl", False)),
                        "wallName": space_info.get("wallName") or "N",
                        "spaceWidth": space_info.get("width"),
                        "spaceDepth": space_info.get("depth"),
                        "spaceHeight": space_info.get("height"),
                        "cabinetCount": asm.get("cabinetCount") or len(asm.get("cabinets") or []),
                        "previewLabel": run.get("previewLabel") or "SKIPPED",
                    }
                )

        products: list[dict[str, Any]] = []
        tenant_product_ids: set[str] = set()
        for pid, rec in plat.parametrics.items():
            spec = rec.get("spec") or {}
            if spec.get("tenantId") != tid:
                continue
            tenant_product_ids.add(str(pid))
            q = rec.get("quote") or {}
            report = rec.get("report") or {}
            products.append(
                {
                    "productId": spec.get("productId") or pid,
                    "kind": spec.get("kind"),
                    "kindLabel": PRODUCT_TYPE_LABELS.get(str(spec.get("kind") or ""), str(spec.get("kind") or "")),
                    "width": spec.get("width"),
                    "height": spec.get("height"),
                    "depth": spec.get("depth"),
                    "boardThickness": spec.get("boardThickness") or spec.get("thickness") or 18,
                    "doorCount": spec.get("doorCount", 0),
                    "shelfCount": spec.get("shelfCount", 0),
                    "drawerCount": spec.get("drawerCount", 0),
                    "material": spec.get("material") or "WOOD_WHITE",
                    "openingStyle": spec.get("openingStyle") or "hinged",
                    "topFillerHeight": spec.get("topFillerHeight") or 0,
                    "sideFillerWidth": spec.get("sideFillerWidth") or 0,
                    "revision": spec.get("revision") or 1,
                    "parentProductId": spec.get("parentProductId") or rec.get("resizedFrom"),
                    "engineeringHash": rec.get("engineeringHash") or spec.get("engineeringHash"),
                    "reportOk": report.get("ok", True),
                    "estimatedCost": q.get("estimatedCost"),
                    "suggestedPrice": q.get("suggestedPrice"),
                }
            )

        revisions = [
            rev
            for rev in fac.revisions
            if rev.get("parentProductId") in tenant_product_ids
            or rev.get("childProductId") in tenant_product_ids
        ]

        probe_blocked = list(plat.probe.blocked) if getattr(plat, "probe", None) else []
        return {
            "tenantId": tid,
            "mockBlender": bool(plat.mock_blender),
            "probeBlocked": probe_blocked,
            "liveMachineControl": False,
            "productTypes": product_types,
            "spaces": spaces,
            "runs": runs,
            "quotes": quotes,
            "products": products,
            "revisions": revisions,
        }

    return r
