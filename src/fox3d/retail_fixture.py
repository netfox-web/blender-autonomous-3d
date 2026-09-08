"""Retail Display / POP Fixture Factory.

Reuses CabinetEngine RETAIL_DISPLAY + existing BOM/Nesting/Cost/Packing/Approval.
Not a second Digital Twin or nesting engine.
"""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.kd import pack_flatpack, packed_weight, shipping_metrics
from fox3d.manufacturing import QuoteEngine
from fox3d.nesting_v3 import NestingV3
from fox3d.parametric import BOMEngine, CabinetSpec

FIXTURE_FAMILIES = (
    "COUNTER_DISPLAY",
    "FLOOR_DISPLAY",
    "PDQ_DISPLAY",
    "RISER_DISPLAY",
    "PEGBOARD_DISPLAY",
    "ENDCAP_MODULE",
)

FIXTURE_DEFAULTS: dict[str, dict[str, Any]] = {
    "COUNTER_DISPLAY": {"width": 600, "height": 800, "depth": 400, "shelfCount": 3},
    "FLOOR_DISPLAY": {"width": 800, "height": 1600, "depth": 400, "shelfCount": 5},
    "PDQ_DISPLAY": {"width": 400, "height": 400, "depth": 300, "shelfCount": 2},
    "RISER_DISPLAY": {"width": 400, "height": 200, "depth": 300, "shelfCount": 1},
    "PEGBOARD_DISPLAY": {"width": 800, "height": 1200, "depth": 300, "shelfCount": 0},
    "ENDCAP_MODULE": {"width": 600, "height": 1400, "depth": 400, "shelfCount": 4},
}


class RetailFixtureRegistry:
    def list(self) -> list[str]:
        return list(FIXTURE_FAMILIES)

    def defaults(self, family: str) -> dict[str, Any]:
        if family not in FIXTURE_DEFAULTS:
            raise ValueError(family)
        return dict(FIXTURE_DEFAULTS[family])


def product_slot_layout(
    *,
    product: dict[str, Any],
    facing: int,
    rows: int,
    columns: int,
    clearance_mm: float = 8.0,
) -> dict[str, Any]:
    dims = product.get("dimensions") or {}
    pw = float(dims.get("width") or product.get("width") or 80)
    ph = float(dims.get("height") or product.get("height") or 120)
    pd = float(dims.get("depth") or product.get("depth") or 40)
    slots = []
    for r in range(int(rows)):
        for c in range(int(columns)):
            slots.append(
                {
                    "row": r,
                    "col": c,
                    "x": round(c * (pw + clearance_mm), 3),
                    "y": round(r * (ph + clearance_mm), 3),
                    "w": pw,
                    "h": ph,
                    "d": pd,
                    "facing": int(facing),
                }
            )
    layout = {
        "productSku": product.get("sku") or product.get("twinId"),
        "facing": facing,
        "rows": rows,
        "columns": columns,
        "clearanceMm": clearance_mm,
        "slots": slots,
        "neededWidth": round(columns * pw + max(0, columns - 1) * clearance_mm, 3),
        "neededHeight": round(rows * ph + max(0, rows - 1) * clearance_mm, 3),
        "neededDepth": pd,
    }
    layout["layoutHash"] = stable_hash(layout)
    return layout


