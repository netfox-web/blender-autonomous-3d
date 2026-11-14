"""aiVideoStatus truth labels for blender_to_video."""

from __future__ import annotations

import pytest

from fox3d.blender import BLOCKED_NO_BLENDER
from fox3d.platform import Platform


@pytest.fixture
def twin(platform):
    return platform.create_twin({"tenantId": "t1", "sku": "VID-ST", "dimensions": {"width": 80, "height": 120, "depth": 40}})


def test_succeeded_adapter_marks_real(platform, twin):
    platform.gateway.register_video_adapter(
        "live-test",
        lambda req: {"provider": "live-test", "status": "succeeded", "output": {"duration": req.get("duration", 4)}},
    )
    out = platform.blender_to_video(tenant_id="t1", twin_id=twin["twinId"], adapter="live-test")
    assert out["aiVideoStatus"] == "REAL"
    assert out["aiVideo"]["status"] == "succeeded"


def test_completed_adapter_marks_real(platform, twin):
    platform.gateway.register_video_adapter(
        "live-completed",
        lambda req: {"provider": "live-completed", "status": "completed", "output": {}},
    )
    out = platform.blender_to_video(tenant_id="t1", twin_id=twin["twinId"], adapter="live-completed")
    assert out["aiVideoStatus"] == "REAL"


def test_failed_adapter_not_real(platform, twin):
    platform.gateway.register_video_adapter(
        "live-fail",
        lambda _req: {"provider": "live-fail", "status": "failed", "error": "provider rejected keyframes"},
    )
    out = platform.blender_to_video(tenant_id="t1", twin_id=twin["twinId"], adapter="live-fail")
    assert out["aiVideoStatus"] == "FAILED"
    assert out["aiVideo"]["error"] == "provider rejected keyframes"
    assert out["aiVideoStatus"] != "REAL"


def test_adapter_exception_marked_failed(platform, twin):
    sensitive_message = "transport failed: https://example.invalid/?credential=PRIVATE_TEST_VALUE"

    def boom(_req):
        raise RuntimeError(sensitive_message)

    platform.gateway.register_video_adapter("live-boom", boom)
    out = platform.blender_to_video(tenant_id="t1", twin_id=twin["twinId"], adapter="live-boom")
    assert out["aiVideoStatus"] == "FAILED"
    assert out["aiVideo"]["error"] == "VIDEO_ADAPTER_ERROR"
    assert sensitive_message not in str(out)
    assert "PRIVATE_TEST_VALUE" not in str(out)


@pytest.mark.parametrize("identity", [{"provider": "mock"}, {"kind": "mock_video"}])
@pytest.mark.parametrize("status, expected", [("failed", "FAILED"), ("blocked", "BLOCKED"), ("blocked_policy", "BLOCKED"), ("pending", "FAILED")])
def test_unsuccessful_mock_adapter_preserves_status(platform, twin, identity, status, expected):
    platform.gateway.register_video_adapter("mock-unsuccessful", lambda _req: {**identity, "status": status})
    out = platform.blender_to_video(tenant_id="t1", twin_id=twin["twinId"], adapter="mock-unsuccessful")
    assert out["aiVideoStatus"] == expected
    assert out["aiVideo"]["status"] == status


def test_unregistered_adapter_name_is_mock(platform, twin):
    calls_before = len(platform.gateway.calls)
    out = platform.blender_to_video(tenant_id="t1", twin_id=twin["twinId"], adapter="not-registered-adapter")
    assert out["aiVideoStatus"] == "MOCK"
    assert out["aiVideo"]["kind"] == "mock_video"
    assert len(platform.gateway.calls) == calls_before + 1


def test_production_gate_blocks_without_gateway_call(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "fox3d.platform.probe_host",
        lambda **kwargs: __import__("fox3d.blender", fromlist=["HostProbe"]).HostProbe(
            blender=False,
            blenderBinary=None,
            blenderVersion=None,
            blenderVersionRaw="",
            cycles=False,
            cuda=True,
            optix=False,
            gpus=[],
            gpuName=None,
            vramGb=0,
            driver="test",
            blocked=[BLOCKED_NO_BLENDER],
            realBlender=False,
            realGPU=False,
            realCycles=False,
            realOptix=False,
        ),
    )
    plat = Platform(root=tmp_path, mock_blender=False)
    plat.runtime.blender_bin = None
    plat.runtime.force_mock = False
    twin = plat.create_twin({"tenantId": "t1", "sku": "VID-GATE"})
    calls_before = len(plat.gateway.calls)
    out = plat.blender_to_video(tenant_id="t1", twin_id=twin["twinId"])
    assert out["aiVideoStatus"] == "BLOCKED"
    assert out["blender"]["status"] == "blocked"
    assert out["aiVideo"]["error"] == BLOCKED_NO_BLENDER
    assert len(plat.gateway.calls) == calls_before
