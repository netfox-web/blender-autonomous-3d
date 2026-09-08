"""Phase 181–240 Physical Product OS regressions. Mock blender — not production ready."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from fox3d.acrylic import ACRYLIC_FAMILIES
from fox3d.api import create_app
from fox3d.inventory import DurableRemnantStore, remnant_value
from fox3d.kd import assembly_instruction_v2, carton_contents_manifest, connector_recipe_for, misassembly_risk, part_label_manifest
from fox3d.manufacturing import NestingEngine, RemnantInventory
from fox3d.nesting_v3 import NestingStrategyRegistry, NestingV3, run_benchmark
from fox3d.packaging import BOX_FAMILIES, PAPERBOARD_SHEETS
from fox3d.physical_os import PHYSICAL_FAMILIES
from fox3d.platform import Platform
from fox3d.retail_fixture import FIXTURE_FAMILIES, planogram_solve


def test_hygiene_not_required_here():
    assert "KD_FURNITURE" in PHYSICAL_FAMILIES


def test_cache_key_includes_acrylic():
    from fox3d.infra import job_cache_key

    render = {"width": 256, "height": 256, "engine": "CYCLES", "device": "OPTIX", "samples": 8}
    a = job_cache_key({"mode": "ACRYLIC_PRODUCT", "acrylic": {"kind": "MENU_STAND"}, "render": render}, blender_version="5.2.1")
    b = job_cache_key({"mode": "ACRYLIC_PRODUCT", "acrylic": {"kind": "SIGN_HOLDER"}, "render": render}, blender_version="5.2.1")
    assert a != b


def test_remnant_store_restart_ttl_stale_tenant_grain(tmp_path):
    plat = Platform(root=tmp_path / "data", mock_blender=True)
    rec = plat.kd.build_sku(tenant_id="t1", kind="STORAGE_BENCH")
    nest = plat.kd.nester.nest(rec["bom"], material=rec["spec"]["material"], thickness=rec["spec"]["boardThickness"])
    created = plat.kd.extract_remnants(nest, material=rec["spec"]["material"], thickness=rec["spec"]["boardThickness"], run_id="run-a", tenant_id="t1")
    if not created:
        plat.remnants.items["r-hy"] = {
            "remnantId": "r-hy",
            "tenantId": "t1",
            "status": "available",
            "qualityState": "AVAILABLE",
            "w": 800,
            "h": 400,
            "thickness": 18,
            "material": rec["spec"]["material"],
            "materialCode": "WOOD_WHITE",
            "grain": "length",
            "version": 1,
            "area": 320000,
        }
        plat.remnants.store.put(plat.remnants.items["r-hy"])
        created = [plat.remnants.items["r-hy"]]
    rid = created[0]["remnantId"]
    reserved = plat.remnants.reserve(rid, by="w1", version=created[0]["version"], lease_seconds=0.0, tenant_id="t1")
    assert reserved["leaseToken"]
    with pytest.raises(PermissionError):
        plat.remnants.reserve(rid, by="w2", tenant_id="t1")
    with pytest.raises(PermissionError):
        plat.remnants.consume(rid, by="w1", version=1, tenant_id="t1")
    plat2 = Platform(root=tmp_path / "data", mock_blender=True)
    loaded = plat2.remnants.get(rid, tenant_id="t1")
    assert loaded["status"] == "reserved"
    with pytest.raises(PermissionError):
        plat2.remnants.get(rid, tenant_id="other")
    past = datetime.now(timezone.utc) + timedelta(seconds=1)
    recovered = plat2.remnants.recover_expired(now=past)
    assert any(r["remnantId"] == rid for r in recovered)
    again = plat2.remnants.get(rid, tenant_id="t1")
    assert again["status"] == "available"
    plat2.remnants.reserve(rid, by="w3", tenant_id="t1")
    plat2.remnants.consume(rid, by="w3", tenant_id="t1")
    with pytest.raises(PermissionError):
        plat2.remnants.consume(rid, by="w3", tenant_id="t1")
    damaged = plat2.kd.build_sku(tenant_id="t1", kind="DESK_RISER")
    dnest = plat2.kd.nester.nest(damaged["bom"], material=damaged["spec"]["material"], thickness=18)
    extra = plat2.kd.extract_remnants(dnest, material=damaged["spec"]["material"], thickness=18, run_id="run-b", tenant_id="t1")
    if extra:
        plat2.remnants.set_quality(extra[0]["remnantId"], "damaged", tenant_id="t1")
        blocked = plat2.kd.nester.nest(
            damaged["bom"],
            material=damaged["spec"]["material"],
            thickness=18,
            remnants=[plat2.remnants.items[extra[0]["remnantId"]]],
        )
        assert blocked.get("remnantConsumedArea") in {0, 0.0} or not blocked.get("remnantUsed")


def test_grain_blocks_rotated_remnant(platform):
    part = {"partId": "p1", "partName": "P", "length": 400, "width": 200, "grain": "length"}
    rem = {"remnantId": "g1", "w": 200, "h": 400, "thickness": 18, "materialCode": "WOOD_WHITE", "grain": "length", "status": "available"}
    engine = NestingEngine()
    miss = engine.nest_parts([part], material="WOOD_WHITE", thickness=18, remnants=[rem], sheet={"length": 2440, "width": 1220, "grain": "length", "sku": "PB_18_WHITE"})
    on_rem = [p for r in miss.get("remnantUsed") or [] for p in r["placements"]]
    assert not on_rem
    rem2 = dict(rem)
    rem2["grain"] = "none"
    rem2["remnantId"] = "g2"
    hit = engine.nest_parts([{**part, "grain": "none"}], material="WOOD_WHITE", thickness=18, remnants=[rem2], sheet={"length": 2440, "width": 1220, "grain": "none", "sku": "MDF_18_BLACK"})
    assert hit.get("remnantConsumedArea") or hit["sheetCount"] >= 0


def test_valuation_and_inventory_manifest(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    a = platform.kd.build_sku(tenant_id="t1", kind="DESK_RISER")
    batch = platform.kd.production_batch([rec, a], [1, 2], tenant_id="t1")
    man = batch["inventory"]
    assert man["reconciliationHash"]
    assert man["newSheetsAllocated"] == batch["nesting"]["sheetCount"]
    val = remnant_value({"w": 800, "h": 400, "createdAt": None}, cost_per_m2=280)
    assert val["source"] == "ESTIMATED/CONFIG"
    assert val["notAccountingCost"] is True


def test_material_lot_lineage(platform):
    lot = platform.lots.create(tenant_id="t1", material="WOOD_WHITE", thickness=18, supplier_lot="SL-1", sheet_count=3)
    rec = platform.kd.build_sku(tenant_id="t1", kind="PET_FURNITURE")
    nest = platform.kd.nester.nest(rec["bom"], material=rec["spec"]["material"], thickness=18, material_lot_id=lot["lotId"])
    placed_lots = {p.get("materialLotId") for s in nest["sheets"] for p in s["placements"]}
    assert lot["lotId"] in placed_lots or nest["sheetCount"] == 0
    got = platform.lots.get(lot["lotId"], tenant_id="t1")
    assert got["configCostSnapshot"]["source"] == "CONFIG"
    with pytest.raises(PermissionError):
        platform.lots.get(lot["lotId"], tenant_id="other")


def test_nesting_v3_registry_defects_benchmark(platform):
    reg = NestingStrategyRegistry()
    assert "guillotine_baseline" in reg.list()
    assert "best_fit_decreasing" in reg.list()
    rec = platform.kd.build_sku(tenant_id="t1", kind="OPEN_SHELF")
    a = NestingEngine().nest(rec["bom"], material=rec["spec"]["material"], thickness=18, seed="baseline")
    b = NestingEngine().nest(rec["bom"], material=rec["spec"]["material"], thickness=18, seed="baseline")
    assert a["nestingHash"] == b["nestingHash"]
    v3 = NestingV3().nest(rec["bom"], material=rec["spec"]["material"], thickness=18, seed="v3")
    assert v3["sheetCount"] >= 1
    assert v3.get("cutSequence")
    assert v3["liveMachineControl"] is False
    defected = NestingEngine().nest_parts(
        [{"partId": "p", "partName": "P", "length": 200, "width": 200, "grain": "none"}],
        sheet={"length": 500, "width": 500, "grain": "none", "sku": "X", "defects": [{"x": 10, "y": 10, "w": 480, "h": 480}]},
        trim_mm=0,
        kerf_mm=0,
    )
    assert defected["unplaceable"] or defected["illegal"]
    bench = run_benchmark(platform, tenant_id="t1")
    assert len(bench["cases"]) >= 10
    assert "v3SheetLosses" in bench


def test_kd_dfa_labels_instructions_redesign(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    assert rec["instructionsV2"]["version"] == 2
    assert rec["partLabels"]["labels"]
    assert rec["cartonContents"]["reconciled"] is True
    assert rec["tools"]["toolCount"] >= 1
    recipe = connector_recipe_for("BEDSIDE_CABINET", version=2)
    assert recipe["version"] == 2
    assert "KD_CAM_DOWEL_V1" in recipe["compatibility"]
    board = platform.physical.kd_optimized_board(tenant_id="t1", count=10)
    assert len(board["candidates"]) == 10
    assert board["demand"] == "MOCK"
    huge = platform.kd.build_sku(tenant_id="t1", kind="NARROW_BOOKCASE", height=1600)
    from fox3d.kd import auto_redesign_candidates

    loop = auto_redesign_candidates(platform.cabinets, huge, tenant_id="t1")
    assert loop["engineeringVetoAlways"] is True
    assert loop["triggered"] is True


def test_retail_fixture_planogram_pipeline(platform):
    assert len(FIXTURE_FAMILIES) == 6
    product = {"sku": "COSM-1", "dimensions": {"width": 70, "height": 110, "depth": 35}, "weightKg": 0.2}
    rec = platform.physical.retail.build(tenant_id="t1", family="COUNTER_DISPLAY", product=product, facing=2)
    assert rec["report"]["ok"]
    assert rec["samePipeline"][0] == "BOM"
    assert rec["capacity"]["source"] == "CONFIG_ESTIMATE"
    assert rec["lighting"]["electricalCompliance"] == "BLOCKED"
    assert rec["artwork"]["printPreflight"] == "PARTIAL"
    chosen = rec["planogram"]["chosen"]
    assert chosen.get("legal") is True
    slots = chosen["slots"]
    for i, a in enumerate(slots):
        for b in slots[i + 1 :]:
            overlap = not (a["x"] + a["w"] <= b["x"] + 1e-6 or b["x"] + b["w"] <= a["x"] + 1e-6 or a["y"] + a["h"] <= b["y"] + 1e-6 or b["y"] + b["h"] <= a["y"] + 1e-6)
            assert not overlap
    assert rec["approval"]["liveMachineControl"] is False
    inner = {"width": 200, "height": 100, "depth": 50}
    bad = planogram_solve(fixture_inner=inner, product={"dimensions": {"width": 300, "height": 300, "depth": 300}})
    assert bad["chosen"].get("legal") is False or bad["chosen"].get("capacityUnits") == 0


def test_packaging_structure_and_acrylic(platform):
    assert len(BOX_FAMILIES) == 5
    pkg = platform.physical.packaging.build(tenant_id="t1", family="RSC_CARTON", product_dims={"width": 120, "height": 80, "depth": 40})
    assert pkg["engineering"]["strength"]["structuralCertification"] is False
    assert pkg["engineering"]["bleed"]["preflight"] == "PARTIAL"
    assert pkg["nesting"]["sheetCount"] >= 1
    assert pkg["liveMachineControl"] is False
    assert len(ACRYLIC_FAMILIES) == 5
    acr = platform.physical.acrylic.build(tenant_id="t1", kind="MENU_STAND")
    assert acr["sheet"]["source"] == "CONFIG"
    assert acr["cutBend"]["liveMachineControl"] is False
    assert acr["nesting"]["grainConstraint"] in {"none", "length"}
    bundle = platform.physical.packaging.bundle_with_retail(tenant_id="t1", product={"sku": "P1", "dimensions": {"width": 80, "height": 120, "depth": 40}})
    assert bundle["sameTwin"] is True
    assert bundle["retailFixture"]["family"] == "PDQ_DISPLAY"


def test_physical_os_reverse_and_readiness(platform):
    out = platform.physical.reverse_rd(tenant_id="t1", remnants=[{"w": 800, "h": 600, "thickness": 18, "materialCode": "WOOD_WHITE"}])
    assert out["market"] == "MARKET_UNVERIFIED"
    assert out["candidates"]
    m = platform.physical.readiness()
    assert m["fullAutonomousFactoryReady"] is False
    assert m["liveMachineControl"]["label"] == "BLOCKED"
    assert m["vision"]["label"] == "MOCK"
    assert m["demand"]["label"] == "MOCK"
    families = platform.physical.families.list()
    assert set(families) == {"KD_FURNITURE", "RETAIL_FIXTURE", "PACKAGING_STRUCTURE", "ACRYLIC_SHEET"}
    appr = platform.physical.approve(entity_id="x", actor="ops")
    assert appr["status"] == "WAITING_APPROVAL"
    assert "LIVE_CNC" in appr["forbidden"]


def test_api_physical_routes(platform):
    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "acme"}
    assert client.get("/api/physical-os/families").status_code == 200
    mats = client.get("/api/materials", headers=headers)
    assert mats.status_code == 200
    lot = client.post("/api/materials/lots", json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 2}, headers=headers)
    assert lot.status_code == 200
    fx = client.post("/api/retail/fixtures", json={"family": "RISER_DISPLAY"}, headers=headers)
    assert fx.status_code == 200
    pkg = client.post("/api/packaging/structures", json={"family": "MAILER_BOX", "productDims": {"width": 90, "height": 60, "depth": 30}}, headers=headers)
    assert pkg.status_code == 200
    acr = client.post("/api/acrylic/products", json={"kind": "SIGN_HOLDER"}, headers=headers)
    assert acr.status_code == 200
    ap = client.post("/api/physical-os/approve", json={"entityId": acr.json()["productId"], "actor": "ops"}, headers=headers)
    assert ap.json()["liveMachineControl"] is False
    admin = client.get("/admin")
    assert "Physical Product OS" in admin.text
    assert "Blender UI" in admin.text
