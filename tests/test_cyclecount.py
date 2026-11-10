"""CycleCountService (manual cycle count, variance waits human approval) — unit/REAL_LOGIC.

Exercised through the ``platform`` fixture as ``platform.pilot.cyclecounts``.
"""

from __future__ import annotations

import pytest

from fox3d.platform import Platform

TENANT = "cc-a"
OTHER = "cc-b"
CONFIRM = {"confirm": True}


def _lot(platform, *, tenant: str = TENANT, quantity: int = 10, reserve: int = 0, consume: int = 0) -> str:
    lot = platform.lots.receive(
        tenant_id=tenant, material="PB_18_WHITE", thickness=18, quantity=quantity, actor="ops", source="MANUAL"
    )
    lot_id = lot["lotId"]
    if consume:
        item = platform.lots.reserve_sheets(lot_id, tenant_id=tenant, work_order_id="wo-consume", quantity=consume)
        platform.lots.consume_reservation(item["reservationId"], tenant_id=tenant, work_order_id="wo-consume")
    if reserve:
        platform.lots.reserve_sheets(lot_id, tenant_id=tenant, work_order_id="wo-reserve", quantity=reserve)
    return lot_id


def _q(platform, lot_id: str, tenant: str = TENANT) -> dict:
    return platform.lots.quantities(lot_id, tenant_id=tenant)


def test_create_without_variance_waits_for_approval(platform):
    lot_id = _lot(platform, quantity=8)
    before = _q(platform, lot_id)
    cc = platform.pilot.cyclecounts.create(tenant_id=TENANT, lot_id=lot_id, counted=8, reason="weekly", actor="ops")
    assert cc["status"] == "WAITING_HUMAN_APPROVAL"
    assert cc["applied"] is False
    assert cc["variance"] == 0
    assert cc["systemAvailable"] == 8
    assert cc["tenantId"] == TENANT
    assert cc["lotId"] == lot_id
    assert cc["notAccounting"] is True
    assert cc["cycleCountHash"]
    assert _q(platform, lot_id) == before


def test_create_with_variance_records_snapshot_and_does_not_touch_lot(platform):
    lot_id = _lot(platform, quantity=10, reserve=2, consume=3)
    before = _q(platform, lot_id)
    assert before["available"] == 5
    short = platform.pilot.cyclecounts.create(tenant_id=TENANT, lot_id=lot_id, counted=3, reason="short", actor="ops")
    over = platform.pilot.cyclecounts.create(tenant_id=TENANT, lot_id=lot_id, counted=7, reason="over", actor="ops")
    assert short["variance"] == -2
    assert over["variance"] == 2
    for cc in (short, over):
        assert cc["status"] == "WAITING_HUMAN_APPROVAL"
        assert cc["systemAvailable"] == 5
        assert cc["systemReserved"] == 2
        assert cc["systemConsumed"] == 3
        assert cc["systemSheetCount"] == 10
    assert short["cycleCountId"] != over["cycleCountId"]
    # Creating a count never moves inventory; only approval does.
    assert _q(platform, lot_id) == before


def test_create_is_idempotent_for_same_key(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform)
    first = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=4, reason="r", actor="ops", idempotency_key="k1")
    again = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=4, reason="r", actor="ops", idempotency_key="k1")
    assert again["cycleCountId"] == first["cycleCountId"]
    assert len([c for c in svc.counts.values() if c["lotId"] == lot_id]) == 1


@pytest.mark.parametrize("payload", [None, {}, {"confirm": False}, {"confirm": "no"}, {"confirm": 0}])
def test_approve_requires_confirm(platform, payload):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10, reserve=2)
    before = _q(platform, lot_id)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=4, reason="r", actor="ops")
    with pytest.raises(PermissionError, match="confirm"):
        svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=payload)
    rec = svc.counts[cc["cycleCountId"]]
    assert rec["status"] == "WAITING_HUMAN_APPROVAL"
    assert rec["applied"] is False
    assert _q(platform, lot_id) == before


