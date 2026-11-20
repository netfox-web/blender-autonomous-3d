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
from fox3d.logistics import (
    CARRIER_QUOTE_RECORD_REMEDIATION,
    carrier_quote_id,
    classify_carrier_quote,
    is_explicit_global_carrier_quote,
    is_valid_tenant_carrier_quote,
    scan_carrier_quote_records,
)
from fox3d.release import (
    is_matching_tenant_stem,
    legacy_safe_tenant_filename,
    safe_tenant_filename,
)
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
    "portfolio",
    "prototype",
    "pilot_batch",
)
VOLATILE_SUFFIXES = {".lock", ".tmp", ".staging"}
TENANT_OWNED = "TENANT_OWNED"
TENANT_DERIVED = "TENANT_DERIVED"
GLOBAL_REFERENCE = "GLOBAL_REFERENCE"
GLOBAL_REFERENCE_POLICY = "EXCLUDE_FROM_TENANT_SCOPED"
CARRIER_QUOTES_POLICY = (
    "tenant carrier_quotes are TENANT_OWNED; explicit global quotes excluded (EXCLUDE_FROM_TENANT_SCOPED); "
    "legacy tenantless quotes fail-closed"
)
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
        "carrier_quotes": TENANT_OWNED,
        "checklists": TENANT_OWNED,
        "handoffs": TENANT_OWNED,
    },
    "qc/qc.json": {"checks": TENANT_OWNED, "defects": TENANT_OWNED},
    "exceptions/exceptions.json": {"items": TENANT_OWNED},
    "releases/releases.json": {"releases": TENANT_OWNED},
    "portfolio/portfolio.json": {
        "intents": TENANT_OWNED,
        "candidates": TENANT_OWNED,
        "rankings": TENANT_OWNED,
        "approvals": TENANT_OWNED,
        "plans": TENANT_OWNED,
    },
    "prototype/prototype.json": {
        "selections": TENANT_OWNED,
        "units": TENANT_OWNED,
        "measurements": TENANT_OWNED,
        "ecos": TENANT_OWNED,
        "costs": TENANT_OWNED,
        "checklists": TENANT_OWNED,
        "decisions": TENANT_OWNED,
        "inventoryIntents": TENANT_OWNED,
        "packages": TENANT_OWNED,
        "launchDecisions": TENANT_OWNED,
        "pilotPlans": TENANT_OWNED,
        "labor": TENANT_OWNED,
    },
    "pilot_batch/pilot_batch.json": {
        "batches": TENANT_OWNED,
        "units": TENANT_OWNED,
        "cartons": TENANT_OWNED,
        "costs": TENANT_OWNED,
        "ncrs": TENANT_OWNED,
        "decisions": TENANT_OWNED,
        "qc": TENANT_OWNED,
        "labor": TENANT_OWNED,
    },
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
    "carrierQuotes",
    "checklists",
    "handoffs",
    "qc",
    "exceptions",
    "journal",
    "outbox",
    "dam",
    "portfolioIntents",
    "portfolioCandidates",
    "portfolioRankings",
    "portfolioApprovals",
    "portfolioPlans",
    "prototypeSelections",
    "prototypeUnits",
    "prototypeMeasurements",
    "prototypeEcos",
    "prototypeCosts",
    "prototypeChecklists",
    "prototypeDecisions",
    "prototypeInventoryIntents",
    "prototypePackages",
    "prototypeLaunchDecisions",
    "prototypePilotPlans",
    "prototypeLabor",
    "pilotBatches",
    "pilotBatchUnits",
    "pilotBatchCartons",
    "pilotBatchDecisions",
    "pilotBatchNcrs",
    "pilotBatchCosts",
)
OPTIONAL_EMPTY_DOMAINS = frozenset(
    {
        "carrierQuotes",
        "outbox",
        "portfolioIntents",
        "portfolioCandidates",
        "portfolioRankings",
        "portfolioApprovals",
        "portfolioPlans",
        "prototypeSelections",
        "prototypeUnits",
        "prototypeMeasurements",
        "prototypeEcos",
        "prototypeCosts",
        "prototypeChecklists",
        "prototypeDecisions",
        "prototypeInventoryIntents",
        "prototypePackages",
        "prototypeLaunchDecisions",
        "prototypePilotPlans",
        "prototypeLabor",
        "pilotBatches",
        "pilotBatchUnits",
        "pilotBatchCartons",
        "pilotBatchDecisions",
        "pilotBatchNcrs",
        "pilotBatchCosts",
    }
)


