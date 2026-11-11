"""Direct unit tests for ProductDigitalTwin and TwinStore (fox3d.twin)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fox3d.ids import new_id
from fox3d.infra import DAM
from fox3d.twin import ProductDigitalTwin, TwinStore


def _store(tmp_path) -> TwinStore:
    return TwinStore(DAM(tmp_path / "dam"))


def _twin(*, tenant_id: str = "tenant-a", sku: str = "SKU-001", **kwargs) -> ProductDigitalTwin:
    return ProductDigitalTwin(tenantId=tenant_id, sku=sku, **kwargs)


def test_content_hash_ignores_dam_asset_id_and_version():
    twin = _twin(dimensions={"width": 10, "depth": 20, "height": 30})
    base = twin.compute_hash()
    twin.damAssetId = "dam-override"
    twin.version = 42
    assert twin.compute_hash() == base


def test_content_hash_changes_when_sku_changes():
    a = _twin(sku="ALPHA", twinId="fixed-id-for-content-hash-sku")
    b = a.model_copy(update={"sku": "BETA"})
    assert a.compute_hash() != b.compute_hash()


def test_content_hash_changes_when_dimensions_change():
    a = _twin(
        dimensions={"width": 1, "depth": 2, "height": 3},
        twinId="fixed-id-for-content-hash-dimensions",
    )
    b = a.model_copy(update={"dimensions": {"width": 9, "depth": 2, "height": 3}})
    assert a.compute_hash() != b.compute_hash()


def test_create_with_glb_bytes_writes_dam_and_sets_dam_asset_id(tmp_path):
    store = _store(tmp_path)
    twin = _twin()
    payload = b"FAKE_GLB_BYTES_FOR_TEST"
    created = store.create(twin, glb_bytes=payload)
    assert created.damAssetId is not None
    obj = store.dam.get(created.damAssetId, tenant_id="tenant-a")
    assert obj.kind == "digital_twin"
    from pathlib import Path

    assert Path(obj.path).read_bytes() == payload


def test_create_without_glb_bytes_keeps_dam_asset_id_none(tmp_path):
    store = _store(tmp_path)
    twin = _twin(glb="/already/on/disk/model.glb")
    created = store.create(twin)
    assert created.damAssetId is None


def test_get_cross_tenant_raises_permission_error(tmp_path):
    store = _store(tmp_path)
    created = store.create(_twin(), glb_bytes=b"glb")
    with pytest.raises(PermissionError, match="tenant isolation"):
        store.get(created.twinId, tenant_id="other-tenant")


def test_get_missing_raises_key_error(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(KeyError):
        store.get("missing-twin-id", tenant_id="tenant-a")


def test_new_version_serialized_payload_clears_dam_asset_id_before_create(tmp_path):
    store = _store(tmp_path)
    v1 = store.create(_twin(sku="V1"), glb_bytes=b"v1-glb")
    assert v1.damAssetId is not None
    current = store.get(v1.twinId, tenant_id="tenant-a")
    data = current.model_dump()
    data.update({"sku": "V2"})
    data["twinId"] = new_id()
    data["version"] = current.version + 1
    data["damAssetId"] = None
    nxt = ProductDigitalTwin.model_validate(data)
    assert nxt.damAssetId is None


def test_new_version_returns_new_identity_with_cleared_dam_asset(tmp_path):
    store = _store(tmp_path)
    v1 = store.create(_twin(), glb_bytes=b"glb-one")
    assert v1.damAssetId is not None
    v2 = store.new_version(v1.twinId, tenant_id="tenant-a", sku="SKU-NEXT")
    assert v2.twinId != v1.twinId
    assert v2.version == v1.version + 1
    assert v2.damAssetId is None
    assert v2.contentHash != v1.contentHash


def test_product_digital_twin_rejects_missing_required_fields():
    with pytest.raises(ValidationError):
        ProductDigitalTwin.model_validate({"sku": "only-sku"})
    with pytest.raises(ValidationError):
        ProductDigitalTwin.model_validate({"tenantId": "only-tenant"})


def test_product_digital_twin_allows_negative_dimensions():
    twin = ProductDigitalTwin(
        tenantId="tenant-a",
        sku="NEG",
        dimensions={"width": -10, "depth": 5, "height": 3},
    )
    assert twin.dimensions["width"] == -10


def test_create_sets_content_hash_from_compute_hash(tmp_path):
    store = _store(tmp_path)
    twin = _twin(glb="/preset.glb")
    created = store.create(twin)
    assert created.contentHash == created.compute_hash()


def test_list_returns_only_matching_tenant(tmp_path):
    store = _store(tmp_path)
    a = store.create(_twin(tenant_id="t-a", sku="A"), glb_bytes=b"a")
    store.create(_twin(tenant_id="t-b", sku="B"), glb_bytes=b"b")
    listed = store.list(tenant_id="t-a")
    assert len(listed) == 1
    assert listed[0].twinId == a.twinId