def test_approve_applies_counted_and_keeps_reserved_consumed(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10, reserve=2, consume=3)
    before = _q(platform, lot_id)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=4, reason="short by one", actor="ops")
    approved = svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    after = _q(platform, lot_id)
    assert approved["status"] == "APPLIED"
    assert approved["applied"] is True
    assert approved["approvedBy"] == "sup"
    assert after["available"] == 4
    assert after["reserved"] == before["reserved"] == 2
    assert after["consumed"] == before["consumed"] == 3
    assert after["sheetCount"] == 4 + 2 + 3
    assert after["conserved"] is True
    assert approved["reservedUnchanged"] is True
    assert approved["consumedUnchanged"] is True
    assert approved["conserved"] is True
    assert approved["before"]["available"] == 5
    assert approved["after"]["available"] == 4


def test_approve_with_positive_variance_increases_available(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=6, reserve=1)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=9, reason="found extra", actor="ops")
    svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload={"confirm": "true"})
    after = _q(platform, lot_id)
    assert after["available"] == 9
    assert after["reserved"] == 1
    assert after["consumed"] == 0
    assert after["sheetCount"] == 10
    assert after["conserved"] is True


def test_reject_leaves_quantities_unchanged(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10, reserve=2, consume=1)
    before = _q(platform, lot_id)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=1, reason="miscount", actor="ops")
    rejected = svc.reject(cc["cycleCountId"], tenant_id=TENANT, actor="sup")
    assert rejected["status"] == "REJECTED"
    assert rejected["rejectedBy"] == "sup"
    assert rejected["applied"] is False
    assert _q(platform, lot_id) == before
    # A rejected count can never be applied afterwards.
    with pytest.raises(PermissionError, match="REJECTED"):
        svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    assert _q(platform, lot_id) == before
    assert svc.counts[cc["cycleCountId"]]["status"] == "REJECTED"


def test_double_approve_does_not_reapply(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=7, reason="r", actor="ops")
    first = svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    snapshot = dict(first)
    lot_version = platform.lots.get(lot_id, tenant_id=TENANT)["version"]
    # Inventory moves on after the approval (new reservation).
    platform.lots.reserve_sheets(lot_id, tenant_id=TENANT, work_order_id="later", quantity=2)
    after_reserve = _q(platform, lot_id)
    second = svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="someone-else", payload=CONFIRM)
    assert second == snapshot
    assert second["approvedBy"] == "sup"
    # Second approval must not overwrite available back to the old counted value.
    assert _q(platform, lot_id) == after_reserve
    assert after_reserve["available"] == 5
    assert platform.lots.get(lot_id, tenant_id=TENANT)["version"] == lot_version + 1


def test_cannot_reject_after_approve(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=6, reason="r", actor="ops")
    svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    with pytest.raises(PermissionError, match="applied"):
        svc.reject(cc["cycleCountId"], tenant_id=TENANT, actor="sup")
    rec = svc.counts[cc["cycleCountId"]]
    assert rec["status"] == "APPLIED"
    assert "rejectedBy" not in rec
    assert _q(platform, lot_id)["available"] == 6


def test_double_reject_keeps_first_rejection(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10)
    before = _q(platform, lot_id)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=2, reason="r", actor="ops")
    first = svc.reject(cc["cycleCountId"], tenant_id=TENANT, actor="sup-1")
    snapshot = dict(first)
    second = svc.reject(cc["cycleCountId"], tenant_id=TENANT, actor="sup-2")
    assert second == snapshot
    assert second["rejectedBy"] == "sup-1"
    assert _q(platform, lot_id) == before


