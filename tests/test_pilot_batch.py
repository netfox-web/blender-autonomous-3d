"""Phase 721–780 pilot batch execution. MOCK/unit + FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from fox3d.backup import backup_pilot, evaluate_tenant_restore_matrix, restore_pilot
from fox3d.inventory import StockShortage
from fox3d.pilot_batch import PilotBatchError, run_pilot_batch_scenario
from fox3d.platform import Platform
from fox3d.prototype import run_prototype_scenario
from fox3d.workorder import STRICT_STOCK


def _proto_helpers():
    path = Path(__file__).resolve().parent / "test_prototype.py"
    spec = importlib.util.spec_from_file_location("fox3d_test_prototype_helpers", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_H = _proto_helpers()
_ops = _H._ops
_built_unit = _H._built_unit
_manual_launch_ready = _H._manual_launch_ready
_eco_change = _H._eco_change


def _proto(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_prototype_scenario(plat, tenant_a="pa", tenant_b="pb")
    return plat, result


def test_fixture_batch_create_and_execute(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    batch = plat.pilot_batch.create(
        sel["candidateId"],
        tenant_id="pa",
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        quantity=5,
        source="FIXTURE",
        reason="ci-batch",
    )
    assert batch["truthLabel"] == "FIXTURE"
    assert batch["launchDecisionId"] is None
    assert batch["liveMachineControl"] is False
    plat.pilot_batch.release_for_manual(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.pilot_batch.reserve_materials(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    units = plat.pilot_batch.units_for(batch["batchId"], tenant_id="pa")
    assert len(units) == 5
    assert len({u["unitExecutionId"] for u in units}) == 5
    for unit in units:
        plat.pilot_batch.start_unit(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
        plat.pilot_batch.consume_unit(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
        plat.pilot_batch.record_labor(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], minutes=10, reason="assembly")
        plat.pilot_batch.record_qc(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], ok=True)
    plat.pilot_batch.pack_units(
        batch["batchId"],
        tenant_id="pa",
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        unit_execution_ids=[u["unitExecutionId"] for u in units],
        measured={"cartonLengthMm": 400, "cartonWidthMm": 300, "cartonHeightMm": 200, "packedWeightKg": 8},
    )
    cost = plat.pilot_batch.record_cost(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], amounts={"materialAmount": 1, "hardwareAmount": 1, "laborAmount": 1, "packagingAmount": 1})
    assert cost["completeness"] == "PARTIAL"
    ready = plat.pilot_batch.readiness(batch["batchId"], tenant_id="pa")
    assert ready["decision"] == "WAITING_HUMAN_EVIDENCE"
    with pytest.raises(PilotBatchError, match="HUMAN_BATCH_GO|fixture"):
        plat.pilot_batch.record_decision(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], decision="HUMAN_BATCH_GO", reason="no")


def test_manual_batch_without_human_go_fails(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    ident = plat.pilot.identity
    human = ident.register_operator(tenant_id="pa", display_name="builder", capabilities=["MANUAL"])
    human_shift = ident.open_shift(tenant_id="pa", operator_id=human["operatorId"], station_id="st-proto")
    with pytest.raises(PilotBatchError, match="HUMAN_GO"):
        plat.pilot_batch.create(
            proto["selected"][0]["candidateId"],
            tenant_id="pa",
            operator_id=human["operatorId"],
            shift_id=human_shift["shiftId"],
            quantity=2,
            source="MANUAL",
            reason="no-go",
        )
    _ = fixture
    _ = shift


def test_fixture_cannot_inherit_human_go(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio = __import__("fox3d.portfolio", fromlist=["run_portfolio_scenario"]).run_portfolio_scenario
    run_portfolio(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    _manual_launch_ready(plat, cand, unit, human, human_shift)
    plat.prototype.record_launch_decision(cand["candidateId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="HUMAN_GO", reason="go")
    with pytest.raises(PilotBatchError, match="inherit HUMAN_GO|FIXTURE"):
        plat.pilot_batch.create(
            cand["candidateId"],
            tenant_id="pa",
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            quantity=2,
            source="FIXTURE",
            reason="inherit",
        )
    _ = actor
    _ = sh


def test_duplicate_batch_and_unit_identity(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    first = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=5, source="FIXTURE", reason="dup")
    again = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=5, source="FIXTURE", reason="dup")
    assert again["batchId"] == first["batchId"]
    assert len(plat.pilot_batch.units_for(first["batchId"], tenant_id="pa")) == 5


def test_material_shortage_rolls_back(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    batch = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=2, source="FIXTURE", reason="short")
    plat.pilot_batch.release_for_manual(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    with pytest.raises(StockShortage):
        plat.pilot_batch.reserve_materials(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], policy=STRICT_STOCK)
    live = plat.pilot_batch.get(batch["batchId"], tenant_id="pa")
    assert live.get("materialReserved") is not True
    wo = plat.pilot.workorders.get(live["workOrderId"])
    assert wo.get("materialReserved") is not True
    assert not wo.get("consumedFlag")


def test_crash_restart_unit_start_and_consume(tmp_path):
    from fox3d.storelock import CrashInjected

    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    batch = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=2, source="FIXTURE", reason="crash")
    plat.pilot_batch.release_for_manual(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.pilot_batch.reserve_materials(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    unit = plat.pilot_batch.units_for(batch["batchId"], tenant_id="pa")[0]
    plat.pilot_batch._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat.pilot_batch.start_unit(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat2 = Platform(root=tmp_path / "live", mock_blender=True)
    started = plat2.pilot_batch.units[unit["unitExecutionId"]]
    assert started["state"] == "STARTED"
    again = plat2.pilot_batch.start_unit(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    assert again["unitExecutionId"] == unit["unitExecutionId"]
    plat2.pilot_batch._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat2.pilot_batch.consume_unit(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat3 = Platform(root=tmp_path / "live", mock_blender=True)
    consumed = plat3.pilot_batch.units[unit["unitExecutionId"]]
    assert consumed.get("consumedQuantity") is not None
    retry = plat3.pilot_batch.consume_unit(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    assert retry.get("consumedQuantity") == consumed.get("consumedQuantity")
    wo = plat3.pilot.workorders.get(batch["workOrderId"])
    assert wo.get("consumedFlag") is True


def test_cross_tenant_batch_reference_fails(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    batch = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=2, source="FIXTURE", reason="iso")
    with pytest.raises(PermissionError):
        plat.pilot_batch.get(batch["batchId"], tenant_id="pb")


def test_duplicate_labor_does_not_double(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    batch = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=2, source="FIXTURE", reason="labor")
    plat.pilot_batch.release_for_manual(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.pilot_batch.reserve_materials(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    unit = plat.pilot_batch.units_for(batch["batchId"], tenant_id="pa")[0]
    plat.pilot_batch.start_unit(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    first = plat.pilot_batch.record_labor(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], minutes=10, reason="assembly")
    again = plat.pilot_batch.record_labor(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], minutes=10, reason="assembly")
    assert again["laborId"] == first["laborId"]
    rows = [r for r in plat.pilot_batch.labor.values() if r.get("unitExecutionId") == unit["unitExecutionId"]]
    assert len(rows) == 1


def test_failed_qc_blocks_batch_go(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    batch = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=2, source="FIXTURE", reason="qc")
    plat.pilot_batch.release_for_manual(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    unit = plat.pilot_batch.units_for(batch["batchId"], tenant_id="pa")[0]
    plat.pilot_batch.start_unit(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.pilot_batch.record_qc(unit["unitExecutionId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], ok=False)
    ready = plat.pilot_batch.readiness(batch["batchId"], tenant_id="pa")
    assert "qc_sample" in ready["blockers"] or "unresolved_hold" in ready["blockers"]
    assert ready["decision"] in {"HOLD_REWORK", "WAITING_HUMAN_EVIDENCE"}


def test_duplicate_carton_assignment_fails(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    batch = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=2, source="FIXTURE", reason="carton")
    units = plat.pilot_batch.units_for(batch["batchId"], tenant_id="pa")
    plat.pilot_batch.pack_units(
        batch["batchId"],
        tenant_id="pa",
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        unit_execution_ids=[units[0]["unitExecutionId"]],
        measured={"cartonLengthMm": 1, "cartonWidthMm": 1, "cartonHeightMm": 1, "packedWeightKg": 1},
    )
    with pytest.raises(PilotBatchError, match="two active cartons"):
        plat.pilot_batch.pack_units(
            batch["batchId"],
            tenant_id="pa",
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            unit_execution_ids=[units[0]["unitExecutionId"], units[1]["unitExecutionId"]],
            measured={"cartonLengthMm": 1, "cartonWidthMm": 1, "cartonHeightMm": 1, "packedWeightKg": 1},
        )


def test_cost_money_without_packaging_qty_is_partial(tmp_path):
    plat, proto = _proto(tmp_path)
    fixture, shift = proto["fixture"], proto["fixtureShift"]
    sel = proto["selected"][0]
    batch = plat.pilot_batch.create(sel["candidateId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"], quantity=2, source="FIXTURE", reason="cost")
    plat.pilot_batch.release_for_manual(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    plat.pilot_batch.reserve_materials(batch["batchId"], tenant_id="pa", operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
    cost = plat.pilot_batch.record_cost(
        batch["batchId"],
        tenant_id="pa",
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        amounts={"materialAmount": 9, "hardwareAmount": 9, "laborAmount": 9, "packagingAmount": 9},
    )
    assert cost["completeness"] == "PARTIAL"
    assert cost["quantityLineage"]["ok"] is not True


def test_accepted_eco_invalidates_batch(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    run_portfolio = __import__("fox3d.portfolio", fromlist=["run_portfolio_scenario"]).run_portfolio_scenario
    run_portfolio(plat, tenant_a="pa", tenant_b="pb")
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, actor, sh = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    _manual_launch_ready(plat, cand, unit, human, human_shift)
    plat.prototype.record_launch_decision(cand["candidateId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], decision="HUMAN_GO", reason="go")
    batch = plat.pilot_batch.create(cand["candidateId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], quantity=2, source="MANUAL", reason="eco")
    plat.prototype.create_eco(cand["candidateId"], tenant_id="pa", operator_id=human["operatorId"], shift_id=human_shift["shiftId"], reason="change", changes=_eco_change(cand))
    ready = plat.pilot_batch.readiness(batch["batchId"], tenant_id="pa")
    assert ready["staleLineage"] is True or "stale_lineage" in ready["blockers"]
    _ = actor
    _ = sh
    _ = fixture
    _ = shift


def test_backup_restore_batch_state_no_tenant_b_leak(tmp_path):
    plat, proto = _proto(tmp_path)
    result = run_pilot_batch_scenario(plat, tenant_a="pa", tenant_b="pb")
    assert len(result["batches"]) == 4
    assert len(result["units"]) == 20
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["pa"])
    restore_pilot(dest, tmp_path / "r", tenant_id="pa")
    restored = Platform(root=tmp_path / "r", mock_blender=True)
    matrix = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="pa", tenant_b="pb")
    assert matrix["tenantLeakageAbsent"] is True
    assert matrix["tenantStateDigest"]["equal"] is True
    assert len(restored.pilot_batch.batches) == 4
    assert not any(b.get("tenantId") == "pb" for b in restored.pilot_batch.batches.values())


def test_scenario_flags_remain_blocked(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_pilot_batch_scenario(plat, tenant_a="pa", tenant_b="pb")
    assert result["physicalPilotBatchValidated"] is False
    assert result["liveMachineControl"] is False
    assert result["globalProductionReady"] is False
    assert result["fullAutonomousFactoryReady"] is False
    assert result["batchLaunchDecision"] != "HUMAN_BATCH_GO"
    from fox3d.pilot_batch import validate_pilot_batch_acceptance_result

    assert validate_pilot_batch_acceptance_result(result) == []
