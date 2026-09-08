"""Phase 301–360 manufacturing release / pilot ops. MOCK blender — not Production Ready."""

from __future__ import annotations

import pytest

from fox3d.logistics import LogisticsService
from fox3d.mfg_release import FORBIDDEN_STATES, ManufacturingReleaseService, product_snapshot
from fox3d.pilot_econ import PilotEconomics
from fox3d.qc import QcService
from fox3d.readiness import scoped_readiness
from fox3d.supplier import SupplierQuoteService
from fox3d.workorder import WorkOrderService


def _open(platform, *, family="KD_FURNITURE", kind="OPEN_SHELF", tenant="t1"):
    return platform.pilot.run_family_e2e(tenant_id=tenant, family=family, kind=kind, actor="tester")


def test_manufacturing_release_packet_and_tamper(platform):
    product = platform.kd.build_sku(tenant_id="t1", kind="OPEN_SHELF")
    svc = platform.pilot.releases
    snap = product_snapshot(product, family="KD_FURNITURE")
    rel = svc.create(snap, tenant_id="t1", created_by="eng")
    assert rel["status"] == "DRAFT"
    assert rel["liveMachineControl"] is False
    assert rel["equalsLiveCnc"] is False
    svc.validate(rel["releaseId"])
    svc.submit_approval(rel["releaseId"], actor="eng")
    svc.approve(rel["releaseId"], actor="human")
    approved = svc.release_for_manual_execution(rel["releaseId"], actor="human")
    assert approved["status"] == "RELEASED_FOR_MANUAL_EXECUTION"
    assert approved["status"] not in FORBIDDEN_STATES
    packet = svc.packet(rel["releaseId"])
    for name in ("release_manifest.json", "bom.csv", "cut_list.csv", "nesting.svg", "nesting.dxf.json", "edge_banding.csv", "hardware_pick.csv", "assembly_steps.json", "carton_packing.json", "checksums.json"):
        assert name in packet
        assert packet[name]
    assert svc.verify(rel["releaseId"])["ok"] is True
    svc.tamper(rel["releaseId"], "bom.csv", packet["bom.csv"] + "\nhacked,1\n")
    assert svc.verify(rel["releaseId"])["ok"] is False
    frozen = dict(approved["frozenCost"])
    assert frozen["recomputeForbidden"] is True


def test_release_stale_on_engineering_change(platform):
    product = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    svc = platform.pilot.releases
    snap = product_snapshot(product, family="KD_FURNITURE")
    rel = svc.create(snap, tenant_id="t1", created_by="eng")
    svc.validate(rel["releaseId"])
    mutated = dict(snap)
    mutated["engineeringHash"] = "deadbeef" * 8
    stale = svc.refresh_stale(rel["releaseId"], mutated)
    assert stale["stale"] is True
    assert stale["status"] == "STALE"


def test_family_packets_retail_packaging_acrylic(platform):
    svc = platform.pilot.releases
    retail = platform.physical.retail.build(tenant_id="t1", family="COUNTER_DISPLAY")
    rel_r = svc.create(product_snapshot(retail, family="RETAIL_FIXTURE"), tenant_id="t1", created_by="eng")
    svc.validate(rel_r["releaseId"])
    pkt_r = svc.packet(rel_r["releaseId"])
    assert "planogram.json" in pkt_r
    assert "BLOCKED" in pkt_r["fixture_dims.json"]
    pkg = platform.physical.packaging.build(tenant_id="t1", family="RSC_CARTON", product_dims={"width": 120, "height": 80, "depth": 40})
    rel_p = svc.create(product_snapshot(pkg, family="PACKAGING_STRUCTURE"), tenant_id="t1", created_by="eng")
    svc.validate(rel_p["releaseId"])
    pkt_p = svc.packet(rel_p["releaseId"])
    assert "dieline.svg" in pkt_p
    assert "ENGINEERING_ESTIMATE" in pkt_p["board_grade.json"]
    acr = platform.physical.acrylic.build(tenant_id="t1", kind="MENU_STAND")
    rel_a = svc.create(product_snapshot(acr, family="ACRYLIC_SHEET"), tenant_id="t1", created_by="eng")
    svc.validate(rel_a["releaseId"])
    pkt_a = svc.packet(rel_a["releaseId"])
    assert "LIVE_LASER" in pkt_a["laser_export.json"]
    assert "false" in pkt_a["cut_plan.json"].lower() or "liveLaser" in pkt_a["cut_plan.json"]


