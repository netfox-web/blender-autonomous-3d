from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.inventory import MaterialLotRegistry
from fox3d.workorder import WorkOrderService


def concurrent(count, fn):
    barrier = Barrier(count)

    def run(_):
        barrier.wait()
        return fn()

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def workorder(platform):
    pilot = platform.pilot
    product = platform.kd.build_sku(tenant_id="alpha", kind="OPEN_SHELF")
    release = pilot.open_release(product, tenant_id="alpha", family="KD_FURNITURE")
    wo = pilot.workorders.create(tenant_id="alpha", release=release, actor="test")
    pilot.workorders.release_for_execution(wo["workOrderId"], actor="test")
    pilot.workorders.reserve_materials(wo["workOrderId"], actor="test", tenant_id="alpha", allocation_policy="FIXTURE_AUTO_SEED")
    return wo


def test_receipt_concurrent_and_tenant(platform):
    client = TestClient(create_app(platform))
    body = {"material": "PB_18_WHITE", "quantity": 5, "idempotencyKey": "same"}
    responses = concurrent(6, lambda: client.post("/api/pilot/receipts", headers={"X-Tenant-Id": "alpha"}, json=body))
    assert [r.status_code for r in responses] == [200] * 6
    assert len({r.json()["receiptId"] for r in responses}) == 1
    assert len(platform.lots.list(tenant_id="alpha")) == 1
    other = client.post("/api/pilot/receipts", headers={"X-Tenant-Id": "beta"}, json=body)
    assert other.status_code == 200
    assert other.json()["receiptId"] != responses[0].json()["receiptId"]


