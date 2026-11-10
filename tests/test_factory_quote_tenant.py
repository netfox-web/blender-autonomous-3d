"""Factory quotes are tenant-scoped: another tenant can neither read nor approve them."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fox3d.api import create_app


def _run(client: TestClient, tenant: str) -> dict:
    res = client.post("/api/factory/run", json={"text": "鞋櫃", "render": False}, headers={"X-Tenant-Id": tenant})
    assert res.status_code == 200
    return res.json()


def test_quote_read_and_approve_are_tenant_scoped(platform) -> None:  # noqa: ANN001 - conftest fixture
    client = TestClient(create_app(platform))
    run = _run(client, "t1")
    quote_id = run["quote"]["quoteId"]

    assert client.get(f"/api/factory/quotes/{quote_id}", headers={"X-Tenant-Id": "t1"}).status_code == 200
    # other tenant: same answer as an unknown id, and nothing changes
    assert client.get(f"/api/factory/quotes/{quote_id}", headers={"X-Tenant-Id": "other"}).status_code == 404
    assert client.post(f"/api/factory/quotes/{quote_id}/approve", json={"actor": "x"}, headers={"X-Tenant-Id": "other"}).status_code == 404
    assert platform.factory.runs[run["runId"]]["gate"]["status"] == "WAITING_APPROVAL"
    # no tenant header at all
    assert client.get(f"/api/factory/quotes/{quote_id}").status_code == 400
    assert client.post(f"/api/factory/quotes/{quote_id}/approve", json={}).status_code == 400
    # body tenant must match the header
    assert client.post(f"/api/factory/quotes/{quote_id}/approve", json={"tenantId": "other"}, headers={"X-Tenant-Id": "t1"}).status_code == 403

    ok = client.post(f"/api/factory/quotes/{quote_id}/approve", json={"actor": "ops"}, headers={"X-Tenant-Id": "t1"})
    assert ok.status_code == 200 and ok.json()["gate"]["status"] == "APPROVED"
    # approving twice is a conflict, not a 500
    assert client.post(f"/api/factory/quotes/{quote_id}/approve", json={"actor": "ops"}, headers={"X-Tenant-Id": "t1"}).status_code == 409


def test_revise_unknown_or_foreign_product_is_404_not_500(platform) -> None:  # noqa: ANN001 - conftest fixture
    client = TestClient(create_app(platform))
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 800})
    product_id = created["spec"]["productId"]
    assert client.post(f"/api/factory/products/{product_id}/revise", json={"width": 900}, headers={"X-Tenant-Id": "other"}).status_code == 404
    assert client.post("/api/factory/products/no-such-product/revise", json={"width": 900}, headers={"X-Tenant-Id": "t1"}).status_code == 404
    assert client.post(f"/api/factory/products/{product_id}/revise", json={"width": 900}, headers={"X-Tenant-Id": "t1"}).status_code == 200
