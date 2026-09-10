"""run_pilot_batch_e2e fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fox3d.evidence import prepare_evidence_lineage

ROOT = Path(__file__).resolve().parents[1]
SHA = "c" * 40


def _load():
    path = ROOT / "scripts" / "run_pilot_batch_e2e.py"
    spec = importlib.util.spec_from_file_location("run_pilot_batch_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_pilot_batch_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _inspect(sha: str, *, clean: bool = True):
    def inspect(root, allow_dirty=False):
        porcelain = "" if clean else " M src/fox3d/pilot_batch.py\n"
        return prepare_evidence_lineage(head_sha=sha, porcelain=porcelain, allow_dirty=allow_dirty)

    return inspect


class _FakePlat:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.mock_blender = True


def _passing(plat):
    batches = []
    units = []
    for i in range(4):
        bid = f"b{i}"
        batches.append(
            {
                "batchId": bid,
                "tenantId": "pa",
                "candidateId": f"c{i}",
                "engineeringHash": f"e{i}",
                "canonicalHash": f"h{i}",
                "bomHash": f"bom{i}",
                "nestingHash": f"n{i}",
                "rankingPolicyHash": "p" * 64,
                "requestedQuantity": 5,
                "source": "FIXTURE",
                "truthLabel": "FIXTURE",
                "state": "IN_PROGRESS",
                "liveMachineControl": False,
                "cost": {"completeness": "PARTIAL", "truthLabel": "FIXTURE", "quantityLineage": {"ok": False}},
            }
        )
        for s in range(5):
            units.append(
                {
                    "unitExecutionId": f"u{i}-{s}",
                    "tenantId": "pa",
                    "batchId": bid,
                    "engineeringHash": f"e{i}",
                    "state": "PACKED",
                }
            )
    return {
        "ok": True,
        "batches": batches,
        "units": units,
        "cartons": [],
        "board": {"decision": "WAITING_HUMAN_EVIDENCE", "rows": []},
        "batchAuthority": {
            "batches": [{"batchId": b["batchId"], "tenantId": "pa", "engineeringHash": b["engineeringHash"]} for b in batches],
            "units": [{"unitExecutionId": u["unitExecutionId"], "batchId": u["batchId"]} for u in units],
        },
        "batchLaunchDecision": "WAITING_HUMAN_EVIDENCE",
        "launchDecision": "WAITING_HUMAN_EVIDENCE",
        "physicalPilotBatchValidated": False,
        "physicalPrototypeValidated": False,
        "demandLabel": "MOCK",
        "label": "FIXTURE/REAL_LOGIC",
        "liveMachineControl": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
    }


def _run(mod, docs, scenario, **hooks):
    payload = {
        "inspect": _inspect(SHA),
        "acceptance_root": docs.parent / "acc",
        "platform": _FakePlat,
        "scenario": scenario,
    }
    payload.update(hooks)
    return mod.main(["--docs-root", str(docs), "--expected-commit", SHA], hooks=payload)


def test_pilot_batch_runner_binds_clean_head(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = _run(mod, docs, _passing)
    assert rc == 0
    body = json.loads((docs / "PILOT_BATCH_EXECUTION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert body["ok"] is True
    assert body["physicalPilotBatchValidated"] is False
    assert "batchAuthority" in body


def test_pilot_batch_runner_fixture_go_fails(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PILOT_BATCH_EXECUTION_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")

    def scenario(plat):
        body = _passing(plat)
        body["batchLaunchDecision"] = "HUMAN_BATCH_GO"
        return body

    rc = _run(mod, docs, scenario)
    assert rc != 0
    kept = json.loads((docs / "PILOT_BATCH_EXECUTION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True