def test_receipt_emit_failure_removes_lot(platform, monkeypatch):
    import fox3d.receipt as receipt

    def fail(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(receipt, "emit", fail)
    with pytest.raises(RuntimeError):
        platform.pilot.receiving.import_receipt({"quantity": 5}, tenant_id="alpha", actor="test", idempotency_key="fail")
    assert platform.lots.list(tenant_id="alpha") == []
    assert MaterialLotRegistry(platform.lots.root).list(tenant_id="alpha") == []
    assert not platform.pilot.receiving.receipts


def test_dispatch_complete_and_cancel(platform):
    client = TestClient(create_app(platform))
    wo = workorder(platform)
    station = platform.pilot.stations.register(tenant_id="alpha", capabilities=["PANEL_CUTTING_MANUAL"], actor="test")
    body = {"workOrderId": wo["workOrderId"], "stationId": station["stationId"], "operation": "panel_cutting"}
    headers = {"X-Tenant-Id": "alpha"}
    assert client.post("/api/pilot/dispatch", headers=headers, json={**body, "workOrderId": "missing"}).status_code == 404
    assert client.post("/api/pilot/dispatch", headers=headers, json={**body, "stationId": "missing"}).status_code == 404
    foreign = platform.pilot.stations.register(tenant_id="beta", capabilities=["PANEL_CUTTING_MANUAL"], actor="test")
    assert client.post("/api/pilot/dispatch", headers=headers, json={**body, "stationId": foreign["stationId"]}).status_code in (403, 404)
    assert client.post("/api/pilot/dispatch", headers={"X-Tenant-Id": "beta"}, json=body).status_code in (403, 404)
    assert client.post("/api/pilot/dispatch", headers=headers, json={**body, "operation": "invalid"}).status_code == 422
    lease = client.post("/api/pilot/dispatch", headers=headers, json=body).json()
    assert client.post("/api/pilot/dispatch", headers=headers, json=body).json()["leaseId"] == lease["leaseId"]
    responses = concurrent(5, lambda: client.post(f"/api/pilot/leases/{lease['leaseId']}/complete", headers=headers, json={"confirm": True}))
    assert [r.status_code for r in responses] == [200] * 5
    assert len([op for op in wo["ops"] if op["status"] == "COMPLETED"]) == 1
    wo2 = workorder(platform)
    lease2 = client.post("/api/pilot/dispatch", headers=headers, json={**body, "workOrderId": wo2["workOrderId"]}).json()
    platform.pilot.workorders.cancel(wo2["workOrderId"], actor="test")
    assert platform.pilot.dispatcher.leases[lease2["leaseId"]]["status"] == "CANCELLED"
    assert platform.queue.get(lease2["jobId"])["status"] == "cancelled"
    assert any(item["errorCode"] == "WORKORDER_CANCELLED" for item in platform.pilot.inbox.list(tenant_id="alpha"))
    wo3 = workorder(platform)
    assert client.post("/api/pilot/dispatch", headers=headers, json={**body, "workOrderId": wo3["workOrderId"]}).status_code == 200


def test_reject_audit_and_terminal_restart(platform):
    wo = workorder(platform)
    svc = platform.pilot.workorders
    svc.reject(wo["workOrderId"], actor="test", reason="defect")
    assert wo["audit"][-1]["to"] == "REJECTED"
    assert any(e["eventType"] == "workorder.reject" for e in platform.pilot.journal.list("alpha"))
    assert WorkOrderService(root=svc.root).get(wo["workOrderId"])["state"] == "REJECTED"
    wo2 = workorder(platform)
    wo2["state"] = "COMPLETED"
    svc.persist()
    client = TestClient(create_app(platform))
    path = f"/api/pilot/workorders/{wo2['workOrderId']}/reject"
    assert client.post(path, headers={"X-Tenant-Id": "beta"}, json={"reason": "late"}).status_code in (403, 404)
    assert client.post(path, headers={"X-Tenant-Id": "alpha"}, json={"reason": "late"}).status_code == 409
    assert WorkOrderService(root=svc.root).get(wo2["workOrderId"])["state"] == "COMPLETED"


def test_other_idempotent_creates_concurrent(platform):
    pilot = platform.pilot
    snap = {"productId": "p", "productVersion": 1, "productFamily": "KD_FURNITURE"}
    releases = concurrent(5, lambda: pilot.releases.create(snap, tenant_id="alpha", created_by="test", idempotency_key="release"))
    assert len({r["releaseId"] for r in releases}) == 1
    lot = platform.lots.create(tenant_id="alpha", material="PB_18_WHITE", thickness=18, sheet_count=5)
    counts = concurrent(5, lambda: pilot.cyclecounts.create(tenant_id="alpha", lot_id=lot["lotId"], counted=5, reason="count", actor="test", idempotency_key="count"))
    assert len({r["cycleCountId"] for r in counts}) == 1
    payload = {"schemaVersion": "fox3d.receipt.v1", "rows": [{"material": "PB_18_WHITE", "quantity": 3}]}
    bundles = concurrent(5, lambda: pilot.contracts.import_bundle(payload, tenant_id="alpha", actor="test", idempotency_key="bundle"))
    assert len({r["importId"] for r in bundles}) == 1
    assert len(platform.lots.list(tenant_id="alpha")) == 2


def test_receipt_semantic_conflict_is_409(platform, monkeypatch):
    from fox3d.journal import SemanticKeyConflictError
    import fox3d.receipt as receipt

    def conflict(*args, **kwargs):
        raise SemanticKeyConflictError("private detail")

    monkeypatch.setattr(receipt, "emit", conflict)
    response = TestClient(create_app(platform)).post(
        "/api/pilot/receipts", headers={"X-Tenant-Id": "alpha"}, json={"quantity": 5}
    )
    assert response.status_code == 409
    assert "private detail" not in response.text
    assert platform.lots.list(tenant_id="alpha") == []


def _lot_reservation(wo):
    return next(item for item in wo["reservations"] if item.get("kind") == "lot")


def _assert_unconsumed_released(platform, wo):
    assert wo["materialReserved"] is False
    for item in wo["reservations"]:
        if item.get("kind") != "lot" or item.get("state") == "CONSUMED":
            continue
        assert item["state"] == "RELEASED"
        lot = platform.lots.get(item["lotId"], tenant_id=wo["tenantId"])
        assert lot["reservations"][item["reservationId"]]["state"] == "RELEASED"
        assert int(lot["reservedSheets"]) == 0


def _race(first, second):
    barrier = Barrier(2)

    def run(fn):
        barrier.wait()
        return fn()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(run, (first, second)))


