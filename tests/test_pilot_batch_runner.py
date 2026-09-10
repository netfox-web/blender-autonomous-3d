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
    cartons = []
    labor = []
    qc = []
    materials = []
    costs = []
    board_rows = []
    for i in range(4):
        bid = f"b{i}"
        wo = f"wo{i}"
        rel = f"rel{i}"
        rh = f"rh{i}"
        uids = []
        alloc = []
        for s in range(5):
            uid = f"u{i}-{s}"
            uids.append(uid)
            units.append(
                {
                    "unitExecutionId": uid,
                    "tenantId": "pa",
                    "batchId": bid,
                    "selectionId": f"s{i}",
                    "prototypeUnitId": f"pu{i}",
                    "engineeringHash": f"e{i}",
                    "releaseId": rel,
                    "releaseHash": rh,
                    "workOrderId": wo,
                    "seq": s,
                    "state": "PACKED",
                    "sampled": True,
                    "startedBy": "op",
                    "consumedQuantity": 1.0,
                    "allocatedQuantity": 1.0,
                    "consumeKind": "BATCH_ALLOCATION_PROJECTION",
                    "reservationIds": [f"r{i}"],
                    "laborId": f"lb{i}-{s}",
                    "qcId": f"qc{i}-{s}",
                    "qcFinalId": f"qc{i}-{s}",
                    "cartonId": f"ct{i}",
                }
            )
            labor.append(
                {
                    "laborId": f"lb{i}-{s}",
                    "tenantId": "pa",
                    "batchId": bid,
                    "unitExecutionId": uid,
                    "minutes": 12,
                    "idempotencyKey": f"pa::batch-labor::{uid}::e{i}::12.0::assembly",
                    "reason": "assembly",
                    "engineeringHash": f"e{i}",
                }
            )
            qc.append(
                {
                    "qcId": f"qc{i}-{s}",
                    "tenantId": "pa",
                    "batchId": bid,
                    "unitExecutionId": uid,
                    "stage": "FINAL",
                    "ok": True,
                    "result": "PASS",
                    "qcPlanHash": f"qph{i}",
                    "engineeringHash": f"e{i}",
                    "releaseHash": rh,
                }
            )
            alloc.append({"unitExecutionId": uid, "quantity": 1.0})
        batches.append(
            {
                "batchId": bid,
                "tenantId": "pa",
                "candidateId": f"c{i}",
                "selectionId": f"s{i}",
                "prototypeUnitId": f"pu{i}",
                "engineeringHash": f"e{i}",
                "canonicalHash": f"h{i}",
                "bomHash": f"bom{i}",
                "nestingHash": f"n{i}",
                "rankingPolicyHash": "p" * 64,
                "releaseId": rel,
                "releaseHash": rh,
                "workOrderId": wo,
                "requestedQuantity": 5,
                "source": "FIXTURE",
                "truthLabel": "FIXTURE",
                "state": "IN_PROGRESS",
                "liveMachineControl": False,
                "cost": {"completeness": "PARTIAL", "truthLabel": "FIXTURE", "quantityLineage": {"ok": False}},
            }
        )
        cartons.append(
            {
                "cartonId": f"ct{i}",
                "tenantId": "pa",
                "batchId": bid,
                "unitExecutionIds": list(uids),
                "packagingQty": None,
                "checklistId": f"ck{i}",
                "engineeringHash": f"e{i}",
                "measured": {"lengthMm": 400, "widthMm": 300, "heightMm": 200, "weightKg": 8},
                "damageDefect": "OK",
                "hardwareObserved": 4,
                "partObserved": 6,
            }
        )
        materials.append(
            {
                "batchId": bid,
                "tenantId": "pa",
                "workOrderId": wo,
                "kind": "BATCH_ALLOCATION_PROJECTION",
                "consumedQuantity": 5.0,
                "reservationIds": [f"r{i}"],
                "lotIds": [f"lot{i}"],
                "unitAllocations": alloc,
            }
        )
        costs.append(
            {
                "costId": f"cost{i}",
                "tenantId": "pa",
                "batchId": bid,
                "completeness": "PARTIAL",
                "truthLabel": "FIXTURE",
                "quantityLineage": {"ok": False},
            }
        )
        board_rows.append({"batchId": bid, "tenantId": "pa", "decision": "WAITING_HUMAN_EVIDENCE", "state": "IN_PROGRESS"})
    authority = {
        "batches": [dict(b) for b in batches],
        "units": [dict(u) for u in units],
        "cartons": [dict(c) for c in cartons],
        "labor": labor,
        "qc": qc,
        "materials": materials,
        "costs": costs,
        "decisions": [],
    }
    return {
        "ok": True,
        "batches": batches,
        "units": units,
        "cartons": cartons,
        "board": {"decision": "WAITING_HUMAN_EVIDENCE", "rows": board_rows},
        "batchAuthority": authority,
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


def _assert_fail(tmp_path, mutate):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PILOT_BATCH_EXECUTION_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")

    def scenario(plat):
        body = _passing(plat)
        mutate(body)
        return body

    rc = _run(mod, docs, scenario)
    assert rc != 0
    kept = json.loads((docs / "PILOT_BATCH_EXECUTION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_pilot_batch_runner_empty_cartons_fail(tmp_path):
    _assert_fail(tmp_path, lambda body: body.__setitem__("cartons", []))


def test_pilot_batch_runner_empty_board_rows_fail(tmp_path):
    def mutate(body):
        body["board"] = {"decision": "WAITING_HUMAN_EVIDENCE", "rows": []}

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_missing_qc_authority_fail(tmp_path):
    def mutate(body):
        body["batchAuthority"]["qc"] = []

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_missing_material_authority_fail(tmp_path):
    def mutate(body):
        body["batchAuthority"]["materials"] = []

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_labor_covers_one_unit_fail(tmp_path):
    def mutate(body):
        body["batchAuthority"]["labor"] = [body["batchAuthority"]["labor"][0]]

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_batch_field_mismatch_fail(tmp_path):
    def mutate(body):
        body["batches"][0]["engineeringHash"] = "other-hash"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_unit_wrong_lineage_fail(tmp_path):
    def mutate(body):
        body["units"][0]["workOrderId"] = "wrong-wo"
        body["batchAuthority"]["units"][0]["workOrderId"] = "wrong-wo"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_coordinated_bogus_carton_fail(tmp_path):
    def mutate(body):
        body["cartons"][0]["cartonId"] = "bogus-ct"
        body["units"][0]["cartonId"] = "bogus-ct"
        for u in body["units"]:
            if u.get("batchId") == "b0":
                u["cartonId"] = "bogus-ct"
        body["cartons"][0]["cartonId"] = "bogus-ct"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_carton_missing_unit_fail(tmp_path):
    def mutate(body):
        body["cartons"][0]["unitExecutionIds"] = body["cartons"][0]["unitExecutionIds"][1:]
        body["batchAuthority"]["cartons"][0]["unitExecutionIds"] = body["cartons"][0]["unitExecutionIds"]

    _assert_fail(tmp_path, mutate)
