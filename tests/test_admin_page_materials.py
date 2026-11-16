"""Admin plug-in page: /admin/materials."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.admin_pages import page_features
from fox3d.api import create_app

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def test_materials_plugin_claims_feature() -> None:
    assert page_features().get("materials") == "/admin/materials"


def test_materials_page_serves_html_and_shell(client: TestClient) -> None:
    res = client.get("/admin/materials")
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in res.text
    assert "/admin/pages/assets/materials.js" in res.text
    assert "/admin/pages/assets/materials.css" in res.text
    assert 'aria-label="工作台導覽"' not in res.text


@pytest.mark.parametrize("asset", ["materials.js", "materials.css"])
def test_materials_assets(client: TestClient, asset: str) -> None:
    res = client.get(f"/admin/pages/assets/{asset}")
    assert res.status_code == 200
    assert res.content


def test_materials_apis_with_tenant(client: TestClient) -> None:
    mats = client.get("/api/materials", headers=HEADERS)
    assert mats.status_code == 200
    body = mats.json()
    assert "sheets" in body and "lots" in body

    lot = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 1, "actor": "test"},
    )
    assert lot.status_code == 200

    rem = client.get("/api/remnants", headers=HEADERS)
    assert rem.status_code == 200
    snap = rem.json()
    assert "items" in snap


def test_materials_lots_are_tenant_scoped(client: TestClient) -> None:
    lots = {}
    for tenant in ("tenant-a", "tenant-b"):
        response = client.post(
            "/api/materials/lots",
            headers={"X-Tenant-Id": tenant},
            json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 1},
        )
        assert response.status_code == 200
        lots[tenant] = response.json()["lotId"]

    for headers in ({}, {"X-Tenant-Id": ""}):
        response = client.get("/api/materials", headers=headers)
        assert response.status_code == 400
        assert response.json() == {"detail": "X-Tenant-Id 無效"}

    for tenant, lot_id in lots.items():
        response = client.get("/api/materials", headers={"X-Tenant-Id": tenant})
        assert response.status_code == 200
        assert {lot["lotId"] for lot in response.json()["lots"]} == {lot_id}


def test_remnant_reserve_round_trip(client: TestClient, platform) -> None:  # noqa: ANN001
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="admin-page-test",
        tenant_id=TENANT,
    )
    assert created
    rid = created[0]["remnantId"]
    res = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-test", "version": created[0]["version"]},
    )
    assert res.status_code == 200
    assert res.json().get("status") == "reserved"


@pytest.mark.parametrize(
    "bad_body",
    [
        {"by": "wo-test", "version": 1, "leaseSeconds": 1e12},
        {"by": "wo-test", "version": 1, "leaseSeconds": "x"},
        {"by": "wo-test", "version": 1, "leaseSeconds": -5},
        {"by": "wo-test", "version": 1, "leaseSeconds": 0},
        {"by": "wo-test", "version": 1, "leaseSeconds": 7 * 86400 + 1},
        {"by": "wo-test", "version": 1, "leaseSeconds": True},
        {"by": "wo-test", "version": 1, "leaseSeconds": None},
        {"by": "wo-test", "version": 1, "leaseSeconds": "inf"},
        {"by": "wo-test", "version": 1, "leaseSeconds": 10**400},
        {"by": "wo-test", "version": "abc"},
        {"by": "wo-test", "version": 0},
        {"by": "wo-test", "version": -1},
        {"by": "wo-test", "version": 1.5},
        {"by": "wo-test", "version": True},
        {"by": "wo-test", "version": None},
        {"by": "wo-test"},
        {"by": ["a"], "version": 1},
        {"by": "", "version": 1},
        {"by": "   ", "version": 1},
        {"by": None, "version": 1},
        {"by": 123, "version": 1},
        {"by": True, "version": 1},
        {"by": "x" * 121, "version": 1},
        {"version": 1},
    ],
)
def test_remnant_reserve_invalid_inputs_return_422(
    client: TestClient, platform, bad_body: dict[str, object]  # noqa: ANN001
) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="reserve-validation",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]
    res = client.post(f"/api/remnants/{rid}/reserve", headers=HEADERS, json=bad_body)
    assert res.status_code == 422, res.text
    assert platform.remnants.items[rid]["status"] == "available"


@pytest.mark.parametrize("lease_seconds", [1, 3600, 7 * 86400])
def test_remnant_reserve_valid_lease_boundaries(
    client: TestClient, platform, lease_seconds: int  # noqa: ANN001
) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 500, "h": 300, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="reserve-lease-bounds",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]
    res = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "x" * 120, "version": 1, "leaseSeconds": lease_seconds},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "reserved"
    assert body["reservedBy"] == "x" * 120
    assert body["reservedUntil"] is not None


def test_remnant_reserve_unknown_or_other_tenant_returns_404(client: TestClient, platform) -> None:  # noqa: ANN001
    missing = client.post(
        "/api/remnants/no-such-remnant/reserve",
        headers=HEADERS,
        json={"by": "wo-test", "version": 1},
    )
    assert missing.status_code == 404

    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="tenant-a-run",
        tenant_id="tenant-a",
    )
    rid = created[0]["remnantId"]
    other = client.post(
        f"/api/remnants/{rid}/reserve",
        headers={"X-Tenant-Id": "tenant-b"},
        json={"by": "wo-other", "version": 1},
    )
    assert other.status_code == 404
    assert platform.remnants.items[rid]["status"] == "available"


def test_remnant_reserve_requires_tenant_and_checks_body_tenant_conflict(
    client: TestClient, platform  # noqa: ANN001
) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="tenant-guard-run",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]

    no_header = client.post(f"/api/remnants/{rid}/reserve", json={"by": "wo-1", "version": 1})
    assert no_header.status_code == 400

    bad_type = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "tenantId": 123},
    )
    assert bad_type.status_code == 422

    conflict = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "tenantId": "other-tenant"},
    )
    assert conflict.status_code == 403
    assert platform.remnants.items[rid]["status"] == "available"


def test_legacy_remnant_without_tenant_id_only_reservable_by_default_tenant(
    client: TestClient, platform  # noqa: ANN001
) -> None:
    legacy_id = "legacy-no-tenant"
    platform.remnants.items[legacy_id] = {
        "remnantId": legacy_id,
        "tenantId": None,
        "material": "WOOD_WHITE",
        "materialCode": "WOOD_WHITE",
        "thickness": 18,
        "w": 600,
        "h": 400,
        "grain": "length",
        "status": "available",
        "qualityState": "AVAILABLE",
        "version": 1,
    }
    platform.remnants.store.put(platform.remnants.items[legacy_id])

    non_default = client.post(
        f"/api/remnants/{legacy_id}/reserve",
        headers=HEADERS,
        json={"by": "wo-non-default", "version": 1},
    )
    assert non_default.status_code == 404
    assert platform.remnants.items[legacy_id]["status"] == "available"

    default_res = client.post(
        f"/api/remnants/{legacy_id}/reserve",
        headers={"X-Tenant-Id": "default"},
        json={"by": "wo-default", "version": 1},
    )
    assert default_res.status_code == 200
    assert default_res.json()["status"] == "reserved"


def test_remnant_reserve_conflict_and_idempotent_retry(client: TestClient, platform) -> None:  # noqa: ANN001
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="conflict-test",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]

    stale = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 99},
    )
    assert stale.status_code == 409

    ok1 = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "idempotencyKey": "idem-res-1"},
    )
    assert ok1.status_code == 200

    retry_same = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "idempotencyKey": "idem-res-1"},
    )
    assert retry_same.status_code == 200
    assert retry_same.json()["version"] == ok1.json()["version"]

    second_confirm = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "idempotencyKey": "idem-res-2"},
    )
    assert second_confirm.status_code == 409


def test_materials_lots_without_supplier_lot_create_distinct_lots_with_distinct_idempotency_keys(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 2, "idempotencyKey": "k-1"},
    )
    retry = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 2, "idempotencyKey": "k-1"},
    )
    second = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 2, "idempotencyKey": "k-2"},
    )
    assert first.status_code == 200 and retry.status_code == 200 and second.status_code == 200
    assert first.json()["receiptId"] == retry.json()["receiptId"]
    assert first.json()["lotId"] == retry.json()["lotId"]
    assert first.json()["lotId"] != second.json()["lotId"]


def test_nesting_benchmark_api_caps_per_tenant(client: TestClient, platform) -> None:  # noqa: ANN001
    from fox3d.physical_os import MAX_BENCHMARKS_PER_TENANT

    res = client.post("/api/nesting/benchmarks", headers=HEADERS, json={})
    assert res.status_code == 200
    data = res.json()
    assert "cases" in data
    assert data.get("liveMachineControl") is False
    assert data.get("tenantId") == TENANT

    for i in range(MAX_BENCHMARKS_PER_TENANT + 5):
        platform.physical.record_benchmark({"seq": i}, tenant_id=TENANT)
    platform.physical.record_benchmark({"seq": 0}, tenant_id="other-tenant")

    tenant_rows = [b for b in platform.physical.benchmarks if b.get("tenantId") == TENANT]
    other_rows = [b for b in platform.physical.benchmarks if b.get("tenantId") == "other-tenant"]
    assert len(tenant_rows) == MAX_BENCHMARKS_PER_TENANT
    assert tenant_rows[-1]["seq"] == MAX_BENCHMARKS_PER_TENANT + 4
    assert tenant_rows[0]["seq"] == 5
    assert len(other_rows) == 1
    assert all(b.get("tenantId") for b in platform.physical.benchmarks)


def test_confirm_dialog_resets_return_value_before_opening() -> None:
    # Esc keeps the previous returnValue; without a reset, Esc after an earlier "ok" would confirm.
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/materials.js").read_text(encoding="utf-8")
    assert js.index("dlg.returnValue = '';") < js.index("dlg.showModal();")
    assert "innerHTML" not in js
    assert "crypto.randomUUID" in js
