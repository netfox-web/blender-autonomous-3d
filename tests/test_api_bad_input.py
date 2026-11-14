"""Incomplete POST bodies must be 4xx, not 500. Issue #447."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.station import OP_CAPABILITY
from fox3d.workorder import STRICT_STOCK

HEADERS = {"X-Tenant-Id": "acme"}

# Empty JSON starts a Blender / fleet render. Twin preview also KeyErrors on a
# placeholder id before it would call Blender; that KeyError is outside this issue.
SKIP_BLENDER_OR_EXTERNAL = frozenset(
    {
        "/api/digital-twins/{twin_id}/preview",
        "/api/ecommerce-scenes/batches",
    }
)
# A placeholder path id is not a stored resource. These handlers raise KeyError.
# This issue forbids a global KeyError handler, and these routes are not the five
# body-field endpoints.
SKIP_UNKNOWN_PATH_ID = frozenset(
    {
        "/api/pilot/work-orders/{work_order_id}/reserve",
        "/api/pilot/stations/{station_id}/heartbeat",
        "/api/pilot/leases/{lease_id}/ack",
        "/api/pilot/leases/{lease_id}/start",
    }
)
SKIP_EMPTY_BODY_POSTS = SKIP_BLENDER_OR_EXTERNAL | SKIP_UNKNOWN_PATH_ID


def _post_paths(routes: Iterable[Any]) -> set[str]:
    found: set[str] = set()
    for route in routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if path and "POST" in methods:
            found.add(path)
        original = getattr(route, "original_router", None)
        if original is not None:
            found |= _post_paths(original.routes)
    return found

BAD_BODIES = [
    ("/api/digital-twins", {}, "empty"),
    ("/api/digital-twins", {"dimensions": {"width": 10}}, "missing-sku"),
    ("/api/digital-twins", {"sku": "A-1", "weight": "heavy"}, "bad-weight"),
    ("/api/pilot/receipts", {}, "empty"),
    ("/api/pilot/receipts", {"material": "PB_18_WHITE"}, "missing-quantity"),
    ("/api/pilot/receipts", {"quantity": "nope"}, "bad-quantity"),
    ("/api/pilot/receipts", {"quantity": 1, "source": "LIVE"}, "bad-source"),
    ("/api/pilot/stations", {}, "empty"),
    ("/api/pilot/stations", {"actor": "api"}, "missing-capabilities"),
    ("/api/pilot/stations", {"capabilities": ["NOT_A_CAP"]}, "bad-capabilities"),
    ("/api/pilot/import", {}, "empty"),
    ("/api/pilot/import", {"rows": [{"material": "TEST", "quantity": 1}]}, "missing-schema"),
    ("/api/pilot/import", {"schemaVersion": "fox3d.receipt.v1", "source": "LIVE"}, "bad-source"),
    ("/api/pilot/dispatch", {}, "empty"),
    ("/api/pilot/dispatch", {"workOrderId": "wo-1"}, "missing-operation-and-station"),
    ("/api/pilot/dispatch", {"workOrderId": 1, "operation": "panel_cutting", "stationId": "st-1"}, "bad-types"),
]

VALID_BODIES = [
    ("/api/digital-twins", {"sku": "A-1"}, "sku"),
    ("/api/pilot/receipts", {"quantity": 1}, "quantity"),
    ("/api/pilot/receipts", {"sheetCount": 2}, "sheet-count"),
    ("/api/pilot/stations", {"capabilities": ["PANEL_CUTTING_MANUAL"]}, "capability"),
    ("/api/pilot/import", {"schemaVersion": "fox3d.receipt.v1", "rows": [{"material": "TEST", "quantity": 1}]}, "receipt-row"),
    ("/api/pilot/dispatch", None, "work-order"),
]


@pytest.fixture
def client(platform):
    return TestClient(create_app(platform), raise_server_exceptions=False)


def _ready_dispatch(client: TestClient, platform) -> dict:
    tenant = "acme"
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
    platform.pilot.receiving.import_receipt(
        row,
        tenant_id=tenant,
        actor="recv",
        source="MANUAL",
        idempotency_key=f"{tenant}-lot",
    )
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    platform.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    platform.pilot.workorders.reserve_materials(
        wo["workOrderId"],
        actor="ops",
        tenant_id=tenant,
        allocation_policy=STRICT_STOCK,
    )
    operation = wo["traveler"]["steps"][0]["operation"]
    station = client.post(
        "/api/pilot/stations",
        headers=HEADERS,
        json={"capabilities": [OP_CAPABILITY[operation]]},
    )
    assert station.status_code == 200, station.text
    return {
        "workOrderId": wo["workOrderId"],
        "operation": operation,
        "stationId": station.json()["stationId"],
    }


@pytest.mark.parametrize("path,body,label", BAD_BODIES, ids=[f"{path} {label}" for path, _, label in BAD_BODIES])
def test_incomplete_body_is_4xx(client: TestClient, path: str, body: dict, label: str) -> None:
    del label
    response = client.post(path, headers=HEADERS, json=body)
    assert 400 <= response.status_code <= 422, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, str) and detail.strip()
    assert "traceback" not in response.text.lower()


@pytest.mark.parametrize("path,body,label", VALID_BODIES, ids=[f"{path} {label}" for path, _, label in VALID_BODIES])
def test_minimal_valid_body_is_200(client: TestClient, platform, path: str, body: dict | None, label: str) -> None:
    del label
    if path == "/api/pilot/dispatch":
        body = _ready_dispatch(client, platform)
    response = client.post(path, headers=HEADERS, json=body)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/digital-twins",
        "/api/pilot/receipts",
        "/api/pilot/stations",
        "/api/pilot/import",
        "/api/pilot/dispatch",
    ],
)
def test_tenant_mismatch_stays_403(client: TestClient, path: str) -> None:
    response = client.post(path, headers=HEADERS, json={"tenantId": "other-tenant"})
    assert response.status_code == 403, response.text


def test_post_routes_reject_empty_body_without_5xx(client: TestClient) -> None:
    app = client.app
    assert isinstance(app, FastAPI)
    post_paths = _post_paths(app.routes)
    assert SKIP_EMPTY_BODY_POSTS <= post_paths
    failures: list[str] = []
    seen: set[str] = set()
    for path in sorted(post_paths - SKIP_EMPTY_BODY_POSTS):
        seen.add(path)
        url = re.sub(r"\{[^}]+\}", "missing", path)
        response = client.post(url, headers=HEADERS, json={})
        if response.status_code >= 500:
            failures.append(f"{path} -> {response.status_code} {response.text[:180]}")
    assert not failures, "\n".join(failures)
    assert {
        "/api/digital-twins",
        "/api/pilot/receipts",
        "/api/pilot/stations",
        "/api/pilot/import",
        "/api/pilot/dispatch",
    } <= seen
