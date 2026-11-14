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
    ("/api/pilot/receipts", {"quantity": 1.9}, "fractional-quantity"),
    ("/api/pilot/receipts", {"quantity": 1.0}, "float-quantity"),
    ("/api/pilot/receipts", {"quantity": True}, "bool-quantity"),
    ("/api/pilot/receipts", {"quantity": False}, "bool-false-quantity"),
    ("/api/pilot/receipts", {"quantity": False, "sheetCount": 3}, "bool-does-not-fall-through"),
    ("/api/pilot/receipts", {"sheetCount": 1.9}, "fractional-sheet-count"),
    ("/api/pilot/receipts", {"sheetCount": True}, "bool-sheet-count"),
    ("/api/pilot/receipts", {"quantity": 1, "length": ""}, "blank-length"),
    ("/api/pilot/receipts", {"quantity": 1, "width": ""}, "blank-width"),
    ("/api/pilot/receipts", {"quantity": 1, "expectedQuantity": "bad"}, "bad-expected-quantity"),
    ("/api/pilot/receipts", {"quantity": 1, "expectedQuantity": ""}, "blank-expected-quantity"),
    ("/api/pilot/receipts", {"quantity": 1, "expectedQuantity": 1.9}, "fractional-expected-quantity"),
    ("/api/pilot/receipts", {"quantity": 1, "expectedQuantity": True}, "bool-expected-quantity"),
    ("/api/pilot/receipts", {"quantity": 1, "expectedThickness": ""}, "blank-expected-thickness"),
    ("/api/pilot/receipts", {"quantity": 1, "expectedLength": "bad"}, "bad-expected-length"),
    ("/api/pilot/receipts", {"quantity": 1, "expectedWidth": "bad"}, "bad-expected-width"),
    ("/api/pilot/receipts", {"quantity": 1, "thickness": "bad"}, "bad-thickness"),
    ("/api/pilot/receipts", {"quantity": 1, "unitCost": "bad"}, "bad-unit-cost"),
    ("/api/pilot/receipts", {"quantity": 1, "source": "LIVE"}, "bad-source"),
    ("/api/pilot/stations", {}, "empty"),
    ("/api/pilot/stations", {"actor": "api"}, "missing-capabilities"),
    ("/api/pilot/stations", {"capabilities": ["NOT_A_CAP"]}, "bad-capabilities"),
    ("/api/pilot/import", {}, "empty"),
    ("/api/pilot/import", {"rows": [{"material": "TEST", "quantity": 1}]}, "missing-schema"),
    ("/api/pilot/import", {"schemaVersion": []}, "schema-array"),
    ("/api/pilot/import", {"schemaVersion": {}}, "schema-object"),
    ("/api/pilot/import", {"schemaVersion": "fox3d.receipt.v1", "source": "LIVE"}, "bad-source"),
    ("/api/pilot/dispatch", {}, "empty"),
    ("/api/pilot/dispatch", {"workOrderId": "wo-1"}, "missing-operation-and-station"),
    ("/api/pilot/dispatch", {"workOrderId": 1, "operation": "panel_cutting", "stationId": "st-1"}, "bad-types"),
]

