"""run_pilot_batch_e2e fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import copy
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
                    "releaseId": rel,
                    "workOrderId": wo,
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
                "executedQuantity": 5,
                "costId": f"cost{i}",
                "source": "FIXTURE",
                "truthLabel": "FIXTURE",
                "state": "IN_PROGRESS",
                "qcPlanHash": f"qph{i}",
                "reservationIds": [f"r{i}"],
                "lotIds": [f"lot{i}"],
                "consumedQuantity": 5.0,
                "allocationPolicy": "FIXTURE_AUTO_SEED",
                "consumeKind": "BATCH_ALLOCATION_PROJECTION",
                "liveMachineControl": False,
                "cost": {
                    "completeness": "PARTIAL",
                    "truthLabel": "FIXTURE",
                    "quantityLineage": {
                        "ok": False,
                        "sources": {
                            "materialQty": "MATERIAL_LOT",
                            "laborMinutes": "LABOR_RECORD",
                            "hardwareQty": "BOM",
                            "packagingQty": "MISSING",
                        },
                    },
                },
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
                "source": "FIXTURE",
                "truthLabel": "FIXTURE",
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
                "allocationPolicy": "FIXTURE_AUTO_SEED",
                "consumeKind": "BATCH_ALLOCATION_PROJECTION",
                "reservations": [
                    {
                        "reservationId": f"r{i}",
                        "lotId": f"lot{i}",
                        "quantity": 5,
                        "tenantId": "pa",
                        "workOrderId": wo,
                        "state": "CONSUMED",
                        "kind": "lot",
                    }
                ],
                "consumed": [
                    {
                        "reservationId": f"r{i}",
                        "lotId": f"lot{i}",
                        "quantity": 5,
                        "tenantId": "pa",
                        "workOrderId": wo,
                        "state": "CONSUMED",
                        "kind": "lot",
                    }
                ],
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
                "quantityLineage": {
                    "ok": False,
                    "sources": {
                        "materialQty": "MATERIAL_LOT",
                        "laborMinutes": "LABOR_RECORD",
                        "hardwareQty": "BOM",
                        "packagingQty": "MISSING",
                    },
                },
            }
        )
        board_rows.append(
            {
                "batchId": bid,
                "tenantId": "pa",
                "engineeringHash": f"e{i}",
                "decision": "WAITING_HUMAN_EVIDENCE",
                "state": "IN_PROGRESS",
                "blockers": ["cost_partial", "fixture_evidence"],
            }
        )
    decisions = [
        {
            "decisionId": f"derived:{b['batchId']}",
            "kind": "DERIVED_READINESS",
            "tenantId": "pa",
            "batchId": b["batchId"],
            "decision": "WAITING_HUMAN_EVIDENCE",
            "engineeringHash": b["engineeringHash"],
            "state": "IN_PROGRESS",
            "blockers": ["cost_partial", "fixture_evidence"],
        }
        for b in batches
    ]
    work_orders = [
        {
            "workOrderId": b["workOrderId"],
            "tenantId": "pa",
            "batchId": b["batchId"],
            "releaseId": b["releaseId"],
            "releaseHash": b["releaseHash"],
            "qcPlanHash": b["qcPlanHash"],
        }
        for b in batches
    ]
    authority = {
        "batches": copy.deepcopy(batches),
        "units": copy.deepcopy(units),
        "cartons": copy.deepcopy(cartons),
        "labor": copy.deepcopy(labor),
        "qc": copy.deepcopy(qc),
        "materials": copy.deepcopy(materials),
        "costs": copy.deepcopy(costs),
        "decisions": copy.deepcopy(decisions),
        "workOrders": copy.deepcopy(work_orders),
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


def test_pilot_batch_runner_qc_fail_not_pass(tmp_path):
    def mutate(body):
        body["batchAuthority"]["qc"][0]["result"] = "FAIL"
        body["batchAuthority"]["qc"][0]["ok"] = False

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_qc_wrong_plan_hash(tmp_path):
    def mutate(body):
        body["batchAuthority"]["qc"][0]["qcPlanHash"] = ""

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_qc_wrong_release(tmp_path):
    def mutate(body):
        body["batchAuthority"]["qc"][0]["releaseHash"] = "stale-rel"
        body["batchAuthority"]["qc"][0]["workOrderId"] = "wrong-wo"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_duplicate_final_qc(tmp_path):
    def mutate(body):
        dup = dict(body["batchAuthority"]["qc"][0])
        dup["qcId"] = "qc-dup"
        body["batchAuthority"]["qc"].append(dup)

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_board_duplicate_row(tmp_path):
    def mutate(body):
        body["board"]["rows"].append(dict(body["board"]["rows"][0]))

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_missing_decision_authority(tmp_path):
    def mutate(body):
        body["batchAuthority"]["decisions"] = []

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_coordinated_bogus_board_decision(tmp_path):
    def mutate(body):
        body["board"]["rows"][0]["decision"] = "HUMAN_BATCH_GO"
        body["batchAuthority"]["decisions"][0]["decision"] = "HUMAN_BATCH_GO"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_units_planned_skip_fail(tmp_path):
    def mutate(body):
        for unit in body["units"]:
            if unit.get("batchId") == "b0":
                unit["state"] = "PLANNED"
        for unit in body["batchAuthority"]["units"]:
            if unit.get("batchId") == "b0":
                unit["state"] = "PLANNED"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_executed_qty_mismatch(tmp_path):
    def mutate(body):
        body["batches"][0]["executedQuantity"] = 1
        body["batchAuthority"]["batches"][0]["executedQuantity"] = 1

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_carton_tenant_mismatch(tmp_path):
    def mutate(body):
        body["cartons"][0]["tenantId"] = "pb"
        body["batchAuthority"]["cartons"][0]["tenantId"] = "pb"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_material_bogus_unit(tmp_path):
    def mutate(body):
        body["batchAuthority"]["materials"][0]["unitAllocations"][0]["unitExecutionId"] = "ghost-unit"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_material_zero_qty(tmp_path):
    def mutate(body):
        body["batchAuthority"]["materials"][0]["unitAllocations"][0]["quantity"] = 0
        body["batchAuthority"]["materials"][0]["consumedQuantity"] = 4.0

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_labor_wrong_hash_or_minutes(tmp_path):
    def mutate(body):
        body["batchAuthority"]["labor"][0]["engineeringHash"] = "stale"
        body["batchAuthority"]["labor"][0]["minutes"] = 0

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_cost_wrong_lineage(tmp_path):
    def mutate(body):
        body["batchAuthority"]["costs"][0]["tenantId"] = "pb"
        body["batchAuthority"]["costs"][0]["batchId"] = "other"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_qc_wrong_nonempty_plan_hash(tmp_path):
    def mutate(body):
        body["batchAuthority"]["qc"][0]["qcPlanHash"] = "bogus-plan"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_qc_blank_id(tmp_path):
    def mutate(body):
        body["batchAuthority"]["qc"][0]["qcId"] = ""
        body["batchAuthority"]["units"][0]["qcId"] = ""
        body["batchAuthority"]["units"][0]["qcFinalId"] = ""

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_qc_id_mismatch(tmp_path):
    def mutate(body):
        body["batchAuthority"]["units"][0]["qcId"] = "other-qc"
        body["batchAuthority"]["units"][0]["qcFinalId"] = "other-qc"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_qc_blank_workorder(tmp_path):
    def mutate(body):
        body["batchAuthority"]["qc"][0]["workOrderId"] = ""
        body["batchAuthority"]["qc"][0]["releaseHash"] = ""
        body["batchAuthority"]["qc"][0]["releaseId"] = ""

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_ghost_decision(tmp_path):
    def mutate(body):
        body["batchAuthority"]["decisions"].append(
            {
                "decisionId": "ghost",
                "kind": "DERIVED_READINESS",
                "tenantId": "pa",
                "batchId": "ghost-batch",
                "decision": "WAITING_HUMAN_EVIDENCE",
                "engineeringHash": "e0",
                "state": "IN_PROGRESS",
                "blockers": ["fixture_evidence", "cost_partial"],
            }
        )

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_decision_kind_blank(tmp_path):
    def mutate(body):
        body["batchAuthority"]["decisions"][0]["kind"] = None

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_coordinated_state_not_readiness(tmp_path):
    def mutate(body):
        body["board"]["rows"][0]["state"] = "HOLD"
        body["batchAuthority"]["decisions"][0]["state"] = "HOLD"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_coordinated_blockers(tmp_path):
    def mutate(body):
        body["board"]["rows"][0]["blockers"] = ["other"]
        body["batchAuthority"]["decisions"][0]["blockers"] = ["other"]

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_carton_measured_mismatch(tmp_path):
    def mutate(body):
        body["cartons"][0]["measured"]["lengthMm"] = 401

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_carton_damage_fail(tmp_path):
    def mutate(body):
        body["cartons"][0]["damageDefect"] = "DAMAGED"
        body["batchAuthority"]["cartons"][0]["damageDefect"] = "DAMAGED"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_carton_source_mismatch(tmp_path):
    def mutate(body):
        body["cartons"][0]["source"] = "MANUAL"
        body["batchAuthority"]["cartons"][0]["source"] = "MANUAL"
        body["cartons"][0]["truthLabel"] = "MANUAL_EVIDENCE"
        body["batchAuthority"]["cartons"][0]["truthLabel"] = "MANUAL_EVIDENCE"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_bogus_reservation(tmp_path):
    def mutate(body):
        body["batchAuthority"]["materials"][0]["reservationIds"] = ["ghost-res"]
        body["batches"][0]["reservationIds"] = ["ghost-res"]
        body["batchAuthority"]["batches"][0]["reservationIds"] = ["ghost-res"]

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_unit_allocation_mismatch(tmp_path):
    def mutate(body):
        body["batchAuthority"]["materials"][0]["unitAllocations"][0]["quantity"] = 4.0
        body["batchAuthority"]["materials"][0]["unitAllocations"][1]["quantity"] = 0.0

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_consumed_qty_zero(tmp_path):
    def mutate(body):
        body["units"][0]["consumedQuantity"] = 0
        body["units"][0]["allocatedQuantity"] = 0
        body["batchAuthority"]["units"][0]["consumedQuantity"] = 0
        body["batchAuthority"]["units"][0]["allocatedQuantity"] = 0

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_labor_blank_idempotency(tmp_path):
    def mutate(body):
        body["batchAuthority"]["labor"][0]["idempotencyKey"] = ""

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_labor_id_mismatch(tmp_path):
    def mutate(body):
        body["batchAuthority"]["units"][0]["laborId"] = "other-lb"
        body["units"][0]["laborId"] = "other-lb"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_ghost_labor(tmp_path):
    def mutate(body):
        body["batchAuthority"]["labor"].append(
            {
                "laborId": "ghost-lb",
                "tenantId": "pa",
                "batchId": "b0",
                "unitExecutionId": "ghost-unit",
                "minutes": 12,
                "idempotencyKey": "pa::batch-labor::ghost-unit::e0::12.0::assembly",
                "reason": "assembly",
                "engineeringHash": "e0",
            }
        )

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_cost_blank_id(tmp_path):
    def mutate(body):
        body["batchAuthority"]["costs"][0]["costId"] = ""
        body["batches"][0]["costId"] = ""
        body["batchAuthority"]["batches"][0]["costId"] = ""

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_cost_id_mismatch(tmp_path):
    def mutate(body):
        body["batches"][0]["costId"] = "other-cost"
        body["batchAuthority"]["batches"][0]["costId"] = "other-cost"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_ghost_cost(tmp_path):
    def mutate(body):
        body["batchAuthority"]["costs"].append(
            {
                "costId": "ghost-cost",
                "tenantId": "pa",
                "batchId": "ghost-batch",
                "completeness": "PARTIAL",
                "truthLabel": "FIXTURE",
                "quantityLineage": {"ok": False, "sources": {"materialQty": "MATERIAL_LOT", "laborMinutes": "LABOR_RECORD", "hardwareQty": "BOM", "packagingQty": "MISSING"}},
            }
        )

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_lineage_source_tamper(tmp_path):
    def mutate(body):
        body["batchAuthority"]["costs"][0]["quantityLineage"]["sources"]["packagingQty"] = "PACKAGING_CHECKLIST"
        body["batches"][0]["cost"]["quantityLineage"]["sources"]["packagingQty"] = "PACKAGING_CHECKLIST"
        body["batchAuthority"]["costs"][0]["quantityLineage"]["ok"] = True
        body["batches"][0]["cost"]["quantityLineage"]["ok"] = True

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_qc_coordinated_plan_hash(tmp_path):
    def mutate(body):
        body["batchAuthority"]["qc"][0]["qcPlanHash"] = "bogus-plan"
        body["batchAuthority"]["batches"][0]["qcPlanHash"] = "bogus-plan"
        body["batches"][0]["qcPlanHash"] = "bogus-plan"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_ghost_material(tmp_path):
    def mutate(body):
        ghost = copy.deepcopy(body["batchAuthority"]["materials"][0])
        ghost["batchId"] = "ghost-batch"
        ghost["workOrderId"] = "ghost-wo"
        body["batchAuthority"]["materials"].append(ghost)

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_reservation_cross_tenant(tmp_path):
    def mutate(body):
        body["batchAuthority"]["materials"][0]["reservations"][0]["tenantId"] = "pb"
        body["batchAuthority"]["materials"][0]["consumed"][0]["tenantId"] = "pb"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_top_reservation_mismatch(tmp_path):
    def mutate(body):
        body["batches"][0]["reservationIds"] = ["other-r"]

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_unit_wrong_carton_coverage(tmp_path):
    def mutate(body):
        body["units"][0]["cartonId"] = "ct1"
        body["batchAuthority"]["units"][0]["cartonId"] = "ct1"

    _assert_fail(tmp_path, mutate)


def test_pilot_batch_runner_board_blank_tenant(tmp_path):
    def mutate(body):
        body["board"]["rows"][0]["tenantId"] = ""
        body["batchAuthority"]["decisions"][0]["tenantId"] = ""

    _assert_fail(tmp_path, mutate)
