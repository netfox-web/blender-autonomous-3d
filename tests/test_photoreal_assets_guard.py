"""Guards for Poly Haven asset ID validation, include path confinement, and catalog registration."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d import photoreal_assets
from fox3d.platform import Platform
from fox3d.polyhaven_paths import (
    POLYHAVEN_CATALOG_NAME,
    POLYHAVEN_VERSIONS_DIR,
    resolve_polyhaven_bundle_paths,
    resolve_polyhaven_asset_ref_path,
)


@pytest.fixture
def scene_client(platform: Platform) -> TestClient:
    return TestClient(create_app(platform))


@pytest.fixture
def tenant_headers() -> dict[str, str]:
    return {"X-Tenant-Id": "sonaqueen-home"}


def _gltf_body_with_buffer(uri: str, byte_length: int) -> bytes:
    doc = {"asset": {"version": "2.0"}, "buffers": [{"uri": uri, "byteLength": byte_length}]}
    raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    if len(raw) <= photoreal_assets._POLYHAVEN_MIN_GLTF_BYTES:
        raw += b" " * (photoreal_assets._POLYHAVEN_MIN_GLTF_BYTES - len(raw) + 1)
    return raw


def _gltf_body_with_uris(*external_uris: str) -> bytes:
    images: list[dict[str, str]] = []
    buffers: list[dict[str, str]] = []
    for uri in external_uris:
        if uri.lower().endswith((".png", ".jpg", ".jpeg", ".ktx2", ".webp")):
            images.append({"uri": uri})
        else:
            buffers.append({"uri": uri})
    doc = {"asset": {"version": "2.0"}, "buffers": buffers, "images": images}
    raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    if len(raw) <= photoreal_assets._POLYHAVEN_MIN_GLTF_BYTES:
        raw += b" " * (photoreal_assets._POLYHAVEN_MIN_GLTF_BYTES - len(raw) + 1)
    return raw


def _bundle_root(model_root: Path, aid: str) -> Path:
    slot = model_root / aid
    gltf_file = slot / f"{aid}_2k.gltf"
    bundle_root, _resolved = resolve_polyhaven_bundle_paths(slot, gltf_file)
    return bundle_root


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
    gltf_body = _gltf_body_with_uris("textures/ok.png", "../../outside.png", "/etc/passwd")
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
            if path.name.endswith(".polyhaven.lock") and path.parent == model_root:
                continue
            pytest.fail(f"unexpected file outside asset dir: {path}")
    finally:
        photoreal_assets.POLYHAVEN_CURATED_MODELS.pop(aid, None)


def test_include_download_failure_does_not_register(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_include_fail"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
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
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
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
        bundle = _bundle_root(model_root, aid)
        assert (bundle / "textures" / "albedo.png").read_bytes() == b"TEX"
        assert photoreal_assets._polyhaven_cache_complete(model_root / aid, partial_gltf)
    finally:
        photoreal_assets.POLYHAVEN_CURATED_MODELS.pop(aid, None)


def test_valid_asset_id_completes_and_registers_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_ok_asset"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
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
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
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
    gltf_body = _gltf_body_with_uris("textures/albedo.png", "textures/normal.png")
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
    bundle = _bundle_root(model_root, aid)
    assert bundle.joinpath(gltf_file.name).exists()
    assert (bundle / "textures" / "albedo.png").read_bytes() == b"TEX"
    assert (bundle / "textures" / "normal.png").read_bytes() == b"NORM"
    assert photoreal_assets._polyhaven_cache_complete(model_root / aid, gltf_file)
    staging_leftovers = list(model_root.parent.glob(".ph-staging-*"))
    assert not staging_leftovers, staging_leftovers


def test_publish_failure_does_not_mark_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_publish_fail"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
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
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    include_map = {"textures/albedo.png": b"TEX"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    publish_gate = threading.Event()
    publish_done = threading.Event()
    mixed_observed = threading.Event()

    original_publish = photoreal_assets._polyhaven_atomic_publish

    def slow_publish(target: Path, staging: Path) -> None:
        publish_gate.set()
        original_publish(target, staging)
        publish_done.set()

    def reader():
        assert publish_done.wait(timeout=5), "reader must start only after publish completes"
        bundle_root, pinned_gltf, version = photoreal_assets.pin_polyhaven_bundle(model_dir, gltf_file)
        try:
            if not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file):
                return
            tex = bundle_root / "textures" / "albedo.png"
            if tex.exists() and tex.read_bytes() != b"TEX":
                mixed_observed.set()
            _ = pinned_gltf.read_bytes()
        finally:
            photoreal_assets.unpin_polyhaven_bundle(model_dir, version)

    monkeypatch.setattr(photoreal_assets, "_polyhaven_atomic_publish", slow_publish)
    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    try:
        paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
        assert publish_gate.is_set()
        reader_thread.join(timeout=5)
        assert aid in paths
        assert not mixed_observed.is_set()
        assert photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    finally:
        reader_thread.join(timeout=2)


def test_gltf_external_ref_missing_from_include_map_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_missing_bin"
    gltf_body = _gltf_body_with_uris("missing.bin")
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {}),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    with pytest.raises(ValueError):
        photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    assert not (model_dir / photoreal_assets._POLYHAVEN_MANIFEST_NAME).exists()


def test_invalid_gltf_payload_does_not_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_bad_gltf"
    gltf_body = b"not-json-at-all" + b" " * 200
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/x.png": b"X"}),
    )
    with pytest.raises(ValueError):
        photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)


def test_legacy_complete_cache_offline_adopts_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_legacy_ok"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    model_dir.mkdir(parents=True)
    (model_dir / "textures").mkdir()
    gltf_file.write_bytes(gltf_body)
    (model_dir / "textures" / "albedo.png").write_bytes(b"TEX")
    manifest = model_dir / photoreal_assets._POLYHAVEN_MANIFEST_NAME
    assert not manifest.exists()
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    assert photoreal_assets._polyhaven_gltf_bundle_ready(model_dir, gltf_file) is not None

    def fail_network(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        raise HTTPError(url, 503, "offline", {}, io.BytesIO(b""))

    monkeypatch.setattr(photoreal_assets.urllib.request, "urlopen", fail_network)
    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    assert aid in paths
    bundle_dir, resolved_gltf = photoreal_assets._polyhaven_locate_bundle(model_dir, gltf_file.name)
    version_manifest = bundle_dir / photoreal_assets._POLYHAVEN_MANIFEST_NAME
    assert version_manifest.exists()
    assert photoreal_assets._polyhaven_cache_complete(bundle_dir, resolved_gltf)
    includes = json.loads(version_manifest.read_text(encoding="utf-8"))
    assert includes == ["textures/albedo.png"]


def test_legacy_incomplete_cache_offline_still_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_legacy_partial"
    gltf_body = _gltf_body_with_uris("textures/albedo.png", "textures/normal.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    model_dir.mkdir(parents=True)
    (model_dir / "textures").mkdir()
    gltf_file.write_bytes(gltf_body)
    (model_dir / "textures" / "albedo.png").write_bytes(b"TEX")
    assert not (model_dir / photoreal_assets._POLYHAVEN_MANIFEST_NAME).exists()
    assert photoreal_assets._polyhaven_gltf_bundle_ready(model_dir, gltf_file) is None

    def fail_network(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        raise HTTPError(url, 503, "offline", {}, io.BytesIO(b""))

    monkeypatch.setattr(photoreal_assets.urllib.request, "urlopen", fail_network)
    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    assert aid not in paths
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)


def test_cache_complete_false_when_manifest_omits_gltf_dependency(tmp_path: Path):
    aid = "guard_stale_manifest"
    model_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    gltf_file = model_root / f"{aid}_2k.gltf"
    gltf_file.parent.mkdir(parents=True)
    gltf_file.write_bytes(_gltf_body_with_uris("textures/albedo.png", "missing.bin"))
    (model_root / ".polyhaven_complete.json").write_text('["textures/albedo.png"]', encoding="utf-8")
    (model_root / "textures").mkdir()
    (model_root / "textures" / "albedo.png").write_bytes(b"TEX")
    assert not photoreal_assets._polyhaven_cache_complete(model_root, gltf_file)


def test_concurrent_read_pinned_across_catalog_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_catalog_switch"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    switch_ready = threading.Event()
    proceed_switch = threading.Event()
    version_mismatch = threading.Event()

    def first_round(req, timeout=0):
        return _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"OLD_TEX"})(req, timeout=timeout)

    monkeypatch.setattr(photoreal_assets.urllib.request, "urlopen", first_round)
    assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]

    def reader():
        bundle_root, pinned_gltf, version = photoreal_assets.pin_polyhaven_bundle(model_dir, gltf_file)
        try:
            _ = pinned_gltf.read_bytes()
            switch_ready.set()
            assert proceed_switch.wait(timeout=5)
            tex = bundle_root / "textures" / "albedo.png"
            if not tex.exists() or tex.read_bytes() != b"OLD_TEX":
                version_mismatch.set()
        finally:
            photoreal_assets.unpin_polyhaven_bundle(model_dir, version)

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    assert switch_ready.wait(timeout=5)

    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"NEW_TEX"}),
    )
    (model_dir / POLYHAVEN_CATALOG_NAME).unlink(missing_ok=True)
    assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
    proceed_switch.set()
    reader_thread.join(timeout=5)
    bundle = _bundle_root(model_root, aid)
    assert (bundle / "textures" / "albedo.png").read_bytes() == b"NEW_TEX"
    assert not version_mismatch.is_set()


def test_resolve_polyhaven_asset_ref_follows_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_asset_ref"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"TEX"}),
    )
    assets_root = tmp_path / "assets"
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    ref = f"models/polyhaven/{aid}/{aid}_2k.gltf"
    resolved = resolve_polyhaven_asset_ref_path(assets_root, ref)
    assert resolved is not None
    assert resolved.is_file()
    assert resolved.is_relative_to(_bundle_root(assets_root / "models" / "polyhaven", aid))


def test_publish_rename_failure_keeps_old_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_rename_fail"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    include_map = {"textures/albedo.png": b"NEW"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    # Incomplete legacy bundle (missing normal map) so ensure still attempts a download.
    old_gltf = _gltf_body_with_uris("textures/albedo.png", "textures/normal.png")
    old_gltf = json.loads(old_gltf.decode().strip())
    old_gltf["marker"] = "old"
    old_bytes = json.dumps(old_gltf).encode() + b" " * 80
    model_dir.mkdir(parents=True)
    (model_dir / "textures").mkdir()
    gltf_file.write_bytes(old_bytes)
    (model_dir / "textures" / "albedo.png").write_bytes(b"OLD")
    assert photoreal_assets._polyhaven_gltf_bundle_ready(model_dir, gltf_file) is None

    real_rename = Path.rename

    def flaky_rename(self: Path, target: Path) -> None:
        if self.name.startswith(".ph-staging-") and target.parent == model_dir / POLYHAVEN_VERSIONS_DIR:
            raise OSError("simulated version rename failure")
        real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)
    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    assert aid not in paths
    assert gltf_file.read_bytes() == old_bytes
    assert (model_dir / "textures" / "albedo.png").read_bytes() == b"OLD"
    assert not (model_dir / POLYHAVEN_CATALOG_NAME).exists()


def test_polyhaven_download_lock_timeout_exceeds_default_wait_budget():
    assert photoreal_assets._POLYHAVEN_DOWNLOAD_LOCK_TIMEOUT > 30.0 + 45.0 + 20.0


@pytest.mark.parametrize(
    "malicious_uri",
    [
        "guard_main_overwrite_2k.gltf",
        "./guard_main_overwrite_2k.gltf",
        "GUARD_MAIN_OVERWRITE_2K.GLTF",
        ".polyhaven_complete.json",
        "./.polyhaven_complete.json",
    ],
)
def test_include_cannot_target_reserved_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malicious_uri: str
):
    aid = "guard_main_overwrite"
    gltf_body = _gltf_body_with_uris(malicious_uri)
    corrupt_main = b"corrupt" + b" " * 200
    include_map = {malicious_uri: corrupt_main}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    model_dir.mkdir(parents=True)
    gltf_file.write_bytes(b'{"kept": true}' + b" " * 200)
    gltf_entry = {
        "url": "https://mock-cdn.test/models/guard_test_2k.gltf",
        "include": {malicious_uri: {"url": "https://mock-cdn.test/include/0"}},
    }
    headers = {"User-Agent": "test"}

    assert not photoreal_assets._polyhaven_download_bundle(model_dir, gltf_file, gltf_entry, headers)
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    assert gltf_file.read_bytes().startswith(b'{"kept": true}')
    assert not (model_dir / photoreal_assets._POLYHAVEN_MANIFEST_NAME).exists()


def test_staging_integrity_failure_blocks_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_staging_integrity"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    include_map = {"textures/albedo.png": b"TEX"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    publish_called = threading.Event()
    real_publish = photoreal_assets._polyhaven_atomic_publish

    def track_publish(target: Path, staging: Path) -> None:
        publish_called.set()
        real_publish(target, staging)

    monkeypatch.setattr(photoreal_assets, "_polyhaven_atomic_publish", track_publish)
    real_cache_complete = photoreal_assets._polyhaven_cache_complete
    staging_checks = {"n": 0}

    def staging_gate(model_dir_arg: Path, gltf_arg: Path) -> bool:
        staging_checks["n"] += 1
        if model_dir_arg.name.startswith(".ph-staging-"):
            return False
        return real_cache_complete(model_dir_arg, gltf_arg)

    monkeypatch.setattr(photoreal_assets, "_polyhaven_cache_complete", staging_gate)

    req = photoreal_assets.urllib.request.Request(f"https://api.polyhaven.com/files/{aid}")
    # Reuse fake API via ensure_polyhaven_models path: call download_bundle with fetched entry
    api_urlopen = photoreal_assets.urllib.request.urlopen
    raw_api = api_urlopen(req).read()
    gltf_entry = json.loads(raw_api.decode())["gltf"]["2k"]["gltf"]
    assert photoreal_assets._polyhaven_download_bundle(model_dir, gltf_file, gltf_entry, {}) is False
    assert staging_checks["n"] >= 1
    assert not publish_called.is_set()
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)


def test_parallel_download_waits_beyond_default_lock_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_slow_lock"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    include_map = {"textures/albedo.png": b"TEX"}
    base_urlopen = _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map)
  # default FileLock timeout is 30s; hold the lock ~1s while the first worker fetches include
    hold_seconds = 1.0
    download_started = threading.Event()
    release_download = threading.Event()

    def slow_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        if "mock-cdn.test/include/" in url:
            download_started.set()
            assert release_download.wait(timeout=hold_seconds + 5)
            import time

            time.sleep(hold_seconds)
        return base_urlopen(req, timeout=timeout)

    monkeypatch.setattr(photoreal_assets.urllib.request, "urlopen", slow_urlopen)
    monkeypatch.setattr(photoreal_assets, "_POLYHAVEN_DOWNLOAD_LOCK_TIMEOUT", hold_seconds + 2.0)

    model_root = tmp_path / "assets" / "models" / "polyhaven"
    errors: list[BaseException] = []
    results: list[dict[str, str]] = []

    def worker():
        try:
            results.append(photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid]))
        except BaseException as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    assert download_started.wait(timeout=5)
    release_download.set()
    t2.start()
    t1.join(timeout=hold_seconds + 10)
    t2.join(timeout=hold_seconds + 10)
    assert not errors
    assert len(results) == 2
    assert aid in results[0] or aid in results[1]
    gltf_file = model_root / aid / f"{aid}_2k.gltf"
    assert photoreal_assets._polyhaven_cache_complete(model_root / aid, gltf_file)


def test_reserved_asset_id_thumbs_preserves_shared_thumbnails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    thumbs_dir = model_root / "thumbs"
    thumbs_dir.mkdir(parents=True)
    keeper = thumbs_dir / "other_asset.png"
    keeper.write_bytes(b"KEEP_THUMB")

    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"TEX"}),
    )
    for reserved in ("thumbs", "THUMBS", "Thumbs"):
        with pytest.raises(ValueError):
            photoreal_assets.download_custom_polyhaven_asset(reserved, root_dir=tmp_path)
    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=["thumbs"])
    assert "thumbs" not in paths
    assert keeper.read_bytes() == b"KEEP_THUMB"
    assert not (thumbs_dir / "thumbs_2k.gltf").exists()


def test_short_buffer_rejected_until_byte_length_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_short_buffer"
    gltf_body = _gltf_body_with_buffer("meshes/data.bin", 100)
    include_map = {"meshes/data.bin": b"x"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    model_dir.mkdir(parents=True)
    gltf_file.write_bytes(gltf_body)
    (model_dir / "meshes").mkdir(parents=True)
    (model_dir / "meshes" / "data.bin").write_bytes(b"x")
    assert photoreal_assets._polyhaven_gltf_bundle_ready(model_dir, gltf_file) is None

    with pytest.raises(ValueError):
        photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)

    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"meshes/data.bin": b"x" * 100}),
    )
    try:
        out = photoreal_assets.download_custom_polyhaven_asset(aid, root_dir=tmp_path)
        assert out["ready"] is True
        bundle = _bundle_root(model_root, aid)
        assert (bundle / "meshes" / "data.bin").stat().st_size == 100
        assert photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    finally:
        photoreal_assets.POLYHAVEN_CURATED_MODELS.pop(aid, None)


def test_legacy_migration_rejects_reserved_manifest_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_legacy_manifest_dep"
    manifest_name = photoreal_assets._POLYHAVEN_MANIFEST_NAME
    gltf_body = _gltf_body_with_uris(manifest_name)
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    model_dir.mkdir(parents=True)
    gltf_file.write_bytes(gltf_body)
    dep_path = model_dir / manifest_name
    dep_path.write_bytes(b"dependency-payload")
    assert photoreal_assets._polyhaven_gltf_bundle_ready(model_dir, gltf_file) is None
    assert not photoreal_assets._polyhaven_adopt_legacy_cache(model_dir, gltf_file)
    assert dep_path.read_bytes() == b"dependency-payload"
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)

    def fail_network(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        raise HTTPError(url, 503, "offline", {}, io.BytesIO(b""))

    monkeypatch.setattr(photoreal_assets.urllib.request, "urlopen", fail_network)
    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    assert aid not in paths
    assert dep_path.read_bytes() == b"dependency-payload"


def _legacy_cache_with_directory_dependency(tmp_path: Path, aid: str) -> tuple[Path, Path, Path]:
    gltf_body = _gltf_body_with_uris("textures/texture.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    model_dir.mkdir(parents=True)
    gltf_file.write_bytes(gltf_body)
    return model_dir, gltf_file, model_dir / "textures" / "texture.png"


def _assert_legacy_dependency_rejected(tmp_path: Path, monkeypatch, aid, model_dir, gltf_file):
    manifest_path = photoreal_assets._polyhaven_manifest_path(model_dir)
    assert photoreal_assets._polyhaven_gltf_bundle_ready(model_dir, gltf_file) is None
    assert photoreal_assets._polyhaven_adopt_legacy_cache(model_dir, gltf_file) is False
    assert not manifest_path.exists()
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)

    def fail_network(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        raise HTTPError(url, 503, "offline", {}, io.BytesIO(b""))

    monkeypatch.setattr(photoreal_assets.urllib.request, "urlopen", fail_network)
    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    assert aid not in paths
    assert not manifest_path.exists()


def test_legacy_migration_rejects_directory_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_legacy_dir_dep"
    model_dir, gltf_file, dep_path = _legacy_cache_with_directory_dependency(tmp_path, aid)
    dep_path.mkdir(parents=True)
    (dep_path / "inner.bin").write_bytes(b"not-a-texture")
    _assert_legacy_dependency_rejected(tmp_path, monkeypatch, aid, model_dir, gltf_file)


def test_legacy_migration_rejects_symlink_to_directory_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_legacy_symlink_dir_dep"
    model_dir, gltf_file, dep_path = _legacy_cache_with_directory_dependency(tmp_path, aid)
    target_dir = model_dir / "real_dir"
    target_dir.mkdir()
    (target_dir / "inner.bin").write_bytes(b"not-a-texture")
    dep_path.parent.mkdir(parents=True)
    try:
        dep_path.symlink_to(target_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    _assert_legacy_dependency_rejected(tmp_path, monkeypatch, aid, model_dir, gltf_file)


def test_redownload_repairs_corrupt_existing_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_corrupt_version"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    include_map = {"textures/albedo.png": b"FIXED_TEX"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    bundle = _bundle_root(model_root, aid)
    _, resolved_gltf = resolve_polyhaven_bundle_paths(model_dir, gltf_file)
    resolved_gltf.write_bytes(b"{}" + b" " * 200)
    (bundle / "textures" / "albedo.png").unlink(missing_ok=True)
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
    bundle = _bundle_root(model_root, aid)
    assert (bundle / "textures" / "albedo.png").read_bytes() == b"FIXED_TEX"
    assert photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)


def test_pinned_retired_version_survives_catalog_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_pin_prune"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V1"}),
    )
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    first_bundle = _bundle_root(model_root, aid)
    bundle_root, pinned_gltf, version = photoreal_assets.pin_polyhaven_bundle(model_dir, gltf_file)
    try:
        monkeypatch.setattr(
            photoreal_assets.urllib.request,
            "urlopen",
            _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V2"}),
        )
        (model_dir / POLYHAVEN_CATALOG_NAME).unlink(missing_ok=True)
        photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
        assert first_bundle.exists()
        assert (first_bundle / "textures" / "albedo.png").read_bytes() == b"V1"
        _ = pinned_gltf.read_bytes()
    finally:
        photoreal_assets.unpin_polyhaven_bundle(model_dir, version)


def test_blender_worker_resolves_versioned_polyhaven_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import importlib.util

    aid = "guard_worker_ref"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"TEX"}),
    )
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    job_path = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    spec = importlib.util.spec_from_file_location("blender_job_polyhaven", job_path)
    assert spec is not None and spec.loader is not None
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    monkeypatch.setenv("FOX3D_ASSETS_ROOT", str(tmp_path / "assets"))
    ref = bj.resolve_asset_ref(f"assets://models/polyhaven/{aid}/{aid}_2k.gltf")
    assert ref is not None and ref.is_file()
    assert POLYHAVEN_VERSIONS_DIR in ref.parts


def test_furnished_scene_auto_models_use_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import importlib.util

    for aid in ("potted_plant_01", "potted_plant_02", "coffee_table_round_01", "modern_coffee_table_01"):
        gltf_body = _gltf_body_with_uris("textures/albedo.png")
        monkeypatch.setattr(
            photoreal_assets.urllib.request,
            "urlopen",
            _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"TEX"}),
        )
        photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    fs_path = Path(__file__).resolve().parents[1] / "scripts" / "furnished_scene.py"
    spec = importlib.util.spec_from_file_location("furnished_scene_polyhaven", fs_path)
    assert spec is not None and spec.loader is not None
    fs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fs)
    assets_root = tmp_path / "assets"
    resolved = [
        fs._polyhaven_slot_gltf(assets_root, "potted_plant_01", "potted_plant_01_2k.gltf"),
        fs._polyhaven_slot_gltf(assets_root, "potted_plant_02", "potted_plant_02_2k.gltf"),
        fs._polyhaven_slot_gltf(assets_root, "coffee_table_round_01", "coffee_table_round_01_2k.gltf"),
        fs._polyhaven_slot_gltf(assets_root, "modern_coffee_table_01", "modern_coffee_table_01_2k.gltf"),
    ]
    for path in resolved:
        assert path.is_file()
        assert POLYHAVEN_VERSIONS_DIR in path.parts


ROOT = Path(__file__).resolve().parents[1]
_EXECUTOR_JSON = ROOT / "docs" / "fleet" / "blender_scene_render.executor.json"
_POLYHAVEN_PUBLIC_NAMES = (
    "POLYHAVEN_CATALOG_NAME",
    "POLYHAVEN_VERSIONS_DIR",
    "read_polyhaven_catalog",
    "resolve_polyhaven_bundle_paths",
    "resolve_polyhaven_asset_ref_path",
    "acquire_polyhaven_reader_pin",
    "release_polyhaven_reader_pin",
    "listed_polyhaven_reader_pins",
)


def test_polyhaven_paths_worker_module_matches_package():
    import fox3d.polyhaven_paths as pkg

    worker_path = ROOT / "scripts" / "polyhaven_paths.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("worker_polyhaven_paths", worker_path)
    assert spec is not None and spec.loader is not None
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    for name in _POLYHAVEN_PUBLIC_NAMES:
        assert getattr(pkg, name) is not None
        assert getattr(worker, name) is not None


def test_fleet_executor_lists_polyhaven_worker_helpers():
    from fox3d.fleet_blender import BLENDER_SCENE_RENDER_WORKER_SCRIPTS

    doc = json.loads(_EXECUTOR_JSON.read_text(encoding="utf-8"))
    requires = doc["blender_scene_render"]["requires"]
    for script in BLENDER_SCENE_RENDER_WORKER_SCRIPTS:
        needle = f"/scripts/{script}"
        assert any(needle in entry for entry in requires), script


def test_installed_wheel_imports_polyhaven_paths(tmp_path: Path):
    uv = shutil.which("uv")
    if not uv:
        pytest.skip("uv is required to build and install the wheel offline")
    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        [uv, "build", "--wheel", "--offline", "--out-dir", str(wheel_dir), str(ROOT)],
        check=True,
        timeout=120,
    )
    wheel = next(wheel_dir.glob("*.whl"))
    target = tmp_path / "installed"
    subprocess.run(
        [uv, "pip", "install", "--offline", "--no-deps", "--target", str(target), str(wheel)],
        check=True,
        timeout=120,
    )
  # Do not rely on the image's site-packages snapshot (if any) under -I.
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        for entry in sys.argv[1:]:
            sys.path.insert(0, entry)
        import fox3d.polyhaven_paths as ph
        from fox3d import photoreal_assets
        assert ph.POLYHAVEN_CATALOG_NAME
        assert callable(ph.resolve_polyhaven_asset_ref_path)
        assert callable(photoreal_assets.ensure_polyhaven_models)
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [sys.executable, "-I", "-c", script, str(ROOT / "src"), str(target)],
        cwd=tmp_path,
        env=env,
        check=True,
        timeout=30,
    )


def test_isolated_worker_scripts_resolve_polyhaven(tmp_path: Path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in (
        "blender_job.py",
        "worker_polyhaven.py",
        "polyhaven_paths.py",
        "furnished_scene.py",
    ):
        shutil.copy2(ROOT / "scripts" / name, bundle / name)
    aid = "isolated_worker_asset"
    slot = tmp_path / "assets" / "models" / "polyhaven" / aid
    slot.mkdir(parents=True)
    body = _gltf_body_with_uris("textures/albedo.png")
    from unittest.mock import patch

    with patch.object(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, body, {"textures/albedo.png": b"T"}),
    ):
        photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    script = textwrap.dedent(
        f"""
        import os
        import sys
        from pathlib import Path
        sys.path.insert(0, {json.dumps(str(bundle))})
        os.environ["FOX3D_ASSETS_ROOT"] = {json.dumps(str(tmp_path / "assets"))}
        from worker_polyhaven import load_polyhaven_paths
        ph = load_polyhaven_paths()
        ref = ph.resolve_polyhaven_asset_ref_path(
            Path(os.environ["FOX3D_ASSETS_ROOT"]),
            "models/polyhaven/{aid}/{aid}_2k.gltf",
        )
        assert ref is not None and ref.is_file(), ref
        assert "{POLYHAVEN_VERSIONS_DIR}" in ref.parts
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run([sys.executable, "-I", "-c", script], cwd=bundle, env=env, check=True, timeout=30)


