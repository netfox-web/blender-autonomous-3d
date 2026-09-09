"""Versioned MANUAL/IMPORTED import/export contracts. No live providers."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.journal import emit

SCHEMA_RECEIPT = "fox3d.receipt.v1"
SCHEMA_SUPPLIER = "fox3d.supplier_quote.v1"
SCHEMA_CARRIER = "fox3d.carrier_quote.v1"
SCHEMA_ADJUST = "fox3d.inventory_adjustment.v1"
SCHEMA_EXPORT = "fox3d.export.v1"
ALLOWED_SOURCES = frozenset({"MANUAL", "IMPORTED"})


def _now() -> str:
    return utcnow().isoformat()


def _require(row: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [f for f in fields if row.get(f) in {None, ""}]


class ContractService:
    def __init__(self, pilot: Any) -> None:
        self.pilot = pilot
        self.journal: Any | None = None
        self.imports: dict[str, dict[str, Any]] = {}
        self.adjustments: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, str] = {}

    def import_bundle(
        self,
        payload: dict[str, Any],
        *,
        tenant_id: str,
        actor: str,
        source: str = "IMPORTED",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if source not in ALLOWED_SOURCES:
            raise PermissionError("imports are MANUAL/IMPORTED")
        schema = str(payload.get("schemaVersion") or "")
        raw_key = idempotency_key or payload.get("idempotencyKey") or stable_hash(payload)
        key = f"{tenant_id}::import::{schema}::{raw_key}"
        if key in self._idem:
            existing = self.imports[self._idem[key]]
            if existing.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: import")
            return existing
        rows = list(payload.get("rows") or [])
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        if schema == SCHEMA_RECEIPT:
            for i, row in enumerate(rows):
                missing = _require(row, ("material", "quantity"))
                if missing:
                    rejected.append({"index": i, "reasons": missing, "row": row})
                    continue
                rec = self.pilot.receiving.import_receipt(
                    row,
                    tenant_id=tenant_id,
                    actor=actor,
                    source=source,
                    idempotency_key=str(row.get("idempotencyKey") or row.get("supplierLot") or f"{raw_key}:{i}"),
                )
                accepted.append(rec)
        elif schema == SCHEMA_SUPPLIER:
            for i, row in enumerate(rows):
                missing = _require(row, ("supplierId",))
                if missing:
                    rejected.append({"index": i, "reasons": missing, "row": row})
                    continue
                rec = self.pilot.suppliers.import_json(
                    __import__("json").dumps([row]),
                    source=source,
                )[0]
                accepted.append(rec)
        elif schema == SCHEMA_CARRIER:
            for i, row in enumerate(rows):
                missing = _require(row, ("carrier", "charge"))
                if missing:
                    rejected.append({"index": i, "reasons": missing, "row": row})
                    continue
                rec = self.pilot.logistics.import_carrier_quote(row, source=source)
                accepted.append(rec)
        elif schema == SCHEMA_ADJUST:
            for i, row in enumerate(rows):
                missing = _require(row, ("lotId", "quantity", "reason"))
                if missing:
                    rejected.append({"index": i, "reasons": missing, "row": row})
                    continue
                adj = self.draft_adjustment(row, tenant_id=tenant_id, actor=actor, source=source)
                accepted.append(adj)
        else:
            raise PermissionError(f"unknown schema {schema}")
        rec = {
            "importId": new_id(),
            "tenantId": tenant_id,
            "schemaVersion": schema,
            "source": source,
            "truthLabel": source,
            "liveProvider": False,
            "accepted": accepted,
            "rejected": rejected,
            "acceptedCount": len(accepted),
            "rejectedCount": len(rejected),
            "actor": actor,
            "at": _now(),
            "silentPartial": False,
        }
        rec["importHash"] = stable_hash({k: rec[k] for k in rec if k not in {"importId", "importHash", "accepted", "rejected"}})
        self.imports[rec["importId"]] = rec
        self._idem[key] = rec["importId"]
        emit(
            self,
            "contract.import",
            tenant_id=tenant_id,
            aggregate_type="ImportBundle",
            aggregate_id=rec["importId"],
            actor=actor,
            payload={"schemaVersion": schema, "accepted": len(accepted), "rejected": len(rejected)},
            semantic_key=key,
        )
        return rec

    def draft_adjustment(self, row: dict[str, Any], *, tenant_id: str, actor: str, source: str = "MANUAL") -> dict[str, Any]:
        rec = {
            "adjustmentId": new_id(),
            "tenantId": tenant_id,
            "lotId": row["lotId"],
            "quantity": int(row["quantity"]),
            "reason": str(row["reason"]),
            "status": "WAITING_HUMAN_APPROVAL",
            "applied": False,
            "source": source,
            "truthLabel": source,
            "liveProvider": False,
            "actor": actor,
            "at": _now(),
        }
        rec["adjustmentHash"] = stable_hash({k: rec[k] for k in rec if k != "adjustmentHash"})
        self.adjustments[rec["adjustmentId"]] = rec
        return rec

    def approve_adjustment(self, adjustment_id: str, *, tenant_id: str, actor: str, confirm: bool = False) -> dict[str, Any]:
        rec = self.adjustments[adjustment_id]
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: adjustment")
        if not confirm:
            raise PermissionError("human confirmation required")
        if rec.get("applied"):
            return rec
        lot = self.pilot.platform.lots.receive(
            tenant_id=tenant_id,
            material=str(rec.get("material") or "PB_18_WHITE"),
            thickness=float(rec.get("thickness") or 18),
            quantity=int(rec["quantity"]),
            actor=actor,
            source="MANUAL",
            lot_id=rec["lotId"],
            reason=rec["reason"],
        )
        rec["applied"] = True
        rec["status"] = "APPLIED"
        rec["approvedBy"] = actor
        rec["lot"] = {"lotId": lot["lotId"]}
        emit(
            self,
            "contract.adjustment_applied",
            tenant_id=tenant_id,
            aggregate_type="InventoryAdjustment",
            aggregate_id=adjustment_id,
            actor=actor,
            payload={"lotId": rec["lotId"], "quantity": rec["quantity"]},
            semantic_key=f"{tenant_id}::adj::{adjustment_id}",
        )
        return rec

    def export_bundle(self, *, tenant_id: str, release_hash: str | None = None) -> dict[str, Any]:
        wos = [wo for wo in self.pilot.workorders.orders.values() if wo.get("tenantId") == tenant_id and (not release_hash or wo.get("releaseHash") == release_hash)]
        releases = [r for r in self.pilot.releases.releases.values() if r.get("tenantId") == tenant_id and (not release_hash or r.get("releaseHash") == release_hash)]
        lots = self.pilot.platform.lots.list(tenant_id=tenant_id)
        qc = [c for c in self.pilot.qc.checks.values() if c.get("tenantId") == tenant_id]
        cartons = [c for c in self.pilot.logistics.cartons.values() if c.get("tenantId") == tenant_id]
        shipments = [s for s in self.pilot.logistics.shipments.values() if s.get("tenantId") == tenant_id]
        journal = None
        if getattr(self.pilot, "journal", None) is not None:
            journal = self.pilot.journal.export_slice(tenant_id)
        packets = []
        for rel in releases:
            pkt = self.pilot.releases.packet(rel["releaseId"])
            packets.append(
                {
                    "releaseId": rel["releaseId"],
                    "releaseHash": rel.get("releaseHash"),
                    "checksums": rel.get("checksumManifest"),
                    "files": sorted(pkt.keys()),
                }
            )
        bundle = {
            "schemaVersion": SCHEMA_EXPORT,
            "tenantId": tenant_id,
            "exportedAt": _now(),
            "releaseHash": release_hash,
            "truthLabels": {
                "receipts": "MANUAL/IMPORTED",
                "supplierQuotes": "IMPORTED",
                "carrierQuotes": "IMPORTED",
                "journal": (journal or {}).get("truthLabel") or "MISSING",
                "LIVE_CNC": "BLOCKED",
                "LIVE_LASER": "BLOCKED",
            },
            "liveMachineControl": False,
            "submitsCarrierBooking": False,
            "actuatesMachine": False,
            "releases": packets,
            "workOrders": [
                {
                    "workOrderId": wo["workOrderId"],
                    "state": wo["state"],
                    "releaseHash": wo.get("releaseHash"),
                    "traveler": wo.get("traveler"),
                    "reservations": wo.get("reservations"),
                    "consumed": wo.get("consumed"),
                    "ops": wo.get("ops"),
                }
                for wo in wos
            ],
            "materialLots": [{"lotId": l["lotId"], "material": l.get("material"), **self.pilot.platform.lots.quantities(l["lotId"], tenant_id=tenant_id)} for l in lots],
            "qc": qc,
            "cartons": cartons,
            "shipmentDrafts": shipments,
            "journal": journal,
        }
        bundle["contentHash"] = stable_hash({k: bundle[k] for k in bundle if k != "contentHash"})
        emit(
            self,
            "contract.export",
            tenant_id=tenant_id,
            aggregate_type="ExportBundle",
            aggregate_id=bundle["contentHash"][:16],
            actor="export",
            payload={"releaseHash": release_hash},
            release_hash=release_hash,
        )
        return bundle
