"""Manual Work Order / shop traveler. Execution boundary, not a MES.

Binds to ManufacturingRelease.releaseHash. Reuses MaterialLot / RemnantStore.
"""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import MaterialLotRegistry, normalize_status
from fox3d.mfg_release import FAMILY_STEPS

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
    ) -> None:
        self.lots = lots or MaterialLotRegistry()
        self.remnants = remnants
        self.dam = dam
        self.releases = releases
        self.qc: Any | None = None
        self.orders: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, str] = {}
        self.operations: list[dict[str, Any]] = []

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
        if release.get("stale") or release.get("status") == "STALE":
            raise PermissionError("stale release cannot open a work order")
        batch = batch_id or new_id()
        key = idempotency_key or f"{tenant_id}:{release['releaseHash']}:{batch}"
        if key in self._idem:
            return self.orders[self._idem[key]]
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
        }
        rec["traveler"] = self._traveler(family)
        rec["workOrderHash"] = stable_hash({k: rec[k] for k in ("tenantId", "releaseHash", "batchId", "quantity")})
        self.orders[rec["workOrderId"]] = rec
        self._idem[key] = rec["workOrderId"]
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
        if rec["state"] not in {"DRAFT", "RELEASED_FOR_MANUAL_EXECUTION"}:
            raise PermissionError(rec["state"])
        rec["state"] = "RELEASED_FOR_MANUAL_EXECUTION"
        rec["releasedBy"] = actor
        return rec

    def reserve_materials(self, work_order_id: str, *, actor: str, tenant_id: str | None = None) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=tenant_id)
        self._assert_release_fresh(rec)
        if rec.get("materialReserved"):
            return rec
        tid = rec["tenantId"]
        release = self._release_of(rec)
        nesting = (release.get("snapshot") or {}).get("nesting") or {}
        sheet_n = max(int(nesting.get("sheetCount") or 1), 1) * int(rec["quantity"])
        material = str(nesting.get("sheetSku") or "PB_18_WHITE")
        thickness = float(nesting.get("thickness") or 18)
        lots = [l for l in self.lots.list(tenant_id=tid) if int(l.get("remainingSheets") or 0) > 0]
        if not lots:
            lot = self.lots.create(tenant_id=tid, material=material, thickness=thickness, sheet_count=max(sheet_n, 2))
            lots = [lot]
        lot_reservations: list[dict[str, Any]] = []
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
            extra = self.lots.create(tenant_id=tid, material=material, thickness=thickness, sheet_count=remaining)
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
        rec["state"] = "MATERIAL_RESERVED"
        rec["reservedBy"] = actor
        rec["reservedAt"] = _now()
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
        self._assert_release_fresh(rec)
        if rec["state"] in TERMINAL:
            raise PermissionError(rec["state"])
        if rec["state"] in {"DRAFT"}:
            raise PermissionError("not released")
        if rec["state"] == "RELEASED_FOR_MANUAL_EXECUTION":
            rec["state"] = "MATERIAL_RESERVED" if rec.get("materialReserved") else rec["state"]
        if rec["state"] in {"MATERIAL_RESERVED", "QC_HOLD"}:
            rec["state"] = "IN_PROGRESS"
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
        return op

    def complete_operation(self, work_order_id: str, op_id: str, *, actor: str, notes: str = "") -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        op = next(o for o in rec["ops"] if o["opId"] == op_id)
        op["completedAt"] = _now()
        op["status"] = "COMPLETED"
        if notes:
            op["notes"] = (op.get("notes") or "") + (" " + notes if op.get("notes") else notes)
        op["completedBy"] = actor
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
        return rec

    def set_packing(self, work_order_id: str, carton_ids: list[str]) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        rec["state"] = "PACKING"
        rec["lineage"]["package"] = list(carton_ids)
        rec["cartonIds"] = list(carton_ids)
        return rec

    def complete(self, work_order_id: str, *, actor: str, qc_ok: bool = True) -> dict[str, Any]:
        rec = self._require(work_order_id, tenant_id=None)
        self._assert_release_fresh(rec)
        gate = self._authoritative_qc_gate(rec)
        rec["qcGate"] = gate
        if not gate.get("ok"):
            rec["state"] = "QC_HOLD"
            raise PermissionError("required QC missing or failed; completion blocked")
        if not qc_ok:
            rec["state"] = "QC_HOLD"
            raise PermissionError("required QC missing or failed; completion blocked")
        rec["state"] = "COMPLETED"
        rec["completedBy"] = actor
        rec["completedAt"] = _now()
        return rec

    def _authoritative_qc_gate(self, rec: dict[str, Any]) -> dict[str, Any]:
        if self.qc is None:
            return {"ok": False, "reason": "NO_QC_AUTHORITY", "missing": ["*"], "failed": []}
        result = self.qc.required_final_ok(rec["workOrderId"], rec["productFamily"], tenant_id=rec.get("tenantId"))
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
        if rec["state"] == "COMPLETED":
            raise PermissionError("cannot cancel completed")
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
        rec["state"] = "CANCELLED"
        rec["cancelledBy"] = actor
        rec["cancelledAt"] = _now()
        rec["materialReserved"] = False
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

    def _assert_release_fresh(self, rec: dict[str, Any]) -> None:
        if self.releases is None:
            return
        rel = self.releases.get(rec["releaseId"])
        if rel.get("stale") or rel.get("status") == "STALE":
            raise PermissionError("stale release cannot progress")
        if rel.get("releaseHash") != rec.get("releaseHash"):
            raise PermissionError("work order releaseHash mismatch")
