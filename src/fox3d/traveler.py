"""Versioned manual traveler packet. Uses existing WorkOrder/releaseHash."""

from __future__ import annotations

import json
from typing import Any

from fox3d.ids import stable_hash
from fox3d.infra import utcnow
from fox3d.operator import make_token, parse_token, resolve_scan


def _now() -> str:
    return utcnow().isoformat()


def build_traveler_packet(pilot: Any, *, tenant_id: str, work_order_id: str) -> dict[str, Any]:
    wo = pilot.workorders.get(work_order_id)
    if wo.get("tenantId") != tenant_id:
        raise PermissionError("tenant isolation: traveler")
    rel = None
    stale = False
    if pilot.releases is not None and wo.get("releaseId"):
        rel = pilot.releases.get(wo["releaseId"])
        if rel.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: traveler release")
        if rel.get("stale") or rel.get("status") in {"STALE", "SUPERSEDED", "CANCELLED"}:
            stale = True
        if rel.get("releaseHash") != wo.get("releaseHash"):
            stale = True
    steps = []
    done = {o.get("operation"): o for o in wo.get("ops") or []}
    for step in (wo.get("traveler") or {}).get("steps") or []:
        op = done.get(step["operation"]) or {}
        steps.append(
            {
                "seq": step.get("seq"),
                "operation": step["operation"],
                "status": op.get("status") or "PENDING",
                "opId": op.get("opId"),
                "machineCommand": False,
            }
        )
    packet = {
        "schemaVersion": "fox3d.traveler.v1",
        "tenantId": tenant_id,
        "workOrderId": work_order_id,
        "releaseId": wo.get("releaseId"),
        "releaseHash": wo.get("releaseHash"),
        "engineeringHash": (rel or {}).get("engineeringHash") or (wo.get("lineage") or {}).get("engineeringHash"),
        "bomHash": (rel or {}).get("bomHash") or (wo.get("lineage") or {}).get("bomHash"),
        "qcPlanHash": wo.get("qcPlanHash"),
        "state": wo.get("state"),
        "stale": stale,
        "valid": not stale,
        "operations": steps,
        "materialLots": (wo.get("lineage") or {}).get("materialLots") or [],
        "reservations": wo.get("reservations") or [],
        "packing": wo.get("cartonIds") or [],
        "scanToken": make_token("WO", work_order_id),
        "authorizesOperation": False,
        "barcodeHardware": "PARTIAL",
        "truthLabel": "REAL_LOGIC",
        "liveMachineControl": False,
        "generatedAt": _now(),
    }
    packet["packetHash"] = stable_hash({k: packet[k] for k in packet if k != "packetHash"})
    return packet


def traveler_html(packet: dict[str, Any]) -> str:
    ops = "".join(f"<li>{row['seq']}. {row['operation']} — {row['status']}</li>" for row in packet.get("operations") or [])
    return (
        "<html><body>"
        f"<h1>Manual Traveler</h1>"
        f"<p>WO {packet.get('workOrderId')}</p>"
        f"<p>releaseHash {packet.get('releaseHash')}</p>"
        f"<p>scan {packet.get('scanToken')}</p>"
        f"<p>stale={packet.get('stale')} valid={packet.get('valid')}</p>"
        f"<ol>{ops}</ol>"
        "<p>LIVE_CNC=BLOCKED LIVE_LASER=BLOCKED</p>"
        "</body></html>"
    )


def resolve_traveler_token(pilot: Any, token: str, *, tenant_id: str) -> dict[str, Any]:
    kind, object_id = parse_token(token)
    if kind != "WO":
        raise PermissionError("traveler token must be a WorkOrder scan")
    scanned = resolve_scan(pilot, token, tenant_id=tenant_id)
    packet = build_traveler_packet(pilot, tenant_id=tenant_id, work_order_id=object_id)
    scanned["packet"] = packet
    scanned["authorizesOperation"] = False
    scanned["valid"] = bool(packet.get("valid"))
    return scanned


def store_traveler(pilot: Any, packet: dict[str, Any]) -> dict[str, Any]:
    html = traveler_html(packet)
    asset = None
    if getattr(pilot, "platform", None) is not None and getattr(pilot.platform, "dam", None) is not None:
        obj = pilot.platform.dam.put(
            tenant_id=packet["tenantId"],
            kind="traveler",
            name=f"{packet['workOrderId']}.html",
            data=html.encode("utf-8"),
            metadata={"releaseHash": packet.get("releaseHash"), "packetHash": packet.get("packetHash")},
        )
        asset = {"assetId": obj.asset_id, "sha256": obj.sha256, "path": obj.path}
    return {"packet": packet, "html": html, "dam": asset, "json": json.dumps(packet, default=str)}
