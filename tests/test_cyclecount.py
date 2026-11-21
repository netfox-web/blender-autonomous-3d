"""CycleCountService (manual cycle count, variance waits human approval) — unit/REAL_LOGIC.

Exercised through the ``platform`` fixture as ``platform.pilot.cyclecounts``.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from fox3d.cyclecount import BOOK_CHANGED_MSG, IDEMPOTENCY_CONFLICT_MSG, CycleCountConflict
from fox3d.inventory import read_json
from fox3d.outbox import PREPARED, CommitOutbox
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
    svc.approve(first["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    retried = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=4, reason="r", actor="ops", idempotency_key="k1")
    assert retried["cycleCountId"] == first["cycleCountId"]
    assert retried["status"] == "APPLIED"
    assert len([c for c in svc.counts.values() if c["lotId"] == lot_id]) == 1
    adjustments = [
        row
        for row in platform.lots.get(lot_id, tenant_id=TENANT).get("adjustments") or []
        if row.get("source") == "CYCLE_COUNT"
    ]
    assert len(adjustments) == 1


def _create_events(platform, tenant: str = TENANT) -> list[dict]:
    return [e for e in platform.pilot.journal.list(tenant) if e.get("eventType") == "cyclecount.create"]


def test_same_idempotency_key_on_another_lot_conflicts(platform):
    svc = platform.pilot.cyclecounts
    lot_a = _lot(platform, quantity=10)
    lot_b = _lot(platform, quantity=8)
    before_b = _q(platform, lot_b)
    first = svc.create(
        tenant_id=TENANT, lot_id=lot_a, counted=4, reason="r", actor="ops", idempotency_key="shared"
    )
    with pytest.raises(CycleCountConflict, match=IDEMPOTENCY_CONFLICT_MSG) as raised:
        svc.create(tenant_id=TENANT, lot_id=lot_b, counted=4, reason="r", actor="ops", idempotency_key="shared")
    assert first["cycleCountId"] not in str(raised.value)
    assert lot_a not in str(raised.value)
    assert _q(platform, lot_b) == before_b
    rows = [c for c in svc.counts.values() if c["tenantId"] == TENANT]
    assert [c["cycleCountId"] for c in rows] == [first["cycleCountId"]]
    assert rows[0]["lotId"] == lot_a
    again = svc.create(
        tenant_id=TENANT, lot_id=lot_a, counted=4, reason="r", actor="ops", idempotency_key="shared"
    )
    assert again["cycleCountId"] == first["cycleCountId"]
    other = svc.create(
        tenant_id=TENANT, lot_id=lot_b, counted=4, reason="r", actor="ops", idempotency_key="other-key"
    )
    assert other["lotId"] == lot_b
    assert other["cycleCountId"] != first["cycleCountId"]
    assert len(_create_events(platform)) == 2


def test_same_idempotency_key_different_fields_conflict(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform)
    first = svc.create(
        tenant_id=TENANT,
        lot_id=lot_id,
        counted=4,
        reason="r",
        actor="ops",
        operator_id="op-1",
        shift_id="sh-1",
        idempotency_key="k",
    )
    variants = [
        {"counted": 5, "reason": "r", "actor": "ops", "operator_id": "op-1", "shift_id": "sh-1"},
        {"counted": 0, "reason": "r", "actor": "ops", "operator_id": "op-1", "shift_id": "sh-1"},
        {"counted": 4, "reason": "other", "actor": "ops", "operator_id": "op-1", "shift_id": "sh-1"},
        {"counted": 4, "reason": "r", "actor": "clerk", "operator_id": "op-1", "shift_id": "sh-1"},
        {"counted": 4, "reason": "r", "actor": "ops", "operator_id": "op-2", "shift_id": "sh-1"},
        {"counted": 4, "reason": "r", "actor": "ops", "operator_id": "op-1", "shift_id": "sh-2"},
    ]
    for fields in variants:
        with pytest.raises(CycleCountConflict, match=IDEMPOTENCY_CONFLICT_MSG) as raised:
            svc.create(tenant_id=TENANT, lot_id=lot_id, idempotency_key="k", **fields)
        assert first["cycleCountId"] not in str(raised.value)
        assert lot_id not in str(raised.value)
    kept = svc.counts[first["cycleCountId"]]
    assert kept["counted"] == 4
    assert kept["reason"] == "r"
    assert kept["actor"] == "ops"
    assert kept["operatorId"] == "op-1"
    assert kept["shiftId"] == "sh-1"
    assert len([c for c in svc.counts.values() if c["lotId"] == lot_id]) == 1
    assert len(_create_events(platform)) == 1


def test_idempotency_fingerprint_survives_reload_and_ignores_later_book_changes(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10)
    first = svc.create(
        tenant_id=TENANT, lot_id=lot_id, counted=4, reason="r", actor="ops", idempotency_key="persist-key"
    )
    platform.lots.reserve_sheets(lot_id, tenant_id=TENANT, work_order_id="later", quantity=2)
    plat2 = Platform(root=platform.root, mock_blender=True)
    svc2 = plat2.pilot.cyclecounts
    saved = [
        value
        for value in svc2._idem.values()
        if isinstance(value, dict) and value.get("cycleCountId") == first["cycleCountId"]
    ]
    assert saved == [
        {
            "cycleCountId": first["cycleCountId"],
            "lotId": lot_id,
            "counted": 4,
            "reason": "r",
            "actor": "ops",
            "operatorId": None,
            "shiftId": None,
        }
    ]
    again = svc2.create(
        tenant_id=TENANT, lot_id=lot_id, counted=4, reason="r", actor="ops", idempotency_key="persist-key"
    )
    assert again["cycleCountId"] == first["cycleCountId"]
    assert again["status"] == "WAITING_HUMAN_APPROVAL"
    assert again["systemAvailable"] == first["systemAvailable"]
    lot_b = _lot(plat2, quantity=6)
    with pytest.raises(CycleCountConflict, match=IDEMPOTENCY_CONFLICT_MSG):
        svc2.create(
            tenant_id=TENANT, lot_id=lot_b, counted=4, reason="r", actor="ops", idempotency_key="persist-key"
        )
    assert len([c for c in svc2.counts.values() if c["tenantId"] == TENANT]) == 1


def test_idempotency_key_is_isolated_by_tenant(platform):
    svc = platform.pilot.cyclecounts
    lot_a = _lot(platform, tenant=TENANT, quantity=5)
    lot_b = _lot(platform, tenant=OTHER, quantity=5)
    first = svc.create(
        tenant_id=TENANT, lot_id=lot_a, counted=2, reason="r", actor="ops", idempotency_key="shared"
    )
    second = svc.create(
        tenant_id=OTHER, lot_id=lot_b, counted=2, reason="r", actor="ops", idempotency_key="shared"
    )
    assert first["cycleCountId"] != second["cycleCountId"]
    assert first["lotId"] == lot_a
    assert second["lotId"] == lot_b
    listed = svc.list_for_tenant(tenant_id=OTHER)
    assert {row["cycleCountId"] for row in listed["items"]} == {second["cycleCountId"]}
    with pytest.raises(PermissionError):
        svc.create(tenant_id=OTHER, lot_id=lot_a, counted=2, reason="r", actor="intruder", idempotency_key="shared")


def test_concurrent_same_key_on_two_lots_creates_one(platform):
    svc = platform.pilot.cyclecounts
    lot_a = _lot(platform, quantity=9)
    lot_b = _lot(platform, quantity=9)

    def attempt(lot_id: str) -> str:
        try:
            rec = svc.create(
                tenant_id=TENANT,
                lot_id=lot_id,
                counted=3,
                reason="race",
                actor="ops",
                idempotency_key="race-key",
            )
        except CycleCountConflict as exc:
            assert str(exc) == IDEMPOTENCY_CONFLICT_MSG
            return "conflict"
        return rec["lotId"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (lot_a, lot_b)))
    winners = [lot_id for lot_id in results if lot_id != "conflict"]
    assert results.count("conflict") == 1
    assert winners in ([lot_a], [lot_b])
    rows = [c for c in svc.counts.values() if c.get("reason") == "race"]
    assert len(rows) == 1
    assert rows[0]["lotId"] == winners[0]
    reloaded = Platform(root=platform.root, mock_blender=True)
    kept = [c for c in reloaded.pilot.cyclecounts.counts.values() if c.get("reason") == "race"]
    assert len(kept) == 1
    assert kept[0]["lotId"] == winners[0]
    assert len(_create_events(reloaded)) == 1


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
    rejected = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=1, reason="reject", actor="ops")
    svc.reject(rejected["cycleCountId"], tenant_id=TENANT, actor="sup")

    plat2 = Platform(root=platform.root, mock_blender=True)
    svc2 = plat2.pilot.cyclecounts
    assert svc2 is not svc
    assert svc2.counts[waiting["cycleCountId"]]["status"] == "WAITING_HUMAN_APPROVAL"
    assert svc2.counts[rejected["cycleCountId"]]["status"] == "REJECTED"
    assert svc2.counts[rejected["cycleCountId"]]["rejectedBy"] == "sup"

    # Guards still hold after reload.
    with pytest.raises(PermissionError, match="REJECTED"):
        svc2.approve(rejected["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    with pytest.raises(PermissionError, match="tenant isolation"):
        svc2.approve(waiting["cycleCountId"], tenant_id=OTHER, actor="intruder", payload=CONFIRM)
    # Idempotency index survives too.
    again = svc2.create(tenant_id=TENANT, lot_id=lot_id, counted=5, reason="wait", actor="ops")
    assert again["cycleCountId"] == waiting["cycleCountId"]
    # The waiting count can still be approved after reload when the book is unchanged.
    svc2.approve(waiting["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    applied = svc2.create(tenant_id=TENANT, lot_id=lot_id, counted=6, reason="apply", actor="ops")
    svc2.approve(applied["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    q2 = plat2.lots.quantities(lot_id, tenant_id=TENANT)
    assert q2["available"] == 6
    assert q2["reserved"] == 2
    with pytest.raises(PermissionError, match="applied"):
        svc2.reject(applied["cycleCountId"], tenant_id=TENANT, actor="sup")


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


def test_approve_rejects_when_book_changed_after_create(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10, reserve=2)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=4, reason="stale book", actor="ops")
    platform.lots.reserve_sheets(lot_id, tenant_id=TENANT, work_order_id="after-count", quantity=1)
    with pytest.raises(CycleCountConflict, match=BOOK_CHANGED_MSG):
        svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    after = _q(platform, lot_id)
    assert after["available"] == 7
    assert after["reserved"] == 3
    assert svc.counts[cc["cycleCountId"]]["applied"] is False


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


def test_apply_counted_available_rejects_stale_snapshot_in_transaction(platform):
    lot_id = _lot(platform, quantity=10, reserve=2)
    with pytest.raises(CycleCountConflict, match=BOOK_CHANGED_MSG):
        platform.lots.apply_counted_available(
            lot_id,
            tenant_id=TENANT,
            counted=4,
            actor="ops",
            reason="stale",
            expect_available=10,
            expect_reserved=0,
            expect_consumed=0,
        )
    assert _q(platform, lot_id)["available"] == 8


def test_approve_interleaved_reserve_does_not_inflate_sheet_count(platform, monkeypatch):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform, quantity=10)
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=8, reason="interleave", actor="ops")
    gate = threading.Event()
    reserve_done = threading.Event()
    orig = platform.lots.apply_counted_available

    def gated(*args, **kwargs):
        gate.set()
        reserve_done.wait()
        return orig(*args, **kwargs)

    monkeypatch.setattr(platform.lots, "apply_counted_available", gated)
    errors: list[BaseException] = []

    def approve() -> None:
        try:
            svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
        except CycleCountConflict as exc:
            errors.append(exc)

    def reserve() -> None:
        gate.wait()
        platform.lots.reserve_sheets(lot_id, tenant_id=TENANT, work_order_id="interleaved", quantity=3)
        reserve_done.set()

    t1 = threading.Thread(target=approve)
    t2 = threading.Thread(target=reserve)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors
    after = _q(platform, lot_id)
    assert after["available"] == 7
    assert after["reserved"] == 3
    assert after["sheetCount"] == 10
    assert svc.counts[cc["cycleCountId"]]["applied"] is False


def test_list_for_tenant_syncs_create_and_approve_from_other_instance(tmp_path):
    root = tmp_path / "shared-cyclecount-list"
    writer = Platform(root=root, mock_blender=True)
    reader = Platform(root=root, mock_blender=True)
    lot_id = _lot(writer, quantity=10)
    created = writer.pilot.cyclecounts.create(
        tenant_id=TENANT, lot_id=lot_id, counted=6, reason="floor", actor="ops", idempotency_key="list-sync"
    )
    assert reader.pilot.cyclecounts.counts == {}
    listed = reader.pilot.cyclecounts.list_for_tenant(tenant_id=TENANT)
    assert {row["cycleCountId"] for row in listed["items"]} == {created["cycleCountId"]}
    assert listed["items"][0]["status"] == "WAITING_HUMAN_APPROVAL"
    writer.pilot.cyclecounts.approve(created["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    waiting = reader.pilot.cyclecounts.list_for_tenant(tenant_id=TENANT, status="WAITING_HUMAN_APPROVAL")
    applied = reader.pilot.cyclecounts.list_for_tenant(tenant_id=TENANT, status="APPLIED")
    assert waiting["items"] == []
    assert {row["cycleCountId"] for row in applied["items"]} == {created["cycleCountId"]}
    assert applied["items"][0]["status"] == "APPLIED"
    assert reader.pilot.cyclecounts.list_for_tenant(tenant_id=OTHER)["items"] == []


def test_list_for_tenant_skips_disk_reload_when_store_unchanged(platform):
    svc = platform.pilot.cyclecounts
    lot_id = _lot(platform)
    svc.create(tenant_id=TENANT, lot_id=lot_id, counted=4, reason="cache", actor="ops")
    before_sig = svc._store_sig
    listed = svc.list_for_tenant(tenant_id=TENANT)
    assert listed["total"] == 1
    assert svc._store_sig == before_sig


def test_cross_platform_concurrent_approve_applies_once(tmp_path):
    root = tmp_path / "dual-platform"
    plat = Platform(root=root, mock_blender=True)
    lot_id = _lot(plat, quantity=12)
    cc = plat.pilot.cyclecounts.create(
        tenant_id=TENANT, lot_id=lot_id, counted=7, reason="dual", actor="ops", idempotency_key="dual-cc"
    )
    cid = cc["cycleCountId"]

    def approve_from_fresh() -> dict:
        other = Platform(root=root, mock_blender=True)
        return other.pilot.cyclecounts.approve(cid, tenant_id=TENANT, actor="sup", payload=CONFIRM)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: approve_from_fresh(), range(2)))
    assert results[0]["cycleCountId"] == results[1]["cycleCountId"] == cid
    assert results[0]["status"] == results[1]["status"] == "APPLIED"
    assert {results[0]["approvedBy"], results[1]["approvedBy"]} == {"sup"}
    plat2 = Platform(root=root, mock_blender=True)
    adjs = [
        a
        for a in plat2.lots.get(lot_id, tenant_id=TENANT).get("adjustments") or []
        if a.get("source") == "CYCLE_COUNT"
    ]
    assert len(adjs) == 1
    assert plat2.lots.quantities(lot_id, tenant_id=TENANT)["available"] == 7


def test_peer_reconcile_between_prepare_and_mark_applies_once(tmp_path, monkeypatch):
    """Startup reconcile of a second platform runs after prepare and before mark.

    That is the interleaving that deleted the outbox file under load. Both
    approvals must still apply the count once and leave no open transaction.
    """
    root = tmp_path / "peer-during-prepare"
    plat = Platform(root=root, mock_blender=True)
    lot_id = _lot(plat, quantity=12)
    cc = plat.pilot.cyclecounts.create(
        tenant_id=TENANT, lot_id=lot_id, counted=7, reason="peer", actor="ops", idempotency_key="peer-cc"
    )
    cid = cc["cycleCountId"]
    real_prepare = CommitOutbox.prepare
    state: dict[str, Any] = {"armed": False}

    def prepare_then_peer(
        self: CommitOutbox, event: dict[str, Any], *, expected_generation: int | None = None
    ) -> dict[str, Any]:
        rec = real_prepare(self, event, expected_generation=expected_generation)
        if state["armed"] or event.get("event_type") != "material.cyclecount":
            return rec
        state["armed"] = True
        path = self._path(str(rec["txId"]))
        prepared = read_json(path)
        assert prepared["status"] == PREPARED
        assert prepared["txId"] == rec["txId"]
        peer = Platform(root=root, mock_blender=True)
        state["peer"] = peer
        survived = read_json(path)
        assert survived["status"] == PREPARED
        assert survived["txId"] == rec["txId"]
        return rec

    monkeypatch.setattr(CommitOutbox, "prepare", prepare_then_peer)
    approved = plat.pilot.cyclecounts.approve(cid, tenant_id=TENANT, actor="sup", payload=CONFIRM)
    assert state["armed"] is True
    peer = state["peer"]
    assert isinstance(peer, Platform)
    again = peer.pilot.cyclecounts.approve(cid, tenant_id=TENANT, actor="other", payload=CONFIRM)
    assert approved["status"] == "APPLIED"
    assert again["status"] == "APPLIED"
    assert approved["approvedBy"] == "sup"
    assert again["approvedBy"] == "sup"
    final = Platform(root=root, mock_blender=True)
    adjs = [
        row
        for row in final.lots.get(lot_id, tenant_id=TENANT).get("adjustments") or []
        if row.get("source") == "CYCLE_COUNT"
    ]
    assert len(adjs) == 1
    assert final.lots.quantities(lot_id, tenant_id=TENANT)["available"] == 7
    assert final.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert final.pilot.cyclecounts.list_for_tenant(tenant_id=OTHER)["items"] == []
    events = final.pilot.journal.list(TENANT)
    assert len([ev for ev in events if ev.get("eventType") == "material.cyclecount"]) == 1
    assert len([ev for ev in events if ev.get("eventType") == "cyclecount.approve"]) == 1


def test_committed_adjustment_recovers_after_interruption_and_later_stock_change(tmp_path, monkeypatch):
    root = tmp_path / "recovery"
    platform = Platform(root=root, mock_blender=True)
    lot_id = _lot(platform)
    svc = platform.pilot.cyclecounts
    cc = svc.create(tenant_id=TENANT, lot_id=lot_id, counted=8, reason="recovery", actor="ops")
    original = platform.lots.apply_counted_available

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("interrupted after inventory commit")

    monkeypatch.setattr(platform.lots, "apply_counted_available", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        svc.approve(cc["cycleCountId"], tenant_id=TENANT, actor="first", payload=CONFIRM)
    restarted = Platform(root=root, mock_blender=True)
    with pytest.raises(PermissionError, match="applied"):
        restarted.pilot.cyclecounts.reject(cc["cycleCountId"], tenant_id=TENANT, actor="other")
    restarted.lots.reserve_sheets(lot_id, tenant_id=TENANT, work_order_id="later", quantity=2)

    def approve(_):
        instance = Platform(root=root, mock_blender=True)
        return instance.pilot.cyclecounts.approve(cc["cycleCountId"], tenant_id=TENANT, actor="retry", payload=CONFIRM)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, range(2)))
    assert all(r["status"] == "APPLIED" and r["approvedBy"] == "first" for r in results)
    assert results[0]["after"]["available"] == 8
    final = Platform(root=root, mock_blender=True)
    assert _q(final, lot_id)["available"] == 6
    assert len([a for a in final.lots.get(lot_id, tenant_id=TENANT)["adjustments"] if a.get("cycleCountId") == cc["cycleCountId"]]) == 1


def test_lot_staging_replace_retries_transient_permission_error(tmp_path, monkeypatch):
    from pathlib import Path
    from fox3d import inventory as inv_mod

    root = tmp_path / "staging-retry"
    platform = Platform(root=root, mock_blender=True)
    lot_id = _lot(platform, quantity=12)
    cc = platform.pilot.cyclecounts.create(tenant_id=TENANT, lot_id=lot_id, counted=7, reason="win-lock", actor="ops")
    pauses: list[float] = []
    monkeypatch.setattr(inv_mod.time, "sleep", pauses.append)
    orig_replace = Path.replace
    staging_attempts = 0

    def flaky_staging_replace(self: Path, target: Path) -> Path:
        nonlocal staging_attempts
        if self.name == "lots.json.staging":
            staging_attempts += 1
            if staging_attempts <= 2:
                raise PermissionError(13, "Access is denied")
        return orig_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_staging_replace)
    approved = platform.pilot.cyclecounts.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    assert approved["status"] == "APPLIED"
    assert staging_attempts == 3
    assert pauses == [0.02, 0.04]
    assert not (root / "lots" / "lots.json.staging").exists()
    reloaded = Platform(root=root, mock_blender=True)
    assert _q(reloaded, lot_id)["available"] == 7
    adjs = [a for a in reloaded.lots.get(lot_id, tenant_id=TENANT)["adjustments"] if a.get("source") == "CYCLE_COUNT"]
    assert len(adjs) == 1


def test_lot_staging_replace_sustained_permission_error_rolls_back(tmp_path, monkeypatch):
    from pathlib import Path
    from fox3d import inventory as inv_mod

    root = tmp_path / "staging-fail"
    platform = Platform(root=root, mock_blender=True)
    lot_id = _lot(platform, quantity=12)
    before = _q(platform, lot_id)
    cc = platform.pilot.cyclecounts.create(tenant_id=TENANT, lot_id=lot_id, counted=7, reason="denied", actor="ops")
    pauses: list[float] = []
    monkeypatch.setattr(inv_mod.time, "sleep", pauses.append)
    orig_replace = Path.replace
    staging_attempts = 0

    def denied_staging_replace(self: Path, target: Path) -> Path:
        nonlocal staging_attempts
        if self.name == "lots.json.staging":
            staging_attempts += 1
            raise PermissionError(13, "Access is denied")
        return orig_replace(self, target)

    monkeypatch.setattr(Path, "replace", denied_staging_replace)
    with pytest.raises(PermissionError, match="Access is denied"):
        platform.pilot.cyclecounts.approve(cc["cycleCountId"], tenant_id=TENANT, actor="sup", payload=CONFIRM)
    assert staging_attempts == 6
    assert len(pauses) == 5
    assert _q(platform, lot_id) == before
    assert platform.pilot.cyclecounts.counts[cc["cycleCountId"]]["applied"] is False
    reloaded = Platform(root=root, mock_blender=True)
    assert _q(reloaded, lot_id) == before
    assert reloaded.pilot.cyclecounts.counts[cc["cycleCountId"]]["status"] == "WAITING_HUMAN_APPROVAL"


def test_inventory_read_json_retries_transient_windows_permission_error(tmp_path, monkeypatch):
    from pathlib import Path
    from fox3d import inventory as inv_mod

    target = tmp_path / "lots.json"
    inv_mod.atomic_write_json(target, {"generation": 3, "lots": []})
    pauses: list[float] = []
    monkeypatch.setattr(inv_mod.time, "sleep", pauses.append)
    orig_read_text = Path.read_text
    calls = 0

    def flaky_read_text(self: Path, *args, **kwargs) -> str:
        nonlocal calls
        if self == target:
            calls += 1
            if calls <= 2:
                raise PermissionError(13, "Access is denied")
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    monkeypatch.setattr(inv_mod.sys, "platform", "win32")
    assert inv_mod.read_json(target) == {"generation": 3, "lots": []}
    assert calls == 3
    assert pauses == [0.02, 0.04]

    calls = 0
    pauses.clear()
    monkeypatch.setattr(inv_mod.sys, "platform", "linux")
    with pytest.raises(PermissionError, match="Access is denied"):
        inv_mod.read_json(target)
    assert calls == 1
    assert pauses == []

    def unlinked_mid_read(self: Path, *args, **kwargs) -> str:
        if self == target:
            target.unlink(missing_ok=True)
            raise FileNotFoundError(str(self))
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unlinked_mid_read)
    assert inv_mod.read_json(target) is None
