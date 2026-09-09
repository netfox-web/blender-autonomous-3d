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


def connector_recipe_for(kind: str, *, version: int | None = None) -> dict[str, Any]:
    if kind == "MOBILE_SIDE_TABLE":
        key = "KD_BOLT_CASTER_V1"
    elif kind in {"STUDENT_DESK", "VANITY_DESK", "GARMENT_RACK", "DESK_RISER"}:
        key = "KD_SCREW_V1"
    elif version == 2:
        key = "KD_CAM_DOWEL_V2"
    else:
        key = "KD_CAM_DOWEL_V1"
    rec = dict(CONNECTOR_RECIPES[key])
    rec["kind"] = kind
    rec["recipeKey"] = key
    rec["compatibility"] = list(rec.get("compatibility") or [key])
    rec["requiredTools"] = list(rec.get("requiredTools") or rec.get("tools") or [])
    return rec


def connector_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    fam_a = a.get("family") or a.get("recipeKey")
    fam_b = b.get("family") or b.get("recipeKey")
    if fam_a and fam_b and fam_a == fam_b:
        return True
    keys = set(a.get("compatibility") or []) | {a.get("recipeKey")}
    return (b.get("recipeKey") in keys) or (b.get("family") in keys)


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
        boardThickness=merged.get("boardThickness"),
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
    v2 = assembly_instruction_v2(graph, spec, bom, recipe=recipe)
    labels = part_label_manifest(spec, bom, graph)
    contents = carton_contents_manifest(spec, bom, packing)
    risk = misassembly_risk(spec, bom)
    tools = tool_count_kpi({"kd": kd_meta, "assemblyGraph": graph, "spec": spec.model_dump(mode="json")})
    difficulty = {**difficulty, **{k: tools[k] for k in ("toolCount", "toolSwitchCount")}}
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
        "instructionsV2": v2,
        "partLabels": labels,
        "cartonContents": contents,
        "misassembly": risk,
        "tools": tools,
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


