"""HTTP coverage for preview lifecycle and truthful mock reporting."""
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d import golden_preview
from fox3d.api import create_app
from fox3d.golden_product import SKUS
from fox3d.platform import Platform
from fox3d.recipe_admin_api import recipe_router

HEADERS = {"X-Tenant-Id": "tenant-a"}
OTHER = {"X-Tenant-Id": "tenant-b"}


@pytest.fixture
def preview_client(tmp_path, monkeypatch):
    started = threading.Event()
    def render(*args, **kwargs):
        started.set()
        if not kwargs["cancel_flag"].wait(5):
            raise RuntimeError("test timed out waiting for cancellation")
        raise ValueError("cancelled")

    monkeypatch.setattr(golden_preview, "generate", render)
    monkeypatch.setattr("fox3d.recipe_preview_service.generate_recipe_3d_product", render)
    platform = SimpleNamespace(root=tmp_path, mock_blender=False,
                               runtime=SimpleNamespace(available=lambda: True))
    app = FastAPI()
    app.include_router(recipe_router(lambda: platform))
    with TestClient(app) as client:
        yield client, platform, started


@pytest.fixture(params=["golden", "recipe"])
def route(request):
    if request.param == "golden":
        return f"/api/recipe-library/golden/{SKUS[0]}"
    return "/api/recipe-library/products/MY-012/3d"


def start(client, base, started):
    params = {"version": "FIXTURE_MASTER_V1"} if "/golden/" in base else {}
    plan = client.get(base + "/plan", headers=HEADERS, params=params)
    assert plan.status_code == 200
    p = plan.json()
    body = {"planHash": p["planHash"], "assumptionsAccepted": True}
    if params:
        body.update(version=params["version"])
    else:
        body.update(expectedRevision=p["revision"])
    response = client.post(base + "/generate", headers=HEADERS, json=body)
    assert response.status_code == 202, response.text
    assert started.wait(2)
    return response.json()["taskId"]


def wait_cancelled(client, base):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(base + "/status", headers=HEADERS)
        assert response.status_code == 200
        if response.json()["state"] == "cancelled":
            return response.json()
        time.sleep(.01)
    pytest.fail("preview did not reach cancelled state")


def test_idle_status(preview_client, route):
    client, _, _ = preview_client
    response = client.get(route + "/status", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["state"] == "idle"
    assert response.json()["generated"] is False


def test_cancel_lifecycle_is_idempotent(preview_client, route):
    client, _, started = preview_client
    task_id = start(client, route, started)
    body = {"taskId": task_id}
    response = client.post(route + "/cancel", headers=HEADERS, json=body)
    assert response.status_code == 200
    assert response.json() == {"taskId": task_id, "cancelRequested": True}
    assert wait_cancelled(client, route)["taskId"] == task_id
    again = client.post(route + "/cancel", headers=HEADERS, json=body)
    assert again.status_code == 200
    assert again.json() == response.json()
    assert client.get(route + "/status", headers=HEADERS).json()["state"] == "cancelled"


def test_other_tenant_cannot_cancel(preview_client, route):
    client, _, started = preview_client
    task_id = start(client, route, started)
    rejected = client.post(route + "/cancel", headers=OTHER, json={"taskId": task_id})
    assert rejected.status_code in (404, 409, 422)
    assert client.get(route + "/status", headers=HEADERS).json()["state"] == "running"
    assert client.post(route + "/cancel", headers=HEADERS, json={"taskId": task_id}).status_code == 200
    wait_cancelled(client, route)
    assert client.post(route + "/cancel", headers=OTHER, json={"taskId": task_id}).status_code in (404, 409, 422)


@pytest.mark.parametrize("base", ["/api/recipe-library/golden/nonexistent", "/api/recipe-library/products/nonexistent/3d"])
@pytest.mark.parametrize("operation", ["status", "cancel"])
def test_unknown_sku_returns_404(preview_client, base, operation):
    client, _, _ = preview_client
    if operation == "status":
        response = client.get(base + "/status", headers=HEADERS)
    else:
        response = client.post(base + "/cancel", headers=HEADERS, json={"taskId": "missing"})
    assert response.status_code == 404


def test_health_reports_mock_unavailable(preview_client):
    client, platform, _ = preview_client
    platform.mock_blender = True
    response = client.get("/api/recipe-library/health")
    assert response.status_code == 200
    assert response.json()["blenderAvailable"] is False


def test_health_reports_runtime_unavailable(preview_client):
    client, platform, _ = preview_client
    platform.runtime.available = lambda: False
    assert client.get("/api/recipe-library/health").json()["blenderAvailable"] is False


def test_smoke_reports_mock_truth(tmp_path, monkeypatch):
    import fox3d.api as api
    monkeypatch.setattr(api, "_PLATFORM", None)
    platform = Platform(root=tmp_path, mock_blender=True)
    with TestClient(create_app(platform)) as client:
        response = client.post("/api/e2e/smoke")
    assert response.status_code == 200
    result = response.json()
    assert result["discoverySource"] == "MOCK"
    assert result["usedMock"] is True
    assert result["realBlender"] is False
