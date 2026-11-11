"""Issue #96: immutable Poly Haven version dirs + pinned readers during scene assembly."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from fox3d import photoreal_assets, polyhaven_cache


def _gltf_doc(*uris: str) -> bytes:
    images = [{"uri": u} for u in uris if u.lower().endswith(".png")]
    buffers = [{"uri": u} for u in uris if not u.lower().endswith(".png")]
    body = json.dumps({"asset": {"version": "2.0"}, "images": images, "buffers": buffers}).encode()
    if len(body) <= photoreal_assets._POLYHAVEN_MIN_GLTF_BYTES:
        body += b" " * (photoreal_assets._POLYHAVEN_MIN_GLTF_BYTES - len(body) + 1)
    return body


def _seed_version_bundle(asset_root: Path, aid: str, version: str, *, tex_marker: bytes) -> None:
    bundle = polyhaven_cache.version_directory(asset_root, version)
    bundle.mkdir(parents=True, exist_ok=True)
    gltf = bundle / f"{aid}_2k.gltf"
    gltf.write_bytes(_gltf_doc("textures/albedo.png"))
    (bundle / "textures").mkdir(parents=True, exist_ok=True)
    (bundle / "textures/albedo.png").write_bytes(tex_marker)
    manifest = bundle / photoreal_assets._POLYHAVEN_MANIFEST_NAME
    manifest.write_text(json.dumps(["textures/albedo.png"]), encoding="utf-8")
    polyhaven_cache._atomic_write_current(asset_root, version)


def test_reader_pins_during_current_switch(tmp_path: Path):
    aid = "ver_switch"
    assets_root = tmp_path / "assets"
    root = assets_root / "models" / "polyhaven"
    asset_root = root / aid
    asset_root.mkdir(parents=True, exist_ok=True)

    v1 = "a" * 64
    v2 = "b" * 64
    _seed_version_bundle(asset_root, aid, v1, tex_marker=b"TEX_V1")

    switch_allowed = threading.Event()
    polyhaven_cache.publish_pause_before_switch = switch_allowed
    polyhaven_cache.publish_pause_after_switch = None

    reader_ready = threading.Event()
    reader_done = threading.Event()

    def reader():
        with polyhaven_cache.polyhaven_read_session(root) as session:
            main = session.resolve_ref_suffix(f"models/polyhaven/{aid}/{aid}_2k.gltf")
            assert main is not None
            tex = main.parent / "textures/albedo.png"
            assert tex.read_bytes() == b"TEX_V1"
            assert session.pin_asset(aid) == v1
            reader_ready.set()
            time.sleep(0.15)
            assert session.pin_asset(aid) == v1
            assert tex.read_bytes() == b"TEX_V1"
            switch_allowed.set()
            time.sleep(0.05)
            assert session.pin_asset(aid) == v1
            assert tex.read_bytes() == b"TEX_V1"
        reader_done.set()

    t = threading.Thread(target=reader)
    t.start()
    assert reader_ready.wait(timeout=3)
    publisher = threading.Thread(
        target=lambda: _seed_version_bundle(asset_root, aid, v2, tex_marker=b"TEX_V2"),
    )
    publisher.start()
    t.join(timeout=5)
    publisher.join(timeout=5)
    assert reader_done.is_set()

    ref = f"assets://models/polyhaven/{aid}/{aid}_2k.gltf"
    after = polyhaven_cache.resolve_polyhaven_ref_path(ref, assets_root)
    assert after is not None
    assert (after.parent / "textures/albedo.png").read_bytes() == b"TEX_V2"
    polyhaven_cache.publish_pause_before_switch = None


def test_offline_legacy_flat_cache_migrates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "legacy_flat"
    monkeypatch.setattr(
        photoreal_assets.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")),
    )
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    gltf = asset_root / f"{aid}_2k.gltf"
    gltf.write_bytes(_gltf_doc("textures/albedo.png"))
    (asset_root / "textures").mkdir()
    (asset_root / "textures/albedo.png").write_bytes(b"LEGACY")
    (asset_root / photoreal_assets._POLYHAVEN_MANIFEST_NAME).write_text('["textures/albedo.png"]', encoding="utf-8")

    paths = photoreal_assets.ensure_polyhaven_models(root_dir=tmp_path, asset_ids=[aid])
    assert aid in paths
    version = polyhaven_cache.read_current_version(asset_root)
    assert version
    bundle_dir, resolved = photoreal_assets._polyhaven_locate_bundle(asset_root, f"{aid}_2k.gltf")
    assert polyhaven_cache.version_directory(asset_root, version) == bundle_dir
    assert photoreal_assets._polyhaven_cache_complete(bundle_dir, resolved)
    assert (bundle_dir / "textures/albedo.png").read_bytes() == b"LEGACY"


def test_windows_style_ref_suffix_normalizes(tmp_path: Path):
    aid = "win_paths"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    v = "c" * 64
    _seed_version_bundle(asset_root, aid, v, tex_marker=b"W")
    ref = f"assets://models\\polyhaven\\{aid}\\{aid}_2k.gltf"
    path = polyhaven_cache.resolve_polyhaven_ref_path(ref, tmp_path / "assets")
    assert path is not None and path.is_file()
