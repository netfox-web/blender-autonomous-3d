"""Tenant isolation, idempotency and persistence of the pilot QC API."""
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
    for _ in range(2):
        assert client.post(path + "/qc/release-hold", headers=HEADERS, json={"confirm": True}).json()["state"] == "IN_PROGRESS"
    _ops_and_pack(platform, wid, tenant=TENANT)
    response = client.post(path + "/complete", headers=HEADERS, json={"confirm": True})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "COMPLETED"
