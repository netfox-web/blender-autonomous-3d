"""Hardware, drilling/cutting manifests, guillotine nesting, quotes, manufacturing gate.

Live CNC is never enabled. Manufacturing stops at WAITING_APPROVAL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from fox3d.ids import new_id, stable_hash
from fox3d.parametric import MAX_PANEL_H, MAX_PANEL_W, map_cabinet_material

GATE_STATES = ("ENGINEERING_VALID", "COSTED", "PREVIEWED", "WAITING_APPROVAL")
LIVE_CNC_FORBIDDEN = "LIVE_CNC"

HARDWARE_REGISTRY: dict[str, dict[str, Any]] = {
    "HW_HINGE_CLIP_110": {
        "category": "hinge",
        "openingAngle": 110,
        "doorThicknessMin": 15,
        "doorThicknessMax": 22,
        "cupDiameter": 35,
        "cupDepth": 13,
        "vendorNeutral": True,
        "price": 25.0,
    },
    "HW_RAIL_450": {
        "category": "rail",
        "minDrawerWidth": 200,
        "maxDrawerWidth": 900,
        "minDepth": 250,
        "extension": 450,
        "vendorNeutral": True,
        "price": 80.0,
    },
    "HW_HANDLE_BAR": {"category": "handle", "vendorNeutral": True, "price": 35.0},
    "HW_CAM_LOCK_15": {"category": "connector", "boardThicknessMin": 15, "boardThicknessMax": 25, "diameter": 15, "vendorNeutral": True, "price": 3.0},
    "HW_DOWEL_8": {"category": "connector", "diameter": 8, "depth": 25, "vendorNeutral": True, "price": 0.5},
    "HW_LEG_100": {"category": "leg", "heightMin": 80, "heightMax": 150, "vendorNeutral": True, "price": 40.0},
}

SHEET_MATERIALS: dict[str, dict[str, Any]] = {
    "PB_18_WHITE": {"length": 2440, "width": 1220, "thickness": 18, "grain": "length", "costPerSheet": 850.0, "costPerM2": 280.0, "texture": "WOOD_WHITE", "engineering": "particle_board"},
    "PB_18_OAK": {"length": 2440, "width": 1220, "thickness": 18, "grain": "length", "costPerSheet": 980.0, "costPerM2": 320.0, "texture": "WOOD_OAK", "engineering": "particle_board"},
    "PB_18_WALNUT": {"length": 2440, "width": 1220, "thickness": 18, "grain": "length", "costPerSheet": 1100.0, "costPerM2": 360.0, "texture": "WOOD_WALNUT", "engineering": "particle_board"},
    "MDF_18_BLACK": {"length": 2440, "width": 1220, "thickness": 18, "grain": "none", "costPerSheet": 920.0, "costPerM2": 310.0, "texture": "WOOD_BLACK", "engineering": "mdf"},
    "PB_18_CREAM": {"length": 2440, "width": 1220, "thickness": 18, "grain": "length", "costPerSheet": 900.0, "costPerM2": 290.0, "texture": "WOOD_CREAM", "engineering": "particle_board"},
    "PB_25": {"length": 2440, "width": 1220, "thickness": 25, "grain": "length", "costPerSheet": 1200.0, "costPerM2": 400.0, "texture": "WOOD_WHITE", "engineering": "particle_board"},
}

WOOD_TO_SHEET = {
    "WOOD_WHITE": "PB_18_WHITE",
    "WOOD_OAK": "PB_18_OAK",
    "WOOD_WALNUT": "PB_18_WALNUT",
    "WOOD_BLACK": "MDF_18_BLACK",
    "WOOD_CREAM": "PB_18_CREAM",
}


class HardwareRegistry:
    def list(self) -> list[str]:
        return list(HARDWARE_REGISTRY)

    def get(self, sku: str) -> dict[str, Any]:
        return dict(HARDWARE_REGISTRY[sku])

    def assign(self, spec: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if spec.doorCount:
            items.append({"sku": "HW_HINGE_CLIP_110", "quantity": spec.doorCount * 2, **HARDWARE_REGISTRY["HW_HINGE_CLIP_110"]})
            if spec.handles:
                items.append({"sku": "HW_HANDLE_BAR", "quantity": spec.doorCount, **HARDWARE_REGISTRY["HW_HANDLE_BAR"]})
        if spec.drawerCount:
            items.append({"sku": "HW_RAIL_450", "quantity": spec.drawerCount, **HARDWARE_REGISTRY["HW_RAIL_450"]})
            if spec.handles:
                items.append({"sku": "HW_HANDLE_BAR", "quantity": spec.drawerCount, **HARDWARE_REGISTRY["HW_HANDLE_BAR"]})
        items.append({"sku": "HW_CAM_LOCK_15", "quantity": 16, **HARDWARE_REGISTRY["HW_CAM_LOCK_15"]})
        items.append({"sku": "HW_DOWEL_8", "quantity": 16, **HARDWARE_REGISTRY["HW_DOWEL_8"]})
        if spec.legs:
            items.append({"sku": "HW_LEG_100", "quantity": 4, **HARDWARE_REGISTRY["HW_LEG_100"]})
        return items

    def compatibility(self, spec: Any) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        t = float(spec.boardThickness)
        hinge = HARDWARE_REGISTRY["HW_HINGE_CLIP_110"]
        if spec.doorCount and not (hinge["doorThicknessMin"] <= t <= hinge["doorThicknessMax"]):
            issues.append({"code": "HW_HINGE_THICKNESS", "message": f"door thickness {t}mm incompatible with {hinge['doorThicknessMin']}-{hinge['doorThicknessMax']}mm hinge", "severity": "error"})
        rail = HARDWARE_REGISTRY["HW_RAIL_450"]
        if spec.drawerCount:
            from fox3d.parametric import _bay_count

            inner_w = spec.width - 2 * t
            bays = int((spec.constraints or {}).get("bays") or _bay_count(inner_w, 800))
            drawer_w = inner_w / max(bays, 1) - 26
            if drawer_w < rail["minDrawerWidth"] or drawer_w > rail["maxDrawerWidth"] or spec.depth < rail["minDepth"]:
                issues.append({"code": "HW_RAIL_FIT", "message": "drawer rail will not fit carcass", "severity": "error"})
        cam = HARDWARE_REGISTRY["HW_CAM_LOCK_15"]
        if not (cam["boardThicknessMin"] <= t <= cam["boardThicknessMax"]):
            issues.append({"code": "HW_CONNECTOR_THICKNESS", "message": f"board {t}mm outside cam lock range", "severity": "error"})
        return issues


class SheetMaterialRegistry:
    def list(self) -> list[str]:
        return list(SHEET_MATERIALS)

    def get(self, sku: str) -> dict[str, Any]:
        return dict(SHEET_MATERIALS[sku])

    def for_cabinet_material(self, name: str, *, thickness: float = 18) -> dict[str, Any]:
        mapped = map_cabinet_material(name)
        sku = WOOD_TO_SHEET.get(mapped.get("code") or "", "PB_18_WHITE")
        if abs(thickness - 25) < 0.5:
            sku = "PB_25"
        rec = dict(SHEET_MATERIALS[sku])
        rec["sku"] = sku
        return rec


def edge_banding_edges(role: str) -> dict[str, bool]:
    if role in {"door", "drawer_front"}:
        return {"front": True, "back": True, "left": True, "right": True}
    if role in {"shelf", "top", "bottom", "h_partition"}:
        return {"front": True, "back": False, "left": False, "right": False}
    if role in {"left", "right", "divider"}:
        return {"front": True, "back": False, "left": False, "right": False}
    if role in {"top_filler", "side_filler", "plinth", "toe_kick"}:
        return {"front": True, "back": False, "left": True, "right": True}
    return {"front": False, "back": False, "left": False, "right": False}


def edge_banding_length_mm(length: float, width: float, edges: dict[str, bool]) -> float:
    total = 0.0
    if edges.get("front"):
        total += length
    if edges.get("back"):
        total += length
    if edges.get("left"):
        total += width
    if edges.get("right"):
        total += width
    return total


class DrillHole(BaseModel):
    holeId: str = Field(default_factory=new_id)
    partId: str
    face: Literal["front", "back", "left", "right", "top", "bottom"]
    x: float
    y: float
    diameter: float
    depth: float
    coordinateSystem: str = "part-local-mm"
    purpose: str = ""


class DrillingManifest(BaseModel):
    productId: str
    engineeringHash: str
    holes: list[DrillHole] = Field(default_factory=list)

    def manifest_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class CutPanel(BaseModel):
    partId: str
    partName: str
    length: float
    width: float
    thickness: float
    grainDirection: Literal["length", "width", "none"] = "length"
    quantity: int = 1


class CuttingManifest(BaseModel):
    productId: str
    engineeringHash: str
    panels: list[CutPanel] = Field(default_factory=list)

    def manifest_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


def build_drilling_manifest(spec: Any, bom: dict[str, Any]) -> DrillingManifest:
    holes: list[DrillHole] = []
    t = float(spec.boardThickness)
    for line in bom.get("lines") or []:
        if line.get("hardware"):
            continue
        role = line.get("partType") or line.get("role")
        part_id = str(line.get("partId") or line.get("partName"))
        length = float(line.get("length") or 0)
        width = float(line.get("width") or 0)
        side_face: Literal["left", "right"] = "left" if role == "left" else "right"
        if role in {"left", "right"}:
            usable = max(0.0, length - 80)
            n = max(1, int(usable // 64))
            for i in range(n):
                holes.append(DrillHole(partId=part_id, face=side_face, x=37, y=40 + i * 64, diameter=5, depth=10, purpose="shelf_pin"))
            for y in (30.0, length - 30):
                holes.append(DrillHole(partId=part_id, face=side_face, x=width / 2, y=y, diameter=8, depth=25, purpose="dowel"))
                holes.append(DrillHole(partId=part_id, face=side_face, x=width / 2 + 32, y=y, diameter=15, depth=14, purpose="cam"))
        if role == "door":
            holes.append(DrillHole(partId=part_id, face="back", x=22, y=100, diameter=35, depth=13, purpose="hinge_cup"))
            holes.append(DrillHole(partId=part_id, face="back", x=22, y=max(100.0, length - 100), diameter=35, depth=13, purpose="hinge_cup"))
        if role == "drawer_front":
            holes.append(DrillHole(partId=part_id, face="back", x=width / 2, y=length / 2, diameter=5, depth=12, purpose="handle"))
    _ = t
    return DrillingManifest(productId=spec.productId, engineeringHash=spec.engineering_hash(), holes=holes)


def build_cutting_manifest(spec: Any, bom: dict[str, Any]) -> CuttingManifest:
    panels: list[CutPanel] = []
    for line in bom.get("lines") or []:
        if line.get("hardware"):
            continue
        length = float(line.get("length") or 0)
        width = float(line.get("width") or 0)
        if length <= 0 or width <= 0:
            continue
        role = str(line.get("partType") or line.get("role") or "")
        grain: Literal["length", "width", "none"] = "none"
        if role in {"top", "bottom", "shelf", "door", "drawer_front", "h_partition"}:
            grain = "length"
        panels.append(
            CutPanel(
                partId=str(line.get("partId") or line.get("partName")),
                partName=str(line.get("partName")),
                length=length,
                width=width,
                thickness=float(line.get("thickness") or spec.boardThickness),
                grainDirection=grain,
                quantity=int(line.get("quantity") or 1),
            )
        )
    return CuttingManifest(productId=spec.productId, engineeringHash=spec.engineering_hash(), panels=panels)


@dataclass
class _Free:
    x: float
    y: float
    w: float
    h: float


class NestingEngine:
    """Deterministic guillotine / first-fit decreasing baseline. Not a CAM driver."""

    def nest(
        self,
        bom: dict[str, Any],
        *,
        material: str = "WOOD_WHITE",
        thickness: float = 18,
        kerf_mm: float = 4.0,
        trim_mm: float = 10.0,
        sheet: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sheetspec = sheet or SheetMaterialRegistry().for_cabinet_material(material, thickness=thickness)
        sheet_w = float(sheetspec.get("length") or MAX_PANEL_W)
        sheet_h = float(sheetspec.get("width") or MAX_PANEL_H)
        grain_axis = str(sheetspec.get("grain") or "length")
        parts: list[dict[str, Any]] = []
        for line in bom.get("lines") or []:
            if line.get("hardware"):
                continue
            length = float(line.get("length") or 0)
            width = float(line.get("width") or 0)
            if length < 1 or width < 1:
                continue
            qty = int(line.get("quantity") or 1)
            role = str(line.get("partType") or line.get("role") or "")
            grain = "length" if role in {"top", "bottom", "shelf", "door", "drawer_front", "h_partition"} else "none"
            if grain_axis == "none":
                grain = "none"
            for i in range(qty):
                parts.append(
                    {
                        "partId": f"{line.get('partId') or line.get('partName')}#{i+1}",
                        "partName": line.get("partName"),
                        "length": length,
                        "width": width,
                        "grain": grain,
                    }
                )
        parts.sort(key=lambda p: (-max(p["length"], p["width"]), -min(p["length"], p["width"]), p["partId"]))
        usable_w = sheet_w - 2 * trim_mm
        usable_h = sheet_h - 2 * trim_mm
        sheets: list[dict[str, Any]] = []
        remaining = list(parts)
        unplaceable: list[str] = []
        while remaining:
            free = [_Free(trim_mm, trim_mm, usable_w, usable_h)]
            placements: list[dict[str, Any]] = []
            leftover: list[dict[str, Any]] = []
            for part in remaining:
                placed = self._place(part, free, kerf_mm, grain_axis)
                if placed:
                    placements.append(placed)
                else:
                    leftover.append(part)
            if not placements:
                unplaceable.extend(p["partId"] for p in leftover)
                break
            used = sum(p["w"] * p["h"] for p in placements)
            area = sheet_w * sheet_h
            sheets.append(
                {
                    "index": len(sheets),
                    "placements": placements,
                    "usedAreaMm2": used,
                    "utilization": round(used / area, 4),
                }
            )
            remaining = leftover
        used_total = sum(s["usedAreaMm2"] for s in sheets)
        sheet_area = sheet_w * sheet_h
        total_area = sheet_area * max(len(sheets), 1)
        waste = max(0.0, total_area - used_total)
        result = {
            "sheetSku": sheetspec.get("sku") or "PB_18_WHITE",
            "sheetMm": [sheet_w, sheet_h],
            "thickness": thickness,
            "kerfMm": kerf_mm,
            "trimMm": trim_mm,
            "grainConstraint": grain_axis,
            "sheetCount": len(sheets),
            "usedAreaMm2": used_total,
            "usedAreaM2": round(used_total / 1e6, 4),
            "wasteAreaMm2": waste,
            "wasteAreaM2": round(waste / 1e6, 4),
            "utilization": round(used_total / total_area, 4) if total_area else 0,
            "sheets": sheets,
            "unplaceable": unplaceable,
            "liveMachineControl": False,
        }
        result["svg"] = self.to_svg(result)
        result["dxfInterface"] = self.to_dxf_interface(result)
        result["nestingHash"] = stable_hash({k: result[k] for k in ("sheetMm", "kerfMm", "trimMm", "grainConstraint", "sheets")})
        return result

    def _orientations(self, part: dict[str, Any], grain_axis: str) -> list[tuple[float, float, bool]]:
        L, W = float(part["length"]), float(part["width"])
        grain = part.get("grain") or "none"
        if grain_axis == "none" or grain == "none":
            opts = [(L, W, False)]
            if abs(L - W) > 0.5:
                opts.append((W, L, True))
            return opts
        # Sheet grain along X (length). Part grain "length" must align L with X.
        if grain == "length":
            return [(L, W, False)]
        if grain == "width":
            return [(W, L, True)]
        return [(L, W, False), (W, L, True)]

    def _place(self, part: dict[str, Any], free: list[_Free], kerf: float, grain_axis: str) -> dict[str, Any] | None:
        for idx, fr in enumerate(list(free)):
            for pw, ph, rotated in self._orientations(part, grain_axis):
                if pw <= fr.w + 1e-6 and ph <= fr.h + 1e-6:
                    placement = {
                        "partId": part["partId"],
                        "partName": part["partName"],
                        "x": round(fr.x, 3),
                        "y": round(fr.y, 3),
                        "w": round(pw, 3),
                        "h": round(ph, 3),
                        "rotated": rotated,
                    }
                    leftover = self._split(fr, pw, ph, kerf)
                    free.pop(idx)
                    free.extend(leftover)
                    free.sort(key=lambda f: (f.y, f.x, f.w * f.h))
                    return placement
        return None

    def _split(self, fr: _Free, pw: float, ph: float, kerf: float) -> list[_Free]:
        right_w = fr.w - pw - kerf
        top_h = fr.h - ph - kerf
        a: list[_Free] = []
        if right_w >= 1:
            a.append(_Free(fr.x + pw + kerf, fr.y, right_w, ph))
        if top_h >= 1:
            a.append(_Free(fr.x, fr.y + ph + kerf, fr.w, top_h))
        b: list[_Free] = []
        if top_h >= 1:
            b.append(_Free(fr.x, fr.y + ph + kerf, pw, top_h))
        if right_w >= 1:
            b.append(_Free(fr.x + pw + kerf, fr.y, right_w, fr.h))
        area_a = sum(f.w * f.h for f in a)
        area_b = sum(f.w * f.h for f in b)
        return a if area_a >= area_b else b

    def to_svg(self, result: dict[str, Any]) -> str:
        sw, sh = result["sheetMm"]
        parts = []
        for sheet in result.get("sheets") or []:
            idx = sheet["index"]
            parts.append(f'<g id="sheet-{idx}" transform="translate(0,{idx * (sh + 40)})">')
            parts.append(f'<rect x="0" y="0" width="{sw}" height="{sh}" fill="none" stroke="#333"/>')
            for p in sheet["placements"]:
                parts.append(
                    f'<rect x="{p["x"]}" y="{p["y"]}" width="{p["w"]}" height="{p["h"]}" fill="#cde" stroke="#246"/>'
                    f'<title>{p["partId"]}</title></rect>'
                )
            parts.append("</g>")
        height = (sh + 40) * max(len(result.get("sheets") or []), 1)
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {sw} {height}">{"".join(parts)}</svg>'

    def to_dxf_interface(self, result: dict[str, Any]) -> dict[str, Any]:
        lines: list[dict[str, Any]] = []
        for sheet in result.get("sheets") or []:
            ox = 0.0
            oy = sheet["index"] * (result["sheetMm"][1] + 40)
            sw, sh = result["sheetMm"]
            lines.append({"layer": "SHEET", "start": [ox, oy], "end": [ox + sw, oy]})
            lines.append({"layer": "SHEET", "start": [ox + sw, oy], "end": [ox + sw, oy + sh]})
            lines.append({"layer": "SHEET", "start": [ox + sw, oy + sh], "end": [ox, oy + sh]})
            lines.append({"layer": "SHEET", "start": [ox, oy + sh], "end": [ox, oy]})
            for p in sheet["placements"]:
                x, y, w, h = p["x"] + ox, p["y"] + oy, p["w"], p["h"]
                box = [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]
                for a, b in zip(box, box[1:]):
                    lines.append({"layer": "PART", "partId": p["partId"], "start": a, "end": b})
        return {"format": "DXF-lines", "units": "mm", "liveMachineControl": False, "lines": lines}

    def assert_valid(self, result: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        sw, sh = result["sheetMm"]
        for sheet in result.get("sheets") or []:
            placed = sheet["placements"]
            for p in placed:
                if p["x"] < -1e-6 or p["y"] < -1e-6 or p["x"] + p["w"] > sw + 1e-6 or p["y"] + p["h"] > sh + 1e-6:
                    errors.append(f"out of bounds {p['partId']}")
            for i, a in enumerate(placed):
                for b in placed[i + 1 :]:
                    if _overlap(a, b):
                        errors.append(f"overlap {a['partId']} {b['partId']}")
        return errors


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return not (a["x"] + a["w"] <= b["x"] + 1e-6 or b["x"] + b["w"] <= a["x"] + 1e-6 or a["y"] + a["h"] <= b["y"] + 1e-6 or b["y"] + b["h"] <= a["y"] + 1e-6)


class ManufacturingManifest(BaseModel):
    manifestId: str = Field(default_factory=new_id)
    productId: str
    version: int = 1
    engineeringHash: str
    bomHash: str
    drillingHash: str
    cuttingHash: str
    nestingHash: str
    approvalState: str = "ENGINEERING_VALID"
    liveMachineControl: bool = False
    requiresApproval: bool = True

    def manifest_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json", exclude={"manifestId"}))


class ManufacturingCandidateGate:
    def __init__(self) -> None:
        self.state = "ENGINEERING_VALID"

    def advance(self, target: str) -> str:
        if target == LIVE_CNC_FORBIDDEN or target == "LIVE_CNC":
            raise PermissionError("LIVE_CNC forbidden: Human Approval Gate only; liveMachineControl=false")
        if target not in GATE_STATES:
            raise ValueError(target)
        order = list(GATE_STATES)
        if order.index(target) < order.index(self.state):
            raise ValueError(f"cannot regress {self.state} -> {target}")
        self.state = target
        return self.state


class QuoteRecord(BaseModel):
    quoteId: str = Field(default_factory=new_id)
    version: int = 1
    engineeringHash: str
    bomHash: str
    nestingHash: str
    quoteHash: str = ""
    estimatedCost: float
    suggestedPrice: float
    margin: float
    currency: str = "TWD"
    breakdown: dict[str, Any] = Field(default_factory=dict)

    def bind(self) -> "QuoteRecord":
        self.quoteHash = stable_hash(
            {
                "engineeringHash": self.engineeringHash,
                "bomHash": self.bomHash,
                "nestingHash": self.nestingHash,
                "estimatedCost": self.estimatedCost,
                "margin": self.margin,
            }
        )
        return self

    def is_stale(self, *, engineering_hash: str, bom_hash: str, nesting_hash: str) -> bool:
        return self.engineeringHash != engineering_hash or self.bomHash != bom_hash or self.nestingHash != nesting_hash


class QuoteEngine:
    def quote(
        self,
        spec: Any,
        bom: dict[str, Any],
        nesting: dict[str, Any],
        *,
        margin: float = 0.4,
        drilling: DrillingManifest | None = None,
    ) -> QuoteRecord:
        sheet = SheetMaterialRegistry().for_cabinet_material(spec.material, thickness=spec.boardThickness)
        sheet_count = int(nesting.get("sheetCount") or 1)
        sheet_cost = sheet_count * float(sheet.get("costPerSheet") or 850)
        waste_cost = float(nesting.get("wasteAreaM2") or 0) * float(sheet.get("costPerM2") or 280) * 0.25
        edge_m = 0.0
        for line in bom.get("lines") or []:
            if line.get("hardware"):
                continue
            edges = line.get("edgeBandingEdges") or edge_banding_edges(str(line.get("partType") or line.get("role") or ""))
            length = float(line.get("length") or 0)
            width = float(line.get("width") or 0)
            edge_m += edge_banding_length_mm(length, width, edges) / 1000.0 * float(line.get("quantity") or 1)
        from fox3d.parametric import EDGE_BANDING_PER_M, PROCESSING_CUT_PER_PART, PROCESSING_DRILL_PER_HOLE, PROCESSING_EDGE_PER_M, HARDWARE_PRICE as HW

        banding_cost = edge_m * EDGE_BANDING_PER_M
        hardware_cost = 0.0
        for line in bom.get("lines") or []:
            if line.get("hardware"):
                hardware_cost += HW.get(line.get("partId"), HW.get(line.get("partName"), 10.0)) * float(line.get("quantity") or 1)
        hole_n = len(drilling.holes) if drilling else 8 * max(1, len([ln for ln in bom.get("lines") or [] if not ln.get("hardware")]))
        panel_n = len([ln for ln in bom.get("lines") or [] if not ln.get("hardware")])
        cutting_cost = panel_n * PROCESSING_CUT_PER_PART
        drilling_cost = hole_n * PROCESSING_DRILL_PER_HOLE
        edge_proc = edge_m * PROCESSING_EDGE_PER_M
        processing = cutting_cost + drilling_cost + edge_proc
        volume_m3 = (spec.width * spec.height * spec.depth) / 1e9
        from fox3d.parametric import ASSEMBLY_PER_HOUR, PACKAGING_BASE

        assembly = max(0.5, volume_m3 * 8) * ASSEMBLY_PER_HOUR
        packaging = PACKAGING_BASE + volume_m3 * 120
        estimated = sheet_cost + waste_cost + banding_cost + hardware_cost + processing + assembly + packaging
        suggested = estimated * (1 + margin)
        rec = QuoteRecord(
            engineeringHash=spec.engineering_hash(),
            bomHash=str(bom.get("bomHash") or stable_hash(bom.get("lines") or [])),
            nestingHash=str(nesting.get("nestingHash") or ""),
            estimatedCost=round(estimated, 2),
            suggestedPrice=round(suggested, 2),
            margin=margin,
            breakdown={
                "SheetCost": round(sheet_cost, 2),
                "SheetWasteCost": round(waste_cost, 2),
                "EdgeBandingCost": round(banding_cost, 2),
                "HardwareCost": round(hardware_cost, 2),
                "DrillingCost": round(drilling_cost, 2),
                "CuttingCost": round(cutting_cost, 2),
                "ProcessingCost": round(processing, 2),
                "AssemblyCost": round(assembly, 2),
                "PackagingCost": round(packaging, 2),
                "edgeBandingLengthM": round(edge_m, 3),
                "sheetCount": sheet_count,
                "utilization": nesting.get("utilization"),
            },
        )
        return rec.bind()


def build_manufacturing_pack(spec: Any, bom: dict[str, Any], *, kerf_mm: float = 4.0, trim_mm: float = 10.0) -> dict[str, Any]:
    drilling = build_drilling_manifest(spec, bom)
    cutting = build_cutting_manifest(spec, bom)
    nesting = NestingEngine().nest(bom, material=str(spec.material), thickness=float(spec.boardThickness), kerf_mm=kerf_mm, trim_mm=trim_mm)
    quote = QuoteEngine().quote(spec, bom, nesting, drilling=drilling)
    manifest = ManufacturingManifest(
        productId=spec.productId,
        engineeringHash=spec.engineering_hash(),
        bomHash=str(bom.get("bomHash") or stable_hash(bom.get("lines") or [])),
        drillingHash=drilling.manifest_hash(),
        cuttingHash=cutting.manifest_hash(),
        nestingHash=str(nesting.get("nestingHash") or ""),
        approvalState="COSTED",
        liveMachineControl=False,
        requiresApproval=True,
    )
    return {
        "drilling": drilling.model_dump(mode="json"),
        "cutting": cutting.model_dump(mode="json"),
        "nesting": nesting,
        "quote": quote.model_dump(mode="json"),
        "manufacturing": manifest.model_dump(mode="json"),
        "manufacturingHash": manifest.manifest_hash(),
        "liveMachineControl": False,
    }
