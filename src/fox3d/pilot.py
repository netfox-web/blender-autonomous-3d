"""Manual pilot operations E2E. Reuses existing family factories + new release/WO/QC.

Not live factory execution. LIVE_CNC / LIVE_LASER remain BLOCKED.
"""

from __future__ import annotations

import json
from typing import Any

from fox3d.ids import new_id, sha256_bytes
from fox3d.logistics import LogisticsService
from fox3d.mfg_release import ManufacturingReleaseService, product_snapshot
from fox3d.pilot_econ import PilotEconomics
from fox3d.qc import QcService
from fox3d.readiness import scoped_readiness
from fox3d.receipt import ReceivingService
from fox3d.reliability import ReliabilityHarness
from fox3d.supplier import SupplierQuoteService
from fox3d.workorder import FIXTURE_AUTO_SEED, WorkOrderService

PILOT_FAMILIES = ("KD_FURNITURE", "RETAIL_FIXTURE", "PACKAGING_STRUCTURE", "ACRYLIC_SHEET")

STRESS_PLAN = [
    ("KD_FURNITURE", "OPEN_SHELF"),
    ("KD_FURNITURE", "BEDSIDE_CABINET"),
    ("KD_FURNITURE", "DESK_RISER"),
    ("KD_FURNITURE", "NARROW_BOOKCASE"),
    ("KD_FURNITURE", "STORAGE_BENCH"),
    ("KD_FURNITURE", "PET_FURNITURE"),
    ("KD_FURNITURE", "MOBILE_SIDE_TABLE"),
    ("KD_FURNITURE", "STUDENT_DESK"),
    ("RETAIL_FIXTURE", "COUNTER_DISPLAY"),
    ("RETAIL_FIXTURE", "FLOOR_DISPLAY"),
    ("RETAIL_FIXTURE", "PDQ_DISPLAY"),
    ("RETAIL_FIXTURE", "RISER_DISPLAY"),
    ("PACKAGING_STRUCTURE", "RSC_CARTON"),
    ("PACKAGING_STRUCTURE", "MAILER_BOX"),
    ("PACKAGING_STRUCTURE", "SLEEVE"),
    ("PACKAGING_STRUCTURE", "TRAY"),
    ("ACRYLIC_SHEET", "MENU_STAND"),
    ("ACRYLIC_SHEET", "SIGN_HOLDER"),
    ("ACRYLIC_SHEET", "RISER_STAND"),
    ("ACRYLIC_SHEET", "DISPLAY_BOX"),
]


