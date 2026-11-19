"""Supplier / material / logistics provider gateway. Not an ERP/WMS."""

from __future__ import annotations

import csv
import io
import json
from contextlib import contextmanager
from datetime import datetime, time, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Mapping, Protocol

from filelock import FileLock

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json

PROVIDER_BY_KIND = {
    "material": "SupplierPriceProvider",
    "hardware": "HardwarePriceProvider",
    "packaging": "PackagingPriceProvider",
    "logistics": "LogisticsRateProvider",
    "fx": "FxRateProvider",
}


class PriceProvider(Protocol):
    kind: str

    def snapshot(self, **kwargs: Any) -> dict[str, Any] | None: ...


def _row_hash(row: dict[str, Any]) -> str:
    return stable_hash({k: row[k] for k in row if k not in {"snapshotId", "snapshotHash"}})


class ImportValidationError(ValueError):
    """Invalid provider import input."""


class ProviderDisconnectedError(PermissionError):
    """The requested live provider is not connected."""


# Files written before tenant stamping have no formatVersion. Their rows kept whatever
# tenantId the caller sent, so none of them has a trustworthy owner.
SNAPSHOT_FORMAT_VERSION = 2


def _quarantine_legacy_row(row: dict[str, Any]) -> dict[str, Any]:
    rec = dict(row)
    claimed = rec.pop("tenantId", None)
    if claimed is not None and "claimedTenantId" not in rec:
        rec["claimedTenantId"] = claimed
    return rec


def _snapshot_key(row: dict[str, Any]) -> str | tuple[str, str]:
    tenant = row.get("tenantId")
    return (tenant, row["snapshotId"]) if isinstance(tenant, str) and tenant else row["snapshotId"]


def _instant(value: str, *, end_of_day: bool = False) -> datetime:
    # Naive timestamps and dates are UTC; date-only expirations include the whole day.
    if not isinstance(value, str):
        raise ValueError("Invalid snapshot timestamp")
    if len(value) == 10:
        day = datetime.strptime(value, "%Y-%m-%d").date()
        return datetime.combine(day, time.max if end_of_day else time.min, tzinfo=timezone.utc)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


