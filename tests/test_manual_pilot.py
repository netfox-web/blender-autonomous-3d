"""Phase 481–540 Manual Factory Pilot. MOCK/unit/FIXTURE/REAL_LOGIC — not Production Ready."""

from __future__ import annotations

import json

import pytest

from fox3d.backup import BackupError, backup_pilot, restore_pilot, verify_backup
from fox3d.manual_pilot import REQUIRED_GATES, run_manual_factory_scenario
from fox3d.platform import Platform
from fox3d.workorder import FIXTURE_AUTO_SEED


def test_operator_shift_fail_closed_and_restart(platform, tmp_path):
    ident = platform.pilot.identity
    op = ident.register_operator(tenant_id="ta", display_name="A")
    disabled = ident.register_operator(tenant_id="ta", display_name="D", enabled=False)
    other = ident.register_operator(tenant_id="tb", display_name="B")
    shift = ident.open_shift(tenant_id="ta", operator_id=op["operatorId"], station_id="s1")
    ident.require_active(tenant_id="ta", operator_id=op["operatorId"], shift_id=shift["shiftId"])
    with pytest.raises(PermissionError):
        ident.require_active(tenant_id="ta", operator_id=disabled["operatorId"], shift_id=shift["shiftId"])
    ident.close_shift(shift["shiftId"], tenant_id="ta", operator_id=op["operatorId"])
    with pytest.raises(PermissionError):
        ident.require_active(tenant_id="ta", operator_id=op["operatorId"], shift_id=shift["shiftId"])
    with pytest.raises(PermissionError):
        ident.get_operator(other["operatorId"], tenant_id="ta")
    open_shift = ident.open_shift(tenant_id="ta", operator_id=op["operatorId"], station_id="s1")
    plat2 = Platform(root=platform.root, mock_blender=True)
    rec = plat2.pilot.identity.get_shift(open_shift["shiftId"], tenant_id="ta")
    assert rec["status"] == "OPEN"
    plat2.pilot.identity.require_active(tenant_id="ta", operator_id=op["operatorId"], shift_id=open_shift["shiftId"])


def test_traveler_token_does_not_authorize(platform):
    row = platform.pilot.run_family_e2e(tenant_id="tv", family="KD_FURNITURE", kind="OPEN_SHELF")
    stored = platform.pilot.traveler_packet(tenant_id="tv", work_order_id=row["workOrderId"])
    packet = stored["packet"]
    assert packet["releaseHash"] == row["releaseHash"]
    assert packet["authorizesOperation"] is False
    scanned = platform.pilot.resolve_traveler(packet["scanToken"], tenant_id="tv")
    assert scanned["authorizesOperation"] is False
    with pytest.raises(PermissionError):
        platform.pilot.resolve_traveler(packet["scanToken"], tenant_id="other")


def test_cycle_count_approval_preserves_consumed_reserved(platform):
    lot = platform.lots.receive(tenant_id="cc", material="PB_18_WHITE", thickness=18, quantity=6, actor="ops", source="MANUAL")
    platform.lots.reserve_sheets(lot["lotId"], tenant_id="cc", work_order_id="w", quantity=2)
    before = platform.lots.quantities(lot["lotId"], tenant_id="cc")
    cc = platform.pilot.cyclecounts.create(tenant_id="cc", lot_id=lot["lotId"], counted=3, reason="count", actor="ops")
    assert cc["status"] == "WAITING_HUMAN_APPROVAL"
    assert platform.lots.quantities(lot["lotId"], tenant_id="cc") == before
    with pytest.raises(PermissionError):
        platform.pilot.cyclecounts.approve(cc["cycleCountId"], tenant_id="cc", actor="ops", payload={})
    approved = platform.pilot.cyclecounts.approve(
        cc["cycleCountId"], tenant_id="cc", actor="ops", payload={"confirm": True}
    )
    after = platform.lots.quantities(lot["lotId"], tenant_id="cc")
    assert approved["consumedUnchanged"] is True
    assert approved["reservedUnchanged"] is True
    assert after["reserved"] == before["reserved"]
    assert after["consumed"] == before["consumed"]
    assert after["available"] == 3
    assert after["conserved"] is True
    rejected = platform.pilot.cyclecounts.create(
        tenant_id="cc", lot_id=lot["lotId"], counted=9, reason="reject-me", actor="ops"
    )
    platform.pilot.cyclecounts.reject(rejected["cycleCountId"], tenant_id="cc", actor="ops")
    assert platform.lots.quantities(lot["lotId"], tenant_id="cc")["available"] == 3