@pytest.mark.parametrize("phase", ["LEASED", "ACKED", "STARTED"])
def test_reject_active_lease_states(platform, phase):
    wo = workorder(platform)
    dispatcher = platform.pilot.dispatcher
    station = platform.pilot.stations.register(tenant_id="alpha", capabilities=["PANEL_CUTTING_MANUAL"], actor="test")
    lease = dispatcher.dispatch(
        tenant_id="alpha", work_order_id=wo["workOrderId"], operation="panel_cutting", station_id=station["stationId"]
    )
    if phase == "ACKED":
        dispatcher.ack(lease["leaseId"], tenant_id="alpha", actor="test")
    elif phase == "STARTED":
        dispatcher.start(lease["leaseId"], tenant_id="alpha", actor="test")
    held = _lot_reservation(wo)
    before = platform.lots.get(held["lotId"], tenant_id="alpha")
    remaining_before = int(before["remainingSheets"])
    platform.pilot.workorders.reject(wo["workOrderId"], actor="test", reason="defect")
    assert wo["state"] == "REJECTED"
    assert lease["status"] == "CANCELLED"
    assert station["currentLease"] is None
    assert platform.queue.get(lease["jobId"])["status"] == "cancelled"
    _assert_unconsumed_released(platform, wo)
    after = platform.lots.get(held["lotId"], tenant_id="alpha")
    assert int(after["remainingSheets"]) == remaining_before + int(held["quantity"])
    reloaded = MaterialLotRegistry(platform.lots.root)
    assert reloaded.get(held["lotId"], tenant_id="alpha")["reservations"][held["reservationId"]]["state"] == "RELEASED"
    assert WorkOrderService(root=platform.pilot.workorders.root).get(wo["workOrderId"])["state"] == "REJECTED"
    with pytest.raises(PermissionError):
        dispatcher.complete(lease["leaseId"], tenant_id="alpha", actor="test")
    if phase == "STARTED":
        with pytest.raises(PermissionError):
            platform.pilot.workorders.complete_operation(wo["workOrderId"], lease["opId"], actor="test")
    nxt = workorder(platform)
    again = dispatcher.dispatch(
        tenant_id="alpha", work_order_id=nxt["workOrderId"], operation="panel_cutting", station_id=station["stationId"]
    )
    assert again["status"] == "LEASED"
    assert station["currentLease"] == again["leaseId"]


def test_reject_keeps_consumed_reservation(platform):
    wo = workorder(platform)
    held = _lot_reservation(wo)
    platform.pilot.workorders.consume_one(wo["workOrderId"], held["reservationId"], actor="test")
    before = platform.lots.get(held["lotId"], tenant_id="alpha")
    remaining_before = int(before["remainingSheets"])
    consumed_before = int(before["consumedSheets"])
    platform.pilot.workorders.reject(wo["workOrderId"], actor="test", reason="after-consume")
    assert held["state"] == "CONSUMED"
    lot = platform.lots.get(held["lotId"], tenant_id="alpha")
    assert lot["reservations"][held["reservationId"]]["state"] == "CONSUMED"
    assert int(lot["remainingSheets"]) == remaining_before
    assert int(lot["consumedSheets"]) == consumed_before
    assert wo["state"] == "REJECTED"


def test_reject_twice_releases_once(platform):
    wo = workorder(platform)
    held = _lot_reservation(wo)
    before = int(platform.lots.get(held["lotId"], tenant_id="alpha")["remainingSheets"])
    svc = platform.pilot.workorders

    def attempt():
        try:
            svc.reject(wo["workOrderId"], actor="test", reason="once")
            return "ok"
        except PermissionError:
            return "denied"

    assert sorted(concurrent(2, attempt)) == ["denied", "ok"]
    lot = platform.lots.get(held["lotId"], tenant_id="alpha")
    assert int(lot["remainingSheets"]) == before + int(held["quantity"])
    assert lot["reservations"][held["reservationId"]]["state"] == "RELEASED"
    assert wo["state"] == "REJECTED"


def test_reject_dispatch_race_leaves_no_active_lease(platform):
    wo = workorder(platform)
    dispatcher = platform.pilot.dispatcher
    station = platform.pilot.stations.register(tenant_id="alpha", capabilities=["PANEL_CUTTING_MANUAL"], actor="test")

    def do_dispatch():
        try:
            dispatcher.dispatch(
                tenant_id="alpha",
                work_order_id=wo["workOrderId"],
                operation="panel_cutting",
                station_id=station["stationId"],
            )
            return "dispatched"
        except PermissionError:
            return "refused"

    def do_reject():
        platform.pilot.workorders.reject(wo["workOrderId"], actor="test", reason="race")
        return "rejected"

    assert "rejected" in _race(do_dispatch, do_reject)
    assert wo["state"] == "REJECTED"
    active = [
        lease
        for lease in dispatcher.leases.values()
        if lease.get("workOrderId") == wo["workOrderId"] and lease.get("status") in {"LEASED", "ACKED", "STARTED"}
    ]
    assert active == []
    assert station["currentLease"] is None
    _assert_unconsumed_released(platform, wo)


