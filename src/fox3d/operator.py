"""Operator control plane / scan workflow. Extends existing Admin/API, not a second UI stack."""

from __future__ import annotations

from typing import Any

from fox3d.journal import emit
from fox3d.recovery import ExceptionInbox, PilotException

TOKEN_KINDS = {"WO": "WorkOrder", "LOT": "MaterialLot", "REL": "ManufacturingRelease", "CTN": "carton"}


def make_token(kind: str, object_id: str) -> str:
    kind = kind.upper()
    if kind not in TOKEN_KINDS:
        raise PermissionError("unsupported scan kind")
    return f"FOX3D:{kind}:{object_id}"


def parse_token(token: str) -> tuple[str, str]:
    parts = str(token or "").split(":")
    if len(parts) != 3 or parts[0] != "FOX3D" or parts[1] not in TOKEN_KINDS:
        raise PermissionError("invalid scan token")
    return parts[1], parts[2]


def require_confirm(payload: dict[str, Any] | None, *, action: str) -> None:
    body = payload or {}
    if body.get("confirm") not in {True, "true", "1", 1}:
        raise PermissionError(f"human confirmation required for {action}")


def resolve_scan(pilot: Any, token: str, *, tenant_id: str) -> dict[str, Any]:
    kind, object_id = parse_token(token)
    rec: dict[str, Any]
    if kind == "WO":
        rec = dict(pilot.workorders.get(object_id))
    elif kind == "LOT":
        rec = dict(pilot.platform.lots.get(object_id, tenant_id=tenant_id))
    elif kind == "REL":
        rec = dict(pilot.releases.get(object_id))
    else:
        rec = dict(pilot.logistics.cartons[object_id])
    if rec.get("tenantId") != tenant_id:
        raise PermissionError("tenant isolation: scan")
    return {
        "token": token,
        "kind": TOKEN_KINDS[kind],
        "objectId": object_id,
        "tenantId": tenant_id,
        "releaseHash": rec.get("releaseHash"),
        "record": rec,
        "barcodeHardware": "PARTIAL",
        "liveMachineControl": False,
        "authorizesOperation": False,
    }


def operator_view(pilot: Any, *, tenant_id: str) -> dict[str, Any]:
    console = pilot.console(tenant_id=tenant_id)
    waiting = []
    for wo in pilot.workorders.orders.values():
        if wo.get("tenantId") != tenant_id:
            continue
        if wo.get("state") in {"CANCELLED", "COMPLETED", "REJECTED"}:
            continue
        steps = [s["operation"] for s in (wo.get("traveler") or {}).get("steps") or []]
        done = {o.get("operation") for o in wo.get("ops") or [] if o.get("status") == "COMPLETED"}
        waiting.append(
            {
                "workOrderId": wo["workOrderId"],
                "state": wo["state"],
                "releaseHash": wo.get("releaseHash"),
                "scanToken": make_token("WO", wo["workOrderId"]),
                "openOps": [op for op in steps if op not in done],
                "materialLots": (wo.get("lineage") or {}).get("materialLots") or [],
                "qcHold": wo.get("state") == "QC_HOLD",
                "rework": bool(wo.get("rework")),
                "cartonIds": wo.get("cartonIds") or [],
            }
        )
    leases = []
    dispatcher = getattr(pilot, "dispatcher", None)
    if dispatcher is not None:
        for lease in dispatcher.leases.values():
            if lease.get("tenantId") == tenant_id:
                leases.append(lease)
    inbox: ExceptionInbox | None = getattr(pilot, "inbox", None)
    exceptions = inbox.list(tenant_id=tenant_id) if inbox is not None else []
    journal = getattr(pilot, "journal", None)
    journal_status = journal.verify(tenant_id) if journal is not None else {"ok": True, "status": "MISSING", "label": "MISSING"}
    lots = []
    for lot in pilot.platform.lots.list(tenant_id=tenant_id):
        lots.append(
            {
                "lotId": lot["lotId"],
                "scanToken": make_token("LOT", lot["lotId"]),
                "material": lot.get("material"),
                "quarantined": bool(lot.get("quarantined")),
                **pilot.platform.lots.quantities(lot["lotId"], tenant_id=tenant_id),
            }
        )
    return {
        "tenantId": tenant_id,
        "workOrdersWaiting": waiting,
        "stationLeases": leases,
        "materialLots": lots,
        "exceptions": exceptions,
        "console": console,
        "journal": journal_status,
        "liveCnc": False,
        "liveLaser": False,
        "liveMachineControl": False,
        "barcodeHardware": "PARTIAL",
        "humanApprovalGate": True,
    }


def irreversible_action(
    pilot: Any,
    *,
    tenant_id: str,
    action: str,
    work_order_id: str,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_confirm(payload, action=action)
    wo = pilot.workorders.get(work_order_id)
    if wo.get("tenantId") != tenant_id:
        raise PermissionError("tenant isolation: operator")
    if action == "consume":
        rec = pilot.workorders.consume_reserved(work_order_id, actor=actor)
    elif action == "complete_wo":
        rec = pilot.workorders.complete(work_order_id, actor=actor, qc_ok=True)
    elif action == "finalize_qc":
        rec = pilot.qc.required_final_ok(work_order_id, wo["productFamily"], tenant_id=tenant_id)
        if not rec.get("ok"):
            raise PilotException("QC_FINAL_FAIL")
    else:
        raise PermissionError(action)
    emit(
        pilot,
        f"operator.{action}",
        tenant_id=tenant_id,
        aggregate_type="WorkOrder",
        aggregate_id=work_order_id,
        actor=actor,
        payload={"action": action},
        release_hash=wo.get("releaseHash"),
        semantic_key=f"{tenant_id}::operator::{action}::{work_order_id}",
        source="operator",
    )
    return rec if isinstance(rec, dict) else {"ok": rec}
