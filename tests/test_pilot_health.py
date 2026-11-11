"""Tenant-scoped pilot health counters and fail-closed status."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.observability import pilot_health


@pytest.fixture
def health_pilot(platform):
    pilot = platform.pilot
    pilot.workorders.orders.update({
        "a1": {"tenantId": "a", "state": "IN_PROGRESS", "traveler": {"steps": [
            {"operation": "CUT"}, {"operation": "DRILL"}, {"operation": "PACK"},
        ]}, "ops": [{"operation": "CUT", "status": "COMPLETED"},
                     {"operation": "DRILL", "status": "STARTED"}]},
        "a2": {"tenantId": "a", "state": "IN_PROGRESS", "traveler": {"steps": [{"operation": "QC"}]}},
        "a3": {"tenantId": "a", "state": "DRAFT"},
        "b1": {"tenantId": "b", "state": "COMPLETED", "traveler": {"steps": [{"operation": "CUT"}]}},
    })
    for tenant, statuses in [("a", ["LEASED", "ACKED", "STARTED", "EXPIRED", "COMPLETED", "CANCELLED"]),
                             ("b", ["LEASED", "EXPIRED", "EXPIRED"])]:
        for i, status in enumerate(statuses):
            pilot.dispatcher.leases[f"{tenant}{i}"] = {"tenantId": tenant, "status": status}
    for tenant, results in [("a", [True, True, False]), ("b", [True, False, False])]:
        for i, ok in enumerate(results):
            pilot.qc.checks[f"{tenant}{i}"] = {"tenantId": tenant, "ok": ok}
    for tenant, dispositions in [("a", ["REWORK", "REWORK", "SCRAP"]), ("b", ["REWORK"])]:
        for i, disposition in enumerate(dispositions):
            pilot.qc.defects[f"{tenant}{i}"] = {"tenantId": tenant, "disposition": disposition}
    for tenant, codes in [("a", ["MATERIAL_SHORTAGE", "MATERIAL_SHORTAGE", "STALE_RELEASE", "PACKING_MISMATCH", "WRONG_MATERIAL"]),
                          ("b", ["MATERIAL_SHORTAGE", "STALE_RELEASE", "STALE_RELEASE", "PACKING_MISMATCH"])]:
        for code in codes:
            pilot.inbox.record(tenant_id=tenant, code=code)
    return pilot


def test_work_order_state_and_queued_operations(health_pilot):
    health = pilot_health(health_pilot, tenant_id="a")
    assert health["workOrdersByState"] == {"IN_PROGRESS": 2, "DRAFT": 1}
    assert health["queuedManualOperations"] == 3


def test_station_lease_counts(health_pilot):
    health = pilot_health(health_pilot, tenant_id="a")
    assert health["activeStationLeases"] == 3
    assert health["expiredStationLeases"] == 1


def test_qc_counts(health_pilot):
    health = pilot_health(health_pilot, tenant_id="a")
    assert (health["qcPass"], health["qcFail"], health["qcRework"]) == (2, 1, 2)


def test_exception_counts(health_pilot):
    health = pilot_health(health_pilot, tenant_id="a")
    assert (health["reservationShortageCount"], health["staleReleaseRejects"], health["packingExceptions"]) == (2, 1, 1)


def test_other_tenant_and_empty_tenant_are_isolated(health_pilot):
    health = pilot_health(health_pilot, tenant_id="b")
    assert health["workOrdersByState"] == {"COMPLETED": 1}
    assert [health[k] for k in ("queuedManualOperations", "activeStationLeases", "expiredStationLeases",
            "qcPass", "qcFail", "qcRework", "reservationShortageCount", "staleReleaseRejects", "packingExceptions")] == [1, 1, 2, 1, 2, 1, 1, 2, 1]
    empty = pilot_health(health_pilot, tenant_id="empty")
    assert empty["workOrdersByState"] == {}
    assert all(empty[k] == 0 for k in ("queuedManualOperations", "activeStationLeases", "expiredStationLeases",
               "qcPass", "qcFail", "qcRework", "reservationShortageCount", "staleReleaseRejects", "packingExceptions"))


def test_optional_components_missing():
    pilot = SimpleNamespace(workorders=SimpleNamespace(orders={}), qc=SimpleNamespace(checks={}, defects={}))
    health = pilot_health(pilot, tenant_id="a")
    assert health["activeStationLeases"] == health["expiredStationLeases"] == 0
    assert health["reservationShortageCount"] == health["staleReleaseRejects"] == health["packingExceptions"] == 0
    assert health["journalIntegrity"]["ok"] is False
    assert health["journalIntegrity"]["status"] == "MISSING"


def test_safety_labels(health_pilot):
    for tenant in ("a", "b", "empty"):
        health = pilot_health(health_pilot, tenant_id=tenant)
        assert health["liveCnc"] == health["liveLaser"] == "BLOCKED"
        assert health["liveMachineControl"] is False
        assert health["notFactorySla"] is True


def test_health_api_matches_direct_result(platform, health_pilot):
    client = TestClient(create_app(platform))
    for tenant in ("a", "b", "empty"):
        response = client.get("/api/pilot/health", headers={"X-Tenant-Id": tenant})
        assert response.status_code == 200
        actual = response.json()
        expected = pilot_health(health_pilot, tenant_id=tenant)
        assert actual.pop("at")
        assert expected.pop("at")
        assert actual == expected
