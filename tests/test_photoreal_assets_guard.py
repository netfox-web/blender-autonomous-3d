"""Guards for Poly Haven asset ID validation, include path confinement, and catalog registration."""
from __future__ import annotations

import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _fake_urlopen_factory(
    files_payload: dict | None,
    gltf_body: bytes,
    include_map: dict[str, bytes],
    *,
    include_meta: dict[str, dict] | None = None,
    failing_include_urls: frozenset[str] | None = None,
):
    gltf_url = "https://mock-cdn.test/models/guard_test_2k.gltf"
    include_spec: dict[str, dict] = {}
    for idx, rel in enumerate(include_map):
        include_spec[rel] = (include_meta or {}).get(rel, {"url": f"https://mock-cdn.test/include/{idx}"})
    api_body = json.dumps(
        {
            "gltf": {
                "2k": {
                    "gltf": {
                        "url": gltf_url,
                        "include": include_spec,
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
        if failing_include_urls and url in failing_include_urls:
            raise HTTPError(url, 503, "unavailable", {}, io.BytesIO(b""))
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
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    try:
        with pytest.raises(ValueError):
            photoreal_assets.download_custom_polyhaven_asset(
                f"https://polyhaven.com/a/{aid}",
                prop_type="SOFA",
                label="Guard test",
                root_dir=tmp_path,
            )
        assert aid not in photoreal_assets.POLYHAVEN_CURATED_MODELS
        assert not (model_root.parent / "outside.png").exists()
        asset_dir = (model_root / aid).resolve()
        for path in tmp_path.rglob("*"):
            if not path.is_file():
                continue
            if path.is_relative_to(asset_dir):
                continue
            if path.suffix == ".png" and "thumbs" in path.parts:
                continue
            pytest.fail(f"unexpected file outside asset dir: {path}")
    finally:
        photoreal_assets.POLYHAVEN_CURATED_MODELS.pop(aid, None)


def test_include_download_failure_does_not_register(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_include_fail"
    gltf_body = b'{"asset": {"version": "2.0"}}' + b" " * 200
    include_map = {"textures/albedo.png": b"TEX"}
    fail_url = "https://mock-cdn.test/include/0"
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory(
            {"gltf": {}},
            gltf_body,
            include_map,
            failing_include_urls=frozenset({fail_url}),
        ),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    partial_gltf = model_root / aid / f"{aid}_2k.gltf"
    partial_gltf.parent.mkdir(parents=True, exist_ok=True)
    partial_gltf.write_bytes(gltf_body)
    assert aid not in photoreal_assets.POLYHAVEN_CURATED_MODELS
    with pytest.raises(ValueError):
        photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
    assert aid not in photoreal_assets.POLYHAVEN_CURATED_MODELS
    assert not (model_root / aid / "textures" / "albedo.png").exists()


def test_retry_after_include_failure_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_retry_asset"
    gltf_body = b'{"asset": {"version": "2.0"}}' + b" " * 200
    include_map = {"textures/albedo.png": b"TEX"}
    fail_url = "https://mock-cdn.test/include/0"
    state = {"fail_once": True}

    base_urlopen = _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map)

    def urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        if state["fail_once"] and url == fail_url:
            state["fail_once"] = False
            raise HTTPError(url, 503, "unavailable", {}, io.BytesIO(b""))
        return base_urlopen(req, timeout=timeout)

    monkeypatch.setattr(photoreal_assets.urllib.request, "urlopen", urlopen)
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    partial_gltf = model_root / aid / f"{aid}_2k.gltf"
    partial_gltf.parent.mkdir(parents=True, exist_ok=True)
    partial_gltf.write_bytes(gltf_body)

    with pytest.raises(ValueError):
        photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
    assert aid not in photoreal_assets.POLYHAVEN_CURATED_MODELS

    try:
        out = photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
        assert out["ready"] is True
        assert (model_root / aid / "textures" / "albedo.png").read_bytes() == b"TEX"
        assert photoreal_assets._polyhaven_cache_complete(model_root / aid, partial_gltf)
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


def test_missing_include_url_fails_without_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_missing_url"
    gltf_body = b'{"asset": {"version": "2.0"}}' + b" " * 200
    include_map = {"textures/albedo.png": b"UNUSED"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory(
            {"gltf": {}},
            gltf_body,
            include_map,
            include_meta={"textures/albedo.png": {}},
        ),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    with pytest.raises(ValueError):
        photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
    assert aid not in photoreal_assets.POLYHAVEN_CURATED_MODELS
    manifest = model_root / aid / photoreal_assets._POLYHAVEN_MANIFEST_NAME
    assert not manifest.exists()
    assert not (model_root / aid / "textures" / "albedo.png").exists()


def test_parallel_downloads_same_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_parallel"
    gltf_body = b'{"asset": {"version": "2.0"}}' + b" " * 200
    include_map = {"textures/albedo.png": b"TEX", "textures/normal.png": b"NORM"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    gltf_file = model_root / aid / f"{aid}_2k.gltf"
    errors: list[BaseException] = []

    def worker():
        try:
            photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
        except BaseException as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(worker) for _ in range(4)]
        for fut in as_completed(futs):
            fut.result()
    assert not errors
    assert gltf_file.exists()
    assert (model_root / aid / "textures" / "albedo.png").read_bytes() == b"TEX"
    assert (model_root / aid / "textures" / "normal.png").read_bytes() == b"NORM"
    assert photoreal_assets._polyhaven_cache_complete(model_root / aid, gltf_file)
    staging_leftovers = list(model_root.parent.glob(".ph-staging-*"))
    assert not staging_leftovers, staging_leftovers


def test_publish_failure_does_not_mark_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_publish_fail"
    gltf_body = b'{"asset": {"version": "2.0"}}' + b" " * 200
    include_map = {"textures/albedo.png": b"TEX"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    old_gltf = b'{"old": true}' + b" " * 200
    model_dir.mkdir(parents=True)
    (model_dir / "textures").mkdir()
    gltf_file.write_bytes(old_gltf)
    (model_dir / "textures" / "albedo.png").write_bytes(b"OLD")

    original_publish = photoreal_assets._polyhaven_atomic_publish

    def flaky_publish(target: Path, staging: Path) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr(photoreal_assets, "_polyhaven_atomic_publish", flaky_publish)
    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    assert aid not in paths
    assert gltf_file.read_bytes() == old_gltf
    assert (model_dir / "textures" / "albedo.png").read_bytes() == b"OLD"
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)

    monkeypatch.setattr(photoreal_assets, "_polyhaven_atomic_publish", original_publish)
    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    assert aid in paths
    assert photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)


def test_concurrent_read_during_publish_never_sees_mixed_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_concurrent_read"
    gltf_body = b'{"asset": {"version": "2.0"}}' + b" " * 200
    include_map = {"textures/albedo.png": b"TEX"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    publish_enter = threading.Event()
    allow_publish = threading.Event()
    mixed_observed = threading.Event()

    original_publish = photoreal_assets._polyhaven_atomic_publish

    def slow_publish(target: Path, staging: Path) -> None:
        publish_enter.set()
        allow_publish.wait(timeout=5)
        original_publish(target, staging)

    def reader():
        while not publish_enter.wait(timeout=2):
            continue
        if not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file):
            return
        tex = model_dir / "textures" / "albedo.png"
        if tex.exists() and tex.read_bytes() != b"TEX":
            mixed_observed.set()

    monkeypatch.setattr(photoreal_assets, "_polyhaven_atomic_publish", slow_publish)
    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    try:
        paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
        allow_publish.set()
        reader_thread.join(timeout=5)
        assert aid in paths
        assert not mixed_observed.is_set()
        assert photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    finally:
        allow_publish.set()
        reader_thread.join(timeout=2)
