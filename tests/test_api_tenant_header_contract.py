"""Contract for tenant headers on the routes defined directly in fox3d.api.

Requests use valid bodies so FastAPI body validation does not precede the header check.
Other routers have their own contracts.
"""
import re

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app

# Each listed endpoint returns 400 / "X-Tenant-Id 無效" for missing,
# empty, whitespace-only, or malformed headers, except OPTIONAL below.
ROUTES = [
    ('POST', '/api/3d/jobs'),
    ('GET', '/api/3d/jobs'),
    ('GET', '/api/3d/jobs/{job_id}'),
    ('POST', '/api/3d/jobs/{job_id}/cancel'),
    ('GET', '/api/assets/{asset_id}'),
    ('POST', '/api/digital-twins'),
    ('POST', '/api/digital-twins/upload'),
    ('GET', '/api/digital-twins/{twin_id}'),
    ('POST', '/api/digital-twins/{twin_id}/preview'),
    ('POST', '/api/digital-twins/{twin_id}/360'),
    ('POST', '/api/parametric/products'),
    ('POST', '/api/parametric/products/{product_id}/resize'),
    ('POST', '/api/parametric/products/{product_id}/variants'),
    ('POST', '/api/render/preview'),
    ('POST', '/api/render/final'),
    ('POST', '/api/product-rd/generate'),
    ('POST', '/api/factory/spaces'),
    ('POST', '/api/factory/run'),
    ('GET', '/api/factory/quotes/{quote_id}'),
    ('POST', '/api/factory/quotes/{quote_id}/approve'),
    ('POST', '/api/factory/products/{product_id}/revise'),
    ('POST', '/api/kd/skus'),
    ('POST', '/api/kd/catalog'),
    ('GET', '/api/materials'),
    ('POST', '/api/materials/lots'),
    ('GET', '/api/remnants'),
    ('POST', '/api/remnants/{remnant_id}/reserve'),
    ('POST', '/api/nesting/benchmarks'),
    ('POST', '/api/kd/candidates'),
    ('POST', '/api/retail/fixtures'),
    ('POST', '/api/packaging/structures'),
    ('POST', '/api/acrylic/products'),
    ('POST', '/api/physical-os/approve'),
    ('POST', '/api/release/advance'),
    ('POST', '/api/commerce/import'),
    ('POST', '/api/safety/evaluate'),
    ('GET', '/api/pilot/console'),
    ('GET', '/api/pilot/work-orders'),
    ('GET', '/api/pilot/batches'),
    ('GET', '/api/pilot/batches/board'),
    ('POST', '/api/pilot/work-orders/{work_order_id}/reserve'),
    ('POST', '/api/pilot/receipts'),
    ('POST', '/api/pilot/purchase-requests'),
    ('GET', '/api/pilot/health'),
    ('GET', '/api/pilot/operator'),
    ('POST', '/api/pilot/scan'),
    ('POST', '/api/pilot/stations'),
    ('POST', '/api/pilot/stations/{station_id}/heartbeat'),
    ('POST', '/api/pilot/dispatch'),
    ('POST', '/api/pilot/leases/{lease_id}/ack'),
    ('POST', '/api/pilot/leases/{lease_id}/start'),
    ('POST', '/api/pilot/leases/{lease_id}/complete'),
    ('GET', '/api/pilot/exceptions'),
    ('POST', '/api/pilot/import'),
    ('GET', '/api/pilot/export'),
    ('POST', '/api/pilot/work-orders/{work_order_id}/consume'),
    ('POST', '/api/pilot/work-orders/{work_order_id}/complete'),
    ('GET', '/api/pilot/scan-token/{kind}/{object_id}'),
]
OPTIONAL = {("GET", "/api/assets/{asset_id}"), ("GET", "/api/materials")}


@pytest.fixture
def client(platform):
    return TestClient(create_app(platform))


def test_route_inventory(client):
    # Detect new or removed direct endpoints that need an explicit contract.
    actual = {
        (method, route.path)
        for route in client.app.routes
        if getattr(route, "endpoint", None)
        and route.endpoint.__qualname__.startswith("create_app.<locals>.")
        and "x_tenant_id" in route.endpoint.__annotations__
        for method in route.methods
    }
    assert actual == set(ROUTES)


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("header", [None, "", "  ", "../invalid"])
def test_tenant_header_contract(client, method, path, header):
    url = re.sub(r"\{[^}]+\}", "missing", path)
    headers = {} if header is None else {"X-Tenant-Id": header}
    kwargs = {}
    if method == "POST":
        if path == "/api/digital-twins/upload":
            kwargs = {"data": {"sku": "sku"}, "files": {"file": ("test.glb", b"glb")}}
        else:
            kwargs = {"json": {}}
    response = client.request(method, url, headers=headers, **kwargs)
    if (method, path) in OPTIONAL and header in (None, ""):
        if path == "/api/materials":
            assert response.status_code == 200
            assert "detail" not in response.json()
        else:
            assert response.status_code == 404
            assert response.json() == {"detail": "'missing'"}
    else:
        assert response.status_code == 400
        assert response.json() == {"detail": "X-Tenant-Id 無效"}
