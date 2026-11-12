"""Poly Haven on-disk cache: immutable version dirs + atomic current pointer + pinned readers."""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from fox3d import durability

_POLYHAVEN_REF_RE = re.compile(
    r"^models/polyhaven/(?P<aid>[A-Za-z0-9_-]{1,64})/(?P<rel>.+\.(?:gltf|glb))$",
    re.IGNORECASE,
)

_CURRENT_FILENAME = "current"
_VERSIONS_DIRNAME = "versions"
_RETAIN_DIRNAME = ".fox3d-retain"
_LEGACY_MANIFEST_NAME = ".polyhaven_complete.json"

# Test hooks (threading.Event): publisher waits before/after switching current.
publish_pause_before_switch: threading.Event | None = None
publish_pause_after_switch: threading.Event | None = None
read_pause_after_current_before_retain: threading.Event | None = None

_PAUSE_AFTER_CURRENT_ENV = "FOX3D_POLYHAVEN_PAUSE_AFTER_CURRENT_DIR"
_ASSET_COORD_LOCK = ".polyhaven.coord.lock"

_retained_lock = threading.Lock()
_version_refcounts: dict[tuple[str, str], int] = defaultdict(int)
_previous_current: dict[str, str] = {}


def polyhaven_asset_root(polyhaven_root: Path, asset_id: str) -> Path:
    return polyhaven_root / asset_id


def _current_path(asset_root: Path) -> Path:
    return asset_root / _CURRENT_FILENAME


def read_current_version(asset_root: Path) -> str | None:
    path = _current_path(asset_root)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            return None
        version = doc.get("version") if isinstance(doc, dict) else None
        return version if isinstance(version, str) and version else None
    line = raw.splitlines()[0].strip()
    return line or None