class SnapshotStore:
    def __init__(self, root: Path | None = None, *, kind: str) -> None:
        self.kind = kind
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.items: dict[str | tuple[str, str], dict[str, Any]] = {}
        # Pre-upgrade rows of unknown ownership. Never returned by active() or get().
        self.legacy: dict[str, dict[str, Any]] = {}
        self._legacy_unkeyed: list[Any] = []
        self._lock = RLock()
        self._file_lock = FileLock(str((self.root / f"{self.kind}.lock").resolve())) if self.root else None
        self.load()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._lock:
            if self._file_lock is None:
                yield
            else:
                with self._file_lock:
                    yield

    def load(self) -> None:
        with self._locked():
            self._load()

    def _load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / f"{self.kind}.json") or {}
        if not isinstance(payload, dict):
            payload = {}
        if payload.get("formatVersion") == SNAPSHOT_FORMAT_VERSION:
            trusted = payload.get("items") or []
            legacy_rows = payload.get("legacyItems") or []
        else:
            trusted, legacy_rows = [], payload.get("items") or []
        self.items = {_snapshot_key(r): r for r in trusted}
        self.legacy = {}
        self._legacy_unkeyed = []
        for row in legacy_rows:
            if isinstance(row, dict) and isinstance(row.get("snapshotId"), str):
                self.legacy[row["snapshotId"]] = _quarantine_legacy_row(row)
            else:
                # Kept verbatim so a later write does not drop data an operator may need.
                self._legacy_unkeyed.append(row)

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(
            self.root / f"{self.kind}.json",
            {
                "kind": self.kind,
                "formatVersion": SNAPSHOT_FORMAT_VERSION,
                "items": list(self.items.values()),
                "legacyItems": [*self.legacy.values(), *self._legacy_unkeyed],
            },
        )

    def add(self, row: dict[str, Any], *, source: str) -> dict[str, Any]:
        return self.add_many([row], source=source)[0]

    def add_many(self, rows: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ImportValidationError("rows must be a list of objects")
        if any(row.get("snapshotId") is not None and not isinstance(row["snapshotId"], str) for row in rows):
            raise ImportValidationError("snapshotId must be a string")
        if not rows:
            return []
        records = []
        for row in rows:
            rec = dict(row)
            rec["snapshotId"] = rec.get("snapshotId") or new_id()
            rec["kind"] = self.kind
            rec["source"] = source
            rec["importedAt"] = utcnow().isoformat()
            rec["liveProvider"] = source == "LIVE_PROVIDER"
            rec["snapshotHash"] = _row_hash(rec)
            records.append(rec)
        with self._locked():
            self._load()
            previous = self.items
            self.items = {**previous, **{_snapshot_key(rec): rec for rec in records}}
            try:
                self.persist()
            except Exception:
                self.items = previous
                raise
        return records

    def assign_legacy(self, snapshot_ids: list[str], *, tenant_id: str) -> int:
        """Assign explicitly identified quarantined records under the store lock; never overwrite.

        Only rows from pre-upgrade files are eligible. Their stored tenantId was supplied by
        the importer, so the owner must come from an independent, trusted source.
        """
        if not isinstance(tenant_id, str) or not tenant_id or not snapshot_ids or len(set(snapshot_ids)) != len(snapshot_ids):
            raise ValueError("A tenant and unique snapshot IDs are required")
        with self._locked():
            self._load()
            if any(sid not in self.legacy or (tenant_id, sid) in self.items for sid in snapshot_ids):
                raise ValueError("Legacy snapshot missing or destination already exists")
            previous_items, previous_legacy = self.items, self.legacy
            self.items, self.legacy = dict(previous_items), dict(previous_legacy)
            for sid in snapshot_ids:
                row = dict(self.legacy.pop(sid))
                row["tenantId"] = tenant_id
                row["snapshotHash"] = _row_hash(row)
                self.items[(tenant_id, sid)] = row
            try:
                self.persist()
            except Exception:
                self.items, self.legacy = previous_items, previous_legacy
                raise
            return len(snapshot_ids)

    def quarantined(self) -> list[dict[str, Any]]:
        """Pre-upgrade rows awaiting a trusted ownership decision (maintenance use only)."""
        with self._locked():
            self._load()
            return [dict(row) for row in self.legacy.values()]

    def get(self, snapshot_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        """Exact lookup. A tenant sees only its own rows; no tenant sees only unscoped rows."""
        if not isinstance(snapshot_id, str) or not snapshot_id:
            return None
        if tenant_id is not None and (not isinstance(tenant_id, str) or not tenant_id):
            return None
        key: str | tuple[str, str] = (tenant_id, snapshot_id) if tenant_id else snapshot_id
        with self._locked():
            self._load()
            row = self.items.get(key)
        return dict(row) if row is not None else None

    def active(self, *, at: str | None = None) -> list[dict[str, Any]]:
        with self._locked():
            self._load()
            rows = list(self.items.values())
        if at:
            moment = _instant(at)
            def valid(row: dict[str, Any]) -> bool:
                try:
                    start, end = row.get("effectiveAt"), row.get("expiresAt")
                    return (start in (None, "") or _instant(start) <= moment) and (end in (None, "") or _instant(end, end_of_day=True) >= moment)
                except (ValueError, TypeError, OverflowError):
                    return False
            rows = [r for r in rows if valid(r)]
        return rows


class ProviderRegistry:
    def __init__(self, root: Path | None = None) -> None:
        base = Path(root) if root else None
        self.material = SnapshotStore(base, kind="material")
        self.hardware = SnapshotStore(base, kind="hardware")
        self.packaging = SnapshotStore(base, kind="packaging")
        self.logistics = SnapshotStore(base, kind="logistics")
        self.fx = SnapshotStore(base, kind="fx")
        self.live = {
            "SupplierPriceProvider": False,
            "HardwarePriceProvider": False,
            "PackagingPriceProvider": False,
            "LogisticsRateProvider": False,
            "FxRateProvider": False,
        }

    def import_rows(self, store: SnapshotStore, rows: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
        if source not in {"IMPORTED", "MANUAL", "LIVE_PROVIDER", "CONFIG_ESTIMATE"}:
            raise ImportValidationError("Unknown import source")
        if source == "LIVE_PROVIDER":
            provider = PROVIDER_BY_KIND.get(store.kind)
            if provider is None or not self.live.get(provider, False):
                raise ProviderDisconnectedError(f"Live provider is not connected for {store.kind}")
        return store.add_many(rows, source=source)

    def import_csv(self, store: SnapshotStore, text: str, *, source: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(text))
        return self.import_rows(store, [dict(r) for r in reader], source=source)

    def import_json(self, store: SnapshotStore, text: str, *, source: str) -> list[dict[str, Any]]:
        payload = json.loads(text)
        rows = payload if isinstance(payload, list) else payload.get("items") or payload.get("rows") or []
        return self.import_rows(store, rows, source=source)


def mixed_landed_cost(
    components: list[dict[str, Any]], *, live: Mapping[str, bool] | None = None
) -> dict[str, Any]:
    """Label live components only when their kind's provider is connected."""
    total = 0.0
    labeled = []
    for c in components:
        amt = float(c.get("amount") or 0)
        src = str(c.get("source") or "CONFIG_ESTIMATE")
        if src not in {"REAL_IMPORTED", "MANUAL", "CONFIG_ESTIMATE", "LIVE_PROVIDER", "IMPORTED"}:
            src = "CONFIG_ESTIMATE"
        if src == "LIVE_PROVIDER":
            kind = c.get("kind")
            provider = PROVIDER_BY_KIND.get(kind) if isinstance(kind, str) else None
            if provider is None or live is None or live.get(provider) is not True:
                src = "CONFIG_ESTIMATE"
        labeled.append({**c, "source": src, "amount": round(amt, 2)})
        total += amt
    sources = sorted({c["source"] for c in labeled})
    return {
        "components": labeled,
        "total": round(total, 2),
        "sources": sources,
        "mixed": len(sources) > 1,
        "truthLabel": "MIXED" if len(sources) > 1 else sources[0] if sources else "CONFIG_ESTIMATE",
        "notSingleReal": True,
        "liveProviderReady": "LIVE_PROVIDER" in sources,
    }


def quote_binding(entity: dict[str, Any], *, snapshot_ids: list[str], valid_from: str, valid_to: str) -> dict[str, Any]:
    lin = entity.get("lineage") or {}
    rec = {
        "quoteId": new_id(),
        "engineeringHash": entity.get("engineeringHash") or lin.get("engineeringHash"),
        "bomHash": (entity.get("bom") or {}).get("bomHash") or lin.get("bomHash"),
        "nestingHash": (entity.get("nesting") or {}).get("nestingHash") or lin.get("nestingHash"),
        "providerSnapshotIds": list(snapshot_ids),
        "validFrom": valid_from,
        "validTo": valid_to,
        "stale": False,
    }
    rec["quoteBindingHash"] = stable_hash({k: v for k, v in rec.items() if k != "quoteId"})
    return rec


def quote_stale(binding: dict[str, Any], entity: dict[str, Any], *, now: str, snapshot_ids: list[str] | None = None) -> bool:
    lin = entity.get("lineage") or {}
    if binding.get("engineeringHash") != (entity.get("engineeringHash") or lin.get("engineeringHash")):
        return True
    if binding.get("bomHash") != ((entity.get("bom") or {}).get("bomHash") or lin.get("bomHash")):
        return True
    if binding.get("nestingHash") != ((entity.get("nesting") or {}).get("nestingHash") or lin.get("nestingHash")):
        return True
    if now < str(binding.get("validFrom") or "") or now > str(binding.get("validTo") or "9999"):
        return True
    if snapshot_ids is not None and list(binding.get("providerSnapshotIds") or []) != list(snapshot_ids):
        return True
    return False


def supplier_alternatives(
    spec: dict[str, Any],
    snapshots: list[dict[str, Any]],
    *,
    thickness: float,
    material_code: str,
) -> dict[str, Any]:
    compatible = []
    vetoed = []
    for s in snapshots:
        t = float(s.get("thickness") or 0)
        code = str(s.get("materialCode") or s.get("material") or "")
        if abs(t - thickness) > 0.5 or (code and code.upper() not in {material_code.upper(), str(spec.get("material") or "").upper()}):
            vetoed.append({"snapshotId": s.get("snapshotId"), "reason": "ENGINEERING_INCOMPATIBLE", "veto": True})
            continue
        compatible.append({"snapshotId": s.get("snapshotId"), "price": s.get("price"), "supplier": s.get("supplier"), "source": s.get("source")})
    return {
        "compatible": compatible,
        "vetoed": vetoed,
        "autoReplaceForbidden": True,
        "engineeringVeto": True,
        "specMaterial": spec.get("material"),
    }
