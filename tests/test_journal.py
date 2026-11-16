"""Offline unit tests for EventJournal integrity, semantic_key conflict, recovery audit, and export_slice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import EventJournal, JournalCommitError, SemanticKeyConflictError
from fox3d.observability import pilot_health
from fox3d.outbox import CommitOutbox
from fox3d.platform import Platform
from fox3d.recovery import ExceptionInbox


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
