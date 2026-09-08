from fox3d.parametric import parse_design_intent, tv_width_mm
from fox3d.scene import SceneDSL, compile_scene_graph
from fox3d.space import SpacePipeline
from fox3d.studio import MaterialEngine


def test_nl_storage_cabinet_cm():
    from fox3d.parametric import parse_design_intent

    intent = parse_design_intent(
        "幫我做一個寬120公分、高180公分、深40公分，雙門、4層板、白色木紋收納櫃",
        tenant_id="t1",
    )
    assert intent["kind"] == "STORAGE_CABINET"
    assert intent["params"]["width"] == 1200
    assert intent["params"]["height"] == 1800
    assert intent["params"]["depth"] == 400
    assert intent["params"]["doorCount"] == 2
    assert intent["params"]["shelfCount"] == 4
    assert intent["llmMayNotSetMillimetresDirectly"] is True


def test_nl_design_intent_tv_cabinet():
    intent = parse_design_intent(
        "這面牆 360cm，做奶油風電視櫃，75 吋電視，要留掃地機器人。",
        tenant_id="t1",
    )
    assert intent["kind"] == "TV_CABINET"
    assert intent["params"]["legs"] is True
    assert intent["params"]["plinthHeight"] == 100
    assert intent["params"]["metadata"]["style"] == "cream"
    assert intent["params"]["metadata"]["tvInches"] == 75
    assert intent["params"]["width"] >= tv_width_mm(75)
    assert intent["params"]["width"] <= 3600
    assert intent["params"]["width"] < 3600  # wall is a constraint, not the carcass width


def test_scene_dsl_luxury_studio():
    dsl = SceneDSL.from_job(
        {
            "scene": "LUXURY_STUDIO",
            "product": "watch",
            "camera": {"lens": 85, "movement": "SLOW_PUSH_IN"},
            "lighting": "GOLD_RIM",
            "animation": {"type": "TURNTABLE", "degrees": 180, "duration": 8},
        }
    )
    graph = compile_scene_graph(dsl, product={"dimensions": {"width": 80, "height": 40, "depth": 80}})
    assert graph["studio"] == "LUXURY_STUDIO"
    lights = [o["name"] for o in graph["objects"] if o["name"].startswith("Light")]
    assert "Light.Rim" in lights
    assert graph["animation"]["type"] == "TURNTABLE"


def test_material_suggestion_versions(platform):
    engine = MaterialEngine(platform.recipes, platform.gateway)
    first = engine.suggest(tenant_id="t1", images=["a.png"], metadata={"category": "metal"}, twin_id="tw")
    second = engine.suggest(tenant_id="t1", images=["b.png"], metadata={"category": "wood"}, twin_id="tw")
    assert first["overwroteTwin"] is False
    assert second["recipeId"] != first["recipeId"]
    assert first["status"] == "EXPERIMENTAL"


def test_space_and_retail_and_assembly(platform):
    space = platform.spaces.ingest(
        {"tenantId": "t1", "width": 4000, "depth": 3000, "height": 2600, "doors": [{"kind": "door", "width": 900, "height": 2100}]}
    )
    assert space.pipelineStatus == "mock_ready"
    assert len(space.walls) == 4
    retail = platform.retail.propose(space={"kind": "BOOTH", "width": 4000, "depth": 3000}, brand="FOX", skus=["A"], count=6)
    assert retail["kind"] == "BOOTH"
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 800})
    anim = platform.assembly.from_component_graph(created["spec"])
    assert anim["explode"]
    assert anim["assembly"]
    cam = platform.cam.export(
        __import__("fox3d.parametric", fromlist=["CabinetSpec"]).CabinetSpec.model_validate(created["spec"]),
        created["bom"],
    )
    assert cam["liveMachineControl"] is False
    assert cam["requiresApproval"] is True
