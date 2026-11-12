"""Poly Haven on-disk layout helpers (re-exported from worker-shipped module)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_WORKER_MODULE = Path(__file__).resolve().parents[2] / "scripts" / "polyhaven_paths.py"


def _load_worker_polyhaven_paths():
    name = "fox3d._polyhaven_paths_worker"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    if not _WORKER_MODULE.is_file():
        raise ImportError(f"Missing worker Poly Haven helper: {_WORKER_MODULE}")
    spec = importlib.util.spec_from_file_location(name, _WORKER_MODULE)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load worker Poly Haven helper: {_WORKER_MODULE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_mod = _load_worker_polyhaven_paths()

POLYHAVEN_CATALOG_NAME = _mod.POLYHAVEN_CATALOG_NAME
POLYHAVEN_VERSIONS_DIR = _mod.POLYHAVEN_VERSIONS_DIR
read_polyhaven_catalog = _mod.read_polyhaven_catalog
resolve_polyhaven_bundle_paths = _mod.resolve_polyhaven_bundle_paths
resolve_polyhaven_asset_ref_path = _mod.resolve_polyhaven_asset_ref_path
