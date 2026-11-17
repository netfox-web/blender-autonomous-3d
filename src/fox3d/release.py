"""Approval audit trail, staleness, and release-candidate states. Not LIVE_CNC.

Release states advance strictly one step at a time along ``RC_STATES`` (no skipping).
``WAITING_APPROVAL`` and ``APPROVED_FOR_EXPORT`` require having reached ``EVIDENCE_VERIFIED``
because sequential advancement enforces that path. Approval records are keyed by
``(tenantId, entityId)`` so tenants cannot collide on the same entity id.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.storelock import FileLock

RC_STATES = (
    "PROTOTYPE",
    "ENGINEERING_VALID",
    "EVIDENCE_VERIFIED",
    "WAITING_APPROVAL",
    "APPROVED_FOR_EXPORT",
)
FORBIDDEN = frozenset({"LIVE_CNC", "LIVE_LASER", "APPROVED_FOR_PRODUCTION", "APPROVED_FOR_MACHINE"})
BOUND_HASH_KEYS = (
    "engineeringHash",
    "bomHash",
    "nestingHash",
    "costHash",
    "packagingHash",
    "evidenceHash",
)
MAX_EVENTS_PER_TENANT = 20
MAX_RELEASE_EVENTS_PER_TENANT = MAX_EVENTS_PER_TENANT
_CANONICAL_TENANT_STEM_RE = re.compile(r"^[a-z0-9_-]+-[0-9a-f]{12}$")


def sorted_tenant_json_paths(folder: Path) -> list[Path]:
    """Return ``*.json`` paths with legacy filenames before canonical hashed filenames."""
    return sorted(
        folder.glob("*.json"),
        key=lambda p: (bool(_CANONICAL_TENANT_STEM_RE.match(p.stem)), p.name),
    )


def legacy_safe_tenant_filename(tenant_id: str) -> str:
    tid = str(tenant_id or "").strip()
    if not tid:
        raise ValueError("tenantId must be a non-empty string")
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in tid)


def safe_tenant_filename(tenant_id: str) -> str:
    tid = str(tenant_id or "").strip()
    if not tid:
        raise ValueError("tenantId must be a non-empty string")
    cleaned = "".join(
        ch.lower() if (ch.isascii() and ch.isalnum()) or ch in "-_" else "_"
        for ch in tid
    ).strip("_")[:64] or "tenant"
    digest = hashlib.sha256(tid.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned}-{digest}"


def is_matching_tenant_stem(tenant_id: str, stem: str) -> bool:
    if safe_tenant_filename(tenant_id) == stem:
        return True
    legacy = legacy_safe_tenant_filename(tenant_id)
    return legacy == stem or legacy.lower() == stem.lower()


def find_legacy_tenant_file(folder: Path, tenant_id: str) -> Path | None:
    tid = str(tenant_id or "default").strip() or "default"
    canonical = folder / f"{safe_tenant_filename(tid)}.json"
    direct = folder / f"{legacy_safe_tenant_filename(tid)}.json"
    candidates: list[Path] = []
    if direct != canonical and direct.is_file():
        candidates.append(direct)
    want_lower = legacy_safe_tenant_filename(tid).lower()
    for p in sorted(folder.glob("*.json")):
        if p == canonical or p in candidates:
            continue
        if p.stem.lower() == want_lower:
            candidates.append(p)
    for cand in candidates:
        try:
            raw = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return cand
        if not isinstance(raw, dict):
            return cand
        file_tid = raw.get("tenantId")
        if not isinstance(file_tid, str) or not file_tid.strip():
            return cand
        if file_tid == tid:
            return cand
        if legacy_safe_tenant_filename(file_tid).lower() != cand.stem.lower():
            return cand
    return None


def file_sig(path: Path) -> tuple[int, int, int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)


def atomic_write_tenant_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{new_id()[:8]}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    owned = False
    try:
        with tmp.open("x", encoding="utf-8") as fh:
            owned = True
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(6):
            try:
                tmp.replace(path)
                owned = False
                return
            except PermissionError:
                if sys.platform != "win32" or attempt == 5:
                    raise
                time.sleep(0.02 * (2**attempt))
    finally:
        if owned and tmp.exists():
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def read_validated_tenant_json(path: Path, *, required_lists: tuple[str, ...]) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"corrupt state file {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"corrupt state file {path}: root must be an object")
    tid = payload.get("tenantId")
    if not isinstance(tid, str) or not tid.strip():
        raise ValueError(f"corrupt state file {path}: missing or invalid tenantId")
    if not is_matching_tenant_stem(tid, path.stem):
        raise ValueError(
            f"corrupt state file {path}: tenantId {tid!r} does not match filename {path.name}"
        )
    for key in required_lists:
        if key not in payload or not isinstance(payload[key], list):
            raise ValueError(f"corrupt state file {path}: missing or invalid list {key!r}")
    return payload


@contextmanager
def reentrant_store_lock(
    rlock: threading.RLock, state: dict[str, int], lock_path: Path | None
) -> Iterator[None]:
    with rlock:
        flock: FileLock | None = None
        depth = state.get("depth", 0)
        if depth == 0 and lock_path is not None:
            flock = FileLock(lock_path)
            flock.acquire()
        state["depth"] = depth + 1
        try:
            yield
        finally:
            state["depth"] = depth
            if depth == 0 and flock is not None:
                flock.release()


class TenantItemsMixin:
    _store_dir_name: str = "items"
    _alias_dir_names: tuple[str, ...] = ()
    _id_key: str = "productId"
    platform: Any
    root: Path | None
    items: dict[str, dict[str, Any]]
    _lock: threading.RLock
    _lock_state: dict[str, int]
    _sigs: dict[str, tuple[int, int, int, int] | None]

    def _init_item_store(
        self,
        platform: Any = None,
        root: Path | None = None,
        *,
        shared: TenantItemsMixin | None = None,
    ) -> None:
        self.platform = platform
        plat_root = getattr(platform, "root", None)
        base_root = Path(root) if root else (
            Path(plat_root) / self._store_dir_name if plat_root is not None else None
        )
        self.root = base_root
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
        if shared is not None and shared.root == self.root:
            self.items = shared.items
            self._lock = shared._lock
            self._lock_state = shared._lock_state
            self._sigs = shared._sigs
        else:
            self.items = {}
            self._lock = threading.RLock()
            self._lock_state = {"depth": 0}
            self._sigs = {}
        if self.root is not None:
            self.load()

    def _lock_path(self) -> Path | None:
        return (self.root / f"{self._store_dir_name}.lock") if self.root is not None else None

    @contextmanager
    def _locked_store(self) -> Iterator[None]:
        with reentrant_store_lock(self._lock, self._lock_state, self._lock_path()):
            yield

    def _normalize_tenant(self, tenant_id: str | None) -> str:
        tid = str(tenant_id or "default").strip()
        return tid or "default"

    def _tenant_path(self, tenant_id: str) -> Path | None:
        if self.root is None:
            return None
        return self.root / f"{safe_tenant_filename(self._normalize_tenant(tenant_id))}.json"

    def _candidate_dirs(self) -> list[Path]:
        if self.root is None:
            return []
        dirs = [self.root]
        for alias in self._alias_dir_names:
            alt = self.root.parent / alias
            if alt != self.root and alt.is_dir():
                dirs.append(alt)
        return dirs

    def _parse_items_file(self, path: Path) -> tuple[str, dict[str, dict[str, Any]]]:
        payload = read_validated_tenant_json(path, required_lists=("items",))
        tid = str(payload["tenantId"])
        out: dict[str, dict[str, Any]] = {}
        for rec in payload["items"]:
            if not isinstance(rec, dict):
                raise ValueError(f"corrupt state file {path}: item must be an object")
            item_id = rec.get(self._id_key)
            if not isinstance(item_id, str) or not item_id.strip():
                raise ValueError(f"corrupt state file {path}: item missing {self._id_key}")
            if rec.get("tenantId") != tid:
                raise ValueError(f"corrupt state file {path}: item tenantId mismatch")
            out[item_id] = rec
        return tid, out

    def _on_item_loaded(self, item_id: str, rec: dict[str, Any]) -> None:
        _ = (item_id, rec)

    def load(self) -> None:
        if self.root is None:
            return
        with self._locked_store():
            new_items: dict[str, dict[str, Any]] = {}
            new_sigs: dict[str, tuple[int, int, int, int] | None] = {}
            legacy_to_migrate: list[tuple[Path, str]] = []
            for folder in self._candidate_dirs():
                for path in sorted_tenant_json_paths(folder):
                    tid, parsed = self._parse_items_file(path)
                    new_items.update(parsed)
                    if folder == self.root:
                        canonical = self._tenant_path(tid)
                        if canonical is not None and path != canonical:
                            legacy_to_migrate.append((path, tid))
                        else:
                            new_sigs[tid] = file_sig(path)
            self.items.clear()
            self.items.update(new_items)
            self._sigs.clear()
            self._sigs.update(new_sigs)
            for legacy_path, tid in legacy_to_migrate:
                self._persist_tenant_unlocked(tid)
                if legacy_path.exists() and legacy_path != self._tenant_path(tid):
                    legacy_path.unlink(missing_ok=True)
            for item_id, rec in self.items.items():
                self._on_item_loaded(item_id, rec)

    def _sync_tenant(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        with self._locked_store():
            sig = file_sig(path)
            if sig is None:
                legacy_path = find_legacy_tenant_file(self.root, tid)
                if legacy_path is not None:
                    _, parsed = self._parse_items_file(legacy_path)
                    for k in [
                        iid
                        for iid, r in self.items.items()
                        if self._normalize_tenant(r.get("tenantId")) == tid
                    ]:
                        self.items.pop(k, None)
                    self.items.update(parsed)
                    for item_id, rec in parsed.items():
                        self._on_item_loaded(item_id, rec)
                    self._persist_tenant_unlocked(tid)
                    if legacy_path.exists() and legacy_path != path:
                        legacy_path.unlink(missing_ok=True)
                    return
                if tid in self._sigs:
                    for k in [
                        iid
                        for iid, r in self.items.items()
                        if self._normalize_tenant(r.get("tenantId")) == tid
                    ]:
                        self.items.pop(k, None)
                    self._sigs.pop(tid, None)
                return
            if self._sigs.get(tid) == sig:
                return
            _, parsed = self._parse_items_file(path)
            for k in [
                iid
                for iid, r in self.items.items()
                if self._normalize_tenant(r.get("tenantId")) == tid
            ]:
                self.items.pop(k, None)
            self.items.update(parsed)
            for item_id, rec in parsed.items():
                self._on_item_loaded(item_id, rec)
            self._sigs[tid] = file_sig(path)

    def _persist_tenant_unlocked(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        tenant_items = [
            rec
            for rec in self.items.values()
            if self._normalize_tenant(rec.get("tenantId")) == tid
        ]
        if tenant_items:
            atomic_write_tenant_json(
                path,
                {
                    "tenantId": tid,
                    "items": tenant_items,
                },
            )
            self._sigs[tid] = file_sig(path)
        else:
            path.unlink(missing_ok=True)
            self._sigs.pop(tid, None)

    def persist(self, *, tenant_id: str | None = None) -> None:
        if self.root is None:
            return
        with self._locked_store():
            if tenant_id is not None:
                self._persist_tenant_unlocked(tenant_id)
                return
            tenants = {self._normalize_tenant(r.get("tenantId")) for r in self.items.values()}
            for tid in sorted(tenants):
                self._persist_tenant_unlocked(tid)

    def _store_item(self, item_id: str, rec: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
        with self._locked_store():
            self._sync_tenant(tenant_id)
            self.items[item_id] = rec
            self._persist_tenant_unlocked(tenant_id)
        return rec

    def list(self, *, tenant_id: str) -> list[dict[str, Any]]:
        tid = self._normalize_tenant(tenant_id)
        with self._locked_store():
            self._sync_tenant(tid)
            return [
                rec
                for rec in self.items.values()
                if self._normalize_tenant(rec.get("tenantId")) == tid
            ]


class ReleaseGate:
    def __init__(
        self,
        root: Path | None = None,
        *,
        max_events_per_tenant: int = MAX_EVENTS_PER_TENANT,
    ) -> None:
        self.root = Path(root) if root else None
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
        self.max_events_per_tenant = max_events_per_tenant
        self.events: list[dict[str, Any]] = []
        self.approvals: dict[tuple[str, str], dict[str, Any]] = {}
        self._locks_guard = threading.Lock()
        self._key_locks: dict[tuple[str, str], threading.RLock] = {}
        self._store_lock = threading.RLock()
        self._lock_state: dict[str, int] = {"depth": 0}
        self._sigs: dict[str, tuple[int, int, int, int] | None] = {}
        if self.root is not None:
            self.load()

    def _lock_path(self) -> Path | None:
        return (self.root / "release_gate.lock") if self.root is not None else None

    @contextmanager
    def _locked_store(self) -> Iterator[None]:
        with reentrant_store_lock(self._store_lock, self._lock_state, self._lock_path()):
            yield

    def _normalize_tenant(self, tenant_id: str | None) -> str:
        tid = str(tenant_id or "default").strip()
        return tid or "default"

    def _tenant_path(self, tenant_id: str) -> Path | None:
        if self.root is None:
            return None
        return self.root / f"{safe_tenant_filename(self._normalize_tenant(tenant_id))}.json"

    def _candidate_dirs(self) -> list[Path]:
        if self.root is None:
            return []
        dirs = [self.root]
        alt = self.root.parent / "release"
        if alt != self.root and alt.is_dir():
            dirs.append(alt)
        return dirs

    def _cap_tenant_events(
        self, events: list[dict[str, Any]], *, max_per_tenant: int | None = None
    ) -> list[dict[str, Any]]:
        limit = (
            self.max_events_per_tenant
            if max_per_tenant is None
            else int(max_per_tenant)
        )
        if limit <= 0:
            return []
        return events[-limit:]

    def _parse_tenant_file(
        self, path: Path
    ) -> tuple[str, dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
        payload = read_validated_tenant_json(path, required_lists=("approvals", "events"))
        tid = str(payload["tenantId"])
        approvals: dict[tuple[str, str], dict[str, Any]] = {}
        for rec in payload["approvals"]:
            if not isinstance(rec, dict):
                raise ValueError(f"corrupt state file {path}: approval must be an object")
            eid = rec.get("entityId")
            state = rec.get("state")
            if not isinstance(eid, str) or not eid.strip():
                raise ValueError(f"corrupt state file {path}: approval missing entityId")
            if rec.get("tenantId") != tid:
                raise ValueError(f"corrupt state file {path}: approval tenantId mismatch")
            if state not in RC_STATES:
                raise ValueError(f"corrupt state file {path}: invalid approval state {state!r}")
            approvals[(tid, eid)] = rec
        events: list[dict[str, Any]] = []
        for ev in payload["events"]:
            if not isinstance(ev, dict):
                raise ValueError(f"corrupt state file {path}: event must be an object")
            ev_id = ev.get("eventId")
            eid = ev.get("entityId")
            if not isinstance(ev_id, str) or not ev_id.strip():
                raise ValueError(f"corrupt state file {path}: event missing eventId")
            if not isinstance(eid, str) or not eid.strip():
                raise ValueError(f"corrupt state file {path}: event missing entityId")
            ev_tid = self._normalize_tenant(ev.get("tenantId"))
            if ev_tid != tid:
                raise ValueError(f"corrupt state file {path}: event tenantId mismatch")
            events.append(ev)
        return tid, approvals, self._cap_tenant_events(events)

    def load(self) -> None:
        if self.root is None:
            return
        with self._locked_store():
            new_approvals: dict[tuple[str, str], dict[str, Any]] = {}
            by_tenant_events: dict[str, list[dict[str, Any]]] = {}
            new_sigs: dict[str, tuple[int, int, int, int] | None] = {}
            legacy_to_migrate: list[tuple[Path, str]] = []
            for folder in self._candidate_dirs():
                for path in sorted_tenant_json_paths(folder):
                    tid, approvals, events = self._parse_tenant_file(path)
                    new_approvals.update(approvals)
                    combined = [*by_tenant_events.get(tid, []), *events]
                    by_tenant_events[tid] = self._cap_tenant_events(combined)
                    if folder == self.root:
                        canonical = self._tenant_path(tid)
                        if canonical is not None and path != canonical:
                            legacy_to_migrate.append((path, tid))
                        else:
                            new_sigs[tid] = file_sig(path)
            self.approvals = new_approvals
            self.events = [ev for tid_events in by_tenant_events.values() for ev in tid_events]
            self._sigs = new_sigs
            for legacy_path, tid in legacy_to_migrate:
                self._persist_tenant_unlocked(tid)
                if legacy_path.exists() and legacy_path != self._tenant_path(tid):
                    legacy_path.unlink(missing_ok=True)

    def _sync_tenant(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        with self._locked_store():
            sig = file_sig(path)
            if sig is None:
                legacy_path = find_legacy_tenant_file(self.root, tid)
                if legacy_path is not None:
                    _, approvals, events = self._parse_tenant_file(legacy_path)
                    for key in [k for k in self.approvals if k[0] == tid]:
                        self.approvals.pop(key, None)
                    self.approvals.update(approvals)
                    other_events = [
                        e for e in self.events if self._normalize_tenant(e.get("tenantId")) != tid
                    ]
                    self.events = [*other_events, *events]
                    self._persist_tenant_unlocked(tid)
                    if legacy_path.exists() and legacy_path != path:
                        legacy_path.unlink(missing_ok=True)
                    return
                if tid in self._sigs:
                    for key in [k for k in self.approvals if k[0] == tid]:
                        self.approvals.pop(key, None)
                    self.events = [
                        e for e in self.events if self._normalize_tenant(e.get("tenantId")) != tid
                    ]
                    self._sigs.pop(tid, None)
                return
            if self._sigs.get(tid) == sig:
                return
            _, approvals, events = self._parse_tenant_file(path)
            for key in [k for k in self.approvals if k[0] == tid]:
                self.approvals.pop(key, None)
            self.approvals.update(approvals)
            other_events = [
                e for e in self.events if self._normalize_tenant(e.get("tenantId")) != tid
            ]
            self.events = [*other_events, *events]
            self._sigs[tid] = file_sig(path)

    def _persist_tenant_unlocked(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        tenant_approvals = [rec for (t, _), rec in self.approvals.items() if t == tid]
        tenant_events = self._cap_tenant_events(
            [ev for ev in self.events if self._normalize_tenant(ev.get("tenantId")) == tid]
        )
        other_events = [
            ev for ev in self.events if self._normalize_tenant(ev.get("tenantId")) != tid
        ]
        self.events = [*other_events, *tenant_events]
        if tenant_approvals or tenant_events:
            atomic_write_tenant_json(
                path,
                {
                    "tenantId": tid,
                    "approvals": tenant_approvals,
                    "events": tenant_events,
                },
            )
            self._sigs[tid] = file_sig(path)
        else:
            path.unlink(missing_ok=True)
            self._sigs.pop(tid, None)

    def persist(self, *, tenant_id: str | None = None) -> None:
        if self.root is None:
            return
        with self._locked_store():
            if tenant_id is not None:
                self._persist_tenant_unlocked(tenant_id)
                return
            tenants = {t for (t, _) in self.approvals} | {
                self._normalize_tenant(e.get("tenantId")) for e in self.events
            }
            for tid in sorted(tenants):
                self._persist_tenant_unlocked(tid)

    def _entity_lock(self, key: tuple[str, str]) -> threading.RLock:
        with self._locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._key_locks[key] = lock
            return lock

    def _key(self, tenant_id: str, entity_id: str) -> tuple[str, str]:
        return (tenant_id, entity_id)

    def hashes_of(self, entity: dict[str, Any]) -> dict[str, str | None]:
        lin = entity.get("lineage") or {}
        return {
            "engineeringHash": entity.get("engineeringHash") or lin.get("engineeringHash"),
            "bomHash": (entity.get("bom") or {}).get("bomHash") or lin.get("bomHash") or entity.get("bomHash"),
            "nestingHash": (entity.get("nesting") or {}).get("nestingHash") or lin.get("nestingHash") or entity.get("nestingHash"),
            "costHash": lin.get("costHash") or (entity.get("quote") or {}).get("quoteHash") or (entity.get("landed") or {}).get("unitLandedCost") and stable_hash(entity.get("landed")),
            "packagingHash": (entity.get("packing") or {}).get("packagingHash") or lin.get("packagingHash"),
            "evidenceHash": entity.get("evidenceHash") or lin.get("evidenceHash"),
        }

    def audit(
        self,
        *,
        actor: str,
        entity_id: str,
        entity: dict[str, Any],
        decision: str,
        reason: str,
        evidence_hash: str | None = None,
        tenant_id: str | None = None,
        max_per_tenant: int | None = None,
    ) -> dict[str, Any]:
        tid = self._normalize_tenant(tenant_id)
        hashes = self.hashes_of(entity)
        rec = {
            "eventId": new_id(),
            "actor": actor,
            "tenantId": tenant_id,
            "entityId": entity_id,
            "entityVersion": entity.get("spec", {}).get("revision") if isinstance(entity.get("spec"), dict) else entity.get("version") or 1,
            "engineeringHash": hashes["engineeringHash"],
            "evidenceHash": evidence_hash or hashes["evidenceHash"],
            "hashes": hashes,
            "approvedAt": utcnow().isoformat(),
            "decision": decision,
            "reason": reason,
            "immutable": True,
            "liveMachineControl": False,
        }
        rec["auditHash"] = stable_hash({k: rec[k] for k in rec if k not in {"eventId", "auditHash"}})
        limit = (
            self.max_events_per_tenant
            if max_per_tenant is None
            else int(max_per_tenant)
        )
        with self._locked_store():
            self._sync_tenant(tid)
            other = [e for e in self.events if self._normalize_tenant(e.get("tenantId")) != tid]
            same = [e for e in self.events if self._normalize_tenant(e.get("tenantId")) == tid]
            if limit <= 0:
                self.events = other
            else:
                kept_same = same[-(limit - 1) :] if limit > 1 else []
                self.events = [*other, *kept_same, rec]
            self._persist_tenant_unlocked(tid)
        return rec

    def is_stale(self, approval: dict[str, Any], entity: dict[str, Any]) -> bool:
        current = self.hashes_of(entity)
        bound = approval.get("hashes") or {}
        for key in BOUND_HASH_KEYS:
            bound_val = bound.get(key)
            if not bound_val:
                continue
            current_val = current.get(key)
            if not current_val or str(bound_val) != str(current_val):
                return True
        return False

    def _require_bound_hashes(self, approval: dict[str, Any] | None, entity: dict[str, Any]) -> None:
        if not approval:
            return
        bound = approval.get("hashes") or {}
        if not bound and approval.get("state", "PROTOTYPE") == "PROTOTYPE":
            return
        current = self.hashes_of(entity)
        for key in BOUND_HASH_KEYS:
            bound_val = bound.get(key)
            current_val = current.get(key)
            if bound_val and current_val and str(bound_val) != str(current_val):
                raise PermissionError(
                    "entity hashes changed since last gate state; re-verify from ENGINEERING_VALID"
                )
            if bound_val and not current_val:
                raise PermissionError("entity hash removed since last gate state")
            if not bound_val and current_val:
                raise PermissionError("cannot bind new hashes after prior gate step without full re-verify")

    def _require_hashes_for_evidence(self, entity: dict[str, Any]) -> None:
        hashes = self.hashes_of(entity)
        if not hashes.get("engineeringHash"):
            raise PermissionError("engineeringHash required before evidence verification")
        if not hashes.get("evidenceHash"):
            raise PermissionError("evidenceHash required before evidence verification")

    def advance(
        self,
        entity_id: str,
        *,
        tenant_id: str,
        target: str,
        actor: str,
        entity: dict[str, Any],
        evidence_ok: bool = False,
    ) -> dict[str, Any]:
        if target in FORBIDDEN or target in {"LIVE_CNC", "LIVE_LASER"}:
            raise PermissionError("LIVE machine states forbidden; liveMachineControl=false")
        if target not in RC_STATES:
            raise ValueError(target)
        key = self._key(tenant_id, entity_id)
        with self._entity_lock(key):
            self._sync_tenant(tenant_id)
            approval = self.approvals.get(key)
            current = (approval or {}).get("state") or "PROTOTYPE"
            order = list(RC_STATES)
            cur_idx = order.index(current)
            tgt_idx = order.index(target)
            if tgt_idx < cur_idx:
                raise ValueError(f"cannot regress {current} -> {target}")
            if tgt_idx > cur_idx + 1:
                raise ValueError(f"cannot skip from {current} to {target}; advance one state at a time")
            if target == "EVIDENCE_VERIFIED":
                if not evidence_ok:
                    raise PermissionError("evidence verifier must PASS")
                self._require_hashes_for_evidence(entity)
            if target == "APPROVED_FOR_EXPORT" and current not in {"WAITING_APPROVAL", "APPROVED_FOR_EXPORT"}:
                raise PermissionError("export requires WAITING_APPROVAL")
            self._require_bound_hashes(approval, entity)
            if approval is not None and tgt_idx == cur_idx and not approval.get("stale"):
                return copy.deepcopy(approval)
            hashes = self.hashes_of(entity)
            rec: dict[str, Any] = {
                "tenantId": tenant_id,
                "entityId": entity_id,
                "state": target,
                "actor": actor,
                "hashes": hashes,
                "stale": False,
                "liveMachineControl": False,
                "equalsLiveCnc": False,
                "note": "APPROVED_FOR_EXPORT is not LIVE_CNC/LASER",
            }
            audit_rec = self.audit(
                actor=actor,
                entity_id=entity_id,
                entity=entity,
                decision=target,
                reason="release-gate",
                evidence_hash=hashes.get("evidenceHash"),
                tenant_id=tenant_id,
            )
            rec["audit"] = audit_rec
            rec["approvedAt"] = audit_rec["approvedAt"]
            with self._locked_store():
                self.approvals[key] = rec
                self._persist_tenant_unlocked(tenant_id)
            return rec

    def refresh_stale(self, entity_id: str, *, tenant_id: str, entity: dict[str, Any]) -> dict[str, Any]:
        key = self._key(tenant_id, entity_id)
        with self._entity_lock(key):
            self._sync_tenant(tenant_id)
            rec = self.approvals.get(key)
            if not rec:
                raise KeyError(entity_id)
            if self.is_stale(rec, entity):
                rec = dict(rec)
                rec["stale"] = True
                rec["state"] = "PROTOTYPE"
                rec["hashes"] = {}
                rec["reason"] = "upstream hash changed; previous approval void"
                with self._locked_store():
                    self.approvals[key] = rec
                self.audit(
                    actor="system",
                    entity_id=entity_id,
                    entity=entity,
                    decision="STALE",
                    reason="hash-change",
                    tenant_id=tenant_id,
                )
            return rec