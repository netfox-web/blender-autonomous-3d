"""run_pilot_e2e.main() fail-closed regressions. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fox3d.acceptance_gate import CANONICAL_REAL_FILES
from fox3d.evidence import prepare_evidence_lineage

SHA = "64c5b6fc624ed1e2b6a75de9a1d76ba6701274b7"
ROOT = Path(__file__).resolve().parents[1]
SIX = [f"{name}.json" for name in CANONICAL_REAL_FILES]
PILOT_JSON = (
    "MANUFACTURING_RELEASE_REAL_ACCEPTANCE.json",
    "PILOT_OPERATIONS_ACCEPTANCE.json",
    "QC_TRACEABILITY_ACCEPTANCE.json",
)
FAMILIES = (
    "KD_FURNITURE",
    "RETAIL_FIXTURE",
    "PACKAGING_STRUCTURE",
    "ACRYLIC_SHEET",
)


def _load_runner():
    path = ROOT / "scripts" / "run_pilot_e2e.py"
    spec = importlib.util.spec_from_file_location("run_pilot_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_pilot_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _inspect(clean: bool = True):
    def inspect(root, allow_dirty=False):
        porcelain = "" if clean else " M src/fox3d/pilot.py\n"
        return prepare_evidence_lineage(head_sha=SHA, porcelain=porcelain, allow_dirty=allow_dirty)

    return inspect


def _seed_six(docs: Path, *, generation="gen-ok", commit=SHA, skip: str | None = None, malformed: str | None = None, mixed_gen=False, mixed_commit=False):
    docs.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(SIX):
        if skip and name == skip:
            continue
        if malformed and name == malformed:
            (docs / name).write_text("{not-json", encoding="utf-8")
            continue
        payload = {
            "acceptanceGenerationId": "gen-other" if mixed_gen and i == 0 else generation,
            "evidenceCodeCommit": "deadbeef" * 5 if mixed_commit and i == 1 else commit,
            "domain": name,
        }
        (docs / name).write_text(json.dumps(payload), encoding="utf-8")


def _seed_pilot_keep(docs: Path) -> None:
    for name in PILOT_JSON:
        (docs / name).write_text("KEEP-OLD", encoding="utf-8")


def _all_keep(docs: Path) -> bool:
    return all((docs / name).read_text(encoding="utf-8") == "KEEP-OLD" for name in PILOT_JSON)


def _pipeline(*, release_hash="rel-kd"):
    hashes = {
        "KD_FURNITURE": release_hash,
        "RETAIL_FIXTURE": "rel-retail",
        "PACKAGING_STRUCTURE": "rel-pack",
        "ACRYLIC_SHEET": "rel-acr",
    }
    families = [{"family": fam, "kind": "X", "releaseHash": hashes[fam], "workOrderState": "COMPLETED", "verify": {"ok": True}} for fam in FAMILIES]
    previews = []
    for fam in FAMILIES:
        bun = {"releaseHash": hashes[fam], "commitSha": SHA, "engineeringHash": "e", "bomHash": "b", "usedMock": False, "realBlender": True}
        previews.append(
            {
                "family": fam,
                "kind": "X",
                "label": "REAL",
                "usedMock": False,
                "realBlender": True,
                "verify": {"ok": True, "errors": []},
                "bundle": bun,
                "releaseHash": hashes[fam],
            }
        )
    four = {"ok": True, "families": families, "liveFactoryExecutionReady": False}

    def pipeline(*, lineage, sha, real_ok):
        return {
            "probe": SimpleNamespace(realBlender=True, realOptix=True, blenderBinary="blender", gpuName="T1000"),
            "four": four,
            "previews": previews,
            "quotes": {"quotes": [{}, {}, {}], "staleOnReleaseChange": True, "fxSource": "MANUAL"},
            "ready": {"fullAutonomousFactoryReady": False, "liveFactoryExecutionReady": False},
            "rows": [],
        }

    return pipeline


def test_runner_valid_six_file_set_can_proceed(tmp_path):
    mod = _load_runner()
    docs = tmp_path / "docs"
    _seed_six(docs)
    _seed_pilot_keep(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline()})
    assert code == 0
    for name in PILOT_JSON:
        payload = json.loads((docs / name).read_text(encoding="utf-8"))
        assert payload["evidenceCodeCommit"] == SHA
        assert payload["acceptanceGenerationId"]


def test_runner_mixed_generation_nonzero_canonical_unchanged(tmp_path):
    mod = _load_runner()
    docs = tmp_path / "docs"
    _seed_six(docs, mixed_gen=True)
    _seed_pilot_keep(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline()})
    assert code != 0
    assert _all_keep(docs)


def test_runner_mixed_commit_nonzero_canonical_unchanged(tmp_path):
    mod = _load_runner()
    docs = tmp_path / "docs"
    _seed_six(docs, mixed_commit=True)
    _seed_pilot_keep(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline()})
    assert code != 0
    assert _all_keep(docs)


def test_runner_missing_canonical_nonzero_unchanged(tmp_path):
    mod = _load_runner()
    docs = tmp_path / "docs"
    _seed_six(docs, skip="NESTING_V3_ACCEPTANCE.json")
    _seed_pilot_keep(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline()})
    assert code != 0
    assert _all_keep(docs)


def test_runner_malformed_canonical_nonzero_unchanged(tmp_path):
    mod = _load_runner()
    docs = tmp_path / "docs"
    _seed_six(docs, malformed="RELEASE_GATE_REAL_ACCEPTANCE.json")
    _seed_pilot_keep(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline()})
    assert code != 0
    assert _all_keep(docs)


def test_runner_release_hash_mismatch_nonzero_unchanged(tmp_path):
    mod = _load_runner()
    docs = tmp_path / "docs"
    _seed_six(docs)
    _seed_pilot_keep(docs)

    def pipeline(*, lineage, sha, real_ok):
        data = _pipeline()(lineage=lineage, sha=sha, real_ok=real_ok)
        data["previews"][0]["bundle"]["releaseHash"] = None
        data["previews"][0]["releaseHash"] = None
        data["previews"][0]["verify"] = {"ok": False, "errors": ["release_hash_missing"]}
        return data

    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": pipeline})
    assert code != 0
    assert _all_keep(docs)
