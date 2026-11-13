"""Unit tests for FoxStudio / Fleet integration maps."""

from __future__ import annotations

from fox3d.capabilities import FLEET_TASK_TYPE_BY_CAPABILITY, FOXSTUDIO_OPERATION_BY_CAPABILITY
from fox3d.integrations import FLEET_TASK_TYPES, FOXSTUDIO_KIND_HANDLERS, foxstudio_handler


def test_foxstudio_kind_handlers_cover_every_operation():
    operations = set(FOXSTUDIO_OPERATION_BY_CAPABILITY.values())
    assert set(FOXSTUDIO_KIND_HANDLERS) == operations
    for operation in operations:
        assert FOXSTUDIO_KIND_HANDLERS[operation] == "fox3d.integrations.foxstudio_handler"


def test_foxstudio_handler_forwards_job_to_platform_execute_job():
    seen: dict = {}

    class FakePlatform:
        def execute_job(self, job):
            seen["job"] = job
            return {"status": "succeeded", "echo": job}

    job = {"jobId": "job-1", "jobType": "BLENDER_PREVIEW", "tenantId": "t1"}
    handler = foxstudio_handler(FakePlatform())
    out = handler(job)
    assert seen["job"] is job
    assert out == {"status": "succeeded", "echo": job}


def test_fleet_task_types_is_copy_of_capability_map(monkeypatch):
    assert FLEET_TASK_TYPES == FLEET_TASK_TYPE_BY_CAPABILITY
    monkeypatch.setitem(FLEET_TASK_TYPES, "BLENDER_PREVIEW", "mutated")
    assert FLEET_TASK_TYPE_BY_CAPABILITY["BLENDER_PREVIEW"] == "blender_preview"
