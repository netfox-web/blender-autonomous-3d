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


def _passing_scenario(plat):
    return {
        "ok": True,
        "candidateCount": 28,
        "kindCount": 8,
        "kinds": ["OPEN_SHELF", "BEDSIDE_CABINET", "DESK_RISER", "NARROW_BOOKCASE", "STORAGE_BENCH", "STUDENT_DESK"],
        "rejected": 4,
        "top10": 10,
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
