"""KD / flat-pack factory: nesting batches, remnants, cost, reverse R&D, catalog."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fox3d.ids import new_id
from fox3d.kd import (
    DemandSignalProvider,
    FLATPACK_PRODUCT_TYPES,
    SMALL_SPACE_PROFILE,
    assembly_instruction_manifest,
    build_flatpack_spec,
    kd_logistics_gate,
    rd_score_v2,
)
from fox3d.manufacturing import NestingEngine, QuoteEngine, RemnantInventory, SheetMaterialRegistry
from fox3d.parametric import CabinetSpec, map_cabinet_material
from fox3d.release import (
    atomic_write_tenant_json,
    file_sig,
    read_validated_tenant_json,
    reentrant_store_lock,
    safe_tenant_filename,
)

PRODUCT_STATES = (
    "IDEA",
    "ENGINEERING_VALID",
    "DFM_VALID",
    "COMMERCIAL_CANDIDATE",
    "WAITING_PRODUCT_APPROVAL",
    "APPROVED_FOR_PROTOTYPE",
)
FORBIDDEN_STATES = {"APPROVED_FOR_PRODUCTION", "LIVE_CNC"}


class KdFactory:
    def __init__(self, platform: Any = None, *, root: Path | None = None) -> None:
        self.platform = platform
        plat_root = getattr(platform, "root", None)
        base_root = Path(root) if root else (
            Path(plat_root) / "kd" if plat_root is not None else None
        )
        self.root = base_root
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
        self.remnants = getattr(platform, "remnants", None) or RemnantInventory()
        self.batches: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.demand = DemandSignalProvider()
        self.nester = NestingEngine()
        self._lock = threading.RLock()
        self._lock_state: dict[str, int] = {"depth": 0}
        self._sigs: dict[str, tuple[int, int, int, int] | None] = {}
        self._batch_depth = 0
        self._dirty_tenants: set[str] = set()
        if self.root is not None:
            self.load()

    def _lock_path(self) -> Path | None:
        return (self.root / "kd.lock") if self.root is not None else None

    @contextmanager
    def _locked_store(self) -> Iterator[None]:
        with reentrant_store_lock(self._lock, self._lock_state, self._lock_path()):
            yield

    @contextmanager
    def batch_write(self, *, tenant_id: str | None = None) -> Iterator[None]:
        with self._lock:
            self._batch_depth += 1
            if tenant_id is not None:
                self._sync_tenant(tenant_id)
            try:
                yield
            finally:
                try:
                    if self._batch_depth == 1 and self._dirty_tenants:
                        with self._locked_store():
                            for tid in sorted(self._dirty_tenants):
                                self._persist_tenant_unlocked(tid)
                        self._dirty_tenants.clear()
                finally:
                    self._batch_depth -= 1

    def _normalize_tenant(self, tenant_id: str | None) -> str:
        tid = str(tenant_id or "default").strip()
        return tid or "default"

    def _candidate_tenant(self, rec: dict[str, Any]) -> str:
        raw_spec = rec.get("spec")
        spec: dict[str, Any] = raw_spec if isinstance(raw_spec, dict) else {}
        return self._normalize_tenant(rec.get("tenantId") or spec.get("tenantId"))

    def _candidate_id(self, rec: dict[str, Any]) -> str | None:
        raw_spec = rec.get("spec")
        spec: dict[str, Any] = raw_spec if isinstance(raw_spec, dict) else {}
        pid = rec.get("productId") or spec.get("productId") or rec.get("candidateId")
        return pid if isinstance(pid, str) and pid.strip() else None

    def _tenant_path(self, tenant_id: str) -> Path | None:
        if self.root is None:
            return None
        return self.root / f"{safe_tenant_filename(self._normalize_tenant(tenant_id))}.json"

    def _candidate_dirs(self) -> list[Path]:
        if self.root is None:
            return []
        dirs = [self.root]
        alt = self.root.parent / "kd_factory"
        if alt != self.root and alt.is_dir():
            dirs.append(alt)
        return dirs

    def _restore_parametric(self, product_id: str, rec: dict[str, Any]) -> None:
        parametrics = getattr(self.platform, "parametrics", None)
        if isinstance(parametrics, dict) and isinstance(rec.get("spec"), dict):
            parametrics.setdefault(
                product_id,
                {
                    "spec": rec["spec"],
                    "report": rec.get("report"),
                    "bom": rec.get("bom"),
                    "engineeringHash": rec.get("engineeringHash"),
                },
            )

    def _parse_tenant_file(
        self, path: Path
    ) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        payload = read_validated_tenant_json(path, required_lists=("candidates", "batches"))
        tid = str(payload["tenantId"])
        candidates: dict[str, dict[str, Any]] = {}
        for rec in payload["candidates"]:
            if not isinstance(rec, dict):
                raise ValueError(f"corrupt state file {path}: candidate must be an object")
            pid = self._candidate_id(rec)
            if not pid:
                raise ValueError(f"corrupt state file {path}: candidate missing productId")
            raw_spec = rec.get("spec")
            spec: dict[str, Any] = raw_spec if isinstance(raw_spec, dict) else {}
            raw_tid = rec.get("tenantId") or spec.get("tenantId")
            if raw_tid != tid:
                raise ValueError(f"corrupt state file {path}: candidate tenantId mismatch")
            rec.setdefault("productId", pid)
            rec.setdefault("tenantId", tid)
            candidates[pid] = rec
        batches: dict[str, dict[str, Any]] = {}
        for rec in payload["batches"]:
            if not isinstance(rec, dict):
                raise ValueError(f"corrupt state file {path}: batch must be an object")
            bid = rec.get("batchId")
            if not isinstance(bid, str) or not bid.strip():
                raise ValueError(f"corrupt state file {path}: batch missing batchId")
            if rec.get("tenantId") != tid:
                raise ValueError(f"corrupt state file {path}: batch tenantId mismatch")
            batches[bid] = rec
        return tid, candidates, batches

    def load(self) -> None:
        if self.root is None:
            return
        with self._locked_store():
            new_candidates: dict[str, dict[str, Any]] = {}
            new_batches: dict[str, dict[str, Any]] = {}
            new_sigs: dict[str, tuple[int, int, int, int] | None] = {}
            for folder in self._candidate_dirs():
                for path in sorted(folder.glob("*.json")):
                    tid, cands, batches = self._parse_tenant_file(path)
                    new_candidates.update(cands)
                    new_batches.update(batches)
                    if folder == self.root:
                        new_sigs[tid] = file_sig(path)
            self.candidates.clear()
            self.candidates.update(new_candidates)
            self.batches.clear()
            self.batches.update(new_batches)
            self._sigs.clear()
            self._sigs.update(new_sigs)
            for pid, rec in self.candidates.items():
                self._restore_parametric(pid, rec)

    def _sync_tenant(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        with self._locked_store():
            sig = file_sig(path)
            if sig is None:
                if tid in self._sigs:
                    for pid in [
                        k
                        for k, r in self.candidates.items()
                        if self._candidate_tenant(r) == tid
                    ]:
                        self.candidates.pop(pid, None)
                    for bid in [
                        k
                        for k, r in self.batches.items()
                        if self._normalize_tenant(r.get("tenantId")) == tid
                    ]:
                        self.batches.pop(bid, None)
                    self._sigs.pop(tid, None)
                return
            if self._sigs.get(tid) == sig:
                return
            _, cands, batches = self._parse_tenant_file(path)
            for pid in [
                k for k, r in self.candidates.items() if self._candidate_tenant(r) == tid
            ]:
                self.candidates.pop(pid, None)
            self.candidates.update(cands)
            for pid, rec in cands.items():
                self._restore_parametric(pid, rec)
            for bid in [
                k
                for k, r in self.batches.items()
                if self._normalize_tenant(r.get("tenantId")) == tid
            ]:
                self.batches.pop(bid, None)
            self.batches.update(batches)
            self._sigs[tid] = file_sig(path)

    def _persist_tenant_unlocked(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        path = self._tenant_path(tid)
        if path is None:
            return
        tenant_cands = [
            rec for rec in self.candidates.values() if self._candidate_tenant(rec) == tid
        ]
        tenant_batches = [
            rec
            for rec in self.batches.values()
            if self._normalize_tenant(rec.get("tenantId")) == tid
        ]
        if tenant_cands or tenant_batches:
            atomic_write_tenant_json(
                path,
                {
                    "tenantId": tid,
                    "candidates": tenant_cands,
                    "batches": tenant_batches,
                },
            )
            self._sigs[tid] = file_sig(path)
        else:
            path.unlink(missing_ok=True)
            self._sigs.pop(tid, None)

    def _mark_or_persist(self, tenant_id: str | None) -> None:
        if self.root is None:
            return
        tid = self._normalize_tenant(tenant_id)
        with self._lock:
            if self._batch_depth > 0:
                self._dirty_tenants.add(tid)
                return
            with self._locked_store():
                self._persist_tenant_unlocked(tid)

    def persist(self, *, tenant_id: str | None = None) -> None:
        if self.root is None:
            return
        with self._locked_store():
            if tenant_id is not None:
                self._persist_tenant_unlocked(tenant_id)
                return
            tenants = {self._candidate_tenant(r) for r in self.candidates.values()} | {
                self._normalize_tenant(r.get("tenantId")) for r in self.batches.values()
            }
            for tid in sorted(tenants):
                self._persist_tenant_unlocked(tid)

    def list_candidates(self, *, tenant_id: str) -> list[dict[str, Any]]:
        tid = self._normalize_tenant(tenant_id)
        with self._locked_store():
            self._sync_tenant(tid)
            return [
                rec
                for rec in self.candidates.values()
                if self._candidate_tenant(rec) == tid
            ]

    def list_batches(self, *, tenant_id: str) -> list[dict[str, Any]]:
        tid = self._normalize_tenant(tenant_id)
        with self._locked_store():
            self._sync_tenant(tid)
            return [
                rec
                for rec in self.batches.values()
                if self._normalize_tenant(rec.get("tenantId")) == tid
            ]

    def build_sku(self, *, tenant_id: str, kind: str, render: bool = False, **params: Any) -> dict[str, Any]:
        rec = build_flatpack_spec(self.platform.cabinets, tenant_id=tenant_id, kind=kind, **params)
        spec = CabinetSpec.model_validate(rec["spec"])
        self.platform.parametrics[spec.productId] = {
            "spec": rec["spec"],
            "report": rec["report"],
            "bom": rec["bom"],
            "engineeringHash": rec["engineeringHash"],
        }
        nest = self.nester.nest(rec["bom"], material=str(spec.material), thickness=float(spec.boardThickness))
        rec["nesting"] = {k: nest[k] for k in nest if k != "svg"}
        rec["nesting"]["svgBytes"] = len(nest.get("svg") or "")
        rec["quote"] = QuoteEngine().quote(spec, rec["bom"], nest).model_dump(mode="json")
        rec["landed"] = self.landed_cost(spec, rec["bom"], nest, rec["packing"], rec["weight"], rec["shipping"], rec["difficulty"])
        rec["gate"] = kd_logistics_gate(rec["packing"], rec["weight"], rec["difficulty"], rec["shipping"])
        rec["instructions"] = assembly_instruction_manifest(rec["assemblyGraph"], spec)
        rec["approvalState"] = "ENGINEERING_VALID" if rec["report"]["ok"] else "IDEA"
        if rec["report"]["ok"] and rec["gate"]["ok"]:
            rec["approvalState"] = "DFM_VALID"
        rec["demand"] = self.demand.signals(kind=kind)
        rec["rdScore"] = rd_score_v2(
            report_ok=rec["report"]["ok"],
            nesting=nest,
            common=rec["commonParts"],
            packing=rec["shipping"],
            weight=rec["weight"],
            difficulty=rec["difficulty"],
            landed=rec["landed"],
            demand=rec["demand"],
            vision={"label": "MOCK", "visionScore": None},
        )
        if rec["approvalState"] == "DFM_VALID" and rec["landed"].get("grossMargin", 0) >= 0.2 and not rec["rdScore"]["engineeringVeto"]:
            rec["approvalState"] = "COMMERCIAL_CANDIDATE"
            if rec["demand"]["status"] != "REAL":
                rec["market"] = "MARKET_UNVERIFIED"
        rec["preview"] = None
        if render and rec["report"]["ok"]:
            rec["preview"] = self.platform.render_parametric(spec.productId, tenant_id=tenant_id)
        rec["productId"] = spec.productId
        rec["tenantId"] = tenant_id
        with self._lock:
            if self._batch_depth == 0:
                self._sync_tenant(tenant_id)
            self.candidates[spec.productId] = rec
            self._mark_or_persist(tenant_id)
        return rec

    def landed_cost(
        self,
        spec: CabinetSpec,
        bom: dict[str, Any],
        nesting: dict[str, Any],
        packing: dict[str, Any],
        weight: dict[str, Any],
        shipping: dict[str, Any],
        difficulty: dict[str, Any],
        *,
        remnant_credit_applied: float | None = None,
    ) -> dict[str, Any]:
        sheet = SheetMaterialRegistry().for_cabinet_material(spec.material, thickness=spec.boardThickness)
        sheet_cost = int(nesting.get("sheetCount") or 0) * float(sheet.get("costPerSheet") or 850)
        scrap_m2 = float(nesting.get("trueScrapArea") or 0) / 1e6
        waste_cost = scrap_m2 * float(sheet.get("costPerM2") or 280)
        credit = remnant_credit_applied
        if credit is None:
            credit = float(nesting.get("reusableRemnantArea") or 0) / 1e6 * float(sheet.get("costPerM2") or 280) * 0.5
        hw = 0.0
        from fox3d.parametric import HARDWARE_PRICE, PROCESSING_CUT_PER_PART, PROCESSING_DRILL_PER_HOLE, PROCESSING_EDGE_PER_M, EDGE_BANDING_PER_M

        for ln in bom.get("lines") or []:
            if ln.get("hardware"):
                hw += HARDWARE_PRICE.get(ln.get("partId"), HARDWARE_PRICE.get(ln.get("partName"), 10.0)) * float(ln.get("quantity") or 1)
        panels = [ln for ln in bom.get("lines") or [] if not ln.get("hardware")]
        cut_n = len(panels)
        drill_n = cut_n * 8
        edge_m = 0.0
        from fox3d.manufacturing import edge_banding_edges, edge_banding_length_mm

        for ln in panels:
            edges = ln.get("edgeBandingEdges") or edge_banding_edges(str(ln.get("partType") or ""))
            edge_m += edge_banding_length_mm(float(ln.get("length") or 0), float(ln.get("width") or 0), edges) / 1000.0
        processing = cut_n * PROCESSING_CUT_PER_PART + drill_n * PROCESSING_DRILL_PER_HOLE + edge_m * (PROCESSING_EDGE_PER_M + EDGE_BANDING_PER_M)
        pack_cost = float(packing.get("packagingCost") or 0)
        logi = float(shipping.get("logisticsFee") or 0)
        assembly = float(difficulty.get("estimatedMinutes") or 20) / 60.0 * 350.0
        unit = sheet_cost + waste_cost - credit + hw + processing + pack_cost + logi + assembly
        price = unit * 1.45
        margin = 0 if price <= 0 else (price - unit) / price
        return {
            "sheetCost": round(sheet_cost, 2),
            "trueWasteCost": round(waste_cost, 2),
            "remnantCredit": round(credit, 2),
            "hardwareCost": round(hw, 2),
            "processingCost": round(processing, 2),
            "packagingCost": round(pack_cost, 2),
            "logisticsCost": round(logi, 2),
            "assemblyCost": round(assembly, 2),
            "unitLandedCost": round(unit, 2),
            "suggestedPrice": round(price, 2),
            "grossMargin": round(margin, 4),
            "source": "ESTIMATED",
            "lineage": {
                "engineeringHash": spec.engineering_hash(),
                "bomHash": bom.get("bomHash"),
                "nestingHash": nesting.get("nestingHash"),
                "packagingHash": packing.get("packagingHash"),
            },
        }

    def nest_quantity(self, rec: dict[str, Any], quantity: int, *, remnants: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        spec = CabinetSpec.model_validate(rec["spec"])
        lines = []
        for ln in rec["bom"]["lines"]:
            item = dict(ln)
            item["quantity"] = int(ln.get("quantity") or 1) * quantity
            item["skuId"] = spec.productId
            item["productVersion"] = spec.revision
            lines.append(item)
        bom = {"productId": spec.productId, "lines": lines, "bomHash": rec["bom"].get("bomHash")}
        nest = self.nester.nest(bom, material=str(spec.material), thickness=float(spec.boardThickness), remnants=remnants)
        return nest

    def nest_cross_sku(self, recs: list[dict[str, Any]], quantities: list[int]) -> dict[str, Any]:
        lines: list[dict[str, Any]] = []
        material = "WOOD_WHITE"
        thickness = 18.0
        for rec, qty in zip(recs, quantities):
            spec = CabinetSpec.model_validate(rec["spec"])
            material = str(spec.material)
            thickness = float(spec.boardThickness)
            for ln in rec["bom"]["lines"]:
                item = dict(ln)
                item["quantity"] = int(ln.get("quantity") or 1) * qty
                item["skuId"] = spec.productId
                item["productVersion"] = spec.revision
                lines.append(item)
        bom = {"productId": "cross", "lines": lines}
        return self.nester.nest(bom, material=material, thickness=thickness)

    def extract_remnants(self, nesting: dict[str, Any], *, material: str, thickness: float, run_id: str, tenant_id: str | None = None, material_lot_id: str | None = None) -> list[dict[str, Any]]:
        return self.remnants.add_from_nesting(
            nesting,
            material=material,
            thickness=thickness,
            source_run=run_id,
            tenant_id=tenant_id,
            material_lot_id=material_lot_id,
        )

    def remnant_first_case(self, rec: dict[str, Any]) -> dict[str, Any]:
        spec = CabinetSpec.model_validate(rec["spec"])
        independent = self.nester.nest(rec["bom"], material=str(spec.material), thickness=float(spec.boardThickness))
        remnants = [
            {
                "remnantId": "fixture-large",
                "w": 1200,
                "h": 800,
                "thickness": spec.boardThickness,
                "materialCode": map_cabinet_material(str(spec.material)).get("code"),
                "status": "available",
            }
        ]
        with_rem = self.nester.nest(rec["bom"], material=str(spec.material), thickness=float(spec.boardThickness), remnants=remnants)
        saved = max(0, int(independent["sheetCount"]) - int(with_rem["sheetCount"]))
        return {
            "independentSheetCount": independent["sheetCount"],
            "remnantFirstSheetCount": with_rem["sheetCount"],
            "savedNewSheetCount": saved,
            "savedNewSheetSource": "PAIRED_BASELINE",
            "estimatedSavedSheetEquivalent": with_rem.get("estimatedSavedSheetEquivalent"),
            "estimatedSavedSheetSource": "ESTIMATED",
            "remnantConsumedArea": with_rem.get("remnantConsumedArea") or 0,
            "costSavedSource": "PAIRED_BASELINE" if saved else "ESTIMATED",
            "independent": {k: independent[k] for k in ("sheetCount", "trueWasteRatio", "utilizationRatio", "reusableRemnantRatio") if k in independent},
            "remnantFirst": {k: with_rem[k] for k in ("sheetCount", "trueWasteRatio", "utilizationRatio", "remnantConsumedArea") if k in with_rem},
        }

    def remnant_shape_cases(self, rec: dict[str, Any]) -> dict[str, Any]:
        """Large unusable remnant vs small remnant that actually drops a sheet."""
        spec = CabinetSpec.model_validate(rec["spec"])
        baseline = self.nester.nest(rec["bom"], material=str(spec.material), thickness=float(spec.boardThickness))
        awkward = self.nester.nest(
            rec["bom"],
            material=str(spec.material),
            thickness=float(spec.boardThickness),
            remnants=[{"remnantId": "awkward-strip", "w": 2400, "h": 40, "thickness": spec.boardThickness, "materialCode": map_cabinet_material(str(spec.material)).get("code")}],
        )
        helpful = self.nester.nest(
            rec["bom"],
            material=str(spec.material),
            thickness=float(spec.boardThickness),
            remnants=[{"remnantId": "small-fit", "w": 700, "h": 280, "thickness": spec.boardThickness, "materialCode": map_cabinet_material(str(spec.material)).get("code")}],
        )
        return {
            "baselineSheets": baseline["sheetCount"],
            "awkwardSavedSheets": max(0, baseline["sheetCount"] - awkward["sheetCount"]),
            "helpfulSavedSheets": max(0, baseline["sheetCount"] - helpful["sheetCount"]),
            "awkwardEstimatedEquivalent": awkward.get("estimatedSavedSheetEquivalent"),
            "note": "savedNewSheetCount is paired sheetCount delta, not area/sheetArea",
        }

    def quantity_breaks(self, rec: dict[str, Any], quantities: tuple[int, ...] = (1, 10, 20, 50, 100)) -> list[dict[str, Any]]:
        spec = CabinetSpec.model_validate(rec["spec"])
        rows = []
        for q in quantities:
            nest = self.nest_quantity(rec, q)
            unit_sheet = nest["sheetCount"] / q
            pack_cost = rec["packing"]["packagingCost"]
            ship = rec["shipping"]["logisticsFee"]
            landed = self.landed_cost(spec, rec["bom"], nest, rec["packing"], rec["weight"], rec["shipping"], rec["difficulty"])
            rows.append(
                {
                    "quantity": q,
                    "sheetCount": nest["sheetCount"],
                    "sheetsPerUnit": round(unit_sheet, 4),
                    "utilizationRatio": nest.get("utilizationRatio"),
                    "trueWasteRatio": nest.get("trueWasteRatio"),
                    "unitLandedCost": round(landed["unitLandedCost"] / q, 2) if q else landed["unitLandedCost"],
                    "packCost": pack_cost,
                    "logistics": ship,
                    "grossMargin": landed["grossMargin"],
                }
            )
        return rows

    def production_batch(self, recs: list[dict[str, Any]], quantities: list[int], *, tenant_id: str) -> dict[str, Any]:
        batch_id = new_id()
        nest = self.nest_cross_sku(recs, quantities)
        agg: dict[str, dict[str, Any]] = {}
        for rec, qty in zip(recs, quantities):
            for ln in rec["bom"]["lines"]:
                key = str(ln.get("partId") or ln.get("partName"))
                slot = agg.setdefault(key, {**ln, "quantity": 0, "sources": []})
                slot["quantity"] += int(ln.get("quantity") or 1) * qty
                slot["sources"].append({"skuId": rec["spec"]["productId"], "qty": int(ln.get("quantity") or 1) * qty})
        hw_rounds = []
        for ln in agg.values():
            if ln.get("hardware"):
                raw = ln["quantity"]
                pack = 20 if "cam" in str(ln.get("partId")) or "dowel" in str(ln.get("partId")) else max(raw, 1)
                rounded = ((raw + pack - 1) // pack) * pack
                hw_rounds.append({"partId": ln.get("partId"), "need": raw, "purchase": rounded, "source": "ESTIMATED"})
        rec = {
            "batchId": batch_id,
            "tenantId": tenant_id,
            "items": [{"skuId": r["spec"]["productId"], "kind": r["spec"]["kind"], "qty": q} for r, q in zip(recs, quantities)],
            "aggregateBom": list(agg.values()),
            "hardwarePurchasing": hw_rounds,
            "nesting": {k: nest[k] for k in nest if k != "svg"},
            "erp": False,
            "liveMachineControl": False,
        }
        spec0 = recs[0]["spec"]
        created = self.extract_remnants(
            nest,
            material=str(spec0.get("material") or "WOOD_WHITE"),
            thickness=float(spec0.get("boardThickness") or 18),
            run_id=batch_id,
            tenant_id=tenant_id,
        )
        from fox3d.inventory import inventory_delta_manifest

        rec["inventory"] = inventory_delta_manifest(
            batch_id=batch_id,
            tenant_id=tenant_id,
            new_sheets=int(nest.get("sheetCount") or 0),
            remnants_created=created,
            reserved=[],
            consumed=[],
            true_scrap_area=float(nest.get("trueScrapArea") or 0),
            reusable_area=float(nest.get("reusableRemnantArea") or 0),
            used_area=float(nest.get("partUsedArea") or 0),
            sheet_area=float((nest.get("sheetMm") or [2440, 1220])[0] * (nest.get("sheetMm") or [2440, 1220])[1]),
        )
        with self._lock:
            if self._batch_depth == 0:
                self._sync_tenant(tenant_id)
            self.batches[batch_id] = rec
            self._mark_or_persist(tenant_id)
        return rec

    def reverse_from_remnants(self, *, tenant_id: str, remnants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        feasible = []
        max_l = max(float(r["w"]) for r in remnants)
        max_w = max(float(r["h"]) for r in remnants)
        with self.batch_write(tenant_id=tenant_id):
            for kind in ("DESK_RISER", "OPEN_SHELF", "PET_FURNITURE", "MOBILE_SIDE_TABLE", "BEDSIDE_CABINET"):
                rec = self.build_sku(tenant_id=tenant_id, kind=kind, render=False)
                spec = rec["spec"]
                panels = [ln for ln in rec["bom"]["lines"] if not ln.get("hardware")]
                fits = all(max(float(ln.get("length") or 0), float(ln.get("width") or 0)) <= max(max_l, max_w) + 1 for ln in panels)
                if fits and rec["report"]["ok"]:
                    feasible.append({"kind": kind, "productId": spec["productId"], "dimensions": {"width": spec["width"], "height": spec["height"], "depth": spec["depth"]}, "fitsRemnants": True})
        return feasible

    def generate_candidates(self, *, tenant_id: str, count: int = 24, preview_top: int = 3, render: bool = False) -> dict[str, Any]:
        kinds = list(FLATPACK_PRODUCT_TYPES)
        materials = ["WOOD_WHITE", "WOOD_OAK"]
        seeded: list[dict[str, Any]] = []
        i = 0
        with self.batch_write(tenant_id=tenant_id):
            while len(seeded) < max(count, 20):
                kind = kinds[i % len(kinds)]
                mat = materials[i % len(materials)]
                rec = self.build_sku(tenant_id=tenant_id, kind=kind, material=mat, render=False)
                rec["candidateId"] = rec["spec"]["productId"]
                rec["seed"] = i
                seeded.append(rec)
                i += 1
                if i > 80:
                    break
            ranked = [r for r in seeded if r["report"]["ok"] and not r["rdScore"]["engineeringVeto"]]
            ranked.sort(key=lambda r: (-(r["rdScore"]["overallDeterministic"] or 0), r["landed"]["unitLandedCost"]))
            top = ranked[: max(preview_top, 1)]
            if render:
                for rec in top:
                    spec = CabinetSpec.model_validate(rec["spec"])
                    rec["preview"] = self.platform.render_parametric(spec.productId, tenant_id=tenant_id, explode=False)
        board = [self._board_row(r) for r in ranked[:count]]
        return {
            "generated": len(seeded),
            "ranked": len(ranked),
            "top": board[:10],
            "catalog": board,
            "profile": SMALL_SPACE_PROFILE,
            "demandLabel": "MOCK",
            "note": "demand source MOCK — not claimed as bestselling",
        }

    def _board_row(self, rec: dict[str, Any]) -> dict[str, Any]:
        spec = rec["spec"]
        nest = rec.get("nesting") or {}
        return {
            "productId": spec["productId"],
            "kind": spec["kind"],
            "dimensions": {"width": spec["width"], "height": spec["height"], "depth": spec["depth"]},
            "engineeringHash": rec["engineeringHash"],
            "bomHash": rec["bom"].get("bomHash"),
            "commonPartRatio": rec["commonParts"]["commonPartRatio"],
            "sheetCount": nest.get("sheetCount"),
            "utilizationRatio": nest.get("utilizationRatio"),
            "trueWasteRatio": nest.get("trueWasteRatio"),
            "reusableRemnantRatio": nest.get("reusableRemnantRatio"),
            "carton": {"L": rec["packing"]["length"], "W": rec["packing"]["width"], "H": rec["packing"]["height"]},
            "packedWeight": rec["weight"]["grossKg"],
            "assemblyDifficulty": rec["difficulty"]["score"],
            "estimatedMinutes": rec["difficulty"]["estimatedMinutes"],
            "landedCost": rec["landed"]["unitLandedCost"],
            "suggestedPrice": rec["landed"]["suggestedPrice"],
            "demandDataConfidence": rec["demand"]["label"],
            "previewAsset": ((rec.get("preview") or {}).get("job") or {}).get("outputAsset"),
            "approvalState": rec.get("approvalState"),
            "rdScore": rec["rdScore"]["overallDeterministic"],
            "engineeringVeto": rec["rdScore"]["engineeringVeto"],
        }

    def approve_prototype(self, product_id: str, *, actor: str) -> dict[str, Any]:
        with self._lock:
            rec = self.candidates.get(product_id)
            if not rec and self.root is not None:
                self.load()
                rec = self.candidates.get(product_id)
            if not rec:
                raise KeyError(product_id)
            if rec.get("approvalState") not in {"COMMERCIAL_CANDIDATE", "WAITING_PRODUCT_APPROVAL", "DFM_VALID"}:
                raise PermissionError(rec.get("approvalState"))
            rec = dict(rec)
            rec["approvalState"] = "WAITING_PRODUCT_APPROVAL"
            rec["approval"] = {
                "status": "WAITING_PRODUCT_APPROVAL",
                "actor": actor,
                "liveMachineControl": False,
                "forbidden": list(FORBIDDEN_STATES),
            }
            self.candidates[product_id] = rec
            self._mark_or_persist(self._candidate_tenant(rec))
            return rec

    def confirm_prototype(self, product_id: str, *, actor: str) -> dict[str, Any]:
        with self._lock:
            rec = self.approve_prototype(product_id, actor=actor)
            rec["approvalState"] = "APPROVED_FOR_PROTOTYPE"
            rec["approval"]["status"] = "APPROVED_FOR_PROTOTYPE"
            rec["approval"]["note"] = "Prototype only; APPROVED_FOR_PRODUCTION / LIVE_CNC forbidden."
            self.candidates[product_id] = rec
            self._mark_or_persist(self._candidate_tenant(rec))
            return rec

    def ecommerce_assets(self, *, tenant_id: str, product_id: str) -> dict[str, Any]:
        record = self.platform.parametrics.get(product_id)
        if not record:
            raise KeyError(product_id)
        hero = self.platform.render_parametric(product_id, tenant_id=tenant_id)
        explode = self.platform.render_parametric(product_id, tenant_id=tenant_id, explode=True)
        twin = self.platform.create_twin(
            {
                "tenantId": tenant_id,
                "sku": record["spec"].get("kind") or product_id,
                "dimensions": {
                    "width": record["spec"]["width"],
                    "height": record["spec"]["height"],
                    "depth": record["spec"]["depth"],
                },
            }
        )
        p360 = None
        if not self.platform._production_gate():
            p360 = self.platform.product_360_e2e(tenant_id=tenant_id, twin_id=twin["twinId"], frames=36)
        ar = {
            "realDimensionsMm": {"width": record["spec"]["width"], "height": record["spec"]["height"], "depth": record["spec"]["depth"]},
            "placementIntent": "floor",
            "boundingBox": [record["spec"]["width"], record["spec"]["depth"], record["spec"]["height"]],
            "anchor": "floor-origin",
            "runtime": "PARTIAL",
            "label": "PARTIAL",
        }
        rec = self.candidates.get(product_id) or {}
        graph = rec.get("assemblyGraph") or {}
        steps = []
        for step in graph.get("steps") or []:
            steps.append({**step, "imageFrom": "assembly_graph", "previewJob": (explode.get("job") or {}).get("jobId")})
        return {
            "hero": hero,
            "exploded": explode,
            "flatPackView": explode,
            "recipes": ["WHITE_STUDIO", "HERO_SHOT", "THREE_QUARTER", "DETAIL"],
            "twin": twin,
            "p360": p360,
            "ar": ar,
            "instructionAssets": steps,
            "sameQueue": True,
            "sameTwinStore": True,
        }

    def readiness(self, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        ev = evidence or {}
        core = bool(ev.get("coreFactoryE2E"))
        kd = bool(ev.get("kdWasteV2") and ev.get("kdPacking") and ev.get("kdRemnants"))
        cost = bool(ev.get("kdLandedCost"))
        market = bool(ev.get("liveDemand"))
        vision = bool(ev.get("liveVision"))
        video = bool(ev.get("liveVideo"))
        sandbox = bool(ev.get("osJail"))
        cnc = bool(ev.get("liveCnc"))
        ci = bool(ev.get("ciStatus"))
        real_provider_cost = bool(ev.get("realProviderCost"))
        matrix = {
            "coreFactoryE2EReady": core,
            "kdDfMReady": kd,
            "estimatedCostModelReady": cost,
            "realProviderCostReady": real_provider_cost,
            "commercialQuoteReady": bool(cost and real_provider_cost and market),
            "commercialCostModelReady": cost,
            "commercialCostModelScope": "CONFIG_ESTIMATE_ONLY",
            "marketDemandVerified": market,
            "liveVisionReady": vision,
            "liveVideoReady": video,
            "osSandboxReady": sandbox,
            "liveMachineControlReady": cnc,
            "ciEvidenceReady": ci,
        }
        matrix["fullAutonomousFactoryReady"] = all(
            [
                matrix["coreFactoryE2EReady"],
                matrix["kdDfMReady"],
                matrix["realProviderCostReady"],
                matrix["commercialQuoteReady"],
                matrix["marketDemandVerified"],
                matrix["liveVisionReady"],
                matrix["liveVideoReady"],
                matrix["osSandboxReady"],
                matrix["liveMachineControlReady"],
                matrix["ciEvidenceReady"],
            ]
        )
        matrix["requiredChecks"] = {
            "coreFactoryE2EReady": ["real Blender furniture factory E2E"],
            "kdDfMReady": ["waste V2 conservation", "remnant extract/consume-once", "packing derived from panels"],
            "estimatedCostModelReady": ["CONFIG/ESTIMATED landed cost lineage"],
            "realProviderCostReady": ["REAL_PROVIDER cost/logistics APIs"],
            "commercialQuoteReady": ["REAL_PROVIDER cost + freshness + demand"],
            "commercialCostModelReady": ["compat alias of estimatedCostModelReady; scope=CONFIG_ESTIMATE_ONLY"],
            "marketDemandVerified": ["live DemandSignal Provider"],
            "liveVisionReady": ["registered vision adapter"],
            "liveVideoReady": ["registered video ProviderAdapter"],
            "osSandboxReady": ["OS jail"],
            "liveMachineControlReady": ["forbidden this round"],
            "ciEvidenceReady": ["GitHub Actions pytest GREEN on this SHA"],
        }
        matrix["productionReady"] = core
        matrix["productionReadyScope"] = "coreFactoryE2E"
        return matrix
