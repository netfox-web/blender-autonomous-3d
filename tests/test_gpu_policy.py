from unittest.mock import Mock

import pytest

from fox3d.gpu import GpuPolicy


@pytest.mark.parametrize(
    ("job_type", "lane"),
    [
        ("BLENDER_TO_VIDEO", "ai_video"),
        ("BLENDER_PREVIEW", "blender_preview"),
        ("BLENDER_SCENE", "blender_preview"),
        ("PARAMETRIC_3D", "blender_preview"),
        ("BLENDER_RENDER", "blender_final"),
        ("BLENDER_ANIMATION", "blender_final"),
        ("BLENDER_PRODUCT", "blender_final"),
        ("BLENDER_360", "blender_final"),
        ("BLENDER_SYNTHETIC_DATA", "blender_final"),
        ("SYNTHETIC_DATA", "blender_final"),
        ("PRODUCT_360", "blender_final"),
        ("BLENDER_AR_ASSET", "general"),
        ("UNKNOWN", "general"),
        ("", "general"),
    ],
)
def test_lane(job_type, lane):
    assert GpuPolicy().lane(job_type) == lane


def test_annotate_copies_job_and_overrides_policy_fields():
    job = {"jobType": "BLENDER_PREVIEW", "lane": "old", "pinForbidden": False}
    annotated = GpuPolicy().annotate(job)
    assert job == {"jobType": "BLENDER_PREVIEW", "lane": "old", "pinForbidden": False}
    assert annotated == {"jobType": "BLENDER_PREVIEW", "lane": "blender_preview", "pinForbidden": True}
    assert annotated is not job


@pytest.mark.parametrize("operator_pinned", [False, True])
def test_place_passes_annotated_job_and_overrides_decision(operator_pinned):
    job = {"jobType": "BLENDER_RENDER", "gpuRequirement": {"exactTargetKey": "target"},
           "operatorPinned": operator_pinned}
    scheduler = Mock()
    scheduler.place.return_value = {"target": "target", "lane": "old", "pinForbidden": False}
    decision = GpuPolicy().place(scheduler, job)
    scheduler.place.assert_called_once_with({**job, "lane": "blender_final", "pinForbidden": True})
    assert decision == {"target": "target", "lane": "blender_final", "pinForbidden": True}
    assert "lane" not in job and "pinForbidden" not in job
