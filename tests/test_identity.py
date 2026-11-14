"""Isolated tests for manual operator identity and shift sessions."""

import pytest

from fox3d.identity import OperatorShiftService
from fox3d.journal import EventJournal


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
