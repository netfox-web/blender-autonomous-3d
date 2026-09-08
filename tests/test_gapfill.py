from fox3d.blender import detect_gpu
from fox3d.parametric import CADAdapter, CABINET_MATERIALS, CabinetSpec, map_cabinet_material


def test_gpu_discovery_uuid_and_vram():
    probe = lambda cmd: "0, GPU-abc, NVIDIA T1000, 4096, 1024, 3072, 596.86\n"
    info = detect_gpu(probe)
    assert info["discoverySource"] == "MOCK"
    assert info["gpuUuid"] == "GPU-abc"
    assert info["vramUsedGb"] == 1.0
    assert info["vramFreeGb"] == 3.0
    assert info["gpus"][0]["gpuIndex"] == 0


def test_queue_dispatched(platform):
    job = platform.submit_job(
        {
            "tenantId": "t1",
            "jobType": "BLENDER_PREVIEW",
            "scene": "WHITE_STUDIO",
            "render": {"width": 32, "height": 32},
        }
    )
    claimed = platform.queue.claim("w1")
    assert claimed["status"] == "reserved"
    platform.queue.set_status(claimed["jobId"], "dispatched")
    assert platform.queue.get(claimed["jobId"])["status"] == "dispatched"
    result = platform.execute_job(platform.queue.get(claimed["jobId"]))
    assert result["status"] in {"succeeded", "completed"}


def test_wood_materials_and_part_type(platform):
    assert set(CABINET_MATERIALS) == {"WOOD_WHITE", "WOOD_OAK", "WOOD_WALNUT", "WOOD_BLACK", "WOOD_CREAM"}
    created = platform.create_parametric(
        {
            "tenantId": "t1",
            "kind": "STORAGE_CABINET",
            "width": 800,
            "height": 1800,
            "depth": 400,
            "boardThickness": 18,
            "shelfCount": 4,
            "doorCount": 2,
            "material": "WOOD_WHITE",
        }
    )
    assert created["material"]["code"] == "WOOD_WHITE"
    types = {line.get("partType") for line in created["bom"]["lines"] if not line.get("hardware")}
    assert {"left", "right", "top", "bottom", "back", "shelf", "door"} <= types
    spec = CabinetSpec.model_validate(created["spec"])
    manifest = CADAdapter().export(spec, created["bom"])
    assert manifest["liveMachineControl"] is False
    assert manifest["requiresApproval"] is True
    assert map_cabinet_material("白色木紋")["code"] == "WOOD_WHITE"
