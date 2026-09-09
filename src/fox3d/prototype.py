"""Phase 601–720 prototype validation + physical evidence / human launch governance. REAL_LOGIC / FIXTURE / MANUAL_EVIDENCE — not Production Ready."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import StockShortage, atomic_write_json, read_json
from fox3d.journal import emit
from fox3d.kd import DEFAULT_LOGISTICS_POLICY
from fox3d.mfg_release import FAMILY_STEPS, product_snapshot
from fox3d.parametric import CabinetSpec
from fox3d.storelock import CrashInjected

UNIT_STATES = (
    "PLANNED",
    "WAITING_HUMAN_START",
    "IN_BUILD",
    "WAITING_VALIDATION",
    "VALIDATED",
    "HOLD",
    "REWORK",
    "SCRAPPED",
)
READINESS_STATES = (
    "NOT_SELECTED",
    "READY_FOR_PROTOTYPE",
    "PROTOTYPE_IN_PROGRESS",
    "WAITING_PHYSICAL_EVIDENCE",
    "HOLD",
    "NEEDS_ECO",
    "PROTOTYPE_VALIDATED",
    "READY_FOR_MANUAL_PILOT_BATCH",
    "READY_FOR_HUMAN_GO_NO_GO",
)
DECISIONS = ("PASS_AS_BUILT", "REWORK_CURRENT_UNIT", "CREATE_ECO", "HOLD_SKU", "SCRAP_UNIT")
LAUNCH_DECISIONS = (
    "WAITING_HUMAN_EVIDENCE",
    "HOLD_REWORK",
    "READY_FOR_HUMAN_GO_NO_GO",
    "HUMAN_GO",
    "HUMAN_NO_GO",
)
PACKAGE_STATES = ("OPEN", "PREPARED", "FINALIZED", "SUPERSEDED", "INVALIDATED")
EVIDENCE_SOURCES = frozenset({"MANUAL", "IMPORTED", "FIXTURE", "MANUAL_EVIDENCE", "IMPORTED_EVIDENCE"})
PACKAGE_SOURCES = frozenset({"FIXTURE", "MANUAL_EVIDENCE", "IMPORTED_EVIDENCE"})
REQUIRED_MEASUREMENTS = ("widthMm", "depthMm", "heightMm", "assembledWeightKg", "assemblyMinutes")
PACK_MEASUREMENTS = ("cartonLengthMm", "cartonWidthMm", "cartonHeightMm", "packedWeightKg")
QC_FIELDS = ("hardware", "panelEdgeFinish", "wobbleStability", "doorDrawerFit")
QC_STATUSES = frozenset({"OK", "PASS", "FAIL", "MISSING", "DAMAGED", "INCORRECT", "NOT_APPLICABLE"})
QTY_COST_FIELDS = ("sheetsConsumed", "materialArea", "hardwareQty", "laborMinutes", "reworkMinutes", "packagingQty")
CURRENCY_FIELDS = (
    "materialAmount",
    "hardwareAmount",
    "laborAmount",
    "reworkAmount",
    "packagingAmount",
    "shippingAmount",
    "externalProcessingAmount",
)
REQUIRED_CURRENCY = ("materialAmount", "hardwareAmount", "laborAmount", "packagingAmount")
ALLOWED_CURRENCIES = frozenset({"TWD", "USD", "CNY", "EUR"})
ALLOWED_ECO_FIELDS = frozenset(
    {
        "width",
        "depth",
        "height",
        "boardThickness",
        "doorCount",
        "shelfCount",
        "drawerCount",
        "legs",
        "plinthHeight",
        "backPanel",
        "material",
    }
)
DEFAULT_TOLERANCE = {
    "dimMm": 3.0,
    "dimPct": 0.02,
    "weightKg": 0.5,
    "assemblyMinutes": 15.0,
    "label": "ENGINEERING_POLICY",
    "certification": False,
}
VOLUMETRIC_POLICY = {
    "divisor": float(DEFAULT_LOGISTICS_POLICY.get("volumetricDivisor") or 6000.0),
    "units": "cm3_per_kg",
    "source": "CONFIG",
    "maxLongestSideMm": float(DEFAULT_LOGISTICS_POLICY.get("maxLongestSideMm") or 1500.0),
    "maxPackedWeightKg": float(DEFAULT_LOGISTICS_POLICY.get("maxPackedWeightKg") or 30.0),
}
PACKAGING_POLICY = {
    "tolerance": dict(DEFAULT_TOLERANCE),
    "volumetric": dict(VOLUMETRIC_POLICY),
    "requiredVarianceFields": list(PACK_MEASUREMENTS) + ["assemblyMinutes"],
    "source": "CONFIG",
}
PACKAGING_POLICY_HASH = stable_hash(PACKAGING_POLICY)
PRIOR_REAL_BLENDER = {
    "commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14",
    "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c",
}
LINEAGE_KEYS = (
    "candidateId",
    "selectionId",
    "prototypeUnitId",
    "engineeringHash",
    "canonicalHash",
    "bomHash",
    "nestingHash",
    "rankingPolicyHash",
)
CANONICAL_SELECTED_FIELDS = LINEAGE_KEYS + ("truthLabel",)
CANONICAL_UNIT_FIELDS = LINEAGE_KEYS + (
    "state",
    "physicalPrototypeValidated",
    "evidenceSource",
    "evidencePackageId",
    "buildCompleted",
    "consumesInventory",
    "materialConsumed",
    "inventoryLineage",
    "truthLabel",
)
CANONICAL_PACKAGE_FIELDS = LINEAGE_KEYS + (
    "evidencePackageId",
    "evidenceSource",
    "engineeringRevision",
    "ecoRevision",
    "state",
    "revision",
    "operatorId",
    "shiftId",
)
REQUIRED_BOARD_FIELDS = (
    "selectionId",
    "prototypeUnitId",
    "engineeringHash",
    "canonicalHash",
    "bomHash",
    "nestingHash",
    "rankingScore",
    "rankingPolicyHash",
    "conservationOk",
    "expectedUtilization",
    "trueScrap",
    "reusableRemnant",
    "prototypeStatus",
    "toleranceResult",
    "dimensionalVariance",
    "assemblyObservedVsEstimated",
    "observedCostLabel",
    "observedMonetaryVariance",
    "costCompleteness",
    "packagingPredictedVsObserved",
    "packagingValidation",
    "qcStatus",
    "realBlenderLineage",
    "demandLabel",
    "blockers",
    "physicalPrototypeValidated",
    "liveMachineControl",
    "launchDecision",
    "evidencePackageId",
)
REQUIRED_MATRIX_KEYS = (
    "selectionId",
    "candidateId",
    "engineeringHash",
    "canonicalHash",
    "bomHash",
    "nestingHash",
    "rankingPolicyHash",
    "prototypeUnitId",
    "unitState",
    "evidenceSource",
    "buildCompleted",
    "toleranceStatus",
    "qcStatus",
    "costCompleteness",
    "monetaryVarianceStatus",
    "packagingCompleteness",
    "packagingVarianceStatus",
    "ecoStatus",
    "decisionState",
    "blockers",
    "physicalPrototypeValidated",
    "liveMachineControl",
    "launchDecision",
    "evidencePackageId",
)
BUILD_INCOMPLETE_STATES = frozenset({"PLANNED", "WAITING_HUMAN_START", "IN_BUILD"})


def _now() -> str:
    return utcnow().isoformat()


def _finite_number(value: Any, field: str, *, allow_zero: bool = False) -> float:
    if value is None or isinstance(value, bool) or isinstance(value, (list, dict)):
        raise PrototypeError("BLOCKED", f"invalid {field}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PrototypeError("BLOCKED", f"non-numeric {field}") from None
    if not math.isfinite(number):
        raise PrototypeError("BLOCKED", f"non-finite {field}")
    if number < 0 or (number == 0 and not allow_zero):
        raise PrototypeError("BLOCKED", f"invalid {field}")
    return number


def variance(target: float | None, actual: float | None) -> dict[str, Any]:
    if target is None or actual is None:
        return {"target": target, "actual": actual, "abs": None, "pct": None, "complete": False}
    diff = actual - target
    pct = (diff / target) if target else None
    return {"target": target, "actual": actual, "abs": diff, "pct": pct, "complete": True}


def evaluate_tolerance(field: str, target: float | None, actual: float | None, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    pol = policy or DEFAULT_TOLERANCE
    base = variance(target, actual)
    if not base["complete"]:
        return {**base, "field": field, "ok": False, "reason": "missing"}
    abs_err = abs(float(base["abs"]))
    pct = abs(float(base["pct"])) if base["pct"] is not None else None
    if field in {"widthMm", "depthMm", "heightMm", "cartonLengthMm", "cartonWidthMm", "cartonHeightMm"}:
        ok = abs_err <= float(pol["dimMm"]) or (pct is not None and pct <= float(pol["dimPct"]))
    elif field in {"assembledWeightKg", "packedWeightKg"}:
        ok = abs_err <= float(pol["weightKg"])
    elif field == "assemblyMinutes":
        ok = abs_err <= float(pol["assemblyMinutes"])
    else:
        ok = abs_err <= float(pol["dimMm"])
    return {**base, "field": field, "ok": ok, "reason": "ok" if ok else "out_of_tolerance"}


def volumetric_weight_kg(length_mm: float, width_mm: float, height_mm: float, *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    pol = policy or VOLUMETRIC_POLICY
    divisor = float(pol["divisor"])
    cm3 = (length_mm / 10.0) * (width_mm / 10.0) * (height_mm / 10.0)
    kg = cm3 / divisor
    return {
        "volumetricWeightKg": kg,
        "cm3": cm3,
        "divisor": divisor,
        "policyHash": stable_hash(pol),
        "source": "CONFIG",
    }


class PrototypeError(PermissionError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.status = "BLOCKED"


def verify_prior_real_blender(docs: Path | str) -> dict[str, Any]:
    from fox3d.portfolio import media_case_real

    path = Path(docs) / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json"
    failures: list[str] = []
    if not path.exists():
        return {"ok": False, "failures": ["prior_real_missing_file"], "cases": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "failures": [f"prior_real_unreadable:{exc}"], "cases": 0}
    if payload.get("evidenceCodeCommit") != PRIOR_REAL_BLENDER["commitSha"]:
        failures.append("prior_real_commit")
    if payload.get("acceptanceGenerationId") != PRIOR_REAL_BLENDER["generation"]:
        failures.append("prior_real_generation")
    if payload.get("ok") is not True:
        failures.append("prior_real_not_ok")
    cases = payload.get("realMediaCases") or []
    if len(cases) < 4:
        failures.append("prior_real_count")
    verified = []
    for i, row in enumerate(cases[:4]):
        if not media_case_real(row, expected_commit=PRIOR_REAL_BLENDER["commitSha"]):
            failures.append(f"prior_real_case_{i}")
            continue
        blender = str(row.get("blenderVersion") or "")
        gpu = str(row.get("gpu") or "")
        if "5.2.1" not in blender or "T1000" not in gpu or str(row.get("device") or "").upper() != "OPTIX":
            failures.append(f"prior_real_lineage_{i}")
            continue
        if row.get("usedMock") is not False or row.get("realOptix") is not True:
            failures.append(f"prior_real_mock_{i}")
            continue
        verified.append(
            {
                "candidateId": row.get("candidateId"),
                "engineeringHash": row.get("engineeringHash"),
                "jobId": row.get("jobId"),
                "artifactSha256": row.get("artifactSha256"),
                "artifactSize": row.get("artifactSize"),
                "blenderVersion": row.get("blenderVersion"),
                "gpu": row.get("gpu"),
                "device": row.get("device"),
                "evidenceCodeCommit": row.get("evidenceCodeCommit"),
            }
        )
    if len(verified) < 4:
        failures.append("prior_real_verified_lt_4")
    return {
        "ok": not failures,
        "failures": failures,
        "cases": len(verified),
        "commitSha": PRIOR_REAL_BLENDER["commitSha"],
        "generation": PRIOR_REAL_BLENDER["generation"],
        "media": verified,
    }


def _required_variance_ok(item: Any) -> bool:
    return isinstance(item, dict) and item.get("complete") is True and item.get("ok") is True


def _packaging_complete_failures(row: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    pack = row.get("packagingCompleteness")
    pack_val = row.get("packagingValidation") or {}
    if pack != "COMPLETE" or not isinstance(pack_val, dict) or pack_val.get("ok") is not True:
        return failures
    vars_ = row.get("packagingPredictedVsObserved")
    if not isinstance(vars_, dict):
        failures.append("packaging_variance_missing")
        return failures
    for field in PACK_MEASUREMENTS:
        if not _required_variance_ok(vars_.get(field)):
            failures.append(f"packaging_variance_{field}")
    assembly = row.get("assemblyObservedVsEstimated")
    if not _required_variance_ok(assembly):
        failures.append("assembly_variance")
    policy_hash = pack_val.get("packagingPolicyHash") or row.get("packagingPolicyHash")
    if policy_hash != PACKAGING_POLICY_HASH:
        failures.append("packaging_policy_hash")
    return failures


def _index_by_candidate(rows: list[Any], *, kind: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    failures: list[str] = []
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            failures.append(f"{kind}_malformed")
            continue
        cid = row.get("candidateId")
        if not cid:
            failures.append(f"{kind}_missing_candidate")
            continue
        if cid in indexed:
            failures.append(f"duplicate_{kind}_candidate")
            continue
        indexed[cid] = row
    return indexed, failures


def _lineage_present(value: Any) -> bool:
    return value is not None and value != ""


def project_published_prototype_truth(result: dict[str, Any]) -> dict[str, Any]:
    """Materialize the serialized canonical four-target proof from in-memory result."""
    selected = [row for row in (result.get("selected") or []) if isinstance(row, dict)]
    units = [row for row in (result.get("units") or []) if isinstance(row, dict)]
    matrix = [row for row in (result.get("matrix") or []) if isinstance(row, dict)]
    board = result.get("board") if isinstance(result.get("board"), dict) else {}
    rows = [row for row in (board.get("rows") or []) if isinstance(row, dict)]
    units_by_cid = {row.get("candidateId"): row for row in units if row.get("candidateId")}
    board_by_cid = {row.get("candidateId"): row for row in rows if row.get("candidateId")}
    projected_selected: list[dict[str, Any]] = []
    selected_board: list[dict[str, Any]] = []
    for sel in selected:
        unit = units_by_cid.get(sel.get("candidateId")) or {}
        projected_selected.append({key: sel[key] if key in sel else unit.get(key) for key in CANONICAL_SELECTED_FIELDS})
        cid = sel.get("candidateId")
        if cid in board_by_cid:
            selected_board.append(board_by_cid[cid])
    projected_units = [{key: unit.get(key) for key in CANONICAL_UNIT_FIELDS} for unit in units]
    published_selected_board = result.get("selectedBoard")
    if not isinstance(published_selected_board, list):
        published_selected_board = selected_board
    packages = [row for row in (result.get("evidencePackages") or []) if isinstance(row, dict)]
    projected_packages = [{key: pkg.get(key) for key in CANONICAL_PACKAGE_FIELDS} for pkg in packages]
    launch = result.get("launchDecision") or "WAITING_HUMAN_EVIDENCE"
    return {
        **result,
        "selected": projected_selected,
        "units": projected_units,
        "matrix": matrix,
        "board": board,
        "selectedBoard": published_selected_board,
        "evidencePackages": projected_packages,
        "launchDecision": launch,
        "physicalPrototypeValidated": bool(result.get("physicalPrototypeValidated")),
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "liveMachineControl": False,
    }


def validate_prototype_acceptance_result(result: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    selected = result.get("selected") or []
    units = result.get("units") or []
    matrix = result.get("matrix") or []
    board = result.get("board") or {}
    rows = board.get("rows") if isinstance(board, dict) else None
    selected_board = result.get("selectedBoard")
    if not isinstance(rows, list) or not rows:
        failures.append("empty_board")
        rows = []
    if not isinstance(selected_board, list):
        failures.append("selected_board_missing")
        selected_board = []
    if len(selected) != 4:
        failures.append("selected_4")
    if len(units) != 4:
        failures.append("units_4")
    if len(matrix) != 4:
        failures.append("matrix_4")
    if len(selected_board) != 4:
        failures.append("selected_board_4")
    selected_by, sel_fail = _index_by_candidate(selected, kind="selected")
    units_by, unit_fail = _index_by_candidate(units, kind="unit")
    matrix_by, matrix_fail = _index_by_candidate(matrix, kind="matrix")
    board_by, board_fail = _index_by_candidate(rows, kind="board")
    selected_board_by, selected_board_fail = _index_by_candidate(selected_board, kind="selected_board")
    failures.extend(sel_fail + unit_fail + matrix_fail + board_fail + selected_board_fail)
    for s in selected:
        if not isinstance(s, dict):
            continue
        cid = s.get("candidateId")
        unit = units_by.get(cid)
        mat = matrix_by.get(cid)
        brd = selected_board_by.get(cid)
        if unit is None:
            failures.append("selected_unit_missing")
        if mat is None:
            failures.append("selected_matrix_missing")
        if brd is None:
            failures.append("selected_board_missing")
        parties = (("selected", s), ("unit", unit), ("matrix", mat), ("selected_board", brd))
        for key in LINEAGE_KEYS:
            present: list[Any] = []
            for kind, row in parties:
                if row is None:
                    continue
                if not _lineage_present(row.get(key)):
                    failures.append(f"{kind}_{key}_missing")
                    continue
                present.append(row.get(key))
            if present and any(value != present[0] for value in present[1:]):
                failures.append(f"{key}_mismatch")
        if unit is None or mat is None:
            continue
        if unit.get("buildCompleted") is not True:
            failures.append("build_incomplete")
        if mat.get("buildCompleted") is not True or mat.get("buildCompleted") != (unit.get("buildCompleted") is True):
            failures.append("buildCompleted_mismatch")
        if brd:
            if brd.get("physicalPrototypeValidated") != mat.get("physicalPrototypeValidated"):
                failures.append("board_matrix_physical_mismatch")
            b_pack = (brd.get("packagingValidation") or {}).get("ok") if isinstance(brd.get("packagingValidation"), dict) else None
            m_pack = (mat.get("packagingValidation") or {}).get("ok") if isinstance(mat.get("packagingValidation"), dict) else None
            if b_pack != m_pack:
                failures.append("board_matrix_packaging_mismatch")
            b_tol = brd.get("toleranceResult") if isinstance(brd.get("toleranceResult"), dict) else {}
            if mat.get("toleranceStatus") is True and b_tol.get("ok") is False:
                failures.append("board_matrix_tolerance_mismatch")
            b_qc = brd.get("qcStatus") if isinstance(brd.get("qcStatus"), dict) else {}
            m_qc = mat.get("qcStatus") if isinstance(mat.get("qcStatus"), dict) else {}
            if b_qc.get("complete") != m_qc.get("complete"):
                failures.append("board_matrix_qc_mismatch")
    for i, row in enumerate(matrix):
        if not isinstance(row, dict):
            failures.append(f"matrix[{i}]:malformed")
            continue
        for key in REQUIRED_MATRIX_KEYS:
            if key not in row:
                failures.append(f"matrix[{i}]:missing:{key}")
            elif key in LINEAGE_KEYS and not _lineage_present(row.get(key)):
                failures.append(f"matrix[{i}]:empty:{key}")
        if row.get("buildCompleted") is not True:
            failures.append(f"matrix[{i}]:build_incomplete")
        if "toleranceStatus" not in row:
            failures.append("tolerance_contract_missing")
        elif row.get("toleranceStatus") is not True:
            failures.append("tolerance_contract_false")
        qc = row.get("qcStatus")
        if not isinstance(qc, dict) or qc.get("complete") is not True:
            failures.append("qc_incomplete")
        pack = row.get("packagingCompleteness")
        if pack == "MISSING":
            failures.append("packaging_missing")
        elif pack == "PARTIAL":
            failures.append("packaging_partial")
        elif pack != "COMPLETE":
            failures.append("packaging_contract_missing")
        pack_val = row.get("packagingValidation") or {}
        if isinstance(pack_val, dict) and pack_val.get("ok") is False:
            failures.append("packaging_validation_false")
        elif pack == "COMPLETE" and (not isinstance(pack_val, dict) or pack_val.get("ok") is not True):
            failures.append("packaging_validation_false")
        failures.extend(_packaging_complete_failures(row))
        if row.get("staleLineage"):
            failures.append("stale_lineage")
        if row.get("costCompleteness") == "COMPLETE" and row.get("observedCostLabel") in {None, "PARTIAL"}:
            failures.append("cost_complete_incorrect")
        if row.get("physicalPrototypeValidated") and row.get("evidenceSource") == "FIXTURE":
            failures.append("fixture_physical_unit")
        if row.get("decisionState") in {"READY_FOR_HUMAN_GO_NO_GO", "READY_FOR_MANUAL_PILOT_BATCH", "HUMAN_GO"} and row.get("evidenceSource") == "FIXTURE":
            failures.append("fixture_upgraded")
        if row.get("launchDecision") in {"READY_FOR_HUMAN_GO_NO_GO", "HUMAN_GO"} and row.get("evidenceSource") == "FIXTURE":
            failures.append("fixture_upgraded")
        if row.get("toleranceStatus") is not True:
            blockers = row.get("blockers") or []
            if isinstance(blockers, list) and "tolerance" not in blockers and "fixture_evidence" not in blockers:
                failures.append("tolerance_false_unblocked")
    proof_rows = {**board_by, **selected_board_by}
    for cid, row in proof_rows.items():
        if cid not in selected_by:
            continue
        for key in REQUIRED_BOARD_FIELDS:
            if key not in row:
                failures.append(f"board:{cid}:missing:{key}")
            elif key in LINEAGE_KEYS and not _lineage_present(row.get(key)):
                failures.append(f"board:{cid}:empty:{key}")
        failures.extend(_packaging_complete_failures({**row, "packagingCompleteness": "COMPLETE" if (row.get("packagingValidation") or {}).get("ok") is True else row.get("packagingCompleteness")}))
        pack_val = row.get("packagingValidation") or {}
        if isinstance(pack_val, dict) and pack_val.get("ok") is False:
            failures.append("packaging_validation_false")
    if result.get("physicalPrototypeValidated") is True:
        fixture_units = [u for u in units if (u.get("evidenceSource") == "FIXTURE" or u.get("truthLabel") == "FIXTURE")]
        if fixture_units or result.get("label") in {"FIXTURE", "FIXTURE/REAL_LOGIC"}:
            failures.append("fixture_physical")
    if result.get("demandLabel") == "REAL":
        failures.append("demand_mislabeled_real")
    if result.get("liveMachineControl") is not False:
        failures.append("liveMachineControl")
    for u in units:
        if u.get("consumesInventory") and u.get("materialConsumed") and not u.get("inventoryLineage"):
            failures.append("boolean_only_consume")
        if u.get("physicalPrototypeValidated") and (u.get("evidenceSource") == "FIXTURE" or u.get("truthLabel") == "FIXTURE"):
            failures.append("fixture_physical_unit")
        if u.get("buildCompleted") is not True:
            failures.append("build_incomplete")
    packages = result.get("evidencePackages") or []
    if not isinstance(packages, list) or len(packages) != 4:
        failures.append("packages_4")
    pkg_by, pkg_fail = _index_by_candidate(packages if isinstance(packages, list) else [], kind="package")
    failures.extend(pkg_fail)
    for s in selected:
        if not isinstance(s, dict):
            continue
        pkg = pkg_by.get(s.get("candidateId"))
        if pkg is None:
            failures.append("selected_package_missing")
            continue
        for key in CANONICAL_PACKAGE_FIELDS:
            if not _lineage_present(pkg.get(key)) and key in LINEAGE_KEYS + ("evidencePackageId", "evidenceSource", "state"):
                failures.append(f"package_{key}_missing")
        unit = units_by.get(s.get("candidateId"))
        if unit is not None:
            for key in LINEAGE_KEYS:
                if _lineage_present(pkg.get(key)) and _lineage_present(unit.get(key)) and pkg.get(key) != unit.get(key):
                    failures.append(f"package_{key}_mismatch")
            if unit.get("evidencePackageId") and pkg.get("evidencePackageId") != unit.get("evidencePackageId"):
                failures.append("package_id_mismatch")
        if pkg.get("evidenceSource") == "FIXTURE" and result.get("physicalPrototypeValidated") is True:
            failures.append("fixture_physical")
    launch = result.get("launchDecision")
    if launch not in LAUNCH_DECISIONS:
        failures.append("launch_decision_missing")
    if result.get("label") in {"FIXTURE", "FIXTURE/REAL_LOGIC"} and launch in {"HUMAN_GO", "READY_FOR_HUMAN_GO_NO_GO"}:
        failures.append("fixture_upgraded")
    if result.get("physicalPrototypeValidated") is False and result.get("label") in {"FIXTURE", "FIXTURE/REAL_LOGIC"}:
        if launch not in {"WAITING_HUMAN_EVIDENCE", "HOLD_REWORK"}:
            failures.append("fixture_launch_not_waiting")
    for flag in ("globalProductionReady", "fullAutonomousFactoryReady", "liveFactoryExecutionReady", "liveProviderReady", "liveMachineControl"):
        if result.get(flag) not in {None, False}:
            failures.append(flag)
    return failures


class PrototypeFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.root = Path(platform.root) / "prototype"
        self.root.mkdir(parents=True, exist_ok=True)
        self.selections: dict[str, dict[str, Any]] = {}
        self.units: dict[str, dict[str, Any]] = {}
        self.measurements: dict[str, dict[str, Any]] = {}
        self.ecos: dict[str, dict[str, Any]] = {}
        self.costs: dict[str, dict[str, Any]] = {}
        self.checklists: dict[str, dict[str, Any]] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.intents: dict[str, dict[str, Any]] = {}
        self.packages: dict[str, dict[str, Any]] = {}
        self.launch_decisions: dict[str, dict[str, Any]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.idem: dict[str, str] = {}
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self._crash_mode = ""
        self._hard_crash = False
        self.load()
        self._bind_journal()

    def _path(self) -> Path:
        return self.root / "prototype.json"

    def load(self) -> None:
        payload = read_json(self._path()) or {}
        self.selections = {r["selectionId"]: r for r in payload.get("selections") or [] if isinstance(r, dict) and r.get("selectionId")}
        self.units = {r["prototypeUnitId"]: r for r in payload.get("units") or [] if isinstance(r, dict) and r.get("prototypeUnitId")}
        self.measurements = {r["measurementId"]: r for r in payload.get("measurements") or [] if isinstance(r, dict) and r.get("measurementId")}
        self.ecos = {r["ecoId"]: r for r in payload.get("ecos") or [] if isinstance(r, dict) and r.get("ecoId")}
        self.costs = {r["costId"]: r for r in payload.get("costs") or [] if isinstance(r, dict) and r.get("costId")}
        self.checklists = {r["checklistId"]: r for r in payload.get("checklists") or [] if isinstance(r, dict) and r.get("checklistId")}
        self.decisions = {r["decisionId"]: r for r in payload.get("decisions") or [] if isinstance(r, dict) and r.get("decisionId")}
        raw_idem = payload.get("idem") or {}
        self.idem = dict(raw_idem) if isinstance(raw_idem, dict) else {}
        self.intents = {r["intentId"]: r for r in payload.get("inventoryIntents") or [] if isinstance(r, dict) and r.get("intentId")}
        self.packages = {r["evidencePackageId"]: r for r in payload.get("packages") or [] if isinstance(r, dict) and r.get("evidencePackageId")}
        self.launch_decisions = {r["launchDecisionId"]: r for r in payload.get("launchDecisions") or [] if isinstance(r, dict) and r.get("launchDecisionId")}
        self.plans = {r["planId"]: r for r in payload.get("pilotPlans") or [] if isinstance(r, dict) and r.get("planId")}
        self._bind_journal()

    def persist(self) -> None:
        atomic_write_json(
            self._path(),
            {
                "selections": list(self.selections.values()),
                "units": list(self.units.values()),
                "measurements": list(self.measurements.values()),
                "ecos": list(self.ecos.values()),
                "costs": list(self.costs.values()),
                "checklists": list(self.checklists.values()),
                "decisions": list(self.decisions.values()),
                "inventoryIntents": list(self.intents.values()),
                "packages": list(self.packages.values()),
                "launchDecisions": list(self.launch_decisions.values()),
                "pilotPlans": list(self.plans.values()),
                "idem": self.idem,
                "liveMachineControl": False,
                "truthLabel": "REAL_LOGIC",
            },
        )

    def _bind_journal(self) -> None:
        pilot = getattr(self.platform, "pilot", None)
        if pilot is None:
            return
        self.journal = getattr(pilot, "journal", None)
        self.outbox = getattr(pilot, "outbox", None)

    def _emit(self, event_type: str, *, tenant_id: str, aggregate_type: str, aggregate_id: str, actor: str, payload: dict[str, Any] | None = None, semantic_key: str | None = None) -> dict[str, Any] | None:
        self._bind_journal()
        return emit(
            self,
            event_type,
            tenant_id=tenant_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor=actor,
            payload=payload or {},
            semantic_key=semantic_key,
        )

    def _require_tenant(self, rec: dict[str, Any], tenant_id: str) -> None:
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: prototype")

    def _identity(self, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        return self.platform.pilot.identity.require_active(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)

    def _is_fixture(self, ident: dict[str, Any]) -> bool:
        op = ident.get("operator") or {}
        caps = {str(c).upper() for c in (op.get("capabilities") or [])}
        name = str(op.get("displayName") or "").lower()
        return "FIXTURE" in caps or name.startswith("fixture")

    def _source_for(self, ident: dict[str, Any], requested: str) -> str:
        source = str(requested or "").upper()
        if source == "MANUAL_EVIDENCE":
            source = "MANUAL"
        elif source == "IMPORTED_EVIDENCE":
            source = "IMPORTED"
        if source not in {"MANUAL", "IMPORTED", "FIXTURE"}:
            raise PrototypeError("BLOCKED", "evidence source must be MANUAL/IMPORTED/FIXTURE")
        if self._is_fixture(ident):
            if source in {"MANUAL", "IMPORTED"}:
                raise PrototypeError("BLOCKED", "fixture actor cannot produce MANUAL_EVIDENCE")
            return "FIXTURE"
        if source == "FIXTURE":
            return "FIXTURE"
        return source

    def _label_for(self, src: str) -> str:
        if src == "FIXTURE":
            return "FIXTURE"
        if src == "IMPORTED":
            return "IMPORTED_EVIDENCE"
        return "MANUAL_EVIDENCE"

    def _idem(self, key: str, factory) -> dict[str, Any]:
        if key in self.idem:
            existing = self.idem[key]
            for store in (
                self.selections,
                self.units,
                self.measurements,
                self.ecos,
                self.costs,
                self.checklists,
                self.decisions,
                self.packages,
                self.launch_decisions,
                self.plans,
            ):
                if existing in store:
                    return store[existing]
            raise PrototypeError("BLOCKED", "idempotent key missing record")
        rec = factory()
        rid = (
            rec.get("prototypeUnitId")
            or rec.get("measurementId")
            or rec.get("ecoId")
            or rec.get("costId")
            or rec.get("checklistId")
            or rec.get("decisionId")
            or rec.get("selectionId")
            or rec.get("evidencePackageId")
            or rec.get("launchDecisionId")
            or rec.get("planId")
        )
        self.idem[key] = str(rid)
        self.persist()
        return rec

    def _candidate(self, candidate_id: str, tenant_id: str) -> dict[str, Any]:
        rec = self.platform.portfolio.candidates[candidate_id]
        self.platform.portfolio._require_tenant(rec, tenant_id)
        return rec

    def _nest(self, cand: dict[str, Any]) -> dict[str, Any]:
        return (cand.get("sku") or {}).get("nesting") or cand.get("nesting") or {}

    def _bom_counts(self, cand: dict[str, Any]) -> dict[str, int]:
        dfm = cand.get("dfm") or {}
        bom = ((cand.get("sku") or {}).get("bom") or cand.get("bom") or {})
        lines = list(bom.get("lines") or [])
        hardware = sum(int(ln.get("quantity") or 1) for ln in lines if ln.get("hardware"))
        parts = sum(int(ln.get("quantity") or 1) for ln in lines if not ln.get("hardware"))
        return {
            "hardwareQty": int(dfm.get("hardwareCount") if dfm.get("hardwareCount") is not None else hardware),
            "partCount": int(dfm.get("partCount") if dfm.get("partCount") is not None else parts),
        }

    def _material_requirement(self, unit: dict[str, Any]) -> dict[str, Any]:
        cand = self._candidate(unit["candidateId"], unit["tenantId"])
        nest = self._nest(cand)
        spec = cand.get("spec") or {}
        sheet_mm = nest.get("sheetMm") or [2440, 1220]
        grain = nest.get("grainConstraint") or nest.get("grain")
        if not isinstance(grain, str) or grain in {"any", "none", ""}:
            grain = "length"
        sheets = int(nest.get("sheetCount") or 1)
        return {
            "material": str(nest.get("sheetSku") or spec.get("material") or "particle_board"),
            "thickness": float(nest.get("thickness") or spec.get("boardThickness") or spec.get("thickness") or 18),
            "grain": grain,
            "length": float(sheet_mm[0]) if sheet_mm else 2440.0,
            "width": float(sheet_mm[1]) if len(sheet_mm) > 1 else 1220.0,
            "sheets": max(sheets, 1),
        }

    def _resolve_dam(self, refs: list[dict[str, Any]] | None, *, tenant_id: str, src: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        dam = getattr(self.platform, "dam", None)
        for ref in refs or []:
            if not isinstance(ref, dict):
                raise PrototypeError("BLOCKED", "malformed DAM ref")
            if ref.get("tenantId") and ref.get("tenantId") != tenant_id:
                raise PrototypeError("BLOCKED", "cross-tenant DAM/evidence reference")
            asset_id = ref.get("assetId") or ref.get("id")
            if not asset_id:
                raise PrototypeError("BLOCKED", "malformed DAM ref")
            if dam is None:
                raise PrototypeError("BLOCKED", "DAM store unavailable")
            try:
                obj = dam.get_unchecked(str(asset_id))
            except KeyError as exc:
                raise PrototypeError("BLOCKED", "DAM object missing") from exc
            if obj.tenant_id != tenant_id:
                raise PrototypeError("BLOCKED", "cross-tenant DAM/evidence reference")
            size = Path(obj.path).stat().st_size if obj.path else 0
            if ref.get("sha256") and str(ref.get("sha256")) != str(obj.sha256):
                raise PrototypeError("BLOCKED", "DAM hash mismatch")
            if ref.get("size") is not None and int(ref["size"]) != int(size):
                raise PrototypeError("BLOCKED", "DAM size mismatch")
            if src == "IMPORTED" and (not obj.sha256 or size <= 0):
                raise PrototypeError("BLOCKED", "imported evidence requires SHA/size")
            out.append(
                {
                    "assetId": obj.asset_id,
                    "tenantId": obj.tenant_id,
                    "sha256": obj.sha256,
                    "size": size,
                    "kind": obj.kind,
                }
            )
        return out

    def _parse_qc(self, raw: dict[str, Any] | None, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        src = raw or {}
        missing: list[str] = []
        parsed: dict[str, Any] = {}
        doors = int(spec.get("doorCount") or 0)
        drawers = int(spec.get("drawerCount") or 0)
        for field in QC_FIELDS:
            item = src.get(field)
            if not isinstance(item, dict):
                if field == "doorDrawerFit" and doors == 0 and drawers == 0:
                    parsed[field] = {"status": "NOT_APPLICABLE", "reason": "no door/drawer"}
                    continue
                missing.append(field)
                continue
            status = str(item.get("status") or "").upper()
            if status not in QC_STATUSES:
                missing.append(field)
                continue
            if status == "NOT_APPLICABLE" and not item.get("reason"):
                missing.append(f"{field}:reason")
                continue
            parsed[field] = {"status": status, "reason": item.get("reason"), "note": item.get("note")}
        for count_field in ("reworkCount", "defectCount"):
            if count_field not in src:
                missing.append(count_field)
                continue
            parsed[count_field] = int(_finite_number(src[count_field], count_field, allow_zero=True))
        return parsed, missing

    def _engineering_revision(self, cand: dict[str, Any]) -> int:
        spec = cand.get("spec") or {}
        try:
            return int(spec.get("revision") or 1)
        except (TypeError, ValueError):
            return 1

    def _lineage_for_unit(self, unit: dict[str, Any]) -> dict[str, Any]:
        sel = self.selections.get(unit.get("selectionId") or "") or {}
        cand = self._candidate(unit["candidateId"], unit["tenantId"])
        eco = next((e for e in self.ecos.values() if e.get("candidateId") == unit["candidateId"] and e.get("tenantId") == unit["tenantId"]), None)
        return {
            "tenantId": unit["tenantId"],
            "candidateId": unit["candidateId"],
            "selectionId": unit.get("selectionId") or sel.get("selectionId"),
            "prototypeUnitId": unit["prototypeUnitId"],
            "engineeringHash": unit.get("engineeringHash"),
            "canonicalHash": unit.get("canonicalHash") or sel.get("canonicalHash"),
            "bomHash": unit.get("bomHash") or sel.get("bomHash"),
            "nestingHash": unit.get("nestingHash") or sel.get("nestingHash"),
            "rankingPolicyHash": unit.get("rankingPolicyHash") or sel.get("rankingPolicyHash"),
            "engineeringRevision": self._engineering_revision(cand),
            "ecoRevision": None if not eco else eco.get("ecoId"),
        }

    def _packages_for_unit(self, prototype_unit_id: str, *, tenant_id: str) -> list[dict[str, Any]]:
        return [
            p
            for p in self.packages.values()
            if p.get("prototypeUnitId") == prototype_unit_id and p.get("tenantId") == tenant_id
        ]

    def _active_package(self, unit: dict[str, Any]) -> dict[str, Any] | None:
        pid = unit.get("evidencePackageId")
        if pid and pid in self.packages:
            pkg = self.packages[pid]
            if pkg.get("tenantId") == unit.get("tenantId"):
                return pkg
        open_pkgs = [
            p
            for p in self._packages_for_unit(unit["prototypeUnitId"], tenant_id=unit["tenantId"])
            if p.get("state") in {"OPEN", "PREPARED"} and p.get("engineeringHash") == unit.get("engineeringHash")
        ]
        if open_pkgs:
            return sorted(open_pkgs, key=lambda r: str(r.get("createdAt") or ""))[-1]
        return None

    def _package_source_label(self, src: str) -> str:
        return self._label_for(src)

    def create_evidence_package(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        source: str,
        reason: str = "physical-evidence",
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        src = self._source_for(ident, source)
        label = self._package_source_label(src)
        if self._is_fixture(ident) and label == "MANUAL_EVIDENCE":
            raise PrototypeError("BLOCKED", "fixture actor cannot produce MANUAL_EVIDENCE")
        cand = self._candidate(unit["candidateId"], tenant_id)
        if cand.get("state") == "SUPERSEDED" or cand.get("engineeringHash") != unit.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "stale engineeringHash/revision evidence after ECO")
        lineage = self._lineage_for_unit(unit)
        for key in LINEAGE_KEYS:
            if not _lineage_present(lineage.get(key)):
                raise PrototypeError("BLOCKED", f"evidence package missing {key}")
        existing = self._active_package(unit)
        if existing:
            if existing.get("evidenceSource") != label:
                raise PrototypeError("HOLD", "evidence package source mismatch")
            for key in LINEAGE_KEYS:
                if existing.get(key) != lineage.get(key):
                    raise PrototypeError("HOLD", "evidence package lineage mismatch")
            return existing
        key = f"{tenant_id}::pkg::{prototype_unit_id}::{lineage['engineeringHash']}::{label}"

        def _make():
            body = {
                "evidencePackageId": new_id(),
                **lineage,
                "evidenceSource": label,
                "state": "OPEN",
                "revision": 1,
                "supersedesPackageId": None,
                "measurementId": None,
                "costId": None,
                "checklistId": None,
                "damRefs": [],
                "operatorId": ident["operator"]["operatorId"] if label != "FIXTURE" else ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "createdAt": _now(),
                "finalizedAt": None,
                "reason": reason,
                "truthLabel": label,
                "liveMachineControl": False,
                "physicalPrototypeValidated": False,
            }
            if label != "FIXTURE" and (not body.get("operatorId") or not body.get("shiftId")):
                raise PrototypeError("BLOCKED", "manual evidence requires operatorId+shiftId")
            self.packages[body["evidencePackageId"]] = body
            unit["evidencePackageId"] = body["evidencePackageId"]
            unit["evidenceSource"] = src
            self.persist()
            self._die("after-package-prepare")
            self._emit(
                "prototype.evidence_package.create",
                tenant_id=tenant_id,
                aggregate_type="PhysicalEvidencePackage",
                aggregate_id=body["evidencePackageId"],
                actor=ident["operator"]["operatorId"],
                payload={"state": "OPEN", "evidenceSource": label, "engineeringHash": body["engineeringHash"]},
                semantic_key=key,
            )
            return body

        return self._idem(key, _make)

    def _attach_to_package(self, unit: dict[str, Any], *, field: str, value: str, ident: dict[str, Any], src: str) -> dict[str, Any]:
        pkg = self._active_package(unit)
        if pkg is None:
            pkg = self.create_evidence_package(
                unit["prototypeUnitId"],
                tenant_id=unit["tenantId"],
                operator_id=ident["operator"]["operatorId"],
                shift_id=ident["shift"]["shiftId"],
                source=src,
            )
        if pkg.get("state") == "FINALIZED":
            pkg = self._supersede_package(pkg, ident=ident, src=src, reason="correction")
        if pkg.get("state") not in {"OPEN", "PREPARED"}:
            raise PrototypeError("BLOCKED", "finalized packages are append-only")
        if pkg.get("engineeringHash") != unit.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "stale engineeringHash/revision evidence after ECO")
        if pkg.get("tenantId") != unit.get("tenantId"):
            raise PrototypeError("BLOCKED", "cross-tenant prototype/evidence/DAM reference")
        pkg[field] = value
        unit["evidencePackageId"] = pkg["evidencePackageId"]
        self.packages[pkg["evidencePackageId"]] = pkg
        self.persist()
        return pkg

    def _supersede_package(self, old: dict[str, Any], *, ident: dict[str, Any], src: str, reason: str) -> dict[str, Any]:
        if old.get("state") not in {"FINALIZED", "OPEN", "PREPARED"}:
            raise PrototypeError("BLOCKED", "cannot correct invalidated package in place")
        unit = self.units[old["prototypeUnitId"]]
        self._require_tenant(unit, old["tenantId"])
        label = self._package_source_label(src)
        lineage = self._lineage_for_unit(unit)
        body = {
            **old,
            **lineage,
            "evidencePackageId": new_id(),
            "state": "OPEN",
            "revision": int(old.get("revision") or 1) + 1,
            "supersedesPackageId": old["evidencePackageId"],
            "measurementId": None,
            "costId": None,
            "checklistId": None,
            "damRefs": [],
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "createdAt": _now(),
            "finalizedAt": None,
            "reason": reason,
            "evidenceSource": label,
            "truthLabel": label,
            "physicalPrototypeValidated": False,
        }
        old["state"] = "SUPERSEDED"
        old["supersededBy"] = body["evidencePackageId"]
        old["supersededAt"] = _now()
        self.packages[old["evidencePackageId"]] = old
        self.packages[body["evidencePackageId"]] = body
        unit["evidencePackageId"] = body["evidencePackageId"]
        self.persist()
        self._emit(
            "prototype.evidence_package.supersede",
            tenant_id=old["tenantId"],
            aggregate_type="PhysicalEvidencePackage",
            aggregate_id=body["evidencePackageId"],
            actor=ident["operator"]["operatorId"],
            payload={"supersedesPackageId": old["evidencePackageId"], "revision": body["revision"]},
            semantic_key=f"{old['tenantId']}::pkg-super::{old['evidencePackageId']}::{body['revision']}",
        )
        return body

    def finalize_evidence_package(
        self,
        evidence_package_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        pkg = self.packages[evidence_package_id]
        self._require_tenant(pkg, tenant_id)
        if pkg.get("state") == "FINALIZED":
            return pkg
        if pkg.get("state") not in {"OPEN", "PREPARED"}:
            raise PrototypeError("BLOCKED", "package cannot finalize")
        unit = self.units[pkg["prototypeUnitId"]]
        cand = self._candidate(unit["candidateId"], tenant_id)
        if cand.get("engineeringHash") != pkg.get("engineeringHash") or cand.get("state") == "SUPERSEDED":
            raise PrototypeError("BLOCKED", "stale engineeringHash/revision evidence after ECO")
        pkg["state"] = "PREPARED"
        self.persist()
        self._die("after-package-prepare")
        pkg["state"] = "FINALIZED"
        pkg["finalizedAt"] = _now()
        pkg["finalizedBy"] = ident["operator"]["operatorId"]
        self.packages[evidence_package_id] = pkg
        self.persist()
        self._emit(
            "prototype.evidence_package.finalize",
            tenant_id=tenant_id,
            aggregate_type="PhysicalEvidencePackage",
            aggregate_id=evidence_package_id,
            actor=ident["operator"]["operatorId"],
            payload={"state": "FINALIZED", "engineeringHash": pkg.get("engineeringHash")},
            semantic_key=f"{tenant_id}::pkg-final::{evidence_package_id}",
        )
        return pkg

    def select(
        self,
        *,
        tenant_id: str,
        candidate_id: str,
        operator_id: str,
        shift_id: str,
        reason: str,
        ranking_id: str | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if not reason:
            raise PrototypeError("BLOCKED", "selection requires reason")
        rec = self._candidate(candidate_id, tenant_id)
        if rec.get("state") in {"REJECTED_DFM", "NEEDS_INPUT", "SUPERSEDED"}:
            raise PrototypeError("BLOCKED", "stale/superseded/rejected candidate cannot be selected")
        ranking = None
        if ranking_id:
            ranking = self.platform.portfolio.rankings[ranking_id]
            self.platform.portfolio._require_tenant(ranking, tenant_id)
        else:
            ranking = next(
                (r for r in self.platform.portfolio.rankings.values() if r.get("portfolioId") == rec.get("portfolioId") and r.get("tenantId") == tenant_id),
                None,
            )
        if not ranking:
            raise PrototypeError("BLOCKED", "ranking required for selection")
        top = next((row for row in (ranking.get("top10") or []) if row.get("candidateId") == candidate_id), None)
        if not top:
            raise PrototypeError("BLOCKED", "candidate not in Top 10")
        commercial = rec.get("commercial") or {}
        if commercial.get("stale") or commercial.get("engineeringHash") != rec.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "stale candidate lineage")
        fixture = self._is_fixture(ident)
        key = f"{tenant_id}::select::{candidate_id}::{rec.get('engineeringHash')}"

        def _make():
            body = {
                "selectionId": new_id(),
                "tenantId": tenant_id,
                "portfolioId": rec.get("portfolioId"),
                "candidateId": candidate_id,
                "canonicalHash": rec.get("canonicalHash"),
                "engineeringHash": rec.get("engineeringHash"),
                "bomHash": rec.get("bomHash"),
                "nestingHash": rec.get("nestingHash") or (rec.get("dfm") or {}).get("lineage", {}).get("nestingHash"),
                "costSnapshotHash": commercial.get("costSnapshotHash"),
                "rankingPolicyHash": ranking.get("rankingPolicyHash"),
                "score": top.get("score"),
                "selectedAt": _now(),
                "selectedBy": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "reason": reason,
                "fixtureActor": fixture,
                "truthLabel": "FIXTURE" if fixture else "MANUAL_EVIDENCE",
                "liveMachineControl": False,
            }
            if body["truthLabel"] == "MANUAL_EVIDENCE" and fixture:
                raise PrototypeError("BLOCKED", "fixture actor cannot produce MANUAL_EVIDENCE")
            self.selections[body["selectionId"]] = body
            self.persist()
            return body

        return self._idem(key, _make)

    def select_four(self, *, tenant_id: str, portfolio_id: str, operator_id: str, shift_id: str, reason: str) -> list[dict[str, Any]]:
        ranking = next(
            (r for r in self.platform.portfolio.rankings.values() if r.get("portfolioId") == portfolio_id and r.get("tenantId") == tenant_id),
            None,
        )
        if not ranking or len(ranking.get("top10") or []) < 4:
            raise PrototypeError("BLOCKED", "Top 10 required")
        return [
            self.select(
                tenant_id=tenant_id,
                candidate_id=row["candidateId"],
                operator_id=operator_id,
                shift_id=shift_id,
                reason=reason,
                ranking_id=ranking["rankingId"],
            )
            for row in ranking["top10"][:4]
        ]

    def create_unit(
        self,
        *,
        tenant_id: str,
        selection_id: str,
        operator_id: str,
        shift_id: str,
        seq: int = 1,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        sel = self.selections[selection_id]
        self._require_tenant(sel, tenant_id)
        cand = self._candidate(sel["candidateId"], tenant_id)
        if cand.get("state") == "SUPERSEDED" or cand.get("engineeringHash") != sel.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "superseded engineering version cannot create prototype unit")
        key = f"{tenant_id}::unit::{selection_id}::{seq}"

        def _make():
            pack = None
            try:
                if cand.get("state") == "APPROVED_FOR_PROTOTYPE":
                    pack = self.platform.portfolio.prototype_pack(cand["candidateId"], tenant_id=tenant_id)
            except Exception:
                pack = None
            steps = FAMILY_STEPS.get("KD_FURNITURE") or ["assembly", "packaging"]
            traveler = (pack or {}).get("traveler") or {
                "family": "KD_FURNITURE",
                "steps": [
                    {"seq": i + 1, "operation": op, "kind": "operator_instruction", "machineCommand": False, "liveCnc": False, "liveLaser": False}
                    for i, op in enumerate(steps)
                ],
                "label": "MANUAL_STATION",
            }
            body = {
                "prototypeUnitId": new_id(),
                "tenantId": tenant_id,
                "selectionId": selection_id,
                "candidateId": sel["candidateId"],
                "seq": int(seq),
                "state": "PLANNED",
                "engineeringHash": sel["engineeringHash"],
                "canonicalHash": sel["canonicalHash"],
                "bomHash": sel["bomHash"],
                "nestingHash": sel["nestingHash"],
                "costSnapshotHash": sel["costSnapshotHash"],
                "rankingPolicyHash": sel["rankingPolicyHash"],
                "traveler": traveler,
                "consumesInventory": False,
                "materialConsumed": False,
                "physicalPrototypeValidated": False,
                "evidencePackageId": None,
                "createdBy": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "createdAt": _now(),
                "liveCnc": False,
                "liveLaser": False,
                "liveMachineControl": False,
                "truthLabel": "FIXTURE" if self._is_fixture(ident) else "REAL_LOGIC",
            }
            self.units[body["prototypeUnitId"]] = body
            self.persist()
            return body

        return self._idem(key, _make)

    def start_unit(self, prototype_unit_id: str, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        rec = self.units[prototype_unit_id]
        self._require_tenant(rec, tenant_id)
        cand = self._candidate(rec["candidateId"], tenant_id)
        if cand.get("state") == "SUPERSEDED" or cand.get("engineeringHash") != rec.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "superseded engineering version cannot silently continue")
        if rec["state"] in {"IN_BUILD", "WAITING_VALIDATION", "VALIDATED"}:
            return rec
        if rec["state"] not in {"PLANNED", "WAITING_HUMAN_START", "REWORK"}:
            raise PrototypeError("BLOCKED", f"cannot start from {rec['state']}")
        rec["state"] = "IN_BUILD"
        rec["startedAt"] = _now()
        self.persist()
        return rec

    def complete_build(self, prototype_unit_id: str, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        rec = self.units[prototype_unit_id]
        self._require_tenant(rec, tenant_id)
        if rec["state"] == "WAITING_VALIDATION":
            return rec
        if rec["state"] != "IN_BUILD":
            raise PrototypeError("BLOCKED", "complete requires IN_BUILD")
        rec["state"] = "WAITING_VALIDATION"
        rec["buildCompletedAt"] = _now()
        rec["buildCompleted"] = True
        self.persist()
        return rec

    def _die(self, point: str) -> None:
        if getattr(self, "_crash_mode", "") != point:
            return
        if getattr(self, "_hard_crash", False):
            os._exit(1)
        raise CrashInjected(point)

    def _intent_key(self, rec: dict[str, Any], qty: int) -> str:
        return f"{rec['tenantId']}::proto-consume::{rec['prototypeUnitId']}::{int(qty)}"

    def _intent_identity(self, rec: dict[str, Any], qty: int, req: dict[str, Any] | None = None) -> dict[str, Any]:
        requirement = req or rec.get("materialRequirement") or self._material_requirement(rec)
        return {
            "tenantId": rec["tenantId"],
            "prototypeUnitId": rec["prototypeUnitId"],
            "workOrderId": rec.get("inventoryWorkOrderId") or f"proto:{rec['prototypeUnitId']}",
            "idempotencyKey": self._intent_key(rec, qty),
            "quantity": int(qty),
            "material": str(requirement["material"]),
            "thickness": float(requirement["thickness"]),
            "grain": str(requirement["grain"]),
            "length": float(requirement["length"]),
            "width": float(requirement["width"]),
        }

    def _intent_matches_identity(self, intent: dict[str, Any] | None, identity: dict[str, Any]) -> bool:
        if not isinstance(intent, dict):
            return False
        for key in ("intentId", "tenantId", "prototypeUnitId", "workOrderId", "idempotencyKey", "quantity", "requirement"):
            if key not in intent:
                return False
            value = intent.get(key)
            if value is None or value == "":
                return False
        req = intent.get("requirement")
        if not isinstance(req, dict):
            return False
        for key in ("material", "thickness", "grain", "length", "width"):
            if key not in req:
                return False
            value = req.get(key)
            if value is None or value == "":
                return False
        if intent.get("tenantId") != identity["tenantId"]:
            return False
        if intent.get("prototypeUnitId") != identity["prototypeUnitId"]:
            return False
        if intent.get("workOrderId") != identity["workOrderId"]:
            return False
        if intent.get("idempotencyKey") != identity["idempotencyKey"]:
            return False
        try:
            if int(intent.get("quantity")) != int(identity["quantity"]):
                return False
            if str(req.get("material")) != str(identity["material"]):
                return False
            if str(req.get("grain")) != str(identity["grain"]):
                return False
            if abs(float(req["thickness"]) - float(identity["thickness"])) > 1e-6:
                return False
            if abs(float(req["length"]) - float(identity["length"])) > 1e-6:
                return False
            if abs(float(req["width"]) - float(identity["width"])) > 1e-6:
                return False
        except (TypeError, ValueError):
            return False
        return True

    def _find_intent(self, rec: dict[str, Any], qty: int, req: dict[str, Any] | None = None) -> dict[str, Any] | None:
        identity = self._intent_identity(rec, qty, req)
        matches = [intent for intent in self.intents.values() if self._intent_matches_identity(intent, identity)]
        if len(matches) > 1:
            raise PrototypeError("HOLD", "ambiguous inventory intent identity")
        ptr = rec.get("inventoryIntentId")
        if ptr:
            pointed = self.intents.get(ptr)
            if pointed is None:
                raise PrototypeError("HOLD", "inventoryIntentId missing")
            if not self._intent_matches_identity(pointed, identity):
                raise PrototypeError("HOLD", "inventoryIntentId identity mismatch")
            if matches and matches[0].get("intentId") != pointed.get("intentId"):
                raise PrototypeError("HOLD", "ambiguous inventory intent identity")
            return pointed
        return matches[0] if matches else None

    def _reservations_for_work_order(self, *, tenant_id: str, work_order_id: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for lot in self.platform.lots.list(tenant_id=tenant_id):
            for item in (lot.get("reservations") or {}).values():
                if not isinstance(item, dict):
                    continue
                if item.get("workOrderId") != work_order_id:
                    continue
                if item.get("state") not in {"RESERVED", "CONSUMED"}:
                    continue
                found.append(
                    {
                        "lotId": lot.get("lotId") or item.get("lotId"),
                        "reservationId": item.get("reservationId"),
                        "quantity": int(item.get("quantity") or 0),
                        "state": item.get("state"),
                    }
                )
        return found

    def _reservations_compatible(self, items: list[dict[str, Any]], req: dict[str, Any], *, tenant_id: str) -> bool:
        lots = self.platform.lots
        for item in items:
            try:
                lot = lots.get(str(item.get("lotId")), tenant_id=tenant_id)
            except (KeyError, PermissionError):
                return False
            if not lots.lot_compatible(
                lot,
                material=req["material"],
                thickness=req["thickness"],
                grain=req["grain"],
                length=req["length"],
                width=req["width"],
            ):
                return False
        return True

    def _refresh_intent_reservations(self, intent: dict[str, Any], *, tenant_id: str) -> list[dict[str, Any]]:
        lots = self.platform.lots
        refreshed: list[dict[str, Any]] = []
        for item in intent.get("reservations") or []:
            try:
                live, lot = lots._find_reservation(item["reservationId"], tenant_id=tenant_id)
            except KeyError as exc:
                raise PrototypeError("HOLD", "inventory intent cannot reconcile reservation") from exc
            refreshed.append(
                {
                    "lotId": lot.get("lotId") or item.get("lotId"),
                    "reservationId": live["reservationId"],
                    "quantity": int(live["quantity"]),
                    "state": live.get("state"),
                }
            )
        intent["reservations"] = refreshed
        return refreshed

    def _apply_inventory_lineage(self, rec: dict[str, Any], intent: dict[str, Any], req: dict[str, Any], qty: int) -> dict[str, Any]:
        pinned = list(intent.get("reservations") or [])
        consumed_qty = sum(int(i.get("quantity") or 0) for i in pinned if i.get("state") == "CONSUMED")
        if consumed_qty != int(qty):
            raise PrototypeError("HOLD", "inventory lineage does not match required quantity")
        rec["materialConsumed"] = True
        rec["consumesInventory"] = True
        rec["consumedSheets"] = qty
        rec["inventoryWorkOrderId"] = intent["workOrderId"]
        rec["materialObservationLabel"] = "REAL_LOGIC"
        rec["materialRequirement"] = req
        rec["inventoryIntentId"] = intent["intentId"]
        rec["inventoryLineage"] = {
            "workOrderId": intent["workOrderId"],
            "intentId": intent["intentId"],
            "idempotencyKey": intent["idempotencyKey"],
            "lotIds": [item.get("lotId") for item in pinned],
            "reservationIds": [item.get("reservationId") for item in pinned],
            "quantities": [item.get("quantity") for item in pinned],
            "consumedQuantity": consumed_qty,
            "material": req["material"],
            "thickness": req["thickness"],
            "grain": req["grain"],
            "length": req["length"],
            "width": req["width"],
        }
        intent["status"] = "CONSUMED"
        self.intents[intent["intentId"]] = intent
        self.persist()
        return rec

    def consume_material_once(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        sheets: int | None = None,
        operator_id: str,
        shift_id: str,
        consumes_inventory: bool = False,
        lot_id: str | None = None,
        material: str | None = None,
        thickness: float | None = None,
        grain: str | None = None,
    ) -> dict[str, Any]:
        self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        rec = self.units[prototype_unit_id]
        self._require_tenant(rec, tenant_id)
        req = self._material_requirement(rec)
        if material and str(material) != str(req["material"]):
            raise PrototypeError("BLOCKED", "wrong SKU/thickness/grain cannot satisfy the prototype requirement")
        if thickness is not None and abs(float(thickness) - float(req["thickness"])) > 1e-6:
            raise PrototypeError("BLOCKED", "wrong SKU/thickness/grain cannot satisfy the prototype requirement")
        if grain and str(grain) != str(req["grain"]):
            raise PrototypeError("BLOCKED", "wrong SKU/thickness/grain cannot satisfy the prototype requirement")
        qty = int(_finite_number(sheets if sheets is not None else req["sheets"], "sheets"))
        if not consumes_inventory:
            if rec.get("consumesInventory"):
                raise PrototypeError("BLOCKED", "inventory consumption already bound")
            if rec.get("observedSheets") not in {None, qty} and rec.get("materialObservationLabel") == "FIXTURE":
                raise PrototypeError("BLOCKED", "no double consume after restart/retry")
            rec["consumesInventory"] = False
            rec["materialConsumed"] = False
            rec["observedSheets"] = qty
            rec["consumedSheets"] = qty
            rec["materialObservationLabel"] = "FIXTURE"
            rec["inventoryLineage"] = None
            self.persist()
            return rec
        lots = self.platform.lots
        wo_id = rec.get("inventoryWorkOrderId") or f"proto:{prototype_unit_id}"
        if rec.get("materialConsumed") and rec.get("inventoryLineage"):
            lineage = rec["inventoryLineage"]
            if int(lineage.get("consumedQuantity") or 0) != qty:
                raise PrototypeError("BLOCKED", "no double consume after restart/retry")
            return rec
        rec["inventoryWorkOrderId"] = wo_id
        intent = self._find_intent(rec, qty, req)
        reserved: list[dict[str, Any]] = []
        try:
            if intent is None:
                intent = {
                    "intentId": new_id(),
                    "tenantId": tenant_id,
                    "prototypeUnitId": prototype_unit_id,
                    "workOrderId": wo_id,
                    "idempotencyKey": self._intent_key(rec, qty),
                    "requirement": req,
                    "quantity": qty,
                    "reservations": [],
                    "status": "PREPARED",
                    "createdAt": _now(),
                }
                self.intents[intent["intentId"]] = intent
                rec["inventoryIntentId"] = intent["intentId"]
                self.persist()
            existing = self._reservations_for_work_order(tenant_id=tenant_id, work_order_id=wo_id)
            if existing:
                total = sum(int(i.get("quantity") or 0) for i in existing)
                if total != qty:
                    raise PrototypeError("HOLD", "ambiguous prior reservation set for prototype operation")
                if not self._reservations_compatible(existing, req, tenant_id=tenant_id):
                    raise PrototypeError("HOLD", "prior reservation incompatible with prototype requirement")
                intent["reservations"] = existing
                intent["status"] = "PINNED"
                rec["inventoryIntentId"] = intent["intentId"]
                self.persist()
            else:
                if lot_id:
                    lot = lots.get(lot_id, tenant_id=tenant_id)
                    if not lots.lot_compatible(
                        lot,
                        material=req["material"],
                        thickness=req["thickness"],
                        grain=req["grain"],
                        length=req["length"],
                        width=req["width"],
                    ):
                        raise PrototypeError("BLOCKED", "wrong SKU/thickness/grain cannot satisfy the prototype requirement")
                    item = lots.reserve_sheets(lot_id, tenant_id=tenant_id, work_order_id=wo_id, quantity=qty)
                    reserved = [{"lotId": lot_id, "reservationId": item["reservationId"], "quantity": qty, "state": "RESERVED"}]
                else:
                    reserved = lots.allocate_requirement(
                        tenant_id=tenant_id,
                        work_order_id=wo_id,
                        quantity=qty,
                        material=req["material"],
                        thickness=req["thickness"],
                        grain=req["grain"],
                        length=req["length"],
                        width=req["width"],
                    )
                self._die("after-reserve")
                intent["reservations"] = reserved
                intent["status"] = "PINNED"
                rec["inventoryIntentId"] = intent["intentId"]
                self.persist()
            pinned = self._refresh_intent_reservations(intent, tenant_id=tenant_id)
            consumed_now = 0
            for item in pinned:
                if item.get("state") == "CONSUMED":
                    continue
                if item.get("state") != "RESERVED":
                    raise PrototypeError("HOLD", "inventory intent reservation not consumable")
                lots.consume_reservation(item["reservationId"], tenant_id=tenant_id, work_order_id=intent["workOrderId"])
                consumed_now += 1
                self._refresh_intent_reservations(intent, tenant_id=tenant_id)
                intent["status"] = "CONSUMING"
                self.persist()
                if consumed_now == 1:
                    self._die("after-first-consume")
            self._refresh_intent_reservations(intent, tenant_id=tenant_id)
            return self._apply_inventory_lineage(rec, intent, req, qty)
        except StockShortage as exc:
            raise PrototypeError("SHORTAGE", str(exc.payload.get("message") or exc)) from exc
        except CrashInjected:
            raise
        except PrototypeError:
            if intent is None:
                for item in reserved:
                    try:
                        lots.release_reservation(item["reservationId"], tenant_id=tenant_id, work_order_id=wo_id)
                    except (KeyError, PermissionError):
                        continue
            raise
        except Exception:
            if intent is None:
                for item in reserved:
                    try:
                        lots.release_reservation(item["reservationId"], tenant_id=tenant_id, work_order_id=wo_id)
                    except (KeyError, PermissionError):
                        continue
            raise

    def record_as_built(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        source: str,
        values: dict[str, Any],
        dam_refs: list[dict[str, Any]] | None = None,
        notes: dict[str, Any] | None = None,
        observations: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        src = self._source_for(ident, source)
        if unit["state"] in BUILD_INCOMPLETE_STATES:
            raise PrototypeError("BLOCKED", "as-built requires completed build (WAITING_VALIDATION)")
        cand = self._candidate(unit["candidateId"], tenant_id)
        if values.get("engineeringHash") and values.get("engineeringHash") != unit.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "wrong engineeringHash")
        if values.get("prototypeUnitId") and values.get("prototypeUnitId") != prototype_unit_id:
            raise PrototypeError("BLOCKED", "wrong prototypeUnitId")
        numeric: dict[str, float] = {}
        for field in list(REQUIRED_MEASUREMENTS) + list(PACK_MEASUREMENTS):
            if field in values:
                numeric[field] = _finite_number(values[field], field, allow_zero=False)
        spec = cand.get("spec") or {}
        pack = ((cand.get("sku") or {}).get("packing") or {})
        weight = ((cand.get("sku") or {}).get("weight") or {})
        targets = {
            "widthMm": spec.get("width"),
            "depthMm": spec.get("depth"),
            "heightMm": spec.get("height"),
            "assembledWeightKg": weight.get("grossKg") or weight.get("netKg"),
            "assemblyMinutes": (cand.get("dfm") or {}).get("assemblyMinutes"),
            "cartonLengthMm": pack.get("length"),
            "cartonWidthMm": pack.get("width"),
            "cartonHeightMm": pack.get("height"),
            "packedWeightKg": weight.get("grossKg"),
        }
        tol_rows = {
            k: evaluate_tolerance(k, float(targets[k]) if targets.get(k) is not None else None, numeric.get(k))
            for k in targets
        }
        required_tol = [tol_rows[k] for k in REQUIRED_MEASUREMENTS]
        tol_ok = all(row.get("ok") for row in required_tol) and not [f for f in REQUIRED_MEASUREMENTS if f not in numeric]
        refs = self._resolve_dam(dam_refs, tenant_id=tenant_id, src=src)
        missing = [f for f in REQUIRED_MEASUREMENTS if f not in numeric]
        qc, qc_missing = self._parse_qc(observations if observations is not None else notes, spec)
        label = self._label_for(src)
        body = {
            "measurementId": new_id(),
            "tenantId": tenant_id,
            "prototypeUnitId": prototype_unit_id,
            "candidateId": unit["candidateId"],
            "engineeringHash": unit["engineeringHash"],
            "source": src,
            "truthLabel": label,
            "values": numeric,
            "targets": targets,
            "variance": {k: variance(float(targets[k]) if targets.get(k) is not None else None, numeric.get(k)) for k in targets},
            "tolerance": {
                "ok": tol_ok,
                "policy": dict(DEFAULT_TOLERANCE),
                "policyHash": stable_hash(DEFAULT_TOLERANCE),
                "fields": tol_rows,
                "failed": [k for k, row in tol_rows.items() if k in REQUIRED_MEASUREMENTS and not row.get("ok")],
            },
            "observations": qc,
            "qcMissing": qc_missing,
            "notes": notes or {},
            "damRefs": refs,
            "missingRequired": missing,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "recordedAt": _now(),
            "liveMachineControl": False,
            "safetyCertification": False,
        }
        self.measurements[body["measurementId"]] = body
        unit["latestMeasurementId"] = body["measurementId"]
        unit["evidenceSource"] = src
        unit["physicalPrototypeValidated"] = False
        pkg = self._attach_to_package(unit, field="measurementId", value=body["measurementId"], ident=ident, src=src)
        pkg["damRefs"] = refs
        pkg["observations"] = qc
        pkg["qcMissing"] = qc_missing
        self.packages[pkg["evidencePackageId"]] = pkg
        if missing or src == "FIXTURE" or qc_missing:
            if unit["state"] in {"VALIDATED", "HOLD"}:
                unit["state"] = "WAITING_VALIDATION"
        elif not tol_ok:
            unit["state"] = "HOLD"
        elif unit["state"] in {"HOLD", "WAITING_VALIDATION", "VALIDATED"}:
            unit["state"] = "WAITING_VALIDATION"
        self.persist()
        return body

    def record_actual_cost(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        source: str,
        components: dict[str, Any],
        currency: str | None = None,
        remnant_return_id: str | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        src = self._source_for(ident, source)
        cand = self._candidate(unit["candidateId"], tenant_id)
        if (components or {}).get("engineeringHash") and components.get("engineeringHash") != unit.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "stale engineeringHash cannot reuse the old observed cost")
        components = dict(components or {})
        lineage = unit.get("inventoryLineage") if isinstance(unit.get("inventoryLineage"), dict) else None
        if lineage and unit.get("materialConsumed"):
            consumed = lineage.get("consumedQuantity")
            if consumed is not None and "sheetsConsumed" not in components:
                components["sheetsConsumed"] = consumed
            area = None
            try:
                area = float(lineage.get("length") or 0) * float(lineage.get("width") or 0) * float(consumed or 0) / 1_000_000.0
            except (TypeError, ValueError):
                area = None
            if area is not None and "materialArea" not in components:
                components["materialArea"] = area
        pack = self.checklists.get(unit.get("packagingChecklistId") or "")
        if pack and "packagingQty" not in components:
            components["packagingQty"] = 1
        estimate = dict(cand.get("commercial") or {})
        snapshot = {
            k: estimate.get(k)
            for k in ("landedCost", "materialCost", "laborCost", "packagingCost", "costSnapshotHash", "engineeringHash", "truthLabel")
        }
        snapshot["truthLabel"] = snapshot.get("truthLabel") or "CONFIG_ESTIMATE"
        quantities: dict[str, Any] = {}
        monetary: dict[str, Any] = {}
        sources: dict[str, str] = {}
        missing: list[str] = []
        known = set(QTY_COST_FIELDS) | set(CURRENCY_FIELDS) | {"laborMinutes", "hardwareConsumed", "currency", "engineeringHash", "remnantCreditAmount", "remnantReturnId"}
        for key in list(QTY_COST_FIELDS) + list(CURRENCY_FIELDS):
            if key not in (components or {}):
                if key in REQUIRED_CURRENCY:
                    missing.append(key)
                    sources[key] = "MISSING"
                continue
            raw = components[key]
            if raw is None:
                missing.append(key)
                sources[key] = "MISSING"
                if key in CURRENCY_FIELDS:
                    monetary[key] = None
                else:
                    quantities[key] = None
                continue
            number = _finite_number(raw, key, allow_zero=True)
            sources[key] = src
            if key in CURRENCY_FIELDS:
                monetary[key] = number
            else:
                quantities[key] = number
        for key, raw in (components or {}).items():
            if key in known:
                continue
            if raw is None:
                missing.append(key)
                sources[key] = "MISSING"
                continue
            _finite_number(raw, key, allow_zero=True)
            sources[key] = src
            quantities[key] = float(raw) if not isinstance(raw, str) else raw
        if "laborMinutes" in (components or {}) and "laborMinutes" not in quantities:
            raw = components["laborMinutes"]
            if raw is None:
                missing.append("laborMinutes")
                sources["laborMinutes"] = "MISSING"
            else:
                quantities["laborMinutes"] = _finite_number(raw, "laborMinutes", allow_zero=True)
                sources["laborMinutes"] = src
        cur = str(currency or (components or {}).get("currency") or "TWD").upper()
        if cur not in ALLOWED_CURRENCIES:
            raise PrototypeError("BLOCKED", "wrong currency")
        remnant_credit = None
        if (components or {}).get("remnantCreditAmount") is not None:
            rid = remnant_return_id or (components or {}).get("remnantReturnId")
            if not rid:
                raise PrototypeError("BLOCKED", "remnant credit requires existing remnant-return record")
            try:
                rem = self.platform.remnants.get(str(rid), tenant_id=tenant_id)
            except (KeyError, PermissionError) as exc:
                raise PrototypeError("BLOCKED", "remnant credit requires existing remnant-return record") from exc
            remnant_credit = {
                "remnantReturnId": rem.get("remnantId") or rid,
                "amount": _finite_number(components["remnantCreditAmount"], "remnantCreditAmount", allow_zero=True),
            }
        complete = not any(k in missing for k in REQUIRED_CURRENCY) and all(
            monetary.get(k) is not None for k in REQUIRED_CURRENCY
        )
        monetary_total = None
        if complete:
            monetary_total = sum(float(monetary[k]) for k in CURRENCY_FIELDS if monetary.get(k) is not None)
            if remnant_credit:
                monetary_total -= float(remnant_credit["amount"])
        est_landed = snapshot.get("landedCost")
        monetary_variance = None
        if complete and est_landed is not None:
            monetary_variance = {
                "estimate": est_landed,
                "observed": monetary_total,
                "abs": float(monetary_total) - float(est_landed),
            }
        if src == "FIXTURE":
            label = "FIXTURE"
        elif src == "IMPORTED":
            label = "IMPORTED" if complete else "PARTIAL"
        else:
            label = "MANUAL" if complete else "PARTIAL"
        body = {
            "costId": new_id(),
            "tenantId": tenant_id,
            "prototypeUnitId": prototype_unit_id,
            "engineeringHash": unit["engineeringHash"],
            "estimateSnapshot": snapshot,
            "quantities": quantities,
            "monetary": monetary,
            "observed": {**quantities, **{k: v for k, v in monetary.items()}},
            "componentSources": sources,
            "missing": missing,
            "completeness": "COMPLETE" if complete else "PARTIAL",
            "monetaryTotal": monetary_total,
            "total": monetary_total,
            "currency": cur,
            "monetaryVariance": monetary_variance,
            "remnantCredit": remnant_credit,
            "source": src,
            "truthLabel": label,
            "liveProvider": False,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "recordedAt": _now(),
        }
        body["costSnapshotHash"] = stable_hash({k: body[k] for k in body if k not in {"costId", "costSnapshotHash", "recordedAt"}})
        self.costs[body["costId"]] = body
        unit["actualCostId"] = body["costId"]
        self._attach_to_package(unit, field="costId", value=body["costId"], ident=ident, src=src)
        self.persist()
        return body

    def packaging_checklist(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        source: str,
        observed: dict[str, Any],
        observations: dict[str, Any] | None = None,
        dam_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        src = self._source_for(ident, source)
        cand = self._candidate(unit["candidateId"], tenant_id)
        if observed.get("engineeringHash") and observed.get("engineeringHash") != unit.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "predicted vs observed engineering version mismatch")
        meas = self.measurements.get(unit.get("latestMeasurementId") or "")
        if meas and meas.get("engineeringHash") != unit.get("engineeringHash"):
            raise PrototypeError("BLOCKED", "predicted vs observed engineering version mismatch")
        numeric: dict[str, float] = {}
        for field in PACK_MEASUREMENTS:
            if field not in observed or observed.get(field) is None:
                raise PrototypeError("BLOCKED", f"missing {field}")
            numeric[field] = _finite_number(observed[field], field)
        pack = ((cand.get("sku") or {}).get("packing") or {})
        weight = ((cand.get("sku") or {}).get("weight") or {})
        predicted = {
            "cartonLengthMm": pack.get("length"),
            "cartonWidthMm": pack.get("width"),
            "cartonHeightMm": pack.get("height"),
            "packedWeightKg": weight.get("grossKg"),
        }
        vars_ = {
            k: evaluate_tolerance(k, float(predicted[k]) if predicted.get(k) is not None else None, numeric.get(k))
            for k in PACK_MEASUREMENTS
        }
        vol = volumetric_weight_kg(numeric["cartonLengthMm"], numeric["cartonWidthMm"], numeric["cartonHeightMm"])
        longest = max(numeric["cartonLengthMm"], numeric["cartonWidthMm"], numeric["cartonHeightMm"])
        oversize = longest > float(VOLUMETRIC_POLICY["maxLongestSideMm"])
        overweight = numeric["packedWeightKg"] > float(VOLUMETRIC_POLICY["maxPackedWeightKg"])
        counts = self._bom_counts(cand)
        obs = observations or {}
        hardware_qty = observed.get("hardwareQty", obs.get("hardwareQty"))
        part_count = observed.get("partCount", obs.get("partCount"))
        if hardware_qty is None or part_count is None:
            mismatch = True
            count_ok = False
        else:
            hardware_n = int(_finite_number(hardware_qty, "hardwareQty", allow_zero=True))
            part_n = int(_finite_number(part_count, "partCount", allow_zero=True))
            count_ok = hardware_n == counts["hardwareQty"] and part_n == counts["partCount"]
            mismatch = not count_ok
        claim = str(observed.get("certificationClaim") or observed.get("testStandard") or obs.get("certificationClaim") or obs.get("testStandard") or "")
        if observed.get("certification") is True or "ISTA" in claim.upper() or "CERTIFIED" in claim.upper():
            report = observed.get("certifiedReport") or obs.get("certifiedReport")
            if not isinstance(report, dict) or not report.get("assetId"):
                raise PrototypeError("BLOCKED", "ISTA/certified transit testing requires certified test report DAM")
            dam_refs = list(dam_refs or []) + [report]
        refs = self._resolve_dam(dam_refs, tenant_id=tenant_id, src=src)
        packing_fit = str(observed.get("packingFit") or obs.get("packingFit") or "").upper()
        missing_parts = str(observed.get("missingParts") or obs.get("missingParts") or "").upper()
        damage = str(observed.get("damageDefect") or obs.get("damageDefect") or "").upper()
        required_obs_missing = not packing_fit or not missing_parts or not damage
        damage_fail = damage in {"FAIL", "DAMAGED", "YES", "TRUE"}
        missing_fail = missing_parts in {"YES", "TRUE", "FAIL", "MISSING"}
        fit_fail = packing_fit in {"FAIL", "MISMATCH", "NO"}
        assembly_obs = observed.get("assemblyMinutes", obs.get("assemblyMinutes"))
        assembly_target = (cand.get("dfm") or {}).get("assemblyMinutes")
        assembly_var = evaluate_tolerance(
            "assemblyMinutes",
            float(assembly_target) if assembly_target is not None else None,
            float(assembly_obs) if assembly_obs is not None else None,
        )
        reasons = []
        if oversize:
            reasons.append("oversize")
        if overweight:
            reasons.append("overweight")
        if mismatch:
            reasons.append("hardware-count/part-count mismatch")
        if required_obs_missing:
            reasons.append("missing required observations")
        if damage_fail:
            reasons.append("packing damage/defect")
        if missing_fail:
            reasons.append("missing-part")
        if fit_fail:
            reasons.append("packing-fit")
        for field in PACK_MEASUREMENTS:
            if not vars_[field].get("ok"):
                reasons.append(f"{field} out of tolerance")
        if not assembly_var.get("ok"):
            reasons.append("assemblyMinutes out of tolerance")
        ok = not reasons
        if not ok:
            unit["state"] = "HOLD"
        body = {
            "checklistId": new_id(),
            "tenantId": tenant_id,
            "prototypeUnitId": prototype_unit_id,
            "engineeringHash": unit["engineeringHash"],
            "source": src,
            "truthLabel": self._label_for(src),
            "carrierTruth": "CONFIG_ESTIMATE",
            "barcodeHardware": "PARTIAL",
            "certification": False,
            "ok": ok,
            "reason": "ok" if ok else ",".join(reasons),
            "packagingPolicyHash": PACKAGING_POLICY_HASH,
            "packagingPolicy": dict(PACKAGING_POLICY),
            "observed": {**observed, **numeric},
            "predicted": predicted,
            "variance": vars_,
            "volumetricWeightKg": vol["volumetricWeightKg"],
            "volumetric": vol,
            "expectedCounts": counts,
            "countOk": count_ok,
            "assemblyObservedVsEstimated": assembly_var,
            "observations": {
                "packingFit": packing_fit or None,
                "missingParts": missing_parts or None,
                "damageDefect": damage or None,
            },
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "packerOperatorId": ident["operator"]["operatorId"],
            "damRefs": refs,
            "recordedAt": _now(),
        }
        self.checklists[body["checklistId"]] = body
        unit["packagingChecklistId"] = body["checklistId"]
        pkg = self._attach_to_package(unit, field="checklistId", value=body["checklistId"], ident=ident, src=src)
        if refs:
            pkg["damRefs"] = list(pkg.get("damRefs") or []) + refs
            self.packages[pkg["evidencePackageId"]] = pkg
        self.persist()
        return body

    def decide(
        self,
        prototype_unit_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        decision: str,
        reason: str,
        changes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if decision not in DECISIONS:
            raise PrototypeError("BLOCKED", "unknown decision")
        if not reason:
            raise PrototypeError("BLOCKED", "decision requires reason")
        unit = self.units[prototype_unit_id]
        self._require_tenant(unit, tenant_id)
        meas = self.measurements.get(unit.get("latestMeasurementId") or "")
        if decision == "PASS_AS_BUILT":
            if unit["state"] in BUILD_INCOMPLETE_STATES:
                raise PrototypeError("BLOCKED", "PLANNED/IN_BUILD unit cannot validate")
            if unit["state"] not in {"WAITING_VALIDATION", "HOLD"}:
                raise PrototypeError("BLOCKED", "as-built requires completed build (WAITING_VALIDATION)")
            if not meas or meas.get("missingRequired"):
                raise PrototypeError("BLOCKED", "missing required measurements cannot validate")
            if meas.get("engineeringHash") != unit.get("engineeringHash"):
                raise PrototypeError("BLOCKED", "old prototype evidence cannot validate a new engineeringHash")
            if meas.get("source") == "FIXTURE" or meas.get("truthLabel") == "FIXTURE":
                unit["physicalPrototypeValidated"] = False
                unit["state"] = "WAITING_VALIDATION"
            else:
                if meas.get("qcMissing"):
                    raise PrototypeError("BLOCKED", "missing required defect/QC observations cannot validate")
                if not (meas.get("tolerance") or {}).get("ok"):
                    unit["state"] = "HOLD"
                    unit["physicalPrototypeValidated"] = False
                    raise PrototypeError("BLOCKED", "out-of-tolerance cannot validate")
                unit["physicalPrototypeValidated"] = True
                unit["state"] = "VALIDATED"
        elif decision == "REWORK_CURRENT_UNIT":
            unit["state"] = "REWORK"
            unit["physicalPrototypeValidated"] = False
        elif decision == "HOLD_SKU":
            unit["state"] = "HOLD"
        elif decision == "SCRAP_UNIT":
            unit["state"] = "SCRAPPED"
            unit["physicalPrototypeValidated"] = False
        elif decision == "CREATE_ECO":
            eco = self.create_eco(unit["candidateId"], tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id, reason=reason, changes=changes)
            unit["ecoId"] = eco["ecoId"]
            unit["state"] = "HOLD"
        body = {
            "decisionId": new_id(),
            "tenantId": tenant_id,
            "prototypeUnitId": prototype_unit_id,
            "candidateId": unit["candidateId"],
            "engineeringHash": unit["engineeringHash"],
            "decision": decision,
            "reason": reason,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "fixtureActor": self._is_fixture(ident),
            "at": _now(),
            "liveMachineControl": False,
        }
        self.decisions[body["decisionId"]] = body
        self.persist()
        return body

    def create_eco(
        self,
        candidate_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        reason: str,
        accept: bool = True,
        changes: dict[str, Any] | None = None,
        classification: str = "ENGINEERING",
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if not reason:
            raise PrototypeError("BLOCKED", "ECO requires reason")
        old = self._candidate(candidate_id, tenant_id)
        old_hash = old.get("engineeringHash")
        eco_id = new_id()
        if not accept:
            body = {
                "ecoId": eco_id,
                "tenantId": tenant_id,
                "candidateId": candidate_id,
                "fromEngineeringHash": old_hash,
                "toEngineeringHash": None,
                "status": "REJECTED",
                "reason": reason,
                "classification": classification,
                "fieldChanges": [],
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "at": _now(),
                "truthLabel": "REAL_LOGIC",
            }
            self.ecos[eco_id] = body
            self.persist()
            return body
        kind = classification.upper()
        payload = dict(changes or {})
        unknown = [k for k in payload if k not in ALLOWED_ECO_FIELDS]
        if unknown:
            raise PrototypeError("BLOCKED", f"ECO field not allowed: {unknown[0]}")
        spec = CabinetSpec.model_validate(old["spec"])
        field_changes: list[dict[str, Any]] = []
        for field, raw in payload.items():
            before = getattr(spec, field)
            field_changes.append({"field": field, "from": before, "to": raw})
        if kind == "NON_ENGINEERING_REVISION":
            if field_changes:
                raise PrototypeError("BLOCKED", "non-engineering revision cannot change BOM/nesting/cost fields")
            body = {
                "ecoId": eco_id,
                "tenantId": tenant_id,
                "candidateId": candidate_id,
                "newCandidateId": candidate_id,
                "fromEngineeringHash": old_hash,
                "toEngineeringHash": old_hash,
                "fromBomHash": old.get("bomHash"),
                "toBomHash": old.get("bomHash"),
                "fromNestingHash": old.get("nestingHash"),
                "toNestingHash": old.get("nestingHash"),
                "fromCostSnapshotHash": (old.get("commercial") or {}).get("costSnapshotHash"),
                "toCostSnapshotHash": (old.get("commercial") or {}).get("costSnapshotHash"),
                "status": "ACCEPTED_NON_ENGINEERING",
                "classification": kind,
                "fieldChanges": [],
                "reason": reason,
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "at": _now(),
                "truthLabel": "REAL_LOGIC",
            }
            self.ecos[eco_id] = body
            self.persist()
            return body
        if not field_changes:
            raise PrototypeError("BLOCKED", "no-op engineering ECO rejects")
        params = {
            "width": spec.width,
            "depth": spec.depth,
            "height": spec.height,
            "boardThickness": spec.boardThickness,
            "doorCount": spec.doorCount,
            "shelfCount": spec.shelfCount,
            "drawerCount": spec.drawerCount,
            "legs": spec.legs,
            "plinthHeight": spec.plinthHeight,
            "backPanel": spec.backPanel,
            "material": spec.material,
        }
        params.update(payload)
        sku = self.platform.kd.build_sku(tenant_id=tenant_id, kind=old["kind"], render=False, **params)
        report = sku.get("report") or {}
        if report.get("ok") is False:
            raise PrototypeError("BLOCKED", "invalid rule/geometry ECO rejects before replacing current candidate")
        new_spec = CabinetSpec.model_validate(sku["spec"])
        geometry_changed = any(
            getattr(new_spec, item["field"]) != item["from"]
            for item in field_changes
            if hasattr(new_spec, item["field"])
        )
        if not geometry_changed:
            raise PrototypeError("BLOCKED", "no-op engineering ECO rejects")
        new_spec.revision = int(spec.revision or 1) + 1
        new_spec.metadata = {**(new_spec.metadata or {}), "ecoParentEngineeringHash": old_hash, "ecoId": eco_id}
        sku["spec"] = new_spec.model_dump(mode="json")
        sku["engineeringHash"] = new_spec.engineering_hash()
        intent = self.platform.portfolio.get_intent(old["portfolioId"], tenant_id=tenant_id)
        nest = sku.get("nesting") or {}
        new_cand = {
            "candidateId": new_id(),
            "tenantId": tenant_id,
            "portfolioId": old["portfolioId"],
            "productId": sku["spec"].get("productId"),
            "kind": old["kind"],
            "family": "KD_FURNITURE",
            "spec": sku["spec"],
            "report": sku.get("report") or {},
            "engineeringHash": sku["engineeringHash"],
            "canonicalHash": stable_hash({"eco": eco_id, "parent": old.get("canonicalHash"), "revision": new_spec.revision}),
            "bomHash": (sku.get("bom") or {}).get("bomHash"),
            "nestingHash": nest.get("nestingHash"),
            "state": "CANDIDATE",
            "rejectionCodes": [],
            "dfm": self.platform.portfolio._scorecard(sku),
            "commercial": self.platform.portfolio._commercial(sku, intent),
            "demand": dict(old.get("demand") or intent.get("demand") or {}),
            "sku": {k: sku.get(k) for k in ("packing", "weight", "difficulty", "shipping", "gate", "commonParts", "bom", "nesting", "landed") if k in sku},
            "ecoOf": old["candidateId"],
            "createdAt": _now(),
            "liveCnc": False,
        }
        if new_cand["engineeringHash"] == old_hash:
            raise PrototypeError("BLOCKED", "no-op engineering ECO rejects")
        self.platform.portfolio.candidates[new_cand["candidateId"]] = new_cand
        old["state"] = "SUPERSEDED"
        old["supersededBy"] = new_cand["candidateId"]
        old["supersededAt"] = _now()
        last_err: Exception | None = None
        for attempt in range(6):
            try:
                self.platform.portfolio.persist()
                last_err = None
                break
            except PermissionError as exc:
                last_err = exc
                time.sleep(0.05 * (attempt + 1))
        if last_err is not None:
            raise last_err
        applied = []
        for item in field_changes:
            applied.append({**item, "to": sku["spec"].get(item["field"], item["to"])})
        body = {
            "ecoId": eco_id,
            "tenantId": tenant_id,
            "candidateId": candidate_id,
            "newCandidateId": new_cand["candidateId"],
            "fromEngineeringHash": old_hash,
            "toEngineeringHash": new_cand["engineeringHash"],
            "fromBomHash": old.get("bomHash"),
            "toBomHash": new_cand.get("bomHash"),
            "fromNestingHash": old.get("nestingHash"),
            "toNestingHash": new_cand.get("nestingHash"),
            "fromCostSnapshotHash": (old.get("commercial") or {}).get("costSnapshotHash"),
            "toCostSnapshotHash": (new_cand.get("commercial") or {}).get("costSnapshotHash"),
            "status": "ACCEPTED",
            "classification": kind,
            "fieldChanges": applied,
            "reason": reason,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "at": _now(),
            "truthLabel": "REAL_LOGIC",
        }
        self.ecos[eco_id] = body
        for pkg in list(self.packages.values()):
            if pkg.get("tenantId") == tenant_id and pkg.get("candidateId") == candidate_id and pkg.get("engineeringHash") == old_hash:
                pkg["state"] = "INVALIDATED"
                pkg["invalidatedByEco"] = eco_id
                pkg["invalidatedAt"] = _now()
        for unit in self.units.values():
            if unit.get("tenantId") == tenant_id and unit.get("candidateId") == candidate_id:
                unit["physicalPrototypeValidated"] = False
                if unit.get("state") == "VALIDATED":
                    unit["state"] = "HOLD"
        self.persist()
        self._emit(
            "prototype.eco.accept",
            tenant_id=tenant_id,
            aggregate_type="EngineeringChange",
            aggregate_id=eco_id,
            actor=ident["operator"]["operatorId"],
            payload={"fromEngineeringHash": old_hash, "toEngineeringHash": new_cand["engineeringHash"]},
            semantic_key=f"{tenant_id}::eco::{eco_id}",
        )
        return body

    def _lineage_stale(self, candidate_id: str, tenant_id: str) -> bool:
        cand = self._candidate(candidate_id, tenant_id)
        sel = next((s for s in self.selections.values() if s.get("candidateId") == candidate_id and s.get("tenantId") == tenant_id), None)
        unit = next((u for u in self.units.values() if u.get("candidateId") == candidate_id and u.get("tenantId") == tenant_id), None)
        if sel and (sel.get("engineeringHash") != cand.get("engineeringHash") or cand.get("state") == "SUPERSEDED"):
            return True
        if unit and unit.get("engineeringHash") != cand.get("engineeringHash"):
            return True
        cost = self.costs.get((unit or {}).get("actualCostId") or "")
        pack = self.checklists.get((unit or {}).get("packagingChecklistId") or "")
        meas = self.measurements.get((unit or {}).get("latestMeasurementId") or "")
        if cost and cost.get("engineeringHash") != cand.get("engineeringHash"):
            return True
        if pack and pack.get("engineeringHash") != cand.get("engineeringHash"):
            return True
        if meas and meas.get("engineeringHash") != cand.get("engineeringHash"):
            return True
        return False

    def _human_go_record(self, candidate_id: str, tenant_id: str) -> dict[str, Any] | None:
        rows = [
            d
            for d in self.launch_decisions.values()
            if d.get("candidateId") == candidate_id and d.get("tenantId") == tenant_id and d.get("decision") in {"HUMAN_GO", "HUMAN_NO_GO"}
        ]
        if not rows:
            return None
        return sorted(rows, key=lambda r: str(r.get("at") or ""))[-1]

    def record_launch_decision(
        self,
        candidate_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        decision: str,
        reason: str,
        demand_upgrade: bool = False,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if decision not in {"HUMAN_GO", "HUMAN_NO_GO"}:
            raise PrototypeError("BLOCKED", "launch decision must be HUMAN_GO or HUMAN_NO_GO")
        if not reason:
            raise PrototypeError("BLOCKED", "launch decision requires reason")
        if demand_upgrade:
            raise PrototypeError("BLOCKED", "MOCK demand cannot upgrade GO")
        if self._is_fixture(ident):
            raise PrototypeError("BLOCKED", "fixture evidence attempts HUMAN_GO")
        board = self.readiness(candidate_id, tenant_id=tenant_id)
        if board.get("demandLabel") == "REAL":
            raise PrototypeError("BLOCKED", "MOCK demand cannot be labeled REAL")
        unit = next((u for u in self.units.values() if u.get("candidateId") == candidate_id and u.get("tenantId") == tenant_id), None)
        if unit is None:
            raise PrototypeError("BLOCKED", "HUMAN_GO without exact selected/unit/evidence/revision lineage")
        self._require_tenant(unit, tenant_id)
        pkg = self.packages.get(unit.get("evidencePackageId") or "")
        sel = self.selections.get(unit.get("selectionId") or "")
        meas = self.measurements.get(unit.get("latestMeasurementId") or "")
        if decision == "HUMAN_GO":
            if not unit.get("physicalPrototypeValidated"):
                raise PrototypeError("BLOCKED", "incomplete validation blocks HUMAN_GO")
            if (meas or {}).get("source") == "FIXTURE" or (meas or {}).get("truthLabel") == "FIXTURE" or (pkg or {}).get("evidenceSource") == "FIXTURE":
                raise PrototypeError("BLOCKED", "fixture evidence attempts HUMAN_GO")
            if (meas or {}).get("truthLabel") not in {"MANUAL_EVIDENCE", "IMPORTED_EVIDENCE"}:
                raise PrototypeError("BLOCKED", "physical prototype validation is MANUAL_EVIDENCE / IMPORTED_EVIDENCE, not FIXTURE")
            if not pkg or pkg.get("state") == "INVALIDATED":
                raise PrototypeError("BLOCKED", "HUMAN_GO without exact selected/unit/evidence/revision lineage")
            for key in LINEAGE_KEYS:
                if not _lineage_present(pkg.get(key)) or pkg.get(key) != unit.get(key):
                    raise PrototypeError("BLOCKED", "HUMAN_GO without exact selected/unit/evidence/revision lineage")
            if not sel or sel.get("selectionId") != unit.get("selectionId"):
                raise PrototypeError("BLOCKED", "HUMAN_GO without exact selected/unit/evidence/revision lineage")
            if self._lineage_stale(candidate_id, tenant_id):
                raise PrototypeError("BLOCKED", "old evidence reused after ECO")
            if board.get("state") not in {"READY_FOR_HUMAN_GO_NO_GO", "PROTOTYPE_VALIDATED", "READY_FOR_MANUAL_PILOT_BATCH"} and board.get("launchDecision") not in {"READY_FOR_HUMAN_GO_NO_GO", "HUMAN_GO"}:
                if not (
                    unit.get("physicalPrototypeValidated")
                    and (meas or {}).get("tolerance", {}).get("ok")
                    and not (meas or {}).get("qcMissing")
                ):
                    raise PrototypeError("BLOCKED", "missing/partial required evidence cannot become launch-ready")
            pack = self.checklists.get(unit.get("packagingChecklistId") or "")
            cost = self.costs.get(unit.get("actualCostId") or "")
            if not pack or pack.get("ok") is not True:
                raise PrototypeError("BLOCKED", "packaging missing/malformed/variance failure cannot become launch-ready")
            if not cost or cost.get("completeness") != "COMPLETE":
                raise PrototypeError("BLOCKED", "partial required actual-cost evidence cannot become launch-ready")
            if pkg.get("state") in {"OPEN", "PREPARED"}:
                self.finalize_evidence_package(
                    pkg["evidencePackageId"],
                    tenant_id=tenant_id,
                    operator_id=operator_id,
                    shift_id=shift_id,
                )
                pkg = self.packages[pkg["evidencePackageId"]]
        existing = self._human_go_record(candidate_id, tenant_id)
        if existing and existing.get("decision") == decision:
            return existing
        if existing and existing.get("decision") != decision:
            raise PrototypeError("HOLD", "duplicate launch decision conflict")
        key = f"{tenant_id}::launch::{candidate_id}::{decision}::{unit.get('engineeringHash')}"

        def _make():
            body = {
                "launchDecisionId": new_id(),
                "tenantId": tenant_id,
                "candidateId": candidate_id,
                "selectionId": unit.get("selectionId"),
                "prototypeUnitId": unit.get("prototypeUnitId"),
                "evidencePackageId": (pkg or {}).get("evidencePackageId"),
                "engineeringHash": unit.get("engineeringHash"),
                "canonicalHash": unit.get("canonicalHash"),
                "bomHash": unit.get("bomHash"),
                "nestingHash": unit.get("nestingHash"),
                "rankingPolicyHash": unit.get("rankingPolicyHash"),
                "decision": decision,
                "reason": reason,
                "demandLabel": board.get("demandLabel") or "MOCK",
                "demandDidNotUpgrade": True,
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "at": _now(),
                "productionReady": False,
                "liveMachineControl": False,
                "globalProductionReady": False,
            }
            self.launch_decisions[body["launchDecisionId"]] = body
            self.persist()
            self._emit(
                "prototype.launch_decision",
                tenant_id=tenant_id,
                aggregate_type="LaunchDecision",
                aggregate_id=body["launchDecisionId"],
                actor=ident["operator"]["operatorId"],
                payload={"decision": decision, "candidateId": candidate_id},
                semantic_key=key,
            )
            return body

        return self._idem(key, _make)

    def create_pilot_plan(
        self,
        candidate_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        reason: str,
        quantity: int = 1,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if self._is_fixture(ident):
            raise PrototypeError("BLOCKED", "fixture actor cannot approve pilot batch")
        go = self._human_go_record(candidate_id, tenant_id)
        if not go or go.get("decision") != "HUMAN_GO":
            raise PrototypeError("BLOCKED", "pilot batch requires authorized HUMAN_GO")
        unit = next((u for u in self.units.values() if u.get("candidateId") == candidate_id and u.get("tenantId") == tenant_id), None)
        if unit is None:
            raise PrototypeError("BLOCKED", "HUMAN_GO without exact selected/unit/evidence/revision lineage")
        self._require_tenant(unit, tenant_id)
        if go.get("engineeringHash") != unit.get("engineeringHash") or go.get("evidencePackageId") != unit.get("evidencePackageId"):
            raise PrototypeError("BLOCKED", "HUMAN_GO without exact selected/unit/evidence/revision lineage")
        if self._lineage_stale(candidate_id, tenant_id):
            raise PrototypeError("BLOCKED", "stale ECO/ranking/cost lineage blocks")
        qty = int(_finite_number(quantity, "quantity", allow_zero=False))
        key = f"{tenant_id}::pilot-plan::{candidate_id}::{unit.get('engineeringHash')}::{qty}"
        if key in self.idem:
            return self._idem(key, lambda: {})
        cand = self._candidate(candidate_id, tenant_id)
        sku = cand.get("sku") or {}
        snap = product_snapshot(
            {
                "productId": cand.get("productId") or (cand.get("spec") or {}).get("productId") or f"proto:{candidate_id}",
                "productVersion": (cand.get("spec") or {}).get("revision") or 1,
                "productFamily": cand.get("family") or "KD_FURNITURE",
                "kind": cand.get("kind"),
                "tenantId": tenant_id,
                "engineeringHash": cand.get("engineeringHash") or unit.get("engineeringHash"),
                "bom": sku.get("bom") or {},
                "bomHash": cand.get("bomHash") or (sku.get("bom") or {}).get("bomHash") or unit.get("bomHash") or stable_hash(sku.get("bom") or {"candidateId": candidate_id}),
                "nesting": sku.get("nesting") or cand.get("nesting") or {},
                "nestingHash": cand.get("nestingHash") or unit.get("nestingHash"),
                "packing": sku.get("packing") or {},
                "spec": cand.get("spec") or {},
                "quote": cand.get("commercial") or {},
            }
        )
        releases = self.platform.pilot.releases
        rel = releases.create(snap, tenant_id=tenant_id, created_by=ident["operator"]["operatorId"], idempotency_key=f"proto-pilot:{candidate_id}:{unit.get('engineeringHash')}")
        if rel.get("status") == "DRAFT":
            releases.validate(rel["releaseId"])
            releases.submit_approval(rel["releaseId"], actor=ident["operator"]["operatorId"])
            releases.approve(rel["releaseId"], actor=ident["operator"]["operatorId"])
            releases.release_for_manual_execution(rel["releaseId"], actor=ident["operator"]["operatorId"])
            rel = releases.get(rel["releaseId"])
        wo = self.platform.pilot.workorders.create(
            tenant_id=tenant_id,
            release=rel,
            quantity=qty,
            actor=ident["operator"]["operatorId"],
            idempotency_key=f"proto-pilot-wo:{candidate_id}:{rel.get('releaseHash')}:{qty}",
        )
        req = self._material_requirement(unit)
        body = {
            "planId": new_id(),
            "tenantId": tenant_id,
            "candidateId": candidate_id,
            "prototypeUnitId": unit["prototypeUnitId"],
            "selectionId": unit.get("selectionId"),
            "evidencePackageId": unit.get("evidencePackageId"),
            "engineeringHash": unit.get("engineeringHash"),
            "canonicalHash": unit.get("canonicalHash"),
            "bomHash": unit.get("bomHash"),
            "nestingHash": unit.get("nestingHash"),
            "rankingPolicyHash": unit.get("rankingPolicyHash"),
            "releaseId": rel.get("releaseId"),
            "releaseHash": rel.get("releaseHash"),
            "workOrderId": wo.get("workOrderId"),
            "quantity": qty,
            "materialPlan": req,
            "operatorStationPlan": {
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "stationLabel": "MANUAL_STATION",
                "liveMachineControl": False,
            },
            "qcCheckpoints": list(wo.get("qcPlan") or []),
            "packingHandoffPlan": {"packingRequired": bool(wo.get("packingRequired")), "carrierBooking": False, "payment": False},
            "expectedVsActual": {"expectedQuantity": qty, "actualQuantity": None, "hooks": ["workorder.complete", "qc.required_final_ok"]},
            "reason": reason,
            "liveCnc": False,
            "liveLaser": False,
            "liveMachineControl": False,
            "productionReady": False,
            "createdAt": _now(),
        }
        self.plans[body["planId"]] = body
        self.idem[key] = body["planId"]
        self.persist()
        self._emit(
            "prototype.pilot_plan.create",
            tenant_id=tenant_id,
            aggregate_type="PilotBatchPlan",
            aggregate_id=body["planId"],
            actor=ident["operator"]["operatorId"],
            payload={"releaseId": body["releaseId"], "workOrderId": body["workOrderId"], "quantity": qty},
            semantic_key=key,
        )
        return body

    def approve_pilot_batch(
        self,
        candidate_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        reason: str,
        cost_exception_reason: str | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if self._is_fixture(ident):
            raise PrototypeError("BLOCKED", "fixture actor cannot approve pilot batch")
        if not reason:
            raise PrototypeError("BLOCKED", "pilot batch requires reason")
        board = self.readiness(candidate_id, tenant_id=tenant_id)
        if self._lineage_stale(candidate_id, tenant_id):
            raise PrototypeError("BLOCKED", "stale ECO/ranking/cost lineage blocks")
        unit = next((u for u in self.units.values() if u.get("candidateId") == candidate_id and u.get("tenantId") == tenant_id), None)
        meas = self.measurements.get((unit or {}).get("latestMeasurementId") or "")
        pack = self.checklists.get((unit or {}).get("packagingChecklistId") or "")
        cost = self.costs.get((unit or {}).get("actualCostId") or "")
        if not unit or not unit.get("physicalPrototypeValidated"):
            raise PrototypeError("BLOCKED", "incomplete validation blocks pilot readiness")
        if (meas or {}).get("source") == "FIXTURE" or (meas or {}).get("truthLabel") == "FIXTURE":
            raise PrototypeError("BLOCKED", "fixture actor/evidence cannot approve pilot batch")
        if (meas or {}).get("truthLabel") not in {"MANUAL_EVIDENCE", "IMPORTED_EVIDENCE"}:
            raise PrototypeError("BLOCKED", "physical prototype validation is MANUAL_EVIDENCE / IMPORTED_EVIDENCE, not FIXTURE")
        if (meas or {}).get("qcMissing") or not (meas or {}).get("tolerance", {}).get("ok"):
            raise PrototypeError("BLOCKED", "required tolerance/QC evidence")
        if not pack or pack.get("ok") is not True:
            raise PrototypeError("BLOCKED", "PROTOTYPE_VALIDATED with no packaging cannot create pilot approval")
        if not cost or cost.get("completeness") != "COMPLETE":
            if not cost_exception_reason:
                raise PrototypeError("BLOCKED", "validated prototype with PARTIAL required actual cost cannot auto-qualify")
        if board.get("demandLabel") == "REAL":
            raise PrototypeError("BLOCKED", "MOCK demand cannot be labeled REAL")
        go = self.record_launch_decision(
            candidate_id,
            tenant_id=tenant_id,
            operator_id=operator_id,
            shift_id=shift_id,
            decision="HUMAN_GO",
            reason=reason,
        )
        plan = self.create_pilot_plan(
            candidate_id,
            tenant_id=tenant_id,
            operator_id=operator_id,
            shift_id=shift_id,
            reason=reason,
            quantity=1,
        )
        rec = {
            "decisionId": new_id(),
            "tenantId": tenant_id,
            "candidateId": candidate_id,
            "decision": "READY_FOR_MANUAL_PILOT_BATCH",
            "launchDecisionId": go.get("launchDecisionId"),
            "launchDecision": "HUMAN_GO",
            "planId": plan.get("planId"),
            "releaseId": plan.get("releaseId"),
            "workOrderId": plan.get("workOrderId"),
            "reason": reason,
            "demandLabel": board.get("demandLabel"),
            "demandDidNotUpgrade": True,
            "productionReady": False,
            "liveMachineControl": False,
            "costExceptionReason": cost_exception_reason,
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "at": _now(),
        }
        self.decisions[rec["decisionId"]] = rec
        self.persist()
        return rec

    def readiness(self, candidate_id: str, *, tenant_id: str) -> dict[str, Any]:
        cand = self._candidate(candidate_id, tenant_id)
        sel = next((s for s in self.selections.values() if s.get("candidateId") == candidate_id and s.get("tenantId") == tenant_id), None)
        unit = next((u for u in self.units.values() if u.get("candidateId") == candidate_id and u.get("tenantId") == tenant_id), None)
        meas = self.measurements.get((unit or {}).get("latestMeasurementId") or "")
        cost = self.costs.get((unit or {}).get("actualCostId") or "")
        pack = self.checklists.get((unit or {}).get("packagingChecklistId") or "")
        eco = next((e for e in self.ecos.values() if e.get("candidateId") == candidate_id and e.get("status") == "ACCEPTED"), None)
        demand = (cand.get("demand") or {}).get("truthLabel") or "MOCK"
        dfm = cand.get("dfm") or {}
        nest = self._nest(cand)
        state = "NOT_SELECTED"
        if sel:
            state = "READY_FOR_PROTOTYPE"
        if unit:
            if unit["state"] in {"PLANNED", "WAITING_HUMAN_START", "IN_BUILD", "REWORK"}:
                state = "PROTOTYPE_IN_PROGRESS"
            elif unit["state"] == "WAITING_VALIDATION":
                state = "WAITING_PHYSICAL_EVIDENCE"
            elif unit["state"] == "HOLD":
                state = "HOLD"
            elif unit["state"] == "SCRAPPED":
                state = "HOLD"
            elif unit["state"] == "VALIDATED" and unit.get("physicalPrototypeValidated"):
                state = "PROTOTYPE_VALIDATED"
            elif unit["state"] == "VALIDATED":
                state = "WAITING_PHYSICAL_EVIDENCE"
        if eco:
            state = "NEEDS_ECO"
        if pack and pack.get("ok") is False:
            state = "HOLD"
        if demand == "REAL":
            raise PrototypeError("BLOCKED", "MOCK demand cannot influence GO state")
        human_pilot = any(d.get("candidateId") == candidate_id and d.get("decision") == "READY_FOR_MANUAL_PILOT_BATCH" for d in self.decisions.values())
        pkg = self.packages.get((unit or {}).get("evidencePackageId") or "")
        evidence_ok = bool(
            unit
            and unit.get("physicalPrototypeValidated")
            and meas
            and meas.get("truthLabel") in {"MANUAL_EVIDENCE", "IMPORTED_EVIDENCE"}
            and (meas.get("tolerance") or {}).get("ok")
            and not meas.get("qcMissing")
            and pack
            and pack.get("ok")
            and cost
            and cost.get("completeness") == "COMPLETE"
            and not self._lineage_stale(candidate_id, tenant_id)
            and pkg
            and pkg.get("evidenceSource") in {"MANUAL_EVIDENCE", "IMPORTED_EVIDENCE"}
            and pkg.get("state") != "INVALIDATED"
        )
        if evidence_ok and state == "PROTOTYPE_VALIDATED":
            state = "READY_FOR_HUMAN_GO_NO_GO"
        if human_pilot and evidence_ok:
            state = "READY_FOR_HUMAN_GO_NO_GO"
        go = self._human_go_record(candidate_id, tenant_id)
        launch = "WAITING_HUMAN_EVIDENCE"
        if unit and unit.get("state") == "REWORK":
            launch = "HOLD_REWORK"
        elif state == "HOLD" or (pack and pack.get("ok") is False) or (meas and not (meas.get("tolerance") or {}).get("ok")):
            launch = "HOLD_REWORK"
        elif state == "READY_FOR_HUMAN_GO_NO_GO":
            launch = "READY_FOR_HUMAN_GO_NO_GO"
        if go and go.get("decision") == "HUMAN_NO_GO":
            launch = "HUMAN_NO_GO"
            state = "HOLD"
        elif go and go.get("decision") == "HUMAN_GO" and evidence_ok:
            launch = "HUMAN_GO"
            state = "READY_FOR_HUMAN_GO_NO_GO"
        blockers = [
            k
            for k, ok in (
                ("not_selected", not sel),
                ("no_unit", not unit),
                ("fixture_evidence", (meas or {}).get("source") == "FIXTURE"),
                ("missing_measurements", bool((meas or {}).get("missingRequired"))),
                ("tolerance", bool(meas) and not (meas.get("tolerance") or {}).get("ok")),
                ("qc", bool(meas) and bool(meas.get("qcMissing"))),
                ("packaging", (not pack) or pack.get("ok") is False),
                ("cost_partial", (not cost) or cost.get("completeness") != "COMPLETE"),
                ("eco", bool(eco)),
                ("stale_lineage", self._lineage_stale(candidate_id, tenant_id) if sel else False),
            )
            if ok
        ]
        return {
            "candidateId": candidate_id,
            "tenantId": tenant_id,
            "state": state,
            "selectionId": sel.get("selectionId") if sel else None,
            "prototypeUnitId": (unit or {}).get("prototypeUnitId"),
            "engineeringHash": (unit or sel or cand).get("engineeringHash"),
            "canonicalHash": (unit or sel or {}).get("canonicalHash") if (unit or sel) else None,
            "bomHash": (unit or sel or {}).get("bomHash") if (unit or sel) else None,
            "nestingHash": (unit or sel or {}).get("nestingHash") if (unit or sel) else None,
            "rankingScore": sel.get("score") if sel else None,
            "rankingPolicyHash": sel.get("rankingPolicyHash") if sel else None,
            "conservationOk": dfm.get("conservationOk"),
            "expectedUtilization": nest.get("utilizationRatio") or dfm.get("utilization"),
            "trueScrap": nest.get("trueScrapArea") or dfm.get("trueScrapArea"),
            "reusableRemnant": nest.get("reusableRemnantArea") or dfm.get("reusableRemnantArea"),
            "prototypeStatus": (unit or {}).get("state"),
            "toleranceResult": (meas or {}).get("tolerance"),
            "dimensionalVariance": (meas or {}).get("variance"),
            "assemblyObservedVsEstimated": (pack or {}).get("assemblyObservedVsEstimated")
            or ((meas or {}).get("variance") or {}).get("assemblyMinutes"),
            "observedCostLabel": (cost or {}).get("truthLabel"),
            "observedMonetaryVariance": (cost or {}).get("monetaryVariance"),
            "costCompleteness": (cost or {}).get("completeness"),
            "packagingPredictedVsObserved": (pack or {}).get("variance"),
            "packagingValidation": None
            if not pack
            else {
                "ok": pack.get("ok"),
                "reason": pack.get("reason"),
                "volumetricWeightKg": pack.get("volumetricWeightKg"),
                "packagingPolicyHash": pack.get("packagingPolicyHash"),
            },
            "qcStatus": None if not meas else {"missing": meas.get("qcMissing") or [], "observations": meas.get("observations"), "complete": not meas.get("qcMissing")},
            "realBlenderLineage": {
                "reused": True,
                "commitSha": PRIOR_REAL_BLENDER["commitSha"],
                "generation": PRIOR_REAL_BLENDER["generation"],
                "label": "REAL",
            },
            "demandLabel": demand,
            "liveMachineControl": False,
            "productionReady": False,
            "physicalPrototypeValidated": bool((unit or {}).get("physicalPrototypeValidated")),
            "evidenceSource": (meas or {}).get("source") or (unit or {}).get("evidenceSource"),
            "evidencePackageId": (pkg or {}).get("evidencePackageId") or (unit or {}).get("evidencePackageId"),
            "launchDecision": launch,
            "blockers": blockers,
        }

    def decision_board(self, portfolio_id: str, *, tenant_id: str) -> dict[str, Any]:
        ranking = next(
            (r for r in self.platform.portfolio.rankings.values() if r.get("portfolioId") == portfolio_id and r.get("tenantId") == tenant_id),
            None,
        )
        rows = []
        for item in (ranking or {}).get("top10") or []:
            rows.append(self.readiness(item["candidateId"], tenant_id=tenant_id))
        missing = []
        for i, row in enumerate(rows):
            for key in REQUIRED_BOARD_FIELDS:
                if key not in row:
                    missing.append(f"{i}:{key}")
        return {
            "portfolioId": portfolio_id,
            "tenantId": tenant_id,
            "rows": rows,
            "missingRequiredFields": missing,
            "liveMachineControl": False,
            "globalProductionReady": False,
            "truthLabel": "REAL_LOGIC",
        }

    def matrix_row(self, unit: dict[str, Any]) -> dict[str, Any]:
        sel = self.selections.get(unit.get("selectionId") or "")
        board = self.readiness(unit["candidateId"], tenant_id=unit["tenantId"])
        meas = self.measurements.get(unit.get("latestMeasurementId") or "")
        cost = self.costs.get(unit.get("actualCostId") or "")
        pack = self.checklists.get(unit.get("packagingChecklistId") or "")
        eco = next((e for e in self.ecos.values() if e.get("candidateId") == unit["candidateId"] and e.get("status") == "ACCEPTED"), None)
        return {
            "selectionId": (sel or {}).get("selectionId"),
            "candidateId": unit.get("candidateId"),
            "engineeringHash": unit.get("engineeringHash"),
            "canonicalHash": unit.get("canonicalHash") or (sel or {}).get("canonicalHash"),
            "bomHash": unit.get("bomHash") or (sel or {}).get("bomHash"),
            "nestingHash": unit.get("nestingHash") or (sel or {}).get("nestingHash"),
            "rankingPolicyHash": unit.get("rankingPolicyHash") or (sel or {}).get("rankingPolicyHash"),
            "costSnapshotHash": unit.get("costSnapshotHash"),
            "prototypeUnitId": unit.get("prototypeUnitId"),
            "unitState": unit.get("state"),
            "evidenceSource": unit.get("evidenceSource") or (meas or {}).get("source"),
            "buildCompleted": unit.get("buildCompleted") is True,
            "toleranceStatus": (meas or {}).get("tolerance", {}).get("ok") if meas else False,
            "qcStatus": None if not meas else {"complete": not meas.get("qcMissing"), "missing": meas.get("qcMissing") or []},
            "assemblyObservedVsEstimated": (pack or {}).get("assemblyObservedVsEstimated")
            or ((meas or {}).get("variance") or {}).get("assemblyMinutes"),
            "costCompleteness": (cost or {}).get("completeness") or "MISSING",
            "observedCostLabel": (cost or {}).get("truthLabel"),
            "monetaryVarianceStatus": None if not cost else ("COMPLETE" if cost.get("monetaryVariance") else cost.get("completeness")),
            "packagingCompleteness": "MISSING" if not pack else ("COMPLETE" if pack.get("ok") else "PARTIAL"),
            "packagingVarianceStatus": None if not pack else pack.get("reason"),
            "packagingValidation": None
            if not pack
            else {
                "ok": pack.get("ok"),
                "reason": pack.get("reason"),
                "packagingPolicyHash": pack.get("packagingPolicyHash"),
            },
            "packagingPredictedVsObserved": (pack or {}).get("variance"),
            "ecoStatus": None if not eco else eco.get("status"),
            "decisionState": board.get("state"),
            "blockers": board.get("blockers"),
            "physicalPrototypeValidated": bool(unit.get("physicalPrototypeValidated")),
            "liveMachineControl": False,
            "consumesInventory": bool(unit.get("consumesInventory")),
            "inventoryLineage": unit.get("inventoryLineage"),
            "staleLineage": self._lineage_stale(unit["candidateId"], unit["tenantId"]),
            "launchDecision": board.get("launchDecision"),
            "evidencePackageId": unit.get("evidencePackageId") or board.get("evidencePackageId"),
        }


def run_prototype_scenario(
    plat: Any,
    *,
    tenant_a: str = "pv-a",
    tenant_b: str = "pv-b",
    render: bool = False,
    evidence_commit: str | None = None,
) -> dict[str, Any]:
    from fox3d.portfolio import run_portfolio_scenario

    portfolio = run_portfolio_scenario(plat, tenant_a=tenant_a, tenant_b=tenant_b, render=render, evidence_commit=evidence_commit)
    ident = plat.pilot.identity
    fixture = ident.register_operator(tenant_id=tenant_a, display_name="fixture-pm", capabilities=["FIXTURE"])
    human = ident.register_operator(tenant_id=tenant_a, display_name="builder", capabilities=["MANUAL"])
    other = ident.register_operator(tenant_id=tenant_b, display_name="other")
    shift = ident.open_shift(tenant_id=tenant_a, operator_id=fixture["operatorId"], station_id="st-proto")
    human_shift = ident.open_shift(tenant_id=tenant_a, operator_id=human["operatorId"], station_id="st-proto")
    closed = ident.open_shift(tenant_id=tenant_a, operator_id=fixture["operatorId"], station_id="st-closed")
    ident.close_shift(closed["shiftId"], tenant_id=tenant_a, operator_id=fixture["operatorId"])
    ident.register_operator(tenant_id=tenant_a, display_name="disabled", operator_id="op-off", enabled=False)
    pf = plat.prototype
    selected = pf.select_four(
        tenant_id=tenant_a,
        portfolio_id=portfolio["portfolioId"],
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        reason="pilot-four",
    )
    units = []
    fixture_obs = {
        "hardware": {"status": "NOT_APPLICABLE", "reason": "FIXTURE_CI"},
        "panelEdgeFinish": {"status": "NOT_APPLICABLE", "reason": "FIXTURE_CI"},
        "wobbleStability": {"status": "NOT_APPLICABLE", "reason": "FIXTURE_CI"},
        "doorDrawerFit": {"status": "NOT_APPLICABLE", "reason": "FIXTURE_CI"},
        "reworkCount": 0,
        "defectCount": 0,
    }
    for sel in selected:
        unit = pf.create_unit(tenant_id=tenant_a, selection_id=sel["selectionId"], operator_id=fixture["operatorId"], shift_id=shift["shiftId"], seq=1)
        unit = pf.start_unit(unit["prototypeUnitId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
        unit = pf.complete_build(unit["prototypeUnitId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
        cand = plat.portfolio.candidates[sel["candidateId"]]
        spec = cand["spec"]
        counts = pf._bom_counts(cand)
        pack = ((cand.get("sku") or {}).get("packing") or {})
        weight = ((cand.get("sku") or {}).get("weight") or {})
        dfm = cand.get("dfm") or {}
        predicted = {
            "widthMm": spec["width"],
            "depthMm": spec["depth"],
            "heightMm": spec["height"],
            "assembledWeightKg": weight.get("grossKg") or weight.get("netKg"),
            "assemblyMinutes": dfm.get("assemblyMinutes"),
            "cartonLengthMm": pack.get("length"),
            "cartonWidthMm": pack.get("width"),
            "cartonHeightMm": pack.get("height"),
            "packedWeightKg": weight.get("grossKg") or weight.get("netKg"),
        }
        pf.record_as_built(
            unit["prototypeUnitId"],
            tenant_id=tenant_a,
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            source="FIXTURE",
            values=predicted,
            observations=fixture_obs,
        )
        pf.record_actual_cost(
            unit["prototypeUnitId"],
            tenant_id=tenant_a,
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            source="FIXTURE",
            components={"laborMinutes": 40, "hardwareConsumed": None},
        )
        pf.packaging_checklist(
            unit["prototypeUnitId"],
            tenant_id=tenant_a,
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            source="FIXTURE",
            observed={
                "cartonLengthMm": predicted["cartonLengthMm"],
                "cartonWidthMm": predicted["cartonWidthMm"],
                "cartonHeightMm": predicted["cartonHeightMm"],
                "packedWeightKg": predicted["packedWeightKg"],
                "hardwareQty": counts["hardwareQty"],
                "partCount": counts["partCount"],
                "packingFit": "OK",
                "missingParts": "NO",
                "damageDefect": "OK",
                "assemblyMinutes": predicted["assemblyMinutes"],
            },
        )
        units.append(unit)
        pkg_id = pf.units[unit["prototypeUnitId"]].get("evidencePackageId")
        if pkg_id:
            try:
                pf.finalize_evidence_package(
                    pkg_id,
                    tenant_id=tenant_a,
                    operator_id=fixture["operatorId"],
                    shift_id=shift["shiftId"],
                )
            except PrototypeError:
                pass
    board = pf.decision_board(portfolio["portfolioId"], tenant_id=tenant_a)
    live_units = [pf.units[u["prototypeUnitId"]] for u in units]
    matrix = [pf.matrix_row(u) for u in live_units]
    board_by_cid = {row.get("candidateId"): row for row in (board.get("rows") or []) if isinstance(row, dict)}
    selected_board = [board_by_cid[sel["candidateId"]] for sel in selected if sel.get("candidateId") in board_by_cid]
    physical = any(u.get("physicalPrototypeValidated") for u in pf.units.values())
    packages = []
    for unit in live_units:
        pkg = pf.packages.get(unit.get("evidencePackageId") or "")
        if pkg:
            packages.append(pkg)
    launch_states = [row.get("launchDecision") for row in selected_board]
    launch = "WAITING_HUMAN_EVIDENCE"
    if launch_states and all(s == "HUMAN_GO" for s in launch_states):
        launch = "HUMAN_GO"
    elif any(s == "HUMAN_NO_GO" for s in launch_states):
        launch = "HUMAN_NO_GO"
    elif any(s == "HOLD_REWORK" for s in launch_states):
        launch = "HOLD_REWORK"
    elif any(s == "READY_FOR_HUMAN_GO_NO_GO" for s in launch_states):
        launch = "READY_FOR_HUMAN_GO_NO_GO"
    return {
        "ok": True,
        "portfolio": portfolio,
        "selected": selected,
        "units": live_units,
        "matrix": matrix,
        "board": board,
        "selectedBoard": selected_board,
        "evidencePackages": packages,
        "launchDecision": launch,
        "physicalPrototypeValidated": physical,
        "fixtureCannotValidate": physical is False,
        "demandLabel": portfolio.get("demandLabel"),
        "liveMachineControl": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "media": portfolio.get("media") or [],
        "label": "FIXTURE/REAL_LOGIC",
        "closedShiftId": closed["shiftId"],
        "disabledOperatorId": "op-off",
        "otherTenantOperatorId": other["operatorId"],
        "human": human,
        "humanShift": human_shift,
        "fixture": fixture,
        "fixtureShift": shift,
    }
