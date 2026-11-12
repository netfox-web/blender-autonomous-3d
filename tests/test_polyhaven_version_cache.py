"""Issue #96: immutable Poly Haven version dirs + pinned readers during scene assembly."""
from __future__ import annotations

import json
import os
import subprocess
import sys
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


def _version_cross_process_retain_empty(version_dir: Path) -> bool:
    pin_dir = version_dir / ".fox3d-retain"
    if not pin_dir.is_dir():
        return True
    try:
        return not any(pin_dir.iterdir())
    except OSError:
        return False


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


def test_cross_process_retain_pins_block_gc(tmp_path: Path):
    aid = "cross_proc"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    v_old = "d" * 64
    v_new = "e" * 64
    _seed_version_bundle(asset_root, aid, v_old, tex_marker=b"PIN_OLD")

    repo_src = Path(__file__).resolve().parents[1] / "src"
    ph_root = tmp_path / "assets" / "models" / "polyhaven"
    ready = tmp_path / "reader_ready"
    hold_script = tmp_path / "hold_pin.py"
    hold_script.write_text(
        "\n".join(
            [
                "import sys, time",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_src)!r})",
                "from fox3d import polyhaven_cache",
                f"root = Path({str(ph_root)!r})",
                f"ready = Path({str(ready)!r})",
                "with polyhaven_cache.polyhaven_read_session(root) as session:",
                f"    main = session.resolve_ref_suffix('models/polyhaven/{aid}/{aid}_2k.gltf')",
                "    assert main is not None",
                "    assert (main.parent / 'textures/albedo.png').read_bytes() == b'PIN_OLD'",
                "    ready.write_text('1', encoding='utf-8')",
                "    time.sleep(1.0)",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.Popen([sys.executable, str(hold_script)])
    try:
        deadline = time.time() + 5.0
        while not ready.is_file() and time.time() < deadline:
            time.sleep(0.02)
        assert ready.is_file(), "child must pin v1 before publisher switches current"
        assert proc.poll() is None, "child must still hold cross-process retain pin"
        old_bundle = polyhaven_cache.version_directory(asset_root, v_old)
        _seed_version_bundle(asset_root, aid, v_new, tex_marker=b"PIN_NEW")
        assert old_bundle.is_dir(), "pinned version must survive GC while another process reads"
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_migrate_legacy_flat_survives_failed_current_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    aid = "migrate_fail"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    gltf = asset_root / f"{aid}_2k.gltf"
    gltf.write_bytes(_gltf_doc("textures/albedo.png"))
    (asset_root / "textures").mkdir()
    (asset_root / "textures/albedo.png").write_bytes(b"MIGRATE_ME")
    manifest = asset_root / photoreal_assets._POLYHAVEN_MANIFEST_NAME
    manifest.write_text('["textures/albedo.png"]', encoding="utf-8")

    original = polyhaven_cache._atomic_write_current

    def boom(root: Path, version: str) -> None:
        if root.name == aid:
            raise OSError("simulated current write failure")
        original(root, version)

    monkeypatch.setattr(polyhaven_cache, "_atomic_write_current", boom)
    ok = photoreal_assets._polyhaven_adopt_legacy_cache(asset_root, gltf)
    assert ok is False
    assert gltf.is_file(), "legacy flat glTF must remain when current write fails"
    assert not (asset_root / "current").is_file()
    versions = list((asset_root / "versions").iterdir()) if (asset_root / "versions").is_dir() else []
    assert versions, "version payload should remain on disk for retry"
    assert (versions[0] / "textures/albedo.png").read_bytes() == b"MIGRATE_ME"


