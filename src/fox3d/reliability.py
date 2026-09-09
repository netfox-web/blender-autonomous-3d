"""FIXTURE reliability stress. Not a factory throughput claim."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fox3d.inventory import StockShortage

FAMILIES = (
    ("KD_FURNITURE", "OPEN_SHELF"),
    ("RETAIL_FIXTURE", "COUNTER_DISPLAY"),
    ("PACKAGING_STRUCTURE", "RSC_CARTON"),
    ("ACRYLIC_SHEET", "MENU_STAND"),
)


class ReliabilityHarness:
    def __init__(self, pilot: Any) -> None:
        self.pilot = pilot

    def run(self, *, tenant_id: str = "rel-fix", n_orders: int = 50) -> dict[str, Any]:
        rec = self.pilot.receiving.import_receipt(
            {"supplierId": "S-REL", "supplierLot": "LOT-REL-1", "material": "PB_18_WHITE", "thickness": 18, "quantity": 800},
            tenant_id=tenant_id,
            actor="recv",
            source="IMPORTED",
            idempotency_key="LOT-REL-1",
        )
        dup = self.pilot.receiving.import_receipt(
            {"supplierId": "S-REL", "supplierLot": "LOT-REL-1", "material": "PB_18_WHITE", "thickness": 18, "quantity": 800},
            tenant_id=tenant_id,
            actor="recv",
            source="IMPORTED",
            idempotency_key="LOT-REL-1",
        )
        qrec = self.pilot.receiving.import_receipt(
            {
                "supplierId": "S-Q",
                "supplierLot": "Q1",
                "material": "PB_18_WHITE",
                "thickness": 18,
                "quantity": 4,
                "expectedMaterial": "MDF_18",
            },
            tenant_id=tenant_id,
            actor="recv",
            source="IMPORTED",
            idempotency_key="Q1",
        )
        q_alloc = False
        try:
            self.pilot.workorders.lots.reserve_sheets(qrec["lotId"], tenant_id=tenant_id, work_order_id="nope", quantity=1)
            q_alloc = True
        except PermissionError:
            q_alloc = False

        releases = []
        for family, kind in FAMILIES:
            product = self.pilot.build_product(tenant_id=tenant_id, family=family, kind=kind)
            rel = self.pilot.open_release(product, tenant_id=tenant_id, family=family, actor="eng")
            releases.append(rel)
            nest = (rel.get("snapshot") or {}).get("nesting") or {}
            sku = str(nest.get("sheetSku") or "PB_18_WHITE")
            th = float(nest.get("thickness") or 18)
            sheet_mm = nest.get("sheetMm") or []
            row = {"supplierLot": f"FAM-{family}", "material": sku, "thickness": th, "quantity": 200}
            if len(sheet_mm) >= 2:
                row["length"] = float(sheet_mm[0])
                row["width"] = float(sheet_mm[1])
            g = nest.get("grain") or nest.get("grainConstraint")
            if isinstance(g, str) and g not in {"any", "none", ""}:
                row["grain"] = g
            self.pilot.receiving.import_receipt(
                row,
                tenant_id=tenant_id,
                actor="recv",
                source="IMPORTED",
                idempotency_key=f"FAM-{family}",
            )

        wo_ids = []
        op_count = 0
        negatives: list[str] = []
        for i in range(n_orders):
            rel = releases[i % 4]
            wo = self.pilot.workorders.create(tenant_id=tenant_id, release=rel, quantity=1, actor="ops", batch_id=f"b{i}")
            self.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
            self.pilot.workorders.reserve_materials(wo["workOrderId"], actor="ops", tenant_id=tenant_id, allocation_policy="STRICT_STOCK")
            for step in wo["traveler"]["steps"]:
                op = self.pilot.workorders.start_operation(wo["workOrderId"], step["operation"], actor="ops")
                self.pilot.workorders.complete_operation(wo["workOrderId"], op["opId"], actor="ops")
                op_count += 2
            schema = self.pilot.qc.schema(rel["productFamily"])
            for spec in schema:
                nominal = float(spec["nominal"] if spec["nominal"] is not None else 100.0)
                self.pilot.qc.record(
                    tenant_id=tenant_id,
                    work_order_id=wo["workOrderId"],
                    stage="FINAL" if spec.get("requiredFinal") else "IN_PROCESS",
                    check_id=spec["checkId"],
                    measured=nominal,
                    nominal=nominal,
                    tol=float(spec["tol"]),
                    unit=spec["unit"],
                    operator="ops",
                    required_final=bool(spec.get("requiredFinal")),
                    source="TEST_DATA",
                )
            cartons = self.pilot.logistics.instantiate_cartons(
                tenant_id=tenant_id,
                work_order_id=wo["workOrderId"],
                batch_id=wo["batchId"],
                plan={"length": 400, "width": 300, "height": 200},
                quantity=1,
                contents=[{"sku": "product", "qty": 1}],
                release_hash=rel["releaseHash"],
                product_version=rel.get("productVersion"),
                lot_ids=wo.get("lineage", {}).get("materialLots") or [],
            )
            self.pilot.workorders.set_packing(wo["workOrderId"], [c["cartonId"] for c in cartons])
            self.pilot.workorders.consume_reserved(wo["workOrderId"], actor="ops")
            self.pilot.workorders.complete(wo["workOrderId"], actor="ops")
            wo_ids.append(wo["workOrderId"])

        # concurrent last-sheet race
        race_lot = self.pilot.receiving.import_receipt(
            {"supplierLot": "RACE", "material": "PB_18_WHITE", "quantity": 1, "thickness": 18},
            tenant_id=tenant_id,
            actor="recv",
            source="MANUAL",
            idempotency_key="RACE",
        )
        wins = []
        lock = threading.Lock()

        def _try(j: int) -> str:
            try:
                self.pilot.workorders.lots.reserve_sheets(
                    race_lot["lotId"], tenant_id=tenant_id, work_order_id=f"race-{j}", quantity=1
                )
                with lock:
                    wins.append(j)
                return "ok"
            except (StockShortage, PermissionError):
                return "fail"

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(_try, j) for j in range(20)]
            _ = [f.result() for f in as_completed(futs)]
        race_ok = len(wins) == 1
        qty = self.pilot.workorders.lots.quantities(race_lot["lotId"], tenant_id=tenant_id)
        race_ok = race_ok and qty["available"] == 0 and qty["reserved"] == 1 and qty["conserved"]

        # illegal transitions
        rel0 = releases[0]
        bad = self.pilot.workorders.create(tenant_id=tenant_id, release=rel0, quantity=1, actor="ops", batch_id="illegal")
        try:
            self.pilot.workorders.start_operation(bad["workOrderId"], "panel_cutting", actor="ops")
            negatives.append("op-before-reserve-passed")
        except PermissionError:
            negatives.append("op-before-reserve-failed")
        self.pilot.workorders.release_for_execution(bad["workOrderId"], actor="ops")
        self.pilot.workorders.reserve_materials(bad["workOrderId"], actor="ops", tenant_id=tenant_id, allocation_policy="STRICT_STOCK")
        try:
            self.pilot.workorders.complete(bad["workOrderId"], actor="ops")
            negatives.append("complete-open-ops-passed")
        except PermissionError:
            negatives.append("complete-open-ops-failed")

        # pack mismatch
        pack_bad = self.pilot.logistics.pack_completeness(work_order_id=wo_ids[0], expected_qty=99)
        pack_ok = self.pilot.logistics.pack_completeness(work_order_id=wo_ids[0], expected_qty=1)

        ship = self.pilot.logistics.shipment_draft(origin="TW", destination="TW-TPE", carton_ids=self.pilot.workorders.get(wo_ids[0]).get("cartonIds") or [])
        cons = self.pilot.workorders.lots.conservation_ok(tenant_id=tenant_id)

        # partial-shortage rollback: isolated tenant, A=2 B=1 need 5
        pst = f"{tenant_id}-ps"
        a = self.pilot.receiving.import_receipt(
            {"supplierLot": "PS-A", "material": "PB_18_WHITE", "thickness": 18, "quantity": 2},
            tenant_id=pst,
            actor="recv",
            source="MANUAL",
            idempotency_key="PS-A",
        )
        b = self.pilot.receiving.import_receipt(
            {"supplierLot": "PS-B", "material": "PB_18_WHITE", "thickness": 18, "quantity": 1},
            tenant_id=pst,
            actor="recv",
            source="MANUAL",
            idempotency_key="PS-B",
        )
        before_a = self.pilot.workorders.lots.quantities(a["lotId"], tenant_id=pst)
        before_b = self.pilot.workorders.lots.quantities(b["lotId"], tenant_id=pst)
        try:
            self.pilot.workorders.lots.allocate_requirement(
                tenant_id=pst, work_order_id="ps-short", quantity=5, material="PB_18_WHITE", thickness=18
            )
            negatives.append("partial-shortage-passed")
        except StockShortage:
            negatives.append("partial-shortage-failed")
        after_a = self.pilot.workorders.lots.quantities(a["lotId"], tenant_id=pst)
        after_b = self.pilot.workorders.lots.quantities(b["lotId"], tenant_id=pst)
        partial_ok = after_a == before_a and after_b == before_b

        # material mismatch
        oak = self.pilot.receiving.import_receipt(
            {"supplierLot": "OAK-ONLY", "material": "OAK", "thickness": 18, "quantity": 8},
            tenant_id=tenant_id,
            actor="recv",
            source="MANUAL",
            idempotency_key="OAK-ONLY",
        )
        oak_before = self.pilot.workorders.lots.quantities(oak["lotId"], tenant_id=tenant_id)
        try:
            self.pilot.workorders.lots.allocate_requirement(
                tenant_id=tenant_id,
                work_order_id="mm",
                quantity=1,
                material="MISSING_SKU",
                thickness=18,
            )
            negatives.append("material-mismatch-passed")
        except StockShortage:
            negatives.append("material-mismatch-failed")
        oak_after = self.pilot.workorders.lots.quantities(oak["lotId"], tenant_id=tenant_id)
        material_ok = oak_after == oak_before

        # tenant isolation
        other = "rel-other"
        a_key = self.pilot.receiving.import_receipt(
            {"supplierLot": "ISO", "material": "PB_18_WHITE", "quantity": 1, "thickness": 18},
            tenant_id=tenant_id,
            actor="recv",
            source="MANUAL",
            idempotency_key="same-key",
        )
        b_key = self.pilot.receiving.import_receipt(
            {"supplierLot": "ISO", "material": "PB_18_WHITE", "quantity": 1, "thickness": 18},
            tenant_id=other,
            actor="recv",
            source="MANUAL",
            idempotency_key="same-key",
        )
        tenant_ok = a_key["receiptId"] != b_key["receiptId"] and a_key["tenantId"] == tenant_id and b_key["tenantId"] == other
        cons_a = self.pilot.console(tenant_id=tenant_id)
        tenant_ok = tenant_ok and all(s.get("tenantId") == tenant_id for s in cons_a.get("shipments") or [])
        mix_rejected = False
        try:
            ca = self.pilot.logistics.instantiate_cartons(
                tenant_id=tenant_id, work_order_id="wa", batch_id="ba", plan={"length": 1, "width": 1, "height": 1}, quantity=1
            )
            cb = self.pilot.logistics.instantiate_cartons(
                tenant_id=other, work_order_id="wb", batch_id="bb", plan={"length": 1, "width": 1, "height": 1}, quantity=1
            )
            self.pilot.logistics.shipment_draft(origin="TW", destination="X", carton_ids=[ca[0]["cartonId"], cb[0]["cartonId"]])
        except PermissionError:
            mix_rejected = True
            negatives.append("tenant-isolation-failed")
        if not mix_rejected:
            negatives.append("tenant-isolation-passed")

        mutated = dict(rel0["snapshot"])
        mutated["engineeringHash"] = "deadbeef" * 8
        self.pilot.releases.refresh_stale(rel0["releaseId"], mutated)
        try:
            self.pilot.workorders.create(tenant_id=tenant_id, release=self.pilot.releases.get(rel0["releaseId"]), quantity=1, actor="ops", batch_id="stale")
            negatives.append("stale-wo-passed")
        except PermissionError:
            negatives.append("stale-wo-failed")

        cons = self.pilot.workorders.lots.conservation_ok(tenant_id=tenant_id)
        return {
            "label": "FIXTURE",
            "workOrderCount": len(wo_ids),
            "operationTransitions": op_count,
            "receiptIdempotent": rec["receiptId"] == dup["receiptId"],
            "quarantineBlocked": qrec["quarantined"] and not q_alloc,
            "noOversell": race_ok,
            "materialConserved": cons["ok"],
            "negatives": negatives,
            "packMismatchFails": pack_bad["ok"] is False and pack_bad["code"] in {"shortage", "duplicate"},
            "packOk": pack_ok["ok"] is True,
            "shipmentDraft": ship["status"] == "SHIPMENT_DRAFT" and ship["submittedToCarrier"] is False and ship["booked"] is False,
            "partialShortageRollback": partial_ok,
            "materialCompatibility": material_ok,
            "tenantIsolation": tenant_ok and mix_rejected,
            "liveFactoryExecutionReady": False,
        }
