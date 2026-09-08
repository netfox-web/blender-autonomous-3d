"""Phase 361–420 reliability. MOCK/unit/FIXTURE — not Production Ready."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.inventory import MaterialLotRegistry, StockShortage
from fox3d.mfg_release import product_snapshot
from fox3d.qc import FAMILY_TOLERANCES, plan_hash
from fox3d.workorder import FIXTURE_AUTO_SEED, STRICT_STOCK


def test_strict_stock_no_phantom_lot(platform):
    wo, rel, wo_svc = _wo(platform, tenant="strict")
    wo_svc.release_for_execution(wo["workOrderId"], actor="ops")
    with pytest.raises(StockShortage) as exc:
        wo_svc.reserve_materials(wo["workOrderId"], actor="ops", tenant_id="strict", allocation_policy=STRICT_STOCK)
    assert exc.value.payload["code"] == "SHORTAGE"
    assert not wo_svc.lots.list(tenant_id="strict")
    pr = platform.pilot.receiving.draft_purchase_request(
        tenant_id="strict", material="PB_18_WHITE", quantity=2, actor="ops", shortage=exc.value.payload
    )
    assert pr["sent"] is False and pr["payment"] is False
    assert pr["status"] == "WAITING_HUMAN_APPROVAL"


def test_fixture_auto_seed_labeled(platform):
    wo, _rel, wo_svc = _wo(platform, tenant="fix")
    wo_svc.release_for_execution(wo["workOrderId"], actor="ops")
    reserved = wo_svc.reserve_materials(wo["workOrderId"], actor="ops", tenant_id="fix", allocation_policy=FIXTURE_AUTO_SEED)
    assert reserved["allocationPolicy"] == FIXTURE_AUTO_SEED
    assert reserved["truthLabel"] == "FIXTURE"
    assert any(i.get("truthLabel") == "FIXTURE" for i in reserved["reservations"] if i.get("kind") == "lot")


def test_concurrent_reserve_no_oversell(tmp_path):
    lots = MaterialLotRegistry(tmp_path / "lots")
    lot = lots.create(tenant_id="t", material="PB_18_WHITE", thickness=18, sheet_count=1)
    wins = []

    def _go(i: int) -> None:
        try:
            lots.reserve_sheets(lot["lotId"], tenant_id="t", work_order_id=f"w{i}", quantity=1)
            wins.append(i)
        except (StockShortage, PermissionError):
            pass

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(as_completed([pool.submit(_go, i) for i in range(40)]))
    assert len(wins) == 1
    q = lots.quantities(lot["lotId"], tenant_id="t")
    assert q["available"] == 0 and q["reserved"] == 1 and q["consumed"] == 0 and q["conserved"]


def test_lot_restart_and_idempotent_reserve(tmp_path):
    root = tmp_path / "lots"
    lots = MaterialLotRegistry(root)
    lot = lots.create(tenant_id="t", material="PB_18_WHITE", thickness=18, sheet_count=5)
    first = lots.reserve_sheets(lot["lotId"], tenant_id="t", work_order_id="wo1", quantity=2)
    again = lots.reserve_sheets(lot["lotId"], tenant_id="t", work_order_id="wo1", quantity=2)
    assert again["reservationId"] == first["reservationId"]
    q = lots.quantities(lot["lotId"], tenant_id="t")
    assert q["available"] == 3 and q["reserved"] == 2
    lots2 = MaterialLotRegistry(root)
    q2 = lots2.quantities(lot["lotId"], tenant_id="t")
    assert q2 == q
    item = (lots2.get(lot["lotId"], tenant_id="t")["reservations"] or {})[first["reservationId"]]
    assert item["workOrderId"] == "wo1" and item["state"] == "RESERVED"


def test_partial_consume_then_cancel(platform):
    rec = platform.pilot.receiving.import_receipt(
        {"supplierLot": "P1", "material": "PB_18_WHITE", "quantity": 6, "thickness": 18},
        tenant_id="part",
        actor="recv",
        source="MANUAL",
        idempotency_key="part:P1",
    )
    wo, _rel, wo_svc = _wo(platform, tenant="part")
    wo_svc.release_for_execution(wo["workOrderId"], actor="ops")
    reserved = wo_svc.reserve_materials(wo["workOrderId"], actor="ops", tenant_id="part", allocation_policy=STRICT_STOCK)
    lot_items = [i for i in reserved["reservations"] if i.get("kind") == "lot"]
    wo_svc.consume_one(wo["workOrderId"], lot_items[0]["reservationId"], actor="ops")
    before = wo_svc.lots.quantities(rec["lotId"], tenant_id="part")
    wo_svc.cancel(wo["workOrderId"], actor="ops")
    after = wo_svc.lots.quantities(rec["lotId"], tenant_id="part")
    assert after["consumed"] == before["consumed"]
    assert after["reserved"] == 0
    assert after["conserved"] is True


def test_workorder_illegal_transitions(platform):
    wo, rel, wo_svc = _wo(platform, tenant="sm")
    with pytest.raises(PermissionError):
        wo_svc.start_operation(wo["workOrderId"], "panel_cutting", actor="ops")
    wo_svc.release_for_execution(wo["workOrderId"], actor="ops")
    with pytest.raises(PermissionError):
        wo_svc.start_operation(wo["workOrderId"], "panel_cutting", actor="ops")
    platform.pilot.receiving.import_receipt(
        {"supplierLot": "SM", "material": "PB_18_WHITE", "quantity": 8, "thickness": 18},
        tenant_id="sm",
        actor="recv",
        source="MANUAL",
        idempotency_key="sm:SM",
    )
    wo_svc.reserve_materials(wo["workOrderId"], actor="ops", tenant_id="sm", allocation_policy=STRICT_STOCK)
    op = wo_svc.start_operation(wo["workOrderId"], "panel_cutting", actor="ops")
    with pytest.raises(PermissionError):
        wo_svc.complete(wo["workOrderId"], actor="ops")
    wo_svc.complete_operation(wo["workOrderId"], op["opId"], actor="ops")
    for step in wo_svc.get(wo["workOrderId"])["traveler"]["steps"][1:]:
        o = wo_svc.start_operation(wo["workOrderId"], step["operation"], actor="ops")
        wo_svc.complete_operation(wo["workOrderId"], o["opId"], actor="ops")
    with pytest.raises(PermissionError):
        wo_svc.complete(wo["workOrderId"], actor="ops")
    mutated = dict(rel["snapshot"])
    mutated["engineeringHash"] = "ff" * 32
    platform.pilot.releases.refresh_stale(rel["releaseId"], mutated)
    with pytest.raises(PermissionError):
        wo_svc.create(tenant_id="sm", release=platform.pilot.releases.get(rel["releaseId"]), quantity=1, actor="ops", batch_id="stale")
    done = wo_svc.get(wo["workOrderId"])
    for spec in platform.pilot.qc.schema(done["productFamily"]):
        nominal = float(spec["nominal"] if spec["nominal"] is not None else 100)
        platform.pilot.qc.record(
            tenant_id="sm",
            work_order_id=wo["workOrderId"],
            stage="FINAL" if spec.get("requiredFinal") else "IN_PROCESS",
            check_id=spec["checkId"],
            measured=nominal,
            nominal=nominal,
            tol=float(spec["tol"]),
            unit=spec["unit"],
            operator="ops",
            required_final=bool(spec.get("requiredFinal")),
            source="TEST_DATA",
        )
    cartons = platform.pilot.logistics.instantiate_cartons(
        tenant_id="sm",
        work_order_id=wo["workOrderId"],
        batch_id=done["batchId"],
        plan={"length": 1, "width": 1, "height": 1},
        quantity=1,
        contents=[{"sku": "product", "qty": 1}],
    )
    wo_svc.set_packing(wo["workOrderId"], [c["cartonId"] for c in cartons])
    wo_svc.complete(wo["workOrderId"], actor="ops")
    with pytest.raises(PermissionError):
        wo_svc.cancel(wo["workOrderId"], actor="ops")
    with pytest.raises(PermissionError):
        wo_svc._require(wo["workOrderId"], tenant_id="other")


def test_qc_plan_pinned_against_schema_change(platform):
    wo, rel, wo_svc = _wo(platform, tenant="pin")
    pinned = wo["qcPlanHash"]
    assert pinned == rel.get("qcPlanHash") or pinned == plan_hash(wo["qcPlan"])
    original = list(FAMILY_TOLERANCES["KD_FURNITURE"])
    FAMILY_TOLERANCES["KD_FURNITURE"] = original + [{"checkId": "NEW_CHECK", "nominal": 1.0, "tol": 0, "unit": "x", "requiredFinal": True}]
    try:
        gate = wo_svc._authoritative_qc_gate(wo_svc.get(wo["workOrderId"]))
        assert "NEW_CHECK" not in gate["required"]
        assert "THICKNESS" in gate["required"]
    finally:
        FAMILY_TOLERANCES["KD_FURNITURE"] = original


def test_release_supersede_and_approval_scope(platform):
    product = platform.kd.build_sku(tenant_id="sup", kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id="sup", family="KD_FURNITURE")
    snap2 = product_snapshot(platform.kd.build_sku(tenant_id="sup", kind="BEDSIDE_CABINET"), family="KD_FURNITURE")
    out = platform.pilot.releases.supersede(rel["releaseId"], snap2, actor="eng", tenant_id="sup")
    assert out["old"]["status"] == "SUPERSEDED"
    assert out["diff"]["changed"]
    with pytest.raises(PermissionError):
        platform.pilot.workorders.create(tenant_id="sup", release=out["old"], quantity=1, actor="ops")
    platform.pilot.releases.tamper(rel["releaseId"], "bom.csv", "hacked")
    assert platform.pilot.releases.verify(rel["releaseId"])["ok"] is False
    waiting = platform.pilot.releases.create(snap2, tenant_id="sup", created_by="eng", idempotency_key="sup:wait")
    platform.pilot.releases.validate(waiting["releaseId"])
    platform.pilot.releases.submit_approval(waiting["releaseId"], actor="eng")
    with pytest.raises(PermissionError):
        platform.pilot.releases.approve(waiting["releaseId"], actor="human", expected_release_hash="not-this-hash")


def test_receipt_idempotent_and_quarantine(platform):
    a = platform.pilot.receiving.import_receipt(
        {"supplierLot": "R1", "material": "PB_18_WHITE", "quantity": 3, "thickness": 18},
        tenant_id="recv",
        actor="ops",
        source="IMPORTED",
        idempotency_key="recv:R1",
    )
    b = platform.pilot.receiving.import_receipt(
        {"supplierLot": "R1", "material": "PB_18_WHITE", "quantity": 3, "thickness": 18},
        tenant_id="recv",
        actor="ops",
        source="IMPORTED",
        idempotency_key="recv:R1",
    )
    assert a["receiptId"] == b["receiptId"]
    q = platform.lots.quantities(a["lotId"], tenant_id="recv")
    assert q["available"] == 3
    bad = platform.pilot.receiving.import_receipt(
        {"supplierLot": "R2", "material": "PB_18_WHITE", "quantity": 2, "thickness": 18, "expectedMaterial": "OAK"},
        tenant_id="recv",
        actor="ops",
        source="IMPORTED",
        idempotency_key="recv:R2",
    )
    assert bad["quarantined"] is True
    with pytest.raises(PermissionError):
        platform.lots.reserve_sheets(bad["lotId"], tenant_id="recv", work_order_id="x", quantity=1)


def test_shipment_draft_not_booked(platform):
    log = platform.pilot.logistics
    cartons = log.instantiate_cartons(
        tenant_id="sh",
        work_order_id="wo",
        batch_id="b",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=2,
        contents=[{"sku": "product", "qty": 1}],
        release_hash="rh",
    )
    assert log.pack_completeness(work_order_id="wo", expected_qty=2)["ok"] is True
    assert log.pack_completeness(work_order_id="wo", expected_qty=1)["code"] == "duplicate"
    assert log.pack_completeness(work_order_id="wo", expected_qty=9)["code"] == "shortage"
    expected = dict(cartons[0]["expected"])
    log.record_measured(cartons[0]["cartonId"], length=1, width=1, height=1, weight_kg=1, source="MANUAL")
    assert cartons[0]["expected"] == expected
    ship = log.shipment_draft(origin="TW", destination="TPE", carton_ids=[c["cartonId"] for c in cartons])
    assert ship["submittedToCarrier"] is False
    assert ship["booked"] is False
    assert ship["shipped"] is False
    again = log.shipment_draft(origin="TW", destination="TPE", carton_ids=[c["cartonId"] for c in cartons])
    assert again["shipmentId"] == ship["shipmentId"]


def test_api_pilot_console_and_fixture_blocked(platform):
    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "api1"}
    assert client.get("/api/pilot/console").status_code == 400
    ok = client.get("/api/pilot/console", headers=headers)
    assert ok.status_code == 200
    assert ok.json()["liveCnc"] is False
    assert ok.json()["badges"]["LIVE_CNC"] == "BLOCKED"
    blocked = client.post(
        "/api/pilot/work-orders/nope/reserve",
        json={"allocationPolicy": "FIXTURE_AUTO_SEED"},
        headers=headers,
    )
    assert blocked.status_code == 403
    admin = client.get("/admin")
    assert "Pilot Reliability" in admin.text
    assert "LIVE_CNC" in admin.text


def test_reliability_fixture_stress(platform):
    result = platform.pilot.reliability.run(tenant_id="stress50", n_orders=50)
    assert result["label"] == "FIXTURE"
    assert result["workOrderCount"] >= 50
    assert result["operationTransitions"] >= 250
    assert result["receiptIdempotent"] is True
    assert result["quarantineBlocked"] is True
    assert result["noOversell"] is True
    assert result["materialConserved"] is True
    assert "op-before-reserve-failed" in result["negatives"]
    assert "complete-open-ops-failed" in result["negatives"]
    assert "stale-wo-failed" in result["negatives"]
    assert result["packMismatchFails"] is True
    assert result["shipmentDraft"] is True
    assert result["liveFactoryExecutionReady"] is False


def _wo(platform, *, tenant, kind="OPEN_SHELF"):
    product = platform.kd.build_sku(tenant_id=tenant, kind=kind)
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    return wo, rel, platform.pilot.workorders
