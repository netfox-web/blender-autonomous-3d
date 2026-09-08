"""Supplier / material / logistics provider gateway. Not an ERP/WMS."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Protocol

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json


class PriceProvider(Protocol):
    kind: str

    def snapshot(self, **kwargs: Any) -> dict[str, Any] | None: ...


def _row_hash(row: dict[str, Any]) -> str:
    return stable_hash({k: row[k] for k in row if k not in {"snapshotId", "snapshotHash"}})


class SnapshotStore:
    def __init__(self, root: Path | None = None, *, kind: str) -> None:
        self.kind = kind
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.items: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        payload = read_json(self.root / f"{self.kind}.json") or {}
        self.items = {r["snapshotId"]: r for r in payload.get("items") or []}

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(self.root / f"{self.kind}.json", {"kind": self.kind, "items": list(self.items.values())})

    def add(self, row: dict[str, Any], *, source: str) -> dict[str, Any]:
        rec = dict(row)
        rec["snapshotId"] = rec.get("snapshotId") or new_id()
        rec["kind"] = self.kind
        rec["source"] = source
        rec["importedAt"] = utcnow().isoformat()
        rec["liveProvider"] = source == "LIVE_PROVIDER"
        rec["snapshotHash"] = _row_hash(rec)
        self.items[rec["snapshotId"]] = rec
        self.persist()
        return rec

    def active(self, *, at: str | None = None) -> list[dict[str, Any]]:
        rows = list(self.items.values())
        if at:
            rows = [r for r in rows if str(r.get("effectiveAt") or "") <= at and (not r.get("expiresAt") or str(r["expiresAt"]) >= at)]
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
            raise ValueError(source)
        return [store.add(r, source=source) for r in rows]

    def import_csv(self, store: SnapshotStore, text: str, *, source: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(text))
        return self.import_rows(store, [dict(r) for r in reader], source=source)

    def import_json(self, store: SnapshotStore, text: str, *, source: str) -> list[dict[str, Any]]:
        payload = json.loads(text)
        rows = payload if isinstance(payload, list) else payload.get("items") or payload.get("rows") or []
        return self.import_rows(store, rows, source=source)


def mixed_landed_cost(components: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0.0
    labeled = []
    for c in components:
        amt = float(c.get("amount") or 0)
        src = str(c.get("source") or "CONFIG_ESTIMATE")
        if src not in {"REAL_IMPORTED", "MANUAL", "CONFIG_ESTIMATE", "LIVE_PROVIDER", "IMPORTED"}:
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
    rec["quoteBindingHash"] = stable_hash(rec)
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
