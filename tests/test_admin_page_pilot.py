"""Pilot page and tenant-scoped API smoke tests."""
from fastapi.testclient import TestClient

from fox3d.api import create_app


def test_page_and_read_apis(platform):  # noqa: ANN001, ANN201
    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    page = client.get("/admin/pilot", headers=headers)
    assert page.status_code == 200
    assert "fox3d-shell.js" in page.text and "pilot.js" in page.text
    for path in ("/admin/pages/assets/pilot.js", "/admin/pages/assets/pilot.css", "/api/pilot/console", "/api/pilot/work-orders", "/api/pilot/batches", "/api/pilot/batches/board", "/api/pilot/health", "/api/pilot/export"):
        assert client.get(path, headers=headers).status_code == 200


def test_receipt_purchase_and_import(platform):  # noqa: ANN001, ANN201
    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    receipt = client.post("/api/pilot/receipts", headers=headers, json={"material": "TEST", "quantity": 2, "supplierLot": "lot-1", "source": "MANUAL"})
    assert receipt.status_code == 200 and receipt.json()["acceptedQty"] == 2
    purchase = client.post("/api/pilot/purchase-requests", headers=headers, json={"material": "TEST", "quantity": 2})
    assert purchase.status_code == 200 and purchase.json()["status"] == "WAITING_HUMAN_APPROVAL"
    imported = client.post("/api/pilot/import", headers=headers, json={"schemaVersion": "fox3d.receipt.v1", "rows": [{"material": "TEST", "quantity": 1, "supplierLot": "lot-2"}]})
    assert imported.status_code == 200
    console = client.get("/api/pilot/console", headers=headers).json()
    assert len(console["receipts"]) == 2 and len(console["purchaseRequests"]) == 1
    assert client.get("/api/pilot/console", headers={"X-Tenant-Id": "other"}).json()["receipts"] == []


def test_work_order_actions_require_confirmation_and_respect_tenant(platform):  # noqa: ANN001, ANN201
    fixture = platform.pilot.run_family_e2e(tenant_id="sonaqueen-home", family="KD_FURNITURE", kind="OPEN_SHELF")
    order = fixture["workOrderId"]
    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    for action in ("consume", "complete"):
        path = f"/api/pilot/work-orders/{order}/{action}"
        assert client.post(path, headers=headers, json={}).status_code == (403 if action == "consume" else 409)
    assert client.post(f"/api/pilot/work-orders/{order}/complete", headers=headers, json={"confirm": True}).status_code == 200
    assert client.post(f"/api/pilot/work-orders/{order}/complete", headers={"X-Tenant-Id": "other"}, json={"confirm": True}).status_code == 409
