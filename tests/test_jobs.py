"""BlenderJob numeric constraints and POST /api/3d/jobs 422 contract. Issue #550."""

from __future__ import annotations

import math
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fox3d.api import create_app
from fox3d.jobs import MAX_TIMEOUT_SECONDS, BlenderJob

HEADERS = {"X-Tenant-Id": "acme"}


def _job(**fields: Any) -> BlenderJob:
    return BlenderJob.model_validate({"tenantId": "acme", **fields})


# ----- defaults & built-in job parameters --------------------------------


def test_defaults_are_valid() -> None:
    job = _job()
    assert job.timeoutSeconds == 300.0
    assert job.maxAttempts == 3
    assert job.attemptCount == 0
    assert job.progress == 0.0
    assert job.priority == 50
    assert job.gpuRequirement.minVramGb is None


@pytest.mark.parametrize("timeout", [900, 600, 1800, 14400])
def test_builtin_preview_job_parameters_stay_valid(timeout: int) -> None:
    # golden_preview / print_preview / model_compositions use maxAttempts=1, timeoutSeconds=900.
    job = _job(maxAttempts=1, timeoutSeconds=timeout, jobType="PARAMETRIC_3D", mode="CABINET_PREVIEW")
    assert job.maxAttempts == 1
    assert job.timeoutSeconds == float(timeout)


# ----- per-field boundaries ----------------------------------------------

VALID = [
    ("timeoutSeconds", 0.001),
    ("timeoutSeconds", 1),
    ("timeoutSeconds", MAX_TIMEOUT_SECONDS),
    ("timeoutSeconds", "300"),
    ("maxAttempts", 1),
    ("maxAttempts", 20),
    ("attemptCount", 0),
    ("attemptCount", 5),
    ("progress", 0.0),
    ("progress", 0.5),
    ("progress", 1.0),
    ("priority", 0),
    ("priority", 100),
]

INVALID = [
    ("timeoutSeconds", 0),
    ("timeoutSeconds", -5),
    ("timeoutSeconds", MAX_TIMEOUT_SECONDS + 1),
    ("timeoutSeconds", "nan"),
    ("timeoutSeconds", math.nan),
    ("timeoutSeconds", math.inf),
    ("timeoutSeconds", "inf"),
    ("timeoutSeconds", "abc"),
    ("maxAttempts", 0),
    ("maxAttempts", -1),
    ("maxAttempts", 21),
    ("maxAttempts", "abc"),
    ("maxAttempts", 1.5),
    ("attemptCount", -1),
    ("progress", -0.01),
    ("progress", 1.01),
    ("progress", 7),
    ("progress", math.nan),
    ("priority", -1),
    ("priority", -999),
    ("priority", 101),
]


@pytest.mark.parametrize(("field", "value"), VALID)
def test_valid_boundaries(field: str, value: Any) -> None:
    job = _job(**{field: value})
    assert getattr(job, field) == pytest.approx(float(value))


@pytest.mark.parametrize(("field", "value"), INVALID)
def test_invalid_boundaries_raise(field: str, value: Any) -> None:
    with pytest.raises(ValidationError) as info:
        _job(**{field: value})
    assert any(err["loc"] == (field,) for err in info.value.errors())


@pytest.mark.parametrize("vram", [None, 0, 0.0, 8, 32.5])
def test_min_vram_valid(vram: float | None) -> None:
    assert _job(gpuRequirement={"minVramGb": vram}).gpuRequirement.minVramGb == vram


@pytest.mark.parametrize("vram", [-1, -0.5, math.nan, math.inf, "nan", "abc"])
def test_min_vram_invalid(vram: Any) -> None:
    with pytest.raises(ValidationError) as info:
        _job(gpuRequirement={"minVramGb": vram})
    assert any(err["loc"] == ("gpuRequirement", "minVramGb") for err in info.value.errors())


# ----- scene / lighting coercion -----------------------------------------


def test_scene_string_coerced_to_dict() -> None:
    assert _job(scene="WHITE_STUDIO").scene == {"scene": "WHITE_STUDIO"}


def test_lighting_string_coerced_to_preset() -> None:
    assert _job(lighting="SOFTBOX").lighting == {"preset": "SOFTBOX"}


@pytest.mark.parametrize("empty", [None, {}])
def test_scene_and_lighting_empty_become_dict(empty: Any) -> None:
    job = _job(scene=empty, lighting=empty)
    assert job.scene == {}
    assert job.lighting == {}