def test_supplier_quotes_compare_and_stale():
    svc = SupplierQuoteService()
    svc.capabilities.add({"name": "Mill A", "materials": ["PB_18_WHITE"], "thicknessMm": [18], "moq": 1, "leadTimeDays": 5, "processType": "panel", "currency": "TWD"})
    quotes = svc.import_json(
        """[
          {"supplierId": "A", "material": 400, "processing": 100, "setup": 50, "packaging": 20, "freight": 40, "moq": 1, "leadTimeDays": 4},
          {"supplierId": "B", "material": 350, "processing": 140, "setup": 200, "packaging": 20, "freight": 80, "moq": 50, "leadTimeDays": 14},
          {"supplierId": "C", "material": 410, "processing": 90, "setup": 40, "packaging": 25, "freight": 35, "moq": 5, "leadTimeDays": 6}
        ]""",
        source="IMPORTED",
    )
    assert all(q["source"] == "IMPORTED" and q["liveProvider"] is False for q in quotes)
    fx = svc.import_fx({"pair": "USD/TWD", "rate": 32.1}, source="MANUAL")
    assert fx["source"] == "MANUAL"
    cmp = svc.compare([q["quoteId"] for q in quotes], release_hash="rel-1", quantity=10, fx_snapshot_id=fx["snapshotId"])
    assert cmp["winner"]
    assert cmp["ranked"][0]["components"]
    assert svc.comparison_stale(cmp, release_hash="rel-2", quantity=10, fx_snapshot_id=fx["snapshotId"]) is True
    assert svc.comparison_stale(cmp, release_hash="rel-1", quantity=99, fx_snapshot_id=fx["snapshotId"]) is True
    with pytest.raises(PermissionError):
        svc.import_quote({"supplierId": "X"}, source="LIVE_PROVIDER")


def test_workorder_idempotent_reserve_cancel_and_tenant(platform):
    row = _open(platform, tenant="alpha")
    wo_id = row["workOrderId"]
    rel = platform.pilot.releases.get(row["releaseId"])
    wo_svc: WorkOrderService = platform.pilot.workorders
    again = wo_svc.create(tenant_id="alpha", release=rel, quantity=1, batch_id=wo_svc.get(wo_id)["batchId"])
    assert again["workOrderId"] == wo_id
    reserved = wo_svc.reserve_materials(wo_id, actor="tester", tenant_id="alpha")
    assert reserved["materialReserved"] is True
    n = len(reserved["reservations"])
    reserved2 = wo_svc.reserve_materials(wo_id, actor="tester", tenant_id="alpha")
    assert len(reserved2["reservations"]) == n
    wo_svc.consume_reserved(wo_id, actor="tester")
    wo_svc.consume_reserved(wo_id, actor="tester")
    with pytest.raises(PermissionError):
        wo_svc._require(wo_id, tenant_id="beta")
    rel2 = platform.pilot.open_release(platform.kd.build_sku(tenant_id="alpha", kind="DESK_RISER"), tenant_id="alpha", family="KD_FURNITURE")
    wo2 = wo_svc.create(tenant_id="alpha", release=rel2, quantity=1, actor="tester")
    wo_svc.release_for_execution(wo2["workOrderId"], actor="tester")
    wo_svc.reserve_materials(wo2["workOrderId"], actor="tester", tenant_id="alpha")
    cancelled = wo_svc.cancel(wo2["workOrderId"], actor="tester")
    assert cancelled["state"] == "CANCELLED"
    cancelled2 = wo_svc.cancel(wo2["workOrderId"], actor="tester")
    assert cancelled2["state"] == "CANCELLED"


