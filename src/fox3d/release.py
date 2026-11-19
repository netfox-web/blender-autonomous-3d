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
from typing import Any, Callable, Iterable, Iterator

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
        if not is_matching_tenant_stem(file_tid, cand.stem):
            return cand
    return None


def order_tenants_for_migration(
    tenants_to_persist: Iterable[str],
    legacy_to_cleanup: Iterable[tuple[Path, str]],
    tenant_path_fn: Callable[[str], Path | None],
) -> list[str]:
    """Order tenants so any tenant whose legacy file occupies another tenant's canonical path is persisted first."""
    tenants = sorted(set(tenants_to_persist))
    tenant_set = set(tenants)
    occupant_by_path: dict[Path, set[str]] = {}
    for legacy_path, owner_tid in legacy_to_cleanup:
        occupant_by_path.setdefault(legacy_path, set()).add(owner_tid)
    deps: dict[str, set[str]] = {t: set() for t in tenants}
    for tid in tenants:
        canon = tenant_path_fn(tid)
        if canon is None:
            continue
        for occ_tid in occupant_by_path.get(canon, ()):
            if occ_tid != tid and occ_tid in tenant_set:
                deps[tid].add(occ_tid)
    ordered: list[str] = []
    remaining = set(tenants)
    while remaining:
        ready = sorted(t for t in remaining if not (deps[t] & remaining))
        if not ready:
            ready = [sorted(remaining, key=lambda t: (-len(t), t))[0]]
        for t in ready:
            ordered.append(t)
            remaining.remove(t)
    return ordered


def can_unlink_migrated_legacy_file(
    legacy_path: Path,
    expected_tid: str,
    tenant_path_fn: Callable[[str], Path | None],
    protected_paths: set[Path] | None = None,
) -> bool:
    """Return True only if ``legacy_path`` on disk is still a non-canonical legacy file owned by ``expected_tid``."""
    norm_expected = str(expected_tid or "default").strip() or "default"
    expected_canonical = tenant_path_fn(norm_expected)
    if expected_canonical is not None and legacy_path == expected_canonical:
        return False
    if protected_paths and legacy_path in protected_paths:
        return False
    try:
        raw = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False
    raw_tid = raw.get("tenantId")
    if isinstance(raw_tid, str) and raw_tid.strip():
        disk_tid = raw_tid.strip()
        disk_canonical = tenant_path_fn(disk_tid)
        if disk_canonical is not None and legacy_path == disk_canonical:
            return False
        return disk_tid == norm_expected
    for list_key in ("items", "events", "candidates", "batches", "approvals"):
        rows = raw.get(list_key)
        if isinstance(rows, list) and rows:
            row_tids = {
                str(r.get("tenantId")).strip()
                for r in rows
                if isinstance(r, dict)
                and isinstance(r.get("tenantId"), str)
                and str(r.get("tenantId")).strip()
            }
            return row_tids == {norm_expected}
    return False


def can_unlink_canonical_tenant_file(path: Path, expected_tid: str) -> bool:
    """Return True if ``path`` on disk does not belong to a different tenant."""
    norm_expected = str(expected_tid or "default").strip() or "default"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return True
    if not isinstance(raw, dict):
        return True
    raw_tid = raw.get("tenantId")
    if isinstance(raw_tid, str) and raw_tid.strip():
        return raw_tid.strip() == norm_expected
    return True


def conflicting_legacy_owner_at_path(path: Path, expected_tid: str) -> str | None:
    """If ``path`` on disk is occupied by another tenant's valid legacy file, return that tenantId."""
    norm_expected = str(expected_tid or "default").strip() or "default"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    raw_tid = raw.get("tenantId")
    if not isinstance(raw_tid, str) or not raw_tid.strip():
        return None
    disk_tid = raw_tid.strip()
    if disk_tid == norm_expected:
        return None
    if is_matching_tenant_stem(disk_tid, path.stem):
        return disk_tid
    return None


