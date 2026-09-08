"""Small-space KD / flat-pack product family.

Extends CabinetSpec millimetre SoT. Not a second parametric engine.
"""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.manufacturing import CONNECTOR_RECIPES, DEFAULT_REMNANT_POLICY, NestingEngine
from fox3d.parametric import BOMEngine, CabinetEngine, TYPE_DEFAULTS, map_cabinet_material

FLATPACK_PRODUCT_TYPES = (
    "BEDSIDE_CABINET",
    "DESK_RISER",
    "OPEN_SHELF",
    "NARROW_BOOKCASE",
    "MOBILE_SIDE_TABLE",
    "STUDENT_DESK",
    "VANITY_DESK",
    "GARMENT_RACK",
    "APPLIANCE_RACK",
    "STORAGE_BENCH",
    "PET_FURNITURE",
    "RETAIL_DISPLAY",
)

KD_DIMENSION_GRID = {
    "width": (300, 400, 600, 800),
    "depth": (250, 300, 400),
    "height": (400, 800, 1200, 1600),
}

# Product-family overrides (still a grid, not a single hardcoded size).
KD_GRID_OVERRIDES: dict[str, dict[str, tuple[int, ...]]] = {
    "DESK_RISER": {"width": (400, 600, 800), "depth": (250, 300), "height": (100, 120, 150)},
    "STUDENT_DESK": {"width": (800, 1000, 1200), "depth": (400, 600), "height": (720, 750)},
    "VANITY_DESK": {"width": (600, 800), "depth": (400,), "height": (750,)},
    "MOBILE_SIDE_TABLE": {"width": (400, 600), "depth": (400,), "height": (400, 500)},
    "STORAGE_BENCH": {"width": (600, 800), "depth": (400,), "height": (400, 450)},
    "PET_FURNITURE": {"width": (400, 600), "depth": (300, 400), "height": (400,)},
}

DENSITY_KG_M3 = {
    "particle_board": 680.0,
    "mdf": 750.0,
    "plywood": 600.0,
    "cardboard": 700.0,
    "hardware_steel": 7800.0,
}
DENSITY_SOURCE = "CONFIG:EN-323-typical-furniture-board"

PACKAGING_PRICES = {
    "carton": 35.0,
    "epe": 12.0,
    "corner": 4.0,
    "bag": 3.0,
}
PACKAGING_PRICE_SOURCE = "ESTIMATED"

DEFAULT_LOGISTICS_POLICY = {
    "maxPackedWeightKg": 30.0,
    "maxLongestSideMm": 1500.0,
    "oneCartonPreference": True,
    "maxAssemblyDifficulty": 0.75,
    "volumetricDivisor": 6000.0,
    "baseFee": 80.0,
    "perKg": 12.0,
    "oversizeSurcharge": 180.0,
    "source": "CONFIG",
}

SMALL_SPACE_PROFILE = {
    "name": "student_rental_small_space",
    "smallFootprint": True,
    "easyMove": True,
    "oneCartonPreference": True,
    "simpleAssembly": True,
    "budgetTarget": 3500.0,
    "kind": "product_policy",
}


class FlatPackProductTypeRegistry:
    def list(self) -> list[str]:
        return list(FLATPACK_PRODUCT_TYPES)

    def defaults(self, code: str) -> dict[str, Any]:
        return dict(TYPE_DEFAULTS.get(code) or TYPE_DEFAULTS["STORAGE_CABINET"])

    def grid(self, code: str) -> dict[str, tuple[int, ...]]:
        base = dict(KD_DIMENSION_GRID)
        base.update(KD_GRID_OVERRIDES.get(code) or {})
        return base

    def snap(self, code: str, *, width: float | None = None, depth: float | None = None, height: float | None = None) -> dict[str, float]:
        g = self.grid(code)
        d = self.defaults(code)

        def nearest(value: float | None, choices: tuple[int, ...], fallback: float) -> float:
            if value is None:
                return float(fallback)
            return float(min(choices, key=lambda c: abs(c - value)))

        return {
            "width": nearest(width, tuple(g["width"]), d["width"]),
            "depth": nearest(depth, tuple(g["depth"]), d["depth"]),
            "height": nearest(height, tuple(g["height"]), d["height"]),
        }


def connector_recipe_for(kind: str) -> dict[str, Any]:
    if kind == "MOBILE_SIDE_TABLE":
        return dict(CONNECTOR_RECIPES["KD_BOLT_CASTER_V1"])
    if kind in {"STUDENT_DESK", "VANITY_DESK", "GARMENT_RACK", "DESK_RISER"}:
        return dict(CONNECTOR_RECIPES["KD_SCREW_V1"])
    rec = dict(CONNECTOR_RECIPES["KD_CAM_DOWEL_V1"])
    rec["kind"] = kind
    return rec


