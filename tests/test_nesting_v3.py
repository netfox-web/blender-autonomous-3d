"""Offline unit coverage for the nesting V3 helpers and strategies."""

import copy

import pytest

from fox3d.nesting_v3 import (
    NestingStrategyRegistry,
    cut_sequence_manifest,
    parts_from_simple_panels,
    score_layout,
)


@pytest.mark.parametrize("flag", ["unplaceable", "illegal"])
def test_score_layout_vetoes_invalid_results(flag):
    assert score_layout({flag: ["problem"]})["veto"] is True
    assert score_layout({flag: []})["veto"] is False


def test_score_layout_prefers_fewer_sheets_and_handles_empty_remnants():
    one = score_layout({"sheetCount": 1, "candidateRemnants": []})
    two = score_layout({"sheetCount": 2, "candidateRemnants": []})
    assert one["score"] > two["score"]
    assert one["bestReusableRectArea"] == 0
    assert score_layout({})["bestReusableRectArea"] == 0


def test_cut_sequence_is_safe_and_independent_of_placement_order():
    result = {
        "sheetCount": 1,
        "sheets": [{"index": 0, "placements": [
            {"partId": "b", "skuId": "sku", "bomLineId": "b", "x": 100, "y": 0, "w": 50, "h": 80},
            {"partId": "a", "skuId": "sku", "bomLineId": "a", "x": 0, "y": 0, "w": 100, "h": 80},
        ]}],
    }
    manifest = cut_sequence_manifest(result)
    assert manifest["liveMachineControl"] is False
    assert manifest["notCamDriver"] is True
    assert all(step["liveMachineControl"] is False and step["notCamDriver"] is True for step in manifest["steps"])
    cuts = [step for step in manifest["steps"] if step["op"] in {"RIP", "CROSS"}]
    assert {step["op"] for step in cuts} == {"RIP", "CROSS"}
    assert len(cuts) == manifest["cutCount"] == 5
    assert cut_sequence_manifest(result)["manifestHash"] == manifest["manifestHash"]
    shuffled = copy.deepcopy(result)
    shuffled["sheets"][0]["placements"].reverse()
    assert cut_sequence_manifest(shuffled) == manifest


def test_parts_from_simple_panels_maps_fields_and_defaults():
    panels = [
        {"partId": "side", "partName": "Side", "length": "200", "width": 80, "quantity": 2,
         "grain": "length", "grainDirection": "width", "skuId": "custom", "productVersion": 3, "materialLotId": "lot"},
        {"partName": "Shelf", "length": 100, "width": "50", "grainDirection": "width"},
        {"length": 20, "width": 10},
    ]
    parts = parts_from_simple_panels(panels, sku_id="cabinet")
    assert parts == [
        {"partId": f"cabinet:side#{i}", "partName": "Side", "length": 200.0, "width": 80.0,
         "grain": "length", "skuId": "custom", "productVersion": 3, "bomLineId": "side", "materialLotId": "lot"}
        for i in (1, 2)
    ] + [
        {"partId": "cabinet:Shelf#1", "partName": "Shelf", "length": 100.0, "width": 50.0,
         "grain": "width", "skuId": "cabinet", "productVersion": 1, "bomLineId": "Shelf", "materialLotId": None},
        {"partId": "cabinet:2#1", "partName": None, "length": 20.0, "width": 10.0,
         "grain": "none", "skuId": "cabinet", "productVersion": 1, "bomLineId": "2", "materialLotId": None},
    ]
    assert parts_from_simple_panels([]) == []


def test_registry_unknown_strategy_raises_key_error():
    with pytest.raises(KeyError, match="missing"):
        NestingStrategyRegistry().get("missing")


@pytest.mark.parametrize("name", ["guillotine_baseline", "best_fit_decreasing"])
def test_builtin_strategies_are_reproducible(name):
    parts = parts_from_simple_panels([
        {"partId": "side", "length": 200, "width": 100, "quantity": 2},
        {"partId": "top", "length": 150, "width": 80},
    ])
    strategy = NestingStrategyRegistry().get(name)
    kwargs = {"sheet": {"length": 500, "width": 300, "grain": "none", "sku": "TEST"}, "trim_mm": 0, "kerf_mm": 0}
    first = strategy.nest(copy.deepcopy(parts), **kwargs)
    second = strategy.nest(copy.deepcopy(parts), **kwargs)
    assert first["strategy"] == name
    assert first["sheetCount"] >= 1
    assert first["nestingHash"] == second["nestingHash"]
    assert first["sheets"] == second["sheets"]
