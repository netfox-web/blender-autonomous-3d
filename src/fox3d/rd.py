"""AI furniture designer, variant generator, vision judge, Product R&D agent."""

from __future__ import annotations

from typing import Any, Protocol

from fox3d.ids import new_id
from fox3d.parametric import (
    CabinetEngine,
    CabinetSpec,
    CostEngine,
    EngineeringRuleEngine,
    parse_design_intent,
)
from fox3d.studio import LIGHTING_RECIPES, MATERIALS


class VisionProvider(Protocol):
    name: str
    status: str  # MOCK | REAL

    def score_image(self, *, preview: dict[str, Any]) -> dict[str, float]:
        ...


class HeuristicVisionProvider:
    name = "heuristic"
    status = "MOCK"

    def score_image(self, *, preview: dict[str, Any]) -> dict[str, float]:
        graph = (preview.get("sceneGraph") or {})
        cam = graph.get("camera") or {}
        fill = float(cam.get("fill") or 0.7)
        return {
            "composition": 0.9 if 0.45 <= fill <= 0.85 else 0.55,
            "aesthetics": 0.8 if (preview.get("dsl") or {}).get("scene") else 0.5,
            "product_visibility": 0.85 if graph.get("objects") else 0.2,
            "brand_consistency": 0.7,
        }


class GatewayVisionProvider:
    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway
        self.name = "foxstudio-gateway"

    @property
    def status(self) -> str:
        adapters = getattr(self.gateway, "_vision_adapters", None) or {}
        return "REAL" if adapters else "MOCK"

    def score_image(self, *, preview: dict[str, Any]) -> dict[str, float]:
        fn = None
        adapters = getattr(self.gateway, "_vision_adapters", None) or {}
        if adapters:
            fn = next(iter(adapters.values()))
        if not fn:
            return HeuristicVisionProvider().score_image(preview=preview)
        out = fn(preview)
        return {k: float(v) for k, v in (out or {}).items() if isinstance(v, (int, float))}


class VisionJudge:
    """Product scoring. Live vision models plug in via Provider; default is MOCK heuristic."""

    dimensions = (
        "composition",
        "aesthetics",
        "product_visibility",
        "brand_consistency",
        "engineering_validity",
        "space_utilization",
        "cost",
        "manufacturability",
    )

    def __init__(self, provider: VisionProvider | None = None) -> None:
        self.provider: VisionProvider = provider or HeuristicVisionProvider()

    def score(self, *, preview: dict[str, Any], spec: CabinetSpec | None, quote: dict[str, Any] | None, report_ok: bool) -> dict[str, Any]:
        vision = dict(self.provider.score_image(preview=preview))
        scores: dict[str, float] = {
            "composition": float(vision.get("composition") or 0.5),
            "aesthetics": float(vision.get("aesthetics") or 0.5),
            "product_visibility": float(vision.get("product_visibility") or 0.5),
            "brand_consistency": float(vision.get("brand_consistency") or 0.5),
        }
        engineering: dict[str, float] = {}
        engineering["engineering_validity"] = 1.0 if report_ok else 0.2
        wall = (spec.metadata.get("wallWidth") if spec else None) or 0
        if spec and wall:
            engineering["space_utilization"] = min(1.0, spec.width / wall)
        else:
            engineering["space_utilization"] = 0.7
        cost = (quote or {}).get("estimatedCost") or 0
        engineering["cost"] = 0.9 if cost and cost < 25000 else 0.65 if cost < 80000 else 0.4
        engineering["manufacturability"] = 0.9 if report_ok else 0.3
        scores.update(engineering)
        vision_score = sum(vision.get(k, scores[k]) for k in ("composition", "aesthetics", "product_visibility", "brand_consistency")) / 4
        engineering_score = sum(engineering.values()) / len(engineering)
        veto = not report_ok
        overall = min(vision_score, 0.2) if veto else (0.5 * vision_score + 0.5 * engineering_score)
        return {
            "scores": scores,
            "overall": round(overall, 4),
            "visionScore": round(vision_score, 4),
            "engineeringScore": round(engineering_score, 4),
            "engineeringVeto": veto,
            "previewId": preview.get("variantId"),
            "provider": {"name": getattr(self.provider, "name", "heuristic"), "status": getattr(self.provider, "status", "MOCK")},
            "label": "REAL" if getattr(self.provider, "status", "MOCK") == "REAL" else "MOCK",
        }


class VariantGenerator:
    def generate(self, spec: CabinetSpec, *, count: int = 12) -> list[dict[str, Any]]:
        count = max(10, min(50, count))
        variants: list[dict[str, Any]] = []
        door_opts = [max(0, spec.doorCount - 1), spec.doorCount, spec.doorCount + 1, 2, 3]
        shelf_opts = [max(0, spec.shelfCount - 1), spec.shelfCount, spec.shelfCount + 1]
        drawer_opts = [spec.drawerCount, 0, 1, 2]
        width_opts = [spec.width, spec.width - 50, spec.width + 50, spec.width - 100]
        materials = ["particle_board", "mdf", "plywood"]
        colors = ["cream", "oak", "white", "black"]
        handles = ["bar", "knob", "hidden"]
        i = 0
        for door in door_opts:
            for shelf in shelf_opts:
                for width in width_opts:
                    if i >= count:
                        break
                    variants.append(
                        {
                            "variantId": new_id(),
                            "layout": f"doors:{door}/shelves:{shelf}/drawers:{drawer_opts[i % len(drawer_opts)]}",
                            "dimensions": {"width": max(400, width), "height": spec.height, "depth": spec.depth},
                            "material": materials[i % len(materials)],
                            "color": colors[i % len(colors)],
                            "door": door,
                            "drawer": drawer_opts[i % len(drawer_opts)],
                            "shelf": max(0, shelf),
                            "handle": handles[i % len(handles)],
                            "module": "DOUBLE_DOOR" if door == 2 else ("HINGED_DOOR" if door else "OPEN_BAY"),
                            "previewOnly": True,
                            "finalRender": False,
                            "lighting": LIGHTING_RECIPES[i % len(LIGHTING_RECIPES)],
                        }
                    )
                    i += 1
                if i >= count:
                    break
            if i >= count:
                break
        return variants[:count]