def test_reject_complete_race(platform):
    wo = workorder(platform)
    dispatcher = platform.pilot.dispatcher
    station = platform.pilot.stations.register(tenant_id="alpha", capabilities=["PANEL_CUTTING_MANUAL"], actor="test")
    lease = dispatcher.dispatch(
        tenant_id="alpha", work_order_id=wo["workOrderId"], operation="panel_cutting", station_id=station["stationId"]
    )

    def do_complete():
        try:
            dispatcher.complete(lease["leaseId"], tenant_id="alpha", actor="test")
            return "completed"
        except PermissionError:
            return "refused"

    def do_reject():
        platform.pilot.workorders.reject(wo["workOrderId"], actor="test", reason="race")
        return "rejected"

    results = _race(do_complete, do_reject)
    assert "rejected" in results
    assert wo["state"] == "REJECTED"
    assert lease["status"] in {"CANCELLED", "COMPLETED"}
    assert station["currentLease"] is None
    _assert_unconsumed_released(platform, wo)
    if "completed" in results:
        assert lease["status"] == "COMPLETED"
        again = dispatcher.complete(lease["leaseId"], tenant_id="alpha", actor="test")
        assert again["status"] == "COMPLETED"
    else:
        assert lease["status"] == "CANCELLED"
        with pytest.raises(PermissionError):
            dispatcher.complete(lease["leaseId"], tenant_id="alpha", actor="test")


def test_reject_route_cancels_lease(platform):
    client = TestClient(create_app(platform))
    wo = workorder(platform)
    station = platform.pilot.stations.register(tenant_id="alpha", capabilities=["PANEL_CUTTING_MANUAL"], actor="test")
    headers = {"X-Tenant-Id": "alpha"}
    body = {"workOrderId": wo["workOrderId"], "stationId": station["stationId"], "operation": "panel_cutting"}
    lease = client.post("/api/pilot/dispatch", headers=headers, json=body).json()
    rejected = client.post(
        f"/api/pilot/workorders/{wo['workOrderId']}/reject", headers=headers, json={"reason": "defect", "actor": "qa"}
    )
    assert rejected.status_code == 200
    assert rejected.json()["state"] == "REJECTED"
    assert platform.pilot.dispatcher.leases[lease["leaseId"]]["status"] == "CANCELLED"
    assert station["currentLease"] is None
    done = client.post(f"/api/pilot/leases/{lease['leaseId']}/complete", headers=headers, json={"confirm": True})
    assert done.status_code == 403
    _assert_unconsumed_released(platform, wo)


def test_receipt_prepare_failure_rolls_back_and_retry_succeeds(platform):
    from fox3d.journal import JournalCommitError

    platform.pilot.outbox._fail_prepare = True
    with pytest.raises(JournalCommitError):
        platform.pilot.receiving.import_receipt(
            {"quantity": 3}, tenant_id="alpha", actor="test", source="IMPORTED", idempotency_key="prep"
        )
    assert platform.lots.list(tenant_id="alpha") == []
    assert platform.pilot.receiving.receipts == {}
    assert platform.pilot.outbox.list_open(tenant_id="alpha") == []
    rec = platform.pilot.receiving.import_receipt(
        {"quantity": 3}, tenant_id="alpha", actor="test", source="IMPORTED", idempotency_key="prep"
    )
    assert rec["status"] == "ACCEPTED"
    assert rec["lotId"]
    assert len(platform.lots.list(tenant_id="alpha")) == 1


