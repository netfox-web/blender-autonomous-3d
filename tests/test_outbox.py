"""Offline unit tests for CommitOutbox partial failure resilience, restart consistency, and locking."""

from __future__ import annotations

import errno
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import EventJournal, JournalCommitError, SemanticKeyConflictError
from fox3d.outbox import BUSINESS_COMMITTED, PREPARED, CommitOutbox
from fox3d.storelock import FileLock
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


def test_list_open_interleaved_with_mark_business_committed_does_not_abort_committed_tx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read_json = outbox_mod.read_json

    for hook_mode in (
        "read_json_cross_proc",
        "cache_put_in_proc",
        "during_reconcile_callback",
        "after_post_callback_read_before_abort",
        "before_abort_call",
        "before_abort_lock_acquire_cross_proc",
    ):
        sub = tmp_path / hook_mode
        outbox1 = CommitOutbox(sub / "tx")
        outbox2 = CommitOutbox(sub / "tx")
        journal = EventJournal(sub / "journal")
        journal.outbox = outbox1

        tx = outbox2.prepare(_make_event(1))
        tx_id = tx["txId"]
        tx_path = outbox1._path(tx_id)
        triggered = {"done": False}

        if hook_mode == "read_json_cross_proc":
            def hooked_read_json(
                path: Path,
                _o2: CommitOutbox = outbox2,
                _tx_id: str = tx_id,
                _tx_path: Path = tx_path,
                _trig: dict[str, bool] = triggered,
            ) -> Any:
                data = real_read_json(path)
                if not _trig["done"] and path == _tx_path:
                    _trig["done"] = True
                    saved_gen = outbox_mod._get_tx_gen(path)
                    _o2.mark_business_committed(_tx_id, observed_generation=1)
                    # Also simulate cross-process update where in-process _TX_FILE_GEN did not advance.
                    with outbox_mod._OUTBOX_GEN_LOCK:
                        outbox_mod._TX_FILE_GEN[path.resolve()] = saved_gen
                return data

            monkeypatch.setattr(outbox_mod, "read_json", hooked_read_json)
            open_rows = outbox1.list_open()
            monkeypatch.setattr(outbox_mod, "read_json", real_read_json)
            assert len(open_rows) == 1
            assert open_rows[0]["status"] == BUSINESS_COMMITTED

            res = outbox1.reconcile(journal=journal, business_committed=lambda _tx: False)
        elif hook_mode == "cache_put_in_proc":
            orig_cache_put = outbox1._cache_put

            def hooked_cache_put(
                path: Path,
                rec: dict[str, Any],
                *,
                bump: bool = False,
                _orig: Any = orig_cache_put,
                _o2: CommitOutbox = outbox2,
                _tx_id: str = tx_id,
                _tx_path: Path = tx_path,
                _trig: dict[str, bool] = triggered,
            ) -> None:
                if not bump and not _trig["done"] and path == _tx_path:
                    _trig["done"] = True
                    _o2.mark_business_committed(_tx_id, observed_generation=2)
                _orig(path, rec, bump=bump)

            monkeypatch.setattr(outbox1, "_cache_put", hooked_cache_put)
            open_rows = outbox1.list_open()
            monkeypatch.setattr(outbox1, "_cache_put", orig_cache_put)
            assert len(open_rows) == 1
            assert open_rows[0]["status"] == BUSINESS_COMMITTED

            res = outbox1.reconcile(journal=journal, business_committed=lambda _tx: False)
        elif hook_mode == "during_reconcile_callback":
            # Interleaving where list_open() genuinely observed PREPARED first, and another instance
            # transitions the tx to BUSINESS_COMMITTED while business_committed() callback is running.
            def late_commit_callback(
                _tx: dict[str, Any],
                _o2: CommitOutbox = outbox2,
                _tx_id: str = tx_id,
                _trig: dict[str, bool] = triggered,
            ) -> bool:
                if not _trig["done"]:
                    _trig["done"] = True
                    _o2.mark_business_committed(_tx_id, observed_generation=3)
                return False

            res = outbox1.reconcile(journal=journal, business_committed=late_commit_callback)
        elif hook_mode == "after_post_callback_read_before_abort":
            # Interleaving where business_committed() returns False, reconcile reads PREPARED, and
            # another instance marks BUSINESS_COMMITTED after that read and before abort() acquires the lock.
            orig_load = outbox1._load_tx_file
            callback_returned_false = {"done": False}

            def false_callback(
                _tx: dict[str, Any],
                _cb_done: dict[str, bool] = callback_returned_false,
            ) -> bool:
                _cb_done["done"] = True
                return False

            def hooked_load_after_callback(
                path: Path,
                _orig: Any = orig_load,
                _o2: CommitOutbox = outbox2,
                _tx_id: str = tx_id,
                _tx_path: Path = tx_path,
                _cb_done: dict[str, bool] = callback_returned_false,
                _trig: dict[str, bool] = triggered,
            ) -> dict[str, Any]:
                rec = _orig(path)
                if _cb_done["done"] and not _trig["done"] and path == _tx_path:
                    assert rec.get("status") == PREPARED
                    _trig["done"] = True
                    _o2.mark_business_committed(_tx_id, observed_generation=4)
                return rec

            monkeypatch.setattr(outbox1, "_load_tx_file", hooked_load_after_callback)
            res = outbox1.reconcile(journal=journal, business_committed=false_callback)
            monkeypatch.setattr(outbox1, "_load_tx_file", orig_load)
            assert triggered["done"] is True
        elif hook_mode == "before_abort_call":
            # Interleaving where business_committed() returns False while tx is still PREPARED, and
            # another instance marks BUSINESS_COMMITTED right before abort() acquires the lock.
            orig_abort = outbox1.abort

            def hooked_abort(
                tid: str,
                _orig: Any = orig_abort,
                _o2: CommitOutbox = outbox2,
                _tx_id: str = tx_id,
                _tx_path: Path = tx_path,
                _trig: dict[str, bool] = triggered,
            ) -> bool:
                if not _trig["done"] and tid == _tx_id:
                    assert read_json(_tx_path)["status"] == PREPARED
                    _trig["done"] = True
                    _o2.mark_business_committed(_tx_id, observed_generation=4)
                return _orig(tid)

            monkeypatch.setattr(outbox1, "abort", hooked_abort)
            res = outbox1.reconcile(journal=journal, business_committed=lambda _tx: False)
            monkeypatch.setattr(outbox1, "abort", orig_abort)
            assert triggered["done"] is True
        else:
            # Interleaving where mark_business_committed() races right before abort() acquires FileLock,
            # including simulated cross-process update where _TX_FILE_GEN in outbox1's process did not advance.
            real_file_lock = outbox_mod.FileLock
            in_abort = {"active": False}
            orig_abort = outbox1.abort

            def tracking_abort(
                tid: str,
                _orig: Any = orig_abort,
                _in_abort: dict[str, bool] = in_abort,
            ) -> bool:
                _in_abort["active"] = True
                try:
                    return _orig(tid)
                finally:
                    _in_abort["active"] = False

            class PreAbortFileLock:
                def __init__(
                    self,
                    lock_path: Path,
                    _real: Any = real_file_lock,
                    _in_abort: dict[str, bool] = in_abort,
                    _trig: dict[str, bool] = triggered,
                    _o2: CommitOutbox = outbox2,
                    _tx_id: str = tx_id,
                    _tx_path: Path = tx_path,
                ) -> None:
                    if _in_abort["active"] and not _trig["done"]:
                        _trig["done"] = True
                        _in_abort["active"] = False
                        saved_gen = outbox_mod._get_tx_gen(_tx_path)
                        _o2.mark_business_committed(_tx_id, observed_generation=5)
                        with outbox_mod._OUTBOX_GEN_LOCK:
                            outbox_mod._TX_FILE_GEN[_tx_path.resolve()] = saved_gen
                    self._inner = _real(lock_path)

                def __enter__(self) -> Any:
                    return self._inner.__enter__()

                def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
                    self._inner.__exit__(exc_type, exc, tb)

            monkeypatch.setattr(outbox1, "abort", tracking_abort)
            monkeypatch.setattr(outbox_mod, "FileLock", PreAbortFileLock)
            res = outbox1.reconcile(journal=journal, business_committed=lambda _tx: False)
            monkeypatch.setattr(outbox_mod, "FileLock", real_file_lock)
            monkeypatch.setattr(outbox1, "abort", orig_abort)
            assert triggered["done"] is True

        assert res == {
            "finalized": 1,
            "aborted": 0,
            "failed": [],
            "open": 0,
        }
        assert outbox1.list_open() == []
        events = journal.list("ta")
        assert len(events) == 1
        assert events[0]["aggregateId"] == "wo-1"
        assert events[0]["semanticKey"] == "ta::outbox::1"
        assert journal.verify("ta")["ok"] is True


