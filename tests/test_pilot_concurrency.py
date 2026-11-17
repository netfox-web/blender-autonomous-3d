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
