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


def test_pilot_js_snapshots_tenant_and_locks_confirm() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/pilot.js").read_text(encoding="utf-8")
    assert "options.tenant || tenant()" in js
    assert "tenant: task.tenant" in js
    assert "show('confirm-data', { tenant: tid, body: body })" in js
    assert "$('confirm').disabled = true" in js and "$('confirm').disabled = false" in js
    assert "task.trigger.disabled = true" in js and "task.trigger.disabled = false" in js
    assert ".finally(" in js
    assert "data-pilot-lock" in js
    assert "function isBlockedResult" in js and "veto === true" in js and "truthLabel" in js
    assert "連線失敗" in js and "已阻擋" in js
    assert "if (posting || pending) return" in js
    assert "innerHTML" not in js
    assert "尺寸不符待人工確認" in js
    assert "/cartons" in js and "/measured" in js and "/packing-checklist" in js
    assert "/packing-mismatch/resolve" in js and "packing-resolve-btn" in js
    assert "refreshSeq" in js and "cartonLoadSeq" in js and "Promise.all" in js
    assert "function actionButtons" in js and "setLocked(lockedBtns, true)" in js
