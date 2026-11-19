"""Pilot floor admin APIs: stations list/status, leases list, exception inbox lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.workorder import STRICT_STOCK

TENANT = "sonaqueen-home"
OTHER = "other-tenant"
HEADERS = {"X-Tenant-Id": TENANT}
OTHER_HEADERS = {"X-Tenant-Id": OTHER}


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


def _register_station(client: TestClient, station_id: str | None = None, status: str = "ONLINE") -> str:
    body: dict = {"capabilities": ["PANEL_CUTTING_MANUAL"], "actor": "test", "status": status}
    if station_id:
        body["stationId"] = station_id
    res = client.post("/api/pilot/stations", headers=HEADERS, json=body)
    assert res.status_code == 200
    return res.json()["stationId"]


def test_stations_list_pagination_and_tenant_isolation(client: TestClient) -> None:
    _register_station(client, "st-a")
    _register_station(client, "st-b")
    all_st = client.get("/api/pilot/stations", headers=HEADERS)
    assert all_st.status_code == 200
    body = all_st.json()
    assert body["total"] >= 2
    assert len(body["items"]) == body["total"]

    page = client.get("/api/pilot/stations?offset=0&limit=1", headers=HEADERS)
    assert page.status_code == 200
    pg = page.json()
    assert pg["limit"] == 1
    assert len(pg["items"]) == 1
    assert pg["total"] >= 2

    other_list = client.get("/api/pilot/stations", headers=OTHER_HEADERS).json()["items"]
    assert not any(s.get("stationId") in {"st-a", "st-b"} for s in other_list)


def test_station_status_put_and_dispatch_blocked_when_maintenance(client: TestClient, platform) -> None:
    wo = _ready_wo(platform)
    op = wo["traveler"]["steps"][0]["operation"]
    station_id = _register_station(client, "st-maint")

    ok = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "ACTIVE", "actor": "admin"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "ACTIVE"

    maint = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "scheduled"},
    )
    assert maint.status_code == 200
    assert maint.json()["status"] == "MAINTENANCE"

    blocked = client.post(
        "/api/pilot/dispatch",
        headers=HEADERS,
        json={"workOrderId": wo["workOrderId"], "operation": op, "stationId": station_id, "actor": "test"},
    )
    assert blocked.status_code == 409

    foreign = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=OTHER_HEADERS,
        json={"status": "DISABLED", "actor": "x"},
    )
    assert foreign.status_code == 404


def test_leases_list_filters(client: TestClient, platform) -> None:
    wo = _ready_wo(platform)
    op = wo["traveler"]["steps"][0]["operation"]
    station_id = _register_station(client, "st-lease")
    dispatch = client.post(
        "/api/pilot/dispatch",
        headers=HEADERS,
        json={"workOrderId": wo["workOrderId"], "operation": op, "stationId": station_id, "actor": "test"},
    )
    assert dispatch.status_code == 200
    lease_id = dispatch.json()["leaseId"]

    all_leases = client.get("/api/pilot/leases", headers=HEADERS)
    assert all_leases.status_code == 200
    assert any(item["leaseId"] == lease_id for item in all_leases.json()["items"])

    filtered = client.get(f"/api/pilot/leases?stationId={station_id}&status=LEASED", headers=HEADERS)
    assert filtered.status_code == 200
    items = filtered.json()["items"]
    assert items and all(i.get("stationId") == station_id and i.get("status") == "LEASED" for i in items)

    assert client.get("/api/pilot/leases?offset=0&limit=1", headers=HEADERS).json()["limit"] == 1


def test_exception_ack_resolve_persists_and_idempotent(client: TestClient, platform, tmp_path: Path) -> None:
    _ = tmp_path
    exc = platform.pilot.inbox.record(
        tenant_id=TENANT,
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-test",
        actor="seed",
        detail="short",
    )
    exc_id = exc["exceptionId"]

    ack1 = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin", "note": "seen"})
    assert ack1.status_code == 200
    assert ack1.json()["status"] == "ACKNOWLEDGED"
    assert ack1.json()["acknowledgedBy"] == "admin"

    ack2 = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin"})
    assert ack2.status_code == 200
    assert ack2.json()["status"] == "ACKNOWLEDGED"

    resolve1 = client.post(
        f"/api/pilot/exceptions/{exc_id}/resolve",
        headers=HEADERS,
        json={"actor": "admin", "resolution": "replenished"},
    )
    assert resolve1.status_code == 200
    assert resolve1.json()["status"] == "RESOLVED"

    resolve2 = client.post(f"/api/pilot/exceptions/{exc_id}/resolve", headers=HEADERS, json={"actor": "admin"})
    assert resolve2.status_code == 200
    assert resolve2.json()["status"] == "RESOLVED"

    ack_after = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin"})
    assert ack_after.status_code == 409

    platform.pilot.inbox.load()
    reloaded = platform.pilot.inbox.get(exc_id, tenant_id=TENANT)
    assert reloaded["status"] == "RESOLVED"

    open_only = client.get("/api/pilot/exceptions?status=OPEN", headers=HEADERS)
    assert open_only.status_code == 200
    assert exc_id not in {i["exceptionId"] for i in open_only.json()["items"]}

    foreign = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=OTHER_HEADERS, json={"actor": "x"})
    assert foreign.status_code == 404