def _atomic_write_current(asset_root: Path, version: str) -> None:
    asset_root.mkdir(parents=True, exist_ok=True)
    target = _current_path(asset_root)
    payload = json.dumps({"version": version}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    if publish_pause_before_switch is not None:
        publish_pause_before_switch.wait()

    prev = read_current_version(asset_root)
    if prev and prev != version:
        _previous_current[asset_root.name] = prev

    token = hashlib.sha256(os.urandom(16)).hexdigest()[:16]
    temporary = target.with_name(f".{target.name}.{token}.tmp")
    owned = False
    try:
        with temporary.open("xb") as stream:
            owned = True
            stream.write(payload)
            durability.flush_file(stream)
        os.replace(temporary, target)
        owned = False
        durability.namespace_committed(target, "polyhaven-current")
    except BaseException:
        if owned and temporary.exists():
            try:
                durability.unlink_owned(temporary, missing_ok=True)
            except OSError:
                pass
        raise

    _maybe_gc_asset_versions(asset_root)

    if publish_pause_after_switch is not None:
        publish_pause_after_switch.set()


def version_directory(asset_root: Path, version: str) -> Path:
    return asset_root / _VERSIONS_DIRNAME / version


def bundle_content_hash(bundle_dir: Path, gltf_file: Path, include_rels: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(gltf_file.read_bytes())
    for rel in sorted(r.replace("\\", "/") for r in include_rels):
        digest.update(rel.encode("utf-8"))
        digest.update((bundle_dir / rel).read_bytes())
    return digest.hexdigest()


def parse_polyhaven_asset_ref(ref_suffix: str) -> tuple[str, str] | None:
    normalized = ref_suffix.replace("\\", "/").lstrip("/")
    match = _POLYHAVEN_REF_RE.match(normalized)
    if not match:
        return None
    rel = match.group("rel").replace("\\", "/")
    if ".." in Path(rel).parts:
        return None
    return match.group("aid"), rel


def _retain_version(asset_id: str, version: str) -> None:
    with _retained_lock:
        _version_refcounts[(asset_id, version)] += 1


def _release_version(asset_id: str, version: str) -> None:
    with _retained_lock:
        key = (asset_id, version)
        _version_refcounts[key] -= 1
        if _version_refcounts[key] <= 0:
            del _version_refcounts[key]


def _acquire_cross_process_retain(asset_root: Path, version: str) -> Path:
    """Pin a version for other OS processes (e.g. Blender) via on-disk markers."""
    pin_dir = version_directory(asset_root, version) / _RETAIN_DIRNAME
    pin_dir.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(os.urandom(8)).hexdigest()[:12]
    pin = pin_dir / f"{os.getpid()}.{token}"
    pin.write_text(str(os.getpid()), encoding="utf-8")
    return pin


def _release_cross_process_retain(pin_path: Path) -> None:
    try:
        pin_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        pin_dir = pin_path.parent
        if pin_dir.is_dir() and not any(pin_dir.iterdir()):
            pin_dir.rmdir()
    except OSError:
        pass


def _maybe_pause_after_current_read(asset_root: Path, version: str) -> None:
    """Test hook: pause after reading current, before creating cross-process retain pin."""
    if read_pause_after_current_before_retain is not None:
        read_pause_after_current_before_retain.wait()
        return
    pause_dir = os.environ.get(_PAUSE_AFTER_CURRENT_ENV, "").strip()
    if not pause_dir:
        return
    coord = Path(pause_dir)
    coord.mkdir(parents=True, exist_ok=True)
    (coord / "read_current.json").write_text(
        json.dumps({"asset": asset_root.name, "version": version}, ensure_ascii=False),
        encoding="utf-8",
    )
    resume = coord / "resume_reader"
    deadline = time.time() + 30.0
    while not resume.is_file() and time.time() < deadline:
        time.sleep(0.02)


def _version_dir_has_retain_pins(version_dir: Path) -> bool:
    pin_dir = version_dir / _RETAIN_DIRNAME
    if not pin_dir.is_dir():
        return False
    try:
        return any(pin_dir.iterdir())
    except OSError:
        return True


def _materialize_version_from_bundle(
    source_dir: Path,
    dest_dir: Path,
    gltf_file: Path,
    include_rels: list[str],
) -> None:
    """Copy a flat or legacy bundle into versions/<hash>/ without disturbing the source tree."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(gltf_file, dest_dir / gltf_file.name)
    for rel in include_rels:
        src = source_dir / rel
        if src.is_file():
            dst = dest_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    manifest_src = source_dir / _LEGACY_MANIFEST_NAME
    if manifest_src.is_file():
        shutil.copy2(manifest_src, dest_dir / _LEGACY_MANIFEST_NAME)


@contextmanager
def _asset_versions_coordination(asset_root: Path) -> Iterator[None]:
    """Cross-process mutex shared by readers, publishers, and version GC."""
    from fox3d.storelock import FileLock

    lock_path = asset_root / _ASSET_COORD_LOCK
    with FileLock(lock_path, timeout=30.0):
        yield


def _maybe_gc_asset_versions(asset_root: Path) -> None:
    asset_id = asset_root.name
    current = read_current_version(asset_root)
    keep = {current, _previous_current.get(asset_id)}
    keep.discard(None)
    versions_root = asset_root / _VERSIONS_DIRNAME
    if not versions_root.is_dir():
        return
    with _asset_versions_coordination(asset_root):
        with _retained_lock:
            for child in versions_root.iterdir():
                if not child.is_dir():
                    continue
                ver = child.name
                if ver in keep:
                    continue
                if _version_refcounts.get((asset_id, ver), 0) > 0:
                    continue
                if _version_dir_has_retain_pins(child):
                    continue
                shutil.rmtree(child, ignore_errors=True)


def publish_version(asset_root: Path, staging_bundle: Path, version: str) -> None:
    """Install staging into versions/<version>/ and atomically switch current."""
    versions_root = asset_root / _VERSIONS_DIRNAME
    versions_root.mkdir(parents=True, exist_ok=True)
    final_dir = version_directory(asset_root, version)
    if final_dir.exists():
        shutil.rmtree(final_dir, ignore_errors=True)
    staging_bundle.rename(final_dir)
    _atomic_write_current(asset_root, version)


def migrate_legacy_flat_bundle(
    asset_root: Path,
    gltf_file: Path,
    *,
    cache_complete_fn: Callable[[Path, Path], bool],
    include_rels: list[str],
) -> bool:
    """Promote a legacy flat on-disk bundle into versions/<hash>/ + current."""
    pinned = read_current_version(asset_root)
    if pinned is not None:
        bundle = version_directory(asset_root, pinned)
        target = bundle / gltf_file.name
        return cache_complete_fn(bundle, target)
    if not gltf_file.is_file():
        return False
    if not cache_complete_fn(asset_root, gltf_file):
        return False

    version = bundle_content_hash(asset_root, gltf_file, include_rels)
    dest = version_directory(asset_root, version)
    if dest.exists() and cache_complete_fn(dest, dest / gltf_file.name):
        _atomic_write_current(asset_root, version)
        _cleanup_asset_root_after_migration(asset_root)
        return True

    (asset_root / _VERSIONS_DIRNAME).mkdir(parents=True, exist_ok=True)
    staging_parent: Path | None = None
    try:
        staging_parent = Path(
            tempfile.mkdtemp(prefix=f".ph-migrate-{asset_root.name}-{version[:8]}-", dir=asset_root.parent)
        )
        staging_bundle = staging_parent / "bundle"
        _materialize_version_from_bundle(asset_root, staging_bundle, gltf_file, include_rels)
        if not cache_complete_fn(staging_bundle, staging_bundle / gltf_file.name):
            return False
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        staging_bundle.rename(dest)
        staging_parent = None
        try:
            _atomic_write_current(asset_root, version)
        except BaseException:
            return False
        _cleanup_asset_root_after_migration(asset_root)
        return read_current_version(asset_root) == version
    except BaseException:
        if staging_parent is not None and dest.exists() and read_current_version(asset_root) != version:
            shutil.rmtree(dest, ignore_errors=True)
        raise
    finally:
        if staging_parent is not None:
            shutil.rmtree(staging_parent, ignore_errors=True)


def _cleanup_asset_root_after_migration(asset_root: Path) -> None:
    for stray in list(asset_root.iterdir()):
        if stray.name in (_CURRENT_FILENAME, _VERSIONS_DIRNAME):
            continue
        if stray.name.endswith(".polyhaven.lock") or stray.name.startswith("."):
            continue
        if stray.is_dir():
            shutil.rmtree(stray, ignore_errors=True)
        elif stray.is_file():
            stray.unlink(missing_ok=True)


def active_bundle_dir(asset_root: Path, gltf_name: str, *, cache_complete_fn: Callable[[Path, Path], bool] | None = None) -> tuple[Path, Path] | None:
    version = read_current_version(asset_root)
    if version:
        bundle = version_directory(asset_root, version)
        gltf = bundle / gltf_name
        if gltf.is_file():
            return bundle, gltf
        return None
    gltf = asset_root / gltf_name
    if gltf.is_file():
        return asset_root, gltf
    return None


_active_read_session: contextvars.ContextVar[PolyhavenReadSession | None] = contextvars.ContextVar(
    "polyhaven_read_session",
    default=None,
)


class PolyhavenReadSession:
    """Pin Poly Haven ``current`` versions for one scene-assembly pass."""

    def __init__(self, polyhaven_root: Path) -> None:
        self._root = Path(polyhaven_root)
        self._pins: dict[str, str] = {}
        self._retain_files: dict[str, Path] = {}
        self._closed = False

    def pin_asset(self, asset_id: str) -> str | None:
        if asset_id in self._pins:
            return self._pins[asset_id]
        asset_root = polyhaven_asset_root(self._root, asset_id)
        with _asset_versions_coordination(asset_root):
            version = read_current_version(asset_root)
            if not version:
                return None
            bundle = version_directory(asset_root, version)
            if not bundle.is_dir():
                return None
            _maybe_pause_after_current_read(asset_root, version)
            _retain_version(asset_id, version)
            if asset_id not in self._retain_files:
                self._retain_files[asset_id] = _acquire_cross_process_retain(asset_root, version)
            self._pins[asset_id] = version
        return version

    def resolve_ref_suffix(self, ref_suffix: str) -> Path | None:
        parsed = parse_polyhaven_asset_ref(ref_suffix)
        if parsed is None:
            return None
        aid, rel = parsed
        version = self.pin_asset(aid)
        asset_root = polyhaven_asset_root(self._root, aid)
        if version:
            path = version_directory(asset_root, version) / rel
            if path.is_file():
                return path.resolve()
        legacy = asset_root / rel
        if legacy.is_file():
            return legacy.resolve()
        return None

    def release(self) -> None:
        if self._closed:
            return
        for aid, version in self._pins.items():
            _release_version(aid, version)
        for pin in self._retain_files.values():
            _release_cross_process_retain(pin)
        self._pins.clear()
        self._retain_files.clear()
        self._closed = True

    def __enter__(self) -> PolyhavenReadSession:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


@contextmanager
def polyhaven_read_session(polyhaven_root: Path) -> Iterator[PolyhavenReadSession]:
    session = PolyhavenReadSession(polyhaven_root)
    token = _active_read_session.set(session)
    try:
        yield session
    finally:
        _active_read_session.reset(token)
        session.release()


def resolve_polyhaven_ref_path(
    ref: str,
    assets_root: Path,
    session: PolyhavenReadSession | None = None,
) -> Path | None:
    text = (ref or "").strip()
    prefix = "assets://"
    if not text.startswith(prefix):
        return None
    suffix = text[len(prefix) :]
    parts = suffix.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        return None
    ph_root = assets_root / "models" / "polyhaven"
    if session is None:
        session = _active_read_session.get()
    if session is None:
        ephemeral = PolyhavenReadSession(ph_root)
        try:
            return ephemeral.resolve_ref_suffix(suffix)
        finally:
            ephemeral.release()
    return session.resolve_ref_suffix(suffix)
