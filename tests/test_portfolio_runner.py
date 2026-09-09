"""run_portfolio_factory_e2e fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fox3d.acceptance_gate import PORTFOLIO_ACCEPTANCE_FILES, read_portfolio_truth_set
from fox3d.evidence import prepare_evidence_lineage

ROOT = Path(__file__).resolve().parents[1]
SHA = "c" * 40


def _load():
    path = ROOT / "scripts" / "run_portfolio_factory_e2e.py"
    spec = importlib.util.spec_from_file_location("run_portfolio_factory_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_portfolio_factory_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _inspect(sha: str, *, clean: bool = True, empty: bool = False):
    def inspect(root, allow_dirty=False):
        if empty:
            return {"evidenceCodeCommit": "", "workingTreeClean": True}
        porcelain = "" if clean else " M src/fox3d/portfolio.py\n"
        return prepare_evidence_lineage(head_sha=sha, porcelain=porcelain, allow_dirty=allow_dirty)

    return inspect


class _FakePlat:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.mock_blender = True


def _lineage_row(i: int) -> dict:
    return {
        "candidateId": f"c{i}",
        "canonicalHash": f"can{i}",
        "engineeringHash": f"eng{i}",
        "bomHash": f"bom{i}",
        "nestingHash": f"nest{i}",
        "costSnapshotHash": f"cost{i}",
        "costEngineeringHash": f"eng{i}",
        "rankingPolicyHash": "abc",
        "score": 1.0 - i * 0.01,
        "state": "SHORTLISTED",
        "conservationOk": True,
    }


def _passing_scenario(plat):
    return {
        "ok": True,
        "candidateCount": 28,
        "kindCount": 8,
        "kinds": ["OPEN_SHELF", "BEDSIDE_CABINET", "DESK_RISER", "NARROW_BOOKCASE", "STORAGE_BENCH", "STUDENT_DESK"],
        "rejected": 4,
        "top10": 10,
        "top10Lineage": [_lineage_row(i) for i in range(10)],
        "invalidInTop10": 0,
        "rankingPolicyHash": "abc",
        "plan": {"consumesInventory": False, "doubleAllocation": False, "sheetCountDelta": -1, "trueScrapDelta": 0},
        "tenantIsolation": True,
        "demandLabel": "MOCK",
        "prototypeReady": True,
        "liveMachineControl": False,
        "conservationOk": True,
        "media": [],
        "pack": {"status": "READY_FOR_MANUAL_PROTOTYPE"},
    }


def test_portfolio_runner_binds_clean_head(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing_scenario},
    )
    assert rc == 0
    body = json.loads((docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert body["evidenceCodeCommit"] == SHA
    assert body["ok"] is True
    assert body["liveMachineControl"] is False
    assert (docs / "PORTFOLIO_DFM_ACCEPTANCE.json").exists()
    assert (docs / "PORTFOLIO_COMMERCIAL_ACCEPTANCE.md").exists()


def test_portfolio_runner_dirty_does_not_overwrite(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    prior = {"ok": True, "keep": True}
    (docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").write_text(json.dumps(prior), encoding="utf-8")
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA, clean=False), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing_scenario},
    )
    assert rc != 0
    kept = json.loads((docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_portfolio_runner_mismatch_refuses(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", "d" * 40],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing_scenario},
    )
    assert rc != 0
    assert not (docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").exists()


def test_portfolio_reader_rejects_mixed_generation(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for i, name in enumerate(PORTFOLIO_ACCEPTANCE_FILES):
        payload = {
            "acceptanceGenerationId": "gen-a" if i == 0 else "gen-b",
            "evidenceCodeCommit": SHA,
            "workingTreeClean": True,
            "evidenceCommitMatchesHead": True,
            "ok": True,
            "fullAutonomousFactoryReady": False,
            "liveFactoryExecutionReady": False,
            "liveProviderReady": False,
            "globalProductionReady": False,
            "liveMachineControl": False,
        }
        (docs / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
        (docs / f"{name}.md").write_text("# x\n", encoding="utf-8")
    result = read_portfolio_truth_set(docs)
    assert result["ok"] is False
    assert any("mixed_generation" in e or "generation_mismatch" in e for e in result["errors"])


def _run(mod, tmp_path, scenario, extra=None):
    docs = tmp_path / "docs"
    argv = ["--docs-root", str(docs), "--expected-commit", SHA]
    if extra:
        argv.extend(extra)
    rc = mod.main(
        argv,
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": scenario},
    )
    return rc, docs


def test_portfolio_runner_ok_false_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["ok"] = False
        return body

    rc, docs = _run(mod, tmp_path, scenario)
    assert rc != 0
    assert not (docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").exists()


def test_portfolio_runner_ok_false_keeps_prior(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")

    def scenario(plat):
        body = _passing_scenario(plat)
        body["ok"] = False
        return body

    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": scenario},
    )
    assert rc != 0
    kept = json.loads((docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_portfolio_runner_missing_lineage_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["top10Lineage"][0]["bomHash"] = ""
        return body

    rc, docs = _run(mod, tmp_path, scenario)
    assert rc != 0
    assert not (docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").exists()


def test_portfolio_runner_stale_cost_lineage_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["top10Lineage"][0]["costEngineeringHash"] = "stale"
        return body

    rc, _docs = _run(mod, tmp_path, scenario)
    assert rc != 0


def test_portfolio_runner_rejected_in_top10_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["top10Lineage"][0]["state"] = "REJECTED_DFM"
        return body

    rc, _docs = _run(mod, tmp_path, scenario)
    assert rc != 0


def _media(i, **overrides):
    row = {
        "candidateId": f"c{i}",
        "engineeringHash": f"eng{i}",
        "jobId": f"job{i}",
        "usedMock": False,
        "realBlender": True,
        "blenderVersion": "5.2.1",
        "device": "OPTIX",
        "gpu": "NVIDIA T1000",
        "executedAt": "2026-09-09T00:00:00Z",
        "evidenceCodeCommit": SHA,
        "artifactSha256": f"{i:064x}",
        "artifactSize": 2048,
        "label": "REAL",
    }
    row.update(overrides)
    return row


def test_portfolio_runner_real_media_missing_sha_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["media"] = [_media(i, artifactSha256="") for i in range(4)]
        return body

    rc, docs = _run(mod, tmp_path, scenario, extra=["--real-media"])
    assert rc != 0
    assert not (docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").exists()


def test_portfolio_runner_real_media_zero_size_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["media"] = [_media(i, artifactSize=0) for i in range(4)]
        return body

    rc, _docs = _run(mod, tmp_path, scenario, extra=["--real-media"])
    assert rc != 0


def test_portfolio_runner_real_media_used_mock_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["media"] = [_media(i, usedMock=True) for i in range(4)]
        return body

    rc, _docs = _run(mod, tmp_path, scenario, extra=["--real-media"])
    assert rc != 0


def test_portfolio_runner_real_media_not_blender_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["media"] = [_media(i, realBlender=False) for i in range(4)]
        return body

    rc, _docs = _run(mod, tmp_path, scenario, extra=["--real-media"])
    assert rc != 0


def test_portfolio_runner_real_media_wrong_commit_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["media"] = [_media(i, evidenceCodeCommit="d" * 40) for i in range(4)]
        return body

    rc, _docs = _run(mod, tmp_path, scenario, extra=["--real-media"])
    assert rc != 0


def test_portfolio_runner_real_media_fewer_than_four_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["media"] = [_media(i) for i in range(3)]
        return body

    rc, _docs = _run(mod, tmp_path, scenario, extra=["--real-media"])
    assert rc != 0


def test_portfolio_runner_real_media_pass_persists_detailed_cases(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing_scenario(plat)
        body["media"] = [_media(i) for i in range(4)]
        return body

    rc, docs = _run(mod, tmp_path, scenario, extra=["--real-media"])
    assert rc == 0
    body = json.loads((docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert len(body["realMediaCases"]) == 4
    assert all(row.get("artifactSha256") and row.get("artifactSize") > 0 for row in body["realMediaCases"])
    assert all(row.get("evidenceCodeCommit") == SHA for row in body["realMediaCases"])
    assert len(body["top10Lineage"]) == 10
