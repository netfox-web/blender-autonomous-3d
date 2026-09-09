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
TENANT_OWNED = "TENANT_OWNED"
TENANT_DERIVED = "TENANT_DERIVED"
GLOBAL_REFERENCE = "GLOBAL_REFERENCE"
GLOBAL_REFERENCE_POLICY = "EXCLUDE_FROM_TENANT_SCOPED"
MIXED_SPEC: dict[str, dict[str, str]] = {
    "lots/lots.json": {"lots": TENANT_OWNED},
    "workorders/workorders.json": {"orders": TENANT_OWNED, "operations": TENANT_DERIVED},
    "identity/identity.json": {"operators": TENANT_OWNED, "shifts": TENANT_OWNED},
    "receipts/receipts.json": {"receipts": TENANT_OWNED, "requests": TENANT_OWNED},
    "stations/stations.json": {"stations": TENANT_OWNED},
    "leases/leases.json": {"leases": TENANT_OWNED, "jobs": TENANT_OWNED},
    "cyclecounts/cyclecounts.json": {"counts": TENANT_OWNED},
    "logistics/logistics.json": {
        "cartons": TENANT_OWNED,
        "pallets": TENANT_DERIVED,
        "shipments": TENANT_OWNED,
        "carrier_quotes": GLOBAL_REFERENCE,
        "checklists": TENANT_OWNED,
        "handoffs": TENANT_OWNED,
    },
    "qc/qc.json": {"checks": TENANT_OWNED, "defects": TENANT_OWNED},
    "exceptions/exceptions.json": {"items": TENANT_OWNED},
    "releases/releases.json": {"releases": TENANT_OWNED},
}
MIXED_JSON = {rel: tuple(spec.keys()) for rel, spec in MIXED_SPEC.items()}
SNAPSHOT_RETRIES = 5
TENANT_MATRIX_DOMAINS = (
    "materialLots",
    "remnants",
    "releases",
    "packets",
    "idempotency",
    "workOrders",
    "operations",
    "receipts",
    "stations",
    "leases",
    "operators",
    "shifts",
    "cycleCounts",
    "cartons",
    "palletPlans",
    "shipments",
    "checklists",
    "handoffs",
    "qc",
    "exceptions",
    "journal",
    "outbox",
    "dam",
)


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


def _pallet_carton_ids(rec: dict[str, Any]) -> list[str]:
    ids = [str(x) for x in (rec.get("cartonIds") or [])]
    for pal in rec.get("pallets") or []:
        if isinstance(pal, dict):
            ids.extend(str(x) for x in (pal.get("cartonIds") or []))
    return ids


