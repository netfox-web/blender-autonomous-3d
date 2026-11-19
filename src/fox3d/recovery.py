"""Pilot exception / recovery catalog. Fail-closed, journaled, not a parallel engine."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import emit
from fox3d.storelock import FileLock

CATALOG: dict[str, dict[str, Any]] = {
    "MATERIAL_SHORTAGE": {
        "errorCode": "MATERIAL_SHORTAGE",
        "retrySafe": True,
        "humanRequired": True,
        "allowedNextStates": ["RELEASED_FOR_MANUAL_EXECUTION"],
        "eventType": "exception.material_shortage",
        "lineageValid": True,
    },
    "WRONG_MATERIAL": {
        "errorCode": "WRONG_MATERIAL",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["RELEASED_FOR_MANUAL_EXECUTION", "QC_HOLD"],
        "eventType": "exception.wrong_material",
        "lineageValid": True,
    },
    "QUARANTINED_RECEIPT": {
        "errorCode": "QUARANTINED_RECEIPT",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["DRAFT", "RELEASED_FOR_MANUAL_EXECUTION"],
        "eventType": "exception.quarantined_receipt",
        "lineageValid": True,
    },
    "STALE_RELEASE": {
        "errorCode": "STALE_RELEASE",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["CANCELLED"],
        "eventType": "exception.stale_release",
        "lineageValid": False,
    },
    "QC_FINAL_FAIL": {
        "errorCode": "QC_FINAL_FAIL",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["QC_HOLD", "IN_PROGRESS"],
        "eventType": "exception.qc_final_fail",
        "lineageValid": True,
    },
    "REWORK_REQUIRED": {
        "errorCode": "REWORK_REQUIRED",
        "retrySafe": True,
        "humanRequired": True,
        "allowedNextStates": ["IN_PROGRESS", "QC_HOLD"],
        "eventType": "exception.rework_required",
        "lineageValid": True,
    },
    "DUPLICATE_SCAN": {
        "errorCode": "DUPLICATE_SCAN",
        "retrySafe": True,
        "humanRequired": False,
        "allowedNextStates": ["IN_PROGRESS", "MATERIAL_RESERVED", "PACKING", "COMPLETED"],
        "eventType": "exception.duplicate_scan",
        "lineageValid": True,
    },
    "STATION_OFFLINE": {
        "errorCode": "STATION_OFFLINE",
        "retrySafe": True,
        "humanRequired": True,
        "allowedNextStates": ["MATERIAL_RESERVED", "IN_PROGRESS"],
        "eventType": "exception.station_offline",
        "lineageValid": True,
    },
    "LEASE_EXPIRED": {
        "errorCode": "LEASE_EXPIRED",
        "retrySafe": True,
        "humanRequired": True,
        "allowedNextStates": ["IN_PROGRESS", "MATERIAL_RESERVED"],
        "eventType": "exception.lease_expired",
        "lineageValid": True,
    },
    "PACKING_MISMATCH": {
        "errorCode": "PACKING_MISMATCH",
        "retrySafe": False,
        "humanRequired": True,
        "allowedNextStates": ["PACKING", "QC_HOLD"],
        "eventType": "exception.packing_mismatch",
        "lineageValid": True,
    },
    "PROCESS_RESTART": {
        "errorCode": "PROCESS_RESTART",
        "retrySafe": True,
        "humanRequired": False,
        "allowedNextStates": ["MATERIAL_RESERVED", "IN_PROGRESS", "RELEASED_FOR_MANUAL_EXECUTION"],
        "eventType": "exception.process_restart",
        "lineageValid": True,
    },
}


class PilotException(PermissionError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        spec = CATALOG.get(code) or {"errorCode": code, "retrySafe": False, "humanRequired": True}
        super().__init__(detail or code)
        self.code = code
        self.spec = spec
        self.silentSuccess = False


class ExceptionStateError(PermissionError):
    """Raised when an exception inbox transition is not allowed (e.g. ack after resolve)."""


def catalog_entry(code: str) -> dict[str, Any]:
    if code not in CATALOG:
        raise KeyError(code)
    return dict(CATALOG[code])


class ExceptionInbox:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.items: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self._crash_mode = ""
        self._tx_persisted: bool = False
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "exceptions.json") or {}
        self.items = {r["exceptionId"]: r for r in payload.get("items") or []}

    def persist(self) -> None:
        if self.root:
            with FileLock(self.root / "exceptions.lock"):
                atomic_write_json(self.root / "exceptions.json", {"items": list(self.items.values())})
        self._tx_persisted = True

    def _payload_identity(self, payload: dict[str, Any] | None, exc_id: str) -> dict[str, Any]:
        raw = dict(payload or {})
        if "exceptionId" in raw and str(raw.get("exceptionId")) == exc_id:
            raw = {k: v for k, v in raw.items() if k != "exceptionId"}
        return raw

    def record(
        self,
        *,
        tenant_id: str,
        code: str,
        work_order_id: str | None = None,
        release_hash: str | None = None,
        actor: str = "system",
        detail: str | None = None,
        payload: dict[str, Any] | None = None,
        exception_id: str | None = None,
    ) -> dict[str, Any]:
        spec: dict[str, Any] = catalog_entry(code) if code in CATALOG else {"errorCode": code, "retrySafe": False, "humanRequired": True, "eventType": f"exception.{code}", "lineageValid": True, "allowedNextStates": []}
        raw_payload = copy.deepcopy(payload or {})
        payload_exc_id = raw_payload.get("exceptionId")
        if exception_id is not None and payload_exc_id is not None and str(exception_id) != str(payload_exc_id):
            from fox3d.journal import SemanticKeyConflictError

            raise SemanticKeyConflictError(f"exceptionId conflict for {exception_id}")
        exc_id = str(exception_id or payload_exc_id or new_id())
        resolved_detail = detail or code
        incoming_payload_id = self._payload_identity(raw_payload, exc_id)
        created_new = False
        with self._lock:
            existing = self.items.get(exc_id)
            if existing is not None:
                if existing.get("tenantId") != tenant_id:
                    raise PermissionError("tenant isolation: exception")
                existing_payload_id = self._payload_identity(existing.get("payload"), exc_id)
                if (
                    existing.get("errorCode") != spec["errorCode"]
                    or existing.get("workOrderId") != work_order_id
                    or existing.get("releaseHash") != release_hash
                    or existing.get("detail") != resolved_detail
                    or existing.get("actor") != actor
                    or existing_payload_id != incoming_payload_id
                    or stable_hash(existing_payload_id) != stable_hash(incoming_payload_id)
                ):
                    from fox3d.journal import SemanticKeyConflictError

                    raise SemanticKeyConflictError(f"exceptionId conflict for {exc_id}")
                rec = existing
            else:
                rec = {
                    "exceptionId": exc_id,
                    "tenantId": tenant_id,
                    "errorCode": spec["errorCode"],
                    "retrySafe": bool(spec.get("retrySafe")),
                    "humanRequired": bool(spec.get("humanRequired")),
                    "allowedNextStates": list(spec.get("allowedNextStates") or []),
                    "lineageValid": bool(spec.get("lineageValid")),
                    "workOrderId": work_order_id,
                    "releaseHash": release_hash,
                    "detail": resolved_detail,
                    "payload": raw_payload,
                    "status": "OPEN",
                    "silentSuccess": False,
                    "actor": actor,
                    "at": utcnow().isoformat(),
                }
                rec["exceptionHash"] = stable_hash({k: rec[k] for k in rec if k != "exceptionHash"})
                self.items[rec["exceptionId"]] = rec
                created_new = True
        key_scope = f"{work_order_id}::{rec['exceptionId']}" if work_order_id else rec["exceptionId"]
        try:
            emit(
                self,
                str(spec.get("eventType") or "exception"),
                tenant_id=tenant_id,
                aggregate_type="PilotException",
                aggregate_id=rec["exceptionId"],
                actor=actor,
                payload={
                    "errorCode": rec["errorCode"],
                    "workOrderId": work_order_id,
                    "releaseHash": release_hash,
                    "detail": rec["detail"],
                    "payload": incoming_payload_id,
                    "actor": actor,
                },
                release_hash=release_hash,
                semantic_key=f"{tenant_id}::exc::{code}::{key_scope}",
            )
        except Exception:
            if created_new:
                with self._lock:
                    if self.root and (self.root / "exceptions.json").exists():
                        self.load()
                    else:
                        self.items.pop(exc_id, None)
            raise
        return rec

    def list(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        items = [i for i in self.items.values() if i.get("tenantId") == tenant_id]
        if status:
            items = [i for i in items if i.get("status") == status]
        return items

    def get(self, exception_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.items[exception_id]
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: exception")
        return rec

    def _finalize_transition(
        self,
        *,
        event_type: str,
        tenant_id: str,
        aggregate_id: str,
        actor: str,
        payload: dict[str, Any],
        release_hash: str | None,
        semantic_key: str,
    ) -> None:
        journal = self.journal
        if journal is not None:
            found = (
                journal.check_semantic_key(
                    tenant_id=tenant_id,
                    event_type=event_type,
                    payload=payload,
                    release_hash=release_hash,
                    semantic_key=semantic_key,
                )
                if hasattr(journal, "check_semantic_key")
                else None
            )
            if found is None:
                journal.append(
                    event_type,
                    tenant_id=tenant_id,
                    aggregate_type="PilotException",
                    aggregate_id=aggregate_id,
                    actor=actor,
                    payload=payload,
                    release_hash=release_hash,
                    semantic_key=semantic_key,
                    source=actor,
                )
        outbox = self.outbox or (getattr(journal, "outbox", None) if journal is not None else None)
        if outbox is not None and hasattr(outbox, "list_open"):
            for tx in outbox.list_open(tenant_id=tenant_id):
                if tx.get("semanticKey") == semantic_key:
                    outbox.complete(str(tx["txId"]))

    def _abort_uncommitted_ack_txs(self, *, tenant_id: str, exception_id: str) -> None:
        outbox = self.outbox or (getattr(self.journal, "outbox", None) if self.journal is not None else None)
        if outbox is None or not hasattr(outbox, "list_open") or not hasattr(outbox, "abort"):
            return
        ack_key = f"{tenant_id}::exc-ack::{exception_id}"
        for tx in outbox.list_open(tenant_id=tenant_id):
            if tx.get("status") == "PREPARED" and tx.get("semanticKey") == ack_key:
                outbox.abort(str(tx["txId"]))

    def acknowledge(
        self,
        exception_id: str,
        *,
        tenant_id: str,
        actor: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Acknowledge an OPEN exception with durable outbox/journal recovery."""
        if note is not None and not isinstance(note, str):
            raise ValueError("invalid exception note")
        with self._lock:
            rec = self.get(exception_id, tenant_id=tenant_id)
            if rec.get("status") == "RESOLVED":
                raise ExceptionStateError("exception already resolved")
            semantic_key = f"{tenant_id}::exc-ack::{rec['exceptionId']}"
            if rec.get("status") == "ACKNOWLEDGED":
                self._finalize_transition(
                    event_type="exception.acknowledged",
                    tenant_id=tenant_id,
                    aggregate_id=rec["exceptionId"],
                    actor=str(rec.get("acknowledgedBy") or actor),
                    payload={"note": rec.get("ackNote"), "status": "ACKNOWLEDGED"},
                    release_hash=rec.get("releaseHash"),
                    semantic_key=semantic_key,
                )
                return rec
            prev_snapshot = copy.deepcopy(rec)
            rec["status"] = "ACKNOWLEDGED"
            rec["acknowledgedAt"] = utcnow().isoformat()
            rec["acknowledgedBy"] = actor
            if note is not None:
                rec["ackNote"] = note
            else:
                rec.pop("ackNote", None)
            payload = {"note": note, "status": "ACKNOWLEDGED"}
            self._tx_persisted = False
            try:
                emit(
                    self,
                    "exception.acknowledged",
                    tenant_id=tenant_id,
                    aggregate_type="PilotException",
                    aggregate_id=rec["exceptionId"],
                    actor=actor,
                    payload=payload,
                    release_hash=rec.get("releaseHash"),
                    semantic_key=semantic_key,
                )
            except Exception:
                if not self._tx_persisted:
                    self.items[exception_id] = prev_snapshot
                raise
            self._finalize_transition(
                event_type="exception.acknowledged",
                tenant_id=tenant_id,
                aggregate_id=rec["exceptionId"],
                actor=actor,
                payload=payload,
                release_hash=rec.get("releaseHash"),
                semantic_key=semantic_key,
            )
            return rec

    def resolve(
        self,
        exception_id: str,
        *,
        tenant_id: str,
        actor: str,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        """Resolve an exception with durable outbox/journal recovery."""
        if resolution is not None and not isinstance(resolution, str):
            raise ValueError("invalid exception resolution")
        with self._lock:
            rec = self.get(exception_id, tenant_id=tenant_id)
            if rec.get("acknowledgedAt") is not None:
                self._finalize_transition(
                    event_type="exception.acknowledged",
                    tenant_id=tenant_id,
                    aggregate_id=rec["exceptionId"],
                    actor=str(rec.get("acknowledgedBy") or actor),
                    payload={"note": rec.get("ackNote"), "status": "ACKNOWLEDGED"},
                    release_hash=rec.get("releaseHash"),
                    semantic_key=f"{tenant_id}::exc-ack::{rec['exceptionId']}",
                )
            semantic_key = f"{tenant_id}::exc-resolve::{rec['exceptionId']}"
            if rec.get("status") == "RESOLVED":
                self._finalize_transition(
                    event_type="exception.resolved",
                    tenant_id=tenant_id,
                    aggregate_id=rec["exceptionId"],
                    actor=str(rec.get("resolvedBy") or actor),
                    payload={"resolution": rec.get("resolution"), "status": "RESOLVED"},
                    release_hash=rec.get("releaseHash"),
                    semantic_key=semantic_key,
                )
                if rec.get("acknowledgedAt") is None:
                    self._abort_uncommitted_ack_txs(tenant_id=tenant_id, exception_id=rec["exceptionId"])
                return rec
            prev_snapshot = copy.deepcopy(rec)
            rec["status"] = "RESOLVED"
            rec["resolvedAt"] = utcnow().isoformat()
            rec["resolvedBy"] = actor
            if resolution is not None:
                rec["resolution"] = resolution
            else:
                rec.pop("resolution", None)
            payload = {"resolution": resolution, "status": "RESOLVED"}
            self._tx_persisted = False
            try:
                emit(
                    self,
                    "exception.resolved",
                    tenant_id=tenant_id,
                    aggregate_type="PilotException",
                    aggregate_id=rec["exceptionId"],
                    actor=actor,
                    payload=payload,
                    release_hash=rec.get("releaseHash"),
                    semantic_key=semantic_key,
                )
            except Exception:
                if not self._tx_persisted:
                    self.items[exception_id] = prev_snapshot
                raise
            self._finalize_transition(
                event_type="exception.resolved",
                tenant_id=tenant_id,
                aggregate_id=rec["exceptionId"],
                actor=actor,
                payload=payload,
                release_hash=rec.get("releaseHash"),
                semantic_key=semantic_key,
            )
            if rec.get("acknowledgedAt") is None:
                self._abort_uncommitted_ack_txs(tenant_id=tenant_id, exception_id=rec["exceptionId"])
            return rec
