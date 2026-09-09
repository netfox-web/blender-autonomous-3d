"""Phase 541–600 portfolio integrity gates. MOCK/FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import math

import pytest

from fox3d.platform import Platform
from fox3d.portfolio import (
    ENVELOPE_NUMERIC,
    PortfolioError,
    media_case_real,
    recompute_conservation,
    run_portfolio_scenario,
    validate_envelope,
    validate_top10_lineage,
)


def _valid_nest(**overrides):
    sheet_w, sheet_h, count = 2440.0, 1220.0, 1
    placed, remnant = 100000.0, 50000.0
    scrap = sheet_w * sheet_h * count - placed - remnant
    body = {
        "sheetMm": [sheet_w, sheet_h],
        "sheetCount": count,
        "partUsedArea": placed,
        "reusableRemnantArea": remnant,
        "trueScrapArea": scrap,
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize("field", list(ENVELOPE_NUMERIC))
@pytest.mark.parametrize("value", [0, -1, None, "nope", float("nan"), float("inf")])
def test_envelope_numeric_fail_closed(tmp_path, field, value):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    with pytest.raises(PortfolioError):
        plat.portfolio.create_intent(tenant_id="pa", envelope={field: value})
    assert plat.portfolio.intents == {}


@pytest.mark.parametrize("thickness", [[], [0], [-18], None, "18", [float("nan")], [12], [18, 0]])
def test_envelope_thickness_fail_closed(tmp_path, thickness):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    with pytest.raises(PortfolioError):
        plat.portfolio.create_intent(tenant_id="pa", envelope={"thicknessMm": thickness})
    assert plat.portfolio.intents == {}


def test_envelope_defaults_only_when_unspecified(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    rec = plat.portfolio.create_intent(tenant_id="pa")
    env = rec["envelope"]
    for field in ENVELOPE_NUMERIC:
        assert math.isfinite(float(env[field])) and float(env[field]) > 0
    assert env["thicknessMm"] == [18]
    explicit = plat.portfolio.create_intent(tenant_id="pa", envelope={"maxWidthMm": 900})
    assert explicit["envelope"]["maxWidthMm"] == 900
    assert explicit["envelope"]["maxDepthMm"] == 600


def test_validate_envelope_rejects_bool_and_empty():
    with pytest.raises(PortfolioError):
        validate_envelope({"maxPackedWeightKg": True})
    with pytest.raises(PortfolioError):
        validate_envelope({"thicknessMm": []})


def test_conservation_missing_error_does_not_pass():
    nest = _valid_nest()
    nest.pop("areaConservationError", None)
    nest["partUsedArea"] = None
    result = recompute_conservation(nest, panel_count=4)
    assert result["ok"] is False
    assert result["areaConservationError"] is None


@pytest.mark.parametrize("field", ["partUsedArea", "reusableRemnantArea", "trueScrapArea", "sheetCount", "sheetMm"])
def test_conservation_missing_source_fails(field):
    nest = _valid_nest()
    nest[field] = None if field != "sheetMm" else None
    if field == "sheetMm":
        nest.pop("sheetMm")
    result = recompute_conservation(nest, panel_count=3)
    assert result["ok"] is False


def test_conservation_zero_sheets_with_bom_fails():
    nest = _valid_nest(sheetCount=0, partUsedArea=0, reusableRemnantArea=0, trueScrapArea=0)
    result = recompute_conservation(nest, panel_count=2)
    assert result["ok"] is False


def test_conservation_mismatch_and_valid_known_nest(tmp_path):
    ok = recompute_conservation(_valid_nest(), panel_count=2)
    assert ok["ok"] is True
    assert ok["areaConservationError"] <= ok["toleranceMm2"]
    bad = recompute_conservation(_valid_nest(trueScrapArea=1), panel_count=2)
    assert bad["ok"] is False
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    cid = plat.portfolio.rankings[next(iter(plat.portfolio.rankings))]["top10"][0]["candidateId"]
    rec = plat.portfolio.candidates[cid]
    rec["dfm"]["conservationOk"] = False
    rec["dfm"]["areaConservationError"] = 9999
    rerank = plat.portfolio.rank(result["portfolioId"], tenant_id="pa")
    assert cid not in {r["candidateId"] for r in rerank["top10"]}
    rec["state"] = "APPROVED_FOR_PROTOTYPE"
    with pytest.raises(PortfolioError, match="conservation"):
        plat.portfolio.prototype_pack(cid, tenant_id="pa")


def test_remnant_material_thickness_grain_and_mixed_groups(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    intent = plat.portfolio.create_intent(tenant_id="pa")
    white = plat.portfolio._build_candidate(intent, kind="OPEN_SHELF", width=400, depth=300, height=800, board_thickness=18)
    oak = plat.portfolio._build_candidate(intent, kind="DESK_RISER", width=600, depth=300, height=150, board_thickness=18)
    oak["spec"]["material"] = "WOOD_OAK"
    plat.portfolio.persist()
    wrong_mat = plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 900, "h": 500, "area": 450000, "sheetIndex": 0}]},
        material="WOOD_BLACK",
        thickness=18,
        source_run="wrong-mat",
        tenant_id="pa",
    )[0]
    wrong_thick = plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 900, "h": 500, "area": 450000, "sheetIndex": 1}]},
        material="WOOD_WHITE",
        thickness=25,
        source_run="wrong-thick",
        tenant_id="pa",
    )[0]
    wrong_grain = plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 900, "h": 500, "area": 450000, "sheetIndex": 2}], "grainConstraint": "width"},
        material="WOOD_WHITE",
        thickness=18,
        source_run="wrong-grain",
        tenant_id="pa",
    )[0]
    oak_rem = plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 900, "h": 500, "area": 450000, "sheetIndex": 3}], "grainConstraint": "length"},
        material="WOOD_OAK",
        thickness=18,
        source_run="oak-ok",
        tenant_id="pa",
    )[0]
    white_rem = plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 900, "h": 500, "area": 450000, "sheetIndex": 4}], "grainConstraint": "length"},
        material="WOOD_WHITE",
        thickness=18,
        source_run="white-ok",
        tenant_id="pa",
    )[0]
    plan = plat.portfolio.plan_material(intent["portfolioId"], tenant_id="pa", candidate_ids=[white["candidateId"], oak["candidateId"]])
    eligible = set(plan["remnantFirst"]["candidateRemnantIds"])
    used = plan["remnantFirst"]["usedRemnantIds"]
    assert wrong_mat["remnantId"] not in eligible
    assert wrong_thick["remnantId"] not in eligible
    assert wrong_grain["remnantId"] not in eligible
    assert oak_rem["remnantId"] in eligible
    assert white_rem["remnantId"] in eligible
    for group in plan["remnantFirst"]["groups"]:
        if group["material"] == "WOOD_OAK":
            assert oak["candidateId"] in group["candidateIds"]
            assert white["candidateId"] not in group["candidateIds"]
            assert oak_rem["remnantId"] in group["candidateRemnantIds"]
            assert white_rem["remnantId"] not in group["candidateRemnantIds"]
            assert wrong_mat["remnantId"] not in group["usedRemnantIds"]
        if group["material"] == "WOOD_WHITE":
            assert white["candidateId"] in group["candidateIds"]
            assert oak_rem["remnantId"] not in group["candidateRemnantIds"]
    plat.portfolio.assert_no_double_remnant(used)
    assert plan["consumesInventory"] is False
    assert plan["remnantFirst"]["planningOnly"] is True


def test_duplicate_used_remnant_fail_closed(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    intent = plat.portfolio.create_intent(tenant_id="pa")
    plat.portfolio._build_candidate(intent, kind="OPEN_SHELF", width=400, depth=300, height=800, board_thickness=18)
    orig = plat.kd.nester.nest

    def dup(*args, **kwargs):
        body = orig(*args, **kwargs)
        body = dict(body)
        used = list(body.get("remnantUsed") or [{"remnantId": "r-dup"}])
        rid = used[0].get("remnantId") or "r-dup"
        body["remnantUsed"] = [{"remnantId": rid}, {"remnantId": rid}]
        return body

    plat.kd.nester.nest = dup
    with pytest.raises(PortfolioError, match="double-use"):
        plat.portfolio.plan_material(intent["portfolioId"], tenant_id="pa")


def _media_row(**overrides):
    row = {
        "candidateId": "c1",
        "engineeringHash": "eng",
        "jobId": "job-1",
        "usedMock": False,
        "realBlender": True,
        "blenderVersion": "5.2.1",
        "device": "OPTIX",
        "gpu": "NVIDIA T1000",
        "executedAt": "2026-09-09T00:00:00Z",
        "evidenceCodeCommit": "a" * 40,
        "artifactSha256": "b" * 64,
        "artifactSize": 2048,
        "label": "REAL",
    }
    row.update(overrides)
    return row


def test_media_case_real_negative_rows():
    sha = "a" * 40
    assert media_case_real(_media_row(), expected_commit=sha) is True
    assert media_case_real(_media_row(artifactSha256=""), expected_commit=sha) is False
    assert media_case_real(_media_row(artifactSize=0), expected_commit=sha) is False
    assert media_case_real(_media_row(artifactSize=None), expected_commit=sha) is False
    assert media_case_real(_media_row(usedMock=True), expected_commit=sha) is False
    assert media_case_real(_media_row(realBlender=False), expected_commit=sha) is False
    assert media_case_real(_media_row(evidenceCodeCommit="c" * 40), expected_commit=sha) is False
    assert media_case_real(_media_row(blenderVersion=""), expected_commit=sha) is False
    assert media_case_real(_media_row(device="", gpu=""), expected_commit=sha) is False


def test_top10_lineage_rejects_missing_stale_and_illegal():
    good = {
        "candidateId": "c1",
        "canonicalHash": "can",
        "engineeringHash": "eng",
        "bomHash": "bom",
        "nestingHash": "nest",
        "costSnapshotHash": "cost",
        "costEngineeringHash": "eng",
        "rankingPolicyHash": "pol",
        "state": "SHORTLISTED",
        "conservationOk": True,
    }
    assert validate_top10_lineage([good]) == []
    missing = dict(good)
    missing["bomHash"] = ""
    assert validate_top10_lineage([missing])
    stale = dict(good)
    stale["costEngineeringHash"] = "old"
    assert any("stale-cost" in e for e in validate_top10_lineage([stale]))
    rejected = dict(good)
    rejected["state"] = "REJECTED_DFM"
    assert any("illegal-state" in e for e in validate_top10_lineage([rejected]))
    superceded = dict(good)
    superceded["state"] = "SUPERSEDED"
    assert any("illegal-state" in e for e in validate_top10_lineage([superceded]))
