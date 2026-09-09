"""Phase 481–540 Manual Factory Pilot scenario. FIXTURE/REAL_LOGIC, not Production Ready."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fox3d.backup import BackupError, backup_pilot, evaluate_tenant_restore_matrix, restore_pilot
from fox3d.platform import Platform
from fox3d.station import STATION_CAPS
from fox3d.workorder import FIXTURE_AUTO_SEED

REQUIRED_GATES = (
    "operatorTenantIsolation",
    "shiftRestartRecovery",
    "travelerReleasePinned",
    "scanTokenTenantSafe",
    "cycleCountApprovalRequired",
    "inventoryConservedAfterAdjustment",
    "laborHistoryAppendOnly",
    "blockingHoldPreventsCompletion",
    "reworkLineagePreserved",
    "packingReleasePinned",
    "manualShipmentNoProviderClaim",
    "backupChecksumVerified",
    "restoreReleaseHashPreserved",
    "restoreNoDoubleConsume",
    "restoreNoDoubleCompletion",
    "journalHealthyAfterRestore",
    "crossTenantRestoreRejected",
    "tenantLeakageAbsent",
    "tenantRequiredStatePreserved",
    "snapshotPathSetBound",
    "restoredRootHealthOk",
    "liveMachineControl",
    "globalProductionReady",
    "liveFactoryExecutionReady",
    "fullAutonomousFactoryReady",
)


def _false_ready() -> dict[str, bool]:
    return {
        "liveMachineControl": False,
        "globalProductionReady": False,
        "liveFactoryExecutionReady": False,
        "fullAutonomousFactoryReady": False,
    }


def _complete_remaining(pilot: Any, wo_id: str, *, actor: str, skip: set[str] | None = None) -> None:
    wo = pilot.workorders.get(wo_id)
    skip = skip or set()
    done = {o.get("operation") for o in wo.get("ops") or [] if o.get("status") == "COMPLETED"}
    for step in (wo.get("traveler") or {}).get("steps") or []:
        op_name = step["operation"]
        if op_name in done or op_name in skip:
            continue
        op = pilot.workorders.start_operation(wo_id, op_name, actor=actor)
        if op.get("status") != "COMPLETED":
            pilot.workorders.complete_operation(wo_id, op["opId"], actor=actor)
        done.add(op_name)


def seed_tenant_backup_fixture(plat: Platform, *, tenant_id: str, actor: str = "seed") -> dict[str, Any]:
    lot = plat.lots.receive(
        tenant_id=tenant_id, material="PB_18_WHITE", thickness=18, quantity=6, actor=actor, source="MANUAL"
    )
    remnants = plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 120, "h": 80, "area": 9600, "sheetIndex": 0}]},
        material="PB_18_WHITE",
        thickness=18,
        source_run=f"{tenant_id}-backup-seed",
        tenant_id=tenant_id,
        material_lot_id=lot["lotId"],
    )
    op = plat.pilot.identity.register_operator(
        tenant_id=tenant_id, display_name=f"Op {tenant_id}", capabilities=["MANUAL"]
    )
    shift = plat.pilot.identity.open_shift(
        tenant_id=tenant_id, operator_id=op["operatorId"], station_id=f"st-{tenant_id}"
    )
    station = plat.pilot.stations.register(
        tenant_id=tenant_id, capabilities=list(STATION_CAPS), actor=op["operatorId"]
    )
    product = plat.kd.build_sku(tenant_id=tenant_id, kind="OPEN_SHELF")
    rel = plat.pilot.open_release(product, tenant_id=tenant_id, family="KD_FURNITURE", actor=actor)
    wo = plat.pilot.workorders.create(tenant_id=tenant_id, release=rel, quantity=1, actor=actor)
    plat.pilot.workorders.release_for_execution(wo["workOrderId"], actor=actor)
    plat.pilot.workorders.reserve_materials(
        wo["workOrderId"], actor=actor, tenant_id=tenant_id, allocation_policy=FIXTURE_AUTO_SEED
    )
    first = wo["traveler"]["steps"][0]["operation"]
    plat.pilot.workorders.start_operation(wo["workOrderId"], first, actor=op["operatorId"])
    plat.pilot.dispatcher.dispatch(
        tenant_id=tenant_id,
        work_order_id=wo["workOrderId"],
        operation=first,
        station_id=station["stationId"],
        actor=op["operatorId"],
        operator_id=op["operatorId"],
        shift_id=shift["shiftId"],
    )
    plat.pilot.traveler_packet(tenant_id=tenant_id, work_order_id=wo["workOrderId"])
    plat.pilot.receiving.import_receipt(
        {"supplierLot": f"{tenant_id}-lot", "material": "PB_18_WHITE", "quantity": 2, "thickness": 18},
        tenant_id=tenant_id,
        actor=actor,
        source="IMPORTED",
    )
    plat.pilot.cyclecounts.create(
        tenant_id=tenant_id, lot_id=lot["lotId"], counted=5, reason="seed", actor=op["operatorId"]
    )
    packing = (rel.get("snapshot") or {}).get("packing") or {"length": 400, "width": 300, "height": 200}
    cartons = plat.pilot.logistics.instantiate_cartons(
        tenant_id=tenant_id,
        work_order_id=wo["workOrderId"],
        batch_id=wo["batchId"],
        plan=packing,
        quantity=1,
        release_hash=rel["releaseHash"],
        product_version=rel.get("productVersion"),
    )
    pallet = plat.pilot.logistics.palletize([c["cartonId"] for c in cartons])
    ship = plat.pilot.logistics.shipment_draft(
        origin="TW", destination="TW-TPE", carton_ids=[c["cartonId"] for c in cartons]
    )
    plat.pilot.logistics.packing_checklist(
        tenant_id=tenant_id, work_order_id=wo["workOrderId"], release_hash=rel["releaseHash"]
    )
    plat.pilot.logistics.shipment_handoff(
        ship["shipmentId"], tenant_id=tenant_id, carrier="VAN", tracking=f"TRK-{tenant_id}", actor=op["operatorId"]
    )
    plat.pilot.qc.final(
        tenant_id=tenant_id,
        work_order_id=wo["workOrderId"],
        check_id="THICKNESS",
        measured=18.0,
        nominal=18.0,
        tol=0.5,
        unit="mm",
        operator=op["operatorId"],
        source="MANUAL",
    )
    plat.pilot.qc.defect(
        tenant_id=tenant_id,
        work_order_id=wo["workOrderId"],
        code="DEF_THICKNESS",
        disposition="REWORK",
        actor=op["operatorId"],
    )
    plat.pilot.qc.persist()
    plat.pilot.inbox.record(
        tenant_id=tenant_id,
        code="PACKING_MISMATCH",
        work_order_id=wo["workOrderId"],
        release_hash=rel["releaseHash"],
        actor=op["operatorId"],
    )
    return {
        "lotId": lot["lotId"],
        "workOrderId": wo["workOrderId"],
        "releaseId": rel["releaseId"],
        "releaseHash": rel["releaseHash"],
        "cartonId": cartons[0]["cartonId"],
        "palletPlanId": pallet["palletPlanId"],
        "operatorId": op["operatorId"],
        "batchId": wo["batchId"],
        "remnantIds": [r["remnantId"] for r in remnants],
    }


def run_manual_factory_scenario(
    plat: Platform,
    *,
    tenants: tuple[str, str] = ("man-a", "man-b"),
    backup_dir: Path | None = None,
    restore_root: Path | None = None,
) -> dict[str, Any]:
    a, b = tenants
    gates = _false_ready()
    families = plat.pilot.run_four_family_e2e(tenant_id=a)
    product = plat.kd.build_sku(tenant_id=a, kind="OPEN_SHELF")
    rel = plat.pilot.open_release(product, tenant_id=a, family="KD_FURNITURE", actor="eng")
    wo = plat.pilot.workorders.create(tenant_id=a, release=rel, quantity=1, actor="ops")
    plat.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    plat.pilot.workorders.reserve_materials(
        wo["workOrderId"], actor="ops", tenant_id=a, allocation_policy=FIXTURE_AUTO_SEED
    )
    wo_id = wo["workOrderId"]

    op_a = plat.pilot.identity.register_operator(tenant_id=a, display_name="Op A", capabilities=["MANUAL"])
    op_disabled = plat.pilot.identity.register_operator(tenant_id=a, display_name="Op Off", enabled=False)
    op_b = plat.pilot.identity.register_operator(tenant_id=b, display_name="Op B")
    shift = plat.pilot.identity.open_shift(tenant_id=a, operator_id=op_a["operatorId"], station_id="st-manual")
    closed = plat.pilot.identity.open_shift(tenant_id=a, operator_id=op_a["operatorId"], station_id="st-closed")
    plat.pilot.identity.close_shift(closed["shiftId"], tenant_id=a, operator_id=op_a["operatorId"])

    disabled_rejected = False
    try:
        plat.pilot.identity.require_active(
            tenant_id=a, operator_id=op_disabled["operatorId"], shift_id=shift["shiftId"]
        )
    except PermissionError:
        disabled_rejected = True
    closed_rejected = False
    try:
        plat.pilot.identity.require_active(tenant_id=a, operator_id=op_a["operatorId"], shift_id=closed["shiftId"])
    except PermissionError:
        closed_rejected = True
    cross_op = False
    try:
        plat.pilot.identity.get_operator(op_b["operatorId"], tenant_id=a)
    except PermissionError:
        cross_op = True
    gates["operatorTenantIsolation"] = bool(disabled_rejected and closed_rejected and cross_op)

    station = plat.pilot.stations.register(tenant_id=a, capabilities=list(STATION_CAPS), actor=op_a["operatorId"])
    first = wo["traveler"]["steps"][0]["operation"]
    lease = plat.pilot.dispatcher.dispatch(
        tenant_id=a,
        work_order_id=wo_id,
        operation=first,
        station_id=station["stationId"],
        actor=op_a["operatorId"],
        operator_id=op_a["operatorId"],
        shift_id=shift["shiftId"],
    )
    plat.pilot.dispatcher.ack(
        lease["leaseId"],
        tenant_id=a,
        actor=op_a["operatorId"],
        operator_id=op_a["operatorId"],
        shift_id=shift["shiftId"],
    )
    plat.pilot.dispatcher.start(
        lease["leaseId"],
        tenant_id=a,
        actor=op_a["operatorId"],
        operator_id=op_a["operatorId"],
        shift_id=shift["shiftId"],
    )
    op_rec = plat.pilot.workorders.get(wo_id)["ops"][0]
    plat.pilot.workorders.pause_operation(wo_id, op_rec["opId"], actor=op_a["operatorId"])
    plat.pilot.workorders.resume_operation(wo_id, op_rec["opId"], actor=op_a["operatorId"])
    plat.pilot.workorders.correct_labor(wo_id, op_rec["opId"], actor=op_a["operatorId"], minutes=12, reason="manual-obs")
    plat.pilot.dispatcher.complete(
        lease["leaseId"],
        tenant_id=a,
        actor=op_a["operatorId"],
        confirm=True,
        operator_id=op_a["operatorId"],
        shift_id=shift["shiftId"],
    )
    again = plat.pilot.dispatcher.complete(
        lease["leaseId"], tenant_id=a, actor=op_a["operatorId"], confirm=True
    )
    gates["duplicateCompletionIdempotent"] = again.get("completed") is True

    stored = plat.pilot.traveler_packet(tenant_id=a, work_order_id=wo_id)
    packet = stored["packet"]
    gates["travelerReleasePinned"] = bool(packet.get("valid") and packet.get("releaseHash") == rel["releaseHash"])
    scanned = plat.pilot.resolve_traveler(packet["scanToken"], tenant_id=a)
    scan_safe = False
    try:
        plat.pilot.resolve_traveler(packet["scanToken"], tenant_id=b)
    except PermissionError:
        scan_safe = True
    gates["scanTokenTenantSafe"] = bool(scan_safe and scanned.get("authorizesOperation") is False)

    skip_qc = {"surface_inspection", "packaging", "packing"}
    _complete_remaining(plat.pilot, wo_id, actor=op_a["operatorId"], skip=skip_qc)

    plat.pilot.qc.final(
        tenant_id=a,
        work_order_id=wo_id,
        check_id="THICKNESS",
        measured=22.0,
        nominal=18.0,
        tol=0.5,
        unit="mm",
        operator=op_a["operatorId"],
        source="MANUAL",
    )
    hold = plat.pilot.workorders.hold(wo_id, actor=op_a["operatorId"], reason="QC_FAIL", blocking=True)
    blocked = False
    try:
        plat.pilot.workorders.complete(wo_id, actor=op_a["operatorId"], qc_ok=True)
    except PermissionError:
        blocked = True
    gates["blockingHoldPreventsCompletion"] = blocked
    plat.pilot.workorders.authorize_rework(
        wo_id, actor=op_a["operatorId"], reason="thickness", operation="rework_thickness", payload={"confirm": True}
    )
    plat.pilot.workorders.resolve_hold(wo_id, hold["holdId"], actor=op_a["operatorId"])
    rework_op = plat.pilot.workorders.start_operation(wo_id, "rework_thickness", actor=op_a["operatorId"])
    plat.pilot.workorders.complete_operation(wo_id, rework_op["opId"], actor=op_a["operatorId"])
    plat.pilot.qc.final(
        tenant_id=a,
        work_order_id=wo_id,
        check_id="THICKNESS",
        measured=18.0,
        nominal=18.0,
        tol=0.5,
        unit="mm",
        operator=op_a["operatorId"],
        source="MANUAL",
    )
    plat.pilot.qc.final(
        tenant_id=a,
        work_order_id=wo_id,
        check_id="PANEL_LENGTH",
        measured=400.0,
        nominal=400.0,
        tol=1.0,
        unit="mm",
        operator=op_a["operatorId"],
        source="MANUAL",
    )
    gates["reworkLineagePreserved"] = bool(plat.pilot.workorders.get(wo_id).get("reworkHistory"))
    plat.pilot.workorders.scrap(
        wo_id,
        actor=op_a["operatorId"],
        quantity=0.1,
        remnant_rects=[{"w": 200, "h": 150, "area": 30000, "sheetIndex": 0}],
        payload={"confirm": True},
        reason="offcut",
    )

    _complete_remaining(plat.pilot, wo_id, actor=op_a["operatorId"])
    labor = plat.pilot.workorders.labor_summary(wo_id)
    gates["laborHistoryAppendOnly"] = bool(labor.get("historyAppendOnly") and labor.get("accountingActual") == "NOT_IMPLEMENTED")

    packing = (rel.get("snapshot") or {}).get("packing") or {"length": 400, "width": 300, "height": 200}
    cartons = plat.pilot.logistics.instantiate_cartons(
        tenant_id=a,
        work_order_id=wo_id,
        batch_id=wo["batchId"],
        plan=packing,
        quantity=1,
        contents=[{"sku": "product", "qty": 1}],
        expected_weight_kg=8,
        release_hash=rel["releaseHash"],
        product_version=rel.get("productVersion"),
    )
    measured = plat.pilot.logistics.record_measured(
        cartons[0]["cartonId"], length=900, width=900, height=900, weight_kg=40, source="MANUAL"
    )
    if measured.get("mismatch"):
        plat.pilot.workorders.hold(wo_id, actor=op_a["operatorId"], reason="PACKING_MISMATCH", blocking=True)
        plat.pilot.inbox.record(
            tenant_id=a, code="PACKING_MISMATCH", work_order_id=wo_id, release_hash=rel["releaseHash"], actor=op_a["operatorId"]
        )
        for h in plat.pilot.workorders.get(wo_id).get("holds") or []:
            if h.get("open") and h.get("reason") == "PACKING_MISMATCH":
                plat.pilot.workorders.resolve_hold(wo_id, h["holdId"], actor=op_a["operatorId"])
    checklist = plat.pilot.logistics.packing_checklist(tenant_id=a, work_order_id=wo_id, release_hash=rel["releaseHash"])
    gates["packingReleasePinned"] = bool(checklist.get("pinned") and measured.get("autoOverride") is False)
    plat.pilot.workorders.set_packing(wo_id, [c["cartonId"] for c in cartons])
    ship = plat.pilot.logistics.shipment_draft(
        origin="TW", destination="TW-TPE", carton_ids=[c["cartonId"] for c in cartons]
    )
    handed = plat.pilot.logistics.shipment_handoff(
        ship["shipmentId"], tenant_id=a, carrier="MANUAL_VAN", tracking="TRK-1", actor=op_a["operatorId"]
    )
    again_hand = plat.pilot.logistics.shipment_handoff(
        ship["shipmentId"], tenant_id=a, carrier="MANUAL_VAN", tracking="TRK-1", actor=op_a["operatorId"]
    )
    gates["manualShipmentNoProviderClaim"] = (
        handed.get("booked") is False
        and handed.get("submittedToCarrier") is False
        and (handed.get("handoff") or {}).get("liveProvider") is False
        and (handed.get("handoff") or {}).get("deliveryConfirmed") is False
        and again_hand.get("handoff", {}).get("handoffId") == handed.get("handoff", {}).get("handoffId")
    )
    plat.pilot.logistics.palletize([c["cartonId"] for c in cartons])
    plat.pilot.receiving.import_receipt(
        {"supplierLot": f"{a}-lot", "material": "PB_18_WHITE", "quantity": 2, "thickness": 18},
        tenant_id=a,
        actor=op_a["operatorId"],
        source="IMPORTED",
    )
    plat.pilot.logistics.import_carrier_quote(
        {"carrier": "TW-POST", "service": "ground", "charge": 180, "dimDivisor": 6000}, source="IMPORTED"
    )
    plat.pilot.qc.defect(
        tenant_id=a,
        work_order_id=wo_id,
        code="DEF_THICKNESS",
        disposition="REWORK",
        actor=op_a["operatorId"],
    )
    plat.pilot.qc.persist()

    plat.pilot.workorders.consume_reserved(wo_id, actor=op_a["operatorId"])
    plat.pilot.workorders.complete(wo_id, actor=op_a["operatorId"], qc_ok=True)

    lot = plat.lots.receive(
        tenant_id=a, material="PB_18_WHITE", thickness=18, quantity=10, actor=op_a["operatorId"], source="MANUAL"
    )
    before = plat.lots.quantities(lot["lotId"], tenant_id=a)
    cc = plat.pilot.cyclecounts.create(
        tenant_id=a, lot_id=lot["lotId"], counted=8, reason="physical-count", actor=op_a["operatorId"]
    )
    waiting_status = cc.get("status")
    mid = plat.lots.quantities(lot["lotId"], tenant_id=a)
    no_confirm = False
    try:
        plat.pilot.cyclecounts.approve(cc["cycleCountId"], tenant_id=a, actor=op_a["operatorId"], payload={})
    except PermissionError:
        no_confirm = True
    approved = plat.pilot.cyclecounts.approve(
        cc["cycleCountId"], tenant_id=a, actor=op_a["operatorId"], payload={"confirm": True}
    )
    after = plat.lots.quantities(lot["lotId"], tenant_id=a)
    gates["cycleCountApprovalRequired"] = bool(waiting_status == "WAITING_HUMAN_APPROVAL" and no_confirm and mid == before)
    gates["inventoryConservedAfterAdjustment"] = bool(
        approved.get("consumedUnchanged")
        and approved.get("reservedUnchanged")
        and after.get("conserved")
        and after.get("available") == 8
    )

    mid_wo = plat.pilot.workorders.create(tenant_id=a, release=rel, quantity=1, actor="ops")
    plat.pilot.workorders.release_for_execution(mid_wo["workOrderId"], actor="ops")
    plat.pilot.workorders.reserve_materials(
        mid_wo["workOrderId"], actor="ops", tenant_id=a, allocation_policy=FIXTURE_AUTO_SEED
    )
    plat.pilot.workorders.start_operation(mid_wo["workOrderId"], first, actor=op_a["operatorId"])
    plat2 = Platform(root=plat.root, mock_blender=True)
    recovered_shift = plat2.pilot.identity.get_shift(shift["shiftId"], tenant_id=a)
    recovered_wo = plat2.pilot.workorders.get(mid_wo["workOrderId"])
    gates["shiftRestartRecovery"] = recovered_shift.get("status") == "OPEN" and recovered_wo.get("state") == "IN_PROGRESS"
    plat2.pilot.identity.require_active(tenant_id=a, operator_id=op_a["operatorId"], shift_id=shift["shiftId"])

    seed_tenant_backup_fixture(plat, tenant_id=b, actor=op_b["operatorId"])
    plat.pilot.outbox.prepare(
        {
            "tenant_id": b,
            "aggregate_type": "Seed",
            "aggregate_id": f"{b}-tx",
            "semantic_key": f"{b}::seed-tx",
        }
    )
    live_event_ids = {e.get("eventId") for e in plat.pilot.journal.list(a) if e.get("eventId")}

    backup_dir = Path(backup_dir or (plat.root.parent / "backup-export"))
    restore_root = Path(restore_root or (plat.root.parent / "restore-root"))
    if backup_dir.exists():
        from shutil import rmtree

        rmtree(backup_dir)
    backup = backup_pilot(plat.root, backup_dir, tenant_ids=[a])
    verified = plat.pilot.verify_backup(backup_dir)
    restored = restore_pilot(backup_dir, restore_root, tenant_id=a)
    restarted = plat.pilot.restart_restored(restore_root, tenant_id=a, work_order_id=wo_id)
    cross_restore = False
    try:
        restore_pilot(backup_dir, restore_root.parent / "restore-b", tenant_id=b)
    except PermissionError:
        cross_restore = True
    restored_plat = Platform(root=restore_root, mock_blender=True)
    matrix = evaluate_tenant_restore_matrix(
        live=plat, restored=restored_plat, tenant_a=a, tenant_b=b, live_event_ids=live_event_ids
    )
    carton_retry = restored_plat.pilot.logistics.instantiate_cartons(
        tenant_id=a,
        work_order_id=wo_id,
        batch_id=wo["batchId"],
        plan=packing,
        quantity=1,
        release_hash=rel["releaseHash"],
        product_version=rel.get("productVersion"),
    )
    idem_a = bool(carton_retry) and carton_retry[0]["cartonId"] == cartons[0]["cartonId"] and carton_retry[0].get("tenantId") == a
    b_absent = matrix.get("tenantLeakageAbsent") is True
    from shutil import copytree

    tamper_dir = backup_dir.parent / "backup-tamper"
    if tamper_dir.exists():
        from shutil import rmtree

        rmtree(tamper_dir)
    copytree(backup_dir, tamper_dir)
    extra = tamper_dir / "data" / "lots" / "unlisted.json"
    extra.write_text("{}", encoding="utf-8")
    extra_blocked = False
    try:
        plat.pilot.verify_backup(tamper_dir)
    except (BackupError, PermissionError, ValueError):
        extra_blocked = True
    man = tamper_dir / "manifest.json"
    payload = json.loads(man.read_text(encoding="utf-8"))
    payload["manifestHash"] = "0" * 64
    extra.unlink(missing_ok=True)
    man.write_text(json.dumps(payload), encoding="utf-8")
    tamper_blocked = False
    try:
        plat.pilot.verify_backup(tamper_dir)
    except (BackupError, PermissionError, ValueError):
        tamper_blocked = True
    gates["backupChecksumVerified"] = bool(verified.get("ok") and tamper_blocked and extra_blocked and backup.get("consistentSnapshot") is True)
    gates["restoreReleaseHashPreserved"] = (
        restarted.get("releaseHash") == rel["releaseHash"]
        and restarted.get("releaseHashAfter") == rel["releaseHash"]
        and (restarted.get("before") or {}).get("releaseHash") == rel["releaseHash"]
    )
    gates["restoreNoDoubleConsume"] = restarted.get("noDoubleConsume") is True
    gates["restoreNoDoubleCompletion"] = restarted.get("noDoubleCompletion") is True
    health = restored_plat.pilot.health(tenant_id=a)
    gates["restoredRootHealthOk"] = bool((health.get("journalIntegrity") or {}).get("ok") is True)
    gates["journalHealthyAfterRestore"] = bool(
        restarted.get("journalOk") is True
        and restored_plat.pilot.journal.verify(a).get("ok") is True
        and gates["restoredRootHealthOk"] is True
    )
    gates["tenantLeakageAbsent"] = bool(b_absent)
    gates["tenantRequiredStatePreserved"] = bool(matrix.get("tenantRequiredStatePreserved") is True and idem_a)
    gates["snapshotPathSetBound"] = bool(backup.get("consistentSnapshot") is True and backup.get("snapshotPathSetBound") is True)
    gates["crossTenantRestoreRejected"] = bool(cross_restore and b_absent)
    other = False
    try:
        plat2.pilot.workorders._require(wo_id, tenant_id=b)
    except PermissionError:
        other = True
    gates["operatorTenantIsolation"] = bool(gates["operatorTenantIsolation"] and other)

    return {
        "ok": all(gates[k] is True for k in REQUIRED_GATES if k not in _false_ready())
        and gates["liveMachineControl"] is False
        and gates["globalProductionReady"] is False
        and gates["liveFactoryExecutionReady"] is False
        and gates["fullAutonomousFactoryReady"] is False,
        "gates": gates,
        "families": families,
        "workOrderId": wo_id,
        "releaseHash": rel["releaseHash"],
        "backup": backup,
        "restore": restored,
        "restart": restarted,
        "labor": labor,
        "health": health,
        "tenantBackupMatrix": matrix,
        "label": "FIXTURE/REAL_LOGIC",
        "liveCnc": "BLOCKED",
        "liveLaser": "BLOCKED",
        "notFactoryThroughput": True,
    }
