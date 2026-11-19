"""List or assign quarantined pre-upgrade commerce snapshots.

Dry-run prints each quarantined snapshotId and its informational claimedTenantId.
claimedTenantId is not an owner and is never used as the assignment tenant.

Assignment requires an explicit tenant, a separate backup of the provider file,
and an audit path. The backup must be a byte-for-byte copy of the current
provider file before anything is written. The same command run again does not
assign a second time.

Examples:
  python scripts/assign_commerce_legacy.py --provider-root DIR --dry-run
  python scripts/assign_commerce_legacy.py --provider-root DIR --kind fx \\
      --snapshot-id SNAP --tenant TENANT --backup DIR/fx.json \\
      --audit DIR/audit.jsonl --actor operator
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, TypedDict
from uuid import uuid4

from filelock import FileLock

from fox3d.commerce import PROVIDER_BY_KIND, SNAPSHOT_FORMAT_VERSION, SnapshotStore, _row_hash
from fox3d.ids import sha256_bytes
from fox3d.infra import utcnow

_CONTROL_CHARS = frozenset("\r\n\x00")


class _Applied(TypedDict):
    action: str
    assignedCount: int
    snapshotHashes: dict[str, str]
    backupSha256: str
    mutated: bool


class LegacyOpsError(Exception):
    """Operator-facing refusal. ``code`` is stable; ``message`` has no file contents."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _is_safe_token(value: object) -> bool:
    return isinstance(value, str) and value.strip() != "" and value == value.strip() and not any(char in value for char in _CONTROL_CHARS)


def _reject_control(value: str, *, code: str, message: str) -> str:
    if not _is_safe_token(value):
        raise LegacyOpsError(code, message)
    return value


def _check_kind(kind: str) -> str:
    if kind not in PROVIDER_BY_KIND:
        raise LegacyOpsError("invalid-kind", "Unknown provider kind")
    return kind


def _check_ids(snapshot_ids: list[str]) -> list[str]:
    if not snapshot_ids:
        raise LegacyOpsError("usage", "At least one --snapshot-id is required")
    cleaned: list[str] = []
    for snapshot_id in snapshot_ids:
        cleaned.append(
            _reject_control(
                snapshot_id,
                code="invalid-snapshot",
                message="Snapshot IDs must be non-empty strings without surrounding whitespace",
            )
        )
    if len(set(cleaned)) != len(cleaned):
        raise LegacyOpsError("duplicate-ids", "Snapshot IDs must be unique")
    return cleaned


def _existing_root(provider_root: Path) -> Path:
    root = Path(provider_root).resolve()
    if not root.is_dir():
        raise LegacyOpsError("provider-root", "Provider root must be an existing directory")
    return root


def _same_file(left: Path, right: Path) -> bool:
    try:
        left_stat, right_stat = left.stat(), right.stat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise LegacyOpsError("audit-failed", "Cannot safely compare file paths") from exc
    return left_stat.st_dev == right_stat.st_dev and left_stat.st_ino == right_stat.st_ino


def _backup_file(backup: Path, *, kind: str, live: Path) -> Path:
    candidate = Path(backup).resolve()
    if candidate.is_dir():
        candidate = (Path(backup) / f"{kind}.json").resolve()
    if not candidate.is_file():
        raise LegacyOpsError("backup-missing", "Backup file does not exist")
    if candidate == live.resolve() or _same_file(candidate, live):
        raise LegacyOpsError("backup-is-live", "Backup must be a separate copy of the provider file")
    return candidate


def _claimed(row: Mapping[str, Any]) -> str | None:
    value = row.get("claimedTenantId")
    if isinstance(value, str) and value:
        return value
    return None


def _list_kind(root: Path, kind: str) -> dict[str, Any]:
    path = root / f"{kind}.json"
    if not path.exists():
        return {"kind": kind, "quarantined": []}
    if not path.is_file():
        raise LegacyOpsError("provider-invalid", "Provider path is not a file")
    try:
        rows = SnapshotStore(root, kind=kind).quarantined()
    except json.JSONDecodeError as exc:
        raise LegacyOpsError("provider-invalid", "Provider file is not valid JSON") from exc
    except OSError as exc:
        raise LegacyOpsError("provider-invalid", "Provider file could not be read") from exc
    listed = [
        {"snapshotId": row["snapshotId"], "claimedTenantId": _claimed(row)}
        for row in rows
        if isinstance(row.get("snapshotId"), str)
    ]
    listed.sort(key=lambda item: str(item["snapshotId"]))
    return {"kind": kind, "quarantined": listed}


