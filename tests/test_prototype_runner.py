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
    assert "packagingChecklistAuthority" in body
    assert "laborAuthority" in body
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


def _qty_lineage(i: int, **over) -> dict:
    body = {
        "ok": True,
        "materialQty": 2,
        "laborMinutes": 30,
        "hardwareQty": 4,
        "packagingQty": 1,
        "packagingChecklistId": f"ck{i}",
        "sources": {
            "materialQty": "MATERIAL_LOT",
            "laborMinutes": "LABOR_RECORD",
            "hardwareQty": "PACKAGING_QC",
            "packagingQty": "PACKAGING_CHECKLIST",
        },
        "laborLineage": {
            "ok": True,
            "integrityOk": True,
            "laborIds": [f"lb{i}"],
            "semanticKeys": [f"pa::labor::u{i}::e{i}::30.0::assembly"],
            "minutes": 30,
            "source": "LABOR_RECORD",
            "duplicateKeys": [],
        },
        "packagingLineage": {
            "checklistId": f"ck{i}",
            "tenantId": "pa",
            "prototypeUnitId": f"u{i}",
            "engineeringHash": f"e{i}",
            "packagingQty": 1,
            "source": "PACKAGING_CHECKLIST",
            "truthLabel": "MANUAL_EVIDENCE",
        },
    }
    body.update(over)
    return body


def _pack_lineage(i: int, **over) -> dict:
    body = {
        "checklistId": f"ck{i}",
        "tenantId": "pa",
        "prototypeUnitId": f"u{i}",
        "engineeringHash": f"e{i}",
        "packagingQty": 1,
        "source": "PACKAGING_CHECKLIST",
        "truthLabel": "MANUAL_EVIDENCE",
    }
    body.update(over)
    return body


def _ck_authority(i: int, **over) -> dict:
    body = _pack_lineage(i)
    body.update(over)
    return body


def _lb_authority(i: int, **over) -> dict:
    body = {
        "laborId": f"lb{i}",
        "tenantId": "pa",
        "prototypeUnitId": f"u{i}",
        "engineeringHash": f"e{i}",
        "minutes": 30,
        "reason": "assembly",
        "idempotencyKey": f"pa::labor::u{i}::e{i}::30.0::assembly",
        "source": "LABOR_RECORD",
    }
    body.update(over)
    return body


def _manual_go(plat, mutate=None):
    body = _passing(plat)
    body["launchDecision"] = "HUMAN_GO"
    body["physicalPrototypeValidated"] = True
    body["label"] = "MANUAL_EVIDENCE"
    body["board"] = {
        "rows": [
            _board_row(
                i,
                launchDecision="HUMAN_GO",
                evidenceSource="MANUAL",
                physicalPrototypeValidated=True,
                observedCostLabel="MANUAL",
                costCompleteness="COMPLETE",
                tenantId="pa",
            )
            for i in range(4)
        ]
    }
    body["selectedBoard"] = list(body["board"]["rows"])
    for i, row in enumerate(body["matrix"]):
        row.update(
            {
                "tenantId": "pa",
                "costCompleteness": "COMPLETE",
                "observedCostLabel": "MANUAL",
                "launchDecision": "HUMAN_GO",
                "evidenceSource": "MANUAL",
                "inventoryLineage": {"reservationIds": ["r1"], "consumedQuantity": 2, "workOrderId": "wo"},
                "physicalPrototypeValidated": True,
                "decisionState": "HUMAN_GO",
                "packagingQty": 1,
                "packagingLineage": _pack_lineage(i),
                "quantityLineage": _qty_lineage(i),
            }
        )
    for pkg in body["evidencePackages"]:
        pkg["evidenceSource"] = "MANUAL_EVIDENCE"
        pkg["damRefs"] = [
            {"role": "AS_BUILT", "assetId": "a", "sha256": "aa", "size": 12},
            {"role": "PACKAGING", "assetId": "b", "sha256": "bb", "size": 12},
        ]
    for unit in body["units"]:
        unit["physicalPrototypeValidated"] = True
        unit["materialConsumed"] = True
        unit["inventoryLineage"] = {"reservationIds": ["r1"], "consumedQuantity": 2, "workOrderId": "wo"}
        unit["evidenceSource"] = "MANUAL"
        unit["truthLabel"] = "MANUAL_EVIDENCE"
        unit["tenantId"] = "pa"
    body["packagingChecklistAuthority"] = [_ck_authority(i) for i in range(4)]
    body["laborAuthority"] = [_lb_authority(i) for i in range(4)]
    if mutate:
        mutate(body)
    return body


