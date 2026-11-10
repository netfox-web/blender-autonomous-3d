"""Admin page /admin/pilot-floor: shell, assets, pilot-floor APIs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.workorder import STRICT_STOCK
from fox3d.operator import make_token

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def _ready_wo(platform, tenant: str = TENANT):
    product = platform.kd.build_sku(tenant_id=tenant, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    nest = (rel.get("snapshot") or {}).get("nesting") or {}
    row = {
        "supplierLot": f"{tenant}-lot",
        "material": nest.get("sheetSku") or "PB_18_WHITE",
        "thickness": nest.get("thickness") or 18,
        "quantity": 20,
    }
    sheet_mm = nest.get("sheetMm") or []
    if len(sheet_mm) >= 2:
        row["length"] = float(sheet_mm[0])
        row["width"] = float(sheet_mm[1])
    platform.pilot.receiving.import_receipt(row, tenant_id=tenant, actor="recv", source="MANUAL", idempotency_key=f"{tenant}-lot")
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    platform.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    platform.pilot.workorders.reserve_materials(wo["workOrderId"], actor="ops", tenant_id=tenant, allocation_policy=STRICT_STOCK)
    return wo


def test_pilot_floor_page_and_assets(client: TestClient) -> None:
    page = client.get("/admin/pilot-floor")
    assert page.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in page.text
    assert "/admin/recipes/assets/fox3d-shell.css" in page.text
    assert "/admin/pages/assets/pilot-floor.js" in page.text
    assert "/admin/pages/assets/pilot-floor.css" in page.text
    assert 'aria-label="工作台導覽"' not in page.text

    for name in ("pilot-floor.js", "pilot-floor.css"):
        res = client.get(f"/admin/pages/assets/{name}")
        assert res.status_code == 200 and res.content


def test_pilot_floor_feature_becomes_page(client: TestClient) -> None:
    index = client.get("/api/admin/features").json()
    pf = next(f for f in index["features"] if f["id"] == "pilot-floor")
    assert pf["kind"] == "page"
    assert pf["href"] == "/admin/pilot-floor"
    assert "/admin/pilot-floor" in pf["prefixes"]


def test_pilot_floor_apis(client: TestClient, platform) -> None:
    wo = _ready_wo(platform)
    op = wo["traveler"]["steps"][0]["operation"]

    operator = client.get("/api/pilot/operator", headers=HEADERS)
    assert operator.status_code == 200
    assert operator.json()["tenantId"] == TENANT

    exceptions = client.get("/api/pilot/exceptions", headers=HEADERS)
    assert exceptions.status_code == 200
    assert "items" in exceptions.json()

    station = client.post(
        "/api/pilot/stations",
        headers=HEADERS,
        json={"capabilities": ["PANEL_CUTTING_MANUAL"], "actor": "test", "status": "ONLINE"},
    )
    assert station.status_code == 200
    station_id = station.json()["stationId"]

    heartbeat = client.post(f"/api/pilot/stations/{station_id}/heartbeat", headers=HEADERS, json={"actor": "test"})
    assert heartbeat.status_code == 200

    dispatch = client.post(
        "/api/pilot/dispatch",
        headers=HEADERS,
        json={
            "workOrderId": wo["workOrderId"],
            "operation": op,
            "stationId": station_id,
            "actor": "test",
        },
    )
    assert dispatch.status_code == 200
    lease_id = dispatch.json()["leaseId"]

    for suffix in ("ack", "start"):
        step = client.post(f"/api/pilot/leases/{lease_id}/{suffix}", headers=HEADERS, json={"actor": "test"})
        assert step.status_code == 200

    token = client.get(f"/api/pilot/scan-token/WO/{wo['workOrderId']}", headers=HEADERS)
    assert token.status_code == 200
    scan_token = token.json()["token"]
    assert scan_token == make_token("WO", wo["workOrderId"])

    scan = client.post("/api/pilot/scan", headers=HEADERS, json={"token": scan_token})
    assert scan.status_code == 200
    assert scan.json()["objectId"] == wo["workOrderId"]
