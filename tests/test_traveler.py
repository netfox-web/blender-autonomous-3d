"""Unit tests for fox3d.traveler — HTML escaping, stale detection, DAM store."""

from __future__ import annotations

import pytest

from fox3d.ids import sha256_bytes, stable_hash
from fox3d.mfg_release import product_snapshot
from fox3d.operator import make_token
from fox3d.traveler import (
    build_traveler_packet,
    resolve_traveler_token,
    store_traveler,
    traveler_html,
)


def _open_wo(platform, tenant: str = "trv"):
    product = platform.kd.build_sku(tenant_id=tenant, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    return platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")


def _content_hash(packet: dict) -> str:
    return stable_hash({k: packet[k] for k in packet if k not in ("packetHash", "generatedAt")})


def test_build_traveler_cross_tenant_denied(platform):
    wo = _open_wo(platform, tenant="ta")
    with pytest.raises(PermissionError, match="tenant isolation"):
        build_traveler_packet(platform.pilot, tenant_id="tb", work_order_id=wo["workOrderId"])


def test_build_traveler_stale_when_release_stale(platform):
    wo = _open_wo(platform, tenant="st")
    rel = platform.pilot.releases.get(wo["releaseId"])
    snap = product_snapshot(platform.kd.build_sku(tenant_id="st", kind="OPEN_SHELF"), family="KD_FURNITURE")
    mutated = dict(snap)
    mutated["engineeringHash"] = "cafebabe" * 8
    platform.pilot.releases.refresh_stale(rel["releaseId"], mutated)
    packet = build_traveler_packet(platform.pilot, tenant_id="st", work_order_id=wo["workOrderId"])
    assert packet["stale"] is True
    assert packet["valid"] is False


def test_build_traveler_stale_when_release_superseded(platform):
    tenant = "sup"
    product = platform.kd.build_sku(tenant_id=tenant, kind="BEDSIDE_CABINET")
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    snap2 = product_snapshot(platform.kd.build_sku(tenant_id=tenant, kind="DESK_RISER"), family="KD_FURNITURE")
    platform.pilot.releases.supersede(rel["releaseId"], snap2, actor="eng", tenant_id=tenant)
    packet = build_traveler_packet(platform.pilot, tenant_id=tenant, work_order_id=wo["workOrderId"])
    assert packet["stale"] is True
    assert packet["valid"] is False


def test_build_traveler_stale_when_release_hash_mismatch(platform):
    wo = _open_wo(platform, tenant="rh")
    rec = platform.pilot.workorders.get(wo["workOrderId"])
    rec["releaseHash"] = "intentional-mismatch"
    packet = build_traveler_packet(platform.pilot, tenant_id="rh", work_order_id=wo["workOrderId"])
    assert packet["stale"] is True
    assert packet["valid"] is False


def test_build_traveler_operations_status_and_machine_command(platform):
    wo = _open_wo(platform, tenant="ops")
    wo_id = wo["workOrderId"]
    rec = platform.pilot.workorders.get(wo_id)
    first_op = rec["traveler"]["steps"][0]["operation"]
    rec.setdefault("ops", []).append({"operation": first_op, "status": "DONE", "opId": "fixture-op-1"})
    packet = build_traveler_packet(platform.pilot, tenant_id="ops", work_order_id=wo_id)
    by_op = {row["operation"]: row for row in packet["operations"]}
    assert by_op[first_op]["status"] == "DONE"
    assert all(row["machineCommand"] is False for row in packet["operations"])
    pending_ops = [s["operation"] for s in wo["traveler"]["steps"][1:]]
    for op_name in pending_ops:
        assert by_op[op_name]["status"] == "PENDING"


def test_packet_hash_stable_excluding_generated_at(platform):
    wo = _open_wo(platform, tenant="ph")
    p1 = build_traveler_packet(platform.pilot, tenant_id="ph", work_order_id=wo["workOrderId"])
    p2 = build_traveler_packet(platform.pilot, tenant_id="ph", work_order_id=wo["workOrderId"])
    assert _content_hash(p1) == _content_hash(p2)
    assert p1["packetHash"] != p2["packetHash"] or p1["generatedAt"] == p2["generatedAt"]


def test_resolve_traveler_token_rejects_non_work_order_token(platform):
    lot = platform.lots.receive(
        tenant_id="tok", material="PB_18_WHITE", thickness=18, quantity=2, actor="ops", source="MANUAL"
    )
    with pytest.raises(PermissionError, match="WorkOrder scan"):
        resolve_traveler_token(platform.pilot, make_token("LOT", lot["lotId"]), tenant_id="tok")


def test_traveler_html_escapes_operation_script_tags(platform):
    wo = _open_wo(platform, tenant="xss")
    wo_id = wo["workOrderId"]
    rec = platform.pilot.workorders.get(wo_id)
    evil = '<script>alert("x")</script>'
    rec["traveler"]["steps"][0]["operation"] = evil
    packet = build_traveler_packet(platform.pilot, tenant_id="xss", work_order_id=wo_id)
    html_out = traveler_html(packet)
    assert "<script>" not in html_out
    assert evil not in html_out
    assert "&lt;script&gt;" in html_out


def test_store_traveler_dam_sha256_matches_html(platform):
    wo = _open_wo(platform, tenant="dam")
    packet = build_traveler_packet(platform.pilot, tenant_id="dam", work_order_id=wo["workOrderId"])
    stored = store_traveler(platform.pilot, packet)
    assert stored["dam"] is not None
    expected = sha256_bytes(stored["html"].encode("utf-8"))
    assert stored["dam"]["sha256"] == expected
    obj = platform.dam.get(stored["dam"]["assetId"], tenant_id="dam")
    assert obj.sha256 == expected