class ProductRDAgent:
    def __init__(
        self,
        cabinets: CabinetEngine,
        costs: CostEngine,
        judge: VisionJudge,
        studio_builder: Any,
    ) -> None:
        self.cabinets = cabinets
        self.costs = costs
        self.judge = judge
        self.studio = studio_builder
        self.bom = None

    def run(
        self,
        *,
        tenant_id: str,
        text: str,
        variant_count: int = 12,
        top_n: int = 3,
        auto_approve: bool = False,
    ) -> dict[str, Any]:
        intent = parse_design_intent(text, tenant_id=tenant_id)
        params = {k: v for k, v in intent["params"].items() if k != "kind"}
        spec, report = self.cabinets.create(intent["kind"], tenant_id=tenant_id, **params)
        from fox3d.parametric import BOMEngine

        bom_engine = BOMEngine()
        variants = VariantGenerator().generate(spec, count=variant_count)
        if report.ok:
            variants = [
                {
                    "variantId": spec.productId,
                    "layout": f"doors:{spec.doorCount}/shelves:{spec.shelfCount}",
                    "dimensions": {"width": spec.width, "height": spec.height, "depth": spec.depth},
                    "material": spec.material,
                    "color": spec.metadata.get("style") or "cream",
                    "door": spec.doorCount,
                    "drawer": spec.drawerCount,
                    "shelf": spec.shelfCount,
                    "handle": spec.handleStyle,
                    "lighting": "SOFTBOX",
                    "previewOnly": True,
                    "finalRender": False,
                }
            ] + variants
        scored: list[dict[str, Any]] = []
        for variant in variants:
            vspec, vreport = self.cabinets.resize(
                spec,
                width=variant["dimensions"]["width"],
            )
            vspec.doorCount = int(variant["door"])
            if vspec.doorCount:
                while vspec.doorCount < 10 and (vspec.width / vspec.doorCount) > 600:
                    vspec.doorCount += 1
            vspec.shelfCount = int(variant["shelf"])
            vspec.drawerCount = int(variant["drawer"])
            vspec.material = variant["material"]
            vspec.components = self.cabinets._components(vspec)
            vspec.hardware = self.cabinets._hardware(vspec)
            vreport = EngineeringRuleEngine().validate(vspec)
            if not vreport.ok:
                continue
            bom = bom_engine.build(vspec)
            quote = self.costs.quote(vspec, bom)
            preview = self.studio.build(
                twin={
                    "twinId": vspec.productId,
                    "dimensions": {
                        "width": vspec.width,
                        "height": vspec.height,
                        "depth": vspec.depth,
                    },
                    "material": variant["color"],
                },
                studio="WHITE_STUDIO" if variant["color"] == "white" else "LIFESTYLE",
                lighting=variant["lighting"],
            )
            preview["variantId"] = variant["variantId"]
            judgement = self.judge.score(preview=preview, spec=vspec, quote=quote, report_ok=vreport.ok)
            scored.append(
                {
                    "variant": variant,
                    "spec": vspec.model_dump(),
                    "report": vreport.model_dump(),
                    "bom": bom,
                    "quote": quote,
                    "preview": {"steps": preview["steps"], "variantId": variant["variantId"]},
                    "judge": judgement,
                }
            )
        scored.sort(key=lambda row: row["judge"]["overall"], reverse=True)
        top = scored[:top_n]
        gate = {
            "status": "APPROVED" if auto_approve else "WAITING_APPROVAL",
            "note": "Automatic research may run unattended. Production assets require a human approval gate.",
            "autoApproveForbiddenForProduction": True,
        }
        production_assets: list[dict[str, Any]] = []
        if auto_approve:
            # Still do not emit production assets without an explicit approve() call.
            gate["status"] = "WAITING_APPROVAL"
        return {
            "rdId": new_id(),
            "pipeline": [
                "requirement",
                "design_intent",
                "variant_generator",
                "engineering_validator",
                "cost_engine",
                "blender_preview",
                "vision_judge",
                "top_candidates",
                "human_approval_gate",
                "production_assets",
            ],
            "intent": intent,
            "baseSpec": spec.model_dump(),
            "baseReport": report.model_dump(),
            "variantCount": len(variants),
            "scoredCount": len(scored),
            "top": top,
            "approval": gate,
            "productionAssets": production_assets,
        }

    def approve(self, rd_result: dict[str, Any], *, actor: str) -> dict[str, Any]:
        rd_result = dict(rd_result)
        rd_result["approval"] = {
            "status": "APPROVED",
            "actor": actor,
            "autoApproveForbiddenForProduction": True,
        }
        rd_result["productionAssets"] = [
            {"fromVariant": row["variant"]["variantId"], "kind": "production_candidate"} for row in rd_result.get("top") or []
        ]
        return rd_result
