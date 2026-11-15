"""Unit tests for fox3d.safety dimension validation (fail-closed)."""

from __future__ import annotations

import math

import pytest

from fox3d.safety import (
    SafetyRuleRegistry,
    acrylic_risk,
    assembly_safety,
    compliance_boundary,
    evaluate_product,
    furniture_stability,
    pinch_zones,
    retail_fixture_risk,
    shelf_load_warning,
    wall_anchor_warning,
)

def _assert_blocked(result: dict, rule_id: str) -> None:
    assert result["ruleId"] == rule_id
    assert result["ok"] is False
    assert result["veto"] is True
    assert result["label"] == "BLOCKED"
    assert result["error"] == "invalid_dimension"


def test_furniture_stability_legal_locked():
    spec = {"width": 400, "depth": 350, "height": 800}
    out = furniture_stability(spec)
    assert out == {
        "comZmm": 360.0,
        "baseMm": 350.0,
        "heightOverBase": 2.286,
        "tilt10ShiftMm": 63.47,
        "ok": True,
        "label": "ENGINEERING_ESTIMATE",
        "certification": False,
        "ruleId": "FURN_STABILITY_V1",
        "veto": False,
    }


def test_wall_anchor_warning_legal_locked():
    out = wall_anchor_warning({"width": 400, "depth": 250, "height": 1600})
    assert out == {
        "required": True,
        "ratio": 6.4,
        "approvalRequired": True,
        "ruleId": "FURN_WALL_ANCHOR_V1",
        "label": "ENGINEERING_ESTIMATE",
    }


def test_shelf_load_warning_legal_locked():
    out = shelf_load_warning({"width": 800, "boardThickness": 18})
    assert out == {
        "spanMm": 764.0,
        "conservativeKg": 6.28,
        "label": "PARTIAL",
        "source": "ENGINEERING_ESTIMATE",
        "structuralAnalysis": False,
        "ruleId": "FURN_SHELF_LOAD_V1",
    }


def test_retail_fixture_risk_legal_locked():
    out = retail_fixture_risk(
        {"spec": {"width": 600, "depth": 400, "height": 1200}, "capacity": {"estimatedTotalKg": 25}}
    )
    assert out == {
        "estimatedKg": 25.0,
        "comHeightMm": 660.0,
        "baseMm": 400.0,
        "riskScore": 0.6425,
        "electricalCompliance": "BLOCKED",
        "label": "ENGINEERING_ESTIMATE",
        "ruleId": "RETAIL_TIP_V1",
        "veto": False,
    }


def test_acrylic_risk_legal_locked():
    out = acrylic_risk({"dimensions": {"width": 200, "height": 300}, "sheet": {"thickness": 5}, "cutBend": {}})
    assert out == {
        "warnings": ["EDGE_EXPOSURE"],
        "liveLaser": False,
        "label": "ENGINEERING_ESTIMATE",
        "ruleId": "ACR_SPAN_V1",
        "veto": False,
    }


@pytest.mark.parametrize(
    "bad",
    ["nan", "NaN", float("nan"), float("inf"), float("-inf"), 0, -1, "", "x", None, [], {}],
)
def test_furniture_stability_bad_width_vetoes(bad):
    spec = {"width": bad, "depth": 180, "height": 900}
    if bad is None:
        spec = {"depth": 180, "height": 900}
    out = furniture_stability(spec)
    _assert_blocked(out, "FURN_STABILITY_V1")


@pytest.mark.parametrize("field", ["height", "depth", "width"])
def test_furniture_stability_missing_field_vetoes(field):
    spec = {"width": 400, "depth": 350, "height": 800}
    del spec[field]
    _assert_blocked(furniture_stability(spec), "FURN_STABILITY_V1")


def test_wall_anchor_bad_and_missing_vetoes():
    _assert_blocked(wall_anchor_warning({"height": "nan", "depth": 200}), "FURN_WALL_ANCHOR_V1")
    _assert_blocked(wall_anchor_warning({"depth": 200}), "FURN_WALL_ANCHOR_V1")


def test_shelf_load_bad_and_missing_vetoes():
    _assert_blocked(shelf_load_warning({"width": 0, "boardThickness": 18}), "FURN_SHELF_LOAD_V1")
    _assert_blocked(shelf_load_warning({"boardThickness": 18}), "FURN_SHELF_LOAD_V1")
    _assert_blocked(shelf_load_warning({"width": 800, "boardThickness": -3}), "FURN_SHELF_LOAD_V1")


def test_retail_fixture_invalid_spec_vetoes():
    _assert_blocked(
        retail_fixture_risk({"spec": {"width": "nan", "depth": 400, "height": 800}, "capacity": {}}),
        "RETAIL_TIP_V1",
    )


