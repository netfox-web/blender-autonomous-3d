"""Phase 601–660 prototype validation. MOCK/FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import pytest

from fox3d.backup import backup_pilot, evaluate_tenant_restore_matrix, restore_pilot
from fox3d.kd import FlatPackProductTypeRegistry
from fox3d.platform import Platform
from fox3d.portfolio import run_portfolio_scenario
from fox3d.prototype import PrototypeError, run_prototype_scenario, volumetric_weight_kg

GOOD_QC = {
    "hardware": {"status": "OK"},
    "panelEdgeFinish": {"status": "OK"},
    "wobbleStability": {"status": "OK"},
    "doorDrawerFit": {"status": "OK"},
    "reworkCount": 0,
    "defectCount": 0,
}


def _vals(cand, **over):
    spec = cand["spec"]
    weight = ((cand.get("sku") or {}).get("weight") or {})
    dfm = cand.get("dfm") or {}
    body = {
        "widthMm": spec["width"],
        "depthMm": spec["depth"],
        "heightMm": spec["height"],
        "assembledWeightKg": weight.get("grossKg") or weight.get("netKg") or 10,
        "assemblyMinutes": dfm.get("assemblyMinutes") or 30,
    }
    body.update(over)
    return body


def _eco_change(cand):
    grid = FlatPackProductTypeRegistry().grid(cand["kind"])
    spec = cand["spec"]
    for field in ("width", "height", "depth"):
        for val in grid[field]:
            if abs(float(val) - float(spec[field])) > 1:
                return {field: val}
    return {"boardThickness": 16 if float(spec.get("boardThickness") or 18) != 16 else 18}


def _seed_lot(plat, tenant, unit, sheets=8, **over):
    req = plat.prototype._material_requirement(unit)
    req.update(over)
    return plat.lots.create(
        tenant_id=tenant,
        material=req["material"],
        thickness=req["thickness"],
        length=req["length"],
        width=req["width"],
        grain=req.get("grain") or "length",
        sheet_count=sheets,
    )


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
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
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
    fixture_obs = plat.prototype.consume_material_once(
        unit["prototypeUnitId"], tenant_id="pa", sheets=2, operator_id=fixture["operatorId"], shift_id=shift["shiftId"]
    )
    assert fixture_obs["consumesInventory"] is False
    assert fixture_obs["materialConsumed"] is False
    assert fixture_obs["materialObservationLabel"] == "FIXTURE"
    with pytest.raises(PrototypeError, match="double consume"):
        plat.prototype.consume_material_once(unit["prototypeUnitId"], tenant_id="pa", sheets=3, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    with pytest.raises(PermissionError):
        plat.prototype.create_unit(tenant_id="pb", selection_id=sel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"])


def test_inventory_consume_conservation_retry_shortage(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="inv")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    lot = _seed_lot(plat, "pa", unit, sheets=6)
    before = plat.lots.quantities(lot["lotId"], tenant_id="pa")
    consumed = plat.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=req["sheets"],
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    after = plat.lots.quantities(lot["lotId"], tenant_id="pa")
    assert consumed["consumesInventory"] is True
    assert consumed["inventoryLineage"]["lotIds"] == [lot["lotId"]]
    assert after["consumed"] - before["consumed"] == req["sheets"]
    assert after["available"] + after["reserved"] + after["consumed"] == after["sheetCount"]
    retry = plat.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=req["sheets"],
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    assert retry["inventoryLineage"]["reservationIds"] == consumed["inventoryLineage"]["reservationIds"]
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    assert plat2.prototype.units[unit["prototypeUnitId"]]["inventoryLineage"]["consumedQuantity"] == req["sheets"]
    assert plat2.lots.quantities(lot["lotId"], tenant_id="pa")["consumed"] == after["consumed"]
    _f2, _s2, human2, human_shift2 = _ops(plat2)
    again = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=req["sheets"],
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        consumes_inventory=True,
    )
    assert again["inventoryLineage"]["reservationIds"] == consumed["inventoryLineage"]["reservationIds"]
    assert plat2.lots.quantities(lot["lotId"], tenant_id="pa")["consumed"] == after["consumed"]
    mismatch_unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"], seq=8)
    wrong = plat.lots.create(tenant_id="pa", material="MDF_18_BLACK", thickness=18, grain="none", sheet_count=10)
    before_wrong = plat.lots.quantities(wrong["lotId"], tenant_id="pa")
    with pytest.raises(PrototypeError, match="SKU/thickness/grain"):
        plat.prototype.consume_material_once(
            mismatch_unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=1,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
            lot_id=wrong["lotId"],
        )
    assert plat.lots.quantities(wrong["lotId"], tenant_id="pa")["available"] == before_wrong["available"]
    assert plat.lots.quantities(wrong["lotId"], tenant_id="pa")["consumed"] == before_wrong["consumed"]
    other = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"], seq=9)
    tiny = _seed_lot(plat, "pa", other, sheets=1)
    before_tiny = {k: plat.lots.quantities(tiny["lotId"], tenant_id="pa")[k] for k in ("available", "reserved", "consumed", "sheetCount")}
    with pytest.raises(PrototypeError, match="SHORTAGE|insufficient"):
        plat.prototype.consume_material_once(
            other["prototypeUnitId"],
            tenant_id="pa",
            sheets=8,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
            lot_id=tiny["lotId"],
        )
    assert plat.lots.quantities(tiny["lotId"], tenant_id="pa")["available"] == before_tiny["available"]
    assert plat.lots.quantities(tiny["lotId"], tenant_id="pa")["reserved"] == before_tiny["reserved"]
    assert plat.lots.quantities(tiny["lotId"], tenant_id="pa")["consumed"] == before_tiny["consumed"]


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
    change = _eco_change(plat.portfolio.candidates[cid])
    eco = plat.prototype.create_eco(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="fit", changes=change)
    assert eco["fromEngineeringHash"] != eco["toEngineeringHash"]
    assert eco["fieldChanges"]
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
    assert cost["monetaryTotal"] is None
    assert cost["completeness"] == "PARTIAL"
    assert "laborMinutes" in cost["quantities"]
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


def test_planned_unit_cannot_validate(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="p")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    cand = plat.portfolio.candidates[cid]
    with pytest.raises(PrototypeError, match="completed build"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            values=_vals(cand),
            observations=GOOD_QC,
        )
    with pytest.raises(PrototypeError, match="cannot validate|completed build"):
        plat.prototype.decide(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="PASS_AS_BUILT", reason="no")


def test_tolerance_qc_dam_and_imported_label(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="t")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    cand = plat.portfolio.candidates[cid]
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand, widthMm=cand["spec"]["width"] + 80, assembledWeightKg=80, assemblyMinutes=200),
        observations=GOOD_QC,
    )
    with pytest.raises(PrototypeError, match="out-of-tolerance"):
        plat.prototype.decide(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="PASS_AS_BUILT", reason="bad")
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand),
    )
    with pytest.raises(PrototypeError, match="defect/QC"):
        plat.prototype.decide(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="PASS_AS_BUILT", reason="noqc")
    foreign = plat.dam.put(tenant_id="pb", kind="photo", name="b.bin", data=b"foreign-bytes")
    with pytest.raises(PrototypeError, match="cross-tenant"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            values=_vals(cand),
            observations=GOOD_QC,
            dam_refs=[{"assetId": foreign.asset_id, "tenantId": "pa", "sha256": foreign.sha256, "size": 13}],
        )
    imported = plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="IMPORTED",
        values=_vals(cand),
        observations=GOOD_QC,
    )
    assert imported["truthLabel"] == "IMPORTED_EVIDENCE"


def test_cost_separates_quantity_and_currency(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="cost")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    minutes_only = plat.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"laborMinutes": 40},
    )
    assert minutes_only["completeness"] == "PARTIAL"
    assert minutes_only["monetaryTotal"] is None
    omit = plat.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"hardwareAmount": 12, "laborAmount": 40, "packagingAmount": 8, "laborMinutes": 40},
    )
    assert omit["completeness"] == "PARTIAL"
    mixed = plat.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={
            "laborMinutes": 40,
            "sheetsConsumed": 2,
            "materialAmount": 100,
            "hardwareAmount": 12,
            "laborAmount": 40,
            "packagingAmount": 8,
        },
        currency="TWD",
    )
    assert mixed["monetaryTotal"] == 160
    assert mixed["completeness"] == "COMPLETE"
    snap = mixed["estimateSnapshot"]
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    assert plat2.prototype.costs[mixed["costId"]]["estimateSnapshot"] == snap
    with pytest.raises(PrototypeError, match="currency"):
        plat.prototype.record_actual_cost(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            components={"materialAmount": 1, "hardwareAmount": 1, "laborAmount": 1, "packagingAmount": 1},
            currency="XXX",
        )
    with pytest.raises(PrototypeError):
        plat.prototype.record_actual_cost(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            components={"materialAmount": -1, "hardwareAmount": 1, "laborAmount": 1, "packagingAmount": 1},
        )


def test_packaging_missing_dims_mismatch_and_volumetric(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="pack")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    cand = plat.portfolio.candidates[cid]
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand),
        observations=GOOD_QC,
    )
    counts = plat.prototype._bom_counts(cand)
    for missing_field in ("cartonLengthMm", "cartonWidthMm", "cartonHeightMm", "packedWeightKg"):
        observed = {"cartonLengthMm": 800, "cartonWidthMm": 400, "cartonHeightMm": 200, "packedWeightKg": 12}
        del observed[missing_field]
        with pytest.raises(PrototypeError, match="missing"):
            plat.prototype.packaging_checklist(
                unit["prototypeUnitId"],
                tenant_id="pa",
                operator_id=human["operatorId"],
                shift_id=human_shift["shiftId"],
                source="MANUAL",
                observed=observed,
            )
    mismatch = plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed={
            "cartonLengthMm": 800,
            "cartonWidthMm": 400,
            "cartonHeightMm": 200,
            "packedWeightKg": 12,
            "hardwareQty": counts["hardwareQty"] + 3,
            "partCount": counts["partCount"],
            "packingFit": "OK",
            "missingParts": "NO",
            "damageDefect": "OK",
        },
    )
    assert mismatch["ok"] is False
    damage = plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed={
            "cartonLengthMm": 800,
            "cartonWidthMm": 400,
            "cartonHeightMm": 200,
            "packedWeightKg": 12,
            "hardwareQty": counts["hardwareQty"],
            "partCount": counts["partCount"],
            "packingFit": "OK",
            "missingParts": "NO",
            "damageDefect": "DAMAGED",
        },
    )
    assert damage["ok"] is False
    with pytest.raises(PrototypeError, match="engineering"):
        plat.prototype.packaging_checklist(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            observed={
                "cartonLengthMm": 800,
                "cartonWidthMm": 400,
                "cartonHeightMm": 200,
                "packedWeightKg": 12,
                "engineeringHash": "other",
            },
        )
    vol = volumetric_weight_kg(800, 400, 200)
    ok = plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="IMPORTED",
        observed={
            "cartonLengthMm": 800,
            "cartonWidthMm": 400,
            "cartonHeightMm": 200,
            "packedWeightKg": 12,
            "hardwareQty": counts["hardwareQty"],
            "partCount": counts["partCount"],
            "packingFit": "OK",
            "missingParts": "NO",
            "damageDefect": "OK",
        },
    )
    assert ok["truthLabel"] == "IMPORTED_EVIDENCE"
    assert abs(ok["volumetricWeightKg"] - vol["volumetricWeightKg"]) < 1e-9
    assert ok["volumetric"]["policyHash"] == vol["policyHash"]


def test_eco_payload_noop_invalid_and_restart(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="eco2")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    cand = plat.portfolio.candidates[cid]
    with pytest.raises(PrototypeError, match="no-op"):
        plat.prototype.create_eco(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="same")
    with pytest.raises(PrototypeError, match="no-op"):
        plat.prototype.create_eco(
            cid,
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            reason="same-w",
            changes={"width": cand["spec"]["width"]},
        )
    with pytest.raises(PrototypeError, match="invalid rule/geometry"):
        plat.prototype.create_eco(
            cid,
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            reason="bad-t",
            changes={"boardThickness": 7},
        )
    assert plat.portfolio.candidates[cid]["state"] != "SUPERSEDED"
    change = _eco_change(cand)
    eco = plat.prototype.create_eco(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="resize", changes=change)
    assert eco["fromBomHash"] != eco["toBomHash"] or eco["fromNestingHash"] != eco["toNestingHash"]
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    stored = plat2.prototype.ecos[eco["ecoId"]]
    assert stored["fieldChanges"]
    assert stored["fromEngineeringHash"] == eco["fromEngineeringHash"]
    with pytest.raises(PrototypeError, match="superseded"):
        plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"], seq=2)
    _ = unit


def test_pilot_requires_packaging_cost_and_go_path(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="go")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    cand = plat.portfolio.candidates[cid]
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand),
        observations=GOOD_QC,
    )
    plat.prototype.decide(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="PASS_AS_BUILT", reason="ok")
    with pytest.raises(PrototypeError, match="packaging"):
        plat.prototype.approve_pilot_batch(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="no-pack")
    plat.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"laborMinutes": 20},
    )
    counts = plat.prototype._bom_counts(cand)
    pack = ((cand.get("sku") or {}).get("packing") or {})
    plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed={
            "cartonLengthMm": pack.get("length") or 800,
            "cartonWidthMm": pack.get("width") or 400,
            "cartonHeightMm": pack.get("height") or 200,
            "packedWeightKg": 12,
            "hardwareQty": counts["hardwareQty"],
            "partCount": counts["partCount"],
            "packingFit": "OK",
            "missingParts": "NO",
            "damageDefect": "OK",
        },
    )
    with pytest.raises(PrototypeError, match="PARTIAL"):
        plat.prototype.approve_pilot_batch(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="partial-cost")
    plat.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    with pytest.raises(PrototypeError, match="fixture"):
        plat.prototype.approve_pilot_batch(cid, tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], reason="fix")
    board = plat.prototype.readiness(cid, tenant_id="pa")
    assert all(k in board for k in ("rankingScore", "conservationOk", "packagingValidation", "qcStatus", "realBlenderLineage"))
    assert board["state"] == "READY_FOR_HUMAN_GO_NO_GO"
    assert board["productionReady"] is False
    assert board["liveMachineControl"] is False
    approved = plat.prototype.approve_pilot_batch(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="pilot")
    assert approved["productionReady"] is False
    assert approved["demandDidNotUpgrade"] is True