def build_flatpack_spec(engine: CabinetEngine, *, tenant_id: str, kind: str, **params: Any) -> dict[str, Any]:
    registry = FlatPackProductTypeRegistry()
    if kind not in FLATPACK_PRODUCT_TYPES:
        raise ValueError(kind)
    snapped = registry.snap(kind, width=params.get("width"), depth=params.get("depth"), height=params.get("height"))
    defaults = registry.defaults(kind)
    merged = {**defaults, **params, **snapped}
    spec, report = engine.create(
        kind,
        tenant_id=tenant_id,
        width=merged["width"],
        height=merged["height"],
        depth=merged["depth"],
        doorCount=merged.get("doorCount"),
        shelfCount=merged.get("shelfCount"),
        drawerCount=merged.get("drawerCount"),
        legs=merged.get("legs"),
        plinthHeight=merged.get("plinthHeight"),
        backPanel=merged.get("backPanel"),
        material=merged.get("material") or "WOOD_WHITE",
    )
    spec.metadata["flatPack"] = True
    spec.metadata["productFamily"] = kind
    spec.metadata["kdGrid"] = registry.grid(kind)
    recipe = connector_recipe_for(kind)
    spec.metadata["connectorRecipe"] = recipe
    spec.metadata["disassemblyDirection"] = "panel-flat"
    spec.metadata["maxLoosePartCount"] = len(spec.components) + sum(int(h.get("quantity") or 1) for h in spec.hardware)
    spec.metadata["toolRequirements"] = list(recipe.get("tools") or [])
    bom = BOMEngine().build(spec)
    graph = assembly_graph(spec, bom)
    fps = [part_fingerprint(line, spec) for line in bom["lines"] if not line.get("hardware")]
    packing = pack_flatpack(spec, bom)
    weight = packed_weight(spec, bom, packing)
    ship = shipping_metrics(packing, weight, policy=DEFAULT_LOGISTICS_POLICY)
    difficulty = assembly_difficulty(spec, bom, graph)
    common = common_part_stats(fps, bom)
    kd_meta = {
        "flatPack": True,
        "connectorRecipe": recipe,
        "panelGrouping": _panel_groups(bom),
        "connectorZones": [{"partId": c["from"], "to": c["to"], "joint": c.get("joint")} for c in spec.connections],
        "maximumLoosePartCount": spec.metadata["maxLoosePartCount"],
        "toolRequirements": spec.metadata["toolRequirements"],
    }
    spec.metadata.update(kd_meta)
    return {
        "spec": spec.model_dump(mode="json"),
        "report": report.model_dump(),
        "engineeringHash": spec.engineering_hash(),
        "bom": bom,
        "assemblyGraph": graph,
        "fingerprints": fps,
        "commonParts": common,
        "packing": packing,
        "weight": weight,
        "shipping": ship,
        "difficulty": difficulty,
        "kd": kd_meta,
        "label": "REAL" if report.ok else "BLOCKED",
    }


