"""Packaging / logistics execution boundary. Planning logic, not a carrier."""

from __future__ import annotations

import argparse
from collections.abc import Collection, Mapping
import copy
from datetime import date
import json
import math
import re
import threading
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.journal import SemanticKeyConflictError, emit

ALLOWED_SOURCES = frozenset({"MANUAL", "IMPORTED"})
PALLET_MM = (1200.0, 1000.0)
PALLET_MAX_H = 1400.0
PALLET_MAX_KG = 500.0
DIM_DIVISOR = 6000.0
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now() -> str:
    return utcnow().isoformat()


def _parse_valid_until_date(raw: Any) -> date:
    """Parse and validate a strict ISO 8601 calendar date string (YYYY-MM-DD)."""
    if not isinstance(raw, str):
        raise ValueError("validUntil must be a YYYY-MM-DD date string")
    text = raw.strip()
    if not _ISO_DATE_RE.fullmatch(text):
        raise ValueError("validUntil must be in YYYY-MM-DD format")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("validUntil is not a valid calendar date") from exc


def _file_sig(path: Path) -> tuple[int, int, int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)


TENANT_OWNED_QUOTE = "TENANT_OWNED"
GLOBAL_REFERENCE_QUOTE = "GLOBAL_REFERENCE"


def carrier_quote_id(quote: Mapping[str, Any]) -> str:
    if not isinstance(quote, Mapping):
        return "<missing-quoteId>"
    raw = quote.get("quoteId")
    if raw is None:
        raw = quote.get("quote_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if raw not in (None, ""):
        return str(raw)
    return "<missing-quoteId>"


def is_explicit_global_carrier_quote(quote: dict[str, Any]) -> bool:
    """Return True only when a tenantless quote was explicitly marked as global without conflicting ownership."""
    if not isinstance(quote, dict):
        return False
    raw_tid = quote.get("tenantId")
    if isinstance(raw_tid, str) and raw_tid.strip():
        return False
    if raw_tid not in (None, ""):
        return False
    raw_legacy_tid = quote.get("tenant_id")
    if isinstance(raw_legacy_tid, str) and raw_legacy_tid.strip():
        return False
    if raw_legacy_tid not in (None, ""):
        return False
    if quote.get("ownership") not in (None, "", GLOBAL_REFERENCE_QUOTE):
        return False
    return bool(
        quote.get("globalQuote") is True
        or quote.get("isGlobal") is True
        or quote.get("allowGlobal") is True
    )


def _usable_tenant_id(raw: Any) -> str | None:
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            return text
    return None


def _tenant_field_present_but_invalid(raw: Any) -> bool:
    """True when a tenant field is present but not a usable id.

    None and "" mean the field is absent. Whitespace-only and non-strings are invalid.
    """
    if raw is None or raw == "":
        return False
    return _usable_tenant_id(raw) is None


def _claimed_tenant_ids(*cleaned: str | None) -> list[str]:
    claimed: list[str] = []
    for tid in cleaned:
        if tid is not None and tid not in claimed:
            claimed.append(tid)
    return claimed


def _raw_tenant_fields(quote: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the original tenant fields without choosing a winner."""
    raw: dict[str, Any] = {}
    if "tenantId" in quote:
        raw["tenantId"] = copy.deepcopy(quote["tenantId"])
    if "tenant_id" in quote:
        raw["tenant_id"] = copy.deepcopy(quote["tenant_id"])
    return raw


def tenant_field_repair_hint(quote_id: str, claimed_tenant_ids: list[str]) -> str:
    """Operator hint: batch migration must not rewrite conflicting or invalid tenant fields."""
    if claimed_tenant_ids:
        choices = ", ".join(f"--repair-tenant {quote_id}={tid}" for tid in claimed_tenant_ids)
        return (
            "conflicting or invalid tenant fields stay unresolved; "
            "batch --tenant, shipment inference, and --mark-global will not change them; "
            f"repair by choosing an original tenant with {choices}"
        )
    return (
        "invalid tenant fields stay unresolved; "
        "batch --tenant, shipment inference, and --mark-global will not change them; "
        f"repair explicitly with --repair-tenant {quote_id}=TENANT_ID or --repair-global {quote_id}"
    )


def _carrier_quote_class(
    *,
    status: str,
    issue: str | None,
    tenant_id: str | None,
    explicit_global: bool,
    valid_tenant_owned: bool,
    requires_migration: bool,
    metadata_conflict: bool,
    tenant_field_conflict: bool = False,
    claimed_tenant_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "issue": issue,
        "tenantId": tenant_id,
        "explicitGlobal": explicit_global,
        "validTenantOwned": valid_tenant_owned,
        "requiresMigration": requires_migration,
        "metadataConflict": metadata_conflict,
        "tenantFieldConflict": tenant_field_conflict,
        "claimedTenantIds": list(claimed_tenant_ids or []),
    }


_QUOTE_HASH_EXCLUDED = frozenset(
    {
        "quoteId",
        "quoteHash",
        "ownership",
        "globalQuote",
        "isGlobal",
        "allowGlobal",
        "migratedFromTenantless",
    }
)


def _quote_body_hash(updated: Mapping[str, Any]) -> str:
    return stable_hash({k: updated[k] for k in updated if k not in _QUOTE_HASH_EXCLUDED})


def _canonicalize_tenant_quote(quote: Mapping[str, Any], tenant_id: str) -> dict[str, Any]:
    updated = copy.deepcopy(dict(quote))
    updated["tenantId"] = tenant_id
    updated.pop("tenant_id", None)
    updated.pop("globalQuote", None)
    updated.pop("isGlobal", None)
    updated.pop("allowGlobal", None)
    updated.pop("migratedFromTenantless", None)
    updated["quoteHash"] = _quote_body_hash(updated)
    updated["ownership"] = TENANT_OWNED_QUOTE
    updated["globalQuote"] = False
    return updated


def _canonicalize_global_quote(quote: Mapping[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(dict(quote))
    updated.pop("tenantId", None)
    updated.pop("tenant_id", None)
    updated.pop("isGlobal", None)
    updated.pop("allowGlobal", None)
    updated.pop("migratedFromTenantless", None)
    updated["quoteHash"] = _quote_body_hash(updated)
    updated["ownership"] = GLOBAL_REFERENCE_QUOTE
    updated["globalQuote"] = True
    return updated


def classify_carrier_quote(quote: Any) -> dict[str, Any]:
    """Shared carrier_quote classification rule used by backup filtering, readiness, and migration preflight.

    Conflicting or invalid tenantId/tenant_id values do not resolve to a tenant. tenantId stays None and
    tenantFieldConflict is True so batch migration cannot treat the quote as unowned.
    """
    if not isinstance(quote, dict):
        return _carrier_quote_class(
            status="BLOCKED",
            issue="non_object",
            tenant_id=None,
            explicit_global=False,
            valid_tenant_owned=False,
            requires_migration=True,
            metadata_conflict=True,
        )
    if is_explicit_global_carrier_quote(quote):
        return _carrier_quote_class(
            status="EXPLICIT_GLOBAL",
            issue=None,
            tenant_id=None,
            explicit_global=True,
            valid_tenant_owned=False,
            requires_migration=False,
            metadata_conflict=False,
        )

    raw_tid = quote.get("tenantId")
    clean_tid = _usable_tenant_id(raw_tid)
    raw_legacy_tid = quote.get("tenant_id")
    clean_legacy_tid = _usable_tenant_id(raw_legacy_tid)
    invalid_tid = _tenant_field_present_but_invalid(raw_tid) or _tenant_field_present_but_invalid(raw_legacy_tid)
    mismatch_tid = clean_tid is not None and clean_legacy_tid is not None and clean_tid != clean_legacy_tid
    tenant_field_conflict = bool(invalid_tid or mismatch_tid)
    claimed = _claimed_tenant_ids(clean_tid, clean_legacy_tid)
    # Do not pick either side when the fields disagree or either field is unusable.
    eff_tid = None if tenant_field_conflict else (clean_tid or clean_legacy_tid)

    has_global_flag = bool(
        quote.get("globalQuote") is True
        or quote.get("isGlobal") is True
        or quote.get("allowGlobal") is True
    )
    ownership = quote.get("ownership")
    has_global_ownership = ownership == GLOBAL_REFERENCE_QUOTE
    invalid_ownership = ownership not in (None, "", TENANT_OWNED_QUOTE, GLOBAL_REFERENCE_QUOTE)

    if has_global_flag or has_global_ownership or invalid_ownership:
        if eff_tid is not None or tenant_field_conflict:
            issue = "conflicting_tenant_and_global"
            metadata_conflict = True
        elif has_global_flag:
            issue = "conflicting_ownership_and_global"
            metadata_conflict = True
        elif invalid_ownership:
            issue = "invalid_ownership"
            metadata_conflict = True
        else:
            issue = "unmigrated_global_reference"
            metadata_conflict = False
        return _carrier_quote_class(
            status="BLOCKED",
            issue=issue,
            tenant_id=eff_tid,
            explicit_global=False,
            valid_tenant_owned=False,
            requires_migration=True,
            metadata_conflict=metadata_conflict,
            tenant_field_conflict=tenant_field_conflict,
            claimed_tenant_ids=claimed,
        )

    if mismatch_tid:
        return _carrier_quote_class(
            status="BLOCKED",
            issue="conflicting_tenant_id",
            tenant_id=None,
            explicit_global=False,
            valid_tenant_owned=False,
            requires_migration=True,
            metadata_conflict=True,
            tenant_field_conflict=True,
            claimed_tenant_ids=claimed,
        )

    if eff_tid is None:
        return _carrier_quote_class(
            status="BLOCKED",
            issue="invalid_tenant_id" if invalid_tid else "missing_tenant_id",
            tenant_id=None,
            explicit_global=False,
            valid_tenant_owned=False,
            requires_migration=True,
            metadata_conflict=bool(invalid_tid),
            tenant_field_conflict=bool(invalid_tid),
            claimed_tenant_ids=claimed,
        )

    return _carrier_quote_class(
        status="TENANT_OWNED",
        issue=None,
        tenant_id=eff_tid,
        explicit_global=False,
        valid_tenant_owned=True,
        requires_migration=False,
        metadata_conflict=False,
        claimed_tenant_ids=claimed,
    )


def is_valid_tenant_carrier_quote(quote: dict[str, Any]) -> bool:
    """Return True only when a carrier quote has a valid tenantId and no conflicting global flags or ownership."""
    return bool(classify_carrier_quote(quote)["validTenantOwned"])


def is_tenantless_carrier_quote(
    quote: dict[str, Any],
    *,
    include_explicit_global: bool = False,
) -> bool:
    """Return True when a quote has missing or conflicting tenant/global metadata (or is explicitly global when requested)."""
    info = classify_carrier_quote(quote)
    if info["requiresMigration"]:
        return True
    if include_explicit_global and info["explicitGlobal"]:
        return True
    return False


CARRIER_QUOTE_RECORD_REMEDIATION = (
    "run scripts/migrate_carrier_quotes.py --check to list rawIndex/recordFingerprint, then "
    "--keep-duplicate QUOTE_ID=FINGERPRINT (duplicate quoteId) or --drop-invalid FINGERPRINT (non-object record)"
)


def carrier_quote_record_key(rec: Any, idx: int, taken: Collection[str] = ()) -> str:
    """Storage key used by LogisticsService.load(); records without quoteId get a unique placeholder key."""
    raw_qid = rec.get("quoteId") if isinstance(rec, dict) else None
    if isinstance(raw_qid, str) and raw_qid.strip():
        return raw_qid.strip()
    if raw_qid not in (None, ""):
        return str(raw_qid)
    return f"<missing-quoteId:{idx}>" if "<missing-quoteId>" in taken else "<missing-quoteId>"


def carrier_quote_record_fingerprint(rec: Any) -> str:
    """Content fingerprint that identifies one raw carrier_quotes entry independent of its list position."""
    return stable_hash({"record": rec})


def scan_carrier_quote_records(rows: Any) -> dict[str, Any]:
    """Shared raw-record rule for logistics.json carrier_quotes (load, preflight, migration, backup).

    Every entry that is not a JSON object, and every entry whose quoteId is shared with another
    entry, is an anomaly. Anomalies are never usable as quotes (fail-closed), must be preserved
    verbatim on persist, and block readiness / tenant-scoped backups until explicitly resolved.
    """
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("logistics.json carrier_quotes must be a list")
    keyed: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    taken: set[str] = set()
    anomalies: list[dict[str, Any]] = []
    for idx, rec in enumerate(rows):
        if not isinstance(rec, dict):
            anomalies.append(
                {
                    "rawIndex": idx,
                    "reason": "non_object",
                    "quoteId": None,
                    "recordFingerprint": carrier_quote_record_fingerprint(rec),
                    "record": rec,
                }
            )
            continue
        key = carrier_quote_record_key(rec, idx, taken)
        taken.add(key)
        keyed.setdefault(key, []).append((idx, rec))
    unique: dict[str, tuple[int, dict[str, Any]]] = {}
    for key, entries in keyed.items():
        if len(entries) == 1:
            unique[key] = entries[0]
            continue
        for idx, rec in entries:
            anomalies.append(
                {
                    "rawIndex": idx,
                    "reason": "duplicate_quote_id",
                    "quoteId": key,
                    "duplicateCount": len(entries),
                    "recordFingerprint": carrier_quote_record_fingerprint(rec),
                    "record": rec,
                }
            )
    anomalies.sort(key=lambda a: int(a["rawIndex"]))
    return {
        "unique": unique,
        "anomalies": anomalies,
        "duplicateQuoteIds": sorted({str(a["quoteId"]) for a in anomalies if a["reason"] == "duplicate_quote_id"}),
        "nonObjectCount": sum(1 for a in anomalies if a["reason"] == "non_object"),
    }


def _require_quantity(quantity: object) -> int:
    if isinstance(quantity, bool):
        raise ValueError("quantity must be a positive integer")
    if isinstance(quantity, int):
        n = quantity
    elif isinstance(quantity, float):
        if not math.isfinite(quantity) or not quantity.is_integer():
            raise ValueError("quantity must be a positive integer")
        n = int(quantity)
    else:
        raise ValueError("quantity must be a positive integer")
    if n < 1:
        raise ValueError("quantity must be at least 1")
    return n


def _positive_finite(value: float, name: str) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return v


def _batch_totals(cartons: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for c in cartons:
        for item in c.get("contents") or []:
            sku = str(item.get("sku"))
            totals[sku] = totals.get(sku, 0.0) + float(item.get("qty") or 0)
    return totals


def _pack_contents_conserved(
    cartons: list[dict[str, Any]],
    expected_batch: dict[str, float] | None = None,
) -> bool | None:
    if not cartons:
        return None
    for c in cartons:
        for item in c.get("contents") or []:
            qty = float(item.get("qty") or 0)
            if not math.isfinite(qty) or qty <= 0:
                return False
    if expected_batch is None:
        return None
    recorded = _batch_totals(cartons)
    if set(recorded) != set(expected_batch):
        return False
    for sku, exp in expected_batch.items():
        if abs(recorded.get(sku, 0.0) - float(exp)) > 1e-6:
            return False
    return True


def _measured_snapshot_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = ("length", "width", "height", "weightKg", "source", "truthLabel")
    for key in keys:
        if left.get(key) != right.get(key):
            return False
    return True


def _carton_physical_oversize(dims: dict[str, Any]) -> bool:
    cl = float(dims["length"])
    cw = float(dims["width"])
    ch = float(dims["height"])
    ck = float(dims.get("weightKg") or 0)
    return cl > PALLET_MM[0] or cw > PALLET_MM[1] or ch > PALLET_MAX_H or ck > PALLET_MAX_KG


class LogisticsService:
    def __init__(self, root: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self._crash_mode = ""
        self.cartons: dict[str, dict[str, Any]] = {}
        self.pallets: dict[str, dict[str, Any]] = {}
        self.shipments: dict[str, dict[str, Any]] = {}
        self.carrier_quotes: dict[str, dict[str, Any]] = {}
        self._carrier_quote_anomalies: list[dict[str, Any]] = []
        self.checklists: dict[str, dict[str, Any]] = {}
        self.handoffs: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, Any] = {}
        self._store_sig: tuple[int, int, int, int] | None = None
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        path = self.root / "logistics.json"
        payload = read_json(path) or {}
        self.cartons = {r["cartonId"]: r for r in payload.get("cartons") or []}
        self.pallets = {r["palletPlanId"]: r for r in payload.get("pallets") or []}
        self.shipments = {r["shipmentId"]: r for r in payload.get("shipments") or []}
        scan = scan_carrier_quote_records(payload.get("carrier_quotes"))
        self.carrier_quotes = {key: rec for key, (_idx, rec) in scan["unique"].items()}
        # Non-object entries and every copy of a duplicated quoteId are quarantined: unusable as quotes,
        # written back verbatim by persist(), and reported as blocking until resolve_carrier_quote_records().
        self._carrier_quote_anomalies = scan["anomalies"]
        self.checklists = {r["checklistId"]: r for r in payload.get("checklists") or []}
        self.handoffs = {r["handoffId"]: r for r in payload.get("handoffs") or []}
        self._idem = dict(payload.get("idem") or {})
        self._store_sig = _file_sig(path)

    def _sync_from_disk(self) -> None:
        if not self.root:
            return
        path = self.root / "logistics.json"
        sig = _file_sig(path)
        if sig == self._store_sig or sig is None:
            return
        self.load()

    def persist(self) -> None:
        if not self.root:
            return
        path = self.root / "logistics.json"
        atomic_write_json(
            path,
            {
                "cartons": list(self.cartons.values()),
                "pallets": list(self.pallets.values()),
                "shipments": list(self.shipments.values()),
                "carrier_quotes": [
                    *self.carrier_quotes.values(),
                    *(a["record"] for a in self._carrier_quote_anomalies),
                ],
                "checklists": list(self.checklists.values()),
                "handoffs": list(self.handoffs.values()),
                "idem": self._idem,
            },
        )
        self._store_sig = _file_sig(path)

    def instantiate_cartons(
        self,
        *,
        tenant_id: str,
        work_order_id: str,
        batch_id: str,
        plan: dict[str, Any],
        quantity: int,
        contents: list[dict[str, Any]] | None = None,
        expected_weight_kg: float = 8.0,
        idempotency_key: str | None = None,
        release_hash: str | None = None,
        product_version: Any = None,
        lot_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            n = _require_quantity(quantity)
            raw_key = idempotency_key or f"{work_order_id}:{batch_id}"
            key = f"{tenant_id}::carton::{raw_key}"
            if key in self._idem:
                ids = self._idem[key]
                if not isinstance(ids, list):
                    raise PermissionError("idempotency namespace collision: carton")
                rows = [self.cartons[i] for i in ids]
                if any(r.get("tenantId") != tenant_id for r in rows):
                    raise PermissionError("tenant isolation: carton")
                if len(rows) != n or any(r.get("workOrderId") != work_order_id for r in rows):
                    raise SemanticKeyConflictError("carton idempotency conflict")
                return rows
            rows = []
            ids = []
            for i in range(n):
                rec = {
                    "cartonId": new_id(),
                    "tenantId": tenant_id,
                    "workOrderId": work_order_id,
                    "batchId": batch_id,
                    "index": i,
                    "contents": list(contents or [{"sku": "product", "qty": 1}]),
                    "expected": {
                        "length": float(plan.get("length") or 400),
                        "width": float(plan.get("width") or 300),
                        "height": float(plan.get("height") or 200),
                        "weightKg": float(expected_weight_kg),
                        "source": plan.get("costSource") or "CONFIG_ESTIMATE",
                        "truthLabel": "EXPECTED",
                    },
                    "measured": None,
                    "releaseHash": release_hash,
                    "productVersion": product_version,
                    "lotIds": list(lot_ids or []),
                    "createdAt": _now(),
                }
                rec["cartonHash"] = stable_hash({k: rec[k] for k in rec if k not in {"cartonId", "cartonHash"}})
                self.cartons[rec["cartonId"]] = rec
                rows.append(rec)
                ids.append(rec["cartonId"])
            self._idem[key] = ids
            try:
                emit(
                    self,
                    "carton.instantiate",
                    tenant_id=tenant_id,
                    aggregate_type="Carton",
                    aggregate_id=ids[0] if ids else key,
                    actor="ops",
                    payload={"count": len(ids), "workOrderId": work_order_id},
                    release_hash=release_hash,
                    semantic_key=key,
                )
            except Exception:
                if self.root and (self.root / "logistics.json").exists():
                    self.load()
                else:
                    for cid in ids:
                        self.cartons.pop(cid, None)
                    self._idem.pop(key, None)
                raise
            return rows

    def record_measured(
        self,
        carton_id: str,
        *,
        tenant_id: str,
        length: float,
        width: float,
        height: float,
        weight_kg: float,
        source: str = "IMPORTED",
        measure_op_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            rec = self.cartons[carton_id]
            prev_snapshot = copy.deepcopy(rec)
            if rec.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: carton measure")
            expected = dict(rec["expected"])
            m_len = _positive_finite(length, "length")
            m_wid = _positive_finite(width, "width")
            m_hgt = _positive_finite(height, "height")
            m_wgt = _positive_finite(weight_kg, "weightKg")
            measured = {
                "length": m_len,
                "width": m_wid,
                "height": m_hgt,
                "weightKg": m_wgt,
                "source": source if source in {"IMPORTED", "MANUAL", "MEASURED"} else "IMPORTED",
                "truthLabel": "MEASURED",
            }
            op_id = measure_op_id or new_id()
            ops = rec.setdefault("measureOps", {})
            latest_seq = int(rec.get("measureSeq") or 0)
            prior = ops.get(op_id)
            if prior is not None:
                if not _measured_snapshot_equal(dict(prior["measured"]), measured):
                    raise ValueError("measure op payload mismatch on retry")
                audit_measured = dict(prior["measured"])
                stale_retry = int(prior["seq"]) < latest_seq
            else:
                audit_measured = measured
                stale_retry = False
                latest_seq += 1
                ops[op_id] = {"measured": dict(measured), "seq": latest_seq}
                rec["measureSeq"] = latest_seq
            if not stale_retry:
                rec["measured"] = measured
                rec["expected"] = expected
                mismatch = (
                    abs(m_len - float(expected["length"])) > 5
                    or abs(m_wid - float(expected["width"])) > 5
                    or abs(m_hgt - float(expected["height"])) > 5
                    or abs(m_wgt - float(expected.get("weightKg") or 0)) > 1.0
                )
                rec["mismatch"] = mismatch
                rec["autoOverride"] = False
            try:
                emit(
                    self,
                    "carton.measured",
                    tenant_id=tenant_id,
                    aggregate_type="Carton",
                    aggregate_id=carton_id,
                    actor="ops",
                    payload={"measured": audit_measured, "measureOpId": op_id},
                    release_hash=rec.get("releaseHash"),
                    semantic_key=f"{tenant_id}::carton-measured::{carton_id}::{op_id}",
                )
            except Exception:
                if self.root and (self.root / "logistics.json").exists():
                    disk = read_json(self.root / "logistics.json") or {}
                    disk_cartons = {r["cartonId"]: r for r in disk.get("cartons") or []}
                    if carton_id in disk_cartons:
                        self.cartons[carton_id] = disk_cartons[carton_id]
                    else:
                        self.cartons[carton_id] = prev_snapshot
                else:
                    self.cartons[carton_id] = prev_snapshot
                raise
            return rec

    def packing_list(
        self,
        *,
        tenant_id: str,
        work_order_id: str,
        expected_batch: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        cartons = [
            c
            for c in self.cartons.values()
            if c["workOrderId"] == work_order_id and c.get("tenantId") == tenant_id
        ]
        contents: dict[str, float] = {}
        for c in cartons:
            for item in c.get("contents") or []:
                contents[str(item.get("sku"))] = contents.get(str(item.get("sku")), 0) + float(item.get("qty") or 0)
        return {
            "workOrderId": work_order_id,
            "cartonCount": len(cartons),
            "cartons": [{"cartonId": c["cartonId"], "contents": c["contents"], "expected": c["expected"], "measured": c["measured"]} for c in cartons],
            "batchTotal": contents,
            "tenantId": tenant_id,
            "contentsConserved": _pack_contents_conserved(cartons, expected_batch),
        }

    def contents_conserved(self, *, tenant_id: str, work_order_id: str, expected_qty: float, sku: str = "product") -> bool:
        lst = self.packing_list(tenant_id=tenant_id, work_order_id=work_order_id)
        return abs(float(lst["batchTotal"].get(sku) or 0) - float(expected_qty)) < 1e-6

    def pack_completeness(self, *, tenant_id: str, work_order_id: str, expected_qty: float, sku: str = "product") -> dict[str, Any]:
        lst = self.packing_list(tenant_id=tenant_id, work_order_id=work_order_id)
        got = float(lst["batchTotal"].get(sku) or 0)
        delta = got - float(expected_qty)
        ok = abs(delta) < 1e-6
        code = "ok"
        if delta < -1e-6:
            code = "shortage"
        elif delta > 1e-6:
            code = "duplicate"
        return {
            "ok": ok,
            "code": code,
            "expected": expected_qty,
            "recorded": got,
            "shipmentReady": ok,
            "workOrderId": work_order_id,
        }

    def dim_weight(self, dims: dict[str, Any], *, divisor: float = DIM_DIVISOR) -> dict[str, Any]:
        l, w, h = float(dims["length"]), float(dims["width"]), float(dims["height"])
        vol = l * w * h
        dw = vol / float(divisor)
        oversize = l > 1200 or (2 * (w + h) + l) > 3000
        return {
            "volumeMm3": vol,
            "dimWeightKg": round(dw, 3),
            "divisor": divisor,
            "oversize": oversize,
            "source": "PLANNING",
            "certification": False,
        }

    def palletize(self, carton_ids: list[str], *, persist: bool = True) -> dict[str, Any]:
        with self._lock:
            cartons = [self.cartons[i] for i in carton_ids]
            tenants = {c.get("tenantId") for c in cartons}
            if not cartons or len(tenants) != 1 or None in tenants:
                raise PermissionError("cross-tenant pallet mix")
            stackable: list[dict[str, Any]] = []
            held: list[str] = []
            plan_oversize = False
            for c in cartons:
                d = c.get("measured") or c["expected"]
                if _carton_physical_oversize(d):
                    held.append(c["cartonId"])
                    plan_oversize = True
                else:
                    stackable.append(c)

            current: list[str] = []
            used_w = 0.0
            used_d = 0.0
            height = 0.0
            weight = 0.0
            pallets: list[dict[str, Any]] = []

            def flush() -> None:
                nonlocal current, used_w, used_d, height, weight, plan_oversize
                if not current:
                    return
                pallet_oversize = (
                    height > PALLET_MAX_H
                    or weight > PALLET_MAX_KG
                    or used_w > PALLET_MM[0]
                    or used_d > PALLET_MM[1]
                )
                if pallet_oversize:
                    plan_oversize = True
                pallets.append(
                    {
                        "cartonIds": list(current),
                        "footprintMm": [PALLET_MM[0], PALLET_MM[1]],
                        "heightMm": round(height, 1),
                        "weightKg": round(weight, 3),
                        "usedFootprintMm": [round(used_w, 1), round(used_d, 1)],
                        "label": "PLANNING",
                        "carrierCertification": False,
                        "oversize": pallet_oversize,
                    }
                )
                current, used_w, used_d, height, weight = [], 0.0, 0.0, 0.0, 0.0

            for c in stackable:
                d = c.get("measured") or c["expected"]
                cl, cw, ch, ck = float(d["length"]), float(d["width"]), float(d["height"]), float(d.get("weightKg") or 0)
                if height + ch > PALLET_MAX_H or weight + ck > PALLET_MAX_KG:
                    flush()
                current.append(c["cartonId"])
                used_w = max(used_w, cl)
                used_d = max(used_d, cw)
                height += ch
                weight += ck
            flush()
            status = "NEEDS_HUMAN" if plan_oversize else "PLANNING"
            rec: dict[str, Any] = {
                "palletPlanId": new_id(),
                "tenantId": next(iter(tenants)),
                "cartonIds": list(carton_ids),
                "pallets": pallets,
                "palletCount": len(pallets),
                "heldCartonIds": held,
                "constraints": {"footprintMm": list(PALLET_MM), "maxHeightMm": PALLET_MAX_H, "maxWeightKg": PALLET_MAX_KG},
                "label": "PLANNING",
                "carrierCertification": False,
                "oversize": plan_oversize,
                "status": status,
            }
            rec["planHash"] = stable_hash({k: rec[k] for k in rec if k not in {"palletPlanId", "planHash"}})
            self.pallets[rec["palletPlanId"]] = rec
            if persist:
                try:
                    self.persist()
                except Exception:
                    self.pallets.pop(rec["palletPlanId"], None)
                    raise
            return rec

    def shipping_request(
        self,
        *,
        origin: str,
        destination: str,
        carton_ids: list[str],
        service: str = "ground",
        quote_id: str | None = None,
        dim_divisor: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not carton_ids:
                raise ValueError("carton_ids must not be empty")
            if len(carton_ids) != len(set(carton_ids)):
                raise ValueError("duplicate carton_ids")
            cartons = [self.cartons[i] for i in carton_ids]
            tenants = {c.get("tenantId") for c in cartons}
            if len(tenants) != 1 or None in tenants:
                raise PermissionError("cross-tenant carton mix")
            norm_quote_id: str | None = None
            if quote_id is not None and quote_id != "":
                if not isinstance(quote_id, str) or not quote_id.strip():
                    raise ValueError("quote_id must be a non-empty string")
                norm_quote_id = quote_id.strip()
            norm_divisor = _positive_finite(dim_divisor, "dim_divisor") if dim_divisor is not None else None
            rec: dict[str, Any] = {
                "shipmentId": new_id(),
                "tenantId": next(iter(tenants)),
                "origin": origin,
                "destination": destination,
                "service": service,
                "cartonIds": list(carton_ids),
                "pieces": len(cartons),
                "submittedToCarrier": False,
                "booked": False,
                "shipped": False,
                "status": "SHIPMENT_DRAFT",
                "providerNeutral": True,
                "createdAt": _now(),
            }
            if norm_quote_id is not None:
                rec["quoteId"] = norm_quote_id
            if norm_divisor is not None:
                rec["dimDivisor"] = norm_divisor
            rec["requestHash"] = stable_hash({k: rec[k] for k in rec if k not in {"shipmentId", "requestHash"}})
            tenant = rec["tenantId"]
            ordered = sorted(carton_ids)
            raw = f"{origin}:{destination}:{','.join(ordered)}:{service}"
            idem = f"{tenant}::shipment::{raw}"
            if idem in self._idem:
                stored = self._idem[idem]
                sid = stored[0] if isinstance(stored, list) else stored
                if sid not in self.shipments:
                    raise PermissionError("idempotency namespace collision: shipment")
                existing = self.shipments[sid]
                if existing.get("tenantId") != tenant:
                    raise PermissionError("tenant isolation: shipment")
                if existing.get("status") == "HANDED_OFF_MANUAL" or existing.get("handoff") is not None:
                    raise SemanticKeyConflictError("shipment already handed off; cannot modify or recreate draft")
                existing_quote = existing.get("quoteId")
                existing_div = existing.get("dimDivisor")
                div_matches = (
                    existing_div is None and norm_divisor is None
                ) or (
                    existing_div is not None
                    and norm_divisor is not None
                    and abs(float(existing_div) - norm_divisor) <= 1e-6
                )
                if existing_quote != norm_quote_id or not div_matches:
                    raise SemanticKeyConflictError("shipment draft conflict: quoteId or dimDivisor mismatch")
                return existing
            self._idem[idem] = rec["shipmentId"]
            self.shipments[rec["shipmentId"]] = rec
            return rec

    def shipment_draft(
        self,
        *,
        origin: str,
        destination: str,
        carton_ids: list[str],
        service: str = "ground",
        quote_id: str | None = None,
        dim_divisor: float | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            shipment_ids_before = set(self.shipments)
            idem_keys_before = set(self._idem)
            rec = self.shipping_request(
                origin=origin,
                destination=destination,
                carton_ids=carton_ids,
                service=service,
                quote_id=quote_id,
                dim_divisor=dim_divisor,
            )
            sid = rec["shipmentId"]
            tenant = str(rec.get("tenantId") or "")
            ordered = sorted(carton_ids)
            raw = f"{origin}:{destination}:{','.join(ordered)}:{service}"
            content_idem_key = f"{tenant}::shipment::{raw}"
            created_new_shipment = sid not in shipment_ids_before
            created_content_idem = content_idem_key not in idem_keys_before
            prev_existing = copy.deepcopy(rec) if not created_new_shipment else None

            store_key: str | None = None
            created_store_key = False
            if idempotency_key is not None:
                if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                    if created_content_idem:
                        self._idem.pop(content_idem_key, None)
                    if created_new_shipment:
                        self.shipments.pop(sid, None)
                    raise ValueError("idempotency_key must be a non-empty string")
                clean_idem = idempotency_key.strip()
                store_key = f"{tenant}::shipment-key::{clean_idem}"
                req_sig = {
                    "origin": origin,
                    "destination": destination,
                    "cartonIds": ordered,
                    "service": service,
                    "quoteId": rec.get("quoteId"),
                    "dimDivisor": rec.get("dimDivisor"),
                }
                if store_key in self._idem:
                    entry = self._idem[store_key]
                    if not isinstance(entry, dict) or entry.get("sig") != req_sig or entry.get("shipmentId") != sid:
                        if created_content_idem:
                            self._idem.pop(content_idem_key, None)
                        if created_new_shipment:
                            self.shipments.pop(sid, None)
                        raise SemanticKeyConflictError("idempotencyKey 衝突：相同冪等鍵不可用於不同出貨參數")
                else:
                    self._idem[store_key] = {
                        "shipmentId": sid,
                        "sig": req_sig,
                    }
                    created_store_key = True

            rec["submittedToCarrier"] = False
            rec["booked"] = False
            rec["shipped"] = False
            rec["status"] = "SHIPMENT_DRAFT"
            rec["liveCarrier"] = False
            try:
                emit(
                    self,
                    "shipment.draft",
                    tenant_id=tenant,
                    aggregate_type="Shipment",
                    aggregate_id=sid,
                    actor="ops",
                    payload={"status": "SHIPMENT_DRAFT", "booked": False},
                    semantic_key=f"{tenant}::shipment::{sid}",
                )
            except Exception:
                disk_shipments: set[str] = set()
                disk_idem: dict[str, Any] = {}
                if self.root and (self.root / "logistics.json").exists():
                    try:
                        disk = read_json(self.root / "logistics.json") or {}
                        disk_shipments = {
                            str(r["shipmentId"])
                            for r in (disk.get("shipments") or [])
                            if isinstance(r, dict) and "shipmentId" in r
                        }
                        if isinstance(disk.get("idem"), dict):
                            disk_idem = disk["idem"]
                    except Exception:
                        pass
                if created_store_key and store_key is not None and store_key not in disk_idem:
                    self._idem.pop(store_key, None)
                if created_content_idem and content_idem_key not in disk_idem:
                    self._idem.pop(content_idem_key, None)
                if created_new_shipment and sid not in disk_shipments:
                    self.shipments.pop(sid, None)
                elif not created_new_shipment and prev_existing is not None and sid not in disk_shipments:
                    self.shipments[sid] = prev_existing
                raise
            return rec

    def import_carrier_quote(
        self,
        row: dict[str, Any],
        *,
        source: str,
        raw: str | None = None,
        tenant_id: str | None = None,
        allow_global: bool = False,
        global_quote: bool = False,
        is_global: bool = False,
        persist: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if source not in ALLOWED_SOURCES:
                raise PermissionError("carrier quotes are MANUAL/IMPORTED unless a live carrier is connected")
            if not isinstance(row, dict):
                raise ValueError("carrier quote row must be a dict")
            for flag_name, flag_val in (
                ("allow_global", allow_global),
                ("global_quote", global_quote),
                ("is_global", is_global),
            ):
                if not isinstance(flag_val, bool):
                    raise ValueError(f"{flag_name} must be a boolean")
            explicit_global = bool(allow_global or global_quote or is_global)

            raw_valid_until = row.get("validUntil")
            if raw_valid_until in (None, ""):
                valid_until = "9999-12-31"
            else:
                valid_until = _parse_valid_until_date(raw_valid_until).isoformat()

            eff_tenant: str | None = None
            if tenant_id is not None:
                if not isinstance(tenant_id, str) or not tenant_id.strip():
                    raise ValueError("tenant_id must be a non-empty string")
                eff_tenant = tenant_id.strip()
            if "tenantId" in row and row.get("tenantId") is not None:
                raw_tid = row.get("tenantId")
                if not isinstance(raw_tid, str) or not raw_tid.strip():
                    raise ValueError("tenantId must be a non-empty string")
                row_tid = raw_tid.strip()
                if eff_tenant is not None and row_tid != eff_tenant:
                    raise PermissionError("tenant isolation: carrier quote")
                eff_tenant = row_tid

            if eff_tenant is not None and explicit_global:
                raise ValueError("cannot combine tenant_id with explicit global carrier quote flag")
            if eff_tenant is None and not explicit_global:
                raise ValueError(
                    "tenant_id is required for import_carrier_quote unless allow_global=True (or global_quote=True)"
                )

            raw_qid = row.get("quoteId")
            if raw_qid not in (None, ""):
                if not isinstance(raw_qid, str) or not raw_qid.strip():
                    raise ValueError("quoteId must be a non-empty string")
                quote_id = raw_qid.strip()
            else:
                quote_id = new_id()

            self._refuse_quarantined_quote_ids([quote_id])
            existing = self.carrier_quotes.get(quote_id)
            if existing is not None:
                if existing.get("tenantId") != eff_tenant:
                    raise PermissionError("tenant isolation: carrier quote")
                if eff_tenant is None and not is_explicit_global_carrier_quote(existing):
                    raise PermissionError("tenant isolation: legacy unassigned carrier quote")

            rec: dict[str, Any] = {
                "quoteId": quote_id,
                "carrier": row.get("carrier") or "carrier",
                "service": row.get("service") or "ground",
                "charge": float(row.get("charge") or row.get("amount") or 0),
                "currency": row.get("currency") or "TWD",
                "dimDivisor": float(row.get("dimDivisor") or DIM_DIVISOR),
                "validUntil": valid_until,
                "source": source,
                "truthLabel": source,
                "liveProvider": False,
                "importedAt": _now(),
                "rawSourceHash": stable_hash(raw if raw is not None else json.dumps(row, sort_keys=True, default=str)),
            }
            if eff_tenant is not None:
                rec["tenantId"] = eff_tenant
            rec["quoteHash"] = stable_hash({k: rec[k] for k in rec if k not in {"quoteId", "quoteHash"}})
            if eff_tenant is None:
                rec["ownership"] = "GLOBAL_REFERENCE"
                rec["globalQuote"] = True
            else:
                rec["ownership"] = "TENANT_OWNED"
                rec["globalQuote"] = False
            prev_quotes = copy.deepcopy(self.carrier_quotes)
            self.carrier_quotes[rec["quoteId"]] = rec
            if persist:
                try:
                    self.persist()
                except Exception:
                    self.carrier_quotes = prev_quotes
                    raise
            return rec

    def _quarantined_duplicate_quote_ids(self) -> set[str]:
        return {
            str(a["quoteId"]) for a in self._carrier_quote_anomalies if a["reason"] == "duplicate_quote_id"
        }

    def _refuse_quarantined_quote_ids(self, quote_ids: list[str]) -> None:
        dup_ids = self._quarantined_duplicate_quote_ids()
        for qid in quote_ids:
            if qid in dup_ids:
                # Prefixed with "tenant isolation" so HTTP callers map it to 409 without exposing record contents.
                raise PermissionError(
                    f"tenant isolation: carrier quote {qid} has duplicate records in logistics.json; "
                    f"{CARRIER_QUOTE_RECORD_REMEDIATION}"
                )

    def resolve_carrier_quote_records(
        self,
        *,
        keep: Mapping[str, str] | None = None,
        drop: list[str] | set[str] | tuple[str, ...] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Explicitly resolve quarantined carrier_quotes entries.

        keep: quoteId -> recordFingerprint of the one duplicate copy to keep; all other copies are removed.
        drop: recordFingerprints of non-object entries to remove.
        Removed entries are returned verbatim in ``removed`` so the operator retains a copy.
        """
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        norm_keep: dict[str, str] = {}
        if keep is not None:
            if not isinstance(keep, Mapping):
                raise ValueError("keep must be a mapping of quoteId -> recordFingerprint")
            for raw_qid, raw_fp in keep.items():
                if not isinstance(raw_qid, str) or not raw_qid.strip():
                    raise ValueError("keep quoteId must be a non-empty string")
                if not isinstance(raw_fp, str) or not raw_fp.strip():
                    raise ValueError("keep recordFingerprint must be a non-empty string")
                norm_keep[raw_qid.strip()] = raw_fp.strip()
        norm_drop: list[str] = []
        if drop is not None:
            if not isinstance(drop, (list, set, tuple)):
                raise ValueError("drop must be a collection of recordFingerprint strings")
            for raw_fp in drop:
                if not isinstance(raw_fp, str) or not raw_fp.strip():
                    raise ValueError("drop elements must be non-empty recordFingerprint strings")
                if raw_fp.strip() not in norm_drop:
                    norm_drop.append(raw_fp.strip())
        if not norm_keep and not norm_drop:
            raise ValueError("nothing to resolve: pass keep (quoteId -> fingerprint) and/or drop (fingerprints)")

        with self._lock:
            self._sync_from_disk()
            anomalies = self._carrier_quote_anomalies
            kept: list[dict[str, Any]] = []
            keep_pos_set: set[int] = set()
            removed_pos: set[int] = set()
            restored: dict[str, dict[str, Any]] = {}

            for qid, fp in norm_keep.items():
                positions = [
                    i
                    for i, a in enumerate(anomalies)
                    if a["reason"] == "duplicate_quote_id" and a["quoteId"] == qid
                ]
                if not positions:
                    raise KeyError(f"no duplicate carrier quote records for quoteId: {qid}")
                matches = [i for i in positions if anomalies[i]["recordFingerprint"] == fp]
                if not matches:
                    raise KeyError(f"recordFingerprint {fp} does not match any duplicate record of quoteId {qid}")
                keep_pos = matches[0]
                restored[qid] = anomalies[keep_pos]["record"]
                kept.append({"quoteId": qid, "rawIndex": anomalies[keep_pos]["rawIndex"], "recordFingerprint": fp})
                keep_pos_set.add(keep_pos)
                removed_pos.update(i for i in positions if i != keep_pos)

            for fp in norm_drop:
                matches = [
                    i
                    for i, a in enumerate(anomalies)
                    if a["reason"] == "non_object" and a["recordFingerprint"] == fp
                ]
                if not matches:
                    raise KeyError(f"recordFingerprint {fp} does not match any non-object carrier quote record")
                removed_pos.update(matches)

            removed = [
                {
                    k: copy.deepcopy(anomalies[i][k])
                    for k in ("rawIndex", "reason", "quoteId", "recordFingerprint", "record")
                }
                for i in sorted(removed_pos)
            ]
            resolved_pos = removed_pos | keep_pos_set
            if not dry_run:
                prev_quotes = copy.deepcopy(self.carrier_quotes)
                prev_anomalies = self._carrier_quote_anomalies
                try:
                    for qid, rec in restored.items():
                        self.carrier_quotes[qid] = rec
                    self._carrier_quote_anomalies = [a for i, a in enumerate(anomalies) if i not in resolved_pos]
                    self.persist()
                except Exception:
                    self.carrier_quotes = prev_quotes
                    self._carrier_quote_anomalies = prev_anomalies
                    raise
            return {
                "dryRun": dry_run,
                "keptCount": len(kept),
                "removedCount": len(removed),
                "kept": kept,
                "removed": removed,
                "remainingAnomalyCount": len(anomalies) - len(resolved_pos),
            }

    def _quote_shipment_references(self) -> dict[str, list[dict[str, Any]]]:
        refs: dict[str, list[dict[str, Any]]] = {}
        for ship in self.shipments.values():
            qid = ship.get("quoteId")
            if isinstance(qid, str) and qid.strip():
                refs.setdefault(qid.strip(), []).append(ship)
        return refs

    @staticmethod
    def _anomaly_report_item(
        anomaly: dict[str, Any],
        refs_by_qid: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        rec = anomaly["record"]
        item: dict[str, Any] = copy.deepcopy(rec) if isinstance(rec, dict) else {"rawRecord": copy.deepcopy(rec)}
        qid = anomaly["quoteId"]
        ref_shipments = refs_by_qid.get(qid, []) if qid is not None else []
        if anomaly["reason"] == "duplicate_quote_id":
            item["quoteId"] = qid
            item["tenantId"] = classify_carrier_quote(rec)["tenantId"]
            item["duplicateCount"] = anomaly["duplicateCount"]
            item["remediation"] = (
                f"python scripts/migrate_carrier_quotes.py --root <data-root> "
                f"--keep-duplicate {qid}={anomaly['recordFingerprint']} (removes the other copies)"
            )
        else:
            item["quoteId"] = f"<non-object:{anomaly['rawIndex']}>"
            item["tenantId"] = None
            item["remediation"] = (
                "python scripts/migrate_carrier_quotes.py --root <data-root> "
                f"--drop-invalid {anomaly['recordFingerprint']}"
            )
        item["explicitGlobal"] = False
        item["issue"] = anomaly["reason"]
        item["rawIndex"] = anomaly["rawIndex"]
        item["recordFingerprint"] = anomaly["recordFingerprint"]
        item["inferredTenantId"] = None
        item["referencedByTenants"] = sorted(
            {
                str(s["tenantId"]).strip()
                for s in ref_shipments
                if isinstance(s.get("tenantId"), str) and str(s["tenantId"]).strip()
            }
        )
        item["referencedShipmentIds"] = sorted(
            str(s["shipmentId"]) for s in ref_shipments if isinstance(s.get("shipmentId"), str) and s["shipmentId"]
        )
        item["conflict"] = True
        return item

    def inspect_tenantless_carrier_quotes(
        self,
        *,
        include_explicit_global: bool = False,
    ) -> dict[str, Any]:
        """List carrier quotes missing tenantId or having conflicting tenant/global metadata."""
        if not isinstance(include_explicit_global, bool):
            raise ValueError("include_explicit_global must be a boolean")
        with self._lock:
            self._sync_from_disk()
            refs_by_qid = self._quote_shipment_references()
            items: list[dict[str, Any]] = []
            sorted_quotes = sorted(
                self.carrier_quotes.values(),
                key=lambda q: (str(q.get("importedAt") or ""), carrier_quote_id(q)),
            )
            for q in sorted_quotes:
                if not is_tenantless_carrier_quote(q, include_explicit_global=include_explicit_global):
                    continue
                info = classify_carrier_quote(q)
                qid = carrier_quote_id(q)
                ref_shipments = refs_by_qid.get(qid, [])
                ref_tenants = sorted(
                    {
                        str(s["tenantId"]).strip()
                        for s in ref_shipments
                        if isinstance(s.get("tenantId"), str) and str(s["tenantId"]).strip()
                    }
                )
                ref_ship_ids = sorted(
                    str(s["shipmentId"]) for s in ref_shipments if isinstance(s.get("shipmentId"), str) and s["shipmentId"]
                )
                existing_tid = info["tenantId"]
                field_conflict = bool(info["tenantFieldConflict"])
                claimed = list(info["claimedTenantIds"])
                shipment_mismatch = bool(existing_tid and any(t != existing_tid for t in ref_tenants))
                # A shipment must not nominate an owner while the quote's own tenant fields disagree or are invalid.
                if field_conflict:
                    inferred_tid = None
                elif len(ref_tenants) == 1 and (existing_tid is None or existing_tid == ref_tenants[0]):
                    inferred_tid = ref_tenants[0]
                elif not ref_tenants and existing_tid is not None:
                    inferred_tid = existing_tid
                else:
                    inferred_tid = None
                has_conflict = bool(
                    len(ref_tenants) > 1
                    or shipment_mismatch
                    or info["metadataConflict"]
                    or field_conflict
                )
                item = copy.deepcopy(q)
                item["quoteId"] = qid
                item["tenantId"] = existing_tid
                item["explicitGlobal"] = info["explicitGlobal"]
                item["issue"] = info["issue"]
                item["inferredTenantId"] = inferred_tid
                item["claimedTenantIds"] = claimed
                item["tenantFieldConflict"] = field_conflict
                item["referencedByTenants"] = ref_tenants
                item["referencedShipmentIds"] = ref_ship_ids
                item["conflict"] = has_conflict
                if field_conflict:
                    item["rawTenantFields"] = _raw_tenant_fields(q)
                    item["remediation"] = tenant_field_repair_hint(qid, claimed)
                items.append(item)
            for anomaly in self._carrier_quote_anomalies:
                items.append(self._anomaly_report_item(anomaly, refs_by_qid))
            conflict_items = [item for item in items if item.get("conflict")]
            blocking_items = [item for item in items if not item.get("explicitGlobal")]
            anomalies = self._carrier_quote_anomalies
            return {
                "totalQuotes": len(self.carrier_quotes) + len(anomalies),
                "duplicateQuoteIds": sorted(
                    {str(a["quoteId"]) for a in anomalies if a["reason"] == "duplicate_quote_id"}
                ),
                "duplicateRecordCount": sum(1 for a in anomalies if a["reason"] == "duplicate_quote_id"),
                "invalidRecordCount": sum(1 for a in anomalies if a["reason"] == "non_object"),
                "tenantlessCount": len(items),
                "blockingCount": len(blocking_items),
                "conflictCount": len(conflict_items),
                "ready": len(blocking_items) == 0,
                "quoteIds": [item["quoteId"] for item in items],
                "conflictQuoteIds": [item["quoteId"] for item in conflict_items],
                "items": items,
                "quotes": items,
            }

    list_tenantless_carrier_quotes = inspect_tenantless_carrier_quotes
    check_tenantless_carrier_quotes = inspect_tenantless_carrier_quotes

    def migrate_tenantless_carrier_quotes(
        self,
        *,
        tenant_id: str | None = None,
        default_tenant_id: str | None = None,
        assignments: Mapping[str, str] | None = None,
        quote_ids: list[str] | set[str] | tuple[str, ...] | None = None,
        infer_from_shipments: bool = True,
        mark_global: bool = False,
        include_explicit_global: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Attribute legacy tenantless carrier quotes to tenants (or mark them explicitly global).

        Quotes whose tenantId and tenant_id conflict, or whose tenant fields are present but unusable,
        stay unresolved. Batch default assignment, shipment inference, and --mark-global do not rewrite them.
        """
        if (
            not isinstance(dry_run, bool)
            or not isinstance(mark_global, bool)
            or not isinstance(infer_from_shipments, bool)
            or not isinstance(include_explicit_global, bool)
        ):
            raise ValueError("boolean flags must be bool")

        eff_default_tid: str | None = None
        for label, raw_tid in (("tenant_id", tenant_id), ("default_tenant_id", default_tenant_id)):
            if raw_tid is not None:
                if not isinstance(raw_tid, str) or not raw_tid.strip():
                    raise ValueError(f"{label} must be a non-empty string")
                cleaned = raw_tid.strip()
                if eff_default_tid is not None and eff_default_tid != cleaned:
                    raise ValueError("tenant_id and default_tenant_id mismatch")
                eff_default_tid = cleaned

        norm_assignments: dict[str, str] = {}
        if assignments is not None:
            if not isinstance(assignments, Mapping):
                raise ValueError("assignments must be a mapping of quoteId -> tenantId")
            for raw_qid, raw_target in assignments.items():
                if not isinstance(raw_qid, str) or not raw_qid.strip():
                    raise ValueError("assignment quoteId must be a non-empty string")
                if not isinstance(raw_target, str) or not raw_target.strip():
                    raise ValueError("assignment tenantId must be a non-empty string")
                norm_assignments[raw_qid.strip()] = raw_target.strip()

        if mark_global and (eff_default_tid is not None or norm_assignments):
            raise ValueError("cannot combine mark_global=True with tenant assignments")

        filter_qids: list[str] | None = None
        if quote_ids is not None:
            if not isinstance(quote_ids, (list, set, tuple)):
                raise ValueError("quote_ids must be a collection of quoteId strings")
            filter_qids = []
            seen_filter: set[str] = set()
            for item in quote_ids:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("quote_ids elements must be non-empty strings")
                cleaned_qid = item.strip()
                if cleaned_qid not in seen_filter:
                    seen_filter.add(cleaned_qid)
                    filter_qids.append(cleaned_qid)

        with self._lock:
            self._sync_from_disk()
            self._refuse_quarantined_quote_ids([*norm_assignments, *(filter_qids or [])])
            for qid in norm_assignments:
                if qid not in self.carrier_quotes:
                    raise KeyError(f"carrier quote not found: {qid}")
            if filter_qids is not None:
                for qid in filter_qids:
                    if qid not in self.carrier_quotes:
                        raise KeyError(f"carrier quote not found: {qid}")

            refs_by_qid = self._quote_shipment_references()
            if filter_qids is not None:
                candidate_ids = list(filter_qids)
                for qid in norm_assignments:
                    if qid not in candidate_ids:
                        candidate_ids.append(qid)
            else:
                candidate_ids = [
                    qid_key
                    for qid_key, q in sorted(
                        self.carrier_quotes.items(),
                        key=lambda kv: (str(kv[1].get("importedAt") or ""), carrier_quote_id(kv[1]), kv[0]),
                    )
                    if is_tenantless_carrier_quote(q, include_explicit_global=include_explicit_global)
                    or qid_key in norm_assignments
                ]

            assigned: list[dict[str, Any]] = []
            marked_global: list[dict[str, Any]] = []
            already_assigned: list[dict[str, Any]] = []
            unresolved: list[dict[str, Any]] = []
            conflicts: list[dict[str, Any]] = []
            planned_updates: dict[str, dict[str, Any]] = {}

            for qid in candidate_ids:
                quote = self.carrier_quotes[qid]
                info = classify_carrier_quote(quote)
                existing_tid = info["tenantId"]
                explicit_requested = qid in norm_assignments or (filter_qids is not None and qid in filter_qids)
                ref_shipments = refs_by_qid.get(qid, [])
                ref_tenants = sorted(
                    {
                        str(s["tenantId"]).strip()
                        for s in ref_shipments
                        if isinstance(s.get("tenantId"), str) and str(s["tenantId"]).strip()
                    }
                )

                if info["tenantFieldConflict"]:
                    claimed = list(info["claimedTenantIds"])
                    entry = {
                        "quoteId": qid,
                        "reason": info["issue"] or "conflicting_tenant_id",
                        "claimedTenantIds": claimed,
                        "rawTenantFields": _raw_tenant_fields(quote),
                        "referencedByTenants": ref_tenants,
                        "remediation": tenant_field_repair_hint(qid, claimed),
                    }
                    conflicts.append(entry)
                    unresolved.append(entry)
                    attempted_rewrite = bool(mark_global or qid in norm_assignments or eff_default_tid is not None)
                    if explicit_requested and attempted_rewrite:
                        raise PermissionError(
                            f"tenant isolation: carrier quote {qid} has conflicting or invalid tenant fields; "
                            f"{entry['remediation']}"
                        )
                    continue

                if info["validTenantOwned"]:
                    want_tid = norm_assignments.get(qid) or eff_default_tid
                    if mark_global:
                        raise PermissionError(f"tenant isolation: carrier quote {qid} is already owned by a tenant")
                    if want_tid is not None and want_tid != existing_tid:
                        raise PermissionError(f"tenant isolation: carrier quote {qid} is owned by another tenant")
                    already_assigned.append({"quoteId": qid, "tenantId": existing_tid})
                    continue

                if existing_tid is not None:
                    if mark_global:
                        entry = {
                            "quoteId": qid,
                            "reason": info["issue"] or "conflicting_tenant_and_global",
                            "tenantId": existing_tid,
                            "referencedByTenants": ref_tenants,
                        }
                        conflicts.append(entry)
                        unresolved.append(entry)
                        if explicit_requested:
                            raise PermissionError(
                                f"tenant isolation: carrier quote {qid} is already owned by a tenant"
                            )
                        continue
                    if qid in norm_assignments and norm_assignments[qid] != existing_tid:
                        raise PermissionError(f"tenant isolation: carrier quote {qid} is owned by another tenant")
                    if (
                        filter_qids is not None
                        and qid in filter_qids
                        and qid not in norm_assignments
                        and eff_default_tid is not None
                        and eff_default_tid != existing_tid
                    ):
                        raise PermissionError(f"tenant isolation: carrier quote {qid} is owned by another tenant")

                if mark_global:
                    if ref_tenants:
                        entry = {
                            "quoteId": qid,
                            "reason": "referenced_by_tenant_shipments",
                            "referencedByTenants": ref_tenants,
                        }
                        conflicts.append(entry)
                        unresolved.append(entry)
                        if explicit_requested:
                            raise PermissionError(
                                f"tenant isolation: carrier quote {qid} is referenced by tenant shipments"
                            )
                        continue
                    updated = copy.deepcopy(quote)
                    updated.pop("tenantId", None)
                    updated.pop("tenant_id", None)
                    updated.pop("isGlobal", None)
                    updated.pop("allowGlobal", None)
                    updated.pop("migratedFromTenantless", None)
                    updated["quoteHash"] = stable_hash(
                        {
                            k: updated[k]
                            for k in updated
                            if k
                            not in {
                                "quoteId",
                                "quoteHash",
                                "ownership",
                                "globalQuote",
                                "isGlobal",
                                "allowGlobal",
                                "migratedFromTenantless",
                            }
                        }
                    )
                    updated["ownership"] = "GLOBAL_REFERENCE"
                    updated["globalQuote"] = True
                    planned_updates[qid] = updated
                    marked_global.append({"quoteId": qid, "globalQuote": True})
                    continue

                target_tid: str | None = None
                source_reason = ""
                if qid in norm_assignments:
                    target_tid = norm_assignments[qid]
                    source_reason = "explicit_assignment"
                elif filter_qids is not None and qid in filter_qids and eff_default_tid is not None:
                    target_tid = eff_default_tid
                    source_reason = "explicit_quote_filter"
                elif len(ref_tenants) > 1:
                    conflict_entry = {
                        "quoteId": qid,
                        "reason": "multiple_referencing_tenants",
                        "referencedByTenants": ref_tenants,
                    }
                    conflicts.append(conflict_entry)
                    unresolved.append(conflict_entry)
                    continue
                elif len(ref_tenants) == 1 and infer_from_shipments:
                    if existing_tid is not None and ref_tenants[0] != existing_tid:
                        conflict_entry = {
                            "quoteId": qid,
                            "reason": "shipment_tenant_mismatch",
                            "targetTenantId": existing_tid,
                            "referencedByTenants": ref_tenants,
                        }
                        conflicts.append(conflict_entry)
                        unresolved.append(conflict_entry)
                        continue
                    target_tid = ref_tenants[0]
                    source_reason = "inferred_from_shipment"
                elif eff_default_tid is not None:
                    if existing_tid is not None and eff_default_tid != existing_tid:
                        conflict_entry = {
                            "quoteId": qid,
                            "reason": info["issue"] or "conflicting_tenant_and_global",
                            "tenantId": existing_tid,
                            "targetTenantId": eff_default_tid,
                            "referencedByTenants": ref_tenants,
                        }
                        conflicts.append(conflict_entry)
                        unresolved.append(conflict_entry)
                        continue
                    target_tid = eff_default_tid
                    source_reason = "default_tenant"

                if target_tid is None:
                    unresolved_entry: dict[str, Any] = {
                        "quoteId": qid,
                        "reason": (
                            info["issue"]
                            if info["metadataConflict"] and info["issue"]
                            else "no_target_tenant"
                        ),
                        "referencedByTenants": ref_tenants,
                    }
                    if existing_tid is not None:
                        unresolved_entry["tenantId"] = existing_tid
                    if info["metadataConflict"]:
                        conflicts.append(unresolved_entry)
                    unresolved.append(unresolved_entry)
                    continue

                other_ref_tenants = [t for t in ref_tenants if t != target_tid]
                if other_ref_tenants:
                    if explicit_requested:
                        raise PermissionError(
                            f"tenant isolation: carrier quote {qid} is referenced by another tenant's shipment"
                        )
                    conflict_entry = {
                        "quoteId": qid,
                        "reason": "shipment_tenant_mismatch",
                        "targetTenantId": target_tid,
                        "referencedByTenants": ref_tenants,
                    }
                    conflicts.append(conflict_entry)
                    unresolved.append(conflict_entry)
                    continue

                updated = copy.deepcopy(quote)
                updated["tenantId"] = target_tid
                updated.pop("tenant_id", None)
                updated.pop("globalQuote", None)
                updated.pop("isGlobal", None)
                updated.pop("allowGlobal", None)
                updated["quoteHash"] = stable_hash(
                    {
                        k: updated[k]
                        for k in updated
                        if k
                        not in {
                            "quoteId",
                            "quoteHash",
                            "ownership",
                            "globalQuote",
                            "isGlobal",
                            "allowGlobal",
                            "migratedFromTenantless",
                        }
                    }
                )
                updated["ownership"] = "TENANT_OWNED"
                updated["globalQuote"] = False
                if existing_tid is None or quote.get("migratedFromTenantless") is True:
                    updated["migratedFromTenantless"] = True
                else:
                    updated.pop("migratedFromTenantless", None)
                planned_updates[qid] = updated
                assigned.append(
                    {
                        "quoteId": qid,
                        "tenantId": target_tid,
                        "attribution": source_reason,
                    }
                )

            if filter_qids is None:
                # Quarantined raw records cannot be migrated until resolved; keep them visible so
                # --require-zero never passes while backup would still be BLOCKED.
                for anomaly in self._carrier_quote_anomalies:
                    anomaly_entry: dict[str, Any] = {
                        "quoteId": (
                            anomaly["quoteId"]
                            if anomaly["reason"] == "duplicate_quote_id"
                            else f"<non-object:{anomaly['rawIndex']}>"
                        ),
                        "reason": anomaly["reason"],
                        "rawIndex": anomaly["rawIndex"],
                        "recordFingerprint": anomaly["recordFingerprint"],
                    }
                    conflicts.append(anomaly_entry)
                    unresolved.append(anomaly_entry)

            if not dry_run and planned_updates:
                prev_quotes = copy.deepcopy(self.carrier_quotes)
                try:
                    for qid, updated_rec in planned_updates.items():
                        self.carrier_quotes[qid] = updated_rec
                    self.persist()
                except Exception:
                    self.carrier_quotes = prev_quotes
                    raise

            return {
                "dryRun": dry_run,
                "assignedCount": len(assigned),
                "markedGlobalCount": len(marked_global),
                "alreadyAssignedCount": len(already_assigned),
                "unresolvedCount": len(unresolved),
                "conflictCount": len(conflicts),
                "assigned": assigned,
                "markedGlobal": marked_global,
                "alreadyAssigned": already_assigned,
                "unresolved": unresolved,
                "conflicts": conflicts,
            }

    assign_tenantless_carrier_quotes = migrate_tenantless_carrier_quotes

    def repair_conflicting_carrier_quote_tenants(
        self,
        *,
        assignments: Mapping[str, str] | None = None,
        mark_global_ids: Collection[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Explicitly repair quotes with conflicting or invalid tenant fields.

        Batch migration cannot choose an owner for these records. This call names each quote.
        When the record contains usable tenant ids, the chosen tenant must be one of them.
        The original tenantId and tenant_id values are returned in preservedTenantFields and are
        not copied onto the stored quote, so a later tenant read cannot see the other claim.
        """
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run must be a boolean")

        norm_assignments: dict[str, str] = {}
        if assignments is not None:
            if not isinstance(assignments, Mapping):
                raise ValueError("assignments must be a mapping of quoteId -> tenantId")
            for raw_qid, raw_target in assignments.items():
                if not isinstance(raw_qid, str) or not raw_qid.strip():
                    raise ValueError("assignment quoteId must be a non-empty string")
                if not isinstance(raw_target, str) or not raw_target.strip():
                    raise ValueError("assignment tenantId must be a non-empty string")
                qid = raw_qid.strip()
                if qid in norm_assignments:
                    raise ValueError(f"repair tenant given twice for quoteId {qid}")
                norm_assignments[qid] = raw_target.strip()

        norm_global: list[str] = []
        if mark_global_ids is not None:
            if isinstance(mark_global_ids, str) or not isinstance(mark_global_ids, Collection):
                raise ValueError("mark_global_ids must be a collection of quoteId strings")
            for raw_qid in mark_global_ids:
                if not isinstance(raw_qid, str) or not raw_qid.strip():
                    raise ValueError("mark_global_ids elements must be non-empty strings")
                qid = raw_qid.strip()
                if qid in norm_assignments:
                    raise ValueError(f"quote {qid} given both a tenant repair and mark-global repair")
                if qid in norm_global:
                    raise ValueError(f"repair global given twice for quoteId {qid}")
                norm_global.append(qid)

        if not norm_assignments and not norm_global:
            raise ValueError("nothing to repair: pass assignments and/or mark_global_ids")

        ordered: list[tuple[str, str | None]] = [(qid, tid) for qid, tid in norm_assignments.items()]
        ordered.extend((qid, None) for qid in norm_global)

        with self._lock:
            self._sync_from_disk()
            self._refuse_quarantined_quote_ids([qid for qid, _tid in ordered])
            for qid, _tid in ordered:
                if qid not in self.carrier_quotes:
                    raise KeyError(f"carrier quote not found: {qid}")

            repaired: list[dict[str, Any]] = []
            already: list[dict[str, Any]] = []
            planned: dict[str, dict[str, Any]] = {}
            for qid, target_tid in ordered:
                quote = self.carrier_quotes[qid]
                info = classify_carrier_quote(quote)
                claimed = list(info["claimedTenantIds"])
                preserved = _raw_tenant_fields(quote)
                want_global = target_tid is None
                if info["tenantFieldConflict"]:
                    if want_global:
                        if claimed:
                            raise PermissionError(
                                f"tenant isolation: carrier quote {qid} has original tenant claims; "
                                f"{tenant_field_repair_hint(qid, claimed)}"
                            )
                        planned[qid] = _canonicalize_global_quote(quote)
                        repaired.append(
                            {
                                "quoteId": qid,
                                "tenantId": None,
                                "globalQuote": True,
                                "preservedTenantFields": preserved,
                            }
                        )
                        continue
                    if claimed and target_tid not in claimed:
                        raise PermissionError(
                            f"tenant isolation: carrier quote {qid} cannot be assigned to {target_tid}; "
                            f"{tenant_field_repair_hint(qid, claimed)}"
                        )
                    assert target_tid is not None
                    planned[qid] = _canonicalize_tenant_quote(quote, target_tid)
                    repaired.append(
                        {
                            "quoteId": qid,
                            "tenantId": target_tid,
                            "globalQuote": False,
                            "preservedTenantFields": preserved,
                        }
                    )
                    continue
                if want_global and info["explicitGlobal"]:
                    already.append({"quoteId": qid, "tenantId": None, "globalQuote": True})
                    continue
                if (
                    target_tid is not None
                    and info["validTenantOwned"]
                    and info["tenantId"] == target_tid
                ):
                    already.append({"quoteId": qid, "tenantId": target_tid, "globalQuote": False})
                    continue
                raise PermissionError(
                    f"tenant isolation: carrier quote {qid} does not have conflicting or invalid tenant fields"
                )

            if not dry_run and planned:
                prev_quotes = copy.deepcopy(self.carrier_quotes)
                try:
                    for qid, updated_rec in planned.items():
                        self.carrier_quotes[qid] = updated_rec
                    self.persist()
                except Exception:
                    self.carrier_quotes = prev_quotes
                    raise

            return {
                "dryRun": dry_run,
                "repairedCount": len(repaired),
                "alreadyRepairedCount": len(already),
                "unresolvedCount": 0,
                "repaired": repaired,
                "alreadyRepaired": already,
            }

    def unassign_migrated_carrier_quotes(
        self,
        quote_ids: list[str] | set[str] | tuple[str, ...],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Roll back quotes that were migrated from tenantless state back to unassigned tenantless state."""
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        if not isinstance(quote_ids, (list, set, tuple)) or not quote_ids:
            raise ValueError("quote_ids must be a non-empty collection of quoteId strings")
        norm_ids: list[str] = []
        for item in quote_ids:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("quote_ids elements must be non-empty strings")
            cleaned = item.strip()
            if cleaned not in norm_ids:
                norm_ids.append(cleaned)

        with self._lock:
            self._sync_from_disk()
            self._refuse_quarantined_quote_ids(norm_ids)
            for qid in norm_ids:
                if qid not in self.carrier_quotes:
                    raise KeyError(f"carrier quote not found: {qid}")
                rec = self.carrier_quotes[qid]
                if not rec.get("migratedFromTenantless"):
                    raise PermissionError(f"carrier quote {qid} was not migrated from tenantless state")

            planned: dict[str, dict[str, Any]] = {}
            rolled_back: list[dict[str, Any]] = []
            for qid in norm_ids:
                rec = copy.deepcopy(self.carrier_quotes[qid])
                prev_tid = rec.pop("tenantId", None)
                rec.pop("migratedFromTenantless", None)
                rec.pop("globalQuote", None)
                rec.pop("isGlobal", None)
                rec.pop("allowGlobal", None)
                rec["quoteHash"] = stable_hash(
                    {
                        k: rec[k]
                        for k in rec
                        if k
                        not in {
                            "quoteId",
                            "quoteHash",
                            "ownership",
                            "globalQuote",
                            "isGlobal",
                            "allowGlobal",
                            "migratedFromTenantless",
                        }
                    }
                )
                rec["ownership"] = "GLOBAL_REFERENCE"
                planned[qid] = rec
                rolled_back.append({"quoteId": qid, "previousTenantId": prev_tid})

            if not dry_run and planned:
                prev_quotes = copy.deepcopy(self.carrier_quotes)
                try:
                    for qid, updated_rec in planned.items():
                        self.carrier_quotes[qid] = updated_rec
                    self.persist()
                except Exception:
                    self.carrier_quotes = prev_quotes
                    raise

            return {
                "dryRun": dry_run,
                "rolledBackCount": len(rolled_back),
                "rolledBack": rolled_back,
            }

    def quote_stale(self, quote: dict[str, Any], *, service: str, dim_divisor: float | None = None) -> bool:
        if quote.get("service") != service:
            return True
        if dim_divisor is not None and abs(float(quote.get("dimDivisor") or 0) - float(dim_divisor)) > 1e-6:
            return True
        raw_valid = quote.get("validUntil")
        if raw_valid in (None, ""):
            valid_date = date(9999, 12, 31)
        else:
            try:
                valid_date = _parse_valid_until_date(raw_valid)
            except ValueError:
                return True
        return valid_date < utcnow().date()

    def label_payload(self, carton_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self.cartons[carton_id]
            payload = f"FOX3D:{rec['batchId']}:{rec['cartonId'][:8]}"
            return {
                "cartonId": carton_id,
                "barcode": {"symbology": "CODE128", "payload": payload, "printVerified": False, "label": "PARTIAL"},
                "qr": {"payload": payload, "printVerified": False, "label": "PARTIAL"},
                "text": {"batchId": rec["batchId"], "index": rec["index"]},
                "printerPath": None,
                "scannerPath": None,
            }

    def _checklist_idem_entry(
        self,
        tenant_id: str,
        key: Any,
        value: Any,
    ) -> tuple[str, str] | None:
        if not isinstance(key, str) or not isinstance(value, dict):
            return None
        prefix = f"{tenant_id}::checklist::"
        if not key.startswith(prefix):
            return None
        if value.get("tenantId") not in (None, tenant_id):
            return None
        wo_id = value.get("workOrderId")
        idem_key = value.get("idempotencyKey")
        if isinstance(wo_id, str) and isinstance(idem_key, str):
            return wo_id, idem_key
        chk_id = str(value.get("checklistId") or "")
        existing = self.checklists.get(chk_id)
        if isinstance(existing, dict) and existing.get("tenantId") == tenant_id:
            chk_wo = existing.get("workOrderId")
            if isinstance(chk_wo, str) and chk_wo:
                wo_prefix = f"{prefix}{chk_wo}::"
                if key.startswith(wo_prefix):
                    return chk_wo, key[len(wo_prefix) :]
        rest = key[len(prefix) :]
        legacy_wo, sep, legacy_idem = rest.partition("::")
        if sep:
            return legacy_wo, legacy_idem
        return None

    def packing_checklist(
        self,
        *,
        tenant_id: str,
        work_order_id: str,
        release_hash: str,
        idempotency_key: str | None = None,
        signature: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            cartons = [
                c
                for c in self.cartons.values()
                if c["workOrderId"] == work_order_id and c.get("tenantId") == tenant_id
            ]
            cartons.sort(key=lambda c: (int(c.get("index") or 0), str(c.get("cartonId") or "")))
            items = [
                {
                    "cartonId": c["cartonId"],
                    "expected": c.get("expected"),
                    "measured": c.get("measured"),
                    "mismatch": bool(c.get("mismatch")),
                }
                for c in cartons
            ]
            pinned = bool(cartons) and all(c.get("releaseHash") == release_hash for c in cartons)
            eff_sig = signature or stable_hash({"releaseHash": release_hash, "items": items})
            store_key: str | None = None
            if idempotency_key:
                candidate_key = f"{tenant_id}::checklist::{work_order_id}::{idempotency_key}"
                if candidate_key in self._idem and not isinstance(self._idem[candidate_key], dict):
                    raise SemanticKeyConflictError("packing checklist idempotency conflict")
                matched_value: dict[str, Any] | None = None
                for k, v in self._idem.items():
                    parsed = self._checklist_idem_entry(tenant_id, k, v)
                    if parsed is None:
                        continue
                    entry_wo_id, entry_idem_key = parsed
                    if entry_idem_key != idempotency_key:
                        continue
                    if entry_wo_id != work_order_id:
                        raise SemanticKeyConflictError("packing checklist idempotency conflict")
                    matched_value = v
                    break
                if matched_value is not None:
                    if matched_value.get("signature") != eff_sig:
                        raise SemanticKeyConflictError("packing checklist idempotency conflict")
                    chk_id = str(matched_value.get("checklistId") or "")
                    existing = self.checklists.get(chk_id)
                    if (
                        existing is None
                        or existing.get("tenantId") != tenant_id
                        or existing.get("workOrderId") != work_order_id
                    ):
                        raise SemanticKeyConflictError("packing checklist idempotency conflict")
                    return existing
                if candidate_key not in self._idem:
                    store_key = candidate_key
                else:
                    store_key = (
                        f"{tenant_id}::checklist::{json.dumps([work_order_id, idempotency_key], ensure_ascii=False)}"
                    )
            rec: dict[str, Any] = {
                "checklistId": new_id(),
                "tenantId": tenant_id,
                "workOrderId": work_order_id,
                "releaseHash": release_hash,
                "pinned": pinned,
                "items": items,
                "mismatchHold": any(bool(c.get("mismatch")) for c in cartons),
                "autoOverride": False,
                "truthLabel": "REAL_LOGIC",
                "carrierProvider": "BLOCKED/NOT_CONNECTED",
            }
            rec["checklistHash"] = stable_hash({k: rec[k] for k in rec if k != "checklistHash"})
            self.checklists[rec["checklistId"]] = rec
            if store_key is not None:
                self._idem[store_key] = {
                    "tenantId": tenant_id,
                    "workOrderId": work_order_id,
                    "idempotencyKey": idempotency_key,
                    "signature": eff_sig,
                    "checklistId": rec["checklistId"],
                }
            try:
                emit(
                    self,
                    "packing.checklist",
                    tenant_id=tenant_id,
                    aggregate_type="PackingChecklist",
                    aggregate_id=rec["checklistId"],
                    actor="ops",
                    payload={"workOrderId": work_order_id, "pinned": pinned},
                    release_hash=release_hash,
                    semantic_key=f"{tenant_id}::pack-check::{work_order_id}::{release_hash}::{rec['checklistId']}",
                )
            except Exception:
                if self.root and (self.root / "logistics.json").exists():
                    self.load()
                else:
                    self.checklists.pop(rec["checklistId"], None)
                    if store_key is not None:
                        self._idem.pop(store_key, None)
                raise
            return rec

    def shipment_handoff(
        self,
        shipment_id: str,
        *,
        tenant_id: str,
        carrier: str,
        tracking: str,
        actor: str,
    ) -> dict[str, Any]:
        with self._lock:
            rec = self.shipments[shipment_id]
            if rec.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: shipment")
            key = f"{tenant_id}::handoff::{tracking}"
            if key in self._idem:
                hid = self._idem[key]
                existing = self.handoffs.get(hid)
                if existing is None:
                    raise PermissionError("idempotency namespace collision: handoff")
                if existing.get("tenantId") != tenant_id:
                    raise PermissionError("tenant isolation: handoff")
                if existing.get("shipmentId") != shipment_id:
                    raise SemanticKeyConflictError("tracking already bound to another shipment")
                return rec
            prior_handoff = rec.get("handoff")
            if isinstance(prior_handoff, dict) and prior_handoff.get("tracking") != tracking:
                raise SemanticKeyConflictError("shipment already handed off with different tracking")
            prev_snapshot = copy.deepcopy(rec)
            handoff: dict[str, Any] = {
                "handoffId": new_id(),
                "shipmentId": shipment_id,
                "tenantId": tenant_id,
                "carrier": carrier,
                "tracking": tracking,
                "actor": actor,
                "at": _now(),
                "source": "MANUAL",
                "truthLabel": "MANUAL/IMPORTED",
                "liveProvider": False,
                "booked": False,
                "submittedToCarrier": False,
                "deliveryConfirmed": False,
                "status": "HANDED_OFF_MANUAL",
            }
            rec["handoff"] = handoff
            rec["status"] = "HANDED_OFF_MANUAL"
            rec["booked"] = False
            rec["submittedToCarrier"] = False
            rec["shipped"] = False
            rec["liveCarrier"] = False
            self.handoffs[handoff["handoffId"]] = handoff
            self._idem[key] = handoff["handoffId"]
            try:
                emit(
                    self,
                    "shipment.handoff",
                    tenant_id=tenant_id,
                    aggregate_type="Shipment",
                    aggregate_id=shipment_id,
                    actor=actor,
                    payload={"carrier": carrier, "tracking": tracking, "liveProvider": False, "deliveryConfirmed": False},
                    semantic_key=key,
                )
            except Exception:
                if self.root and (self.root / "logistics.json").exists():
                    self.load()
                else:
                    self.shipments[shipment_id] = prev_snapshot
                    self.handoffs.pop(handoff["handoffId"], None)
                    self._idem.pop(key, None)
                raise
            return rec


def _resolve_logistics_service(target: Any) -> LogisticsService:
    if isinstance(target, LogisticsService):
        return target
    if hasattr(target, "pilot") and hasattr(target.pilot, "logistics"):
        return target.pilot.logistics  # type: ignore[no-any-return]
    if hasattr(target, "logistics") and isinstance(target.logistics, LogisticsService):
        return target.logistics
    if isinstance(target, (str, Path)):
        p = Path(target)
        if p.name == "logistics.json":
            return LogisticsService(root=p.parent)
        if (p / "logistics" / "logistics.json").exists() or (p / "logistics").is_dir():
            return LogisticsService(root=p / "logistics")
        if (p / "logistics.json").exists():
            return LogisticsService(root=p)
        return LogisticsService(root=p / "logistics" if not p.name == "logistics" else p)
    raise TypeError(f"cannot resolve LogisticsService from {type(target).__name__}")


def inspect_tenantless_carrier_quotes(
    target: Any,
    *,
    include_explicit_global: bool = False,
) -> dict[str, Any]:
    svc = _resolve_logistics_service(target)
    return svc.inspect_tenantless_carrier_quotes(include_explicit_global=include_explicit_global)


def migrate_tenantless_carrier_quotes(
    target: Any,
    *,
    tenant_id: str | None = None,
    default_tenant_id: str | None = None,
    assignments: Mapping[str, str] | None = None,
    quote_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    infer_from_shipments: bool = True,
    mark_global: bool = False,
    include_explicit_global: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    svc = _resolve_logistics_service(target)
    return svc.migrate_tenantless_carrier_quotes(
        tenant_id=tenant_id,
        default_tenant_id=default_tenant_id,
        assignments=assignments,
        quote_ids=quote_ids,
        infer_from_shipments=infer_from_shipments,
        mark_global=mark_global,
        include_explicit_global=include_explicit_global,
        dry_run=dry_run,
    )


def unassign_migrated_carrier_quotes(
    target: Any,
    quote_ids: list[str] | set[str] | tuple[str, ...],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    svc = _resolve_logistics_service(target)
    return svc.unassign_migrated_carrier_quotes(quote_ids, dry_run=dry_run)


def repair_conflicting_carrier_quote_tenants(
    target: Any,
    *,
    assignments: Mapping[str, str] | None = None,
    mark_global_ids: Collection[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    svc = _resolve_logistics_service(target)
    return svc.repair_conflicting_carrier_quote_tenants(
        assignments=assignments,
        mark_global_ids=mark_global_ids,
        dry_run=dry_run,
    )


def resolve_carrier_quote_records(
    target: Any,
    *,
    keep: Mapping[str, str] | None = None,
    drop: list[str] | set[str] | tuple[str, ...] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    svc = _resolve_logistics_service(target)
    return svc.resolve_carrier_quote_records(keep=keep, drop=drop, dry_run=dry_run)


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or migrate legacy tenantless carrier quotes in logistics.json.",
    )
    parser.add_argument("--root", required=True, help="Data root directory (.fox3d-data, logistics/, or logistics.json)")
    parser.add_argument(
        "--check",
        "--list",
        dest="check_only",
        action="store_true",
        help="Only inspect and list tenantless carrier quotes without modifying anything",
    )
    parser.add_argument(
        "--require-zero",
        action="store_true",
        help="Pre-deployment check: exit with code 1 if tenantlessCount > 0 (or unresolvedCount > 0)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute migration result without writing to disk")
    parser.add_argument("--tenant", "--default-tenant", dest="tenant_id", default=None, help="Default target tenant ID")
    parser.add_argument(
        "--assign",
        action="append",
        default=[],
        metavar="QUOTE_ID=TENANT_ID",
        help="Explicit quoteId=tenantId assignment (repeatable)",
    )
    parser.add_argument(
        "--quote-id",
        action="append",
        default=[],
        dest="quote_ids",
        help="Specific quoteId to migrate (repeatable)",
    )
    parser.add_argument("--no-infer", action="store_true", help="Do not infer tenant from referencing shipments")
    parser.add_argument("--mark-global", action="store_true", help="Mark tenantless quotes as explicitly global")
    parser.add_argument(
        "--repair-tenant",
        action="append",
        default=[],
        dest="repair_tenants",
        metavar="QUOTE_ID=TENANT_ID",
        help=(
            "Repair one quote with conflicting or invalid tenant fields by keeping an original claimed tenant. "
            "Original tenant fields are printed in preservedTenantFields and removed from the stored quote."
        ),
    )
    parser.add_argument(
        "--repair-global",
        action="append",
        default=[],
        dest="repair_global_ids",
        metavar="QUOTE_ID",
        help=(
            "Repair one quote whose tenant fields are invalid and name no tenant, marking it explicitly global. "
            "Refused when the quote still has a usable tenant id."
        ),
    )
    parser.add_argument(
        "--include-explicit-global",
        action="store_true",
        help="Also include quotes already marked as explicit global",
    )
    parser.add_argument(
        "--unassign",
        action="append",
        default=[],
        dest="unassign_ids",
        help="Roll back a quoteId that was previously migrated from tenantless state",
    )
    parser.add_argument(
        "--keep-duplicate",
        action="append",
        default=[],
        dest="keep_duplicates",
        metavar="QUOTE_ID=FINGERPRINT",
        help="Resolve a duplicated quoteId by keeping the record with this recordFingerprint (repeatable)",
    )
    parser.add_argument(
        "--drop-invalid",
        action="append",
        default=[],
        dest="drop_invalid",
        metavar="FINGERPRINT",
        help="Remove a non-object carrier_quotes entry identified by its recordFingerprint (repeatable)",
    )
    args = parser.parse_args(argv)

    svc = _resolve_logistics_service(Path(args.root))
    if args.repair_tenants or args.repair_global_ids:
        if (
            args.check_only
            or args.unassign_ids
            or args.keep_duplicates
            or args.drop_invalid
            or args.assign
            or args.quote_ids
            or args.tenant_id
            or args.mark_global
            or args.no_infer
            or args.include_explicit_global
        ):
            parser.error("repair flags cannot be combined with check, migrate, unassign, or record-resolution flags")
        repair_assignments: dict[str, str] = {}
        for item in args.repair_tenants:
            if "=" not in item:
                parser.error(f"invalid --repair-tenant {item!r}, expected QUOTE_ID=TENANT_ID")
            qid, tid = item.split("=", 1)
            qid = qid.strip()
            tid = tid.strip()
            if not qid or not tid:
                parser.error(f"invalid --repair-tenant {item!r}, expected QUOTE_ID=TENANT_ID")
            if qid in repair_assignments:
                parser.error(f"--repair-tenant given twice for quoteId {qid!r}")
            repair_assignments[qid] = tid
        repair_globals: list[str] = []
        for item in args.repair_global_ids:
            qid = item.strip()
            if not qid:
                parser.error("invalid --repair-global, expected a quoteId")
            if qid in repair_assignments:
                parser.error(f"{qid!r} given both --repair-tenant and --repair-global")
            if qid in repair_globals:
                parser.error(f"--repair-global given twice for quoteId {qid!r}")
            repair_globals.append(qid)
        result = svc.repair_conflicting_carrier_quote_tenants(
            assignments=repair_assignments or None,
            mark_global_ids=repair_globals or None,
            dry_run=bool(args.dry_run),
        )
        if args.require_zero:
            # The repair names specific quotes. Other legacy quotes must still fail the pre-deployment gate.
            remaining = svc.inspect_tenantless_carrier_quotes()
            result = dict(result)
            result["remainingTenantlessCount"] = remaining["tenantlessCount"]
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.require_zero and int(result.get("remainingTenantlessCount") or 0) > 0:
            return 1
        return 0

    if args.keep_duplicates or args.drop_invalid:
        keep_map: dict[str, str] = {}
        for item in args.keep_duplicates:
            if "=" not in item:
                parser.error(f"invalid --keep-duplicate {item!r}, expected QUOTE_ID=FINGERPRINT")
            qid, fp = item.split("=", 1)
            if qid.strip() in keep_map:
                parser.error(f"--keep-duplicate given twice for quoteId {qid.strip()!r}")
            keep_map[qid.strip()] = fp.strip()
        result = svc.resolve_carrier_quote_records(
            keep=keep_map or None,
            drop=list(args.drop_invalid) or None,
            dry_run=bool(args.dry_run),
        )
        if args.require_zero:
            result["remainingTenantlessCount"] = svc.inspect_tenantless_carrier_quotes()["tenantlessCount"]
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.require_zero and result["remainingTenantlessCount"] > 0:
            return 1
        return 0

    if args.unassign_ids:
        result = svc.unassign_migrated_carrier_quotes(args.unassign_ids, dry_run=bool(args.dry_run))
        if args.require_zero:
            result["remainingTenantlessCount"] = svc.inspect_tenantless_carrier_quotes()["tenantlessCount"]
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.require_zero and result["remainingTenantlessCount"] > 0:
            return 1
        return 0

    if args.check_only:
        result = svc.inspect_tenantless_carrier_quotes(
            include_explicit_global=bool(args.include_explicit_global),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.require_zero and int(result.get("tenantlessCount") or 0) > 0:
            return 1
        return 0

    parsed_assignments: dict[str, str] = {}
    for item in args.assign:
        if "=" not in item:
            raise ValueError(f"invalid --assign {item!r}, expected QUOTE_ID=TENANT_ID")
        qid, tid = item.split("=", 1)
        parsed_assignments[qid.strip()] = tid.strip()

    result = svc.migrate_tenantless_carrier_quotes(
        tenant_id=args.tenant_id,
        assignments=parsed_assignments if parsed_assignments else None,
        quote_ids=args.quote_ids if args.quote_ids else None,
        infer_from_shipments=not bool(args.no_infer),
        mark_global=bool(args.mark_global),
        include_explicit_global=bool(args.include_explicit_global),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.require_zero and int(result.get("unresolvedCount") or 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
