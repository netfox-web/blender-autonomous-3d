"""Stdlib-only path bootstrap so Blender fleet jobs can import ``fox3d`` on GPU nodes."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_POLYHAVEN_PROBE = ("fox3d", "polyhaven_cache.py")


def _repo_root_from_anchor(anchor: Path) -> Path:
    scripts_dir = anchor.resolve().parent
    if scripts_dir.name == "scripts":
        return scripts_dir.parent
    return scripts_dir


def _anchor(anchor: Path | None) -> Path:
    if anchor is not None:
        return _repo_root_from_anchor(Path(anchor))
    bootstrap = Path(__file__).resolve()
    if bootstrap.parent.name == "scripts":
        return bootstrap.parent.parent
    return bootstrap.parent


def fox3d_src_candidates(anchor: Path | None = None) -> list[Path]:
    """Search roots where ``import fox3d`` works (repo checkout vs fleet node layout)."""
    base = _anchor(anchor)
    env_src = os.environ.get("FOX3D_SRC", "").strip()
    ordered: list[Path] = []
    if env_src:
        ordered.append(Path(env_src).expanduser())
    ordered.extend((base / "src", base / "lib"))
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in ordered:
        key = os.path.normcase(str(candidate.resolve())) if candidate.exists() else os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def resolve_fox3d_src(anchor: Path | None = None) -> Path | None:
    for root in fox3d_src_candidates(anchor):
        probe = root.joinpath(*_POLYHAVEN_PROBE)
        if probe.is_file():
            return root.resolve()
    return None


def ensure_fox3d_on_path(anchor: Path | None = None) -> Path:
    """Insert the fleet/repo ``src`` root on ``sys.path``; return that root."""
    resolved = resolve_fox3d_src(anchor)
    if resolved is None:
        base = _anchor(anchor)
        raise ImportError(
            f"fox3d package not found for Blender (checked {', '.join(str(p) for p in fox3d_src_candidates(base))})"
        )
    src = str(resolved)
    if src not in sys.path:
        sys.path.insert(0, src)
    return resolved


def verify_fox3d_polyhaven_importable(anchor: Path | None = None) -> Path:
    """Fail fast when node deploy omitted ``src/fox3d`` (in-process; use from Blender scripts)."""
    root = ensure_fox3d_on_path(anchor)
    from fox3d.polyhaven_cache import polyhaven_read_session  # noqa: F401

    return root


def verify_fox3d_polyhaven_importable_subprocess(anchor: Path | None = None, *, python: str | None = None) -> Path:
    """Isolated import probe for fleet executor preflight (does not touch caller ``sys.path``)."""
    root = resolve_fox3d_src(anchor)
    if root is None:
        base = _anchor(anchor)
        raise ImportError(
            f"fox3d package not found for Blender (checked {', '.join(str(p) for p in fox3d_src_candidates(base))})"
        )
    interpreter = python or sys.executable
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "from fox3d.polyhaven_cache import polyhaven_read_session\n"
    )
    completed = subprocess.run(
        [interpreter, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ImportError(detail or f"fox3d import probe failed (exit {completed.returncode})")
    return root


def fleet_executor_fox3d_requires(deploy_root: str = "/data-fast/fox3d") -> list[str]:
    """Paths that fleet-agent ``requires`` must list so Blender jobs can import ``fox3d``."""
    root = deploy_root.rstrip("/")
    names = (
        "scripts/fox3d_bootstrap.py",
        "src/fox3d/__init__.py",
        "src/fox3d/polyhaven_cache.py",
        "src/fox3d/durability.py",
        "src/fox3d/storelock.py",
    )
    return [f"file:{root}/{name}" for name in names]
