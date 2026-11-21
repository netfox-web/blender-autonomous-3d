"""PREPARED -> business commit -> COMMITTED audit outbox. Not event-sourcing."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import SemanticKeyConflictError
from fox3d.storelock import FileLock
# Claim locks keep this object. Tests replace the FileLock name above.
from fox3d.storelock import FileLock as _StoreFileLock

PREPARED = "PREPARED"
BUSINESS_COMMITTED = "BUSINESS_COMMITTED"
ABORTED = "ABORTED"
COMMITTED = "COMMITTED"

_OUTBOX_GEN_LOCK = threading.Lock()
_OUTBOX_STATE: dict[Path, tuple[tuple[int, int, int, int], int]] = {}
_TX_FILE_GEN: dict[Path, int] = {}
# (resolved outbox root, tx id) -> thread that prepared the tx inside hold().
_HOLD_LOCK = threading.Lock()
_HOLD_CLAIMS: dict[tuple[Path, str], int] = {}
_hold_tls = threading.local()


class _HoldBucket:
    def __init__(self) -> None:
        self.depth = 0
        self.claims: list[_HeldClaim] = []


class _HeldClaim:
    def __init__(self, lock: _StoreFileLock, key: tuple[Path, str]) -> None:
        self.lock = lock
        self.key = key


def _hold_buckets() -> dict[Path, _HoldBucket]:
    buckets = getattr(_hold_tls, "buckets", None)
    if buckets is None:
        buckets = {}
        _hold_tls.buckets = buckets
    return buckets


def _hold_depth(root: Path) -> int:
    bucket = _hold_buckets().get(root)
    return bucket.depth if bucket is not None else 0


def _file_sig(path: Path) -> tuple[int, int, int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)


def _tx_key(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _bump_tx_gen(path: Path) -> int:
    resolved = _tx_key(path)
    with _OUTBOX_GEN_LOCK:
        gen = _TX_FILE_GEN.get(resolved, 0) + 1
        _TX_FILE_GEN[resolved] = gen
        return gen


def _get_tx_gen(path: Path) -> int:
    resolved = _tx_key(path)
    with _OUTBOX_GEN_LOCK:
        return _TX_FILE_GEN.get(resolved, 0)


class CommitOutbox:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._resolved_root = self.root.resolve()
        self._lock = threading.RLock()
        self._fail_prepare = False
        self._seq: int | None = None
        self._seq_sig: tuple[int, int, int, int] | None = None
        self._tx_cache: dict[Path, tuple[tuple[int, int, int, int], int, dict[str, Any]]] = {}
        self._read_snapshot: dict[Path, tuple[tuple[int, int, int, int] | None, int]] = {}

    def _path(self, tx_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in tx_id)
        return self.root / f"{safe}.json"

    def _claim_path(self, tx_id: str) -> Path:
        # Suffix .lock is volatile for backup; it is not a transaction record.
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in tx_id)
        return self.root / f"{safe}.claim.lock"

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Own every tx prepared on this thread until the block exits.

        Another instance's reconcile, abort, or complete must not delete those
        files. The claim is a file lock so a second process sees it too, and a
        registry so this process can tell the owner thread from a peer. The
        lock is released when the block exits, including on crash, so a later
        reconcile can recover a tx the owner did not finish.
        """
        root = self._resolved_root
        buckets = _hold_buckets()
        bucket = buckets.get(root)
        if bucket is None:
            bucket = _HoldBucket()
            buckets[root] = bucket
        bucket.depth += 1
        try:
            yield
        finally:
            bucket.depth -= 1
            if bucket.depth == 0:
                claims = list(bucket.claims)
                bucket.claims.clear()
                for claim in claims:
                    self._release_held_claim(claim)
                if buckets.get(root) is bucket and bucket.depth == 0 and not bucket.claims:
                    buckets.pop(root, None)

    def _arm_inflight(self, tx_id: str) -> None:
        root = self._resolved_root
        if _hold_depth(root) <= 0 or not tx_id:
            return
        lock = _StoreFileLock(self._claim_path(tx_id))
        lock.acquire()
        key = (root, tx_id)
        with _HOLD_LOCK:
            _HOLD_CLAIMS[key] = threading.get_ident()
        bucket = _hold_buckets().get(root)
        if bucket is None:
            lock.release()
            with _HOLD_LOCK:
                if _HOLD_CLAIMS.get(key) == threading.get_ident():
                    _HOLD_CLAIMS.pop(key, None)
            return
        bucket.claims.append(_HeldClaim(lock, key))

    def _release_held_claim(self, claim: _HeldClaim) -> None:
        with _HOLD_LOCK:
            if _HOLD_CLAIMS.get(claim.key) == threading.get_ident():
                _HOLD_CLAIMS.pop(claim.key, None)
        path = claim.lock.path
        try:
            claim.lock.release()
        except OSError:
            pass
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _claim_held_elsewhere(self, tx_id: str) -> bool:
        """True when a live owner outside this registry entry still holds the claim file."""
        if not tx_id:
            return False
        path = self._claim_path(tx_id)
        try:
            if not path.exists():
                return False
        except OSError:
            return True
        lock = _StoreFileLock(path)
        if not lock.try_acquire():
            return True
        lock.release()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    def _owned_by_live_peer(self, tx_id: str) -> bool:
        """True when reconcile must leave this tx alone.

        Includes a hold() on this same thread: startup reconcile of another
        instance can run re-entrantly while the owner is between prepare and
        mark, and must not finalize or abort that tx.
        """
        if not tx_id:
            return False
        key = (self._resolved_root, tx_id)
        with _HOLD_LOCK:
            if key in _HOLD_CLAIMS:
                return True
        return self._claim_held_elsewhere(tx_id)

    def _mutation_blocked(self, tx_id: str) -> bool:
        """True when complete/abort would steal a tx from another owner."""
        if not tx_id:
            return False
        key = (self._resolved_root, tx_id)
        me = threading.get_ident()
        with _HOLD_LOCK:
            owner = _HOLD_CLAIMS.get(key)
        if owner is not None:
            return owner != me
        return self._claim_held_elsewhere(tx_id)

    def _seq_path(self) -> Path:
        return self.root / "outbox.seq.staging"

    def _cache_get(
        self,
        path: Path,
        *,
        sig: tuple[int, int, int, int] | None = None,
        gen: int | None = None,
    ) -> dict[str, Any] | None:
        cur_sig = _file_sig(path) if sig is None else sig
        if cur_sig is None:
            self._tx_cache.pop(path, None)
            return None
        cur_gen = _get_tx_gen(path) if gen is None else gen
        entry = self._tx_cache.get(path)
        if entry is not None and entry[0] == cur_sig and entry[1] == cur_gen:
            return copy.deepcopy(entry[2])
        return None

    def _cache_put(self, path: Path, rec: dict[str, Any], *, bump: bool = False) -> None:
        if bump:
            gen = _bump_tx_gen(path)
            try:
                sig = _file_sig(path)
            except OSError:
                sig = None
            if sig is not None:
                self._tx_cache[path] = (sig, gen, copy.deepcopy(rec))
            else:
                self._tx_cache.pop(path, None)
            return
        sig = _file_sig(path)
        gen = _get_tx_gen(path)
        expected = self._read_snapshot.get(path)
        if sig is None or (expected is not None and (sig != expected[0] or gen != expected[1])):
            self._tx_cache.pop(path, None)
            return
        self._tx_cache[path] = (sig, gen, copy.deepcopy(rec))

    def _load_tx_file(self, path: Path) -> dict[str, Any]:
        sig_before = _file_sig(path)
        gen_before = _get_tx_gen(path)
        cached = self._cache_get(path, sig=sig_before, gen=gen_before)
        if cached is not None:
            return cached
        last_rec: dict[str, Any] = {}
        for attempt in range(8):
            if attempt > 0:
                sig_before = _file_sig(path)
                gen_before = _get_tx_gen(path)
            if sig_before is None:
                self._tx_cache.pop(path, None)
                return {}
            self._read_snapshot[path] = (sig_before, gen_before)
            try:
                try:
                    raw = read_json(path)
                except FileNotFoundError:
                    raw = None
                if not isinstance(raw, dict) or not raw:
                    if _file_sig(path) is None:
                        self._tx_cache.pop(path, None)
                        return {}
                    continue
                last_rec = raw
                self._cache_put(path, raw, bump=False)
                entry = self._tx_cache.get(path)
                if (
                    entry is not None
                    and entry[0] == sig_before
                    and entry[1] == gen_before
                    and _file_sig(path) == sig_before
                    and _get_tx_gen(path) == gen_before
                ):
                    return copy.deepcopy(raw)
            finally:
                self._read_snapshot.pop(path, None)
        self._tx_cache.pop(path, None)
        if not last_rec and _file_sig(path) is not None:
            raise OSError(f"unable to load consistent outbox tx state for {path}")
        return copy.deepcopy(last_rec)

    def _scan_max_seq(self) -> int:
        max_seq = 0
        for path in self.root.glob("*.json"):
            existing = self._load_tx_file(path)
            seq_val = existing.get("seq")
            if isinstance(seq_val, int) and not isinstance(seq_val, bool) and seq_val > max_seq:
                max_seq = seq_val
        return max_seq

    def _next_seq(self) -> int:
        seq_path = self._seq_path()
        cur_sig = _file_sig(seq_path)
        with _OUTBOX_GEN_LOCK:
            mem_state = _OUTBOX_STATE.get(self._resolved_root)
        if (
            self._seq is not None
            and cur_sig is not None
            and cur_sig == self._seq_sig
            and mem_state is not None
            and mem_state[0] == cur_sig
            and mem_state[1] == self._seq
        ):
            base_seq = self._seq
        elif cur_sig is not None and mem_state is not None and mem_state[0] == cur_sig:
            base_seq = max(self._seq or 0, mem_state[1])
        elif cur_sig is not None:
            try:
                raw = seq_path.read_text(encoding="utf-8").strip().split(":", 1)[0]
                disk_seq = int(raw)
                if disk_seq < 0:
                    raise ValueError("negative seq")
                base_seq = max(self._seq or 0, disk_seq)
            except (FileNotFoundError, ValueError):
                base_seq = max(self._seq or 0, self._scan_max_seq())
        else:
            base_seq = max(self._seq or 0, self._scan_max_seq())
        next_seq = base_seq + 1
        self._persist_seq(next_seq)
        return next_seq

    def _persist_seq(self, seq: int) -> None:
        seq_path = self._seq_path()
        seq_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "outbox.seq.tmp"
        tmp.write_text(f"{seq}\n", encoding="utf-8")
        for attempt in range(6):
            try:
                tmp.replace(seq_path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02 * (2 ** attempt))
        try:
            sig = _file_sig(seq_path)
        except OSError:
            sig = None
        self._seq = seq
        self._seq_sig = sig
        if sig is not None:
            with _OUTBOX_GEN_LOCK:
                _OUTBOX_STATE[self._resolved_root] = (sig, seq)
        else:
            with _OUTBOX_GEN_LOCK:
                _OUTBOX_STATE.pop(self._resolved_root, None)

    def prepare(self, event: dict[str, Any], *, expected_generation: int | None = None) -> dict[str, Any]:
        if self._fail_prepare:
            self._fail_prepare = False
            from fox3d.journal import JournalCommitError

            raise JournalCommitError("injected outbox prepare failure")
        stored_event = copy.deepcopy(event)
        with self._lock:
            with FileLock(self.root / "outbox.lock"):
                seq = self._next_seq()
                rec = {
                    "txId": new_id(),
                    "seq": seq,
                    "status": PREPARED,
                    "tenantId": stored_event.get("tenant_id") or stored_event.get("tenantId"),
                    "semanticKey": stored_event.get("semantic_key") or stored_event.get("semanticKey"),
                    "aggregateType": stored_event.get("aggregate_type") or stored_event.get("aggregateType"),
                    "aggregateId": stored_event.get("aggregate_id") or stored_event.get("aggregateId"),
                    "event": stored_event,
                    "expectedGeneration": expected_generation,
                    "at": utcnow().isoformat(),
                }
                rec["txHash"] = stable_hash({k: rec[k] for k in rec if k != "txHash"})
                path = self._path(str(rec["txId"]))
                # Claim before the json is visible so a peer cannot observe a
                # PREPARED file that this hold() does not yet own.
                self._arm_inflight(str(rec["txId"]))
                atomic_write_json(path, rec)
                self._cache_put(path, rec, bump=True)
        return copy.deepcopy(rec)

    def mark_business_committed(self, tx_id: str, *, observed_generation: int | None = None) -> dict[str, Any]:
        with self._lock:
            with FileLock(self.root / "outbox.lock"):
                rec = self._read(tx_id)
                rec["status"] = BUSINESS_COMMITTED
                rec["observedGeneration"] = observed_generation
                rec["businessCommittedAt"] = utcnow().isoformat()
                path = self._path(tx_id)
                atomic_write_json(path, rec)
                self._cache_put(path, rec, bump=True)
                return copy.deepcopy(rec)

    def complete(self, tx_id: str) -> bool:
        if self._mutation_blocked(tx_id):
            return False
        with self._lock:
            with FileLock(self.root / "outbox.lock"):
                path = self._path(tx_id)
                self._tx_cache.pop(path, None)
                _bump_tx_gen(path)
                path.unlink(missing_ok=True)
        return True

    def abort(self, tx_id: str) -> bool | None:
        if self._mutation_blocked(tx_id):
            return None
        with self._lock:
            with FileLock(self.root / "outbox.lock"):
                path = self._path(tx_id)
                rec = self._load_tx_file(path)
                if rec.get("status") in {BUSINESS_COMMITTED, COMMITTED}:
                    return False
                self._tx_cache.pop(path, None)
                _bump_tx_gen(path)
                path.unlink(missing_ok=True)
                return True

    def _read(self, tx_id: str) -> dict[str, Any]:
        path = self._path(tx_id)
        rec = self._load_tx_file(path)
        if not rec:
            raise KeyError(tx_id)
        return rec

    def list_open(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        rows = []
        with self._lock:
            paths = sorted(self.root.glob("*.json"))
            active = set(paths)
            for cached_path in list(self._tx_cache):
                if cached_path not in active:
                    self._tx_cache.pop(cached_path, None)
            for path in paths:
                rec = self._load_tx_file(path)
                if rec.get("status") in {PREPARED, BUSINESS_COMMITTED}:
                    if tenant_id is None or rec.get("tenantId") == tenant_id:
                        rows.append(rec)
        rows.sort(
            key=lambda r: (
                r["seq"] if isinstance(r.get("seq"), int) and not isinstance(r.get("seq"), bool) else 0,
                str(r.get("at") or ""),
                str(r.get("txId") or ""),
            )
        )
        return rows

    def reconcile(
        self,
        *,
        journal: Any,
        business_committed: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any]:
        """Deterministic recovery. PREPARED without business -> abort. Business without journal -> finalize."""
        finalized = 0
        aborted = 0
        failed: list[str] = []
        for tx in self.list_open():
            tx_id = str(tx.get("txId") or "")
            try:
                if tx_id and self._owned_by_live_peer(tx_id):
                    continue
                if tx_id and not self._load_tx_file(self._path(tx_id)):
                    continue
                ev = dict(tx.get("event") or {})
                tenant_id = str(ev.get("tenant_id") or tx.get("tenantId") or "")
                semantic = tx.get("semanticKey")
                event_type = str(ev.get("event_type") or ev.get("eventType") or "reconcile")
                payload = dict(ev.get("payload") or {})
                if journal is not None and semantic:
                    rel_hash = ev.get("release_hash") or ev.get("releaseHash")
                    if hasattr(journal, "check_semantic_key"):
                        found = journal.check_semantic_key(
                            tenant_id=tenant_id,
                            event_type=event_type,
                            payload=payload,
                            release_hash=rel_hash,
                            semantic_key=semantic,
                        )
                        if found is not None:
                            if self.complete(tx_id):
                                finalized += 1
                            continue
                    else:
                        existing = [e for e in journal.list(tenant_id) if e.get("semanticKey") == semantic]
                        if existing:
                            payload_hash = stable_hash(payload)
                            if any(
                                e.get("eventType") == event_type
                                and e.get("payloadHash") == payload_hash
                                and e.get("releaseHash") == rel_hash
                                for e in existing
                            ):
                                if self.complete(tx_id):
                                    finalized += 1
                                continue
                            raise SemanticKeyConflictError(
                                f"semantic_key conflict for {semantic}: eventType, payloadHash, or releaseHash mismatch"
                            )
                try:
                    committed = bool(business_committed(tx))
                except Exception:
                    committed = False
                if not committed and tx.get("status") != BUSINESS_COMMITTED:
                    latest = self._load_tx_file(self._path(tx_id))
                    if latest:
                        tx = latest
                if not committed and tx.get("status") != BUSINESS_COMMITTED:
                    aborted_ok = self.abort(tx_id)
                    if aborted_ok is None:
                        continue
                    latest = self._load_tx_file(self._path(tx_id))
                    if aborted_ok is False or latest.get("status") in {BUSINESS_COMMITTED, COMMITTED}:
                        if latest:
                            tx = latest
                        committed = True
                    else:
                        aborted += 1
                        continue
                if committed or tx.get("status") == BUSINESS_COMMITTED:
                    if journal is not None:
                        ev = dict(tx.get("event") or {})
                        tenant_id = str(ev.get("tenant_id") or tx.get("tenantId") or "")
                        semantic = tx.get("semanticKey")
                        event_type = str(ev.get("event_type") or ev.get("eventType") or "reconcile")
                        payload = dict(ev.get("payload") or {})
                        journal.append(
                            event_type,
                            tenant_id=tenant_id,
                            aggregate_type=str(ev.get("aggregate_type") or tx.get("aggregateType") or "Unknown"),
                            aggregate_id=str(ev.get("aggregate_id") or tx.get("aggregateId") or tx_id),
                            actor=str(ev.get("actor") or "reconcile"),
                            payload=payload,
                            release_hash=ev.get("release_hash") or ev.get("releaseHash"),
                            semantic_key=semantic,
                            source=str(ev.get("source") or "reconcile"),
                        )
                    if self.complete(tx_id):
                        finalized += 1
            except Exception:
                failed.append(tx_id)
        try:
            open_count = len(self.list_open())
        except OSError:
            open_count = max(len(failed), len(list(self.root.glob("*.json"))))
        return {"finalized": finalized, "aborted": aborted, "failed": failed, "open": open_count}
