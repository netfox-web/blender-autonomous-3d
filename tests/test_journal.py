"""Offline unit tests for EventJournal integrity, semantic_key conflict, recovery audit, and export_slice."""

from __future__ import annotations

import errno
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import fox3d.journal as journal_mod
import fox3d.outbox as outbox_mod
from fox3d.api import create_app
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import EventJournal, JournalCommitError, SemanticKeyConflictError, emit
from fox3d.logistics import LogisticsService
from fox3d.mfg_release import product_snapshot
from fox3d.observability import pilot_health
from fox3d.outbox import CommitOutbox
from fox3d.platform import Platform
from fox3d.recovery import ExceptionInbox
from fox3d.storelock import CrashInjected
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


def test_carton_measured_same_value_recovery_before_and_after_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "plat-same-val"
    plat = Platform(root=root, mock_blender=True)
    log = plat.pilot.logistics

    cartons = log.instantiate_cartons(
        tenant_id="ta",
        work_order_id="wo-1",
        batch_id="b-1",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=1,
        release_hash="rel-1",
    )
    cid = cartons[0]["cartonId"]
    dims: dict[str, Any] = {
        "tenant_id": "ta",
        "length": 400.0,
        "width": 300.0,
        "height": 200.0,
        "weight_kg": 8.0,
        "source": "MANUAL",
    }

    # 1. Record first measurement with measure_op_id="first".
    log.record_measured(cid, **dims, measure_op_id="first")
    assert list(log.cartons[cid]["measureOps"]) == ["first"]
    assert [
        e["payload"]["measureOpId"]
        for e in plat.pilot.journal.list("ta")
        if e["eventType"] == "carton.measured"
    ] == ["first"]

    # 2. Interrupt "second" with identical values AFTER outbox PREPARED, BEFORE business persistence.
    log._crash_mode = "after-outbox-prepare"
    with pytest.raises(CrashInjected):
        log.record_measured(cid, **dims, measure_op_id="second")
    log._crash_mode = ""

    open_before_abort = plat.pilot.outbox.list_open(tenant_id="ta")
    assert len(open_before_abort) == 1
    assert open_before_abort[0]["status"] == "PREPARED"
    assert open_before_abort[0]["event"]["payload"]["measureOpId"] == "second"
    assert list(LogisticsService(root / "logistics").cartons[cid]["measureOps"]) == ["first"]
    assert plat.pilot._business_committed(open_before_abort[0]) is False
    assert plat.pilot.journal.verify("ta")["ok"] is False
    assert plat.pilot.journal.verify("ta")["reason"] == "incomplete-tx"

    # Restart Platform: "second" must be aborted (not committed to journal), keeping business and journal aligned.
    plat_after_abort = Platform(root=root, mock_blender=True)
    assert list(plat_after_abort.pilot.logistics.cartons[cid]["measureOps"]) == ["first"]
    assert [
        e["payload"]["measureOpId"]
        for e in plat_after_abort.pilot.journal.list("ta")
        if e["eventType"] == "carton.measured"
    ] == ["first"]
    assert plat_after_abort.pilot.outbox.list_open(tenant_id="ta") == []
    assert plat_after_abort.pilot.journal.verify("ta")["ok"] is True

    # 3. Interrupt "second" with identical values AFTER business persistence, BEFORE outbox marker (tx still PREPARED).
    orig_mark = plat_after_abort.pilot.outbox.mark_business_committed

    def fail_mark(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("interrupted after persist before mark_business_committed")

    monkeypatch.setattr(plat_after_abort.pilot.outbox, "mark_business_committed", fail_mark)
    with pytest.raises(RuntimeError, match="interrupted after persist"):
        plat_after_abort.pilot.logistics.record_measured(cid, **dims, measure_op_id="second")
    monkeypatch.setattr(plat_after_abort.pilot.outbox, "mark_business_committed", orig_mark)

    open_prepared_committed = plat_after_abort.pilot.outbox.list_open(tenant_id="ta")
    assert len(open_prepared_committed) == 1
    assert open_prepared_committed[0]["status"] == "PREPARED"
    assert list(LogisticsService(root / "logistics").cartons[cid]["measureOps"]) == ["first", "second"]
    assert plat_after_abort.pilot._business_committed(open_prepared_committed[0]) is True

    # Verify _business_committed rejects a mismatched payload for an existing measureOpId.
    tampered_tx = {
        **open_prepared_committed[0],
        "event": {
            **open_prepared_committed[0]["event"],
            "payload": {
                "measureOpId": "second",
                "measured": {
                    **open_prepared_committed[0]["event"]["payload"]["measured"],
                    "length": 999.0,
                },
            },
        },
    }
    assert plat_after_abort.pilot._business_committed(tampered_tx) is False

    # Restart Platform: "second" must be finalized into the journal and outbox cleared.
    plat_after_commit = Platform(root=root, mock_blender=True)
    assert list(plat_after_commit.pilot.logistics.cartons[cid]["measureOps"]) == ["first", "second"]
    assert [
        e["payload"]["measureOpId"]
        for e in plat_after_commit.pilot.journal.list("ta")
        if e["eventType"] == "carton.measured"
    ] == ["first", "second"]
    assert plat_after_commit.pilot.outbox.list_open(tenant_id="ta") == []
    assert plat_after_commit.pilot.journal.verify("ta")["ok"] is True

    # 4. Interrupt "third" with identical values at "after-business-persist" crash point.
    plat_after_commit.pilot.logistics._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat_after_commit.pilot.logistics.record_measured(cid, **dims, measure_op_id="third")
    plat_after_commit.pilot.logistics._crash_mode = ""

    assert list(LogisticsService(root / "logistics").cartons[cid]["measureOps"]) == ["first", "second", "third"]
    assert len(plat_after_commit.pilot.outbox.list_open(tenant_id="ta")) == 1
    assert plat_after_commit.pilot.journal.verify("ta")["ok"] is False

    plat_final = Platform(root=root, mock_blender=True)
    assert list(plat_final.pilot.logistics.cartons[cid]["measureOps"]) == ["first", "second", "third"]
    assert [
        e["payload"]["measureOpId"]
        for e in plat_final.pilot.journal.list("ta")
        if e["eventType"] == "carton.measured"
    ] == ["first", "second", "third"]
    assert plat_final.pilot.outbox.list_open(tenant_id="ta") == []
    assert plat_final.pilot.journal.verify("ta")["ok"] is True


def test_carton_measured_delimiter_op_id_recovery_before_and_after_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "plat-delim-op"
    plat = Platform(root=root, mock_blender=True)
    log = plat.pilot.logistics

    cartons = log.instantiate_cartons(
        tenant_id="ta",
        work_order_id="wo-1",
        batch_id="b-1",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=1,
        release_hash="rel-1",
    )
    cid = cartons[0]["cartonId"]
    dims: dict[str, Any] = {
        "tenant_id": "ta",
        "length": 400.0,
        "width": 300.0,
        "height": 200.0,
        "weight_kg": 8.0,
        "source": "MANUAL",
    }

    # 1. Interrupt measure_op_id="batch::123" AFTER outbox PREPARED, BEFORE business persistence.
    log._crash_mode = "after-outbox-prepare"
    with pytest.raises(CrashInjected):
        log.record_measured(cid, **dims, measure_op_id="batch::123")
    log._crash_mode = ""

    open_before_abort = plat.pilot.outbox.list_open(tenant_id="ta")
    assert len(open_before_abort) == 1
    assert open_before_abort[0]["status"] == "PREPARED"
    assert open_before_abort[0]["event"]["payload"]["measureOpId"] == "batch::123"
    assert open_before_abort[0]["semanticKey"] == f"ta::carton-measured::{cid}::batch::123"
    assert not (LogisticsService(root / "logistics").cartons[cid].get("measureOps") or {})
    assert plat.pilot._business_committed(open_before_abort[0]) is False
    assert plat.pilot.journal.verify("ta")["ok"] is False
    assert plat.pilot.journal.verify("ta")["reason"] == "incomplete-tx"

    # Restart Platform: unpersisted "batch::123" must be aborted cleanly.
    plat_after_abort = Platform(root=root, mock_blender=True)
    assert not (plat_after_abort.pilot.logistics.cartons[cid].get("measureOps") or {})
    assert [
        e["payload"]["measureOpId"]
        for e in plat_after_abort.pilot.journal.list("ta")
        if e["eventType"] == "carton.measured"
    ] == []
    assert plat_after_abort.pilot.outbox.list_open(tenant_id="ta") == []
    assert plat_after_abort.pilot.journal.verify("ta")["ok"] is True

    # 2. Interrupt measure_op_id="batch::123" AFTER business persistence, BEFORE mark_business_committed.
    orig_mark = plat_after_abort.pilot.outbox.mark_business_committed

    def fail_mark(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("interrupted after persist before mark_business_committed")

    monkeypatch.setattr(plat_after_abort.pilot.outbox, "mark_business_committed", fail_mark)
    with pytest.raises(RuntimeError, match="interrupted after persist"):
        plat_after_abort.pilot.logistics.record_measured(cid, **dims, measure_op_id="batch::123")
    monkeypatch.setattr(plat_after_abort.pilot.outbox, "mark_business_committed", orig_mark)

    open_prepared_committed = plat_after_abort.pilot.outbox.list_open(tenant_id="ta")
    assert len(open_prepared_committed) == 1
    tx_committed = open_prepared_committed[0]
    assert tx_committed["status"] == "PREPARED"
    assert tx_committed["event"]["payload"]["measureOpId"] == "batch::123"
    assert list(LogisticsService(root / "logistics").cartons[cid]["measureOps"]) == ["batch::123"]
    assert plat_after_abort.pilot._business_committed(tx_committed) is True

    # Fallback without payload["measureOpId"] also resolves full "batch::123" from semanticKey prefix.
    tx_no_payload_op_id = {
        **tx_committed,
        "event": {
            **tx_committed["event"],
            "payload": {"measured": tx_committed["event"]["payload"]["measured"]},
        },
    }
    assert plat_after_abort.pilot._business_committed(tx_no_payload_op_id) is True

    # Mismatched semanticKey, tenantId, or payload is rejected.
    tx_bad_sem = {
        **tx_committed,
        "semanticKey": f"ta::carton-measured::{cid}::batch::999",
    }
    assert plat_after_abort.pilot._business_committed(tx_bad_sem) is False

    tx_bad_ev_sem = {
        **tx_committed,
        "event": {
            **tx_committed["event"],
            "semantic_key": f"ta::carton-measured::{cid}::batch::999",
        },
    }
    assert plat_after_abort.pilot._business_committed(tx_bad_ev_sem) is False

    tx_bad_ev_tenant = {
        **tx_committed,
        "event": {
            **tx_committed["event"],
            "tenant_id": "tb",
        },
    }
    assert plat_after_abort.pilot._business_committed(tx_bad_ev_tenant) is False

    tx_bad_measured = {
        **tx_committed,
        "event": {
            **tx_committed["event"],
            "payload": {
                "measureOpId": "batch::123",
                "measured": {
                    **tx_committed["event"]["payload"]["measured"],
                    "length": 999.0,
                },
            },
        },
    }
    assert plat_after_abort.pilot._business_committed(tx_bad_measured) is False

    # Restart Platform: persisted "batch::123" must be finalized into journal, NOT aborted.
    plat_after_commit = Platform(root=root, mock_blender=True)
    assert list(plat_after_commit.pilot.logistics.cartons[cid]["measureOps"]) == ["batch::123"]
    measured_events = [
        e for e in plat_after_commit.pilot.journal.list("ta") if e["eventType"] == "carton.measured"
    ]
    assert len(measured_events) == 1
    assert measured_events[0]["payload"]["measureOpId"] == "batch::123"
    assert measured_events[0]["semanticKey"] == f"ta::carton-measured::{cid}::batch::123"
    assert plat_after_commit.pilot.outbox.list_open(tenant_id="ta") == []
    assert plat_after_commit.pilot.journal.verify("ta")["ok"] is True

    # 3. Interrupt a second delimiter op ID "batch::sub::456" with identical values at "after-business-persist".
    plat_after_commit.pilot.logistics._crash_mode = "after-business-persist"
    with pytest.raises(CrashInjected):
        plat_after_commit.pilot.logistics.record_measured(cid, **dims, measure_op_id="batch::sub::456")
    plat_after_commit.pilot.logistics._crash_mode = ""

    assert list(LogisticsService(root / "logistics").cartons[cid]["measureOps"]) == [
        "batch::123",
        "batch::sub::456",
    ]
    assert len(plat_after_commit.pilot.outbox.list_open(tenant_id="ta")) == 1
    assert plat_after_commit.pilot.journal.verify("ta")["ok"] is False

    plat_final = Platform(root=root, mock_blender=True)
    assert list(plat_final.pilot.logistics.cartons[cid]["measureOps"]) == [
        "batch::123",
        "batch::sub::456",
    ]
    assert [
        e["payload"]["measureOpId"]
        for e in plat_final.pilot.journal.list("ta")
        if e["eventType"] == "carton.measured"
    ] == ["batch::123", "batch::sub::456"]
    assert plat_final.pilot.outbox.list_open(tenant_id="ta") == []
    assert plat_final.pilot.journal.verify("ta")["ok"] is True


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


def test_emit_and_append_avoid_redundant_reads_at_scale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal_reads = {"count": 0}
    outbox_reads = {"count": 0}
    real_journal_read = journal_mod.read_json
    real_outbox_read = outbox_mod.read_json

    def counting_journal_read(path: Path) -> Any:
        journal_reads["count"] += 1
        return real_journal_read(path)

    def counting_outbox_read(path: Path) -> Any:
        outbox_reads["count"] += 1
        return real_outbox_read(path)

    monkeypatch.setattr(journal_mod, "read_json", counting_journal_read)
    monkeypatch.setattr(outbox_mod, "read_json", counting_outbox_read)

    class _Owner:
        def __init__(self, journal: EventJournal, outbox: CommitOutbox) -> None:
            self.journal = journal
            self.outbox = outbox
            self.persisted = 0

        def persist(self) -> None:
            self.persisted += 1

    j1 = EventJournal(tmp_path / "journal")
    o1 = CommitOutbox(tmp_path / "tx")
    j1.outbox = o1
    owner1 = _Owner(j1, o1)

    n_initial = 250
    for i in range(1, n_initial + 1):
        rec = emit(
            owner1,
            "wo.progress",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id=f"wo-{i}",
            actor="ops",
            payload={"step": i},
            release_hash="rel-1",
            semantic_key=f"ta::wo-progress::{i}",
        )
        assert rec is not None
        assert rec["sequence"] == i

    # Warm instance: check_semantic_key + append + outbox prepare/mark/complete do 0 disk JSON reads.
    assert journal_reads["count"] == 0
    assert outbox_reads["count"] == 0
    assert owner1.persisted == n_initial

    # Cold restart on existing 250-event journal: 50 new emit() calls should read the journal file only ONCE
    # (during the first check_semantic_key), NOT twice per emit (which would be 100 reads).
    j2 = EventJournal(tmp_path / "journal")
    o2 = CommitOutbox(tmp_path / "tx")
    j2.outbox = o2
    owner2 = _Owner(j2, o2)
    journal_reads["count"] = 0
    outbox_reads["count"] = 0

    n_more = 50
    for i in range(n_initial + 1, n_initial + n_more + 1):
        rec = emit(
            owner2,
            "wo.progress",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id=f"wo-{i}",
            actor="ops",
            payload={"step": i},
            release_hash="rel-1",
            semantic_key=f"ta::wo-progress::{i}",
        )
        assert rec is not None
        assert rec["sequence"] == i

    assert journal_reads["count"] == 1
    assert outbox_reads["count"] == 0
    assert owner2.persisted == n_more

    # Idempotent retry and conflict detection hit the in-memory semantic index with 0 extra disk reads.
    reads_before_checks = journal_reads["count"]
    dup = j2.append(
        "wo.progress",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-1",
        actor="ops",
        payload={"step": 1},
        release_hash="rel-1",
        semantic_key="ta::wo-progress::1",
    )
    assert dup["sequence"] == 1
    with pytest.raises(SemanticKeyConflictError):
        emit(
            owner2,
            "wo.progress",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id="wo-1",
            actor="ops",
            payload={"step": 999},
            release_hash="rel-1",
            semantic_key="ta::wo-progress::1",
        )
    with pytest.raises(SemanticKeyConflictError):
        emit(
            owner2,
            "wo.progress",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id=f"wo-{n_initial + n_more}",
            actor="ops",
            payload={"step": n_initial + n_more},
            release_hash="rel-other",
            semantic_key=f"ta::wo-progress::{n_initial + n_more}",
        )
    assert journal_reads["count"] == reads_before_checks
    assert owner2.persisted == n_more

    # Verify reads once from disk and confirms full hash-chain integrity across all 300 events.
    ver = j2.verify("ta")
    assert ver["ok"] is True
    assert ver["count"] == n_initial + n_more
    assert ver["sequence"] == n_initial + n_more


def test_journal_concurrent_appends_and_semantic_key_conflicts(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "journal")
    outbox = CommitOutbox(tmp_path / "tx")
    journal.outbox = outbox

    distinct_count = 60

    def _worker(idx: int) -> tuple[str, Any]:
        if idx < distinct_count:
            ev = journal.append(
                "concurrent.evt",
                tenant_id="ta",
                aggregate_type="WorkOrder",
                aggregate_id=f"wo-{idx}",
                actor="ops",
                payload={"idx": idx},
                release_hash="rel-c",
                semantic_key=f"ta::conc::{idx}",
            )
            return ("distinct", ev["eventId"])
        if idx < distinct_count + 20:
            # Idempotent retry of key 0
            ev = journal.append(
                "concurrent.evt",
                tenant_id="ta",
                aggregate_type="WorkOrder",
                aggregate_id="wo-0",
                actor="ops",
                payload={"idx": 0},
                release_hash="rel-c",
                semantic_key="ta::conc::0",
            )
            return ("retry", ev["eventId"])
        # Conflicting payload on key 0
        try:
            journal.append(
                "concurrent.evt",
                tenant_id="ta",
                aggregate_type="WorkOrder",
                aggregate_id="wo-0",
                actor="ops",
                payload={"idx": 9999 + idx},
                release_hash="rel-c",
                semantic_key="ta::conc::0",
            )
            return ("unexpected-ok", None)
        except SemanticKeyConflictError:
            return ("conflict", None)

    # Seed key 0 first so retries and conflicts race against a deterministic baseline and other distinct appends.
    first_zero = journal.append(
        "concurrent.evt",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-0",
        actor="ops",
        payload={"idx": 0},
        release_hash="rel-c",
        semantic_key="ta::conc::0",
    )

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(_worker, range(1, distinct_count + 40)))

    retry_ids = {val for kind, val in results if kind == "retry"}
    conflicts = [kind for kind, _ in results if kind == "conflict"]
    unexpected = [kind for kind, _ in results if kind == "unexpected-ok"]
    assert retry_ids == {first_zero["eventId"]}
    assert len(conflicts) == 20
    assert unexpected == []

    events = journal.list("ta")
    assert len(events) == distinct_count
    assert [e["sequence"] for e in events] == list(range(1, distinct_count + 1))
    assert journal.verify("ta")["ok"] is True

    # Cross-tenant isolation check
    assert journal.list("tb") == []
    with pytest.raises(PermissionError, match="tenant isolation"):
        journal._find_by_semantic_key(
            events,
            tenant_id="tb",
            event_type="concurrent.evt",
            payload_hash=first_zero["payloadHash"],
            release_hash="rel-c",
            semantic_key="ta::conc::0",
        )


def test_journal_cross_process_read_interleaved_with_writer_preserves_all_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read_json = journal_mod.read_json

    for reader_op in ("list", "verify"):
        sub = tmp_path / reader_op
        j1 = EventJournal(sub / "journal")
        j2 = EventJournal(sub / "journal")

        # Writer j2 commits event 1 first so j1 has to read from disk on list() (and verify() forces reload).
        j2.append(
            "evt.step",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id="wo-1",
            actor="ops",
            payload={"step": 1},
            semantic_key="ta::evt::1",
        )

        interleaved = {"triggered": False}

        def racing_read_json(path: Path, _j2: EventJournal = j2, _state: dict[str, bool] = interleaved) -> Any:
            data = real_read_json(path)
            if not _state["triggered"] and path.name == _j2._path("ta").name:
                _state["triggered"] = True
                saved_gen = journal_mod._get_journal_gen(path)
                # Another process writes event 2 after read_json read old content [1], before j1 caches sig.
                _j2.append(
                    "evt.step",
                    tenant_id="ta",
                    aggregate_type="WorkOrder",
                    aggregate_id="wo-2",
                    actor="ops",
                    payload={"step": 2},
                    semantic_key="ta::evt::2",
                )
                # Simulate separate OS process where in-process generation in j1's process was not bumped.
                with journal_mod._JOURNAL_GEN_LOCK:
                    journal_mod._JOURNAL_GEN[path.resolve()] = saved_gen
            return data

        monkeypatch.setattr(journal_mod, "read_json", racing_read_json)

        if reader_op == "list":
            observed = j1.list("ta")
            assert [e["payload"]["step"] for e in observed] == [1, 2]
        else:
            ver = j1.verify("ta")
            assert ver["ok"] is True
            assert ver["count"] == 2

        monkeypatch.setattr(journal_mod, "read_json", real_read_json)

        # Subsequent append on j1 must NOT hit a poisoned cache with only [1] and overwrite event 2.
        j1.append(
            "evt.step",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id="wo-3",
            actor="ops",
            payload={"step": 3},
            semantic_key="ta::evt::3",
        )

        events = j1.list("ta")
        assert [e["payload"]["step"] for e in events] == [1, 2, 3]
        assert [e["sequence"] for e in events] == [1, 2, 3]
        assert j1.verify("ta")["ok"] is True

        cold_events = EventJournal(sub / "journal").list("ta")
        assert [e["payload"]["step"] for e in cold_events] == [1, 2, 3]
        assert [e["sequence"] for e in cold_events] == [1, 2, 3]


def test_journal_stat_io_error_propagates_and_preserves_existing_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "journal"
    j_warm = EventJournal(root)
    first = j_warm.append(
        "evt.step",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-1",
        actor="ops",
        payload={"step": "first"},
        semantic_key="ta::evt::first",
    )
    journal_path = j_warm._path("ta")
    original_bytes = journal_path.read_bytes()
    original_json = read_json(journal_path)
    orig_stat = Path.stat

    # 1. Cold journal: persistent EIO on Path.stat for the existing journal file must propagate
    # and forbid overwriting the existing file when appending "second".
    def stat_eio(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == journal_path:
            raise OSError(errno.EIO, "simulated transient stat EIO")
        return orig_stat(self, *args, **kwargs)

    j_cold = EventJournal(root)
    monkeypatch.setattr(Path, "stat", stat_eio)
    with pytest.raises(OSError) as exc_cold:
        j_cold.append(
            "evt.step",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id="wo-2",
            actor="ops",
            payload={"step": "second"},
            semantic_key="ta::evt::second",
        )
    assert exc_cold.value.errno == errno.EIO

    # Warm journal and read/verify/check_semantic_key paths must also propagate EIO without poisoning cache.
    with pytest.raises(OSError) as exc_warm:
        j_warm.append(
            "evt.step",
            tenant_id="ta",
            aggregate_type="WorkOrder",
            aggregate_id="wo-2",
            actor="ops",
            payload={"step": "second"},
            semantic_key="ta::evt::second",
        )
    assert exc_warm.value.errno == errno.EIO

    with pytest.raises(OSError):
        j_cold.check_semantic_key(
            tenant_id="ta",
            event_type="evt.step",
            payload={"step": "first"},
            semantic_key="ta::evt::first",
        )
    with pytest.raises(OSError):
        j_cold.list("ta")
    with pytest.raises(OSError):
        j_cold.verify("ta")

    # 2. Single-shot transient EIO on the 1st, 2nd, or 3rd Path.stat call must also fail closed without writing.
    for fail_on_call in (1, 2, 3):
        calls = {"n": 0}

        def stat_nth_eio(
            self: Path,
            *args: Any,
            _calls: dict[str, int] = calls,
            _target: int = fail_on_call,
            **kwargs: Any,
        ) -> Any:
            if self == journal_path:
                _calls["n"] += 1
                if _calls["n"] == _target:
                    raise OSError(errno.EIO, f"simulated stat EIO on call {_target}")
            return orig_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", stat_nth_eio)
        j_transient = EventJournal(root)
        with pytest.raises(OSError) as exc_nth:
            j_transient.append(
                "evt.step",
                tenant_id="ta",
                aggregate_type="WorkOrder",
                aggregate_id="wo-2",
                actor="ops",
                payload={"step": "second"},
                semantic_key="ta::evt::second",
            )
        assert exc_nth.value.errno == errno.EIO

    # Restore Path.stat and confirm the original file bytes and "first" event are completely untouched.
    monkeypatch.setattr(Path, "stat", orig_stat)
    assert journal_path.read_bytes() == original_bytes
    assert read_json(journal_path) == original_json
    assert [e["payload"]["step"] for e in j_warm.list("ta")] == ["first"]
    assert [e["payload"]["step"] for e in EventJournal(root).list("ta")] == ["first"]
    assert j_warm.verify("ta")["ok"] is True

    # Appending "second" after I/O recovery preserves "first" and chains "second" at sequence 2.
    second = EventJournal(root).append(
        "evt.step",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-2",
        actor="ops",
        payload={"step": "second"},
        semantic_key="ta::evt::second",
    )
    assert second["sequence"] == 2
    assert second["previousEventHash"] == first["eventHash"]

    # Post-write stat EIO (4th stat call during cold append) invalidates cache while keeping all events on disk.
    post_write_calls = {"n": 0}

    def stat_4th_eio(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == journal_path:
            post_write_calls["n"] += 1
            if post_write_calls["n"] == 4:
                raise OSError(errno.EIO, "simulated post-write stat EIO")
        return orig_stat(self, *args, **kwargs)

    j_post = EventJournal(root)
    monkeypatch.setattr(Path, "stat", stat_4th_eio)
    third = j_post.append(
        "evt.step",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-3",
        actor="ops",
        payload={"step": "third"},
        semantic_key="ta::evt::third",
    )
    monkeypatch.setattr(Path, "stat", orig_stat)
    assert third["sequence"] == 3
    assert third["previousEventHash"] == second["eventHash"]
    assert "ta" not in j_post._cache

    reloaded = EventJournal(root)
    events = reloaded.list("ta")
    assert [e["payload"]["step"] for e in events] == ["first", "second", "third"]
    assert [e["sequence"] for e in events] == [1, 2, 3]
    ver = reloaded.verify("ta")
    assert ver["ok"] is True
    assert ver["count"] == 3

