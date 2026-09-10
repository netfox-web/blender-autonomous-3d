"""Phase 601–660 prototype validation. MOCK/FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import pytest

from fox3d.backup import backup_pilot, evaluate_tenant_restore_matrix, restore_pilot
from fox3d.ids import new_id
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


def _predicted(cand):
    spec = cand["spec"]
    pack = ((cand.get("sku") or {}).get("packing") or {})
    weight = ((cand.get("sku") or {}).get("weight") or {})
    dfm = cand.get("dfm") or {}
    return {
        "widthMm": spec["width"],
        "depthMm": spec["depth"],
        "heightMm": spec["height"],
        "assembledWeightKg": weight.get("grossKg") or weight.get("netKg"),
        "assemblyMinutes": dfm.get("assemblyMinutes"),
        "cartonLengthMm": pack.get("length"),
        "cartonWidthMm": pack.get("width"),
        "cartonHeightMm": pack.get("height"),
        "packedWeightKg": weight.get("grossKg") or weight.get("netKg"),
    }


def _pack_obs(plat, cand, **over):
    pred = _predicted(cand)
    counts = plat.prototype._bom_counts(cand)
    body = {
        "cartonLengthMm": pred["cartonLengthMm"],
        "cartonWidthMm": pred["cartonWidthMm"],
        "cartonHeightMm": pred["cartonHeightMm"],
        "packedWeightKg": pred["packedWeightKg"],
        "hardwareQty": counts["hardwareQty"],
        "partCount": counts["partCount"],
        "packingFit": "OK",
        "missingParts": "NO",
        "damageDefect": "OK",
        "assemblyMinutes": pred["assemblyMinutes"],
    }
    body.update(over)
    return body


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


def _dam_ref(plat, tenant, name, role):
    obj = plat.dam.put(tenant_id=tenant, kind="photo", name=name, data=b"photo-" + name.encode() + b"-bytesxx")
    return {"assetId": obj.asset_id, "role": role}


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
    assert mixed["completeness"] == "PARTIAL"
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
    with pytest.raises(PrototypeError, match="DAM"):
        plat.prototype.decide(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="PASS_AS_BUILT", reason="ok")
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand),
        observations=GOOD_QC,
        dam_refs=[_dam_ref(plat, "pa", "asbuilt.bin", "AS_BUILT")],
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
    plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat, cand),
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
    money = plat.prototype.costs[plat.prototype.units[unit["prototypeUnitId"]]["actualCostId"]]
    assert money["completeness"] == "PARTIAL"
    with pytest.raises(PrototypeError, match="PARTIAL|DAM"):
        plat.prototype.approve_pilot_batch(cid, tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="money-only")
    plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat, cand, packagingQty=1),
        dam_refs=[_dam_ref(plat, "pa", "pack.bin", "PACKAGING")],
    )
    qty = int(plat.prototype._material_requirement(unit)["sheets"])
    _seed_lot(plat, "pa", unit, sheets=qty + 2)
    plat.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    plat.prototype.record_labor(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        minutes=40,
        reason="build",
    )
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


def test_packaging_enforces_predicted_tolerance(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="tol")
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
    pred = _predicted(cand)
    for field in ("cartonLengthMm", "cartonWidthMm", "cartonHeightMm"):
        bad = plat.prototype.packaging_checklist(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            observed=_pack_obs(plat, cand, **{field: pred[field] + 80}),
        )
        assert bad["ok"] is False
        assert "out of tolerance" in bad["reason"]
        assert plat.prototype.units[unit["prototypeUnitId"]]["state"] == "HOLD"
    weight_bad = plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat, cand, packedWeightKg=min(float(pred["packedWeightKg"]) + 3, 29)),
    )
    assert weight_bad["ok"] is False
    assert "packedWeightKg out of tolerance" in weight_bad["reason"]
    assembly_bad = plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat, cand, assemblyMinutes=float(pred["assemblyMinutes"]) + 40),
    )
    assert assembly_bad["ok"] is False
    assert "assemblyMinutes out of tolerance" in assembly_bad["reason"]
    good = plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat, cand),
    )
    assert good["ok"] is True
    assert good["packagingPolicyHash"]
    for field in ("cartonLengthMm", "cartonWidthMm", "cartonHeightMm", "packedWeightKg"):
        assert good["variance"][field]["ok"] is True


def test_inventory_consume_crash_after_first_lot_reconciles(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="crash")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = max(int(req["sheets"]), 2)
    lot_a = _seed_lot(plat, "pa", unit, sheets=1)
    lot_b = _seed_lot(plat, "pa", unit, sheets=qty + 2)
    before_a = plat.lots.quantities(lot_a["lotId"], tenant_id="pa")
    before_b = plat.lots.quantities(lot_b["lotId"], tenant_id="pa")
    plat.prototype._crash_mode = "after-first-consume"
    with pytest.raises(CrashInjected):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    plat.prototype._crash_mode = ""
    mid_a = plat.lots.quantities(lot_a["lotId"], tenant_id="pa")
    assert mid_a["consumed"] == before_a["consumed"] + 1
    assert plat.prototype.units[unit["prototypeUnitId"]].get("materialConsumed") is not True
    intent = next(iter(plat.prototype.intents.values()))
    reservation_ids = [r["reservationId"] for r in intent["reservations"]]
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _f2, _s2, human2, hs2 = _ops(plat2)
    recovered = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human2["operatorId"],
        shift_id=hs2["shiftId"],
        consumes_inventory=True,
    )
    assert recovered["inventoryLineage"]["consumedQuantity"] == qty
    assert recovered["inventoryLineage"]["reservationIds"] == reservation_ids
    after_a = plat2.lots.quantities(lot_a["lotId"], tenant_id="pa")
    after_b = plat2.lots.quantities(lot_b["lotId"], tenant_id="pa")
    assert (after_a["consumed"] - before_a["consumed"]) + (after_b["consumed"] - before_b["consumed"]) == qty
    again = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human2["operatorId"],
        shift_id=hs2["shiftId"],
        consumes_inventory=True,
    )
    assert again["inventoryLineage"]["reservationIds"] == reservation_ids
    assert plat2.pilot.journal.verify("pa")["ok"] is True


def test_inventory_consume_subprocess_crash_after_first_lot(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="subcrash")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = max(int(req["sheets"]), 2)
    _seed_lot(plat, "pa", unit, sheets=1)
    _seed_lot(plat, "pa", unit, sheets=qty + 2)
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = os.environ.copy()
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "fox3d.crashfix",
            "--root",
            str(tmp_path / "live"),
            "--action",
            "proto-consume",
            "--tenant",
            "pa",
            "--unit",
            unit["prototypeUnitId"],
            "--operator",
            human["operatorId"],
            "--shift",
            human_shift["shiftId"],
            "--qty",
            str(qty),
            "--crash",
            "after-first-consume",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    intent = next(iter(plat2.prototype.intents.values()))
    ids = [r["reservationId"] for r in intent["reservations"]]
    recovered = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    assert recovered["inventoryLineage"]["consumedQuantity"] == qty
    assert recovered["inventoryLineage"]["reservationIds"] == ids
    assert plat2.pilot.journal.verify("pa")["ok"] is True


def _assert_lot_conserved(plat, tenant, lot_id):
    q = plat.lots.quantities(lot_id, tenant_id=tenant)
    assert q["available"] + q["reserved"] + q["consumed"] == q["sheetCount"]
    return q


def test_inventory_consume_crash_after_reserve_single_lot(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="rsv")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = int(req["sheets"])
    lot = _seed_lot(plat, "pa", unit, sheets=qty + 3)
    before = plat.lots.quantities(lot["lotId"], tenant_id="pa")
    plat.prototype._crash_mode = "after-reserve"
    with pytest.raises(CrashInjected):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    plat.prototype._crash_mode = ""
    mid = _assert_lot_conserved(plat, "pa", lot["lotId"])
    assert mid["reserved"] - before["reserved"] == qty
    assert mid["consumed"] == before["consumed"]
    intent = next(iter(plat.prototype.intents.values()))
    assert intent["status"] == "PREPARED"
    pinned = plat.prototype._reservations_for_work_order(tenant_id="pa", work_order_id=f"proto:{unit['prototypeUnitId']}")
    ids = [r["reservationId"] for r in pinned]
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _f2, _s2, human2, hs2 = _ops(plat2)
    recovered = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human2["operatorId"],
        shift_id=hs2["shiftId"],
        consumes_inventory=True,
    )
    assert recovered["inventoryLineage"]["consumedQuantity"] == qty
    assert recovered["inventoryLineage"]["reservationIds"] == ids
    after = _assert_lot_conserved(plat2, "pa", lot["lotId"])
    assert after["consumed"] - before["consumed"] == qty
    assert after["reserved"] == before["reserved"]
    again = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human2["operatorId"],
        shift_id=hs2["shiftId"],
        consumes_inventory=True,
    )
    assert again["inventoryLineage"]["reservationIds"] == ids
    assert plat2.pilot.journal.verify("pa")["ok"] is True


def test_inventory_consume_crash_after_reserve_single_lot_subprocess(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="rsv1s")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = int(req["sheets"])
    lot = _seed_lot(plat, "pa", unit, sheets=qty + 2)
    before = plat.lots.quantities(lot["lotId"], tenant_id="pa")
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = os.environ.copy()
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "fox3d.crashfix",
            "--root",
            str(tmp_path / "live"),
            "--action",
            "proto-consume",
            "--tenant",
            "pa",
            "--unit",
            unit["prototypeUnitId"],
            "--operator",
            human["operatorId"],
            "--shift",
            human_shift["shiftId"],
            "--qty",
            str(qty),
            "--crash",
            "after-reserve",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    pinned = plat2.prototype._reservations_for_work_order(tenant_id="pa", work_order_id=f"proto:{unit['prototypeUnitId']}")
    ids = [r["reservationId"] for r in pinned]
    mid = _assert_lot_conserved(plat2, "pa", lot["lotId"])
    assert mid["reserved"] - before["reserved"] == qty
    recovered = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    assert recovered["inventoryLineage"]["reservationIds"] == ids
    assert recovered["inventoryLineage"]["consumedQuantity"] == qty
    after = _assert_lot_conserved(plat2, "pa", lot["lotId"])
    assert after["consumed"] - before["consumed"] == qty
    assert plat2.pilot.journal.verify("pa")["ok"] is True


def test_inventory_consume_crash_after_reserve_multi_lot_subprocess(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="rsv2")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = max(int(req["sheets"]), 2)
    lot_a = _seed_lot(plat, "pa", unit, sheets=1)
    lot_b = _seed_lot(plat, "pa", unit, sheets=qty + 2)
    before_a = plat.lots.quantities(lot_a["lotId"], tenant_id="pa")
    before_b = plat.lots.quantities(lot_b["lotId"], tenant_id="pa")
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = os.environ.copy()
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "fox3d.crashfix",
            "--root",
            str(tmp_path / "live"),
            "--action",
            "proto-consume",
            "--tenant",
            "pa",
            "--unit",
            unit["prototypeUnitId"],
            "--operator",
            human["operatorId"],
            "--shift",
            human_shift["shiftId"],
            "--qty",
            str(qty),
            "--crash",
            "after-reserve",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    wo = f"proto:{unit['prototypeUnitId']}"
    pinned = plat2.prototype._reservations_for_work_order(tenant_id="pa", work_order_id=wo)
    ids = [r["reservationId"] for r in pinned]
    assert sum(int(r["quantity"]) for r in pinned) == qty
    mid_a = _assert_lot_conserved(plat2, "pa", lot_a["lotId"])
    mid_b = _assert_lot_conserved(plat2, "pa", lot_b["lotId"])
    assert (mid_a["reserved"] - before_a["reserved"]) + (mid_b["reserved"] - before_b["reserved"]) == qty
    recovered = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    assert recovered["inventoryLineage"]["consumedQuantity"] == qty
    assert recovered["inventoryLineage"]["reservationIds"] == ids
    after_a = _assert_lot_conserved(plat2, "pa", lot_a["lotId"])
    after_b = _assert_lot_conserved(plat2, "pa", lot_b["lotId"])
    assert (after_a["consumed"] - before_a["consumed"]) + (after_b["consumed"] - before_b["consumed"]) == qty
    again = plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    assert again["inventoryLineage"]["reservationIds"] == ids
    assert plat2.pilot.journal.verify("pa")["ok"] is True


def test_inventory_intent_qty_mismatch_fails_before_allocation(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="qty")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = int(req["sheets"])
    lot = _seed_lot(plat, "pa", unit, sheets=qty + 4)
    before = plat.lots.quantities(lot["lotId"], tenant_id="pa")
    plat.prototype._crash_mode = "after-reserve"
    with pytest.raises(CrashInjected):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    plat.prototype._crash_mode = ""
    reserved = plat.lots.quantities(lot["lotId"], tenant_id="pa")
    with pytest.raises(PrototypeError):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty + 1,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    after = plat.lots.quantities(lot["lotId"], tenant_id="pa")
    assert after == reserved
    assert after["reserved"] - before["reserved"] == qty


def test_inventory_intent_requirement_mismatch_fails_closed(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="mat")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = int(req["sheets"])
    lot = _seed_lot(plat, "pa", unit, sheets=qty + 2)
    plat.prototype._crash_mode = "after-reserve"
    with pytest.raises(CrashInjected):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    plat.prototype._crash_mode = ""
    intent = next(iter(plat.prototype.intents.values()))
    intent["requirement"] = {**intent["requirement"], "material": "OTHER_SKU"}
    plat.prototype.intents[intent["intentId"]] = intent
    plat.prototype.persist()
    before = plat.lots.quantities(lot["lotId"], tenant_id="pa")
    with pytest.raises(PrototypeError):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    assert plat.lots.quantities(lot["lotId"], tenant_id="pa") == before


def test_inventory_intent_pointer_other_unit_fails_closed(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    ranking = next(iter(plat.portfolio.rankings.values()))
    cid_a = ranking["top10"][0]["candidateId"]
    cid_b = ranking["top10"][1]["candidateId"]
    sel_a = plat.prototype.select(tenant_id="pa", candidate_id=cid_a, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="a")
    sel_b = plat.prototype.select(tenant_id="pa", candidate_id=cid_b, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="b")
    unit_a = plat.prototype.create_unit(tenant_id="pa", selection_id=sel_a["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    unit_b = plat.prototype.create_unit(tenant_id="pa", selection_id=sel_b["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit_a)
    qty = int(req["sheets"])
    _seed_lot(plat, "pa", unit_a, sheets=qty + 2)
    _seed_lot(plat, "pa", unit_b, sheets=qty + 2)
    plat.prototype._crash_mode = "after-reserve"
    with pytest.raises(CrashInjected):
        plat.prototype.consume_material_once(
            unit_a["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    plat.prototype._crash_mode = ""
    intent_id = plat.prototype.units[unit_a["prototypeUnitId"]]["inventoryIntentId"]
    plat.prototype.units[unit_b["prototypeUnitId"]]["inventoryIntentId"] = intent_id
    plat.prototype.persist()
    with pytest.raises(PrototypeError):
        plat.prototype.consume_material_once(
            unit_b["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )


def test_inventory_intent_duplicate_identity_ambiguous(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="dup")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = int(req["sheets"])
    _seed_lot(plat, "pa", unit, sheets=qty + 2)
    plat.prototype._crash_mode = "after-reserve"
    with pytest.raises(CrashInjected):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    plat.prototype._crash_mode = ""
    original = next(iter(plat.prototype.intents.values()))
    clone = dict(original)
    clone["intentId"] = "dup-intent"
    plat.prototype.intents[clone["intentId"]] = clone
    plat.prototype.units[unit["prototypeUnitId"]].pop("inventoryIntentId", None)
    plat.prototype.persist()
    with pytest.raises(PrototypeError):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )


def test_inventory_intent_malformed_missing_identity_fails(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    _f, _s, human, human_shift = _ops(plat)
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][0]["candidateId"]
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="mal")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=human["operatorId"], shift_id=human_shift["shiftId"])
    req = plat.prototype._material_requirement(unit)
    qty = int(req["sheets"])
    _seed_lot(plat, "pa", unit, sheets=qty + 2)
    plat.prototype._crash_mode = "after-reserve"
    with pytest.raises(CrashInjected):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )
    plat.prototype._crash_mode = ""
    intent = next(iter(plat.prototype.intents.values()))
    intent.pop("tenantId", None)
    plat.prototype.intents[intent["intentId"]] = intent
    plat.prototype.persist()
    with pytest.raises(PrototypeError):
        plat.prototype.consume_material_once(
            unit["prototypeUnitId"],
            tenant_id="pa",
            sheets=qty,
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            consumes_inventory=True,
        )


def _built_unit(plat, *, fixture, shift, human, human_shift, seq=1, source="MANUAL"):
    cid = next(iter(plat.portfolio.rankings.values()))["top10"][seq - 1]["candidateId"]
    actor = human if source != "FIXTURE" else fixture
    sh = human_shift if source != "FIXTURE" else shift
    sel = plat.prototype.select(tenant_id="pa", candidate_id=cid, operator_id=actor["operatorId"], shift_id=sh["shiftId"], reason=f"p661-{seq}")
    unit = plat.prototype.create_unit(tenant_id="pa", selection_id=sel["selectionId"], operator_id=actor["operatorId"], shift_id=sh["shiftId"])
    plat.prototype.start_unit(unit["prototypeUnitId"], tenant_id="pa", operator_id=actor["operatorId"], shift_id=sh["shiftId"])
    plat.prototype.complete_build(unit["prototypeUnitId"], tenant_id="pa", operator_id=actor["operatorId"], shift_id=sh["shiftId"])
    return plat.portfolio.candidates[cid], plat.prototype.units[unit["prototypeUnitId"]], actor, sh


def test_fixture_cannot_create_manual_evidence_package(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift, source="FIXTURE")
    with pytest.raises(PrototypeError, match="MANUAL_EVIDENCE"):
        plat.prototype.create_evidence_package(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            source="MANUAL_EVIDENCE",
        )
    _ = cand


def test_cross_tenant_and_missing_dam_rejected(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    foreign = plat.dam.put(tenant_id="pb", kind="photo", name="x.bin", data=b"foreign-bytes")
    with pytest.raises(PrototypeError, match="cross-tenant"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            values=_vals(cand),
            observations=GOOD_QC,
            dam_refs=[{"assetId": foreign.asset_id, "sha256": foreign.sha256}],
        )
    local = plat.dam.put(tenant_id="pa", kind="photo", name="ok.bin", data=b"local-photo-bytes")
    with pytest.raises(PrototypeError, match="DAM hash"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            values=_vals(cand),
            observations=GOOD_QC,
            dam_refs=[{"assetId": local.asset_id, "sha256": "deadbeef"}],
        )
    with pytest.raises(PrototypeError, match="DAM object missing"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            values=_vals(cand),
            observations=GOOD_QC,
            dam_refs=[{"assetId": "missing-asset"}],
        )


def test_ista_claim_without_certified_report_rejected(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand),
        observations=GOOD_QC,
    )
    with pytest.raises(PrototypeError, match="ISTA"):
        plat.prototype.packaging_checklist(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            observed=_pack_obs(plat, cand, certificationClaim="ISTA-6A"),
        )


def test_stale_package_after_eco_and_human_go_gates(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand),
        observations=GOOD_QC,
        dam_refs=[_dam_ref(plat, "pa", "stale-asbuilt.bin", "AS_BUILT")],
    )
    plat.prototype.decide(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="PASS_AS_BUILT", reason="ok")
    plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat, cand),
        dam_refs=[_dam_ref(plat, "pa", "stale-pack.bin", "PACKAGING")],
    )
    plat.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    pkg_id = plat.prototype.units[unit["prototypeUnitId"]]["evidencePackageId"]
    change = _eco_change(cand)
    plat.prototype.create_eco(cand["candidateId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="resize", changes=change)
    assert plat.prototype.packages[pkg_id]["state"] == "INVALIDATED"
    with pytest.raises(PrototypeError, match="stale|ECO|lineage|incomplete"):
        plat.prototype.record_launch_decision(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            decision="HUMAN_GO",
            reason="stale",
        )


def test_human_go_rejects_fixture_partial_demand_and_duplicate(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_prototype_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift = result["fixture"], result["fixtureShift"]
    human, human_shift = result["human"], result["humanShift"]
    cid = result["selected"][0]["candidateId"]
    with pytest.raises(PrototypeError, match="fixture"):
        plat.prototype.record_launch_decision(
            cid,
            tenant_id="pa",
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            decision="HUMAN_GO",
            reason="no",
        )
    with pytest.raises(PrototypeError, match="MOCK demand"):
        plat.prototype.record_launch_decision(
            cid,
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            decision="HUMAN_GO",
            reason="no",
            demand_upgrade=True,
        )
    with pytest.raises(PrototypeError):
        plat.prototype.create_pilot_plan(
            cid,
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            reason="no-go",
        )
    plat2 = Platform(root=tmp_path / "live2", mock_blender=True)
    run_portfolio_scenario(plat2, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat2)
    cand, unit, actor, sh = _built_unit(plat2, fixture=fixture, shift=shift, human=human, human_shift=human_shift, seq=1)
    plat2.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand),
        observations=GOOD_QC,
        dam_refs=[_dam_ref(plat2, "pa", "go-asbuilt.bin", "AS_BUILT")],
    )
    plat2.prototype.decide(unit["prototypeUnitId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="PASS_AS_BUILT", reason="ok")
    with pytest.raises(PrototypeError, match="packaging|partial|cost|launch-ready|DAM"):
        plat2.prototype.record_launch_decision(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            decision="HUMAN_GO",
            reason="partial",
        )
    plat2.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat2, cand),
        dam_refs=[_dam_ref(plat2, "pa", "go-pack.bin", "PACKAGING")],
    )
    plat2.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    with pytest.raises(PrototypeError, match="PARTIAL|launch-ready"):
        plat2.prototype.record_launch_decision(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            decision="HUMAN_GO",
            reason="money-only",
        )
    qty = int(plat2.prototype._material_requirement(unit)["sheets"])
    _seed_lot(plat2, "pa", unit, sheets=qty + 2)
    plat2.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    plat2.prototype.record_labor(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        minutes=35,
        reason="assembly",
    )
    plat2.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    money = plat2.prototype.costs[plat2.prototype.units[unit["prototypeUnitId"]]["actualCostId"]]
    assert money["completeness"] == "PARTIAL"
    assert (money.get("quantityLineage") or {}).get("sources", {}).get("packagingQty") == "MISSING"
    with pytest.raises(PrototypeError, match="PARTIAL|launch-ready"):
        plat2.prototype.record_launch_decision(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            decision="HUMAN_GO",
            reason="no-packaging-qty",
        )
    plat2.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat2, cand, packagingQty=1),
        dam_refs=[_dam_ref(plat2, "pa", "go-pack-qty.bin", "PACKAGING")],
    )
    plat2.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    complete = plat2.prototype.costs[plat2.prototype.units[unit["prototypeUnitId"]]["actualCostId"]]
    assert complete["completeness"] == "COMPLETE"
    assert complete["quantityLineage"]["packagingQty"] == 1
    go = plat2.prototype.record_launch_decision(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        decision="HUMAN_GO",
        reason="go",
    )
    again = plat2.prototype.record_launch_decision(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        decision="HUMAN_GO",
        reason="go-again",
    )
    assert again["launchDecisionId"] == go["launchDecisionId"]
    plan = plat2.prototype.create_pilot_plan(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        reason="pilot",
        quantity=2,
    )
    assert plan["liveMachineControl"] is False
    assert plan["quantity"] == 2
    assert plan["releaseId"]
    assert plan["workOrderId"]
    dest = tmp_path / "bak"
    backup_pilot(plat2.root, dest, tenant_ids=["pa"])
    restore_pilot(dest, tmp_path / "r", tenant_id="pa")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    matrix = evaluate_tenant_restore_matrix(live=plat2, restored=restored, tenant_a="pa", tenant_b="pb")
    assert matrix["tenantLeakageAbsent"] is True
    assert matrix["tenantRequiredStatePreserved"] is True
    assert restored.prototype.packages[go["evidencePackageId"]]["state"] == "FINALIZED"
    assert restored.prototype.launch_decisions[go["launchDecisionId"]]["decision"] == "HUMAN_GO"
    restored_unit = restored.prototype.units[unit["prototypeUnitId"]]
    restored_pack = restored.prototype.checklists[restored_unit["packagingChecklistId"]]
    assert restored_pack.get("packagingQty") == 1
    assert (restored_pack.get("observed") or {}).get("packagingQty") == 1
    restored_cost = restored.prototype.costs[restored_unit["actualCostId"]]
    assert restored_cost["quantityLineage"]["packagingQty"] == 1
    assert restored_cost["quantityLineage"]["sources"]["packagingQty"] == "PACKAGING_CHECKLIST"


def test_package_crash_prepare_reconciles(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    plat.prototype._crash_mode = "after-outbox-prepare"
    with pytest.raises(CrashInjected):
        plat.prototype.create_evidence_package(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
        )
    plat.prototype._crash_mode = ""
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    assert plat2.prototype.packages == {}
    assert plat2.pilot.outbox.list_open(tenant_id="pa") == []
    again = plat2.prototype.create_evidence_package(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        source="MANUAL",
    )
    events = [e for e in plat2.pilot.journal.list("pa") if e.get("eventType") == "prototype.evidence_package.create"]
    assert len(plat2.prototype.packages) == 1
    assert len(events) == 1
    assert plat2.pilot.outbox.list_open(tenant_id="pa") == []
    assert plat2.pilot.journal.verify("pa")["ok"] is True
    third = plat2.prototype.create_evidence_package(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        source="MANUAL",
    )
    assert third["evidencePackageId"] == again["evidencePackageId"]
    assert len([e for e in plat2.pilot.journal.list("pa") if e.get("eventType") == "prototype.evidence_package.create"]) == 1
    _ = cand


def test_package_crash_after_business_persist_reconciles_journal(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    plat.prototype._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat.prototype.create_evidence_package(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
        )
    plat.prototype._crash_mode = ""
    assert len(plat.prototype.packages) == 1
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    events = [e for e in plat2.pilot.journal.list("pa") if e.get("eventType") == "prototype.evidence_package.create"]
    assert len(plat2.prototype.packages) == 1
    assert len(events) == 1
    assert plat2.pilot.outbox.list_open(tenant_id="pa") == []
    assert plat2.pilot.journal.verify("pa")["ok"] is True
    _ = cand


def test_package_create_subprocess_crash_windows(tmp_path):
    import os
    import subprocess
    import sys

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    env = dict(os.environ)
    root = str(tmp_path / "live")
    src = str((__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "fox3d.crashfix",
            "--root",
            root,
            "--action",
            "proto-package-create",
            "--tenant",
            "pa",
            "--unit",
            unit["prototypeUnitId"],
            "--operator",
            human["operatorId"],
            "--shift",
            human_shift["shiftId"],
            "--crash",
            "after-business-persist",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    events = [e for e in plat2.pilot.journal.list("pa") if e.get("eventType") == "prototype.evidence_package.create"]
    assert len(plat2.prototype.packages) == 1
    assert len(events) == 1
    assert plat2.pilot.outbox.list_open(tenant_id="pa") == []
    assert plat2.pilot.journal.verify("pa")["ok"] is True
    _ = cand


def test_zero_byte_required_dam_rejected(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    empty = plat.dam.put(tenant_id="pa", kind="photo", name="empty.bin", data=b"")
    with pytest.raises(PrototypeError, match="non-empty"):
        plat.prototype.record_as_built(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            values=_vals(cand),
            observations=GOOD_QC,
            dam_refs=[{"assetId": empty.asset_id, "role": "AS_BUILT"}],
        )


def _crash_proc(tmp_path, action, crash, *, unit="", operator="", shift="", wo="", qty=12, payload="", reason=""):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = dict(os.environ)
    root = str(tmp_path / "live")
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable,
        "-m",
        "fox3d.crashfix",
        "--root",
        root,
        "--action",
        action,
        "--tenant",
        "pa",
        "--crash",
        crash,
        "--unit",
        unit,
        "--operator",
        operator,
        "--shift",
        shift,
        "--wo",
        wo,
        "--qty",
        str(qty),
    ]
    if payload:
        cmd.extend(["--payload", payload if isinstance(payload, str) else json.dumps(payload)])
    if reason:
        cmd.extend(["--reason", reason])
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    return proc


def _manual_launch_ready(plat, cand, unit, human, human_shift, *, pack_qty=1, labor_minutes=35):
    plat.prototype.record_as_built(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        values=_vals(cand),
        observations=GOOD_QC,
        dam_refs=[_dam_ref(plat, "pa", "ready-asbuilt.bin", "AS_BUILT")],
    )
    plat.prototype.decide(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        decision="PASS_AS_BUILT",
        reason="ok",
    )
    pack_kwargs = _pack_obs(plat, cand)
    if pack_qty is not None:
        pack_kwargs["packagingQty"] = pack_qty
    plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=pack_kwargs,
        dam_refs=[_dam_ref(plat, "pa", "ready-pack.bin", "PACKAGING")],
    )
    qty = int(plat.prototype._material_requirement(unit)["sheets"])
    _seed_lot(plat, "pa", unit, sheets=qty + 2)
    plat.prototype.consume_material_once(
        unit["prototypeUnitId"],
        tenant_id="pa",
        sheets=qty,
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        consumes_inventory=True,
    )
    plat.prototype.record_labor(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        minutes=labor_minutes,
        reason="assembly",
    )
    plat.prototype.record_actual_cost(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    live = plat.prototype.units[unit["prototypeUnitId"]]
    pkg_id = live.get("evidencePackageId")
    if pkg_id and plat.prototype.packages.get(pkg_id, {}).get("state") in {"OPEN", "PREPARED"}:
        plat.prototype.finalize_evidence_package(
            pkg_id,
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
        )
        live = plat.prototype.units[unit["prototypeUnitId"]]
    return live


def _assert_journal_one(plat, tenant, event_type, n=1):
    events = [e for e in plat.pilot.journal.list(tenant) if e.get("eventType") == event_type]
    assert len(events) == n
    assert plat.pilot.outbox.list_open(tenant_id=tenant) == []
    assert plat.pilot.journal.verify(tenant)["ok"] is True
    return events


def test_explicit_packaging_qty_required_and_lineage(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    unit = _manual_launch_ready(plat, cand, unit, human, human_shift, pack_qty=None)
    cost = plat.prototype.costs[unit["actualCostId"]]
    assert cost["completeness"] == "PARTIAL"
    assert cost["quantityLineage"]["sources"]["packagingQty"] == "MISSING"
    with pytest.raises(PrototypeError, match="PARTIAL|launch-ready"):
        plat.prototype.record_launch_decision(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            decision="HUMAN_GO",
            reason="missing-qty",
        )
    with pytest.raises(PrototypeError, match="invalid packagingQty|non-numeric packagingQty"):
        plat.prototype.packaging_checklist(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            observed=_pack_obs(plat, cand, packagingQty="nope"),
            dam_refs=[_dam_ref(plat, "pa", "bad-qty.bin", "PACKAGING")],
        )
    with pytest.raises(PrototypeError, match="invalid packagingQty"):
        plat.prototype.packaging_checklist(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            source="MANUAL",
            observed=_pack_obs(plat, cand, packagingQty=-2),
            dam_refs=[_dam_ref(plat, "pa", "neg-qty.bin", "PACKAGING")],
        )
    plat.prototype.packaging_checklist(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        observed=_pack_obs(plat, cand, packagingQty=1),
        dam_refs=[_dam_ref(plat, "pa", "ok-qty.bin", "PACKAGING")],
    )
    live = plat.prototype.units[unit["prototypeUnitId"]]
    pack = plat.prototype.checklists[live["packagingChecklistId"]]
    pack["prototypeUnitId"] = "other-unit"
    plat.prototype.checklists[pack["checklistId"]] = pack
    plat.prototype.persist()
    wrong = plat.prototype.record_actual_cost(
        live["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    assert wrong["completeness"] == "PARTIAL"
    pack["prototypeUnitId"] = live["prototypeUnitId"]
    pack["engineeringHash"] = "stale-hash"
    plat.prototype.checklists[pack["checklistId"]] = pack
    plat.prototype.persist()
    stale = plat.prototype.record_actual_cost(
        live["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    assert stale["completeness"] == "PARTIAL"
    pack["engineeringHash"] = live["engineeringHash"]
    plat.prototype.checklists[pack["checklistId"]] = pack
    plat.prototype.persist()
    ok = plat.prototype.record_actual_cost(
        live["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    assert ok["completeness"] == "COMPLETE"
    assert ok["quantityLineage"]["packagingQty"] == 1
    go = plat.prototype.record_launch_decision(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        decision="HUMAN_GO",
        reason="qty-ok",
    )
    assert go["decision"] == "HUMAN_GO"


def test_labor_crash_after_outbox_complete_does_not_duplicate(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    plat.prototype._crash_mode = "after-outbox-complete"
    with pytest.raises(CrashInjected):
        plat.prototype.record_labor(
            unit["prototypeUnitId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            minutes=21,
            reason="crash-labor",
        )
    plat.prototype._crash_mode = ""
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    rows = [r for r in plat2.prototype.labor.values() if r.get("prototypeUnitId") == unit["prototypeUnitId"]]
    assert len(rows) == 1
    assert rows[0]["minutes"] == 21
    _assert_journal_one(plat2, "pa", "prototype.labor.append")
    again = plat2.prototype.record_labor(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        minutes=21,
        reason="crash-labor",
    )
    assert again["laborId"] == rows[0]["laborId"]
    rows2 = [r for r in plat2.prototype.labor.values() if r.get("prototypeUnitId") == unit["prototypeUnitId"]]
    assert len(rows2) == 1
    _assert_journal_one(plat2, "pa", "prototype.labor.append")
    _ = cand


def test_labor_subprocess_crash_before_idem_index(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    _crash_proc(
        tmp_path,
        "proto-labor",
        "after-labor-emit-before-idem",
        unit=unit["prototypeUnitId"],
        operator=human["operatorId"],
        shift=human_shift["shiftId"],
        qty=18,
        reason="crash-labor",
    )
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    rows = [r for r in plat2.prototype.labor.values() if r.get("reason") == "crash-labor"]
    assert len(rows) == 1
    assert rows[0]["minutes"] == 18
    _assert_journal_one(plat2, "pa", "prototype.labor.append")
    again = plat2.prototype.record_labor(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        minutes=18,
        reason="crash-labor",
    )
    assert again["laborId"] == rows[0]["laborId"]
    assert len([r for r in plat2.prototype.labor.values() if r.get("reason") == "crash-labor"]) == 1
    _ = cand


def test_finalize_and_attach_crash_windows(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    pkg = plat.prototype.create_evidence_package(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
    )
    plat.prototype._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat.prototype.finalize_evidence_package(
            pkg["evidencePackageId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
        )
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    assert plat2.prototype.packages[pkg["evidencePackageId"]]["state"] == "FINALIZED"
    _assert_journal_one(plat2, "pa", "prototype.evidence_package.finalize")
    again = plat2.prototype.finalize_evidence_package(
        pkg["evidencePackageId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
    )
    assert again["evidencePackageId"] == pkg["evidencePackageId"]
    _assert_journal_one(plat2, "pa", "prototype.evidence_package.finalize")
    _ = cand


def test_finalize_subprocess_crash_window(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    pkg = plat.prototype.create_evidence_package(
        unit["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
    )
    _crash_proc(
        tmp_path,
        "proto-package-finalize",
        "after-business-persist",
        wo=pkg["evidencePackageId"],
        operator=human["operatorId"],
        shift=human_shift["shiftId"],
    )
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    assert plat2.prototype.packages[pkg["evidencePackageId"]]["state"] == "FINALIZED"
    _assert_journal_one(plat2, "pa", "prototype.evidence_package.finalize")
    again = plat2.prototype.finalize_evidence_package(
        pkg["evidencePackageId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
    )
    assert again["evidencePackageId"] == pkg["evidencePackageId"]
    _assert_journal_one(plat2, "pa", "prototype.evidence_package.finalize")
    _ = cand


def test_human_go_and_pilot_plan_crash_windows(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    _manual_launch_ready(plat, cand, unit, human, human_shift)
    plat.prototype._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat.prototype.record_launch_decision(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            decision="HUMAN_GO",
            reason="crash-go",
        )
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    gos = [d for d in plat2.prototype.launch_decisions.values() if d.get("decision") == "HUMAN_GO"]
    assert len(gos) == 1
    _assert_journal_one(plat2, "pa", "prototype.launch_decision")
    again = plat2.prototype.record_launch_decision(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        decision="HUMAN_GO",
        reason="crash-go-retry",
    )
    assert again["launchDecisionId"] == gos[0]["launchDecisionId"]
    plat2.prototype._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat2.prototype.create_pilot_plan(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human2["operatorId"],
            shift_id=human_shift2["shiftId"],
            reason="crash-plan",
            quantity=1,
        )
    plat3 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human3, human_shift3 = _ops(plat3)
    plans = list(plat3.prototype.plans.values())
    assert len(plans) == 1
    _assert_journal_one(plat3, "pa", "prototype.pilot_plan.create")
    retry_plan = plat3.prototype.create_pilot_plan(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human3["operatorId"],
        shift_id=human_shift3["shiftId"],
        reason="crash-plan",
        quantity=1,
    )
    assert retry_plan["planId"] == plans[0]["planId"]
    assert retry_plan["releaseId"] == plans[0]["releaseId"]
    assert retry_plan["workOrderId"] == plans[0]["workOrderId"]
    assert len(plat3.prototype.plans) == 1


def test_human_go_pilot_plan_subprocess_crash_windows(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    _manual_launch_ready(plat, cand, unit, human, human_shift)
    _crash_proc(
        tmp_path,
        "proto-launch-go",
        "after-business-persist",
        wo=cand["candidateId"],
        operator=human["operatorId"],
        shift=human_shift["shiftId"],
    )
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    gos = [d for d in plat2.prototype.launch_decisions.values() if d.get("decision") == "HUMAN_GO"]
    assert len(gos) == 1
    _assert_journal_one(plat2, "pa", "prototype.launch_decision")
    retry_go = plat2.prototype.record_launch_decision(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        decision="HUMAN_GO",
        reason="retry-go",
    )
    assert retry_go["launchDecisionId"] == gos[0]["launchDecisionId"]
    _crash_proc(
        tmp_path,
        "proto-pilot-plan",
        "after-business-persist",
        wo=cand["candidateId"],
        operator=human2["operatorId"],
        shift=human_shift2["shiftId"],
    )
    plat3 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human3, human_shift3 = _ops(plat3)
    plans = list(plat3.prototype.plans.values())
    assert len(plans) == 1
    releases = [r for r in plat3.pilot.releases.releases.values() if r.get("tenantId") == "pa"]
    wos = [w for w in plat3.pilot.workorders.orders.values() if w.get("tenantId") == "pa"]
    assert len(plans) == 1
    retry_plan = plat3.prototype.create_pilot_plan(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human3["operatorId"],
        shift_id=human_shift3["shiftId"],
        reason="retry-plan",
        quantity=1,
    )
    assert retry_plan["planId"] == plans[0]["planId"]
    assert retry_plan["releaseId"] == plans[0]["releaseId"]
    assert retry_plan["workOrderId"] == plans[0]["workOrderId"]
    assert len(plat3.prototype.plans) == 1
    assert len([r for r in plat3.pilot.releases.releases.values() if r.get("tenantId") == "pa"]) == len(releases)
    assert len([w for w in plat3.pilot.workorders.orders.values() if w.get("tenantId") == "pa"]) == len(wos)
    _assert_journal_one(plat3, "pa", "prototype.pilot_plan.create")
    _ = sh
    _ = actor
    _ = fixture


def test_accepted_eco_crash_window(tmp_path):
    from fox3d.storelock import CrashInjected

    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    change = _eco_change(cand)
    plat.prototype._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat.prototype.create_eco(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            reason="crash-eco",
            changes=change,
        )
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    ecos = [e for e in plat2.prototype.ecos.values() if e.get("status") == "ACCEPTED"]
    assert len(ecos) == 1
    _assert_journal_one(plat2, "pa", "prototype.eco.accept")
    retry = plat2.prototype.create_eco(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        reason="crash-eco",
        changes=change,
    )
    assert retry["ecoId"] == ecos[0]["ecoId"]
    assert len([e for e in plat2.prototype.ecos.values() if e.get("status") == "ACCEPTED"]) == 1
    _ = unit


def test_accepted_eco_subprocess_crash_window(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    change = _eco_change(cand)
    _crash_proc(
        tmp_path,
        "proto-eco",
        "after-business-persist",
        wo=cand["candidateId"],
        operator=human["operatorId"],
        shift=human_shift["shiftId"],
        payload=change,
        reason="crash-eco",
    )
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    _, _, human2, human_shift2 = _ops(plat2)
    ecos = [e for e in plat2.prototype.ecos.values() if e.get("status") == "ACCEPTED"]
    assert len(ecos) == 1
    _assert_journal_one(plat2, "pa", "prototype.eco.accept")
    retry = plat2.prototype.create_eco(
        cand["candidateId"],
        tenant_id="pa",
        operator_id=human2["operatorId"],
        shift_id=human_shift2["shiftId"],
        reason="crash-eco",
        changes=change,
    )
    assert retry["ecoId"] == ecos[0]["ecoId"]
    assert len([e for e in plat2.prototype.ecos.values() if e.get("status") == "ACCEPTED"]) == 1
    _ = unit
    _ = actor
    _ = sh
    _ = fixture


def _inject_duplicate_labor(plat, unit):
    live = plat.prototype.units[unit["prototypeUnitId"]]
    original = next(r for r in plat.prototype.labor.values() if r.get("prototypeUnitId") == live["prototypeUnitId"])
    dup = dict(original)
    dup["laborId"] = new_id()
    plat.prototype.labor[dup["laborId"]] = dup
    plat.prototype.persist()
    return original, dup


def test_duplicate_semantic_labor_blocks_complete_and_human_go(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio_scenario(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    _manual_launch_ready(plat, cand, unit, human, human_shift)
    live = plat.prototype.units[unit["prototypeUnitId"]]
    before = plat.prototype.costs[live["actualCostId"]]
    assert before["completeness"] == "COMPLETE"
    original, dup = _inject_duplicate_labor(plat, live)
    integrity = plat.prototype._labor_integrity(live)
    assert integrity["integrityOk"] is False
    assert integrity["duplicateKeys"]
    assert integrity["minutes"] is None
    cost = plat.prototype.record_actual_cost(
        live["prototypeUnitId"],
        tenant_id="pa",
        operator_id=human["operatorId"],
        shift_id=human_shift["shiftId"],
        source="MANUAL",
        components={"materialAmount": 100, "hardwareAmount": 20, "laborAmount": 40, "packagingAmount": 10},
        currency="TWD",
    )
    assert cost["completeness"] == "PARTIAL"
    assert cost["quantityLineage"]["laborLineage"]["integrityOk"] is False
    assert cost["quantities"].get("laborMinutes") in {None, original["minutes"], dup["minutes"]}
    assert cost["quantityLineage"]["laborMinutes"] is None
    with pytest.raises(PrototypeError, match="PARTIAL|launch-ready|duplicate|labor"):
        plat.prototype.record_launch_decision(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            decision="HUMAN_GO",
            reason="dup-labor",
        )
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    live2 = plat2.prototype.units[unit["prototypeUnitId"]]
    integrity2 = plat2.prototype._labor_integrity(live2)
    assert integrity2["integrityOk"] is False
    dest = tmp_path / "bak"
    backup_pilot(plat2.root, dest, tenant_ids=["pa"])
    restore_pilot(dest, tmp_path / "r", tenant_id="pa")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    matrix = evaluate_tenant_restore_matrix(live=plat2, restored=restored, tenant_a="pa", tenant_b="pb")
    assert matrix["tenantLeakageAbsent"] is True
    live_r = restored.prototype.units[unit["prototypeUnitId"]]
    integrity_r = restored.prototype._labor_integrity(live_r)
    assert integrity_r["integrityOk"] is False
    assert len([r for r in restored.prototype.labor.values() if r.get("prototypeUnitId") == unit["prototypeUnitId"]]) == 2
    _ = actor
    _ = sh
    _ = fixture
    _ = shift
