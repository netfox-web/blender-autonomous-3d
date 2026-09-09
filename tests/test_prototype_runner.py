"""run_prototype_validation_e2e fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fox3d.evidence import prepare_evidence_lineage
from fox3d.prototype import PRIOR_REAL_BLENDER, REQUIRED_BOARD_FIELDS, REQUIRED_MATRIX_KEYS

ROOT = Path(__file__).resolve().parents[1]
SHA = "c" * 40


def _load():
    path = ROOT / "scripts" / "run_prototype_validation_e2e.py"
    spec = importlib.util.spec_from_file_location("run_prototype_validation_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_prototype_validation_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _inspect(sha: str, *, clean: bool = True):
    def inspect(root, allow_dirty=False):
        porcelain = "" if clean else " M src/fox3d/prototype.py\n"
        return prepare_evidence_lineage(head_sha=sha, porcelain=porcelain, allow_dirty=allow_dirty)

    return inspect


class _FakePlat:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.mock_blender = True


def _board_row(i: int, **over) -> dict:
    row = {
        "candidateId": f"c{i}",
        "state": "WAITING_PHYSICAL_EVIDENCE",
        "rankingScore": 0.7,
        "rankingPolicyHash": "p" * 64,
        "conservationOk": True,
        "expectedUtilization": 0.6,
        "trueScrap": 100.0,
        "reusableRemnant": 50.0,
        "prototypeStatus": "WAITING_VALIDATION",
        "toleranceResult": {"ok": True, "failed": []},
        "dimensionalVariance": {},
        "assemblyObservedVsEstimated": {"complete": True},
        "observedCostLabel": "FIXTURE",
        "observedMonetaryVariance": None,
        "costCompleteness": "PARTIAL",
        "packagingPredictedVsObserved": {},
        "packagingValidation": {"ok": True, "complete": True},
        "qcStatus": {"complete": True, "source": "FIXTURE"},
        "realBlenderLineage": {"reused": True, "commitSha": PRIOR_REAL_BLENDER["commitSha"]},
        "demandLabel": "MOCK",
        "blockers": ["fixture_evidence"],
        "physicalPrototypeValidated": False,
        "liveMachineControl": False,
        "evidenceSource": "FIXTURE",
        "productionReady": False,
    }
    row.update(over)
    return row


def _matrix_row(i: int, **over) -> dict:
    row = {k: None for k in REQUIRED_MATRIX_KEYS}
    row.update(
        {
            "selectionId": f"s{i}",
            "candidateId": f"c{i}",
            "engineeringHash": f"e{i}",
            "canonicalHash": f"h{i}",
            "bomHash": f"b{i}",
            "nestingHash": f"n{i}",
            "rankingPolicyHash": "p" * 64,
            "prototypeUnitId": f"u{i}",
            "unitState": "WAITING_VALIDATION",
            "evidenceSource": "FIXTURE",
            "buildCompleted": True,
            "toleranceStatus": True,
            "qcStatus": {"complete": True},
            "costCompleteness": "PARTIAL",
            "observedCostLabel": "FIXTURE",
            "monetaryVarianceStatus": "PARTIAL",
            "packagingCompleteness": "COMPLETE",
            "packagingVarianceStatus": "ok",
            "ecoStatus": None,
            "decisionState": "WAITING_PHYSICAL_EVIDENCE",
            "blockers": ["fixture_evidence"],
            "physicalPrototypeValidated": False,
            "liveMachineControl": False,
            "consumesInventory": False,
            "inventoryLineage": None,
            "staleLineage": False,
        }
    )
    row.update(over)
    return row


def _passing(plat):
    return {
        "ok": True,
        "selected": [
            {"selectionId": f"s{i}", "candidateId": f"c{i}", "engineeringHash": f"e{i}", "canonicalHash": f"h{i}", "bomHash": f"b{i}", "nestingHash": f"n{i}", "truthLabel": "FIXTURE"}
            for i in range(4)
        ],
        "units": [
            {
                "prototypeUnitId": f"u{i}",
                "candidateId": f"c{i}",
                "engineeringHash": f"e{i}",
                "state": "WAITING_VALIDATION",
                "physicalPrototypeValidated": False,
                "evidenceSource": "FIXTURE",
                "buildCompleted": True,
                "consumesInventory": False,
                "materialConsumed": False,
                "truthLabel": "FIXTURE",
            }
            for i in range(4)
        ],
        "matrix": [_matrix_row(i) for i in range(4)],
        "physicalPrototypeValidated": False,
        "demandLabel": "MOCK",
        "liveMachineControl": False,
        "media": [],
        "board": {"rows": [_board_row(i) for i in range(4)]},
        "label": "FIXTURE/REAL_LOGIC",
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


def test_prototype_runner_binds_clean_head(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing},
    )
    assert rc == 0
    body = json.loads((docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert body["ok"] is True
    assert body["physicalPrototypeValidated"] is False
    assert body["liveMachineControl"] is False
    assert len(body["matrix"]) == 4
    assert body["priorRealBlenderEvidence"]["verified"] is True
    assert (docs / "SKU_LAUNCH_READINESS_ACCEPTANCE.md").exists()


def test_prototype_runner_dirty_does_not_overwrite(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA, clean=False), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing},
    )
    assert rc != 0
    kept = json.loads((docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_prototype_runner_mismatch_refuses(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", "d" * 40],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing},
    )
    assert rc != 0
    assert not (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").exists()


def test_prototype_runner_fixture_physical_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["physicalPrototypeValidated"] = True
        return body

    docs = tmp_path / "docs"
    rc = _run(mod, docs, scenario)
    assert rc != 0
    assert not (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").exists()


def test_prototype_runner_empty_board_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["board"] = {"rows": []}
        return body

    docs = tmp_path / "docs"
    rc = _run(mod, docs, scenario)
    assert rc != 0
    assert not (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").exists()


def test_prototype_runner_missing_board_field_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        del body["board"]["rows"][0]["packagingValidation"]
        return body

    docs = tmp_path / "docs"
    rc = _run(mod, docs, scenario)
    assert rc != 0


def test_prototype_runner_missing_packaging_contract_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["packagingCompleteness"] = "nope"
        return body

    docs = tmp_path / "docs"
    rc = _run(mod, docs, scenario)
    assert rc != 0


def test_prototype_runner_cost_complete_incorrect_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][1]["costCompleteness"] = "COMPLETE"
        body["matrix"][1]["observedCostLabel"] = "PARTIAL"
        return body

    docs = tmp_path / "docs"
    rc = _run(mod, docs, scenario)
    assert rc != 0


def test_prototype_runner_stale_lineage_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][2]["staleLineage"] = True
        return body

    docs = tmp_path / "docs"
    rc = _run(mod, docs, scenario)
    assert rc != 0


def test_prototype_runner_boolean_only_consume_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["units"][0]["consumesInventory"] = True
        body["units"][0]["materialConsumed"] = True
        body["units"][0]["inventoryLineage"] = None
        return body

    docs = tmp_path / "docs"
    rc = _run(mod, docs, scenario)
    assert rc != 0


def test_prototype_runner_tenant_restore_mismatch_fails(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={
            "inspect": _inspect(SHA),
            "acceptance_root": tmp_path / "acc",
            "platform": _FakePlat,
            "scenario": _passing,
            "restore_matrix": {"tenantLeakageAbsent": False, "tenantRequiredStatePreserved": False, "tenantStateDigest": {"equal": False}},
        },
    )
    assert rc != 0
    assert not (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").exists()


def test_prototype_runner_prior_media_missing_fails(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    empty_prior = tmp_path / "empty-docs"
    empty_prior.mkdir()
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={
            "inspect": _inspect(SHA),
            "acceptance_root": tmp_path / "acc",
            "platform": _FakePlat,
            "scenario": _passing,
            "prior_docs": empty_prior,
        },
    )
    assert rc != 0
    assert not (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").exists()