def _merge_unique_events(
    existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for ev in (*existing, *incoming):
        ev_id = str(ev.get("eventId") or "")
        if ev_id and ev_id in seen_ids:
            continue
        if ev_id:
            seen_ids.add(ev_id)
        out.append(ev)
    return out


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
            canonical_by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
            legacy_by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
            new_sigs: dict[str, tuple[int, int, int, int] | None] = {}
            legacy_to_cleanup: list[tuple[Path, str]] = []
            for folder in self._candidate_dirs():
                for path in sorted_tenant_json_paths(folder):
                    tid, parsed = self._parse_items_file(path)
                    canonical = self._tenant_path(tid)
                    if folder == self.root and canonical is not None and path == canonical:
                        canonical_by_tenant[tid] = parsed
                        new_sigs[tid] = file_sig(path)
                    else:
                        legacy_by_tenant.setdefault(tid, {}).update(parsed)
                        if folder == self.root:
                            legacy_to_cleanup.append((path, tid))
            new_items: dict[str, dict[str, Any]] = {}
            tenants_to_persist: set[str] = set()
            all_tids = sorted(set(canonical_by_tenant) | set(legacy_by_tenant))
            for tid in all_tids:
                if tid in canonical_by_tenant:
                    new_items.update(canonical_by_tenant[tid])
                else:
                    new_items.update(legacy_by_tenant[tid])
                    tenants_to_persist.add(tid)
            self.items.clear()
            self.items.update(new_items)
            self._sigs.clear()
            self._sigs.update(new_sigs)
            for tid in order_tenants_for_migration(
                tenants_to_persist, legacy_to_cleanup, self._tenant_path
            ):
                self._persist_tenant_unlocked(tid)
            protected_paths = {
                p for t in all_tids if (p := self._tenant_path(t)) is not None
            }
            for legacy_path, tid in legacy_to_cleanup:
                if can_unlink_migrated_legacy_file(
                    legacy_path, tid, self._tenant_path, protected_paths
                ):
                    legacy_path.unlink(missing_ok=True)
            for item_id, rec in self.items.items():
                self._on_item_loaded(item_id, rec)

    def _sync_tenant(
        self, tenant_id: str | None, *, _visited: set[str] | None = None
    ) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        if _visited is not None and tid in _visited:
            return
        seen = set(_visited) if _visited is not None else set()
        seen.add(tid)
        path = self._tenant_path(tid)
        if path is None:
            return
        with self._locked_store():
            sig = file_sig(path)
            if sig is not None and self._sigs.get(tid) != sig:
                parsed_tid, parsed = self._parse_items_file(path)
                if parsed_tid != tid:
                    self._sync_tenant(parsed_tid, _visited=seen)
                    if can_unlink_migrated_legacy_file(
                        path, parsed_tid, self._tenant_path
                    ):
                        path.unlink(missing_ok=True)
                    sig = file_sig(path)
                else:
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
                    return
            if sig is None:
                legacy_path = find_legacy_tenant_file(self.root, tid)
                if legacy_path is not None:
                    parsed_tid, parsed = self._parse_items_file(legacy_path)
                    if parsed_tid != tid:
                        raise ValueError(
                            f"refusing to migrate {legacy_path} owned by {parsed_tid!r} for tenant {tid!r}"
                        )
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
                    if can_unlink_migrated_legacy_file(
                        legacy_path, tid, self._tenant_path, {path}
                    ):
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

    def _persist_tenant_unlocked(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        occ_tid = conflicting_legacy_owner_at_path(path, tid)
        if occ_tid is not None:
            occ_canon = self._tenant_path(occ_tid)
            if occ_canon is not None and occ_canon != path and not occ_canon.exists():
                self._sync_tenant(occ_tid)
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
            if can_unlink_canonical_tenant_file(path, tid):
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
        self._archived_events: dict[str, list[dict[str, Any]]] = {}
        self.approvals: dict[tuple[str, str], dict[str, Any]] = {}
        self._locks_guard = threading.Lock()
        self._key_locks: dict[tuple[str, str], threading.RLock] = {}
        self._store_lock = threading.RLock()
        self._lock_state: dict[str, int] = {"depth": 0}
        self._sigs: dict[str, tuple[int, int, int, int] | None] = {}
        self._archive_sigs: dict[str, tuple[int, int, int, int] | None] = {}
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

    def _tenant_archive_path(self, tenant_id: str) -> Path | None:
        if self.root is None:
            return None
        return (
            self.root
            / "archive"
            / f"{safe_tenant_filename(self._normalize_tenant(tenant_id))}.json"
        )

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

    def _split_tenant_events(
        self, events: list[dict[str, Any]], *, max_per_tenant: int | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        limit = (
            self.max_events_per_tenant
            if max_per_tenant is None
            else int(max_per_tenant)
        )
        if limit <= 0:
            return list(events), []
        if len(events) <= limit:
            return [], list(events)
        return list(events[:-limit]), list(events[-limit:])

    def _validate_events_list(
        self, path: Path, tid: str, raw_events: list[Any]
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for ev in raw_events:
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
        return events

    def _parse_archive_file(self, path: Path) -> tuple[str, list[dict[str, Any]]]:
        payload = read_validated_tenant_json(path, required_lists=("events",))
        tid = str(payload["tenantId"])
        events = self._validate_events_list(path, tid, payload["events"])
        return tid, events

    def _sync_tenant_archive_unlocked(self, tenant_id: str) -> list[dict[str, Any]]:
        tid = self._normalize_tenant(tenant_id)
        if self.root is None:
            return list(self._archived_events.get(tid, []))
        arch_path = self._tenant_archive_path(tid)
        if arch_path is None:
            return list(self._archived_events.get(tid, []))
        sig = file_sig(arch_path)
        if sig is None:
            self._archived_events.pop(tid, None)
            self._archive_sigs.pop(tid, None)
            return []
        if self._archive_sigs.get(tid) == sig and tid in self._archived_events:
            return list(self._archived_events[tid])
        _, events = self._parse_archive_file(arch_path)
        self._archived_events[tid] = events
        self._archive_sigs[tid] = file_sig(arch_path)
        return list(events)

    def _archive_tenant_events_unlocked(
        self, tenant_id: str, overflow_events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        tid = self._normalize_tenant(tenant_id)
        current = self._sync_tenant_archive_unlocked(tid)
        if not overflow_events:
            return current
        merged = _merge_unique_events(current, overflow_events)
        self._archived_events[tid] = merged
        if self.root is not None:
            arch_path = self._tenant_archive_path(tid)
            if arch_path is not None and merged:
                atomic_write_tenant_json(
                    arch_path,
                    {
                        "tenantId": tid,
                        "events": merged,
                    },
                )
                self._archive_sigs[tid] = file_sig(arch_path)
        return merged

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
        events = self._validate_events_list(path, tid, payload["events"])
        return tid, approvals, events

    def load(self) -> None:
        if self.root is None:
            return
        with self._locked_store():
            self._archived_events.clear()
            self._archive_sigs.clear()
            arch_dir = self.root / "archive"
            if arch_dir.is_dir():
                for arch_path in sorted_tenant_json_paths(arch_dir):
                    arch_tid, arch_events = self._parse_archive_file(arch_path)
                    self._archived_events[arch_tid] = _merge_unique_events(
                        self._archived_events.get(arch_tid, []), arch_events
                    )
                    self._archive_sigs[arch_tid] = file_sig(arch_path)
            canonical_by_tenant: dict[
                str, tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]
            ] = {}
            legacy_approvals_by_tenant: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
            legacy_events_by_tenant: dict[str, list[dict[str, Any]]] = {}
            new_sigs: dict[str, tuple[int, int, int, int] | None] = {}
            legacy_to_cleanup: list[tuple[Path, str]] = []
            for folder in self._candidate_dirs():
                for path in sorted_tenant_json_paths(folder):
                    tid, approvals, events = self._parse_tenant_file(path)
                    canonical = self._tenant_path(tid)
                    if folder == self.root and canonical is not None and path == canonical:
                        canonical_by_tenant[tid] = (approvals, events)
                        new_sigs[tid] = file_sig(path)
                    else:
                        legacy_approvals_by_tenant.setdefault(tid, {}).update(approvals)
                        legacy_events_by_tenant[tid] = _merge_unique_events(
                            legacy_events_by_tenant.get(tid, []), events
                        )
                        if folder == self.root:
                            legacy_to_cleanup.append((path, tid))
            new_approvals: dict[tuple[str, str], dict[str, Any]] = {}
            by_tenant_events: dict[str, list[dict[str, Any]]] = {}
            tenants_to_persist: set[str] = set()
            all_tids = sorted(
                set(canonical_by_tenant)
                | set(legacy_approvals_by_tenant)
                | set(legacy_events_by_tenant)
                | set(self._archived_events)
            )
            for tid in all_tids:
                if tid in canonical_by_tenant:
                    approvals, events = canonical_by_tenant[tid]
                    overflow, active = self._split_tenant_events(events)
                    if overflow:
                        self._archive_tenant_events_unlocked(tid, overflow)
                        tenants_to_persist.add(tid)
                    new_approvals.update(approvals)
                    by_tenant_events[tid] = active
                elif tid in legacy_approvals_by_tenant or tid in legacy_events_by_tenant:
                    approvals = legacy_approvals_by_tenant.get(tid, {})
                    events = legacy_events_by_tenant.get(tid, [])
                    overflow, active = self._split_tenant_events(events)
                    if overflow:
                        self._archive_tenant_events_unlocked(tid, overflow)
                    new_approvals.update(approvals)
                    by_tenant_events[tid] = active
                    tenants_to_persist.add(tid)
            self.approvals = new_approvals
            self.events = [ev for tid_events in by_tenant_events.values() for ev in tid_events]
            self._sigs = new_sigs
            for tid in order_tenants_for_migration(
                tenants_to_persist, legacy_to_cleanup, self._tenant_path
            ):
                self._persist_tenant_unlocked(tid)
            protected_paths = {
                p for t in all_tids if (p := self._tenant_path(t)) is not None
            }
            for legacy_path, tid in legacy_to_cleanup:
                if can_unlink_migrated_legacy_file(
                    legacy_path, tid, self._tenant_path, protected_paths
                ):
                    legacy_path.unlink(missing_ok=True)

    def _sync_tenant(
        self, tenant_id: str | None, *, _visited: set[str] | None = None
    ) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        if _visited is not None and tid in _visited:
            return
        seen = set(_visited) if _visited is not None else set()
        seen.add(tid)
        path = self._tenant_path(tid)
        if path is None:
            return
        with self._locked_store():
            self._sync_tenant_archive_unlocked(tid)
            sig = file_sig(path)
            if sig is not None and self._sigs.get(tid) != sig:
                parsed_tid, approvals, events = self._parse_tenant_file(path)
                if parsed_tid != tid:
                    self._sync_tenant(parsed_tid, _visited=seen)
                    if can_unlink_migrated_legacy_file(
                        path, parsed_tid, self._tenant_path
                    ):
                        path.unlink(missing_ok=True)
                    sig = file_sig(path)
                else:
                    for key in [k for k in self.approvals if k[0] == tid]:
                        self.approvals.pop(key, None)
                    self.approvals.update(approvals)
                    overflow, active = self._split_tenant_events(events)
                    other_events = [
                        e for e in self.events if self._normalize_tenant(e.get("tenantId")) != tid
                    ]
                    self.events = [*other_events, *active]
                    if overflow:
                        self._archive_tenant_events_unlocked(tid, overflow)
                        self._persist_tenant_unlocked(tid)
                    else:
                        self._sigs[tid] = file_sig(path)
                    return
            if sig is None:
                legacy_path = find_legacy_tenant_file(self.root, tid)
                if legacy_path is not None:
                    parsed_tid, approvals, events = self._parse_tenant_file(legacy_path)
                    if parsed_tid != tid:
                        raise ValueError(
                            f"refusing to migrate {legacy_path} owned by {parsed_tid!r} for tenant {tid!r}"
                        )
                    for key in [k for k in self.approvals if k[0] == tid]:
                        self.approvals.pop(key, None)
                    self.approvals.update(approvals)
                    other_events = [
                        e for e in self.events if self._normalize_tenant(e.get("tenantId")) != tid
                    ]
                    self.events = [*other_events, *events]
                    self._persist_tenant_unlocked(tid)
                    if can_unlink_migrated_legacy_file(
                        legacy_path, tid, self._tenant_path, {path}
                    ):
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

    def _persist_tenant_unlocked(
        self, tenant_id: str | None, *, max_per_tenant: int | None = None
    ) -> None:
        tid = self._normalize_tenant(tenant_id)
        if self.root is not None:
            path = self._tenant_path(tid)
            if path is not None:
                occ_tid = conflicting_legacy_owner_at_path(path, tid)
                if occ_tid is not None:
                    occ_canon = self._tenant_path(occ_tid)
                    if (
                        occ_canon is not None
                        and occ_canon != path
                        and not occ_canon.exists()
                    ):
                        self._sync_tenant(occ_tid)
        raw_tenant_events = [
            ev for ev in self.events if self._normalize_tenant(ev.get("tenantId")) == tid
        ]
        overflow_events, tenant_events = self._split_tenant_events(
            raw_tenant_events, max_per_tenant=max_per_tenant
        )
        archived = self._archive_tenant_events_unlocked(tid, overflow_events)
        other_events = [
            ev for ev in self.events if self._normalize_tenant(ev.get("tenantId")) != tid
        ]
        self.events = [*other_events, *tenant_events]
        if self.root is None:
            return
        path = self._tenant_path(tid)
        if path is None:
            return
        tenant_approvals = [rec for (t, _), rec in self.approvals.items() if t == tid]
        if tenant_approvals or tenant_events or archived:
            payload: dict[str, Any] = {
                "tenantId": tid,
                "approvals": tenant_approvals,
                "events": tenant_events,
            }
            if archived:
                payload["archivedEventCount"] = len(archived)
                payload["totalEventCount"] = len(archived) + len(tenant_events)
                payload["archivePath"] = f"archive/{safe_tenant_filename(tid)}.json"
            atomic_write_tenant_json(path, payload)
            self._sigs[tid] = file_sig(path)
        else:
            if can_unlink_canonical_tenant_file(path, tid):
                path.unlink(missing_ok=True)
            self._sigs.pop(tid, None)

    def persist(self, *, tenant_id: str | None = None) -> None:
        with self._locked_store():
            if tenant_id is not None:
                self._persist_tenant_unlocked(tenant_id)
                return
            tenants = (
                {t for (t, _) in self.approvals}
                | {self._normalize_tenant(e.get("tenantId")) for e in self.events}
                | set(self._archived_events)
            )
            for tid in sorted(tenants):
                self._persist_tenant_unlocked(tid)

    def archived_events(
        self, tenant_id: str | None = None, *, entity_id: str | None = None
    ) -> list[dict[str, Any]]:
        if tenant_id is not None and (
            not isinstance(tenant_id, str) or not tenant_id.strip()
        ):
            raise ValueError("tenant_id must be a non-empty string")
        if entity_id is not None and (
            not isinstance(entity_id, str) or not entity_id.strip()
        ):
            raise ValueError("entity_id must be a non-empty string")
        with self._locked_store():
            if tenant_id is not None:
                tid = self._normalize_tenant(tenant_id)
                self._sync_tenant(tid)
                rows = list(self._archived_events.get(tid, []))
            else:
                if self.root is not None:
                    self.load()
                rows = [
                    ev
                    for t in sorted(self._archived_events)
                    for ev in self._archived_events.get(t, [])
                ]
            if entity_id is not None:
                rows = [ev for ev in rows if ev.get("entityId") == entity_id]
            return copy.deepcopy(rows)

    def list_events(
        self,
        tenant_id: str | None = None,
        *,
        entity_id: str | None = None,
        include_archived: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if tenant_id is not None and (
            not isinstance(tenant_id, str) or not tenant_id.strip()
        ):
            raise ValueError("tenant_id must be a non-empty string")
        if entity_id is not None and (
            not isinstance(entity_id, str) or not entity_id.strip()
        ):
            raise ValueError("entity_id must be a non-empty string")
        if not isinstance(include_archived, bool):
            raise ValueError("include_archived must be a boolean")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise ValueError("limit must be a non-negative integer")
        with self._locked_store():
            if tenant_id is not None:
                tid = self._normalize_tenant(tenant_id)
                self._sync_tenant(tid)
                active = [
                    ev
                    for ev in self.events
                    if self._normalize_tenant(ev.get("tenantId")) == tid
                ]
                archived = (
                    list(self._archived_events.get(tid, [])) if include_archived else []
                )
                combined = _merge_unique_events(archived, active)
            else:
                if self.root is not None:
                    self.load()
                archived_all = (
                    [
                        ev
                        for t in sorted(self._archived_events)
                        for ev in self._archived_events.get(t, [])
                    ]
                    if include_archived
                    else []
                )
                combined = _merge_unique_events(archived_all, self.events)
            if entity_id is not None:
                combined = [ev for ev in combined if ev.get("entityId") == entity_id]
            if limit == 0:
                return []
            sliced = (
                combined[offset : offset + limit]
                if limit is not None
                else combined[offset:]
            )
            return copy.deepcopy(sliced)

    def events_page(
        self,
        tenant_id: str,
        *,
        entity_id: str | None = None,
        limit: int = MAX_EVENTS_PER_TENANT,
        offset: int = 0,
        include_archived: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        if entity_id is not None and (
            not isinstance(entity_id, str) or not entity_id.strip()
        ):
            raise ValueError("entity_id must be a non-empty string")
        if not isinstance(include_archived, bool):
            raise ValueError("include_archived must be a boolean")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        tid = self._normalize_tenant(tenant_id)
        with self._locked_store():
            self._sync_tenant(tid)
            active = [
                ev
                for ev in self.events
                if self._normalize_tenant(ev.get("tenantId")) == tid
                and (entity_id is None or ev.get("entityId") == entity_id)
            ]
            archived = [
                ev
                for ev in self._archived_events.get(tid, [])
                if entity_id is None or ev.get("entityId") == entity_id
            ]
            combined = (
                _merge_unique_events(archived, active)
                if include_archived
                else list(active)
            )
            page = copy.deepcopy(combined[offset : offset + limit])
            total = len(combined)
            return {
                "tenantId": tid,
                "items": page,
                "events": page,
                "total": total,
                "limit": limit,
                "offset": offset,
                "hasMore": offset + len(page) < total,
                "archivedCount": len(archived),
                "activeCount": len(active),
            }

    def list_approvals(self, tenant_id: str) -> list[dict[str, Any]]:
        """Read-only approvals for one tenant. Does not record or rotate events."""
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        tid = self._normalize_tenant(tenant_id)
        with self._locked_store():
            self._sync_tenant(tid)
            rows = [
                copy.deepcopy(rec)
                for (owner, _entity), rec in self.approvals.items()
                if owner == tid
            ]
        rows.sort(
            key=lambda rec: (
                str(rec.get("entityId") or ""),
                str(rec.get("approvedAt") or ""),
            )
        )
        return rows

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
            self.events.append(rec)
            self._persist_tenant_unlocked(tid, max_per_tenant=limit)
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