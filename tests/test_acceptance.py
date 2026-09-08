"""Phase 40 — 30 required acceptance checks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fox3d.blender import detect_blender, detect_gpu, detect_node
from fox3d.capabilities import BLENDER_PREVIEW, BLENDER_RENDER, BLENDER_TO_VIDEO, foxstudio_operations
from fox3d.infra import Recipe
from fox3d.pngutil import is_glb, is_png
from fox3d.studio import CAMERA_RECIPES, LIGHTING_RECIPES


def _job(tenant: str = "t1", **extra):
    payload = {
        "tenantId": tenant,
        "projectId": "p1",
        "jobType": BLENDER_PREVIEW,
        "scene": {"scene": "WHITE_STUDIO", "product": "sku-1"},
        "camera": {"lens": 85, "movement": "STATIC", "recipe": "HERO_SHOT"},
        "lighting": "SOFTBOX",
        "render": {"width": 48, "height": 48, "engine": "CYCLES", "device": "OPTIX"},
        "maxAttempts": 3,
        "timeoutSeconds": 5,
    }
    payload.update(extra)
    if "render" in extra:
        payload["render"] = {**{"width": 48, "height": 48, "engine": "CYCLES", "device": "OPTIX"}, **extra["render"]}
    return payload


def test_01_headless_blender_worker(platform, tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    source = script.read_text(encoding="utf-8")
    assert "-b" in source or "factory" in source
    assert "bpy.ops.wm.read_factory_settings" in source
    job = platform.submit_job(_job())
    result = platform.execute_job(job)
    assert result["status"] == "succeeded"
    assert result["output"]["engine"] in {"CYCLES", "EEVEE"}
    files = result["output"]["files"]
    assert "beauty.png" in files
    stored = platform.dam.get(files["beauty.png"], tenant_id="t1")
    assert is_png(Path(stored.path))


def test_02_nvidia_gpu_detection():
    probe = lambda cmd: "NVIDIA GeForce RTX 5090, 32768, 560.12\nNVIDIA GeForce RTX 5080, 16384, 560.12\n"
    info = detect_gpu(probe)
    assert info["gpuCount"] == 2
    assert info["cuda"] is True
    assert info["realGPU"] is True
    assert info["vramGb"] == 32
    assert "5090" in info["gpuName"]
    node = detect_node(gpu_probe=probe, blender_probe=lambda cmd: "Blender 4.2.0\n")
    # blender binary may be missing; GPU fields still present
    assert node["cuda"] is True


def test_03_optix_render(platform):
    job = platform.submit_job(_job(jobType=BLENDER_RENDER, render={"engine": "CYCLES", "device": "OPTIX", "optix": True}))
    result = platform.execute_job(job)
    assert result["status"] == "succeeded"
    assert result["output"]["device"] == "OPTIX"


def test_04_queue(platform):
    a = platform.submit_job(_job())
    b = platform.submit_job(_job())
    assert a["status"] == "queued"
    assert b["status"] == "queued"
    claimed = platform.queue.claim("w1")
    assert claimed["status"] == "reserved"
    assert claimed["leaseOwner"] == "w1"


def test_05_retry(platform):
    job = platform.submit_job(_job(render={"injectFailure": "nan"}, maxAttempts=3))
    result = platform.execute_job(job)
    assert result["attemptCount"] >= 1
    assert result["status"] in {"queued", "retry_scheduled"}
    assert result["error"]


def test_06_cancel(platform):
    job = platform.submit_job(_job())
    cancelled = platform.cancel_job(job["jobId"], tenant_id="t1")
    assert cancelled["status"] == "cancelled"
    running = platform.submit_job(_job())
    platform.queue.set_status(running["jobId"], "reserved")
    platform.queue.set_status(running["jobId"], "running")
    flag = __import__("threading").Event()
    flag.set()
    result = platform.execute_job(platform.queue.get(running["jobId"]), cancel_flag=flag)
    assert result["status"] in {"cancelled", "cancel_requested"}


def test_07_timeout(platform):
    job = platform.submit_job(_job(render={"injectFailure": "timeout"}, maxAttempts=2))
    result = platform.execute_job(job)
    assert "timeout" in (result.get("error") or "")
    assert result["attemptCount"] >= 1


def test_08_worker_offline_recovery(platform):
    job = platform.submit_job(_job())
    platform.queue.set_status(job["jobId"], "reserved")
    platform.queue.set_status(job["jobId"], "running")
    stored = platform.queue.get(job["jobId"])
    stored["heartbeatAt"] = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
    stored["startedAt"] = stored["heartbeatAt"]
    recovered = platform.worker_offline_recovery()
    assert job["jobId"] in recovered
    assert platform.queue.get(job["jobId"])["status"] == "queued"


def test_09_digital_twin(platform):
    twin = platform.create_twin(
        {
            "tenantId": "t1",
            "sku": "SKU-001",
            "dimensions": {"width": 200, "height": 300, "depth": 80},
            "weight": 1.2,
            "materials": ["plastic"],
            "compatibleRecipes": ["camera:HERO_SHOT"],
        }
    )
    assert twin["damAssetId"]
    assert Path(twin["glb"]).exists()
    loaded = platform.get_twin(twin["twinId"], tenant_id="t1")
    assert loaded["sku"] == "SKU-001"


def test_10_product_studio(platform):
    twin = platform.create_twin({"tenantId": "t1", "sku": "BOTTLE", "dimensions": {"width": 70, "height": 220, "depth": 70}})
    plan = platform.studio.build(twin=twin, studio="WHITE_STUDIO", camera="HERO_SHOT", lighting="SOFTBOX")
    assert plan["steps"] == [
        "load_product",
        "center",
        "ground_placement",
        "camera_framing",
        "lighting",
        "shadow",
        "reflection",
        "dof",
        "render",
    ]
    assert plan["sceneGraph"]["framing"]["centered"]
    assert set(plan["outputFormats"]) == {"PNG", "WEBP", "EXR"}


def test_11_camera_recipe(platform):
    recipes = {r.recipe_key for r in platform.recipes.find(tenant_id="system", recipe_type="CAMERA")}
    for name in CAMERA_RECIPES:
        assert name in recipes
    cam = platform.recipes.get("camera:PUSH_IN")
    assert cam.configuration["movement"] == "PUSH_IN"
    assert "duration" in cam.configuration


def test_12_lighting_recipe(platform):
    recipes = {r.recipe_key for r in platform.recipes.find(tenant_id="system", recipe_type="LIGHTING")}
    for name in LIGHTING_RECIPES:
        assert name in recipes
    gold = platform.recipes.get("lighting:GOLD_RIM")
    assert gold.version >= 1
    platform.recipes.upsert(
        Recipe(
            recipe_id="lighting:GOLD_RIM-vnext",
            recipe_key="GOLD_RIM",
            recipe_type="LIGHTING",
            tenant_id="system",
            status="EXPERIMENTAL",
            configuration={"preset": "GOLD_RIM", "energy": 1.2},
        )
    )


def test_13_packaging_mock(platform):
    pkg = platform.packaging.build(tenant_id="t1", template="BOX", sku="SOAP")
    assert pkg["pipeline"] == ["Artwork", "PackagingTemplate", "UVMapping", "Package3D", "BlenderRender"]
    assert pkg["physicalProductionRequired"] is False
    assert pkg["template"] == "BOX"


def test_14_parametric_cabinet(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "WARDROBE", "width": 1200, "height": 2200, "depth": 560})
    assert created["report"]["ok"] is True
    assert created["spec"]["kind"] == "WARDROBE"
    assert any(p["partName"] == "L_SIDE" for p in created["spec"]["components"])


def test_15_cabinet_resize(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 800, "height": 1800, "depth": 400})
    from fox3d.parametric import CabinetSpec

    spec = CabinetSpec.model_validate(created["spec"])
    resized, report = platform.cabinets.resize(spec, width=1000)
    assert report.ok
    assert resized.width == 1000
    assert resized.productId != spec.productId
    bom_a = platform.bom.build(spec)
    bom_b = platform.bom.build(resized)
    assert bom_a["engineeringHash"] != bom_b["engineeringHash"]
    assert bom_b["engineeringHash"] == resized.engineering_hash()


def test_16_bom_consistency(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "BOOKCASE", "width": 800, "height": 1800, "depth": 300, "shelfCount": 5, "doorCount": 0})
    spec_hash = created["spec"]  # dumped
    from fox3d.parametric import CabinetSpec

    spec = CabinetSpec.model_validate(created["spec"])
    bom = created["bom"]
    assert bom["engineeringHash"] == spec.engineering_hash()
    names = {line["partName"] for line in bom["lines"]}
    assert "L_SIDE" in names
    assert any(line["hardware"] for line in bom["lines"])


def test_17_cost_engine(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "KITCHEN_BASE", "width": 800})
    quote = created["quote"]
    for key in ("MaterialCost", "HardwareCost", "ProcessingCost", "AssemblyCost", "PackagingCost", "ShippingEstimate", "estimatedCost", "margin", "suggestedPrice"):
        assert key in quote
    assert quote["suggestedPrice"] > quote["estimatedCost"]


def test_18_engineering_collision(platform):
    bad, report = platform.cabinets.create(
        "CABINET",
        tenant_id="t1",
        width=400,
        height=350,
        depth=180,
        doorCount=2,
        drawerCount=3,
        shelfCount=0,
        boardThickness=18,
    )
    codes = {v.code for v in report.violations}
    assert report.ok is False
    assert "DOOR_SWING" in codes or "DRAWER_SLIDE" in codes or "DRAWER_COLLISION" in codes or "DOOR_WIDTH_MIN" in codes
    # LLM-sized fantasy rejected
    huge, huge_report = platform.cabinets.create("WARDROBE", tenant_id="t1", width=6000, height=4000, depth=800, doorCount=1, boardThickness=12)
    huge_codes = {v.code for v in huge_report.violations}
    assert huge_report.ok is False
    assert "BOARD_THICKNESS" in huge_codes or "MAX_PANEL" in huge_codes or "DOOR_WIDTH" in huge_codes


def test_19_360_render(platform, tmp_path):
    twin = platform.create_twin({"tenantId": "t1", "sku": "SKU-360", "dimensions": {"width": 100, "height": 100, "depth": 100}})
    out = platform.p360.render_mock(tmp_path, twin, frames=36)
    assert out["frames"] == 36
    assert len(out["images"]) == 36
    assert Path(out["images"][0]).exists()


def test_20_glb_export(platform, tmp_path):
    twin = platform.create_twin({"tenantId": "t1", "sku": "SKU-AR"})
    exported = platform.ar.export(twin, tmp_path)
    assert is_glb(Path(exported["glb"]))
    assert exported["usdzReserved"] is True
    assert len(exported["lod"]) == 3


def test_21_synthetic_dataset(platform, tmp_path):
    man = platform.synthetic.generate(tmp_path, job_id="j1", twin_id="tw1", frames=4)
    assert (tmp_path / "manifest.json").exists()
    assert len(man["files"]["rgb"]) == 4
    assert man["boundingBoxes"]
    assert man["cameraPoses"]
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["jobId"] == "j1"


def test_22_blender_to_video_mock(platform):
    twin = platform.create_twin({"tenantId": "t1", "sku": "SKU-VID", "dimensions": {"width": 80, "height": 120, "depth": 40}})
    plan = platform.studio.build(twin=twin)
    result = platform.b2v.run(twin=twin, scene_graph=plan["sceneGraph"], gateway=platform.gateway, adapter=None)
    assert result["adapterHardcoded"] is False
    assert result["video"]["status"] == "succeeded"
    names = {k["name"] for k in result["keyframes"]["keyframes"]}
    assert names == {"START_FRAME", "MIDDLE_FRAME", "END_FRAME"}
    assert result["keyframes"]["principle"]["blender"] == "deterministic control"


def test_23_vision_judge_mock(platform):
    rd = platform.product_rd(tenant_id="t1", text="這面牆 360cm，做奶油風電視櫃，75 吋電視，要留掃地機器人。", variant_count=12)
    assert rd["intent"]["kind"] == "TV_CABINET"
    assert rd["approval"]["status"] == "WAITING_APPROVAL"
    assert rd["productionAssets"] == []
    assert rd["scoredCount"] >= 1
    assert "overall" in rd["top"][0]["judge"]
    approved = platform.rd.approve(rd, actor="owner")
    assert approved["approval"]["status"] == "APPROVED"
    assert approved["productionAssets"]


def test_24_recipe_research(platform):
    prod = platform.recipes.get("lighting:SOFTBOX")
    assert prod.status == "PRODUCTION"
    created = platform.research.research_idle(tenant_id="t1", gpu_idle=True)
    assert created
    assert all(r.status in {"EXPERIMENTAL", "CANDIDATE"} for r in created)
    with pytest.raises(ValueError):
        platform.recipes.upsert(
            Recipe(
                recipe_id="lighting:SOFTBOX",
                recipe_key="SOFTBOX",
                recipe_type="LIGHTING",
                status="PRODUCTION",
                tenant_id="system",
                configuration={"clobber": True},
            )
        )


def test_25_tenant_isolation(platform):
    twin = platform.create_twin({"tenantId": "alpha", "sku": "SECRET"})
    with pytest.raises(PermissionError):
        platform.get_twin(twin["twinId"], tenant_id="beta")
    job = platform.submit_job(_job(tenant="alpha"))
    with pytest.raises(PermissionError):
        platform.get_job(job["jobId"], tenant_id="beta")


def test_26_asset_lineage(platform):
    job = platform.submit_job(_job())
    result = platform.execute_job(job)
    rows = platform.lineage.for_job(result["jobId"], tenant_id="t1")
    assert rows
    row = rows[0]
    assert row.job_id == result["jobId"]
    assert row.worker_id
    assert row.gpu
    assert row.blender_version
    assert row.output


def test_27_cache(platform):
    payload = _job()
    first = platform.execute_job(platform.submit_job(payload))
    second = platform.execute_job(platform.submit_job(payload))
    assert first["status"] == "succeeded"
    assert second["cacheHit"] is True
    assert second["status"] == "succeeded"


def test_28_scheduler(platform):
    preview = platform.gpu_policy.place(platform.scheduler, {"jobType": BLENDER_PREVIEW, "gpuRequirement": {"minVramGb": 2}})
    assert preview["targetKey"] == "5080-1"
    video = platform.gpu_policy.place(platform.scheduler, {"jobType": BLENDER_TO_VIDEO, "gpuRequirement": {"minVramGb": 8}})
    assert video["targetKey"] == "5090-1"
    assert preview["pinForbidden"] is True
    assert set(foxstudio_operations())


def test_29_gpu_draining(platform):
    drained = platform.drain.request_drain("5080-1", "preempt for AI video")
    assert drained["status"] == "draining"
    placement = platform.gpu_policy.place(platform.scheduler, {"jobType": BLENDER_PREVIEW, "gpuRequirement": {}})
    assert placement["targetKey"] != "5080-1"
    steps = platform.drain.finish_unit_and_release({"jobId": "x"}, frame=12, tile=3)
    assert steps["killed"] is False
    assert steps["steps"][0] == "frame_or_tile_complete"
    platform.compute.control("5080-1", "resume", "done")
    assert platform.compute.get("5080-1").status == "online"


def test_30_security_sandbox(platform):
    evil = b"import os; os.system('rm -rf /')"
    with pytest.raises(PermissionError):
        platform.scripts.authorize(evil, production=True)
    experimental = platform.scripts.register(name="agent.py", source=evil, signature="unsigned", allow_production=False)
    with pytest.raises(PermissionError):
        platform.scripts.authorize(evil, production=True)
    script = Path(__file__).resolve().parents[1] / "scripts" / "blender_job.py"
    rec = platform.scripts.authorize(script.read_bytes(), production=True)
    assert rec["allowlist"] is True
    assert rec["networkRestrictions"] == ["deny_all"]
