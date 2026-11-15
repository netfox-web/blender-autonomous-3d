import struct

import pytest

from fox3d.publish import CatalogRelease, ar_export_boundary, glb_publication, web3d_manifest


def test_glb_publication_valid_and_missing(tmp_path):
    path = tmp_path / "model.glb"
    assert glb_publication({}, path) == {"ok": False, "label": "BLOCKED", "error": "missing_glb"}
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
    result = glb_publication({"dimensions": {"width": 1, "height": 2, "depth": 3}}, path)
    assert result["ok"] and result["label"] == "REAL"
    assert result["dimsValid"] and result["size"] == 12


@pytest.mark.parametrize("content", [b"", b"glTF", b"xxxx" + bytes(8), b"glTF" + bytes(7)])
def test_invalid_glb_is_blocked(tmp_path, content):
    path = tmp_path / "model.glb"
    path.write_bytes(content)
    assert glb_publication({}, path) == {"ok": False, "label": "BLOCKED", "error": "invalid_glb"}


@pytest.mark.parametrize("dimensions", [
    {}, {"width": 1, "height": 2}, {"width": 0, "height": 2, "depth": 3},
    {"width": -1, "height": 2, "depth": 3}, {"width": float("nan"), "height": 2, "depth": 3},
    {"width": float("inf"), "height": 2, "depth": 3}, {"width": "1", "height": 2, "depth": 3},
    {"width": True, "height": 2, "depth": 3},
])
def test_invalid_dimensions(tmp_path, dimensions):
    path = tmp_path / "model.glb"
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
    assert glb_publication({"dimensions": dimensions}, path)["dimsValid"] is False


def test_catalog_integrity():
    catalog = CatalogRelease()
    sku = catalog.add_sku({"productId": "sku", "engineeringHash": "hash"}, family="chair")
    assert catalog.add_sku({"productId": "sku", "engineeringHash": "hash"}, family="chair") == sku
    with pytest.raises(ValueError):
        catalog.add_sku({"productId": "sku", "engineeringHash": "other"}, family="chair")
    assert catalog.skus["sku"] == sku
    with pytest.raises(KeyError):
        catalog.release(name="bad", sku_ids=["sku", "unknown"])
    assert not catalog.releases
    first = catalog.release(name="first", sku_ids=["sku"])
    second = catalog.release(name="second", sku_ids=["sku"])
    with pytest.raises(KeyError):
        catalog.supersede(first["releaseId"], successor="unknown")
    assert first["status"] == "active"
    catalog.supersede(first["releaseId"], successor=second["releaseId"])
    assert first["status"] == "superseded" and first["supersededBy"] == second["releaseId"]
    with pytest.raises(ValueError):
        catalog.supersede(first["releaseId"], successor=second["releaseId"])


def test_manifest_and_ar_boundary(tmp_path):
    manifest = web3d_manifest(twin={"dimensions": {"width": 1}}, glb=None)
    assert manifest["glbRef"] is None and manifest["glbHash"] is None
    assert manifest["arRuntime"] == "PARTIAL"
    for result in (None, {"usdz": str(tmp_path / "missing.usdz")}):
        boundary = ar_export_boundary(result)
        assert boundary["label"] == "PARTIAL" and boundary["usdzProduced"] is False
        assert "artifact" not in boundary and "usdz" not in boundary
    path = tmp_path / "model.usdz"
    path.write_bytes(b"fixture")
    assert ar_export_boundary({"usdz": str(path)}) == {"label": "REAL", "artifact": str(path)}
    assert web3d_manifest(twin={}, glb={"path": "model.glb", "hash": "hash"}, variants=["red"])["variantIds"] == ["red"]