def test_cross_process_reader_pin_blocks_prune(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_cross_proc_pin"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V1"}),
    )
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    catalog = json.loads((model_dir / POLYHAVEN_CATALOG_NAME).read_text(encoding="utf-8"))
    version_id = catalog["versionId"]
    pin_script = textwrap.dedent(
        f"""
        import json
        import os
        import sys
        import time
        from pathlib import Path
        sys.path.insert(0, {json.dumps(str(ROOT / "scripts"))})
        os.chdir({json.dumps(str(model_dir))})
        import polyhaven_paths as ph
        slot = Path({json.dumps(str(model_dir))})
        pin = ph.acquire_polyhaven_reader_pin(slot, {json.dumps(version_id)})
        Path({json.dumps(str(tmp_path / "pin_ready"))}).write_text("1", encoding="utf-8")
        while not Path({json.dumps(str(tmp_path / "pin_release"))}).exists():
            time.sleep(0.02)
        ph.release_polyhaven_reader_pin(pin)
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = subprocess.Popen([sys.executable, "-I", "-c", pin_script], env=env)
    try:
        for _ in range(250):
            if (tmp_path / "pin_ready").exists():
                break
            threading.Event().wait(0.02)
        else:
            pytest.fail("subprocess reader pin did not start")
        first_bundle = _bundle_root(model_root, aid)
        monkeypatch.setattr(
            photoreal_assets.urllib.request,
            "urlopen",
            _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V2"}),
        )
        (model_dir / POLYHAVEN_CATALOG_NAME).unlink(missing_ok=True)
        photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
        assert first_bundle.exists()
        assert (first_bundle / "textures" / "albedo.png").read_bytes() == b"V1"
    finally:
        (tmp_path / "pin_release").write_text("1", encoding="utf-8")
        proc.wait(timeout=10)


def test_redownload_repairs_corrupt_main_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_corrupt_main"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    include_map = {"textures/albedo.png": b"FIXED_TEX"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    _, resolved_gltf = resolve_polyhaven_bundle_paths(model_dir, gltf_file)
    resolved_gltf.write_bytes(b"{}" + b" " * 200)
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
    bundle = _bundle_root(model_root, aid)
    _, resolved_after = resolve_polyhaven_bundle_paths(model_dir, gltf_file)
    assert b"buffers" in resolved_after.read_bytes()
    assert (bundle / "textures" / "albedo.png").read_bytes() == b"FIXED_TEX"
    assert photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)


def test_redownload_repairs_corrupt_dependency_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_corrupt_dep"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    include_map = {"textures/albedo.png": b"FIXED_TEX"}
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, include_map),
    )
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    bundle = _bundle_root(model_root, aid)
    (bundle / "textures" / "albedo.png").unlink(missing_ok=True)
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
    bundle = _bundle_root(model_root, aid)
    assert (bundle / "textures" / "albedo.png").read_bytes() == b"FIXED_TEX"
    assert photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)


def test_pinned_read_spans_corrupt_main_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_span_repair_main"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"OLD_TEX"}),
    )
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    bundle_root, pinned_gltf, version = photoreal_assets.pin_polyhaven_bundle(model_dir, gltf_file)
    try:
        _ = pinned_gltf.read_bytes()
        pinned_gltf.write_bytes(b"{}" + b" " * 200)
        assert not photoreal_assets._polyhaven_cache_complete(bundle_root, pinned_gltf)
        monkeypatch.setattr(
            photoreal_assets.urllib.request,
            "urlopen",
            _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"NEW_TEX"}),
        )
        assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
        assert bundle_root.is_dir()
        assert (bundle_root / "textures" / "albedo.png").read_bytes() == b"OLD_TEX"
        new_bundle = _bundle_root(model_root, aid)
        assert new_bundle != bundle_root
        assert (new_bundle / "textures" / "albedo.png").read_bytes() == b"NEW_TEX"
    finally:
        photoreal_assets.unpin_polyhaven_bundle(model_dir, version)


def test_pinned_read_spans_corrupt_dependency_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_span_repair_dep"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"OLD_TEX"}),
    )
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    bundle_root, pinned_gltf, version = photoreal_assets.pin_polyhaven_bundle(model_dir, gltf_file)
    try:
        _ = pinned_gltf.read_bytes()
        (bundle_root / "textures" / "albedo.png").unlink(missing_ok=True)
        assert not photoreal_assets._polyhaven_cache_complete(bundle_root, pinned_gltf)
        monkeypatch.setattr(
            photoreal_assets.urllib.request,
            "urlopen",
            _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"NEW_TEX"}),
        )
        assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
        assert bundle_root.is_dir()
        assert pinned_gltf.is_file()
        assert not (bundle_root / "textures" / "albedo.png").exists()
        assert (_bundle_root(model_root, aid) / "textures" / "albedo.png").read_bytes() == b"NEW_TEX"
    finally:
        photoreal_assets.unpin_polyhaven_bundle(model_dir, version)


def test_legacy_migration_syncs_catalog_for_worker_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fox3d.polyhaven_cache import read_current_version

    aid = "guard_legacy_catalog"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    gltf = asset_root / f"{aid}_2k.gltf"
    gltf.write_bytes(_gltf_body_with_uris("textures/albedo.png"))
    (asset_root / "textures").mkdir()
    (asset_root / "textures" / "albedo.png").write_bytes(b"LEGACY")
    (asset_root / photoreal_assets._POLYHAVEN_MANIFEST_NAME).write_text('["textures/albedo.png"]', encoding="utf-8")
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")),
    )
    assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
    assert read_current_version(asset_root)
    catalog_path = asset_root / POLYHAVEN_CATALOG_NAME
    assert catalog_path.is_file()
    assert not gltf.is_file()
    import importlib.util

    worker_path = Path(__file__).resolve().parents[1] / "scripts" / "polyhaven_paths.py"
    spec = importlib.util.spec_from_file_location("worker_ph_catalog", worker_path)
    assert spec is not None and spec.loader is not None
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    ref = worker.resolve_polyhaven_asset_ref_path(tmp_path / "assets", f"models/polyhaven/{aid}/{aid}_2k.gltf")
    assert ref is not None and ref.is_file()
    assert POLYHAVEN_VERSIONS_DIR in ref.parts


def test_worker_pin_blocks_prune_until_publish_finishes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "guard_worker_pin_publish"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V1"}),
    )
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    first_bundle = _bundle_root(model_root, aid)
    pin_script = textwrap.dedent(
        f"""
        import json
        import os
        import sys
        import time
        from pathlib import Path
        sys.path.insert(0, {json.dumps(str(ROOT / "scripts"))})
        os.chdir({json.dumps(str(ROOT / "scripts"))})
        from worker_polyhaven import load_polyhaven_paths
        ph = load_polyhaven_paths()
        assets = Path({json.dumps(str(tmp_path / "assets"))})
        ref = ph.resolve_polyhaven_asset_ref_path_pinned(assets, "models/polyhaven/{aid}/{aid}_2k.gltf")
        assert ref is not None and ref.is_file()
        ready = Path({json.dumps(str(tmp_path / "worker_pinned"))})
        ready.write_text(str(ref.parent), encoding="utf-8")
        while not Path({json.dumps(str(tmp_path / "worker_release"))}).exists():
            time.sleep(0.02)
        ph.release_all_polyhaven_worker_pins()
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = subprocess.Popen([sys.executable, "-I", "-c", pin_script], env=env)
    try:
        pinned_root: Path | None = None
        for _ in range(250):
            if (tmp_path / "worker_pinned").exists():
                pinned_root = Path((tmp_path / "worker_pinned").read_text(encoding="utf-8"))
                break
            threading.Event().wait(0.02)
        else:
            pytest.fail("worker pin subprocess did not start")
        assert pinned_root == first_bundle
        monkeypatch.setattr(
            photoreal_assets.urllib.request,
            "urlopen",
            _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V2"}),
        )
        (model_dir / POLYHAVEN_CATALOG_NAME).unlink(missing_ok=True)
        assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
        assert first_bundle.exists()
        assert (first_bundle / "textures" / "albedo.png").read_bytes() == b"V1"
    finally:
        (tmp_path / "worker_release").write_text("1", encoding="utf-8")
        proc.wait(timeout=10)


def test_worker_pinned_bundle_survives_double_catalog_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Worker disk pin must match resolved bundle and block reclaim across B/C publishes (issue #205)."""
    import importlib.util

    aid = "guard_worker_bc_publish"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V1"}),
    )
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    first_bundle = _bundle_root(model_root, aid)

    worker_path = ROOT / "scripts" / "worker_polyhaven.py"
    spec = importlib.util.spec_from_file_location("worker_ph_bc", worker_path)
    assert spec is not None and spec.loader is not None
    worker_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker_mod)
    ph = worker_mod.load_polyhaven_paths()
    ref = ph.resolve_polyhaven_asset_ref_path_pinned(
        tmp_path / "assets",
        f"models/polyhaven/{aid}/{aid}_2k.gltf",
    )
    assert ref is not None and ref.parent == first_bundle
    try:
        monkeypatch.setattr(
            photoreal_assets.urllib.request,
            "urlopen",
            _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V2"}),
        )
        (model_dir / POLYHAVEN_CATALOG_NAME).unlink(missing_ok=True)
        photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
        monkeypatch.setattr(
            photoreal_assets.urllib.request,
            "urlopen",
            _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"V3"}),
        )
        (model_dir / POLYHAVEN_CATALOG_NAME).unlink(missing_ok=True)
        photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
        assert first_bundle.is_dir()
        assert (first_bundle / "textures" / "albedo.png").read_bytes() == b"V1"
        assert ref.read_bytes()
        assert (ref.parent / "textures" / "albedo.png").read_bytes() == b"V1"
    finally:
        ph.release_all_polyhaven_worker_pins()