def test_receipt_journal_failure_keeps_snapshot_for_restart(platform, monkeypatch):
    from fox3d.journal import JournalCommitError
    from fox3d.platform import Platform

    def fail_append(*_args, **_kwargs):
        raise JournalCommitError("injected journal failure")

    monkeypatch.setattr(platform.pilot.journal, "append", fail_append)
    saved = platform.pilot.receiving.import_receipt(
        {"quantity": 4}, tenant_id="alpha", actor="recv", source="IMPORTED", idempotency_key="journal-fail"
    )
    assert saved["lotId"]
    assert len(platform.lots.list(tenant_id="alpha")) == 1
    assert platform.pilot.receiving.receipts[saved["receiptId"]]["lotId"] == saved["lotId"]
    assert not any(event.get("eventType") == "receipt.accepted" for event in platform.pilot.journal.list("alpha"))
    assert any(
        tx.get("semanticKey") == "alpha::journal-fail" for tx in platform.pilot.outbox.list_open(tenant_id="alpha")
    )
    restarted = Platform(root=platform.root, mock_blender=True)
    resent = restarted.pilot.receiving.import_receipt(
        {"quantity": 4}, tenant_id="alpha", actor="recv", source="IMPORTED", idempotency_key="journal-fail"
    )
    assert resent["receiptId"] == saved["receiptId"]
    assert resent["lotId"] == saved["lotId"]
    assert len(restarted.lots.list(tenant_id="alpha")) == 1
    events = [
        event
        for event in restarted.pilot.journal.list("alpha")
        if event.get("semanticKey") == "alpha::journal-fail"
    ]
    assert len(events) == 1
    assert events[0]["payload"]["lotId"] == saved["lotId"]
    assert restarted.pilot.journal.verify("alpha")["ok"] is True


def test_receipt_outbox_complete_failure_keeps_lot_and_restart_resends(platform, monkeypatch):
    from fox3d.platform import Platform

    def always_fail(_tx_id):
        raise RuntimeError("injected outbox complete failure")

    monkeypatch.setattr(platform.pilot.outbox, "complete", always_fail)
    row = {"material": "PB_18_WHITE", "quantity": 4}
    rec = platform.pilot.receiving.import_receipt(
        row, tenant_id="alpha", actor="recv", source="IMPORTED", idempotency_key="recv-1"
    )
    assert platform.lots.get(rec["lotId"], tenant_id="alpha")["sheetCount"] == 4
    events = [event for event in platform.pilot.journal.list("alpha") if event.get("semanticKey") == "alpha::recv-1"]
    assert len(events) == 1
    assert events[0]["payload"]["lotId"] == rec["lotId"]
    again = platform.pilot.receiving.import_receipt(
        row, tenant_id="alpha", actor="recv", source="IMPORTED", idempotency_key="recv-1"
    )
    assert again["receiptId"] == rec["receiptId"]
    assert again["lotId"] == rec["lotId"]
    assert len(platform.lots.list(tenant_id="alpha")) == 1
    assert any(tx.get("semanticKey") == "alpha::recv-1" for tx in platform.pilot.outbox.list_open(tenant_id="alpha"))
    restarted = Platform(root=platform.root, mock_blender=True)
    resent = restarted.pilot.receiving.import_receipt(
        row, tenant_id="alpha", actor="recv", source="IMPORTED", idempotency_key="recv-1"
    )
    assert resent["receiptId"] == rec["receiptId"]
    assert resent["lotId"] == rec["lotId"]
    assert len(restarted.lots.list(tenant_id="alpha")) == 1
    journal_events = [
        event for event in restarted.pilot.journal.list("alpha") if event.get("semanticKey") == "alpha::recv-1"
    ]
    assert len(journal_events) == 1
    assert journal_events[0]["payload"]["lotId"] == rec["lotId"]
    assert restarted.pilot.journal.verify("alpha")["ok"] is True
    assert restarted.pilot.outbox.list_open(tenant_id="alpha") == []


@pytest.mark.parametrize("phase", ["LEASED", "ACKED", "STARTED"])
def test_cancel_active_lease_states(platform, phase):
    wo = workorder(platform)
    dispatcher = platform.pilot.dispatcher
    station = platform.pilot.stations.register(tenant_id="alpha", capabilities=["PANEL_CUTTING_MANUAL"], actor="test")
    lease = dispatcher.dispatch(tenant_id="alpha", work_order_id=wo["workOrderId"], operation="panel_cutting", station_id=station["stationId"])
    if phase == "ACKED":
        dispatcher.ack(lease["leaseId"], tenant_id="alpha", actor="test")
    elif phase == "STARTED":
        dispatcher.start(lease["leaseId"], tenant_id="alpha", actor="test")
    platform.pilot.workorders.cancel(wo["workOrderId"], actor="test")
    assert lease["status"] == "CANCELLED"
    assert station["currentLease"] is None
    with pytest.raises(PermissionError):
        dispatcher.complete(lease["leaseId"], tenant_id="alpha", actor="test")
