"""Tenant-partitioned durable storage and approval gate for Product R&D results."""

from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fox3d.durability import publish_bytes
from fox3d.ids import stable_hash
from fox3d.infra import utcnow, validate_tenant_id
from fox3d.storelock import FileLock

MAX_RD_TEXT_CHARS = 2000
MAX_RD_TEXT_UTF8_BYTES = 6000
MIN_RD_VARIANT_COUNT = 1
MAX_RD_VARIANT_COUNT = 100
DEFAULT_RD_VARIANT_COUNT = 12
MAX_IDEMPOTENCY_KEY_LEN = 200
MAX_ACTOR_LEN = 120
MAX_CURSOR_LEN = 200

_RD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TLS = threading.local()
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_RLOCKS: dict[str, threading.RLock] = {}


class ProductRDIdempotencyConflict(ValueError):
    """Raised when an idempotencyKey is reused with different parameters."""


def _path_rlock(key: str) -> threading.RLock:
    with _PATH_LOCKS_GUARD:
        lock = _PATH_RLOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_RLOCKS[key] = lock
        return lock


def is_valid_rd_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_RD_ID_RE.fullmatch(value))


def validate_rd_text(raw: Any, *, required_non_empty: bool = False) -> str:
    if raw is None:
        if required_non_empty:
            raise ValueError("text 不可為空白")
        return ""
    if not isinstance(raw, str):
        raise ValueError("text 格式錯誤")
    if "\x00" in raw or any(0xD800 <= ord(c) <= 0xDFFF for c in raw):
        raise ValueError("text 格式錯誤")
    if required_non_empty and not raw.strip():
        raise ValueError("text 不可為空白")
    if len(raw) > MAX_RD_TEXT_CHARS or len(raw.encode("utf-8")) > MAX_RD_TEXT_UTF8_BYTES:
        raise ValueError(f"text 長度不可超過 {MAX_RD_TEXT_CHARS} 字")
    return raw


def validate_rd_variant_count(raw: Any, *, default: int = DEFAULT_RD_VARIANT_COUNT) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"variantCount 須為 {MIN_RD_VARIANT_COUNT} 至 {MAX_RD_VARIANT_COUNT} 的整數")
    if not (MIN_RD_VARIANT_COUNT <= raw <= MAX_RD_VARIANT_COUNT):
        raise ValueError(f"variantCount 須為 {MIN_RD_VARIANT_COUNT} 至 {MAX_RD_VARIANT_COUNT} 的整數")
    return raw


