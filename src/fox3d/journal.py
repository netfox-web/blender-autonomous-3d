"""Durable append-only pilot event journal. Audit/recovery evidence, not event-sourcing."""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.release import (
    can_unlink_migrated_legacy_file,
    conflicting_legacy_owner_at_path,
    is_matching_tenant_stem,
    legacy_safe_tenant_filename,
    order_tenants_for_migration,
    safe_tenant_filename,
)
from fox3d.storelock import FileLock

GENESIS = "GENESIS"
SCHEMA = "fox3d.journal.v1"
_CANONICAL_STEM_RE = re.compile(r"^[a-z0-9_-]+-[0-9a-f]{12}$")

_JOURNAL_GEN_LOCK = threading.Lock()
_JOURNAL_GEN: dict[Path, int] = {}


def _file_sig(path: Path) -> tuple[int, int, int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)


def _journal_key(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _bump_journal_gen(path: Path) -> int:
    key = _journal_key(path)
    with _JOURNAL_GEN_LOCK:
        gen = _JOURNAL_GEN.get(key, 0) + 1
        _JOURNAL_GEN[key] = gen
        return gen


def _get_journal_gen(path: Path) -> int:
    key = _journal_key(path)
    with _JOURNAL_GEN_LOCK:
        return _JOURNAL_GEN.get(key, 0)


class JournalCommitError(RuntimeError):
    """Required durable audit append could not be committed."""


class SemanticKeyConflictError(JournalCommitError, ValueError):
    """Same semantic_key reused with different eventType or payloadHash."""


def _validate_since_seq(since_seq: Any) -> int:
    if isinstance(since_seq, (bool, float)):
        raise ValueError("since_seq must be a non-negative integer")
    if isinstance(since_seq, int):
        seq = since_seq
    elif isinstance(since_seq, str):
        raw = since_seq.strip()
        if not raw:
            raise ValueError("since_seq must be a non-negative integer")
        try:
            seq = int(raw)
        except ValueError as exc:
            raise ValueError("since_seq must be a non-negative integer") from exc
    else:
        raise ValueError("since_seq must be a non-negative integer")
    if seq < 0:
        raise ValueError("since_seq must be a non-negative integer")
    return seq


def _maybe_crash(owner: Any, point: str) -> None:
    if getattr(owner, "_crash_mode", "") != point:
        return
    if getattr(owner, "_hard_crash", False):
        os._exit(1)
    from fox3d.storelock import CrashInjected

    raise CrashInjected(point)


def emit(
    owner: Any,
    event_type: str,
    *,
    tenant_id: str,
    aggregate_type: str,
    aggregate_id: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    release_hash: str | None = None,
    semantic_key: str | None = None,
    source: str | None = None,
) -> dict[str, Any] | None:
    """Persist business snapshot first when possible, then COMMITTED journal."""
    persist = getattr(owner, "persist", None)
    if getattr(owner, "_tx_depth", 0) == 0 and callable(persist):
        # Defer persist to the outbox path below so PREPARED exists first.
        pass
    event = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "actor": actor,
        "payload": payload or {},
        "release_hash": release_hash,
        "semantic_key": semantic_key,
        "source": source,
    }
    journal = getattr(owner, "journal", None)
    outbox = getattr(owner, "outbox", None) or getattr(journal, "outbox", None) if journal is not None else getattr(owner, "outbox", None)
    if journal is None:
        if getattr(owner, "_tx_depth", 0) == 0 and callable(persist):
            persist()
        return None
    if outbox is not None and callable(persist) and getattr(owner, "_tx_depth", 0) == 0:
        if semantic_key and hasattr(journal, "check_semantic_key"):
            journal.check_semantic_key(
                tenant_id=tenant_id,
                event_type=event_type,
                payload=payload or {},
                release_hash=release_hash,
                semantic_key=semantic_key,
            )
        tx = outbox.prepare(event)
        _maybe_crash(owner, "after-outbox-prepare")
        persist()
        if hasattr(outbox, "mark_business_committed"):
            outbox.mark_business_committed(tx["txId"])
        _maybe_crash(owner, "after-business-persist")
        rec = journal.append(
            event_type,
            tenant_id=tenant_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor=actor,
            payload=payload or {},
            release_hash=release_hash,
            semantic_key=semantic_key,
            source=source,
        )
        outbox.complete(tx["txId"])
        _maybe_crash(owner, "after-outbox-complete")
        return rec
    if getattr(owner, "_tx_depth", 0) == 0 and callable(persist):
        if semantic_key and hasattr(journal, "check_semantic_key"):
            journal.check_semantic_key(
                tenant_id=tenant_id,
                event_type=event_type,
                payload=payload or {},
                release_hash=release_hash,
                semantic_key=semantic_key,
            )
        persist()
    return journal.append(
        event_type,
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        actor=actor,
        payload=payload or {},
        release_hash=release_hash,
        semantic_key=semantic_key,
        source=source,
    )


