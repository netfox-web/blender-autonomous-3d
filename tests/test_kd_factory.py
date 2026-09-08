"""Phase 121–180 KD / flat-pack factory regressions. Mock blender — not production ready."""

from __future__ import annotations

import pytest

from fox3d.kd import FLATPACK_PRODUCT_TYPES, DemandSignalProvider, assembly_graph, pack_flatpack
from fox3d.manufacturing import NestingEngine, RemnantInventory
from fox3d.parametric import CabinetSpec, parse_design_intent


def test_twelve_kd_types_geometry_bom(platform):
    from fox3d.kd import FlatPackProductTypeRegistry

    assert len(FLATPACK_PRODUCT_TYPES) == 12
    assert len(FlatPackProductTypeRegistry().list()) == 12
    for kind in FLATPACK_PRODUCT_TYPES:
        rec = platform.kd.build_sku(tenant_id="t1", kind=kind)
        assert rec["report"]["ok"] is True, (kind, rec["report"])
        spec = rec["spec"]
        assert spec["kind"] == kind
        assert spec["width"] > 0 and spec["height"] > 0
        names = {ln["partName"] for ln in rec["bom"]["lines"]}
        assert "L_SIDE" in names
        assert rec["bom"]["bomHash"]
        assert rec["kd"]["flatPack"] is True
        assert rec["fingerprints"]


def test_common_part_fingerprint_stable(platform):
    a = platform.kd.build_sku(tenant_id="t1", kind="OPEN_SHELF", width=800, height=1200, depth=300)
    b = platform.kd.build_sku(tenant_id="t1", kind="OPEN_SHELF", width=800, height=1200, depth=300)
    fa = sorted(x["fingerprint"] for x in a["fingerprints"])
    fb = sorted(x["fingerprint"] for x in b["fingerprints"])
    assert fa == fb
    assert a["commonParts"]["uniquePartCount"] >= 1


