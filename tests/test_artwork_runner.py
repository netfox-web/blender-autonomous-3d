"""Artwork placement runner fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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


def test_artwork_runner_corrupted_result_does_not_publish(tmp_path):
    from fox3d.platform import Platform
    from fox3d.artwork import run_artwork_scenario

    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    prior = (docs / "ARTWORK_PLACEMENT_ACCEPTANCE.json")
    prior.write_text("old", encoding="utf-8")

    def bad(plat):
        rec = run_artwork_scenario(plat)
        rec["ok"] = True
        rec["surfaceDecorationLogicReady"] = True
        rec["productionArtworkFileReady"] = True
        rec["negatives"]["keepout"] = "passed"
        rec["lineage"]["placementHash"] = "forged"
        rec["preview"]["placementHash"] = "forged"
        rec["scenarios"]["cabinet4"]["production"][0]["placementHash"] = "forged"
        return rec

    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={
            "inspect": _inspect(SHA),
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": bad,
            "acceptance_root": tmp_path / "acc",
            "prior_docs": ROOT / "docs",
        },
    )
    assert rc != 0
    assert prior.read_text(encoding="utf-8") == "old"


def _corrupt_fewer_crops(rec):
    rec["scenarios"]["cabinet4"]["panelCrops"] = rec["scenarios"]["cabinet4"]["panelCrops"][:3]


def _corrupt_fewer_ids(rec):
    rec["scenarios"]["cabinet4"]["surfaceIds"] = rec["scenarios"]["cabinet4"]["surfaceIds"][:3]


def _corrupt_duplicate_placement(rec):
    hashes = list(rec["scenarios"]["cabinet4"]["placementHashes"])
    hashes[3] = hashes[0]
    rec["scenarios"]["cabinet4"]["placementHashes"] = hashes


def _corrupt_wrong_final_uv(rec):
    applied = [dict(row) for row in rec["scenarios"]["cabinet4"]["appliedUv"]]
    applied[0] = dict(applied[0])
    applied[0]["uvRect"] = dict(applied[0]["uvRect"])
    applied[0]["uvRect"]["u0"] = 0.99
    rec["scenarios"]["cabinet4"]["appliedUv"] = applied


def _corrupt_preview_missing_applied(rec):
    rec["preview"] = dict(rec.get("preview") or {})
    rec["preview"]["status"] = "succeeded"
    rec["preview"]["realBlender"] = True
    rec["preview"].pop("artworkApplied", None)
    rec["realArtworkPreviewReady"] = True
    rec["mockBlender"] = False


@pytest.mark.parametrize(
    "corrupt",
    [
        _corrupt_fewer_crops,
        _corrupt_fewer_ids,
        _corrupt_duplicate_placement,
        _corrupt_wrong_final_uv,
        _corrupt_preview_missing_applied,
    ],
)
def test_artwork_runner_new_corruptions_do_not_publish(tmp_path, corrupt):
    from fox3d.platform import Platform
    from fox3d.artwork import run_artwork_scenario

    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    prior = docs / "ARTWORK_PLACEMENT_ACCEPTANCE.json"
    prior.write_text("old", encoding="utf-8")

    def bad(plat):
        rec = run_artwork_scenario(plat)
        rec["ok"] = True
        rec["surfaceDecorationLogicReady"] = True
        rec["productionArtworkFileReady"] = True
        corrupt(rec)
        return rec

    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={
            "inspect": _inspect(SHA),
            "platform": lambda root: Platform(root=root, mock_blender=True),
            "scenario": bad,
            "acceptance_root": tmp_path / "acc",
            "prior_docs": ROOT / "docs",
        },
    )
    assert rc != 0
    assert prior.read_text(encoding="utf-8") == "old"


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