def test_qc_blocks_and_rework_and_trace(platform):
    row = _open(platform, tenant="qc1")
    qc: QcService = platform.pilot.qc
    wo_svc = platform.pilot.workorders
    rel = platform.pilot.open_release(platform.kd.build_sku(tenant_id="qc1", kind="OPEN_SHELF"), tenant_id="qc1", family="KD_FURNITURE")
    wo = wo_svc.create(tenant_id="qc1", release=rel, quantity=1, actor="qc")
    wo_svc.release_for_execution(wo["workOrderId"], actor="qc")
    wo_svc.reserve_materials(wo["workOrderId"], actor="qc")
    fail = qc.final(
        tenant_id="qc1",
        work_order_id=wo["workOrderId"],
        check_id="THICKNESS",
        measured=20.0,
        nominal=18.0,
        tol=0.5,
        unit="mm",
        operator="qc",
        source="TEST_DATA",
    )
    assert fail["ok"] is False
    assert qc.completion_allowed(wo["workOrderId"], "KD_FURNITURE") is False
    with pytest.raises(PermissionError):
        wo_svc.complete(wo["workOrderId"], actor="qc", qc_ok=False)
    assert wo_svc.get(wo["workOrderId"])["state"] == "QC_HOLD"
    qc.defect(tenant_id="qc1", work_order_id=wo["workOrderId"], code="DEF_THICKNESS", disposition="REWORK", actor="qc")
    assert wo_svc.get(wo["workOrderId"])["state"] == "IN_PROGRESS"
    qc.final(
        tenant_id="qc1",
        work_order_id=wo["workOrderId"],
        check_id="THICKNESS",
        measured=18.1,
        nominal=18.0,
        tol=0.5,
        unit="mm",
        operator="qc",
    )
    qc.final(
        tenant_id="qc1",
        work_order_id=wo["workOrderId"],
        check_id="PANEL_LENGTH",
        measured=400,
        nominal=400,
        tol=1.0,
        unit="mm",
        operator="qc",
    )
    assert qc.completion_allowed(wo["workOrderId"], "KD_FURNITURE") is True
    wo_svc.complete(wo["workOrderId"], actor="qc", qc_ok=True)
    trace = qc.trace(work_order_id=wo["workOrderId"])
    assert trace["releaseHash"] == rel["releaseHash"]
    assert trace["workOrderId"] == wo["workOrderId"]
    assert trace["qc"]
    asset = platform.dam.put(tenant_id="qc1", kind="qc", name="photo.png", data=b"\x89PNG")
    qc.record(
        tenant_id="qc1",
        work_order_id=wo["workOrderId"],
        stage="IN_PROCESS",
        check_id="FINISH",
        measured=1,
        nominal=1,
        tol=0,
        unit="ok",
        operator="qc",
        dam_asset_id=asset.asset_id,
        source="IMPORTED",
    )
    with pytest.raises(PermissionError):
        platform.dam.get(asset.asset_id, tenant_id="other")


def test_logistics_conservation_dimweight_pallet_label():
    log = LogisticsService()
    cartons = log.instantiate_cartons(
        tenant_id="t",
        work_order_id="wo1",
        batch_id="b1",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=4,
        contents=[{"sku": "product", "qty": 1}],
        expected_weight_kg=10,
    )
    assert log.contents_conserved(work_order_id="wo1", expected_qty=4) is True
    expected = dict(cartons[0]["expected"])
    log.record_measured(cartons[0]["cartonId"], length=402, width=298, height=201, weight_kg=10.4, source="IMPORTED")
    assert log.cartons[cartons[0]["cartonId"]]["expected"] == expected
    dw = log.dim_weight(cartons[0]["expected"])
    assert "dimWeightKg" in dw
    pal = log.palletize([c["cartonId"] for c in cartons])
    assert pal["carrierCertification"] is False
    assert pal["label"] == "PLANNING"
    req = log.shipping_request(origin="TW", destination="TW-TPE", carton_ids=[c["cartonId"] for c in cartons])
    assert req["submittedToCarrier"] is False
    q = log.import_carrier_quote({"carrier": "X", "service": "ground", "charge": 220, "dimDivisor": 6000}, source="IMPORTED")
    assert q["truthLabel"] == "IMPORTED"
    assert log.quote_stale(q, service="air") is True
    label = log.label_payload(cartons[0]["cartonId"])
    assert label["barcode"]["label"] == "PARTIAL"
    assert label["printerPath"] is None
    again = log.instantiate_cartons(
        tenant_id="t",
        work_order_id="wo1",
        batch_id="b1",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=4,
    )
    assert [c["cartonId"] for c in again] == [c["cartonId"] for c in cartons]


