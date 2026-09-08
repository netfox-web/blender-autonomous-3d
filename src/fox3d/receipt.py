"""Receiving / procurement boundary. No autonomous PO or payment."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import MaterialLotRegistry

ALLOWED = frozenset({"MANUAL", "IMPORTED"})


def _now() -> str:
    return utcnow().isoformat()


class ReceivingService:
    def __init__(self, lots: MaterialLotRegistry | None = None) -> None:
        self.lots = lots or MaterialLotRegistry()
        self.requests: dict[str, dict[str, Any]] = {}
        self.receipts: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, str] = {}

    def draft_purchase_request(
        self,
        *,
        tenant_id: str,
        material: str,
        quantity: int,
        actor: str,
        shortage: dict[str, Any] | None = None,
        release_hash: str | None = None,
    ) -> dict[str, Any]:
        rec = {
            "requestId": new_id(),
            "tenantId": tenant_id,
            "material": material,
            "quantity": int(quantity),
            "status": "WAITING_HUMAN_APPROVAL",
            "kind": "DRAFT_PURCHASE_REQUEST",
            "sent": False,
            "payment": False,
            "poIssued": False,
            "liveProvider": False,
            "shortage": shortage or {},
            "releaseHash": release_hash,
            "createdBy": actor,
            "createdAt": _now(),
            "truthLabel": "MANUAL",
        }
        rec["requestHash"] = stable_hash({k: rec[k] for k in rec if k not in {"requestId", "requestHash"}})
        self.requests[rec["requestId"]] = rec
        return rec

    def import_receipt(
        self,
        row: dict[str, Any],
        *,
        tenant_id: str,
        actor: str,
        source: str = "IMPORTED",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if source not in ALLOWED:
            raise PermissionError("receipt source must be MANUAL/IMPORTED")
        key = idempotency_key or f"{tenant_id}:{row.get('supplierLot') or row.get('supplierId')}:{row.get('material')}:{row.get('quantity')}"
        if key in self._idem:
            return self.receipts[self._idem[key]]
        qty = int(row.get("quantity") or row.get("sheetCount") or 0)
        material = str(row.get("material") or "PB_18_WHITE")
        thickness = float(row.get("thickness") or 18)
        expected_material = row.get("expectedMaterial")
        expected_qty = row.get("expectedQuantity")
        expected_thickness = row.get("expectedThickness")
        mismatch = False
        reasons = []
        if expected_material and str(expected_material) != material:
            mismatch = True
            reasons.append("material")
        if expected_qty is not None and int(expected_qty) != qty:
            mismatch = True
            reasons.append("quantity")
        if expected_thickness is not None and abs(float(expected_thickness) - thickness) > 1e-6:
            mismatch = True
            reasons.append("thickness")
        rec = {
            "receiptId": new_id(),
            "tenantId": tenant_id,
            "supplierId": row.get("supplierId"),
            "supplierLot": row.get("supplierLot"),
            "material": material,
            "thickness": thickness,
            "quantity": qty,
            "unitCost": float(row.get("unitCost") or row.get("costPerSheet") or 850),
            "source": source,
            "truthLabel": source,
            "liveProvider": False,
            "actor": actor,
            "coaAssetId": row.get("coaAssetId"),
            "createdAt": _now(),
            "quarantined": mismatch,
            "mismatchReasons": reasons,
            "acceptedQty": 0 if mismatch else qty,
        }
        rec["receiptHash"] = stable_hash({k: rec[k] for k in rec if k not in {"receiptId", "receiptHash"}})
        if mismatch:
            lot = self.lots.create(
                tenant_id=tenant_id,
                material=material,
                thickness=thickness,
                sheet_count=qty,
                supplier_lot=row.get("supplierLot"),
                cost_per_sheet=rec["unitCost"],
            )
            self.lots.quarantine(lot["lotId"], tenant_id=tenant_id, actor=actor, reason=",".join(reasons) or "mismatch")
            rec["lotId"] = lot["lotId"]
            rec["status"] = "QUARANTINED"
        else:
            lot = self.lots.receive(
                tenant_id=tenant_id,
                material=material,
                thickness=thickness,
                quantity=qty,
                actor=actor,
                source=source,
                supplier_id=row.get("supplierId"),
                supplier_lot=row.get("supplierLot"),
                unit_cost=rec["unitCost"],
            )
            rec["lotId"] = lot["lotId"]
            rec["status"] = "ACCEPTED"
        self.receipts[rec["receiptId"]] = rec
        self._idem[key] = rec["receiptId"]
        return rec