def test_reader_session_survives_two_current_switches(tmp_path: Path):
    """Pinned reader keeps v1 on disk while current advances twice (issue #161)."""
    aid = "double_switch"
    root = tmp_path / "assets" / "models" / "polyhaven"
    asset_root = root / aid
    asset_root.mkdir(parents=True)
    v1 = "1" * 64
    v2 = "2" * 64
    v3 = "3" * 64
    _seed_version_bundle(asset_root, aid, v1, tex_marker=b"TEX_V1")

    reader_ready = threading.Event()
    reader_done = threading.Event()
    held: dict[str, bytes] = {}

    def reader():
        with polyhaven_cache.polyhaven_read_session(root) as session:
            assert session.pin_asset(aid) == v1
            main = session.resolve_ref_suffix(f"models/polyhaven/{aid}/{aid}_2k.gltf")
            assert main is not None
            held["tex"] = (main.parent / "textures/albedo.png").read_bytes()
            reader_ready.set()
            time.sleep(0.25)
            assert (main.parent / "textures/albedo.png").read_bytes() == b"TEX_V1"
        reader_done.set()

    t = threading.Thread(target=reader)
    t.start()
    assert reader_ready.wait(timeout=3)
    _seed_version_bundle(asset_root, aid, v2, tex_marker=b"TEX_V2")
    _seed_version_bundle(asset_root, aid, v3, tex_marker=b"TEX_V3")
    t.join(timeout=5)
    assert reader_done.is_set()
    assert held["tex"] == b"TEX_V1"
    v1_bundle = polyhaven_cache.version_directory(asset_root, v1)
    assert v1_bundle.is_dir()
    assert (v1_bundle / "textures/albedo.png").read_bytes() == b"TEX_V1"
    ref = f"assets://models/polyhaven/{aid}/{aid}_2k.gltf"
    after = polyhaven_cache.resolve_polyhaven_ref_path(ref, tmp_path / "assets")
    assert after is not None
    assert (after.parent / "textures/albedo.png").read_bytes() == b"TEX_V3"


def test_cross_process_reader_survives_double_switch_before_retain(tmp_path: Path):
    """Subprocess pins v1, parent switches twice before child finishes resolve (issue #161)."""
    aid = "race_double"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    v1 = "f" * 64
    v2 = "0" * 64
    v3 = "9" * 64
    _seed_version_bundle(asset_root, aid, v1, tex_marker=b"RACE_V1")

    repo_src = Path(__file__).resolve().parents[1] / "src"
    ph_root = tmp_path / "assets" / "models" / "polyhaven"
    ready = tmp_path / "reader_pinned"
    hold_script = tmp_path / "hold_double_switch.py"
    hold_script.write_text(
        "\n".join(
            [
                "import sys, time",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_src)!r})",
                "from fox3d import polyhaven_cache",
                f"root = Path({str(ph_root)!r})",
                f"ready = Path({str(ready)!r})",
                "with polyhaven_cache.polyhaven_read_session(root) as session:",
                f"    main = session.resolve_ref_suffix('models/polyhaven/{aid}/{aid}_2k.gltf')",
                "    assert main is not None",
                "    assert (main.parent / 'textures/albedo.png').read_bytes() == b'RACE_V1'",
                "    ready.write_text('1', encoding='utf-8')",
                "    time.sleep(0.6)",
                "    assert (main.parent / 'textures/albedo.png').read_bytes() == b'RACE_V1'",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.Popen([sys.executable, str(hold_script)])
    try:
        deadline = time.time() + 5.0
        while not ready.is_file() and time.time() < deadline:
            time.sleep(0.02)
        assert ready.is_file(), "child must pin v1 before parent switches"
        _seed_version_bundle(asset_root, aid, v2, tex_marker=b"RACE_V2")
        _seed_version_bundle(asset_root, aid, v3, tex_marker=b"RACE_V3")
        v1_bundle = polyhaven_cache.version_directory(asset_root, v1)
        assert v1_bundle.is_dir(), "pinned v1 must survive two switches"
        assert (v1_bundle / "textures/albedo.png").read_bytes() == b"RACE_V1"
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_windows_style_ref_suffix_normalizes(tmp_path: Path):
    aid = "win_paths"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    v = "c" * 64
    _seed_version_bundle(asset_root, aid, v, tex_marker=b"W")
    ref = f"assets://models\\polyhaven\\{aid}\\{aid}_2k.gltf"
    path = polyhaven_cache.resolve_polyhaven_ref_path(ref, tmp_path / "assets")
    assert path is not None and path.is_file()


