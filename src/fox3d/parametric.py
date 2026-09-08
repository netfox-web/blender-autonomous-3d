"""Parametric product, cabinet, engineering rules, BOM, cost, CAM adapters.

Blender is never the millimetre source of truth. One engineering record drives
mesh, BOM, cost, and future CAM.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from fox3d.ids import new_id, stable_hash

CabinetKind = Literal[
    "WARDROBE",
    "SHOE_CABINET",
    "TV_CABINET",
    "STORAGE_CABINET",
    "BOOKCASE",
    "KITCHEN_BASE",
    "KITCHEN_WALL",
    "DISPLAY_CABINET",
    "CABINET",
]

# 4x8 sheet in mm — Taiwan/CN furniture panel standard.
MAX_PANEL_W = 2440
MAX_PANEL_H = 1220
ALLOWED_THICKNESS = (15, 16, 18, 25, 30)

TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "WARDROBE": {"width": 1200, "height": 2200, "depth": 560, "doorCount": 2, "shelfCount": 2, "drawerCount": 0, "legs": False},
    "SHOE_CABINET": {"width": 800, "height": 1200, "depth": 350, "doorCount": 2, "shelfCount": 4, "drawerCount": 0},
    "TV_CABINET": {"width": 1800, "height": 500, "depth": 400, "doorCount": 2, "shelfCount": 0, "drawerCount": 2, "legs": True, "plinthHeight": 100},
    "STORAGE_CABINET": {"width": 800, "height": 1800, "depth": 400, "doorCount": 2, "shelfCount": 3, "drawerCount": 0},
    "BOOKCASE": {"width": 800, "height": 1800, "depth": 300, "doorCount": 0, "shelfCount": 5, "drawerCount": 0},
    "KITCHEN_BASE": {"width": 800, "height": 870, "depth": 580, "doorCount": 2, "shelfCount": 1, "drawerCount": 0, "plinthHeight": 150},
    "KITCHEN_WALL": {"width": 800, "height": 720, "depth": 330, "doorCount": 2, "shelfCount": 2, "drawerCount": 0},
    "DISPLAY_CABINET": {"width": 900, "height": 1800, "depth": 400, "doorCount": 2, "shelfCount": 3, "drawerCount": 0},
    "CABINET": {"width": 800, "height": 1800, "depth": 400, "doorCount": 2, "shelfCount": 2, "drawerCount": 0},
}

MATERIAL_PRICE_PER_M2 = {
    "particle_board": 280.0,
    "mdf": 360.0,
    "plywood": 520.0,
    "solid_wood": 980.0,
    "glass": 850.0,
}
HARDWARE_PRICE = {
    "hinge": 25.0,
    "drawer_slide_pair": 80.0,
    "handle": 35.0,
    "leg": 40.0,
    "cam_lock": 3.0,
    "dowel": 0.5,
    "hanging_rail": 60.0,
}
EDGE_BANDING_PER_M = 8.0
PROCESSING_CUT_PER_PART = 12.0
PROCESSING_EDGE_PER_M = 6.0
PROCESSING_DRILL_PER_HOLE = 1.5
ASSEMBLY_PER_HOUR = 350.0
PACKAGING_BASE = 80.0


class ParametricProduct(BaseModel):
    productId: str = Field(default_factory=new_id)
    tenantId: str
    kind: str = "CABINET"
    width: float
    height: float
    depth: float
    thickness: float = 18
    material: str = "particle_board"
    components: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    connections: list[dict[str, Any]] = Field(default_factory=list)
    hardware: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def engineering_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json", exclude={"productId"}))


class CabinetSpec(ParametricProduct):
    kind: CabinetKind = "CABINET"
    boardThickness: float = 18
    doorCount: int = 2
    shelfCount: int = 2
    drawerCount: int = 0
    backPanel: bool = True
    backThickness: float = 3
    legs: bool = False
    plinthHeight: float = 0
    handles: bool = True
    handleStyle: str = "bar"
    modules: list[dict[str, Any]] = Field(default_factory=list)
    toeKickHeight: float = 0
    topFillerHeight: float = 0
    sideFillerWidth: float = 0
    wallClearance: float = 0
    openingStyle: str = "hinged"
    parentProductId: str | None = None
    revision: int = 1
    verticalPartitions: int | None = None
    horizontalPartitions: int = 0

    def to_product(self) -> ParametricProduct:
        data = self.model_dump()
        data["thickness"] = self.boardThickness
        return ParametricProduct.model_validate({k: data[k] for k in ParametricProduct.model_fields})


class RuleViolation(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    field: str | None = None


class EngineeringReport(BaseModel):
    ok: bool
    violations: list[RuleViolation] = Field(default_factory=list)

    @property
    def errors(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == "error"]


def tv_width_mm(inches: float, *, ratio: tuple[int, int] = (16, 9)) -> float:
    diag_mm = inches * 25.4
    w, h = ratio
    return diag_mm * w / math.hypot(w, h)


class EngineeringRuleEngine:
    """Deterministic millimetre validation. LLM may propose; this validates."""

    def validate(self, spec: CabinetSpec) -> EngineeringReport:
        v: list[RuleViolation] = []
        t = spec.boardThickness
        if t not in ALLOWED_THICKNESS:
            v.append(RuleViolation(code="BOARD_THICKNESS", message=f"board thickness {t}mm not in {ALLOWED_THICKNESS}", field="boardThickness"))
        if spec.width <= 0 or spec.height <= 0 or spec.depth <= 0:
            v.append(RuleViolation(code="DIMENSION_POSITIVE", message="width/height/depth must be positive"))
        inner_w = spec.width - 2 * t
        inner_h = spec.height - 2 * t - spec.plinthHeight
        inner_d = spec.depth - (spec.backThickness if spec.backPanel else 0) - t
        bays = _bay_count(inner_w, 800)
        bay_span = inner_w / bays
        if spec.doorCount:
            door_w = spec.width / spec.doorCount
            door_h = spec.height - spec.plinthHeight
            if door_w > 600:
                v.append(RuleViolation(code="DOOR_WIDTH", message=f"door width {door_w:.0f}mm exceeds 600mm", field="doorCount"))
            if door_h > 2400:
                v.append(RuleViolation(code="DOOR_HEIGHT", message=f"door height {door_h:.0f}mm exceeds 2400mm"))
            if door_w < 150 and spec.doorCount > 0:
                v.append(RuleViolation(code="DOOR_WIDTH_MIN", message=f"door width {door_w:.0f}mm below 150mm"))
            # Door swing vs adjacent carcass: 90° needs door_w clearance in front.
            if spec.depth < 200:
                v.append(RuleViolation(code="DOOR_SWING", message="depth too small for door swing", field="depth"))
        if spec.drawerCount:
            drawer_h = min(180.0, inner_h / max(spec.drawerCount, 1) - 4)
            drawer_w = bay_span - 26  # slide clearance per bay (dividers keep span ≤ 800)
            if drawer_w > 900:
                v.append(RuleViolation(code="DRAWER_WIDTH", message=f"drawer width {drawer_w:.0f}mm exceeds 900mm"))
            if drawer_h < 60:
                v.append(RuleViolation(code="DRAWER_HEIGHT", message="drawer height below 60mm"))
            if spec.depth < 250:
                v.append(RuleViolation(code="DRAWER_SLIDE", message="depth < 250mm cannot fit drawer slides"))
            # Full-height doors swinging through a drawer bank on a short carcass.
            if spec.doorCount and spec.drawerCount and spec.shelfCount == 0 and spec.height < 400:
                v.append(RuleViolation(code="DRAWER_COLLISION", message="drawers collide with door opening on a short carcass"))
            v.append(
                RuleViolation(
                    code="DRAWER_EXTENSION",
                    message="drawer full-extension needs front clearance ≥ drawer-box depth; geometric placeholder only",
                    severity="warning",
                    field="depth",
                )
            )
        if spec.shelfCount:
            limit = {15: 600, 16: 700, 18: 800, 25: 1000, 30: 1200}.get(int(t), 800)
            if bay_span > limit:
                v.append(RuleViolation(code="SHELF_SPAN", message=f"shelf span {bay_span:.0f}mm exceeds {limit}mm for {t}mm board — add a divider", field="width"))
            v.append(
                RuleViolation(
                    code="SHELF_LOAD_PLACEHOLDER",
                    message="shelf span check is geometric only; not a structural certification",
                    severity="warning",
                    field="shelfCount",
                )
            )
        if spec.backPanel and spec.backThickness < 3:
            v.append(RuleViolation(code="BACK_PANEL", message="back panel thinner than 3mm"))
        # Hardware space: hinge cup 12mm + overlay.
        if spec.doorCount and inner_d < 40:
            v.append(RuleViolation(code="HARDWARE_SPACE", message="insufficient depth for hinge cups"))
        # Max panel size vs 4x8 sheet (each carcass panel).
        panels = [
            ("side", spec.height, spec.depth),
            ("top", spec.width, spec.depth),
            ("door", spec.height - spec.plinthHeight, spec.width / max(spec.doorCount, 1)),
        ]
        for name, a, b in panels:
            long, short = max(a, b), min(a, b)
            if long > MAX_PANEL_W + 1 or short > MAX_PANEL_H + 1:
                v.append(RuleViolation(code="MAX_PANEL", message=f"{name} {long:.0f}x{short:.0f} exceeds {MAX_PANEL_W}x{MAX_PANEL_H} sheet"))
        # Structural: very tall+narrow.
        if spec.height / max(spec.width, 1) > 6:
            v.append(RuleViolation(code="STRUCTURE", message="height/width ratio > 6 is unstable"))
        # Robot vacuum / TV cabinet rules.
        if spec.kind == "TV_CABINET" and spec.legs and spec.plinthHeight < 100:
            v.append(RuleViolation(code="ROBOT_VACUUM", message="TV cabinet with legs needs >=100mm clearance for robot vacuum", field="plinthHeight"))
        tv_inch = spec.metadata.get("tvInches")
        if tv_inch:
            need = tv_width_mm(float(tv_inch)) + 200
            if spec.width < need:
                v.append(RuleViolation(code="TV_WIDTH", message=f"cabinet width {spec.width}mm < TV {tv_inch}\" + margins ({need:.0f}mm)"))
        try:
            from fox3d.manufacturing import HardwareRegistry

            for issue in HardwareRegistry().compatibility(spec):
                v.append(RuleViolation(code=str(issue["code"]), message=str(issue["message"]), severity=issue.get("severity") or "error"))
        except Exception:
            pass
        errors = [x for x in v if x.severity == "error"]
        return EngineeringReport(ok=len(errors) == 0, violations=v)


class CabinetEngine:
    def __init__(self, rules: EngineeringRuleEngine | None = None) -> None:
        self.rules = rules or EngineeringRuleEngine()

    def create(self, kind: str, *, tenant_id: str, **params: Any) -> tuple[CabinetSpec, EngineeringReport]:
        defaults = dict(TYPE_DEFAULTS.get(kind, TYPE_DEFAULTS["CABINET"]))
        defaults.update({k: v for k, v in params.items() if v is not None})
        defaults.setdefault("boardThickness", defaults.get("thickness", 18))
        door_count = int(defaults.get("doorCount") or 0)
        width = float(defaults["width"])
        if door_count:
            while door_count < 10 and (width / door_count) > 600:
                door_count += 1
        spec = CabinetSpec(
            tenantId=tenant_id,
            kind=kind,  # type: ignore[arg-type]
            width=width,
            height=float(defaults["height"]),
            depth=float(defaults["depth"]),
            thickness=float(defaults.get("boardThickness") or 18),
            boardThickness=float(defaults.get("boardThickness") or 18),
            doorCount=door_count,
            shelfCount=int(defaults.get("shelfCount") or 0),
            drawerCount=int(defaults.get("drawerCount") or 0),
            backPanel=bool(defaults.get("backPanel", True)),
            legs=bool(defaults.get("legs") or False),
            plinthHeight=float(defaults.get("plinthHeight") or (100 if defaults.get("legs") else 0)),
            handles=bool(defaults.get("handles", True)),
            material=str(defaults.get("material") or "particle_board"),
            metadata=dict(defaults.get("metadata") or {}),
            toeKickHeight=float(defaults.get("toeKickHeight") or 0),
            topFillerHeight=float(defaults.get("topFillerHeight") or 0),
            sideFillerWidth=float(defaults.get("sideFillerWidth") or 0),
            wallClearance=float(defaults.get("wallClearance") or 0),
            openingStyle=str(defaults.get("openingStyle") or "hinged"),
            verticalPartitions=defaults.get("verticalPartitions"),
            horizontalPartitions=int(defaults.get("horizontalPartitions") or 0),
        )
        inner_w = spec.width - 2 * spec.boardThickness
        if spec.verticalPartitions is not None:
            spec.constraints["bays"] = max(1, int(spec.verticalPartitions) + 1)
        else:
            spec.constraints["bays"] = _bay_count(inner_w, 800)
        spec.components = self._components(spec)
        spec.hardware = self._hardware(spec)
        spec.connections = self._connections(spec)
        from fox3d.furniture import sync_modules

        sync_modules(spec)
        report = self.rules.validate(spec)
        return spec, report

    def resize(self, spec: CabinetSpec, **dims: float) -> tuple[CabinetSpec, EngineeringReport]:
        data = spec.model_dump()
        data.update({k: v for k, v in dims.items() if v is not None})
        data["productId"] = new_id()
        data["modules"] = []
        data["parentProductId"] = spec.productId
        data["revision"] = int(getattr(spec, "revision", 1) or 1) + 1
        nxt = CabinetSpec.model_validate(data)
        inner_w = nxt.width - 2 * nxt.boardThickness
        if nxt.verticalPartitions is not None:
            nxt.constraints["bays"] = max(1, int(nxt.verticalPartitions) + 1)
        else:
            nxt.constraints["bays"] = _bay_count(inner_w, 800)
        nxt.components = self._components(nxt)
        nxt.hardware = self._hardware(nxt)
        nxt.connections = self._connections(nxt)
        from fox3d.furniture import sync_modules

        sync_modules(nxt)
        return nxt, self.rules.validate(nxt)

    def _components(self, spec: CabinetSpec) -> list[dict[str, Any]]:
        t = spec.boardThickness
        inner_w = spec.width - 2 * t
        if spec.verticalPartitions is not None:
            bays = max(1, int(spec.verticalPartitions) + 1)
        else:
            bays = _bay_count(inner_w, 800)
        spec.constraints["bays"] = bays
        parts = [
            _panel("L_SIDE", spec.height, spec.depth, t, "left"),
            _panel("R_SIDE", spec.height, spec.depth, t, "right"),
            _panel("TOP", spec.width, spec.depth, t, "top"),
            _panel("BOTTOM", spec.width - 2 * t, spec.depth, t, "bottom"),
        ]
        for i in range(bays - 1):
            parts.append(_panel(f"DIVIDER_{i+1}", spec.height - 2 * t, spec.depth - 20, t, "divider"))
        if spec.backPanel:
            parts.append(_panel("BACK", spec.width - 2 * t, spec.height - 2 * t, spec.backThickness, "back"))
        if spec.shelfCount:
            for i in range(spec.shelfCount):
                parts.append(_panel(f"SHELF_{i+1}", inner_w, spec.depth - 20, t, "shelf"))
        for i in range(int(spec.horizontalPartitions or 0)):
            parts.append(_panel(f"H_PARTITION_{i+1}", inner_w, spec.depth - 20, t, "h_partition"))
        if spec.doorCount:
            door_w = spec.width / spec.doorCount
            door_h = spec.height - spec.plinthHeight
            for i in range(spec.doorCount):
                parts.append(_panel(f"DOOR_{i+1}", door_h, door_w, t, "door"))
        if spec.drawerCount:
            for i in range(spec.drawerCount):
                parts.append(_panel(f"DRAWER_FRONT_{i+1}", 160, inner_w, t, "drawer_front"))
                parts.append(_panel(f"DRAWER_BOX_{i+1}", spec.depth - 40, inner_w - 30, 12, "drawer_box"))
        if spec.legs:
            for i in range(4):
                parts.append({"partId": f"leg_{i+1}", "partName": f"LEG_{i+1}", "partType": "leg", "length": spec.plinthHeight or 100, "width": 40, "thickness": 40, "quantity": 1, "role": "leg", "material": spec.material, "edgeBanding": False})
        if spec.topFillerHeight:
            parts.append(_panel("TOP_FILLER", spec.width, spec.depth, t, "top_filler"))
        if spec.sideFillerWidth:
            parts.append(_panel("SIDE_FILLER", spec.height, spec.depth, t, "side_filler"))
        if spec.plinthHeight and not spec.legs:
            parts.append(_panel("PLINTH", spec.width, spec.depth, spec.plinthHeight, "plinth"))
            parts.append(_panel("TOE_KICK", spec.width, 80, spec.plinthHeight, "toe_kick"))
        elif spec.toeKickHeight:
            parts.append(_panel("TOE_KICK", spec.width, 80, spec.toeKickHeight, "toe_kick"))
        return parts

    def _hardware(self, spec: CabinetSpec) -> list[dict[str, Any]]:
        hw: list[dict[str, Any]] = []
        if spec.doorCount:
            hw.append({"partName": "hinge", "quantity": spec.doorCount * 2, "sku": "hinge"})
            if spec.handles:
                hw.append({"partName": "handle", "quantity": spec.doorCount, "sku": "handle"})
        if spec.drawerCount:
            hw.append({"partName": "drawer_slide_pair", "quantity": spec.drawerCount, "sku": "drawer_slide_pair"})
            if spec.handles:
                hw.append({"partName": "handle", "quantity": spec.drawerCount, "sku": "handle"})
        if spec.legs:
            hw.append({"partName": "leg", "quantity": 4, "sku": "leg"})
        # Cams + dowels per carcass joint (4 corners × 2).
        hw.append({"partName": "cam_lock", "quantity": 16, "sku": "cam_lock"})
        hw.append({"partName": "dowel", "quantity": 16, "sku": "dowel"})
        if spec.kind == "WARDROBE":
            hw.append({"partName": "hanging_rail", "quantity": 1, "sku": "hanging_rail", "vendorNeutralId": "HW_HANGING_RAIL"})
        for item in hw:
            if item["sku"] == "hinge":
                item["vendorNeutralId"] = "HW_HINGE_CLIP_110"
            elif item["sku"] == "drawer_slide_pair":
                item["vendorNeutralId"] = "HW_RAIL_450"
            elif item["sku"] == "handle":
                item["vendorNeutralId"] = "HW_HANDLE_BAR"
            elif item["sku"] == "leg":
                item["vendorNeutralId"] = "HW_LEG_100"
            elif item["sku"] == "cam_lock":
                item["vendorNeutralId"] = "HW_CAM_LOCK_15"
            elif item["sku"] == "dowel":
                item["vendorNeutralId"] = "HW_DOWEL_8"
        return hw

    def _connections(self, spec: CabinetSpec) -> list[dict[str, Any]]:
        return [
            {"from": "L_SIDE", "to": "TOP", "joint": "cam"},
            {"from": "R_SIDE", "to": "TOP", "joint": "cam"},
            {"from": "L_SIDE", "to": "BOTTOM", "joint": "cam"},
            {"from": "R_SIDE", "to": "BOTTOM", "joint": "cam"},
        ]


def _bay_count(inner_w: float, limit: float) -> int:
    if inner_w <= 0:
        return 1
    return max(1, math.ceil(inner_w / limit))


CABINET_MATERIALS = {
    "WOOD_WHITE": {
        "visual": "white_wood",
        "engineering": "particle_board",
        "costUnit": "TWD/m2",
        "thicknessOptionsMm": [15, 18, 25],
        "textureAsset": "wood_white",
        "baseColor": (0.86, 0.82, 0.74),
    },
    "WOOD_OAK": {
        "visual": "oak",
        "engineering": "particle_board",
        "costUnit": "TWD/m2",
        "thicknessOptionsMm": [15, 18, 25],
        "textureAsset": "wood_oak",
        "baseColor": (0.62, 0.45, 0.28),
    },
    "WOOD_WALNUT": {
        "visual": "walnut",
        "engineering": "particle_board",
        "costUnit": "TWD/m2",
        "thicknessOptionsMm": [15, 18, 25],
        "textureAsset": "wood_walnut",
        "baseColor": (0.28, 0.18, 0.12),
    },
    "WOOD_BLACK": {
        "visual": "black_wood",
        "engineering": "mdf",
        "costUnit": "TWD/m2",
        "thicknessOptionsMm": [16, 18],
        "textureAsset": "wood_black",
        "baseColor": (0.08, 0.08, 0.09),
    },
    "WOOD_CREAM": {
        "visual": "cream_wood",
        "engineering": "particle_board",
        "costUnit": "TWD/m2",
        "thicknessOptionsMm": [15, 18, 25],
        "textureAsset": "wood_cream",
        "baseColor": (0.90, 0.84, 0.72),
    },
}


def map_cabinet_material(name: str) -> dict[str, Any]:
    key = (name or "").upper()
    if key in CABINET_MATERIALS:
        return {"code": key, **CABINET_MATERIALS[key]}
    if "白" in (name or "") or name in {"white_wood", "particle_board"}:
        return {"code": "WOOD_WHITE", **CABINET_MATERIALS["WOOD_WHITE"]}
    return {"code": "WOOD_WHITE", **CABINET_MATERIALS["WOOD_WHITE"]}


def _panel(name: str, length: float, width: float, thickness: float, role: str) -> dict[str, Any]:
    from fox3d.manufacturing import edge_banding_edges

    edges = edge_banding_edges(role)
    grain = "length" if role in {"top", "bottom", "shelf", "door", "drawer_front", "h_partition"} else "none"
    return {
        "partId": name.lower(),
        "partName": name,
        "partType": role,
        "length": round(length, 2),
        "width": round(width, 2),
        "thickness": thickness,
        "quantity": 1,
        "role": role,
        "edgeBanding": any(edges.values()),
        "edgeBandingEdges": edges,
        "grainDirection": grain,
    }


class BOMEngine:
    def build(self, spec: CabinetSpec) -> dict[str, Any]:
        lines = []
        for part in spec.components:
            lines.append(
                {
                    "partId": part.get("partId") or part["partName"].lower(),
                    "partName": part["partName"],
                    "partType": part.get("partType") or part.get("role"),
                    "material": spec.material,
                    "length": part.get("length"),
                    "width": part.get("width"),
                    "thickness": part.get("thickness"),
                    "quantity": part.get("quantity", 1),
                    "edgeBanding": bool(part.get("edgeBanding")),
                    "edgeBandingEdges": part.get("edgeBandingEdges"),
                    "grainDirection": part.get("grainDirection"),
                    "hardware": False,
                    "cost": None,
                }
            )
        for hw in spec.hardware:
            lines.append(
                {
                    "partId": hw.get("sku") or hw["partName"],
                    "partName": hw["partName"],
                    "material": "hardware",
                    "length": None,
                    "width": None,
                    "thickness": None,
                    "quantity": hw.get("quantity", 1),
                    "edgeBanding": False,
                    "hardware": True,
                    "cost": None,
                    "vendorNeutralId": hw.get("vendorNeutralId"),
                }
            )
        payload = {
            "productId": spec.productId,
            "engineeringHash": spec.engineering_hash(),
            "lines": lines,
        }
        payload["bomHash"] = stable_hash(lines)
        return payload


class CostEngine:
    def quote(self, spec: CabinetSpec, bom: dict[str, Any], *, margin: float = 0.4, nesting: dict[str, Any] | None = None) -> dict[str, Any]:
        material_cost = 0.0
        processing = 0.0
        edge_m = 0.0
        for line in bom["lines"]:
            if line.get("hardware"):
                continue
            qty = float(line.get("quantity") or 1)
            length = float(line.get("length") or 0) / 1000.0
            width = float(line.get("width") or 0) / 1000.0
            area = length * width * qty
            eng_mat = map_cabinet_material(str(spec.material)).get("engineering") or spec.material
            material_cost += area * MATERIAL_PRICE_PER_M2.get(eng_mat, MATERIAL_PRICE_PER_M2.get(spec.material, 300.0))
            processing += PROCESSING_CUT_PER_PART * qty
            if line.get("edgeBanding") or line.get("edgeBandingEdges"):
                edges = line.get("edgeBandingEdges")
                if edges:
                    from fox3d.manufacturing import edge_banding_length_mm

                    perim = edge_banding_length_mm(float(line.get("length") or 0), float(line.get("width") or 0), edges) / 1000.0 * qty
                else:
                    perim = 2 * (length + width) * qty
                edge_m += perim
                processing += perim * PROCESSING_EDGE_PER_M
            processing += 8 * PROCESSING_DRILL_PER_HOLE * qty  # typical cam/dowel holes
        hardware_cost = 0.0
        for line in bom["lines"]:
            if not line.get("hardware"):
                continue
            hardware_cost += HARDWARE_PRICE.get(line["partId"], HARDWARE_PRICE.get(line["partName"], 10.0)) * float(line["quantity"])
        banding_cost = edge_m * EDGE_BANDING_PER_M
        volume_m3 = (spec.width * spec.height * spec.depth) / 1e9
        assembly = max(0.5, volume_m3 * 8) * ASSEMBLY_PER_HOUR
        packaging = PACKAGING_BASE + volume_m3 * 120
        shipping = 150 + volume_m3 * 400
        waste_cost = 0.0
        if nesting:
            waste_cost = float(nesting.get("wasteAreaM2") or 0) * 80.0
            material_cost = material_cost  # panel area remains; waste called out separately
        estimated = material_cost + banding_cost + hardware_cost + processing + assembly + packaging + waste_cost
        suggested = estimated * (1 + margin)
        for line in bom["lines"]:
            if line.get("hardware"):
                line["cost"] = HARDWARE_PRICE.get(line["partId"], 10.0) * float(line["quantity"])
        return {
            "MaterialCost": round(material_cost + banding_cost, 2),
            "HardwareCost": round(hardware_cost, 2),
            "ProcessingCost": round(processing, 2),
            "AssemblyCost": round(assembly, 2),
            "PackagingCost": round(packaging, 2),
            "ShippingEstimate": round(shipping, 2),
            "estimatedCost": round(estimated, 2),
            "margin": margin,
            "suggestedPrice": round(suggested, 2),
            "currency": "TWD",
            "engineeringHash": bom["engineeringHash"],
            "SheetWasteCost": round(waste_cost, 2),
            "edgeBandingLengthM": round(edge_m, 3),
        }


class CADAdapter:
    """Interface only. Same engineering JSON as Blender/BOM. No live CAD control."""

    name = "CADAdapter"

    def export(self, spec: CabinetSpec, bom: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "format": "ManufacturingManifest",
            "engineeringHash": spec.engineering_hash(),
            "liveMachineControl": False,
            "requiresApproval": True,
            "dxfInterface": True,
            "parts": [{"partId": line.get("partId"), "partType": line.get("partType"), "cut": {"length": line.get("length"), "width": line.get("width"), "thickness": line.get("thickness")}} for line in bom["lines"] if not line.get("hardware")],
        }


class CAMAdapter:
    """Interface only — no live CNC. Requires a later approval to drive a machine."""

    name = "CAMAdapter"

    def export(self, spec: CabinetSpec, bom: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "format": "ManufacturingManifest",
            "reserved": ["DXF", "SVG", "CSV", "BOM", "Drilling data", "Cutting data"],
            "liveMachineControl": False,
            "requiresApproval": True,
            "engineeringHash": spec.engineering_hash(),
            "parts": [
                {
                    "partName": line["partName"],
                    "cut": {"length": line.get("length"), "width": line.get("width"), "thickness": line.get("thickness")},
                    "drill": [],
                }
                for line in bom["lines"]
                if not line.get("hardware")
            ],
        }


class CNCAdapter(CAMAdapter):
    name = "CNCAdapter"


class NestingAdapter(CAMAdapter):
    name = "NestingAdapter"

    def export(self, spec: CabinetSpec, bom: dict[str, Any]) -> dict[str, Any]:
        manifest = super().export(spec, bom)
        from fox3d.manufacturing import NestingEngine

        nested = NestingEngine().nest(bom, material=str(spec.material), thickness=float(spec.boardThickness))
        manifest["nesting"] = nested
        manifest["liveMachineControl"] = False
        return manifest


def _named_mm(prefix: str, text: str) -> float | None:
    m = re.search(prefix + r"\s*(\d+(?:\.\d+)?)\s*(cm|公分|厘米|mm|毫米)?", text, re.I)
    if not m:
        return None
    n = float(m.group(1))
    unit = (m.group(2) or "cm").lower()
    return n if unit in {"mm", "毫米"} else n * 10.0


def parse_design_intent(text: str, *, tenant_id: str) -> dict[str, Any]:
    """Deterministic NL → DesignIntent JSON. LLM may call this; it does not talk to Blender."""
    named_w = _named_mm("寬", text)
    named_h = _named_mm("高", text)
    named_d = _named_mm("深", text)
    wall = None if named_w else _first_mm(text, (r"(\d+(?:\.\d+)?)\s*(?:cm|公分|厘米)", 10.0), (r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)", 1.0))
    tv = _search_float(r"(\d+)\s*(?:吋|寸|\"|inch)", text)
    robot = bool(re.search(r"掃地|機器人|robot", text, re.I))
    cream = bool(re.search(r"奶油", text))
    kind: str = "CABINET"
    unknown_fields: list[str] = []
    needs_input: list[str] = []
    if re.search(r"電視櫃|电视柜|TV", text, re.I):
        kind = "TV_CABINET"
    elif re.search(r"衣櫃|衣櫥|wardrobe", text, re.I):
        kind = "WARDROBE"
    elif re.search(r"鞋櫃|shoe", text, re.I):
        kind = "SHOE_CABINET"
    elif re.search(r"展示", text):
        kind = "DISPLAY_CABINET"
    elif re.search(r"書櫃|book", text, re.I):
        kind = "BOOKCASE"
    elif re.search(r"吊櫃|wall cabinet", text, re.I):
        kind = "KITCHEN_WALL"
    elif re.search(r"廚|kitchen", text, re.I):
        kind = "KITCHEN_BASE"
    elif re.search(r"收納|儲物|storage", text, re.I):
        kind = "STORAGE_CABINET"
    else:
        unknown_fields.append("productType")
    width = float(named_w or TYPE_DEFAULTS[kind]["width"])
    metadata: dict[str, Any] = {"style": "cream" if cream else "neutral", "sourceText": text}
    if re.search(r"白|木紋", text):
        metadata["style"] = "white_wood"
        metadata["materialHint"] = "WOOD_WHITE"
    if tv:
        metadata["tvInches"] = tv
        width = max(width, tv_width_mm(tv) + 200)
    if wall:
        metadata["wallWidth"] = wall
        width = min(width, wall)
    width = min(width, MAX_PANEL_W)
    params: dict[str, Any] = {"width": width, "metadata": metadata}
    if metadata.get("materialHint") == "WOOD_WHITE":
        params["material"] = "WOOD_WHITE"
    if named_h:
        params["height"] = named_h
    if named_d:
        params["depth"] = named_d
    if re.search(r"雙門|兩門|2門", text):
        params["doorCount"] = 2
    if re.search(r"四層|4層|四層板", text):
        params["shelfCount"] = 4
    else:
        m_shelf = re.search(r"(\d+)\s*層", text)
        if m_shelf:
            params["shelfCount"] = int(m_shelf.group(1))
    if kind == "TV_CABINET" and robot:
        params["legs"] = True
        params["plinthHeight"] = 100
    if wall:
        params["wallWidth"] = wall
    budget = _search_float(r"預算\s*(\d+)", text)
    if budget is None:
        budget = _search_float(r"(\d+)\s*(?:元|塊|TWD)", text)
    storage_req = []
    if re.search(r"吊衣|掛衣|hang", text, re.I):
        storage_req.append("hanging")
    if re.search(r"抽屜|drawer", text, re.I):
        storage_req.append("drawers")
    if re.search(r"層板|shelf", text, re.I):
        storage_req.append("shelves")
    if re.search(r"牆|wall", text, re.I) and not wall:
        needs_input.append("wallWidth")
    if named_w is None and wall is None:
        unknown_fields.append("exactWidth")
    room = None
    if re.search(r"客廳|living", text, re.I):
        room = "living"
    elif re.search(r"臥|bedroom", text, re.I):
        room = "bedroom"
    elif re.search(r"廚|kitchen", text, re.I):
        room = "kitchen"
    elif re.search(r"玄關|entry", text, re.I):
        room = "entry"
    return {
        "tenantId": tenant_id,
        "kind": kind,
        "params": params,
        "notes": text,
        "llmMayNotSetMillimetresDirectly": True,
        "roomTarget": room,
        "wallTarget": wall,
        "purpose": kind,
        "style": metadata.get("style"),
        "budget": budget,
        "storageRequirements": storage_req,
        "unknownFields": unknown_fields,
        "needsInput": needs_input,
    }


def _search_float(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.I)
    return float(m.group(1)) if m else None


def _first_mm(*args: Any) -> float | None:
    text = None
    # parse_design_intent calls _first_mm(text, (pat, mul), ...)
    return_val = None
    if not args:
        return None
    text = args[0]
    for pat, mul in args[1:]:
        m = re.search(pat, text, re.I)
        if m:
            return_val = float(m.group(1)) * mul
            break
    return return_val
