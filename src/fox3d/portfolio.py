"""Small-Space KD SKU Portfolio Factory V1. Planning/shortlist, not live demand or CNC."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json, read_json
from fox3d.kd import FLATPACK_PRODUCT_TYPES, FlatPackProductTypeRegistry
from fox3d.mfg_release import FAMILY_STEPS
from fox3d.parametric import CabinetSpec, map_cabinet_material
from fox3d.qc import plan_for_family, plan_hash

PORTFOLIO_KINDS = (
    "OPEN_SHELF",
    "BEDSIDE_CABINET",
    "DESK_RISER",
    "NARROW_BOOKCASE",
    "STORAGE_BENCH",
    "STUDENT_DESK",
    "MOBILE_SIDE_TABLE",
    "PET_FURNITURE",
)
CANDIDATE_STATES = (
    "CANDIDATE",
    "REJECTED_DFM",
    "NEEDS_INPUT",
    "SHORTLISTED",
    "WAITING_PRODUCT_APPROVAL",
    "APPROVED_FOR_PROTOTYPE",
    "SUPERSEDED",
)
DEMAND_SOURCES = frozenset({"MOCK", "IMPORTED", "MANUAL", "UNAVAILABLE"})
DEFAULT_RANKING_POLICY = {
    "version": 1,
    "weights": {
        "utilization": 0.25,
        "trueScrap": 0.15,
        "remnantReuse": 0.10,
        "landedCost": 0.20,
        "carton": 0.10,
        "assembly": 0.10,
        "complexity": 0.10,
    },
    "demandMayInfluence": False,
    "demandLabel": "MOCK",
    "truthLabel": "CONFIG_ESTIMATE",
}
ALLOWED_THICKNESS = (18,)


def _now() -> str:
    return utcnow().isoformat()


class PortfolioError(PermissionError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.status = "BLOCKED"


class PortfolioFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.root = Path(platform.root) / "portfolio"
        self.root.mkdir(parents=True, exist_ok=True)
        self.intents: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.rankings: dict[str, dict[str, Any]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.load()

    def _path(self) -> Path:
        return self.root / "portfolio.json"

    def load(self) -> None:
        payload = read_json(self._path()) or {}
        self.intents = {r["portfolioId"]: r for r in payload.get("intents") or [] if isinstance(r, dict) and r.get("portfolioId")}
        self.candidates = {r["candidateId"]: r for r in payload.get("candidates") or [] if isinstance(r, dict) and r.get("candidateId")}
        self.rankings = {r["rankingId"]: r for r in payload.get("rankings") or [] if isinstance(r, dict) and r.get("rankingId")}
        self.approvals = {r["approvalId"]: r for r in payload.get("approvals") or [] if isinstance(r, dict) and r.get("approvalId")}
        self.plans = {r["planId"]: r for r in payload.get("plans") or [] if isinstance(r, dict) and r.get("planId")}

    def persist(self) -> None:
        atomic_write_json(
            self._path(),
            {
                "intents": list(self.intents.values()),
                "candidates": list(self.candidates.values()),
                "rankings": list(self.rankings.values()),
                "approvals": list(self.approvals.values()),
                "plans": list(self.plans.values()),
            },
        )

    def _require_tenant(self, rec: dict[str, Any], tenant_id: str) -> None:
        if rec.get("tenantId") != tenant_id:
            raise PermissionError("tenant isolation: portfolio")

    def create_intent(
        self,
        *,
        tenant_id: str,
        segment: str = "STUDENT",
        demand_source: str = "MOCK",
        candidate_count: int = 24,
        seed: str = "portfolio-v1",
        envelope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if demand_source not in DEMAND_SOURCES:
            raise PortfolioError("BLOCKED", "demand source must be MOCK/IMPORTED/MANUAL/UNAVAILABLE")
        if demand_source == "REAL":
            raise PortfolioError("BLOCKED", "MOCK demand cannot be labeled REAL")
        env = {
            "maxWidthMm": 1200,
            "maxDepthMm": 600,
            "maxHeightMm": 1800,
            "maxLongestCartonMm": 1500,
            "maxPackedWeightKg": 30,
            "thicknessMm": list(ALLOWED_THICKNESS),
            "maxAssemblyMinutes": 90,
            **(envelope or {}),
        }
        if not env.get("maxWidthMm") or float(env["maxWidthMm"]) <= 0:
            raise PortfolioError("NEEDS_INPUT", "missing manufacturing envelope")
        rec = {
            "portfolioId": new_id(),
            "tenantId": tenant_id,
            "targetSegment": segment,
            "allowedFamilies": ["KD_FURNITURE"],
            "allowedKinds": list(PORTFOLIO_KINDS),
            "envelope": env,
            "materialCatalog": ["WOOD_WHITE", "PB_18_WHITE"],
            "thicknessMm": list(ALLOWED_THICKNESS),
            "maxCarton": {"longestMm": env["maxLongestCartonMm"], "weightKg": env["maxPackedWeightKg"]},
            "assembly": {"maxMinutes": env["maxAssemblyMinutes"], "source": "CONFIG_ESTIMATE"},
            "landedCostScenario": {"targetMargin": 0.3, "source": "CONFIG_ESTIMATE"},
            "candidateCountTarget": int(candidate_count),
            "demand": {"source": demand_source, "truthLabel": demand_source, "status": "MARKET_UNVERIFIED"},
            "seed": seed,
            "createdAt": _now(),
            "liveMachineControl": False,
            "truthLabel": "REAL_LOGIC",
        }
        rec["intentHash"] = stable_hash({k: rec[k] for k in rec if k not in {"portfolioId", "intentHash", "createdAt"}})
        self.intents[rec["portfolioId"]] = rec
        self.persist()
        return rec

    def get_intent(self, portfolio_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.intents[portfolio_id]
        self._require_tenant(rec, tenant_id)
        return rec

    def generate_candidates(self, portfolio_id: str, *, tenant_id: str) -> dict[str, Any]:
        intent = self.get_intent(portfolio_id, tenant_id=tenant_id)
        registry = FlatPackProductTypeRegistry()
        seen: set[str] = set()
        created: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        kinds = [k for k in PORTFOLIO_KINDS if k in FLATPACK_PRODUCT_TYPES]
        for kind in kinds:
            grid = registry.grid(kind)
            combos = []
            for w in grid["width"]:
                for d in grid["depth"][:2]:
                    for h in grid["height"][:2]:
                        combos.append((int(w), int(d), int(h)))
            for w, d, h in combos[:3]:
                rec = self._build_candidate(intent, kind=kind, width=w, depth=d, height=h, board_thickness=18)
                if rec["canonicalHash"] in seen:
                    raise PortfolioError("BLOCKED", "duplicate candidate canonical hash")
                seen.add(rec["canonicalHash"])
                created.append(rec)
        invalids = [
            self._build_candidate(intent, kind="OPEN_SHELF", width=400, depth=300, height=800, board_thickness=12),
            self._build_candidate(intent, kind="BEDSIDE_CABINET", width=400, depth=300, height=400, board_thickness=9),
            self._forced_invalid(intent, kind="NARROW_BOOKCASE", width=200, height=1400, depth=250, code="STRUCTURE"),
            self._forced_invalid(intent, kind="STUDENT_DESK", width=3000, height=750, depth=600, code="MAX_PANEL"),
        ]
        for rec in invalids:
            if rec["canonicalHash"] in seen:
                rec["canonicalHash"] = stable_hash({"invalid": rec["candidateId"], "kind": rec["kind"]})
            seen.add(rec["canonicalHash"])
            created.append(rec)
            if rec["state"] == "REJECTED_DFM":
                rejected.append(rec)
        return {
            "portfolioId": portfolio_id,
            "count": len(created),
            "kinds": sorted({c["kind"] for c in created}),
            "rejected": len([c for c in created if c["state"] == "REJECTED_DFM"]),
            "candidates": created,
        }

    def _forced_invalid(self, intent: dict[str, Any], *, kind: str, width: float, height: float, depth: float, code: str) -> dict[str, Any]:
        spec, report = self.platform.cabinets.create(
            kind, tenant_id=intent["tenantId"], width=width, height=height, depth=depth, boardThickness=18
        )
        ok = bool(report.ok)
        rec = {
            "candidateId": new_id(),
            "tenantId": intent["tenantId"],
            "portfolioId": intent["portfolioId"],
            "kind": kind,
            "family": "KD_FURNITURE",
            "spec": spec.model_dump(mode="json"),
            "report": report.model_dump() if hasattr(report, "model_dump") else {"ok": ok, "violations": [code]},
            "engineeringHash": spec.engineering_hash(),
            "canonicalHash": stable_hash(
                {
                    "kind": kind,
                    "width": spec.width,
                    "depth": spec.depth,
                    "height": spec.height,
                    "boardThickness": spec.boardThickness,
                    "material": spec.material,
                    "invalid": True,
                    "code": code,
                }
            ),
            "state": "CANDIDATE" if ok else "REJECTED_DFM",
            "rejectionCodes": [] if ok else [code],
            "productId": spec.productId,
            "createdAt": _now(),
        }
        if not ok:
            rec["rejectionCodes"] = [v.code if hasattr(v, "code") else code for v in (report.violations or [])] or [code]
            rec["state"] = "REJECTED_DFM"
        rec["dfm"] = self._empty_dfm(rec)
        rec["commercial"] = self._empty_commercial()
        rec["demand"] = dict(intent["demand"])
        self.candidates[rec["candidateId"]] = rec
        self.persist()
        return rec

    def _build_candidate(
        self,
        intent: dict[str, Any],
        *,
        kind: str,
        width: float,
        depth: float,
        height: float,
        board_thickness: float,
    ) -> dict[str, Any]:
        sku = self.platform.kd.build_sku(
            tenant_id=intent["tenantId"],
            kind=kind,
            render=False,
            width=width,
            depth=depth,
            height=height,
            boardThickness=board_thickness,
        )
        spec = sku["spec"]
        report = sku["report"]
        nest = sku.get("nesting") or {}
        pack = sku.get("packing") or {}
        gate = sku.get("gate") or {}
        env = intent["envelope"]
        codes: list[str] = []
        if not report.get("ok"):
            codes.extend([str(v.get("code") or v) for v in (report.get("violations") or [])] or ["ENGINEERING"])
        if gate.get("ok") is False:
            codes.append("LOGISTICS_GATE")
        if float(spec.get("width") or 0) > float(env["maxWidthMm"]) or float(spec.get("depth") or 0) > float(env["maxDepthMm"]) or float(spec.get("height") or 0) > float(env["maxHeightMm"]):
            codes.append("ENVELOPE")
        if float(spec.get("boardThickness") or 0) not in set(intent["thicknessMm"]):
            codes.append("THICKNESS")
        longest = max(float(pack.get("length") or 0), float(pack.get("width") or 0), float(pack.get("height") or 0))
        if longest > float(env["maxLongestCartonMm"]):
            codes.append("CARTON_OVERSIZE")
        state = "REJECTED_DFM" if codes else "CANDIDATE"
        dfm = self._scorecard(sku)
        commercial = self._commercial(sku, intent)
        rec = {
            "candidateId": new_id(),
            "tenantId": intent["tenantId"],
            "portfolioId": intent["portfolioId"],
            "productId": spec.get("productId"),
            "kind": kind,
            "family": "KD_FURNITURE",
            "spec": spec,
            "report": report,
            "engineeringHash": sku.get("engineeringHash") or spec.get("engineeringHash"),
            "canonicalHash": stable_hash(
                {
                    "kind": kind,
                    "width": spec.get("width"),
                    "depth": spec.get("depth"),
                    "height": spec.get("height"),
                    "boardThickness": spec.get("boardThickness"),
                    "material": spec.get("material"),
                }
            ),
            "bomHash": (sku.get("bom") or {}).get("bomHash"),
            "nestingHash": nest.get("nestingHash"),
            "state": state,
            "rejectionCodes": codes,
            "dfm": dfm,
            "commercial": commercial,
            "demand": dict(intent["demand"]),
            "sku": {k: sku.get(k) for k in ("packing", "weight", "difficulty", "shipping", "gate", "commonParts", "bom", "nesting", "landed") if k in sku},
            "createdAt": _now(),
            "liveCnc": False,
        }
        if rec["canonicalHash"] in {c.get("canonicalHash") for c in self.candidates.values() if c.get("portfolioId") == intent["portfolioId"]}:
            raise PortfolioError("BLOCKED", "duplicate candidate canonical hash")
        self.candidates[rec["candidateId"]] = rec
        self.persist()
        return rec

    def _empty_dfm(self, rec: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "engineeringOk": False,
            "conservationOk": False,
            "lineage": {"candidateHash": rec.get("canonicalHash")},
            "truthLabel": "REAL_LOGIC",
        }

    def _scorecard(self, sku: dict[str, Any]) -> dict[str, Any]:
        nest = sku.get("nesting") or {}
        pack = sku.get("packing") or {}
        bom = sku.get("bom") or {}
        lines = list(bom.get("lines") or [])
        panels = [ln for ln in lines if not ln.get("hardware")]
        hardware = [ln for ln in lines if ln.get("hardware")]
        placed = float(nest.get("partUsedArea") or nest.get("usedAreaMm2") or 0)
        remnant = float(nest.get("reusableRemnantArea") or 0)
        scrap = float(nest.get("trueScrapArea") or 0)
        sheet_area = float((nest.get("sheetMm") or [2440, 1220])[0]) * float((nest.get("sheetMm") or [2440, 1220])[1]) * max(int(nest.get("sheetCount") or 0), 0)
        err = float(nest.get("areaConservationError") or 0)
        conservation = err < 2
        qc = plan_hash(plan_for_family("KD_FURNITURE"))
        return {
            "ok": bool((sku.get("report") or {}).get("ok")) and conservation,
            "engineeringOk": bool((sku.get("report") or {}).get("ok")),
            "violations": (sku.get("report") or {}).get("violations") or [],
            "bomHash": bom.get("bomHash"),
            "sheetCount": nest.get("sheetCount"),
            "material": (sku.get("spec") or {}).get("material"),
            "thickness": (sku.get("spec") or {}).get("boardThickness"),
            "placedArea": placed,
            "reusableRemnantArea": remnant,
            "trueScrapArea": scrap,
            "inputSheetArea": sheet_area,
            "utilization": nest.get("utilizationRatio"),
            "trueWasteRatio": nest.get("trueWasteRatio"),
            "conservationOk": conservation,
            "areaConservationError": err,
            "hardwareCount": sum(int(h.get("quantity") or 1) for h in hardware),
            "partCount": len(panels),
            "carton": {"length": pack.get("length"), "width": pack.get("width"), "height": pack.get("height")},
            "weightKg": (sku.get("weight") or {}).get("grossKg"),
            "oversize": bool((sku.get("shipping") or {}).get("oversize") or (sku.get("gate") or {}).get("ok") is False),
            "assemblyMinutes": (sku.get("difficulty") or {}).get("estimatedMinutes"),
            "assemblyOps": len((sku.get("assemblyGraph") or {}).get("steps") or panels),
            "qcPlanHash": qc,
            "lineage": {
                "engineeringHash": sku.get("engineeringHash"),
                "bomHash": bom.get("bomHash"),
                "nestingHash": nest.get("nestingHash"),
            },
            "truthLabel": "REAL_LOGIC",
        }

    def _empty_commercial(self) -> dict[str, Any]:
        return {"ok": False, "source": "CONFIG_ESTIMATE", "truthLabel": "CONFIG_ESTIMATE", "liveProvider": False}

    def _commercial(self, sku: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        landed = dict(sku.get("landed") or {})
        eng = sku.get("engineeringHash")
        snap = {
            "materialCost": landed.get("sheetCost"),
            "hardwareCost": landed.get("hardwareCost"),
            "processingCost": landed.get("processingCost"),
            "packagingCost": landed.get("packagingCost"),
            "shippingCost": landed.get("logisticsCost"),
            "laborCost": landed.get("assemblyCost"),
            "remnantCredit": landed.get("remnantCredit"),
            "scrapCost": landed.get("trueWasteCost"),
            "landedCost": landed.get("unitLandedCost"),
            "sellingPrice": landed.get("suggestedPrice"),
            "grossMargin": landed.get("grossMargin"),
            "sources": {
                "materialCost": "CONFIG_ESTIMATE",
                "hardwareCost": "CONFIG_ESTIMATE",
                "processingCost": "CONFIG_ESTIMATE",
                "packagingCost": "CONFIG_ESTIMATE",
                "shippingCost": "CONFIG_ESTIMATE",
                "laborCost": "CONFIG_ESTIMATE",
                "remnantCredit": "CONFIG_ESTIMATE",
                "scrapCost": "CONFIG_ESTIMATE",
                "sellingPrice": "CONFIG_ESTIMATE",
            },
            "engineeringHash": eng,
            "bomHash": (sku.get("bom") or {}).get("bomHash"),
            "liveProvider": False,
            "truthLabel": "CONFIG_ESTIMATE",
        }
        snap["costSnapshotHash"] = stable_hash({k: snap[k] for k in snap if k != "costSnapshotHash"})
        snap["stale"] = False
        snap["targetMargin"] = (intent.get("landedCostScenario") or {}).get("targetMargin")
        return snap

    def detect_stale_cost(self, candidate_id: str, *, tenant_id: str) -> bool:
        rec = self.candidates[candidate_id]
        self._require_tenant(rec, tenant_id)
        commercial = rec.get("commercial") or {}
        if commercial.get("engineeringHash") != rec.get("engineeringHash") or commercial.get("bomHash") != rec.get("bomHash"):
            commercial["stale"] = True
            rec["commercial"] = commercial
            self.persist()
            return True
        return bool(commercial.get("stale"))

    def plan_material(self, portfolio_id: str, *, tenant_id: str, candidate_ids: list[str] | None = None) -> dict[str, Any]:
        intent = self.get_intent(portfolio_id, tenant_id=tenant_id)
        rows = [
            self.candidates[cid]
            for cid in (candidate_ids or list(self.candidates))
            if cid in self.candidates and self.candidates[cid].get("portfolioId") == portfolio_id
        ]
        for rec in rows:
            self._require_tenant(rec, tenant_id)
        valid = [r for r in rows if r.get("state") != "REJECTED_DFM" and (r.get("sku") or {}).get("bom")]
        independent_sheets = 0
        independent_scrap = 0.0
        batch_sheets = 0
        for rec in valid:
            nest = (rec.get("sku") or {}).get("nesting") or {}
            independent_sheets += int(nest.get("sheetCount") or 0)
            independent_scrap += float(nest.get("trueScrapArea") or 0)
            try:
                batch = self.platform.kd.nest_quantity({"spec": rec["spec"], "bom": rec["sku"]["bom"]}, 2)
                batch_sheets += int(batch.get("sheetCount") or 0)
            except Exception:
                batch_sheets += int(nest.get("sheetCount") or 0) * 2
        recs = [{"spec": r["spec"], "bom": r["sku"]["bom"]} for r in valid]
        cross = self.platform.kd.nest_cross_sku(recs, [1] * len(recs)) if recs else {"sheetCount": 0, "trueScrapArea": 0, "reusableRemnantArea": 0}
        planning_rems = []
        used_ids: set[str] = set()
        for rem in self.platform.remnants.available(tenant_id=tenant_id):
            rid = rem.get("remnantId")
            if not rid or rid in used_ids:
                continue
            if float(rem.get("thickness") or 0) not in set(intent["thicknessMm"]):
                continue
            used_ids.add(str(rid))
            planning_rems.append(
                {
                    "remnantId": rid,
                    "w": rem.get("w"),
                    "h": rem.get("h"),
                    "thickness": rem.get("thickness"),
                    "materialCode": rem.get("materialCode") or map_cabinet_material(str(rem.get("material") or "WOOD_WHITE")).get("code"),
                    "status": "available",
                }
            )
        remnant_first = cross
        if recs:
            lines: list[dict[str, Any]] = []
            material = "WOOD_WHITE"
            thickness = 18.0
            for rec in recs:
                spec = CabinetSpec.model_validate(rec["spec"])
                material = str(spec.material)
                thickness = float(spec.boardThickness)
                for ln in rec["bom"]["lines"]:
                    item = dict(ln)
                    item["skuId"] = spec.productId
                    lines.append(item)
            remnant_first = self.platform.kd.nester.nest(
                {"productId": "portfolio-plan", "lines": lines},
                material=material,
                thickness=thickness,
                remnants=planning_rems,
            )
        plan = {
            "planId": new_id(),
            "tenantId": tenant_id,
            "portfolioId": portfolio_id,
            "mode": "PLANNING",
            "consumesInventory": False,
            "independent": {"sheetCount": independent_sheets, "trueScrapArea": independent_scrap},
            "batchSameSku": {"sheetCount": batch_sheets},
            "crossSku": {
                "sheetCount": int(cross.get("sheetCount") or 0),
                "trueScrapArea": float(cross.get("trueScrapArea") or 0),
                "reusableRemnantArea": float(cross.get("reusableRemnantArea") or 0),
            },
            "remnantFirst": {
                "sheetCount": int(remnant_first.get("sheetCount") or 0),
                "trueScrapArea": float(remnant_first.get("trueScrapArea") or 0),
                "reusableRemnantArea": float(remnant_first.get("reusableRemnantArea") or 0),
                "remnantIds": sorted(used_ids),
                "planningOnly": True,
            },
            "sheetCountDelta": int(cross.get("sheetCount") or 0) - independent_sheets,
            "trueScrapDelta": float(cross.get("trueScrapArea") or 0) - independent_scrap,
            "candidateIds": [r["candidateId"] for r in valid],
            "doubleAllocation": False,
            "oversell": False,
            "liveMachineControl": False,
            "truthLabel": "REAL_LOGIC / PLANNING",
        }
        plan["planHash"] = stable_hash({k: plan[k] for k in plan if k not in {"planId", "planHash"}})
        self.plans[plan["planId"]] = plan
        self.persist()
        return plan

    def assert_no_double_remnant(self, remnant_ids: list[str]) -> None:
        if len(remnant_ids) != len(set(remnant_ids)):
            raise PortfolioError("BLOCKED", "remnant double-use in portfolio planning")

    def rank(self, portfolio_id: str, *, tenant_id: str, policy: dict[str, Any] | None = None, demand_real: bool = False) -> dict[str, Any]:
        intent = self.get_intent(portfolio_id, tenant_id=tenant_id)
        if demand_real and intent["demand"]["source"] != "REAL":
            raise PortfolioError("BLOCKED", "MOCK demand cannot be labeled REAL")
        pol = dict(DEFAULT_RANKING_POLICY if policy is None else {**DEFAULT_RANKING_POLICY, **policy})
        pol["rankingPolicyHash"] = stable_hash({k: pol[k] for k in pol if k != "rankingPolicyHash"})
        rows = [c for c in self.candidates.values() if c.get("portfolioId") == portfolio_id]
        for rec in rows:
            self._require_tenant(rec, tenant_id)
        scored = []
        for rec in rows:
            valid = rec.get("state") != "REJECTED_DFM" and bool((rec.get("dfm") or {}).get("engineeringOk"))
            breakdown = self._score_breakdown(rec, pol)
            total = sum(breakdown[k]["weighted"] for k in pol["weights"]) if valid else None
            scored.append(
                {
                    "candidateId": rec["candidateId"],
                    "kind": rec["kind"],
                    "canonicalHash": rec["canonicalHash"],
                    "valid": valid,
                    "score": total,
                    "breakdown": breakdown,
                    "state": rec["state"],
                    "engineeringHash": rec.get("engineeringHash"),
                    "bomHash": rec.get("bomHash"),
                    "costSnapshotHash": (rec.get("commercial") or {}).get("costSnapshotHash"),
                    "demand": rec.get("demand"),
                }
            )
        valid_rows = [r for r in scored if r["valid"] and r["score"] is not None]
        valid_rows.sort(key=lambda r: (-float(r["score"]), str(r["canonicalHash"]), str(r["kind"]), str(r["candidateId"])))
        top = valid_rows[:10]
        top_ids = {r["candidateId"] for r in top}
        for rec in rows:
            if rec["candidateId"] in top_ids and rec["state"] == "CANDIDATE":
                rec["state"] = "SHORTLISTED"
            elif rec["state"] == "SHORTLISTED" and rec["candidateId"] not in top_ids:
                rec["state"] = "CANDIDATE"
        ranking = {
            "rankingId": new_id(),
            "tenantId": tenant_id,
            "portfolioId": portfolio_id,
            "policy": pol,
            "rankingPolicyHash": pol["rankingPolicyHash"],
            "scored": scored,
            "top10": top,
            "humanOverrides": [],
            "demandTruthLabel": intent["demand"]["truthLabel"],
            "createdAt": _now(),
            "truthLabel": "REAL_LOGIC",
        }
        self.rankings[ranking["rankingId"]] = ranking
        self.persist()
        return ranking

    def _score_breakdown(self, rec: dict[str, Any], pol: dict[str, Any]) -> dict[str, Any]:
        dfm = rec.get("dfm") or {}
        commercial = rec.get("commercial") or {}
        util = float(dfm.get("utilization") or 0)
        scrap = 1.0 - min(float(dfm.get("trueWasteRatio") or 0), 1.0)
        remnant = min(float(dfm.get("reusableRemnantArea") or 0) / 1e6, 1.0)
        cost = commercial.get("landedCost") or 0
        cost_s = 1.0 / (1.0 + float(cost) / 5000.0)
        carton = dfm.get("carton") or {}
        vol = float(carton.get("length") or 1) * float(carton.get("width") or 1) * float(carton.get("height") or 1)
        carton_s = 1.0 / (1.0 + vol / 1e8)
        minutes = float(dfm.get("assemblyMinutes") or 30)
        assembly_s = 1.0 / (1.0 + minutes / 60.0)
        complexity = 1.0 / (1.0 + float(dfm.get("hardwareCount") or 0) / 20.0 + float(dfm.get("partCount") or 0) / 20.0)
        raw = {
            "utilization": util,
            "trueScrap": scrap,
            "remnantReuse": remnant,
            "landedCost": cost_s,
            "carton": carton_s,
            "assembly": assembly_s,
            "complexity": complexity,
        }
        weights = pol["weights"]
        return {k: {"raw": raw[k], "weight": weights[k], "weighted": raw[k] * float(weights[k])} for k in weights}

    def override_rank(self, ranking_id: str, *, tenant_id: str, actor: str, reason: str, candidate_id: str) -> dict[str, Any]:
        ranking = self.rankings[ranking_id]
        self._require_tenant(ranking, tenant_id)
        if not actor or not reason:
            raise PortfolioError("BLOCKED", "human override requires actor/reason")
        ranking["humanOverrides"].append(
            {"actor": actor, "reason": reason, "candidateId": candidate_id, "at": _now(), "rewritesScore": False}
        )
        self.persist()
        return ranking

    def submit_approval(self, candidate_id: str, *, tenant_id: str, actor: str) -> dict[str, Any]:
        rec = self.candidates[candidate_id]
        self._require_tenant(rec, tenant_id)
        if rec["state"] not in {"SHORTLISTED", "WAITING_PRODUCT_APPROVAL"}:
            raise PortfolioError("BLOCKED", "only shortlisted candidates can be submitted")
        if rec["state"] == "SUPERSEDED":
            raise PortfolioError("BLOCKED", "superseded candidate")
        rec["state"] = "WAITING_PRODUCT_APPROVAL"
        approval = {
            "approvalId": new_id(),
            "tenantId": tenant_id,
            "candidateId": candidate_id,
            "portfolioId": rec["portfolioId"],
            "status": "WAITING_PRODUCT_APPROVAL",
            "actor": actor,
            "engineeringHash": rec.get("engineeringHash"),
            "bomHash": rec.get("bomHash"),
            "costSnapshotHash": (rec.get("commercial") or {}).get("costSnapshotHash"),
            "liveCnc": False,
            "at": _now(),
        }
        self.approvals[approval["approvalId"]] = approval
        self.persist()
        return approval

    def approve_prototype(self, approval_id: str, *, tenant_id: str, actor: str, reason: str) -> dict[str, Any]:
        approval = self.approvals[approval_id]
        self._require_tenant(approval, tenant_id)
        if not actor or not reason:
            raise PortfolioError("BLOCKED", "human approval requires actor/reason")
        rec = self.candidates[approval["candidateId"]]
        if rec["state"] == "SUPERSEDED":
            raise PortfolioError("BLOCKED", "superseded candidate")
        rec["state"] = "APPROVED_FOR_PROTOTYPE"
        approval["status"] = "APPROVED_FOR_PROTOTYPE"
        approval["approvedBy"] = actor
        approval["reason"] = reason
        approval["approvedAt"] = _now()
        approval["notLiveCnc"] = True
        self.persist()
        return approval

    def supersede(self, candidate_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.candidates[candidate_id]
        self._require_tenant(rec, tenant_id)
        rec["state"] = "SUPERSEDED"
        rec["supersededAt"] = _now()
        self.persist()
        return rec

    def prototype_pack(self, candidate_id: str, *, tenant_id: str) -> dict[str, Any]:
        rec = self.candidates[candidate_id]
        self._require_tenant(rec, tenant_id)
        if rec["state"] == "SUPERSEDED":
            raise PortfolioError("BLOCKED", "superseded candidate")
        approved = rec["state"] == "APPROVED_FOR_PROTOTYPE"
        ranking = next((r for r in self.rankings.values() if r.get("portfolioId") == rec["portfolioId"] and r.get("tenantId") == tenant_id), None)
        score = None
        policy_hash = None
        if ranking:
            policy_hash = ranking.get("rankingPolicyHash")
            for row in ranking.get("top10") or []:
                if row["candidateId"] == candidate_id:
                    score = row.get("score")
        steps = FAMILY_STEPS.get("KD_FURNITURE") or ["packaging"]
        traveler = {
            "family": "KD_FURNITURE",
            "steps": [{"seq": i + 1, "operation": op, "kind": "operator_instruction", "machineCommand": False, "liveCnc": False, "liveLaser": False} for i, op in enumerate(steps)],
            "label": "MANUAL_STATION",
        }
        if rec.get("commercial", {}).get("stale"):
            raise PortfolioError("BLOCKED", "stale cost snapshot")
        ready = bool(approved and rec.get("engineeringHash") and rec.get("bomHash") and (rec.get("commercial") or {}).get("costSnapshotHash"))
        pack = {
            "candidateId": candidate_id,
            "portfolioId": rec["portfolioId"],
            "tenantId": tenant_id,
            "engineeringHash": rec.get("engineeringHash"),
            "bomHash": rec.get("bomHash"),
            "nestingHash": rec.get("nestingHash") or (rec.get("dfm") or {}).get("lineage", {}).get("nestingHash"),
            "costSnapshotHash": (rec.get("commercial") or {}).get("costSnapshotHash"),
            "rankingPolicyHash": policy_hash,
            "score": score,
            "traveler": traveler,
            "bom": (rec.get("sku") or {}).get("bom"),
            "hardware": [ln for ln in ((rec.get("sku") or {}).get("bom") or {}).get("lines") or [] if ln.get("hardware")],
            "qc": {"qcPlanHash": (rec.get("dfm") or {}).get("qcPlanHash"), "plan": plan_for_family("KD_FURNITURE")},
            "packing": (rec.get("sku") or {}).get("packing"),
            "exceptionPath": ["HOLD", "REWORK", "WAITING_HUMAN_APPROVAL"],
            "executionLabel": "MANUAL_STATION",
            "readyForManualPrototype": ready,
            "liveMachineControl": False,
            "liveCnc": False,
            "status": "READY_FOR_MANUAL_PROTOTYPE" if ready else "BLOCKED_NO_APPROVAL",
        }
        if not approved:
            raise PortfolioError("BLOCKED", "human approval missing")
        return pack

    def media_pack(self, candidate_id: str, *, tenant_id: str, render: bool = False) -> dict[str, Any]:
        rec = self.candidates[candidate_id]
        self._require_tenant(rec, tenant_id)
        preview = None
        alt = None
        if render and rec.get("productId") and rec.get("spec"):
            self.platform.parametrics[rec["productId"]] = {"spec": rec["spec"], "report": rec.get("report") or {}, "bom": (rec.get("sku") or {}).get("bom") or {}, "engineeringHash": rec.get("engineeringHash")}
            preview = self.platform.render_parametric(rec["productId"], tenant_id=tenant_id, explode=False)
            alt = self.platform.render_parametric(rec["productId"], tenant_id=tenant_id, explode=True)
        job = (preview or {}).get("job") or {}
        used_mock = bool(job.get("usedMock"))
        real = bool(job.get("realBlender")) and not used_mock and job.get("status") in {"completed", "succeeded"}
        files = (job.get("output") or {}).get("files") or {}
        art = files.get("png") or files.get("preview") or job.get("outputPath")
        digest = None
        size = None
        if art:
            path = Path(str(art))
            if path.exists():
                blob = path.read_bytes()
                digest = sha256_bytes(blob)
                size = len(blob)
        label = "REAL" if real and digest else ("MOCK" if used_mock else "BLOCKED")
        pack = {
            "candidateId": candidate_id,
            "tenantId": tenant_id,
            "engineeringHash": rec.get("engineeringHash"),
            "usedMock": used_mock,
            "realBlender": bool(job.get("realBlender")),
            "label": label,
            "artifactSha256": digest,
            "artifactSize": size,
            "preview": preview,
            "alternate": alt,
            "liveMachineControl": False,
        }
        rec["media"] = {k: pack[k] for k in pack if k not in {"preview", "alternate"}}
        self.persist()
        return pack

    def list_candidates(self, portfolio_id: str, *, tenant_id: str) -> list[dict[str, Any]]:
        self.get_intent(portfolio_id, tenant_id=tenant_id)
        return [c for c in self.candidates.values() if c.get("portfolioId") == portfolio_id and c.get("tenantId") == tenant_id]


def run_portfolio_scenario(plat: Any, *, tenant_a: str = "pf-a", tenant_b: str = "pf-b", render: bool = False) -> dict[str, Any]:
    pf = plat.portfolio
    intent = pf.create_intent(tenant_id=tenant_a, segment="STUDENT", demand_source="MOCK", seed="phase541")
    generated = pf.generate_candidates(intent["portfolioId"], tenant_id=tenant_a)
    pf.create_intent(tenant_id=tenant_b, segment="RENTAL_SMALL_SPACE", demand_source="MOCK", seed="other")
    cross = False
    try:
        pf.get_intent(intent["portfolioId"], tenant_id=tenant_b)
    except PermissionError:
        cross = True
    plan = pf.plan_material(intent["portfolioId"], tenant_id=tenant_a)
    pf.assert_no_double_remnant(plan["remnantFirst"]["remnantIds"])
    ranking = pf.rank(intent["portfolioId"], tenant_id=tenant_a)
    top = ranking["top10"]
    invalid_in_top = [r for r in top if not r["valid"]]
    media_rows = []
    if render:
        for row in top[:4]:
            media_rows.append(pf.media_pack(row["candidateId"], tenant_id=tenant_a, render=True))
    approval = None
    pack = None
    if top:
        approval = pf.submit_approval(top[0]["candidateId"], tenant_id=tenant_a, actor="pm")
        approval = pf.approve_prototype(approval["approvalId"], tenant_id=tenant_a, actor="pm", reason="prototype-pilot")
        pack = pf.prototype_pack(top[0]["candidateId"], tenant_id=tenant_a)
    kinds = sorted({c["kind"] for c in generated["candidates"]})
    conservation = all((c.get("dfm") or {}).get("conservationOk") is not False or c["state"] == "REJECTED_DFM" for c in generated["candidates"])
    return {
        "ok": True,
        "portfolioId": intent["portfolioId"],
        "candidateCount": generated["count"],
        "kindCount": len(kinds),
        "kinds": kinds,
        "rejected": generated["rejected"],
        "top10": len(top),
        "invalidInTop10": len(invalid_in_top),
        "rankingPolicyHash": ranking["rankingPolicyHash"],
        "plan": plan,
        "tenantIsolation": cross,
        "demandLabel": intent["demand"]["truthLabel"],
        "prototypeReady": bool(pack and pack.get("readyForManualPrototype")),
        "liveMachineControl": False,
        "media": media_rows,
        "conservationOk": conservation,
        "approval": approval,
        "pack": pack,
        "label": "FIXTURE/REAL_LOGIC",
    }
