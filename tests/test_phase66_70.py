from fox3d.ops import assert_job_paths_safe


def test_path_traversal_blocked(platform):
    job = platform.submit_job(
        {
            "tenantId": "t1",
            "jobType": "BLENDER_PREVIEW",
            "scene": "WHITE_STUDIO",
            "glbPath": r"..\..\Windows\System32\cmd.exe",
            "render": {"width": 16, "height": 16},
        }
    )
    result = platform.execute_job(job)
    assert result["status"] == "blocked"
    assert "traversal" in (result.get("error") or "")


def test_packaging_uses_same_twin_store(platform):
    out = platform.packaging_twin(tenant_id="t1", template="BOX", sku="BOX-01")
    assert out["sameTwinStore"] is True
    twin_id = out["twin"]["twinId"]
    loaded = platform.get_twin(twin_id, tenant_id="t1")
    assert loaded["productMetadata"]["kind"] == "PACKAGING"
    assert loaded["productMetadata"]["template"] == "BOX"
    assert loaded["sku"] == "BOX-01"


def test_blender_to_video_adapter_not_hardcoded(platform):
    twin = platform.create_twin({"tenantId": "t1", "sku": "VID-1", "dimensions": {"width": 80, "height": 120, "depth": 40}})
    out = platform.blender_to_video(tenant_id="t1", twin_id=twin["twinId"])
    assert out["adapterHardcoded"] is False
    assert out["aiVideoStatus"] == "MOCK"
    assert out["principle"]["blender"] == "deterministic control"


def test_synthetic_manifest_required(platform):
    twin = platform.create_twin({"tenantId": "t1", "sku": "SYN-1"})
    out = platform.synthetic_dataset(tenant_id="t1", twin_id=twin["twinId"], frames=4)
    assert "manifest" in out
    assert out["manifest"]["jobId"]
    assert "RGB" in out["manifest"]["produced"]
    assert out["manifest"]["manifestAssetId"]


def test_hardening_and_sandbox(platform):
    report = platform.hardening_report()
    assert report["pathTraversalGuard"] is True
    assert report["liveCnc"] is False
    assert "SANDBOX ONLY" in report["arbitraryPython"]
    assert_job_paths_safe({"glbPath": "ok.glb"})
    rd = platform.product_rd(tenant_id="t1", text="做一個書櫃 80cm 寬")
    assert rd["HUMAN_APPROVAL_REQUIRED"] is True