def test_prototype_runner_complete_cost_without_packaging_qty_fails(tmp_path):
    def scenario(plat):
        body = _passing(plat)
        body["launchDecision"] = "HUMAN_GO"
        body["physicalPrototypeValidated"] = True
        body["label"] = "MANUAL_EVIDENCE"
        for row in body["matrix"]:
            row["costCompleteness"] = "COMPLETE"
            row["observedCostLabel"] = "MANUAL"
            row["launchDecision"] = "HUMAN_GO"
            row["evidenceSource"] = "MANUAL"
            row["inventoryLineage"] = {"reservationIds": ["r1"], "consumedQuantity": 2, "workOrderId": "wo"}
            row["quantityLineage"] = {
                "ok": True,
                "materialQty": 2,
                "laborMinutes": 30,
                "hardwareQty": 4,
                "packagingQty": None,
                "sources": {
                    "materialQty": "MATERIAL_LOT",
                    "laborMinutes": "LABOR_RECORD",
                    "hardwareQty": "PACKAGING_QC",
                    "packagingQty": "MISSING",
                },
            }
        for pkg in body["evidencePackages"]:
            pkg["evidenceSource"] = "MANUAL_EVIDENCE"
            pkg["damRefs"] = [
                {"role": "AS_BUILT", "assetId": "a", "sha256": "aa", "size": 12},
                {"role": "PACKAGING", "assetId": "b", "sha256": "bb", "size": 12},
            ]
        for unit in body["units"]:
            unit["physicalPrototypeValidated"] = True
            unit["materialConsumed"] = True
            unit["inventoryLineage"] = {"reservationIds": ["r1"], "consumedQuantity": 2, "workOrderId": "wo"}
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


def _mutate_first_matrix(body, **over):
    body["matrix"][0].update(over)
    if "quantityLineage" in over and isinstance(over["quantityLineage"], dict):
        body["matrix"][0]["quantityLineage"] = over["quantityLineage"]
    if "packagingLineage" in over:
        body["matrix"][0]["packagingLineage"] = over["packagingLineage"]


def test_prototype_runner_missing_packaging_checklist_id_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            lineage = dict(body["matrix"][0]["quantityLineage"])
            lineage["packagingChecklistId"] = None
            body["matrix"][0]["quantityLineage"] = lineage

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_bogus_packaging_checklist_id_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            lineage = dict(body["matrix"][0]["quantityLineage"])
            lineage["packagingChecklistId"] = "bogus-ck"
            body["matrix"][0]["quantityLineage"] = lineage

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_packaging_lineage_wrong_tenant_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            pack = dict(body["matrix"][0]["packagingLineage"])
            pack["tenantId"] = "pb"
            body["matrix"][0]["packagingLineage"] = pack

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_packaging_lineage_wrong_unit_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            pack = dict(body["matrix"][0]["packagingLineage"])
            pack["prototypeUnitId"] = "other-unit"
            body["matrix"][0]["packagingLineage"] = pack

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_packaging_lineage_stale_engineering_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            pack = dict(body["matrix"][0]["packagingLineage"])
            pack["engineeringHash"] = "stale-hash"
            body["matrix"][0]["packagingLineage"] = pack

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_matrix_packaging_qty_mismatch_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            body["matrix"][0]["packagingQty"] = 9

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_lineage_packaging_qty_mismatch_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            pack = dict(body["matrix"][0]["packagingLineage"])
            pack["packagingQty"] = 7
            body["matrix"][0]["packagingLineage"] = pack

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_packaging_source_without_lineage_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            body["matrix"][0]["packagingLineage"] = None

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_duplicate_labor_semantic_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            lineage = dict(body["matrix"][0]["quantityLineage"])
            labor = dict(lineage["laborLineage"])
            labor["laborIds"] = ["lb0", "lb0-dup"]
            labor["semanticKeys"] = [labor["semanticKeys"][0], labor["semanticKeys"][0]]
            labor["duplicateKeys"] = [labor["semanticKeys"][0]]
            labor["integrityOk"] = False
            labor["ok"] = False
            labor["minutes"] = 60
            lineage["laborLineage"] = labor
            lineage["laborMinutes"] = 60
            body["matrix"][0]["quantityLineage"] = lineage

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_labor_total_inconsistent_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            lineage = dict(body["matrix"][0]["quantityLineage"])
            labor = dict(lineage["laborLineage"])
            labor["minutes"] = 12
            lineage["laborLineage"] = labor
            lineage["laborMinutes"] = 30
            body["matrix"][0]["quantityLineage"] = lineage

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_manual_go_authority_validates():
    from fox3d.prototype import project_published_prototype_truth, validate_prototype_acceptance_result

    body = project_published_prototype_truth(_manual_go(None))
    assert validate_prototype_acceptance_result(body) == []
    assert len(body.get("packagingChecklistAuthority") or []) == 4
    assert len(body.get("laborAuthority") or []) == 4


