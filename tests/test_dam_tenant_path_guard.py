from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.infra import DAM, validate_tenant_id
from fox3d.platform import Platform
from fox3d.twin import ProductDigitalTwin, TwinStore


@pytest.mark.parametrize("tenant", ["../x", "a/b", "a\\b", "..", "x\x00", "", " x", "x ", ".", "system", "a" * 121, "x\x7f"])
def test_invalid_tenant_at_all_storage_boundaries(tmp_path: Path, tenant: str) -> None:
    dam = DAM(tmp_path / "dam")
    with pytest.raises(ValueError):
        dam.put(tenant_id=tenant, kind="test", name="a", data=b"x")
    with pytest.raises(ValueError):
        dam.get("missing", tenant_id=tenant)
    with pytest.raises(ValueError):
        dam.list(tenant_id=tenant)
    store = TwinStore(dam)
    with pytest.raises(ValueError):
        store.create(ProductDigitalTwin(tenantId=tenant, sku="sku"))
    with pytest.raises(ValueError):
        store.get("missing", tenant_id=tenant)
    with pytest.raises(ValueError):
        store.list(tenant_id=tenant)


@pytest.mark.parametrize("tenant", ["sonaqueen-home", "t1", "中文名稱", "a" * 120])
def test_valid_tenant(tmp_path: Path, tenant: str) -> None:
    assert validate_tenant_id(tenant) == tenant
    dam = DAM(tmp_path / "dam")
    obj = dam.put(tenant_id=tenant, kind="test", name="a", data=b"x")
    assert dam.get(obj.asset_id, tenant_id=tenant) == obj
    assert dam.list(tenant_id=tenant) == [obj]


@pytest.mark.parametrize("field", ["kind", "name", "asset_id"])
@pytest.mark.parametrize("value", ["../x", "a/b", "a\\b", "x\x00"])
def test_invalid_path_components(tmp_path: Path, field: str, value: str) -> None:
    dam = DAM(tmp_path / "dam")
    args = {"tenant_id": "t1", "kind": "test", "name": "a", "asset_id": "id", "data": b"x"}
    args[field] = value
    with pytest.raises(ValueError):
        dam.put(**args)  # type: ignore[arg-type]
    if field == "kind":
        with pytest.raises(ValueError):
            dam.list(tenant_id="t1", kind=value)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    dam = DAM(tmp_path / "dam")
    outside = tmp_path / "outside"
    outside.mkdir()
    (dam.root / "t1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        dam.put(tenant_id="t1", kind="test", name="a", data=b"x")
    assert not list(outside.iterdir())


@pytest.mark.parametrize("sku", ["ABC/123", "A\\B", "a/b/c"])
def test_twin_store_accepts_sku_with_path_separators(tmp_path: Path, sku: str) -> None:
    dam = DAM(tmp_path / "dam")
    store = TwinStore(dam)
    twin = store.create(ProductDigitalTwin(tenantId="t1", sku=sku), glb_bytes=b"glb")
    assert twin.sku == sku
    obj = dam.get(twin.damAssetId or twin.twinId, tenant_id="t1")
    assert obj.metadata["sku"] == sku
    assert "/" not in Path(obj.path).name.replace("\\", "/")


def test_api_create_twin_and_upload_accept_sku_with_slashes(tmp_path: Path) -> None:
    platform = Platform(root=tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(platform), raise_server_exceptions=False)
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    created = client.post("/api/digital-twins", json={"sku": "ABC/123"}, headers=headers)
    assert created.status_code == 200, created.text
    assert created.json()["sku"] == "ABC/123"
    uploaded = client.post(
        "/api/digital-twins/upload",
        headers=headers,
        data={"sku": "DEF/456"},
        files={"file": ("a.glb", b"glb")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["twin"]["sku"] == "DEF/456"


def test_api_read_asset_rejects_invalid_tenant_header(tmp_path: Path) -> None:
    platform = Platform(root=tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(platform), raise_server_exceptions=False)
    response = client.get("/api/assets/missing", headers={"X-Tenant-Id": "../x"})
    assert response.status_code == 400


def test_api_read_asset_enforces_tenant_isolation(tmp_path: Path) -> None:
    platform = Platform(root=tmp_path / "data", mock_blender=True)
    asset = platform.dam.put(tenant_id="owner", kind="test", name="asset.png", data=b"private image")
    client = TestClient(create_app(platform))
    url = f"/api/assets/{asset.asset_id}"

    for headers in ({}, {"X-Tenant-Id": ""}, {"X-Tenant-Id": " "}, {"X-Tenant-Id": "../x"}):
        assert client.get(url, headers=headers).status_code == 400
    assert client.get(url, headers={"X-Tenant-Id": "other"}).status_code == 404
    assert client.get("/api/assets/missing", headers={"X-Tenant-Id": "owner"}).status_code == 404
    response = client.get(url, headers={"X-Tenant-Id": "owner"})
    assert response.status_code == 200
    assert response.content == b"private image"
    assert response.headers["content-type"] == "image/png"


def test_api_rejects_escape_and_accepts_upload(tmp_path: Path) -> None:
    platform = Platform(root=tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "../../escape"}
    response = client.post("/api/digital-twins/upload", headers=headers, data={"sku": "sku"}, files={"file": ("a.glb", b"glb")})
    assert response.status_code == 400
    for path, payload in [("/api/render/preview", {"scene": "WHITE_STUDIO"}), ("/api/packaging/structures", {"family": "RSC_CARTON", "render": False})]:
        assert client.post(path, headers=headers, json=payload).status_code == 400
    assert not list(tmp_path.rglob("*escape*"))
    platform.register_node(target_key="mock", name="mock", detected={"blender": True, "cuda": True, "optix": True, "gpuCount": 1, "vramGb": 16, "gpus": [{"gpuIndex": 0, "name": "mock", "vramGb": 16, "freeVramGb": 16}]})
    response = client.post("/api/digital-twins/upload", headers={"X-Tenant-Id": "sonaqueen-home"}, data={"sku": "sku"}, files={"file": ("a.glb", b"glb")})
    assert response.status_code == 200, response.text
