"""MANUAL_STATION dispatch boundary. Traveler/queue workflow, not machine control."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import JobQueue, utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import SemanticKeyConflictError, emit
from fox3d.recovery import ExceptionInbox, PilotException
from fox3d.storelock import FileLock

STATION_CAPS = (
    "PANEL_CUTTING_MANUAL",
    "EDGE_BANDING_MANUAL",
    "DRILLING_MANUAL",
    "ASSEMBLY_MANUAL",
    "PACKING_MANUAL",
    "QC_MANUAL",
)
OP_CAPABILITY = {
    "panel_cutting": "PANEL_CUTTING_MANUAL",
    "sheet_cutting": "PANEL_CUTTING_MANUAL",
    "blank_cutting": "PANEL_CUTTING_MANUAL",
    "edge_banding": "EDGE_BANDING_MANUAL",
    "edge_finishing": "EDGE_BANDING_MANUAL",
    "drilling_routing": "DRILLING_MANUAL",
    "hardware_prep": "ASSEMBLY_MANUAL",
    "assembly": "ASSEMBLY_MANUAL",
    "fixture_assembly": "ASSEMBLY_MANUAL",
    "bend": "ASSEMBLY_MANUAL",
    "creasing": "PACKING_MANUAL",
    "folding": "PACKING_MANUAL",
    "gluing": "PACKING_MANUAL",
    "packaging": "PACKING_MANUAL",
    "packing": "PACKING_MANUAL",
    "surface_inspection": "QC_MANUAL",
    "inspection": "QC_MANUAL",
    "print_inspection": "QC_MANUAL",
    "load_label": "QC_MANUAL",
    "rework": "QC_MANUAL",
}
LEASE_SECONDS = 120.0
ADMIN_STATION_STATUSES = frozenset({"ACTIVE", "MAINTENANCE", "DISABLED"})
OPERATOR_STATION_STATUSES = frozenset({"ONLINE", "OFFLINE", "PAUSED"})
ALL_STATION_STATUSES = ADMIN_STATION_STATUSES | OPERATOR_STATION_STATUSES
DISPATCHABLE_STATION_STATUSES = frozenset({"ONLINE", "ACTIVE"})


def _now() -> str:
    return utcnow().isoformat()


class StationRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.stations: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self._crash_mode = ""
        self._tx_persisted: bool = False
        self.load()

    def _path(self) -> Path | None:
        return (self.root / "stations.json") if self.root else None

    def load(self) -> None:
        path = self._path()
        if not path:
            return
        payload = read_json(path) or {}
        self.stations = {s["stationId"]: s for s in payload.get("stations") or []}

    def persist(self) -> None:
        path = self._path()
        if path:
            lock = self.root / "stations.lock" if self.root else None
            if lock:
                with FileLock(lock):
                    atomic_write_json(path, {"stations": list(self.stations.values())})
            else:
                atomic_write_json(path, {"stations": list(self.stations.values())})
        self._tx_persisted = True

    def register(
        self,
        *,
        tenant_id: str,
        capabilities: list[str],
        station_id: str | None = None,
        actor: str = "ops",
        status: str = "ONLINE",
    ) -> dict[str, Any]:
        caps = [c for c in capabilities if c in STATION_CAPS]
        if not caps:
            raise PermissionError("station requires a MANUAL capability")
        resolved_status = status if status in {"ONLINE", "OFFLINE", "PAUSED"} else "ONLINE"
        st_id = station_id or new_id()
        with self._lock:
            existing = self.stations.get(st_id)
            if existing is not None:
                if existing.get("tenantId") != tenant_id:
                    raise PermissionError("tenant isolation: station")
                if (
                    existing.get("capabilities") != caps
                    or existing.get("status") != resolved_status
                ):
                    from fox3d.journal import SemanticKeyConflictError

                    raise SemanticKeyConflictError(f"stationId conflict for {st_id}")
                rec = existing
            else:
                rec = {
                    "stationId": st_id,
                    "tenantId": tenant_id,
                    "capabilities": caps,
                    "status": resolved_status,
                    "heartbeatAt": _now(),
                    "currentLease": None,
                    "operator": actor,
                    "actuatorEndpoint": None,
                    "machineCommand": False,
                    "liveCnc": False,
                    "liveLaser": False,
                }
                rec["stationHash"] = stable_hash({k: rec[k] for k in rec if k != "stationHash"})
                self.stations[rec["stationId"]] = rec
                self.persist()
        emit(
            self,
            "station.register",
            tenant_id=tenant_id,
            aggregate_type="Station",
            aggregate_id=rec["stationId"],
            actor=actor,
            payload={"capabilities": caps, "status": rec["status"]},
            semantic_key=f"{tenant_id}::station::{rec['stationId']}",
        )
        return rec

    def get(self, station_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.stations[station_id]
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: station")
        return rec

    def heartbeat(self, station_id: str, *, tenant_id: str, actor: str | None = None) -> dict[str, Any]:
        rec = self.get(station_id, tenant_id=tenant_id)
        rec["heartbeatAt"] = _now()
        if actor:
            rec["operator"] = actor
        self.persist()
        return rec

    def _status_semantic_key(self, tenant_id: str, station_id: str, transition_id: str) -> str:
        return f"{tenant_id}::station::{station_id}::status::{transition_id}"

    def _finalize_status_transition(
        self,
        rec: dict[str, Any],
        *,
        tenant_id: str,
        transition_id: str,
    ) -> None:
        op = (rec.get("statusTransitions") or {}).get(transition_id)
        if not isinstance(op, dict):
            return
        payload = {"status": op.get("status"), "note": op.get("note"), "transitionId": transition_id}
        actor = str(op.get("actor") or rec.get("statusUpdatedBy") or "ops")
        semantic_key = self._status_semantic_key(tenant_id, str(rec["stationId"]), transition_id)
        journal = self.journal
        if journal is not None:
            found = (
                journal.check_semantic_key(
                    tenant_id=tenant_id,
                    event_type="station.status",
                    payload=payload,
                    release_hash=None,
                    semantic_key=semantic_key,
                )
                if hasattr(journal, "check_semantic_key")
                else None
            )
            if found is None:
                journal.append(
                    "station.status",
                    tenant_id=tenant_id,
                    aggregate_type="Station",
                    aggregate_id=str(rec["stationId"]),
                    actor=actor,
                    payload=payload,
                    release_hash=None,
                    semantic_key=semantic_key,
                    source=actor,
                )
        outbox = self.outbox or (getattr(journal, "outbox", None) if journal is not None else None)
        if outbox is not None and hasattr(outbox, "list_open"):
            for tx in outbox.list_open(tenant_id=tenant_id):
                if tx.get("semanticKey") == semantic_key:
                    outbox.complete(str(tx["txId"]))

    def _cleanup_uncommitted_status_txs(self, rec: dict[str, Any], *, tenant_id: str) -> None:
        outbox = self.outbox or (getattr(self.journal, "outbox", None) if self.journal is not None else None)
        if outbox is None or not hasattr(outbox, "list_open") or not hasattr(outbox, "abort"):
            return
        committed_ids = set((rec.get("statusTransitions") or {}).keys())
        for tx in outbox.list_open(tenant_id=tenant_id):
            ev = tx.get("event") or {}
            if (
                tx.get("status") == "PREPARED"
                and tx.get("aggregateType") == "Station"
                and tx.get("aggregateId") == rec.get("stationId")
                and (ev.get("event_type") or ev.get("eventType")) == "station.status"
            ):
                tid_in_tx = (ev.get("payload") or {}).get("transitionId")
                if tid_in_tx not in committed_ids:
                    outbox.abort(str(tx["txId"]))

    def set_status(
        self,
        station_id: str,
        *,
        tenant_id: str,
        status: str,
        actor: str = "ops",
        note: str | None = None,
        transition_id: str | None = None,
    ) -> dict[str, Any]:
        """Update station status with an independent, retryable transition event."""
        if status not in ALL_STATION_STATUSES:
            raise ValueError(f"invalid station status: {status}")
        if note is not None and not isinstance(note, str):
            raise ValueError("invalid station status note")
        explicit_tid: str | None = None
        if transition_id is not None and transition_id != "":
            if not isinstance(transition_id, str) or not transition_id.strip() or len(transition_id) > 200:
                raise ValueError("invalid transition_id")
            explicit_tid = transition_id.strip()
        with self._lock:
            rec = self.get(station_id, tenant_id=tenant_id)
            ops = rec.get("statusTransitions")
            if explicit_tid is not None and isinstance(ops, dict) and explicit_tid in ops:
                prior = ops[explicit_tid]
                if prior.get("status") != status or prior.get("note") != note:
                    raise SemanticKeyConflictError(f"transitionId conflict for {explicit_tid}")
                self._finalize_status_transition(rec, tenant_id=tenant_id, transition_id=explicit_tid)
                self._cleanup_uncommitted_status_txs(rec, tenant_id=tenant_id)
                return rec
            last_tid = rec.get("statusTransitionId")
            if isinstance(last_tid, str) and last_tid:
                self._finalize_status_transition(rec, tenant_id=tenant_id, transition_id=last_tid)
            if rec.get("status") == status:
                if explicit_tid is not None and self.journal is not None and hasattr(self.journal, "check_semantic_key"):
                    self.journal.check_semantic_key(
                        tenant_id=tenant_id,
                        event_type="station.status",
                        payload={"status": status, "note": note, "transitionId": explicit_tid},
                        release_hash=None,
                        semantic_key=self._status_semantic_key(tenant_id, str(rec["stationId"]), explicit_tid),
                    )
                self._cleanup_uncommitted_status_txs(rec, tenant_id=tenant_id)
                return rec
            prev_snapshot = copy.deepcopy(rec)
            trans_id = explicit_tid or new_id()
            seq = int(rec.get("statusSeq") or 0) + 1
            transitions = dict(rec.get("statusTransitions") or {})
            transitions[trans_id] = {"status": status, "note": note, "actor": actor, "seq": seq}
            rec["status"] = status
            rec["statusUpdatedAt"] = _now()
            rec["statusUpdatedBy"] = actor
            rec["statusSeq"] = seq
            rec["statusTransitionId"] = trans_id
            rec["statusTransitions"] = transitions
            if note is not None:
                rec["statusNote"] = note
            else:
                rec.pop("statusNote", None)
            payload = {"status": status, "note": note, "transitionId": trans_id}
            semantic_key = self._status_semantic_key(tenant_id, str(rec["stationId"]), trans_id)
            self._tx_persisted = False
            try:
                emit(
                    self,
                    "station.status",
                    tenant_id=tenant_id,
                    aggregate_type="Station",
                    aggregate_id=rec["stationId"],
                    actor=actor,
                    payload=payload,
                    semantic_key=semantic_key,
                )
            except Exception:
                if not self._tx_persisted:
                    self.stations[station_id] = prev_snapshot
                raise
            self._cleanup_uncommitted_status_txs(rec, tenant_id=tenant_id)
            return rec

    def list(self, *, tenant_id: str) -> list[dict[str, Any]]:
        return [s for s in self.stations.values() if s.get("tenantId") == tenant_id]


class StationDispatcher:
    def __init__(
        self,
        *,
        stations: StationRegistry,
        queue: JobQueue,
        workorders: Any,
        releases: Any | None = None,
        inbox: ExceptionInbox | None = None,
        lease_seconds: float = LEASE_SECONDS,
        root: Path | None = None,
    ) -> None:
        self.stations = stations
        self.queue = queue
        self.workorders = workorders
        self.releases = releases
        self.inbox = inbox or ExceptionInbox()
        self.lease_seconds = lease_seconds
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.leases: dict[str, dict[str, Any]] = {}
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self.identity: Any | None = None
        self._lock = threading.RLock()
        self.load()

    def _require_identity(
        self,
        *,
        tenant_id: str,
        operator_id: str | None,
        shift_id: str | None,
        capability: str | None = None,
    ) -> dict[str, Any] | None:
        if self.identity is None or (operator_id is None and shift_id is None):
            return None
        if not operator_id or not shift_id:
            raise PermissionError("operatorId and shiftId required together")
        return self.identity.require_active(
            tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id, capability=capability
        )

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "leases.json") or {}
        self.leases = {l["leaseId"]: l for l in payload.get("leases") or []}
        for job in payload.get("jobs") or []:
            # The lease snapshot is a fallback for jobs missing from the durable store.
            self.queue.restore(job)

    def persist(self) -> None:
        if not self.root:
            return
        jobs = []
        for lease in self.leases.values():
            job = self.queue.get(lease.get("jobId") or "")
            if job:
                with self.queue._lock, self.queue._process_lock():
                    saved = next((r for r in self.queue._store.read_all()
                                  if r.get("jobId") == job["jobId"]), None) if self.queue._store else None
                    if saved and saved.get("status") == job.get("status") and not saved.get("cancelRequested"):
                        for field in ("heartbeatAt", "startedAt"):
                            if field in job:
                                saved[field] = job[field]
                        self.queue._save(saved)
                jobs.append(job)
        atomic_write_json(self.root / "leases.json", {"leases": list(self.leases.values()), "jobs": jobs})

    def reconcile(self) -> dict[str, Any]:
        cleared = 0
        for station in list(self.stations.stations.values()):
            lid = station.get("currentLease")
            if not lid:
                continue
            lease = self.leases.get(lid)
            if lease is None or lease.get("status") in {"COMPLETED", "EXPIRED", "CANCELLED"} or lease.get("tenantId") != station.get("tenantId"):
                station["currentLease"] = None
                cleared += 1
                self.inbox.record(
                    tenant_id=str(station.get("tenantId") or ""),
                    code="PROCESS_RESTART",
                    work_order_id=(lease or {}).get("workOrderId"),
                    release_hash=(lease or {}).get("releaseHash"),
                    actor="reconcile",
                    detail="orphaned or cross-tenant currentLease cleared",
                )
        if cleared:
            self.stations.persist()
            self.persist()
        return {"cleared": cleared}

    def capability_for(self, operation: str) -> str:
        if str(operation).startswith("rework"):
            return "QC_MANUAL"
        cap = OP_CAPABILITY.get(operation)
        if not cap:
            raise ValueError("invalid operation")
        return cap

    def _require_wo(self, work_order_id: str, tenant_id: str) -> dict[str, Any]:
        wo = self.workorders.get(work_order_id)
        if wo.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: work order")
        if wo.get("state") in {"CANCELLED", "COMPLETED", "REJECTED"}:
            raise PermissionError("cancelled/completed work order cannot dispatch")
        if not wo.get("materialReserved"):
            raise PermissionError("dispatch requires material reservation")
        if self.releases is not None:
            rel = self.releases.get(wo["releaseId"])
            if rel.get("stale") or rel.get("status") in {"STALE", "SUPERSEDED", "CANCELLED"}:
                raise PermissionError("stale/superseded release cannot dispatch")
            if rel.get("releaseHash") != wo.get("releaseHash"):
                raise PermissionError("dispatch releaseHash mismatch")
        return wo

    def active_lease_for_op(self, *, work_order_id: str, operation: str) -> dict[str, Any] | None:
        for lease in self.leases.values():
            if lease.get("workOrderId") == work_order_id and lease.get("operation") == operation:
                if lease.get("status") in {"LEASED", "ACKED", "STARTED"}:
                    return lease
        return None

    def dispatch(
        self,
        *,
        tenant_id: str,
        work_order_id: str,
        operation: str,
        station_id: str,
        actor: str = "ops",
        operator_id: str | None = None,
        shift_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            wo = self._require_wo(work_order_id, tenant_id)
            self._require_identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
            station = self.stations.get(station_id, tenant_id=tenant_id)
            station_status = str(station.get("status") or "")
            if station_status not in DISPATCHABLE_STATION_STATUSES:
                if station_status in {"MAINTENANCE", "DISABLED"}:
                    raise PermissionError("station unavailable for dispatch")
                self.inbox.record(
                    tenant_id=tenant_id,
                    code="STATION_OFFLINE",
                    work_order_id=work_order_id,
                    release_hash=wo.get("releaseHash"),
                    actor=actor,
                )
                raise PilotException("STATION_OFFLINE")
            cap = self.capability_for(operation)
            if cap not in (station.get("capabilities") or []):
                raise PermissionError("station missing capability")
            existing = self.active_lease_for_op(work_order_id=work_order_id, operation=operation)
            if existing:
                if existing.get("stationId") == station_id:
                    return existing
                raise PermissionError("operation already leased")
            if station.get("currentLease"):
                raise PermissionError("station already owns an operation")
            if station.get("actuatorEndpoint") or station.get("machineCommand"):
                raise PermissionError("station adapter may not execute machine commands")
            job = self.queue.enqueue(
                {
                    "jobId": new_id(),
                    "jobType": "MANUAL_STATION",
                    "capability": cap,
                    "tenantId": tenant_id,
                    "workOrderId": work_order_id,
                    "releaseId": wo.get("releaseId"),
                    "releaseHash": wo.get("releaseHash"),
                    "operation": operation,
                    "stationId": station_id,
                    "status": "queued",
                    "machineCommand": False,
                    "liveCnc": False,
                    "liveLaser": False,
                    "heartbeatAt": _now(),
                }
            )
            self.queue.set_status(job["jobId"], "reserved", leaseOwner=station_id)
            claimed = job
            lease = {
                "leaseId": claimed["jobId"],
                "jobId": claimed["jobId"],
                "tenantId": tenant_id,
                "stationId": station_id,
                "workOrderId": work_order_id,
                "releaseId": wo.get("releaseId"),
                "releaseHash": wo.get("releaseHash"),
                "operation": operation,
                "capability": cap,
                "status": "LEASED",
                "acked": False,
                "started": False,
                "completed": False,
                "actor": actor,
                "operatorId": operator_id,
                "shiftId": shift_id,
                "createdAt": _now(),
                "machineCommand": False,
            }
            lease["leaseHash"] = stable_hash({k: lease[k] for k in lease if k != "leaseHash"})
            self.leases[lease["leaseId"]] = lease
            station["currentLease"] = lease["leaseId"]
            self.stations.persist()
            emit(
                self,
                "station.dispatch",
                tenant_id=tenant_id,
                aggregate_type="StationLease",
                aggregate_id=lease["leaseId"],
                actor=actor,
                payload={"workOrderId": work_order_id, "operation": operation, "stationId": station_id},
                release_hash=wo.get("releaseHash"),
                semantic_key=f"{tenant_id}::dispatch::{work_order_id}::{operation}::{lease['leaseId']}",
            )
            return lease

    def ack(
        self,
        lease_id: str,
        *,
        tenant_id: str,
        actor: str,
        confirm: bool = True,
        operator_id: str | None = None,
        shift_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            lease = self._lease(lease_id, tenant_id)
            self._require_identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
            if lease.get("acked"):
                return lease
            self._refuse_closed_workorder(lease.get("workOrderId"))
            lease["acked"] = True
            lease["status"] = "ACKED"
            lease["ackedBy"] = actor
            lease["ackedAt"] = _now()
            self.stations.heartbeat(lease["stationId"], tenant_id=tenant_id, actor=actor)
            self.queue.heartbeat(lease["jobId"])
            emit(
                self,
                "station.ack",
                tenant_id=tenant_id,
                aggregate_type="StationLease",
                aggregate_id=lease_id,
                actor=actor,
                payload={"confirm": bool(confirm)},
                release_hash=lease.get("releaseHash"),
                semantic_key=f"{tenant_id}::ack::{lease_id}",
            )
            return lease

    def start(
        self,
        lease_id: str,
        *,
        tenant_id: str,
        actor: str,
        operator_id: str | None = None,
        shift_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            lease = self._lease(lease_id, tenant_id)
            self._require_identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
            if not lease.get("acked"):
                self.ack(lease_id, tenant_id=tenant_id, actor=actor, operator_id=operator_id, shift_id=shift_id)
            if lease.get("started"):
                return lease
            self._refuse_closed_workorder(lease.get("workOrderId"))
            op = self.workorders.start_operation(
                lease["workOrderId"],
                lease["operation"],
                actor=actor,
                tenant_id=tenant_id,
                operator_id=operator_id,
                shift_id=shift_id,
            )
            lease["started"] = True
            lease["status"] = "STARTED"
            lease["opId"] = op["opId"]
            lease["startedBy"] = actor
            self.queue.set_status(lease["jobId"], "running")
            emit(
                self,
                "station.start",
                tenant_id=tenant_id,
                aggregate_type="StationLease",
                aggregate_id=lease_id,
                actor=actor,
                payload={"opId": op["opId"]},
                release_hash=lease.get("releaseHash"),
                semantic_key=f"{tenant_id}::start::{lease_id}",
            )
            return lease

    def complete(
        self,
        lease_id: str,
        *,
        tenant_id: str,
        actor: str,
        confirm: bool = True,
        operator_id: str | None = None,
        shift_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not confirm:
                raise PermissionError("human confirmation required")
            lease = self._lease(lease_id, tenant_id)
            self._require_identity(tenant_id=tenant_id, operator_id=operator_id, shift_id=shift_id)
            if lease.get("completed"):
                return lease
            self._refuse_closed_workorder(lease.get("workOrderId"))
            if not lease.get("started"):
                self.start(lease_id, tenant_id=tenant_id, actor=actor, operator_id=operator_id, shift_id=shift_id)
            op_id = lease.get("opId")
            self.workorders.complete_operation(
                lease["workOrderId"], op_id, actor=actor, operator_id=operator_id, shift_id=shift_id
            )
            lease["completed"] = True
            lease["status"] = "COMPLETED"
            lease["completedBy"] = actor
            lease["completedAt"] = _now()
            station = self.stations.get(lease["stationId"], tenant_id=tenant_id)
            if station.get("currentLease") == lease_id:
                station["currentLease"] = None
                self.stations.persist()
            try:
                self.queue.set_status(lease["jobId"], "completed")
            except Exception:
                job = self.queue.get(lease["jobId"])
                if job:
                    job["status"] = "completed"
            emit(
                self,
                "station.complete",
                tenant_id=tenant_id,
                aggregate_type="StationLease",
                aggregate_id=lease_id,
                actor=actor,
                payload={"opId": op_id},
                release_hash=lease.get("releaseHash"),
                semantic_key=f"{tenant_id}::complete::{lease_id}",
            )
            return lease

    def cancel_workorder(self, work_order_id: str, *, tenant_id: str, actor: str) -> None:
        with self._lock:
            for lease in self.leases.values():
                if lease.get("tenantId") != tenant_id or lease.get("workOrderId") != work_order_id:
                    continue
                if lease.get("status") not in {"LEASED", "ACKED", "STARTED"}:
                    continue
                lease["status"] = "CANCELLED"
                station = self.stations.get(lease["stationId"], tenant_id=tenant_id)
                if station.get("currentLease") == lease["leaseId"]:
                    station["currentLease"] = None
                job = self.queue.get(lease["jobId"])
                if job:
                    job["status"] = "cancelled"
                self.inbox.record(
                    tenant_id=tenant_id, code="WORKORDER_CANCELLED", work_order_id=work_order_id,
                    release_hash=lease.get("releaseHash"), actor=actor,
                )
            self.stations.persist()
            self.persist()

    def expire_leases(self, *, max_age_seconds: float | None = None) -> list[str]:
        recovered = self.queue.recover_stale_leases(max_age_seconds=max_age_seconds or self.lease_seconds)
        expired: list[str] = []
        for job_id in recovered:
            lease = self.leases.get(job_id)
            if not lease or lease.get("completed"):
                continue
            lease["status"] = "EXPIRED"
            lease["expiredAt"] = _now()
            try:
                station = self.stations.get(lease["stationId"], tenant_id=lease["tenantId"])
                if station.get("currentLease") == job_id:
                    station["currentLease"] = None
            except (KeyError, PermissionError):
                pass
            self.inbox.record(
                tenant_id=lease["tenantId"],
                code="LEASE_EXPIRED",
                work_order_id=lease.get("workOrderId"),
                release_hash=lease.get("releaseHash"),
                actor="system",
            )
            expired.append(job_id)
        if recovered:
            self.stations.persist()
            self.persist()
        return expired

    def _refuse_closed_workorder(self, work_order_id: str | None) -> None:
        if not work_order_id:
            return
        wo = self.workorders.get(work_order_id)
        if wo.get("state") in {"CANCELLED", "COMPLETED", "REJECTED"}:
            raise PermissionError("cancelled/completed work order cannot dispatch")

    def list_leases(
        self,
        *,
        tenant_id: str,
        station_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        items = [dict(lease) for lease in self.leases.values() if lease.get("tenantId") == tenant_id]
        if station_id:
            items = [lease for lease in items if lease.get("stationId") == station_id]
        if status:
            items = [lease for lease in items if lease.get("status") == status]
        return items

    def _lease(self, lease_id: str, tenant_id: str) -> dict[str, Any]:
        lease = self.leases[lease_id]
        if lease.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: lease")
        if lease.get("status") == "CANCELLED":
            raise PermissionError("lease cancelled")
        if lease.get("status") == "EXPIRED":
            self.inbox.record(
                tenant_id=tenant_id,
                code="LEASE_EXPIRED",
                work_order_id=lease.get("workOrderId"),
                release_hash=lease.get("releaseHash"),
                actor="ops",
            )
            raise PilotException("LEASE_EXPIRED")
        return lease
