"""Unified AI Physical Product OS V1.

Adapter/registry over existing Twin/Queue/DAM/Engineering. Does not rewrite CabinetSpec.
"""

from __future__ import annotations

from typing import Any

from fox3d.acrylic import ACRYLIC_FAMILIES, AcrylicFactory
from fox3d.ids import stable_hash
from fox3d.kd import FLATPACK_PRODUCT_TYPES, auto_redesign_candidates, common_hardware_optimizer, common_panel_optimizer
from fox3d.packaging import BOX_FAMILIES, StructuralPackagingFactory
from fox3d.retail_fixture import FIXTURE_FAMILIES, RetailFixtureFactory

PHYSICAL_FAMILIES = {
    "KD_FURNITURE": {"kinds": list(FLATPACK_PRODUCT_TYPES), "pipeline": ["CabinetSpec", "BOM", "NestingV3", "WasteV2", "Packing", "Approval"]},
    "RETAIL_FIXTURE": {"kinds": list(FIXTURE_FAMILIES), "pipeline": ["RETAIL_DISPLAY", "Planogram", "BOM", "NestingV3", "Packing", "Approval"]},
    "PACKAGING_STRUCTURE": {"kinds": list(BOX_FAMILIES), "pipeline": ["PackagingEngineering", "Dieline", "NestingV3", "FoldPreview", "Approval"]},
    "ACRYLIC_SHEET": {"kinds": list(ACRYLIC_FAMILIES), "pipeline": ["AcrylicParts", "NestingV3", "CutBend", "Packing", "Approval"]},
}


class PhysicalProductFamilyRegistry:
    def list(self) -> list[str]:
        return list(PHYSICAL_FAMILIES)

    def get(self, family: str) -> dict[str, Any]:
        rec = dict(PHYSICAL_FAMILIES[family])
        rec["family"] = family
        rec["reuses"] = ["TwinStore", "JobQueue", "DAM", "EngineeringRuleEngine", "NestingStrategyRegistry"]
        rec["rewritesCabinetSpec"] = False
        return rec


