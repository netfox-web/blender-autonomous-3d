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
    if len(batches) < 4:
        failures.append("batches_4")
    if len(units) < 20:
        failures.append("units_20")
    if result.get("physicalPilotBatchValidated") is True:
        failures.append("fixture_physical_batch")
    if result.get("label") in {"FIXTURE", "FIXTURE/REAL_LOGIC"} and result.get("physicalPilotBatchValidated") is True:
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
    if len(batch_ids) != len(set(batch_ids)):
        failures.append("duplicate_batch_id")
    unit_ids = [u.get("unitExecutionId") for u in units if u.get("unitExecutionId")]
    if len(unit_ids) != len(set(unit_ids)):
        failures.append("duplicate_unit_execution_id")
    authority = result.get("batchAuthority") if isinstance(result.get("batchAuthority"), dict) else {}
    auth_batches = [r for r in (authority.get("batches") or []) if isinstance(r, dict)]
    auth_units = [r for r in (authority.get("units") or []) if isinstance(r, dict)]
    if batches and not auth_batches:
        failures.append("batch_authority_missing")
    auth_batch_ids = {r.get("batchId") for r in auth_batches if r.get("batchId")}
    if set(batch_ids) - auth_batch_ids:
        failures.append("batch_authority_id_mismatch")
    auth_unit_ids = {r.get("unitExecutionId") for r in auth_units if r.get("unitExecutionId")}
    if set(unit_ids) - auth_unit_ids:
        failures.append("unit_authority_id_mismatch")
    for batch in batches:
        if batch.get("truthLabel") == "FIXTURE" and batch.get("state") == "HUMAN_BATCH_GO":
            failures.append("fixture_batch_go")
        if batch.get("liveMachineControl") is True:
            failures.append("liveMachineControl")
        for key in ("engineeringHash", "canonicalHash", "bomHash", "nestingHash", "rankingPolicyHash", "tenantId"):
            if not batch.get(key):
                failures.append(f"batch_{key}_missing")
        cost = batch.get("cost") if isinstance(batch.get("cost"), dict) else {}
        if cost.get("completeness") == "COMPLETE" and cost.get("truthLabel") in {None, "PARTIAL", "FIXTURE"}:
            failures.append("cost_complete_incorrect")
        if cost.get("completeness") == "COMPLETE" and not (cost.get("quantityLineage") or {}).get("ok"):
            failures.append("cost_complete_without_qty")
    board = result.get("board") if isinstance(result.get("board"), dict) else {}
    if (board.get("decision") or launch) == "HUMAN_BATCH_GO" and result.get("label") in {"FIXTURE", "FIXTURE/REAL_LOGIC"}:
        failures.append("fixture_batch_go")
    cartons = [c for c in (result.get("cartons") or []) if isinstance(c, dict)]
    seen_units: set[str] = set()
    for carton in cartons:
        for uid in carton.get("unitExecutionIds") or []:
            if uid in seen_units:
                failures.append("duplicate_unit_carton")
            seen_units.add(str(uid))
        if carton.get("tenantId") and batches and carton.get("tenantId") != batches[0].get("tenantId") and carton.get("batchId") not in set(batch_ids):
            failures.append("carton_cross_batch")
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
        unit["reservationIds"] = list(batch.get("reservationIds") or [])
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
        key = f"{tenant_id}::batch-qc::{unit_execution_id}::{stage}"
        if unit.get("qcId") and key in self.idem:
            return self.qc[unit["qcId"]]

        def _make():
            rec = {
                "qcId": new_id(),
                "tenantId": tenant_id,
                "batchId": batch["batchId"],
                "unitExecutionId": unit_execution_id,
                "workOrderId": batch["workOrderId"],
                "engineeringHash": unit.get("engineeringHash"),
                "releaseHash": batch.get("releaseHash"),
                "qcPlanHash": (self.platform.pilot.workorders.get(batch["workOrderId"]) or {}).get("qcPlanHash"),
                "stage": stage,
                "ok": bool(ok),
                "result": "PASS" if ok else "FAIL",
                "sampled": True,
                "source": "TEST_DATA" if batch.get("source") == "FIXTURE" else "MANUAL",
                "operatorId": ident["operator"]["operatorId"],
                "shiftId": ident["shift"]["shiftId"],
                "at": _now(),
                "idempotencyKey": key,
            }
            self.qc[rec["qcId"]] = rec
            unit["qcId"] = rec["qcId"]
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
            if unit.get("cartonId"):
                other = self.cartons.get(unit["cartonId"]) or {}
                if other and other.get("state") != "CANCELLED":
                    raise PilotBatchError("BLOCKED", "same unit assigned to two active cartons")
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
        rec = {
            "cartonId": new_id(),
            "tenantId": tenant_id,
            "batchId": batch_id,
            "workOrderId": batch.get("workOrderId"),
            "unitExecutionIds": ids,
            "engineeringHash": batch.get("engineeringHash"),
            "checklistId": (pack or {}).get("checklistId") or checklist_id,
            "packagingQty": qty,
            "measured": {
                "lengthMm": measured.get("lengthMm") or measured.get("cartonLengthMm"),
                "widthMm": measured.get("widthMm") or measured.get("cartonWidthMm"),
                "heightMm": measured.get("heightMm") or measured.get("cartonHeightMm"),
                "weightKg": measured.get("weightKg") or measured.get("packedWeightKg"),
            },
            "hardwareExpected": (self.platform.prototype._bom_counts(self.platform.prototype._candidate(batch["candidateId"], tenant_id))).get("hardwareQty"),
            "hardwareObserved": measured.get("hardwareQty"),
            "partExpected": (self.platform.prototype._bom_counts(self.platform.prototype._candidate(batch["candidateId"], tenant_id))).get("partCount"),
            "partObserved": measured.get("partCount"),
            "damageDefect": measured.get("damageDefect") or "OK",
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
        ok = bool(rows) and not dups and len(ids) == len(set(ids))
        minutes = float(sum(float(r.get("minutes") or 0) for r in rows)) if ok else None
        return {
            "ok": ok,
            "integrityOk": ok,
            "laborIds": ids,
            "semanticKeys": [labor_semantic_key(r) for r in rows],
            "minutes": minutes,
            "duplicateKeys": dups,
            "source": "LABOR_RECORD" if ok else ("DUPLICATE" if dups else "MISSING"),
        }

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
        sampled = [u for u in units if u.get("sampled")]
        sampled_qc = [self.qc.get(u.get("qcId") or "") for u in sampled]
        qc_ok = all(isinstance(r, dict) and r.get("ok") is True for r in sampled_qc) and all(u.get("qcId") for u in sampled)
        holds = [u for u in units if u.get("state") in {"HOLD", "QC_FAILED"}] or [n for n in self.ncrs.values() if n.get("batchId") == batch_id]
        packed = [u for u in units if u.get("cartonId")]
        cartons = [c for c in self.cartons.values() if c.get("batchId") == batch_id and c.get("state") == "ACTIVE"]
        pack_ok = bool(cartons) and len(packed) == len(units) and all(c.get("packagingQty") for c in cartons)
        counts_ok = int(batch.get("requestedQuantity") or 0) == len(units)
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
        ready = self.readiness(batch_id, tenant_id=tenant_id)
        if self._is_fixture(ident) or batch.get("source") == "FIXTURE" or batch.get("truthLabel") == "FIXTURE":
            raise PilotBatchError("BLOCKED", "fixture/mock evidence cannot become HUMAN_BATCH_GO")
        if decision == "HUMAN_BATCH_GO" and ready.get("decision") != "READY_FOR_HUMAN_BATCH_GO_NO_GO":
            raise PilotBatchError("BLOCKED", "batch is not ready for HUMAN_BATCH_GO")
        key = f"{tenant_id}::batch-decision::{batch_id}::{decision}::{batch.get('engineeringHash')}"

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
        for batch in batches:
            batch_rows.append(
                {
                    "batchId": batch.get("batchId"),
                    "tenantId": batch.get("tenantId"),
                    "candidateId": batch.get("candidateId"),
                    "engineeringHash": batch.get("engineeringHash"),
                    "requestedQuantity": batch.get("requestedQuantity"),
                    "workOrderId": batch.get("workOrderId"),
                    "releaseHash": batch.get("releaseHash"),
                    "source": batch.get("source"),
                    "truthLabel": batch.get("truthLabel"),
                    "state": batch.get("state"),
                }
            )
            for unit in self.units_for(batch["batchId"], tenant_id=batch["tenantId"]):
                unit_rows.append(
                    {
                        "unitExecutionId": unit.get("unitExecutionId"),
                        "tenantId": unit.get("tenantId"),
                        "batchId": unit.get("batchId"),
                        "engineeringHash": unit.get("engineeringHash"),
                        "state": unit.get("state"),
                        "consumedQuantity": unit.get("consumedQuantity"),
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
                        }
                    )
            for row in self.labor.values():
                if row.get("batchId") == batch.get("batchId"):
                    labor_rows.append(
                        {
                            "laborId": row.get("laborId"),
                            "tenantId": row.get("tenantId"),
                            "unitExecutionId": row.get("unitExecutionId"),
                            "minutes": row.get("minutes"),
                            "idempotencyKey": row.get("idempotencyKey"),
                            "reason": row.get("reason"),
                        }
                    )
        return {"batches": batch_rows, "units": unit_rows, "cartons": carton_rows, "labor": labor_rows}


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