def dry_run(provider_root: Path, *, kind: str | None = None) -> dict[str, Any]:
    """List quarantined rows. Does not rewrite provider JSON."""
    root = _existing_root(provider_root)
    if kind is None:
        kinds = tuple(PROVIDER_BY_KIND)
    else:
        kinds = (_check_kind(kind),)
    return {
        "ok": True,
        "mode": "dry-run",
        "providerRoot": str(root),
        "claimedTenantIdIsNotAuthority": True,
        "kinds": [_list_kind(root, item) for item in kinds],
    }


def _ids_in_backup(data: bytes) -> set[str]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyOpsError("backup-invalid", "Backup is not a readable provider JSON file") from exc
    if not isinstance(payload, dict):
        raise LegacyOpsError("backup-invalid", "Backup is not a readable provider JSON file")
    found: set[str] = set()
    for key in ("items", "legacyItems"):
        rows = payload.get(key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("snapshotId"), str):
                found.add(row["snapshotId"])
    return found


def _classify(store: SnapshotStore, snapshot_ids: list[str], tenant_id: str) -> str:
    conflicts: list[str] = []
    missing: list[str] = []
    already: list[str] = []
    pending: list[str] = []
    for snapshot_id in snapshot_ids:
        in_legacy = snapshot_id in store.legacy
        destination = (tenant_id, snapshot_id) in store.items
        if in_legacy and destination:
            conflicts.append(snapshot_id)
        elif in_legacy:
            pending.append(snapshot_id)
        elif destination:
            already.append(snapshot_id)
        else:
            missing.append(snapshot_id)
    if conflicts:
        raise LegacyOpsError("destination-exists", "Destination already has this snapshot")
    if missing:
        raise LegacyOpsError("missing", "Snapshot is not quarantined")
    if pending and already:
        raise LegacyOpsError("mixed-state", "Request mixes quarantined and already-assigned snapshots")
    if pending:
        return "assign"
    return "already-assigned"


