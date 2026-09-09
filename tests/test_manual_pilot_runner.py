"""run_manual_pilot_e2e fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fox3d.acceptance_gate import MANUAL_PILOT_ACCEPTANCE_FILES, read_manual_pilot_truth_set
from fox3d.evidence import prepare_evidence_lineage
from fox3d.manual_pilot import REQUIRED_GATES

ROOT = Path(__file__).resolve().parents[1]
SHA = "b" * 40


def _load():
    path = ROOT / "scripts" / "run_manual_pilot_e2e.py"
    spec = importlib.util.spec_from_file_location("run_manual_pilot_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_manual_pilot_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _inspect(sha: str, *, clean: bool = True, empty: bool = False):
    def inspect(root, allow_dirty=False):
        if empty:
            return {"evidenceCodeCommit": "", "workingTreeClean": True}
        porcelain = "" if clean else " M src/fox3d/pilot.py\n"
        return prepare_evidence_lineage(head_sha=sha, porcelain=porcelain, allow_dirty=allow_dirty)

    return inspect


class _FakePlat:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.mock_blender = True


def _passing_scenario(plat):
    gates = {k: True for k in REQUIRED_GATES}
    gates["liveMachineControl"] = False
    gates["globalProductionReady"] = False
    gates["liveFactoryExecutionReady"] = False
    gates["fullAutonomousFactoryReady"] = False
    return {
        "ok": True,
        "gates": gates,
        "families": {"ok": True},
        "workOrderId": "wo",
        "releaseHash": "rh",
        "labor": {"historyAppendOnly": True},
        "health": {"journalIntegrity": {"ok": True, "status": "REAL"}, "liveCnc": "BLOCKED", "liveLaser": "BLOCKED"},
        "liveCnc": "BLOCKED",
        "liveLaser": "BLOCKED",
        "restart": {"journalOk": True, "noDoubleConsume": True, "noDoubleCompletion": True},
    }


def test_manual_runner_binds_clean_head(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    acc = tmp_path / "acc"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={
            "inspect": _inspect(SHA),
            "acceptance_root": acc,
            "platform": _FakePlat,
            "scenario": _passing_scenario,
        },
    )
    assert rc == 0
    body = json.loads((docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert body["evidenceCodeCommit"] == SHA
    assert body["workingTreeClean"] is True
    assert body["ok"] is True
    assert body["liveMachineControl"] is False
    assert (docs / "OPERATOR_SHIFT_ACCEPTANCE.json").exists()
    assert (docs / "INVENTORY_RECONCILIATION_ACCEPTANCE.json").exists()
    assert (docs / "PILOT_BACKUP_RESTORE_ACCEPTANCE.json").exists()


def test_manual_runner_dirty_does_not_overwrite(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    prior = {"ok": True, "keep": True}
    (docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json").write_text(json.dumps(prior), encoding="utf-8")
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA, clean=False), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing_scenario},
    )
    assert rc != 0
    kept = json.loads((docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_manual_runner_mismatch_refuses(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", "c" * 40],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing_scenario},
    )
    assert rc != 0
    assert not (docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json").exists()


def test_manual_runner_publish_failure_preserves_prior(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc1", "platform": _FakePlat, "scenario": _passing_scenario},
    )
    assert rc == 0
    prior = (docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json").read_text(encoding="utf-8")
    calls = {"n": 0}

    def boom(src, dst):
        calls["n"] += 1
        if calls["n"] > 3:
            raise OSError("injected publish failure")
        import os

        os.replace(src, dst)

    rc2 = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={
            "inspect": _inspect(SHA),
            "acceptance_root": tmp_path / "acc2",
            "platform": _FakePlat,
            "scenario": _passing_scenario,
            "replace": boom,
        },
    )
    assert rc2 != 0
    kept = json.loads((docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert json.loads(prior)["acceptanceGenerationId"] == kept["acceptanceGenerationId"]
    for name in MANUAL_PILOT_ACCEPTANCE_FILES:
        assert (docs / f"{name}.json").exists()
        assert (docs / f"{name}.md").exists()


def test_manual_pilot_reader_rejects_mixed_generation(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for i, name in enumerate(MANUAL_PILOT_ACCEPTANCE_FILES):
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
    result = read_manual_pilot_truth_set(docs)
    assert result["ok"] is False
    assert any("mixed_generation" in e or "generation_mismatch" in e for e in result["errors"])


def test_manual_runner_missing_gate_does_not_overwrite(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc1", "platform": _FakePlat, "scenario": _passing_scenario},
    )
    assert rc == 0
    prior = json.loads((docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json").read_text(encoding="utf-8"))

    def failing(plat):
        body = _passing_scenario(plat)
        body["ok"] = False
        body["gates"]["restoreNoDoubleConsume"] = False
        return body

    rc2 = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc2", "platform": _FakePlat, "scenario": failing},
    )
    assert rc2 != 0
    kept = json.loads((docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept["acceptanceGenerationId"] == prior["acceptanceGenerationId"]
    assert kept["ok"] is True