def test_abort_under_shared_lock_preserves_late_committed_tx_when_journal_append_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox1 = CommitOutbox(tmp_path / "tx")
    outbox2 = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = outbox1

    tx = outbox2.prepare(_make_event(1))
    tx_id = tx["txId"]

    # Direct abort() call after another instance committed the tx must refuse to delete it.
    _ = outbox1.list_open()  # prime outbox1 cache with PREPARED
    outbox2.mark_business_committed(tx_id, observed_generation=1)
    assert outbox1.abort(tx_id) is False
    open_after_direct_abort = outbox1.list_open()
    assert len(open_after_direct_abort) == 1
    assert open_after_direct_abort[0]["status"] == BUSINESS_COMMITTED

    # Now test reconcile when mark_business_committed happens right before abort() AND journal.append fails:
    # the tx must stay in the outbox as BUSINESS_COMMITTED (never lost) and finalize on the next reconcile.
    tx2 = outbox2.prepare(_make_event(2))
    tx2_id = tx2["txId"]
    outbox1.complete(tx_id)

    orig_abort = outbox1.abort
    triggered = {"done": False}

    def mark_before_abort(tid: str) -> bool | None:
        if not triggered["done"] and tid == tx2_id:
            triggered["done"] = True
            outbox2.mark_business_committed(tx2_id, observed_generation=2)
        return orig_abort(tid)

    monkeypatch.setattr(outbox1, "abort", mark_before_abort)
    journal._fail_next = True
    res_fail = outbox1.reconcile(journal=journal, business_committed=lambda _tx: False)
    monkeypatch.setattr(outbox1, "abort", orig_abort)

    assert res_fail == {
        "finalized": 0,
        "aborted": 0,
        "failed": [tx2_id],
        "open": 1,
    }
    remaining = outbox1.list_open()
    assert len(remaining) == 1
    assert remaining[0]["txId"] == tx2_id
    assert remaining[0]["status"] == BUSINESS_COMMITTED
    assert journal.list("ta") == []

    res_ok = outbox1.reconcile(journal=journal, business_committed=lambda _tx: False)
    assert res_ok == {
        "finalized": 1,
        "aborted": 0,
        "failed": [],
        "open": 0,
    }
    assert outbox1.list_open() == []
    events = journal.list("ta")
    assert [e["aggregateId"] for e in events] == ["wo-2"]
    assert journal.verify("ta")["ok"] is True