VALID_BODIES = [
    ("/api/digital-twins", {"sku": "A-1"}, "sku"),
    ("/api/pilot/receipts", {"quantity": 1}, "quantity"),
    ("/api/pilot/receipts", {"quantity": "2"}, "string-quantity"),
    ("/api/pilot/receipts", {"sheetCount": 2}, "sheet-count"),
    ("/api/pilot/receipts", {"quantity": 0, "sheetCount": 3}, "zero-falls-through"),
    ("/api/pilot/receipts", {"quantity": 1, "thickness": ""}, "blank-thickness"),
    ("/api/pilot/receipts", {"quantity": 1, "unitCost": ""}, "blank-unit-cost"),
    ("/api/pilot/receipts", {"quantity": 1, "unitCost": 10, "costPerSheet": "ignored"}, "unit-cost-wins"),
    ("/api/pilot/receipts", {"quantity": 1, "length": 0}, "zero-length"),
    ("/api/pilot/receipts", {"quantity": 1, "length": 2440, "expectedQuantity": 1}, "matching-expected-quantity"),
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


def _acme_lot_ids(platform) -> set[str]:
    return {lot["lotId"] for lot in platform.lots.list(tenant_id="acme")}


def _assert_unchanged(platform, receipts: set[str], imports: set[str], lots: set[str]) -> None:
    assert set(platform.pilot.receiving.receipts) == receipts
    assert set(platform.pilot.contracts.imports) == imports
    assert _acme_lot_ids(platform) == lots


@pytest.mark.parametrize("schema", [[], {}, 1, True])
def test_import_schema_version_must_be_string(client: TestClient, platform, schema: object) -> None:
    receipts = set(platform.pilot.receiving.receipts)
    imports = set(platform.pilot.contracts.imports)
    lots = _acme_lot_ids(platform)
    response = client.post(
        "/api/pilot/import",
        headers=HEADERS,
        json={"schemaVersion": schema, "rows": [{"material": "TEST", "quantity": 1, "supplierLot": "nope"}]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "schemaVersion 無效或缺少"
    _assert_unchanged(platform, receipts, imports, lots)


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": 1.9},
        {"quantity": True},
        {"quantity": False},
        {"quantity": 1, "length": ""},
        {"quantity": 1, "expectedQuantity": "bad"},
    ],
)
def test_receipt_bad_numbers_do_not_write(client: TestClient, platform, body: dict) -> None:
    receipts = set(platform.pilot.receiving.receipts)
    lots = _acme_lot_ids(platform)
    response = client.post("/api/pilot/receipts", headers=HEADERS, json=body)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail.strip()
    assert "traceback" not in response.text.lower()
    assert set(platform.pilot.receiving.receipts) == receipts
    assert _acme_lot_ids(platform) == lots


def test_fractional_quantity_is_not_stored_as_truncated_int(client: TestClient, platform) -> None:
    response = client.post("/api/pilot/receipts", headers=HEADERS, json={"quantity": 1.9})
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "quantity 須為正整數"
    assert platform.pilot.receiving.receipts == {}
    assert _acme_lot_ids(platform) == set()


@pytest.mark.parametrize(
    "bad_row",
    [
        {"material": "TEST", "quantity": "bad", "supplierLot": "bad-qty"},
        {"material": "TEST", "quantity": 1.9, "supplierLot": "fraction"},
        {"material": "TEST", "quantity": True, "supplierLot": "bool"},
        {"material": "TEST", "quantity": 1, "length": "", "supplierLot": "blank-length"},
        {"material": "TEST", "quantity": 1, "expectedQuantity": "bad", "supplierLot": "bad-expected"},
    ],
)
def test_import_bad_receipt_row_rejects_batch_before_write(client: TestClient, platform, bad_row: dict) -> None:
    receipts = set(platform.pilot.receiving.receipts)
    imports = set(platform.pilot.contracts.imports)
    lots = _acme_lot_ids(platform)
    response = client.post(
        "/api/pilot/import",
        headers=HEADERS,
        json={
            "schemaVersion": "fox3d.receipt.v1",
            "rows": [
                {"material": "TEST", "quantity": 1, "supplierLot": "good-row"},
                bad_row,
            ],
        },
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail.startswith("rows[1] ")
    assert "traceback" not in response.text.lower()
    _assert_unchanged(platform, receipts, imports, lots)


def test_import_two_valid_receipt_rows_match_stored_quantities(client: TestClient, platform) -> None:
    before = set(platform.pilot.receiving.receipts)
    response = client.post(
        "/api/pilot/import",
        headers=HEADERS,
        json={
            "schemaVersion": "fox3d.receipt.v1",
            "rows": [
                {"material": "TEST", "quantity": 1, "supplierLot": "row-1"},
                {"material": "TEST", "quantity": 2, "supplierLot": "row-2"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["acceptedCount"] == 2
    assert data["rejectedCount"] == 0
    accepted_ids = {row["receiptId"] for row in data["accepted"]}
    stored = platform.pilot.receiving.receipts
    assert set(stored) - before == accepted_ids
    assert {stored[rid]["supplierLot"]: stored[rid]["quantity"] for rid in accepted_ids} == {"row-1": 1, "row-2": 2}
    assert data["importId"] in platform.pilot.contracts.imports


def test_import_missing_receipt_field_records_only_accepted_row(client: TestClient, platform) -> None:
    before = set(platform.pilot.receiving.receipts)
    response = client.post(
        "/api/pilot/import",
        headers=HEADERS,
        json={
            "schemaVersion": "fox3d.receipt.v1",
            "rows": [
                {"material": "TEST", "quantity": 1, "supplierLot": "kept"},
                {"quantity": 3, "supplierLot": "no-material"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["acceptedCount"] == 1
    assert data["rejectedCount"] == 1
    assert data["rejected"][0]["index"] == 1
    accepted_ids = {row["receiptId"] for row in data["accepted"]}
    assert set(platform.pilot.receiving.receipts) - before == accepted_ids
    assert data["importId"] in platform.pilot.contracts.imports


@pytest.mark.parametrize(
    "schema,rows,store",
    [
        (
            "fox3d.supplier_quote.v1",
            [{"supplierId": "S-A", "material": 100}, {"supplierId": "S-B", "material": "bad"}],
            "quotes",
        ),
        (
            "fox3d.carrier_quote.v1",
            [{"carrier": "DHL", "charge": 120}, {"carrier": "DHL", "charge": "bad"}],
            "carrier_quotes",
        ),
        (
            "fox3d.carrier_quote.v1",
            [{"carrier": "DHL", "charge": 120}, {"carrier": "DHL", "charge": 80, "dimDivisor": "bad"}],
            "carrier_quotes",
        ),
        (
            "fox3d.inventory_adjustment.v1",
            [
                {"lotId": "lot-1", "quantity": 1, "reason": "cycle"},
                {"lotId": "lot-1", "quantity": "bad", "reason": "cycle"},
            ],
            "adjustments",
        ),
    ],
)
def test_import_bad_row_of_each_schema_writes_nothing(client: TestClient, platform, schema: str, rows: list, store: str) -> None:
    if store == "quotes":
        before = set(platform.pilot.suppliers.quotes)
    elif store == "carrier_quotes":
        before = set(platform.pilot.logistics.carrier_quotes)
    else:
        before = set(platform.pilot.contracts.adjustments)
    imports = set(platform.pilot.contracts.imports)
    response = client.post(
        "/api/pilot/import",
        headers=HEADERS,
        json={"schemaVersion": schema, "rows": rows},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"].startswith("rows[1] ")
    assert set(platform.pilot.contracts.imports) == imports
    if store == "quotes":
        assert set(platform.pilot.suppliers.quotes) == before
    elif store == "carrier_quotes":
        assert set(platform.pilot.logistics.carrier_quotes) == before
    else:
        assert set(platform.pilot.contracts.adjustments) == before
