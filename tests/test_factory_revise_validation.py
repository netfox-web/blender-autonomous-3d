from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", "abc"),
        ("shelfCount", "x"),
        ("material", 123),
        ("shelfCount", -3),
        ("doorCount", -1),
        ("drawerCount", -1),
        ("width", 0),
        ("height", None),
        ("topFillerHeight", -1),
        ("unknown", 1),
        ("tenant_id", "t1"),
        ("product_id", "other"),
        ("spec", {}),
        ("engine", {}),
    ],
)
def test_invalid_revision_does_not_write(platform, field, value):
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET"})
    product_id = created["spec"]["productId"]
    before = dict(platform.parametrics)
    revisions = list(platform.factory.revisions)
    response = TestClient(create_app(platform)).post(
        f"/api/factory/products/{product_id}/revise", headers={"X-Tenant-Id": "t1"}, json={field: value}
    )
    assert response.status_code == 422
    assert field in response.json()["detail"]
    assert platform.parametrics == before
    assert platform.factory.revisions == revisions


def test_valid_revision_and_tenant_isolation(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET"})
    product_id = created["spec"]["productId"]
    client = TestClient(create_app(platform))
    before = dict(platform.parametrics)
    revisions = list(platform.factory.revisions)
    denied = client.post(f"/api/factory/products/{product_id}/revise", headers={"X-Tenant-Id": "t2"}, json={"width": "abc"})
    assert denied.status_code == 404
    assert platform.parametrics == before
    assert platform.factory.revisions == revisions
    response = client.post(f"/api/factory/products/{product_id}/revise", headers={"X-Tenant-Id": "t1"}, json={"width": 900})
    assert response.status_code == 200
    assert response.json()["spec"]["width"] == 900
    assert response.json()["spec"]["revision"] == created["spec"]["revision"] + 1
    assert len(platform.parametrics) == len(before) + 1
    assert len(platform.factory.revisions) == len(revisions) + 1
