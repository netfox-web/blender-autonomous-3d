"""Offline unit tests for CommitOutbox partial failure resilience, restart consistency, and locking."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from fox3d.journal import EventJournal, JournalCommitError
from fox3d.outbox import BUSINESS_COMMITTED, PREPARED, CommitOutbox
import fox3d.journal as journal_mod
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


def test_prepare_scales_without_scanning_open_transactions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox_reads = {"count": 0}
    journal_reads = {"count": 0}
    real_outbox_read = outbox_mod.read_json
    real_journal_read = journal_mod.read_json

    def counting_outbox_read(path: Path) -> Any:
        outbox_reads["count"] += 1
        return real_outbox_read(path)

    def counting_journal_read(path: Path) -> Any:
        journal_reads["count"] += 1
        return real_journal_read(path)

    monkeypatch.setattr(outbox_mod, "read_json", counting_outbox_read)
    monkeypatch.setattr(journal_mod, "read_json", counting_journal_read)

    outbox = CommitOutbox(tmp_path / "tx")
    n_open = 250
    txs = [outbox.prepare(_make_event(i)) for i in range(1, n_open + 1)]
    assert [t["seq"] for t in txs] == list(range(1, n_open + 1))
    # Preparing 250 open transactions does 0 JSON reads (previously 249 * 250 / 2 = 31,125 reads).
    assert outbox_reads["count"] == 0

    # Mark even-indexed transactions as BUSINESS_COMMITTED; hit cache without disk JSON reads.
    for tx in txs:
        if tx["seq"] % 2 == 0:
            outbox.mark_business_committed(tx["txId"], observed_generation=tx["seq"])
    assert outbox_reads["count"] == 0

    # Simulate cold OS process restart (clearing in-memory _OUTBOX_STATE) with 250 open transactions
    # still on disk, then prepare 50 more.
    outbox_mod._OUTBOX_STATE.clear()
    outbox_restarted = CommitOutbox(tmp_path / "tx")
    more_txs = [outbox_restarted.prepare(_make_event(i)) for i in range(n_open + 1, n_open + 51)]
    assert [t["seq"] for t in more_txs] == list(range(n_open + 1, n_open + 51))
    assert outbox_reads["count"] == 0

    # If the volatile sequence file is missing (e.g. after backup restore), the first prepare scans
    # existing *.json once to recover max_seq and all subsequent prepares do 0 JSON reads.
    outbox_mod._OUTBOX_STATE.clear()
    outbox_restarted._seq_path().unlink(missing_ok=True)
    outbox_restored = CommitOutbox(tmp_path / "tx")
    first_after_restore = outbox_restored.prepare(_make_event(n_open + 51))
    assert first_after_restore["seq"] == n_open + 51
    assert outbox_reads["count"] == n_open + 50
    outbox_reads["count"] = 0
    second_after_restore = outbox_restored.prepare(_make_event(n_open + 52))
    assert second_after_restore["seq"] == n_open + 52
    assert outbox_reads["count"] == 0
    outbox_restored.complete(first_after_restore["txId"])
    outbox_restored.complete(second_after_restore["txId"])

    # Cold restart and reconcile all 300 open transactions in exact seq order.
    outbox_recover = CommitOutbox(tmp_path / "tx")
    journal_recover = EventJournal(tmp_path / "journal")
    journal_recover.outbox = outbox_recover
    outbox_reads["count"] = 0
    journal_reads["count"] = 0

    res = outbox_recover.reconcile(
        journal=journal_recover,
        business_committed=lambda tx: int(tx.get("seq") or 0) <= n_open,
    )
    assert res == {
        "finalized": n_open,
        "aborted": 50,
        "failed": [],
        "open": 0,
    }
    # Each open tx JSON on disk was read only once during cold list_open(), and journal was read 0 times.
    assert outbox_reads["count"] == n_open + 50
    assert journal_reads["count"] == 0

    events = journal_recover.list("ta")
    assert [e["aggregateId"] for e in events] == [f"wo-{i}" for i in range(1, n_open + 1)]
    assert journal_recover.verify("ta")["ok"] is True


def test_outbox_concurrent_prepare_and_restart_recovery_order(tmp_path: Path) -> None:
    outbox = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = outbox

    # Pre-commit one event into the journal to exercise semanticKey deduplication during reconcile.
    journal.append(
        "outbox.step.1",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-1",
        actor="ops",
        payload={"idx": 1},
        semantic_key="ta::outbox::1",
    )

    n_tx = 120
    with ThreadPoolExecutor(max_workers=12) as pool:
        prepared = list(pool.map(lambda idx: outbox.prepare(_make_event(idx)), range(1, n_tx + 1)))

    seqs = [t["seq"] for t in prepared]
    assert sorted(seqs) == list(range(1, n_tx + 1))

    # Mark a subset as BUSINESS_COMMITTED concurrently.
    to_mark = [t for t in prepared if t["seq"] % 3 == 0]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda t: outbox.mark_business_committed(t["txId"]), to_mark))

    # Restart and reconcile: seq % 3 == 0 (BUSINESS_COMMITTED), seq % 3 == 1 (business_committed callback True),
    # seq % 3 == 2 (uncommitted PREPARED -> abort, except idx==1 which is already in journal -> finalized).
    outbox_after = CommitOutbox(tmp_path / "tx")
    journal_after = EventJournal(tmp_path / "journal")
    journal_after.outbox = outbox_after

    expected_committed_seqs = [
        t["seq"]
        for t in sorted(prepared, key=lambda r: r["seq"])
        if t["seq"] % 3 in {0, 1} and t["aggregateId"] != "wo-1"
    ]
    expected_aggregate_ids = ["wo-1"] + [
        t["aggregateId"]
        for t in sorted(prepared, key=lambda r: r["seq"])
        if t["seq"] % 3 in {0, 1} and t["aggregateId"] != "wo-1"
    ]

    res = outbox_after.reconcile(
        journal=journal_after,
        business_committed=lambda tx: int(tx.get("seq") or 0) % 3 == 1,
    )
    assert res["failed"] == []
    assert res["open"] == 0
    assert res["finalized"] == len(expected_committed_seqs) + 1
    assert res["aborted"] == n_tx - res["finalized"]
    assert outbox_after.list_open() == []

    committed_events = journal_after.list("ta")
    assert [e["aggregateId"] for e in committed_events] == expected_aggregate_ids
    assert journal_after.verify("ta")["ok"] is True