def test_unit_economics_freeze_and_no_double_credit():
    econ = PilotEconomics()
    frozen = {
        "estimatedCost": 1000.0,
        "breakdown": {"SheetCost": 400, "ProcessingCost": 200, "HardwareCost": 80, "PackagingCost": 40, "SheetWasteCost": 30},
        "freezeHash": "abc",
        "recomputeForbidden": True,
    }
    actual = econ.import_actuals(
        work_order_id="wo",
        release_hash="rh",
        rows={"material": 420, "processing": 210, "hardware": 80, "packaging": 42, "freight": 50, "scrap": 20, "rework": 10},
        source="MANUAL",
    )
    var = econ.variance(frozen=frozen, actual=actual)
    assert var["historyUnchanged"] is True
    assert var["delta"] != 0
    waste = econ.waste_economics(true_scrap_mm2=1e6, remnant_mm2=2e6, recovered_mm2=5e5, cost_per_m2=280)
    assert waste["doubleCredit"] is False
    assert waste["trueScrapCost"] == 280.0
    with pytest.raises(ValueError):
        econ.waste_economics(true_scrap_mm2=1, remnant_mm2=10, recovered_mm2=11, cost_per_m2=280)
    m = econ.contribution_margin(price=2000, cost=actual["total"])
    assert m["paymentProcessing"] is False
    be = econ.break_even(setup=200, tooling=100, price=50, unit_variable=20, moq=10)
    assert be["breakEvenQty"] >= 10
    obs = econ.rd_observation(sku_id="sku", product_version=1, window="2026-W1", metrics={"margin": 0.4}, source="MANUAL")
    assert obs["demand"] == "MOCK"
    assert econ.history_intact(frozen, "abc") is True


def test_four_family_pilot_e2e(platform):
    result = platform.pilot.run_four_family_e2e(tenant_id="fam")
    assert result["ok"] is True
    assert result["liveFactoryExecutionReady"] is False
    families = {r["family"] for r in result["families"]}
    assert families == {"KD_FURNITURE", "RETAIL_FIXTURE", "PACKAGING_STRUCTURE", "ACRYLIC_SHEET"}
    for row in result["families"]:
        assert row["workOrderState"] == "COMPLETED"
        assert row["verify"]["ok"] is True
        assert row["liveMachineControl"] is False


def test_batch_stress_and_readiness(platform):
    stress = platform.pilot.batch_stress(tenant_id="stress")
    assert stress["releaseCount"] == 20
    assert stress["operationCount"] >= 100
    assert stress["idempotentRelease"] is True
    assert stress["noDoubleConsume"] is True
    assert stress["materialConserved"] is True
    assert stress["tenantIsolation"] is True
    assert stress["staleReleaseBlocked"] is True
    assert stress["label"] == "FIXTURE"
    wo0 = next(iter(platform.pilot.workorders.orders.values()))
    rel = platform.pilot.releases.get(wo0["releaseId"])
    quotes = platform.pilot.supplier_fixture(rel)
    assert len(quotes["quotes"]) >= 3
    assert quotes["staleOnReleaseChange"] is True
    ready = platform.pilot.readiness(evidence={"releasePackage": True, "pilotOps": True, "qc": True, "supplierQuotes": True, "carrierQuotes": True})
    assert ready["manufacturingReleasePackageReady"] is True
    assert ready["manualPilotOpsReady"] is True
    assert ready["qcTraceabilityReady"] is True
    assert ready["importedSupplierQuoteReady"] is True
    assert ready["importedCarrierQuoteReady"] is True
    assert ready["liveFactoryExecutionReady"] is False
    assert ready["liveProviderReady"] is False
    assert ready["globalProductionReady"] is False
    assert ready["fullAutonomousFactoryReady"] is False
    base = scoped_readiness()
    assert base["liveFactoryExecutionReady"] is False
    assert base["fullAutonomousFactoryReady"] is False


