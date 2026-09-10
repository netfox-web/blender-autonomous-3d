"""Phase 721–780 Manual Pilot Batch Execution & Commercial Launch Readiness.

FIXTURE/REAL_LOGIC software governance — not Production Ready, not live factory.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import StockShortage, atomic_write_json, read_json
from fox3d.journal import emit
from fox3d.mfg_release import product_snapshot
from fox3d.workorder import FIXTURE_AUTO_SEED, STRICT_STOCK

BATCH_STATES = (
    "PLANNED",
    "WAITING_HUMAN_RELEASE",
    "RELEASED_FOR_MANUAL_PILOT",
    "IN_PROGRESS",
    "HOLD",
    "REWORK",
    "COMPLETED_PENDING_REVIEW",
    "READY_FOR_HUMAN_BATCH_GO_NO_GO",
    "HUMAN_BATCH_GO",
    "HUMAN_BATCH_NO_GO",
)
UNIT_STATES = (
    "PLANNED",
    "STARTED",
    "MATERIAL_CONSUMED",
    "IN_PROCESS",
    "QC_PENDING",
    "QC_PASSED",
    "QC_FAILED",
    "PACKED",
    "HOLD",
    "REWORK",
    "SCRAPPED",
    "COMPLETED",
)
BATCH_DECISIONS = (
    "WAITING_HUMAN_EVIDENCE",
    "HOLD_REWORK",
    "READY_FOR_HUMAN_BATCH_GO_NO_GO",
    "HUMAN_BATCH_GO",
    "HUMAN_BATCH_NO_GO",
)
ALLOWED_SOURCES = frozenset({"FIXTURE", "MANUAL", "IMPORTED", "MANUAL_EVIDENCE", "IMPORTED_EVIDENCE"})
SAMPLING_PLAN = {
    "kind": "OPERATIONAL_CONFIG",
    "sampleEvery": 1,
    "certification": False,
    "aql": None,
    "iso": False,
    "label": "not a certified AQL/ISO sampling program",
}


class PilotBatchError(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return utcnow().isoformat()


def _finite_positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PilotBatchError("BLOCKED", f"invalid {name}") from exc
    if not math.isfinite(number) or number <= 0:
        raise PilotBatchError("BLOCKED", f"invalid {name}")
    return number


def _same_qty(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) < 1e-9
    except (TypeError, ValueError):
        return False


def _qty_ok(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _index_rows(rows: Any, key: str) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            grouped.setdefault(None, []).append({"_malformed": True})
            continue
        grouped.setdefault(row.get(key), []).append(row)
    return grouped


def labor_semantic_key(row: dict[str, Any]) -> str:
    if row.get("idempotencyKey"):
        return str(row["idempotencyKey"])
    try:
        qty_s = str(float(row.get("minutes")))
    except (TypeError, ValueError):
        qty_s = str(row.get("minutes") or "")
    return (
        f"{row.get('tenantId') or ''}::batch-labor::{row.get('unitExecutionId') or ''}::"
        f"{row.get('engineeringHash') or ''}::{qty_s}::{row.get('reason') or ''}"
    )


def validate_pilot_batch_acceptance_result(result: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    batches = [b for b in (result.get("batches") or []) if isinstance(b, dict)]
    units = [u for u in (result.get("units") or []) if isinstance(u, dict)]
    cartons = [c for c in (result.get("cartons") or []) if isinstance(c, dict)]
    board = result.get("board") if isinstance(result.get("board"), dict) else {}
    board_rows = [r for r in (board.get("rows") or []) if isinstance(r, dict)]
    authority = result.get("batchAuthority") if isinstance(result.get("batchAuthority"), dict) else {}
    auth_batches = [r for r in (authority.get("batches") or []) if isinstance(r, dict)]
    auth_units = [r for r in (authority.get("units") or []) if isinstance(r, dict)]
    auth_cartons = [r for r in (authority.get("cartons") or []) if isinstance(r, dict)]
    auth_labor = [r for r in (authority.get("labor") or []) if isinstance(r, dict)]
    auth_qc = [r for r in (authority.get("qc") or []) if isinstance(r, dict)]
    auth_material = [r for r in (authority.get("materials") or []) if isinstance(r, dict)]
    auth_costs = [r for r in (authority.get("costs") or []) if isinstance(r, dict)]
    auth_decisions = [r for r in (authority.get("decisions") or []) if isinstance(r, dict)]
    if len(batches) < 4:
        failures.append("batches_4")
    if len(units) < 20:
        failures.append("units_20")
    if result.get("physicalPilotBatchValidated") is True:
        failures.append("fixture_physical_batch")
    launch = result.get("batchLaunchDecision") or result.get("launchDecision")
    if result.get("label") in {"FIXTURE", "FIXTURE/REAL_LOGIC"} and launch == "HUMAN_BATCH_GO":
        failures.append("fixture_batch_go")
    for flag in (
        "globalProductionReady",
        "fullAutonomousFactoryReady",
        "liveFactoryExecutionReady",
        "liveProviderReady",
        "liveMachineControl",
    ):
        if result.get(flag) not in {None, False}:
            failures.append(flag)
    if result.get("demandLabel") == "REAL":
        failures.append("demand_mislabeled_real")
    batch_ids = [b.get("batchId") for b in batches if b.get("batchId")]
    unit_ids = [u.get("unitExecutionId") for u in units if u.get("unitExecutionId")]
    if len(batch_ids) != len(set(batch_ids)):
        failures.append("duplicate_batch_id")
    if len(unit_ids) != len(set(unit_ids)):
        failures.append("duplicate_unit_execution_id")
    auth_batch_ids = [r.get("batchId") for r in auth_batches if r.get("batchId")]
    auth_unit_ids = [r.get("unitExecutionId") for r in auth_units if r.get("unitExecutionId")]
    if set(batch_ids) != set(auth_batch_ids) or len(auth_batch_ids) != len(set(auth_batch_ids)):
        failures.append("batch_authority_id_mismatch")
    if set(unit_ids) != set(auth_unit_ids) or len(auth_unit_ids) != len(set(auth_unit_ids)):
        failures.append("unit_authority_id_mismatch")
    if not auth_batches:
        failures.append("batch_authority_missing")
    if not auth_units:
        failures.append("unit_authority_missing")
    if not auth_material:
        failures.append("material_authority_missing")
    if not auth_labor:
        failures.append("labor_authority_missing")
    if not auth_qc:
        failures.append("qc_authority_missing")
    if not auth_costs:
        failures.append("cost_authority_missing")
    packed_units = [u for u in units if str(u.get("state") or "") == "PACKED" or u.get("cartonId")]
    if packed_units and not cartons:
        failures.append("cartons_missing")
    if len(batches) >= 4 and not board_rows:
        failures.append("board_rows_missing")
    batch_by = _index_rows(batches, "batchId")
    unit_by = _index_rows(units, "unitExecutionId")
    auth_batch_by = _index_rows(auth_batches, "batchId")
    auth_unit_by = _index_rows(auth_units, "unitExecutionId")
    auth_carton_by = _index_rows(auth_cartons, "cartonId")
    auth_labor_by_unit = _index_rows(auth_labor, "unitExecutionId")
    auth_qc_by_unit = _index_rows(auth_qc, "unitExecutionId")
    auth_mat_by_batch = _index_rows(auth_material, "batchId")
    auth_cost_by_batch = _index_rows(auth_costs, "batchId")
    board_by = _index_rows(board_rows, "batchId")
    batch_keys = (
        "tenantId",
        "candidateId",
        "selectionId",
        "prototypeUnitId",
        "engineeringHash",
        "canonicalHash",
        "bomHash",
        "nestingHash",
        "rankingPolicyHash",
        "releaseId",
        "releaseHash",
        "workOrderId",
        "requestedQuantity",
        "source",
        "truthLabel",
    )
    unit_keys = (
        "tenantId",
        "batchId",
        "engineeringHash",
        "releaseId",
        "releaseHash",
        "workOrderId",
        "seq",
        "state",
    )
    for batch in batches:
        bid = batch.get("batchId")
        matches = auth_batch_by.get(bid) or []
        if len(matches) != 1:
            failures.append("batch_authority_missing")
            continue
        auth = matches[0]
        if batch.get("truthLabel") == "FIXTURE" and batch.get("state") == "HUMAN_BATCH_GO":
            failures.append("fixture_batch_go")
        if batch.get("liveMachineControl") is True:
            failures.append("liveMachineControl")
        for key in batch_keys:
            if not _present(auth.get(key)):
                failures.append(f"batch_{key}_missing")
            elif _present(batch.get(key)) and batch.get(key) != auth.get(key):
                failures.append("batch_authority_field_mismatch")
        if not (board_by.get(bid) or []):
            failures.append("board_rows_missing")
        mat = auth_mat_by_batch.get(bid) or []
        if len(mat) != 1:
            failures.append("material_authority_missing")
        else:
            rec = mat[0]
            if rec.get("kind") != "BATCH_ALLOCATION_PROJECTION":
                failures.append("material_allocation_kind")
            if rec.get("workOrderId") != auth.get("workOrderId"):
                failures.append("material_authority_lineage")
            alloc = rec.get("unitAllocations") if isinstance(rec.get("unitAllocations"), list) else []
            try:
                total = float(sum(float(a.get("quantity") or 0) for a in alloc if isinstance(a, dict)))
            except (TypeError, ValueError):
                total = None
            if rec.get("consumedQuantity") is None or total is None or abs(total - float(rec.get("consumedQuantity") or 0)) > 1e-9:
                failures.append("material_allocation_sum")
        costs = auth_cost_by_batch.get(bid) or []
        if len(costs) != 1:
            failures.append("cost_authority_missing")
        else:
            cost_auth = costs[0]
            cost = batch.get("cost") if isinstance(batch.get("cost"), dict) else {}
            if cost.get("completeness") == "COMPLETE" and cost.get("truthLabel") in {None, "PARTIAL", "FIXTURE"}:
                failures.append("cost_complete_incorrect")
            if cost.get("completeness") == "COMPLETE" and cost_auth.get("quantityLineage", {}).get("ok") is not True:
                failures.append("cost_complete_without_qty")
    seq_seen: dict[str, set[Any]] = {}
    packed_ids: list[str] = []
    executed_ids: list[str] = []
    for unit in units:
        uid = unit.get("unitExecutionId")
        matches = auth_unit_by.get(uid) or []
        if len(matches) != 1:
            failures.append("unit_authority_missing")
            continue
        auth = matches[0]
        for key in unit_keys:
            if not _present(auth.get(key)) and key != "seq":
                failures.append(f"unit_{key}_missing")
            elif key in unit and _present(unit.get(key)) and unit.get(key) != auth.get(key):
                failures.append("unit_authority_field_mismatch")
        parent = (auth_batch_by.get(auth.get("batchId")) or [None])[0]
        if parent is None:
            failures.append("unit_authority_lineage")
        else:
            for key in ("tenantId", "engineeringHash", "releaseId", "releaseHash", "workOrderId"):
                if auth.get(key) != parent.get(key):
                    failures.append("unit_authority_lineage")
        seq_seen.setdefault(str(auth.get("batchId")), set())
        if auth.get("seq") in seq_seen[str(auth.get("batchId"))]:
            failures.append("unit_seq_duplicate")
        seq_seen[str(auth.get("batchId"))].add(auth.get("seq"))
        if auth.get("state") not in {"PLANNED"}:
            executed_ids.append(str(uid))
            labs = auth_labor_by_unit.get(uid) or []
            if len(labs) != 1:
                failures.append("labor_authority_coverage")
            else:
                lab = labs[0]
                if lab.get("tenantId") != auth.get("tenantId") or lab.get("batchId") != auth.get("batchId"):
                    failures.append("labor_authority_lineage")
                if not lab.get("idempotencyKey") and not lab.get("laborId"):
                    failures.append("labor_authority_missing")
            if auth.get("sampled") is not False:
                qcs = [r for r in (auth_qc_by_unit.get(uid) or []) if r.get("stage") == "FINAL"]
                if len(qcs) != 1:
                    failures.append("qc_authority_missing")
                else:
                    qc = qcs[0]
                    if qc.get("result") not in {"PASS", "FAIL"} or not qc.get("qcPlanHash"):
                        failures.append("qc_authority_final")
                    if qc.get("tenantId") != auth.get("tenantId") or qc.get("engineeringHash") != auth.get("engineeringHash"):
                        failures.append("qc_authority_lineage")
            if auth.get("consumedQuantity") is None and auth.get("allocatedQuantity") is None:
                failures.append("material_authority_missing")
        if str(auth.get("state") or "") == "PACKED" or unit.get("cartonId"):
            packed_ids.append(str(uid))
            cid = unit.get("cartonId") or auth.get("cartonId")
            found = auth_carton_by.get(cid) or []
            if not _present(cid) or len(found) != 1:
                failures.append("carton_authority_missing")
    labor_ids = [r.get("laborId") for r in auth_labor if r.get("laborId")]
    if len(labor_ids) != len(set(labor_ids)):
        failures.append("labor_duplicate_id")
    keys = [str(r.get("idempotencyKey") or labor_semantic_key(r)) for r in auth_labor]
    if len(keys) != len(set(keys)):
        failures.append("labor_duplicate_semantic")
    covered = {str(r.get("unitExecutionId")) for r in auth_labor if r.get("unitExecutionId")}
    if set(executed_ids) - covered:
        failures.append("labor_authority_coverage")
    carton_unit_ids: list[str] = []
    for carton in cartons:
        cid = carton.get("cartonId")
        matches = auth_carton_by.get(cid) or []
        if not _present(cid) or len(matches) != 1:
            failures.append("carton_authority_missing")
        if carton.get("batchId") and carton.get("batchId") not in set(batch_ids):
            failures.append("carton_cross_batch")
        meas = carton.get("measured") if isinstance(carton.get("measured"), dict) else {}
        if packed_ids and not all(_qty_ok(meas.get(k)) for k in ("lengthMm", "widthMm", "heightMm", "weightKg")):
            failures.append("carton_measurements")
    for carton in auth_cartons:
        if carton.get("batchId") and carton.get("batchId") not in set(batch_ids):
            failures.append("carton_cross_batch")
        for uid in carton.get("unitExecutionIds") or []:
            carton_unit_ids.append(str(uid))
        meas = carton.get("measured") if isinstance(carton.get("measured"), dict) else {}
        if packed_ids and not all(_qty_ok(meas.get(k)) for k in ("lengthMm", "widthMm", "heightMm", "weightKg")):
            failures.append("carton_measurements")
    if len(carton_unit_ids) != len(set(carton_unit_ids)):
        failures.append("duplicate_unit_carton")
    if packed_ids and set(packed_ids) != set(carton_unit_ids):
        failures.append("carton_unit_coverage")
    if set(board_by) - {None} != set(batch_ids):
        failures.append("board_rows_missing")
    if (board.get("decision") or launch) == "HUMAN_BATCH_GO" and result.get("label") in {"FIXTURE", "FIXTURE/REAL_LOGIC"}:
        failures.append("fixture_batch_go")
    return failures


class PilotBatchFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.root = Path(platform.root) / "pilot_batch"
        self.root.mkdir(parents=True, exist_ok=True)
        self.batches: dict[str, dict[str, Any]] = {}
        self.units: dict[str, dict[str, Any]] = {}
        self.cartons: dict[str, dict[str, Any]] = {}
        self.costs: dict[str, dict[str, Any]] = {}
        self.ncrs: dict[str, dict[str, Any]] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.qc: dict[str, dict[str, Any]] = {}
        self.labor: dict[str, dict[str, Any]] = {}
        self.idem: dict[str, str] = {}
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self._crash_mode = ""
        self._hard_crash = False
        self.load()
        self._bind_journal()

    def _path(self) -> Path:
        return self.root / "pilot_batch.json"

    def load(self) -> None:
        payload = read_json(self._path()) or {}
        self.batches = {r["batchId"]: r for r in payload.get("batches") or [] if isinstance(r, dict) and r.get("batchId")}
        self.units = {r["unitExecutionId"]: r for r in payload.get("units") or [] if isinstance(r, dict) and r.get("unitExecutionId")}
        self.cartons = {r["cartonId"]: r for r in payload.get("cartons") or [] if isinstance(r, dict) and r.get("cartonId")}
        self.costs = {r["costId"]: r for r in payload.get("costs") or [] if isinstance(r, dict) and r.get("costId")}
        self.ncrs = {r["ncrId"]: r for r in payload.get("ncrs") or [] if isinstance(r, dict) and r.get("ncrId")}
        self.decisions = {r["decisionId"]: r for r in payload.get("decisions") or [] if isinstance(r, dict) and r.get("decisionId")}
        self.qc = {r["qcId"]: r for r in payload.get("qc") or [] if isinstance(r, dict) and r.get("qcId")}
        self.labor = {r["laborId"]: r for r in payload.get("labor") or [] if isinstance(r, dict) and r.get("laborId")}
        raw = payload.get("idem") or {}
        self.idem = dict(raw) if isinstance(raw, dict) else {}
        self._bind_journal()

    def persist(self) -> None:
        atomic_write_json(
            self._path(),
            {
                "batches": list(self.batches.values()),
                "units": list(self.units.values()),
                "cartons": list(self.cartons.values()),
                "costs": list(self.costs.values()),
                "ncrs": list(self.ncrs.values()),
                "decisions": list(self.decisions.values()),
                "qc": list(self.qc.values()),
                "labor": list(self.labor.values()),
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

    def _identity(self, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        return self.platform.pilot.identity.require_active(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)

    def _is_fixture(self, ident: dict[str, Any]) -> bool:
        op = ident.get("operator") or {}
        caps = {str(c).upper() for c in (op.get("capabilities") or [])}
        name = str(op.get("displayName") or "").lower()
        return "FIXTURE" in caps or name.startswith("fixture")

    def _require_tenant(self, rec: dict[str, Any], tenant_id: str) -> None:
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: pilot batch")

    def _normalize_source(self, source: str) -> str:
        src = str(source or "").upper()
        if src == "MANUAL_EVIDENCE":
            return "MANUAL"
        if src == "IMPORTED_EVIDENCE":
            return "IMPORTED"
        if src not in ALLOWED_SOURCES and src not in {"MANUAL", "IMPORTED", "FIXTURE"}:
            raise PilotBatchError("BLOCKED", "unknown batch evidence source")
        return src if src in {"FIXTURE", "MANUAL", "IMPORTED"} else src

    def _lookup_idem(self, key: str) -> dict[str, Any] | None:
        rid = self.idem.get(key)
        if not rid:
            for store in (self.batches, self.units, self.cartons, self.costs, self.ncrs, self.decisions, self.qc, self.labor):
                hits = [row for row in store.values() if row.get("idempotencyKey") == key]
                if len(hits) > 1:
                    raise PilotBatchError("HOLD", "duplicate semantic batch operation")
                if hits:
                    self.idem[key] = str(
                        hits[0].get("batchId")
                        or hits[0].get("unitExecutionId")
                        or hits[0].get("cartonId")
                        or hits[0].get("costId")
                        or hits[0].get("ncrId")
                        or hits[0].get("decisionId")
                        or hits[0].get("qcId")
                        or hits[0].get("laborId")
                    )
                    return hits[0]
            return None
        for store in (self.batches, self.units, self.cartons, self.costs, self.ncrs, self.decisions, self.qc, self.labor):
            if rid in store:
                return store[rid]
        raise PilotBatchError("BLOCKED", "idempotent key missing record")

    def _idem(self, key: str, factory) -> dict[str, Any]:
        found = self._lookup_idem(key)
        if found is not None:
            return found
        rec = factory()
        return rec

    def _proto_unit(self, candidate_id: str, tenant_id: str) -> dict[str, Any]:
        proto = self.platform.prototype
        unit = next((u for u in proto.units.values() if u.get("candidateId") == candidate_id and u.get("tenantId") == tenant_id), None)
        if unit is None:
            raise PilotBatchError("BLOCKED", "pilot batch requires selected prototype unit lineage")
        self._require_tenant(unit, tenant_id)
        return unit

    def _open_release_wo(self, *, candidate_id: str, tenant_id: str, ident: dict[str, Any], qty: int, source: str, unit: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        proto = self.platform.prototype
        cand = proto._candidate(candidate_id, tenant_id)
        sku = cand.get("sku") or {}
        snap = product_snapshot(
            {
                "productId": cand.get("productId") or (cand.get("spec") or {}).get("productId") or f"batch:{candidate_id}",
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
        actor = ident["operator"]["operatorId"]
        rel = releases.create(snap, tenant_id=tenant_id, created_by=actor, idempotency_key=f"pilot-batch:{source}:{candidate_id}:{unit.get('engineeringHash')}:{qty}")
        if rel.get("status") == "DRAFT":
            releases.validate(rel["releaseId"])
            releases.submit_approval(rel["releaseId"], actor=actor)
            releases.approve(rel["releaseId"], actor=actor)
            releases.release_for_manual_execution(rel["releaseId"], actor=actor)
            rel = releases.get(rel["releaseId"])
        wo = self.platform.pilot.workorders.create(
            tenant_id=tenant_id,
            release=rel,
            quantity=qty,
            actor=actor,
            idempotency_key=f"pilot-batch-wo:{source}:{candidate_id}:{rel.get('releaseHash')}:{qty}",
        )
        return rel, wo

    def create(
        self,
        candidate_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        quantity: int,
        source: str,
        reason: str,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        src = self._normalize_source(source)
        if not reason:
            raise PilotBatchError("BLOCKED", "pilot batch requires reason")
        qty = int(_finite_positive(quantity, "quantity"))
        proto = self.platform.prototype
        unit = self._proto_unit(candidate_id, tenant_id)
        sel = proto.selections.get(unit.get("selectionId") or "") or {}
        pkg = proto.packages.get(unit.get("evidencePackageId") or "")
        eco = next((e for e in proto.ecos.values() if e.get("candidateId") == candidate_id and e.get("tenantId") == tenant_id and e.get("status") == "ACCEPTED"), None)
        if proto._lineage_stale(candidate_id, tenant_id):
            raise PilotBatchError("BLOCKED", "stale/superseded engineeringHash, ECO revision, ManufacturingRelease or evidence package")
        go = proto._human_go_record(candidate_id, tenant_id)
        if src in {"MANUAL", "IMPORTED"}:
            if self._is_fixture(ident):
                raise PilotBatchError("BLOCKED", "fixture actor cannot create production-like pilot batch")
            if not go or go.get("decision") != "HUMAN_GO":
                raise PilotBatchError("BLOCKED", "pilot batch creation without valid HUMAN_GO")
            if go.get("engineeringHash") != unit.get("engineeringHash"):
                raise PilotBatchError("BLOCKED", "stale/superseded engineeringHash, ECO revision, ManufacturingRelease or evidence package")
            if not pkg or pkg.get("state") != "FINALIZED":
                raise PilotBatchError("BLOCKED", "pilot batch requires finalized authoritative evidence")
            if go.get("evidencePackageId") != unit.get("evidencePackageId"):
                raise PilotBatchError("BLOCKED", "stale/superseded engineeringHash, ECO revision, ManufacturingRelease or evidence package")
            truth = "MANUAL_EVIDENCE" if src == "MANUAL" else "IMPORTED_EVIDENCE"
            state = "WAITING_HUMAN_RELEASE"
        else:
            if go and go.get("decision") == "HUMAN_GO":
                raise PilotBatchError("BLOCKED", "FIXTURE batch cannot inherit HUMAN_GO")
            truth = "FIXTURE"
            state = "PLANNED"
        key = f"{tenant_id}::pilot-batch::{candidate_id}::{unit.get('engineeringHash')}::{qty}::{src}"

        def _make():
            rel, wo = self._open_release_wo(candidate_id=candidate_id, tenant_id=tenant_id, ident=ident, qty=qty, source=src, unit=unit)
            body = {
                "batchId": new_id(),
                "tenantId": tenant_id,
                "candidateId": candidate_id,
                "selectionId": unit.get("selectionId") or sel.get("selectionId"),
                "prototypeUnitId": unit.get("prototypeUnitId"),
                "engineeringHash": unit.get("engineeringHash"),
                "canonicalHash": unit.get("canonicalHash"),
                "bomHash": unit.get("bomHash"),
                "nestingHash": unit.get("nestingHash"),
                "rankingPolicyHash": unit.get("rankingPolicyHash"),
                "engineeringRevision": proto._engineering_revision(proto._candidate(candidate_id, tenant_id)),
                "ecoRevision": None if not eco else eco.get("toRevision") or eco.get("revision"),
                "launchDecisionId": None if src == "FIXTURE" else (go or {}).get("launchDecisionId"),
                "evidencePackageId": unit.get("evidencePackageId"),
                "requestedQuantity": qty,
                "executedQuantity": 0,
                "source": src,
                "truthLabel": truth,
                "state": state,
                "reason": reason,
                "releaseId": rel.get("releaseId"),
                "releaseHash": rel.get("releaseHash"),
                "workOrderId": wo.get("workOrderId"),
                "samplingPlan": dict(SAMPLING_PLAN),
                "staleLineage": False,
                "physicalPilotBatchValidated": False,
                "liveMachineControl": False,
                "liveCnc": False,
                "liveLaser": False,
                "productionReady": False,
                "createdBy": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "createdAt": _now(),
                "idempotencyKey": key,
            }
            self.batches[body["batchId"]] = body
            for seq in range(qty):
                ukey = f"{tenant_id}::unit-exec::{body['batchId']}::{seq}"
                urec = {
                    "unitExecutionId": new_id(),
                    "tenantId": tenant_id,
                    "batchId": body["batchId"],
                    "seq": seq,
                    "candidateId": candidate_id,
                    "selectionId": body["selectionId"],
                    "prototypeUnitId": body["prototypeUnitId"],
                    "engineeringHash": body["engineeringHash"],
                    "canonicalHash": body["canonicalHash"],
                    "bomHash": body["bomHash"],
                    "nestingHash": body["nestingHash"],
                    "rankingPolicyHash": body["rankingPolicyHash"],
                    "releaseId": body["releaseId"],
                    "releaseHash": body["releaseHash"],
                    "workOrderId": body["workOrderId"],
                    "state": "PLANNED",
                    "truthLabel": truth,
                    "source": src,
                    "reservationIds": [],
                    "consumedQuantity": None,
                    "cartonId": None,
                    "qcId": None,
                    "laborId": None,
                    "sampled": seq % int(SAMPLING_PLAN["sampleEvery"] or 1) == 0,
                    "liveMachineControl": False,
                    "idempotencyKey": ukey,
                    "createdAt": _now(),
                }
                self.units[urec["unitExecutionId"]] = urec
                self.idem[ukey] = urec["unitExecutionId"]
            self.idem[key] = body["batchId"]
            self._emit(
                "pilot_batch.create",
                tenant_id=tenant_id,
                aggregate_type="PilotBatch",
                aggregate_id=body["batchId"],
                actor=ident["operator"]["operatorId"],
                payload={"candidateId": candidate_id, "quantity": qty, "source": src, "workOrderId": wo.get("workOrderId")},
                semantic_key=key,
            )
            return body

        return self._idem(key, _make)

    def get(self, batch_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.batches[batch_id]
        self._require_tenant(rec, tenant_id)
        return rec

    def units_for(self, batch_id: str, *, tenant_id: str) -> list[dict[str, Any]]:
        self.get(batch_id, tenant_id=tenant_id)
        rows = [u for u in self.units.values() if u.get("batchId") == batch_id]
        for row in rows:
            self._require_tenant(row, tenant_id)
        return sorted(rows, key=lambda r: int(r.get("seq") or 0))

    def release_for_manual(self, batch_id: str, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        rec = self.get(batch_id, tenant_id=tenant_id)
        if rec.get("state") == "RELEASED_FOR_MANUAL_PILOT":
            return rec
        key = f"{tenant_id}::pilot-batch-release::{batch_id}::{rec.get('engineeringHash')}"
        found = self._lookup_idem(key)
        if found is not None:
            return rec
        wo = self.platform.pilot.workorders.release_for_execution(rec["workOrderId"], actor=ident["operator"]["operatorId"])
        rec["state"] = "RELEASED_FOR_MANUAL_PILOT"
        rec["workOrderState"] = wo.get("state")
        self.idem[key] = rec["batchId"]
        self._emit(
            "pilot_batch.release",
            tenant_id=tenant_id,
            aggregate_type="PilotBatch",
            aggregate_id=rec["batchId"],
            actor=ident["operator"]["operatorId"],
            payload={"workOrderId": rec["workOrderId"]},
            semantic_key=key,
        )
        return rec

    def reserve_materials(self, batch_id: str, *, tenant_id: str, operator_id: str, shift_id: str, policy: str | None = None) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        rec = self.get(batch_id, tenant_id=tenant_id)
        if rec.get("state") not in {"RELEASED_FOR_MANUAL_PILOT", "IN_PROGRESS", "PLANNED", "WAITING_HUMAN_RELEASE"}:
            if rec.get("materialReserved"):
                return rec
        alloc = policy or (FIXTURE_AUTO_SEED if rec.get("source") == "FIXTURE" else STRICT_STOCK)
        key = f"{tenant_id}::pilot-batch-reserve::{batch_id}::{rec.get('workOrderId')}"
        found = self._lookup_idem(key)
        if found is not None and rec.get("materialReserved"):
            return rec
        try:
            wo = self.platform.pilot.workorders.reserve_materials(
                rec["workOrderId"],
                actor=ident["operator"]["operatorId"],
                tenant_id=tenant_id,
                allocation_policy=alloc,
            )
        except StockShortage:
            rec["shortage"] = True
            rec["materialReserved"] = False
            self.persist()
            raise
        rec["materialReserved"] = True
        rec["reservationIds"] = [i.get("reservationId") for i in (wo.get("reservations") or []) if i.get("reservationId")]
        rec["lotIds"] = list((wo.get("lineage") or {}).get("materialLots") or [])
        rec["shortage"] = False
        rec["allocationPolicy"] = alloc
        self.idem[key] = rec["batchId"]
        self._emit(
            "pilot_batch.reserve",
            tenant_id=tenant_id,
            aggregate_type="PilotBatch",
            aggregate_id=rec["batchId"],
            actor=ident["operator"]["operatorId"],
            payload={"reservationIds": rec["reservationIds"], "lotIds": rec["lotIds"]},
            semantic_key=key,
        )
        return rec

    def start_unit(self, unit_execution_id: str, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[unit_execution_id]
        self._require_tenant(unit, tenant_id)
        batch = self.get(unit["batchId"], tenant_id=tenant_id)
        if batch.get("staleLineage"):
            raise PilotBatchError("BLOCKED", "stale/superseded engineeringHash, ECO revision, ManufacturingRelease or evidence package")
        key = f"{tenant_id}::unit-start::{unit_execution_id}"
        if unit.get("state") not in {"PLANNED"}:
            return unit
        found = self._lookup_idem(key)
        if found is not None:
            return unit
        unit["state"] = "STARTED"
        unit["startedBy"] = ident["operator"]["operatorId"]
        unit["shiftId"] = ident["shift"]["shiftId"]
        unit["startedAt"] = _now()
        batch["state"] = "IN_PROGRESS"
        batch["executedQuantity"] = len([u for u in self.units.values() if u.get("batchId") == batch["batchId"] and u.get("state") != "PLANNED"])
        self.idem[key] = unit["unitExecutionId"]
        self._emit(
            "pilot_batch.unit.start",
            tenant_id=tenant_id,
            aggregate_type="PilotUnitExecution",
            aggregate_id=unit["unitExecutionId"],
            actor=ident["operator"]["operatorId"],
            payload={"batchId": batch["batchId"], "seq": unit.get("seq")},
            semantic_key=key,
        )
        return unit

    def consume_unit(self, unit_execution_id: str, *, tenant_id: str, operator_id: str, shift_id: str) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[unit_execution_id]
        self._require_tenant(unit, tenant_id)
        batch = self.get(unit["batchId"], tenant_id=tenant_id)
        if not batch.get("materialReserved"):
            raise PilotBatchError("BLOCKED", "consume requires reserved material")
        key = f"{tenant_id}::unit-consume::{unit_execution_id}"
        if unit.get("consumedQuantity") is not None:
            return unit
        found = self._lookup_idem(key)
        if found is not None:
            return unit
        wo = self.platform.pilot.workorders.get(batch["workOrderId"])
        if wo.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: work order")
        if not wo.get("consumedFlag"):
            self.platform.pilot.workorders.consume_reserved(batch["workOrderId"], actor=ident["operator"]["operatorId"])
            wo = self.platform.pilot.workorders.get(batch["workOrderId"])
        qty = float(sum(float(i.get("quantity") or 0) for i in (wo.get("consumed") or []) if i.get("kind") == "lot"))
        share = qty / max(int(batch.get("requestedQuantity") or 1), 1)
        unit["consumedQuantity"] = share
        unit["allocatedQuantity"] = share
        unit["consumeKind"] = "BATCH_ALLOCATION_PROJECTION"
        unit["reservationIds"] = list(batch.get("reservationIds") or [])
        batch["consumedQuantity"] = qty
        batch["consumeKind"] = "BATCH_ALLOCATION_PROJECTION"
        unit["state"] = "MATERIAL_CONSUMED"
        self.idem[key] = unit["unitExecutionId"]
        self._emit(
            "pilot_batch.unit.consume",
            tenant_id=tenant_id,
            aggregate_type="PilotUnitExecution",
            aggregate_id=unit["unitExecutionId"],
            actor=ident["operator"]["operatorId"],
            payload={"consumedQuantity": share, "workOrderId": batch["workOrderId"]},
            semantic_key=key,
        )
        return unit

    def record_labor(self, unit_execution_id: str, *, tenant_id: str, operator_id: str, shift_id: str, minutes: float, reason: str) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[unit_execution_id]
        self._require_tenant(unit, tenant_id)
        qty = _finite_positive(minutes, "laborMinutes")
        if not reason:
            raise PilotBatchError("BLOCKED", "labor requires reason")
        key = f"{tenant_id}::batch-labor::{unit_execution_id}::{unit.get('engineeringHash')}::{qty}::{reason}"

        def _make():
            rec = {
                "laborId": new_id(),
                "tenantId": tenant_id,
                "batchId": unit["batchId"],
                "unitExecutionId": unit_execution_id,
                "engineeringHash": unit.get("engineeringHash"),
                "minutes": qty,
                "reason": reason,
                "source": "LABOR_RECORD",
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "at": _now(),
                "idempotencyKey": key,
            }
            dups = [r for r in self.labor.values() if labor_semantic_key(r) == key]
            if dups:
                raise PilotBatchError("HOLD", "duplicate semantic labor")
            self.labor[rec["laborId"]] = rec
            unit["laborId"] = rec["laborId"]
            if unit.get("state") in {"MATERIAL_CONSUMED", "STARTED"}:
                unit["state"] = "IN_PROCESS"
            self.idem[key] = rec["laborId"]
            self._emit(
                "pilot_batch.labor",
                tenant_id=tenant_id,
                aggregate_type="PilotBatchLabor",
                aggregate_id=rec["laborId"],
                actor=ident["operator"]["operatorId"],
                payload={"minutes": qty, "unitExecutionId": unit_execution_id},
                semantic_key=key,
            )
            return rec

        return self._idem(key, _make)

    def record_qc(self, unit_execution_id: str, *, tenant_id: str, operator_id: str, shift_id: str, ok: bool = True, stage: str = "FINAL") -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[unit_execution_id]
        self._require_tenant(unit, tenant_id)
        batch = self.get(unit["batchId"], tenant_id=tenant_id)
        stage_name = str(stage or "FINAL").upper()
        key = f"{tenant_id}::batch-qc::{unit_execution_id}::{stage_name}"
        found = self._lookup_idem(key)
        if found is not None:
            return found
        wo = self.platform.pilot.workorders.get(batch["workOrderId"])
        if wo.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: work order")

        def _make():
            rec = {
                "qcId": new_id(),
                "tenantId": tenant_id,
                "batchId": batch["batchId"],
                "unitExecutionId": unit_execution_id,
                "workOrderId": batch["workOrderId"],
                "engineeringHash": unit.get("engineeringHash"),
                "releaseHash": batch.get("releaseHash"),
                "qcPlanHash": wo.get("qcPlanHash"),
                "stage": stage_name,
                "ok": bool(ok),
                "result": "PASS" if ok else "FAIL",
                "sampled": True,
                "source": "TEST_DATA" if batch.get("source") == "FIXTURE" else "MANUAL",
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "at": _now(),
                "idempotencyKey": key,
            }
            if stage_name == "FINAL":
                prior = [
                    r
                    for r in self.qc.values()
                    if r.get("unitExecutionId") == unit_execution_id and r.get("stage") == "FINAL" and r.get("qcId") != rec["qcId"]
                ]
                if prior and any(p.get("ok") is not bool(ok) for p in prior):
                    raise PilotBatchError("HOLD", "duplicate conflicting FINAL QC")
            self.qc[rec["qcId"]] = rec
            unit["qcIds"] = list(unit.get("qcIds") or []) + [rec["qcId"]]
            if stage_name == "FINAL":
                unit["qcId"] = rec["qcId"]
                unit["qcFinalId"] = rec["qcId"]
                unit["state"] = "QC_PASSED" if ok else "QC_FAILED"
                if not ok:
                    batch["state"] = "HOLD"
                    unit["state"] = "HOLD"
            self.idem[key] = rec["qcId"]
            self._emit(
                "pilot_batch.qc",
                tenant_id=tenant_id,
                aggregate_type="PilotBatchQc",
                aggregate_id=rec["qcId"],
                actor=ident["operator"]["operatorId"],
                payload={"result": rec["result"], "unitExecutionId": unit_execution_id},
                semantic_key=key,
            )
            return rec

        return self._idem(key, _make)

    def pack_units(
        self,
        batch_id: str,
        *,
        tenant_id: str,
        operator_id: str,
        shift_id: str,
        unit_execution_ids: list[str],
        measured: dict[str, Any],
        packaging_qty: float | None = None,
        checklist_id: str | None = None,
        dam_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        batch = self.get(batch_id, tenant_id=tenant_id)
        ids = [str(i) for i in unit_execution_ids]
        if not ids:
            raise PilotBatchError("BLOCKED", "carton requires unitExecutionIds")
        key = f"{tenant_id}::batch-carton::{batch_id}::{','.join(sorted(ids))}"
        found = self._lookup_idem(key)
        if found is not None:
            return found
        for uid in ids:
            unit = self.units.get(uid)
            if unit is None:
                raise PilotBatchError("BLOCKED", "unknown unitExecutionId")
            self._require_tenant(unit, tenant_id)
            if unit.get("batchId") != batch_id:
                raise PilotBatchError("BLOCKED", "carton from wrong batch/tenant")
            if unit.get("state") == "PLANNED" or not unit.get("startedBy") or unit.get("consumedQuantity") is None or not unit.get("laborId"):
                raise PilotBatchError("BLOCKED", "incomplete unit cannot be packed")
            if unit.get("cartonId"):
                other = self.cartons.get(unit["cartonId"]) or {}
                if other and other.get("state") != "CANCELLED":
                    raise PilotBatchError("BLOCKED", "same unit assigned to two active cartons")
            if batch.get("source") != "FIXTURE" and unit.get("sampled") and not self._final_qc(unit, batch):
                raise PilotBatchError("BLOCKED", "sampled unit missing FINAL QC")
        length = measured.get("lengthMm") if measured.get("lengthMm") is not None else measured.get("cartonLengthMm")
        width = measured.get("widthMm") if measured.get("widthMm") is not None else measured.get("cartonWidthMm")
        height = measured.get("heightMm") if measured.get("heightMm") is not None else measured.get("cartonHeightMm")
        weight = measured.get("weightKg") if measured.get("weightKg") is not None else measured.get("packedWeightKg")
        if not all(_qty_ok(v) for v in (length, width, height, weight)):
            raise PilotBatchError("BLOCKED", "carton measurements missing")
        damage = measured.get("damageDefect")
        if not damage:
            raise PilotBatchError("BLOCKED", "damage/defect result required")
        proto = self.platform.prototype
        proto_unit = proto.units.get(batch.get("prototypeUnitId") or "")
        pack = proto.checklists.get(checklist_id or (proto_unit or {}).get("packagingChecklistId") or "")
        qty = packaging_qty
        if qty is None and pack:
            observed = pack.get("observed") if isinstance(pack.get("observed"), dict) else {}
            raw = observed.get("packagingQty")
            if raw is None:
                raw = pack.get("packagingQty")
            try:
                qty = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                qty = None
        counts = proto._bom_counts(proto._candidate(batch["candidateId"], tenant_id))
        if batch.get("source") != "FIXTURE":
            if not _qty_ok(qty):
                raise PilotBatchError("BLOCKED", "explicit packaging quantity required")
            if pack and (
                pack.get("tenantId") != tenant_id
                or pack.get("prototypeUnitId") not in {None, batch.get("prototypeUnitId")}
                or (pack.get("engineeringHash") and pack.get("engineeringHash") != batch.get("engineeringHash"))
            ):
                raise PilotBatchError("BLOCKED", "stale/wrong checklist lineage")
            if measured.get("hardwareQty") is None or measured.get("partCount") is None:
                raise PilotBatchError("HOLD", "part/hardware counts required")
            if counts.get("hardwareQty") is not None and float(measured.get("hardwareQty")) != float(counts.get("hardwareQty")):
                raise PilotBatchError("HOLD", "hardware count mismatch")
            if counts.get("partCount") is not None and float(measured.get("partCount")) != float(counts.get("partCount")):
                raise PilotBatchError("HOLD", "part count mismatch")
            if str(damage).upper() not in {"OK", "PASS", "NONE", "NO"}:
                raise PilotBatchError("HOLD", "damage/defect blocks packing")
            pkg = proto.packages.get(batch.get("evidencePackageId") or "")
            dam = proto._package_dam(pkg, None, pack)
            dam = proto._merge_dam(dam, dam_refs)
            if not proto._has_dam_role(dam, "PACKAGING", engineering_hash=batch.get("engineeringHash")):
                raise PilotBatchError("BLOCKED", "required PACKAGING DAM evidence missing")
        rec = {
            "cartonId": new_id(),
            "tenantId": tenant_id,
            "batchId": batch_id,
            "workOrderId": batch.get("workOrderId"),
            "unitExecutionIds": ids,
            "engineeringHash": batch.get("engineeringHash"),
            "checklistId": (pack or {}).get("checklistId") or checklist_id,
            "checklistTenantId": (pack or {}).get("tenantId"),
            "checklistEngineeringHash": (pack or {}).get("engineeringHash"),
            "packagingQty": qty,
            "measured": {"lengthMm": float(length), "widthMm": float(width), "heightMm": float(height), "weightKg": float(weight)},
            "hardwareExpected": counts.get("hardwareQty"),
            "hardwareObserved": measured.get("hardwareQty"),
            "partExpected": counts.get("partCount"),
            "partObserved": measured.get("partCount"),
            "damageDefect": damage,
            "damRefs": list(dam_refs or []),
            "state": "ACTIVE",
            "shipmentState": "DRAFT",
            "carrierBooking": False,
            "truthLabel": batch.get("truthLabel"),
            "operatorId": ident["operator"]["operatorId"],
            "shiftId": ident["shift"]["shiftId"],
            "at": _now(),
            "idempotencyKey": key,
            "liveMachineControl": False,
        }
        self.cartons[rec["cartonId"]] = rec
        for uid in ids:
            self.units[uid]["cartonId"] = rec["cartonId"]
            self.units[uid]["state"] = "PACKED"
        self.idem[key] = rec["cartonId"]
        self._emit(
            "pilot_batch.pack",
            tenant_id=tenant_id,
            aggregate_type="PilotBatchCarton",
            aggregate_id=rec["cartonId"],
            actor=ident["operator"]["operatorId"],
            payload={"unitExecutionIds": ids, "packagingQty": qty},
            semantic_key=key,
        )
        return rec

    def _labor_integrity(self, batch: dict[str, Any]) -> dict[str, Any]:
        rows = [r for r in self.labor.values() if r.get("batchId") == batch["batchId"] and r.get("tenantId") == batch["tenantId"]]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(labor_semantic_key(row), []).append(row)
        dups = [k for k, g in grouped.items() if len(g) > 1]
        ids = [str(r.get("laborId")) for r in rows if r.get("laborId")]
        executed = [
            u
            for u in self.units.values()
            if u.get("batchId") == batch["batchId"] and u.get("tenantId") == batch["tenantId"] and u.get("state") not in {"PLANNED"}
        ]
        covered = {str(r.get("unitExecutionId")) for r in rows if r.get("unitExecutionId")}
        need = {str(u.get("unitExecutionId")) for u in executed}
        coverage_ok = need <= covered
        ok = bool(rows) and not dups and len(ids) == len(set(ids)) and coverage_ok
        minutes = float(sum(float(r.get("minutes") or 0) for r in rows)) if ok else None
        return {
            "ok": ok,
            "integrityOk": ok,
            "laborIds": ids,
            "semanticKeys": [labor_semantic_key(r) for r in rows],
            "minutes": minutes,
            "duplicateKeys": dups,
            "missingUnits": sorted(need - covered),
            "source": "LABOR_RECORD" if ok else ("DUPLICATE" if dups else ("MISSING" if not coverage_ok else "MISSING")),
        }

    def _final_qc(self, unit: dict[str, Any], batch: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = [
            r
            for r in self.qc.values()
            if r.get("unitExecutionId") == unit.get("unitExecutionId") and str(r.get("stage") or "").upper() == "FINAL"
        ]
        if len(rows) != 1:
            return None
        rec = rows[0]
        if rec.get("ok") is not True or rec.get("result") != "PASS":
            return None
        if not rec.get("qcPlanHash"):
            return None
        batch = batch or self.batches.get(unit.get("batchId") or "")
        if not batch:
            return None
        if rec.get("tenantId") != unit.get("tenantId") or rec.get("batchId") != batch.get("batchId"):
            return None
        if rec.get("engineeringHash") != unit.get("engineeringHash") or rec.get("releaseHash") != batch.get("releaseHash"):
            return None
        wo = self.platform.pilot.workorders.get(batch.get("workOrderId"))
        if not wo or wo.get("qcPlanHash") != rec.get("qcPlanHash"):
            return None
        return rec

    def _carton_packaging_ok(self, carton: dict[str, Any], batch: dict[str, Any]) -> bool:
        meas = carton.get("measured") if isinstance(carton.get("measured"), dict) else {}
        if not all(_qty_ok(meas.get(k)) for k in ("lengthMm", "widthMm", "heightMm", "weightKg")):
            return False
        if not carton.get("damageDefect"):
            return False
        if batch.get("source") == "FIXTURE":
            return True
        if not _qty_ok(carton.get("packagingQty")) or not carton.get("checklistId"):
            return False
        if carton.get("hardwareObserved") is None or carton.get("partObserved") is None:
            return False
        if carton.get("hardwareExpected") is not None and float(carton.get("hardwareObserved")) != float(carton.get("hardwareExpected")):
            return False
        if carton.get("partExpected") is not None and float(carton.get("partObserved")) != float(carton.get("partExpected")):
            return False
        if str(carton.get("damageDefect") or "").upper() not in {"OK", "PASS", "NONE", "NO"}:
            return False
        proto = self.platform.prototype
        pkg = proto.packages.get(batch.get("evidencePackageId") or "")
        pack = proto.checklists.get(carton.get("checklistId") or "")
        dam = proto._package_dam(pkg, None, pack)
        dam = proto._merge_dam(dam, carton.get("damRefs"))
        if not proto._has_dam_role(dam, "PACKAGING", engineering_hash=batch.get("engineeringHash")):
            return False
        return True

    def record_cost(self, batch_id: str, *, tenant_id: str, operator_id: str, shift_id: str, amounts: dict[str, Any] | None = None, currency: str = "TWD") -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        batch = self.get(batch_id, tenant_id=tenant_id)
        wo = self.platform.pilot.workorders.get(batch["workOrderId"])
        if wo.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: work order")
        material = float(sum(float(i.get("quantity") or 0) for i in (wo.get("consumed") or []) if i.get("kind") == "lot")) if wo.get("consumed") else None
        labor_meta = self._labor_integrity(batch)
        hardware = None
        packaging = None
        cartons = [c for c in self.cartons.values() if c.get("batchId") == batch_id and c.get("state") == "ACTIVE"]
        if cartons and all(c.get("packagingQty") is not None for c in cartons):
            packaging = float(sum(float(c.get("packagingQty") or 0) for c in cartons))
        proto_unit = self.platform.prototype.units.get(batch.get("prototypeUnitId") or "")
        if proto_unit:
            counts = self.platform.prototype._bom_counts(self.platform.prototype._candidate(batch["candidateId"], tenant_id))
            hardware = float(counts.get("hardwareQty") or 0) * int(batch.get("requestedQuantity") or 1)
        sources = {
            "materialQty": "MATERIAL_LOT" if material is not None and material > 0 else "MISSING",
            "laborMinutes": labor_meta.get("source") or "MISSING",
            "hardwareQty": "BOM" if hardware is not None else "MISSING",
            "packagingQty": "PACKAGING_CHECKLIST" if packaging is not None and packaging > 0 else "MISSING",
        }
        if labor_meta.get("integrityOk") is not True:
            sources["laborMinutes"] = "DUPLICATE" if labor_meta.get("duplicateKeys") else sources["laborMinutes"]
        qty_ok = all(v not in {"MISSING", "DUPLICATE"} for v in sources.values()) and labor_meta.get("integrityOk") is True
        money = amounts or {}
        money_fields = ("materialAmount", "hardwareAmount", "laborAmount", "packagingAmount")
        money_ok = all(money.get(k) is not None for k in money_fields)
        completeness = "COMPLETE" if qty_ok and money_ok else "PARTIAL"
        if completeness == "COMPLETE" and batch.get("source") == "FIXTURE":
            completeness = "PARTIAL"
        key = f"{tenant_id}::batch-cost::{batch_id}::{batch.get('engineeringHash')}"

        def _make():
            rec = {
                "costId": new_id(),
                "tenantId": tenant_id,
                "batchId": batch_id,
                "completeness": completeness,
                "currency": currency,
                "truthLabel": batch.get("truthLabel") if completeness == "PARTIAL" else "MANUAL",
                "quantities": {"materialQty": material, "laborMinutes": labor_meta.get("minutes"), "hardwareQty": hardware, "packagingQty": packaging},
                "amounts": {k: money.get(k) for k in money_fields},
                "quantityLineage": {"ok": qty_ok, "sources": sources, "laborLineage": labor_meta, "packagingQty": packaging, "laborMinutes": labor_meta.get("minutes")},
                "estimateVsActual": {"estimated": None, "actual": None, "variance": "PARTIAL" if completeness != "COMPLETE" else "RECORDED"},
                "liveMachineControl": False,
                "idempotencyKey": key,
            }
            self.costs[rec["costId"]] = rec
            batch["costId"] = rec["costId"]
            batch["cost"] = {"completeness": completeness, "truthLabel": rec["truthLabel"], "quantityLineage": rec["quantityLineage"]}
            self.idem[key] = rec["costId"]
            self._emit(
                "pilot_batch.cost",
                tenant_id=tenant_id,
                aggregate_type="PilotBatchCost",
                aggregate_id=rec["costId"],
                actor=ident["operator"]["operatorId"],
                payload={"completeness": completeness},
                semantic_key=key,
            )
            return rec

        existing = self._lookup_idem(key)
        if existing is not None:
            existing.update(
                {
                    "completeness": completeness,
                    "quantities": {"materialQty": material, "laborMinutes": labor_meta.get("minutes"), "hardwareQty": hardware, "packagingQty": packaging},
                    "quantityLineage": {"ok": qty_ok, "sources": sources, "laborLineage": labor_meta, "packagingQty": packaging, "laborMinutes": labor_meta.get("minutes")},
                    "amounts": {k: money.get(k) for k in money_fields},
                    "truthLabel": batch.get("truthLabel") if completeness == "PARTIAL" else existing.get("truthLabel"),
                }
            )
            batch["cost"] = {"completeness": completeness, "truthLabel": existing.get("truthLabel"), "quantityLineage": existing["quantityLineage"]}
            self.persist()
            return existing
        return self._idem(key, _make)

    def record_ncr(self, unit_execution_id: str, *, tenant_id: str, operator_id: str, shift_id: str, category: str, evidence: str, root_cause: str | None = None) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        unit = self.units[unit_execution_id]
        self._require_tenant(unit, tenant_id)
        batch = self.get(unit["batchId"], tenant_id=tenant_id)
        key = f"{tenant_id}::batch-ncr::{unit_execution_id}::{category}"

        def _make():
            rec = {
                "ncrId": new_id(),
                "tenantId": tenant_id,
                "batchId": batch["batchId"],
                "unitExecutionId": unit_execution_id,
                "category": category,
                "evidence": evidence,
                "rootCause": root_cause,
                "rootCauseLabel": "MANUAL" if root_cause else "MISSING",
                "aiIsNotEngineeringFact": True,
                "engineeringHash": unit.get("engineeringHash"),
                "operatorId": ident["operator"]["operatorId"],
                "at": _now(),
                "idempotencyKey": key,
            }
            self.ncrs[rec["ncrId"]] = rec
            unit["state"] = "HOLD"
            batch["state"] = "HOLD"
            self.idem[key] = rec["ncrId"]
            self._emit(
                "pilot_batch.ncr",
                tenant_id=tenant_id,
                aggregate_type="PilotBatchNcr",
                aggregate_id=rec["ncrId"],
                actor=ident["operator"]["operatorId"],
                payload={"category": category, "unitExecutionId": unit_execution_id},
                semantic_key=key,
            )
            return rec

        return self._idem(key, _make)

    def refresh_stale(self, batch_id: str, *, tenant_id: str) -> dict[str, Any]:
        batch = self.get(batch_id, tenant_id=tenant_id)
        proto = self.platform.prototype
        if proto._lineage_stale(batch["candidateId"], tenant_id):
            batch["staleLineage"] = True
            batch["state"] = "HOLD"
            rel = self.platform.pilot.releases.releases.get(batch["releaseId"])
            if rel and rel.get("status") not in {"STALE", "SUPERSEDED", "CANCELLED"}:
                rel = dict(rel)
                rel["stale"] = True
                rel["staleReason"] = "accepted ECO invalidates batch/release/QC/packaging lineage"
                self.platform.pilot.releases.releases[batch["releaseId"]] = rel
                batch["releaseStale"] = True
            self.persist()
        return batch

    def readiness(self, batch_id: str, *, tenant_id: str) -> dict[str, Any]:
        batch = self.refresh_stale(batch_id, tenant_id=tenant_id)
        units = self.units_for(batch_id, tenant_id=tenant_id)
        cost = self.costs.get(batch.get("costId") or "")
        labor = self._labor_integrity(batch)
        sampled = [u for u in units if u.get("sampled") is not False]
        qc_ok = True
        for unit in sampled:
            if self._final_qc(unit, batch) is None:
                qc_ok = False
                break
        holds = [u for u in units if u.get("state") in {"HOLD", "QC_FAILED", "REWORK"}] or [
            n for n in self.ncrs.values() if n.get("batchId") == batch_id
        ]
        executed = [
            u
            for u in units
            if u.get("startedBy") and u.get("consumedQuantity") is not None and u.get("laborId")
        ]
        packed = [u for u in executed if u.get("cartonId")]
        cartons = [c for c in self.cartons.values() if c.get("batchId") == batch_id and c.get("state") == "ACTIVE"]
        pack_ok = (
            bool(cartons)
            and len(packed) == len(units) == len(executed)
            and all(self._carton_packaging_ok(c, batch) for c in cartons)
        )
        counts_ok = int(batch.get("requestedQuantity") or 0) == len(units) == len(executed)
        lineage_ok = not batch.get("staleLineage")
        cost_ok = bool(cost) and cost.get("completeness") == "COMPLETE" and (cost.get("quantityLineage") or {}).get("ok") is True
        fixture = batch.get("source") == "FIXTURE" or batch.get("truthLabel") == "FIXTURE"
        blockers = []
        if not lineage_ok:
            blockers.append("stale_lineage")
        if not counts_ok:
            blockers.append("count_mismatch")
        if not labor.get("integrityOk"):
            blockers.append("labor_integrity")
        if not qc_ok:
            blockers.append("qc_sample")
        if holds:
            blockers.append("unresolved_hold")
        if not pack_ok:
            blockers.append("packaging")
        if not cost_ok:
            blockers.append("cost_partial")
        if fixture:
            blockers.append("fixture_evidence")
        decision = "WAITING_HUMAN_EVIDENCE"
        if holds or not lineage_ok:
            decision = "HOLD_REWORK"
        elif not fixture and not blockers:
            decision = "READY_FOR_HUMAN_BATCH_GO_NO_GO"
        existing = next((d for d in self.decisions.values() if d.get("batchId") == batch_id), None)
        if existing and existing.get("decision") in {"HUMAN_BATCH_GO", "HUMAN_BATCH_NO_GO"}:
            decision = existing["decision"]
        return {
            "batchId": batch_id,
            "tenantId": tenant_id,
            "state": batch.get("state"),
            "decision": decision,
            "blockers": blockers,
            "requestedQuantity": batch.get("requestedQuantity"),
            "executedQuantity": len([u for u in units if u.get("state") != "PLANNED"]),
            "laborIntegrityOk": labor.get("integrityOk"),
            "qcOk": qc_ok,
            "packagingOk": pack_ok,
            "costCompleteness": (cost or {}).get("completeness") or "MISSING",
            "staleLineage": batch.get("staleLineage"),
            "physicalPilotBatchValidated": False if fixture else bool(batch.get("physicalPilotBatchValidated")),
            "liveMachineControl": False,
            "truthLabel": batch.get("truthLabel"),
            "samplingPlan": batch.get("samplingPlan"),
        }

    def record_decision(self, batch_id: str, *, tenant_id: str, operator_id: str, shift_id: str, decision: str, reason: str) -> dict[str, Any]:
        ident = self._identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
        if decision not in {"HUMAN_BATCH_GO", "HUMAN_BATCH_NO_GO"}:
            raise PilotBatchError("BLOCKED", "batch decision must be HUMAN_BATCH_GO or HUMAN_BATCH_NO_GO")
        if not reason:
            raise PilotBatchError("BLOCKED", "batch decision requires reason")
        batch = self.get(batch_id, tenant_id=tenant_id)
        key = f"{tenant_id}::batch-decision::{batch_id}::{decision}::{batch.get('engineeringHash')}"
        found = self._lookup_idem(key)
        if found is not None:
            return found
        ready = self.readiness(batch_id, tenant_id=tenant_id)
        if self._is_fixture(ident) or batch.get("source") == "FIXTURE" or batch.get("truthLabel") == "FIXTURE":
            raise PilotBatchError("BLOCKED", "fixture/mock evidence cannot become HUMAN_BATCH_GO")
        if decision == "HUMAN_BATCH_GO" and ready.get("decision") != "READY_FOR_HUMAN_BATCH_GO_NO_GO":
            raise PilotBatchError("BLOCKED", "batch is not ready for HUMAN_BATCH_GO")

        def _make():
            rec = {
                "decisionId": new_id(),
                "tenantId": tenant_id,
                "batchId": batch_id,
                "decision": decision,
                "reason": reason,
                "engineeringHash": batch.get("engineeringHash"),
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "at": _now(),
                "liveMachineControl": False,
                "globalProductionReady": False,
                "productionReady": False,
                "idempotencyKey": key,
            }
            self.decisions[rec["decisionId"]] = rec
            batch["state"] = decision
            batch["batchLaunchDecision"] = decision
            self.idem[key] = rec["decisionId"]
            self._emit(
                "pilot_batch.decision",
                tenant_id=tenant_id,
                aggregate_type="PilotBatchDecision",
                aggregate_id=rec["decisionId"],
                actor=ident["operator"]["operatorId"],
                payload={"decision": decision},
                semantic_key=key,
            )
            return rec

        return self._idem(key, _make)

    def decision_board(self, *, tenant_id: str, candidate_ids: list[str] | None = None) -> dict[str, Any]:
        rows = []
        for batch in self.batches.values():
            if batch.get("tenantId") != tenant_id:
                continue
            if candidate_ids and batch.get("candidateId") not in candidate_ids:
                continue
            rows.append(self.readiness(batch["batchId"], tenant_id=tenant_id))
        decisions = [r.get("decision") for r in rows]
        overall = "WAITING_HUMAN_EVIDENCE"
        if decisions and all(d == "HUMAN_BATCH_GO" for d in decisions):
            overall = "HUMAN_BATCH_GO"
        elif any(d == "HUMAN_BATCH_NO_GO" for d in decisions):
            overall = "HUMAN_BATCH_NO_GO"
        elif any(d == "HOLD_REWORK" for d in decisions):
            overall = "HOLD_REWORK"
        elif decisions and all(d == "READY_FOR_HUMAN_BATCH_GO_NO_GO" for d in decisions):
            overall = "READY_FOR_HUMAN_BATCH_GO_NO_GO"
        return {
            "tenantId": tenant_id,
            "rows": rows,
            "decision": overall,
            "liveMachineControl": False,
            "globalProductionReady": False,
            "physicalPilotBatchValidated": False,
        }

    def genealogy(self, batch_id: str, *, tenant_id: str) -> dict[str, Any]:
        batch = self.get(batch_id, tenant_id=tenant_id)
        units = []
        for unit in self.units_for(batch_id, tenant_id=tenant_id):
            carton = self.cartons.get(unit.get("cartonId") or "")
            units.append(
                {
                    "unitExecutionId": unit["unitExecutionId"],
                    "state": unit.get("state"),
                    "reservationIds": unit.get("reservationIds"),
                    "consumedQuantity": unit.get("consumedQuantity"),
                    "operatorId": unit.get("startedBy"),
                    "shiftId": unit.get("shiftId"),
                    "laborId": unit.get("laborId"),
                    "qcId": unit.get("qcId"),
                    "cartonId": unit.get("cartonId"),
                    "packagingQty": None if not carton else carton.get("packagingQty"),
                    "checklistId": None if not carton else carton.get("checklistId"),
                    "evidencePackageId": batch.get("evidencePackageId"),
                }
            )
        return {"batchId": batch_id, "tenantId": tenant_id, "workOrderId": batch.get("workOrderId"), "units": units}

    def canonical_authority(self, batches: list[dict[str, Any]]) -> dict[str, Any]:
        batch_rows = []
        unit_rows = []
        carton_rows = []
        labor_rows = []
        qc_rows = []
        material_rows = []
        cost_rows = []
        decision_rows = []
        for batch in batches:
            batch_rows.append(
                {
                    "batchId": batch.get("batchId"),
                    "tenantId": batch.get("tenantId"),
                    "candidateId": batch.get("candidateId"),
                    "selectionId": batch.get("selectionId"),
                    "prototypeUnitId": batch.get("prototypeUnitId"),
                    "engineeringHash": batch.get("engineeringHash"),
                    "canonicalHash": batch.get("canonicalHash"),
                    "bomHash": batch.get("bomHash"),
                    "nestingHash": batch.get("nestingHash"),
                    "rankingPolicyHash": batch.get("rankingPolicyHash"),
                    "releaseId": batch.get("releaseId"),
                    "releaseHash": batch.get("releaseHash"),
                    "workOrderId": batch.get("workOrderId"),
                    "requestedQuantity": batch.get("requestedQuantity"),
                    "source": batch.get("source"),
                    "truthLabel": batch.get("truthLabel"),
                    "state": batch.get("state"),
                }
            )
            units = self.units_for(batch["batchId"], tenant_id=batch["tenantId"])
            alloc = []
            for unit in units:
                unit_rows.append(
                    {
                        "unitExecutionId": unit.get("unitExecutionId"),
                        "tenantId": unit.get("tenantId"),
                        "batchId": unit.get("batchId"),
                        "engineeringHash": unit.get("engineeringHash"),
                        "releaseId": unit.get("releaseId") or batch.get("releaseId"),
                        "releaseHash": unit.get("releaseHash") or batch.get("releaseHash"),
                        "workOrderId": unit.get("workOrderId") or batch.get("workOrderId"),
                        "seq": unit.get("seq"),
                        "state": unit.get("state"),
                        "sampled": unit.get("sampled"),
                        "startedBy": unit.get("startedBy"),
                        "consumedQuantity": unit.get("consumedQuantity"),
                        "allocatedQuantity": unit.get("allocatedQuantity"),
                        "consumeKind": unit.get("consumeKind"),
                        "reservationIds": unit.get("reservationIds"),
                        "laborId": unit.get("laborId"),
                        "qcId": unit.get("qcId"),
                        "qcFinalId": unit.get("qcFinalId"),
                        "qcIds": unit.get("qcIds"),
                        "cartonId": unit.get("cartonId"),
                    }
                )
                if unit.get("allocatedQuantity") is not None or unit.get("consumedQuantity") is not None:
                    alloc.append({"unitExecutionId": unit.get("unitExecutionId"), "quantity": unit.get("allocatedQuantity", unit.get("consumedQuantity"))})
            wo = self.platform.pilot.workorders.get(batch.get("workOrderId")) if batch.get("workOrderId") else None
            consumed = float(sum(float(i.get("quantity") or 0) for i in ((wo or {}).get("consumed") or []) if i.get("kind") == "lot")) if wo else float(batch.get("consumedQuantity") or 0)
            material_rows.append(
                {
                    "batchId": batch.get("batchId"),
                    "tenantId": batch.get("tenantId"),
                    "workOrderId": batch.get("workOrderId"),
                    "kind": "BATCH_ALLOCATION_PROJECTION",
                    "consumedQuantity": consumed,
                    "reservationIds": batch.get("reservationIds") or (wo or {}).get("reservations"),
                    "lotIds": batch.get("lotIds") or ((wo or {}).get("lineage") or {}).get("materialLots"),
                    "unitAllocations": alloc,
                }
            )
            for carton in self.cartons.values():
                if carton.get("batchId") == batch.get("batchId"):
                    carton_rows.append(
                        {
                            "cartonId": carton.get("cartonId"),
                            "tenantId": carton.get("tenantId"),
                            "batchId": carton.get("batchId"),
                            "unitExecutionIds": carton.get("unitExecutionIds"),
                            "packagingQty": carton.get("packagingQty"),
                            "checklistId": carton.get("checklistId"),
                            "engineeringHash": carton.get("engineeringHash"),
                            "measured": carton.get("measured"),
                            "damageDefect": carton.get("damageDefect"),
                            "hardwareObserved": carton.get("hardwareObserved"),
                            "partObserved": carton.get("partObserved"),
                        }
                    )
            for row in self.labor.values():
                if row.get("batchId") == batch.get("batchId"):
                    labor_rows.append(
                        {
                            "laborId": row.get("laborId"),
                            "tenantId": row.get("tenantId"),
                            "batchId": row.get("batchId"),
                            "unitExecutionId": row.get("unitExecutionId"),
                            "minutes": row.get("minutes"),
                            "idempotencyKey": row.get("idempotencyKey"),
                            "reason": row.get("reason"),
                            "engineeringHash": row.get("engineeringHash"),
                        }
                    )
            for row in self.qc.values():
                if row.get("batchId") == batch.get("batchId"):
                    qc_rows.append(
                        {
                            "qcId": row.get("qcId"),
                            "tenantId": row.get("tenantId"),
                            "batchId": row.get("batchId"),
                            "unitExecutionId": row.get("unitExecutionId"),
                            "stage": row.get("stage"),
                            "ok": row.get("ok"),
                            "result": row.get("result"),
                            "qcPlanHash": row.get("qcPlanHash"),
                            "engineeringHash": row.get("engineeringHash"),
                            "releaseHash": row.get("releaseHash"),
                        }
                    )
            cost = self.costs.get(batch.get("costId") or "")
            if cost:
                cost_rows.append(
                    {
                        "costId": cost.get("costId"),
                        "tenantId": cost.get("tenantId"),
                        "batchId": cost.get("batchId"),
                        "completeness": cost.get("completeness"),
                        "truthLabel": cost.get("truthLabel"),
                        "quantityLineage": cost.get("quantityLineage"),
                    }
                )
            for row in self.decisions.values():
                if row.get("batchId") == batch.get("batchId"):
                    decision_rows.append(
                        {
                            "decisionId": row.get("decisionId"),
                            "tenantId": row.get("tenantId"),
                            "batchId": row.get("batchId"),
                            "decision": row.get("decision"),
                            "engineeringHash": row.get("engineeringHash"),
                        }
                    )
        return {
            "batches": batch_rows,
            "units": unit_rows,
            "cartons": carton_rows,
            "labor": labor_rows,
            "qc": qc_rows,
            "materials": material_rows,
            "costs": cost_rows,
            "decisions": decision_rows,
        }


def run_pilot_batch_scenario(plat: Any, *, tenant_a: str = "pv-a", tenant_b: str = "pv-b", evidence_commit: str | None = None) -> dict[str, Any]:
    from fox3d.prototype import run_prototype_scenario

    proto = run_prototype_scenario(plat, tenant_a=tenant_a, tenant_b=tenant_b, render=False, evidence_commit=evidence_commit)
    fixture = proto["fixture"]
    shift = proto["fixtureShift"]
    pb = plat.pilot_batch
    batches = []
    for sel in proto["selected"]:
        batch = pb.create(
            sel["candidateId"],
            tenant_id=tenant_a,
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            quantity=5,
            source="FIXTURE",
            reason="fixture-pilot-batch",
        )
        pb.release_for_manual(batch["batchId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
        pb.reserve_materials(batch["batchId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"], policy=FIXTURE_AUTO_SEED)
        units = pb.units_for(batch["batchId"], tenant_id=tenant_a)
        packed_ids = []
        for unit in units:
            pb.start_unit(unit["unitExecutionId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
            pb.consume_unit(unit["unitExecutionId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"])
            pb.record_labor(unit["unitExecutionId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"], minutes=12, reason="assembly")
            if unit.get("sampled"):
                pb.record_qc(unit["unitExecutionId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"], ok=True)
            packed_ids.append(unit["unitExecutionId"])
        pb.pack_units(
            batch["batchId"],
            tenant_id=tenant_a,
            operator_id=fixture["operatorId"],
            shift_id=shift["shiftId"],
            unit_execution_ids=packed_ids,
            measured={"cartonLengthMm": 400, "cartonWidthMm": 300, "cartonHeightMm": 200, "packedWeightKg": 8, "hardwareQty": 4, "partCount": 6, "damageDefect": "OK"},
        )
        pb.record_cost(batch["batchId"], tenant_id=tenant_a, operator_id=fixture["operatorId"], shift_id=shift["shiftId"], amounts={"materialAmount": 10, "hardwareAmount": 4, "laborAmount": 8, "packagingAmount": 2})
        batches.append(pb.get(batch["batchId"], tenant_id=tenant_a))
    live_units = [u for b in batches for u in pb.units_for(b["batchId"], tenant_id=tenant_a)]
    cartons = [c for c in pb.cartons.values() if c.get("tenantId") == tenant_a]
    board = pb.decision_board(tenant_id=tenant_a, candidate_ids=[s["candidateId"] for s in proto["selected"]])
    authority = pb.canonical_authority(batches)
    return {
        "ok": True,
        "prototype": proto,
        "selected": proto.get("selected"),
        "batches": batches,
        "units": live_units,
        "cartons": cartons,
        "board": board,
        "batchAuthority": authority,
        "batchLaunchDecision": board.get("decision"),
        "launchDecision": proto.get("launchDecision"),
        "physicalPilotBatchValidated": False,
        "physicalPrototypeValidated": False,
        "demandLabel": proto.get("demandLabel"),
        "label": "FIXTURE/REAL_LOGIC",
        "liveMachineControl": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "pilotBatchExecutionReady": "FIXTURE/REAL_LOGIC",
        "commercialLaunchGovernanceReady": "FIXTURE/REAL_LOGIC",
        "media": proto.get("media") or [],
        "fixture": fixture,
        "fixtureShift": shift,
    }