def test_reconcile_preserves_tx_on_check_semantic_key_errors_and_handles_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = outbox

    # Journal already has event 1 committed; tx1 is still PREPARED on disk (e.g. crash before complete).
    journal.append(
        "outbox.step.1",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-1",
        actor="ops",
        payload={"idx": 1},
        semantic_key="ta::outbox::1",
    )
    tx1 = outbox.prepare(_make_event(1))

    # 1. Transient OSError during real check_semantic_key read must NOT abort tx1 when business_committed is False.
    real_journal_read = journal_mod.read_json
    saved_journal_bytes = read_json(journal._path("ta"))

    def fail_journal_read(_path: Path) -> Any:
        raise OSError("simulated transient journal read failure")

    journal_cold = EventJournal(tmp_path / "journal")
    journal_cold.outbox = outbox
    monkeypatch.setattr(journal_mod, "read_json", fail_journal_read)
    res_io = outbox.reconcile(journal=journal_cold, business_committed=lambda _tx: False)
    monkeypatch.setattr(journal_mod, "read_json", real_journal_read)
    assert res_io == {
        "finalized": 0,
        "aborted": 0,
        "failed": [tx1["txId"]],
        "open": 1,
    }
    assert [t["txId"] for t in outbox.list_open()] == [tx1["txId"]]

    # 2. Tenant isolation PermissionError from real check_semantic_key must ALSO preserve tx1 in failed.
    tampered_tenant = {**saved_journal_bytes, "tenantId": "tb"}
    atomic_write_json(journal._path("ta"), tampered_tenant)
    journal_iso = EventJournal(tmp_path / "journal")
    journal_iso.outbox = outbox
    res_perm = outbox.reconcile(journal=journal_iso, business_committed=lambda _tx: False)
    assert res_perm == {
        "finalized": 0,
        "aborted": 0,
        "failed": [tx1["txId"]],
        "open": 1,
    }
    assert [t["txId"] for t in outbox.list_open()] == [tx1["txId"]]

    # Restore valid journal file: tx1 is now matched against the existing journal event and finalized.
    atomic_write_json(journal._path("ta"), saved_journal_bytes)
    journal_recovered = EventJournal(tmp_path / "journal")
    journal_recovered.outbox = outbox
    res_recovered = outbox.reconcile(journal=journal_recovered, business_committed=lambda _tx: False)
    assert res_recovered == {
        "finalized": 1,
        "aborted": 0,
        "failed": [],
        "open": 0,
    }
    assert outbox.list_open() == []

    # 3. SemanticKeyConflictError handling:
    # Both PREPARED (business_committed=False) and BUSINESS_COMMITTED transactions whose semanticKey
    # conflicts with an already-committed journal event must NOT be finalized or silently aborted;
    # they must be recorded in failed and preserved in the outbox.
    with pytest.raises(SemanticKeyConflictError):
        journal.check_semantic_key(
            tenant_id="ta",
            event_type="outbox.step.1",
            payload={"idx": 888},
            semantic_key="ta::outbox::1",
        )
    bad_uncommitted = _make_event(1)
    bad_uncommitted["payload"] = {"idx": 888}
    tx_conflict_uncommitted = outbox.prepare(bad_uncommitted)

    bad_committed = _make_event(1)
    bad_committed["payload"] = {"idx": 999}
    tx_conflict_committed = outbox.prepare(bad_committed)
    outbox.mark_business_committed(tx_conflict_committed["txId"])

    res_conflict = outbox.reconcile(journal=journal, business_committed=lambda _tx: False)
    assert res_conflict == {
        "finalized": 0,
        "aborted": 0,
        "failed": [tx_conflict_uncommitted["txId"], tx_conflict_committed["txId"]],
        "open": 2,
    }
    assert [t["txId"] for t in outbox.list_open()] == [
        tx_conflict_uncommitted["txId"],
        tx_conflict_committed["txId"],
    ]
    assert [e["payload"] for e in journal.list("ta")] == [{"idx": 1}]

    # Fallback path when journal object does not expose check_semantic_key also preserves conflicting txs in failed.
    class _ListOnlyJournal:
        def list(self, tid: str) -> list[dict[str, Any]]:
            return journal.list(tid)

        def append(self, event_type: str, **kwargs: Any) -> dict[str, Any]:
            return journal.append(event_type, **kwargs)

    res_fallback_conflict = outbox.reconcile(
        journal=_ListOnlyJournal(),
        business_committed=lambda _tx: False,
    )
    assert res_fallback_conflict == {
        "finalized": 0,
        "aborted": 0,
        "failed": [tx_conflict_uncommitted["txId"], tx_conflict_committed["txId"]],
        "open": 2,
    }


