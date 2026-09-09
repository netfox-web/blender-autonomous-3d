"""MANUAL_STATION dispatch boundary. Traveler/queue workflow, not machine control."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import JobQueue, utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import emit
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
}
LEASE_SECONDS = 120.0


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
        if not path:
            return
        lock = self.root / "stations.lock" if self.root else None
        if lock:
            with FileLock(lock):
                atomic_write_json(path, {"stations": list(self.stations.values())})
        else:
            atomic_write_json(path, {"stations": list(self.stations.values())})

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
        rec = {
            "stationId": station_id or new_id(),
            "tenantId": tenant_id,
            "capabilities": caps,
            "status": status if status in {"ONLINE", "OFFLINE", "PAUSED"} else "ONLINE",
            "heartbeatAt": _now(),
            "currentLease": None,
            "operator": actor,
            "actuatorEndpoint": None,
            "machineCommand": False,
            "liveCnc": False,
            "liveLaser": False,
        }
        rec["stationHash"] = stable_hash({k: rec[k] for k in rec if k != "stationHash"})
        with self._lock:
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

    def set_status(self, station_id: str, *, tenant_id: str, status: str) -> dict[str, Any]:
        rec = self.get(station_id, tenant_id=tenant_id)
        rec["status"] = status
        self.persist()
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
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / "leases.json") or {}
        self.leases = {l["leaseId"]: l for l in payload.get("leases") or []}
        for job in payload.get("jobs") or []:
            if self.queue.get(job["jobId"]) is None:
                self.queue.restore(job)

    def persist(self) -> None:
        if not self.root:
            return
        jobs = []
        for lease in self.leases.values():
            job = self.queue.get(lease.get("jobId") or "")
            if job:
                jobs.append(job)
        atomic_write_json(self.root / "leases.json", {"leases": list(self.leases.values()), "jobs": jobs})

    def reconcile(self) -> dict[str, Any]:
        cleared = 0
        for station in list(self.stations.stations.values()):
            lid = station.get("currentLease")
            if not lid:
                continue
            lease = self.leases.get(lid)
            if lease is None or lease.get("status") in {"COMPLETED", "EXPIRED"} or lease.get("tenantId") != station.get("tenantId"):
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
        cap = OP_CAPABILITY.get(operation)
        if not cap:
            raise PermissionError(f"no MANUAL_STATION capability for {operation}")
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
    ) -> dict[str, Any]:
        wo = self._require_wo(work_order_id, tenant_id)
        station = self.stations.get(station_id, tenant_id=tenant_id)
        if station.get("status") != "ONLINE":
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
        if station.get("currentLease"):
            raise PermissionError("station already owns an operation")
        existing = self.active_lease_for_op(work_order_id=work_order_id, operation=operation)
        if existing:
            if existing.get("stationId") == station_id:
                return existing
            raise PermissionError("operation already leased")
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
        job["status"] = "reserved"
        job["leaseOwner"] = station_id
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
            "createdAt": _now(),
            "machineCommand": False,
        }
        lease["leaseHash"] = stable_hash({k: lease[k] for k in lease if k != "leaseHash"})
        with self._lock:
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
            semantic_key=f"{tenant_id}::dispatch::{work_order_id}::{operation}",
        )
        return lease

    def ack(self, lease_id: str, *, tenant_id: str, actor: str, confirm: bool = True) -> dict[str, Any]:
        lease = self._lease(lease_id, tenant_id)
        if lease.get("acked"):
            return lease
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

    def start(self, lease_id: str, *, tenant_id: str, actor: str) -> dict[str, Any]:
        lease = self._lease(lease_id, tenant_id)
        if not lease.get("acked"):
            self.ack(lease_id, tenant_id=tenant_id, actor=actor)
        if lease.get("started"):
            return lease
        op = self.workorders.start_operation(lease["workOrderId"], lease["operation"], actor=actor, tenant_id=tenant_id)
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

    def complete(self, lease_id: str, *, tenant_id: str, actor: str, confirm: bool = True) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("human confirmation required")
        lease = self._lease(lease_id, tenant_id)
        if lease.get("completed"):
            return lease
        if not lease.get("started"):
            self.start(lease_id, tenant_id=tenant_id, actor=actor)
        op_id = lease.get("opId")
        self.workorders.complete_operation(lease["workOrderId"], op_id, actor=actor)
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

    def _lease(self, lease_id: str, tenant_id: str) -> dict[str, Any]:
        lease = self.leases[lease_id]
        if lease.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: lease")
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