def test_cross_process_legacy_flat_survives_migration_while_reading(tmp_path: Path):
    """Reader on flat cache (no current) keeps paths readable while another process migrates."""
    aid = "legacy_race"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    gltf = asset_root / f"{aid}_2k.gltf"
    gltf.write_bytes(_gltf_doc("textures/albedo.png"))
    (asset_root / "textures").mkdir()
    (asset_root / "textures/albedo.png").write_bytes(b"KEEP_FLAT")
    (asset_root / photoreal_assets._POLYHAVEN_MANIFEST_NAME).write_text(
        '["textures/albedo.png"]',
        encoding="utf-8",
    )

    repo_src = Path(__file__).resolve().parents[1] / "src"
    ph_root = tmp_path / "assets" / "models" / "polyhaven"
    ready = tmp_path / "legacy_reader_ready"
    hold_script = tmp_path / "legacy_hold.py"
    hold_script.write_text(
        "\n".join(
            [
                "import sys, time",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(repo_src)!r})",
                "from fox3d import polyhaven_cache",
                f"root = Path({str(ph_root)!r})",
                f"ready = Path({str(ready)!r})",
                "with polyhaven_cache.polyhaven_read_session(root) as session:",
                f"    main = session.resolve_ref_suffix('models/polyhaven/{aid}/{aid}_2k.gltf')",
                "    assert main is not None",
                "    assert (main.parent / 'textures/albedo.png').read_bytes() == b'KEEP_FLAT'",
                "    ready.write_text('1', encoding='utf-8')",
                "    time.sleep(0.8)",
                "    assert main.is_file(), 'legacy glTF must survive concurrent migration'",
                "    assert (main.parent / 'textures/albedo.png').read_bytes() == b'KEEP_FLAT'",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.Popen([sys.executable, str(hold_script)])
    try:
        deadline = time.time() + 5.0
        while not ready.is_file() and time.time() < deadline:
            time.sleep(0.02)
        assert ready.is_file(), "reader must resolve legacy path before migration"
        assert proc.poll() is None
        migrated = photoreal_assets._polyhaven_adopt_legacy_cache(asset_root, gltf)
        assert migrated is True
        assert polyhaven_cache.read_current_version(asset_root) is not None
        assert proc.wait(timeout=8) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_gc_defers_while_coordination_lock_held(tmp_path: Path):
    """Publish and reclaim wait while the shared catalog lock is held, then complete after release."""
    aid = "gc_defer"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    v1 = "1" * 64
    v2 = "2" * 64
    v3 = "3" * 64
    _seed_version_bundle(asset_root, aid, v1, tex_marker=b"KEEP_UNTIL_UNLOCK")

    release = threading.Event()
    acquired = threading.Event()
    published = threading.Event()

    def hold_coord_lock():
        with polyhaven_cache._asset_versions_coordination(asset_root):
            acquired.set()
            release.wait(timeout=5.0)

    def run_publish():
        _seed_version_bundle(asset_root, aid, v2, tex_marker=b"NEW_CURRENT")
        _seed_version_bundle(asset_root, aid, v3, tex_marker=b"NEW_CURRENT")
        published.set()

    holder = threading.Thread(target=hold_coord_lock, daemon=True)
    holder.start()
    assert acquired.wait(timeout=3.0)
    try:
        publisher = threading.Thread(target=run_publish, daemon=True)
        publisher.start()
        time.sleep(0.15)
        assert not published.is_set(), "publish must wait on held catalog lock"
        v1_bundle = polyhaven_cache.version_directory(asset_root, v1)
        assert v1_bundle.is_dir(), "GC must not run while the lock is held"
        assert polyhaven_cache.read_current_version(asset_root) == v1
        release.set()
        holder.join(timeout=5.0)
        assert published.wait(timeout=5.0)
        publisher.join(timeout=5.0)
        polyhaven_cache._maybe_gc_asset_versions(asset_root)
        assert not v1_bundle.exists(), "GC must reclaim deferred versions after the lock is free"
    finally:
        release.set()
        holder.join(timeout=2.0)


def test_cross_process_race_before_retain_marker_survives_double_switch(tmp_path: Path):
    """Pause after current read, before retain pin; publish waits; v1 survives once retain pin exists."""
    aid = "pre_retain_race"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    v1 = "7" * 64
    v2 = "8" * 64
    v3 = "4" * 64
    _seed_version_bundle(asset_root, aid, v1, tex_marker=b"RACE_KEEP")

    repo_src = Path(__file__).resolve().parents[1] / "src"
    ph_root = tmp_path / "assets" / "models" / "polyhaven"
    pause_dir = tmp_path / "pause_coord"
    pause_dir.mkdir(parents=True, exist_ok=True)
    hold_script = tmp_path / "race_before_retain.py"
    hold_script.write_text(
        "\n".join(
            [
                "import json, os, sys, time",
                "from pathlib import Path",
                f"os.environ[{polyhaven_cache._PAUSE_AFTER_CURRENT_ENV!r}] = {str(pause_dir)!r}",
                f"sys.path.insert(0, {str(repo_src)!r})",
                "from fox3d import polyhaven_cache",
                f"root = Path({str(ph_root)!r})",
                "with polyhaven_cache.polyhaven_read_session(root) as session:",
                f"    main = session.resolve_ref_suffix('models/polyhaven/{aid}/{aid}_2k.gltf')",
                "    assert main is not None and main.is_file()",
                f"    assert main.name == '{aid}_2k.gltf'",
                "    tex = main.parent / 'textures/albedo.png'",
                "    assert tex.read_bytes() == b'RACE_KEEP'",
                "    time.sleep(0.1)",
                "    assert main.is_file() and tex.read_bytes() == b'RACE_KEEP'",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.Popen([sys.executable, str(hold_script)], env={**os.environ, "PYTHONPATH": ""})
    try:
        deadline = time.time() + 8.0
        paused_payload = None
        while time.time() < deadline:
            marker = pause_dir / "read_current.json"
            if marker.is_file():
                paused_payload = json.loads(marker.read_text(encoding="utf-8"))
                break
            time.sleep(0.02)
        assert paused_payload == {"asset": aid, "version": v1}, "reader must pause before retain pin"
        assert proc.poll() is None, "child must still be blocked before retain pin exists"
        v1_bundle = polyhaven_cache.version_directory(asset_root, v1)
        assert _version_cross_process_retain_empty(v1_bundle), "cross-process retain pin must not exist yet"
        assert polyhaven_cache.read_current_version(asset_root) == v1
        published = threading.Event()

        def run_publish():
            _seed_version_bundle(asset_root, aid, v2, tex_marker=b"RACE_V2")
            _seed_version_bundle(asset_root, aid, v3, tex_marker=b"RACE_V3")
            published.set()

        publisher = threading.Thread(target=run_publish, daemon=True)
        publisher.start()
        time.sleep(0.15)
        assert not published.is_set(), "publish must wait while reader holds catalog lock"
        assert polyhaven_cache.read_current_version(asset_root) == v1
        assert v1_bundle.is_dir(), "v1 must not be GC'd before cross-process retain pin"
        (pause_dir / "resume_reader").write_text("go", encoding="utf-8")
        retain_deadline = time.time() + 8.0
        retain_payload = None
        while time.time() < retain_deadline:
            marker = pause_dir / "retain_pin.json"
            if marker.is_file():
                retain_payload = json.loads(marker.read_text(encoding="utf-8"))
                break
            time.sleep(0.02)
        assert retain_payload == {"asset": aid, "version": v1}, "reader must create retain pin after resume"
        assert published.wait(timeout=8.0)
        publisher.join(timeout=5.0)
        assert polyhaven_cache.read_current_version(asset_root) == v3
        assert v1_bundle.is_dir(), "retain pin must keep v1 across publishes"
        assert (v1_bundle / f"{aid}_2k.gltf").is_file(), "reader's pinned glTF must not be GC'd"
        assert (v1_bundle / "textures/albedo.png").read_bytes() == b"RACE_KEEP"
        (pause_dir / "release_reader").write_text("go", encoding="utf-8")
        assert proc.wait(timeout=8) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            (pause_dir / "resume_reader").write_text("go", encoding="utf-8")
            (pause_dir / "release_reader").write_text("go", encoding="utf-8")
            proc.wait(timeout=3)


def test_worker_legacy_pin_blocks_flat_migration_cleanup(tmp_path: Path):
    """Fleet worker ``.polyhaven_pins/__legacy_flat__`` must defer legacy-flat cleanup during migration."""
    from fox3d.polyhaven_paths import acquire_polyhaven_reader_pin, release_polyhaven_reader_pin

    aid = "worker_legacy_pin"
    asset_root = tmp_path / "assets" / "models" / "polyhaven" / aid
    asset_root.mkdir(parents=True)
    gltf = asset_root / f"{aid}_2k.gltf"
    gltf.write_bytes(_gltf_doc("textures/albedo.png"))
    (asset_root / "textures").mkdir()
    (asset_root / "textures/albedo.png").write_bytes(b"KEEP_UNTIL_READ")
    (asset_root / photoreal_assets._POLYHAVEN_MANIFEST_NAME).write_text(
        '["textures/albedo.png"]',
        encoding="utf-8",
    )
    pin_file = acquire_polyhaven_reader_pin(asset_root, None)
    try:
        assert photoreal_assets._polyhaven_adopt_legacy_cache(asset_root, gltf)
        assert gltf.is_file()
        assert (asset_root / "textures/albedo.png").read_bytes() == b"KEEP_UNTIL_READ"
    finally:
        release_polyhaven_reader_pin(pin_file)
