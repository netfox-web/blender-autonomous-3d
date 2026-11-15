"""Incomplete POST bodies must be 4xx, not 500. Issue #447."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.operator import make_token, parse_token
from fox3d.station import OP_CAPABILITY
from fox3d.workorder import STRICT_STOCK

HEADERS = {"X-Tenant-Id": "acme"}

# Empty JSON starts a Blender / fleet render.
SKIP_BLENDER_OR_EXTERNAL = frozenset(
    {
        "/api/ecommerce-scenes/batches",
    }
)
SKIP_UNKNOWN_PATH_ID: frozenset[str] = frozenset()
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
    ("/api/materials/lots", {}, "empty"),
    ("/api/materials/lots", {"quantity": "abc"}, "bad-quantity"),
    ("/api/materials/lots", {"quantity": -5}, "negative-quantity"),
    ("/api/materials/lots", {"quantity": 0}, "zero-quantity"),
    ("/api/materials/lots", {"quantity": 1.5}, "fractional-quantity"),
    ("/api/materials/lots", {"quantity": True}, "bool-quantity"),
    ("/api/materials/lots", {"quantity": False}, "bool-false-quantity"),
    ("/api/materials/lots", {"sheetCount": "abc"}, "bad-sheet-count"),
    ("/api/materials/lots", {"sheetCount": -5}, "negative-sheet-count"),
    ("/api/materials/lots", {"sheetCount": 0}, "zero-sheet-count"),
    ("/api/materials/lots", {"sheetCount": 1.5}, "fractional-sheet-count"),
    ("/api/materials/lots", {"sheetCount": True}, "bool-sheet-count"),
    ("/api/materials/lots", {"quantity": 1, "thickness": "bad"}, "bad-thickness"),
    ("/api/materials/lots", {"quantity": 1, "unitCost": "bad"}, "bad-unit-cost"),
    ("/api/materials/lots", {"quantity": 1, "costPerSheet": "bad"}, "bad-cost-per-sheet"),
    ("/api/materials/lots", {"quantity": 1, "source": "LIVE"}, "bad-source"),
    ("/api/pilot/purchase-requests", {}, "empty"),
    ("/api/pilot/purchase-requests", {"quantity": "abc"}, "bad-quantity"),
    ("/api/pilot/purchase-requests", {"quantity": -5}, "negative-quantity"),
    ("/api/pilot/purchase-requests", {"quantity": 0}, "zero-quantity"),
    ("/api/pilot/purchase-requests", {"quantity": 1.5}, "fractional-quantity"),
    ("/api/pilot/purchase-requests", {"quantity": True}, "bool-quantity"),
    ("/api/pilot/purchase-requests", {"quantity": False}, "bool-false-quantity"),
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
    ("/api/materials/lots", {"quantity": 1}, "quantity"),
    ("/api/materials/lots", {"quantity": "2"}, "string-quantity"),
    ("/api/materials/lots", {"sheetCount": 2}, "sheet-count"),
    ("/api/pilot/receipts", {"quantity": 1}, "quantity"),
    ("/api/pilot/receipts", {"quantity": "2"}, "string-quantity"),
    ("/api/pilot/receipts", {"sheetCount": 2}, "sheet-count"),
    ("/api/pilot/receipts", {"quantity": 0, "sheetCount": 3}, "zero-falls-through"),
    ("/api/pilot/receipts", {"quantity": 1, "thickness": ""}, "blank-thickness"),
    ("/api/pilot/receipts", {"quantity": 1, "unitCost": ""}, "blank-unit-cost"),
    ("/api/pilot/receipts", {"quantity": 1, "unitCost": 10, "costPerSheet": "ignored"}, "unit-cost-wins"),
    ("/api/pilot/receipts", {"quantity": 1, "length": 0}, "zero-length"),
    ("/api/pilot/receipts", {"quantity": 1, "length": 2440, "expectedQuantity": 1}, "matching-expected-quantity"),
    ("/api/pilot/purchase-requests", {"quantity": 1}, "quantity"),
    ("/api/pilot/purchase-requests", {"quantity": "2"}, "string-quantity"),
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
        "/api/digital-twins/{twin_id}/preview",
        "/api/materials/lots",
        "/api/pilot/work-orders/{work_order_id}/reserve",
        "/api/pilot/receipts",
        "/api/pilot/purchase-requests",
        "/api/pilot/stations",
        "/api/pilot/stations/{station_id}/heartbeat",
        "/api/pilot/leases/{lease_id}/ack",
        "/api/pilot/leases/{lease_id}/start",
        "/api/pilot/leases/{lease_id}/complete",
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


def _import_stores(platform) -> dict[str, set[str]]:
    return {
        "receipts": set(platform.pilot.receiving.receipts),
        "imports": set(platform.pilot.contracts.imports),
        "lots": _acme_lot_ids(platform),
        "quotes": set(platform.pilot.suppliers.quotes),
        "carrier_quotes": set(platform.pilot.logistics.carrier_quotes),
        "adjustments": set(platform.pilot.contracts.adjustments),
    }


# A valid row followed by a list or object in a required field. Includes the sparse
# shape, where a sibling required field is absent and the old tuple check returned
# early before the service hashed the container.
_CONTAINER_SAMPLES: tuple[tuple[str, Any], ...] = (
    ("array", []),
    ("object", {}),
    ("array-values", ["x"]),
    ("object-values", {"a": 1}),
)
_IMPORT_GOOD_ROWS: tuple[tuple[str, dict[str, Any], tuple[str, ...]], ...] = (
    (
        "fox3d.receipt.v1",
        {"material": "TEST", "quantity": 1, "supplierLot": "good"},
        ("material", "quantity"),
    ),
    (
        "fox3d.supplier_quote.v1",
        {"supplierId": "S-A", "material": 100},
        ("supplierId",),
    ),
    (
        "fox3d.carrier_quote.v1",
        {"carrier": "DHL", "charge": 120},
        ("carrier", "charge"),
    ),
    (
        "fox3d.inventory_adjustment.v1",
        {"lotId": "lot-1", "quantity": 1, "reason": "cycle"},
        ("lotId", "quantity", "reason"),
    ),
)


def _container_import_cases() -> list[tuple[str, list[dict[str, Any]], str, str]]:
    cases: list[tuple[str, list[dict[str, Any]], str, str]] = []
    for schema, good, fields in _IMPORT_GOOD_ROWS:
        for field in fields:
            for label, value in _CONTAINER_SAMPLES:
                replaced = dict(good)
                replaced[field] = value
                cases.append((schema, [dict(good), replaced], field, f"{field}-{label}"))
                cases.append((schema, [dict(good), {field: value}], field, f"{field}-{label}-sparse"))
    return cases


CONTAINER_IMPORT_CASES = _container_import_cases()


def test_import_receipt_array_material_after_valid_row_writes_nothing(client: TestClient, platform) -> None:
    before = _import_stores(platform)
    response = client.post(
        "/api/pilot/import",
        headers=HEADERS,
        json={
            "schemaVersion": "fox3d.receipt.v1",
            "rows": [
                {"material": "TEST", "quantity": 1, "supplierLot": "good"},
                {"material": [], "quantity": 1},
            ],
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "rows[1] material 格式錯誤"
    assert "traceback" not in response.text.lower()
    assert _import_stores(platform) == before


@pytest.mark.parametrize(
    "schema,rows,field",
    [(schema, rows, field) for schema, rows, field, _label in CONTAINER_IMPORT_CASES],
    ids=[f"{schema} {label}" for schema, _rows, _field, label in CONTAINER_IMPORT_CASES],
)
def test_import_container_required_field_after_valid_row_writes_nothing(
    client: TestClient,
    platform,
    schema: str,
    rows: list[dict[str, Any]],
    field: str,
) -> None:
    before = _import_stores(platform)
    response = client.post(
        "/api/pilot/import",
        headers=HEADERS,
        json={"schemaVersion": schema, "rows": rows},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == f"rows[1] {field} 格式錯誤"
    assert "traceback" not in response.text.lower()
    assert _import_stores(platform) == before


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


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/pilot/work-orders/missing/reserve", {}),
        ("/api/pilot/stations/missing/heartbeat", {}),
        ("/api/pilot/leases/missing/ack", {}),
        ("/api/pilot/leases/missing/start", {}),
        ("/api/pilot/leases/missing/complete", {}),
        ("/api/pilot/leases/missing/complete", {"confirm": True}),
        ("/api/digital-twins/missing/preview", {}),
    ],
)
def test_unknown_path_id_returns_404(client: TestClient, path: str, body: dict[str, Any]) -> None:
    response = client.post(path, headers=HEADERS, json=body)
    assert response.status_code == 404, response.text
    assert "traceback" not in response.text.lower()


def test_cross_tenant_twin_preview_and_station_heartbeat(client: TestClient, platform) -> None:
    twin = client.post("/api/digital-twins", headers=HEADERS, json={"sku": "ACME-TWIN-1"})
    assert twin.status_code == 200, twin.text
    twin_id = twin.json()["twinId"]

    other_headers = {"X-Tenant-Id": "other"}
    foreign_preview = client.post(f"/api/digital-twins/{twin_id}/preview", headers=other_headers, json={})
    missing_preview = client.post("/api/digital-twins/no-such-twin/preview", headers=other_headers, json={})
    assert foreign_preview.status_code == 404, foreign_preview.text
    assert foreign_preview.json() == missing_preview.json() == {"detail": "找不到數位分身"}

    dispatch_payload = _ready_dispatch(client, platform)
    station_id = dispatch_payload["stationId"]
    foreign_hb = client.post(f"/api/pilot/stations/{station_id}/heartbeat", headers=other_headers, json={})
    assert foreign_hb.status_code == 403, foreign_hb.text

    foreign_reserve = client.post(
        f"/api/pilot/work-orders/{dispatch_payload['workOrderId']}/reserve",
        headers=other_headers,
        json={},
    )
    assert foreign_reserve.status_code == 403, foreign_reserve.text

    lease = client.post("/api/pilot/dispatch", headers=HEADERS, json=dispatch_payload)
    assert lease.status_code == 200, lease.text
    lease_id = lease.json()["leaseId"]
    for suffix, body in (("ack", {}), ("start", {}), ("complete", {"confirm": True})):
        foreign_lease = client.post(f"/api/pilot/leases/{lease_id}/{suffix}", headers=other_headers, json=body)
        assert foreign_lease.status_code == 403, foreign_lease.text


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": "abc"},
        {"quantity": -5},
        {"quantity": 0},
        {"quantity": 1.5},
        {"quantity": True},
        {"quantity": False},
        {"sheetCount": "abc"},
        {"sheetCount": -5},
        {"sheetCount": 0},
        {"sheetCount": 1.5},
        {"quantity": 1, "thickness": "bad"},
        {"quantity": 1, "unitCost": "bad"},
        {"quantity": 1, "costPerSheet": "bad"},
    ],
)
def test_materials_lots_bad_numbers_return_422_and_do_not_write(
    client: TestClient, platform, body: dict[str, Any]
) -> None:
    receipts = set(platform.pilot.receiving.receipts)
    lots = _acme_lot_ids(platform)
    response = client.post("/api/materials/lots", headers=HEADERS, json=body)
    assert response.status_code == 422, response.text
    assert "traceback" not in response.text.lower()
    assert set(platform.pilot.receiving.receipts) == receipts
    assert _acme_lot_ids(platform) == lots


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"material": "PB_18_WHITE"},
        {"quantity": ""},
        {"quantity": "abc"},
        {"quantity": -5},
        {"quantity": 0},
        {"quantity": "0"},
        {"quantity": 1.5},
        {"quantity": True},
        {"quantity": False},
        {"quantity": []},
        {"quantity": {}},
    ],
)
def test_purchase_requests_bad_quantity_returns_422_and_does_not_write(
    client: TestClient, platform, body: dict[str, Any]
) -> None:
    before = set(platform.pilot.receiving.requests)
    response = client.post("/api/pilot/purchase-requests", headers=HEADERS, json=body)
    assert response.status_code == 422, response.text
    assert "traceback" not in response.text.lower()
    assert set(platform.pilot.receiving.requests) == before


@pytest.mark.parametrize(
    "kind,object_id",
    [
        ("BAD", "wo-1"),
        ("UNKNOWN", "lot-1"),
        ("station", "st-1"),
        ("WO", "wo:1"),
        ("LOT", "a:b:c"),
        ("REL", "rel 1"),
        ("CTN", "ctn.1"),
        ("WO", "..wo"),
        ("WO", "wo$1"),
    ],
)
def test_scan_token_rejects_unknown_kind_and_unsafe_object_id(
    client: TestClient, kind: str, object_id: str
) -> None:
    response = client.get(f"/api/pilot/scan-token/{kind}/{object_id}", headers=HEADERS)
    assert response.status_code == 422, response.text
    assert "traceback" not in response.text.lower()
    with pytest.raises(PermissionError):
        make_token(kind, object_id)


@pytest.mark.parametrize(
    "kind,object_id,expected_kind",
    [
        ("WO", "wo-1", "WO"),
        ("wo", "wo_2", "WO"),
        ("LOT", "lot-10", "LOT"),
        ("REL", "550e8400-e29b-41d4-a716-446655440000", "REL"),
        ("CTN", "CTN_01", "CTN"),
    ],
)
def test_scan_token_valid_kind_and_object_id_round_trips(
    client: TestClient, kind: str, object_id: str, expected_kind: str
) -> None:
    response = client.get(f"/api/pilot/scan-token/{kind}/{object_id}", headers=HEADERS)
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert parse_token(token) == (expected_kind, object_id)
