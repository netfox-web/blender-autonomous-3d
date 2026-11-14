"""Contract tests for probe, golden catalog, and golden admin routes."""

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.blender import HostProbe
from fox3d.golden_product import SKUS


@pytest.fixture
def client(platform):
    with TestClient(create_app(platform)) as client:
        yield client


def test_probe_registers_missing_probe_without_claiming_real_blender(client, platform, monkeypatch):
    detected = HostProbe(
        blender=False, blenderBinary=None, blenderVersion=None, blenderVersionRaw="",
        cycles=False, cuda=False, optix=False, realBlender=False,
    )
    calls = []

    def fake_probe_host(**kwargs):
        calls.append(kwargs)
        return detected

    monkeypatch.setattr("fox3d.platform.probe_host", fake_probe_host)
    assert platform.mock_blender and platform.probe is None
    response = client.get("/api/probe")
    assert response.status_code == 200
    assert response.json() == detected.to_dict()
    assert response.json()["realBlender"] is False
    assert len(calls) == 1
    assert platform.probe is detected


def test_probe_reuses_cached_probe(client, platform, monkeypatch):
    detected = HostProbe(
        blender=False, blenderBinary=None, blenderVersion=None, blenderVersionRaw="",
        cycles=False, cuda=False, optix=False, realBlender=False,
    )
    platform.probe = detected
    def unexpected_registration():
        pytest.fail("cached probe must not trigger registration")
    monkeypatch.setattr(platform, "register_detected_workers", unexpected_registration)
    response = client.get("/api/probe")
    assert response.status_code == 200
    assert response.json() == detected.to_dict()


def test_golden_catalog_skus(client):
    response = client.get("/api/recipe-library/golden")
    assert response.status_code == 200
    assert response.json()["skus"] == list(SKUS)


@pytest.mark.parametrize(
    ("version", "truth"),
    [("HISTORICAL_PENDING", "BLOCKED"), ("FIXTURE_MASTER_V1", "FIXTURE"),
     ("FIXTURE_SINGLE_V1", "FIXTURE")],
)
def test_golden_catalog_version_truth(client, version, truth):
    response = client.get("/api/recipe-library/golden")
    assert response.status_code == 200
    versions = response.json()["versions"]
    assert len(versions) == 3
    assert {item["id"] for item in versions} == {
        "HISTORICAL_PENDING", "FIXTURE_MASTER_V1", "FIXTURE_SINGLE_V1"
    }
    assert {item["id"]: item["truth"] for item in versions}[version] == truth
    assert all(item["truth"] != "REAL" for item in versions)


def test_golden_admin_html_and_csp(client):
    response = client.get("/admin/recipes/golden")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text.lower()
    directives = {part.strip() for part in response.headers["content-security-policy"].split(";")}
    assert "object-src 'none'" in directives
    assert "frame-ancestors 'self'" in directives