@pytest.mark.parametrize(
    "dims",
    [
        {},
        {"width": 0, "height": 100},
        {"width": 100, "height": float("inf")},
        {"width": "nan", "height": 200},
    ],
)
def test_acrylic_invalid_dimensions_veto(dims):
    _assert_blocked(
        acrylic_risk({"dimensions": dims, "sheet": {"thickness": 5}, "cutBend": {}}),
        "ACR_SPAN_V1",
    )


def test_evaluate_product_nan_spec_veto():
    rec = {"spec": {"width": "nan", "depth": 180, "height": 900}}
    ev = evaluate_product("KD", rec)
    assert ev["veto"] is True
    assert any(c.get("error") == "invalid_dimension" for c in ev["checks"])


def test_evaluate_product_kd_empty_spec_veto():
    ev = evaluate_product("KD", {"spec": {}})
    assert ev["veto"] is True
    assert len(ev["checks"]) == 4
    assert all(c.get("error") == "invalid_dimension" for c in ev["checks"][:3])
    assert ev["checks"][3]["ruleId"] == "FURN_PINCH_V1"


def test_evaluate_product_acrylic_empty_cut_bend_veto():
    ev = evaluate_product(
        "ACRYLIC",
        {"dimensions": {"width": 0, "height": 100}, "sheet": {"thickness": 5}, "cutBend": {}},
    )
    assert ev["veto"] is True
    assert any(c.get("ruleId") == "ACR_SPAN_V1" and c.get("error") == "invalid_dimension" for c in ev["checks"])


def test_evaluate_product_invalid_width_with_door_veto():
    ev = evaluate_product("KD", {"spec": {"width": "x", "depth": 180, "height": 900, "doorCount": 1}})
    assert ev["veto"] is True
    pinch = next(c for c in ev["checks"] if c.get("ruleId") == "FURN_PINCH_V1")
    assert pinch.get("label") == "BLOCKED"


def test_evaluate_product_missing_width_with_door_veto():
    ev = evaluate_product("KD", {"spec": {"depth": 180, "height": 900, "doorCount": 1}})
    assert ev["veto"] is True
    pinch = next(c for c in ev["checks"] if c.get("ruleId") == "FURN_PINCH_V1")
    _assert_blocked(pinch, "FURN_PINCH_V1")


def test_pinch_zones_drawer_invalid_depth_blocked():
    _assert_blocked(pinch_zones({"drawerCount": 1, "width": 400, "depth": 0}), "FURN_PINCH_V1")


def test_assembly_safety_depth_zero_blocked_manifest():
    man = assembly_safety({"spec": {"depth": 0, "height": 900}, "instructionsV2": {"steps": [{"id": "s1"}]}})
    assert man["blocked"] is True
    assert man["steps"][0]["wallAnchor"] is False
    assert any(b.get("ruleId") == "FURN_WALL_ANCHOR_V1" for b in man["safetyBlocks"])


def test_shelf_load_huge_thickness_veto():
    _assert_blocked(shelf_load_warning({"width": 800, "boardThickness": 1e308}), "FURN_SHELF_LOAD_V1")


def test_shelf_load_huge_integer_thickness_veto():
    _assert_blocked(shelf_load_warning({"width": 800, "boardThickness": 10**400}), "FURN_SHELF_LOAD_V1")


def test_evaluate_product_retail_invalid_veto():
    rec = {
        "family": "COUNTER_DISPLAY",
        "spec": {"width": -10, "depth": 400, "height": 800},
        "capacity": {},
    }
    ev = evaluate_product("RETAIL", rec)
    assert ev["veto"] is True


def test_compliance_boundary_certification_flags():
    checks = [
        furniture_stability({"width": 400, "depth": 350, "height": 800}),
        wall_anchor_warning({"width": 400, "depth": 250, "height": 800}),
    ]
    b = compliance_boundary(checks)
    assert b["notCertified"] is True
    assert b["certificationRequired"] is True


def test_safety_rule_registry_scope_filter():
    reg = SafetyRuleRegistry()
    all_rules = reg.list()
    assert len(all_rules) >= 7
    kd = reg.list(scope="KD_FURNITURE")
    assert kd and all("KD_FURNITURE" in r["scope"] for r in kd)
    assert all(r["ruleId"].startswith("FURN_") for r in kd)
    retail = reg.list(scope="RETAIL_FIXTURE")
    assert len(retail) == 1 and retail[0]["ruleId"] == "RETAIL_TIP_V1"
    acrylic = reg.list(scope="ACRYLIC_SHEET")
    assert len(acrylic) == 1 and acrylic[0]["ruleId"] == "ACR_SPAN_V1"
    pkg = reg.list(scope="PACKAGING_STRUCTURE")
    assert len(pkg) == 1 and pkg[0]["ruleId"] == "PKG_FIT_V1"
    assert math.isfinite(furniture_stability({"width": 1, "depth": 1, "height": 1})["baseMm"])