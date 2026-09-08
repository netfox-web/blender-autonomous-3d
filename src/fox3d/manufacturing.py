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
    "HW_CASTER_50": {"category": "caster", "vendorNeutral": True, "price": 45.0},
    "HW_SCREW_M4": {"category": "screw", "vendorNeutral": True, "price": 0.4},
    "HW_BOLT_M6": {"category": "bolt", "vendorNeutral": True, "price": 1.2},
    "HW_BRACKET_L": {"category": "bracket", "vendorNeutral": True, "price": 8.0},
    "HW_HANGING_RAIL": {"category": "rail", "vendorNeutral": True, "price": 60.0},
}

CONNECTOR_RECIPES: dict[str, dict[str, Any]] = {
    "KD_CAM_DOWEL_V1": {
        "version": 1,
        "family": "KD_CAM_DOWEL",
        "connectors": ["HW_CAM_LOCK_15", "HW_DOWEL_8"],
        "tools": ["hex_key", "mallet"],
        "requiredTools": ["hex_key"],
        "compatibility": ["KD_CAM_DOWEL_V1", "KD_CAM_DOWEL_V2"],
        "vendorNeutral": True,
    },
    "KD_CAM_DOWEL_V2": {
        "version": 2,
        "family": "KD_CAM_DOWEL",
        "connectors": ["HW_CAM_LOCK_15", "HW_DOWEL_8"],
        "tools": ["hex_key"],
        "requiredTools": ["hex_key"],
        "compatibility": ["KD_CAM_DOWEL_V1", "KD_CAM_DOWEL_V2"],
        "vendorNeutral": True,
    },
    "KD_SCREW_V1": {
        "version": 1,
        "family": "KD_SCREW",
        "connectors": ["HW_SCREW_M4", "HW_BRACKET_L"],
        "tools": ["screwdriver"],
        "requiredTools": ["screwdriver"],
        "compatibility": ["KD_SCREW_V1"],
        "vendorNeutral": True,
    },
    "KD_BOLT_CASTER_V1": {
        "version": 1,
        "family": "KD_BOLT_CASTER",
        "connectors": ["HW_BOLT_M6", "HW_CASTER_50"],
        "tools": ["wrench"],
        "requiredTools": ["wrench"],
        "compatibility": ["KD_BOLT_CASTER_V1"],
        "vendorNeutral": True,
    },
}

