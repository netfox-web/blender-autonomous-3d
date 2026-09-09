"""Receiving / procurement boundary. No autonomous PO or payment."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import MaterialLotRegistry
from fox3d.journal import emit

ALLOWED = frozenset({"MANUAL", "IMPORTED"})


def _now() -> str:
    return utcnow().isoformat()


class ReceivingService:
    def __init__(self, lots: MaterialLotRegistry | None = None) -> None:
        self.lots = lots or MaterialLotRegistry()
        self.journal: Any | None = None
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
        raw_key = idempotency_key or f"{row.get('supplierLot') or row.get('supplierId')}:{row.get('material')}:{row.get('quantity')}"
        key = f"{tenant_id}::{raw_key}"
        if key in self._idem:
            existing = self.receipts[self._idem[key]]
            if existing.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: receipt")
            return existing
        qty = int(row.get("quantity") or row.get("sheetCount") or 0)
        material = str(row.get("material") or "PB_18_WHITE")
        thickness = float(row.get("thickness") or 18)
        length = row.get("length")
        width = row.get("width")
        grain = row.get("grain")
        expected_material = row.get("expectedMaterial")
        expected_qty = row.get("expectedQuantity")
        expected_thickness = row.get("expectedThickness")
        expected_length = row.get("expectedLength")
        expected_width = row.get("expectedWidth")
        expected_grain = row.get("expectedGrain")
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
        if expected_length is not None and (length is None or abs(float(length) - float(expected_length)) > 1e-3):
            mismatch = True
            reasons.append("length")
        if expected_width is not None and (width is None or abs(float(width) - float(expected_width)) > 1e-3):
            mismatch = True
            reasons.append("width")
        if expected_grain is not None and str(grain or "") != str(expected_grain):
            mismatch = True
            reasons.append("grain")
        rec = {
            "receiptId": new_id(),
            "tenantId": tenant_id,
            "supplierId": row.get("supplierId"),
            "supplierLot": row.get("supplierLot"),
            "material": material,
            "thickness": thickness,
            "length": float(length) if length is not None else None,
            "width": float(width) if width is not None else None,
            "grain": grain,
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
                length=float(length) if length is not None else 2440,
                width=float(width) if width is not None else 1220,
                grain=str(grain or "length"),
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
                length=float(length) if length is not None else None,
                width=float(width) if width is not None else None,
                grain=str(grain) if grain is not None else None,
            )
            rec["lotId"] = lot["lotId"]
            rec["status"] = "ACCEPTED"
        self.receipts[rec["receiptId"]] = rec
        self._idem[key] = rec["receiptId"]
        try:
            emit(
                self,
                "receipt.quarantined" if rec.get("quarantined") else "receipt.accepted",
                tenant_id=tenant_id,
                aggregate_type="Receipt",
                aggregate_id=rec["receiptId"],
                actor=actor,
                payload={"status": rec.get("status"), "lotId": rec.get("lotId"), "source": source},
                semantic_key=key,
            )
        except Exception:
            del self.receipts[rec["receiptId"]]
            del self._idem[key]
            raise
        return rec