def test_prototype_runner_coordinated_bogus_checklist_id_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            lineage = dict(body["matrix"][0]["quantityLineage"])
            lineage["packagingChecklistId"] = "bogus-ck"
            body["matrix"][0]["quantityLineage"] = lineage
            pack = dict(body["matrix"][0]["packagingLineage"])
            pack["checklistId"] = "bogus-ck"
            body["matrix"][0]["packagingLineage"] = pack

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_missing_authoritative_checklist_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            body["packagingChecklistAuthority"] = [
                r for r in body["packagingChecklistAuthority"] if r.get("checklistId") != "ck0"
            ]

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_duplicate_authoritative_checklist_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["packagingChecklistAuthority"])
            auth.append(dict(auth[0]))
            body["packagingChecklistAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_checklist_blank_tenant_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["packagingChecklistAuthority"])
            rec = dict(auth[0])
            rec["tenantId"] = ""
            auth[0] = rec
            body["packagingChecklistAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_checklist_wrong_tenant_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["packagingChecklistAuthority"])
            rec = dict(auth[0])
            rec["tenantId"] = "pb"
            auth[0] = rec
            body["packagingChecklistAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_checklist_wrong_unit_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["packagingChecklistAuthority"])
            rec = dict(auth[0])
            rec["prototypeUnitId"] = "other-unit"
            auth[0] = rec
            body["packagingChecklistAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_checklist_stale_hash_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["packagingChecklistAuthority"])
            rec = dict(auth[0])
            rec["engineeringHash"] = "stale-hash"
            auth[0] = rec
            body["packagingChecklistAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_checklist_qty_differs_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["packagingChecklistAuthority"])
            rec = dict(auth[0])
            rec["packagingQty"] = 9
            auth[0] = rec
            body["packagingChecklistAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_quantity_lineage_qty_differs_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            lineage = dict(body["matrix"][0]["quantityLineage"])
            lineage["packagingQty"] = 8
            body["matrix"][0]["quantityLineage"] = lineage

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_contradictory_packaging_source_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            lineage = dict(body["matrix"][0]["quantityLineage"])
            sources = dict(lineage.get("sources") or {})
            sources["packagingQty"] = "INFERRED"
            lineage["sources"] = sources
            body["matrix"][0]["quantityLineage"] = lineage

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_fake_labor_lineage_without_authority_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            lineage = dict(body["matrix"][0]["quantityLineage"])
            lineage["laborLineage"] = {
                "ok": True,
                "integrityOk": True,
                "laborIds": ["fake-lb"],
                "semanticKeys": ["pa::labor::u0::e0::30.0::assembly"],
                "minutes": 30,
                "source": "LABOR_RECORD",
                "duplicateKeys": [],
            }
            lineage["laborMinutes"] = 30
            body["matrix"][0]["quantityLineage"] = lineage

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_missing_authoritative_labor_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            body["laborAuthority"] = [r for r in body["laborAuthority"] if r.get("laborId") != "lb0"]

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_duplicate_authoritative_labor_semantic_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["laborAuthority"])
            dup = dict(auth[0])
            dup["laborId"] = "lb0-dup"
            auth.append(dup)
            body["laborAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_duplicate_authoritative_labor_id_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["laborAuthority"])
            auth.append(dict(auth[0]))
            body["laborAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_labor_wrong_tenant_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["laborAuthority"])
            rec = dict(auth[0])
            rec["tenantId"] = "pb"
            auth[0] = rec
            body["laborAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_labor_wrong_unit_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["laborAuthority"])
            rec = dict(auth[0])
            rec["prototypeUnitId"] = "other-unit"
            auth[0] = rec
            body["laborAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_labor_stale_hash_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["laborAuthority"])
            rec = dict(auth[0])
            rec["engineeringHash"] = "stale-hash"
            auth[0] = rec
            body["laborAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_labor_semantic_mismatch_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["laborAuthority"])
            rec = dict(auth[0])
            rec["reason"] = "other-reason"
            auth[0] = rec
            body["laborAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_authoritative_labor_minutes_differ_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            auth = list(body["laborAuthority"])
            rec = dict(auth[0])
            rec["minutes"] = 99
            auth[0] = rec
            body["laborAuthority"] = auth

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)


def test_prototype_runner_workorder_complete_without_labor_authority_fails(tmp_path):
    def scenario(plat):
        def mutate(body):
            body["laborAuthority"] = []
            lineage = dict(body["matrix"][0]["quantityLineage"])
            lineage["laborLineage"] = {
                "ok": True,
                "integrityOk": True,
                "laborIds": ["wo:wo0"],
                "semanticKeys": ["pa::labor::u0::e0::30.0::"],
                "minutes": 30,
                "source": "WORKORDER",
                "duplicateKeys": [],
            }
            lineage["laborMinutes"] = 30
            sources = dict(lineage.get("sources") or {})
            sources["laborMinutes"] = "WORKORDER"
            lineage["sources"] = sources
            body["matrix"][0]["quantityLineage"] = lineage

        return _manual_go(plat, mutate)

    _assert_no_overwrite(_load(), tmp_path, scenario)
