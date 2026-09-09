"""Durable remnant / material-lot inventory.

Not a second WMS. RemnantStore is the persistence port for RemnantInventory.
In-memory behaviour stays compatible; durable JSON lives under `.fox3d-data`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
from fox3d.storelock import CrashInjected, FileLock, StaleGeneration

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


class StockShortage(PermissionError):
    """STRICT_STOCK failure. payload is structured shortage evidence, not a fabricated lot."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("message") or "SHORTAGE")
        self.payload = payload


class MaterialLotRegistry:
    """Sheet lots with lineage. CONFIG cost snapshot, not a supplier live feed."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
        self.lots: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._tx_depth = 0
        self._tx_expected = 0
        self.generation = 0
        self.journal: Any | None = None
        self.outbox: Any | None = None
        self._crash_after_first_stage = False
        self._crash_before_commit = False
        self._crash_mode = ""
        self._hard_crash = False
        self._fail_after_prepare = False
        self._fail_journal_finalize = False
        self._pending_audit: list[dict[str, Any]] = []
        self.load()

    def _lock_path(self) -> Path | None:
        return (self.root / "lots.lock") if self.root else None

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            flock: FileLock | None = None
            if self._tx_depth == 0 and self.root:
                flock = FileLock(self._lock_path())  # type: ignore[arg-type]
                flock.acquire()
                self.load()
                self._tx_expected = self.generation
            self._tx_depth += 1
            if self._tx_depth == 1:
                self._pending_audit = []
            persisted = False
            try:
                yield
                if self._tx_depth == 1:
                    self._commit_business_and_audit()
                    persisted = True
            except Exception:
                if self._tx_depth == 1 and self.root and not persisted:
                    self.load()
                raise
            finally:
                self._tx_depth -= 1
                if self._tx_depth == 0 and flock is not None:
                    flock.release()

    def _die(self, point: str) -> None:
        if self._crash_mode != point:
            return
        if self._hard_crash:
            os._exit(1)
        raise CrashInjected(point)

    def _commit_business_and_audit(self) -> None:
        pending = list(self._pending_audit)
        self._pending_audit = []
        txs: list[dict[str, Any]] = []
        outbox = self.outbox
        if self.journal is not None and outbox is not None and pending:
            for ev in pending:
                txs.append(outbox.prepare(ev, expected_generation=self._tx_expected))
            if self._fail_after_prepare:
                self._fail_after_prepare = False
                from fox3d.journal import JournalCommitError

                raise JournalCommitError("injected prepare-then-business-fail")
            self._die("after-prepare")
        self.persist(expected_generation=self._tx_expected)
        if outbox is not None:
            for tx in txs:
                outbox.mark_business_committed(tx["txId"], observed_generation=self.generation)
        self._die("after-business")
        if self.journal is not None:
            if self._fail_journal_finalize:
                self._fail_journal_finalize = False
                from fox3d.journal import JournalCommitError

                raise JournalCommitError("injected journal finalize failure")
            for ev in pending:
                self.journal.append(
                    ev["event_type"],
                    tenant_id=ev["tenant_id"],
                    aggregate_type=ev["aggregate_type"],
                    aggregate_id=ev["aggregate_id"],
                    actor=ev["actor"],
                    payload=ev["payload"],
                    semantic_key=ev.get("semantic_key"),
                    source=ev.get("source"),
                )
            if outbox is not None:
                for tx in txs:
                    outbox.complete(tx["txId"])

    def _emit(self, event_type: str, *, tenant_id: str, aggregate_id: str, actor: str, payload: dict[str, Any], semantic_key: str | None = None) -> None:
        if self.journal is None:
            return
        rec = {
            "event_type": event_type,
            "tenant_id": tenant_id,
            "aggregate_type": "MaterialLot",
            "aggregate_id": aggregate_id,
            "actor": actor,
            "payload": payload,
            "semantic_key": semantic_key,
            "source": actor,
        }
        if self._tx_depth > 0:
            self._pending_audit.append(rec)
            return
        self.journal.append(
            event_type,
            tenant_id=tenant_id,
            aggregate_type="MaterialLot",
            aggregate_id=aggregate_id,
            actor=actor,
            payload=payload,
            semantic_key=semantic_key,
        )

    def load(self) -> None:
        if not self.root:
            self.generation = 0
            return
        path = self.root / "lots.json"
        payload = read_json(path) or {}
        self.generation = int(payload.get("generation") or 0)
        self.lots = {rec["lotId"]: rec for rec in payload.get("lots") or []}

    def persist(self, *, expected_generation: int | None = None) -> None:
        if not self.root:
            return
        path = self.root / "lots.json"
        disk = read_json(path) or {}
        disk_gen = int(disk.get("generation") or 0)
        want = self.generation if expected_generation is None else int(expected_generation)
        if disk_gen != want:
            raise StaleGeneration(f"stale lot store generation disk={disk_gen} expected={want}")
        payload = {"generation": disk_gen + 1, "lots": list(self.lots.values())}
        staging = self.root / "lots.json.staging"
        atomic_write_json(staging, payload)
        if self._crash_before_commit or self._crash_mode == "after-staging":
            self._crash_before_commit = False
            self._die("after-staging")
            raise CrashInjected("before commit")
        staging.replace(path)
        self.generation = disk_gen + 1

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
            "reservedSheets": 0,
            "consumedSheets": 0,
            "quarantined": False,
            "qualityState": "AVAILABLE",
            "reservations": {},
            "adjustments": [],
            "version": 1,
        }
        rec["lotHash"] = stable_hash({k: rec[k] for k in rec if k not in {"lotHash"}})
        with self._transaction():
            self.lots[rec["lotId"]] = rec
        return rec

    def get(self, lot_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.lots[lot_id]
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: material lot")
        self._ensure_qty(rec)
        return rec

    def _ensure_qty(self, rec: dict[str, Any]) -> dict[str, Any]:
        rec.setdefault("reservedSheets", 0)
        rec.setdefault("consumedSheets", 0)
        rec.setdefault("reservations", {})
        remaining = int(rec.get("remainingSheets") or 0)
        reserved = int(rec.get("reservedSheets") or 0)
        consumed = int(rec.get("consumedSheets") or 0)
        if "sheetCount" not in rec:
            rec["sheetCount"] = remaining + reserved + consumed
        sheet_count = int(rec.get("sheetCount") or 0)
        if reserved == 0 and remaining + consumed != sheet_count and 0 <= remaining <= sheet_count:
            rec["consumedSheets"] = sheet_count - remaining
        return rec

    def quantities(self, lot_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.get(lot_id, tenant_id=tenant_id)
        remaining = int(rec.get("remainingSheets") or 0)
        reserved = int(rec.get("reservedSheets") or 0)
        consumed = int(rec.get("consumedSheets") or 0)
        sheet_count = int(rec.get("sheetCount") or 0)
        return {
            "lotId": lot_id,
            "available": remaining,
            "reserved": reserved,
            "consumed": consumed,
            "sheetCount": sheet_count,
            "conserved": remaining + reserved + consumed == sheet_count,
        }

    def conservation_ok(self, *, tenant_id: str) -> dict[str, Any]:
        rows = [self.quantities(lot["lotId"], tenant_id=tenant_id) for lot in self.list(tenant_id=tenant_id)]
        return {"ok": all(r["conserved"] for r in rows) if rows else True, "lots": rows}

    def lot_compatible(
        self,
        lot: dict[str, Any],
        *,
        material: str,
        thickness: float,
        grain: str | None = None,
        length: float | None = None,
        width: float | None = None,
    ) -> bool:
        if lot.get("quarantined") or lot.get("qualityState") == "QUARANTINED":
            return False
        if str(lot.get("material") or "") != str(material):
            return False
        if abs(float(lot.get("thickness") or 0) - float(thickness)) > 1e-6:
            return False
        if grain:
            lot_grain = lot.get("grain")
            if not lot_grain or str(lot_grain) in {"any", "none"}:
                return False
            if str(lot_grain) != str(grain):
                return False
        if length is not None:
            if lot.get("length") is None:
                return False
            if abs(float(lot.get("length")) - float(length)) > 1e-3:
                return False
        if width is not None:
            if lot.get("width") is None:
                return False
            if abs(float(lot.get("width")) - float(width)) > 1e-3:
                return False
        return True

    def allocate_requirement(
        self,
        *,
        tenant_id: str,
        work_order_id: str,
        quantity: int,
        material: str,
        thickness: float,
        grain: str | None = None,
        length: float | None = None,
        width: float | None = None,
    ) -> list[dict[str, Any]]:
        """Preflight compatible stock then reserve atomically. SHORTAGE mutates nothing."""
        qty = int(quantity)
        with self._transaction():
            candidates = [
                l
                for l in self.list(tenant_id=tenant_id, allocatable=True)
                if self.lot_compatible(l, material=material, thickness=thickness, grain=grain, length=length, width=width)
            ]
            total = sum(int(l.get("remainingSheets") or 0) for l in candidates)
            if total < qty:
                raise StockShortage(
                    {
                        "code": "SHORTAGE",
                        "needed": qty,
                        "available": total,
                        "material": material,
                        "thickness": thickness,
                        "message": "STRICT_STOCK: insufficient compatible material, no phantom lot",
                    }
                )
            taken: list[dict[str, Any]] = []
            remaining = qty
            for lot in candidates:
                avail = int(lot.get("remainingSheets") or 0)
                if avail <= 0 or remaining <= 0:
                    continue
                take = min(remaining, avail)
                item = self.reserve_sheets(
                    lot["lotId"], tenant_id=tenant_id, work_order_id=work_order_id, quantity=take
                )
                taken.append(
                    {
                        "kind": "lot",
                        "lotId": lot["lotId"],
                        "quantity": take,
                        "reservationId": item["reservationId"],
                        "state": "RESERVED",
                    }
                )
                remaining -= take
                if self._crash_after_first_stage and taken:
                    if self.root:
                        atomic_write_json(self.root / "lots.json.staging", {"partial": True, "taken": taken})
                    raise CrashInjected("after first lot staging")
            if remaining > 0:
                for item in taken:
                    try:
                        self.release_reservation(item["reservationId"], tenant_id=tenant_id, work_order_id=work_order_id)
                    except (KeyError, PermissionError):
                        continue
                raise StockShortage(
                    {
                        "code": "SHORTAGE",
                        "needed": qty,
                        "available": qty - remaining,
                        "material": material,
                        "message": "STRICT_STOCK: reservation raced to shortage; rolled back",
                    }
                )
            return taken

    def _reservation_key(self, *, tenant_id: str, work_order_id: str, lot_id: str, quantity: int) -> str:
        return f"{tenant_id}:{work_order_id}:{lot_id}:{int(quantity)}"

    def _find_reservation(self, reservation_id: str, *, tenant_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        other = False
        for rec in self.lots.values():
            self._ensure_qty(rec)
            item = (rec.get("reservations") or {}).get(reservation_id)
            if not item:
                continue
            if rec.get("tenantId") != tenant_id:
                other = True
                continue
            return item, rec
        if other:
            raise PermissionError("tenant isolation: material lot")
        raise KeyError(reservation_id)

    def reserve_sheets(
        self,
        lot_id: str,
        *,
        tenant_id: str,
        work_order_id: str,
        quantity: int,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        with self._transaction():
            rec = self.get(lot_id, tenant_id=tenant_id)
            if rec.get("quarantined") or rec.get("qualityState") == "QUARANTINED":
                raise PermissionError("quarantined lot not allocatable")
            if expected_version is not None and int(rec.get("version") or 1) != int(expected_version):
                raise PermissionError("stale lot version")
            qty = int(quantity)
            if qty <= 0:
                raise PermissionError("reservation quantity must be positive")
            key = self._reservation_key(tenant_id=tenant_id, work_order_id=work_order_id, lot_id=lot_id, quantity=qty)
            existing = (rec.get("reservations") or {}).get(key)
            if existing and existing.get("state") == "RESERVED":
                return existing
            if existing and existing.get("state") == "CONSUMED":
                raise PermissionError("lot reservation already consumed")
            available = int(rec.get("remainingSheets") or 0)
            if qty > available:
                raise StockShortage(
                    {
                        "code": "SHORTAGE",
                        "lotId": lot_id,
                        "needed": qty,
                        "available": available,
                        "message": f"lot {lot_id} insufficient available sheets",
                    }
                )
            rec["remainingSheets"] = available - qty
            rec["reservedSheets"] = int(rec.get("reservedSheets") or 0) + qty
            rec["version"] = int(rec.get("version") or 1) + 1
            item = {
                "reservationId": key,
                "lotId": lot_id,
                "tenantId": tenant_id,
                "workOrderId": work_order_id,
                "quantity": qty,
                "state": "RESERVED",
            }
            rec.setdefault("reservations", {})[key] = item
            self._emit(
                "material.reserve",
                tenant_id=tenant_id,
                aggregate_id=lot_id,
                actor=work_order_id,
                payload={"reservationId": key, "quantity": qty, "workOrderId": work_order_id},
                semantic_key=f"{tenant_id}::reserve::{key}",
            )
            return item

    def consume_reservation(self, reservation_id: str, *, tenant_id: str, work_order_id: str) -> dict[str, Any]:
        with self._transaction():
            item, rec = self._find_reservation(reservation_id, tenant_id=tenant_id)
            if rec.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: material lot")
            if item.get("workOrderId") != work_order_id:
                raise PermissionError("reservation ownership")
            if item.get("state") == "CONSUMED":
                return item
            if item.get("state") != "RESERVED":
                raise PermissionError(f"lot reservation not consumable ({item.get('state')})")
            qty = int(item["quantity"])
            rec["reservedSheets"] = int(rec.get("reservedSheets") or 0) - qty
            rec["consumedSheets"] = int(rec.get("consumedSheets") or 0) + qty
            item["state"] = "CONSUMED"
            rec["version"] = int(rec.get("version") or 1) + 1
            self._emit(
                "material.consume",
                tenant_id=tenant_id,
                aggregate_id=rec["lotId"],
                actor=work_order_id,
                payload={"reservationId": reservation_id, "quantity": qty, "workOrderId": work_order_id},
                semantic_key=f"{tenant_id}::consume::{reservation_id}",
            )
            return item

    def release_reservation(self, reservation_id: str, *, tenant_id: str, work_order_id: str) -> dict[str, Any]:
        with self._transaction():
            item, rec = self._find_reservation(reservation_id, tenant_id=tenant_id)
            if rec.get("tenantId") != tenant_id:
                raise PermissionError("tenant isolation: material lot")
            if item.get("workOrderId") != work_order_id:
                raise PermissionError("reservation ownership")
            if item.get("state") == "RELEASED":
                return item
            if item.get("state") == "CONSUMED":
                raise PermissionError("cannot release consumed lot reservation")
            if item.get("state") != "RESERVED":
                raise PermissionError(f"lot reservation not releasable ({item.get('state')})")
            qty = int(item["quantity"])
            rec["reservedSheets"] = int(rec.get("reservedSheets") or 0) - qty
            rec["remainingSheets"] = int(rec.get("remainingSheets") or 0) + qty
            item["state"] = "RELEASED"
            rec["version"] = int(rec.get("version") or 1) + 1
            self._emit(
                "material.rollback",
                tenant_id=tenant_id,
                aggregate_id=rec["lotId"],
                actor=work_order_id,
                payload={"reservationId": reservation_id, "quantity": qty, "workOrderId": work_order_id},
                semantic_key=f"{tenant_id}::rollback::{reservation_id}",
            )
            return item

    def allocate_sheet(self, lot_id: str, *, tenant_id: str) -> dict[str, Any]:
        with self._transaction():
            rec = self.get(lot_id, tenant_id=tenant_id)
            if rec.get("quarantined"):
                raise PermissionError("quarantined lot not allocatable")
            if int(rec.get("remainingSheets") or 0) <= 0:
                raise PermissionError(f"lot {lot_id} exhausted")
            rec["remainingSheets"] = int(rec["remainingSheets"]) - 1
            rec["consumedSheets"] = int(rec.get("consumedSheets") or 0) + 1
            rec["version"] = int(rec.get("version") or 1) + 1
            return rec

    def receive(
        self,
        *,
        tenant_id: str,
        material: str,
        thickness: float,
        quantity: int,
        actor: str,
        source: str = "MANUAL",
        supplier_id: str | None = None,
        supplier_lot: str | None = None,
        lot_id: str | None = None,
        unit_cost: float = 850.0,
        reason: str = "receipt",
        length: float | None = None,
        width: float | None = None,
        grain: str | None = None,
    ) -> dict[str, Any]:
        if source not in {"MANUAL", "IMPORTED"}:
            raise PermissionError("receipt source must be MANUAL/IMPORTED")
        qty = int(quantity)
        if qty <= 0:
            raise PermissionError("receipt quantity must be positive")
        with self._transaction():
            if lot_id:
                rec = self.get(lot_id, tenant_id=tenant_id)
                before = dict(self.quantities(lot_id, tenant_id=tenant_id))
                rec["sheetCount"] = int(rec.get("sheetCount") or 0) + qty
                rec["remainingSheets"] = int(rec.get("remainingSheets") or 0) + qty
                rec["version"] = int(rec.get("version") or 1) + 1
            else:
                rec = self.create(
                    tenant_id=tenant_id,
                    material=material,
                    thickness=thickness,
                    sheet_count=qty,
                    supplier_lot=supplier_lot,
                    cost_per_sheet=unit_cost,
                    length=float(length) if length is not None else 2440,
                    width=float(width) if width is not None else 1220,
                    grain=str(grain or "length"),
                )
                before = {"available": 0, "reserved": 0, "consumed": 0, "sheetCount": 0}
            rec["supplierId"] = supplier_id
            rec["receiptSource"] = source
            rec["truthLabel"] = source
            rec.setdefault("adjustments", []).append(
                {
                    "actor": actor,
                    "reason": reason,
                    "source": source,
                    "tenantId": tenant_id,
                    "qty": qty,
                    "before": before,
                    "after": self.quantities(rec["lotId"], tenant_id=tenant_id),
                    "at": _now_iso(),
                    "hash": stable_hash({"lotId": rec["lotId"], "qty": qty, "actor": actor, "reason": reason}),
                }
            )
            return rec

    def apply_counted_available(self, lot_id: str, *, tenant_id: str, counted: int, actor: str, reason: str) -> dict[str, Any]:
        """Set available sheets to a counted value. Does not rewrite consumed/reserved."""
        qty = int(counted)
        if qty < 0:
            raise PermissionError("counted quantity cannot be negative")
        with self._transaction():
            rec = self.get(lot_id, tenant_id=tenant_id)
            reserved = int(rec.get("reservedSheets") or 0)
            consumed = int(rec.get("consumedSheets") or 0)
            rec["remainingSheets"] = qty
            rec["sheetCount"] = qty + reserved + consumed
            rec["version"] = int(rec.get("version") or 1) + 1
            rec.setdefault("adjustments", []).append(
                {
                    "actor": actor,
                    "reason": reason,
                    "source": "CYCLE_COUNT",
                    "counted": qty,
                    "reservedUnchanged": reserved,
                    "consumedUnchanged": consumed,
                    "at": _now_iso(),
                }
            )
            self._emit(
                "material.cyclecount",
                tenant_id=tenant_id,
                aggregate_id=lot_id,
                actor=actor,
                payload={"counted": qty, "reserved": reserved, "consumed": consumed},
                semantic_key=f"{tenant_id}::cyclecount::{lot_id}::{qty}:{reason}",
            )
            return rec

    def quarantine(self, lot_id: str, *, tenant_id: str, actor: str, reason: str) -> dict[str, Any]:
        with self._transaction():
            rec = self.get(lot_id, tenant_id=tenant_id)
            rec["quarantined"] = True
            rec["qualityState"] = "QUARANTINED"
            rec["quarantineReason"] = reason
            rec["quarantinedBy"] = actor
            rec["version"] = int(rec.get("version") or 1) + 1
            self._emit(
                "material.quarantine",
                tenant_id=tenant_id,
                aggregate_id=lot_id,
                actor=actor,
                payload={"reason": reason},
                semantic_key=f"{tenant_id}::quarantine::{lot_id}::{reason}",
            )
            return rec

    def list(self, *, tenant_id: str, allocatable: bool = False) -> list[dict[str, Any]]:
        rows = [self._ensure_qty(v) for v in self.lots.values() if v.get("tenantId") == tenant_id]
        if allocatable:
            rows = [r for r in rows if int(r.get("remainingSheets") or 0) > 0 and not r.get("quarantined")]
        return rows


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


def worker_main(argv: list[str] | None = None) -> int:
    """Cross-process STRICT_STOCK worker. Invoked as `python -m fox3d.inventory`."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--wo", required=True)
    parser.add_argument("--qty", type=int, required=True)
    parser.add_argument("--material", default="PB_18_WHITE")
    parser.add_argument("--thickness", type=float, default=18)
    parser.add_argument("--crash", default="")
    parser.add_argument("--tx", default="")
    parser.add_argument("--journal", default="")
    args = parser.parse_args(argv)
    reg = MaterialLotRegistry(Path(args.root))
    if args.tx:
        from fox3d.journal import EventJournal
        from fox3d.outbox import CommitOutbox

        reg.outbox = CommitOutbox(Path(args.tx))
        jroot = Path(args.journal) if args.journal else Path(args.tx).parent / "journal"
        reg.journal = EventJournal(jroot)
        reg.journal.outbox = reg.outbox
    if args.crash:
        reg._crash_mode = args.crash
        reg._hard_crash = True
    try:
        items = reg.allocate_requirement(
            tenant_id=args.tenant,
            work_order_id=args.wo,
            quantity=int(args.qty),
            material=args.material,
            thickness=float(args.thickness),
        )
        print(json.dumps({"ok": True, "qty": sum(int(i["quantity"]) for i in items)}))
        return 0
    except StockShortage as exc:
        print(json.dumps({"ok": False, "shortage": True, **exc.payload}))
        return 2


if __name__ == "__main__":
    raise SystemExit(worker_main())