def _hashes(store: SnapshotStore, snapshot_ids: list[str], tenant_id: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for snapshot_id in snapshot_ids:
        row = store.items.get((tenant_id, snapshot_id))
        digest = row.get("snapshotHash") if isinstance(row, dict) else None
        if isinstance(digest, str):
            hashes[snapshot_id] = digest
    return hashes


def _read_bytes(path: Path, *, code: str, message: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LegacyOpsError(code, message) from exc


def _apply_assignment(
    *,
    root: Path,
    kind: str,
    snapshot_ids: list[str],
    tenant_id: str,
    backup_path: Path,
    live: Path,
    audit_path: Path,
    at: str,
    actor: str,
) -> _Applied:
    """Classify, audit and assign while the provider lock is held."""
    try:
        store = SnapshotStore(root, kind=kind)
    except json.JSONDecodeError as exc:
        raise LegacyOpsError("provider-invalid", "Provider file is not valid JSON") from exc
    except OSError as exc:
        raise LegacyOpsError("provider-invalid", "Provider file could not be read") from exc
    # Hold this store's lock until assign_legacy returns. A second FileLock on the same
    # path would release the operating-system lock when that inner lock exited.
    with store._locked():
        try:
            store.load()
        except json.JSONDecodeError as exc:
            raise LegacyOpsError("provider-invalid", "Provider file is not valid JSON") from exc
        except OSError as exc:
            raise LegacyOpsError("provider-invalid", "Provider file could not be read") from exc
        # Re-check inside the lock. A symlink swap must not turn the backup into the live file.
        if backup_path.resolve() == live.resolve() or _same_file(backup_path, live):
            raise LegacyOpsError("backup-is-live", "Backup must be a separate copy of the provider file")
        live_bytes = _read_bytes(live, code="provider-invalid", message="Provider file could not be read")
        _reject_duplicate_rows(live_bytes)
        tag = _classify(store, snapshot_ids, tenant_id)
        backup_bytes = _read_bytes(backup_path, code="backup-missing", message="Backup file does not exist")
        backup_sha = sha256_bytes(backup_bytes)
        if tag == "assign":
            if live_bytes != backup_bytes:
                raise LegacyOpsError("backup-mismatch", "Backup does not match the current provider file")
            hashes = {}
            for snapshot_id in snapshot_ids:
                row = dict(store.legacy[snapshot_id])
                row["tenantId"] = tenant_id
                hashes[snapshot_id] = _row_hash(row)
            intent = _audit_record(
                at=at, action="intent", ok=False, reason=None,
                message="Assignment intended; confirm completion against provider", kind=kind,
                tenant_id=tenant_id, snapshot_ids=snapshot_ids, actor=actor,
                backup=str(backup_path), assigned_count=len(snapshot_ids),
                snapshot_hashes=hashes, backup_sha256=backup_sha,
            )
            intent["providerRoot"] = str(root)
            intent["transactionId"] = uuid4().hex
            _append_audit(audit_path, intent)
            try:
                assigned = store.assign_legacy(snapshot_ids, tenant_id=tenant_id)
            except ValueError as exc:
                raise LegacyOpsError("rejected", "Legacy snapshot was not assigned") from exc
            except OSError as exc:
                raise LegacyOpsError("io-error", "Provider file could not be written") from exc
            completed = dict(intent)
            completed.update(action="assigned", ok=True, message="Assignment recorded", intentAt=at)
            _append_audit(audit_path, completed)
            return {
                "action": "assigned",
                "assignedCount": assigned,
                "snapshotHashes": _hashes(store, snapshot_ids, tenant_id),
                "backupSha256": backup_sha,
                "mutated": True,
            }
        if set(snapshot_ids) - _ids_in_backup(backup_bytes):
            raise LegacyOpsError("backup-unrelated", "Backup does not contain the requested snapshot IDs")
        if tag == "already-assigned":
            _recover_audit(audit_path, root, kind, tenant_id, snapshot_ids, backup_sha, store)
            return {
                "action": "already-assigned",
                "assignedCount": 0,
                "snapshotHashes": _hashes(store, snapshot_ids, tenant_id),
                "backupSha256": backup_sha,
                "mutated": False,
            }
        raise LegacyOpsError("rejected", "Legacy snapshot was not assigned")


def _reject_duplicate_rows(data: bytes) -> None:
    try:
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError
        legacy = payload.get("legacyItems", []) if payload.get("formatVersion") == SNAPSHOT_FORMAT_VERSION else payload.get("items", [])
        if not isinstance(legacy, list):
            raise ValueError
        seen: set[str] = set()
        for row in legacy:
            if isinstance(row, dict) and isinstance(row.get("snapshotId"), str):
                sid = row["snapshotId"]
                if sid in seen:
                    raise LegacyOpsError("duplicate-provider-ids", "Provider contains duplicate legacy snapshot IDs")
                seen.add(sid)
    except (ValueError, UnicodeError) as exc:
        raise LegacyOpsError("provider-invalid", "Provider file is not valid JSON") from exc


def _recover_audit(path: Path, root: Path, kind: str, tenant: str, ids: list[str], backup_sha: str, store: SnapshotStore) -> None:
    hashes = _hashes(store, ids, tenant)
    if not path.exists():
        return
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeError, ValueError) as exc:
        raise LegacyOpsError("audit-failed", "Audit log cannot be read safely") from exc
    for index, record in reversed(list(enumerate(records))):
        if not isinstance(record, dict) or record.get("action") != "intent":
            continue
        if (record.get("providerRoot"), record.get("kind"), record.get("tenantId"), record.get("snapshotIds"), record.get("backupSha256")) != (str(root), kind, tenant, ids, backup_sha):
            continue
        if any(isinstance(later, dict) and later.get("action") == "assigned" and later.get("transactionId") == record.get("transactionId") for later in records[index + 1:]):
            break
        if not isinstance(record.get("at"), str) or not isinstance(record.get("transactionId"), str):
            raise LegacyOpsError("audit-failed", "Audit intent is malformed")
        if record.get("snapshotHashes") != hashes or any(_row_hash(store.items[(tenant, sid)]) != hashes.get(sid) for sid in ids):
            raise LegacyOpsError("audit-failed", "Assigned snapshots do not match the audit intent")
        recovered = dict(record)
        recovered.update(action="assigned", ok=True, message="Assignment recovered from intent", intentAt=record["at"])
        _append_audit(path, recovered)
        break


def _append_audit(path: Path, record: Mapping[str, Any]) -> None:
    if path.exists() and not path.is_file():
        raise LegacyOpsError("audit-failed", "Audit path is not a file")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LegacyOpsError("audit-failed", "Could not write the audit record") from exc
    line = json.dumps(dict(record), ensure_ascii=False, sort_keys=True) + "\n"
    data = line.encode("utf-8")
    lock = FileLock(str(path) + ".lock")
    try:
        with lock:
            if path.exists():
                raw = path.read_bytes()
                if raw and (not raw.endswith(b"\n") or any(not isinstance(json.loads(line), dict) for line in raw.splitlines())):
                    raise OSError("Invalid audit log")
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
            try:
                written = os.write(fd, data)
                if written != len(data):
                    raise OSError("Short audit write")
                os.fsync(fd)
            finally:
                os.close(fd)
            if os.name != "nt":
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
    except (OSError, ValueError, UnicodeError) as exc:
        raise LegacyOpsError("audit-failed", "Could not write the audit record") from exc


def _audit_record(
    *,
    at: str,
    action: str,
    ok: bool,
    reason: str | None,
    message: str,
    kind: str,
    tenant_id: str,
    snapshot_ids: list[str],
    actor: str,
    backup: str,
    assigned_count: int,
    snapshot_hashes: Mapping[str, str],
    backup_sha256: str | None,
) -> dict[str, Any]:
    return {
        "at": at,
        "action": action,
        "ok": ok,
        "reason": reason,
        "message": message,
        "kind": kind,
        "tenantId": tenant_id,
        "snapshotIds": list(snapshot_ids),
        "actor": actor,
        "backup": backup,
        "assignedCount": assigned_count,
        "snapshotHashes": dict(snapshot_hashes),
        "backupSha256": backup_sha256,
    }


def _clobbers_provider(audit_path: Path, root: Path | None, backup_path: Path | None) -> bool:
    if root is not None and root.is_dir():
        for kind in PROVIDER_BY_KIND:
            live = (root / f"{kind}.json").resolve()
            if audit_path == live or _same_file(audit_path, live):
                return True
    if backup_path is not None and (audit_path == backup_path or _same_file(audit_path, backup_path)):
        return True
    return False


def _optional_sha(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def execute_assign(
    provider_root: Path,
    *,
    kind: str,
    snapshot_ids: list[str],
    tenant_id: str,
    backup: Path,
    audit: Path,
    actor: str,
) -> dict[str, Any]:
    """Assign quarantined snapshots, or refuse. Appends one audit record when that would not clobber data."""
    audit_path = Path(audit).resolve()
    at = utcnow().isoformat()
    checked_kind = ""
    checked_ids: list[str] = []
    checked_tenant = ""
    checked_actor = ""
    backup_path: Path | None = None
    root: Path | None = None
    audit_safe = False
    try:
        root = _existing_root(provider_root)
        # Resolve the supplied backup even when argument validation will fail.
        backup_path = Path(backup).resolve()
        if backup_path.is_dir():
            if kind not in PROVIDER_BY_KIND:
                raise LegacyOpsError("invalid-kind", "Unknown provider kind")
            backup_path = (backup_path / f"{kind}.json").resolve()
        if (_clobbers_provider(audit_path, root, backup_path)
                or _clobbers_provider(Path(str(audit_path) + ".lock"), root, backup_path)):
            raise LegacyOpsError("audit-failed", "Audit path must not be the provider file or the backup")
        audit_safe = True
        checked_kind = _check_kind(kind)
        if all(_is_safe_token(item) for item in snapshot_ids):
            checked_ids = list(snapshot_ids)
        checked_ids = _check_ids(snapshot_ids)
        checked_tenant = _reject_control(
            tenant_id,
            code="invalid-tenant",
            message="Tenant id must be a non-empty string without surrounding whitespace",
        )
        checked_actor = _reject_control(
            actor,
            code="invalid-actor",
            message="Actor must be a non-empty string without surrounding whitespace",
        )
        root = _existing_root(provider_root)
        live = root / f"{checked_kind}.json"
        if _clobbers_provider(audit_path, root, None):
            raise LegacyOpsError("audit-failed", "Audit path must not be the provider file or the backup")
        if not live.is_file():
            raise LegacyOpsError("provider-missing", "Provider file does not exist")
        backup_path = _backup_file(backup, kind=checked_kind, live=live)
        if _clobbers_provider(audit_path, root, backup_path):
            raise LegacyOpsError("audit-failed", "Audit path must not be the provider file or the backup")
        applied = _apply_assignment(
            root=root,
            kind=checked_kind,
            snapshot_ids=checked_ids,
            tenant_id=checked_tenant,
            backup_path=backup_path,
            live=live,
            audit_path=audit_path,
            at=at,
            actor=checked_actor,
        )
    except LegacyOpsError as exc:
        if exc.code != "audit-failed" and audit_safe and not _clobbers_provider(audit_path, root, backup_path):
            try:
                _append_audit(
                    audit_path,
                    _audit_record(
                        at=at,
                        action="refused",
                        ok=False,
                        reason=exc.code,
                        message=exc.message,
                        kind=checked_kind,
                        tenant_id=checked_tenant,
                        snapshot_ids=checked_ids,
                        actor=checked_actor,
                        backup="" if backup_path is None else str(backup_path),
                        assigned_count=0,
                        snapshot_hashes={},
                        backup_sha256=_optional_sha(backup_path),
                    ),
                )
            except LegacyOpsError as audit_exc:
                raise LegacyOpsError("audit-failed", f"Could not write the audit record ({exc.code})") from audit_exc
        raise
    record = _audit_record(
        at=at,
        action=applied["action"],
        ok=True,
        reason=None,
        message="Assignment recorded" if applied["action"] == "assigned" else "Snapshot already assigned to this tenant",
        kind=checked_kind,
        tenant_id=checked_tenant,
        snapshot_ids=checked_ids,
        actor=checked_actor,
        backup="" if backup_path is None else str(backup_path),
        assigned_count=applied["assignedCount"],
        snapshot_hashes=applied["snapshotHashes"],
        backup_sha256=applied["backupSha256"],
    )
    if not applied["mutated"]:
        _append_audit(audit_path, record)
    return {
        "ok": True,
        "action": applied["action"],
        "kind": checked_kind,
        "tenantId": checked_tenant,
        "snapshotIds": checked_ids,
        "assignedCount": applied["assignedCount"],
        "snapshotHashes": applied["snapshotHashes"],
        "backupSha256": applied["backupSha256"],
        "audit": str(audit_path),
        "actor": checked_actor,
    }


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--kind", default=None)
    parser.add_argument("--snapshot-id", action="append", default=[])
    parser.add_argument("--tenant", default=None)
    parser.add_argument("--backup", type=Path, default=None)
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument("--actor", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = _build_parser().parse_args(argv)
    try:
        if args.dry_run:
            if args.snapshot_id or args.tenant is not None or args.backup is not None or args.audit is not None or args.actor is not None:
                raise LegacyOpsError("usage", "Dry-run does not accept assignment options")
            if args.kind is not None and not isinstance(args.kind, str):
                raise LegacyOpsError("invalid-kind", "Unknown provider kind")
            result = dry_run(args.provider_root, kind=args.kind)
        else:
            if (
                not isinstance(args.kind, str)
                or not args.snapshot_id
                or not isinstance(args.tenant, str)
                or not isinstance(args.backup, Path)
                or not isinstance(args.audit, Path)
                or not isinstance(args.actor, str)
            ):
                raise LegacyOpsError(
                    "usage",
                    "Assignment requires --kind, --snapshot-id, --tenant, --backup, --audit, and --actor",
                )
            snapshot_ids = [item for item in args.snapshot_id if isinstance(item, str)]
            if len(snapshot_ids) != len(args.snapshot_id):
                raise LegacyOpsError("invalid-snapshot", "Snapshot IDs must be non-empty strings without surrounding whitespace")
            result = execute_assign(
                args.provider_root,
                kind=args.kind,
                snapshot_ids=snapshot_ids,
                tenant_id=args.tenant,
                backup=args.backup,
                audit=args.audit,
                actor=args.actor,
            )
    except LegacyOpsError as exc:
        print(json.dumps({"ok": False, "error": exc.code, "message": exc.message}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