def test_scene_and_lighting_empty_string_is_still_wrapped() -> None:
    # Existing behaviour: any str (even empty) is wrapped, not dropped.
    job = _job(scene="", lighting="")
    assert job.scene == {"scene": ""}
    assert job.lighting == {"preset": ""}


def test_scene_and_lighting_dicts_pass_through() -> None:
    job = _job(scene={"scene": "X", "floor": True}, lighting={"preset": "P", "intensity": 2})
    assert job.scene == {"scene": "X", "floor": True}
    assert job.lighting == {"preset": "P", "intensity": 2}


# ----- routing_requirements ----------------------------------------------


def test_routing_requirements_without_pins() -> None:
    req = _job(gpuRequirement={"minVramGb": 12}).routing_requirements()
    assert req["requiredCapabilities"] == {"blender": True}
    assert req["minVramGb"] == 12
    assert "computeTargetKey" not in req
    assert "allowedComputeTargets" not in req


def test_routing_requirements_exact_target_key() -> None:
    req = _job(gpuRequirement={"exactTargetKey": "5090-1"}).routing_requirements()
    assert req["computeTargetKey"] == "5090-1"
    assert "allowedComputeTargets" not in req


def test_routing_requirements_prefer_target_keys() -> None:
    req = _job(gpuRequirement={"preferTargetKeys": ["5080-1", "5090-1"]}).routing_requirements()
    assert req["allowedComputeTargets"] == ["5080-1", "5090-1"]
    assert "computeTargetKey" not in req


def test_routing_requirements_both_pins() -> None:
    req = _job(gpuRequirement={"exactTargetKey": "5090-1", "preferTargetKeys": ["5080-1"]}).routing_requirements()
    assert req["computeTargetKey"] == "5090-1"
    assert req["allowedComputeTargets"] == ["5080-1"]


# ----- API: 422 not 500 ---------------------------------------------------


@pytest.fixture
def client(platform: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FOX3D_MOCK_BLENDER", "1")
    return TestClient(create_app(platform), raise_server_exceptions=False)


API_INVALID: list[dict[str, Any]] = [
    {"maxAttempts": "abc"},
    {"maxAttempts": 0},
    {"maxAttempts": 21},
    {"timeoutSeconds": "nan"},
    {"timeoutSeconds": -5},
    {"timeoutSeconds": 0},
    {"timeoutSeconds": 86401},
    {"progress": 7},
    {"priority": -999},
    {"priority": 101},
    {"attemptCount": -1},
    {"gpuRequirement": {"minVramGb": -1}},
    {"gpuRequirement": {"minVramGb": "nan"}},
    {"status": "not-a-status"},
]


@pytest.mark.parametrize("body", API_INVALID, ids=lambda b: repr(b))
def test_api_invalid_job_fields_return_422(client: TestClient, body: dict[str, Any]) -> None:
    res = client.post("/api/3d/jobs", json={"jobType": "BLENDER_PREVIEW", **body}, headers=HEADERS)
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert isinstance(detail, str)
    assert "格式錯誤" in detail
    # Never leak internal paths or pydantic internals.
    for leak in ("/", "\\", "src", "fox3d", "pydantic", "Traceback", ".py"):
        assert leak not in detail


def test_api_invalid_job_is_not_enqueued(client: TestClient) -> None:
    res = client.post("/api/3d/jobs", json={"maxAttempts": "abc"}, headers=HEADERS)
    assert res.status_code == 422
    assert client.get("/api/3d/jobs", headers=HEADERS).json()["items"] == []


def test_api_valid_boundary_job_is_accepted(client: TestClient) -> None:
    body = {
        "jobType": "BLENDER_PREVIEW",
        "scene": "WHITE_STUDIO",
        "lighting": "SOFTBOX",
        "maxAttempts": 1,
        "timeoutSeconds": 900,
        "priority": 100,
        "progress": 0,
        "gpuRequirement": {"minVramGb": 0, "exactTargetKey": "5090-1"},
    }
    res = client.post("/api/3d/jobs", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    job = res.json()
    assert job["maxAttempts"] == 1
    assert job["timeoutSeconds"] == 900
    assert job["scene"] == {"scene": "WHITE_STUDIO"}
    assert job["lighting"] == {"preset": "SOFTBOX"}
    assert job["routing_requirements"]["computeTargetKey"] == "5090-1"
