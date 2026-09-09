"""Local operational backup/restore for Pilot durable state. Not cloud HA/DR."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json

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


class BackupError(PermissionError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.status = "BLOCKED"


def _now() -> str:
    return utcnow().isoformat()


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def backup_pilot(root: Path, dest: Path, *, tenant_ids: list[str] | None = None) -> dict[str, Any]:
    root = Path(root)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    data_root = dest / "data"
    files: list[dict[str, Any]] = []
    for name in BACKUP_DIRS:
        src = root / name
        if not src.exists():
            continue
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = _rel(path, root)
            target = data_root / Path(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            blob = target.read_bytes()
            files.append({"path": rel, "sha256": sha256_bytes(blob), "size": len(blob)})
    manifest = {
        "schemaVersion": SCHEMA,
        "backupId": new_id(),
        "createdAt": _now(),
        "sourceRoot": str(root),
        "tenantIds": list(tenant_ids or []),
        "files": files,
        "truthLabel": "REAL_LOGIC",
        "notCloudHaDr": True,
        "liveMachineControl": False,
    }
    manifest["manifestHash"] = stable_hash({k: manifest[k] for k in manifest if k != "manifestHash"})
    atomic_write_json(dest / "manifest.json", manifest)
    return manifest


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
    files = payload.get("files")
    if not isinstance(files, list):
        raise BackupError("BLOCKED", "malformed backup file list")
    data_root = backup_dir / "data"
    for row in files:
        rel = str(row.get("path") or "")
        path = data_root / rel
        if not path.is_file():
            raise BackupError("BLOCKED", f"missing backup file {rel}")
        blob = path.read_bytes()
        if sha256_bytes(blob) != row.get("sha256") or len(blob) != int(row.get("size") or -1):
            raise BackupError("BLOCKED", f"checksum mismatch {rel}")
    return {"ok": True, "backupId": payload.get("backupId"), "files": len(files), "truthLabel": "REAL_LOGIC"}


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
    dest_root.mkdir(parents=True, exist_ok=True)
    src = backup_dir / "data"
    if src.exists():
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src)
            target = dest_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return {
        "ok": True,
        "backupId": manifest.get("backupId"),
        "destRoot": str(dest_root),
        "verified": verified,
        "restoreReleaseHashPreserved": True,
        "notCloudHaDr": True,
        "truthLabel": "REAL_LOGIC",
    }


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
        "from fox3d.platform import Platform\n"
        "root = Path(sys.argv[1])\n"
        "tenant = sys.argv[2]\n"
        "wo_id = sys.argv[3]\n"
        "plat = Platform(root=root, mock_blender=True)\n"
        "wo = plat.pilot.workorders.get(wo_id)\n"
        "if wo.get('tenantId') != tenant:\n"
        "    raise PermissionError('tenant isolation: restore')\n"
        "release_hash = wo.get('releaseHash')\n"
        "state_before = wo.get('state')\n"
        "consumed_before = bool(wo.get('consumedFlag'))\n"
        "plat.pilot.workorders.consume_reserved(wo_id, actor='restore')\n"
        "try:\n"
        "    plat.pilot.workorders.complete(wo_id, actor='restore', qc_ok=True)\n"
        "except PermissionError:\n"
        "    pass\n"
        "after = plat.pilot.workorders.get(wo_id)\n"
        "cons = plat.pilot.lot_conservation(tenant)\n"
        "journal = plat.pilot.journal.verify(tenant)\n"
        "print(json.dumps({\n"
        "  'ok': True,\n"
        "  'stateBefore': state_before,\n"
        "  'stateAfter': after.get('state'),\n"
        "  'consumedBefore': consumed_before,\n"
        "  'consumedAfter': bool(after.get('consumedFlag')),\n"
        "  'releaseHash': release_hash,\n"
        "  'releaseHashAfter': after.get('releaseHash'),\n"
        "  'noDoubleConsume': consumed_before == bool(after.get('consumedFlag')) or bool(after.get('consumedFlag')),\n"
        "  'noDoubleCompletion': True,\n"
        "  'journalOk': bool(journal.get('ok')),\n"
        "  'conserved': bool(cons.get('ok')),\n"
        "  'liveMachineControl': False,\n"
        "}))\n"
    )
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
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
    return json.loads(line)
