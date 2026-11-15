"""Isolated tests for manual operator identity and shift sessions."""

import pytest

from fox3d.identity import OperatorShiftService
from fox3d.journal import EventJournal
from fox3d.outbox import CommitOutbox
from fox3d.pilot import PilotOps
from fox3d.storelock import CrashInjected


@pytest.fixture
def service(tmp_path):
    return OperatorShiftService(tmp_path / "identity")


@pytest.fixture
def operator(service):
    return service.register_operator(
        tenant_id="tenant-a", display_name="Operator A", capabilities=["inspect"]
    )


@pytest.fixture
def shift(service, operator):
    return service.open_shift(
        tenant_id="tenant-a", operator_id=operator["operatorId"], station_id="station-1"
    )


def test_register_and_get_operator(service, operator):
    assert service.get_operator(operator["operatorId"], tenant_id="tenant-a") == operator
    assert operator["enabled"] is True


def test_get_operator_rejects_other_tenant(service, operator):
    with pytest.raises(PermissionError, match="tenant isolation"):
        service.get_operator(operator["operatorId"], tenant_id="tenant-b")


def test_set_enabled_rejects_other_tenant(service, operator):
    with pytest.raises(PermissionError, match="tenant isolation"):
        service.set_enabled(operator["operatorId"], tenant_id="tenant-b", enabled=False)
    assert operator["enabled"] is True


def test_open_shift_rejects_other_tenant(service, operator):
    with pytest.raises(PermissionError, match="tenant isolation"):
        service.open_shift(tenant_id="tenant-b", operator_id=operator["operatorId"], station_id="station-1")


def test_disabled_operator_cannot_open_shift(service, operator):
    service.set_enabled(operator["operatorId"], tenant_id="tenant-a", enabled=False)
    with pytest.raises(PermissionError, match="disabled operator"):
        service.open_shift(tenant_id="tenant-a", operator_id=operator["operatorId"], station_id="station-1")


def test_disabled_operator_cannot_require_active(service, operator, shift):
    service.set_enabled(operator["operatorId"], tenant_id="tenant-a", enabled=False)
    with pytest.raises(PermissionError, match="disabled operator"):
        service.require_active(tenant_id="tenant-a", operator_id=operator["operatorId"], shift_id=shift["shiftId"])


def test_get_shift_rejects_other_tenant(service, shift):
    with pytest.raises(PermissionError, match="tenant isolation"):
        service.get_shift(shift["shiftId"], tenant_id="tenant-b")


def test_close_shift_rejects_wrong_operator(service, shift):
    with pytest.raises(PermissionError, match="operator mismatch"):
        service.close_shift(shift["shiftId"], tenant_id="tenant-a", operator_id="other")
    assert shift["status"] == "OPEN"


def test_close_shift_is_idempotent(service, operator, shift, tmp_path):
    service.journal = EventJournal(tmp_path / "journal")
    first = service.close_shift(shift["shiftId"], tenant_id="tenant-a", operator_id=operator["operatorId"])
    closed_at = first["closedAt"]
    second = service.close_shift(shift["shiftId"], tenant_id="tenant-a", operator_id=operator["operatorId"])
    assert second["status"] == "CLOSED"
    assert closed_at is not None and second["closedAt"] == closed_at
    assert [event["eventType"] for event in service.journal.list("tenant-a")] == ["identity.shift_close"]


def test_closed_shift_cannot_require_active(service, operator, shift):
    service.close_shift(shift["shiftId"], tenant_id="tenant-a", operator_id=operator["operatorId"])
    with pytest.raises(PermissionError, match="closed shift"):
        service.require_active(tenant_id="tenant-a", operator_id=operator["operatorId"], shift_id=shift["shiftId"])


def test_require_active_rejects_missing_capability(service, operator, shift):
    with pytest.raises(PermissionError, match="missing capability"):
        service.require_active(tenant_id="tenant-a", operator_id=operator["operatorId"], shift_id=shift["shiftId"], capability="operate")


def test_require_active_accepts_granted_capability(service, operator, shift):
    result = service.require_active(tenant_id="tenant-a", operator_id=operator["operatorId"], shift_id=shift["shiftId"], capability="inspect")
    assert result["operator"] == operator and result["shift"] == shift


def test_require_active_rejects_another_operators_shift(service, shift):
    other = service.register_operator(tenant_id="tenant-a", display_name="Other")
    with pytest.raises(PermissionError, match="operator mismatch"):
        service.require_active(tenant_id="tenant-a", operator_id=other["operatorId"], shift_id=shift["shiftId"])


