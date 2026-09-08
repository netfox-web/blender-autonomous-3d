"""Durable remnant / material-lot inventory.

Not a second WMS. RemnantStore is the persistence port for RemnantInventory.
In-memory behaviour stays compatible; durable JSON lives under `.fox3d-data`.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow

QUALITY_STATES = ("available", "reserved", "consumed", "quarantined", "damaged")
QUALITY_UPPER = {
    "available": "AVAILABLE",
    "reserved": "RESERVED",
    "consumed": "CONSUMED",
    "quarantined": "QUARANTINED",
    "damaged": "DAMAGED",
}
AUTO_NEST_BLOCKED = frozenset({"quarantined", "damaged", "consumed"})
DEFAULT_LEASE_SECONDS = 3600.0


def _now_iso() -> str:
    return utcnow().isoformat()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_status(status: str | None) -> str:
    if not status:
        return "available"
    s = str(status).strip().lower()
    aliases = {"available": "available", "reserved": "reserved", "consumed": "consumed", "quarantined": "quarantined", "damaged": "damaged"}
    return aliases.get(s, s)


def nestable(rec: dict[str, Any]) -> bool:
    return normalize_status(rec.get("status")) not in AUTO_NEST_BLOCKED


class RemnantStore(Protocol):
    def put(self, rec: dict[str, Any]) -> dict[str, Any]: ...
    def get(self, remnant_id: str, *, tenant_id: str) -> dict[str, Any]: ...
    def list(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]: ...
    def as_dict(self) -> dict[str, dict[str, Any]]: ...
    def persist(self) -> None: ...
    def load(self) -> None: ...


class InMemoryRemnantStore:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return self._items

    def put(self, rec: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._items[rec["remnantId"]] = rec
            return rec

    def get(self, remnant_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self._items[remnant_id]
        if rec.get("tenantId") not in {None, tenant_id}:
            raise PermissionError(f"tenant isolation: remnant {remnant_id}")
        return rec

    def list(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        rows = [v for v in self._items.values() if v.get("tenantId") in {None, tenant_id}]
        if status:
            want = normalize_status(status)
            rows = [r for r in rows if normalize_status(r.get("status")) == want]
        return rows

    def persist(self) -> None:
        return None

    def load(self) -> None:
        return None


class DurableRemnantStore:
    """JSON files under root/{tenantId}.json. Survives process restart."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.load()

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return self._items

    def _tenant_path(self, tenant_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in tenant_id)
        return self.root / f"{safe}.json"

    def load(self) -> None:
        with self._lock:
            self._items.clear()
            for path in sorted(self.root.glob("*.json")):
                payload = read_json(path) or {}
                for rec in (payload.get("items") or []):
                    self._items[rec["remnantId"]] = rec

    def persist(self) -> None:
        with self._lock:
            by_tenant: dict[str, list[dict[str, Any]]] = {}
            for rec in self._items.values():
                tid = str(rec.get("tenantId") or "default")
                by_tenant.setdefault(tid, []).append(rec)
            written = set()
            for tid, items in by_tenant.items():
                atomic_write_json(
                    self._tenant_path(tid),
                    {"tenantId": tid, "kind": "remnant-store", "count": len(items), "items": items},
                )
                written.add(self._tenant_path(tid))
            for path in self.root.glob("*.json"):
                if path not in written:
                    path.unlink(missing_ok=True)

    def put(self, rec: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._items[rec["remnantId"]] = rec
            self.persist()
            return rec

    def get(self, remnant_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self._items[remnant_id]
        if rec.get("tenantId") not in {None, tenant_id}:
            raise PermissionError(f"tenant isolation: remnant {remnant_id}")
        return rec

    def list(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        rows = [v for v in self._items.values() if v.get("tenantId") in {None, tenant_id}]
        if status:
            want = normalize_status(status)
            rows = [r for r in rows if normalize_status(r.get("status")) == want]
        return rows


class MaterialLotRegistry:
    """Sheet lots with lineage. CONFIG cost snapshot, not a supplier live feed."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.lots: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        if not self.root:
            return
        path = self.root / "lots.json"
        payload = read_json(path) or {}
        self.lots = {rec["lotId"]: rec for rec in payload.get("lots") or []}

    def persist(self) -> None:
        if not self.root:
            return
        atomic_write_json(self.root / "lots.json", {"lots": list(self.lots.values())})

    def create(
        self,
        *,
        tenant_id: str,
        material: str,
        thickness: float,
        length: float = 2440,
        width: float = 1220,
        grain: str = "length",
        supplier_lot: str | None = None,
        cost_per_sheet: float = 850.0,
        sheet_count: int = 1,
    ) -> dict[str, Any]:
        rec = {
            "lotId": new_id(),
            "tenantId": tenant_id,
            "supplierLot": supplier_lot or "CONFIG-LOT",
            "receivedAt": _now_iso(),
            "material": material,
            "thickness": thickness,
            "grain": grain,
            "length": length,
            "width": width,
            "sheetDimensions": [length, width, thickness],
            "configCostSnapshot": {"costPerSheet": cost_per_sheet, "source": "CONFIG"},
            "sheetCount": sheet_count,
            "remainingSheets": sheet_count,
            "version": 1,
        }
        rec["lotHash"] = stable_hash({k: rec[k] for k in rec if k not in {"lotHash"}})
        with self._lock:
            self.lots[rec["lotId"]] = rec
            self.persist()
        return rec

    def get(self, lot_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.lots[lot_id]
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: material lot")
        return rec

    def allocate_sheet(self, lot_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.get(lot_id, tenant_id=tenant_id)
        if int(rec.get("remainingSheets") or 0) <= 0:
            raise PermissionError(f"lot {lot_id} exhausted")
        rec["remainingSheets"] = int(rec["remainingSheets"]) - 1
        rec["version"] = int(rec.get("version") or 1) + 1
        self.persist()
        return rec

    def list(self, *, tenant_id: str) -> list[dict[str, Any]]:
        return [v for v in self.lots.values() if v.get("tenantId") == tenant_id]


def remnant_value(rec: dict[str, Any], *, cost_per_m2: float = 280.0, now_iso: str | None = None) -> dict[str, Any]:
    w = float(rec.get("w") or 0)
    h = float(rec.get("h") or 0)
    area_m2 = (w * h) / 1e6
    short = max(min(w, h), 1.0)
    aspect = max(w, h) / short
    usability = round(1.0 / (1.0 + max(0.0, aspect - 2.0) * 0.15), 4)
    age_days = 0.0
    created = rec.get("createdAt")
    if created:
        try:
            from datetime import datetime

            then = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            now = datetime.fromisoformat((now_iso or _now_iso()).replace("Z", "+00:00"))
            age_days = max(0.0, (now - then).total_seconds() / 86400.0)
        except ValueError:
            age_days = 0.0
    age_factor = max(0.5, 1.0 - min(age_days, 180.0) / 180.0 * 0.5)
    value = area_m2 * float(cost_per_m2) * usability * age_factor
    return {
        "areaMm2": round(w * h, 3),
        "areaM2": round(area_m2, 6),
        "shapeUsability": usability,
        "ageDays": round(age_days, 3),
        "ageFactor": round(age_factor, 4),
        "configCostPerM2": cost_per_m2,
        "estimatedValue": round(value, 4),
        "source": "ESTIMATED/CONFIG",
        "notAccountingCost": True,
    }


def inventory_delta_manifest(
    *,
    batch_id: str,
    tenant_id: str,
    new_sheets: int,
    remnants_created: list[dict[str, Any]],
    reserved: list[dict[str, Any]],
    consumed: list[dict[str, Any]],
    true_scrap_area: float,
    reusable_area: float,
    used_area: float,
    sheet_area: float,
) -> dict[str, Any]:
    payload = {
        "batchId": batch_id,
        "tenantId": tenant_id,
        "newSheetsAllocated": int(new_sheets),
        "newSheetAreaMm2": int(new_sheets) * float(sheet_area),
        "remnantsCreated": [{"remnantId": r.get("remnantId"), "w": r.get("w"), "h": r.get("h"), "area": r.get("area")} for r in remnants_created],
        "reserved": [r.get("remnantId") for r in reserved],
        "consumed": [r.get("remnantId") for r in consumed],
        "trueScrapArea": true_scrap_area,
        "reusableRemnantArea": reusable_area,
        "usedAreaMm2": used_area,
    }
    payload["reconciliationHash"] = stable_hash(payload)
    conserved = used_area + reusable_area + true_scrap_area
    allocated = int(new_sheets) * float(sheet_area) + sum(float(r.get("area") or 0) for r in consumed)
    payload["conservationError"] = round(abs(conserved - allocated), 3) if allocated else 0.0
    payload["source"] = "REAL" if remnants_created or consumed or new_sheets else "EMPTY"
    return payload


def lease_token(remnant_id: str, version: int, by: str) -> str:
    return f"{remnant_id}:{int(version)}:{by}"