def test_redownload_reuses_intact_version_and_fixes_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When staging matches an existing complete version, atomically switch catalog away from corrupt current."""
    from fox3d.recipe_3d import atomic_json

    aid = "guard_reuse_catalog"
    gltf_body = _gltf_body_with_uris("textures/albedo.png")
    model_root = tmp_path / "assets" / "models" / "polyhaven"
    model_dir = model_root / aid
    gltf_file = model_dir / f"{aid}_2k.gltf"
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        _fake_urlopen_factory({"gltf": {}}, gltf_body, {"textures/albedo.png": b"GOOD"}),
    )
    photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    good_id = json.loads((model_dir / POLYHAVEN_CATALOG_NAME).read_text(encoding="utf-8"))["versionId"]
    broken_id = "c" * 32
    broken_dir = model_dir / POLYHAVEN_VERSIONS_DIR / broken_id
    broken_dir.mkdir(parents=True)
    (broken_dir / gltf_file.name).write_bytes(b"{}" + b" " * 200)
    atomic_json(
        model_dir / POLYHAVEN_CATALOG_NAME,
        {"versionId": broken_id, "gltfName": gltf_file.name},
    )
    assert not photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
    assert photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])[aid]
    catalog = json.loads((model_dir / POLYHAVEN_CATALOG_NAME).read_text(encoding="utf-8"))
    assert catalog["versionId"] == good_id
    assert photoreal_assets._polyhaven_cache_complete(model_dir, gltf_file)