class BackupError(PermissionError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.status = "BLOCKED"


def _now() -> str:
    return utcnow().isoformat()


def _safe_tenant(tenant_id: str) -> str:
    return safe_tenant_filename(tenant_id)


def _legacy_safe_tenant(tenant_id: str) -> str:
    return legacy_safe_tenant_filename(tenant_id)


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
    if not isinstance(val, str) or not val.strip():
        return None
    return val


def _is_explicit_global_carrier_quote(rec: dict[str, Any]) -> bool:
    return is_explicit_global_carrier_quote(rec)


def _quote_id_of(rec: dict[str, Any]) -> str:
    return carrier_quote_id(rec)


def _block_carrier_quote_record_anomalies(rows: list[Any], rel: str, key: str) -> None:
    """Fail closed on raw entries LogisticsService quarantines (same rule as preflight / readiness)."""
    anomalies = scan_carrier_quote_records(rows)["anomalies"]
    if not anomalies:
        return
    first = anomalies[0]
    if first["reason"] == "duplicate_quote_id":
        detail = f"duplicate quoteId={first['quoteId']} ({first['duplicateCount']} records)"
    else:
        detail = f"non-object record at rawIndex={first['rawIndex']}"
    raise BackupError(
        "BLOCKED",
        f"ambiguous {rel}:{key} {detail}; {len(anomalies)} unresolved raw record(s); "
        f"{CARRIER_QUOTE_RECORD_REMEDIATION}",
    )


def _filter_idem(idem: Any, tids: set[str]) -> dict[str, Any]:
    if not isinstance(idem, dict):
        raise BackupError("BLOCKED", "malformed idem container")
    out: dict[str, Any] = {}
    for key, value in idem.items():
        if any(str(key).startswith(f"{tid}::") for tid in tids):
            out[key] = value
    return out


def _pallet_carton_ids(rec: dict[str, Any]) -> list[str]:
    ids = [str(x) for x in (rec.get("cartonIds") or [])]
    for pal in rec.get("pallets") or []:
        if isinstance(pal, dict):
            ids.extend(str(x) for x in (pal.get("cartonIds") or []))
    return ids


def _require_list(payload: dict[str, Any], rel: str, key: str) -> list[Any] | None:
    if key not in payload:
        return None
    rows = payload[key]
    if not isinstance(rows, list):
        raise BackupError("BLOCKED", f"malformed {rel}:{key} expected list")
    return rows


def _parent_tenants(payload: dict[str, Any], rel: str, key: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if rel == "logistics/logistics.json" and key == "pallets":
        parent_key, id_key = "cartons", "cartonId"
    elif rel == "workorders/workorders.json" and key == "operations":
        parent_key, id_key = "orders", "workOrderId"
    else:
        return out
    rows = _require_list(payload, rel, parent_key)
    if rows is None:
        return out
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
        rows = _require_list(payload, rel, key)
        if rows is None:
            continue
        if policy == GLOBAL_REFERENCE:
            filtered[key] = []
            continue
        kept: list[dict[str, Any]] = []
        parents = _parent_tenants(payload, rel, key) if policy == TENANT_DERIVED else {}
        if rel == "logistics/logistics.json" and key == "carrier_quotes":
            _block_carrier_quote_record_anomalies(rows, rel, key)
        for rec in rows:
            if not isinstance(rec, dict):
                raise BackupError("BLOCKED", f"ambiguous non-object in {rel}:{key}")
            if policy == TENANT_OWNED:
                if rel == "logistics/logistics.json" and key == "carrier_quotes":
                    info = classify_carrier_quote(rec)
                    if info["explicitGlobal"]:
                        continue
                    qid = _quote_id_of(rec)
                    if not info["validTenantOwned"]:
                        if info["issue"] in {
                            "conflicting_tenant_and_global",
                            "conflicting_ownership_and_global",
                            "unmigrated_global_reference",
                            "invalid_ownership",
                        }:
                            raise BackupError(
                                "BLOCKED",
                                f"ambiguous {rel}:{key} quoteId={qid} global flag or unmigrated/rolled-back "
                                "GLOBAL_REFERENCE ownership with missing or conflicting tenantId; "
                                "run migrate_tenantless_carrier_quotes (scripts/migrate_carrier_quotes.py) first",
                            )
                        raise BackupError(
                            "BLOCKED",
                            f"ambiguous {rel}:{key} quoteId={qid} missing tenantId; "
                            "run migrate_tenantless_carrier_quotes (scripts/migrate_carrier_quotes.py) first",
                        )
                    tid = info["tenantId"]
                    if tid in tids:
                        kept.append(rec)
                    continue
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
        release_rows = _require_list(filtered, rel, "releases") or []
        kept_ids = {str(r.get("releaseId")) for r in release_rows if isinstance(r, dict) and r.get("releaseId")}
        source_rows = _require_list(payload, rel, "releases") or []
        all_ids = {str(r.get("releaseId")) for r in source_rows if isinstance(r, dict) and r.get("releaseId")}
        if "packets" in payload:
            packets = payload["packets"]
            if not isinstance(packets, dict):
                raise BackupError("BLOCKED", "malformed packets payload")
            out_packets: dict[str, Any] = {}
            for pkt_id, value in packets.items():
                if pkt_id not in all_ids:
                    raise BackupError("BLOCKED", f"ambiguous packet parent {pkt_id}")
                if pkt_id in kept_ids:
                    out_packets[pkt_id] = value
            filtered["packets"] = out_packets
    if "idem" in payload:
        filtered["idem"] = _filter_idem(payload["idem"], tids)
    return filtered


def _include_file(rel: str, tids: set[str] | None) -> bool:
    if not tids:
        return True
    parts = rel.split("/")
    if parts[0] in {"journal", "remnants"} and len(parts) >= 2:
        if len(parts) != 2 or not parts[1].endswith(".json"):
            return True
        stem_lower = Path(parts[1]).stem.lower()
        allowed = {
            _safe_tenant(t).lower() for t in tids
        } | {
            _legacy_safe_tenant(t).lower() for t in tids
        }
        return stem_lower in allowed
    if parts[0] == "dam" and len(parts) >= 2:
        return parts[1] in tids
    if parts[0] == "tx":
        return True
    return True


def _has_canonical_store_file(root: Path, store_dir: str, tid: str) -> bool:
    canonical = root / store_dir / f"{_safe_tenant(tid)}.json"
    if not canonical.exists():
        return False
    try:
        raw = read_json(canonical)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False
    return raw.get("tenantId") == tid


def _inspect_tenant_store_file(
    src: Path, root: Path, rel: str, tids: set[str]
) -> tuple[str, dict[str, Any] | None]:
    parts = rel.split("/")
    if len(parts) != 2 or not parts[1].endswith(".json"):
        raise BackupError("BLOCKED", f"unexpected file in tenant store: {rel}")
    try:
        payload = read_json(src)
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("BLOCKED", f"malformed {rel}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BackupError("BLOCKED", f"malformed {rel}: expected object")

    if parts[0] == "journal":
        raw_tid = payload.get("tenantId")
        if not isinstance(raw_tid, str) or not raw_tid.strip():
            raise BackupError("BLOCKED", f"ambiguous journal tenant {rel}: missing tenantId")
        header_tid = raw_tid
        if not is_matching_tenant_stem(header_tid, src.stem):
            raise BackupError(
                "BLOCKED",
                f"ambiguous journal tenant {rel}: tenantId {header_tid!r} mismatches filename",
            )
        events = payload.get("events")
        if not isinstance(events, list):
            raise BackupError("BLOCKED", f"malformed {rel}:events expected list")
        for ev in events:
            if not isinstance(ev, dict):
                raise BackupError("BLOCKED", f"malformed journal event in {rel}")
            ev_tid = _tenant_of(ev)
            if not isinstance(ev_tid, str) or not ev_tid.strip():
                raise BackupError("BLOCKED", f"ambiguous {rel}:events missing tenantId")
            if ev_tid != header_tid:
                raise BackupError("BLOCKED", f"mixed tenant journal {rel}")
        if header_tid not in tids:
            return ("EXCLUDE", None)
        canonical = root / "journal" / f"{_safe_tenant(header_tid)}.json"
        if src != canonical and _has_canonical_store_file(root, "journal", header_tid):
            return ("EXCLUDE", None)
        return ("RAW", None)

    rows = _require_list(payload, rel, "items")
    if rows is None:
        raise BackupError("BLOCKED", f"malformed {rel}:items expected list")
    raw_tid = payload.get("tenantId")
    header_tid_opt: str | None = None
    if "tenantId" in payload and raw_tid is not None:
        if not isinstance(raw_tid, str) or not raw_tid.strip():
            raise BackupError("BLOCKED", f"ambiguous remnants tenant {rel}: invalid tenantId")
        if not is_matching_tenant_stem(raw_tid, src.stem):
            raise BackupError(
                "BLOCKED",
                f"ambiguous remnants tenant {rel}: tenantId {raw_tid!r} mismatches filename",
            )
        header_tid_opt = raw_tid
    item_tids: set[str] = set()
    for rec in rows:
        if not isinstance(rec, dict):
            raise BackupError("BLOCKED", f"ambiguous non-object in {rel}:items")
        rec_tid = _tenant_of(rec)
        if not isinstance(rec_tid, str) or not rec_tid.strip():
            raise BackupError("BLOCKED", f"ambiguous {rel}:items missing tenantId")
        if not is_matching_tenant_stem(rec_tid, src.stem):
            raise BackupError(
                "BLOCKED",
                f"ambiguous {rel}:items tenantId {rec_tid!r} mismatches filename",
            )
        item_tids.add(rec_tid)
    if not rows:
        if header_tid_opt is None:
            raise BackupError("BLOCKED", f"ambiguous empty remnants {rel}: missing tenantId")
        if header_tid_opt not in tids:
            return ("EXCLUDE", None)
        canonical = root / "remnants" / f"{_safe_tenant(header_tid_opt)}.json"
        if src != canonical and _has_canonical_store_file(root, "remnants", header_tid_opt):
            return ("EXCLUDE", None)
        return ("RAW", None)
    if header_tid_opt is not None and src.stem == _safe_tenant(header_tid_opt):
        if item_tids != {header_tid_opt}:
            raise BackupError("BLOCKED", f"mixed tenant in canonical remnants {rel}")
        if header_tid_opt not in tids:
            return ("EXCLUDE", None)
        return ("RAW", None)
    if header_tid_opt is None:
        raise BackupError("BLOCKED", f"ambiguous remnants {rel}: missing header tenantId")
    if len(item_tids) == 1 and item_tids == {header_tid_opt}:
        if header_tid_opt not in tids:
            return ("EXCLUDE", None)
        canonical = root / "remnants" / f"{_safe_tenant(header_tid_opt)}.json"
        if src != canonical and _has_canonical_store_file(root, "remnants", header_tid_opt):
            return ("EXCLUDE", None)
        return ("RAW", None)
    active_legacy_tids = {
        t for t in tids if not _has_canonical_store_file(root, "remnants", t)
    }
    kept = [rec for rec in rows if _tenant_of(rec) in active_legacy_tids]
    if not kept:
        return ("EXCLUDE", None)
    kept_tids = {str(_tenant_of(rec)) for rec in kept}
    if len(kept_tids) > 1:
        raise BackupError("BLOCKED", f"mixed legacy remnants {rel} spans multiple requested tenants")
    kept_tid = next(iter(kept_tids))
    filtered = {
        **payload,
        "tenantId": kept_tid,
        "kind": payload.get("kind") or "remnant-store",
        "count": len(kept),
        "items": kept,
    }
    return ("FILTERED", filtered)


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
        if tids and rel.startswith(("journal/", "remnants/")):
            mode, filtered_store = _inspect_tenant_store_file(path, root, rel, tids)
            if mode == "EXCLUDE":
                continue
            if mode == "FILTERED" and filtered_store is not None:
                out[rel] = _payload_fingerprint(filtered_store)
                continue
            out[rel] = sha256_bytes(path.read_bytes())
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
    if tids and rel.startswith(("journal/", "remnants/")):
        mode, filtered_store = _inspect_tenant_store_file(src, root, rel, tids)
        if mode == "EXCLUDE":
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "FILTERED" and filtered_store is not None:
            atomic_write_json(target, filtered_store)
        else:
            shutil.copy2(src, target)
        blob = target.read_bytes()
        return {"path": rel, "sha256": sha256_bytes(blob), "size": len(blob)}
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
    if tenant_ids is not None:
        for raw_t in tenant_ids:
            if not isinstance(raw_t, str) or (raw_t != "" and not raw_t.strip()):
                raise BackupError("BLOCKED", "invalid tenantId in tenant_ids")
        if any(raw_t == "" for raw_t in tenant_ids):
            raise BackupError("BLOCKED", "empty tenantId in tenant_ids")
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
                    "TENANT_OWNED": "record.tenantId authoritative (including logistics.carrier_quotes); missing tenantId fail-closed",
                    "TENANT_DERIVED": "pallet->carton, operation->workOrder, packet->release; cross-tenant fail-closed",
                    "CARRIER_QUOTES": CARRIER_QUOTES_POLICY,
                    "GLOBAL_REFERENCE": "explicit global quotes only (globalQuote/isGlobal/allowGlobal without tenantId); excluded from tenant-scoped backups; legacy tenantless quotes fail-closed",
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


def _entry(rows: list[dict[str, Any]], id_key: str) -> dict[str, Any]:
    ids = sorted(str(r.get(id_key)) for r in rows if r.get(id_key) is not None)
    return {"ids": ids, "count": len(rows), "digest": stable_hash(rows)}


def _idem_entries(mapping: Any, tenant_id: str) -> list[dict[str, Any]]:
    if not isinstance(mapping, dict):
        return []
    rows = [{"key": str(key), "ref": value} for key, value in mapping.items() if str(key).startswith(f"{tenant_id}::")]
    return sorted(rows, key=lambda r: r["key"])


def _dam_entries(root: Path, tenant_id: str) -> list[dict[str, Any]]:
    base = Path(root) / "dam" / tenant_id
    rows: list[dict[str, Any]] = []
    if not base.exists():
        return rows
    for path in sorted(p for p in base.rglob("*") if p.is_file() and not _is_volatile(p)):
        rel = _validate_rel(path.relative_to(Path(root)).as_posix())
        rows.append({"path": rel, "sha256": sha256_bytes(path.read_bytes())})
    return rows


def _tx_entries(root: Path, tenant_id: str) -> list[dict[str, Any]]:
    tx_root = Path(root) / "tx"
    rows: list[dict[str, Any]] = []
    if not tx_root.exists():
        return rows
    for path in sorted(tx_root.glob("*.json")):
        rec = read_json(path) or {}
        if isinstance(rec, dict) and rec.get("tenantId") == tenant_id:
            rows.append({"path": path.name, "txId": rec.get("txId"), "sha256": sha256_bytes(path.read_bytes())})
    return rows


def _a_pallets(pilot: Any, tenant_id: str) -> list[dict[str, Any]]:
    carton_ids = {c["cartonId"] for c in _owned(pilot.logistics.cartons, tenant_id) if c.get("cartonId")}
    rows = []
    for pal in (pilot.logistics.pallets or {}).values():
        if not isinstance(pal, dict):
            continue
        ids = _pallet_carton_ids(pal)
        if pal.get("tenantId") == tenant_id or (ids and set(ids) <= carton_ids):
            rows.append(pal)
    return rows


def tenant_state_digest(plat: Any, tenant_id: str) -> dict[str, Any]:
    pilot = plat.pilot
    lots = []
    for lot in plat.lots.list(tenant_id=tenant_id):
        qty = plat.lots.quantities(lot["lotId"], tenant_id=tenant_id)
        lots.append(
            {
                "lotId": lot["lotId"],
                "material": lot.get("material"),
                "thickness": lot.get("thickness"),
                "available": qty.get("available"),
                "reserved": qty.get("reserved"),
                "consumed": qty.get("consumed"),
                "sheetCount": qty.get("sheetCount"),
                "quarantined": lot.get("quarantined"),
            }
        )
    remnants = [
        {
            "remnantId": r.get("remnantId"),
            "material": r.get("material"),
            "w": r.get("w"),
            "h": r.get("h"),
            "area": r.get("area"),
            "source": r.get("sourceNestingRun") or r.get("sourceRun"),
            "materialLotId": r.get("materialLotId"),
            "status": r.get("status"),
        }
        for r in (plat.remnants.items or {}).values()
        if r.get("tenantId") == tenant_id
    ]
    releases = [
        {
            "releaseId": r.get("releaseId"),
            "releaseHash": r.get("releaseHash"),
            "productVersion": r.get("productVersion"),
            "status": r.get("status"),
        }
        for r in _owned(pilot.releases.releases, tenant_id)
    ]
    release_ids = {str(r["releaseId"]) for r in releases if r.get("releaseId")}
    packets = []
    for rid, pkt in (pilot.releases.packets or {}).items():
        if rid not in release_ids:
            continue
        blob = json.dumps(pkt, sort_keys=True, default=str).encode()
        packets.append({"releaseId": rid, "sha256": sha256_bytes(blob), "size": len(blob)})
    work_orders = [
        {
            "workOrderId": w.get("workOrderId"),
            "releaseHash": w.get("releaseHash"),
            "state": w.get("state"),
            "traveler": [s.get("operation") for s in ((w.get("traveler") or {}).get("steps") or [])],
            "ops": sorted(
                [
                    {"opId": o.get("opId"), "operation": o.get("operation"), "status": o.get("status")}
                    for o in (w.get("ops") or [])
                    if isinstance(o, dict)
                ],
                key=lambda o: str(o.get("opId") or ""),
            ),
        }
        for w in _owned(pilot.workorders.orders, tenant_id)
    ]
    wo_ids = {str(w["workOrderId"]) for w in work_orders if w.get("workOrderId")}
    operations = [
        {
            "opId": o.get("opId"),
            "workOrderId": o.get("workOrderId"),
            "operation": o.get("operation"),
            "status": o.get("status"),
        }
        for o in (pilot.workorders.operations or [])
        if isinstance(o, dict) and str(o.get("workOrderId") or "") in wo_ids
    ]
    idem = (
        _idem_entries(pilot.workorders._idem, tenant_id)
        + _idem_entries(pilot.releases._idem, tenant_id)
        + _idem_entries(pilot.logistics._idem, tenant_id)
        + _idem_entries(pilot.receiving._idem, tenant_id)
        + _idem_entries(pilot.cyclecounts._idem, tenant_id)
    )
    journal_events = [e for e in pilot.journal.list(tenant_id) if e.get("eventId")]
    integrity = pilot.journal.verify(tenant_id)
    journal = {
        "ids": sorted(str(e["eventId"]) for e in journal_events),
        "sequence": integrity.get("sequence"),
        "headHash": integrity.get("headHash"),
        "ok": bool(integrity.get("ok") is True),
    }
    dam = _dam_entries(plat.root, tenant_id)
    tx = _tx_entries(plat.root, tenant_id)
    domains = {
        "materialLots": _entry(sorted(lots, key=lambda r: str(r["lotId"])), "lotId"),
        "remnants": _entry(sorted(remnants, key=lambda r: str(r.get("remnantId"))), "remnantId"),
        "releases": _entry(sorted(releases, key=lambda r: str(r.get("releaseId"))), "releaseId"),
        "packets": _entry(sorted(packets, key=lambda r: str(r.get("releaseId"))), "releaseId"),
        "idempotency": _entry(sorted(idem, key=lambda r: r["key"]), "key"),
        "workOrders": _entry(sorted(work_orders, key=lambda r: str(r.get("workOrderId"))), "workOrderId"),
        "operations": _entry(sorted(operations, key=lambda r: str(r.get("opId"))), "opId"),
        "receipts": _entry(
            sorted(
                [
                    {
                        "receiptId": r.get("receiptId"),
                        "status": r.get("status"),
                        "lotId": r.get("lotId"),
                        "quantity": r.get("quantity"),
                    }
                    for r in _owned(pilot.receiving.receipts, tenant_id)
                ],
                key=lambda r: str(r.get("receiptId")),
            ),
            "receiptId",
        ),
        "stations": _entry(
            sorted(
                [
                    {"stationId": s.get("stationId"), "status": s.get("status"), "capabilities": s.get("capabilities")}
                    for s in _owned(pilot.stations.stations, tenant_id)
                ],
                key=lambda r: str(r.get("stationId")),
            ),
            "stationId",
        ),
        "leases": _entry(
            sorted(
                [
                    {
                        "leaseId": l.get("leaseId"),
                        "workOrderId": l.get("workOrderId"),
                        "stationId": l.get("stationId"),
                        "status": l.get("status"),
                        "jobId": l.get("jobId"),
                    }
                    for l in _owned(pilot.dispatcher.leases, tenant_id)
                ],
                key=lambda r: str(r.get("leaseId")),
            ),
            "leaseId",
        ),
        "operators": _entry(
            sorted(
                [
                    {"operatorId": o.get("operatorId"), "enabled": o.get("enabled")}
                    for o in _owned(pilot.identity.operators, tenant_id)
                ],
                key=lambda r: str(r.get("operatorId")),
            ),
            "operatorId",
        ),
        "shifts": _entry(
            sorted(
                [
                    {"shiftId": s.get("shiftId"), "status": s.get("status"), "operatorId": s.get("operatorId")}
                    for s in _owned(pilot.identity.shifts, tenant_id)
                ],
                key=lambda r: str(r.get("shiftId")),
            ),
            "shiftId",
        ),
        "cycleCounts": _entry(
            sorted(
                [
                    {
                        "cycleCountId": c.get("cycleCountId"),
                        "lotId": c.get("lotId"),
                        "status": c.get("status"),
                        "counted": c.get("counted"),
                    }
                    for c in _owned(pilot.cyclecounts.counts, tenant_id)
                ],
                key=lambda r: str(r.get("cycleCountId")),
            ),
            "cycleCountId",
        ),
        "cartons": _entry(
            sorted(
                [
                    {
                        "cartonId": c.get("cartonId"),
                        "workOrderId": c.get("workOrderId"),
                        "releaseHash": c.get("releaseHash"),
                        "tenantId": c.get("tenantId"),
                    }
                    for c in _owned(pilot.logistics.cartons, tenant_id)
                ],
                key=lambda r: str(r.get("cartonId")),
            ),
            "cartonId",
        ),
        "palletPlans": _entry(
            sorted(
                [
                    {
                        "palletPlanId": p.get("palletPlanId"),
                        "cartonIds": _pallet_carton_ids(p),
                        "tenantId": p.get("tenantId"),
                    }
                    for p in _a_pallets(pilot, tenant_id)
                ],
                key=lambda r: str(r.get("palletPlanId")),
            ),
            "palletPlanId",
        ),
        "shipments": _entry(
            sorted(
                [
                    {
                        "shipmentId": s.get("shipmentId"),
                        "cartonIds": list(s.get("cartonIds") or []),
                        "status": s.get("status"),
                        "tenantId": s.get("tenantId"),
                    }
                    for s in _owned(pilot.logistics.shipments, tenant_id)
                ],
                key=lambda r: str(r.get("shipmentId")),
            ),
            "shipmentId",
        ),
        "carrierQuotes": _entry(
            sorted(
                [
                    {
                        "quoteId": q.get("quoteId"),
                        "carrier": q.get("carrier"),
                        "service": q.get("service"),
                        "charge": q.get("charge"),
                        "currency": q.get("currency"),
                        "dimDivisor": q.get("dimDivisor"),
                        "validUntil": q.get("validUntil"),
                        "quoteHash": q.get("quoteHash"),
                        "tenantId": q.get("tenantId"),
                    }
                    for q in _owned(pilot.logistics.carrier_quotes, tenant_id)
                ],
                key=lambda r: str(r.get("quoteId")),
            ),
            "quoteId",
        ),
        "checklists": _entry(
            sorted(
                [
                    {
                        "checklistId": c.get("checklistId"),
                        "workOrderId": c.get("workOrderId"),
                        "releaseHash": c.get("releaseHash"),
                    }
                    for c in _owned(pilot.logistics.checklists, tenant_id)
                ],
                key=lambda r: str(r.get("checklistId")),
            ),
            "checklistId",
        ),
        "handoffs": _entry(
            sorted(
                [
                    {"handoffId": h.get("handoffId"), "shipmentId": h.get("shipmentId"), "tenantId": h.get("tenantId")}
                    for h in _owned(pilot.logistics.handoffs, tenant_id)
                ],
                key=lambda r: str(r.get("handoffId")),
            ),
            "handoffId",
        ),
        "qc": _entry(
            sorted(
                [
                    {"id": c.get("qcId"), "workOrderId": c.get("workOrderId"), "kind": "check"}
                    for c in _owned(pilot.qc.checks, tenant_id)
                ]
                + [
                    {"id": d.get("defectId"), "workOrderId": d.get("workOrderId"), "kind": "defect"}
                    for d in _owned(pilot.qc.defects, tenant_id)
                ],
                key=lambda r: str(r.get("id")),
            ),
            "id",
        ),
        "exceptions": _entry(
            sorted(
                [
                    {
                        "exceptionId": e.get("exceptionId"),
                        "workOrderId": e.get("workOrderId"),
                        "errorCode": e.get("errorCode"),
                        "releaseHash": e.get("releaseHash"),
                    }
                    for e in _owned(pilot.inbox.items, tenant_id)
                ],
                key=lambda r: str(r.get("exceptionId")),
            ),
            "exceptionId",
        ),
        "journal": {"ids": journal["ids"], "count": len(journal["ids"]), "digest": stable_hash(journal)},
        "outbox": _entry(tx, "path"),
        "dam": _entry(dam, "path"),
        "portfolioIntents": _entry(
            sorted(
                [
                    {"portfolioId": r.get("portfolioId"), "intentHash": r.get("intentHash")}
                    for r in _owned(getattr(getattr(plat, "portfolio", None), "intents", {}), tenant_id)
                ],
                key=lambda r: str(r.get("portfolioId")),
            ),
            "portfolioId",
        ),
        "portfolioCandidates": _entry(
            sorted(
                [
                    {
                        "candidateId": r.get("candidateId"),
                        "canonicalHash": r.get("canonicalHash"),
                        "state": r.get("state"),
                        "engineeringHash": r.get("engineeringHash"),
                    }
                    for r in _owned(getattr(getattr(plat, "portfolio", None), "candidates", {}), tenant_id)
                ],
                key=lambda r: str(r.get("candidateId")),
            ),
            "candidateId",
        ),
        "portfolioRankings": _entry(
            sorted(
                [
                    {"rankingId": r.get("rankingId"), "rankingPolicyHash": r.get("rankingPolicyHash")}
                    for r in _owned(getattr(getattr(plat, "portfolio", None), "rankings", {}), tenant_id)
                ],
                key=lambda r: str(r.get("rankingId")),
            ),
            "rankingId",
        ),
        "portfolioApprovals": _entry(
            sorted(
                [
                    {"approvalId": r.get("approvalId"), "status": r.get("status"), "candidateId": r.get("candidateId")}
                    for r in _owned(getattr(getattr(plat, "portfolio", None), "approvals", {}), tenant_id)
                ],
                key=lambda r: str(r.get("approvalId")),
            ),
            "approvalId",
        ),
        "portfolioPlans": _entry(
            sorted(
                [
                    {"planId": r.get("planId"), "planHash": r.get("planHash")}
                    for r in _owned(getattr(getattr(plat, "portfolio", None), "plans", {}), tenant_id)
                ],
                key=lambda r: str(r.get("planId")),
            ),
            "planId",
        ),
        "prototypeSelections": _entry(
            sorted(
                [
                    {
                        "selectionId": r.get("selectionId"),
                        "candidateId": r.get("candidateId"),
                        "engineeringHash": r.get("engineeringHash"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "selections", {}), tenant_id)
                ],
                key=lambda r: str(r.get("selectionId")),
            ),
            "selectionId",
        ),
        "prototypeUnits": _entry(
            sorted(
                [
                    {
                        "prototypeUnitId": r.get("prototypeUnitId"),
                        "engineeringHash": r.get("engineeringHash"),
                        "state": r.get("state"),
                        "consumesInventory": r.get("consumesInventory"),
                        "inventoryLineage": r.get("inventoryLineage"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "units", {}), tenant_id)
                ],
                key=lambda r: str(r.get("prototypeUnitId")),
            ),
            "prototypeUnitId",
        ),
        "prototypeMeasurements": _entry(
            sorted(
                [
                    {
                        "measurementId": r.get("measurementId"),
                        "prototypeUnitId": r.get("prototypeUnitId"),
                        "engineeringHash": r.get("engineeringHash"),
                        "toleranceOk": (r.get("tolerance") or {}).get("ok"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "measurements", {}), tenant_id)
                ],
                key=lambda r: str(r.get("measurementId")),
            ),
            "measurementId",
        ),
        "prototypeEcos": _entry(
            sorted(
                [
                    {
                        "ecoId": r.get("ecoId"),
                        "fromEngineeringHash": r.get("fromEngineeringHash"),
                        "toEngineeringHash": r.get("toEngineeringHash"),
                        "status": r.get("status"),
                        "fieldChanges": r.get("fieldChanges"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "ecos", {}), tenant_id)
                ],
                key=lambda r: str(r.get("ecoId")),
            ),
            "ecoId",
        ),
        "prototypeCosts": _entry(
            sorted(
                [
                    {
                        "costId": r.get("costId"),
                        "prototypeUnitId": r.get("prototypeUnitId"),
                        "costSnapshotHash": r.get("costSnapshotHash"),
                        "completeness": r.get("completeness"),
                        "monetaryTotal": r.get("monetaryTotal"),
                        "packagingQty": (r.get("quantityLineage") or {}).get("packagingQty")
                        if isinstance(r.get("quantityLineage"), dict)
                        else None,
                        "packagingChecklistId": (r.get("quantityLineage") or {}).get("packagingChecklistId")
                        if isinstance(r.get("quantityLineage"), dict)
                        else None,
                        "laborIds": ((r.get("quantityLineage") or {}).get("laborLineage") or {}).get("laborIds")
                        if isinstance(r.get("quantityLineage"), dict)
                        else None,
                        "laborSemanticKeys": ((r.get("quantityLineage") or {}).get("laborLineage") or {}).get("semanticKeys")
                        if isinstance(r.get("quantityLineage"), dict)
                        else None,
                        "quantitySources": (r.get("quantityLineage") or {}).get("sources")
                        if isinstance(r.get("quantityLineage"), dict)
                        else None,
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "costs", {}), tenant_id)
                ],
                key=lambda r: str(r.get("costId")),
            ),
            "costId",
        ),
        "prototypeChecklists": _entry(
            sorted(
                [
                    {
                        "checklistId": r.get("checklistId"),
                        "tenantId": r.get("tenantId"),
                        "prototypeUnitId": r.get("prototypeUnitId"),
                        "engineeringHash": r.get("engineeringHash"),
                        "ok": r.get("ok"),
                        "volumetricWeightKg": r.get("volumetricWeightKg"),
                        "packagingQty": (r.get("observed") or {}).get("packagingQty")
                        if isinstance(r.get("observed"), dict)
                        else r.get("packagingQty"),
                        "source": r.get("source"),
                        "truthLabel": r.get("truthLabel"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "checklists", {}), tenant_id)
                ],
                key=lambda r: str(r.get("checklistId")),
            ),
            "checklistId",
        ),
        "prototypeDecisions": _entry(
            sorted(
                [
                    {"decisionId": r.get("decisionId"), "decision": r.get("decision"), "prototypeUnitId": r.get("prototypeUnitId")}
                    for r in _owned(getattr(getattr(plat, "prototype", None), "decisions", {}), tenant_id)
                ],
                key=lambda r: str(r.get("decisionId")),
            ),
            "decisionId",
        ),
        "prototypeInventoryIntents": _entry(
            sorted(
                [
                    {
                        "intentId": r.get("intentId"),
                        "prototypeUnitId": r.get("prototypeUnitId"),
                        "workOrderId": r.get("workOrderId"),
                        "status": r.get("status"),
                        "quantity": r.get("quantity"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "intents", {}), tenant_id)
                ],
                key=lambda r: str(r.get("intentId")),
            ),
            "intentId",
        ),
        "prototypePackages": _entry(
            sorted(
                [
                    {
                        "evidencePackageId": r.get("evidencePackageId"),
                        "prototypeUnitId": r.get("prototypeUnitId"),
                        "engineeringHash": r.get("engineeringHash"),
                        "evidenceSource": r.get("evidenceSource"),
                        "state": r.get("state"),
                        "revision": r.get("revision"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "packages", {}), tenant_id)
                ],
                key=lambda r: str(r.get("evidencePackageId")),
            ),
            "evidencePackageId",
        ),
        "prototypeLaunchDecisions": _entry(
            sorted(
                [
                    {
                        "launchDecisionId": r.get("launchDecisionId"),
                        "candidateId": r.get("candidateId"),
                        "decision": r.get("decision"),
                        "engineeringHash": r.get("engineeringHash"),
                        "evidencePackageId": r.get("evidencePackageId"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "launch_decisions", {}), tenant_id)
                ],
                key=lambda r: str(r.get("launchDecisionId")),
            ),
            "launchDecisionId",
        ),
        "prototypePilotPlans": _entry(
            sorted(
                [
                    {
                        "planId": r.get("planId"),
                        "candidateId": r.get("candidateId"),
                        "releaseId": r.get("releaseId"),
                        "workOrderId": r.get("workOrderId"),
                        "quantity": r.get("quantity"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "plans", {}), tenant_id)
                ],
                key=lambda r: str(r.get("planId")),
            ),
            "planId",
        ),
        "prototypeLabor": _entry(
            sorted(
                [
                    {
                        "laborId": r.get("laborId"),
                        "tenantId": r.get("tenantId"),
                        "prototypeUnitId": r.get("prototypeUnitId"),
                        "workOrderId": r.get("workOrderId"),
                        "minutes": r.get("minutes"),
                        "reason": r.get("reason"),
                        "engineeringHash": r.get("engineeringHash"),
                        "idempotencyKey": r.get("idempotencyKey"),
                        "source": r.get("source"),
                    }
                    for r in _owned(getattr(getattr(plat, "prototype", None), "labor", {}), tenant_id)
                ],
                key=lambda r: str(r.get("laborId")),
            ),
            "laborId",
        ),
        "pilotBatches": _entry(
            sorted(
                [
                    {
                        "batchId": r.get("batchId"),
                        "tenantId": r.get("tenantId"),
                        "candidateId": r.get("candidateId"),
                        "engineeringHash": r.get("engineeringHash"),
                        "requestedQuantity": r.get("requestedQuantity"),
                        "workOrderId": r.get("workOrderId"),
                        "releaseHash": r.get("releaseHash"),
                        "state": r.get("state"),
                        "source": r.get("source"),
                    }
                    for r in _owned(getattr(getattr(plat, "pilot_batch", None), "batches", {}), tenant_id)
                ],
                key=lambda r: str(r.get("batchId")),
            ),
            "batchId",
        ),
        "pilotBatchUnits": _entry(
            sorted(
                [
                    {
                        "unitExecutionId": r.get("unitExecutionId"),
                        "batchId": r.get("batchId"),
                        "engineeringHash": r.get("engineeringHash"),
                        "state": r.get("state"),
                        "consumedQuantity": r.get("consumedQuantity"),
                        "idempotencyKey": r.get("idempotencyKey"),
                    }
                    for r in _owned(getattr(getattr(plat, "pilot_batch", None), "units", {}), tenant_id)
                ],
                key=lambda r: str(r.get("unitExecutionId")),
            ),
            "unitExecutionId",
        ),
        "pilotBatchCartons": _entry(
            sorted(
                [
                    {
                        "cartonId": r.get("cartonId"),
                        "batchId": r.get("batchId"),
                        "unitExecutionIds": r.get("unitExecutionIds"),
                        "packagingQty": r.get("packagingQty"),
                        "checklistId": r.get("checklistId"),
                    }
                    for r in _owned(getattr(getattr(plat, "pilot_batch", None), "cartons", {}), tenant_id)
                ],
                key=lambda r: str(r.get("cartonId")),
            ),
            "cartonId",
        ),
        "pilotBatchDecisions": _entry(
            sorted(
                [
                    {
                        "decisionId": r.get("decisionId"),
                        "batchId": r.get("batchId"),
                        "decision": r.get("decision"),
                        "engineeringHash": r.get("engineeringHash"),
                    }
                    for r in _owned(getattr(getattr(plat, "pilot_batch", None), "decisions", {}), tenant_id)
                ],
                key=lambda r: str(r.get("decisionId")),
            ),
            "decisionId",
        ),
        "pilotBatchNcrs": _entry(
            sorted(
                [
                    {
                        "ncrId": r.get("ncrId"),
                        "batchId": r.get("batchId"),
                        "unitExecutionId": r.get("unitExecutionId"),
                        "category": r.get("category"),
                    }
                    for r in _owned(getattr(getattr(plat, "pilot_batch", None), "ncrs", {}), tenant_id)
                ],
                key=lambda r: str(r.get("ncrId")),
            ),
            "ncrId",
        ),
        "pilotBatchCosts": _entry(
            sorted(
                [
                    {
                        "costId": r.get("costId"),
                        "batchId": r.get("batchId"),
                        "completeness": r.get("completeness"),
                        "laborIds": ((r.get("quantityLineage") or {}).get("laborLineage") or {}).get("laborIds"),
                    }
                    for r in _owned(getattr(getattr(plat, "pilot_batch", None), "costs", {}), tenant_id)
                ],
                key=lambda r: str(r.get("costId")),
            ),
            "costId",
        ),
    }
    compact = {k: domains[k]["digest"] for k in TENANT_MATRIX_DOMAINS}
    return {**domains, "tenantStateDigest": stable_hash(compact)}


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
        "carrierQuotes": len(_owned(pilot.logistics.carrier_quotes, tenant_id)),
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
    live_state = tenant_state_digest(live, tenant_a)
    restored_state = tenant_state_digest(restored, tenant_a)
    restored_b = tenant_state_digest(restored, tenant_b)
    quotes = list((restored.pilot.logistics.carrier_quotes or {}).values())
    leaked_quotes = [
        q
        for q in quotes
        if not isinstance(q, dict)
        or not is_valid_tenant_carrier_quote(q)
        or _tenant_of(q) != tenant_a
        or _is_explicit_global_carrier_quote(q)
    ]
    leakage = {k: restored_b[k]["count"] for k in TENANT_MATRIX_DOMAINS if restored_b[k]["count"]}
    if leaked_quotes:
        leakage["carrierQuotes"] = max(leakage.get("carrierQuotes", 0), len(leaked_quotes))
    identity_mismatch = [
        key for key in TENANT_MATRIX_DOMAINS if live_state[key] != restored_state[key]
    ]
    missing = list(identity_mismatch)
    if live_event_ids:
        restored_ids = set(restored_state["journal"]["ids"])
        if not live_event_ids <= restored_ids:
            if "journal" not in identity_mismatch:
                identity_mismatch.append("journal")
                missing.append("journal")
    return {
        "domains": {
            key: {
                "liveA": live_state[key]["count"],
                "restoredA": restored_state[key]["count"],
                "restoredB": restored_b[key]["count"],
                "liveDigest": live_state[key]["digest"],
                "restoredDigest": restored_state[key]["digest"],
            }
            for key in TENANT_MATRIX_DOMAINS
        },
        "tenantStateDigest": {
            "liveA": live_state["tenantStateDigest"],
            "restoredA": restored_state["tenantStateDigest"],
            "equal": live_state["tenantStateDigest"] == restored_state["tenantStateDigest"],
        },
        "identityMismatch": identity_mismatch,
        "tenantLeakageAbsent": not leakage and not leaked_quotes,
        "tenantRequiredStatePreserved": not missing,
        "leakage": leakage,
        "missing": missing,
        "carrierQuotesPolicy": CARRIER_QUOTES_POLICY,
        "truthLabel": "REAL_LOGIC",
    }
