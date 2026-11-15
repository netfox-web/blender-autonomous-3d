"""Product safety / DFM risk engine. Not a regulatory certification."""

from __future__ import annotations

import math
from typing import Any

from fox3d.ids import stable_hash

SAFETY_RULES: dict[str, dict[str, Any]] = {
    "FURN_STABILITY_V1": {"scope": ["KD_FURNITURE"], "severity": "warning", "version": 1, "assumption": "uniform density, geometric COM"},
    "FURN_WALL_ANCHOR_V1": {"scope": ["KD_FURNITURE"], "severity": "warning", "version": 1, "assumption": "height/depth ratio policy"},
    "FURN_PINCH_V1": {"scope": ["KD_FURNITURE"], "severity": "info", "version": 1, "assumption": "door/drawer sweep boxes"},
    "FURN_SHELF_LOAD_V1": {"scope": ["KD_FURNITURE"], "severity": "warning", "version": 1, "assumption": "span/thickness conservative table"},
    "RETAIL_TIP_V1": {"scope": ["RETAIL_FIXTURE"], "severity": "warning", "version": 1, "assumption": "planogram mass at shelf mid-height"},
    "ACR_SPAN_V1": {"scope": ["ACRYLIC_SHEET"], "severity": "warning", "version": 1, "assumption": "unsupported span vs thickness"},
    "PKG_FIT_V1": {"scope": ["PACKAGING_STRUCTURE"], "severity": "error", "version": 1, "assumption": "inner > product+clearance"},
}


class SafetyRuleRegistry:
    def list(self, *, scope: str | None = None) -> list[dict[str, Any]]:
        rows = [{"ruleId": k, **v} for k, v in SAFETY_RULES.items()]
        if scope:
            rows = [r for r in rows if scope in r["scope"]]
        return rows


