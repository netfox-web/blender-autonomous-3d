"""Manual Work Order / shop traveler. Execution boundary, not a MES.

Binds to ManufacturingRelease.releaseHash. Reuses MaterialLot / RemnantStore.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import MaterialLotRegistry, StockShortage, atomic_write_json, normalize_status, read_json
from fox3d.journal import emit
from fox3d.mfg_release import FAMILY_STEPS
from fox3d.qc import plan_for_family, plan_hash

WO_STATES = (
    "DRAFT",
    "RELEASED_FOR_MANUAL_EXECUTION",
    "MATERIAL_RESERVED",
    "IN_PROGRESS",
    "QC_HOLD",
    "PACKING",
    "COMPLETED",
    "REJECTED",
    "CANCELLED",
)
TERMINAL = frozenset({"COMPLETED", "REJECTED", "CANCELLED"})
STRICT_STOCK = "STRICT_STOCK"
FIXTURE_AUTO_SEED = "FIXTURE_AUTO_SEED"
TRANSITIONS = {
    "DRAFT": frozenset({"RELEASED_FOR_MANUAL_EXECUTION", "CANCELLED"}),
    "RELEASED_FOR_MANUAL_EXECUTION": frozenset({"MATERIAL_RESERVED", "CANCELLED"}),
    "MATERIAL_RESERVED": frozenset({"IN_PROGRESS", "PACKING", "QC_HOLD", "CANCELLED", "REJECTED"}),
    "IN_PROGRESS": frozenset({"IN_PROGRESS", "PACKING", "QC_HOLD", "COMPLETED", "CANCELLED", "REJECTED"}),
    "QC_HOLD": frozenset({"IN_PROGRESS", "PACKING", "REJECTED", "CANCELLED", "QC_HOLD"}),
    "PACKING": frozenset({"COMPLETED", "QC_HOLD", "CANCELLED", "REJECTED", "PACKING"}),
    "COMPLETED": frozenset(),
    "REJECTED": frozenset(),
    "CANCELLED": frozenset({"CANCELLED"}),
}


def _now() -> str:
    return utcnow().isoformat()


class WorkOrderService:
    def __init__(
        self,
        *,
        lots: MaterialLotRegistry | None = None,
        remnants: Any | None = None,
        dam: Any | None = None,
        releases: Any | None = None,
        root: Path | None = None,
    ) -> None:
        self.lots = lots or MaterialLotRegistry()
        self.remnants = remnants
        self.dam = dam
        self.releases = releases
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.qc: Any | None = None
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self.orders: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, str] = {}
        self.operations: list[dict[str, Any]] = []
        self.allocation_policy = STRICT_STOCK
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "workorders.json") or {}
        self.orders = {r["workOrderId"]: r for r in payload.get("orders") or []}
        self._idem = dict(payload.get("idem") or {})
        self.operations = list(payload.get("operations") or [])

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(
            self.root / "workorders.json",
            {"orders": list(self.orders.values()), "idem": self._idem, "operations": self.operations},
        )

    def bind_qc(self, qc: Any) -> None:
        self.qc = qc

    def get(self, work_order_id: str) -> dict[str, Any]:
        return self.orders[work_order_id]

    def create(
        self,
        *,
        tenant_id: str,
        release: dict[str, Any],
        quantity: int = 1,
        batch_id: str | None = None,
        actor: str = "ops",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if release.get("status") not in {"RELEASED_FOR_MANUAL_EXECUTION", "APPROVED_FOR_MANUAL_RELEASE"}:
            raise PermissionError("work order requires a released/approved manufacturing packet")
        if release.get("stale") or release.get("status") in {"STALE", "SUPERSEDED", "CANCELLED"} or release.get("supersededBy"):
            raise PermissionError("stale/superseded release cannot open a work order")
        batch = batch_id or new_id()
        raw_key = idempotency_key or f"{release['releaseHash']}:{batch}"
        key = f"{tenant_id}::wo::{raw_key}"
        if key in self._idem:
            existing = self.orders[self._idem[key]]
            if existing.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: work order")
            return existing
        family = release.get("productFamily") or "KD_FURNITURE"
        rec = {
            "workOrderId": new_id(),
            "tenantId": tenant_id,
            "releaseId": release.get("releaseId"),
            "releaseHash": release["releaseHash"],
            "productId": release.get("productId"),
            "productVersion": release.get("productVersion"),
            "productFamily": family,
            "quantity": int(quantity),
            "batchId": batch,
            "state": "DRAFT",
            "createdBy": actor,
            "createdAt": _now(),
            "reservations": [],
            "consumed": [],
            "scrap": [],
            "recordedCut": [],
            "expectedCut": [],
            "ops": [],
            "lineage": {
                "productVersion": release.get("productVersion"),
                "releaseHash": release["releaseHash"],
                "bomHash": release.get("bomHash"),
                "materialLots": [],
                "remnants": [],
                "operators": [],
                "qc": [],
                "package": None,
            },
            "materialReserved": False,
            "liveMachineControl": False,
            "mes": False,
            "audit": [],
            "allocationPolicy": None,
        }
        snap = release.get("snapshot") or {}
        rec["qcPlan"] = list(snap.get("qcPlan") or plan_for_family(family))
        rec["qcPlanHash"] = release.get("qcPlanHash") or snap.get("qcPlanHash") or plan_hash(rec["qcPlan"])
        rec["lineage"]["qcPlanHash"] = rec["qcPlanHash"]
        rec["traveler"] = self._traveler(family)
        rec["workOrderHash"] = stable_hash({k: rec[k] for k in ("tenantId", "releaseHash", "batchId", "quantity")})
        rec["packingRequired"] = any(s["operation"] == "packaging" or s["operation"] == "packing" for s in rec["traveler"]["steps"])
        self.orders[rec["workOrderId"]] = rec
        self._idem[key] = rec["workOrderId"]
        self._audit(rec, actor=actor, from_state=None, to="DRAFT", reason="create", key=key)
        try:
            emit(
                self,
                "workorder.create",
                tenant_id=tenant_id,
                aggregate_type="WorkOrder",
                aggregate_id=rec["workOrderId"],
                actor=actor,
                payload={"releaseHash": rec["releaseHash"], "state": "DRAFT"},
                release_hash=rec["releaseHash"],
                semantic_key=key,
            )
        except Exception:
            if self.root:
                self.load()
            else:
                del self.orders[rec["workOrderId"]]
                del self._idem[key]
            raise
        return rec

    def _traveler(self, family: str) -> dict[str, Any]:
        steps = FAMILY_STEPS.get(family, ["packaging"])
        return {
            "family": family,
            "steps": [
                {
                    "seq": i + 1,
                    "operation": op,
                    "kind": "operator_instruction",
                    "machineCommand": False,
                    "liveLaser": False,
                    "liveCnc": False,
                }
                for i, op in enumerate(steps)
            ],
            "note": "operator instructions, not machine commands",
        }

    def release_for_execution(self, work_order_id: str, *, actor: str) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        self._assert_release_fresh(rec)
        if rec["state"] == "RELEASED_FOR_MANUAL_EXECUTION":
            return rec
        self._transition(rec, "RELEASED_FOR_MANUAL_EXECUTION", actor=actor, reason="release")
        rec["releasedBy"] = actor
        emit(
            self,
            "workorder.release_for_execution",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"state": rec["state"]},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::wo-release::{rec['workOrderId']}",
        )
        return rec

    def reserve_materials(
        self,
        work_order_id: str,
        *,
        actor: str,
        tenant_id: str | None = None,
        allocation_policy: str | None = None,
    ) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=tenant_id)
        self._assert_release_fresh(rec)
        if rec.get("materialReserved"):
            return rec
        policy = allocation_policy or self.allocation_policy or STRICT_STOCK
        if policy not in {STRICT_STOCK, FIXTURE_AUTO_SEED}:
            raise PermissionError(policy)
        tid = rec["tenantId"]
        release = self._release_of(rec)
        nesting = (release.get("snapshot") or {}).get("nesting") or {}
        sheet_n = max(int(nesting.get("sheetCount") or 1), 1) * int(rec["quantity"])
        material = str(nesting.get("sheetSku") or "PB_18_WHITE")
        thickness = float(nesting.get("thickness") or 18)
        grain = nesting.get("grain") or nesting.get("grainConstraint")
        if not isinstance(grain, str) or grain in {"any", "none", ""}:
            grain = None
        sheet_mm = nesting.get("sheetMm") or []
        length = float(sheet_mm[0]) if len(sheet_mm) >= 1 and sheet_mm[0] is not None else None
        width = float(sheet_mm[1]) if len(sheet_mm) >= 2 and sheet_mm[1] is not None else None
        lot_reservations: list[dict[str, Any]] = []
        remaining = sheet_n
        if policy == STRICT_STOCK:
            try:
                lot_reservations = self.lots.allocate_requirement(
                    tenant_id=tid,
                    work_order_id=rec["workOrderId"],
                    quantity=sheet_n,
                    material=material,
                    thickness=thickness,
                    grain=grain,
                    length=length,
                    width=width,
                )
                remaining = 0
            except StockShortage as exc:
                rec["shortage"] = {**exc.payload, "workOrderId": rec["workOrderId"], "policy": STRICT_STOCK}
                raise
        else:
            lots = [
                l
                for l in self.lots.list(tenant_id=tid, allocatable=True)
                if self.lots.lot_compatible(l, material=material, thickness=thickness, grain=grain, length=length, width=width)
            ]
            remaining = sheet_n
            for lot in lots:
                avail = int(lot.get("remainingSheets") or 0)
                if avail <= 0 or remaining <= 0:
                    continue
                take = min(remaining, avail)
                item = self.lots.reserve_sheets(
                    lot["lotId"], tenant_id=tid, work_order_id=rec["workOrderId"], quantity=take
                )
                lot_reservations.append(
                    {
                        "kind": "lot",
                        "lotId": lot["lotId"],
                        "quantity": take,
                        "reservationId": item["reservationId"],
                        "state": "RESERVED",
                    }
                )
                remaining -= take
            if remaining > 0:
                extra = self.lots.create(
                    tenant_id=tid,
                    material=material,
                    thickness=thickness,
                    sheet_count=remaining,
                    length=length if length is not None else 2440,
                    width=width if width is not None else 1220,
                    grain=str(grain or "length"),
                )
                extra["truthLabel"] = "FIXTURE"
                extra["allocationPolicy"] = FIXTURE_AUTO_SEED
                item = self.lots.reserve_sheets(
                    extra["lotId"], tenant_id=tid, work_order_id=rec["workOrderId"], quantity=remaining
                )
                lot_reservations.append(
                    {
                        "kind": "lot",
                        "lotId": extra["lotId"],
                        "quantity": remaining,
                        "reservationId": item["reservationId"],
                        "state": "RESERVED",
                        "truthLabel": "FIXTURE",
                    }
                )
                remaining = 0
        remnant_ids: list[str] = []
        if self.remnants is not None:
            for rem in list(self.remnants.available(tenant_id=tid)):
                try:
                    self.remnants.reserve(rem["remnantId"], by=rec["workOrderId"], tenant_id=tid, version=rem.get("version"))
                    remnant_ids.append(rem["remnantId"])
                except PermissionError:
                    continue
        rec["reservations"] = lot_reservations + [{"kind": "remnant", "remnantId": rid} for rid in remnant_ids]
        rec["lineage"]["materialLots"] = sorted({item["lotId"] for item in lot_reservations})
        rec["lineage"]["remnants"] = remnant_ids
        rec["materialReserved"] = True
        rec["allocationPolicy"] = policy
        rec["truthLabel"] = "FIXTURE" if policy == FIXTURE_AUTO_SEED else "REAL"
        rec["reservedBy"] = actor
        rec["reservedAt"] = _now()
        self._transition(rec, "MATERIAL_RESERVED", actor=actor, reason=f"reserve:{policy}")
        emit(
            self,
            "workorder.reserve",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"policy": policy, "lots": rec["lineage"]["materialLots"]},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::wo-reserve::{rec['workOrderId']}",
        )
        return rec

    def start_operation(
        self,
        work_order_id: str,
        operation: str,
        *,
        actor: str,
        notes: str = "",
        dam_asset_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=tenant_id)
        self._assert_release_fresh(rec, allow_bound_finish=True)
        if rec["state"] in TERMINAL:
            raise PermissionError(rec["state"])
        if rec["state"] in {"DRAFT"}:
            raise PermissionError("not released")
        if not rec.get("materialReserved"):
            raise PermissionError("operation requires material reservation")
        for existing in rec["ops"]:
            if existing.get("operation") == operation and existing.get("status") in {"STARTED", "COMPLETED"}:
                return existing
        if rec["state"] in {"MATERIAL_RESERVED", "QC_HOLD", "RELEASED_FOR_MANUAL_EXECUTION"}:
            self._transition(rec, "IN_PROGRESS", actor=actor, reason=f"start:{operation}")
        op = {
            "opId": new_id(),
            "workOrderId": rec["workOrderId"],
            "operation": operation,
            "operatorId": actor,
            "startedAt": _now(),
            "completedAt": None,
            "notes": notes,
            "damAssetId": dam_asset_id,
            "status": "STARTED",
            "sensorEvidence": False,
        }
        if dam_asset_id and self.dam is not None:
            self.dam.get(dam_asset_id, tenant_id=rec["tenantId"])
        rec["ops"].append(op)
        rec["lineage"]["operators"] = sorted(set(list(rec["lineage"].get("operators") or []) + [actor]))
        self.operations.append(op)
        emit(
            self,
            "workorder.operation_start",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"opId": op["opId"], "operation": operation},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::op-start::{rec['workOrderId']}::{operation}",
        )
        return op

    def complete_operation(self, work_order_id: str, op_id: str, *, actor: str, notes: str = "") -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        op = next(o for o in rec["ops"] if o["opId"] == op_id)
        if op.get("status") == "COMPLETED":
            return op
        op["completedAt"] = _now()
        op["status"] = "COMPLETED"
        if notes:
            op["notes"] = (op.get("notes") or "") + (" " + notes if op.get("notes") else notes)
        op["completedBy"] = actor
        emit(
            self,
            "workorder.operation_complete",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"opId": op_id, "operation": op.get("operation")},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::op-complete::{op_id}",
        )
        return op

    def record_cut_outcome(
        self,
        work_order_id: str,
        *,
        expected_qty: float,
        recorded_qty: float,
        remnant_rects: list[dict[str, Any]] | None = None,
        scrap_area_mm2: float = 0.0,
        actor: str,
    ) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        outcome = {
            "expectedQty": float(expected_qty),
            "recordedQty": float(recorded_qty),
            "scrapAreaMm2": float(scrap_area_mm2),
            "actor": actor,
            "at": _now(),
        }
        rec["expectedCut"].append({"qty": expected_qty})
        rec["recordedCut"].append(outcome)
        created = []
        if self.remnants is not None and remnant_rects:
            nest_like = {
                "candidateRemnants": remnant_rects,
                "grainConstraint": "length",
            }
            created = self.remnants.add_from_nesting(
                nest_like,
                material="WOOD_WHITE",
                thickness=18,
                source_run=rec["workOrderId"],
                tenant_id=rec["tenantId"],
            )
            rec["lineage"]["remnants"] = list(rec["lineage"].get("remnants") or []) + [r["remnantId"] for r in created]
        rec["scrap"].append({"areaMm2": scrap_area_mm2, "kind": "trueScrap", "source": "MANUAL"})
        return {"outcome": outcome, "remnants": created, "expectedVsRecordedSeparated": True}

    def consume_reserved(self, work_order_id: str, *, actor: str) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        if rec.get("consumedFlag"):
            return rec
        for item in rec.get("reservations") or []:
            if item.get("kind") == "lot":
                self.lots.consume_reservation(
                    item["reservationId"], tenant_id=rec["tenantId"], work_order_id=rec["workOrderId"]
                )
                item["state"] = "CONSUMED"
                rec["consumed"].append(item)
            elif item.get("kind") == "remnant" and self.remnants is not None:
                rem = self.remnants.get(item["remnantId"], tenant_id=rec["tenantId"])
                self.remnants.consume(
                    item["remnantId"],
                    by=rec["workOrderId"],
                    tenant_id=rec["tenantId"],
                    version=rem.get("version"),
                    lease_token=rem.get("leaseToken"),
                )
                rec["consumed"].append(item)
        rec["consumedFlag"] = True
        rec["consumedBy"] = actor
        emit(
            self,
            "workorder.consume",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"consumed": True},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::wo-consume::{rec['workOrderId']}",
        )
        return rec

    def consume_one(self, work_order_id: str, reservation_id: str, *, actor: str) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        item = next((i for i in rec.get("reservations") or [] if i.get("reservationId") == reservation_id), None)
        if item is None or item.get("kind") != "lot":
            raise KeyError(reservation_id)
        if item.get("state") == "CONSUMED":
            return rec
        self.lots.consume_reservation(reservation_id, tenant_id=rec["tenantId"], work_order_id=rec["workOrderId"])
        item["state"] = "CONSUMED"
        rec["consumed"].append(item)
        rec["partialConsumed"] = True
        rec["consumedBy"] = actor
        return rec

    def set_packing(self, work_order_id: str, carton_ids: list[str]) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        rec["lineage"]["package"] = list(carton_ids)
        rec["cartonIds"] = list(carton_ids)
        if rec["state"] not in TERMINAL:
            self._transition(rec, "PACKING", actor="ops", reason="packing")
        self.persist()
        return rec

    def complete(self, work_order_id: str, *, actor: str, qc_ok: bool = True) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        self._assert_release_fresh(rec, allow_bound_finish=True)
        if rec["state"] == "COMPLETED":
            return rec
        if rec["state"] in {"REJECTED"}:
            raise PermissionError("cannot complete rejected work order")
        open_ops = [o for o in rec.get("ops") or [] if o.get("status") != "COMPLETED"]
        needed = [s["operation"] for s in rec.get("traveler", {}).get("steps") or []]
        done = {o.get("operation") for o in rec.get("ops") or [] if o.get("status") == "COMPLETED"}
        missing_ops = [op for op in needed if op not in done]
        if rec.get("ops"):
            if open_ops:
                raise PermissionError("open operation blocks completion")
            if missing_ops:
                raise PermissionError(f"required operations incomplete: {missing_ops}")
        gate = self._authoritative_qc_gate(rec)
        rec["qcGate"] = gate
        if rec["state"] == "QC_HOLD" and not gate.get("ok"):
            raise PermissionError("required QC missing or failed; completion blocked")
        if not gate.get("ok"):
            if rec["state"] != "QC_HOLD":
                self._transition(rec, "QC_HOLD", actor=actor, reason="qc-gate")
            raise PermissionError("required QC missing or failed; completion blocked")
        if not qc_ok:
            if rec["state"] != "QC_HOLD":
                self._transition(rec, "QC_HOLD", actor=actor, reason="caller-qc-flag")
            raise PermissionError("required QC missing or failed; completion blocked")
        if missing_ops:
            raise PermissionError(f"required operations incomplete: {missing_ops}")
        if rec.get("packingRequired") and not rec.get("cartonIds"):
            raise PermissionError("packing required before completion")
        rec["completedBy"] = actor
        rec["completedAt"] = _now()
        self._transition(rec, "COMPLETED", actor=actor, reason="complete")
        emit(
            self,
            "workorder.complete",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"state": "COMPLETED"},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::wo-complete::{rec['workOrderId']}",
        )
        return rec

    def _authoritative_qc_gate(self, rec: dict[str, Any]) -> dict[str, Any]:
        if self.qc is None:
            return {"ok": False, "reason": "NO_QC_AUTHORITY", "missing": ["*"], "failed": []}
        result = self.qc.required_final_ok(
            rec["workOrderId"], rec["productFamily"], tenant_id=rec.get("tenantId"), plan=rec.get("qcPlan")
        )
        result = dict(result)
        result["reason"] = None if result.get("ok") else "REQUIRED_FINAL_QC"
        rec["qcGateHash"] = stable_hash(result)
        return result

    def reject(self, work_order_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        rec["state"] = "REJECTED"
        rec["rejectedBy"] = actor
        rec["rejectReason"] = reason
        return rec

    def cancel(self, work_order_id: str, *, actor: str) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        if rec["state"] == "CANCELLED":
            return rec
        if rec["state"] in {"COMPLETED", "REJECTED"}:
            raise PermissionError("cannot cancel completed")
        if rec.get("consumedFlag"):
            rec["consumedFrozen"] = True
        for item in rec.get("reservations") or []:
            if item.get("kind") == "lot" and item.get("state") == "RESERVED":
                try:
                    self.lots.release_reservation(
                        item["reservationId"], tenant_id=rec["tenantId"], work_order_id=rec["workOrderId"]
                    )
                    item["state"] = "RELEASED"
                except (KeyError, PermissionError):
                    continue
            elif item.get("kind") == "remnant" and self.remnants is not None:
                try:
                    rem = self.remnants.get(item["remnantId"], tenant_id=rec["tenantId"])
                    if normalize_status(rem.get("status")) == "reserved" and rem.get("reservedBy") == rec["workOrderId"]:
                        rem["status"] = "available"
                        rem["reservedBy"] = None
                        rem["leaseToken"] = None
                        rem["version"] = int(rem.get("version") or 1) + 1
                        self.remnants.store.put(rem)
                except (KeyError, PermissionError):
                    continue
        rec["cancelledBy"] = actor
        rec["cancelledAt"] = _now()
        rec["materialReserved"] = False
        self._transition(rec, "CANCELLED", actor=actor, reason="cancel")
        emit(
            self,
            "workorder.cancel",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"state": "CANCELLED"},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::wo-cancel::{rec['workOrderId']}",
        )
        return rec

    def rework(self, work_order_id: str, *, actor: str, reason: str = "rework") -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        if rec.get("rework") and rec["state"] == "IN_PROGRESS":
            return rec
        if rec["state"] == "QC_HOLD":
            self._transition(rec, "IN_PROGRESS", actor=actor, reason=reason)
        elif rec["state"] != "IN_PROGRESS":
            raise PermissionError(rec["state"])
        rec["rework"] = True
        rec["reworkBy"] = actor
        emit(
            self,
            "workorder.rework",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"reason": reason},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::wo-rework::{rec['workOrderId']}:{reason}",
        )
        return rec

    def _require(self, work_order_id: str, tenant_id: str | None) -> dict[str, Any]:
        rec = self.orders[work_order_id]
        if tenant_id is not None and rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: work order")
        return rec

    def _release_of(self, rec: dict[str, Any]) -> dict[str, Any]:
        if self.releases is None:
            return {"snapshot": {}, "status": "RELEASED_FOR_MANUAL_EXECUTION", "releaseHash": rec["releaseHash"]}
        rel = self.releases.get(rec["releaseId"])
        return rel

    def _assert_release_fresh(self, rec: dict[str, Any], *, allow_bound_finish: bool = False) -> None:
        if self.releases is None:
            return
        rel = self.releases.get(rec["releaseId"])
        if rel.get("releaseHash") != rec.get("releaseHash"):
            raise PermissionError("work order releaseHash mismatch")
        stale = bool(rel.get("stale") or rel.get("status") in {"STALE", "SUPERSEDED"})
        if stale and allow_bound_finish and rec["state"] in {"MATERIAL_RESERVED", "IN_PROGRESS", "PACKING", "QC_HOLD"}:
            rec["boundToOriginalRelease"] = True
            rec["staleReleaseNoted"] = True
            return
        if stale:
            raise PermissionError("stale release cannot progress")

    def _transition(self, rec: dict[str, Any], to: str, *, actor: str, reason: str, key: str | None = None) -> None:
        frm = rec.get("state")
        allowed = TRANSITIONS.get(frm, frozenset())
        if to not in allowed and frm != to:
            raise PermissionError(f"illegal transition {frm}->{to}")
        rec["state"] = to
        self._audit(rec, actor=actor, from_state=frm, to=to, reason=reason, key=key)

    def _audit(self, rec: dict[str, Any], *, actor: str, from_state: str | None, to: str, reason: str, key: str | None = None) -> None:
        ev = {
            "actor": actor,
            "at": _now(),
            "from": from_state,
            "to": to,
            "reason": reason,
            "idempotencyKey": key,
        }
        ev["hash"] = stable_hash(ev)
        rec.setdefault("audit", []).append(ev)
