"""run_prototype_validation_e2e fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fox3d.evidence import prepare_evidence_lineage
from fox3d.prototype import PACKAGING_POLICY_HASH, PRIOR_REAL_BLENDER, REQUIRED_BOARD_FIELDS, REQUIRED_MATRIX_KEYS

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


def _ok_var():
    return {"ok": True, "complete": True}


def _board_row(i: int, **over) -> dict:
    row = {
        "candidateId": f"c{i}",
        "selectionId": f"s{i}",
        "prototypeUnitId": f"u{i}",
        "engineeringHash": f"e{i}",
        "canonicalHash": f"h{i}",
        "bomHash": f"b{i}",
        "nestingHash": f"n{i}",
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
        "assemblyObservedVsEstimated": _ok_var(),
        "observedCostLabel": "FIXTURE",
        "observedMonetaryVariance": None,
        "costCompleteness": "PARTIAL",
        "packagingPredictedVsObserved": {
            "cartonLengthMm": _ok_var(),
            "cartonWidthMm": _ok_var(),
            "cartonHeightMm": _ok_var(),
            "packedWeightKg": _ok_var(),
        },
        "packagingValidation": {"ok": True, "complete": True, "packagingPolicyHash": PACKAGING_POLICY_HASH},
        "qcStatus": {"complete": True, "source": "FIXTURE"},
        "realBlenderLineage": {"reused": True, "commitSha": PRIOR_REAL_BLENDER["commitSha"]},
        "demandLabel": "MOCK",
        "blockers": ["fixture_evidence"],
        "physicalPrototypeValidated": False,
        "liveMachineControl": False,
        "evidenceSource": "FIXTURE",
        "productionReady": False,
        "launchDecision": "WAITING_HUMAN_EVIDENCE",
        "evidencePackageId": f"p{i}",
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
            "packagingValidation": {"ok": True, "packagingPolicyHash": PACKAGING_POLICY_HASH},
            "packagingPredictedVsObserved": {
                "cartonLengthMm": _ok_var(),
                "cartonWidthMm": _ok_var(),
                "cartonHeightMm": _ok_var(),
                "packedWeightKg": _ok_var(),
            },
            "assemblyObservedVsEstimated": _ok_var(),
            "ecoStatus": None,
            "decisionState": "WAITING_PHYSICAL_EVIDENCE",
            "blockers": ["fixture_evidence"],
            "physicalPrototypeValidated": False,
            "liveMachineControl": False,
            "consumesInventory": False,
            "inventoryLineage": None,
            "staleLineage": False,
            "launchDecision": "WAITING_HUMAN_EVIDENCE",
            "evidencePackageId": f"p{i}",
        }
    )
    row.update(over)
    return row


def _passing(plat):
    return {
        "ok": True,
        "selected": [
            {"selectionId": f"s{i}", "candidateId": f"c{i}", "engineeringHash": f"e{i}", "canonicalHash": f"h{i}", "bomHash": f"b{i}", "nestingHash": f"n{i}", "rankingPolicyHash": "p" * 64, "truthLabel": "FIXTURE"}
            for i in range(4)
        ],
        "units": [
            {
                "prototypeUnitId": f"u{i}",
                "candidateId": f"c{i}",
                "selectionId": f"s{i}",
                "engineeringHash": f"e{i}",
                "canonicalHash": f"h{i}",
                "bomHash": f"b{i}",
                "nestingHash": f"n{i}",
                "rankingPolicyHash": "p" * 64,
                "state": "WAITING_VALIDATION",
                "physicalPrototypeValidated": False,
                "evidenceSource": "FIXTURE",
                "buildCompleted": True,
                "consumesInventory": False,
                "materialConsumed": False,
                "truthLabel": "FIXTURE",
                "evidencePackageId": f"p{i}",
            }
            for i in range(4)
        ],
        "matrix": [_matrix_row(i) for i in range(4)],
        "physicalPrototypeValidated": False,
        "demandLabel": "MOCK",
        "liveMachineControl": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "media": [],
        "board": {"rows": [_board_row(i) for i in range(4)]},
        "evidencePackages": [
            {
                "evidencePackageId": f"p{i}",
                "candidateId": f"c{i}",
                "selectionId": f"s{i}",
                "prototypeUnitId": f"u{i}",
                "engineeringHash": f"e{i}",
                "canonicalHash": f"h{i}",
                "bomHash": f"b{i}",
                "nestingHash": f"n{i}",
                "rankingPolicyHash": "p" * 64,
                "evidenceSource": "FIXTURE",
                "engineeringRevision": 1,
                "ecoRevision": None,
                "state": "FINALIZED",
                "revision": 1,
                "operatorId": "fixture",
                "shiftId": "sh1",
            }
            for i in range(4)
        ],
        "launchDecision": "WAITING_HUMAN_EVIDENCE",
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
    for unit in body["units"]:
        for key in ("selectionId", "canonicalHash", "bomHash", "nestingHash", "rankingPolicyHash", "prototypeUnitId"):
            assert unit.get(key)
    for sel in body["selected"]:
        assert sel.get("rankingPolicyHash")
        assert sel.get("prototypeUnitId")
    assert len(body["selectedBoard"]) == 4


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


def _assert_no_overwrite(mod, tmp_path, scenario):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")
    rc = _run(mod, docs, scenario)
    assert rc != 0
    kept = json.loads((docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_prototype_runner_tolerance_false_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["toleranceStatus"] = False
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_missing_tolerance_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        del body["matrix"][0]["toleranceStatus"]
        return body

    docs = tmp_path / "docs"
    rc = _run(mod, docs, scenario)
    assert rc != 0


def test_prototype_runner_packaging_missing_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["packagingCompleteness"] = "MISSING"
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_packaging_partial_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["packagingCompleteness"] = "PARTIAL"
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_packaging_validation_false_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["packagingValidation"] = {"ok": False, "reason": "oversize"}
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_packaging_variance_contradiction_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["packagingValidation"] = {"ok": True}
        body["matrix"][0]["packagingPredictedVsObserved"] = {"packedWeightKg": {"ok": False, "target": 20, "actual": 13}}
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_qc_incomplete_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["qcStatus"] = {"complete": False, "missing": ["hardware"]}
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


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


def test_prototype_runner_missing_each_packaging_variance_field_fails(tmp_path):
    mod = _load()
    for field in ("cartonLengthMm", "cartonWidthMm", "cartonHeightMm", "packedWeightKg"):

        def scenario(plat, missing=field):
            body = _passing(plat)
            del body["matrix"][0]["packagingPredictedVsObserved"][missing]
            return body

        _assert_no_overwrite(mod, tmp_path / field, scenario)


def test_prototype_runner_malformed_packaging_variance_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["packagingPredictedVsObserved"]["cartonLengthMm"] = {"ok": True, "complete": False}
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_assembly_variance_missing_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        del body["matrix"][0]["assemblyObservedVsEstimated"]
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_assembly_variance_incomplete_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["assemblyObservedVsEstimated"] = {"ok": True, "complete": False}
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_assembly_variance_false_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["assemblyObservedVsEstimated"] = {"ok": False, "complete": True}
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_packaging_policy_hash_mismatch_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["packagingValidation"] = {"ok": True, "packagingPolicyHash": "stale"}
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_buildcompleted_mismatch_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["units"][0]["buildCompleted"] = False
        body["units"][0]["state"] = "WAITING_VALIDATION"
        body["matrix"][0]["buildCompleted"] = True
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_selected_matrix_candidate_mismatch_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["candidateId"] = "other"
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_engineering_hash_mismatch_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["units"][0]["engineeringHash"] = "other-hash"
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_bom_nesting_ranking_mismatch_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["matrix"][0]["bomHash"] = "other-bom"
        body["matrix"][0]["nestingHash"] = "other-nest"
        body["matrix"][0]["rankingPolicyHash"] = "other-rank"
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_duplicate_selected_candidate_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["selected"][1]["candidateId"] = body["selected"][0]["candidateId"]
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_selected_absent_from_board_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["board"]["rows"] = body["board"]["rows"][1:]
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def test_prototype_runner_board_matrix_physical_contradiction_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["board"]["rows"][0]["physicalPrototypeValidated"] = True
        body["matrix"][0]["physicalPrototypeValidated"] = False
        return body

    _assert_no_overwrite(mod, tmp_path, scenario)


def _lineage_drop_scenario(field, target="units"):
    def scenario(plat):
        body = _passing(plat)
        if target == "units":
            body["units"][0][field] = None
        elif target == "selected":
            body["selected"][0][field] = None
        elif target == "board":
            body["board"]["rows"][0][field] = ""
        return body

    return scenario


def test_prototype_runner_unit_selection_id_missing_fails(tmp_path):
    _assert_no_overwrite(_load(), tmp_path, _lineage_drop_scenario("selectionId"))


def test_prototype_runner_unit_canonical_hash_missing_fails(tmp_path):
    _assert_no_overwrite(_load(), tmp_path, _lineage_drop_scenario("canonicalHash"))


def test_prototype_runner_unit_bom_nesting_ranking_missing_fails(tmp_path):
    mod = _load()
    for field in ("bomHash", "nestingHash", "rankingPolicyHash"):
        _assert_no_overwrite(mod, tmp_path / field, _lineage_drop_scenario(field))


def test_prototype_runner_selected_ranking_policy_missing_fails(tmp_path):
    _assert_no_overwrite(_load(), tmp_path, _lineage_drop_scenario("rankingPolicyHash", "selected"))


def test_prototype_runner_empty_lineage_string_fails(tmp_path):
    def scenario(plat):
        body = _passing(plat)
        body["units"][0]["engineeringHash"] = ""
        return body

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_board_hash_empty_fails(tmp_path):
    _assert_no_overwrite(_load(), tmp_path, _lineage_drop_scenario("rankingPolicyHash", "board"))


def test_prototype_runner_selected_board_duplicate_fails(tmp_path):
    def scenario(plat):
        body = _passing(plat)
        body["selectedBoard"] = [body["board"]["rows"][0], body["board"]["rows"][0], body["board"]["rows"][2], body["board"]["rows"][3]]
        return body

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_serializer_drop_rolls_back(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")

    def mutate(result):
        units = list(result.get("units") or [])
        if units:
            dropped = dict(units[0])
            dropped.pop("canonicalHash", None)
            result = dict(result)
            result["units"] = [dropped, *units[1:]]
        return result

    rc = _run(mod, docs, _passing, mutate_published=mutate)
    assert rc != 0
    kept = json.loads((docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_prototype_runner_package_lineage_drop_rolls_back(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")

    def mutate(result):
        pkgs = list(result.get("evidencePackages") or [])
        if pkgs:
            dropped = dict(pkgs[0])
            dropped.pop("evidencePackageId", None)
            dropped.pop("engineeringHash", None)
            result = dict(result)
            result["evidencePackages"] = [dropped, *pkgs[1:]]
        return result

    rc = _run(mod, docs, _passing, mutate_published=mutate)
    assert rc != 0
    kept = json.loads((docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_prototype_runner_fixture_human_go_fails(tmp_path):
    def scenario(plat):
        body = _passing(plat)
        body["launchDecision"] = "HUMAN_GO"
        return body

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_missing_packages_fail(tmp_path):
    def scenario(plat):
        body = _passing(plat)
        body["evidencePackages"] = []
        return body

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_manual_go_without_dam_fails(tmp_path):
    def scenario(plat):
        body = _passing(plat)
        body["launchDecision"] = "HUMAN_GO"
        body["physicalPrototypeValidated"] = True
        body["label"] = "MANUAL_EVIDENCE"
        for pkg in body["evidencePackages"]:
            pkg["evidenceSource"] = "MANUAL_EVIDENCE"
            pkg["damRefs"] = []
        for unit in body["units"]:
            unit["physicalPrototypeValidated"] = True
            unit["evidenceSource"] = "MANUAL"
            unit["truthLabel"] = "MANUAL_EVIDENCE"
        return body

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_complete_cost_without_qty_fails(tmp_path):
    def scenario(plat):
        body = _passing(plat)
        body["launchDecision"] = "HUMAN_GO"
        body["label"] = "MANUAL_EVIDENCE"
        for row in body["matrix"]:
            row["costCompleteness"] = "COMPLETE"
            row["observedCostLabel"] = "MANUAL"
            row["launchDecision"] = "HUMAN_GO"
            row["evidenceSource"] = "MANUAL"
        for pkg in body["evidencePackages"]:
            pkg["evidenceSource"] = "MANUAL_EVIDENCE"
            pkg["damRefs"] = [
                {"role": "AS_BUILT", "assetId": "a", "sha256": "aa", "size": 12},
                {"role": "PACKAGING", "assetId": "b", "sha256": "bb", "size": 12},
            ]
        for unit in body["units"]:
            unit["physicalPrototypeValidated"] = True
            unit["materialConsumed"] = False
            unit["inventoryLineage"] = None
            unit["evidenceSource"] = "MANUAL"
        return body

    _assert_no_overwrite(_load(), tmp_path, scenario)
