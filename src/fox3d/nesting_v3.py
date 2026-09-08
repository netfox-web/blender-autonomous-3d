"""Nesting Optimizer V3 — strategy registry on top of the guillotine baseline.

Does not delete NestingEngine. Not a CAM/saw driver. liveMachineControl=false.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Protocol

from fox3d.ids import stable_hash
from fox3d.inventory import remnant_value
from fox3d.manufacturing import NestingEngine, SheetMaterialRegistry
from fox3d.parametric import map_cabinet_material


class NestingStrategy(Protocol):
    name: str

    def nest(self, parts: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]: ...


def _part_sort_key(part: dict[str, Any], mode: str, seed: str) -> tuple:
    L, W = float(part["length"]), float(part["width"])
    pid = str(part.get("partId") or "")
    if mode == "area":
        return (-L * W, -max(L, W), pid)
    if mode == "min_side":
        return (-min(L, W), -max(L, W), pid)
    if mode == "width":
        return (-L, -W, pid)
    if mode == "seed":
        digest = hashlib.sha256(f"{seed}:{pid}".encode()).hexdigest()
        return (digest, -max(L, W), pid)
    return (-max(L, W), -min(L, W), pid)


class GuillotineBaselineStrategy:
    name = "guillotine_baseline"

    def __init__(self, engine: NestingEngine | None = None) -> None:
        self.engine = engine or NestingEngine()

    def nest(self, parts: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("strategy", "guillotine")
        kwargs.setdefault("objective", "min_sheets")
        kwargs.setdefault("seed", "baseline")
        result = self.engine.nest_parts(parts, **kwargs)
        result["strategy"] = self.name
        return result


class BestFitDecreasingStrategy:
    name = "best_fit_decreasing"

    def __init__(self, engine: NestingEngine | None = None) -> None:
        self.engine = engine or NestingEngine()

    def nest(self, parts: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("strategy", "best_fit")
        kwargs.setdefault("objective", "min_sheets")
        kwargs.setdefault("seed", "bfd")
        result = self.engine.nest_parts(parts, **kwargs)
        result["strategy"] = self.name
        return result


class NestingStrategyRegistry:
    def __init__(self, engine: NestingEngine | None = None) -> None:
        self.engine = engine or NestingEngine()
        self._strategies: dict[str, NestingStrategy] = {
            "guillotine_baseline": GuillotineBaselineStrategy(self.engine),
            "best_fit_decreasing": BestFitDecreasingStrategy(self.engine),
        }

    def list(self) -> list[str]:
        return list(self._strategies)

    def get(self, name: str) -> NestingStrategy:
        return self._strategies[name]

    def register(self, strategy: NestingStrategy) -> None:
        self._strategies[strategy.name] = strategy


def score_layout(result: dict[str, Any], *, remnant_cost_per_m2: float = 280.0) -> dict[str, Any]:
    veto = bool(result.get("unplaceable")) or bool(result.get("illegal"))
    sheets = int(result.get("sheetCount") or 0)
    scrap = float(result.get("trueWasteRatio") or 0)
    rem_area = float(result.get("reusableRemnantArea") or 0)
    cut_count = int(result.get("cutCount") or 0)
    grain_pen = float(result.get("grainViolations") or 0)
    lot_split = int(result.get("materialLotSplit") or 0)
    candidates = result.get("candidateRemnants") or []
    best_rect = max((float(c.get("w") or 0) * float(c.get("h") or 0) for c in candidates), default=0.0)
    val = remnant_value({"w": (best_rect ** 0.5), "h": (best_rect ** 0.5), "createdAt": None}, cost_per_m2=remnant_cost_per_m2)
    # Prefer fewer new sheets, then less true scrap, then more useful leftover rectangles.
    score = (
        -1000.0 * sheets
        - 80.0 * scrap
        + 0.00001 * rem_area
        + 0.000004 * best_rect
        - 0.15 * cut_count
        - 25.0 * grain_pen
        - 8.0 * lot_split
    )
    return {
        "score": round(score, 4),
        "veto": veto,
        "sheetCount": sheets,
        "trueWasteRatio": scrap,
        "reusableRemnantRatio": result.get("reusableRemnantRatio"),
        "reusableRemnantValue": val,
        "cutCount": cut_count,
        "grainViolations": grain_pen,
        "materialLotSplit": lot_split,
        "bestReusableRectArea": best_rect,
        "source": "deterministic",
    }


def cut_sequence_manifest(result: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for sheet in result.get("sheets") or []:
        placed = sorted(sheet.get("placements") or [], key=lambda p: (float(p["y"]), float(p["x"]), str(p.get("partId"))))
        ys = sorted({round(float(p["y"]), 3) for p in placed} | {round(float(p["y"]) + float(p["h"]), 3) for p in placed})
        xs = sorted({round(float(p["x"]), 3) for p in placed} | {round(float(p["x"]) + float(p["w"]), 3) for p in placed})
        for y in ys:
            steps.append({"sheetIndex": sheet["index"], "op": "RIP", "axis": "y", "pos": y, "liveMachineControl": False})
        for x in xs:
            steps.append({"sheetIndex": sheet["index"], "op": "CROSS", "axis": "x", "pos": x, "liveMachineControl": False})
        for p in placed:
            steps.append(
                {
                    "sheetIndex": sheet["index"],
                    "op": "PART",
                    "partId": p.get("partId"),
                    "skuId": p.get("skuId"),
                    "bomLineId": p.get("bomLineId"),
                    "x": p.get("x"),
                    "y": p.get("y"),
                    "w": p.get("w"),
                    "h": p.get("h"),
                    "liveMachineControl": False,
                }
            )
    man = {
        "kind": "saw-friendly-cut-sequence",
        "sheetCount": result.get("sheetCount"),
        "steps": steps,
        "cutCount": len([s for s in steps if s["op"] in {"RIP", "CROSS"}]),
        "liveMachineControl": False,
        "notCamDriver": True,
    }
    man["manifestHash"] = stable_hash({k: man[k] for k in man if k != "manifestHash"})
    return man


class NestingV3:
    """Multi-start deterministic search with multi-objective scoring. Falls back to baseline."""

    def __init__(self, engine: NestingEngine | None = None, *, max_candidates: int = 8, max_seconds: float = 2.0) -> None:
        self.engine = engine or NestingEngine()
        self.registry = NestingStrategyRegistry(self.engine)
        self.max_candidates = max_candidates
        self.max_seconds = max_seconds

    def nest_parts(self, parts: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        objective = kwargs.pop("objective", "multi")
        seed = str(kwargs.get("seed") or "v3")
        modes = ("max_side", "area", "min_side", "width", "seed")
        strategies = ("guillotine_baseline", "best_fit_decreasing")
        candidates: list[dict[str, Any]] = []
        n = 0
        for strat_name in strategies:
            for mode in modes:
                if n >= self.max_candidates or (time.perf_counter() - started) > self.max_seconds:
                    break
                ordered = sorted(parts, key=lambda p: _part_sort_key(p, mode, f"{seed}:{mode}:{strat_name}"))
                kwargs_run = dict(kwargs)
                kwargs_run["seed"] = f"{seed}:{strat_name}:{mode}"
                kwargs_run["objective"] = "reusable_offcut" if objective == "reusable_offcut" else "min_sheets"
                result = self.registry.get(strat_name).nest(ordered, **kwargs_run)
                result["sortMode"] = mode
                seq = cut_sequence_manifest(result)
                result["cutSequence"] = seq
                result["cutCount"] = seq["cutCount"]
                result["scored"] = score_layout(result)
                candidates.append(result)
                n += 1
        legal = [c for c in candidates if not c["scored"]["veto"]]
        pool = legal or candidates
        baseline = next((c for c in pool if c.get("strategy") == "guillotine_baseline" and c.get("sortMode") == "max_side"), pool[0])
        if objective == "reusable_offcut":
            # Same sheet count: prefer larger reusable rectangle.
            best = min(
                pool,
                key=lambda c: (
                    c["scored"]["veto"],
                    c["scored"]["sheetCount"],
                    -c["scored"]["bestReusableRectArea"],
                    c["scored"]["trueWasteRatio"],
                    c.get("nestingHash") or "",
                ),
            )
        else:
            best = min(pool, key=lambda c: (c["scored"]["veto"], -c["scored"]["score"], c.get("nestingHash") or ""))
        # Honest fallback: if V3 uses more sheets than baseline, keep baseline.
        chosen = best
        fallback = False
        if best["scored"]["sheetCount"] > baseline["scored"]["sheetCount"]:
            chosen = baseline
            fallback = True
        chosen = dict(chosen)
        chosen["candidatesEvaluated"] = len(candidates)
        chosen["runtimeSec"] = round(time.perf_counter() - started, 4)
        chosen["fallbackToBaseline"] = fallback
        chosen["selector"] = "nesting_v3"
        chosen["objective"] = objective
        chosen["liveMachineControl"] = False
        return chosen

    def nest(self, bom: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        parts = self.engine.parts_from_bom(bom, material=str(kwargs.get("material") or "WOOD_WHITE"), thickness=float(kwargs.get("thickness") or 18))
        return self.nest_parts(parts, **{k: v for k, v in kwargs.items() if k != "bom"})


def parts_from_simple_panels(panels: list[dict[str, Any]], *, sku_id: str = "sku") -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for i, ln in enumerate(panels):
        qty = int(ln.get("quantity") or 1)
        for q in range(qty):
            parts.append(
                {
                    "partId": f"{sku_id}:{ln.get('partId') or ln.get('partName') or i}#{q+1}",
                    "partName": ln.get("partName") or ln.get("partId"),
                    "length": float(ln["length"]),
                    "width": float(ln["width"]),
                    "grain": ln.get("grain") or ln.get("grainDirection") or "none",
                    "skuId": ln.get("skuId") or sku_id,
                    "productVersion": ln.get("productVersion") or 1,
                    "bomLineId": ln.get("partId") or ln.get("partName") or str(i),
                    "materialLotId": ln.get("materialLotId"),
                }
            )
    return parts


BENCHMARK_FIXTURES: list[dict[str, Any]] = [
    {"name": "desk_riser_x4", "kind": "DESK_RISER", "qty": 4},
    {"name": "bedside_x2", "kind": "BEDSIDE_CABINET", "qty": 2},
    {"name": "open_shelf", "kind": "OPEN_SHELF", "qty": 1},
    {"name": "pet_x3", "kind": "PET_FURNITURE", "qty": 3},
    {"name": "storage_bench", "kind": "STORAGE_BENCH", "qty": 1},
    {"name": "narrow_book", "kind": "NARROW_BOOKCASE", "qty": 1},
    {"name": "mobile_table_x2", "kind": "MOBILE_SIDE_TABLE", "qty": 2},
    {"name": "garment_rack", "kind": "GARMENT_RACK", "qty": 1},
    {"name": "appliance_rack", "kind": "APPLIANCE_RACK", "qty": 1},
    {"name": "student_desk", "kind": "STUDENT_DESK", "qty": 1},
]


def run_benchmark(platform: Any, *, tenant_id: str = "bench") -> dict[str, Any]:
    from fox3d.kd import build_flatpack_spec

    engine = NestingEngine()
    v3 = NestingV3(engine)
    rows: list[dict[str, Any]] = []
    for fx in BENCHMARK_FIXTURES:
        rec = build_flatpack_spec(platform.cabinets, tenant_id=tenant_id, kind=fx["kind"])
        lines = []
        for ln in rec["bom"]["lines"]:
            item = dict(ln)
            item["quantity"] = int(ln.get("quantity") or 1) * int(fx["qty"])
            item["skuId"] = rec["spec"]["productId"]
            item["productVersion"] = rec["spec"].get("revision") or 1
            item["bomLineId"] = ln.get("partId")
            lines.append(item)
        bom = {"productId": rec["spec"]["productId"], "lines": lines, "revision": rec["spec"].get("revision") or 1}
        t0 = time.perf_counter()
        base = engine.nest(bom, material=str(rec["spec"]["material"]), thickness=float(rec["spec"]["boardThickness"]), seed="baseline")
        t1 = time.perf_counter()
        opt = v3.nest(bom, material=str(rec["spec"]["material"]), thickness=float(rec["spec"]["boardThickness"]), seed="v3")
        t2 = time.perf_counter()
        seq = opt.get("cutSequence") or cut_sequence_manifest(opt)
        rows.append(
            {
                "name": fx["name"],
                "kind": fx["kind"],
                "qty": fx["qty"],
                "baseline": {
                    "sheetCount": base["sheetCount"],
                    "trueWasteRatio": base.get("trueWasteRatio"),
                    "reusableRemnantRatio": base.get("reusableRemnantRatio"),
                    "cutCount": cut_sequence_manifest(base)["cutCount"],
                    "runtimeSec": round(t1 - t0, 4),
                    "strategy": "guillotine_baseline",
                },
                "v3": {
                    "sheetCount": opt["sheetCount"],
                    "trueWasteRatio": opt.get("trueWasteRatio"),
                    "reusableRemnantRatio": opt.get("reusableRemnantRatio"),
                    "cutCount": seq["cutCount"],
                    "runtimeSec": round(t2 - t1, 4),
                    "strategy": opt.get("strategy"),
                    "fallbackToBaseline": opt.get("fallbackToBaseline"),
                    "score": (opt.get("scored") or {}).get("score"),
                },
                "v3BetterSheets": int(opt["sheetCount"]) < int(base["sheetCount"]),
                "v3WorseSheets": int(opt["sheetCount"]) > int(base["sheetCount"]),
            }
        )
    wins = sum(1 for r in rows if r["v3BetterSheets"])
    losses = sum(1 for r in rows if r["v3WorseSheets"])
    return {
        "cases": rows,
        "v3SheetWins": wins,
        "v3SheetLosses": losses,
        "note": "Honest benchmark; selector may fall back to baseline. Not all cases win.",
        "liveMachineControl": False,
        "materialMapped": map_cabinet_material("WOOD_WHITE"),
        "sheet": SheetMaterialRegistry().for_cabinet_material("WOOD_WHITE"),
    }