def _draft_wo(platform, *, tenant="cons", kind="OPEN_SHELF"):
    product = platform.kd.build_sku(tenant_id=tenant, kind=kind)
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    wo_svc = platform.pilot.workorders
    wo = wo_svc.create(tenant_id=tenant, release=rel, quantity=1, actor="tester")
    wo_svc.release_for_execution(wo["workOrderId"], actor="tester")
    return wo, rel, wo_svc


def test_lot_reserve_cancel_consume_conservation(platform):
    tenant = "cons"
    lots = platform.lots
    lot = lots.create(tenant_id=tenant, material="PB_18_WHITE", thickness=18, sheet_count=10)
    before = lots.quantities(lot["lotId"], tenant_id=tenant)
    assert before["available"] == 10
    assert before["conserved"] is True
    wo, _rel, wo_svc = _draft_wo(platform, tenant=tenant)
    reserved = wo_svc.reserve_materials(wo["workOrderId"], actor="tester", tenant_id=tenant)
    after_reserve = lots.quantities(lot["lotId"], tenant_id=tenant)
    assert after_reserve["available"] < before["available"]
    assert after_reserve["reserved"] > 0
    assert after_reserve["consumed"] == 0
    assert after_reserve["conserved"] is True
    reserved_qty = after_reserve["reserved"]
    wo_svc.reserve_materials(wo["workOrderId"], actor="tester", tenant_id=tenant)
    assert lots.quantities(lot["lotId"], tenant_id=tenant) == after_reserve
    cancelled = wo_svc.cancel(wo["workOrderId"], actor="tester")
    assert cancelled["state"] == "CANCELLED"
    restored = lots.quantities(lot["lotId"], tenant_id=tenant)
    assert restored["available"] == before["available"]
    assert restored["reserved"] == 0
    assert restored["consumed"] == 0
    wo2, _rel2, _ = _draft_wo(platform, tenant=tenant, kind="DESK_RISER")
    wo_svc.reserve_materials(wo2["workOrderId"], actor="tester", tenant_id=tenant)
    mid = lots.quantities(lot["lotId"], tenant_id=tenant)
    assert mid["reserved"] > 0
    wo_svc.consume_reserved(wo2["workOrderId"], actor="tester")
    after_consume = lots.quantities(lot["lotId"], tenant_id=tenant)
    assert after_consume["consumed"] == mid["reserved"]
    assert after_consume["reserved"] == 0
    assert after_consume["available"] == before["available"] - after_consume["consumed"]
    assert after_consume["conserved"] is True
    wo_svc.consume_reserved(wo2["workOrderId"], actor="tester")
    assert lots.quantities(lot["lotId"], tenant_id=tenant) == after_consume
    with pytest.raises(PermissionError):
        lots.reserve_sheets(lot["lotId"], tenant_id="other", work_order_id=wo2["workOrderId"], quantity=1)
    with pytest.raises(PermissionError):
        lots.consume_reservation(reserved["reservations"][0]["reservationId"], tenant_id="other", work_order_id=wo2["workOrderId"])
    assert lots.conservation_ok(tenant_id=tenant)["ok"] is True
    assert reserved_qty > 0


def test_no_double_consume_negative_regression(platform):
    row = platform.pilot.run_family_e2e(tenant_id="dbl", family="KD_FURNITURE", kind="OPEN_SHELF")
    assert platform.pilot.observe_no_double_consume(row["workOrderId"]) is True
    rec = platform.pilot.workorders.get(row["workOrderId"])
    lot_id = rec["lineage"]["materialLots"][0]
    lot = platform.lots.get(lot_id, tenant_id=rec["tenantId"])
    lot["remainingSheets"] = int(lot["remainingSheets"]) + 1
    lot["sheetCount"] = int(lot["sheetCount"]) + 1
    assert platform.lots.quantities(lot_id, tenant_id=rec["tenantId"])["conserved"] is True

    def bad_consume(work_order_id, *, actor):
        platform.lots.allocate_sheet(lot_id, tenant_id=rec["tenantId"])

    assert platform.pilot.observe_no_double_consume(row["workOrderId"], consume=bad_consume) is False