class EventJournal:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._fail_next = False
        self.outbox: Any | None = None
        self._cache: dict[str, dict[str, Any]] = {}
        self._migrate_legacy_files()

    def _safe(self, tenant_id: str) -> str:
        tid = str(tenant_id or "default").strip() or "default"
        return safe_tenant_filename(tid)

    def _legacy_safe(self, tenant_id: str) -> str:
        tid = str(tenant_id or "default").strip() or "default"
        return legacy_safe_tenant_filename(tid)

    def _path(self, tenant_id: str) -> Path:
        return self.root / f"{self._safe(tenant_id)}.json"

    def _legacy_path(self, tenant_id: str) -> Path:
        return self.root / f"{self._legacy_safe(tenant_id)}.json"

    def _lock_path(self, tenant_id: str) -> Path:
        return self.root / f"{self._safe(tenant_id)}.lock"

    def _extract_journal_tid(self, raw: Any) -> str | None:
        if not isinstance(raw, dict) or not raw:
            return None
        tid = raw.get("tenantId")
        if isinstance(tid, str) and tid.strip():
            return tid
        events = raw.get("events") or []
        event_tids = {
            ev["tenantId"]
            for ev in events
            if isinstance(ev, dict)
            and isinstance(ev.get("tenantId"), str)
            and ev["tenantId"].strip()
        }
        if len(event_tids) == 1:
            return next(iter(event_tids))
        return None

    def _is_canonical_journal_for(self, path: Path, tid: str) -> bool:
        if path != self._path(tid):
            return False
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return self._extract_journal_tid(raw) == tid

    def _migrate_legacy_files(self) -> None:
        with self._lock:
            canonical_tids: set[str] = set()
            legacy_by_tid: dict[str, tuple[Path, dict[str, Any]]] = {}
            legacy_to_cleanup: list[tuple[Path, str]] = []
            for path in sorted(self.root.glob("*.json")):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(raw, dict) or not raw:
                    continue
                tid = self._extract_journal_tid(raw)
                if not isinstance(tid, str) or not tid.strip():
                    continue
                canonical = self._path(tid)
                if path == canonical:
                    canonical_tids.add(tid)
                    continue
                if self._legacy_safe(tid).lower() != path.stem.lower():
                    continue
                legacy_by_tid[tid] = (path, raw)
                legacy_to_cleanup.append((path, tid))
            for tid in order_tenants_for_migration(
                legacy_by_tid.keys(), legacy_to_cleanup, self._path
            ):
                path, raw = legacy_by_tid[tid]
                canonical = self._path(tid)
                with FileLock(self._lock_path(tid)):
                    if not self._is_canonical_journal_for(canonical, tid):
                        raw.setdefault("tenantId", tid)
                        atomic_write_json(canonical, raw)
                        _bump_journal_gen(canonical)
            protected_paths = {
                self._path(t) for t in (canonical_tids | set(legacy_by_tid))
            }
            for path, tid in legacy_to_cleanup:
                with FileLock(self._lock_path(tid)):
                    if can_unlink_migrated_legacy_file(
                        path, tid, self._path, protected_paths
                    ):
                        path.unlink(missing_ok=True)
                    old_lock = self.root / f"{path.stem}.lock"
                    if (
                        old_lock != self._lock_path(tid)
                        and old_lock.with_suffix(".json") not in protected_paths
                    ):
                        old_lock.unlink(missing_ok=True)

    def _maybe_migrate_legacy_tenant(
        self, tenant_id: str, *, _visited: set[str] | None = None
    ) -> None:
        tid = str(tenant_id or "default").strip() or "default"
        if _visited is not None and tid in _visited:
            return
        seen = set(_visited) if _visited is not None else set()
        seen.add(tid)
        canonical = self._path(tid)
        occ_tid = conflicting_legacy_owner_at_path(canonical, tid)
        if occ_tid is not None and self._path(occ_tid) != canonical:
            self._maybe_migrate_legacy_tenant(occ_tid, _visited=seen)
            if can_unlink_migrated_legacy_file(canonical, occ_tid, self._path):
                canonical.unlink(missing_ok=True)
        legacy = self._legacy_path(tid)
        candidates: list[Path] = []
        if legacy != canonical and _file_sig(legacy) is not None:
            candidates.append(legacy)
        want_lower = self._legacy_safe(tid).lower()
        for p in sorted(self.root.glob("*.json")):
            if p == canonical or p in candidates:
                continue
            if p.stem.lower() == want_lower:
                candidates.append(p)
        for cand in candidates:
            try:
                raw = read_json(cand)
            except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not raw:
                continue
            file_tid = raw.get("tenantId")
            if file_tid is None:
                events = raw.get("events") or []
                if events and all(isinstance(ev, dict) and ev.get("tenantId") == tid for ev in events):
                    file_tid = tid
                else:
                    continue
            if file_tid == tid:
                if not self._is_canonical_journal_for(canonical, tid):
                    raw.setdefault("tenantId", tid)
                    atomic_write_json(canonical, raw)
                    _bump_journal_gen(canonical)
                if can_unlink_migrated_legacy_file(
                    cand, tid, self._path, {canonical}
                ):
                    cand.unlink(missing_ok=True)
                return
            if isinstance(file_tid, str) and file_tid.strip() and is_matching_tenant_stem(file_tid, cand.stem):
                continue
            raise PermissionError("tenant isolation: journal")

    def _build_semantic_index(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for ev in events:
            if isinstance(ev, dict):
                sk = ev.get("semanticKey")
                if isinstance(sk, str) and sk and sk not in index:
                    index[sk] = ev
        return index

    def _load_entry(self, tenant_id: str, *, force_reload: bool = False) -> dict[str, Any]:
        path = self._path(tenant_id)
        sig_before = _file_sig(path)
        if sig_before is None:
            self._maybe_migrate_legacy_tenant(tenant_id)
            sig_before = _file_sig(path)
        gen_before = _get_journal_gen(path)
        if not force_reload and sig_before is not None:
            cached = self._cache.get(tenant_id)
            if cached is not None and cached.get("sig") == sig_before and cached.get("gen") == gen_before:
                return cached
        payload: dict[str, Any] = {}
        by_semantic_key: dict[str, dict[str, Any]] = {}
        for attempt in range(8):
            if attempt > 0:
                sig_before = _file_sig(path)
                gen_before = _get_journal_gen(path)
            if sig_before is None:
                raw_payload: Any = None
            else:
                try:
                    raw_payload = read_json(path)
                except FileNotFoundError:
                    raw_payload = None
            sig_after = _file_sig(path)
            gen_after = _get_journal_gen(path)
            if raw_payload is None and sig_after is not None:
                continue
            payload = copy.deepcopy(raw_payload) if isinstance(raw_payload, dict) and raw_payload else {}
            if not payload:
                payload = {
                    "tenantId": tenant_id,
                    "schemaVersion": SCHEMA,
                    "headHash": GENESIS,
                    "sequence": 0,
                    "events": [],
                }
            else:
                raw_file_tid = payload.get("tenantId")
                if raw_file_tid not in {None, tenant_id}:
                    if (
                        isinstance(raw_file_tid, str)
                        and raw_file_tid.strip()
                        and self._path(raw_file_tid) != path
                        and self._legacy_safe(raw_file_tid).lower() == path.stem.lower()
                    ):
                        self._maybe_migrate_legacy_tenant(tenant_id)
                        payload = {}
                        continue
                    raise PermissionError("tenant isolation: journal")
                payload.setdefault("events", [])
                payload.setdefault("headHash", GENESIS)
                payload.setdefault("sequence", 0)
                payload.setdefault("schemaVersion", SCHEMA)
            by_semantic_key = self._build_semantic_index(payload["events"])
            if sig_before == sig_after and gen_before == gen_after:
                entry = {
                    "sig": sig_after,
                    "gen": gen_after,
                    "data": payload,
                    "by_semantic_key": by_semantic_key,
                }
                if sig_after is not None:
                    self._cache[tenant_id] = entry
                else:
                    self._cache.pop(tenant_id, None)
                return entry
        self._cache.pop(tenant_id, None)
        if not payload:
            raise OSError(f"unable to load consistent journal state for {path}")
        return {
            "sig": None,
            "gen": -1,
            "data": payload,
            "by_semantic_key": by_semantic_key,
        }

    def _load(self, tenant_id: str, *, force_reload: bool = False) -> dict[str, Any]:
        return self._load_entry(tenant_id, force_reload=force_reload)["data"]

    def _event_hash(self, rec: dict[str, Any]) -> str:
        body = {k: rec[k] for k in rec if k != "eventHash"}
        return stable_hash(body)

    def _find_by_semantic_key(
        self,
        events: list[dict[str, Any]],
        *,
        tenant_id: str,
        event_type: str,
        payload_hash: str,
        release_hash: str | None,
        semantic_key: str,
        semantic_index: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        if semantic_index is not None:
            ev = semantic_index.get(semantic_key)
            candidates = [ev] if ev is not None else []
        else:
            candidates = [e for e in events if e.get("semanticKey") == semantic_key]
        for ev in candidates:
            if ev.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: journal")
            if (
                ev.get("eventType") != event_type
                or ev.get("payloadHash") != payload_hash
                or ev.get("releaseHash") != release_hash
            ):
                raise SemanticKeyConflictError(
                    f"semantic_key conflict for {semantic_key}: eventType, payloadHash, or releaseHash mismatch"
                )
            return copy.deepcopy(ev)
        return None

    def check_semantic_key(
        self,
        *,
        tenant_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        release_hash: str | None = None,
        semantic_key: str | None = None,
    ) -> dict[str, Any] | None:
        if not semantic_key:
            return None
        payload_hash = stable_hash(payload or {})
        with self._lock:
            with FileLock(self._lock_path(tenant_id)):
                entry = self._load_entry(tenant_id)
                return self._find_by_semantic_key(
                    entry["data"]["events"],
                    tenant_id=tenant_id,
                    event_type=event_type,
                    payload_hash=payload_hash,
                    release_hash=release_hash,
                    semantic_key=semantic_key,
                    semantic_index=entry["by_semantic_key"],
                )

    def append(
        self,
        event_type: str,
        *,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        actor: str,
        payload: dict[str, Any] | None = None,
        release_hash: str | None = None,
        semantic_key: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        if self._fail_next:
            self._fail_next = False
            raise JournalCommitError("injected journal failure")
        body = copy.deepcopy(payload) if payload else {}
        payload_hash = stable_hash(body)
        with self._lock:
            with FileLock(self._lock_path(tenant_id)):
                entry = self._load_entry(tenant_id)
                data = entry["data"]
                semantic_index: dict[str, dict[str, Any]] = entry["by_semantic_key"]
                if semantic_key:
                    found = self._find_by_semantic_key(
                        data["events"],
                        tenant_id=tenant_id,
                        event_type=event_type,
                        payload_hash=payload_hash,
                        release_hash=release_hash,
                        semantic_key=semantic_key,
                        semantic_index=semantic_index,
                    )
                    if found is not None:
                        return found
                prev_seq = data.get("sequence")
                prev_head = data.get("headHash")
                prev_tenant = data.get("tenantId")
                seq = int(prev_seq or 0) + 1
                rec = {
                    "eventId": new_id(),
                    "eventType": event_type,
                    "tenantId": tenant_id,
                    "aggregateType": aggregate_type,
                    "aggregateId": aggregate_id,
                    "sequence": seq,
                    "actor": actor,
                    "source": source or actor,
                    "at": utcnow().isoformat(),
                    "releaseHash": release_hash,
                    "payload": body,
                    "payloadHash": payload_hash,
                    "previousEventHash": prev_head or GENESIS,
                    "semanticKey": semantic_key,
                    "schemaVersion": SCHEMA,
                    "commitStatus": "COMMITTED",
                }
                rec["eventHash"] = self._event_hash(rec)
                path = self._path(tenant_id)
                data["events"].append(rec)
                data["sequence"] = seq
                data["headHash"] = rec["eventHash"]
                data["tenantId"] = tenant_id
                try:
                    atomic_write_json(path, data)
                except Exception as exc:
                    data["events"].pop()
                    data["sequence"] = prev_seq
                    data["headHash"] = prev_head
                    data["tenantId"] = prev_tenant
                    self._cache.pop(tenant_id, None)
                    raise JournalCommitError(str(exc)) from exc
                if semantic_key and semantic_key not in semantic_index:
                    semantic_index[semantic_key] = rec
                entry["gen"] = _bump_journal_gen(path)
                try:
                    post_sig = _file_sig(path)
                except OSError:
                    post_sig = None
                if post_sig is not None:
                    entry["sig"] = post_sig
                    self._cache[tenant_id] = entry
                else:
                    self._cache.pop(tenant_id, None)
                return copy.deepcopy(rec)

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                copy.deepcopy(ev)
                for ev in self._load(tenant_id).get("events") or []
                if ev.get("tenantId") == tenant_id
            ]

    def verify(self, tenant_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._load(tenant_id, force_reload=True)
        events = data.get("events") or []
        prev = GENESIS
        for idx, ev in enumerate(events, start=1):
            if ev.get("tenantId") != tenant_id:
                return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "tenant-mix", "label": "BLOCKED_EVIDENCE"}
            if ev.get("previousEventHash") != prev:
                return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "chain-break", "label": "BLOCKED_EVIDENCE"}
            ev_seq = ev.get("sequence")
            if isinstance(ev_seq, bool) or ev_seq != idx:
                return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "sequence-gap", "label": "BLOCKED_EVIDENCE"}
            if self._event_hash(ev) != ev.get("eventHash"):
                return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "payload-tamper", "label": "BLOCKED_EVIDENCE"}
            prev = ev.get("eventHash")
        raw_seq = data.get("sequence", 0)
        if isinstance(raw_seq, bool) or not isinstance(raw_seq, int) or raw_seq < 0:
            return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "truncated", "label": "BLOCKED_EVIDENCE"}
        header_seq = raw_seq
        count = len(events)
        last_seq = events[-1].get("sequence") if events else 0
        if last_seq != header_seq or count != header_seq:
            return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "truncated", "label": "BLOCKED_EVIDENCE"}
        if (data.get("headHash") or GENESIS) != prev:
            return {"ok": False, "status": "BLOCKED_EVIDENCE", "reason": "head-mismatch", "label": "BLOCKED_EVIDENCE"}
        open_tx = []
        if self.outbox is not None:
            open_tx = self.outbox.list_open(tenant_id=tenant_id)
        if open_tx:
            return {
                "ok": False,
                "status": "BLOCKED_EVIDENCE",
                "reason": "incomplete-tx",
                "label": "BLOCKED_EVIDENCE",
                "openTransactions": len(open_tx),
            }
        return {
            "ok": True,
            "status": "REAL",
            "label": "REAL",
            "count": count,
            "headHash": prev,
            "sequence": header_seq,
        }

    def export_slice(self, tenant_id: str, *, since_seq: int = 0) -> dict[str, Any]:
        min_seq = _validate_since_seq(since_seq)
        integrity = self.verify(tenant_id)
        events = [e for e in self.list(tenant_id) if int(e.get("sequence") or 0) >= min_seq]
        bundle = {
            "tenantId": tenant_id,
            "schemaVersion": SCHEMA,
            "exportedAt": utcnow().isoformat(),
            "events": events,
            "integrity": integrity,
            "truthLabel": "REAL" if integrity.get("ok") else "BLOCKED_EVIDENCE",
            "liveMachineControl": False,
        }
        bundle["contentHash"] = stable_hash({"events": events, "integrity": integrity})
        return bundle

    def tamper(self, tenant_id: str, index: int, **fields: Any) -> None:
        """Test helper: break the hash chain."""
        with self._lock:
            with FileLock(self._lock_path(tenant_id)):
                path = self._path(tenant_id)
                data = self._load(tenant_id, force_reload=True)
                data["events"][index].update(fields)
                atomic_write_json(path, data)
                _bump_journal_gen(path)
                self._cache.pop(tenant_id, None)
