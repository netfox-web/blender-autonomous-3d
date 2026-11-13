"""Unit tests for fox3d.packv2 validators and estimators (issue #389)."""

from __future__ import annotations

import math

import pytest

from fox3d.packaging import BOX_FAMILIES, dieline_primitives
from fox3d.packv2 import (
    barcode_zone,
    board_grade,
    box_compression_estimate,
    carton_optimize,
    shipping_load_scenario,
    validate_bleed,
    validate_dieline,
)


def _die(panels, *, family="TRAY", crease=True, glue=True):
    return {
        "family": family,
        "panels": panels,
        "crease": [{"from": "a", "to": "b"}] if crease else [],
        "glue": [{"panelId": "a"}] if glue else [],
    }


# ---------------------------------------------------------------- validate_dieline


@pytest.mark.parametrize(
    "panel",
    [
        {"id": "p1", "h": 50},
        {"id": "p1", "w": 50},
        {"id": "p1"},
        {"id": "p1", "w": None, "h": 50},
        {"id": "p1", "w": "abc", "h": 50},
        {"id": "p1", "w": 50, "h": [1, 2]},
        {"id": "p1", "w": float("nan"), "h": 50},
        {"id": "p1", "w": float("inf"), "h": 50},
        {"id": "p1", "w": True, "h": 50},
        {"id": "p1", "w": 0, "h": 50},
        {"id": "p1", "w": -5, "h": 50},
    ],
)
def test_validate_dieline_bad_dims_reports_bounds_without_raising(panel):
    out = validate_dieline(_die([panel]))
    assert out["ok"] is False
    assert "bounds:p1" in out["errors"]
    # Invalid dims are a bounds error, not additionally a short flap.
    assert "short_flap:p1" not in out["errors"]


def test_validate_dieline_missing_dims_mixed_with_valid_panels():
    out = validate_dieline(_die([{"id": "a", "w": 100, "h": 50}, {"id": "b", "h": 50}]))
    assert out["errors"] == ["bounds:b"]


def test_validate_dieline_numeric_strings_accepted():
    out = validate_dieline(_die([{"id": "a", "w": "100", "h": "50.5"}]))
    assert out["ok"] is True


def test_validate_dieline_no_panels():
    for die in ({}, {"panels": []}, {"panels": None}):
        out = validate_dieline(die)
        assert out["ok"] is False
        assert out["errors"] == ["no_panels"]


def test_validate_dieline_short_flap_boundary():
    assert validate_dieline(_die([{"id": "a", "w": 8, "h": 8}]))["ok"] is True
    out = validate_dieline(_die([{"id": "a", "w": 7.99, "h": 100}]))
    assert out["errors"] == ["short_flap:a"]


def test_validate_dieline_duplicate_and_missing_crease_and_glue():
    panels = [{"id": "a", "w": 20, "h": 20}, {"id": "a", "w": 20, "h": 20}]
    out = validate_dieline(_die(panels, family="RSC_CARTON", crease=False, glue=False))
    assert "duplicate_panel" in out["errors"]
    assert "missing_crease" in out["errors"]
    assert "missing_glue" in out["errors"]
    assert out["foldConsistent"] is False
    # Single panel needs no crease; glue only required for RSC_CARTON / SLEEVE.
    single = validate_dieline(_die([{"id": "a", "w": 20, "h": 20}], family="TRAY", crease=False, glue=False))
    assert single["ok"] is True
    assert single["foldConsistent"] is True


def test_validate_dieline_overlap_uses_placed_coordinates():
    panels = [
        {"id": "a", "x": 0, "y": 0, "w": 100, "h": 50},
        {"id": "b", "x": 50, "y": 10, "w": 100, "h": 50},
    ]
    out = validate_dieline(_die(panels))
    assert out["ok"] is False
    assert out["errors"] == ["overlap:a:b"]


def test_validate_dieline_touching_edges_do_not_overlap():
    panels = [
        {"id": "a", "x": 0, "y": 0, "w": 100, "h": 50},
        {"id": "b", "x": 100, "y": 0, "w": 100, "h": 50},
        {"id": "c", "x": 0, "y": 50, "w": 100, "h": 50},
    ]
    assert validate_dieline(_die(panels))["ok"] is True


def test_validate_dieline_overlap_skips_panels_without_coordinates():
    # Without x/y the net is abstract/sequential and cannot overlap.
    panels = [
        {"id": "a", "w": 100, "h": 50},
        {"id": "b", "w": 100, "h": 50},
        {"id": "c", "x": 0, "y": 0, "w": 100, "h": 50},
    ]
    assert validate_dieline(_die(panels))["ok"] is True
    # A panel with bad dims and coordinates is a bounds error, not an overlap.
    bad = [
        {"id": "a", "x": 0, "y": 0, "w": 100, "h": 50},
        {"id": "b", "x": 10, "y": 10, "w": "x", "h": 50},
    ]
    assert validate_dieline(_die(bad))["errors"] == ["bounds:b"]


@pytest.mark.parametrize("family", BOX_FAMILIES)
def test_validate_dieline_generated_primitives_ok(family):
    die = dieline_primitives(family, {"length": 120, "width": 80, "height": 40})
    assert validate_dieline(die)["ok"] is True


# ---------------------------------------------------------------- validate_bleed


