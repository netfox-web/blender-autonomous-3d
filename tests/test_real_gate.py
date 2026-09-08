"""Production path must not fall back to mock and claim success."""

from __future__ import annotations

from fox3d.blender import BLOCKED_NO_BLENDER, BlenderRuntime
from fox3d.platform import Platform


def test_runtime_without_blender_blocks_not_mocks(tmp_path, monkeypatch):
    monkeypatch.delenv("FOX3D_MOCK_BLENDER", raising=False)
    runtime = BlenderRuntime(work_dir=tmp_path, force_mock=False, blender_bin=None)
    runtime.blender_bin = None
    result = runtime.run_job({"jobId": "j1", "render": {}})
    assert result.used_mock is False
    assert result.status == "blocked"
    assert result.error == BLOCKED_NO_BLENDER
    assert result.real_blender is False


def test_real_smoke_blocked_without_blender(tmp_path, monkeypatch):
    monkeypatch.setattr("fox3d.blender.find_blender", lambda explicit=None: None)
    monkeypatch.setattr("fox3d.platform.probe_host", lambda **kwargs: __import__("fox3d.blender", fromlist=["HostProbe"]).HostProbe(
        blender=False,
        blenderBinary=None,
        blenderVersion=None,
        blenderVersionRaw="",
        cycles=False,
        cuda=True,
        optix=False,
        gpus=[{"gpuIndex": 0, "name": "NVIDIA T1000", "vramGb": 4}],
        gpuName="NVIDIA T1000",
        vramGb=4,
        driver="test",
        blocked=[BLOCKED_NO_BLENDER],
        realBlender=False,
        realGPU=True,
        realCycles=False,
        realOptix=False,
    ))
    plat = Platform(root=tmp_path, mock_blender=False)
    plat.runtime.blender_bin = None
    plat.runtime.force_mock = False
    result = plat.real_smoke_test()
    assert result["status"] == "blocked"
    assert result["error"] == BLOCKED_NO_BLENDER
    assert result.get("usedMock") is not True
    assert result.get("realBlender") is False