def test_cross_tenant_create_read_approve_reject_denied(platform):
    svc = platform.pilot.cyclecounts
    lot_a = _lot(platform, tenant=TENANT, quantity=10)
    before = _q(platform, lot_a)
    # Tenant B cannot count tenant A's lot.
    with pytest.raises(PermissionError):
        svc.create(tenant_id=OTHER, lot_id=lot_a, counted=1, reason="r", actor="intruder")
    cc = svc.create(tenant_id=TENANT, lot_id=lot_a, counted=3, reason="r", actor="ops")
    cid = cc["cycleCountId"]
    with pytest.raises(PermissionError, match="tenant isolation"):
        svc.approve(cid, tenant_id=OTHER, actor="intruder", payload=CONFIRM)
    with pytest.raises(PermissionError, match="tenant isolation"):
        svc.reject(cid, tenant_id=OTHER, actor="intruder")
    rec = svc.counts[cid]
    assert rec["status"] == "WAITING_HUMAN_APPROVAL"
    assert "rejectedBy" not in rec
    assert _q(platform, lot_a) == before
    # Same idempotency key from another tenant never resolves to tenant A's record.
    with pytest.raises(PermissionError):
        svc.create(tenant_id=OTHER, lot_id=lot_a, counted=3, reason="r", actor="intruder")
    # Tenant A can still approve normally.
    svc.approve(cid, tenant_id=TENANT, actor="sup", payload=CONFIRM)
    assert _q(platform, lot_a)["available"] == 3
    with pytest.raises(PermissionError, match="tenant isolation"):
        svc.approve(cid, tenant_id=OTHER, actor="intruder", payload=CONFIRM)


def test_state_survives_reload(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10, reserve=2)
    waiting = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=5, reason="wait", actor="ops")
    applied = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=6, reason="apply", actor="ops")
    rejected = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=1, reason="reject", actor="ops")
    svc.approve(applied["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    svc.reject(rejected["cycleCountId"], tenant_id=TENANT, actor="sup")

    plat2 = Platform(root=platform.root, mock_blender=True)
    svc2 = plat2.pilot.cyclecounts
    assert svc2 is not svc
    assert svc2.counts[waiting["cycleCountId"]]["status"] == "WAITING_HUMAN_APPROVAL"
    assert svc2.counts[applied["cycleCountId"]]["status"] == "APPLIED"
    assert svc2.counts[applied["cycleCountId"]]["approvedBy"] == "sup"
    assert svc2.counts[rejected["cycleCountId"]]["status"] == "REJECTED"
    assert svc2.counts[rejected["cycleCountId"]]["rejectedBy"] == "sup"
    q = plat2.lots.quantities(lot_id, tenant_id=TENANT)
    assert q["available"] == 6
    assert q["reserved"] == 2
    assert q["conserved"] is True

    # Guards still hold after reload.
    with pytest.raises(PermissionError, match="REJECTED"):
        svc2.approve(rejected["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    with pytest.raises(PermissionError, match="applied"):
        svc2.reject(applied["cycleCountId"], tenant_id=TENANT, actor="sup")
    with pytest.raises(PermissionError, match="tenant isolation"):
        svc2.approve(waiting["cycleCountId"], tenant_id=OTHER, actor="intruder", payload=CONFIRM)
    # Idempotency index survives too.
    again = svc2.create(tenant_id=TENANT, lot_id=lot_id, counted=5, reason="wait", actor="ops")
    assert again["cycleCountId"] == waiting["cycleCountId"]
    # The waiting count can still be approved after reload.
    svc2.approve(waiting["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    q2 = plat2.lots.quantities(lot_id, tenant_id=TENANT)
    assert q2["available"] == 5
    assert q2["reserved"] == 2


def test_unknown_lot_is_error(platform):
    svc = platform.pilot.cyclecounts
    with pytest.raises((KeyError, PermissionError)):
        svc.create(tenant_id=TENANT, lot_id="no-such-lot", counted=1, reason="r", actor="ops")
    assert svc.counts == {}


def test_unknown_cycle_count_id_is_error(platform):
    svc = platform.pilot.cyclecounts
    with pytest.raises(KeyError):
        svc.approve("no-such-id", tenant_id=TENANT, actor="sup", payload=CONFIRM)
    with pytest.raises(KeyError):
        svc.reject("no-such-id", tenant_id=TENANT, actor="sup")


def test_negative_count_cannot_be_applied(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=5)
    before = _q(platform, lot_id)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=-1, reason="typo", actor="ops")
    with pytest.raises(PermissionError, match="negative"):
        svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    rec = svc.counts[cc["cycleCountId"]]
    assert rec["status"] == "WAITING_HUMAN_APPROVAL"
    assert rec["applied"] is False
    assert _q(platform, lot_id) == before