def test_enablement_events_record_each_change(service, operator, tmp_path):
    service.journal = EventJournal(tmp_path / "journal")
    for enabled in (False, True, False):
        service.set_enabled(operator["operatorId"], tenant_id="tenant-a", enabled=enabled)
    events = service.journal.list("tenant-a")
    assert [event["eventType"] for event in events] == ["identity.operator_enabled"] * 3
    assert [event["payload"]["enabled"] for event in events] == [False, True, False]
    assert all(event["aggregateId"] == operator["operatorId"] for event in events)
    assert service.journal.verify("tenant-a")["ok"]


def test_state_survives_restart(service, operator, shift):
    open_shift = service.open_shift(tenant_id="tenant-a", operator_id=operator["operatorId"], station_id="station-2")
    service.close_shift(shift["shiftId"], tenant_id="tenant-a", operator_id=operator["operatorId"])
    service.set_enabled(operator["operatorId"], tenant_id="tenant-a", enabled=False)
    restored = OperatorShiftService(service.root)
    assert restored.get_operator(operator["operatorId"], tenant_id="tenant-a") == operator
    assert restored.get_operator(operator["operatorId"], tenant_id="tenant-a")["enabled"] is False
    assert restored.get_shift(shift["shiftId"], tenant_id="tenant-a") == shift
    assert restored.get_shift(shift["shiftId"], tenant_id="tenant-a")["status"] == "CLOSED"
    assert restored.get_shift(open_shift["shiftId"], tenant_id="tenant-a")["status"] == "OPEN"
    restored.set_enabled(operator["operatorId"], tenant_id="tenant-a", enabled=True)
    assert OperatorShiftService(service.root).get_operator(operator["operatorId"], tenant_id="tenant-a")["enabled"] is True


def _reconcile_identity(root):
    identity = OperatorShiftService(root / "identity")
    journal = EventJournal(root / "journal")
    outbox = CommitOutbox(root / "tx")
    pilot = PilotOps.__new__(PilotOps)
    pilot.identity = identity
    result = outbox.reconcile(journal=journal, business_committed=pilot._business_committed)
    return identity, journal, outbox, result


@pytest.fixture
def durable_identity(tmp_path):
    identity = OperatorShiftService(tmp_path / "identity")
    identity.journal = EventJournal(tmp_path / "journal")
    identity.outbox = CommitOutbox(tmp_path / "tx")
    op = identity.register_operator(tenant_id="tenant-a", display_name="A")
    return identity, op


def test_prepare_failure_does_not_change_memory_or_later_persistence(durable_identity, tmp_path):
    identity, op = durable_identity
    identity.outbox._fail_prepare = True
    with pytest.raises(RuntimeError, match="prepare failure"):
        identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=False)
    assert identity.get_operator(op["operatorId"], tenant_id="tenant-a")["enabled"] is True
    identity.register_operator(tenant_id="tenant-a", display_name="B")
    restored, journal, _, _ = _reconcile_identity(tmp_path)
    assert restored.get_operator(op["operatorId"], tenant_id="tenant-a")["enabled"] is True
    assert not [e for e in journal.list("tenant-a") if e["eventType"] == "identity.operator_enabled"]


def test_snapshot_failure_rolls_back_memory(durable_identity, tmp_path, monkeypatch):
    identity, op = durable_identity
    persist = identity.persist
    def fail_persist():
        raise OSError("snapshot failure")
    monkeypatch.setattr(identity, "persist", fail_persist)
    with pytest.raises(OSError, match="snapshot failure"):
        identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=False)
    assert identity.get_operator(op["operatorId"], tenant_id="tenant-a")["enabled"] is True
    monkeypatch.setattr(identity, "persist", persist)
    identity.register_operator(tenant_id="tenant-a", display_name="B")
    restored, journal, _, result = _reconcile_identity(tmp_path)
    assert restored.get_operator(op["operatorId"], tenant_id="tenant-a")["enabled"] is True
    assert result["aborted"] == 1
    assert not [e for e in journal.list("tenant-a") if e["eventType"] == "identity.operator_enabled"]


