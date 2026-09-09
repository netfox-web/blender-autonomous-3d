"""Packaging / logistics execution boundary. Planning logic, not a carrier."""

from __future__ import annotations

import json
from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow

ALLOWED_SOURCES = frozenset({"MANUAL", "IMPORTED"})
PALLET_MM = (1200.0, 1000.0)
PALLET_MAX_H = 1400.0
PALLET_MAX_KG = 500.0
DIM_DIVISOR = 6000.0


def _now() -> str:
    return utcnow().isoformat()


class LogisticsService:
    def __init__(self) -> None:
        self.cartons: dict[str, dict[str, Any]] = {}
        self.pallets: dict[str, dict[str, Any]] = {}
        self.shipments: dict[str, dict[str, Any]] = {}
        self.carrier_quotes: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, list[str]] = {}

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
        raw_key = idempotency_key or f"{work_order_id}:{batch_id}"
        key = f"{tenant_id}::carton::{raw_key}"
        if key in self._idem:
            ids = self._idem[key]
            if not isinstance(ids, list):
                raise PermissionError("idempotency namespace collision: carton")
            rows = [self.cartons[i] for i in ids]
            if any(r.get("tenantId") != tenant_id for r in rows):
                raise PermissionError("tenant isolation: carton")
            return rows
        n = max(int(quantity), 1)
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
        return rows

    def record_measured(
        self,
        carton_id: str,
        *,
        length: float,
        width: float,
        height: float,
        weight_kg: float,
        source: str = "IMPORTED",
    ) -> dict[str, Any]:
        rec = self.cartons[carton_id]
        expected = dict(rec["expected"])
        rec["measured"] = {
            "length": float(length),
            "width": float(width),
            "height": float(height),
            "weightKg": float(weight_kg),
            "source": source if source in {"IMPORTED", "MANUAL", "MEASURED"} else "IMPORTED",
            "truthLabel": "MEASURED",
        }
        rec["expected"] = expected
        return rec

    def packing_list(self, *, work_order_id: str) -> dict[str, Any]:
        cartons = [c for c in self.cartons.values() if c["workOrderId"] == work_order_id]
        contents: dict[str, float] = {}
        for c in cartons:
            for item in c.get("contents") or []:
                contents[str(item.get("sku"))] = contents.get(str(item.get("sku")), 0) + float(item.get("qty") or 0)
        return {
            "workOrderId": work_order_id,
            "cartonCount": len(cartons),
            "cartons": [{"cartonId": c["cartonId"], "contents": c["contents"], "expected": c["expected"], "measured": c["measured"]} for c in cartons],
            "batchTotal": contents,
            "contentsConserved": True,
        }

    def contents_conserved(self, *, work_order_id: str, expected_qty: float, sku: str = "product") -> bool:
        lst = self.packing_list(work_order_id=work_order_id)
        return abs(float(lst["batchTotal"].get(sku) or 0) - float(expected_qty)) < 1e-6

    def pack_completeness(self, *, work_order_id: str, expected_qty: float, sku: str = "product") -> dict[str, Any]:
        lst = self.packing_list(work_order_id=work_order_id)
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
        cartons = [self.cartons[i] for i in carton_ids]
        layers: list[list[str]] = []
        current: list[str] = []
        used_w = 0.0
        used_d = 0.0
        height = 0.0
        weight = 0.0
        pallets = []

        def flush() -> None:
            nonlocal current, used_w, used_d, height, weight
            if not current:
                return
            pallets.append(
                {
                    "cartonIds": list(current),
                    "footprintMm": [PALLET_MM[0], PALLET_MM[1]],
                    "heightMm": round(height, 1),
                    "weightKg": round(weight, 3),
                    "label": "PLANNING",
                    "carrierCertification": False,
                }
            )
            current, used_w, used_d, height, weight = [], 0.0, 0.0, 0.0, 0.0

        for c in cartons:
            d = c.get("measured") or c["expected"]
            cl, cw, ch, ck = float(d["length"]), float(d["width"]), float(d["height"]), float(d.get("weightKg") or 0)
            if height + ch > PALLET_MAX_H or weight + ck > PALLET_MAX_KG:
                flush()
            current.append(c["cartonId"])
            used_w = max(used_w, cl)
            used_d = max(used_d, cw)
            height += ch
            weight += ck
            _ = layers
        flush()
        rec = {
            "palletPlanId": new_id(),
            "pallets": pallets,
            "palletCount": len(pallets),
            "constraints": {"footprintMm": list(PALLET_MM), "maxHeightMm": PALLET_MAX_H, "maxWeightKg": PALLET_MAX_KG},
            "label": "PLANNING",
            "carrierCertification": False,
        }
        rec["planHash"] = stable_hash({k: rec[k] for k in rec if k not in {"palletPlanId", "planHash"}})
        self.pallets[rec["palletPlanId"]] = rec
        return rec

    def shipping_request(
        self,
        *,
        origin: str,
        destination: str,
        carton_ids: list[str],
        service: str = "ground",
    ) -> dict[str, Any]:
        cartons = [self.cartons[i] for i in carton_ids]
        tenants = {c.get("tenantId") for c in cartons}
        if len(tenants) != 1 or None in tenants:
            raise PermissionError("cross-tenant carton mix")
        rec = {
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
        rec["requestHash"] = stable_hash({k: rec[k] for k in rec if k not in {"shipmentId", "requestHash"}})
        tenant = rec["tenantId"]
        raw = f"{origin}:{destination}:{','.join(carton_ids)}:{service}"
        idem = f"{tenant}::shipment::{raw}"
        if idem in self._idem:
            stored = self._idem[idem]
            sid = stored[0] if isinstance(stored, list) else stored
            if sid not in self.shipments:
                raise PermissionError("idempotency namespace collision: shipment")
            existing = self.shipments[sid]
            if existing.get("tenantId") != tenant:
                raise PermissionError("tenant isolation: shipment")
            return existing
        self._idem[idem] = rec["shipmentId"]
        self.shipments[rec["shipmentId"]] = rec
        return rec

    def shipment_draft(self, *, origin: str, destination: str, carton_ids: list[str], service: str = "ground") -> dict[str, Any]:
        rec = self.shipping_request(origin=origin, destination=destination, carton_ids=carton_ids, service=service)
        rec["submittedToCarrier"] = False
        rec["booked"] = False
        rec["shipped"] = False
        rec["status"] = "SHIPMENT_DRAFT"
        rec["liveCarrier"] = False
        return rec

    def import_carrier_quote(self, row: dict[str, Any], *, source: str, raw: str | None = None) -> dict[str, Any]:
        if source not in ALLOWED_SOURCES:
            raise PermissionError("carrier quotes are MANUAL/IMPORTED unless a live carrier is connected")
        rec = {
            "quoteId": row.get("quoteId") or new_id(),
            "carrier": row.get("carrier") or "carrier",
            "service": row.get("service") or "ground",
            "charge": float(row.get("charge") or row.get("amount") or 0),
            "currency": row.get("currency") or "TWD",
            "dimDivisor": float(row.get("dimDivisor") or DIM_DIVISOR),
            "validUntil": row.get("validUntil") or "9999-12-31",
            "source": source,
            "truthLabel": source,
            "liveProvider": False,
            "importedAt": _now(),
            "rawSourceHash": stable_hash(raw if raw is not None else json.dumps(row, sort_keys=True, default=str)),
        }
        rec["quoteHash"] = stable_hash({k: rec[k] for k in rec if k not in {"quoteId", "quoteHash"}})
        self.carrier_quotes[rec["quoteId"]] = rec
        return rec

    def quote_stale(self, quote: dict[str, Any], *, service: str, dim_divisor: float | None = None) -> bool:
        if quote.get("service") != service:
            return True
        if dim_divisor is not None and abs(float(quote.get("dimDivisor") or 0) - float(dim_divisor)) > 1e-6:
            return True
        return False

    def label_payload(self, carton_id: str) -> dict[str, Any]:
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