def _parent_tenants(payload: dict[str, Any], rel: str, key: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if rel == "logistics/logistics.json" and key == "pallets":
        rows = payload.get("cartons") or []
        id_key = "cartonId"
    elif rel == "workorders/workorders.json" and key == "operations":
        rows = payload.get("orders") or []
        id_key = "workOrderId"
    else:
        return out
    if not isinstance(rows, list):
        raise BackupError("BLOCKED", f"malformed parent collection for {rel}:{key}")
    for rec in rows:
        if not isinstance(rec, dict) or not rec.get(id_key):
            raise BackupError("BLOCKED", f"ambiguous parent row in {rel}:{key}")
        tid = _tenant_of(rec)
        if not tid:
            raise BackupError("BLOCKED", f"ambiguous {id_key} tenantId")
        out[str(rec[id_key])] = tid
    return out


def _derive_tenants(rel: str, key: str, rec: dict[str, Any], parents: dict[str, str]) -> set[str]:
    if rel == "logistics/logistics.json" and key == "pallets":
        carton_ids = _pallet_carton_ids(rec)
        if not carton_ids:
            raise BackupError("BLOCKED", "ambiguous pallet plan with no carton parent")
        tenants: set[str] = set()
        for cid in carton_ids:
            tid = parents.get(cid)
            if not tid:
                raise BackupError("BLOCKED", f"ambiguous pallet parent carton {cid}")
            tenants.add(tid)
        if len(tenants) != 1:
            raise BackupError("BLOCKED", "cross-tenant pallet plan")
        stamped = _tenant_of(rec)
        if stamped is not None and stamped not in tenants:
            raise BackupError("BLOCKED", "pallet tenantId mismatches derived owner")
        return tenants
    if rel == "workorders/workorders.json" and key == "operations":
        stamped = _tenant_of(rec)
        derived = parents.get(str(rec.get("workOrderId") or ""))
        if stamped and derived and stamped != derived:
            raise BackupError("BLOCKED", "operation tenantId mismatches work order")
        tid = stamped or derived
        if not tid:
            raise BackupError("BLOCKED", "ambiguous work order operation ownership")
        return {tid}
    stamped = _tenant_of(rec)
    if stamped:
        return {stamped}
    raise BackupError("BLOCKED", f"ambiguous {rel}:{key} ownership")


def _filter_payload(payload: dict[str, Any], rel: str, tids: set[str]) -> dict[str, Any]:
    spec = MIXED_SPEC.get(rel)
    if not spec:
        return payload
    filtered = dict(payload)
    for key, policy in spec.items():
        rows = payload.get(key) or []
        if not isinstance(rows, list):
            continue
        if policy == GLOBAL_REFERENCE:
            filtered[key] = []
            continue
        kept: list[dict[str, Any]] = []
        parents = _parent_tenants(payload, rel, key) if policy == TENANT_DERIVED else {}
        for rec in rows:
            if not isinstance(rec, dict):
                raise BackupError("BLOCKED", f"ambiguous non-object in {rel}:{key}")
            if policy == TENANT_OWNED:
                tid = _tenant_of(rec)
                if tid is None:
                    raise BackupError("BLOCKED", f"ambiguous {rel}:{key} missing tenantId")
                if tid in tids:
                    kept.append(rec)
            elif policy == TENANT_DERIVED:
                owners = _derive_tenants(rel, key, rec, parents)
                if owners <= tids:
                    kept.append(rec)
                elif owners & tids:
                    raise BackupError("BLOCKED", f"cross-tenant {rel}:{key}")
            else:
                raise BackupError("BLOCKED", f"unknown collection policy {policy}")
        filtered[key] = kept
    if rel == "releases/releases.json":
        kept_ids = {str(r.get("releaseId")) for r in filtered.get("releases") or [] if isinstance(r, dict) and r.get("releaseId")}
        all_ids = {
            str(r.get("releaseId"))
            for r in (payload.get("releases") or [])
            if isinstance(r, dict) and r.get("releaseId")
        }
        packets = payload.get("packets") or {}
        if packets and not isinstance(packets, dict):
            raise BackupError("BLOCKED", "ambiguous packets payload")
        out_packets: dict[str, Any] = {}
        for pkt_id, value in (packets.items() if isinstance(packets, dict) else []):
            if pkt_id not in all_ids:
                raise BackupError("BLOCKED", f"ambiguous packet parent {pkt_id}")
            if pkt_id in kept_ids:
                out_packets[pkt_id] = value
        filtered["packets"] = out_packets
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


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    slim = {k: v for k, v in payload.items() if k != "generation"}
    return stable_hash(slim)


def _relevant_fingerprint(root: Path, tids: set[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in _source_files(root):
        rel = _validate_rel(path.relative_to(root).as_posix())
        if not _include_file(rel, tids):
            continue
        if tids and rel.startswith("tx/"):
            payload = read_json(path)
            if not isinstance(payload, dict):
                raise BackupError("BLOCKED", f"malformed tx {rel}")
            tid = _tenant_of(payload)
            if tid is None:
                raise BackupError("BLOCKED", f"ambiguous tx tenant {rel}")
            if tid not in tids:
                continue
            out[rel] = sha256_bytes(path.read_bytes())
            continue
        if tids and rel in MIXED_SPEC:
            payload = read_json(path)
            if not isinstance(payload, dict):
                raise BackupError("BLOCKED", f"malformed {rel}")
            filtered = _filter_payload(payload, rel, tids)
            out[rel] = _payload_fingerprint(filtered)
            continue
        out[rel] = sha256_bytes(path.read_bytes())
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
        if not isinstance(payload, dict):
            raise BackupError("BLOCKED", f"malformed tx {rel}")
        tid = _tenant_of(payload)
        if tid is None:
            raise BackupError("BLOCKED", f"ambiguous tx tenant {rel}")
        if tid not in tids:
            return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if tids and rel in MIXED_SPEC:
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
            try:
                before = _relevant_fingerprint(root, tids)
                sources = _source_files(root)
            except FileNotFoundError:
                last_error = "source path-set or hash changed during snapshot"
                continue
            if data_root.exists():
                shutil.rmtree(data_root)
            data_root.mkdir(parents=True, exist_ok=True)
            files: list[dict[str, Any]] = []
            seen: set[str] = set()
            vanished = False
            for src in sources:
                if not src.exists():
                    vanished = True
                    break
                try:
                    row = _copy_one(src, root, data_root, tids)
                except FileNotFoundError:
                    vanished = True
                    break
                if row is None:
                    continue
                if row["path"] in seen:
                    raise BackupError("BLOCKED", f"duplicate path {row['path']}")
                seen.add(row["path"])
                files.append(row)
            if vanished:
                last_error = "source path-set or hash changed during snapshot"
                continue
            try:
                after = _relevant_fingerprint(root, tids)
            except FileNotFoundError:
                last_error = "source path-set or hash changed during snapshot"
                continue
            if before != after:
                last_error = "source path-set or hash changed during snapshot"
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
                "snapshotPathSetBound": True,
                "collectionPolicy": {
                    "TENANT_OWNED": "record.tenantId authoritative; missing tenantId fail-closed",
                    "TENANT_DERIVED": "pallet->carton, operation->workOrder, packet->release; cross-tenant fail-closed",
                    "GLOBAL_REFERENCE": "logistics.carrier_quotes",
                    "GLOBAL_REFERENCE_POLICY": GLOBAL_REFERENCE_POLICY,
                },
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


def _owned(items: Any, tenant_id: str) -> list[dict[str, Any]]:
    rows = items.values() if isinstance(items, dict) else list(items or [])
    return [r for r in rows if isinstance(r, dict) and r.get("tenantId") == tenant_id]


def _idem_count(mapping: Any, tenant_id: str) -> int:
    if not isinstance(mapping, dict):
        return 0
    return sum(1 for key in mapping if str(key).startswith(f"{tenant_id}::"))


def _file_count(root: Path, rel: str) -> int:
    path = Path(root) / rel
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for p in path.rglob("*") if p.is_file())


def _tx_count(root: Path, tenant_id: str) -> int:
    tx_root = Path(root) / "tx"
    if not tx_root.exists():
        return 0
    n = 0
    for path in tx_root.glob("*.json"):
        rec = read_json(path) or {}
        if isinstance(rec, dict) and rec.get("tenantId") == tenant_id:
            n += 1
    return n


def tenant_domain_counts(plat: Any, tenant_id: str) -> dict[str, int]:
    pilot = plat.pilot
    release_ids = {r["releaseId"] for r in _owned(pilot.releases.releases, tenant_id) if r.get("releaseId")}
    wo_ids = {w["workOrderId"] for w in _owned(pilot.workorders.orders, tenant_id) if w.get("workOrderId")}
    packets = [k for k in (pilot.releases.packets or {}) if k in release_ids]
    ops = [
        o
        for o in (pilot.workorders.operations or [])
        if isinstance(o, dict) and str(o.get("workOrderId") or "") in wo_ids
    ]
    remnants = [r for r in (plat.remnants.items or {}).values() if r.get("tenantId") == tenant_id]
    return {
        "materialLots": len(plat.lots.list(tenant_id=tenant_id)),
        "remnants": len(remnants),
        "releases": len(release_ids),
        "packets": len(packets),
        "idempotency": (
            _idem_count(pilot.workorders._idem, tenant_id)
            + _idem_count(pilot.releases._idem, tenant_id)
            + _idem_count(pilot.logistics._idem, tenant_id)
            + _idem_count(pilot.receiving._idem, tenant_id)
            + _idem_count(pilot.cyclecounts._idem, tenant_id)
        ),
        "workOrders": len(wo_ids),
        "operations": len(ops),
        "receipts": len(_owned(pilot.receiving.receipts, tenant_id)),
        "stations": len(pilot.stations.list(tenant_id=tenant_id)),
        "leases": len(_owned(pilot.dispatcher.leases, tenant_id)),
        "operators": len(_owned(pilot.identity.operators, tenant_id)),
        "shifts": len(_owned(pilot.identity.shifts, tenant_id)),
        "cycleCounts": len(_owned(pilot.cyclecounts.counts, tenant_id)),
        "cartons": len(_owned(pilot.logistics.cartons, tenant_id)),
        "palletPlans": len(
            [
                p
                for p in (pilot.logistics.pallets or {}).values()
                if isinstance(p, dict)
                and (
                    p.get("tenantId") == tenant_id
                    or set(_pallet_carton_ids(p)) <= {c["cartonId"] for c in _owned(pilot.logistics.cartons, tenant_id)}
                    and bool(_pallet_carton_ids(p))
                )
            ]
        ),
        "shipments": len(_owned(pilot.logistics.shipments, tenant_id)),
        "checklists": len(_owned(pilot.logistics.checklists, tenant_id)),
        "handoffs": len(_owned(pilot.logistics.handoffs, tenant_id)),
        "qc": len(_owned(pilot.qc.checks, tenant_id)) + len(_owned(pilot.qc.defects, tenant_id)),
        "exceptions": len(_owned(pilot.inbox.items, tenant_id)),
        "journal": len(pilot.journal.list(tenant_id)),
        "outbox": _tx_count(plat.root, tenant_id),
        "dam": _file_count(plat.root, f"dam/{tenant_id}"),
    }


def evaluate_tenant_restore_matrix(
    *,
    live: Any,
    restored: Any,
    tenant_a: str,
    tenant_b: str,
    live_event_ids: set[str] | None = None,
) -> dict[str, Any]:
    live_a = tenant_domain_counts(live, tenant_a)
    restored_a = tenant_domain_counts(restored, tenant_a)
    restored_b = tenant_domain_counts(restored, tenant_b)
    quotes = list((restored.pilot.logistics.carrier_quotes or {}).values())
    leakage = {k: restored_b[k] for k in TENANT_MATRIX_DOMAINS if restored_b[k]}
    missing = []
    for key in TENANT_MATRIX_DOMAINS:
        if key == "outbox":
            if restored_a[key] != live_a[key]:
                missing.append(key)
            continue
        if live_a[key] <= 0:
            missing.append(f"{key}:empty-live")
            continue
        if key == "journal":
            live_ids = live_event_ids
            if live_ids is None:
                live_ids = {e.get("eventId") for e in live.pilot.journal.list(tenant_a) if e.get("eventId")}
            restored_ids = {e.get("eventId") for e in restored.pilot.journal.list(tenant_a) if e.get("eventId")}
            if not live_ids or not live_ids <= restored_ids:
                missing.append("journal")
            continue
        if restored_a[key] < live_a[key]:
            missing.append(key)
    return {
        "domains": {
            key: {"liveA": live_a[key], "restoredA": restored_a[key], "restoredB": restored_b[key]}
            for key in TENANT_MATRIX_DOMAINS
        },
        "tenantLeakageAbsent": not leakage and quotes == [],
        "tenantRequiredStatePreserved": not missing,
        "leakage": leakage,
        "missing": missing,
        "carrierQuotesPolicy": GLOBAL_REFERENCE_POLICY,
        "truthLabel": "REAL_LOGIC",
    }
