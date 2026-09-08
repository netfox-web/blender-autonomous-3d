"""Phase 71–120 furniture factory regressions. Mock blender only — not production ready."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.furniture import FurnitureProductTypeRegistry, validate_assembly
from fox3d.manufacturing import ManufacturingCandidateGate, NestingEngine, QuoteEngine
from fox3d.parametric import CabinetSpec, parse_design_intent


PRODUCT_TYPES = (
    "WARDROBE",
    "SHOE_CABINET",
    "TV_CABINET",
    "BOOKCASE",
    "STORAGE_CABINET",
    "DISPLAY_CABINET",
    "KITCHEN_BASE",
    "KITCHEN_WALL",
)


def test_product_type_registry_and_geometry_bom(platform):
    registry = FurnitureProductTypeRegistry()
    assert set(registry.list()) == set(PRODUCT_TYPES)
    for kind in PRODUCT_TYPES:
        created = platform.create_parametric({"tenantId": "t1", "kind": kind})
        assert created["report"]["ok"] is True, (kind, created["report"])
        spec = CabinetSpec.model_validate(created["spec"])
        assert spec.kind == kind
        assert spec.modules
        kinds = {m["kind"] for m in spec.modules}
        assert kinds, kind
        names = {line["partName"] for line in created["bom"]["lines"]}
        assert "L_SIDE" in names
        assert created["bom"]["engineeringHash"] == spec.engineering_hash()
        assert created["bom"]["bomHash"]
        panel = next(ln for ln in created["bom"]["lines"] if ln.get("partType") == "top")
        assert "edgeBandingEdges" in panel
        assert "front" in panel["edgeBandingEdges"]


def test_modules_partitions_fillers_change_hash(platform):
    a = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 1200, "verticalPartitions": 1})
    b = platform.create_parametric(
        {
            "tenantId": "t1",
            "kind": "STORAGE_CABINET",
            "width": 1200,
            "verticalPartitions": 2,
            "horizontalPartitions": 1,
            "topFillerHeight": 50,
            "sideFillerWidth": 40,
            "wallClearance": 20,
        }
    )
    assert a["engineeringHash"] != b["engineeringHash"]
    assert a["bom"]["bomHash"] != b["bom"]["bomHash"]
    roles = {ln.get("partType") for ln in b["bom"]["lines"]}
    assert "top_filler" in roles
    assert "side_filler" in roles
    assert "h_partition" in roles
    kinds = {m["kind"] for m in b["spec"]["modules"]}
    assert "VERTICAL_PARTITION" in kinds
    assert "TOP_FILLER" in kinds
    assert "WALL_CLEARANCE" in kinds


def test_open_shelf_vs_closed_and_door_styles(platform):
    book = platform.create_parametric({"tenantId": "t1", "kind": "BOOKCASE", "doorCount": 0, "shelfCount": 5})
    kinds = {m["kind"] for m in book["spec"]["modules"]}
    assert "OPEN_SHELF" in kinds or "OPEN_BAY" in kinds
    closed = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "doorCount": 2})
    ck = {m["kind"] for m in closed["spec"]["modules"]}
    assert "DOUBLE_DOOR" in ck or "CLOSED_COMPARTMENT" in ck
    hinged = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "doorCount": 1, "width": 500})
    hk = {m["kind"] for m in hinged["spec"]["modules"]}
    assert "HINGED_DOOR" in hk
    drawers = platform.create_parametric({"tenantId": "t1", "kind": "TV_CABINET"})
    dk = {m["kind"] for m in drawers["spec"]["modules"]}
    assert "DRAWER_BANK" in dk
    kitchen = platform.create_parametric({"tenantId": "t1", "kind": "KITCHEN_BASE"})
    kk = {m["kind"] for m in kitchen["spec"]["modules"]}
    assert "TOE_KICK" in kk or "PLINTH" in kk


def test_multi_cabinet_2_3_4_and_hash(platform):
    run = platform.furniture_factory_run(tenant_id="t1", render=False)
    counts = {len(c["placements"]) for c in run["layouts"] if not c["rejected"]}
    assert counts & {2, 3, 4} or any(len(c["placements"]) in {2, 3, 4} for c in run["layouts"])
    assert run["assembly"]["cabinetCount"] >= 1
    h1 = run["assembly"]["assemblyHash"]
    # Mutate one module/cabinet width via revision — new assembly hash from a second run with different types.
    run2 = platform.furniture_factory_run(tenant_id="t1", product_types=["WARDROBE", "SHOE_CABINET"], render=False)
    assert run2["assembly"]["assemblyHash"]
    if run2["assembly"]["cabinetCount"] != run["assembly"]["cabinetCount"] or run2["cabinets"][0]["engineeringHash"] != run["cabinets"][0]["engineeringHash"]:
        assert run2["assembly"]["assemblyHash"] != h1


def test_space_solver_rejects_door_window_column(platform):
    fx = platform.factory.collision_fixture(tenant_id="t1")
    space = platform.spaces.ingest(
        {
            "tenantId": "t1",
            "width": 3600,
            "depth": 3000,
            "height": 2600,
            "doors": [{"kind": "door", "width": 900, "height": 2100, "startMm": 1200, "position": [1200.0, 0.0]}],
            "windows": [{"kind": "window", "width": 1000, "height": 1200, "sill": 900, "startMm": 2400, "position": [2400.0, 0.0]}],
            "columns": [{"width": 250, "depth": 250, "startMm": 200}],
        }
    )
    wall = next(w for w in space.walls if w.name == "N")
    door = platform.factory.constraints.validate(space, [{"wallId": wall.wallId, "startMm": 1250, "width": 800, "height": 1800, "originZ": 0}])
    window = platform.factory.constraints.validate(space, [{"wallId": wall.wallId, "startMm": 2450, "width": 800, "height": 1800, "originZ": 900}])
    column = platform.factory.constraints.validate(space, [{"wallId": wall.wallId, "startMm": 150, "width": 400, "height": 1800, "originZ": 0}])
    assert any("DOOR" in v["code"] for v in door)
    assert any("WINDOW" in v["code"] for v in window)
    assert any("COLUMN" in v["code"] for v in column)
    assert fx["spaceId"]


def test_nesting_deterministic_bounds_grain_no_overlap(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 800, "height": 1800, "depth": 400, "shelfCount": 4, "doorCount": 2})
    nester = NestingEngine()
    a = nester.nest(created["bom"], material="WOOD_WHITE")
    b = nester.nest(created["bom"], material="WOOD_WHITE")
    assert a["nestingHash"] == b["nestingHash"]
    assert a["sheetCount"] >= 1
    assert 0 <= a["utilization"] <= 1
    assert a["wasteAreaMm2"] >= 0
    assert not nester.assert_valid(a)
    grain_parts = [p for sheet in a["sheets"] for p in sheet["placements"]]
    assert grain_parts
    for p in grain_parts:
        assert p["x"] >= 0 and p["y"] >= 0
        assert p["x"] + p["w"] <= a["sheetMm"][0] + 1e-3
        assert p["y"] + p["h"] <= a["sheetMm"][1] + 1e-3
    # Grain: length-constrained part must not rotate.
    fake_bom = {
        "lines": [
            {"partId": "top", "partName": "TOP", "partType": "top", "length": 800, "width": 1000, "thickness": 18, "quantity": 1},
        ]
    }
    nested = nester.nest(fake_bom, material="WOOD_WHITE")
    place = nested["sheets"][0]["placements"][0]
    assert place["rotated"] is False
    assert place["w"] == 800
    assert place["h"] == 1000
    assert nested["svg"]
    assert nested["dxfInterface"]["liveMachineControl"] is False
    assert nested["kerfMm"] == 4.0
    assert nested["trimMm"] == 10.0


def test_quote_stale_and_manufacturing_gate(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 800})
    nest = NestingEngine().nest(created["bom"], material="WOOD_WHITE")
    spec = CabinetSpec.model_validate(created["spec"])
    quote = QuoteEngine().quote(spec, created["bom"], nest)
    assert quote.is_stale(engineering_hash=spec.engineering_hash(), bom_hash=created["bom"]["bomHash"], nesting_hash=nest["nestingHash"]) is False
    resized = platform.resize_parametric(spec.productId, tenant_id="t1", width=1200)
    assert quote.is_stale(engineering_hash=resized["engineeringHash"], bom_hash=resized["bom"]["bomHash"], nesting_hash=nest["nestingHash"]) is True
    assert "SheetWasteCost" in quote.breakdown
    assert "EdgeBandingCost" in quote.breakdown
    gate = ManufacturingCandidateGate()
    assert gate.advance("COSTED") == "COSTED"
    assert gate.advance("PREVIEWED") == "PREVIEWED"
    assert gate.advance("WAITING_APPROVAL") == "WAITING_APPROVAL"
    with pytest.raises(PermissionError):
        gate.advance("LIVE_CNC")


def test_nl_product_family_and_unknowns():
    wardrobe = parse_design_intent("客廳做一個衣櫃 120cm 寬", tenant_id="t1")
    assert wardrobe["kind"] == "WARDROBE"
    assert wardrobe["roomTarget"] == "living"
    shoe = parse_design_intent("玄關鞋櫃", tenant_id="t1")
    assert shoe["kind"] == "SHOE_CABINET"
    display = parse_design_intent("做一個展示櫃", tenant_id="t1")
    assert display["kind"] == "DISPLAY_CABINET"
    vague = parse_design_intent("幫我做櫃子，這面牆要滿", tenant_id="t1")
    assert "wallWidth" in vague["needsInput"] or "exactWidth" in vague["unknownFields"]
    assert vague["llmMayNotSetMillimetresDirectly"] is True


def test_customer_revision_lineage(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 800, "material": "WOOD_WHITE", "shelfCount": 3, "doorCount": 2})
    nxt = platform.factory.revise_cabinet(created["spec"]["productId"], tenant_id="t1", width=1000, material="WOOD_OAK", shelfCount=4, doorCount=2)
    assert nxt["spec"]["parentProductId"] == created["spec"]["productId"]
    assert nxt["spec"]["revision"] == 2
    assert nxt["engineeringHash"] != created["engineeringHash"]
    assert nxt["lineage"]["immutable"] is True


def test_factory_e2e_mock_and_api(platform, tmp_path):
    run = platform.furniture_factory_run(tenant_id="t1", render=True, text="做一個收納櫃")
    assert run["legalLayoutCount"] >= 1
    assert run["gate"]["status"] == "WAITING_APPROVAL"
    assert run["gate"]["liveMachineControl"] is False
    assert run["gate"]["HUMAN_APPROVAL_REQUIRED"] is True
    assert run["lineage"]["space"]["spaceHash"]
    assert run["lineage"]["furniture"]["assemblyHash"]
    assert run["bom"]["bomHash"]
    assert run["quote"]["quoteHash"]
    assert run["nesting"]["sheetCount"] >= 1
    assert run["assembly"]["cabinetCount"] >= 1
    judge = platform.judge.score(preview={"variantId": "x", "sceneGraph": {"objects": [{}], "camera": {"fill": 0.7}}, "dsl": {"scene": "WHITE_STUDIO"}}, spec=CabinetSpec.model_validate(run["cabinets"][0]["placement"]["spec"]), quote=run["quote"], report_ok=True)
    assert judge["label"] == "MOCK"
    assert "visionScore" in judge and "engineeringScore" in judge
    assert judge["engineeringVeto"] is False
    bad = platform.judge.score(preview={"variantId": "y"}, spec=None, quote=None, report_ok=False)
    assert bad["engineeringVeto"] is True
    assert bad["overall"] <= 0.2
    approved = platform.factory.approve(run["runId"], actor="ops")
    assert approved["gate"]["status"] == "APPROVED"
    assert approved["gate"]["liveMachineControl"] is False

    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "t1"}
    types = client.get("/api/factory/product-types", headers=headers)
    assert types.status_code == 200
    assert "STORAGE_CABINET" in types.json()["items"]
    posted = client.post("/api/factory/run", json={"text": "鞋櫃", "render": False}, headers=headers)
    assert posted.status_code == 200
    assert posted.json()["gate"]["status"] == "WAITING_APPROVAL"
    admin = client.get("/admin")
    assert "Furniture Factory" in admin.text


def test_vision_veto_does_not_override_engineering(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 800})
    spec = CabinetSpec.model_validate(created["spec"])
    out = platform.judge.score(preview={"sceneGraph": {"objects": [{}], "camera": {"fill": 0.7}}, "dsl": {"scene": "X"}}, spec=spec, quote=created["quote"], report_ok=False)
    assert out["engineeringVeto"] is True
    assert out["label"] == "MOCK"
