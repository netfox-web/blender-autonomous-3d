"""Issue #96: immutable Poly Haven version dirs + pinned readers during scene assembly."""
from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from fox3d import photoreal_assets, polyhaven_cache


def _gltf_doc(*uris: str) -> bytes:
    images = [{"uri": u} for u in uris if u.lower().endswith(".png")]
    buffers = [{"uri": u} for u in uris if not u.lower().endswith(".png")]
    body = json.dumps({"asset": {"version": "2.0"}, "images": images, "buffers": buffers}).encode()
    if len(body) <= photoreal_assets._POLYHAVEN_MIN_GLTF_BYTES:
        body += b" " * (photoreal_assets._POLYHAVEN_MIN_GLTF_BYTES - len(body) + 1)
    return body


def _poll_coord_json(marker: Path, deadline: float) -> dict | None:
    return polyhaven_cache.poll_coord_json_signal(marker, deadline=deadline)


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


def test_cross_process_race_before_retain_marker_survives_double_switch(tmp_path: Path):
    """Issue #168: pause after current read, before on-disk retain; publisher GC must wait on coord lock."""
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
    publisher_errors: list[BaseException] = []
    publisher_done = threading.Event()
    lock_wait_dir = tmp_path / "publish_lock_wait"
    lock_wait_dir.mkdir(parents=True, exist_ok=True)
    os.environ[polyhaven_cache._PUBLISH_LOCK_WAIT_DIR_ENV] = str(lock_wait_dir)
    publisher_blocked = lock_wait_dir / "publisher_blocked_on_lock.json"

    def publisher_switches() -> None:
        try:
            _seed_version_bundle(asset_root, aid, v2, tex_marker=b"RACE_V2")
            _seed_version_bundle(asset_root, aid, v3, tex_marker=b"RACE_V3")
        except BaseException as exc:
            publisher_errors.append(exc)
        finally:
            publisher_done.set()

    pub = threading.Thread(target=publisher_switches, daemon=True, name="pre_retain_publisher")
    try:
        paused_payload = _poll_coord_json(pause_dir / "read_current.json", time.time() + 8.0)
        assert paused_payload == {"asset": aid, "version": v1}, "reader must pause before retain pin"
        assert proc.poll() is None, "child must still be blocked before retain pin exists"

        v1_bundle = polyhaven_cache.version_directory(asset_root, v1)
        assert _version_cross_process_retain_empty(v1_bundle), "cross-process retain pin must not exist yet"
        assert polyhaven_cache.read_current_version(asset_root) == v1

        pub.start()
        blocked_deadline = time.time() + 8.0
        while time.time() < blocked_deadline and not publisher_blocked.is_file():
            time.sleep(0.02)
        assert publisher_blocked.is_file(), "publisher must be blocked on coord lock while reader paused"
        assert v1_bundle.is_dir(), "v1 must remain before reader creates cross-process retain pin"
        assert (v1_bundle / f"{aid}_2k.gltf").is_file(), "reader's pinned glTF must not be GC'd yet"
        assert _version_cross_process_retain_empty(v1_bundle), "retain marker not created while paused"
        assert not publisher_done.is_set(), "publisher must remain blocked before reader resumes"

        (pause_dir / "resume_reader").write_text("go", encoding="utf-8")
        retain_payload = _poll_coord_json(pause_dir / "retain_pin.json", time.time() + 8.0)
        assert retain_payload == {"asset": aid, "version": v1}, "reader must create retain pin before publisher runs"
        assert proc.poll() is None, "reader must stay alive while cross-process retain pin is held"
        assert publisher_done.wait(timeout=8), "publisher must finish both switches while reader retain pin is held"
        assert not publisher_errors, publisher_errors
        assert v1_bundle.is_dir(), "pinned v1 must survive two switches"
        assert polyhaven_cache.read_current_version(asset_root) == v3
        assert (v1_bundle / "textures/albedo.png").read_bytes() == b"RACE_KEEP"
        (pause_dir / "release_reader").write_text("go", encoding="utf-8")
        assert proc.wait(timeout=8) == 0
    finally:
        os.environ.pop(polyhaven_cache._PUBLISH_LOCK_WAIT_DIR_ENV, None)
        if proc.poll() is None:
            proc.kill()
            (pause_dir / "resume_reader").write_text("go", encoding="utf-8")
            (pause_dir / "release_reader").write_text("go", encoding="utf-8")
            proc.wait(timeout=3)
        pub.join(timeout=2)


