"""Poly Haven on-disk layout helpers (immutable version dirs + catalog pointer).

Shipped beside Blender worker scripts so fleet nodes can resolve versioned bundles
without the full application ``src`` tree on ``PYTHONPATH``. API matches ``fox3d.polyhaven_paths``.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Iterator

_catalog_lock_depth = threading.local()

POLYHAVEN_CATALOG_NAME = ".polyhaven_catalog.json"
POLYHAVEN_VERSIONS_DIR = "versions"
POLYHAVEN_CATALOG_LOCK_NAME = ".catalog.lock"
_POLYHAVEN_CURRENT_FILENAME = "current"
_POLYHAVEN_PINS_DIR = ".polyhaven_pins"
_POLYHAVEN_LEGACY_PIN = "__legacy_flat__"
_CATALOG_LOCK_PAUSE_ENV = "FOX3D_POLYHAVEN_CATALOG_LOCK_PAUSE_DIR"


class CatalogLockTimeout(TimeoutError):
    """Timed out waiting for the Poly Haven catalog cross-process lock."""


def catalog_lock_path(cache_root: Path) -> Path:
    return cache_root / POLYHAVEN_CATALOG_LOCK_NAME


def _catalog_lock_depths() -> dict[str, int]:
    depths = getattr(_catalog_lock_depth, "depths", None)
    if depths is None:
        depths = {}
        _catalog_lock_depth.depths = depths
    return depths


@contextmanager
def catalog_lock(cache_root: Path, *, timeout: float = 30.0) -> Iterator[None]:
    """Cross-process mutex for catalog read/pin, publish, and reclaim on one cache slot."""
    path = catalog_lock_path(cache_root)
    key = str(path.resolve())
    depths = _catalog_lock_depths()
    if depths.get(key, 0) > 0:
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
            if depths[key] <= 0:
                depths.pop(key, None)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fh: IO[bytes] | None = None
    acquired = False
    deadline = time.time() + timeout
    try:
        fh = open(path, "a+b")
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    if fh.read(1) == b"":
                        fh.write(b"\0")
                        fh.flush()
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.time() >= deadline:
                    raise CatalogLockTimeout(f"catalog lock timeout: {path}")
                time.sleep(0.02)
        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)
    finally:
        if fh is not None:
            try:
                if acquired:
                    if os.name == "nt":
                        import msvcrt

                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                try:
                    fh.close()
                except OSError:
                    pass


def _maybe_pause_catalog_pin_before_acquire(slot: Path, version_id: str | None) -> None:
    """Test hook: pause after resolve, before pin, while still holding :func:`catalog_lock`."""
    pause_dir = os.environ.get(_CATALOG_LOCK_PAUSE_ENV, "").strip()
    if not pause_dir:
        return
    coord = Path(pause_dir)
    coord.mkdir(parents=True, exist_ok=True)
    (coord / "resolved.json").write_text(
        json.dumps({"slot": slot.name, "versionId": version_id}, ensure_ascii=False),
        encoding="utf-8",
    )
    resume = coord / "resume_pin"
    deadline = time.time() + 30.0
    while not resume.is_file() and time.time() < deadline:
        time.sleep(0.02)
_WORKER_PIN_REGISTRY: list[Path] = []
_POLYHAVEN_GLTF_REF_RE = re.compile(
    r"^models/polyhaven/([A-Za-z0-9_-]{1,64})/([A-Za-z0-9_.-]+\.gltf)$"
)


def read_polyhaven_catalog(slot: Path) -> dict[str, Any] | None:
    path = slot / POLYHAVEN_CATALOG_NAME
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    version_id = doc.get("versionId")
    gltf_name = doc.get("gltfName")
    if not isinstance(version_id, str) or not version_id:
        return None
    if "/" in version_id or "\\" in version_id or version_id in (".", ".."):
        return None
    if not isinstance(gltf_name, str) or not gltf_name:
        return None
    if "/" in gltf_name or "\\" in gltf_name:
        return None
    return doc


def read_polyhaven_current_version(slot: Path) -> str | None:
    """Workbench-style ``current`` pointer (JSON or plain version id)."""
    path = slot / _POLYHAVEN_CURRENT_FILENAME
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


def resolve_polyhaven_bundle_paths(slot: Path, nominal_gltf: Path) -> tuple[Path, Path]:
    """Return ``(bundle_root, gltf_path)`` for integrity checks, downloads, and pins."""
    catalog = read_polyhaven_catalog(slot)
    if catalog is None:
        version = read_polyhaven_current_version(slot)
        if version:
            version_dir = (slot / POLYHAVEN_VERSIONS_DIR / version).resolve()
            try:
                version_dir.relative_to(slot.resolve())
            except ValueError:
                return slot, nominal_gltf
            gltf_path = (version_dir / nominal_gltf.name).resolve()
            if gltf_path.is_file():
                try:
                    gltf_path.relative_to(version_dir)
                except ValueError:
                    return slot, nominal_gltf
                return version_dir, gltf_path
        return slot, nominal_gltf
    version_dir = (slot / POLYHAVEN_VERSIONS_DIR / catalog["versionId"]).resolve()
    try:
        version_dir.relative_to(slot.resolve())
    except ValueError:
        return slot, nominal_gltf
    gltf_path = (version_dir / catalog["gltfName"]).resolve()
    try:
        gltf_path.relative_to(version_dir)
    except ValueError:
        return slot, nominal_gltf
    return version_dir, gltf_path


def version_id_for_resolved_bundle(slot: Path, bundle_root: Path) -> str | None:
    """Map a resolved bundle directory to its immutable version id (``None`` = legacy flat slot)."""
    slot_resolved = slot.resolve()
    bundle_resolved = bundle_root.resolve()
    if bundle_resolved == slot_resolved:
        return None
    versions_root = (slot_resolved / POLYHAVEN_VERSIONS_DIR).resolve()
    try:
        rel = bundle_resolved.relative_to(versions_root)
    except ValueError:
        return None
    if rel.parts and rel.parts[0]:
        return rel.parts[0]
    return None


def resolve_polyhaven_asset_ref_path(assets_root: Path, asset_ref_rel: str) -> Path | None:
    """Resolve ``models/polyhaven/<id>/<file>.gltf`` through the active catalog pointer when present."""
    rel = asset_ref_rel.replace("\\", "/").lstrip("/")
    match = _POLYHAVEN_GLTF_REF_RE.match(rel)
    if not match:
        return None
    aid, gltf_name = match.group(1), match.group(2)
    slot = assets_root / "models" / "polyhaven" / aid
    _bundle_root, gltf_path = resolve_polyhaven_bundle_paths(slot, slot / gltf_name)
    return gltf_path if gltf_path.is_file() else None


def pin_polyhaven_bundle_paths(slot: Path, nominal_gltf: Path) -> tuple[Path, Path, Path]:
    """Pin an immutable bundle for the duration of a worker read (register :func:`release_all_polyhaven_worker_pins`)."""
    with catalog_lock(slot):
        bundle_root, gltf_path = resolve_polyhaven_bundle_paths(slot, nominal_gltf)
        version_id = version_id_for_resolved_bundle(slot, bundle_root)
        _maybe_pause_catalog_pin_before_acquire(slot, version_id)
        pin_file = acquire_polyhaven_reader_pin(slot, version_id)
    _WORKER_PIN_REGISTRY.append(pin_file)
    return bundle_root, gltf_path, pin_file


def resolve_polyhaven_asset_ref_path_pinned(assets_root: Path, asset_ref_rel: str) -> Path | None:
    """Like :func:`resolve_polyhaven_asset_ref_path` but retains the resolved version until pins are released."""
    rel = asset_ref_rel.replace("\\", "/").lstrip("/")
    match = _POLYHAVEN_GLTF_REF_RE.match(rel)
    if not match:
        return None
    aid, gltf_name = match.group(1), match.group(2)
    slot = assets_root / "models" / "polyhaven" / aid
    _bundle_root, gltf_path, _pin = pin_polyhaven_bundle_paths(slot, slot / gltf_name)
    return gltf_path if gltf_path.is_file() else None


def release_all_polyhaven_worker_pins() -> None:
    for pin_file in _WORKER_PIN_REGISTRY:
        release_polyhaven_reader_pin(pin_file)
    _WORKER_PIN_REGISTRY.clear()


def polyhaven_pins_root(slot: Path) -> Path:
    return slot / _POLYHAVEN_PINS_DIR


def acquire_polyhaven_reader_pin(slot: Path, version_id: str | None) -> Path:
    """Create a cross-process reader pin; unlink the returned path (or call :func:`release_polyhaven_reader_pin`)."""
    pin_key = version_id if isinstance(version_id, str) and version_id else _POLYHAVEN_LEGACY_PIN
    pin_dir = polyhaven_pins_root(slot) / pin_key
    pin_dir.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    pin_file = pin_dir / token
    pin_file.write_text("", encoding="utf-8")
    return pin_file


def release_polyhaven_reader_pin(pin_file: Path) -> None:
    pin_file.unlink(missing_ok=True)
    try:
        parent = pin_file.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
    pins_root = pin_file.parents[1] if len(pin_file.parents) >= 2 else None
    if pins_root is not None and pins_root.name == _POLYHAVEN_PINS_DIR:
        try:
            if pins_root.is_dir() and not any(pins_root.iterdir()):
                pins_root.rmdir()
        except OSError:
            pass


def listed_polyhaven_reader_pins(slot: Path) -> set[str]:
    """Version ids (and legacy sentinel) that currently have at least one on-disk reader pin."""
    pins_root = polyhaven_pins_root(slot)
    if not pins_root.is_dir():
        return set()
    pinned: set[str] = set()
    for entry in pins_root.iterdir():
        if not entry.is_dir():
            continue
        if any(entry.iterdir()):
            pinned.add(entry.name)
    return pinned