def _positive_finite_dimension(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or isinstance(value, (list, dict)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _invalid_dimension(rule_id: str) -> dict[str, Any]:
    return {
        "ok": False,
        "veto": True,
        "label": "BLOCKED",
        "error": "invalid_dimension",
        "ruleId": rule_id,
    }


def _spec_dimension(spec: dict[str, Any], key: str, *, default: float | None = None) -> float | None:
    if key not in spec:
        if default is not None:
            return default
        return None
    return _positive_finite_dimension(spec.get(key))


def furniture_stability(spec: dict[str, Any]) -> dict[str, Any]:
    w = _positive_finite_dimension(spec.get("width"))
    d = _positive_finite_dimension(spec.get("depth"))
    h = _positive_finite_dimension(spec.get("height"))
    if w is None or d is None or h is None:
        return _invalid_dimension("FURN_STABILITY_V1")
    com_z = h * 0.45
    base = min(w, d)
    ratio = h / max(base, 1)
    # 10° tilt: horizontal COM shift = com_z * tan(10°)
    shift = com_z * 0.1763
    ok = shift < base / 2
    return {
        "comZmm": round(com_z, 2),
        "baseMm": base,
        "heightOverBase": round(ratio, 3),
        "tilt10ShiftMm": round(shift, 2),
        "ok": ok,
        "label": "ENGINEERING_ESTIMATE",
        "certification": False,
        "ruleId": "FURN_STABILITY_V1",
        "veto": ratio >= 5 and not ok,
    }


def wall_anchor_warning(spec: dict[str, Any], *, max_ratio: float = 3.5, tall_mm: float = 1200) -> dict[str, Any]:
    h = _positive_finite_dimension(spec.get("height"))
    d = _positive_finite_dimension(spec.get("depth"))
    if h is None or d is None:
        return _invalid_dimension("FURN_WALL_ANCHOR_V1")
    ratio = h / max(d, 1)
    need = h >= tall_mm or ratio >= max_ratio
    return {
        "required": need,
        "ratio": round(ratio, 3),
        "approvalRequired": need,
        "ruleId": "FURN_WALL_ANCHOR_V1",
        "label": "ENGINEERING_ESTIMATE",
    }


def pinch_zones(spec: dict[str, Any]) -> dict[str, Any]:
    zones = []
    if int(spec.get("doorCount") or 0):
        zones.append({"kind": "door_sweep", "radiusMm": float(spec["width"]) * 0.5, "pinch": True})
        zones.append({"kind": "door_edge", "sharp": True})
    if int(spec.get("drawerCount") or 0):
        zones.append({"kind": "drawer_extension", "lengthMm": float(spec["depth"]) * 0.8, "pinch": True})
    return {"zones": zones, "ruleId": "FURN_PINCH_V1", "label": "ENGINEERING_ESTIMATE"}


def shelf_load_warning(spec: dict[str, Any]) -> dict[str, Any]:
    w = _positive_finite_dimension(spec.get("width"))
    if w is None:
        return _invalid_dimension("FURN_SHELF_LOAD_V1")
    if "boardThickness" in spec:
        t = _positive_finite_dimension(spec.get("boardThickness"))
        if t is None:
            return _invalid_dimension("FURN_SHELF_LOAD_V1")
    else:
        t = 18.0
    span = w - 2 * t
    # conservative kg for PB: 12kg per 400mm span at 18mm, scale t^2 / span
    cap = 12.0 * (t / 18.0) ** 2 * (400.0 / max(span, 1))
    return {
        "spanMm": span,
        "conservativeKg": round(cap, 2),
        "label": "PARTIAL",
        "source": "ENGINEERING_ESTIMATE",
        "structuralAnalysis": False,
        "ruleId": "FURN_SHELF_LOAD_V1",
    }


def retail_fixture_risk(fixture: dict[str, Any]) -> dict[str, Any]:
    cap = fixture.get("capacity") or {}
    spec = fixture.get("spec") or {}
    kg = float(cap.get("estimatedTotalKg") or 0)
    h = _spec_dimension(spec, "height", default=800.0)
    w = _spec_dimension(spec, "width", default=600.0)
    d = _spec_dimension(spec, "depth", default=400.0)
    if h is None or w is None or d is None:
        return _invalid_dimension("RETAIL_TIP_V1")
    base = min(w, d)
    com_z = h * 0.55
    score = min(1.0, (kg / 40.0) * 0.5 + (com_z / max(base, 1)) * 0.2)
    return {
        "estimatedKg": kg,
        "comHeightMm": com_z,
        "baseMm": base,
        "riskScore": round(score, 4),
        "electricalCompliance": "BLOCKED",
        "label": "ENGINEERING_ESTIMATE",
        "ruleId": "RETAIL_TIP_V1",
        "veto": score >= 0.95,
    }


def acrylic_risk(rec: dict[str, Any]) -> dict[str, Any]:
    dims = rec.get("dimensions") or {}
    sheet = rec.get("sheet") or {}
    if "thickness" in sheet:
        t = _positive_finite_dimension(sheet.get("thickness"))
        if t is None:
            return _invalid_dimension("ACR_SPAN_V1")
    else:
        t = 5.0

    def _span_axis(key: str) -> float | None:
        if key not in dims:
            return 0.0
        return _positive_finite_dimension(dims.get(key))

    w = _span_axis("width")
    h = _span_axis("height")
    if w is None or h is None:
        return _invalid_dimension("ACR_SPAN_V1")
    span = max(w, h)
    if span <= 0:
        return _invalid_dimension("ACR_SPAN_V1")
    bend = rec.get("cutBend") or {}
    warnings = []
    if t < 4:
        warnings.append("THIN_SHEET")
    if span / max(t, 0.1) > 80:
        warnings.append("UNSUPPORTED_SPAN")
    if bend.get("bends") and t < 6:
        warnings.append("BEND_PROXIMITY")
    warnings.append("EDGE_EXPOSURE")
    return {
        "warnings": warnings,
        "liveLaser": False,
        "label": "ENGINEERING_ESTIMATE",
        "ruleId": "ACR_SPAN_V1",
        "veto": "UNSUPPORTED_SPAN" in warnings and span > 600,
    }


def assembly_safety(rec: dict[str, Any]) -> dict[str, Any]:
    spec = rec["spec"] if isinstance(rec.get("spec"), dict) else rec.get("spec") or rec
    tools = rec.get("tools") or {}
    pinch = pinch_zones(spec if isinstance(spec, dict) else {})
    wall = wall_anchor_warning(spec if isinstance(spec, dict) else rec.get("spec") or {})
    two = bool((rec.get("assemblyGraph") or {}).get("twoPerson"))
    steps = []
    for st in (rec.get("instructionsV2") or {}).get("steps") or []:
        steps.append(
            {
                **st,
                "pinch": bool(pinch["zones"]),
                "twoPersonLift": two,
                "wallAnchor": wall["required"],
                "tools": st.get("tools") or tools.get("tools"),
            }
        )
    man = {"steps": steps, "source": "assembly_v2+safety", "traceable": True}
    man["manifestHash"] = stable_hash(man)
    return man


def compliance_boundary(checked: list[dict[str, Any]]) -> dict[str, Any]:
    unresolved = [c["ruleId"] for c in checked if c.get("label") in {"PARTIAL", "ENGINEERING_ESTIMATE"} and c.get("veto") is not True]
    return {
        "checkedRules": [c.get("ruleId") for c in checked],
        "assumptions": [c.get("assumption") or c.get("label") for c in checked],
        "unresolved": unresolved,
        "certificationRequired": True,
        "notCertified": True,
        "liveMachineControl": False,
    }


def evaluate_product(kind: str, rec: dict[str, Any]) -> dict[str, Any]:
    checks = []
    veto = False
    if kind in {"KD_FURNITURE", "KD"} or rec.get("spec"):
        spec = rec["spec"] if isinstance(rec.get("spec"), dict) else rec.get("spec") or {}
        if spec:
            st = furniture_stability(spec)
            wa = wall_anchor_warning(spec)
            sh = shelf_load_warning(spec)
            checks.extend([st, wa, sh, pinch_zones(spec)])
    if rec.get("family") in {"COUNTER_DISPLAY", "FLOOR_DISPLAY", "PDQ_DISPLAY", "RISER_DISPLAY", "PEGBOARD_DISPLAY", "ENDCAP_MODULE"} or rec.get("planogram"):
        rt = retail_fixture_risk(rec)
        checks.append(rt)
    if rec.get("sheet") and rec.get("cutBend"):
        ac = acrylic_risk(rec)
        checks.append(ac)
    for check in checks:
        veto = veto or bool(check.get("veto"))
    boundary = compliance_boundary(checks)
    return {"checks": checks, "veto": veto, "boundary": boundary, "notCertified": True}