def _panel_groups(bom: dict[str, Any]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for line in bom.get("lines") or []:
        if line.get("hardware"):
            continue
        role = str(line.get("partType") or "panel")
        groups.setdefault(role, []).append(str(line.get("partId")))
    return groups


def part_fingerprint(line: dict[str, Any], spec: Any) -> dict[str, Any]:
    payload = {
        "material": map_cabinet_material(str(getattr(spec, "material", None) or line.get("material") or "")).get("code"),
        "thickness": line.get("thickness"),
        "length": round(float(line.get("length") or 0), 1),
        "width": round(float(line.get("width") or 0), 1),
        "edge": line.get("edgeBandingEdges") or {},
        "grain": line.get("grainDirection") or "none",
        "drillPattern": line.get("drillPattern") or [],
    }
    return {
        "partId": line.get("partId"),
        "partName": line.get("partName"),
        "fingerprint": stable_hash(payload),
        **payload,
    }


def common_part_stats(fingerprints: list[dict[str, Any]], bom: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for fp in fingerprints:
        counts[fp["fingerprint"]] = counts.get(fp["fingerprint"], 0) + 1
    unique_parts = len(counts)
    shared = sum(1 for n in counts.values() if n > 1)
    hw = [ln for ln in bom.get("lines") or [] if ln.get("hardware")]
    hw_skus = {ln.get("vendorNeutralId") or ln.get("partId") for ln in hw}
    return {
        "commonPartRatio": round((len(fingerprints) - unique_parts) / max(len(fingerprints), 1), 4) if fingerprints else 0.0,
        "uniquePartCount": unique_parts,
        "sharedFingerprintCount": shared,
        "hardwareCommonality": round(1.0 / max(len(hw_skus), 1), 4) if hw_skus else 1.0,
        "totalPanelCount": len(fingerprints),
    }


def assembly_graph(spec: Any, bom: dict[str, Any]) -> dict[str, Any]:
    panels = [ln for ln in bom.get("lines") or [] if not ln.get("hardware")]
    nodes = [str(ln.get("partId") or ln.get("partName")) for ln in panels]
    edges: list[dict[str, Any]] = []
    for conn in spec.connections or []:
        edges.append({"from": str(conn.get("from") or "").lower(), "to": str(conn.get("to") or "").lower(), "connector": conn.get("joint") or "cam", "step": len(edges) + 1})
    # Side → shelves sequential.
    shelves = [n for n in nodes if n.startswith("shelf")]
    sides = [n for n in nodes if n in {"l_side", "r_side"}]
    for i, sh in enumerate(shelves):
        for side in sides[:1]:
            edges.append({"from": side, "to": sh, "connector": "dowel", "step": 10 + i})
    cyclic = _has_cycle(nodes, edges)
    longest = max((float(ln.get("length") or 0), float(ln.get("width") or 0)) for ln in panels) if panels else (0, 0)
    two_person = max(longest) >= 1200 or (spec.width * spec.height * spec.depth) / 1e9 * 680 > 18
    steps = _topo_steps(nodes, edges)
    return {
        "nodes": nodes,
        "edges": edges,
        "acyclic": not cyclic,
        "canFlatPack": True,
        "twoPerson": bool(two_person),
        "steps": steps,
        "stepCount": len(steps),
        "reorientationCount": 1 + int(bool(spec.doorCount)) + int(bool(spec.drawerCount)),
    }


def _has_cycle(nodes: list[str], edges: list[dict[str, Any]]) -> bool:
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    indeg = {n: 0 for n in nodes}
    for e in edges:
        a, b = e["from"], e["to"]
        if a in adj and b in indeg:
            adj[a].append(b)
            indeg[b] += 1
    q = [n for n, d in indeg.items() if d == 0]
    seen = 0
    while q:
        n = q.pop()
        seen += 1
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    return seen < len(nodes)


def _topo_steps(nodes: list[str], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if _has_cycle(nodes, edges):
        return [{"step": 1, "parts": nodes, "warning": "cyclic_fallback"}]
    by_step: dict[int, list[str]] = {}
    for e in edges:
        by_step.setdefault(int(e.get("step") or 1), []).append(e["to"])
    steps = []
    for i, (step, parts) in enumerate(sorted(by_step.items()), start=1):
        steps.append(
            {
                "step": i,
                "parts": sorted(set(parts)),
                "hardware": [e["connector"] for e in edges if int(e.get("step") or 1) == step],
                "tool": "hex_key",
                "orientation": "upright",
                "warning": None,
            }
        )
    if not steps:
        steps = [{"step": 1, "parts": nodes, "hardware": ["cam"], "tool": "hex_key", "orientation": "upright", "warning": None}]
    return steps


def assembly_instruction_manifest(graph: dict[str, Any], spec: Any) -> dict[str, Any]:
    return {
        "productId": spec.productId,
        "engineeringHash": spec.engineering_hash(),
        "steps": graph.get("steps") or [],
        "twoPerson": graph.get("twoPerson"),
        "canFlatPack": graph.get("canFlatPack"),
        "source": "assembly_graph",
    }


def assembly_difficulty(spec: Any, bom: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    panels = [ln for ln in bom.get("lines") or [] if not ln.get("hardware")]
    hw = [ln for ln in bom.get("lines") or [] if ln.get("hardware")]
    fastener_types = {ln.get("vendorNeutralId") or ln.get("partId") for ln in hw}
    tools = set((spec.metadata or {}).get("toolRequirements") or ["hex_key"])
    steps = int(graph.get("stepCount") or 1)
    reorient = int(graph.get("reorientationCount") or 1)
    two = 1 if graph.get("twoPerson") else 0
    part_n = len(panels)
    score = min(
        1.0,
        0.18 * min(part_n / 20, 1)
        + 0.14 * min(len(fastener_types) / 6, 1)
        + 0.10 * min(len(tools) / 3, 1)
        + 0.22 * min(steps / 12, 1)
        + 0.16 * min(reorient / 4, 1)
        + 0.20 * two,
    )
    minutes = round(part_n * 1.4 + steps * 0.9 + two * 8, 1)
    return {
        "partCount": part_n,
        "uniqueFastenerTypes": len(fastener_types),
        "toolCount": len(tools),
        "steps": steps,
        "reorientationCount": reorient,
        "twoPersonSteps": two,
        "estimatedMinutes": minutes,
        "score": round(score, 4),
        "source": "deterministic",
    }


def pack_flatpack(spec: Any, bom: dict[str, Any], *, padding_mm: float = 12.0, hardware_box: tuple[float, float, float] = (160.0, 110.0, 45.0)) -> dict[str, Any]:
    panels = [ln for ln in bom.get("lines") or [] if not ln.get("hardware") and float(ln.get("length") or 0) > 0]
    if not panels:
        raise ValueError("no panels to pack")
    faces = []
    for ln in panels:
        qty = int(ln.get("quantity") or 1)
        L, W, T = float(ln["length"]), float(ln["width"]), float(ln.get("thickness") or spec.boardThickness)
        long, short = max(L, W), min(L, W)
        for _ in range(qty):
            faces.append({"partId": ln.get("partId"), "L": long, "W": short, "T": T})
    max_l = max(f["L"] for f in faces)
    max_w = max(f["W"] for f in faces)
    stack_t = sum(f["T"] for f in faces)
    inner_l = max_l + 2 * padding_mm
    inner_w = max_w + 2 * padding_mm
    inner_h = stack_t + 2 * padding_mm + hardware_box[2]
    carton = {
        "length": round(inner_l, 1),
        "width": round(inner_w, 1),
        "height": round(inner_h, 1),
        "paddingMm": padding_mm,
        "hardwareBox": list(hardware_box),
        "largestPanel": {"length": max_l, "width": max_w},
        "stackHeight": stack_t,
        "panelCount": len(faces),
        "derivedFromPanels": True,
    }
    carton["recipeVersion"] = 1
    carton["packagingHash"] = stable_hash(carton)
    carton["materials"] = [
        {"sku": "carton", "qty": 1, "cost": PACKAGING_PRICES["carton"], "source": PACKAGING_PRICE_SOURCE},
        {"sku": "epe", "qty": 1, "cost": PACKAGING_PRICES["epe"], "source": PACKAGING_PRICE_SOURCE},
        {"sku": "corner", "qty": 8, "cost": PACKAGING_PRICES["corner"], "source": PACKAGING_PRICE_SOURCE},
        {"sku": "bag", "qty": 1, "cost": PACKAGING_PRICES["bag"], "source": PACKAGING_PRICE_SOURCE},
    ]
    carton["packagingCost"] = round(sum(m["cost"] * m["qty"] for m in carton["materials"]), 2)
    carton["costSource"] = PACKAGING_PRICE_SOURCE
    return carton


def packed_weight(spec: Any, bom: dict[str, Any], packing: dict[str, Any]) -> dict[str, Any]:
    eng = map_cabinet_material(str(spec.material)).get("engineering") or "particle_board"
    dens = DENSITY_KG_M3.get(eng, 680.0)
    net = 0.0
    for ln in bom.get("lines") or []:
        if ln.get("hardware"):
            net += 0.02 * float(ln.get("quantity") or 1)
            continue
        vol = (float(ln.get("length") or 0) * float(ln.get("width") or 0) * float(ln.get("thickness") or 0) * float(ln.get("quantity") or 1)) / 1e9
        net += vol * dens
    pack_w = 0.35 + packing.get("panelCount", 0) * 0.01
    gross = net + pack_w
    return {
        "netKg": round(net, 3),
        "grossKg": round(gross, 3),
        "densityKgM3": dens,
        "densitySource": DENSITY_SOURCE,
        "packagingKg": round(pack_w, 3),
    }


def shipping_metrics(packing: dict[str, Any], weight: dict[str, Any], *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = {**DEFAULT_LOGISTICS_POLICY, **(policy or {})}
    L, W, H = packing["length"], packing["width"], packing["height"]
    cbm = (L * W * H) / 1e9
    longest = max(L, W, H)
    volumetric_kg = (L * W * H) / 1000.0 / float(p["volumetricDivisor"])
    chargeable = max(float(weight["grossKg"]), volumetric_kg)
    oversize = longest > float(p["maxLongestSideMm"]) or float(weight["grossKg"]) > float(p["maxPackedWeightKg"])
    fee = float(p["baseFee"]) + chargeable * float(p["perKg"])
    if oversize:
        fee += float(p["oversizeSurcharge"])
    return {
        "cbm": round(cbm, 6),
        "longestSideMm": longest,
        "volumetricKg": round(volumetric_kg, 3),
        "chargeableKg": round(chargeable, 3),
        "oversize": oversize,
        "oneCarton": True,
        "logisticsFee": round(fee, 2),
        "source": p.get("source") or "CONFIG",
        "policyHash": stable_hash({k: p[k] for k in p if k != "source"}),
    }


def kd_logistics_gate(packing: dict[str, Any], weight: dict[str, Any], difficulty: dict[str, Any], shipping: dict[str, Any], *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = {**DEFAULT_LOGISTICS_POLICY, **(policy or {})}
    hard: list[str] = []
    soft: list[str] = []
    if shipping["oversize"]:
        hard.append("OVERSIZE")
    if weight["grossKg"] > float(p["maxPackedWeightKg"]):
        hard.append("OVERWEIGHT")
    if difficulty["score"] > float(p["maxAssemblyDifficulty"]):
        soft.append("ASSEMBLY_DIFFICULTY")
    if p.get("oneCartonPreference") and not shipping.get("oneCarton"):
        soft.append("MULTI_CARTON")
    return {
        "ok": not hard,
        "hard": hard,
        "soft": soft,
        "policyHash": shipping.get("policyHash"),
        "redesignRequired": bool(hard),
    }


def sku_family_variants(engine: CabinetEngine, *, tenant_id: str, kind: str, chassis: dict[str, Any]) -> list[dict[str, Any]]:
    family_id = new_id()
    variants = []
    materials = ["WOOD_WHITE", "WOOD_OAK"]
    for mat in materials:
        for doors in {0, int(chassis.get("doorCount") or 0)}:
            rec = build_flatpack_spec(engine, tenant_id=tenant_id, kind=kind, material=mat, doorCount=doors, width=chassis.get("width"), height=chassis.get("height"), depth=chassis.get("depth"))
            rec["familyId"] = family_id
            rec["parentFamily"] = kind
            rec["immutable"] = True
            variants.append(rec)
    return variants


class DemandSignalProvider:
    name = "unbound"
    status = "UNAVAILABLE"

    def signals(self, *, kind: str) -> dict[str, Any]:
        return {"status": "UNAVAILABLE", "label": "MOCK", "kind": kind, "note": "no live demand source", "score": None}


def rd_score_v2(*, report_ok: bool, nesting: dict[str, Any], common: dict[str, Any], packing: dict[str, Any], weight: dict[str, Any], difficulty: dict[str, Any], landed: dict[str, Any], demand: dict[str, Any], vision: dict[str, Any] | None) -> dict[str, Any]:
    veto = not report_ok
    util = float(nesting.get("utilizationRatio") or nesting.get("utilization") or 0)
    waste = float(nesting.get("trueWasteRatio") or 0)
    remnant = float(nesting.get("reusableRemnantRatio") or 0)
    engineering = 1.0 if report_ok else 0.0
    dfm = max(0.0, min(1.0, 0.5 * util + 0.3 * (1 - waste) + 0.2 * remnant))
    pack_score = 1.0 if not packing.get("oversize") else 0.3
    asm = max(0.0, 1.0 - float(difficulty.get("score") or 0))
    margin = float(landed.get("grossMargin") or 0)
    cost_score = max(0.0, min(1.0, margin / 0.5)) if margin else 0.4
    demand_score = demand.get("score")
    vision_score = (vision or {}).get("visionScore")
    overall = None if veto else round(
        0.35 * engineering
        + 0.20 * dfm
        + 0.10 * float(common.get("commonPartRatio") or 0)
        + 0.10 * pack_score
        + 0.10 * asm
        + 0.15 * cost_score,
        4,
    )
    return {
        "engineeringValidity": {"value": engineering, "confidence": "REAL", "veto": veto},
        "trueWasteUtilization": {"value": round(dfm, 4), "confidence": "REAL", "trueWasteRatio": waste, "utilizationRatio": util},
        "remnantConsumption": {"value": remnant, "confidence": "REAL"},
        "commonPartRatio": {"value": common.get("commonPartRatio"), "confidence": "REAL"},
        "packagingCubeWeight": {"value": pack_score, "confidence": "CONFIG", "grossKg": weight.get("grossKg")},
        "assemblyDifficulty": {"value": asm, "confidence": "REAL", "score": difficulty.get("score")},
        "landedCostMargin": {"value": round(cost_score, 4), "confidence": landed.get("source") or "ESTIMATED"},
        "demandScore": {"value": demand_score, "confidence": demand.get("label") or "MOCK"},
        "visualScore": {"value": vision_score, "confidence": (vision or {}).get("label") or "MOCK"},
        "overallDeterministic": overall,
        "engineeringVeto": veto,
        "mixedConfidenceForbidden": True,
    }
