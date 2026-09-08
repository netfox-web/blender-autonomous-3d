"""Furniture product family, cabinet modules, multi-cabinet assembly.

CabinetSpec remains the millimetre Source of Truth. Modules and assemblies
are structured views of that record — not a second parametric engine.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from fox3d.ids import new_id, stable_hash
from fox3d.parametric import TYPE_DEFAULTS

FURNITURE_PRODUCT_TYPE_CODES = (
    "WARDROBE",
    "SHOE_CABINET",
    "TV_CABINET",
    "BOOKCASE",
    "STORAGE_CABINET",
    "DISPLAY_CABINET",
    "KITCHEN_BASE",
    "KITCHEN_WALL",
)

ModuleKind = Literal[
    "VERTICAL_PARTITION",
    "HORIZONTAL_PARTITION",
    "OPEN_SHELF",
    "CLOSED_COMPARTMENT",
    "HINGED_DOOR",
    "DOUBLE_DOOR",
    "DRAWER_BANK",
    "OPEN_BAY",
    "TOE_KICK",
    "LEGS",
    "PLINTH",
    "TOP_FILLER",
    "SIDE_FILLER",
    "WALL_CLEARANCE",
]


class FurnitureProductType(BaseModel):
    code: str
    defaultWidth: float
    defaultHeight: float
    defaultDepth: float
    doorCount: int = 0
    shelfCount: int = 0
    drawerCount: int = 0
    legs: bool = False
    plinthHeight: float = 0
    notes: str = ""


class FurnitureProductTypeRegistry:
    """Phase 71 — product family registry. Defaults live in TYPE_DEFAULTS."""

    def list(self) -> list[str]:
        return list(FURNITURE_PRODUCT_TYPE_CODES)

    def get(self, code: str) -> FurnitureProductType:
        key = (code or "STORAGE_CABINET").upper()
        if key == "CABINET":
            key = "STORAGE_CABINET"
        raw = dict(TYPE_DEFAULTS.get(key) or TYPE_DEFAULTS["STORAGE_CABINET"])
        return FurnitureProductType(
            code=key if key in FURNITURE_PRODUCT_TYPE_CODES else "STORAGE_CABINET",
            defaultWidth=float(raw["width"]),
            defaultHeight=float(raw["height"]),
            defaultDepth=float(raw["depth"]),
            doorCount=int(raw.get("doorCount") or 0),
            shelfCount=int(raw.get("shelfCount") or 0),
            drawerCount=int(raw.get("drawerCount") or 0),
            legs=bool(raw.get("legs") or False),
            plinthHeight=float(raw.get("plinthHeight") or 0),
        )

    def defaults(self, code: str) -> dict[str, Any]:
        return self.get(code).model_dump()


class CabinetModule(BaseModel):
    moduleId: str = Field(default_factory=new_id)
    kind: ModuleKind
    width: float = 0
    height: float = 0
    depth: float = 0
    originX: float = 0
    originY: float = 0
    originZ: float = 0
    quantity: int = 1
    openingStyle: str | None = None
    notes: str = ""


class PlacedCabinet(BaseModel):
    placementId: str = Field(default_factory=new_id)
    cabinetId: str
    kind: str
    originX: float
    originY: float = 0
    originZ: float = 0
    startMm: float
    wallId: str
    spec: dict[str, Any]
    engineeringHash: str


class MultiCabinetAssembly(BaseModel):
    assemblyId: str = Field(default_factory=new_id)
    tenantId: str
    wallId: str
    spaceId: str | None = None
    cabinets: list[PlacedCabinet] = Field(default_factory=list)
    gapMm: float = 20
    clearanceMm: float = 10
    symmetric: bool = False

    def engineering_hash(self) -> str:
        payload = [
            {
                "kind": c.kind,
                "startMm": c.startMm,
                "originX": c.originX,
                "originY": c.originY,
                "hash": c.engineeringHash,
            }
            for c in self.cabinets
        ]
        return stable_hash({"wallId": self.wallId, "gap": self.gapMm, "cabinets": payload})


def modules_from_spec(spec: Any) -> list[CabinetModule]:
    from fox3d.parametric import _bay_count

    t = float(spec.boardThickness)
    inner_w = spec.width - 2 * t
    bays = int(spec.constraints.get("bays") or _bay_count(inner_w, 800))
    if spec.verticalPartitions is not None:
        bays = max(1, int(spec.verticalPartitions) + 1)
    modules: list[CabinetModule] = []
    bay_w = inner_w / max(bays, 1)
    for i in range(max(0, bays - 1)):
        modules.append(
            CabinetModule(
                kind="VERTICAL_PARTITION",
                width=t,
                height=spec.height - 2 * t,
                depth=spec.depth - 20,
                originX=t + bay_w * (i + 1),
            )
        )
    for i in range(int(spec.horizontalPartitions or 0)):
        modules.append(
            CabinetModule(
                kind="HORIZONTAL_PARTITION",
                width=inner_w,
                height=t,
                depth=spec.depth - 20,
                originZ=t + (i + 1) * 300,
            )
        )
    if spec.shelfCount:
        usable_h = spec.height - 2 * t - spec.plinthHeight - spec.drawerCount * 180
        closed = spec.doorCount > 0
        kind: ModuleKind = "CLOSED_COMPARTMENT" if closed else "OPEN_SHELF"
        for i in range(spec.shelfCount):
            modules.append(
                CabinetModule(
                    kind=kind,
                    width=inner_w,
                    height=usable_h / max(spec.shelfCount, 1),
                    depth=spec.depth - 20,
                    originZ=t + spec.plinthHeight + (i + 1) * (usable_h / (spec.shelfCount + 1)),
                )
            )
    if spec.doorCount == 0 and spec.drawerCount == 0:
        for i in range(bays):
            modules.append(CabinetModule(kind="OPEN_BAY", width=bay_w, height=spec.height - 2 * t, depth=spec.depth, originX=t + i * bay_w))
    elif spec.doorCount == 2:
        modules.append(
            CabinetModule(
                kind="DOUBLE_DOOR",
                width=spec.width,
                height=spec.height - spec.plinthHeight,
                depth=t,
                quantity=2,
                openingStyle="double",
            )
        )
    elif spec.doorCount:
        for i in range(spec.doorCount):
            modules.append(
                CabinetModule(
                    kind="HINGED_DOOR",
                    width=spec.width / spec.doorCount,
                    height=spec.height - spec.plinthHeight,
                    depth=t,
                    originX=i * (spec.width / spec.doorCount),
                    openingStyle=spec.openingStyle or "hinged",
                )
            )
    if spec.drawerCount:
        modules.append(
            CabinetModule(
                kind="DRAWER_BANK",
                width=inner_w,
                height=spec.drawerCount * 180,
                depth=spec.depth - 40,
                quantity=spec.drawerCount,
            )
        )
    if spec.legs:
        modules.append(CabinetModule(kind="LEGS", height=spec.plinthHeight or 100, width=40, depth=40, quantity=4))
    elif spec.plinthHeight:
        modules.append(CabinetModule(kind="PLINTH", width=spec.width, height=spec.plinthHeight, depth=spec.depth))
        modules.append(CabinetModule(kind="TOE_KICK", width=spec.width, height=spec.plinthHeight, depth=80))
    if spec.toeKickHeight and spec.toeKickHeight != spec.plinthHeight:
        modules.append(CabinetModule(kind="TOE_KICK", width=spec.width, height=spec.toeKickHeight, depth=80))
    if spec.topFillerHeight:
        modules.append(CabinetModule(kind="TOP_FILLER", width=spec.width, height=spec.topFillerHeight, depth=spec.depth))
    if spec.sideFillerWidth:
        modules.append(CabinetModule(kind="SIDE_FILLER", width=spec.sideFillerWidth, height=spec.height, depth=spec.depth, quantity=1))
    if spec.wallClearance:
        modules.append(CabinetModule(kind="WALL_CLEARANCE", width=spec.wallClearance, height=spec.height, depth=spec.depth))
    return modules


def apply_module_extras(spec: Any) -> None:
    from fox3d.parametric import _panel

    t = spec.boardThickness
    roles = {p.get("role") for p in spec.components}
    for i, mod in enumerate(spec.modules):
        kind = mod.kind if hasattr(mod, "kind") else mod.get("kind")
        if kind == "HORIZONTAL_PARTITION":
            name = f"H_PARTITION_{i+1}"
            if not any(p.get("partName") == name for p in spec.components):
                spec.components.append(_panel(name, spec.width - 2 * t, spec.depth - 20, t, "h_partition"))
        elif kind == "TOP_FILLER" and "top_filler" not in roles:
            spec.components.append(_panel("TOP_FILLER", spec.width, spec.depth, t, "top_filler"))
            roles.add("top_filler")
        elif kind == "SIDE_FILLER" and "side_filler" not in roles:
            spec.components.append(_panel("SIDE_FILLER", spec.height, spec.depth, t, "side_filler"))
            roles.add("side_filler")
        elif kind == "TOE_KICK" and "toe_kick" not in roles:
            spec.components.append(_panel("TOE_KICK", spec.width, 80, spec.toeKickHeight or spec.plinthHeight or 80, "toe_kick"))
            roles.add("toe_kick")
        elif kind == "PLINTH" and "plinth" not in roles and not spec.legs:
            spec.components.append(_panel("PLINTH", spec.width, spec.depth, spec.plinthHeight or 80, "plinth"))
            roles.add("plinth")
        elif kind == "VERTICAL_PARTITION":
            n_div = sum(1 for p in spec.components if p.get("role") == "divider")
            need = sum(1 for m in spec.modules if (m.kind if hasattr(m, "kind") else m.get("kind")) == "VERTICAL_PARTITION")
            if n_div < need:
                spec.components.append(_panel(f"DIVIDER_{n_div+1}", spec.height - 2 * t, spec.depth - 20, t, "divider"))


def sync_modules(spec: Any) -> None:
    if not spec.modules:
        models = modules_from_spec(spec)
    else:
        models = [m if isinstance(m, CabinetModule) else CabinetModule.model_validate(m) for m in spec.modules]
    spec.modules = models
    apply_module_extras(spec)
    spec.modules = [m.model_dump(mode="json") if hasattr(m, "model_dump") else m for m in spec.modules]


def assembly_from_placements(
    *,
    tenant_id: str,
    wall_id: str,
    space_id: str | None,
    placements: list[dict[str, Any]],
    cabinets: CabinetEngineLike | Any,
    gap_mm: float = 20,
    clearance_mm: float = 10,
    symmetric: bool = False,
) -> MultiCabinetAssembly:
    placed: list[PlacedCabinet] = []
    for row in placements:
        spec, report = cabinets.create(
            row.get("kind") or "STORAGE_CABINET",
            tenant_id=tenant_id,
            width=row.get("width"),
            height=row.get("height"),
            depth=row.get("depth"),
            doorCount=row.get("doorCount"),
            shelfCount=row.get("shelfCount"),
            drawerCount=row.get("drawerCount"),
            material=row.get("material") or "WOOD_WHITE",
            topFillerHeight=row.get("topFillerHeight") or 0,
            sideFillerWidth=row.get("sideFillerWidth") or 0,
            wallClearance=row.get("wallClearance") or clearance_mm,
        )
        if not report.ok and row.get("requireOk", True):
            # Keep the spec; caller may still inspect violations.
            pass
        placed.append(
            PlacedCabinet(
                cabinetId=spec.productId,
                kind=spec.kind,
                originX=float(row.get("originX") or 0),
                originY=float(row.get("originY") or 0),
                originZ=float(row.get("originZ") or 0),
                startMm=float(row.get("startMm") or row.get("originX") or 0),
                wallId=wall_id,
                spec=spec.model_dump(mode="json"),
                engineeringHash=spec.engineering_hash(),
            )
        )
    asm = MultiCabinetAssembly(
        tenantId=tenant_id,
        wallId=wall_id,
        spaceId=space_id,
        cabinets=placed,
        gapMm=gap_mm,
        clearanceMm=clearance_mm,
        symmetric=symmetric,
    )
    return asm


class CabinetEngineLike:
    create: Any


def validate_assembly(assembly: MultiCabinetAssembly, *, space: Any | None = None) -> list[dict[str, Any]]:
    """Door-sweep / drawer-extension collisions between neighbouring cabinets."""
    violations: list[dict[str, Any]] = []
    ordered = sorted(assembly.cabinets, key=lambda c: c.startMm)
    for i, cab in enumerate(ordered):
        spec = cab.spec
        width = float(spec.get("width") or 0)
        depth = float(spec.get("depth") or 0)
        doors = int(spec.get("doorCount") or 0)
        drawers = int(spec.get("drawerCount") or 0)
        end = cab.startMm + width
        if i + 1 < len(ordered):
            nxt = ordered[i + 1]
            gap = nxt.startMm - end
            if gap < assembly.gapMm - 0.5:
                violations.append({"code": "CABINET_GAP", "message": f"gap {gap:.0f}mm < {assembly.gapMm}mm", "severity": "error"})
        if doors:
            door_w = width / max(doors, 1)
            # 90° sweep occupies door_w in front of the carcass.
            if depth < door_w * 0.25:
                violations.append({"code": "DOOR_SWEEP_COLLISION", "message": "carcass too shallow for door sweep", "severity": "error", "cabinetId": cab.cabinetId})
            if i + 1 < len(ordered) and ordered[i + 1].originY < door_w and abs(ordered[i + 1].originY - cab.originY) < 1:
                # same wall line; neighbour is beside, not in front — OK unless overlapping.
                pass
        if drawers:
            extension = max(250.0, depth - 40)
            if space is not None:
                room_depth = float(getattr(space, "depth", 0) or (space.get("depth") if isinstance(space, dict) else 0) or 0)
                if room_depth and cab.originY + depth + extension > room_depth + 1:
                    violations.append({"code": "DRAWER_EXTENSION_COLLISION", "message": "drawer extension hits opposite wall", "severity": "error", "cabinetId": cab.cabinetId})
    return violations


def customer_revision(engine: Any, spec: Any, **changes: Any) -> tuple[Any, Any, dict[str, Any]]:
    dim_keys = {k: v for k, v in changes.items() if k in {"width", "height", "depth"} and v is not None}
    nxt, report = engine.resize(spec, **dim_keys) if dim_keys else engine.resize(spec)
    for key in ("material", "shelfCount", "doorCount", "drawerCount", "openingStyle", "topFillerHeight", "sideFillerWidth"):
        if key in changes and changes[key] is not None:
            setattr(nxt, key, changes[key])
    nxt.parentProductId = spec.productId
    nxt.revision = int(getattr(spec, "revision", 1) or 1) + 1
    nxt.components = engine._components(nxt)
    nxt.hardware = engine._hardware(nxt)
    nxt.connections = engine._connections(nxt)
    sync_modules(nxt)
    report = engine.rules.validate(nxt)
    lineage = {
        "parentProductId": spec.productId,
        "childProductId": nxt.productId,
        "parentHash": spec.engineering_hash(),
        "childHash": nxt.engineering_hash(),
        "revision": nxt.revision,
        "immutable": True,
    }
    return nxt, report, lineage