def test_qc_complete_cannot_bypass_required_final(platform):
    wo, _rel, wo_svc = _draft_wo(platform, tenant="qcbypass")
    wo_svc.reserve_materials(wo["workOrderId"], actor="qc", tenant_id="qcbypass")
    with pytest.raises(PermissionError):
        wo_svc.complete(wo["workOrderId"], actor="qc", qc_ok=True)
    assert wo_svc.get(wo["workOrderId"])["state"] == "QC_HOLD"
    qc = platform.pilot.qc
    qc.final(
        tenant_id="qcbypass",
        work_order_id=wo["workOrderId"],
        check_id="THICKNESS",
        measured=18.0,
        nominal=18.0,
        tol=0.5,
        unit="mm",
        operator="qc",
    )
    with pytest.raises(PermissionError):
        wo_svc.complete(wo["workOrderId"], actor="qc", qc_ok=True)
    fail = qc.final(
        tenant_id="qcbypass",
        work_order_id=wo["workOrderId"],
        check_id="PANEL_LENGTH",
        measured=50.0,
        nominal=400.0,
        tol=1.0,
        unit="mm",
        operator="qc",
    )
    assert fail["ok"] is False
    with pytest.raises(PermissionError):
        wo_svc.complete(wo["workOrderId"], actor="qc", qc_ok=True)
    qc.defect(tenant_id="qcbypass", work_order_id=wo["workOrderId"], code="DEF_SIZE", disposition="REWORK", actor="qc")
    qc.final(
        tenant_id="qcbypass",
        work_order_id=wo["workOrderId"],
        check_id="PANEL_LENGTH",
        measured=400.0,
        nominal=400.0,
        tol=1.0,
        unit="mm",
        operator="qc",
    )
    wo_svc.complete(wo["workOrderId"], actor="qc", qc_ok=True)
    assert wo_svc.get(wo["workOrderId"])["state"] == "COMPLETED"
    wo2, _rel2, _ = _draft_wo(platform, tenant="qcbypass", kind="DESK_RISER")
    for check_id, nominal in (("THICKNESS", 18.0), ("PANEL_LENGTH", 400.0)):
        qc.checks[f"x-{check_id}"] = {
            "qcId": f"x-{check_id}",
            "tenantId": "other-tenant",
            "workOrderId": wo2["workOrderId"],
            "stage": "FINAL",
            "checkId": check_id,
            "ok": True,
            "at": "2099-01-01T00:00:00+00:00",
        }
    with pytest.raises(PermissionError):
        wo_svc.complete(wo2["workOrderId"], actor="qc", qc_ok=True)
    with pytest.raises(PermissionError):
        qc.final(
            tenant_id="other-tenant",
            work_order_id=wo2["workOrderId"],
            check_id="THICKNESS",
            measured=18.0,
            nominal=18.0,
            tol=0.5,
            unit="mm",
            operator="qc",
        )


def test_readiness_defaults_unverified_without_evidence(platform):
    empty = platform.pilot.readiness()
    for key in (
        "manufacturingReleasePackageReady",
        "manualPilotOpsReady",
        "qcTraceabilityReady",
        "importedSupplierQuoteReady",
        "importedCarrierQuoteReady",
    ):
        assert empty[key] is False
        assert empty["labels"][key] == "UNVERIFIED"
    assert empty["liveFactoryExecutionReady"] is False
    assert empty["liveProviderReady"] is False
    assert empty["globalProductionReady"] is False
    assert empty["fullAutonomousFactoryReady"] is False
    only_release = platform.pilot.readiness(evidence={"releasePackage": True})
    assert only_release["manufacturingReleasePackageReady"] is True
    assert only_release["labels"]["manufacturingReleasePackageReady"] == "REAL"
    assert only_release["importedSupplierQuoteReady"] is False
    assert only_release["labels"]["importedSupplierQuoteReady"] == "UNVERIFIED"
    assert only_release["importedCarrierQuoteReady"] is False
