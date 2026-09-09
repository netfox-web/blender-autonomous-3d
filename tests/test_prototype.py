"""Phase 601–660 prototype validation. MOCK/FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import pytest

from fox3d.backup import backup_pilot, evaluate_tenant_restore_matrix, restore_pilot
from fox3d.platform import Platform
from fox3d.portfolio import run_portfolio_scenario
from fox3d.prototype import PrototypeError, run_prototype_scenario


def _ops(plat, tenant="pa"):
    ident = plat.pilot.identity
    fixture = ident.register_operator(tenant_id=tenant, display_name="fixture-pm", capabilities=["FIXTURE"])
    human = ident.register_operator(tenant_id=tenant, display_name="builder", capabilities=["MANUAL"])
    shift = ident.open_shift(tenant_id=tenant, operator_id=fixture["operatorId"], station_id="st")
    human_shift = ident.open_shift(tenant_id=tenant, operator_id=human["operatorId"], station_id="st")
    return fixture, shift, human, human_shift


def test_select_four_fixture_not_physical(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_prototype_scenario(plat, tenant_a="pa", tenant_b="pb")
    assert len(result["selected"]) == 4
    assert result["physicalPrototypeValidated"] is False
    assert all(s["truthLabel"] == "FIXTURE" for s in result["selected"])
    assert result["liveMachineControl"] is False
    assert result["demandLabel"] == "MOCK"


def test_disabled_closed_shift_cross_tenant_cannot_select(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    port = run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    ident = plat.pilot.identity
    op = ident.register_operator(tenant_id="pa", display_name="builder", capabilities=["MANUAL"])
    disabled = ident.register_operator(tenant_id="pa", display_name="off", enabled=False)
    other = ident.register_operator(tenant_id="pb", display_name="b")
    shift = ident.open_shift(tenant_id="pa", operator_id=op["operatorId"], station_id="st")
    closed = ident.open_shift(tenant_id="pa", operator_id=op["operatorId"], station_id="st2")
    ident.close_shift(closed["shiftId"], tenant_id="pa", operator_id=op["operatorId"])
    cid = plat.portfolio.rankings[next(iter(plat.portfolio.rankings))]["top10"][0]["candidateId"]
    with pytest.raises(PermissionError):
        plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=disabled["operatorId"], shift_id=shift["shiftId"], reason="x")
    with pytest.raises(PermissionError):
        plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=op["operatorId"], shift_id=closed["shiftId"], reason="x")
    with pytest.raises(PermissionError):
        plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=other["operatorId"], shift_id=shift["shiftId"], reason="x")
    assert port["top10"] == 10


def test_stale_superseded_rejected_and_fixture_manual(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    ranking = next(iter(plat.portfolio.rankings.values()))
    top = ranking["top10"][1]["candidateId"]
    plat.portfolio.candidates[top]["commercial"]["stale"] = True
    plat.portfolio.candidates[top]["commercial"]["engineeringHash"] = "old"
    with pytest.raises(PrototypeError, match="stale"):
        plat.prototype.select(tenant_id="pa", candidate_id=top, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="x")
    rejected = next(c["candidateId"] for c in plat.portfolio.candidates.values() if c["state"] == "REJECTED_DFM" and c["tenantId"] == "pa")
    with pytest.raises(PrototypeError):
        plat.prototype.select(tenant_id="pa", candidate_id=rejected, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="x")
    ok_id = ranking["top10"][2]["candidateId"]
    plat.portfolio.supersede(ok_id, tenant_id="pa")
    with pytest.raises(PrototypeError):
        plat.prototype.select(tenant_id="pa", candidate_id=ok_id, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="x")
    good = ranking["top10"][3]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=good, operator_id=fixture["operatorId"], shift_id=shift["shiftId"], reason="pilot")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    with pytest.raises(PrototypeError, match="fixture actor"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            source="MANUAL",
            values={"widthMm": 400, "depthMm": 300, "heightMm": 800, "assembledWeightKg": 10, "assemblyMinutes": 30},
        )


def test_restart_preserves_selection_and_idempotent_unit(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, _h, _hs = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=fixture["operatorId"], shift_id=shift["shiftId"], reason="keep")
    again = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=fixture["operatorId"], shift_id=shift["shiftId"], reason="keep")
    assert again["selectionId"] == sel["selectionId"]
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    unit2 = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    assert unit2["prototypeUnitId"] == unit["prototypeUnitId"]
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    assert sel["selectionId"] in plat2.prototype.selections
    assert plat2.prototype.selections[sel["selectionId"]]["engineeringHash"] == sel["engineeringHash"]
    assert plat2.prototype.units[unit["prototypeUnitId"]]["state"] == "WAITING_VALIDATION"


def test_no_double_consume_and_cross_tenant_unit(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, _h, _hs = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=fixture["operatorId"], shift_id=shift["shiftId"], reason="c")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.prototype.consume_material_once(unit["prototypeUnitId"], tenant_id="pa", sheets=2, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    again = plat.prototype.consume_material_once(unit["prototypeUnitId"], tenant_id="pa", sheets=2, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    assert again["consumedSheets"] == 2
    with pytest.raises(PrototypeError, match="double consume"):
        plat.prototype.consume_material_once(unit["prototypeUnitId"], tenant_id="pa", sheets=3, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    with pytest.raises(PermissionError):
        plat.prototype.create_unit(tenant_id="pb", selection_id=sel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"])


def test_as_built_fail_closed_and_fixture_cannot_validate(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="m")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    for bad in (0, -1, None, "x", float("nan"), float("inf")):
        with pytest.raises(PrototypeError):
            plat.prototype.record_as_built(
                unit["prototypeUnitId"],
                tenant_id="pa",
                operator_id=human["operatorId"],
                shift_id=human_shift["shiftId"],
                source="MANUAL",
                values={"widthMm": bad, "depthMm": 300, "heightMm": 800, "assembledWeightKg": 10, "assemblyMinutes": 20},
            )
    missing = plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values={"widthMm": 400},
    )
    assert missing["missingRequired"]
    with pytest.raises(PrototypeError, match="missing required"):
        plat.prototype.decide(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="PASS_AS_BUILT", reason="no")
    with pytest.raises(PrototypeError, match="engineeringHash"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            values={"widthMm": 400, "depthMm": 300, "heightMm": 800, "assembledWeightKg": 10, "assemblyMinutes": 20, "engineeringHash": "other"},
        )
    with pytest.raises(PrototypeError, match="cross-tenant"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="IMPORTED",
            values={"widthMm": 400, "depthMm": 300, "heightMm": 800, "assembledWeightKg": 10, "assemblyMinutes": 20},
            dam_refs=[{"tenantId": "pb", "sha256": "aa", "size": 12}],
        )
    fsel = plat.prototype.select(
        tenant_id="pa",
        candidate_id=next(iter(plat.portfolio.rankings.values()))["top10"][1]["candidateId"],
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        reason="fix",
    )
    funit = plat.prototype.create_unit(tenant_id="pa", selection_id=fsel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.prototype.start_unit(funit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.prototype.complete_build(funit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.prototype.record_as_built(
        funit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        source="FIXTURE",
        values={"widthMm": 400, "depthMm": 300, "heightMm": 800, "assembledWeightKg": 10, "assemblyMinutes": 20},
    )
    plat.prototype.decide(funit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], decision="PASS_AS_BUILT", reason="ci")
    assert plat.prototype.units[funit["prototypeUnitId"]]["physicalPrototypeValidated"] is False


def test_eco_invalidates_and_rejected_does_not_replace(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="e")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values={"widthMm": 400, "depthMm": 300, "heightMm": 800, "assembledWeightKg": 10, "assemblyMinutes": 20},
    )
    rejected = plat.prototype.create_eco(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="no", accept=False)
    assert rejected["status"] == "REJECTED"
    assert plat.portfolio.candidates[cid]["state"] != "SUPERSEDED"
    eco = plat.prototype.create_eco(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="fit")
    assert eco["fromEngineeringHash"] != eco["toEngineeringHash"]
    assert plat.portfolio.candidates[cid]["state"] == "SUPERSEDED"
    with pytest.raises(PrototypeError, match="engineeringHash"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            values={
                "widthMm": 400,
                "depthMm": 300,
                "heightMm": 800,
                "assembledWeightKg": 10,
                "assemblyMinutes": 20,
                "engineeringHash": eco["toEngineeringHash"],
            },
        )
    with pytest.raises(PrototypeError, match="superseded"):
        plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"], seq=2)


def test_actual_cost_partial_and_packaging_blocks(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="c")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    cost = plat.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"laborMinutes": 30, "hardwareConsumed": None},
    )
    assert cost["truthLabel"] == "PARTIAL"
    assert cost["total"] is None
    assert cost["estimateSnapshot"].get("truthLabel") == "CONFIG_ESTIMATE"
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values={"widthMm": 400, "depthMm": 300, "heightMm": 800, "assembledWeightKg": 10, "assemblyMinutes": 20},
    )
    pack = plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed={"cartonLengthMm": 2000, "cartonWidthMm": 400, "cartonHeightMm": 200, "packedWeightKg": 12},
    )
    assert pack["ok"] is False
    ready = plat.prototype.readiness(cid, tenant_id="pa")
    assert ready["state"] == "HOLD"
    with pytest.raises(PrototypeError):
        plat.prototype.packaging_checklist(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            observed={"cartonLengthMm": 800, "cartonWidthMm": 400, "cartonHeightMm": 200},
        )


def test_tenant_backup_preserves_prototype_identities(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_prototype_scenario(plat, tenant_a="pa", tenant_b="pb")
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["pa"])
    restore_pilot(dest, tmp_path / "r", tenant_id="pa")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    matrix = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="pa", tenant_b="pb")
    assert matrix["tenantLeakageAbsent"] is True
    assert matrix["tenantRequiredStatePreserved"] is True
    assert matrix["domains"]["prototypeUnits"]["liveDigest"] == matrix["domains"]["prototypeUnits"]["restoredDigest"]
    assert matrix["domains"]["prototypeUnits"]["restoredB"] == 0
    assert restored.prototype.units
    assert list(restored.prototype.units) == list(plat.prototype.units)


def test_mock_demand_cannot_upgrade_go(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_prototype_scenario(plat, tenant_a="pa", tenant_b="pb")
    cid = result["selected"][0]["candidateId"]
    board = plat.prototype.readiness(cid, tenant_id="pa")
    assert board["demandLabel"] == "MOCK"
    assert board["state"] != "READY_FOR_HUMAN_GO_NO_GO"
    assert board["productionReady"] is False
    with pytest.raises(PrototypeError):
        plat.prototype.approve_pilot_batch(
            cid,
            tenant_id="pa",
            operator_id=result["human"]["operatorId"],
            shift_id=result["humanShift"]["shiftId"],
            reason="go",
        )
