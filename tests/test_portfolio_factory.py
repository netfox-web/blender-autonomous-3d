"""Phase 541–600 SKU portfolio factory. MOCK/FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import json

import pytest

from fox3d.backup import BackupError, backup_pilot, evaluate_tenant_restore_matrix, restore_pilot
from fox3d.platform import Platform
from fox3d.portfolio import PortfolioError, run_portfolio_scenario


def test_generate_24_candidates_six_kinds_and_rejects(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    assert result["candidateCount"] >= 24
    assert result["kindCount"] >= 6
    assert result["rejected"] >= 1
    assert result["top10"] == 10
    assert result["invalidInTop10"] == 0
    assert result["demandLabel"] == "MOCK"
    assert result["liveMachineControl"] is False
    assert result["tenantIsolation"] is True
    assert result["conservationOk"] is True
    assert result["prototypeReady"] is True
    ranking = plat.portfolio.rank(result["portfolioId"], tenant_id="pa")
    again = plat.portfolio.rank(result["portfolioId"], tenant_id="pa")
    assert [r["candidateId"] for r in ranking["top10"]] == [r["candidateId"] for r in again["top10"]]


def test_duplicate_canonical_hash_fail_closed(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    intent = plat.portfolio.create_intent(tenant_id="pa", seed="dup")
    first = plat.portfolio._build_candidate(intent, kind="OPEN_SHELF", width=400, depth=300, height=800, board_thickness=18)
    with pytest.raises(PortfolioError, match="duplicate"):
        plat.portfolio._build_candidate(intent, kind="OPEN_SHELF", width=400, depth=300, height=800, board_thickness=18)
    assert first["canonicalHash"]


def test_invalid_cannot_enter_top10(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    ranking = next(iter(plat.portfolio.rankings.values()))
    for row in ranking["top10"]:
        rec = plat.portfolio.candidates[row["candidateId"]]
        rec["state"] = "REJECTED_DFM"
        rec["dfm"]["engineeringOk"] = False
    rerank = plat.portfolio.rank(result["portfolioId"], tenant_id="pa")
    assert all(r["valid"] for r in rerank["top10"])
    assert not any(plat.portfolio.candidates[r["candidateId"]]["state"] == "REJECTED_DFM" for r in rerank["top10"])


def test_stale_cost_snapshot(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    cid = plat.portfolio.rankings[next(iter(plat.portfolio.rankings))]["top10"][0]["candidateId"]
    rec = plat.portfolio.candidates[cid]
    rec["engineeringHash"] = "mutated-hash"
    assert plat.portfolio.detect_stale_cost(cid, tenant_id="pa") is True
    rec["state"] = "APPROVED_FOR_PROTOTYPE"
    with pytest.raises(PortfolioError, match="stale"):
        plat.portfolio.prototype_pack(cid, tenant_id="pa")


def test_remnant_double_use_and_incompatible_thickness(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 800, "h": 400, "area": 320000, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="pf",
        tenant_id="pa",
    )
    plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 800, "h": 400, "area": 320000, "sheetIndex": 1}]},
        material="WOOD_WHITE",
        thickness=25,
        source_run="pf-thick",
        tenant_id="pa",
    )
    result = run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    plan = plat.portfolio.plans[next(iter(plat.portfolio.plans))]
    ids = plan["remnantFirst"]["usedRemnantIds"]
    plat.portfolio.assert_no_double_remnant(ids)
    with pytest.raises(PortfolioError, match="double-use"):
        plat.portfolio.assert_no_double_remnant(ids + ids)
    thick = [r for r in plat.remnants.available(tenant_id="pa") if float(r.get("thickness") or 0) == 25]
    assert thick
    assert thick[0]["remnantId"] not in ids
    assert result["plan"]["consumesInventory"] is False


def test_mock_demand_cannot_be_real_and_cross_tenant(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    with pytest.raises(PortfolioError):
        plat.portfolio.create_intent(tenant_id="pa", demand_source="REAL")
    result = run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    with pytest.raises(PortfolioError, match="MOCK demand"):
        plat.portfolio.rank(result["portfolioId"], tenant_id="pa", demand_real=True)
    with pytest.raises(PermissionError):
        plat.portfolio.list_candidates(result["portfolioId"], tenant_id="pb")


def test_approval_required_and_superseded_pack(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    cid = next(c["candidateId"] for c in plat.portfolio.candidates.values() if c["state"] == "CANDIDATE")
    with pytest.raises(PortfolioError, match="shortlisted"):
        plat.portfolio.submit_approval(cid, tenant_id="pa", actor="pm")
    top_id = plat.portfolio.rankings[next(iter(plat.portfolio.rankings))]["top10"][1]["candidateId"]
    plat.portfolio.supersede(top_id, tenant_id="pa")
    with pytest.raises(PortfolioError, match="superseded"):
        plat.portfolio.prototype_pack(top_id, tenant_id="pa")


def test_portfolio_tenant_backup_semantic_digest(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["pa"])
    restore_pilot(dest, tmp_path / "r", tenant_id="pa")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    matrix = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="pa", tenant_b="pb")
    assert matrix["tenantLeakageAbsent"] is True
    assert matrix["tenantRequiredStatePreserved"] is True
    assert matrix["domains"]["portfolioCandidates"]["restoredB"] == 0
    assert matrix["domains"]["portfolioCandidates"]["liveDigest"] == matrix["domains"]["portfolioCandidates"]["restoredDigest"]
    omitted = tmp_path / "bak-omit"
    backup_pilot(plat.root, omitted, tenant_ids=["pa"])
    payload = json.loads((omitted / "manifest.json").read_text(encoding="utf-8"))
    data = json.loads((omitted / "data" / "portfolio" / "portfolio.json").read_text(encoding="utf-8"))
    data["candidates"] = [c for c in data["candidates"] if c.get("tenantId") == "pa"][:-1]
    (omitted / "data" / "portfolio" / "portfolio.json").write_text(json.dumps(data), encoding="utf-8")
    # mutate dest files without updating digest — restore then compare
    restore_pilot.__wrapped__ if False else None
    bad_root = tmp_path / "r-omit"
    # Direct copy of mutated backup would fail checksum. Mutate restored instead:
    restored.portfolio.candidates.pop(next(iter(restored.portfolio.candidates)))
    bad = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="pa", tenant_b="pb")
    assert bad["tenantRequiredStatePreserved"] is False
    assert "portfolioCandidates" in bad["identityMismatch"]
    assert payload.get("scope") == "TENANT_SCOPED"


def test_malformed_portfolio_collection_fail_closed(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    path = plat.root / "portfolio" / "portfolio.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candidates"] = {c["candidateId"]: c for c in payload["candidates"]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    dest = tmp_path / "bak"
    with pytest.raises(BackupError, match="malformed"):
        backup_pilot(plat.root, dest, tenant_ids=["pa"])
    assert not (dest / "manifest.json").exists()
