"""Guards for Poly Haven asset ID validation, include path confinement, and catalog registration."""
from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d import photoreal_assets
from fox3d.platform import Platform


@pytest.fixture
def scene_client(platform: Platform) -> TestClient:
    return TestClient(create_app(platform))


@pytest.fixture
def tenant_headers() -> dict[str, str]:
    return {"X-Tenant-Id": "sonaqueen-home"}


def _fake_urlopen_factory(files_payload: dict | None, gltf_body: bytes, include_map: dict[str, bytes]):
    gltf_url = "https://mock-cdn.test/models/guard_test_2k.gltf"
    api_body = json.dumps(
        {
            "gltf": {
                "2k": {
                    "gltf": {
                        "url": gltf_url,
                        "include": {rel: {"url": f"https://mock-cdn.test/include/{idx}"} for idx, rel in enumerate(include_map)},
                    }
                }
            }
        }
    ).encode("utf-8")

    bodies: dict[str, bytes] = {gltf_url: gltf_body, **{f"https://mock-cdn.test/include/{idx}": data for idx, data in enumerate(include_map.values())}}

    def urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        if "api.polyhaven.com/files/" in url:
            if files_payload is None:
                raise HTTPError(url, 404, "not found", {}, io.BytesIO(b"{}"))

            return io.BytesIO(api_body)
        if url in bodies:
            return io.BytesIO(bodies[url])
        if "cdn.polyhaven.com" in url:
            return io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
        raise HTTPError(url, 404, "not found", {}, io.BytesIO(b""))

    return urlopen


def test_invalid_asset_id_returns_422(scene_client: TestClient, tenant_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(photoreal_assets.urllib.request, "urlopen", _fake_urlopen_factory({}, b"x" * 200, {}))
    for bad in ("../escape", "foo/bar", "bad id", "a" * 65, "https://evil.example/a/foo"):
        r = scene_client.post(
            "/api/ecommerce-scenes/polyhaven-fetch",
            headers=tenant_headers,
            json={"assetIdOrUrl": bad, "propType": "SOFA", "label": "x"},
        )
        assert r.status_code == 422, bad


def test_download_failure_does_not_pollute_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_fail_asset"
    assert aid not in photoreal_assets.POLYHAVEN_CURATED_MODELS
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory(None, b"", {}),
    )
    with pytest.raises(ValueError):
        photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
    assert aid not in photoreal_assets.POLYHAVEN_CURATED_MODELS


def test_malicious_includes_stay_inside_model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_safe_asset"
    gltf_body = b'{"asset": {"version": "2.0"}, "buffers": []}' + b" " * 200
    include_map = {
        "textures/ok.png": b"OKBYTES",
        "../../outside.png": b"EVIL",
        "/etc/passwd": b"ABS",
    }
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    try:
        photoreal_assets.download_custom_polyhaven_asset(
            f"https://polyhaven.com/a/{aid}",
            prop_type="SOFA",
            label="Guard test",
            root_dir=tmp_path,
        )
        model_root = tmp_path / "assets" / "models" / "polyhaven"
        assert (model_root / aid / f"{aid}_2k.gltf").exists()
        assert (model_root / aid / "textures" / "ok.png").read_bytes() == b"OKBYTES"
        assert not (model_root.parent / "outside.png").exists()
        asset_dir = (model_root / aid).resolve()
        for path in tmp_path.rglob("*"):
            if not path.is_file():
                continue
            if path.name in (f"{aid}_2k.gltf",) or path.is_relative_to(asset_dir):
                continue
            if path.suffix == ".png" and "thumbs" in path.parts:
                continue
            pytest.fail(f"unexpected file outside asset dir: {path}")
    finally:
        photoreal_assets.POLYHAVEN_CURATED_MODELS.pop(aid, None)


def test_valid_asset_id_completes_and_registers_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_ok_asset"
    gltf_body = b'{"asset": {"version": "2.0"}}' + b" " * 200
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"TEX"}),
    )
    try:
        out = photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
        assert out["ready"] is True
        assert out["assetId"] == aid
        assert aid in photoreal_assets.POLYHAVEN_CURATED_MODELS
        assert Path(out["gltfPath"]).exists()
    finally:
        photoreal_assets.POLYHAVEN_CURATED_MODELS.pop(aid, None)
