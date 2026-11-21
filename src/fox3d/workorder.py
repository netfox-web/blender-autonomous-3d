"""Manual Work Order / shop traveler. Execution boundary, not a MES.

Binds to ManufacturingRelease.releaseHash. Reuses MaterialLot / RemnantStore.
"""

from __future__ import annotations

import threading
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import MaterialLotRegistry, StockShortage, atomic_write_json, normalize_status, read_json
from fox3d.journal import emit
from fox3d.mfg_release import FAMILY_STEPS
from fox3d.operator import require_confirm
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
PACKING_MISMATCH = "PACKING_MISMATCH"
PACKING_MISMATCH_SOURCE = "CARTON_MEASURED"
FIXTURE_AUTO_SEED = "FIXTURE_AUTO_SEED"
TRANSITIONS = {
    "DRAFT": frozenset({"RELEASED_FOR_MANUAL_EXECUTION", "CANCELLED", "REJECTED"}),
    "RELEASED_FOR_MANUAL_EXECUTION": frozenset({"MATERIAL_RESERVED", "CANCELLED", "REJECTED"}),
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


def _elapsed_minutes(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    a = datetime.fromisoformat(str(start))
    b = datetime.fromisoformat(str(end))
    return max((b - a).total_seconds() / 60.0, 0.0)


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
        self.dispatcher: Any | None = None
        self.qc: Any | None = None
        self.logistics: Any | None = None
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self.orders: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, str] = {}
        self.operations: list[dict[str, Any]] = []
        self.allocation_policy = STRICT_STOCK
        self._lock = threading.RLock()
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
            "holds": [],
            "reworkHistory": [],
            "remnantDispositions": [],
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

    def _remnant_transaction(self, tenant_id: str) -> Any:
        if self.remnants is None:
            return nullcontext()
        tx = getattr(self.remnants, "_transaction", None)
        if callable(tx):
            try:
                return tx(tenant_id=tenant_id)
            except TypeError:
                return tx()
        store_tx = getattr(getattr(self.remnants, "store", None), "transaction", None)
        if callable(store_tx):
            try:
                return store_tx(tenant_id=tenant_id)
            except TypeError:
                return store_tx()
        return nullcontext()

    def reserve_materials(
        self,
        work_order_id: str,
        *,
        actor: str,
        tenant_id: str | None = None,
        allocation_policy: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
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
                with self.lots._transaction():
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
                reserve_batch = getattr(self.remnants, "reserve_available", None)
                if callable(reserve_batch):
                    reserved_remnants = reserve_batch(by=rec["workOrderId"], tenant_id=tid)
                    remnant_ids = [r["remnantId"] for r in reserved_remnants]
                else:
                    with self._remnant_transaction(tid):
                        for rem in list(self.remnants.available(tenant_id=tid)):
                            try:
                                self.remnants.reserve(
                                    rem["remnantId"], by=rec["workOrderId"], tenant_id=tid, version=rem.get("version")
                                )
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
        operator_id: str | None = None,
        shift_id: str | None = None,
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
            "operatorId": operator_id or actor,
            "shiftId": shift_id,
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
        op["labor"] = {"segments": [{"start": op["startedAt"], "end": None, "kind": "manual"}], "corrections": [], "paused": False}
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

    def complete_operation(
        self,
        work_order_id: str,
        op_id: str,
        *,
        actor: str,
        notes: str = "",
        operator_id: str | None = None,
        shift_id: str | None = None,
    ) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        op = next(o for o in rec["ops"] if o["opId"] == op_id)
        if op.get("status") == "COMPLETED":
            return op
        if rec["state"] in {"REJECTED", "CANCELLED"}:
            raise PermissionError(f"cannot complete operation on {rec['state']} work order")
        op["completedAt"] = _now()
        op["status"] = "COMPLETED"
        if notes:
            op["notes"] = (op.get("notes") or "") + (" " + notes if op.get("notes") else notes)
        op["completedBy"] = actor
        if operator_id:
            op["completedOperatorId"] = operator_id
        if shift_id:
            op["completedShiftId"] = shift_id
        labor = op.setdefault("labor", {"segments": [], "corrections": [], "paused": False})
        segs = labor.setdefault("segments", [])
        if segs and segs[-1].get("end") is None:
            segs[-1]["end"] = op["completedAt"]
        labor["paused"] = False
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
        with self._lock:
            rec = self._require(work_order_id, tenant_id=None)
            if rec.get("consumedFlag"):
                return rec
            reservations = rec.get("reservations") or []
            has_remnants = self.remnants is not None and any(item.get("kind") == "remnant" for item in reservations)
            with self._remnant_transaction(rec["tenantId"]) if has_remnants else nullcontext():
                for item in reservations:
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
        with self._lock, self.logistics._lock if self.logistics is not None else nullcontext():
            rec = self._require(work_order_id, tenant_id=None)
            ids = list(carton_ids)
            if (
                rec.get("cartonIds") == ids
                and rec.get("lineage", {}).get("package") == ids
                and (rec["state"] == "PACKING" or rec["state"] in TERMINAL)
            ):
                return rec
            self._transition(rec, "PACKING", actor="ops", reason="packing")
            rec["lineage"]["package"] = ids
            rec["cartonIds"] = ids
            self.persist()
            return rec

    def complete(self, work_order_id: str, *, actor: str, qc_ok: bool = True) -> dict[str, Any]:
        with self._lock, self.logistics._lock if self.logistics is not None else nullcontext():
            if self.qc is not None:
                self.qc.recover_pending()
            return self._complete_locked(work_order_id, actor=actor, qc_ok=qc_ok)

    def _complete_locked(self, work_order_id: str, *, actor: str, qc_ok: bool) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        self._assert_release_fresh(rec, allow_bound_finish=True)
        if rec["state"] == "COMPLETED":
            return rec
        if rec["state"] in {"REJECTED", "CANCELLED"}:
            raise PermissionError(f"cannot complete {rec['state'].lower()} work order")
        open_holds = [h for h in rec.get("holds") or [] if h.get("open") and h.get("blocking")]
        if any(h.get("reason") == PACKING_MISMATCH for h in open_holds):
            raise PermissionError("尺寸不符待人工確認 (mismatchHold)")
        if open_holds:
            raise PermissionError("blocking hold prevents completion")
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
        if self.logistics is not None:
            sig = self._packing_mismatch_signature(rec)
            if sig is not None and not self._packing_mismatch_resolved(rec, sig):
                self.sync_packing_mismatch(work_order_id, actor=actor)
                raise PermissionError("尺寸不符待人工確認 (mismatchHold)")
        if rec.get("mismatchHold"):
            raise PermissionError("尺寸不符待人工確認 (mismatchHold)")
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

    def _packing_mismatch_signature(self, rec: dict[str, Any]) -> str | None:
        """Hash of the currently out-of-tolerance cartons (id + measurement seq), or None."""
        if self.logistics is None:
            return None
        with self.logistics._lock:
            rows = sorted(
                [str(c.get("cartonId")), int(c.get("measureSeq") or 0)]
                for c in list(self.logistics.cartons.values())
                if c.get("workOrderId") == rec["workOrderId"]
                and c.get("tenantId") == rec.get("tenantId")
                and bool(c.get("mismatch"))
            )
        return stable_hash(rows) if rows else None

    @staticmethod
    def _packing_mismatch_resolved(rec: dict[str, Any], sig: str) -> bool:
        """A closed PACKING_MISMATCH hold covers this mismatch (manual holds carry no signature)."""
        return any(
            h.get("reason") == PACKING_MISMATCH
            and not h.get("open")
            and h.get("mismatchSignature") in (None, sig)
            for h in rec.get("holds") or []
        )

    def sync_packing_mismatch(self, work_order_id: str, *, actor: str) -> bool:
        """Open (or retarget) one blocking PACKING_MISMATCH hold while cartons are out of tolerance.

        Returns the work order ``mismatchHold`` flag: an open PACKING_MISMATCH hold exists, or a
        carton is out of tolerance and no closed hold covers that measurement.
        """
        with self._lock, self.logistics._lock if self.logistics is not None else nullcontext():
            rec = self._require(work_order_id, tenant_id=None)
            sig = self._packing_mismatch_signature(rec)
            holds = rec.setdefault("holds", [])
            auto_open = [
                h for h in holds if h.get("open") and h.get("reason") == PACKING_MISMATCH and h.get("source") == PACKING_MISMATCH_SOURCE
            ]
            if sig is not None and not any(
                h.get("reason") == PACKING_MISMATCH and h.get("mismatchSignature") == sig for h in holds
            ):
                if auto_open:
                    auto_open[0]["mismatchSignature"] = sig
                elif rec["state"] not in TERMINAL:
                    h = self.hold(work_order_id, actor=actor, reason=PACKING_MISMATCH, blocking=True)
                    h["source"] = PACKING_MISMATCH_SOURCE
                    h["mismatchSignature"] = sig
            elif sig is None:
                # Re-measured within tolerance: close only holds this sync opened itself.
                for h in auto_open:
                    self.resolve_hold(work_order_id, h["holdId"], actor=actor)
            open_pm = any(h.get("open") and h.get("reason") == PACKING_MISMATCH for h in holds)
            flag = open_pm or (sig is not None and not self._packing_mismatch_resolved(rec, sig))
            rec["mismatchHold"] = flag
            self.persist()
            return flag

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
        # Same lock as dispatch / ack / start / complete so a lease cannot be
        # finished, or a station claimed, after the work order is rejected.
        with (
            self.dispatcher._lock if self.dispatcher is not None else nullcontext(),
            self._lock,
            self.logistics._lock if self.logistics is not None else nullcontext(),
        ):
            rec = self._require(work_order_id, tenant_id=None)
            if rec["state"] in TERMINAL:
                raise PermissionError("cannot reject terminal work order")
            self._release_unconsumed(rec)
            if self.dispatcher is not None:
                self.dispatcher.cancel_workorder(work_order_id, tenant_id=rec["tenantId"], actor=actor)
            rec["rejectedBy"] = actor
            rec["rejectReason"] = reason
            self._transition(rec, "REJECTED", actor=actor, reason=reason)
            emit(
                self, "workorder.reject", tenant_id=rec["tenantId"], aggregate_type="WorkOrder",
                aggregate_id=work_order_id, actor=actor, payload={"state": "REJECTED", "reason": reason},
                release_hash=rec.get("releaseHash"), semantic_key=f"{rec['tenantId']}::wo-reject::{work_order_id}",
            )
            return rec

    def cancel(self, work_order_id: str, *, actor: str) -> dict[str, Any]:
        with (
            self.dispatcher._lock if self.dispatcher is not None else nullcontext(),
            self._lock,
            self.logistics._lock if self.logistics is not None else nullcontext(),
        ):
            if self.qc is not None:
                self.qc.recover_pending()
            rec = self._require(work_order_id, tenant_id=None)
            if rec["state"] == "CANCELLED":
                return rec
            if rec["state"] in {"COMPLETED", "REJECTED"}:
                raise PermissionError("cannot cancel completed")
            self._release_unconsumed(rec)
            if self.dispatcher is not None:
                self.dispatcher.cancel_workorder(work_order_id, tenant_id=rec["tenantId"], actor=actor)
            rec["cancelledBy"] = actor
            rec["cancelledAt"] = _now()
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

    def pause_operation(self, work_order_id: str, op_id: str, *, actor: str) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        op = next(o for o in rec["ops"] if o["opId"] == op_id)
        labor = op.setdefault("labor", {"segments": [], "corrections": [], "paused": False})
        if labor.get("paused"):
            return op
        segs = labor.setdefault("segments", [])
        if segs and segs[-1].get("end") is None:
            segs[-1]["end"] = _now()
        labor["paused"] = True
        emit(
            self,
            "workorder.operation_pause",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"opId": op_id},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::op-pause::{op_id}",
        )
        return op

    def resume_operation(self, work_order_id: str, op_id: str, *, actor: str) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        op = next(o for o in rec["ops"] if o["opId"] == op_id)
        labor = op.setdefault("labor", {"segments": [], "corrections": [], "paused": False})
        if not labor.get("paused"):
            return op
        labor["paused"] = False
        labor.setdefault("segments", []).append({"start": _now(), "end": None, "kind": "manual"})
        emit(
            self,
            "workorder.operation_resume",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"opId": op_id},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::op-resume::{op_id}",
        )
        return op

    def correct_labor(
        self,
        work_order_id: str,
        op_id: str,
        *,
        actor: str,
        minutes: float,
        reason: str,
    ) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        op = next(o for o in rec["ops"] if o["opId"] == op_id)
        labor = op.setdefault("labor", {"segments": [], "corrections": [], "paused": False})
        correction_id = new_id()
        minutes_val = float(minutes)
        labor.setdefault("corrections", []).append(
            {
                "correctionId": correction_id,
                "minutes": minutes_val,
                "reason": reason,
                "actor": actor,
                "at": _now(),
                "appendOnly": True,
            }
        )
        emit(
            self,
            "workorder.labor_correct",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"opId": op_id, "minutes": minutes_val, "reason": reason},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::labor-correct::{op_id}::{reason}::{minutes_val}::{correction_id}",
        )
        return op

    def labor_summary(self, work_order_id: str) -> dict[str, Any]:
        rec = self.get(work_order_id)
        minutes = 0.0
        for op in rec.get("ops") or []:
            labor = op.get("labor") or {}
            for seg in labor.get("segments") or []:
                minutes += _elapsed_minutes(seg.get("start"), seg.get("end"))
            for corr in labor.get("corrections") or []:
                minutes += float(corr.get("minutes") or 0)
        n_ops = max(len((rec.get("traveler") or {}).get("steps") or []), 1)
        est_minutes = 15.0 * n_ops
        rate = 6.0
        estimated = est_minutes * rate
        actual = minutes * rate
        return {
            "workOrderId": work_order_id,
            "estimatedLaborMinutes": est_minutes,
            "actualManualLaborMinutes": round(minutes, 4),
            "estimatedLaborCost": round(estimated, 2),
            "actualManualLaborCost": round(actual, 2),
            "variance": round(actual - estimated, 2),
            "estimateSource": "CONFIG_ESTIMATE",
            "actualSource": "MANUAL",
            "accountingActual": "NOT_IMPLEMENTED",
            "rateSource": "CONFIG_ESTIMATE",
            "wageClaim": False,
            "historyAppendOnly": True,
            "truthLabel": "REAL_LOGIC / MANUAL",
        }

    def hold(
        self,
        work_order_id: str,
        *,
        actor: str,
        reason: str,
        blocking: bool = True,
        operator_id: str | None = None,
        shift_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            rec = self._require(work_order_id, tenant_id=None)
            h = {
                "holdId": new_id(),
                "reason": reason,
                "actor": actor,
                "open": True,
                "blocking": bool(blocking),
                "operatorId": operator_id,
                "shiftId": shift_id,
                "at": _now(),
            }
            rec.setdefault("holds", []).append(h)
            if blocking and rec["state"] not in TERMINAL and rec["state"] != "QC_HOLD":
                self._transition(rec, "QC_HOLD", actor=actor, reason=f"hold:{reason}")
            emit(
                self,
                "workorder.hold",
                tenant_id=rec["tenantId"],
                aggregate_type="WorkOrder",
                aggregate_id=rec["workOrderId"],
                actor=actor,
                payload={"holdId": h["holdId"], "reason": reason, "blocking": bool(blocking)},
                release_hash=rec.get("releaseHash"),
                semantic_key=f"{rec['tenantId']}::hold::{rec['workOrderId']}::{h['holdId']}",
            )
            return h

    def resolve_hold(self, work_order_id: str, hold_id: str, *, actor: str) -> dict[str, Any]:
        with self._lock:
            rec = self._require(work_order_id, tenant_id=None)
            h = next(x for x in rec.get("holds") or [] if x["holdId"] == hold_id)
            if not h.get("open"):
                return h
            h["open"] = False
            h["resolvedBy"] = actor
            h["resolvedAt"] = _now()
            if h.get("reason") == PACKING_MISMATCH:
                rec["mismatchHold"] = any(
                    x.get("open") and x.get("reason") == PACKING_MISMATCH for x in rec.get("holds") or []
                )
            open_blocking = [x for x in rec.get("holds") or [] if x.get("open") and x.get("blocking")]
            if rec["state"] == "QC_HOLD" and not open_blocking:
                gate = self._authoritative_qc_gate(rec)
                if gate.get("ok"):
                    self._transition(rec, "IN_PROGRESS", actor=actor, reason="hold-resolved")
            emit(
                self,
                "workorder.hold_resolve",
                tenant_id=rec["tenantId"],
                aggregate_type="WorkOrder",
                aggregate_id=rec["workOrderId"],
                actor=actor,
                payload={"holdId": hold_id},
                release_hash=rec.get("releaseHash"),
                semantic_key=f"{rec['tenantId']}::hold-resolve::{hold_id}",
            )
            return h

    def authorize_rework(
        self,
        work_order_id: str,
        *,
        actor: str,
        reason: str,
        operation: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        require_confirm(payload, action="rework")
        rec = self._require(work_order_id, tenant_id=None)
        rework_id = new_id()
        rec.setdefault("reworkHistory", []).append(
            {
                "reworkId": rework_id,
                "reason": reason,
                "actor": actor,
                "operation": operation,
                "at": _now(),
                "appendOnly": True,
            }
        )
        rec["rework"] = True
        rec["reworkBy"] = actor
        if rec["state"] == "QC_HOLD":
            self._transition(rec, "IN_PROGRESS", actor=actor, reason=reason)
        op_name = operation or f"rework_{len(rec.get('reworkHistory') or [])}"
        steps = rec.setdefault("traveler", {}).setdefault("steps", [])
        if not any(s.get("operation") == op_name and s.get("rework") for s in steps):
            steps.append(
                {
                    "seq": len(steps) + 1,
                    "operation": op_name,
                    "kind": "rework",
                    "machineCommand": False,
                    "liveLaser": False,
                    "liveCnc": False,
                    "rework": True,
                }
            )
        emit(
            self,
            "workorder.rework_authorize",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"reason": reason, "operation": op_name},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::wo-rework-auth::{rec['workOrderId']}:{op_name}:{reason}:{rework_id}",
        )
        return rec

    def scrap(
        self,
        work_order_id: str,
        *,
        actor: str,
        quantity: float,
        remnant_rects: list[dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
        reason: str = "scrap",
    ) -> dict[str, Any]:
        require_confirm(payload, action="scrap")
        rec = self._require(work_order_id, tenant_id=None)
        qty = float(quantity)
        if qty < 0:
            raise PermissionError("scrap quantity cannot be negative")
        created: list[dict[str, Any]] = []
        if remnant_rects and self.remnants is not None:
            created = self.remnants.add_from_nesting(
                {"candidateRemnants": remnant_rects, "grainConstraint": "length"},
                material="WOOD_WHITE",
                thickness=18,
                source_run=rec["workOrderId"],
                tenant_id=rec["tenantId"],
            )
            rec["lineage"]["remnants"] = list(rec["lineage"].get("remnants") or []) + [r["remnantId"] for r in created]
            rec.setdefault("remnantDispositions", []).append(
                {"kind": "REMNANT", "ids": [r["remnantId"] for r in created], "at": _now(), "silentScrap": False}
            )
        scrap_id = new_id()
        rec.setdefault("scrap", []).append(
            {
                "scrapId": scrap_id,
                "qty": qty,
                "kind": "scrapWithRemnantSplit" if created else "trueScrap",
                "source": "MANUAL",
                "actor": actor,
                "reason": reason,
                "silentScrap": False,
                "at": _now(),
            }
        )
        emit(
            self,
            "workorder.scrap",
            tenant_id=rec["tenantId"],
            aggregate_type="WorkOrder",
            aggregate_id=rec["workOrderId"],
            actor=actor,
            payload={"qty": qty, "remnants": [r["remnantId"] for r in created]},
            release_hash=rec.get("releaseHash"),
            semantic_key=f"{rec['tenantId']}::wo-scrap::{rec['workOrderId']}:{qty}:{reason}:{scrap_id}",
        )
        return {"workOrder": rec, "remnants": created, "silentScrap": False}

    def _release_unconsumed(self, rec: dict[str, Any]) -> None:
        """Release lot and remnant reservations that this work order has not consumed."""
        if rec.get("consumedFlag"):
            rec["consumedFrozen"] = True
        reservations = rec.get("reservations") or []
        has_remnants = self.remnants is not None and any(item.get("kind") == "remnant" for item in reservations)
        with self._remnant_transaction(rec["tenantId"]) if has_remnants else nullcontext():
            for item in reservations:
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
                            current_v = int(rem.get("version") or 1)
                            updated = dict(rem)
                            updated["status"] = "available"
                            updated["qualityState"] = "AVAILABLE"
                            updated["reservedBy"] = None
                            updated["leaseToken"] = None
                            updated["reservedUntil"] = None
                            updated["idempotencyKey"] = None
                            updated["version"] = current_v + 1
                            self.remnants.store.put(updated, expected_version=current_v)
                            self.remnants.items[item["remnantId"]] = updated
                    except (KeyError, PermissionError):
                        continue
        rec["materialReserved"] = False

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
        allowed = TRANSITIONS.get(str(frm) if frm is not None else "", frozenset())
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