class PilotOps:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.releases = ManufacturingReleaseService(dam=getattr(platform, "dam", None))
        self.suppliers = SupplierQuoteService(getattr(platform, "providers", None))
        self.workorders = WorkOrderService(
            lots=platform.lots,
            remnants=platform.remnants,
            dam=platform.dam,
            releases=self.releases,
        )
        self.qc = QcService(dam=platform.dam, workorders=self.workorders)
        self.workorders.bind_qc(self.qc)
        self.logistics = LogisticsService()
        self.econ = PilotEconomics()
        self.receiving = ReceivingService(lots=platform.lots)
        self.reliability = ReliabilityHarness(self)

    def build_product(self, *, tenant_id: str, family: str, kind: str, render: bool = False) -> dict[str, Any]:
        if family == "KD_FURNITURE":
            return self.platform.kd.build_sku(tenant_id=tenant_id, kind=kind, render=render)
        if family == "RETAIL_FIXTURE":
            return self.platform.physical.retail.build(tenant_id=tenant_id, family=kind, render=render)
        if family == "PACKAGING_STRUCTURE":
            return self.platform.physical.packaging.build(
                tenant_id=tenant_id, family=kind, product_dims={"width": 120, "height": 80, "depth": 40}
            )
        if family == "ACRYLIC_SHEET":
            return self.platform.physical.acrylic.build(tenant_id=tenant_id, kind=kind, render=render)
        raise ValueError(family)

    def open_release(self, product: dict[str, Any], *, tenant_id: str, family: str, actor: str = "eng") -> dict[str, Any]:
        snap = product_snapshot(product, family=family)
        rel = self.releases.create(snap, tenant_id=tenant_id, created_by=actor)
        self.releases.validate(rel["releaseId"])
        self.releases.submit_approval(rel["releaseId"], actor=actor)
        gate = getattr(self.platform, "release", None)
        audit_hash = None
        if gate is not None:
            audit = gate.audit(actor=actor, entity_id=rel["productId"], entity=product, decision="APPROVED_FOR_MANUAL_RELEASE", reason="pilot-human-gate")
            audit_hash = audit.get("auditHash")
        self.releases.approve(rel["releaseId"], actor=actor, audit_hash=audit_hash)
        self.releases.release_for_manual_execution(rel["releaseId"], actor=actor)
        return self.releases.get(rel["releaseId"])

    def run_family_e2e(self, *, tenant_id: str, family: str, kind: str, actor: str = "pilot") -> dict[str, Any]:
        product = self.build_product(tenant_id=tenant_id, family=family, kind=kind, render=False)
        rel = self.open_release(product, tenant_id=tenant_id, family=family, actor=actor)
        verify = self.releases.verify(rel["releaseId"])
        wo = self.workorders.create(tenant_id=tenant_id, release=rel, quantity=1, actor=actor)
        self.workorders.release_for_execution(wo["workOrderId"], actor=actor)
        self.workorders.reserve_materials(
            wo["workOrderId"], actor=actor, tenant_id=tenant_id, allocation_policy=FIXTURE_AUTO_SEED
        )
        ops = []
        for step in (wo["traveler"]["steps"]):
            op = self.workorders.start_operation(wo["workOrderId"], step["operation"], actor=actor)
            self.workorders.complete_operation(wo["workOrderId"], op["opId"], actor=actor)
            ops.append(op)
        nest = (rel.get("snapshot") or {}).get("nesting") or {}
        self.workorders.record_cut_outcome(
            wo["workOrderId"],
            expected_qty=float(nest.get("sheetCount") or 1),
            recorded_qty=float(nest.get("sheetCount") or 1),
            remnant_rects=[{"w": 400, "h": 300, "area": 120000, "sheetIndex": 0}],
            scrap_area_mm2=float(nest.get("trueScrapArea") or 10000),
            actor=actor,
        )
        self.workorders.consume_reserved(wo["workOrderId"], actor=actor)
        schema = self.qc.schema(family)
        qc_rows = []
        for spec in schema:
            nominal = float(spec["nominal"] if spec["nominal"] is not None else 100.0)
            row = self.qc.record(
                tenant_id=tenant_id,
                work_order_id=wo["workOrderId"],
                stage="FINAL" if spec.get("requiredFinal") else "IN_PROCESS",
                check_id=spec["checkId"],
                measured=nominal,
                nominal=nominal,
                tol=float(spec["tol"]),
                unit=spec["unit"],
                operator=actor,
                required_final=bool(spec.get("requiredFinal")),
                source="TEST_DATA",
            )
            qc_rows.append(row)
        packing = (rel.get("snapshot") or {}).get("packing") or {}
        cartons = self.logistics.instantiate_cartons(
            tenant_id=tenant_id,
            work_order_id=wo["workOrderId"],
            batch_id=wo["batchId"],
            plan=packing or {"length": 400, "width": 300, "height": 200},
            quantity=1,
            contents=[{"sku": "product", "qty": 1}],
            expected_weight_kg=float(((product.get("weight") or {}).get("grossKg") or 8)),
            release_hash=rel["releaseHash"],
            product_version=rel.get("productVersion"),
            lot_ids=wo.get("lineage", {}).get("materialLots") or [],
        )
        self.workorders.set_packing(wo["workOrderId"], [c["cartonId"] for c in cartons])
        qc_ok = self.qc.completion_allowed(wo["workOrderId"], family)
        self.workorders.complete(wo["workOrderId"], actor=actor, qc_ok=qc_ok)
        frozen = self.econ.freeze_from_release(rel)
        actual = self.econ.import_actuals(
            work_order_id=wo["workOrderId"],
            release_hash=rel["releaseHash"],
            rows={
                "material": float(frozen.get("estimatedCost") or 100) * 0.45,
                "processing": float(frozen.get("estimatedCost") or 100) * 0.2,
                "hardware": 20,
                "packaging": 15,
                "freight": 30,
                "scrap": 8,
                "rework": 0,
            },
            source="MANUAL",
            batch_id=wo["batchId"],
        )
        var = self.econ.variance(frozen=frozen, actual=actual)
        waste = self.econ.waste_economics(
            true_scrap_mm2=float(nest.get("trueScrapArea") or 10000),
            remnant_mm2=float(nest.get("reusableRemnantArea") or 50000),
            recovered_mm2=min(float(nest.get("reusableRemnantArea") or 50000), 20000),
            cost_per_m2=280.0,
        )
        price = float((product.get("quote") or {}).get("suggestedPrice") or (product.get("landed") or {}).get("suggestedPrice") or 1800)
        margin = self.econ.contribution_margin(price=price, cost=actual["total"])
        trace = self.qc.trace(work_order_id=wo["workOrderId"])
        wo_final = self.workorders.get(wo["workOrderId"])
        return {
            "family": family,
            "kind": kind,
            "productId": rel["productId"],
            "releaseId": rel["releaseId"],
            "releaseHash": rel["releaseHash"],
            "releaseStatus": rel["status"],
            "verify": verify,
            "workOrderId": wo["workOrderId"],
            "workOrderState": wo_final["state"],
            "ops": len(ops),
            "qc": qc_rows,
            "qcOk": qc_ok,
            "cartons": [c["cartonId"] for c in cartons],
            "variance": var,
            "waste": waste,
            "margin": margin,
            "trace": trace,
            "liveMachineControl": False,
            "liveCnc": False,
            "liveLaser": False,
        }

    def run_four_family_e2e(self, *, tenant_id: str = "pilot") -> dict[str, Any]:
        kinds = {
            "KD_FURNITURE": "OPEN_SHELF",
            "RETAIL_FIXTURE": "COUNTER_DISPLAY",
            "PACKAGING_STRUCTURE": "RSC_CARTON",
            "ACRYLIC_SHEET": "MENU_STAND",
        }
        rows = [self.run_family_e2e(tenant_id=tenant_id, family=fam, kind=kind) for fam, kind in kinds.items()]
        return {
            "families": rows,
            "ok": all(r["workOrderState"] == "COMPLETED" and r["verify"]["ok"] and r["qcOk"] for r in rows),
            "liveFactoryExecutionReady": False,
        }

    def batch_stress(
        self,
        *,
        tenant_id: str = "pilot-stress",
        plan: list[tuple[str, str]] | None = None,
        consume_retry: Any | None = None,
    ) -> dict[str, Any]:
        plan = plan or STRESS_PLAN
        releases = []
        wo_ids = []
        op_count = 0
        for family, kind in plan:
            row = self.run_family_e2e(tenant_id=tenant_id, family=family, kind=kind)
            releases.append(row["releaseId"])
            wo_ids.append(row["workOrderId"])
            op_count += row["ops"]
        # idempotency: retry create
        first = self.releases.get(releases[0])
        again = self.releases.create(
            first["snapshot"],
            tenant_id=tenant_id,
            created_by="pilot",
            idempotency_key=f"{first['productId']}:{first['productVersion']}:{first['engineeringHash']}",
        )
        no_double = self.observe_no_double_consume(wo_ids[0], consume=consume_retry)
        conservation = self.lot_conservation(tenant_id)
        # tenant isolation
        isolated = False
        try:
            self.workorders._require(wo_ids[0], tenant_id="other-tenant")
        except PermissionError:
            isolated = True
        # stale cannot complete
        stale_blocked = False
        last = self.releases.get(releases[-1])
        mutated = dict(last["snapshot"])
        mutated["engineeringHash"] = sha256_bytes(b"mutated-engineering")
        self.releases.refresh_stale(last["releaseId"], mutated)
        try:
            extra = self.workorders.create(tenant_id=tenant_id, release=self.releases.get(last["releaseId"]), quantity=1, batch_id=new_id())
            _ = extra
        except PermissionError:
            stale_blocked = True
        return {
            "releaseCount": len(releases),
            "workOrderCount": len(wo_ids),
            "operationCount": op_count,
            "idempotentRelease": again["releaseId"] == releases[0],
            "noDoubleConsume": bool(no_double),
            "materialConserved": bool(conservation["ok"]),
            "tenantIsolation": isolated,
            "staleReleaseBlocked": stale_blocked,
            "label": "FIXTURE",
            "liveFactoryExecutionReady": False,
        }

    def _lot_state(self, tenant_id: str) -> dict[str, tuple[int, int, int]]:
        return {
            lot["lotId"]: (
                int(lot.get("remainingSheets") or 0),
                int(lot.get("reservedSheets") or 0),
                int(lot.get("consumedSheets") or 0),
            )
            for lot in self.workorders.lots.list(tenant_id=tenant_id)
        }

    def lot_conservation(self, tenant_id: str) -> dict[str, Any]:
        return self.workorders.lots.conservation_ok(tenant_id=tenant_id)

    def observe_no_double_consume(self, work_order_id: str, *, consume: Any | None = None) -> bool:
        rec = self.workorders.get(work_order_id)
        tid = rec["tenantId"]
        before = self._lot_state(tid)
        fn = consume or self.workorders.consume_reserved
        try:
            fn(work_order_id, actor="pilot")
        except PermissionError:
            pass
        after = self._lot_state(tid)
        return before == after and bool(self.lot_conservation(tid)["ok"])

    def supplier_fixture(self, release: dict[str, Any]) -> dict[str, Any]:
        rfq = self.suppliers.rfq_from_release(release, quantity=10)
        quotes = self.suppliers.import_json(
            json.dumps(
                [
                    {"supplierId": "S1", "material": 400, "processing": 120, "setup": 200, "packaging": 40, "freight": 80, "moq": 1, "leadTimeDays": 5, "currency": "TWD"},
                    {"supplierId": "S2", "material": 380, "processing": 150, "setup": 80, "packaging": 35, "freight": 90, "moq": 20, "leadTimeDays": 12, "currency": "TWD"},
                    {"supplierId": "S3", "material": 420, "processing": 100, "setup": 50, "packaging": 45, "freight": 60, "moq": 5, "leadTimeDays": 7, "currency": "TWD"},
                ]
            ),
            source="IMPORTED",
        )
        fx = self.suppliers.import_fx({"pair": "USD/TWD", "rate": 32.0, "effectiveAt": "2026-01-01"}, source="MANUAL")
        cmp = self.suppliers.compare(
            [q["quoteId"] for q in quotes],
            release_hash=release["releaseHash"],
            quantity=10,
            fx_snapshot_id=fx["snapshotId"],
        )
        stale = self.suppliers.comparison_stale(cmp, release_hash="other", quantity=10, fx_snapshot_id=fx["snapshotId"])
        return {"rfq": rfq, "quotes": quotes, "comparison": cmp, "staleOnReleaseChange": stale, "fxSource": fx.get("source")}

    def render_family_previews(
        self,
        *,
        tenant_id: str,
        commit_sha: str,
        real_ok: bool,
        families: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        from fox3d.evidence import evidence_bundle, verify_bundle

        mode_map = {
            "KD_FURNITURE": "PARAMETRIC_CABINET",
            "RETAIL_FIXTURE": "PARAMETRIC_CABINET",
            "PACKAGING_STRUCTURE": "PACKAGING_FOLD",
            "ACRYLIC_SHEET": "ACRYLIC_PRODUCT",
        }
        if families is None:
            families = self.run_four_family_e2e(tenant_id=tenant_id)["families"]
        previews: list[dict[str, Any]] = []
        for fam in families:
            rel = self.releases.get(fam["releaseId"])
            snap = rel.get("snapshot") or {}
            family = rel["productFamily"]
            kind = rel.get("kind") or fam.get("kind")
            mode = mode_map[family]
            release_hash = rel["releaseHash"]
            eng_hash = rel.get("engineeringHash") or snap.get("engineeringHash")
            bom_hash = rel.get("bomHash") or (snap.get("bom") or {}).get("bomHash")
            rec = {
                "spec": snap.get("spec") or {},
                "engineering": snap.get("engineering") or {},
                "kind": kind,
                "dimensions": snap.get("dimensions"),
                "sheet": snap.get("sheet"),
            }
            payload: dict[str, Any] = {
                "tenantId": tenant_id,
                "jobType": "BLENDER_PREVIEW",
                "mode": mode,
                "render": {"width": 256, "height": 256, "engine": "CYCLES", "device": "OPTIX", "samples": 8},
                "timeoutSeconds": 180,
            }
            if mode == "PARAMETRIC_CABINET" and rec.get("spec"):
                payload["engineering"] = rec["spec"]
            if mode == "PACKAGING_FOLD":
                payload["foldPreview"] = True
                payload["packagingTemplate"] = "BOX"
                payload["dimensions"] = (rec.get("engineering") or {}).get("fit", {}).get("outer") or rec.get("dimensions") or {
                    "width": 120,
                    "height": 80,
                    "depth": 40,
                }
            if mode == "ACRYLIC_PRODUCT":
                payload["acrylic"] = {
                    "kind": rec.get("kind"),
                    "dimensions": rec.get("dimensions"),
                    "finish": (rec.get("sheet") or {}).get("finish"),
                }
            job = self.platform.execute_job(self.platform.submit_job(payload))
            if job.get("status") in {"queued", "retry_scheduled"}:
                job = self.platform.execute_job(job)
            files = (job.get("output") or {}).get("files") or {}
            beauty = None
            asset = job.get("outputAsset") or files.get("beauty.png")
            if asset:
                try:
                    beauty = self.platform.dam.get_unchecked(str(asset)).path
                except Exception:
                    beauty = files.get("beauty.png")
            bun = evidence_bundle(
                commit_sha=commit_sha,
                job=job,
                artifact_path=beauty,
                engineering_hash=eng_hash,
                bom_hash=bom_hash,
                extra={"releaseHash": release_hash, "productFamily": family, "releaseId": rel["releaseId"]},
            )
            verify_kwargs: dict[str, Any] = {
                "require_real": True,
                "expected_commit_sha": commit_sha,
                "expected_release_hash": release_hash,
            }
            if eng_hash:
                verify_kwargs["expected_engineering_hash"] = eng_hash
            if bom_hash:
                verify_kwargs["expected_bom_hash"] = bom_hash
            ver = verify_bundle(bun, **verify_kwargs)
            used_mock = bool(job.get("usedMock"))
            real_blender = bool(job.get("realBlender"))
            label = "REAL" if real_ok and ver["ok"] and real_blender and not used_mock else "PARTIAL"
            if not real_ok:
                label = "UNVERIFIED"
            previews.append(
                {
                    "family": family,
                    "kind": kind,
                    "jobId": job.get("jobId"),
                    "usedMock": used_mock,
                    "realBlender": real_blender,
                    "verify": ver,
                    "bundle": bun,
                    "label": label,
                    "releaseHash": release_hash,
                    "engineeringHash": eng_hash,
                    "bomHash": bom_hash,
                    "blenderVersion": job.get("blenderVersion"),
                    "gpuName": job.get("gpu") or job.get("gpuName"),
                    "workerId": job.get("worker"),
                }
            )
        return previews

    def readiness(self, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        ev = evidence or {}
        matrix = scoped_readiness(evidence=ev)

        def _flag(key: str) -> bool:
            if key not in ev:
                return False
            return bool(ev[key])

        def _label(ready: bool, when_true: str) -> str:
            return when_true if ready else "UNVERIFIED"

        matrix["manufacturingReleasePackageReady"] = _flag("releasePackage")
        matrix["manualPilotOpsReady"] = _flag("pilotOps")
        matrix["qcTraceabilityReady"] = _flag("qc")
        matrix["importedSupplierQuoteReady"] = _flag("supplierQuotes")
        matrix["importedCarrierQuoteReady"] = _flag("carrierQuotes")
        matrix["liveFactoryExecutionReady"] = False
        matrix["liveProviderReady"] = False
        matrix["globalProductionReady"] = False
        matrix["pilotReliabilityReady"] = _flag("reliability")
        matrix["strictStockReady"] = _flag("strictStock")
        matrix["fullAutonomousFactoryReady"] = False
        matrix["labels"] = {
            **(matrix.get("labels") or {}),
            "manufacturingReleasePackageReady": _label(matrix["manufacturingReleasePackageReady"], "REAL"),
            "manualPilotOpsReady": _label(matrix["manualPilotOpsReady"], "REAL"),
            "qcTraceabilityReady": _label(matrix["qcTraceabilityReady"], "REAL"),
            "importedSupplierQuoteReady": _label(matrix["importedSupplierQuoteReady"], "IMPORTED"),
            "importedCarrierQuoteReady": _label(matrix["importedCarrierQuoteReady"], "IMPORTED"),
            "liveFactoryExecutionReady": "BLOCKED",
            "liveProviderReady": "BLOCKED",
            "globalProductionReady": "BLOCKED",
            "fullAutonomousFactoryReady": "BLOCKED",
            "pilotReliabilityReady": _label(matrix["pilotReliabilityReady"], "FIXTURE"),
            "strictStockReady": _label(matrix["strictStockReady"], "REAL"),
        }
        return matrix

    def console(self, *, tenant_id: str) -> dict[str, Any]:
        lots = []
        for lot in self.workorders.lots.list(tenant_id=tenant_id):
            q = self.workorders.lots.quantities(lot["lotId"], tenant_id=tenant_id)
            lots.append(
                {
                    **q,
                    "quarantined": bool(lot.get("quarantined")),
                    "material": lot.get("material"),
                    "truthLabel": lot.get("truthLabel") or lot.get("receiptSource") or "CONFIG",
                }
            )
        wos = []
        for wo in self.workorders.orders.values():
            if wo.get("tenantId") != tenant_id:
                continue
            wos.append(
                {
                    "workOrderId": wo["workOrderId"],
                    "state": wo["state"],
                    "releaseHash": wo.get("releaseHash"),
                    "materialReserved": wo.get("materialReserved"),
                    "openOps": [o["operation"] for o in wo.get("ops") or [] if o.get("status") != "COMPLETED"],
                    "qcHold": wo.get("state") == "QC_HOLD",
                    "packing": wo.get("cartonIds") or [],
                    "allocationPolicy": wo.get("allocationPolicy"),
                    "truthLabel": wo.get("truthLabel") or "REAL",
                }
            )
        releases = []
        for rel in self.releases.releases.values():
            if rel.get("tenantId") != tenant_id:
                continue
            releases.append(
                {
                    "releaseId": rel["releaseId"],
                    "status": rel["status"],
                    "stale": bool(rel.get("stale")),
                    "supersededBy": rel.get("supersededBy"),
                    "releaseHash": rel.get("releaseHash"),
                    "approvedReleaseHash": rel.get("approvedReleaseHash"),
                    "qcPlanHash": rel.get("qcPlanHash"),
                }
            )
        return {
            "tenantId": tenant_id,
            "lots": lots,
            "workOrders": wos,
            "releases": releases,
            "receipts": [r for r in self.receiving.receipts.values() if r.get("tenantId") == tenant_id],
            "purchaseRequests": [r for r in self.receiving.requests.values() if r.get("tenantId") == tenant_id],
            "shipments": [s for s in self.logistics.shipments.values() if s.get("tenantId") == tenant_id],
            "cartons": [c for c in self.logistics.cartons.values() if c.get("tenantId") == tenant_id],
            "qcRework": [d for d in self.qc.defects.values() if d.get("tenantId") == tenant_id],
            "liveCnc": False,
            "liveLaser": False,
            "liveMachineControl": False,
            "badges": {
                "LIVE_CNC": "BLOCKED",
                "LIVE_LASER": "BLOCKED",
                "Vision": "MOCK",
                "Demand": "MOCK",
                "quotes": "IMPORTED",
                "receipts": "MANUAL/IMPORTED",
                "sandbox": "PARTIAL",
            },
        }
