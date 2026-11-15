from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.kd import FlatPackProductTypeRegistry

HEADERS = {"X-Tenant-Id": "acme"}


@pytest.fixture
def client(platform):
    return TestClient(create_app(platform), raise_server_exceptions=False)


@pytest.mark.parametrize("field", ["width", "height", "depth", "boardThickness", "backThickness"])
@pytest.mark.parametrize("value", [-100, 0, "inf", "nan", "abc", 1e9, None])
def test_parametric_invalid_dimensions(client, field, value):
    response = client.post("/api/parametric/products", headers=HEADERS, json={field: value})
    assert response.status_code == 422, response.text
    assert field in response.json()["detail"]
    assert "traceback" not in response.text.lower()


@pytest.mark.parametrize("field", ["doorCount", "shelfCount", "drawerCount"])
@pytest.mark.parametrize("value", [-1, 101, 1.5, "abc", None])
def test_parametric_invalid_counts(client, field, value):
    response = client.post("/api/parametric/products", headers=HEADERS, json={field: value})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("field", ["width", "height", "depth"])
@pytest.mark.parametrize("value", [-100, 0, "inf", "nan", "abc", 1e9, None])
def test_resize_invalid_dimensions(client, field, value):
    created = client.post("/api/parametric/products", headers=HEADERS, json={}).json()
    response = client.post(f'/api/parametric/products/{created["spec"]["productId"]}/resize', headers=HEADERS, json={field: value, "render": False})
    assert response.status_code == 422, response.text
    assert field in response.json()["detail"]


@pytest.mark.parametrize("field,value", [("width", "abc"), ("height", "inf"), ("depth", "nan")])
def test_kd_invalid_dimensions(client, field, value):
    response = client.post("/api/kd/skus", headers=HEADERS, json={field: value})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("value", ["abc", float("inf"), float("nan"), True])
def test_snap_rejects_invalid_numbers(value):
    with pytest.raises(ValueError):
        FlatPackProductTypeRegistry().snap("BEDSIDE_CABINET", width=value)


@pytest.mark.parametrize("path,field", [("/api/product-rd/generate", "variantCount"), ("/api/retail/fixtures", "facing")])
@pytest.mark.parametrize("value", ["abc", -4, -3, 0, 101, 100000, 1.5, True])
def test_invalid_counts(client, path, field, value):
    response = client.post(path, headers=HEADERS, json={field: value})
    assert response.status_code == 422, response.text
    assert "traceback" not in response.text.lower()


@pytest.mark.parametrize("body,expected", [({}, "731cb2ef8d86a9f725c8a528dc2b3697c399d1c994de9884ff12a785dcc42e0d"), ({"width": 1, "height": 1, "depth": 1, "boardThickness": 1, "backThickness": 1, "doorCount": 0, "shelfCount": 0, "drawerCount": 0}, "e62400b6616f64f1741765eb9969d3fd2d06f4b6d01fde1058481b3361537c8e")])
def test_valid_hash_unchanged(client, body, expected, monkeypatch):
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=1))
    response = client.post("/api/parametric/products", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["engineeringHash"] == expected


@pytest.mark.parametrize("path", ["/api/parametric/products", "/api/kd/skus", "/api/product-rd/generate", "/api/retail/fixtures"])
def test_tenant_mismatch(client, path):
    response = client.post(path, headers=HEADERS, json={"tenantId": "other"})
    assert response.status_code == 403, response.text


def test_resize_tenant_mismatch(client):
    created = client.post("/api/parametric/products", headers=HEADERS, json={}).json()
    response = client.post(f'/api/parametric/products/{created["spec"]["productId"]}/resize', headers=HEADERS, json={"tenantId": "other"})
    assert response.status_code == 403, response.text


def test_oversize_is_rejected_before_bay_generation(client, monkeypatch):
    def unexpected_bays(*args, **kwargs):
        raise AssertionError("oversized input reached geometry generation")

    monkeypatch.setattr("fox3d.parametric._bay_count", unexpected_bays)
    response = client.post("/api/parametric/products", headers=HEADERS, json={"width": 1e9})
    assert response.status_code == 422, response.text