@pytest.mark.parametrize("run_index", range(3))
def test_coord_json_signal_atomic_under_concurrent_poll(tmp_path: Path, run_index: int):
    """Issue #209: signal files must not expose partial JSON while publishing."""
    path = tmp_path / "read_current.json"
    decode_errors: list[json.JSONDecodeError] = []
    writer_done = threading.Event()
    writer_errors: list[BaseException] = []

    def writer() -> None:
        try:
            for i in range(250):
                polyhaven_cache._atomic_write_coord_signal(
                    path,
                    {"asset": "race", "version": f"{i:03d}"},
                )
        except BaseException as exc:
            writer_errors.append(exc)
        finally:
            writer_done.set()

    def _try_parse_signal() -> None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            decode_errors.append(exc)

    def aggressive_reader() -> None:
        while not writer_done.is_set():
            if path.is_file():
                _try_parse_signal()
            time.sleep(0.001)
        if path.is_file():
            _try_parse_signal()

    wt = threading.Thread(target=writer, name="coord_signal_writer")
    rt = threading.Thread(target=aggressive_reader, name="coord_signal_reader", daemon=True)
    try:
        wt.start()
        rt.start()
        wt.join(timeout=10)
        assert writer_done.is_set(), "writer must always signal completion (even after replace errors)"
        assert not writer_errors, writer_errors
        rt.join(timeout=2)
        assert not decode_errors, decode_errors
        final = polyhaven_cache.read_coord_json_signal(path)
        assert final == {"asset": "race", "version": "249"}
    finally:
        writer_done.set()
        wt.join(timeout=1)
        rt.join(timeout=1)


@pytest.mark.parametrize(
    "error,probe,expected",
    [
        (PermissionError(errno.EACCES, "denied"), 32, True),
        (PermissionError(13, "Access is denied"), 32, True),
        (PermissionError(errno.EACCES, "denied"), 0, False),
    ],
)
def test_windows_replace_contention_errno_without_winerror(
    monkeypatch: pytest.MonkeyPatch, error: OSError, probe: int, expected: bool
) -> None:
    monkeypatch.setattr(polyhaven_cache, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(polyhaven_cache, "_delete_sharing_error", lambda p: probe)
    assert polyhaven_cache._windows_replace_contention(error, Path("unused")) is expected


@pytest.mark.parametrize(
    "probe,expected",
    [
        (32, True),
        (0, True),
        (5, False),
    ],
)
def test_windows_replace_contention_access_denied_probe_race(
    monkeypatch: pytest.MonkeyPatch, probe: int, expected: bool
) -> None:
    err = PermissionError(13, "Access is denied")
    err.winerror = 5
    monkeypatch.setattr(polyhaven_cache, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(polyhaven_cache, "_delete_sharing_error", lambda p: probe)
    assert polyhaven_cache._windows_replace_contention(err, Path("unused")) is expected


def test_coord_signal_atomic_replace_retries_transient_windows_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Bounded Windows sharing retries must not leave coordination signal partial."""
    path = tmp_path / "read_current.json"
    payload = b'{"asset":"race","version":"001"}'
    monkeypatch.setattr(polyhaven_cache, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(polyhaven_cache, "_delete_sharing_error", lambda p: 32)
    real_replace = os.replace
    calls: list[tuple[str, str]] = []

    def flaky_replace(src, dst) -> None:
        calls.append((str(src), str(dst)))
        if len(calls) == 1:
            err = PermissionError(errno.EACCES, "sharing violation")
            setattr(err, "winerror", 32)
            raise err
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    polyhaven_cache._atomic_replace_file(path, payload)
    assert polyhaven_cache.read_coord_json_signal(path) == {"asset": "race", "version": "001"}
    assert len(calls) == 2


@pytest.mark.parametrize("run_index", range(3))
def test_cross_process_race_before_retain_marker_repeated(tmp_path: Path, run_index: int):
    """Stress cross-process coordination signals across repeated runs (issue #209)."""
    test_cross_process_race_before_retain_marker_survives_double_switch(tmp_path)
