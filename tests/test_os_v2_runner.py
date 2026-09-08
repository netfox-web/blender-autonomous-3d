"""Runner-level main() / exit-code regressions. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fox3d.acceptance_gate import CANONICAL_REAL_FILES, read_canonical_truth_set
from fox3d.evidence import evidence_bundle, prepare_evidence_lineage, verify_bundle
from fox3d.ids import sha256_bytes

SHA = "6d9de7e4c57085054f373c63efe51eaccdf59f04"
ROOT = Path(__file__).resolve().parents[1]
CANON = [
    "PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.json",
    "RELEASE_GATE_REAL_ACCEPTANCE.json",
    "COMMERCIAL_COST_ACCEPTANCE.json",
    "PACKAGING_V2_ACCEPTANCE.json",
    "MATERIAL_REMNANT_REAL_ACCEPTANCE.json",
    "NESTING_V3_ACCEPTANCE.json",
]


def _load_runner():
    path = ROOT / "scripts" / "run_os_v2_e2e.py"
    spec = importlib.util.spec_from_file_location("run_os_v2_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_os_v2_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _preview(tmp_path, *, i: int, sha: str = SHA, commit: str | None = None, used_mock: bool = False, real_blender: bool = True, size_mismatch: bool = False, hash_mismatch: bool = False):
    art = tmp_path / f"p{i}.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
    digest = sha256_bytes(art.read_bytes())
    job = {
        "jobId": f"j{i}",
        "usedMock": used_mock,
        "realBlender": real_blender,
        "status": "completed",
        "outputHash": digest,
        "outputSize": art.stat().st_size,
        "blenderVersion": "5.2.1",
    }
    bun = evidence_bundle(commit_sha=commit or sha, job=job, artifact_path=art, engineering_hash="e", bom_hash="b")
    if hash_mismatch:
        bun["artifactHash"] = "0" * 64
    if size_mismatch:
        bun["artifactSize"] = 1
    ver = verify_bundle(bun, require_real=True, expected_commit_sha=sha)
    label = "REAL" if ver["ok"] and not used_mock and real_blender else "PARTIAL"
    return {"label": label, "verify": ver, "bundle": bun, "usedMock": used_mock, "realBlender": real_blender}


def _inspect(clean: bool = True, allow_used: bool = False):
    def inspect(root, allow_dirty=False):
        porcelain = "" if clean else " M src/fox3d/evidence.py\n"
        return prepare_evidence_lineage(head_sha=SHA, porcelain=porcelain, allow_dirty=allow_dirty or allow_used)

    return inspect


def _pipeline(tmp_path, previews, *, live_cnc=True, live_laser=True):
    def pipeline(*, lineage, sha, real_ok):
        return {
            "probe": SimpleNamespace(realBlender=True, realOptix=True, blenderBinary="blender", gpuName="T1000"),
            "previews": previews,
            "adv": {"state": "APPROVED_FOR_EXPORT", "audit": {"auditHash": "audit"}},
            "stale": {"stale": True},
            "live_cnc_blocked": live_cnc,
            "live_laser_blocked": live_laser,
            "mixed": {"truthLabel": "MIXED"},
            "fit": {"passed": 20, "n": 20, "allOk": True},
            "opt": {"chosen": {"family": "SLEEVE"}},
            "packs": [{"publicationHash": "x"}] * 5,
            "ready": {"fullAutonomousFactoryReady": False},
            "rows": [{"check": "publication 5-family Blender+EvidenceBundle", "status": "REAL", "evidence": "5/5"}],
        }

    return pipeline


def _seed_old(docs: Path) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    for name in CANON:
        (docs / name).write_text("KEEP-OLD", encoding="utf-8")


def _all_keep(docs: Path) -> bool:
    return all((docs / name).read_text(encoding="utf-8") == "KEEP-OLD" for name in CANON)


def test_runner_success_exit_0(tmp_path):
    mod = _load_runner()
    previews = [_preview(tmp_path, i=i) for i in range(5)]
    docs = tmp_path / "docs"
    _seed_old(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews)})
    assert code == 0
    check = read_canonical_truth_set(docs)
    assert check["ok"] is True
    assert set(check["payloads"]) == set(CANONICAL_REAL_FILES)
    assert check["evidenceCodeCommit"] == SHA
    gens = {check["payloads"][n]["acceptanceGenerationId"] for n in CANONICAL_REAL_FILES}
    commits = {check["payloads"][n]["evidenceCodeCommit"] for n in CANONICAL_REAL_FILES}
    assert len(gens) == 1
    assert commits == {SHA}


def test_runner_commit_mismatch_nonzero_canonical_unchanged(tmp_path):
    mod = _load_runner()
    previews = [_preview(tmp_path, i=i, commit="b9e7861be28c6f94a1bc7c985c77877b98b70720") for i in range(5)]
    docs = tmp_path / "docs"
    _seed_old(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews)})
    assert code != 0
    assert _all_keep(docs)


def test_runner_hash_mismatch_nonzero_canonical_unchanged(tmp_path):
    mod = _load_runner()
    previews = [_preview(tmp_path, i=i, hash_mismatch=(i == 1)) for i in range(5)]
    docs = tmp_path / "docs"
    _seed_old(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews)})
    assert code != 0
    assert _all_keep(docs)


def test_runner_size_mismatch_nonzero_canonical_unchanged(tmp_path):
    mod = _load_runner()
    previews = [_preview(tmp_path, i=i, size_mismatch=(i == 2)) for i in range(5)]
    docs = tmp_path / "docs"
    _seed_old(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews)})
    assert code != 0
    assert _all_keep(docs)


def test_runner_used_mock_or_not_real_blender_nonzero(tmp_path):
    mod = _load_runner()
    docs = tmp_path / "docs"
    _seed_old(docs)
    previews = [_preview(tmp_path, i=i, used_mock=(i == 0)) for i in range(5)]
    assert mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews)}) != 0
    assert _all_keep(docs)
    previews2 = [_preview(tmp_path, i=i, real_blender=(i != 4)) for i in range(5)]
    assert mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews2)}) != 0


def test_runner_four_of_five_nonzero(tmp_path):
    mod = _load_runner()
    previews = [_preview(tmp_path, i=i) for i in range(4)]
    docs = tmp_path / "docs"
    _seed_old(docs)
    assert mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews)}) != 0
    assert _all_keep(docs)


def test_runner_dirty_without_override_nonzero(tmp_path):
    mod = _load_runner()
    docs = tmp_path / "docs"
    _seed_old(docs)
    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(False), "pipeline": _pipeline(tmp_path, [])})
    assert code != 0
    assert _all_keep(docs)


def test_runner_allow_dirty_unverified_nonzero_canonical_unchanged(tmp_path):
    mod = _load_runner()
    previews = [_preview(tmp_path, i=i) for i in range(5)]
    docs = tmp_path / "docs"
    _seed_old(docs)
    code = mod.main(["--docs-root", str(docs), "--allow-dirty"], hooks={"inspect": _inspect(False), "pipeline": _pipeline(tmp_path, previews)})
    assert code != 0
    assert _all_keep(docs)


def test_runner_live_machine_not_blocked_nonzero(tmp_path):
    mod = _load_runner()
    previews = [_preview(tmp_path, i=i) for i in range(5)]
    docs = tmp_path / "docs"
    _seed_old(docs)
    assert mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews, live_cnc=False)}) != 0
    assert _all_keep(docs)
    assert mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews, live_laser=False)}) != 0
    assert _all_keep(docs)


def test_runner_atomic_publish_failure_rolls_back(tmp_path):
    mod = _load_runner()
    previews = [_preview(tmp_path, i=i) for i in range(5)]
    docs = tmp_path / "docs"
    _seed_old(docs)
    n = {"c": 0}

    def boom(src, dst):
        n["c"] += 1
        if n["c"] == 3:
            raise OSError("simulated disk error")
        os.replace(src, dst)

    code = mod.main(["--docs-root", str(docs)], hooks={"inspect": _inspect(True), "pipeline": _pipeline(tmp_path, previews), "replace_fn": boom})
    assert code != 0
    assert _all_keep(docs)
    gens = set()
    for name in CANON:
        text = (docs / name).read_text(encoding="utf-8")
        assert text == "KEEP-OLD"
        gens.add(text)
    assert gens == {"KEEP-OLD"}