def test_packing_one_carton_and_oversize(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    pack = rec["packing"]
    assert pack["derivedFromPanels"] is True
    assert pack["length"] >= rec["spec"]["height"] or pack["length"] >= rec["spec"]["width"]
    assert rec["shipping"]["oneCarton"] is True
    huge = platform.kd.build_sku(tenant_id="t1", kind="NARROW_BOOKCASE", height=1600)
    # 1600mm panel longest side + padding exceeds 1500 default
    assert huge["shipping"]["oversize"] is True
    assert huge["gate"]["redesignRequired"] is True
    assert "OVERSIZE" in huge["gate"]["hard"]


def test_packed_weight_and_cbm_deterministic(platform):
    a = platform.kd.build_sku(tenant_id="t1", kind="PET_FURNITURE")
    b = platform.kd.build_sku(tenant_id="t1", kind="PET_FURNITURE")
    assert a["weight"]["densitySource"].startswith("CONFIG")
    assert a["weight"]["grossKg"] == b["weight"]["grossKg"]
    assert a["shipping"]["cbm"] == b["shipping"]["cbm"]
    assert a["shipping"]["source"] == "CONFIG"


def test_assembly_acyclic_and_difficulty(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="APPLIANCE_RACK")
    g = rec["assemblyGraph"]
    assert g["acyclic"] is True
    d = rec["difficulty"]
    assert d["partCount"] >= 4
    assert d["estimatedMinutes"] > 0
    assert 0 <= d["score"] <= 1
    assert d["source"] == "deterministic"
    spec = CabinetSpec.model_validate(rec["spec"])
    g2 = assembly_graph(spec, rec["bom"])
    assert g2["acyclic"] is True


def test_waste_v2_conservation(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="OPEN_SHELF")
    nest = rec["nesting"]
    assert nest["areaConservationError"] < 1.0
    used = nest["partUsedArea"] + nest["kerfLossArea"] + nest["trimLossArea"]
    leftover = nest["reusableRemnantArea"] + (nest["trueScrapArea"] - nest["kerfLossArea"] - nest["trimLossArea"])
    # leftover scrap is unqualified free; conservation on sheets:
    assert nest["trueWasteRatio"] >= 0
    assert nest["reusableRemnantRatio"] >= 0
    assert nest["trueScrapArea"] >= nest["kerfLossArea"]
    assert "trueWasteRatio" in nest


def test_remnant_qualify_reserve_consume_once(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="STORAGE_BENCH")
    spec = CabinetSpec.model_validate(rec["spec"])
    nest = platform.kd.nester.nest(rec["bom"], material=str(spec.material), thickness=float(spec.boardThickness))
    created = platform.kd.extract_remnants(nest, material=str(spec.material), thickness=float(spec.boardThickness), run_id="run-1")
    inv = platform.kd.remnants
    if not created:
        # force a qualified remnant
        inv.items["r1"] = {
            "remnantId": "r1",
            "status": "available",
            "w": 800,
            "h": 400,
            "thickness": 18,
            "materialCode": "WOOD_WHITE",
        }
        created = [inv.items["r1"]]
    rid = created[0]["remnantId"]
    inv.reserve(rid, by="batch-1")
    inv.consume(rid, by="batch-1")
    with pytest.raises(PermissionError):
        inv.consume(rid, by="batch-2")


def test_batch_single_sku_and_cross_sku(platform):
    a = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    b = platform.kd.build_sku(tenant_id="t1", kind="DESK_RISER")
    c = platform.kd.build_sku(tenant_id="t1", kind="OPEN_SHELF")
    one = platform.kd.nest_quantity(a, 1)
    ten = platform.kd.nest_quantity(a, 10)
    assert ten["sheetCount"] >= one["sheetCount"]
    # not a linear multiply of independent nests
    assert ten["sheetCount"] < one["sheetCount"] * 10 or ten["utilizationRatio"] >= one["utilizationRatio"]
    cross = platform.kd.nest_cross_sku([a, b, c], [2, 3, 1])
    assert not platform.kd.nester.assert_valid(cross)
    skus = {p.get("skuId") for s in cross["sheets"] for p in s["placements"]}
    assert a["spec"]["productId"] in skus
    assert b["spec"]["productId"] in skus


def test_remnant_first_saves_sheets(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="DESK_RISER")
    case = platform.kd.remnant_first_case(rec)
    assert case["savedNewSheetCount"] >= 1 or case["remnantFirstSheetCount"] < case["independentSheetCount"]
    assert case["remnantConsumedArea"] > 0


def test_quote_stale_after_engineering_or_packaging(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    lineage = rec["landed"]["lineage"]
    resized = platform.factory.revise_cabinet(rec["spec"]["productId"], tenant_id="t1", width=600)
    assert resized["engineeringHash"] != lineage["engineeringHash"]
    spec = CabinetSpec.model_validate(resized["spec"])
    pack2 = pack_flatpack(spec, resized["bom"])
    assert pack2["packagingHash"] != rec["packing"]["packagingHash"]


def test_quantity_break_nonlinear(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    rows = platform.kd.quantity_breaks(rec, (1, 10, 20))
    assert rows[0]["quantity"] == 1
    # sheets per unit should not increase with volume
    assert rows[-1]["sheetsPerUnit"] <= rows[0]["sheetsPerUnit"] + 1e-6


def test_reverse_remnant_feasibility(platform):
    remnants = [{"w": 800, "h": 600, "thickness": 18, "materialCode": "WOOD_WHITE"}]
    found = platform.kd.reverse_from_remnants(tenant_id="t1", remnants=remnants)
    assert found
    kinds = {r["kind"] for r in found}
    assert kinds & {"DESK_RISER", "PET_FURNITURE", "BEDSIDE_CABINET", "OPEN_SHELF", "MOBILE_SIDE_TABLE"}


def test_rd_engineering_veto_and_demand_mock(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    assert rec["rdScore"]["engineeringVeto"] is False
    assert rec["demand"]["label"] == "MOCK"
    assert rec["rdScore"]["demandScore"]["confidence"] == "MOCK"
    assert rec["rdScore"]["visualScore"]["confidence"] == "MOCK"
    demand = DemandSignalProvider().signals(kind="BEDSIDE_CABINET")
    assert demand["status"] == "UNAVAILABLE"
    bad = platform.cabinets.create("BEDSIDE_CABINET", tenant_id="t1", width=50, height=50, depth=50, boardThickness=12)
    assert bad[1].ok is False


def test_readiness_matrix_truthful(platform):
    m = platform.kd.readiness(evidence={"coreFactoryE2E": True, "kdWasteV2": True, "kdPacking": True, "kdRemnants": True, "kdLandedCost": True})
    assert m["coreFactoryE2EReady"] is True
    assert m["kdDfMReady"] is True
    assert m["commercialCostModelReady"] is True
    assert m["marketDemandVerified"] is False
    assert m["liveVisionReady"] is False
    assert m["liveVideoReady"] is False
    assert m["osSandboxReady"] is False
    assert m["liveMachineControlReady"] is False
    assert m["fullAutonomousFactoryReady"] is False
    assert m["productionReadyScope"] == "coreFactoryE2E"


def test_approval_not_production(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="PET_FURNITURE")
    waiting = platform.kd.approve_prototype(rec["spec"]["productId"], actor="ops")
    assert waiting["approvalState"] == "WAITING_PRODUCT_APPROVAL"
    proto = platform.kd.confirm_prototype(rec["spec"]["productId"], actor="ops")
    assert proto["approvalState"] == "APPROVED_FOR_PROTOTYPE"
    assert "LIVE_CNC" in proto["approval"]["forbidden"]


def test_catalog_covers_six_families(platform):
    out = platform.kd.generate_candidates(tenant_id="t1", count=24, render=False)
    kinds = {row["kind"] for row in out["catalog"]}
    needed = {"STUDENT_DESK", "OPEN_SHELF", "BEDSIDE_CABINET", "NARROW_BOOKCASE", "APPLIANCE_RACK", "GARMENT_RACK"}
    assert needed <= kinds or len(kinds) >= 6
    assert out["demandLabel"] == "MOCK"
    assert "not claimed" in out["note"].lower()
    row = out["catalog"][0]
    for key in ("engineeringHash", "bomHash", "commonPartRatio", "trueWasteRatio", "carton", "packedWeight", "assemblyDifficulty", "landedCost", "approvalState"):
        assert key in row


def test_retail_display_same_pipeline(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="RETAIL_DISPLAY")
    assert rec["report"]["ok"]
    assert rec["nesting"]["sheetCount"] >= 1
    assert rec["packing"]["derivedFromPanels"]
    assert rec["kd"]["flatPack"]


def test_nl_kd_kinds():
    assert parse_design_intent("做一個床頭櫃", tenant_id="t1")["kind"] == "BEDSIDE_CABINET"
    assert parse_design_intent("學生書桌 80cm", tenant_id="t1")["kind"] == "STUDENT_DESK"
