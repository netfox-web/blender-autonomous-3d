"""Receiving / procurement boundary. No autonomous PO or payment."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import MaterialLotRegistry, atomic_write_json, read_json
from fox3d.journal import SemanticKeyConflictError, emit
from fox3d.outbox import BUSINESS_COMMITTED, PREPARED

ALLOWED = frozenset({"MANUAL", "IMPORTED"})


def _now() -> str:
    return utcnow().isoformat()


class ReceivingService:
    def __init__(self, lots: MaterialLotRegistry | None = None, root: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.lots = lots or MaterialLotRegistry()
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self.requests: dict[str, dict[str, Any]] = {}
        self.receipts: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "receipts.json") or {}
        self.receipts = {r["receiptId"]: r for r in payload.get("receipts") or []}
        self.requests = {r["requestId"]: r for r in payload.get("requests") or []}
        self._idem = dict(payload.get("idem") or {})

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(
            self.root / "receipts.json",
            {"receipts": list(self.receipts.values()), "requests": list(self.requests.values()), "idem": self._idem},
        )

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
        rec: dict[str, Any] = {
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
        with self._lock:
            with self.lots._lock:
                if source not in ALLOWED:
                    raise PermissionError("receipt source must be MANUAL/IMPORTED")
                raw_key = idempotency_key or f"{row.get('supplierLot') or row.get('supplierId')}:{row.get('material')}:{row.get('quantity')}"
                key = f"{tenant_id}::{raw_key}"
                if key in self._idem:
                    existing = self.receipts[self._idem[key]]
                    if existing.get("tenantId") != tenant_id:
                        raise PermissionError("tenant isolation: receipt")
                    self._finalize_existing(existing, tenant_id=tenant_id, semantic_key=key, actor=actor)
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
                rec: dict[str, Any] = {
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
                lots_before = copy.deepcopy(self.lots.lots)
                event_type = "receipt.quarantined" if mismatch else "receipt.accepted"
                payload: dict[str, Any] = {}
                try:
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
                    payload = {"status": rec.get("status"), "lotId": rec.get("lotId"), "source": source}
                    emit(
                        self,
                        event_type,
                        tenant_id=tenant_id,
                        aggregate_type="Receipt",
                        aggregate_id=rec["receiptId"],
                        actor=actor,
                        payload=payload,
                        semantic_key=key,
                    )
                except Exception:
                    if self._receipt_durable(
                        tenant_id=tenant_id, semantic_key=key, event_type=event_type, payload=payload
                    ):
                        # Business snapshot and/or journal already committed. Rolling
                        # them back would mint a new lot id on retry and collide with
                        # the semantic key. Finish the outbox when we can; otherwise
                        # keep the committed snapshot for restart reconcile.
                        self._finalize_receipt_tx(
                            tenant_id=tenant_id,
                            semantic_key=key,
                            event_type=event_type,
                            payload=payload,
                            actor=actor,
                            aggregate_id=rec["receiptId"],
                        )
                        return rec
                    self._rollback_receipt(lots_before, rec["receiptId"], key, tenant_id=tenant_id)
                    raise
                return rec

    def _finalize_existing(self, existing: dict[str, Any], *, tenant_id: str, semantic_key: str, actor: str) -> None:
        event_type = "receipt.quarantined" if existing.get("quarantined") else "receipt.accepted"
        payload = {"status": existing.get("status"), "lotId": existing.get("lotId"), "source": existing.get("source")}
        try:
            self._finalize_receipt_tx(
                tenant_id=tenant_id,
                semantic_key=semantic_key,
                event_type=event_type,
                payload=payload,
                actor=actor,
                aggregate_id=str(existing.get("receiptId") or ""),
            )
        except Exception:
            return

    def _open_receipt_txs(self, *, tenant_id: str, semantic_key: str) -> list[dict[str, Any]]:
        outbox = self.outbox
        if outbox is None or not semantic_key or not hasattr(outbox, "list_open"):
            return []
        return [tx for tx in outbox.list_open(tenant_id=tenant_id) if tx.get("semanticKey") == semantic_key]

    def _journal_matches(
        self, *, tenant_id: str, semantic_key: str, event_type: str, payload: dict[str, Any]
    ) -> bool:
        journal = self.journal
        if journal is None or not semantic_key or not payload or not hasattr(journal, "check_semantic_key"):
            return False
        try:
            found = journal.check_semantic_key(
                tenant_id=tenant_id,
                event_type=event_type,
                payload=payload,
                release_hash=None,
                semantic_key=semantic_key,
            )
        except SemanticKeyConflictError:
            return False
        return found is not None

    def _receipt_durable(
        self, *, tenant_id: str, semantic_key: str, event_type: str, payload: dict[str, Any]
    ) -> bool:
        if self._journal_matches(
            tenant_id=tenant_id, semantic_key=semantic_key, event_type=event_type, payload=payload
        ):
            return True
        return any(tx.get("status") == BUSINESS_COMMITTED for tx in self._open_receipt_txs(
            tenant_id=tenant_id, semantic_key=semantic_key
        ))

    def _finalize_receipt_tx(
        self,
        *,
        tenant_id: str,
        semantic_key: str,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        aggregate_id: str,
    ) -> bool:
        """Append the journal event when the business snapshot is already committed, then close the outbox."""
        journal = self.journal
        matched = self._journal_matches(
            tenant_id=tenant_id, semantic_key=semantic_key, event_type=event_type, payload=payload
        )
        if not matched and journal is not None and hasattr(journal, "append"):
            try:
                journal.append(
                    event_type,
                    tenant_id=tenant_id,
                    aggregate_type="Receipt",
                    aggregate_id=aggregate_id,
                    actor=actor,
                    payload=payload,
                    semantic_key=semantic_key,
                    source=actor,
                )
            except Exception:
                return False
            matched = True
        outbox = self.outbox
        if outbox is None or not hasattr(outbox, "complete"):
            return matched
        for tx in self._open_receipt_txs(tenant_id=tenant_id, semantic_key=semantic_key):
            try:
                outbox.complete(str(tx["txId"]))
            except Exception:
                return matched
        return matched

    def _rollback_receipt(
        self,
        lots_before: dict[str, Any],
        receipt_id: str,
        semantic_key: str,
        *,
        tenant_id: str,
    ) -> None:
        self.lots.lots = lots_before
        self.lots.persist()
        self.receipts.pop(receipt_id, None)
        self._idem.pop(semantic_key, None)
        self.persist()
        outbox = self.outbox
        if outbox is None or not hasattr(outbox, "abort"):
            return
        for tx in self._open_receipt_txs(tenant_id=tenant_id, semantic_key=semantic_key):
            if tx.get("status") == PREPARED:
                outbox.abort(str(tx["txId"]))
