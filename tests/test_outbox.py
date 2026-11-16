"""Offline unit tests for CommitOutbox partial failure resilience, restart consistency, and locking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fox3d.journal import EventJournal, JournalCommitError
from fox3d.outbox import BUSINESS_COMMITTED, PREPARED, CommitOutbox
import fox3d.outbox as outbox_mod


def _make_event(idx: int, *, tenant_id: str = "ta") -> dict[str, Any]:
    return {
        "event_type": f"outbox.step.{idx}",
        "tenant_id": tenant_id,
        "aggregate_type": "WorkOrder",
        "aggregate_id": f"wo-{idx}",
        "actor": "ops",
        "payload": {"idx": idx},
        "semantic_key": f"{tenant_id}::outbox::{idx}",
    }


def test_reconcile_continues_when_second_tx_fails_and_keeps_second_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = outbox

    tx1 = outbox.prepare(_make_event(1))
    tx2 = outbox.prepare(_make_event(2))
    tx3 = outbox.prepare(_make_event(3))
    outbox.mark_business_committed(tx1["txId"])
    outbox.mark_business_committed(tx2["txId"])
    outbox.mark_business_committed(tx3["txId"])

    orig_append = journal.append

    def flaky_append(event_type: str, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("aggregate_id") == "wo-2":
            raise JournalCommitError("simulated failure on 2nd tx")
        return orig_append(event_type, **kwargs)

    monkeypatch.setattr(journal, "append", flaky_append)

    res = outbox.reconcile(journal=journal, business_committed=lambda _tx: True)
    assert res == {
        "finalized": 2,
        "aborted": 0,
        "failed": [tx2["txId"]],
        "open": 1,
    }
    open_txs = outbox.list_open(tenant_id="ta")
    assert [t["txId"] for t in open_txs] == [tx2["txId"]]
    assert [e["aggregateId"] for e in journal.list("ta")] == ["wo-1", "wo-3"]
    verify = journal.verify("ta")
    assert verify["ok"] is False
    assert verify["reason"] == "incomplete-tx"
    assert verify["openTransactions"] == 1


def test_reconcile_across_restart_produces_identical_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Compare direct in-memory reconcile vs restarted (freshly constructed) objects under identical conditions.
    for mode in ("direct", "restarted"):
        sub = tmp_path / mode
        outbox = CommitOutbox(sub / "tx")
        journal = EventJournal(sub / "journal")
        journal.outbox = outbox

        tx1 = outbox.prepare(_make_event(1))
        tx2 = outbox.prepare(_make_event(2))
        tx3 = outbox.prepare(_make_event(3))
        outbox.mark_business_committed(tx1["txId"])
        outbox.mark_business_committed(tx2["txId"])
        # tx3 left PREPARED and not committed in business store -> should abort

        if mode == "restarted":
            outbox = CommitOutbox(sub / "tx")
            journal = EventJournal(sub / "journal")
            journal.outbox = outbox

        orig_append = journal.append

        def fail_second(event_type: str, _orig=orig_append, **kwargs: Any) -> dict[str, Any]:
            if kwargs.get("aggregate_id") == "wo-2":
                raise JournalCommitError("tx2 failure")
            return _orig(event_type, **kwargs)

        monkeypatch.setattr(journal, "append", fail_second)
        res = outbox.reconcile(
            journal=journal,
            business_committed=lambda tx: tx.get("aggregateId") in {"wo-1", "wo-2"},
        )
        assert res == {
            "finalized": 1,
            "aborted": 1,
            "failed": [tx2["txId"]],
            "open": 1,
        }
        assert [t["txId"] for t in outbox.list_open()] == [tx2["txId"]]
        assert tx3["txId"] not in [t["txId"] for t in outbox.list_open()]
        assert [e["aggregateId"] for e in journal.list("ta")] == ["wo-1"]

        # Restart again with working journal: only tx2 remains and is finalized cleanly.
        outbox_after = CommitOutbox(sub / "tx")
        journal_after = EventJournal(sub / "journal")
        journal_after.outbox = outbox_after
        res_after = outbox_after.reconcile(
            journal=journal_after,
            business_committed=lambda tx: tx.get("aggregateId") in {"wo-1", "wo-2"},
        )
        assert res_after == {
            "finalized": 1,
            "aborted": 0,
            "failed": [],
            "open": 0,
        }
        assert outbox_after.list_open() == []
        assert [e["aggregateId"] for e in journal_after.list("ta")] == ["wo-1", "wo-2"]
        assert journal_after.verify("ta")["ok"] is True

        # Idempotent on subsequent restart.
        outbox_idem = CommitOutbox(sub / "tx")
        journal_idem = EventJournal(sub / "journal")
        journal_idem.outbox = outbox_idem
        assert outbox_idem.reconcile(journal=journal_idem, business_committed=lambda _tx: True) == {
            "finalized": 0,
            "aborted": 0,
            "failed": [],
            "open": 0,
        }


def test_mark_business_committed_holds_self_lock_and_file_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = CommitOutbox(tmp_path / "tx")
    tx = outbox.prepare(_make_event(1))
    assert tx["status"] == PREPARED

    events: list[str] = []
    real_lock = outbox._lock
    real_file_lock = outbox_mod.FileLock
    real_read = outbox._read

    class TrackingRLock:
        def __init__(self) -> None:
            self.depth = 0

        def __enter__(self) -> TrackingRLock:
            real_lock.__enter__()
            self.depth += 1
            events.append("self_lock_enter")
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            events.append("self_lock_exit")
            self.depth -= 1
            real_lock.__exit__(exc_type, exc, tb)

    tracking_lock = TrackingRLock()
    file_lock_depth = {"n": 0}

    class TrackingFileLock:
        def __init__(self, path: Path) -> None:
            self._inner = real_file_lock(path)

        def __enter__(self) -> Any:
            assert tracking_lock.depth > 0, "FileLock must be acquired inside self._lock"
            res = self._inner.__enter__()
            file_lock_depth["n"] += 1
            events.append("file_lock_enter")
            return res

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            events.append("file_lock_exit")
            file_lock_depth["n"] -= 1
            self._inner.__exit__(exc_type, exc, tb)

    def checked_read(tx_id: str) -> dict[str, Any]:
        assert tracking_lock.depth > 0, "_read must hold self._lock"
        assert file_lock_depth["n"] > 0, "_read must hold FileLock"
        events.append("read")
        return real_read(tx_id)

    monkeypatch.setattr(outbox, "_lock", tracking_lock)
    monkeypatch.setattr(outbox_mod, "FileLock", TrackingFileLock)
    monkeypatch.setattr(outbox, "_read", checked_read)

    updated = outbox.mark_business_committed(tx["txId"], observed_generation=7)
    assert updated["status"] == BUSINESS_COMMITTED
    assert updated["observedGeneration"] == 7
    assert events == ["self_lock_enter", "file_lock_enter", "read", "file_lock_exit", "self_lock_exit"]

    reloaded = CommitOutbox(tmp_path / "tx").list_open(tenant_id="ta")
    assert len(reloaded) == 1
    assert reloaded[0]["status"] == BUSINESS_COMMITTED
    assert reloaded[0]["observedGeneration"] == 7

    with pytest.raises(KeyError):
        outbox.mark_business_committed("nonexistent-tx")


def test_outbox_tenant_isolation_in_list_open(tmp_path: Path) -> None:
    outbox = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = outbox

    tx_a = outbox.prepare(_make_event(1, tenant_id="ta"))
    tx_b = outbox.prepare(_make_event(2, tenant_id="tb"))

    assert [t["txId"] for t in outbox.list_open(tenant_id="ta")] == [tx_a["txId"]]
    assert [t["txId"] for t in outbox.list_open(tenant_id="tb")] == [tx_b["txId"]]

    outbox.complete(tx_a["txId"])
    assert journal.verify("ta")["ok"] is True
    assert journal.verify("tb")["ok"] is False
    assert journal.verify("tb")["reason"] == "incomplete-tx"