def validate_optional_idempotency_key(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("idempotencyKey 格式錯誤")
    if len(raw) > MAX_IDEMPOTENCY_KEY_LEN or any(ord(c) < 32 for c in raw):
        raise ValueError("idempotencyKey 格式錯誤")
    key = raw.strip()
    if not key:
        raise ValueError("idempotencyKey 格式錯誤")
    return key


def validate_rd_actor(raw: Any, *, default: str = "human") -> str:
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ValueError("actor 格式錯誤")
    if len(raw) > MAX_ACTOR_LEN or any(ord(c) < 32 for c in raw):
        raise ValueError("actor 格式錯誤")
    actor = raw.strip()
    if not actor:
        raise ValueError("actor 格式錯誤")
    return actor


def _format_utc(dt: datetime) -> str:
    utc_dt = dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or value != value.strip() or "|" in value:
        return None
    if len(value) < 19 or ("T" not in value and " " not in value):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canonical_utc_timestamp(value: Any) -> str | None:
    dt = _parse_iso_utc(value)
    return _format_utc(dt) if dt is not None else None


def resolve_judge_label(rd: dict[str, Any], *, default_status: str = "MOCK") -> str:
    top = rd.get("top")
    if isinstance(top, list) and top:
        labels = [
            str((row.get("judge") or {}).get("label") or "MOCK")
            for row in top
            if isinstance(row, dict)
        ]
        if labels and all(lbl == "REAL" for lbl in labels):
            return "REAL"
        return "MOCK"
    for candidate in (
        rd.get("judgeLabel"),
        rd.get("scoringStatus"),
        (rd.get("approval") or {}).get("judgeLabel") if isinstance(rd.get("approval"), dict) else None,
    ):
        if candidate in {"REAL", "MOCK"}:
            return str(candidate)
    return "REAL" if default_status == "REAL" else "MOCK"


def _resolve_render_label(rd: dict[str, Any]) -> str:
    param_render = rd.get("parametricRender")
    if not isinstance(param_render, dict):
        return "SKIPPED"
    job = param_render.get("job")
    if not isinstance(job, dict):
        return "SKIPPED"
    status = str(job.get("status") or "").lower()
    if status == "blocked" or str(job.get("error") or "").startswith("BLOCKED"):
        return str(job.get("error") or "BLOCKED")
    if status not in {"succeeded", "completed"}:
        return status.upper() or "SKIPPED"
    if job.get("realBlender") and not job.get("usedMock"):
        return "REAL"
    return "MOCK"


class ProductRDStore:
    """Tenant-scoped atomic JSON persistence for Product R&D schemes."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache_lock = threading.RLock()
        self._file_cache: dict[str, tuple[tuple[int, int, int], dict[str, Any]]] = {}
        self._last_ts_by_tenant: dict[str, datetime] = {}

    def _tenant_token(self, tenant_id: str) -> str:
        return stable_hash(tenant_id)[:24]

    def _tenant_dir(self, tenant_id: str) -> Path:
        return self.root / stable_hash(tenant_id)

    def _lock_path(self, tenant_id: str) -> Path:
        return self.root / "locks" / f"{stable_hash(tenant_id)}.lock"

    def _record_path(self, tenant_id: str, rd_id: str) -> Path:
        return self._tenant_dir(tenant_id) / f"{stable_hash(rd_id)}.json"

    @contextmanager
    def tenant_lock(self, tenant_id: str) -> Iterator[None]:
        tid = validate_tenant_id(tenant_id)
        lock_path = self._lock_path(tid)
        key = str(lock_path.resolve())
        rlock = _path_rlock(key)
        depths: dict[str, int] | None = getattr(_TLS, "depths", None)
        if depths is None:
            depths = {}
            _TLS.depths = depths
        with rlock:
            depth = depths.get(key, 0)
            if depth == 0:
                flock = FileLock(lock_path)
                flock.acquire()
                depths[key] = 1
                try:
                    yield
                finally:
                    depths.pop(key, None)
                    flock.release()
            else:
                depths[key] = depth + 1
                try:
                    yield
                finally:
                    depths[key] = depth

    @staticmethod
    def _is_valid_record(data: Any, tenant_id: str) -> bool:
        if not isinstance(data, dict):
            return False
        rd_id = data.get("rdId")
        if not is_valid_rd_id(rd_id):
            return False
        if data.get("tenantId") != tenant_id:
            return False
        if canonical_utc_timestamp(data.get("createdAt")) is None:
            return False
        approval = data.get("approval")
        if not isinstance(approval, dict) or approval.get("status") not in {"WAITING_APPROVAL", "APPROVED"}:
            return False
        if not isinstance(data.get("top"), list):
            return False
        return True

    def _read_path(self, path: Path, tenant_id: str) -> dict[str, Any] | None:
        if path.name.startswith(".") or path.is_symlink():
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        cache_key = str(path)
        with self._cache_lock:
            cached = self._file_cache.get(cache_key)
            if cached is not None and cached[0] == sig:
                rec = cached[1]
                if self._is_valid_record(rec, tenant_id) and path.name == f"{stable_hash(rec['rdId'])}.json":
                    return rec
                return None
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not self._is_valid_record(parsed, tenant_id):
            return None
        if path.name != f"{stable_hash(parsed['rdId'])}.json":
            return None
        with self._cache_lock:
            self._file_cache[cache_key] = (sig, parsed)
        return parsed

    def _write_record_unlocked(self, tenant_id: str, record: dict[str, Any]) -> None:
        rd_id = str(record["rdId"])
        target = self._record_path(tenant_id, rd_id)
        try:
            raw_json = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except ValueError as exc:
            raise ValueError("數值超出有效範圍") from exc
        data = raw_json.encode("utf-8")
        publish_bytes(lambda stream: stream.write(data), target)
        try:
            st = target.stat()
        except OSError:
            with self._cache_lock:
                self._file_cache.pop(str(target), None)
        else:
            with self._cache_lock:
                self._file_cache[str(target)] = ((st.st_mtime_ns, st.st_size, st.st_ino), copy.deepcopy(record))

    def _scan_tenant_records(self, tenant_id: str) -> tuple[list[tuple[tuple[str, str], dict[str, Any]]], int]:
        folder = self._tenant_dir(tenant_id)
        if not folder.is_dir():
            return [], 0
        entries: list[tuple[tuple[str, str], dict[str, Any]]] = []
        skipped = 0
        for path in sorted(folder.glob("*.json")):
            if path.name.startswith("."):
                continue
            rec = self._read_path(path, tenant_id)
            if rec is None:
                skipped += 1
                continue
            canon_created = canonical_utc_timestamp(rec["createdAt"])
            if canon_created is None:
                skipped += 1
                continue
            entries.append(((canon_created, str(rec["rdId"])), rec))
        entries.sort(key=lambda item: item[0], reverse=True)
        return entries, skipped

    def _next_created_at_unlocked(self, tenant_id: str, existing_entries: list[tuple[tuple[str, str], dict[str, Any]]]) -> str:
        candidate = utcnow().astimezone(timezone.utc)
        floor_dt = self._last_ts_by_tenant.get(tenant_id)
        if existing_entries:
            newest_iso = existing_entries[0][0][0]
            newest_dt = _parse_iso_utc(newest_iso)
            if newest_dt is not None and (floor_dt is None or newest_dt > floor_dt):
                floor_dt = newest_dt
        if floor_dt is not None and candidate <= floor_dt:
            candidate = floor_dt + timedelta(microseconds=1)
        self._last_ts_by_tenant[tenant_id] = candidate
        return _format_utc(candidate)

    def create_or_get(
        self,
        *,
        tenant_id: str,
        text: str,
        variant_count: int,
        idempotency_key: str | None,
        fingerprint: str,
        default_judge_status: str,
        builder: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        tid = validate_tenant_id(tenant_id)
        idem = validate_optional_idempotency_key(idempotency_key)
        with self.tenant_lock(tid):
            entries, _ = self._scan_tenant_records(tid)
            if idem is not None:
                for _, existing in entries:
                    if existing.get("idempotencyKey") == idem:
                        if existing.get("idempotencyFingerprint") != fingerprint:
                            raise ProductRDIdempotencyConflict("idempotency conflict")
                        return copy.deepcopy(existing)

            built = builder()
            record = copy.deepcopy(built)
            rd_id = str(record.get("rdId") or "")
            if not is_valid_rd_id(rd_id):
                raise ValueError("invalid rdId")

            created_at = self._next_created_at_unlocked(tid, entries)
            judge_label = resolve_judge_label(record, default_status=default_judge_status)
            render_label = _resolve_render_label(record)
            truth_label = "REAL" if (judge_label == "REAL" and render_label == "REAL") else "MOCK"

            approval_val = record.get("approval")
            raw_approval: dict[str, Any] = approval_val if isinstance(approval_val, dict) else {}
            record["rdId"] = rd_id
            record["tenantId"] = tid
            record["createdAt"] = created_at
            record["text"] = text
            record["requestedVariantCount"] = variant_count
            record["judgeLabel"] = judge_label
            record["scoringStatus"] = judge_label
            record["truthLabel"] = truth_label
            record["HUMAN_APPROVAL_REQUIRED"] = True
            record["liveMachineControl"] = False
            record["approvedAt"] = None
            record["approval"] = {
                **raw_approval,
                "status": "WAITING_APPROVAL",
                "HUMAN_APPROVAL_REQUIRED": True,
                "autoApproveForbiddenForProduction": True,
                "liveMachineControl": False,
                "approvedAt": None,
                "actor": None,
                "judgeLabel": judge_label,
            }
            if idem is not None:
                record["idempotencyKey"] = idem
                record["idempotencyFingerprint"] = fingerprint

            self._write_record_unlocked(tid, record)
            return copy.deepcopy(record)

    def get(self, tenant_id: str, rd_id: str) -> dict[str, Any]:
        tid = validate_tenant_id(tenant_id)
        if not is_valid_rd_id(rd_id):
            raise KeyError(rd_id)
        target = self._record_path(tid, rd_id)
        rec = self._read_path(target, tid)
        if rec is None or rec.get("rdId") != rd_id:
            raise KeyError(rd_id)
        return copy.deepcopy(rec)

    def exists(self, tenant_id: str, rd_id: str) -> bool:
        try:
            self.get(tenant_id, rd_id)
            return True
        except KeyError:
            return False

    def _parse_cursor(
        self,
        raw_cursor: str,
        tenant_token: str,
        entries: list[tuple[tuple[str, str], dict[str, Any]]],
    ) -> tuple[str, str] | None:
        if "|" in raw_cursor:
            parts = raw_cursor.split("|")
            if len(parts) != 3:
                return None
            tok, raw_ts, raw_id = parts
            if tok != tenant_token or not is_valid_rd_id(raw_id):
                return None
            canon_ts = canonical_utc_timestamp(raw_ts)
            if canon_ts is None:
                return None
            for sort_key, rec in entries:
                if rec["rdId"] == raw_id:
                    return (canon_ts, raw_id) if sort_key == (canon_ts, raw_id) else None
            return (canon_ts, raw_id)
        if is_valid_rd_id(raw_cursor):
            for sort_key, rec in entries:
                if rec["rdId"] == raw_cursor:
                    return sort_key
        return None

    def list_results(
        self,
        tenant_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        tid = validate_tenant_id(tenant_id)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset 須為非負整數")
        if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 100):
            raise ValueError("limit 須為 1 至 100 的整數")
        if cursor is not None:
            if not isinstance(cursor, str) or len(cursor) > MAX_CURSOR_LEN:
                raise ValueError("cursor 格式錯誤")

        entries, skipped = self._scan_tenant_records(tid)
        total = len(entries)
        tenant_token = self._tenant_token(tid)

        if isinstance(cursor, str) and cursor.strip():
            parsed_key = self._parse_cursor(cursor, tenant_token, entries)
            if parsed_key is not None:
                remaining = [item for item in entries if item[0] < parsed_key]
            else:
                remaining = entries[offset:]
            sliced = remaining[:limit]
            has_more = len(remaining) > len(sliced)
        else:
            sliced = entries[offset : offset + limit]
            has_more = (offset + len(sliced)) < total

        next_cursor: str | None = None
        if has_more and sliced:
            last_created, last_id = sliced[-1][0]
            next_cursor = f"{tenant_token}|{last_created}|{last_id}"

        return {
            "items": [copy.deepcopy(rec) for _, rec in sliced],
            "total": total,
            "offset": offset,
            "limit": limit,
            "hasMore": has_more,
            "nextCursor": next_cursor,
            "skipped": skipped,
        }

    def approve(
        self,
        tenant_id: str,
        rd_id: str,
        *,
        actor: str,
        default_judge_status: str,
        approve_fn: Callable[[dict[str, Any], str], dict[str, Any]],
    ) -> dict[str, Any]:
        tid = validate_tenant_id(tenant_id)
        valid_actor = validate_rd_actor(actor)
        if not is_valid_rd_id(rd_id):
            raise KeyError(rd_id)

        with self.tenant_lock(tid):
            target = self._record_path(tid, rd_id)
            current = self._read_path(target, tid)
            if current is None or current.get("rdId") != rd_id:
                raise KeyError(rd_id)

            cur_approval_val = current.get("approval")
            cur_approval: dict[str, Any] = cur_approval_val if isinstance(cur_approval_val, dict) else {}
            existing_approved_at = cur_approval.get("approvedAt") or current.get("approvedAt")
            if cur_approval.get("status") == "APPROVED" and isinstance(existing_approved_at, str) and existing_approved_at:
                return copy.deepcopy(current)

            judge_label = resolve_judge_label(current, default_status=default_judge_status)
            render_label = _resolve_render_label(current)
            truth_label = str(
                current.get("truthLabel")
                or ("REAL" if (judge_label == "REAL" and render_label == "REAL") else "MOCK")
            )
            if judge_label != "REAL":
                truth_label = "MOCK"

            approved_raw = approve_fn(copy.deepcopy(current), valid_actor)
            approved = copy.deepcopy(approved_raw)
            approved_at = _format_utc(utcnow())

            top_val = approved.get("top")
            top_rows: list[Any] = top_val if isinstance(top_val, list) else []
            variant_judge_by_id: dict[str, str] = {}
            for row in top_rows:
                if not isinstance(row, dict):
                    continue
                vid = str((row.get("variant") or {}).get("variantId") or "")
                j_obj = row.get("judge")
                if isinstance(j_obj, dict):
                    row_lbl = "REAL" if j_obj.get("label") == "REAL" and judge_label == "REAL" else (
                        str(j_obj.get("label") or judge_label)
                    )
                    if judge_label == "MOCK":
                        row_lbl = "MOCK"
                    j_obj["label"] = row_lbl
                else:
                    row_lbl = judge_label
                if vid:
                    variant_judge_by_id[vid] = row_lbl

            prod_assets: list[dict[str, Any]] = []
            for item in approved.get("productionAssets") or []:
                if not isinstance(item, dict):
                    continue
                vid = str(item.get("fromVariant") or "")
                item_lbl = variant_judge_by_id.get(vid, judge_label)
                prod_assets.append(
                    {
                        **item,
                        "judgeLabel": item_lbl,
                        "liveMachineControl": False,
                    }
                )

            approved["rdId"] = rd_id
            approved["tenantId"] = tid
            approved["createdAt"] = current["createdAt"]
            approved["text"] = current.get("text", "")
            if "requestedVariantCount" in current:
                approved["requestedVariantCount"] = current["requestedVariantCount"]
            if "idempotencyKey" in current:
                approved["idempotencyKey"] = current["idempotencyKey"]
            if "idempotencyFingerprint" in current:
                approved["idempotencyFingerprint"] = current["idempotencyFingerprint"]
            if "parametricRender" in current and "parametricRender" not in approved:
                approved["parametricRender"] = current["parametricRender"]

            approved["judgeLabel"] = judge_label
            approved["scoringStatus"] = judge_label
            approved["truthLabel"] = truth_label
            approved["HUMAN_APPROVAL_REQUIRED"] = True
            approved["liveMachineControl"] = False
            approved["approvedAt"] = approved_at
            approved["productionAssets"] = prod_assets
            approved_gate_val = approved.get("approval")
            approved_gate: dict[str, Any] = approved_gate_val if isinstance(approved_gate_val, dict) else {}
            approved["approval"] = {
                **approved_gate,
                "status": "APPROVED",
                "actor": valid_actor,
                "approvedAt": approved_at,
                "autoApproveForbiddenForProduction": True,
                "HUMAN_APPROVAL_REQUIRED": True,
                "liveMachineControl": False,
                "judgeLabel": judge_label,
            }

            self._write_record_unlocked(tid, approved)
            return copy.deepcopy(approved)