def common_hardware_optimizer(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer shared connector SKUs across a SKU family. Vendor-neutral only."""
    all_hw: list[str] = []
    per: list[set[str]] = []
    for rec in recs:
        hw = {
            str(ln.get("vendorNeutralId") or ln.get("partId") or ln.get("partName"))
            for ln in (rec.get("bom") or {}).get("lines") or []
            if ln.get("hardware")
        }
        per.append(hw)
        all_hw.extend(hw)
    union = set(all_hw)
    inter = set.intersection(*per) if per else set()
    ratio = round(len(inter) / max(len(union), 1), 4)
    return {
        "commonHardwareRatio": ratio,
        "sharedSkus": sorted(inter),
        "unionSkus": sorted(union),
        "familySize": len(recs),
        "vendorNeutral": True,
    }


def common_panel_optimizer(rec: dict[str, Any], *, max_delta_mm: float = 10.0, hard_dims: dict[str, float] | None = None) -> dict[str, Any]:
    """Propose shared panel sizes within tolerance. Never silently change hard user dims."""
    hard = hard_dims or {}
    fps = rec.get("fingerprints") or []
    groups: dict[str, list[dict[str, Any]]] = {}
    for fp in fps:
        key = f"{fp.get('thickness')}:{fp.get('material')}"
        groups.setdefault(key, []).append(fp)
    proposals: list[dict[str, Any]] = []
    for items in groups.values():
        for i, a in enumerate(items):
            for b in items[i + 1 :]:
                dl = abs(float(a["length"]) - float(b["length"]))
                dw = abs(float(a["width"]) - float(b["width"]))
                if 0 < dl + dw <= max_delta_mm:
                    proposals.append(
                        {
                            "a": a.get("partId"),
                            "b": b.get("partId"),
                            "deltaMm": round(dl + dw, 2),
                            "blockedByHardDim": bool(hard),
                        }
                    )
    applied = [] if hard else proposals
    ratio = rec.get("commonParts", {}).get("commonPartRatio") or 0
    if applied:
        ratio = min(1.0, float(ratio) + 0.05 * len(applied))
    return {
        "commonPanelRatio": round(ratio, 4),
        "proposals": proposals,
        "applied": applied,
        "hardDimsHonored": True,
        "changedUserHardSize": False,
    }


def tool_count_kpi(rec: dict[str, Any]) -> dict[str, Any]:
    tools = list((rec.get("kd") or {}).get("toolRequirements") or (rec.get("spec") or {}).get("metadata", {}).get("toolRequirements") or [])
    steps = (rec.get("assemblyGraph") or {}).get("steps") or []
    switches = 0
    prev = None
    for st in steps:
        tool = st.get("tool")
        if prev is not None and tool != prev:
            switches += 1
        prev = tool
    return {
        "toolCount": len(set(tools) | {st.get("tool") for st in steps if st.get("tool")}),
        "toolSwitchCount": switches,
        "tools": sorted({*(tools), *(st.get("tool") for st in steps if st.get("tool"))}),
        "source": "deterministic",
    }


def misassembly_risk(spec: Any, bom: dict[str, Any]) -> dict[str, Any]:
    panels = [ln for ln in bom.get("lines") or [] if not ln.get("hardware")]
    warnings: list[dict[str, Any]] = []
    left = next((ln for ln in panels if str(ln.get("partId") or "").lower() in {"l_side", "left"}), None)
    right = next((ln for ln in panels if str(ln.get("partId") or "").lower() in {"r_side", "right"}), None)
    if left and right:
        same = abs(float(left.get("length") or 0) - float(right.get("length") or 0)) < 0.5 and abs(float(left.get("width") or 0) - float(right.get("width") or 0)) < 0.5
        if same:
            warnings.append({"code": "LR_SIMILAR", "message": "left/right panels same size — orientation marking required", "severity": "warning"})
    doors = [ln for ln in panels if str(ln.get("partType") or "") in {"door", "drawer_front"}]
    if doors:
        warnings.append({"code": "FACE_HANDEDNESS", "message": "front/back identification required for drilled faces", "severity": "warning"})
    sym = {}
    for ln in panels:
        key = (round(float(ln.get("length") or 0), 1), round(float(ln.get("width") or 0), 1), round(float(ln.get("thickness") or 0), 1))
        sym.setdefault(key, []).append(ln.get("partId"))
    for key, ids in sym.items():
        if len(ids) > 1:
            warnings.append({"code": "SYMMETRIC_PARTS", "message": f"identical outline {ids}", "severity": "info"})
    return {
        "warnings": warnings,
        "riskScore": round(min(1.0, 0.15 * len(warnings)), 4),
        "source": "deterministic",
    }


def part_label_manifest(spec: Any, bom: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    steps = graph.get("steps") or []
    labels = []
    for ln in bom.get("lines") or []:
        if ln.get("hardware"):
            continue
        pid = str(ln.get("partId") or ln.get("partName"))
        step_refs = [st.get("step") for st in steps if pid in (st.get("parts") or [])]
        payload = {
            "productVersion": getattr(spec, "revision", None) or (spec.get("revision") if isinstance(spec, dict) else 1),
            "partId": pid,
            "orientation": "grain-length" if (ln.get("partType") in {"top", "bottom", "shelf", "door"}) else "any",
            "stepRefs": step_refs,
        }
        labels.append({**payload, "qrPayload": payload, "print": False})
    man = {
        "productId": getattr(spec, "productId", None) or (spec.get("productId") if isinstance(spec, dict) else None),
        "labels": labels,
        "print": False,
        "source": "metadata-only",
    }
    man["manifestHash"] = stable_hash(man)
    return man


def assembly_instruction_v2(graph: dict[str, Any], spec: Any, bom: dict[str, Any], *, recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    tools = list((recipe or {}).get("requiredTools") or (recipe or {}).get("tools") or ["hex_key"])
    connectors = list((recipe or {}).get("connectors") or [])
    steps_out = []
    nodes = list(graph.get("nodes") or [])
    assembled: list[str] = []
    for st in graph.get("steps") or []:
        inputs = [p for p in (st.get("parts") or []) if p]
        before = list(assembled)
        assembled = sorted(set(assembled + inputs))
        steps_out.append(
            {
                "step": st.get("step"),
                "inputs": inputs,
                "connectors": st.get("hardware") or connectors[:1],
                "tools": [st.get("tool") or (tools[0] if tools else "hex_key")],
                "before": before,
                "after": list(assembled),
                "warning": st.get("warning") or None,
            }
        )
    if not steps_out:
        steps_out.append(
            {
                "step": 1,
                "inputs": nodes,
                "connectors": connectors[:1] or ["cam"],
                "tools": tools[:1] or ["hex_key"],
                "before": [],
                "after": nodes,
                "warning": None,
            }
        )
    man = {
        "productId": getattr(spec, "productId", None) or (spec.get("productId") if isinstance(spec, dict) else None),
        "engineeringHash": spec.engineering_hash() if hasattr(spec, "engineering_hash") else None,
        "version": 2,
        "steps": steps_out,
        "twoPerson": graph.get("twoPerson"),
        "source": "assembly_graph_v2",
    }
    man["manifestHash"] = stable_hash({k: man[k] for k in man if k != "manifestHash"})
    return man


def carton_contents_manifest(spec: Any, bom: dict[str, Any], packing: dict[str, Any]) -> dict[str, Any]:
    panels = [ln for ln in bom.get("lines") or [] if not ln.get("hardware")]
    hw = [ln for ln in bom.get("lines") or [] if ln.get("hardware")]
    checklist = [{"kind": "panel", "partId": ln.get("partId"), "qty": ln.get("quantity")} for ln in panels]
    checklist.extend({"kind": "hardware", "partId": ln.get("partId") or ln.get("partName"), "qty": ln.get("quantity")} for ln in hw)
    checklist.append({"kind": "instructions", "partId": "MANUAL", "qty": 1})
    bom_qty = sum(int(ln.get("quantity") or 1) for ln in bom.get("lines") or [])
    pack_qty = sum(int(x.get("qty") or 1) for x in checklist if x["kind"] != "instructions")
    man = {
        "productId": getattr(spec, "productId", None) or (spec.get("productId") if isinstance(spec, dict) else None),
        "carton": {"L": packing.get("length"), "W": packing.get("width"), "H": packing.get("height")},
        "checklist": checklist,
        "bomLineCount": bom_qty,
        "packedLineCount": pack_qty,
        "reconciled": bom_qty == pack_qty,
        "source": "bom",
    }
    man["manifestHash"] = stable_hash({k: man[k] for k in man if k != "manifestHash"})
    return man


def auto_redesign_candidates(engine: CabinetEngine, rec: dict[str, Any], *, tenant_id: str, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Constrained redesign when oversize / waste / assembly / tools exceed policy. Engineering veto still applies."""
    p = {**DEFAULT_LOGISTICS_POLICY, **(policy or {})}
    kind = rec["spec"]["kind"] if isinstance(rec["spec"], dict) else rec["spec"].kind
    gate = rec.get("gate") or {}
    difficulty = rec.get("difficulty") or {}
    nesting = rec.get("nesting") or {}
    tools = tool_count_kpi(rec)
    triggers: list[str] = []
    if gate.get("hard"):
        triggers.extend(gate["hard"])
    if float(nesting.get("trueWasteRatio") or 0) > 0.35:
        triggers.append("TRUE_WASTE")
    if float(difficulty.get("score") or 0) > float(p.get("maxAssemblyDifficulty") or 0.75):
        triggers.append("ASSEMBLY_DIFFICULTY")
    if int(tools.get("toolCount") or 0) > 3:
        triggers.append("TOOL_COUNT")
    if not triggers:
        return {"triggered": False, "candidates": [], "engineeringVetoAlways": True}
    registry = FlatPackProductTypeRegistry()
    grid = registry.grid(kind)
    spec = rec["spec"] if isinstance(rec["spec"], dict) else rec["spec"].model_dump()
    candidates = []
    for w in grid["width"]:
        for d in grid["depth"]:
            for h in grid["height"]:
                if w == spec["width"] and d == spec["depth"] and h == spec["height"]:
                    continue
                if w > spec["width"] or h > spec["height"]:
                    continue
                built = build_flatpack_spec(engine, tenant_id=tenant_id, kind=kind, width=w, depth=d, height=h, material=spec.get("material"))
                if not built["report"]["ok"]:
                    continue
                candidates.append(
                    {
                        "kind": kind,
                        "width": w,
                        "depth": d,
                        "height": h,
                        "engineeringHash": built["engineeringHash"],
                        "oversize": built["shipping"]["oversize"],
                        "trueWasteRatio": None,
                        "difficulty": built["difficulty"]["score"],
                        "reportOk": built["report"]["ok"],
                    }
                )
                if len(candidates) >= 4:
                    break
            if len(candidates) >= 4:
                break
        if len(candidates) >= 4:
            break
    return {
        "triggered": True,
        "triggers": triggers,
        "candidates": candidates,
        "engineeringVetoAlways": True,
        "note": "Variant generator is constrained; Engineering Rule Engine veto remains hard.",
    }