def test_hold_rework_labor_and_packing(platform):
    rel = platform.pilot.open_release(
        platform.kd.build_sku(tenant_id="hz", kind="OPEN_SHELF"), tenant_id="hz", family="KD_FURNITURE"
    )
    wo = platform.pilot.workorders.create(tenant_id="hz", release=rel, quantity=1, actor="ops")
    platform.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    platform.pilot.workorders.reserve_materials(
        wo["workOrderId"], actor="ops", tenant_id="hz", allocation_policy=FIXTURE_AUTO_SEED
    )
    wo_id = wo["workOrderId"]
    first = wo["traveler"]["steps"][0]["operation"]
    op = platform.pilot.workorders.start_operation(wo_id, first, actor="ops")
    platform.pilot.workorders.pause_operation(wo_id, op["opId"], actor="ops")
    platform.pilot.workorders.resume_operation(wo_id, op["opId"], actor="ops")
    platform.pilot.workorders.correct_labor(wo_id, op["opId"], actor="ops", minutes=5, reason="obs")
    segs = platform.pilot.workorders.get(wo_id)["ops"][0]["labor"]["segments"]
    assert segs  # append-only segments, corrections never rewrite
    platform.pilot.workorders.complete_operation(wo_id, op["opId"], actor="ops")
    hold = platform.pilot.workorders.hold(wo_id, actor="ops", reason="WAIT", blocking=True)
    with pytest.raises(PermissionError, match="blocking hold"):
        platform.pilot.workorders.complete(wo_id, actor="ops", qc_ok=True)
    platform.pilot.workorders.authorize_rework(
        wo_id, actor="ops", reason="fix", operation="rework_hold", payload={"confirm": True}
    )
    assert platform.pilot.workorders.get(wo_id)["reworkHistory"]
    platform.pilot.workorders.resolve_hold(wo_id, hold["holdId"], actor="ops")
    labor = platform.pilot.workorders.labor_summary(wo_id)
    assert labor["estimateSource"] == "CONFIG_ESTIMATE"
    assert labor["actualSource"] == "MANUAL"
    assert labor["accountingActual"] == "NOT_IMPLEMENTED"
    assert labor["historyAppendOnly"] is True
    cartons = platform.pilot.logistics.instantiate_cartons(
        tenant_id="hz",
        work_order_id=wo_id,
        batch_id=wo["batchId"],
        plan={"length": 400, "width": 300, "height": 200},
        quantity=1,
        release_hash=rel["releaseHash"],
    )
    expected = dict(cartons[0]["expected"])
    measured = platform.pilot.logistics.record_measured(
        cartons[0]["cartonId"], length=900, width=900, height=900, weight_kg=40, source="MANUAL"
    )
    assert measured["mismatch"] is True
    assert measured["expected"] == expected
    assert measured["autoOverride"] is False
    checklist = platform.pilot.logistics.packing_checklist(
        tenant_id="hz", work_order_id=wo_id, release_hash=rel["releaseHash"]
    )
    assert checklist["pinned"] is True
    ship = platform.pilot.logistics.shipment_draft(
        origin="TW", destination="TW-TPE", carton_ids=[cartons[0]["cartonId"]]
    )
    handed = platform.pilot.logistics.shipment_handoff(
        ship["shipmentId"], tenant_id="hz", carrier="VAN", tracking="T1", actor="ops"
    )
    assert handed["booked"] is False
    assert handed["handoff"]["liveProvider"] is False
    assert handed["handoff"]["deliveryConfirmed"] is False
    again = platform.pilot.logistics.shipment_handoff(
        ship["shipmentId"], tenant_id="hz", carrier="VAN", tracking="T1", actor="ops"
    )
    assert again["handoff"]["handoffId"] == handed["handoff"]["handoffId"]
    with pytest.raises(PermissionError):
        platform.pilot.logistics.shipment_handoff(
            ship["shipmentId"], tenant_id="other", carrier="VAN", tracking="T1", actor="ops"
        )


def test_backup_restore_checksum_and_tenant(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    plat.lots.receive(tenant_id="ba", material="PB_18_WHITE", thickness=18, quantity=2, actor="ops", source="MANUAL")
    dest = tmp_path / "bak"
    backup_pilot(plat.root, dest, tenant_ids=["ba"])
    assert verify_backup(dest)["ok"] is True
    with pytest.raises(PermissionError):
        restore_pilot(dest, tmp_path / "r-b", tenant_id="bb")
    restored = restore_pilot(dest, tmp_path / "r-a", tenant_id="ba")
    assert restored["ok"] is True
    man = dest / "manifest.json"
    payload = json.loads(man.read_text(encoding="utf-8"))
    payload["manifestHash"] = "0" * 64
    man.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError):
        verify_backup(dest)


def test_manual_factory_scenario_gates(tmp_path):
    plat = Platform(root=tmp_path / "live", mock_blender=True)
    result = run_manual_factory_scenario(
        plat, backup_dir=tmp_path / "bak", restore_root=tmp_path / "restore"
    )
    assert result["liveCnc"] == "BLOCKED"
    assert result["gates"]["liveMachineControl"] is False
    assert result["gates"]["globalProductionReady"] is False
    missing = [
        k
        for k in REQUIRED_GATES
        if k not in {"liveMachineControl", "globalProductionReady", "liveFactoryExecutionReady", "fullAutonomousFactoryReady"}
        and result["gates"].get(k) is not True
    ]
    assert missing == [], missing
    assert result["ok"] is True
