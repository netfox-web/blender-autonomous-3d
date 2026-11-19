"""Packaging / logistics execution boundary. Planning logic, not a carrier."""

from __future__ import annotations

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
        self.carrier_quotes = {r["quoteId"]: r for r in payload.get("carrier_quotes") or []}
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
                "carrier_quotes": list(self.carrier_quotes.values()),
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

    def palletize(self, carton_ids: list[str]) -> dict[str, Any]:
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
            self.persist()
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
    ) -> dict[str, Any]:
        with self._lock:
            rec = self.shipping_request(
                origin=origin,
                destination=destination,
                carton_ids=carton_ids,
                service=service,
                quote_id=quote_id,
                dim_divisor=dim_divisor,
            )
            rec["submittedToCarrier"] = False
            rec["booked"] = False
            rec["shipped"] = False
            rec["status"] = "SHIPMENT_DRAFT"
            rec["liveCarrier"] = False
            emit(
                self,
                "shipment.draft",
                tenant_id=rec.get("tenantId") or "",
                aggregate_type="Shipment",
                aggregate_id=rec["shipmentId"],
                actor="ops",
                payload={"status": "SHIPMENT_DRAFT", "booked": False},
                semantic_key=f"{rec.get('tenantId')}::shipment::{rec['shipmentId']}",
            )
            return rec

    def import_carrier_quote(
        self,
        row: dict[str, Any],
        *,
        source: str,
        raw: str | None = None,
        tenant_id: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if source not in ALLOWED_SOURCES:
                raise PermissionError("carrier quotes are MANUAL/IMPORTED unless a live carrier is connected")
            eff_tenant: str | None = None
            if tenant_id is not None:
                if not isinstance(tenant_id, str) or not tenant_id.strip():
                    raise ValueError("tenant_id must be a non-empty string")
                eff_tenant = tenant_id.strip()
            elif row.get("tenantId") not in (None, ""):
                raw_tid = row.get("tenantId")
                if not isinstance(raw_tid, str) or not raw_tid.strip():
                    raise ValueError("tenantId must be a non-empty string")
                eff_tenant = raw_tid.strip()

            raw_qid = row.get("quoteId")
            if raw_qid not in (None, ""):
                if not isinstance(raw_qid, str) or not raw_qid.strip():
                    raise ValueError("quoteId must be a non-empty string")
                quote_id = raw_qid.strip()
            else:
                quote_id = new_id()

            existing = self.carrier_quotes.get(quote_id)
            if existing is not None and existing.get("tenantId") != eff_tenant:
                raise PermissionError("tenant isolation: carrier quote")

            raw_valid_until = row.get("validUntil")
            if raw_valid_until in (None, ""):
                valid_until = "9999-12-31"
            else:
                valid_until = _parse_valid_until_date(raw_valid_until).isoformat()

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
            rec["ownership"] = "GLOBAL_REFERENCE"
            self.carrier_quotes[rec["quoteId"]] = rec
            if persist:
                self.persist()
            return rec

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