class PhysicalProductOS:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.families = PhysicalProductFamilyRegistry()
        self.retail = RetailFixtureFactory(platform)
        self.packaging = StructuralPackagingFactory(platform)
        self.acrylic = AcrylicFactory(platform)
        self.approvals: dict[str, dict[str, Any]] = {}
        self.benchmarks: list[dict[str, Any]] = []

    def reverse_rd(self, *, tenant_id: str, sheets: list[dict[str, Any]] | None = None, remnants: list[dict[str, Any]] | None = None, lots: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        remnants = remnants or self.platform.remnants.available(tenant_id=tenant_id)
        max_l = max((float(r.get("w") or 0) for r in remnants), default=800)
        max_w = max((float(r.get("h") or 0) for r in remnants), default=600)
        kd = self.platform.kd.reverse_from_remnants(tenant_id=tenant_id, remnants=remnants or [{"w": max_l, "h": max_w, "thickness": 18, "materialCode": "WOOD_WHITE"}])
        scored = []
        for item in kd:
            rec = self.platform.kd.candidates.get(item["productId"]) or self.platform.kd.build_sku(tenant_id=tenant_id, kind=item["kind"], render=False)
            nest = rec.get("nesting") or {}
            pack = rec.get("packing") or {}
            scored.append(
                {
                    **item,
                    "family": "KD_FURNITURE",
                    "materialUtilization": nest.get("utilizationRatio"),
                    "trueScrap": nest.get("trueWasteRatio"),
                    "remnantConsumption": nest.get("remnantConsumedArea") or 0,
                    "commonParts": (rec.get("commonParts") or {}).get("commonPartRatio"),
                    "packing": {"L": pack.get("length"), "W": pack.get("width"), "H": pack.get("height")},
                    "assembly": (rec.get("difficulty") or {}).get("score"),
                    "estimatedMargin": (rec.get("landed") or {}).get("grossMargin"),
                    "market": "MARKET_UNVERIFIED",
                    "demand": "MOCK",
                }
            )
        scored.sort(key=lambda r: (-(r.get("materialUtilization") or 0), r.get("trueScrap") or 1))
        return {
            "tenantId": tenant_id,
            "lots": [l.get("lotId") for l in (lots or [])],
            "newSheets": sheets or [],
            "candidates": scored,
            "market": "MARKET_UNVERIFIED",
            "note": "Demand provider is MOCK — not claimed as bestselling.",
        }

    def approve(self, *, entity_id: str, actor: str, kind: str = "product") -> dict[str, Any]:
        rec = {
            "entityId": entity_id,
            "kind": kind,
            "actor": actor,
            "status": "WAITING_APPROVAL",
            "liveMachineControl": False,
            "forbidden": ["LIVE_CNC", "LIVE_LASER", "APPROVED_FOR_PRODUCTION"],
        }
        self.approvals[entity_id] = rec
        return rec

    def readiness(self, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        ev = evidence or {}
        matrix = {
            "kdFurnitureE2E": {"label": "REAL" if ev.get("kd") else "PARTIAL", "ready": bool(ev.get("kd"))},
            "retailFixtureE2E": {"label": "REAL" if ev.get("retail") else "PARTIAL", "ready": bool(ev.get("retail"))},
            "packagingOrAcrylicE2E": {"label": "REAL" if ev.get("pack_or_acr") else "PARTIAL", "ready": bool(ev.get("pack_or_acr"))},
            "durableRemnants": {"label": "REAL" if ev.get("remnants") else "PARTIAL", "ready": bool(ev.get("remnants"))},
            "nestingV3": {"label": "REAL" if ev.get("nesting_v3") else "PARTIAL", "ready": bool(ev.get("nesting_v3"))},
            "estimatedCost": {"label": "ESTIMATED-CONFIG", "ready": True},
            "realProviderCost": {"label": "BLOCKED", "ready": False},
            "vision": {"label": "MOCK", "ready": False},
            "demand": {"label": "MOCK", "ready": False},
            "video": {"label": "MOCK", "ready": False},
            "osSandbox": {"label": "PARTIAL", "ready": False},
            "liveMachineControl": {"label": "BLOCKED", "ready": False},
            "structuralCertification": {"label": "PARTIAL", "ready": False},
            "electricalCompliance": {"label": "BLOCKED", "ready": False},
            "ciEvidence": {"label": "MOCK" if not ev.get("ci") else "REAL", "ready": bool(ev.get("ci")), "note": "pytest mock suite only unless GitHub GREEN recorded"},
        }
        matrix["fullAutonomousFactoryReady"] = False
        matrix["productionReadyScope"] = "physicalProductOsV1-prototype-boundary"
        matrix["humanApprovalGate"] = True
        return matrix

    def kd_optimized_board(self, *, tenant_id: str, count: int = 10) -> dict[str, Any]:
        kinds = ["DESK_RISER", "BEDSIDE_CABINET", "OPEN_SHELF", "PET_FURNITURE", "STORAGE_BENCH", "MOBILE_SIDE_TABLE", "NARROW_BOOKCASE", "APPLIANCE_RACK", "STUDENT_DESK", "GARMENT_RACK"]
        rows = []
        recs = []
        for kind in kinds[:count]:
            before = self.platform.kd.build_sku(tenant_id=tenant_id, kind=kind, render=False)
            recs.append(before)
            hw = common_hardware_optimizer([before])
            panel = common_panel_optimizer(before)
            redesign = auto_redesign_candidates(self.platform.cabinets, before, tenant_id=tenant_id)
            after = before
            if redesign.get("triggered") and redesign.get("candidates"):
                c0 = redesign["candidates"][0]
                after = self.platform.kd.build_sku(tenant_id=tenant_id, kind=kind, width=c0["width"], depth=c0["depth"], height=c0["height"], render=False)
            rows.append(
                {
                    "kind": kind,
                    "before": {
                        "waste": (before.get("nesting") or {}).get("trueWasteRatio"),
                        "carton": {"L": before["packing"]["length"], "W": before["packing"]["width"], "H": before["packing"]["height"]},
                        "weight": before["weight"]["grossKg"],
                        "commonPartRatio": before["commonParts"]["commonPartRatio"],
                        "assembly": before["difficulty"]["score"],
                    },
                    "after": {
                        "waste": (after.get("nesting") or {}).get("trueWasteRatio"),
                        "carton": {"L": after["packing"]["length"], "W": after["packing"]["width"], "H": after["packing"]["height"]},
                        "weight": after["weight"]["grossKg"],
                        "commonPartRatio": after["commonParts"]["commonPartRatio"],
                        "assembly": after["difficulty"]["score"],
                    },
                    "commonHardwareRatio": hw["commonHardwareRatio"],
                    "commonPanel": panel["commonPanelRatio"],
                    "redesignTriggered": bool(redesign.get("triggered")),
                    "demand": "MOCK",
                }
            )
        family_hw = common_hardware_optimizer(recs)
        return {
            "candidates": rows,
            "familyHardware": family_hw,
            "demand": "MOCK",
            "note": "Not claimed as market bestsellers.",
        }
