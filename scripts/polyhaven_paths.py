"""Poly Haven on-disk layout helpers (immutable version dirs + catalog pointer).

Shipped beside Blender worker scripts so fleet nodes can resolve versioned bundles
without the full application ``src`` tree on ``PYTHONPATH``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

POLYHAVEN_CATALOG_NAME = ".polyhaven_catalog.json"
POLYHAVEN_VERSIONS_DIR = "versions"
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


def resolve_polyhaven_bundle_paths(slot: Path, nominal_gltf: Path) -> tuple[Path, Path]:
    """Return ``(bundle_root, gltf_path)`` for integrity checks, downloads, and pins."""
    catalog = read_polyhaven_catalog(slot)
    if catalog is None:
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


def resolve_polyhaven_asset_ref_path(assets_root: Path, asset_ref_rel: str) -> Path | None:
    """Resolve ``models/polyhaven/<id>/<file>.gltf`` through the active catalog pointer when present."""
    rel = asset_ref_rel.replace("\\", "/").lstrip("/")
    match = _POLYHAVEN_GLTF_REF_RE.match(rel)
    if not match:
        return None
    aid, gltf_name = match.group(1), match.group(2)
    slot = assets_root / "models" / "polyhaven" / aid
    _bundle_root, gltf_path = resolve_polyhaven_bundle_paths(slot, slot / gltf_name)
    return gltf_path
