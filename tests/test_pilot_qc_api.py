"""Tenant isolation, idempotency and persistence of the pilot QC API."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

from fastapi.testclient import TestClient

from fox3d.api import create_app
from test_pilot_packing_api import HEADERS, TENANT, _concurrent, _seed_release_receipt_and_wo
from test_pilot_ops import _ops_and_pack


def test_isolation_and_validation(platform: Any) -> None:
    client = TestClient(create_app(platform))
    _, wo = _seed_release_receipt_and_wo(platform)
    for wid, headers in [("missing", HEADERS), (wo["workOrderId"], {"X-Tenant-Id": "other"})]:
        for action in ("consume", "complete", "qc", "defects", "qc/release-hold"):
            response = client.post(f"/api/pilot/work-orders/{wid}/{action}", headers=headers, json={"confirm": True})
            assert response.status_code == 404
        assert client.get(f"/api/pilot/work-orders/{wid}/qc", headers=headers).status_code == 404
    path = f"/api/pilot/work-orders/{wo['workOrderId']}/qc"
    assert client.post(path, headers=HEADERS, json={"checkId": "INVALID", "idempotencyKey": "x"}).status_code == 422
    assert client.get('/api/pilot/work-orders?limit=101', headers=HEADERS).status_code == 422
    assert client.get('/api/pilot/work-orders', headers={"X-Tenant-Id": "other"}).json()['total'] == 0


def test_concurrent_qc_and_defect_reload(platform: Any) -> None:
    client = TestClient(create_app(platform))
    _, wo = _seed_release_receipt_and_wo(platform)
    path = f"/api/pilot/work-orders/{wo['workOrderId']}"
    body = {"stage": "FINAL", "checkId": "THICKNESS", "measured": 19, "source": "MANUAL", "idempotencyKey": "one"}
    responses = _concurrent(4, lambda: client.post(path + '/qc', headers=HEADERS, json=body))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()['qcId'] for r in responses}) == 1
    assert len(client.get(path + '/qc', headers=HEADERS).json()['checks']) == 1
    assert client.post(path + '/qc', headers=HEADERS, json={**body, 'measured': 18}).status_code == 409
    defect = {"code": "DEF_THICKNESS", "disposition": "REWORK", "idempotencyKey": "defect-one", "confirm": True}
    r = client.post(path + '/defects', headers=HEADERS, json=defect)
    assert r.status_code == 200
    assert client.post(path + '/defects', headers=HEADERS, json=defect).json() == r.json()
    platform.pilot.qc.load()
    platform.pilot.workorders.load()
    assert platform.pilot.workorders.get(wo['workOrderId'])['state'] == 'IN_PROGRESS'
    assert r.json()['defectId'] in platform.pilot.qc.defects
    from fox3d.journal import EventJournal

    journal = EventJournal(platform.pilot.journal.root)
    assert any(e['eventType'] == 'qc.defect' and e['aggregateId'] == r.json()['defectId'] for e in journal.list(TENANT))


def test_release_and_complete(platform: Any) -> None:
    client = TestClient(create_app(platform))
    _, wo = _seed_release_receipt_and_wo(platform)
    wid = wo["workOrderId"]
    path = f"/api/pilot/work-orders/{wid}"
    fail = {"stage": "FINAL", "checkId": "THICKNESS", "measured": 20, "source": "MANUAL", "idempotencyKey": "fail"}
    assert client.post(path + "/qc", headers=HEADERS, json=fail).json()["result"] == "FAIL"
    assert client.post(path + "/qc/release-hold", headers=HEADERS, json={"confirm": True}).status_code == 409
    for spec in wo["qcPlan"]:
        if spec["requiredFinal"]:
            nominal = spec["nominal"] if spec["nominal"] is not None else 100
            body = {"stage": "FINAL", "checkId": spec["checkId"], "measured": nominal, "nominal": nominal, "source": "MANUAL", "idempotencyKey": spec["checkId"]}
            assert client.post(path + "/qc", headers=HEADERS, json=body).status_code == 200
    optional = {"stage": "FINAL", "checkId": "HOLE_DIA", "measured": 20, "source": "MANUAL", "idempotencyKey": "optional-fail"}
    assert client.post(path + "/qc", headers=HEADERS, json=optional).json()["result"] == "FAIL"
    for _ in range(2):
        assert client.post(path + "/qc/release-hold", headers=HEADERS, json={"confirm": True}).json()["state"] == "IN_PROGRESS"
    _ops_and_pack(platform, wid, tenant=TENANT)
    response = client.post(path + "/complete", headers=HEADERS, json={"confirm": True})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "COMPLETED"


def test_qc_invalid_inputs_and_defect_conflict(platform: Any) -> None:
    client = TestClient(create_app(platform))
    _, wo = _seed_release_receipt_and_wo(platform)
    path = f"/api/pilot/work-orders/{wo['workOrderId']}"
    body = {"stage": "FINAL", "checkId": "THICKNESS", "measured": 18, "source": "MANUAL", "idempotencyKey": "key"}
    for changes in ({"stage": None}, {"source": "DEVICE"}, {"measured": True}, {"measured": "18"}, {"idempotencyKey": " "}):
        assert client.post(path + "/qc", headers=HEADERS, json={**body, **changes}).status_code == 422
    assert client.post(path + "/qc/release-hold", headers=HEADERS, json={"confirm": []}).status_code == 403
    assert client.post(path + "/defects", headers=HEADERS, json={"confirm": []}).status_code == 403
    defect = {"code": "DEF_THICKNESS", "disposition": "REWORK", "idempotencyKey": "defect", "confirm": True}
    responses = _concurrent(4, lambda: client.post(path + "/defects", headers=HEADERS, json=defect))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["defectId"] for r in responses}) == 1
    assert client.post(path + "/defects", headers=HEADERS, json={**defect, "code": "DEF_SIZE"}).status_code == 409
    page = client.get('/api/pilot/work-orders?offset=0&limit=1', headers=HEADERS).json()
    assert page['total'] == 1 and len(page['items']) == 1
    assert page['items'][0]['qcHold'] is False and page['items'][0]['qcOk'] is False
    assert client.get('/api/pilot/work-orders?offset=1&limit=1', headers=HEADERS).json()['items'] == []


def test_work_orders_without_pagination_returns_all(platform: Any) -> None:
    client = TestClient(create_app(platform))
    _, wo = _seed_release_receipt_and_wo(platform)
    product = platform.kd.build_sku(tenant_id=TENANT, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=TENANT, family="KD_FURNITURE")
    last_id = wo["workOrderId"]
    for i in range(101):
        created = platform.pilot.workorders.create(
            tenant_id=TENANT,
            release=rel,
            quantity=1,
            actor="ops",
            idempotency_key=f"legacy-list-{i}",
        )
        last_id = created["workOrderId"]
    legacy = client.get("/api/pilot/work-orders", headers=HEADERS)
    assert legacy.status_code == 200
    body = legacy.json()
    assert body["total"] >= 102
    assert len(body["items"]) == body["total"]
    assert any(item["workOrderId"] == last_id for item in body["items"])
    paged = client.get("/api/pilot/work-orders?offset=100&limit=100", headers=HEADERS)
    assert paged.status_code == 200
    page = paged.json()
    assert page["total"] >= 102
    assert len(page["items"]) >= 2
    assert any(item["workOrderId"] == last_id for item in page["items"])
    other = client.get("/api/pilot/work-orders", headers={"X-Tenant-Id": "other-tenant-list"}).json()
    assert other["total"] == 0
    assert other["items"] == []


def test_concurrent_qc_post_and_work_order_list(platform: Any) -> None:
    client = TestClient(create_app(platform))
    _, wo = _seed_release_receipt_and_wo(platform)
    path = f"/api/pilot/work-orders/{wo['workOrderId']}/qc"
    workers = 8
    barrier = Barrier(workers)

    def list_orders(_: int) -> None:
        barrier.wait()
        for _ in range(25):
            response = client.get("/api/pilot/work-orders", headers=HEADERS)
            assert response.status_code != 500, response.text

    def record_qc(thread_id: int) -> None:
        barrier.wait()
        for i in range(40):
            body = {
                "stage": "FINAL",
                "checkId": "THICKNESS",
                "measured": 17 + ((thread_id + i) % 5),
                "source": "MANUAL",
                "idempotencyKey": f"concurrent-{thread_id}-{i}",
            }
            client.post(path, headers=HEADERS, json=body)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        tasks = [pool.submit(list_orders, i) for i in range(4)] + [pool.submit(record_qc, i) for i in range(4)]
        for task in tasks:
            task.result()
