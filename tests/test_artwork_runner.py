"""Artwork placement runner fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fox3d.evidence import prepare_evidence_lineage

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def _load():
    path = ROOT / "scripts" / "run_artwork_placement_e2e.py"
    spec = importlib.util.spec_from_file_location("run_artwork_placement_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_artwork_placement_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _inspect(sha: str, *, clean: bool = True):
    def inspect(root, allow_dirty=False):
        porcelain = "" if clean else " M src/fox3d/artwork.py\n"
        return prepare_evidence_lineage(head_sha=sha, porcelain=porcelain, allow_dirty=allow_dirty)

    return inspect


def test_artwork_runner_refuses_dirty(tmp_path):
    mod = _load()
    rc = mod.main(["--docs-root", str(tmp_path / "docs")], hooks={"inspect": _inspect(SHA, clean=False)})
    assert rc != 0


def test_artwork_runner_publishes_canonical(tmp_path):
    from fox3d.platform import Platform
    from fox3d.artwork import run_artwork_scenario

    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={
            "inspect": _inspect(SHA),
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": run_artwork_scenario,
            "acceptance_root": tmp_path / "acc",
            "prior_docs": ROOT / "docs",
        },
    )
    assert rc == 0
    body = (docs / "ARTWORK_PLACEMENT_ACCEPTANCE.json").read_text(encoding="utf-8")
    assert SHA in body
    assert "physicalPrintValidated" in body
    assert (docs / "ARTWORK_PLACEMENT_ACCEPTANCE.md").exists()