def test_validate_bleed_boundaries():
    assert validate_bleed({"zones": [{"name": "z", "bleedMm": 3, "safeMm": 5}]})["ok"] is True
    out = validate_bleed({"zones": [{"name": "z", "bleedMm": 2.99, "safeMm": 4.99}]})
    assert out["errors"] == ["bleed:z", "safe:z"]
    missing = validate_bleed({"zones": [{"name": "m"}]})
    assert missing["errors"] == ["bleed:m", "safe:m"]


def test_validate_bleed_no_zones_and_custom_thresholds():
    out = validate_bleed({})
    assert out["ok"] is True
    assert out["completePrintPreflight"] is False
    assert out["label"] == "PARTIAL"
    out = validate_bleed({"zones": [{"name": "z", "bleedMm": 3, "safeMm": 5}]}, min_bleed=4, min_safe=6)
    assert out["errors"] == ["bleed:z", "safe:z"]


# ---------------------------------------------------------------- barcode_zone


def test_barcode_zone_width_clamped_and_defaults():
    assert barcode_zone({"w": 120})["w"] == 40.0
    assert barcode_zone({"w": 25})["w"] == 25.0
    assert barcode_zone({"w": 40})["w"] == 40.0
    assert barcode_zone({})["w"] == 40.0
    zone = barcode_zone({"w": 0}, quiet_mm=5)
    assert zone["w"] == 40.0
    assert zone["quietZoneMm"] == 5
    assert zone["keepOut"] is True
    assert zone["validator"] is None
    assert zone["label"] == "PARTIAL"


# ---------------------------------------------------------------- box_compression_estimate


def test_box_compression_estimate_formula_and_labels():
    grade = board_grade("KRAFT_B_ECT32")
    out = box_compression_estimate(inner={"length": 300, "width": 200}, grade=grade)
    peri_in = 2 * 500 / 25.4
    expected_n = 5.87 * 32 * math.sqrt(peri_in * 3.0 / 25.4) * 4.448
    assert out["bctNewton"] == pytest.approx(expected_n, abs=0.01)
    assert out["allowableNewton"] == pytest.approx(expected_n / 3.0, abs=0.01)
    assert out["certification"] is False
    assert out["source"] == "ENGINEERING_ESTIMATE"
    assert out["grade"] == "KRAFT_B_ECT32"


def test_box_compression_estimate_stronger_grade_and_safety_factor():
    inner = {"length": 300, "width": 200}
    weak = box_compression_estimate(inner=inner, grade=board_grade("KRAFT_B_ECT32"))
    strong = box_compression_estimate(inner=inner, grade=board_grade("KRAFT_C_ECT44"))
    assert strong["bctNewton"] > weak["bctNewton"]
    sf6 = box_compression_estimate(inner=inner, grade=board_grade("KRAFT_B_ECT32"), safety_factor=6)
    assert sf6["allowableNewton"] == pytest.approx(weak["allowableNewton"] / 2, abs=0.01)


def test_box_compression_estimate_zero_dims_and_empty_grade_floor():
    out = box_compression_estimate(inner={"length": 0, "width": 0}, grade={})
    # perimeter*caliper floored at 0.01, defaults ECT 32
    assert out["bctNewton"] == pytest.approx(5.87 * 32 * 0.1 * 4.448, abs=0.01)
    assert out["grade"] is None


def test_shipping_load_scenario_single_box_has_no_top_load():
    comp = {"allowableNewton": 100.0}
    one = shipping_load_scenario(product_weight_kg=10, stack_count=1, compression=comp)
    assert one["topLoadNewton"] == 0
    assert one["ok"] is True
    heavy = shipping_load_scenario(product_weight_kg=10, stack_count=3, compression=comp)
    assert heavy["topLoadNewton"] == pytest.approx(196.2)
    assert heavy["ok"] is False


def test_board_grade_returns_copy():
    g = board_grade("KRAFT_B_ECT32")
    g["ectLbIn"] = 0
    assert board_grade("KRAFT_B_ECT32")["ectLbIn"] == 32.0
    with pytest.raises(KeyError):
        board_grade("NOPE")


# ---------------------------------------------------------------- carton_optimize


def test_carton_optimize_candidates_cover_all_families():
    out = carton_optimize({"width": 120, "height": 80, "depth": 40}, grade=board_grade("KRAFT_B_ECT32"))
    fams = [c["family"] for c in out["candidates"]]
    assert sorted(fams) == sorted(BOX_FAMILIES)
    assert out["engineeringVetoFirst"] is True
    chosen = out["chosen"]
    assert chosen["engineeringVeto"] is False
    legal = [c for c in out["candidates"] if not c["engineeringVeto"]]
    assert chosen["score"] == max(c["score"] for c in legal)


def test_carton_optimize_tiny_product_vetoes_short_flaps():
    # Very small product yields sub-8mm flaps for some families -> engineering veto, score None.
    out = carton_optimize({"width": 2, "height": 2, "depth": 2}, grade=board_grade("KRAFT_B_ECT32"))
    assert any(c["engineeringVeto"] for c in out["candidates"])
    for c in out["candidates"]:
        if c["engineeringVeto"]:
            assert c["score"] is None
        else:
            assert isinstance(c["score"], float)
    assert out["chosen"] in out["candidates"]
    assert out["chosen"]["engineeringVeto"] is False