DEFAULT_REMNANT_POLICY: dict[str, Any] = {
    "minWidthMm": 200.0,
    "minHeightMm": 200.0,
    "minAreaMm2": 60000.0,
    "requireSameMaterial": True,
    "requireSameThickness": True,
    "requireGrainCompatible": True,
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

    def parts_from_bom(self, bom: dict[str, Any], *, material: str = "WOOD_WHITE", thickness: float = 18, sheet: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        sheetspec = sheet or SheetMaterialRegistry().for_cabinet_material(material, thickness=thickness)
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
            grain = line.get("grain") or line.get("grainDirection") or ("length" if role in {"top", "bottom", "shelf", "door", "drawer_front", "h_partition"} else "none")
            if grain_axis == "none":
                grain = "none"
            for i in range(qty):
                parts.append(
                    {
                        "partId": f"{line.get('skuId') or bom.get('productId') or 'sku'}:{line.get('partId') or line.get('partName')}#{i+1}",
                        "partName": line.get("partName"),
                        "length": length,
                        "width": width,
                        "grain": grain,
                        "skuId": line.get("skuId") or bom.get("productId"),
                        "productVersion": line.get("productVersion") or bom.get("revision") or 1,
                        "bomLineId": line.get("bomLineId") or line.get("partId") or line.get("partName"),
                        "materialLotId": line.get("materialLotId"),
                    }
                )
        return parts

    def nest(
        self,
        bom: dict[str, Any],
        *,
        material: str = "WOOD_WHITE",
        thickness: float = 18,
        kerf_mm: float = 4.0,
        trim_mm: float = 10.0,
        sheet: dict[str, Any] | None = None,
        remnants: list[dict[str, Any]] | None = None,
        remnant_policy: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        sheetspec = sheet or SheetMaterialRegistry().for_cabinet_material(material, thickness=thickness)
        parts = self.parts_from_bom(bom, material=material, thickness=thickness, sheet=sheetspec)
        return self.nest_parts(
            parts,
            material=material,
            thickness=thickness,
            kerf_mm=kerf_mm,
            trim_mm=trim_mm,
            sheet=sheetspec,
            remnants=remnants,
            remnant_policy=remnant_policy,
            **kwargs,
        )

    def nest_parts(
        self,
        parts: list[dict[str, Any]],
        *,
        material: str = "WOOD_WHITE",
        thickness: float = 18,
        kerf_mm: float = 4.0,
        trim_mm: float = 10.0,
        sheet: dict[str, Any] | None = None,
        remnants: list[dict[str, Any]] | None = None,
        remnant_policy: dict[str, Any] | None = None,
        objective: str = "min_sheets",
        seed: str = "baseline",
        strategy: str = "guillotine",
        defects: list[dict[str, Any]] | None = None,
        material_lot_id: str | None = None,
    ) -> dict[str, Any]:
        sheetspec = sheet or SheetMaterialRegistry().for_cabinet_material(material, thickness=thickness)
        sheet_w = float(sheetspec.get("length") or MAX_PANEL_W)
        sheet_h = float(sheetspec.get("width") or MAX_PANEL_H)
        grain_axis = str(sheetspec.get("grain") or "length")
        policy = {**DEFAULT_REMNANT_POLICY, **(remnant_policy or {})}
        place_mode = "best_fit" if strategy in {"best_fit", "best_fit_decreasing"} else "first_fit"
        ordered = list(parts)
        if seed in {"baseline", "bfd"} or not seed:
            ordered = sorted(parts, key=lambda p: (-max(float(p["length"]), float(p["width"])), -min(float(p["length"]), float(p["width"])), str(p.get("partId"))))
        usable_w = sheet_w - 2 * trim_mm
        usable_h = sheet_h - 2 * trim_mm
        remnant_used: list[dict[str, Any]] = []
        remaining = list(ordered)
        grain_violations = 0
        if remnants:
            for rem in remnants:
                if remaining and self._remnant_compatible(rem, material, thickness, grain_axis, policy):
                    rem_grain = str(rem.get("grain") or grain_axis)
                    rem_defects = list(rem.get("defects") or [])
                    free = [_Free(0.0, 0.0, float(rem["w"]), float(rem["h"]))]
                    placed: list[dict[str, Any]] = []
                    leftover: list[dict[str, Any]] = []
                    for part in remaining:
                        hit = self._place(part, free, kerf_mm, rem_grain, defects=rem_defects, mode=place_mode)
                        if hit:
                            hit["skuId"] = part.get("skuId")
                            hit["productVersion"] = part.get("productVersion")
                            hit["bomLineId"] = part.get("bomLineId")
                            hit["materialLotId"] = rem.get("materialLotId") or part.get("materialLotId")
                            hit["remnantId"] = rem.get("remnantId")
                            hit["sourceKind"] = "remnant"
                            placed.append(hit)
                        else:
                            leftover.append(part)
                    if placed:
                        remnant_used.append(
                            {
                                "remnantId": rem.get("remnantId"),
                                "placements": placed,
                                "usedAreaMm2": sum(p["w"] * p["h"] for p in placed),
                                "grain": rem_grain,
                                "materialLotId": rem.get("materialLotId"),
                            }
                        )
                        remaining = leftover
        sheets: list[dict[str, Any]] = []
        unplaceable: list[str] = []
        lot_ids: set[str] = set()
        sheet_defects = list(defects or sheetspec.get("defects") or [])
        while remaining:
            free = [_Free(trim_mm, trim_mm, usable_w, usable_h)]
            placements: list[dict[str, Any]] = []
            leftover_parts: list[dict[str, Any]] = []
            lot_id = material_lot_id or (remaining[0].get("materialLotId") if remaining else None)
            if lot_id:
                lot_ids.add(str(lot_id))
            for part in remaining:
                placed = self._place(part, free, kerf_mm, grain_axis, defects=sheet_defects, mode=place_mode)
                if placed:
                    placed["skuId"] = part.get("skuId")
                    placed["productVersion"] = part.get("productVersion")
                    placed["bomLineId"] = part.get("bomLineId")
                    placed["materialLotId"] = lot_id or part.get("materialLotId")
                    placed["sourceKind"] = "sheet"
                    placements.append(placed)
                else:
                    leftover_parts.append(part)
            if not placements:
                unplaceable.extend(p["partId"] for p in leftover_parts)
                break
            used = sum(p["w"] * p["h"] for p in placements)
            area = sheet_w * sheet_h
            sheets.append(
                {
                    "index": len(sheets),
                    "placements": placements,
                    "usedAreaMm2": used,
                    "utilization": round(used / area, 4),
                    "freeRects": [{"x": f.x, "y": f.y, "w": f.w, "h": f.h} for f in free if f.w >= 1 and f.h >= 1],
                }
            )
            remaining = leftover_parts
        used_total = sum(s["usedAreaMm2"] for s in sheets) + sum(r["usedAreaMm2"] for r in remnant_used)
        sheet_area = sheet_w * sheet_h
        n_sheets = len(sheets)
        total_area = sheet_area * max(n_sheets, 1 if not remnant_used else 0) if n_sheets else (0.0 if remnant_used else sheet_area)
        if n_sheets == 0:
            total_area = 0.0
        waste_v2 = self._waste_v2(sheets, sheet_w, sheet_h, usable_w, usable_h, kerf_mm, trim_mm, policy)
        result = {
            "sheetSku": sheetspec.get("sku") or "PB_18_WHITE",
            "sheetMm": [sheet_w, sheet_h],
            "thickness": thickness,
            "kerfMm": kerf_mm,
            "trimMm": trim_mm,
            "grainConstraint": grain_axis,
            "sheetCount": n_sheets,
            "usedAreaMm2": used_total,
            "usedAreaM2": round(used_total / 1e6, 4),
            "partUsedArea": waste_v2["partUsedArea"],
            "kerfLossArea": waste_v2["kerfLossArea"],
            "trimLossArea": waste_v2["trimLossArea"],
            "reusableRemnantArea": waste_v2["reusableRemnantArea"],
            "trueScrapArea": waste_v2["trueScrapArea"],
            "utilizationRatio": waste_v2["utilizationRatio"],
            "reusableRemnantRatio": waste_v2["reusableRemnantRatio"],
            "trueWasteRatio": waste_v2["trueWasteRatio"],
            "areaConservationError": waste_v2["areaConservationError"],
            "wasteAreaMm2": waste_v2["trueScrapArea"],
            "wasteAreaM2": round(waste_v2["trueScrapArea"] / 1e6, 4),
            "utilization": waste_v2["utilizationRatio"],
            "sheets": sheets,
            "unplaceable": unplaceable,
            "remnantUsed": remnant_used,
            "savedNewSheetCount": None,
            "estimatedSavedSheetEquivalent": round(sum(r["usedAreaMm2"] for r in remnant_used) / max(sheet_area, 1), 4) if remnant_used else 0.0,
            "estimatedSavedSheetSource": "ESTIMATED",
            "remnantConsumedArea": sum(r["usedAreaMm2"] for r in remnant_used),
            "candidateRemnants": waste_v2["candidateRemnants"],
            "objective": objective,
            "seed": seed,
            "strategy": strategy,
            "grainViolations": grain_violations,
            "materialLotSplit": max(0, len(lot_ids) - 1),
            "materialLotIds": sorted(lot_ids),
            "defects": sheet_defects,
            "illegal": bool(unplaceable),
            "liveMachineControl": False,
        }
        result["svg"] = self.to_svg(result)
        result["dxfInterface"] = self.to_dxf_interface(result)
        result["nestingHash"] = stable_hash({k: result[k] for k in ("sheetMm", "kerfMm", "trimMm", "grainConstraint", "sheets", "remnantUsed", "seed", "objective", "strategy")})
        return result

    def _remnant_compatible(self, rem: dict[str, Any], material: str, thickness: float, grain_axis: str, policy: dict[str, Any]) -> bool:
        from fox3d.inventory import nestable, normalize_status

        if not nestable(rem):
            return False
        if normalize_status(rem.get("status")) in {"reserved", "consumed"} and not rem.get("allowReserved"):
            # reserved/consumed stock is not auto-nested unless caller marked allowReserved
            if normalize_status(rem.get("status")) == "consumed":
                return False
        if policy.get("requireSameThickness") and rem.get("thickness") is not None and abs(float(rem["thickness"]) - thickness) > 0.5:
            return False
        rem_mat = rem.get("materialCode") or rem.get("texture") or rem.get("material")
        if policy.get("requireSameMaterial") and rem_mat:
            mapped = str(map_cabinet_material(material).get("code") or material).upper()
            if str(rem_mat).upper() not in {mapped, str(material).upper()}:
                return False
        if policy.get("requireGrainCompatible") and rem.get("grain") and grain_axis not in {"none", None}:
            rem_grain = str(rem.get("grain") or "none")
            if rem_grain not in {"none", grain_axis}:
                return False
        return float(rem.get("w") or 0) >= 1 and float(rem.get("h") or 0) >= 1

    def _waste_v2(
        self,
        sheets: list[dict[str, Any]],
        sheet_w: float,
        sheet_h: float,
        usable_w: float,
        usable_h: float,
        kerf_mm: float,
        trim_mm: float,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        n = max(len(sheets), 0)
        sheet_total = sheet_w * sheet_h * n
        usable_total = usable_w * usable_h * n
        trim_loss = max(0.0, sheet_total - usable_total)
        part_used = sum(s.get("usedAreaMm2") or 0 for s in sheets)
        leftover = 0.0
        candidates: list[dict[str, Any]] = []
        scrap = 0.0
        reusable = 0.0
        for s in sheets:
            for fr in s.get("freeRects") or []:
                area = float(fr["w"]) * float(fr["h"])
                leftover += area
                if self.qualify_remnant(fr["w"], fr["h"], policy):
                    reusable += area
                    candidates.append({**fr, "sheetIndex": s["index"], "area": area})
                else:
                    scrap += area
        kerf_loss = max(0.0, usable_total - part_used - leftover)
        conserved = part_used + kerf_loss + trim_loss + leftover
        err = abs(conserved - sheet_total) if n else 0.0
        util = (part_used / sheet_total) if sheet_total else 1.0
        return {
            "partUsedArea": round(part_used, 3),
            "kerfLossArea": round(kerf_loss, 3),
            "trimLossArea": round(trim_loss, 3),
            "reusableRemnantArea": round(reusable, 3),
            "trueScrapArea": round(scrap + kerf_loss + trim_loss, 3),
            "utilizationRatio": round(util, 4),
            "reusableRemnantRatio": round((reusable / sheet_total) if sheet_total else 0.0, 4),
            "trueWasteRatio": round(((scrap + kerf_loss + trim_loss) / sheet_total) if sheet_total else 0.0, 4),
            "areaConservationError": round(err, 3),
            "candidateRemnants": candidates,
        }

    def qualify_remnant(self, w: float, h: float, policy: dict[str, Any] | None = None) -> bool:
        p = {**DEFAULT_REMNANT_POLICY, **(policy or {})}
        return float(w) >= float(p["minWidthMm"]) and float(h) >= float(p["minHeightMm"]) and (float(w) * float(h)) >= float(p["minAreaMm2"])

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

    def _hits_defect(self, x: float, y: float, w: float, h: float, defects: list[dict[str, Any]] | None) -> bool:
        box = {"x": x, "y": y, "w": w, "h": h}
        for d in defects or []:
            dx, dy = float(d.get("x") or 0), float(d.get("y") or 0)
            dw, dh = float(d.get("w") or 0), float(d.get("h") or 0)
            if dw >= 1 and dh >= 1 and _overlap(box, {"x": dx, "y": dy, "w": dw, "h": dh}):
                return True
        return False

    def _place(
        self,
        part: dict[str, Any],
        free: list[_Free],
        kerf: float,
        grain_axis: str,
        *,
        defects: list[dict[str, Any]] | None = None,
        mode: str = "first_fit",
    ) -> dict[str, Any] | None:
        hits: list[tuple[tuple, int, float, float, bool]] = []
        for idx, fr in enumerate(list(free)):
            for pw, ph, rotated in self._orientations(part, grain_axis):
                if pw <= fr.w + 1e-6 and ph <= fr.h + 1e-6 and not self._hits_defect(fr.x, fr.y, pw, ph, defects):
                    leftover_area = fr.w * fr.h - pw * ph
                    key = (leftover_area, fr.w * fr.h, fr.y, fr.x, idx)
                    hits.append((key, idx, pw, ph, rotated))
                    if mode != "best_fit":
                        break
            if hits and mode != "best_fit":
                break
        if not hits:
            return None
        hits.sort(key=lambda h: h[0])
        _key, idx, pw, ph, rotated = hits[0]
        fr = free[idx]
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
        true_scrap_m2 = float(nesting.get("trueScrapArea") or 0) / 1e6 if nesting.get("trueScrapArea") is not None else float(nesting.get("wasteAreaM2") or 0)
        remnant_m2 = float(nesting.get("reusableRemnantArea") or 0) / 1e6
        waste_cost = true_scrap_m2 * float(sheet.get("costPerM2") or 280) * 0.25
        remnant_credit = remnant_m2 * float(sheet.get("costPerM2") or 280) * 0.5
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
        estimated = sheet_cost + waste_cost - remnant_credit + banding_cost + hardware_cost + processing + assembly + packaging
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
                "RemnantCredit": round(remnant_credit, 2),
                "costSource": "CONFIG",
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


class RemnantInventory:
    """Remnant ledger over RemnantStore. Not a WMS. Consume-once reservation."""

    def __init__(self, store: Any | None = None, *, default_tenant: str = "default") -> None:
        from fox3d.inventory import InMemoryRemnantStore

        self.store = store or InMemoryRemnantStore()
        self.items: dict[str, dict[str, Any]] = self.store.as_dict()
        self.default_tenant = default_tenant
        self._durable = type(self.store).__name__ == "DurableRemnantStore"

    def _persist_label(self) -> str:
        return "durable-json" if self._durable else "in-process-ledger"

    def add_from_nesting(
        self,
        nesting: dict[str, Any],
        *,
        material: str,
        thickness: float,
        source_run: str,
        policy: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        material_lot_id: str | None = None,
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        from fox3d.infra import utcnow
        from fox3d.inventory import QUALITY_UPPER

        tid = tenant_id or self.default_tenant
        for rem in nesting.get("candidateRemnants") or []:
            rec = {
                "remnantId": new_id(),
                "tenantId": tid,
                "sourceNestingRun": source_run,
                "sourceRun": source_run,
                "material": material,
                "materialCode": map_cabinet_material(material).get("code"),
                "thickness": thickness,
                "w": rem["w"],
                "h": rem["h"],
                "grain": nesting.get("grainConstraint") or rem.get("grain") or "length",
                "location": f"sheet:{rem.get('sheetIndex')}",
                "status": "available",
                "qualityState": QUALITY_UPPER["available"],
                "reservedBy": None,
                "consumedBy": None,
                "createdAt": utcnow().isoformat(),
                "area": rem.get("area") or rem["w"] * rem["h"],
                "version": 1,
                "leaseToken": None,
                "reservedUntil": None,
                "materialLotId": material_lot_id or rem.get("materialLotId") or nesting.get("materialLotId"),
                "defects": list(rem.get("defects") or []),
                "persistence": self._persist_label(),
            }
            self.store.put(rec)
            created.append(rec)
        return created

    def available(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        from fox3d.inventory import normalize_status

        tid = tenant_id
        rows = list(self.items.values())
        if tid is not None:
            rows = [v for v in rows if v.get("tenantId") in {None, tid}]
        return [v for v in rows if normalize_status(v.get("status")) == "available"]

    def get(self, remnant_id: str, *, tenant_id: str) -> dict[str, Any]:
        return self.store.get(remnant_id, tenant_id=tenant_id)

    def set_quality(self, remnant_id: str, status: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        from fox3d.inventory import QUALITY_UPPER, normalize_status

        rec = self.items[remnant_id]
        if tenant_id is not None and rec.get("tenantId") not in {None, tenant_id}:
            raise PermissionError("tenant isolation: remnant")
        st = normalize_status(status)
        if st not in QUALITY_UPPER:
            raise ValueError(st)
        rec["status"] = st
        rec["qualityState"] = QUALITY_UPPER[st]
        rec["version"] = int(rec.get("version") or 1) + 1
        rec["persistence"] = self._persist_label()
        self.store.put(rec)
        return rec

    def reserve(
        self,
        remnant_id: str,
        *,
        by: str,
        version: int | None = None,
        lease_seconds: float | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        from datetime import timedelta

        from fox3d.infra import utcnow
        from fox3d.inventory import QUALITY_UPPER, lease_token, normalize_status

        rec = self.items[remnant_id]
        if tenant_id is not None and rec.get("tenantId") not in {None, tenant_id}:
            raise PermissionError("tenant isolation: remnant")
        if normalize_status(rec.get("status")) != "available":
            raise PermissionError(f"remnant {remnant_id} not available ({rec['status']})")
        current_v = int(rec.get("version") or 1)
        if version is not None and int(version) != current_v:
            raise PermissionError(f"stale remnant version {version} != {current_v}")
        rec["status"] = "reserved"
        rec["qualityState"] = QUALITY_UPPER["reserved"]
        rec["reservedBy"] = by
        rec["version"] = current_v + 1
        rec["leaseToken"] = lease_token(remnant_id, rec["version"], by)
        if lease_seconds is not None:
            rec["reservedUntil"] = (utcnow() + timedelta(seconds=float(lease_seconds))).isoformat()
        rec["persistence"] = self._persist_label()
        self.store.put(rec)
        return rec

    def consume(
        self,
        remnant_id: str,
        *,
        by: str,
        version: int | None = None,
        lease_token: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        from fox3d.inventory import QUALITY_UPPER, normalize_status

        rec = self.items[remnant_id]
        if tenant_id is not None and rec.get("tenantId") not in {None, tenant_id}:
            raise PermissionError("tenant isolation: remnant")
        st = normalize_status(rec.get("status"))
        if st == "consumed":
            raise PermissionError(f"remnant {remnant_id} already consumed")
        if st == "reserved" and rec.get("reservedBy") != by:
            raise PermissionError(f"remnant {remnant_id} reserved by {rec.get('reservedBy')}")
        if st not in {"available", "reserved"}:
            raise PermissionError(f"remnant {remnant_id} not consumable ({rec['status']})")
        current_v = int(rec.get("version") or 1)
        if version is not None and int(version) != current_v:
            raise PermissionError(f"stale remnant version {version} != {current_v}")
        if lease_token is not None and rec.get("leaseToken") and rec.get("leaseToken") != lease_token:
            raise PermissionError("stale remnant lease token")
        rec["status"] = "consumed"
        rec["qualityState"] = QUALITY_UPPER["consumed"]
        rec["consumedBy"] = by
        rec["version"] = current_v + 1
        rec["leaseToken"] = None
        rec["persistence"] = self._persist_label()
        self.store.put(rec)
        return rec

    def recover_expired(self, *, now: Any | None = None) -> list[dict[str, Any]]:
        from datetime import datetime

        from fox3d.inventory import QUALITY_UPPER, normalize_status

        stamp = now.isoformat() if hasattr(now, "isoformat") else (now or None)
        recovered: list[dict[str, Any]] = []
        for rec in list(self.items.values()):
            if normalize_status(rec.get("status")) != "reserved":
                continue
            until = rec.get("reservedUntil")
            if not until:
                continue
            try:
                deadline = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
            except ValueError:
                continue
            current = now if hasattr(now, "isoformat") else datetime.fromisoformat((stamp or datetime.now().isoformat()).replace("Z", "+00:00"))
            if current.tzinfo is None and deadline.tzinfo is not None:
                from datetime import timezone

                current = current.replace(tzinfo=timezone.utc)
            if current >= deadline:
                rec["status"] = "available"
                rec["qualityState"] = QUALITY_UPPER["available"]
                rec["reservedBy"] = None
                rec["leaseToken"] = None
                rec["reservedUntil"] = None
                rec["version"] = int(rec.get("version") or 1) + 1
                rec["recoveredFrom"] = "expired-lease"
                rec["persistence"] = self._persist_label()
                self.store.put(rec)
                recovered.append(rec)
        return recovered

    def snapshot(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        items = self.available(tenant_id=tenant_id) if tenant_id else list(self.items.values())
        return {
            "source": "CONFIG",
            "label": "REAL" if self._durable else "MOCK",
            "persistence": self._persist_label(),
            "items": list(self.items.values()) if tenant_id is None else [v for v in self.items.values() if v.get("tenantId") in {None, tenant_id}],
            "availableCount": len(self.available(tenant_id=tenant_id) if tenant_id else self.available()),
        }
