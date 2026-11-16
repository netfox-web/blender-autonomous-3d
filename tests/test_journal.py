"""Offline unit tests for EventJournal integrity, semantic_key conflict, recovery audit, and export_slice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import EventJournal, JournalCommitError, SemanticKeyConflictError
from fox3d.logistics import LogisticsService
from fox3d.mfg_release import product_snapshot
from fox3d.observability import pilot_health
from fox3d.outbox import CommitOutbox
from fox3d.platform import Platform
from fox3d.recovery import ExceptionInbox
from fox3d.workorder import FIXTURE_AUTO_SEED


def _seed_three_events(journal: EventJournal, tenant_id: str = "ta") -> list[dict]:
    return [
        journal.append(
            "evt.one",
            tenant_id=tenant_id,
            aggregate_type="WorkOrder",
            aggregate_id=f"wo-{i}",
            actor="ops",
            payload={"step": i},
            semantic_key=f"{tenant_id}::evt::{i}",
        )
        for i in range(1, 4)
    ]


def test_verify_detects_tail_truncation(tmp_path: Path) -> None:
    j = EventJournal(tmp_path / "journal")
    _seed_three_events(j, "ta")
    assert j.verify("ta")["ok"] is True

    path = j._path("ta")
    data = read_json(path)
    data["events"].pop()
    data["headHash"] = data["events"][-1]["eventHash"]
    atomic_write_json(path, data)

    res = j.verify("ta")
    assert res["ok"] is False
    assert res["status"] == "BLOCKED_EVIDENCE"
    assert res["label"] == "BLOCKED_EVIDENCE"
    assert res["reason"] == "truncated"

    # Truncating all events back to GENESIS while sequence > 0 is also detected as truncated.
    data["events"] = []
    data["headHash"] = "GENESIS"
    atomic_write_json(path, data)
    res_all = j.verify("ta")
    assert res_all["ok"] is False
    assert res_all["status"] == "BLOCKED_EVIDENCE"
    assert res_all["reason"] == "truncated"


def test_pilot_health_reports_truncated_journal_as_unhealthy(tmp_path: Path) -> None:
    plat = Platform(root=tmp_path / "plat", mock_blender=True)
    _seed_three_events(plat.pilot.journal, "ta")
    assert pilot_health(plat.pilot, tenant_id="ta")["journalIntegrity"]["ok"] is True

    path = plat.pilot.journal._path("ta")
    data = read_json(path)
    data["events"].pop()
    data["headHash"] = data["events"][-1]["eventHash"]
    atomic_write_json(path, data)

    health = pilot_health(plat.pilot, tenant_id="ta")
    assert health["journalIntegrity"]["ok"] is False
    assert health["journalIntegrity"]["status"] == "BLOCKED_EVIDENCE"
    assert health["journalIntegrity"]["reason"] == "truncated"


def test_verify_detects_middle_deletion(tmp_path: Path) -> None:
    j = EventJournal(tmp_path / "journal")
    _seed_three_events(j, "ta")

    path = j._path("ta")
    data = read_json(path)
    del data["events"][1]
    atomic_write_json(path, data)

    res = j.verify("ta")
    assert res["ok"] is False
    assert res["status"] == "BLOCKED_EVIDENCE"
    assert res["reason"] == "chain-break"

    # Even if an attacker relinks previousEventHash, eventHash, and headHash after deleting the middle event,
    # sequence continuity catches the gap with sequence-gap.
    data["events"][1]["previousEventHash"] = data["events"][0]["eventHash"]
    data["events"][1]["eventHash"] = j._event_hash(data["events"][1])
    data["headHash"] = data["events"][1]["eventHash"]
    atomic_write_json(path, data)

    res_relinked = j.verify("ta")
    assert res_relinked["ok"] is False
    assert res_relinked["status"] == "BLOCKED_EVIDENCE"
    assert res_relinked["reason"] == "sequence-gap"


def test_verify_detects_sequence_tamper(tmp_path: Path) -> None:
    j = EventJournal(tmp_path / "journal")
    _seed_three_events(j, "ta")

    path = j._path("ta")
    data = read_json(path)
    data["events"][1]["sequence"] = 9
    data["events"][1]["eventHash"] = j._event_hash(data["events"][1])
    data["events"][2]["previousEventHash"] = data["events"][1]["eventHash"]
    data["events"][2]["eventHash"] = j._event_hash(data["events"][2])
    data["headHash"] = data["events"][2]["eventHash"]
    atomic_write_json(path, data)

    res = j.verify("ta")
    assert res["ok"] is False
    assert res["status"] == "BLOCKED_EVIDENCE"
    assert res["reason"] == "sequence-gap"


def test_verify_detects_payload_tamper(tmp_path: Path) -> None:
    j = EventJournal(tmp_path / "journal")
    _seed_three_events(j, "ta")

    j.tamper("ta", 1, payload={"step": 999})
    res = j.verify("ta")
    assert res["ok"] is False
    assert res["status"] == "BLOCKED_EVIDENCE"
    assert res["reason"] == "payload-tamper"


def test_verify_detects_tenant_mix(tmp_path: Path) -> None:
    j = EventJournal(tmp_path / "journal")
    _seed_three_events(j, "ta")

    j.tamper("ta", 1, tenantId="tb")
    res = j.verify("ta")
    assert res["ok"] is False
    assert res["status"] == "BLOCKED_EVIDENCE"
    assert res["reason"] == "tenant-mix"


def test_append_same_semantic_key_rejects_different_payload_or_event_type(tmp_path: Path) -> None:
    j = EventJournal(tmp_path / "journal")
    first = j.append(
        "wo.step",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-1",
        actor="ops",
        payload={"qty": 1},
        semantic_key="ta::wo::1",
    )
    retry = j.append(
        "wo.step",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-1",
        actor="ops",
        payload={"qty": 1},
        semantic_key="ta::wo::1",
    )
    assert retry["eventId"] == first["eventId"]
    assert len(j.list("ta")) == 1

    with pytest.raises((SemanticKeyConflictError, ValueError, JournalCommitError)):
        j.append(
            "wo.step",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id="wo-1",
            actor="ops",
            payload={"qty": 2},
            semantic_key="ta::wo::1",
        )

    with pytest.raises((SemanticKeyConflictError, ValueError, JournalCommitError)):
        j.append(
            "wo.other_type",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id="wo-1",
            actor="ops",
            payload={"qty": 1},
            semantic_key="ta::wo::1",
        )

    with pytest.raises((SemanticKeyConflictError, ValueError, JournalCommitError)):
        j.append(
            "wo.step",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id="wo-1",
            actor="ops",
            payload={"qty": 1},
            release_hash="rel-different",
            semantic_key="ta::wo::1",
        )

    assert len(j.list("ta")) == 1
    assert j.verify("ta")["ok"] is True


def test_recovery_records_two_events_for_same_code_and_work_order_and_deduplicates_retry(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "journal")
    outbox = CommitOutbox(tmp_path / "tx")
    journal.outbox = outbox
    inbox = ExceptionInbox(tmp_path / "exceptions")
    inbox.journal = journal
    inbox.outbox = outbox

    exc1 = inbox.record(
        tenant_id="ta",
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-1",
        actor="ops",
        detail="first shortage",
    )
    exc2 = inbox.record(
        tenant_id="ta",
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-1",
        actor="ops",
        detail="second shortage",
    )
    assert exc1["exceptionId"] != exc2["exceptionId"]
    assert len(inbox.list(tenant_id="ta")) == 2
    events = journal.list("ta")
    assert len(events) == 2
    assert {e["aggregateId"] for e in events} == {exc1["exceptionId"], exc2["exceptionId"]}
    assert len({e["semanticKey"] for e in events}) == 2

    # True retry with the same exceptionId records only once.
    retry = inbox.record(
        tenant_id="ta",
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-1",
        actor="ops",
        detail="first shortage",
        exception_id=exc1["exceptionId"],
    )
    assert retry["exceptionId"] == exc1["exceptionId"]
    assert len(inbox.list(tenant_id="ta")) == 2
    assert len(journal.list("ta")) == 2

    # Conflicting payload for the same exceptionId is rejected.
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        inbox.record(
            tenant_id="ta",
            code="MATERIAL_SHORTAGE",
            work_order_id="wo-1",
            actor="ops",
            detail="tampered detail",
            exception_id=exc1["exceptionId"],
        )

    # Tenant isolation on ExceptionInbox.
    assert inbox.list(tenant_id="tb") == []
    with pytest.raises(PermissionError, match="tenant isolation"):
        inbox.get(exc1["exceptionId"], tenant_id="tb")
    with pytest.raises(PermissionError, match="tenant isolation"):
        inbox.record(
            tenant_id="tb",
            code="MATERIAL_SHORTAGE",
            work_order_id="wo-1",
            exception_id=exc1["exceptionId"],
        )
    assert journal.verify("ta")["ok"] is True


def test_export_slice_validates_since_seq_and_api_returns_422(tmp_path: Path) -> None:
    j = EventJournal(tmp_path / "journal")
    # Even on an empty journal, invalid since_seq must raise ValueError.
    bad_values: tuple[Any, ...] = ("abc", "", "-1", -1, 1.5, True, False, None, [], {})
    for bad in bad_values:
        with pytest.raises(ValueError):
            j.export_slice("ta", since_seq=bad)

    _seed_three_events(j, "ta")
    _seed_three_events(j, "tb")
    more_bad: tuple[Any, ...] = ("abc", "-5", -2, 2.5, True)
    for bad in more_bad:
        with pytest.raises(ValueError):
            j.export_slice("ta", since_seq=bad)

    sliced = j.export_slice("ta", since_seq=2)
    assert [e["sequence"] for e in sliced["events"]] == [2, 3]
    assert all(e["tenantId"] == "ta" for e in sliced["events"])

    plat = Platform(root=tmp_path / "plat", mock_blender=True)
    _seed_three_events(plat.pilot.journal, "ta")
    _seed_three_events(plat.pilot.journal, "tb")
    client = TestClient(create_app(plat))

    bad_resp = client.get("/api/pilot/export?since_seq=abc", headers={"X-Tenant-Id": "ta"})
    assert bad_resp.status_code == 422

    bad_camel = client.get("/api/pilot/export?sinceSeq=-1", headers={"X-Tenant-Id": "ta"})
    assert bad_camel.status_code == 422

    ok_resp = client.get("/api/pilot/export?since_seq=2", headers={"X-Tenant-Id": "ta"})
    assert ok_resp.status_code == 200
    body = ok_resp.json()
    assert body["tenantId"] == "ta"
    assert [e["sequence"] for e in body["journal"]["events"]] == [2, 3]
    assert all(e["tenantId"] == "ta" for e in body["journal"]["events"])


def test_recovery_rejects_conflicting_payload_release_hash_and_actor(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "journal")
    outbox = CommitOutbox(tmp_path / "tx")
    journal.outbox = outbox
    inbox = ExceptionInbox(tmp_path / "exceptions")
    inbox.journal = journal
    inbox.outbox = outbox

    caller_payload: dict[str, Any] = {"qty": 1, "material": "PB_18_WHITE"}
    exc1 = inbox.record(
        tenant_id="ta",
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-1",
        release_hash="rel-A",
        actor="ops",
        detail="shortage",
        payload=caller_payload,
    )
    exc_id = exc1["exceptionId"]

    # Mutating caller's dict after record() must not mutate stored payload.
    caller_payload["qty"] = 999
    assert inbox.get(exc_id, tenant_id="ta")["payload"] == {"qty": 1, "material": "PB_18_WHITE"}
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        inbox.record(
            tenant_id="ta",
            code="MATERIAL_SHORTAGE",
            work_order_id="wo-1",
            release_hash="rel-A",
            actor="ops",
            detail="shortage",
            payload=caller_payload,
            exception_id=exc_id,
        )

    # Exact retry succeeds idempotently (via exception_id and via payload.exceptionId).
    retry = inbox.record(
        tenant_id="ta",
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-1",
        release_hash="rel-A",
        actor="ops",
        detail="shortage",
        payload={"qty": 1, "material": "PB_18_WHITE"},
        exception_id=exc_id,
    )
    assert retry["exceptionId"] == exc_id
    assert retry["payload"] == {"qty": 1, "material": "PB_18_WHITE"}
    assert retry["releaseHash"] == "rel-A"

    retry_in_payload = inbox.record(
        tenant_id="ta",
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-1",
        release_hash="rel-A",
        actor="ops",
        detail="shortage",
        payload={"qty": 1, "material": "PB_18_WHITE", "exceptionId": exc_id},
    )
    assert retry_in_payload["exceptionId"] == exc_id
    assert len(inbox.list(tenant_id="ta")) == 1
    assert len(journal.list("ta")) == 1

    # Different payload only -> rejected.
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        inbox.record(
            tenant_id="ta",
            code="MATERIAL_SHORTAGE",
            work_order_id="wo-1",
            release_hash="rel-A",
            actor="ops",
            detail="shortage",
            payload={"qty": 2, "material": "PB_18_WHITE"},
            exception_id=exc_id,
        )

    # Different release_hash only -> rejected.
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        inbox.record(
            tenant_id="ta",
            code="MATERIAL_SHORTAGE",
            work_order_id="wo-1",
            release_hash="rel-B",
            actor="ops",
            detail="shortage",
            payload={"qty": 1, "material": "PB_18_WHITE"},
            exception_id=exc_id,
        )

    # Both payload and release_hash different (qty 2, version B) -> rejected.
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        inbox.record(
            tenant_id="ta",
            code="MATERIAL_SHORTAGE",
            work_order_id="wo-1",
            release_hash="rel-B",
            actor="ops",
            detail="shortage",
            payload={"qty": 2, "material": "PB_18_WHITE"},
            exception_id=exc_id,
        )

    # Different actor -> rejected.
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        inbox.record(
            tenant_id="ta",
            code="MATERIAL_SHORTAGE",
            work_order_id="wo-1",
            release_hash="rel-A",
            actor="other-actor",
            detail="shortage",
            payload={"qty": 1, "material": "PB_18_WHITE"},
            exception_id=exc_id,
        )

    # Conflicting exception_id vs payload["exceptionId"] -> rejected.
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        inbox.record(
            tenant_id="ta",
            code="MATERIAL_SHORTAGE",
            work_order_id="wo-1",
            release_hash="rel-A",
            actor="ops",
            detail="shortage",
            payload={"qty": 1, "material": "PB_18_WHITE", "exceptionId": "other-id"},
            exception_id=exc_id,
        )

    stored = ExceptionInbox(tmp_path / "exceptions").get(exc_id, tenant_id="ta")
    assert stored["payload"] == {"qty": 1, "material": "PB_18_WHITE"}
    assert stored["releaseHash"] == "rel-A"
    assert outbox.list_open(tenant_id="ta") == []
    assert journal.verify("ta")["ok"] is True


def test_logistics_repeated_carton_measured_persistence_and_recovery(tmp_path: Path) -> None:
    plat = Platform(root=tmp_path / "plat", mock_blender=True)
    log = plat.pilot.logistics
    journal = plat.pilot.journal
    outbox = plat.pilot.outbox

    cartons = log.instantiate_cartons(
        tenant_id="ta",
        work_order_id="wo-1",
        batch_id="b-1",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=1,
        release_hash="rel-1",
    )
    cid = cartons[0]["cartonId"]

    # First measurement followed by corrected second measurement with length=11.
    m1 = log.record_measured(
        cid, tenant_id="ta", length=400, width=300, height=200, weight_kg=8.0, source="MANUAL"
    )
    assert m1["measured"]["length"] == 400.0
    m2 = log.record_measured(
        cid, tenant_id="ta", length=11, width=300, height=200, weight_kg=8.0, source="MANUAL"
    )
    assert m2["measured"]["length"] == 11.0
    assert m2["mismatch"] is True

    reloaded = LogisticsService(tmp_path / "plat" / "logistics")
    assert reloaded.cartons[cid]["measured"]["length"] == 11.0
    assert outbox.list_open(tenant_id="ta") == []
    assert journal.verify("ta")["ok"] is True

    measured_events = [e for e in journal.list("ta") if e["eventType"] == "carton.measured"]
    assert len(measured_events) == 2
    assert [e["payload"]["measured"]["length"] for e in measured_events] == [400.0, 11.0]
    assert len({e["semanticKey"] for e in measured_events}) == 2

    # Simulate journal append failure after business persistence on a third measurement (length=12).
    journal._fail_next = True
    with pytest.raises(JournalCommitError):
        log.record_measured(
            cid, tenant_id="ta", length=12, width=300, height=200, weight_kg=8.0, source="MANUAL"
        )

    assert LogisticsService(tmp_path / "plat" / "logistics").cartons[cid]["measured"]["length"] == 12.0
    assert len(outbox.list_open(tenant_id="ta")) == 1
    assert journal.verify("ta")["ok"] is False
    assert journal.verify("ta")["reason"] == "incomplete-tx"

    # Restart / reconcile recovers the open outbox transaction and restores REAL journal health.
    plat_recovered = Platform(root=tmp_path / "plat", mock_blender=True)
    assert plat_recovered.pilot.logistics.cartons[cid]["measured"]["length"] == 12.0
    assert plat_recovered.pilot.outbox.list_open(tenant_id="ta") == []
    assert plat_recovered.pilot.journal.verify("ta")["ok"] is True
    recovered_events = [e for e in plat_recovered.pilot.journal.list("ta") if e["eventType"] == "carton.measured"]
    assert [e["payload"]["measured"]["length"] for e in recovered_events] == [400.0, 11.0, 12.0]

    # Simulate outbox prepare failure before business persistence on a fourth measurement (length=99).
    plat_recovered.pilot.outbox._fail_prepare = True
    with pytest.raises(JournalCommitError):
        plat_recovered.pilot.logistics.record_measured(
            cid, tenant_id="ta", length=99, width=300, height=200, weight_kg=8.0, source="MANUAL"
        )
    assert plat_recovered.pilot.logistics.cartons[cid]["measured"]["length"] == 12.0
    assert LogisticsService(tmp_path / "plat" / "logistics").cartons[cid]["measured"]["length"] == 12.0
    assert plat_recovered.pilot.outbox.list_open(tenant_id="ta") == []
    assert plat_recovered.pilot.journal.verify("ta")["ok"] is True


def test_repeatable_domain_events_produce_unique_semantic_keys_without_conflict(tmp_path: Path) -> None:
    plat = Platform(root=tmp_path / "plat", mock_blender=True)
    tid = "ta"

    product = plat.kd.build_sku(tenant_id=tid, kind="OPEN_SHELF")
    rel = plat.pilot.open_release(product, tenant_id=tid, family="KD_FURNITURE", actor="eng")
    wo = plat.pilot.workorders.create(tenant_id=tid, release=rel, quantity=1, actor="ops")
    wo_id = wo["workOrderId"]
    plat.pilot.workorders.release_for_execution(wo_id, actor="ops")
    plat.pilot.workorders.reserve_materials(
        wo_id, actor="ops", tenant_id=tid, allocation_policy=FIXTURE_AUTO_SEED
    )

    # 1. Packing checklist before cartons exist (pinned=False) and after cartons exist (pinned=True).
    chk_before = plat.pilot.logistics.packing_checklist(
        tenant_id=tid, work_order_id=wo_id, release_hash=rel["releaseHash"]
    )
    assert chk_before["pinned"] is False
    plat.pilot.logistics.instantiate_cartons(
        tenant_id=tid,
        work_order_id=wo_id,
        batch_id=wo["batchId"],
        plan={"length": 400, "width": 300, "height": 200},
        quantity=1,
        release_hash=rel["releaseHash"],
    )
    chk_after = plat.pilot.logistics.packing_checklist(
        tenant_id=tid, work_order_id=wo_id, release_hash=rel["releaseHash"]
    )
    assert chk_after["pinned"] is True

    # 2. Repeated workorder.scrap with same qty and reason producing new remnantIds.
    s1 = plat.pilot.workorders.scrap(
        wo_id,
        actor="ops",
        quantity=0.1,
        remnant_rects=[{"w": 200, "h": 150, "area": 30000, "sheetIndex": 0}],
        payload={"confirm": True},
        reason="offcut",
    )
    s2 = plat.pilot.workorders.scrap(
        wo_id,
        actor="ops",
        quantity=0.1,
        remnant_rects=[{"w": 200, "h": 150, "area": 30000, "sheetIndex": 0}],
        payload={"confirm": True},
        reason="offcut",
    )
    assert s1["remnants"][0]["remnantId"] != s2["remnants"][0]["remnantId"]

    # 3. Repeated labor corrections and rework authorizations.
    first_op = wo["traveler"]["steps"][0]["operation"]
    op = plat.pilot.workorders.start_operation(wo_id, first_op, actor="ops")
    plat.pilot.workorders.correct_labor(wo_id, op["opId"], actor="ops", minutes=5, reason="obs")
    plat.pilot.workorders.correct_labor(wo_id, op["opId"], actor="ops", minutes=5.0, reason="obs")
    plat.pilot.workorders.authorize_rework(
        wo_id, actor="ops", reason="fix", operation="rework_edge", payload={"confirm": True}
    )
    plat.pilot.workorders.authorize_rework(
        wo_id, actor="ops", reason="fix", operation="rework_edge", payload={"confirm": True}
    )

    # 4. Repeated lot cycle count with same (counted, reason) when reserved sheets change in between.
    lot = plat.lots.receive(
        tenant_id=tid, material="PB_18_WHITE", thickness=18, quantity=10, actor="ops", source="MANUAL"
    )
    plat.lots.apply_counted_available(lot["lotId"], tenant_id=tid, counted=8, actor="ops", reason="monthly")
    plat.lots.reserve_sheets(lot["lotId"], tenant_id=tid, work_order_id="wo-cc", quantity=2)
    plat.lots.apply_counted_available(lot["lotId"], tenant_id=tid, counted=8, actor="ops", reason="monthly")

    # 5. Repeated release supersede on the same old release.
    snap2 = product_snapshot(product, family="KD_FURNITURE")
    snap2["productVersion"] = 2
    snap3 = product_snapshot(product, family="KD_FURNITURE")
    snap3["productVersion"] = 3
    plat.pilot.releases.supersede(rel["releaseId"], snap2, actor="eng", tenant_id=tid)
    plat.pilot.releases.supersede(rel["releaseId"], snap3, actor="eng", tenant_id=tid)

    # 6. Operator and station registration idempotency, conflict rejection, and tenant isolation.
    op_reg = plat.pilot.identity.register_operator(
        tenant_id=tid, display_name="Op 1", capabilities=["MANUAL"], operator_id="op-fixed", enabled=True
    )
    op_retry = plat.pilot.identity.register_operator(
        tenant_id=tid, display_name="Op 1", capabilities=["MANUAL"], operator_id="op-fixed", enabled=True
    )
    assert op_retry["operatorId"] == op_reg["operatorId"]
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        plat.pilot.identity.register_operator(
            tenant_id=tid, display_name="Op 1", capabilities=["MANUAL"], operator_id="op-fixed", enabled=False
        )
    with pytest.raises(PermissionError, match="tenant isolation"):
        plat.pilot.identity.register_operator(
            tenant_id="tb", display_name="Op 1", capabilities=["MANUAL"], operator_id="op-fixed", enabled=True
        )

    st_reg = plat.pilot.stations.register(
        tenant_id=tid, capabilities=["PANEL_CUTTING_MANUAL"], station_id="st-fixed", status="ONLINE"
    )
    st_retry = plat.pilot.stations.register(
        tenant_id=tid, capabilities=["PANEL_CUTTING_MANUAL"], station_id="st-fixed", status="ONLINE"
    )
    assert st_retry["stationId"] == st_reg["stationId"]
    with pytest.raises((SemanticKeyConflictError, ValueError)):
        plat.pilot.stations.register(
            tenant_id=tid, capabilities=["PANEL_CUTTING_MANUAL"], station_id="st-fixed", status="OFFLINE"
        )
    with pytest.raises(PermissionError, match="tenant isolation"):
        plat.pilot.stations.register(
            tenant_id="tb", capabilities=["PANEL_CUTTING_MANUAL"], station_id="st-fixed", status="ONLINE"
        )

    assert plat.pilot.outbox.list_open(tenant_id=tid) == []
    assert plat.pilot.journal.verify(tid)["ok"] is True

