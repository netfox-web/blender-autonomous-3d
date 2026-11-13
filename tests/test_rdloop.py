"""Offline unit tests for outcome ingestion and R&D decisions."""

import json

import pytest

from fox3d.ids import stable_hash
from fox3d.rdloop import (
    evidence_weighted_rank,
    experiment_lineage,
    import_outcomes,
    inventory_rd_v2,
    substitution_candidates,
)


@pytest.mark.parametrize(
    ("text", "fmt"),
    [
        ('[{"skuId": "sku-1", "margin": "0.3"}]', "json"),
        ('{"items": [{"skuId": "sku-1", "margin": "0.3"}]}', "json"),
        ("skuId,margin\nsku-1,0.3\n", "csv"),
    ],
)
def test_import_formats_and_fixture_label(text, fmt):
    row, = import_outcomes(text, fmt=fmt, source="FIXTURE")
    assert row["skuId"] == "sku-1"
    assert row["margin"] == "0.3"
    assert row["source"] == row["label"] == "FIXTURE"
    assert row["realMarketData"] is False
    assert row["outcomeId"] and row["importedAt"]


@pytest.mark.parametrize("source", ["IMPORTED", "MANUAL"])
def test_import_real_market_sources(source):
    row, = import_outcomes('[{"skuId":"x"}]', source=source)
    assert row["source"] == source
    assert row["realMarketData"] is True


@pytest.mark.parametrize("payload", [{"items": {}}, {"items": None}, {}, "text", 1, None])
def test_import_rejects_non_list_payload(payload):
    with pytest.raises(ValueError, match="list"):
        import_outcomes(json.dumps(payload), source="FIXTURE")


@pytest.mark.parametrize("row", [None, 1, "text", []])
def test_import_rejects_non_object_rows(row):
    with pytest.raises(ValueError, match="row 0.*object"):
        import_outcomes(json.dumps([row]), source="FIXTURE")


def test_import_rejects_invalid_source_and_json():
    with pytest.raises(ValueError, match="Invalid outcome source.*BAD"):
        import_outcomes("[]", source="BAD")
    with pytest.raises(ValueError, match="Invalid outcomes JSON"):
        import_outcomes("{broken", source="FIXTURE")


def test_ranking_uses_only_real_market_and_is_stable():
    candidates = [
        {"productId": "a", "kind": "same", "materialUtilization": 0.6},
        {"productId": "b", "kind": "same", "materialUtilization": 0.6},
        {"productId": "c", "kind": "same", "materialUtilization": 0.6},
    ]
    outcomes = [
        {"skuId": "a", "realMarketData": True, "margin": 1.0},
        {"skuId": "b", "realMarketData": False, "margin": 9.0},
    ]
    result = evidence_weighted_rank(candidates, outcomes)
    assert result["marketUsed"] is True
    assert [r["productId"] for r in result["ranked"]] == ["a", "b", "c"]
    assert result["ranked"][0]["rankScore"] == pytest.approx(0.8)
    assert result["ranked"][1]["rankSource"] == "ENGINEERING_MATERIAL_ONLY"
    assert evidence_weighted_rank(candidates, outcomes[1:])["marketUsed"] is False


def test_inventory_safety_veto_penalizes_score():
    candidates = [{"productId": "safe"}, {"productId": "vetoed"}]
    rows = inventory_rd_v2(candidates, safety={"vetoed": {"veto": True}})
    assert [row["productId"] for row in rows] == ["safe", "vetoed"]
    assert rows[0]["rdScoreV2"] - rows[1]["rdScoreV2"] == pytest.approx(0.3)
    assert [row["safetyVeto"] for row in rows] == [False, True]


def test_substitution_thickness_tolerance_boundary():
    result = substitution_candidates({"thickness": 18}, [
        {"snapshotId": "inside", "thickness": 18.49},
        {"snapshotId": "boundary", "thickness": 18.5},
        {"snapshotId": "outside", "thickness": 17.49},
    ])
    assert [row["compatible"] for row in result["alternatives"]] == [True, False, False]
    assert result["autoSwapForbidden"] is True


def test_experiment_lineage_hash_is_stable_for_same_record(monkeypatch):
    monkeypatch.setattr("fox3d.rdloop.new_id", lambda: "experiment-1")
    kwargs = dict(product_version=1, release_id="release-1", recipe_id="recipe-1", window="week")
    first = experiment_lineage(**kwargs)
    assert first == experiment_lineage(**kwargs)
    assert first["lineageHash"] == stable_hash({k: v for k, v in first.items() if k != "lineageHash"})
    assert first["lineageHash"] != experiment_lineage(**{**kwargs, "window": "month"})["lineageHash"]
