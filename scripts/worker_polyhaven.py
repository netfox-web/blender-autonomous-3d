"""Load ``polyhaven_paths`` from the same directory as Blender worker scripts."""
from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType


@lru_cache(maxsize=1)
def load_polyhaven_paths() -> ModuleType:
    path = Path(__file__).with_name("polyhaven_paths.py")
    name = "_worker_polyhaven_paths"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Poly Haven paths helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