def planogram_solve(*, fixture_inner: dict[str, float], product: dict[str, Any], facing: int = 1, clearance_mm: float = 8.0) -> dict[str, Any]:
    fw = float(fixture_inner["width"])
    fh = float(fixture_inner["height"])
    fd = float(fixture_inner.get("depth") or 400)
    dims = product.get("dimensions") or {}
    pw = float(dims.get("width") or 80) + clearance_mm
    ph = float(dims.get("height") or 120) + clearance_mm
    pd = float(dims.get("depth") or 40)
    cols = max(1, int(fw // pw))
    rows = max(1, int(fh // ph))
    candidates = []
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            layout = product_slot_layout(product=product, facing=facing, rows=r, columns=c, clearance_mm=clearance_mm)
            ok = layout["neededWidth"] <= fw + 1e-6 and layout["neededHeight"] <= fh + 1e-6 and pd <= fd + 1e-6
            overlap = False
            slots = layout["slots"]
            for i, a in enumerate(slots):
                for b in slots[i + 1 :]:
                    if not (a["x"] + a["w"] <= b["x"] + 1e-6 or b["x"] + b["w"] <= a["x"] + 1e-6 or a["y"] + a["h"] <= b["y"] + 1e-6 or b["y"] + b["h"] <= a["y"] + 1e-6):
                        overlap = True
            if ok and not overlap:
                candidates.append({**layout, "legal": True, "capacityUnits": r * c * facing})
    candidates.sort(key=lambda x: (-x["capacityUnits"], x["neededWidth"]))
    chosen = candidates[0] if candidates else {
        "legal": False,
        "slots": [],
        "capacityUnits": 0,
        "note": "no legal planogram for product vs fixture inner",
    }
    return {
        "candidates": candidates[:6],
        "chosen": chosen,
        "inner": fixture_inner,
        "liveMachineControl": False,
    }


def capacity_load(planogram: dict[str, Any], *, unit_weight_kg: float = 0.25) -> dict[str, Any]:
    qty = int((planogram.get("chosen") or planogram).get("capacityUnits") or 0)
    total = qty * float(unit_weight_kg)
    return {
        "unitCount": qty,
        "estimatedTotalKg": round(total, 3),
        "source": "CONFIG_ESTIMATE",
        "label": "PARTIAL",
        "structuralCertification": False,
        "note": "No REAL structural analysis — not a certified load rating.",
    }


def artwork_zones(spec: dict[str, Any]) -> dict[str, Any]:
    w = float(spec.get("width") or 600)
    h = float(spec.get("height") or 800)
    return {
        "zones": [
            {"name": "front_header", "x": 20, "y": h - 120, "w": w - 40, "h": 90, "kind": "logo"},
            {"name": "front_body", "x": 20, "y": 40, "w": w - 40, "h": h - 180, "kind": "printable"},
        ],
        "safeAreaMm": 8,
        "printPreflight": "PARTIAL",
        "note": "geometry metadata only — not print preflight complete",
    }


def lighting_metadata() -> dict[str, Any]:
    return {
        "ledStripReserve": True,
        "cableChannelMm": 12,
        "electricalCompliance": "BLOCKED",
        "label": "PARTIAL",
        "note": "No electrical engineering rules registered.",
    }


class RetailFixtureFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.registry = RetailFixtureRegistry()
        self.nester = NestingV3()
        self.items: dict[str, dict[str, Any]] = {}

    def build(
        self,
        *,
        tenant_id: str,
        family: str,
        product: dict[str, Any] | None = None,
        facing: int = 2,
        render: bool = False,
        **params: Any,
    ) -> dict[str, Any]:
        defaults = self.registry.defaults(family)
        width = float(params.get("width") or defaults["width"])
        height = float(params.get("height") or defaults["height"])
        depth = float(params.get("depth") or defaults["depth"])
        spec, report = self.platform.cabinets.create(
            "RETAIL_DISPLAY",
            tenant_id=tenant_id,
            width=width,
            height=height,
            depth=depth,
            shelfCount=int(params.get("shelfCount") or defaults.get("shelfCount") or 3),
            doorCount=0,
            material=params.get("material") or "WOOD_WHITE",
        )
        spec.metadata["fixtureFamily"] = family
        spec.metadata["physicalProductFamily"] = "RETAIL_FIXTURE"
        bom = BOMEngine().build(spec)
        t = float(spec.boardThickness)
        inner = {"width": spec.width - 2 * t, "height": spec.height - 2 * t, "depth": spec.depth - t}
        product = product or {"sku": "SKU-DEMO", "dimensions": {"width": 80, "height": 140, "depth": 40}}
        slots = product_slot_layout(product=product, facing=facing, rows=max(1, spec.shelfCount or 1), columns=max(1, int(inner["width"] // 90)), clearance_mm=8)
        plano = planogram_solve(fixture_inner=inner, product=product, facing=facing)
        load = capacity_load(plano, unit_weight_kg=float(product.get("weightKg") or 0.25))
        art = artwork_zones(spec.model_dump(mode="json"))
        light = lighting_metadata()
        nest = self.nester.nest(bom, material=str(spec.material), thickness=float(spec.boardThickness), seed=f"fixture:{family}")
        quote = QuoteEngine().quote(spec, bom, nest)
        packing = pack_flatpack(spec, bom)
        weight = packed_weight(spec, bom, packing)
        ship = shipping_metrics(packing, weight)
        rec = {
            "fixtureId": spec.productId,
            "tenantId": tenant_id,
            "family": family,
            "spec": spec.model_dump(mode="json"),
            "report": report.model_dump(),
            "engineeringHash": spec.engineering_hash(),
            "bom": bom,
            "bomHash": bom.get("bomHash"),
            "slots": slots,
            "planogram": plano,
            "capacity": load,
            "artwork": art,
            "lighting": light,
            "nesting": {k: nest[k] for k in nest if k not in {"svg"}},
            "nestingHash": nest.get("nestingHash"),
            "quote": quote.model_dump(mode="json"),
            "packing": packing,
            "weight": weight,
            "shipping": ship,
            "approvalState": "WAITING_APPROVAL" if report.ok else "IDEA",
            "liveMachineControl": False,
            "samePipeline": ["BOM", "NestingV3", "WasteV2", "Remnant", "Cost", "Packing", "Approval"],
            "preview": None,
        }
        rec["lineage"] = {
            "engineeringHash": rec["engineeringHash"],
            "bomHash": rec["bomHash"],
            "nestingHash": rec["nestingHash"],
            "packagingHash": packing.get("packagingHash"),
        }
        if render and report.ok:
            self.platform.parametrics[spec.productId] = {"spec": rec["spec"], "report": rec["report"], "bom": bom, "engineeringHash": rec["engineeringHash"]}
            rec["preview"] = self.platform.render_parametric(spec.productId, tenant_id=tenant_id)
        rec["approval"] = {
            "status": rec["approvalState"],
            "requiresHuman": True,
            "liveMachineControl": False,
            "forbidden": ["LIVE_CNC", "APPROVED_FOR_PRODUCTION"],
        }
        self.items[spec.productId] = rec
        return rec
