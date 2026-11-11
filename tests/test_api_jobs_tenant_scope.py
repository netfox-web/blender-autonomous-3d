"""GET /api/3d/jobs must be tenant-scoped; missing X-Tenant-Id returns 400."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fox3d.api import create_app

_JOB = {"jobType": "BLENDER_PREVIEW", "scene": "WHITE_STUDIO"}


def _submit(client: TestClient, tenant: str) -> str:
    res = client.post("/api/3d/jobs", json=_JOB, headers={"X-Tenant-Id": tenant})
    assert res.status_code == 200, res.text
    return res.json()["jobId"]


def test_list_jobs_requires_tenant_header_and_scopes_items(platform) -> None:  # noqa: ANN001 - conftest fixture
    client = TestClient(create_app(platform))
    job_t1 = _submit(client, "t1")
    job_t2 = _submit(client, "t2")

    assert client.get("/api/3d/jobs").status_code == 400

    items_t1 = client.get("/api/3d/jobs", headers={"X-Tenant-Id": "t1"}).json()["items"]
    ids_t1 = {j["jobId"] for j in items_t1}
    assert job_t1 in ids_t1
    assert job_t2 not in ids_t1

    items_t2 = client.get("/api/3d/jobs", headers={"X-Tenant-Id": "t2"}).json()["items"]
    ids_t2 = {j["jobId"] for j in items_t2}
    assert job_t2 in ids_t2
    assert job_t1 not in ids_t2
