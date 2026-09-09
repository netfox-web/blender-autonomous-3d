"""Local operational backup/restore for Pilot durable state. Not cloud HA/DR."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.storelock import FileLock

SCHEMA = "fox3d.backup.v1"
BACKUP_DIRS = (
    "lots",
    "remnants",
    "dam",
    "journal",
    "tx",
    "releases",
    "workorders",
    "receipts",
    "stations",
    "leases",
    "identity",
    "cyclecounts",
    "logistics",
    "qc",
    "exceptions",
)
VOLATILE_SUFFIXES = {".lock", ".tmp", ".staging"}
MIXED_JSON = {
    "lots/lots.json": ("lots",),
    "workorders/workorders.json": ("orders", "operations"),
    "identity/identity.json": ("operators", "shifts"),
    "receipts/receipts.json": ("receipts", "requests"),
    "stations/stations.json": ("stations",),
    "leases/leases.json": ("leases", "jobs"),
    "cyclecounts/cyclecounts.json": ("counts",),
    "logistics/logistics.json": ("cartons", "pallets", "shipments", "carrier_quotes", "checklists", "handoffs"),
    "qc/qc.json": ("checks", "defects"),
    "exceptions/exceptions.json": ("items",),
    "releases/releases.json": ("releases",),
}
SNAPSHOT_RETRIES = 5


class BackupError(PermissionError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.status = "BLOCKED"


def _now() -> str:
    return utcnow().isoformat()


def _safe_tenant(tenant_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in tenant_id)


def _is_volatile(path: Path) -> bool:
    name = path.name
    return path.suffix in VOLATILE_SUFFIXES or name.endswith(".json.tmp") or name.endswith(".json.staging")


def _validate_rel(rel: str) -> str:
    raw = str(rel or "").replace("\\", "/").strip()
    if not raw:
        raise BackupError("BLOCKED", "empty backup path")
    if raw.startswith("/") or raw.startswith("\\"):
        raise BackupError("BLOCKED", f"absolute path {rel}")
    if len(raw) >= 2 and raw[1] == ":":
        raise BackupError("BLOCKED", f"absolute path {rel}")
    parts = [p for p in raw.split("/") if p not in {"", "."}]
    if not parts or ".." in parts:
        raise BackupError("BLOCKED", f"path traversal {rel}")
    return "/".join(parts)


def _tenant_of(rec: Any) -> str | None:
    if not isinstance(rec, dict):
        return None
    val = rec.get("tenantId")
    if val is None:
        val = rec.get("tenant_id")
    return str(val) if val is not None else None


def _filter_idem(idem: Any, tids: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (idem or {}).items() if isinstance(idem, dict) else []:
        if any(str(key).startswith(f"{tid}::") for tid in tids):
            out[key] = value
    return out


def _filter_payload(payload: dict[str, Any], rel: str, tids: set[str]) -> dict[str, Any]:
    keys = MIXED_JSON.get(rel)
    if not keys:
        return payload
    filtered = dict(payload)
    kept_ids: set[str] = set()
    for key in keys:
        rows = payload.get(key) or []
        if not isinstance(rows, list):
            continue
        kept = [r for r in rows if isinstance(r, dict) and _tenant_of(r) in tids]
        filtered[key] = kept
        for rec in kept:
            for id_key in ("workOrderId", "releaseId", "lotId", "stationId", "leaseId", "jobId"):
                if rec.get(id_key):
                    kept_ids.add(str(rec[id_key]))
    if rel == "workorders/workorders.json":
        filtered["operations"] = [
            o
            for o in (payload.get("operations") or [])
            if isinstance(o, dict) and (o.get("workOrderId") in kept_ids or _tenant_of(o) in tids)
        ]
    if rel == "releases/releases.json":
        packets = payload.get("packets") or {}
        filtered["packets"] = {k: v for k, v in packets.items() if k in kept_ids} if isinstance(packets, dict) else {}
    if "idem" in payload:
        filtered["idem"] = _filter_idem(payload.get("idem"), tids)
    return filtered


def _include_file(rel: str, tids: set[str] | None) -> bool:
    if not tids:
        return True
    parts = rel.split("/")
    if parts[0] in {"journal", "remnants"} and len(parts) >= 2:
        stem = Path(parts[-1]).stem
        return stem in {_safe_tenant(t) for t in tids}
    if parts[0] == "dam" and len(parts) >= 2:
        return parts[1] in tids
    if parts[0] == "tx":
        return True
    return True


def _source_files(root: Path) -> list[Path]:
    rows: list[Path] = []
    for name in BACKUP_DIRS:
        src = root / name
        if not src.exists():
            continue
        for path in src.rglob("*"):
            if path.is_symlink():
                raise BackupError("BLOCKED", f"symlink {path}")
            if not path.is_file() or _is_volatile(path):
                continue
            rows.append(path)
    return rows


def _fingerprint(root: Path, paths: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in paths:
        rel = _validate_rel(path.relative_to(root).as_posix())
        out[rel] = sha256_bytes(path.read_bytes()) if path.exists() else ""
    return out


def _lock_paths(root: Path, tenant_ids: list[str] | None) -> list[Path]:
    paths = [
        root / "lots" / "lots.lock",
        root / "stations" / "stations.lock",
        root / "tx" / "outbox.lock",
    ]
    for tid in tenant_ids or []:
        paths.append(root / "journal" / f"{_safe_tenant(tid)}.lock")
    return sorted({p for p in paths if p.parent.exists()})


def _copy_one(src: Path, root: Path, data_root: Path, tids: set[str] | None) -> dict[str, Any] | None:
    rel = _validate_rel(src.relative_to(root).as_posix())
    if not _include_file(rel, tids):
        return None
    target = data_root / Path(*rel.split("/"))
    if src.is_symlink() or target.is_symlink():
        raise BackupError("BLOCKED", f"symlink {rel}")
    if rel.startswith("tx/") and tids:
        payload = read_json(src)
        if isinstance(payload, dict) and _tenant_of(payload) not in tids and payload.get("tenantId") not in tids:
            return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if tids and rel in MIXED_JSON:
        payload = read_json(src)
        if not isinstance(payload, dict):
            raise BackupError("BLOCKED", f"malformed {rel}")
        filtered = _filter_payload(payload, rel, tids)
        atomic_write_json(target, filtered)
    else:
        shutil.copy2(src, target)
    blob = target.read_bytes()
    return {"path": rel, "sha256": sha256_bytes(blob), "size": len(blob)}


def backup_pilot(root: Path, dest: Path, *, tenant_ids: list[str] | None = None) -> dict[str, Any]:
    root = Path(root)
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise BackupError("BLOCKED", "backup destination must be empty")
    dest.mkdir(parents=True, exist_ok=True)
    data_root = dest / "data"
    tids = set(tenant_ids or []) or None
    last_error = "inconsistent snapshot"
    for _ in range(SNAPSHOT_RETRIES):
        locks = [FileLock(p) for p in _lock_paths(root, tenant_ids)]
        try:
            for lock in locks:
                lock.acquire()
            sources = _source_files(root)
            before = _fingerprint(root, sources)
            if data_root.exists():
                shutil.rmtree(data_root)
            data_root.mkdir(parents=True, exist_ok=True)
            files: list[dict[str, Any]] = []
            seen: set[str] = set()
            for src in sources:
                row = _copy_one(src, root, data_root, tids)
                if row is None:
                    continue
                if row["path"] in seen:
                    raise BackupError("BLOCKED", f"duplicate path {row['path']}")
                seen.add(row["path"])
                files.append(row)
            after = _fingerprint(root, sources)
            if before != after:
                last_error = "source changed during snapshot"
                continue
            files = sorted(files, key=lambda r: r["path"])
            scope = "TENANT_SCOPED" if tids else "WHOLE_PILOT_ROOT"
            manifest = {
                "schemaVersion": SCHEMA,
                "backupId": new_id(),
                "createdAt": _now(),
                "sourceRoot": str(root),
                "tenantIds": list(tenant_ids or []),
                "scope": scope,
                "files": files,
                "truthLabel": "REAL_LOGIC",
                "notCloudHaDr": True,
                "liveMachineControl": False,
                "consistentSnapshot": True,
            }
            manifest["manifestHash"] = stable_hash({k: manifest[k] for k in manifest if k != "manifestHash"})
            atomic_write_json(dest / "manifest.json", manifest)
            verify_backup(dest)
            return manifest
        finally:
            for lock in reversed(locks):
                lock.release()
    raise BackupError("BLOCKED", last_error)


def _listed_paths(files: list[Any]) -> list[str]:
    if not isinstance(files, list):
        raise BackupError("BLOCKED", "malformed backup file list")
    listed: list[str] = []
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, dict):
            raise BackupError("BLOCKED", "malformed backup file row")
        rel = _validate_rel(str(row.get("path") or ""))
        if rel in seen:
            raise BackupError("BLOCKED", f"duplicate path {rel}")
        seen.add(rel)
        listed.append(rel)
    return listed


def _actual_data_files(data_root: Path) -> set[str]:
    actual: set[str] = set()
    if not data_root.exists():
        return actual
    for path in data_root.rglob("*"):
        if path.is_symlink():
            raise BackupError("BLOCKED", f"symlink {path}")
        if not path.is_file() or _is_volatile(path):
            continue
        actual.add(_validate_rel(path.relative_to(data_root).as_posix()))
    return actual


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    backup_dir = Path(backup_dir)
    payload = read_json(backup_dir / "manifest.json")
    if not payload or not isinstance(payload, dict):
        raise BackupError("BLOCKED", "malformed or missing backup manifest")
    if payload.get("schemaVersion") != SCHEMA:
        raise BackupError("BLOCKED", "unsupported backup schema")
    expected = stable_hash({k: payload[k] for k in payload if k != "manifestHash"})
    if payload.get("manifestHash") != expected:
        raise BackupError("BLOCKED", "tampered backup manifest")
    listed = _listed_paths(payload.get("files") or [])
    data_root = backup_dir / "data"
    actual = _actual_data_files(data_root)
    listed_set = set(listed)
    extra = sorted(actual - listed_set)
    missing = sorted(listed_set - actual)
    if extra:
        raise BackupError("BLOCKED", f"unlisted backup files {extra}")
    if missing:
        raise BackupError("BLOCKED", f"missing backup file {missing}")
    for row in payload.get("files") or []:
        rel = _validate_rel(str(row.get("path") or ""))
        path = data_root / Path(*rel.split("/"))
        blob = path.read_bytes()
        if sha256_bytes(blob) != row.get("sha256") or len(blob) != int(row.get("size") or -1):
            raise BackupError("BLOCKED", f"checksum mismatch {rel}")
    return {
        "ok": True,
        "backupId": payload.get("backupId"),
        "files": len(listed),
        "exactSet": True,
        "truthLabel": "REAL_LOGIC",
    }


def _dest_has_pilot_state(dest_root: Path) -> bool:
    for name in BACKUP_DIRS:
        path = dest_root / name
        if path.exists() and any(p.is_file() for p in path.rglob("*")):
            return True
    return False


def restore_pilot(
    backup_dir: Path,
    dest_root: Path,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    backup_dir = Path(backup_dir)
    dest_root = Path(dest_root)
    verified = verify_backup(backup_dir)
    manifest = read_json(backup_dir / "manifest.json") or {}
    tenants = list(manifest.get("tenantIds") or [])
    if tenant_id and tenants and tenant_id not in tenants:
        raise PermissionError("cross-tenant restore rejected")
    if dest_root.exists() and _dest_has_pilot_state(dest_root):
        raise BackupError("BLOCKED", "restore destination has unexpected Pilot state")
    dest_root.mkdir(parents=True, exist_ok=True)
    data_root = backup_dir / "data"
    for row in manifest.get("files") or []:
        rel = _validate_rel(str(row.get("path") or ""))
        src = data_root / Path(*rel.split("/"))
        if src.is_symlink():
            raise BackupError("BLOCKED", f"symlink {rel}")
        target = dest_root / Path(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return {
        "ok": True,
        "backupId": manifest.get("backupId"),
        "destRoot": str(dest_root),
        "verified": verified,
        "scope": manifest.get("scope"),
        "restoreReleaseHashPreserved": True,
        "notCloudHaDr": True,
        "truthLabel": "REAL_LOGIC",
    }


def capture_restore_facts(plat: Any, *, tenant_id: str, work_order_id: str) -> dict[str, Any]:
    wo = plat.pilot.workorders.get(work_order_id)
    if wo.get("tenantId") != tenant_id:
        raise PermissionError("tenant isolation: restore facts")
    reservations = []
    consumed_qty = 0
    lot_consumed: dict[str, int] = {}
    for item in wo.get("reservations") or []:
        qty = int(item.get("quantity") or 0)
        rec = {
            "reservationId": item.get("reservationId"),
            "lotId": item.get("lotId"),
            "quantity": qty,
            "state": item.get("state"),
        }
        reservations.append(rec)
        if item.get("state") == "CONSUMED":
            consumed_qty += qty
        if item.get("lotId"):
            lot_consumed[str(item["lotId"])] = int(
                plat.lots.quantities(item["lotId"], tenant_id=tenant_id).get("consumed") or 0
            )
    events = plat.pilot.journal.list(tenant_id)
    consume_events = [
        e
        for e in events
        if e.get("eventType") in {"workorder.consume", "material.consume"}
        and (
            e.get("aggregateId") == work_order_id
            or (e.get("payload") or {}).get("workOrderId") == work_order_id
        )
    ]
    complete_events = [
        e for e in events if e.get("eventType") == "workorder.complete" and e.get("aggregateId") == work_order_id
    ]
    integrity = plat.pilot.journal.verify(tenant_id)
    return {
        "state": wo.get("state"),
        "releaseHash": wo.get("releaseHash"),
        "reservations": reservations,
        "consumedQty": consumed_qty,
        "lotConsumed": lot_consumed,
        "consumeEventCount": len(consume_events),
        "completeEventCount": len(complete_events),
        "journalHead": integrity.get("headHash"),
        "journalSequence": integrity.get("sequence"),
        "journalOk": bool(integrity.get("ok") is True),
    }


def no_double_consume_ok(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    required = ("consumedQty", "consumeEventCount", "lotConsumed", "reservations")
    if any(before.get(k) is None or after.get(k) is None for k in required):
        return False
    return (
        before["consumedQty"] == after["consumedQty"]
        and before["consumeEventCount"] == after["consumeEventCount"]
        and before["lotConsumed"] == after["lotConsumed"]
        and before["reservations"] == after["reservations"]
    )


def no_double_complete_ok(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    required = ("state", "completeEventCount", "releaseHash")
    if any(before.get(k) is None or after.get(k) is None for k in required):
        return False
    return (
        before["state"] == after["state"] == "COMPLETED"
        and before["completeEventCount"] == after["completeEventCount"]
        and before["releaseHash"] == after["releaseHash"]
    )


def restart_after_restore(
    dest_root: Path,
    *,
    tenant_id: str,
    work_order_id: str,
    src_root: Path | None = None,
) -> dict[str, Any]:
    env_python = sys.executable
    src = str((src_root or Path(__file__).resolve().parents[1]))
    script = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, os.environ['FOX3D_SRC'])\n"
        "from fox3d.backup import capture_restore_facts, no_double_complete_ok, no_double_consume_ok\n"
        "from fox3d.platform import Platform\n"
        "root = Path(sys.argv[1])\n"
        "tenant = sys.argv[2]\n"
        "wo_id = sys.argv[3]\n"
        "plat = Platform(root=root, mock_blender=True)\n"
        "before = capture_restore_facts(plat, tenant_id=tenant, work_order_id=wo_id)\n"
        "plat.pilot.workorders.consume_reserved(wo_id, actor='restore')\n"
        "try:\n"
        "    plat.pilot.workorders.complete(wo_id, actor='restore', qc_ok=True)\n"
        "except PermissionError:\n"
        "    pass\n"
        "after = capture_restore_facts(plat, tenant_id=tenant, work_order_id=wo_id)\n"
        "print(json.dumps({\n"
        "  'stateBefore': before.get('state'),\n"
        "  'stateAfter': after.get('state'),\n"
        "  'releaseHash': before.get('releaseHash'),\n"
        "  'releaseHashAfter': after.get('releaseHash'),\n"
        "  'before': before,\n"
        "  'after': after,\n"
        "  'noDoubleConsume': no_double_consume_ok(before, after),\n"
        "  'noDoubleCompletion': no_double_complete_ok(before, after),\n"
        "  'journalOk': bool(after.get('journalOk') is True),\n"
        "  'liveMachineControl': False,\n"
        "}))\n"
    )
    env = dict(os.environ)
    env["FOX3D_SRC"] = src
    proc = subprocess.run(
        [env_python, "-c", script, str(dest_root), tenant_id, work_order_id],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise BackupError("BLOCKED", proc.stderr or proc.stdout or "restore restart failed")
    line = (proc.stdout or "").strip().splitlines()[-1]
    payload = json.loads(line)
    if payload.get("noDoubleConsume") is not True or payload.get("noDoubleCompletion") is not True:
        raise BackupError("BLOCKED", "restore retry mutated consume/complete facts")
    payload["ok"] = True
    return payload
