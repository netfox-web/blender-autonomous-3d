"""Pilot observability / health. Tenant-safe counters, no fake factory SLA."""

from __future__ import annotations

from typing import Any

from fox3d.infra import utcnow
from fox3d.station import OP_CAPABILITY


def _now() -> str:
    return utcnow().isoformat()


def pilot_health(pilot: Any, *, tenant_id: str) -> dict[str, Any]:
    wos = [wo for wo in pilot.workorders.orders.values() if wo.get("tenantId") == tenant_id]
    by_state: dict[str, int] = {}
    queued_ops = 0
    for wo in wos:
        by_state[wo["state"]] = by_state.get(wo["state"], 0) + 1
        steps = [s["operation"] for s in (wo.get("traveler") or {}).get("steps") or []]
        done = {o.get("operation") for o in wo.get("ops") or [] if o.get("status") == "COMPLETED"}
        queued_ops += sum(1 for op in steps if op not in done)
    dispatcher = getattr(pilot, "dispatcher", None)
    active = expired = 0
    if dispatcher is not None:
        for lease in dispatcher.leases.values():
            if lease.get("tenantId") != tenant_id:
                continue
            if lease.get("status") == "EXPIRED":
                expired += 1
            elif lease.get("status") in {"LEASED", "ACKED", "STARTED"}:
                active += 1
    inbox = getattr(pilot, "inbox", None)
    exceptions = inbox.list(tenant_id=tenant_id) if inbox is not None else []
    shortage = sum(1 for e in exceptions if e.get("errorCode") == "MATERIAL_SHORTAGE")
    stale = sum(1 for e in exceptions if e.get("errorCode") == "STALE_RELEASE")
    packing = sum(1 for e in exceptions if e.get("errorCode") == "PACKING_MISMATCH")
    qc_rows = [c for c in pilot.qc.checks.values() if c.get("tenantId") == tenant_id]
    qc_pass = sum(1 for c in qc_rows if c.get("ok"))
    qc_fail = sum(1 for c in qc_rows if not c.get("ok"))
    rework = sum(1 for d in pilot.qc.defects.values() if d.get("tenantId") == tenant_id and d.get("disposition") == "REWORK")
    journal = getattr(pilot, "journal", None)
    integrity = journal.verify(tenant_id) if journal is not None else {"ok": False, "status": "MISSING", "label": "MISSING"}
    return {
        "tenantId": tenant_id,
        "at": _now(),
        "queuedManualOperations": queued_ops,
        "activeStationLeases": active,
        "expiredStationLeases": expired,
        "workOrdersByState": by_state,
        "reservationShortageCount": shortage,
        "staleReleaseRejects": stale,
        "qcPass": qc_pass,
        "qcFail": qc_fail,
        "qcRework": rework,
        "packingExceptions": packing,
        "journalIntegrity": integrity,
        "liveCnc": "BLOCKED",
        "liveLaser": "BLOCKED",
        "liveMachineControl": False,
        "latencyLabel": "local/runtime measurement",
        "notFactorySla": True,
        "capabilityMapSize": len(OP_CAPABILITY),
        "lastSuccessfulRealAcceptance": {
            "commit": None,
            "generation": None,
            "note": "filled by acceptance runner when REAL evidence is published",
        },
    }
