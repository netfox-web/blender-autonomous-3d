"""Pilot floor admin APIs: stations list/status, leases list, exception inbox lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.journal import JournalCommitError
from fox3d.platform import Platform
from fox3d.recovery import ExceptionInbox
from fox3d.station import StationRegistry
from fox3d.storelock import CrashInjected
from fox3d.workorder import STRICT_STOCK

TENANT = "sonaqueen-home"
OTHER = "other-tenant"
HEADERS = {"X-Tenant-Id": TENANT}
OTHER_HEADERS = {"X-Tenant-Id": OTHER}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def _ready_wo(platform, tenant: str = TENANT):
    product = platform.kd.build_sku(tenant_id=tenant, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    nest = (rel.get("snapshot") or {}).get("nesting") or {}
    row = {
        "supplierLot": f"{tenant}-lot",
        "material": nest.get("sheetSku") or "PB_18_WHITE",
        "thickness": nest.get("thickness") or 18,
        "quantity": 20,
    }
    sheet_mm = nest.get("sheetMm") or []
    if len(sheet_mm) >= 2:
        row["length"] = float(sheet_mm[0])
        row["width"] = float(sheet_mm[1])
    platform.pilot.receiving.import_receipt(row, tenant_id=tenant, actor="recv", source="MANUAL", idempotency_key=f"{tenant}-lot")
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    platform.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    platform.pilot.workorders.reserve_materials(wo["workOrderId"], actor="ops", tenant_id=tenant, allocation_policy=STRICT_STOCK)
    return wo


def _register_station(client: TestClient, station_id: str | None = None, status: str = "ONLINE") -> str:
    body: dict = {"capabilities": ["PANEL_CUTTING_MANUAL"], "actor": "test", "status": status}
    if station_id:
        body["stationId"] = station_id
    res = client.post("/api/pilot/stations", headers=HEADERS, json=body)
    assert res.status_code == 200
    return res.json()["stationId"]


def test_stations_list_pagination_and_tenant_isolation(client: TestClient) -> None:
    _register_station(client, "st-a")
    _register_station(client, "st-b")
    all_st = client.get("/api/pilot/stations", headers=HEADERS)
    assert all_st.status_code == 200
    body = all_st.json()
    assert body["total"] >= 2
    assert len(body["items"]) == body["total"]

    page = client.get("/api/pilot/stations?offset=0&limit=1", headers=HEADERS)
    assert page.status_code == 200
    pg = page.json()
    assert pg["limit"] == 1
    assert len(pg["items"]) == 1
    assert pg["total"] >= 2

    other_list = client.get("/api/pilot/stations", headers=OTHER_HEADERS).json()["items"]
    assert not any(s.get("stationId") in {"st-a", "st-b"} for s in other_list)


def test_station_status_put_and_dispatch_blocked_when_maintenance(client: TestClient, platform) -> None:
    wo = _ready_wo(platform)
    op = wo["traveler"]["steps"][0]["operation"]
    station_id = _register_station(client, "st-maint")

    ok = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "ACTIVE", "actor": "admin"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "ACTIVE"

    maint = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "scheduled"},
    )
    assert maint.status_code == 200
    assert maint.json()["status"] == "MAINTENANCE"

    blocked = client.post(
        "/api/pilot/dispatch",
        headers=HEADERS,
        json={"workOrderId": wo["workOrderId"], "operation": op, "stationId": station_id, "actor": "test"},
    )
    assert blocked.status_code == 409

    foreign = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=OTHER_HEADERS,
        json={"status": "DISABLED", "actor": "x"},
    )
    assert foreign.status_code == 404


def test_leases_list_filters(client: TestClient, platform) -> None:
    wo = _ready_wo(platform)
    op = wo["traveler"]["steps"][0]["operation"]
    station_id = _register_station(client, "st-lease")
    dispatch = client.post(
        "/api/pilot/dispatch",
        headers=HEADERS,
        json={"workOrderId": wo["workOrderId"], "operation": op, "stationId": station_id, "actor": "test"},
    )
    assert dispatch.status_code == 200
    lease_id = dispatch.json()["leaseId"]

    all_leases = client.get("/api/pilot/leases", headers=HEADERS)
    assert all_leases.status_code == 200
    assert any(item["leaseId"] == lease_id for item in all_leases.json()["items"])

    filtered = client.get(f"/api/pilot/leases?stationId={station_id}&status=LEASED", headers=HEADERS)
    assert filtered.status_code == 200
    items = filtered.json()["items"]
    assert items and all(i.get("stationId") == station_id and i.get("status") == "LEASED" for i in items)

    assert client.get("/api/pilot/leases?offset=0&limit=1", headers=HEADERS).json()["limit"] == 1


def test_exception_ack_resolve_persists_and_idempotent(client: TestClient, platform, tmp_path: Path) -> None:
    _ = tmp_path
    exc = platform.pilot.inbox.record(
        tenant_id=TENANT,
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-test",
        actor="seed",
        detail="short",
    )
    exc_id = exc["exceptionId"]

    ack1 = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin", "note": "seen"})
    assert ack1.status_code == 200
    assert ack1.json()["status"] == "ACKNOWLEDGED"
    assert ack1.json()["acknowledgedBy"] == "admin"

    ack2 = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin"})
    assert ack2.status_code == 200
    assert ack2.json()["status"] == "ACKNOWLEDGED"

    resolve1 = client.post(
        f"/api/pilot/exceptions/{exc_id}/resolve",
        headers=HEADERS,
        json={"actor": "admin", "resolution": "replenished"},
    )
    assert resolve1.status_code == 200
    assert resolve1.json()["status"] == "RESOLVED"

    resolve2 = client.post(f"/api/pilot/exceptions/{exc_id}/resolve", headers=HEADERS, json={"actor": "admin"})
    assert resolve2.status_code == 200
    assert resolve2.json()["status"] == "RESOLVED"

    ack_after = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin"})
    assert ack_after.status_code == 409

    platform.pilot.inbox.load()
    reloaded = platform.pilot.inbox.get(exc_id, tenant_id=TENANT)
    assert reloaded["status"] == "RESOLVED"

    open_only = client.get("/api/pilot/exceptions?status=OPEN", headers=HEADERS)
    assert open_only.status_code == 200
    assert exc_id not in {i["exceptionId"] for i in open_only.json()["items"]}

    foreign = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=OTHER_HEADERS, json={"actor": "x"})
    assert foreign.status_code == 404


def test_station_status_cycle_with_different_and_identical_notes(client: TestClient, platform) -> None:
    station_id = _register_station(client, "st-cycle")
    steps = [
        ("MAINTENANCE", "first"),
        ("ACTIVE", None),
        ("MAINTENANCE", "second"),
        ("ACTIVE", None),
        ("MAINTENANCE", "second"),
        ("DISABLED", "retired"),
        ("ACTIVE", None),
    ]
    for status, note in steps:
        body: dict[str, object] = {"status": status, "actor": "admin"}
        if note is not None:
            body["note"] = note
        res = client.put(f"/api/pilot/stations/{station_id}/status", headers=HEADERS, json=body)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == status
        if note is not None:
            assert res.json()["statusNote"] == note
        else:
            assert "statusNote" not in res.json()

    reloaded = StationRegistry(platform.root / "stations").get(station_id, tenant_id=TENANT)
    assert reloaded["status"] == "ACTIVE"

    events = [
        ev
        for ev in platform.pilot.journal.list(TENANT)
        if ev.get("eventType") == "station.status" and ev.get("aggregateId") == station_id
    ]
    assert [(ev["payload"]["status"], ev["payload"]["note"]) for ev in events] == steps
    assert len({ev["semanticKey"] for ev in events}) == len(steps)
    assert len({ev["payload"]["transitionId"] for ev in events}) == len(steps)
    assert platform.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert platform.pilot.journal.verify(TENANT)["ok"] is True


def test_station_status_transition_id_retry_conflict_and_interleaved_replay(client: TestClient, platform) -> None:
    station_id = _register_station(client, "st-tid")

    first = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "first", "transitionId": "tr-1"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "MAINTENANCE"

    replay = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "first", "transitionId": "tr-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "MAINTENANCE"

    conflict_status = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "ACTIVE", "actor": "admin", "transitionId": "tr-1"},
    )
    assert conflict_status.status_code == 409
    assert "tr-1" not in conflict_status.text
    assert platform.pilot.stations.get(station_id, tenant_id=TENANT)["status"] == "MAINTENANCE"

    conflict_note = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "other", "transitionId": "tr-1"},
    )
    assert conflict_note.status_code == 409
    assert platform.pilot.stations.get(station_id, tenant_id=TENANT)["statusNote"] == "first"

    second = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "ACTIVE", "actor": "admin", "idempotencyKey": "tr-2"},
    )
    assert second.status_code == 200
    assert second.json()["status"] == "ACTIVE"

    stale_replay = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "first", "transitionId": "tr-1"},
    )
    assert stale_replay.status_code == 200
    assert platform.pilot.stations.get(station_id, tenant_id=TENANT)["status"] == "ACTIVE"

    events = [
        ev
        for ev in platform.pilot.journal.list(TENANT)
        if ev.get("eventType") == "station.status" and ev.get("aggregateId") == station_id
    ]
    assert [(ev["payload"]["transitionId"], ev["payload"]["status"]) for ev in events] == [
        ("tr-1", "MAINTENANCE"),
        ("tr-2", "ACTIVE"),
    ]
    assert platform.pilot.journal.verify(TENANT)["ok"] is True


def test_station_status_prepare_and_journal_failure_recovery(client: TestClient, platform, tmp_path: Path) -> None:
    station_id = _register_station(client, "st-fail")

    # 1. Prepare failure leaves status unchanged in memory and on disk.
    platform.pilot.outbox._fail_prepare = True
    prep_fail = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "first"},
    )
    assert prep_fail.status_code == 503
    assert platform.pilot.stations.get(station_id, tenant_id=TENANT)["status"] == "ONLINE"
    assert StationRegistry(platform.root / "stations").get(station_id, tenant_id=TENANT)["status"] == "ONLINE"
    assert platform.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert platform.pilot.journal.verify(TENANT)["ok"] is True

    # 2. Journal failure after business persist recovers on retry (without and with explicit transitionId).
    platform.pilot.journal._fail_next = True
    j_fail_1 = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "first"},
    )
    assert j_fail_1.status_code == 503
    assert len(platform.pilot.outbox.list_open(tenant_id=TENANT)) == 1
    assert platform.pilot.journal.verify(TENANT)["ok"] is False

    retry_1 = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "first"},
    )
    assert retry_1.status_code == 200
    assert retry_1.json()["status"] == "MAINTENANCE"
    assert platform.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert platform.pilot.journal.verify(TENANT)["ok"] is True

    active = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "ACTIVE", "actor": "admin"},
    )
    assert active.status_code == 200

    platform.pilot.journal._fail_next = True
    j_fail_2 = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "second", "transitionId": "retry-tid"},
    )
    assert j_fail_2.status_code == 503
    assert platform.pilot.journal.verify(TENANT)["ok"] is False

    retry_2 = client.put(
        f"/api/pilot/stations/{station_id}/status",
        headers=HEADERS,
        json={"status": "MAINTENANCE", "actor": "admin", "note": "second", "transitionId": "retry-tid"},
    )
    assert retry_2.status_code == 200
    assert platform.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert platform.pilot.journal.verify(TENANT)["ok"] is True

    events = [
        ev
        for ev in platform.pilot.journal.list(TENANT)
        if ev.get("eventType") == "station.status" and ev.get("aggregateId") == station_id
    ]
    assert [(ev["payload"]["status"], ev["payload"]["note"]) for ev in events] == [
        ("MAINTENANCE", "first"),
        ("ACTIVE", None),
        ("MAINTENANCE", "second"),
    ]

    # 3. Crash boundaries reconcile accurately across Platform restarts.
    crash_root = tmp_path / "plat-station-crash"
    plat = Platform(root=crash_root, mock_blender=True)
    st = plat.pilot.stations.register(tenant_id=TENANT, capabilities=["PANEL_CUTTING_MANUAL"], station_id="st-crash", actor="op")

    plat.pilot.stations._crash_mode = "after-outbox-prepare"
    with pytest.raises(CrashInjected):
        plat.pilot.stations.set_status(
            st["stationId"],
            tenant_id=TENANT,
            status="MAINTENANCE",
            actor="admin",
            note="crash-prep",
            transition_id="c-prep",
        )
    plat.pilot.stations._crash_mode = ""
    assert plat.pilot.stations.get(st["stationId"], tenant_id=TENANT)["status"] == "ONLINE"
    assert len(plat.pilot.outbox.list_open(tenant_id=TENANT)) == 1

    plat2 = Platform(root=crash_root, mock_blender=True)
    assert plat2.pilot.stations.get(st["stationId"], tenant_id=TENANT)["status"] == "ONLINE"
    assert [e for e in plat2.pilot.journal.list(TENANT) if e.get("eventType") == "station.status"] == []
    assert plat2.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert plat2.pilot.journal.verify(TENANT)["ok"] is True

    plat2.pilot.stations._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat2.pilot.stations.set_status(
            st["stationId"],
            tenant_id=TENANT,
            status="MAINTENANCE",
            actor="admin",
            note="crash-biz",
            transition_id="c-biz",
        )
    plat2.pilot.stations._crash_mode = ""
    assert StationRegistry(crash_root / "stations").get(st["stationId"], tenant_id=TENANT)["status"] == "MAINTENANCE"
    assert plat2.pilot.journal.verify(TENANT)["ok"] is False

    plat3 = Platform(root=crash_root, mock_blender=True)
    assert plat3.pilot.stations.get(st["stationId"], tenant_id=TENANT)["status"] == "MAINTENANCE"
    c_events = [e for e in plat3.pilot.journal.list(TENANT) if e.get("eventType") == "station.status"]
    assert len(c_events) == 1
    assert c_events[0]["payload"] == {"status": "MAINTENANCE", "note": "crash-biz", "transitionId": "c-biz"}
    assert plat3.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert plat3.pilot.journal.verify(TENANT)["ok"] is True


def test_exception_ack_and_resolve_journal_failure_and_retry(client: TestClient, platform, tmp_path: Path) -> None:
    exc = platform.pilot.inbox.record(
        tenant_id=TENANT,
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-retry",
        actor="seed",
        detail="short",
    )
    exc_id = exc["exceptionId"]

    # Outbox prepare failure leaves status OPEN on disk and in memory.
    platform.pilot.outbox._fail_prepare = True
    ack_prep = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin", "note": "seen"})
    assert ack_prep.status_code == 503
    assert platform.pilot.inbox.get(exc_id, tenant_id=TENANT)["status"] == "OPEN"
    assert ExceptionInbox(platform.root / "exceptions").get(exc_id, tenant_id=TENANT)["status"] == "OPEN"
    assert platform.pilot.outbox.list_open(tenant_id=TENANT) == []

    # Journal failure during ack -> retry completes missing exception.acknowledged event.
    platform.pilot.journal._fail_next = True
    ack_fail = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin", "note": "seen"})
    assert ack_fail.status_code == 503
    assert not any(
        e.get("eventType") == "exception.acknowledged" and e.get("aggregateId") == exc_id
        for e in platform.pilot.journal.list(TENANT)
    )
    assert len(platform.pilot.outbox.list_open(tenant_id=TENANT)) == 1
    assert platform.pilot.journal.verify(TENANT)["ok"] is False

    ack_retry = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin"})
    assert ack_retry.status_code == 200
    assert ack_retry.json()["status"] == "ACKNOWLEDGED"
    ack_events = [
        e
        for e in platform.pilot.journal.list(TENANT)
        if e.get("eventType") == "exception.acknowledged" and e.get("aggregateId") == exc_id
    ]
    assert len(ack_events) == 1
    assert ack_events[0]["payload"] == {"note": "seen", "status": "ACKNOWLEDGED"}
    assert platform.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert platform.pilot.journal.verify(TENANT)["ok"] is True

    # Idempotent 3rd ack does not duplicate the event.
    assert client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json={"actor": "admin"}).status_code == 200
    assert len([
        e
        for e in platform.pilot.journal.list(TENANT)
        if e.get("eventType") == "exception.acknowledged" and e.get("aggregateId") == exc_id
    ]) == 1

    # Outbox prepare failure on resolve keeps ACKNOWLEDGED status unchanged.
    platform.pilot.outbox._fail_prepare = True
    res_prep = client.post(
        f"/api/pilot/exceptions/{exc_id}/resolve",
        headers=HEADERS,
        json={"actor": "admin", "resolution": "replenished"},
    )
    assert res_prep.status_code == 503
    assert platform.pilot.inbox.get(exc_id, tenant_id=TENANT)["status"] == "ACKNOWLEDGED"
    assert ExceptionInbox(platform.root / "exceptions").get(exc_id, tenant_id=TENANT)["status"] == "ACKNOWLEDGED"

    # Journal failure during resolve -> retry completes missing exception.resolved event.
    platform.pilot.journal._fail_next = True
    res_fail = client.post(
        f"/api/pilot/exceptions/{exc_id}/resolve",
        headers=HEADERS,
        json={"actor": "admin", "resolution": "replenished"},
    )
    assert res_fail.status_code == 503
    assert not any(
        e.get("eventType") == "exception.resolved" and e.get("aggregateId") == exc_id
        for e in platform.pilot.journal.list(TENANT)
    )
    assert len(platform.pilot.outbox.list_open(tenant_id=TENANT)) == 1
    assert platform.pilot.journal.verify(TENANT)["ok"] is False

    res_retry = client.post(f"/api/pilot/exceptions/{exc_id}/resolve", headers=HEADERS, json={"actor": "admin"})
    assert res_retry.status_code == 200
    assert res_retry.json()["status"] == "RESOLVED"
    res_events = [
        e
        for e in platform.pilot.journal.list(TENANT)
        if e.get("eventType") == "exception.resolved" and e.get("aggregateId") == exc_id
    ]
    assert len(res_events) == 1
    assert res_events[0]["payload"] == {"resolution": "replenished", "status": "RESOLVED"}
    assert platform.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert platform.pilot.journal.verify(TENANT)["ok"] is True

    # Idempotent 3rd resolve does not duplicate the event.
    assert client.post(f"/api/pilot/exceptions/{exc_id}/resolve", headers=HEADERS, json={"actor": "admin"}).status_code == 200
    assert len([
        e
        for e in platform.pilot.journal.list(TENANT)
        if e.get("eventType") == "exception.resolved" and e.get("aggregateId") == exc_id
    ]) == 1

    # Ack fails on journal, then operator immediately resolves: both events commit cleanly.
    exc2 = platform.pilot.inbox.record(
        tenant_id=TENANT,
        code="STATION_OFFLINE",
        work_order_id="wo-ack-then-resolve",
        actor="seed",
    )
    exc2_id = exc2["exceptionId"]
    platform.pilot.journal._fail_next = True
    with pytest.raises(JournalCommitError):
        platform.pilot.inbox.acknowledge(exc2_id, tenant_id=TENANT, actor="op", note="urgent")
    platform.pilot.inbox.resolve(exc2_id, tenant_id=TENANT, actor="mgr", resolution="handled")
    exc2_events = [
        e
        for e in platform.pilot.journal.list(TENANT)
        if e.get("aggregateId") == exc2_id and e.get("eventType") in {"exception.acknowledged", "exception.resolved"}
    ]
    assert [(e["eventType"], e["payload"]) for e in exc2_events] == [
        ("exception.acknowledged", {"note": "urgent", "status": "ACKNOWLEDGED"}),
        ("exception.resolved", {"resolution": "handled", "status": "RESOLVED"}),
    ]
    assert platform.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert platform.pilot.journal.verify(TENANT)["ok"] is True

    # Crash boundaries on Platform restarts for both acknowledge and resolve.
    crash_root = tmp_path / "plat-exc-crash"
    plat = Platform(root=crash_root, mock_blender=True)
    exc3 = plat.pilot.inbox.record(tenant_id=TENANT, code="MATERIAL_SHORTAGE", work_order_id="wo-c", actor="seed")
    exc3_id = exc3["exceptionId"]

    plat.pilot.inbox._crash_mode = "after-outbox-prepare"
    with pytest.raises(CrashInjected):
        plat.pilot.inbox.acknowledge(exc3_id, tenant_id=TENANT, actor="op", note="c1")
    plat.pilot.inbox._crash_mode = ""
    plat2 = Platform(root=crash_root, mock_blender=True)
    assert plat2.pilot.inbox.get(exc3_id, tenant_id=TENANT)["status"] == "OPEN"
    assert not any(e.get("eventType") == "exception.acknowledged" for e in plat2.pilot.journal.list(TENANT))
    assert plat2.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert plat2.pilot.journal.verify(TENANT)["ok"] is True

    plat2.pilot.inbox._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat2.pilot.inbox.acknowledge(exc3_id, tenant_id=TENANT, actor="op", note="c2")
    plat2.pilot.inbox._crash_mode = ""
    plat3 = Platform(root=crash_root, mock_blender=True)
    assert plat3.pilot.inbox.get(exc3_id, tenant_id=TENANT)["status"] == "ACKNOWLEDGED"
    assert [
        e["payload"] for e in plat3.pilot.journal.list(TENANT) if e.get("eventType") == "exception.acknowledged"
    ] == [{"note": "c2", "status": "ACKNOWLEDGED"}]
    assert plat3.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert plat3.pilot.journal.verify(TENANT)["ok"] is True

    plat3.pilot.inbox._crash_mode = "after-outbox-prepare"
    with pytest.raises(CrashInjected):
        plat3.pilot.inbox.resolve(exc3_id, tenant_id=TENANT, actor="mgr", resolution="r1")
    plat3.pilot.inbox._crash_mode = ""
    plat4 = Platform(root=crash_root, mock_blender=True)
    assert plat4.pilot.inbox.get(exc3_id, tenant_id=TENANT)["status"] == "ACKNOWLEDGED"
    assert not any(e.get("eventType") == "exception.resolved" for e in plat4.pilot.journal.list(TENANT))
    assert plat4.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert plat4.pilot.journal.verify(TENANT)["ok"] is True

    plat4.pilot.inbox._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat4.pilot.inbox.resolve(exc3_id, tenant_id=TENANT, actor="mgr", resolution="r2")
    plat4.pilot.inbox._crash_mode = ""
    plat5 = Platform(root=crash_root, mock_blender=True)
    assert plat5.pilot.inbox.get(exc3_id, tenant_id=TENANT)["status"] == "RESOLVED"
    assert [
        e["payload"] for e in plat5.pilot.journal.list(TENANT) if e.get("eventType") == "exception.resolved"
    ] == [{"resolution": "r2", "status": "RESOLVED"}]
    assert plat5.pilot.outbox.list_open(tenant_id=TENANT) == []
    assert plat5.pilot.journal.verify(TENANT)["ok"] is True


def test_pilot_floor_admin_bad_inputs_and_tenant_isolation(client: TestClient, platform) -> None:
    station_id = _register_station(client, "st-bad")
    exc = platform.pilot.inbox.record(
        tenant_id=TENANT,
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-bad",
        actor="seed",
    )
    exc_id = exc["exceptionId"]

    bad_station_inputs: tuple[object, ...] = (
        [],
        "bad",
        None,
        {"status": 123},
        {"status": "ACTIVE", "note": 123},
        {"status": "ACTIVE", "actor": 123},
        {"status": "ACTIVE", "transitionId": 123},
        {"status": "ACTIVE", "transitionId": "   "},
        {"status": "ACTIVE", "transitionId": "a", "idempotencyKey": "b"},
    )
    for bad in bad_station_inputs:
        res = client.put(f"/api/pilot/stations/{station_id}/status", headers=HEADERS, json=bad)
        assert res.status_code == 422, f"{bad} -> {res.status_code} {res.text}"

    assert client.put("/api/pilot/stations/missing/status", headers=HEADERS, json={"status": "ACTIVE"}).status_code == 404
    assert client.put(f"/api/pilot/stations/{station_id}/status", headers=OTHER_HEADERS, json={"status": "ACTIVE"}).status_code == 404

    bad_ack_inputs: tuple[object, ...] = ([], {"note": 123}, {"actor": 123})
    for bad in bad_ack_inputs:
        res = client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=HEADERS, json=bad)
        assert res.status_code == 422, f"{bad} -> {res.status_code} {res.text}"

    bad_resolve_inputs: tuple[object, ...] = ([], {"resolution": 123}, {"actor": 123})
    for bad in bad_resolve_inputs:
        res = client.post(f"/api/pilot/exceptions/{exc_id}/resolve", headers=HEADERS, json=bad)
        assert res.status_code == 422, f"{bad} -> {res.status_code} {res.text}"

    assert client.post("/api/pilot/exceptions/missing/ack", headers=HEADERS, json={}).status_code == 404
    assert client.post("/api/pilot/exceptions/missing/resolve", headers=HEADERS, json={}).status_code == 404
    assert client.post(f"/api/pilot/exceptions/{exc_id}/ack", headers=OTHER_HEADERS, json={}).status_code == 404
    assert client.post(f"/api/pilot/exceptions/{exc_id}/resolve", headers=OTHER_HEADERS, json={}).status_code == 404