def test_reconcile_and_abort_preserve_journal_and_tx_on_stat_eio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = outbox

    first = journal.append(
        "outbox.step.1",
        tenant_id="ta",
        aggregate_type="WorkOrder",
        aggregate_id="wo-1",
        actor="ops",
        payload={"idx": 1},
        semantic_key="ta::outbox::1",
    )
    journal_path = journal._path("ta")
    original_journal_bytes = journal_path.read_bytes()

    tx2 = outbox.prepare(_make_event(2))
    outbox.mark_business_committed(tx2["txId"])
    tx2_path = outbox._path(tx2["txId"])
    orig_stat = Path.stat

    # 1. Transient Path.stat EIO on the journal file during cold reconcile must NOT overwrite event 1
    # and must keep tx2 open in failed.
    def stat_journal_eio(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == journal_path:
            raise OSError(errno.EIO, "simulated journal stat EIO")
        return orig_stat(self, *args, **kwargs)

    journal_cold = EventJournal(tmp_path / "journal")
    journal_cold.outbox = outbox
    monkeypatch.setattr(Path, "stat", stat_journal_eio)
    res_journal_eio = outbox.reconcile(journal=journal_cold, business_committed=lambda _tx: True)
    monkeypatch.setattr(Path, "stat", orig_stat)

    assert res_journal_eio == {
        "finalized": 0,
        "aborted": 0,
        "failed": [tx2["txId"]],
        "open": 1,
    }
    assert journal_path.read_bytes() == original_journal_bytes

    # 2. Transient Path.stat EIO on a BUSINESS_COMMITTED tx file during abort() must raise OSError
    # instead of treating the tx as non-existent/uncommitted and unlinking it.
    outbox_cold = CommitOutbox(tmp_path / "tx")

    def stat_tx_eio(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == tx2_path:
            raise OSError(errno.EIO, "simulated tx stat EIO")
        return orig_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_tx_eio)
    with pytest.raises(OSError) as exc_abort:
        outbox_cold.abort(tx2["txId"])
    assert exc_abort.value.errno == errno.EIO
    monkeypatch.setattr(Path, "stat", orig_stat)
    assert tx2_path.exists()

    # Once Path.stat recovers, reconcile finalizes tx2 alongside event 1 without losing any audit history.
    res_ok = outbox_cold.reconcile(journal=EventJournal(tmp_path / "journal"), business_committed=lambda _tx: True)
    assert res_ok == {
        "finalized": 1,
        "aborted": 0,
        "failed": [],
        "open": 0,
    }
    reloaded_journal = EventJournal(tmp_path / "journal")
    reloaded_journal.outbox = outbox_cold
    events = reloaded_journal.list("ta")
    assert [e["aggregateId"] for e in events] == ["wo-1", "wo-2"]
    assert events[0]["eventId"] == first["eventId"]
    assert reloaded_journal.verify("ta")["ok"] is True


def test_hold_keeps_inflight_tx_when_peer_reconciles_and_recovers_after_release(tmp_path: Path) -> None:
    """Peer reconcile during hold() must not finalize or abort; after release it still can."""
    owner = CommitOutbox(tmp_path / "tx")
    peer = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = peer

    with owner.hold():
        tx_a = owner.prepare(_make_event(1, tenant_id="ta"))
        tx_b = owner.prepare(_make_event(2, tenant_id="tb"))
        res = peer.reconcile(journal=journal, business_committed=lambda _tx: True)
        assert res == {"finalized": 0, "aborted": 0, "failed": [], "open": 2}
        assert read_json(owner._path(tx_a["txId"]))["status"] == PREPARED
        assert read_json(owner._path(tx_b["txId"]))["status"] == PREPARED
        assert [row["txId"] for row in peer.list_open(tenant_id="ta")] == [tx_a["txId"]]
        assert [row["txId"] for row in peer.list_open(tenant_id="tb")] == [tx_b["txId"]]
        marked = owner.mark_business_committed(tx_a["txId"], observed_generation=1)
        assert marked["status"] == BUSINESS_COMMITTED
        # Callback says the business change is absent. A peer must still not abort it
        # while this hold() owns the file.
        res_late = peer.reconcile(journal=journal, business_committed=lambda _tx: False)
        assert res_late["aborted"] == 0
        assert res_late["finalized"] == 0
        assert read_json(owner._path(tx_a["txId"]))["status"] == BUSINESS_COMMITTED
        assert read_json(owner._path(tx_b["txId"]))["status"] == PREPARED
        owner.complete(tx_a["txId"])

    assert not owner._path(tx_a["txId"]).exists()
    assert journal.list("ta") == []
    assert journal.list("tb") == []
    # tx_b was left PREPARED and the hold has released its claim, so recovery aborts it.
    res_abort = peer.reconcile(journal=journal, business_committed=lambda _tx: False)
    assert res_abort == {"finalized": 0, "aborted": 1, "failed": [], "open": 0}
    assert not owner._path(tx_b["txId"]).exists()
    assert peer.list_open() == []


def test_hold_exit_on_error_lets_peer_finalize_business_committed_tx_once(tmp_path: Path) -> None:
    owner = CommitOutbox(tmp_path / "tx")
    peer = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = peer
    tx_id = ""
    with pytest.raises(RuntimeError, match="interrupted"):
        with owner.hold():
            tx = owner.prepare(_make_event(1))
            tx_id = str(tx["txId"])
            owner.mark_business_committed(tx_id)
            raise RuntimeError("interrupted")
    assert read_json(owner._path(tx_id))["status"] == BUSINESS_COMMITTED
    res = peer.reconcile(journal=journal, business_committed=lambda _tx: False)
    assert res == {"finalized": 1, "aborted": 0, "failed": [], "open": 0}
    again = peer.reconcile(journal=journal, business_committed=lambda _tx: True)
    assert again == {"finalized": 0, "aborted": 0, "failed": [], "open": 0}
    events = journal.list("ta")
    assert len(events) == 1
    assert events[0]["aggregateId"] == "wo-1"
    assert events[0]["semanticKey"] == "ta::outbox::1"
    assert journal.verify("ta")["ok"] is True


def test_other_thread_cannot_complete_or_reconcile_away_inflight_tx(tmp_path: Path) -> None:
    owner = CommitOutbox(tmp_path / "tx")
    peer = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = peer
    ready = threading.Event()
    done = threading.Event()
    outcome: dict[str, Any] = {}
    tx_id = ""

    def peer_side() -> None:
        try:
            ready.wait()
            outcome["abort"] = peer.abort(tx_id)
            peer.complete(tx_id)
            outcome["reconcile"] = peer.reconcile(journal=journal, business_committed=lambda _tx: True)
            outcome["exists"] = owner._path(tx_id).exists()
            outcome["status"] = (read_json(owner._path(tx_id)) or {}).get("status")
        except BaseException as exc:
            outcome["peer_error"] = exc
            raise
        finally:
            done.set()

    worker = threading.Thread(target=peer_side)
    worker.start()
    try:
        with owner.hold():
            tx = owner.prepare(_make_event(1))
            tx_id = str(tx["txId"])
            ready.set()
            assert done.wait(timeout=30), "peer thread did not finish"
            assert "peer_error" not in outcome, outcome.get("peer_error")
            assert outcome["abort"] is None
            assert outcome["exists"] is True
            assert outcome["status"] == PREPARED
            assert outcome["reconcile"] == {"finalized": 0, "aborted": 0, "failed": [], "open": 1}
            owner.mark_business_committed(tx_id)
            owner.complete(tx_id)
    finally:
        ready.set()
        worker.join()
    assert not owner._path(tx_id).exists()
    assert journal.list("ta") == []
    assert peer.list_open() == []


def test_claim_held_outside_this_process_blocks_cleanup_until_released(tmp_path: Path) -> None:
    """A claim file locked without this process's registry stands in for another process."""
    owner = CommitOutbox(tmp_path / "tx")
    peer = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = peer
    tx = owner.prepare(_make_event(1))
    tx_id = str(tx["txId"])
    claim = FileLock(owner._claim_path(tx_id))
    claim.acquire()
    try:
        res = peer.reconcile(journal=journal, business_committed=lambda _tx: True)
        assert res == {"finalized": 0, "aborted": 0, "failed": [], "open": 1}
        peer.complete(tx_id)
        assert peer.abort(tx_id) is None
        assert read_json(owner._path(tx_id))["status"] == PREPARED
    finally:
        claim.release()
    res_abort = peer.reconcile(journal=journal, business_committed=lambda _tx: False)
    assert res_abort == {"finalized": 0, "aborted": 1, "failed": [], "open": 0}
    assert not owner._path(tx_id).exists()
    assert journal.list("ta") == []


def test_reconcile_abort_blocked_during_claim_probe_does_not_finalize(tmp_path: Path) -> None:
    """Concurrent claim probing during business_committed must not write journal events."""
    outbox = CommitOutbox(tmp_path / "tx")
    journal = EventJournal(tmp_path / "journal")
    journal.outbox = outbox
    tx = outbox.prepare(_make_event(1))
    tx_id = str(tx["txId"])
    claim_path = outbox._claim_path(tx_id)
    probe_holder: dict[str, FileLock] = {}

    def probe_during_callback(_tx: dict[str, Any]) -> bool:
        probe = FileLock(claim_path)
        assert probe.try_acquire(), "simulated peer must hold claim before abort runs"
        probe_holder["probe"] = probe
        return False

    res = outbox.reconcile(journal=journal, business_committed=probe_during_callback)
    assert res == {"finalized": 0, "aborted": 0, "failed": [], "open": 1}
    assert journal.list("ta") == []
    assert read_json(outbox._path(tx_id))["status"] == PREPARED

    probe = probe_holder.pop("probe")
    probe.release()
    try:
        claim_path.unlink(missing_ok=True)
    except OSError:
        pass

    res_after = outbox.reconcile(journal=journal, business_committed=lambda _tx: False)
    assert res_after == {"finalized": 0, "aborted": 1, "failed": [], "open": 0}
    assert journal.list("ta") == []
    assert not outbox._path(tx_id).exists()