@pytest.mark.parametrize("point,committed", [("after-outbox-prepare", False), ("after-business-persist", True)])
def test_enablement_recovery_at_commit_boundaries(durable_identity, tmp_path, point, committed):
    identity, op = durable_identity
    identity._crash_mode = point
    with pytest.raises(CrashInjected):
        identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=False)
    restored, journal, outbox, result = _reconcile_identity(tmp_path)
    assert restored.get_operator(op["operatorId"], tenant_id="tenant-a")["enabled"] is (not committed)
    events = [e for e in journal.list("tenant-a") if e["eventType"] == "identity.operator_enabled"]
    assert len(events) == int(committed)
    assert result["finalized"] == int(committed)
    assert result["aborted"] == int(not committed)
    assert not outbox.list_open()


def test_recovery_between_snapshot_and_outbox_marker(durable_identity, tmp_path, monkeypatch):
    identity, op = durable_identity
    def fail_marker(*args, **kwargs):
        raise RuntimeError("marker failure")
    monkeypatch.setattr(identity.outbox, "mark_business_committed", fail_marker)
    with pytest.raises(RuntimeError, match="marker failure"):
        identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=False)
    restored, journal, _, result = _reconcile_identity(tmp_path)
    assert not restored.get_operator(op["operatorId"], tenant_id="tenant-a")["enabled"]
    assert result["finalized"] == 1
    assert len([e for e in journal.list("tenant-a") if e["eventType"] == "identity.operator_enabled"]) == 1


def test_recovery_deduplicates_and_preserves_distinct_toggles(durable_identity, tmp_path, monkeypatch):
    identity, op = durable_identity
    def fail_complete(*args):
        raise RuntimeError("complete failure")
    monkeypatch.setattr(identity.outbox, "complete", fail_complete)
    with pytest.raises(RuntimeError, match="complete failure"):
        identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=False)
    restored, journal, outbox, _ = _reconcile_identity(tmp_path)
    restored.journal, restored.outbox = journal, outbox
    restored.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=True)
    restored.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=False)
    _, journal, _, _ = _reconcile_identity(tmp_path)
    events = [e for e in journal.list("tenant-a") if e["eventType"] == "identity.operator_enabled"]
    assert [e["payload"]["enabled"] for e in events] == [False, True, False]
    assert len({e["semanticKey"] for e in events}) == 3
    assert journal.verify("tenant-a")["ok"]


def test_cleanup_preserves_pending_snapshot_evidence_across_toggles(durable_identity, tmp_path, monkeypatch):
    identity, op = durable_identity
    mark = identity.outbox.mark_business_committed

    def fail_marker(*args, **kwargs):
        raise RuntimeError("marker failure")

    monkeypatch.setattr(identity.outbox, "mark_business_committed", fail_marker)
    with pytest.raises(RuntimeError, match="marker failure"):
        identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=False)
    pending_id = identity.outbox.list_open()[0]["event"]["payload"]["changeId"]
    monkeypatch.setattr(identity.outbox, "mark_business_committed", mark)
    for i in range(30):
        identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=bool(i % 2))
    saved = OperatorShiftService(identity.root).get_operator(op["operatorId"], tenant_id="tenant-a")
    assert pending_id in saved["enablementChangeIds"]
    assert len(saved["enablementChangeIds"]) <= 2
    restored, journal, outbox, result = _reconcile_identity(tmp_path)
    assert result["finalized"] == 1
    assert not outbox.list_open()
    restored.journal, restored.outbox = journal, outbox
    restored.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=True)
    assert len(restored.get_operator(op["operatorId"], tenant_id="tenant-a")["enablementChangeIds"]) == 1
    _, journal, _, _ = _reconcile_identity(tmp_path)
    events = [e for e in journal.list("tenant-a") if e["eventType"] == "identity.operator_enabled"]
    assert len(events) == 32
    assert len({e["semanticKey"] for e in events}) == 32
    assert sum(e["payload"]["changeId"] == pending_id for e in events) == 1
    assert journal.verify("tenant-a")["ok"]


def test_cleanup_legacy_ids_and_preserve_without_outbox(durable_identity):
    identity, op = durable_identity
    op["enablementChangeIds"] = ["old-1", "old-2"]
    identity.persist()
    identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=False)
    assert len(op["enablementChangeIds"]) == 1
    identity.outbox = None
    identity.journal = None
    identity.set_enabled(op["operatorId"], tenant_id="tenant-a", enabled=True)
    assert len(op["enablementChangeIds"]) == 1
    assert OperatorShiftService(identity.root).get_operator(op["operatorId"], tenant_id="tenant-a") == op
