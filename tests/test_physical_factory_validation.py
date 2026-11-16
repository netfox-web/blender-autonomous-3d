from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform


@pytest.fixture
def client_and_platform(tmp_path):
    platform = Platform(root=tmp_path, mock_blender=True)
    return TestClient(create_app(platform)), platform


@pytest.mark.parametrize("path,body", [
    ("packaging/structures", {"productDims": {"width": -5, "height": "abc"}}),
    ("packaging/structures", {"productDims": "x"}),
    ("packaging/structures", {"family": "NOPE"}),
    ("packaging/structures", {"productDims": {"width": 1e9, "height": 1e9, "depth": 1e9}}),
    ("acrylic/products", {"kind": "NOPE"}),
    ("acrylic/products", {"sheetSku": "NOPE"}),
    ("retail/fixtures", {"product": "x"}),
    ("retail/fixtures", {"product": {"dimensions": "x"}}),
    ("retail/fixtures", {"product": {"width": -1}}),
    ("factory/spaces", {"width": "abc"}),
    ("factory/run", {"space": "x"}),
    ("factory/run", {"space": {"width": 100}}),
    ("factory/run", {"productTypes": "x"}),
    ("factory/run", {"productTypes": ["NOPE"]}),
    ("factory/run", {"space": {"width": -1, "depth": 3000}}),
    ("physical-os/approve", {}),
    ("release/advance", {}),
])
def test_invalid_inputs(client_and_platform, path, body):
    client, _ = client_and_platform
    result = client.post('/api/' + path, json=body, headers={"X-Tenant-Id": "a"})
    assert result.status_code == 422
    assert 'Traceback' not in result.text


@pytest.mark.parametrize("field", ["width", "depth", "height"])
@pytest.mark.parametrize("value", [-1, 0, 1e12, None, "nan", True])
def test_space_dimension_boundaries(client_and_platform, field, value):
    client, platform = client_and_platform
    result = client.post('/api/factory/spaces', json={field: value}, headers={"X-Tenant-Id": "a"})
    assert result.status_code == 422
    assert not platform.factory.spaces


@pytest.mark.parametrize("endpoint", ["physical-os/approve", "release/advance"])
@pytest.mark.parametrize("value", [None, "", " ", "../x", 12, "x/y"])
def test_invalid_entity_id(client_and_platform, endpoint, value):
    client, _ = client_and_platform
    assert client.post('/api/' + endpoint, json={"entityId": value}, headers={"X-Tenant-Id": "a"}).status_code == 422


@pytest.mark.parametrize("endpoint,id_key", [("acrylic/products", "productId"), ("packaging/structures", "packageId"), ("retail/fixtures", "fixtureId")])
def test_approval_ownership(client_and_platform, endpoint, id_key):
    client, platform = client_and_platform
    created = client.post('/api/' + endpoint, json={}, headers={"X-Tenant-Id": "a"})
    assert created.status_code == 200
    entity = created.json()[id_key]
    assert client.post('/api/physical-os/approve', json={"entityId": entity}, headers={"X-Tenant-Id": "b"}).status_code == 404
    response = client.post('/api/physical-os/approve', json={"entityId": entity}, headers={"X-Tenant-Id": "a"})
    assert response.status_code == 200
    assert response.json()['audit']['tenantId'] == 'a'
    assert ('a', entity) in platform.physical.approvals


def test_same_unknown_id_is_tenant_scoped(client_and_platform):
    client, platform = client_and_platform
    for tenant in ('a', 'b'):
        result = client.post('/api/physical-os/approve', json={"entityId": "shared", "actor": tenant}, headers={"X-Tenant-Id": tenant})
        assert result.status_code == 200
        assert result.json()['tenantId'] == tenant
    assert platform.physical.approvals[('a', 'shared')]['actor'] == 'a'
    assert platform.physical.approvals[('b', 'shared')]['actor'] == 'b'


def test_valid_packaging_preserves_engineering_hash(client_and_platform):
    client, platform = client_and_platform
    dims = {"width": 120, "height": 80, "depth": 40}
    expected = platform.physical.packaging.build(tenant_id='a', family='RSC_CARTON', product_dims=dims)
    actual = client.post('/api/packaging/structures', json={"productDims": dims}, headers={"X-Tenant-Id": "a"})
    assert actual.status_code == 200
    assert actual.json()["engineering"]["engineeringHash"] == expected["engineering"]["engineeringHash"]


@pytest.mark.parametrize("path,body,expected", [
    ("packaging/structures", {"family": "NOPE"}, "RSC_CARTON"),
    ("retail/fixtures", {"family": "NOPE"}, "COUNTER_DISPLAY"),
    ("acrylic/products", {"kind": "NOPE"}, "MENU_STAND"),
    ("acrylic/products", {"sheetSku": "NOPE"}, "ACR_CLEAR_5"),
    ("factory/run", {"productTypes": ["NOPE"]}, "STORAGE_CABINET"),
])
def test_unknown_values_list_choices(client_and_platform, path, body, expected):
    client, _ = client_and_platform
    result = client.post('/api/' + path, json=body, headers={"X-Tenant-Id": "a"})
    assert result.status_code == 422
    assert expected in result.json()['detail']


@pytest.mark.parametrize("endpoint,body", [
    ("packaging/structures", {"productDims": {"width": 0}}),
    ("packaging/structures", {"productDims": {"depth": None}}),
    ("retail/fixtures", {"product": {"dimensions": {"height": 1e9}}}),
    ("acrylic/products", {"width": -1}),
    ("factory/run", {"space": {"width": 3000, "depth": 0}}),
])
def test_other_invalid_dimensions(client_and_platform, endpoint, body):
    client, _ = client_and_platform
    assert client.post('/api/' + endpoint, json=body, headers={"X-Tenant-Id": "a"}).status_code == 422
