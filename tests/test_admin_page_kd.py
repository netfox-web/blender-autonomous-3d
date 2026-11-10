"""Admin page /admin/kd — KD catalog and structure generation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.features import resolved_features

TENANT = "sonaqueen-home"
HDR = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def test_kd_plugin_claims_features() -> None:
    kd = next(f for f in resolved_features() if f["id"] == "kd")
    structures = next(f for f in resolved_features() if f["id"] == "structures")
    assert kd["kind"] == "page" and kd["href"] == "/admin/kd"
    assert structures["kind"] == "page" and structures["href"] == "/admin/kd#structures"
    assert "/admin/kd" in kd["prefixes"]


def test_kd_page_loads_shared_shell(client: TestClient) -> None:
    res = client.get("/admin/kd")
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in res.text
    assert "/admin/pages/assets/kd.js" in res.text
    assert "/admin/pages/assets/kd.css" in res.text
    assert 'aria-label="工作台導覽"' not in res.text


@pytest.mark.parametrize("asset", ["kd.js", "kd.css"])
def test_kd_page_assets(client: TestClient, asset: str) -> None:
    res = client.get(f"/admin/pages/assets/{asset}")
    assert res.status_code == 200
    assert res.content


def test_kd_get_apis(client: TestClient) -> None:
    types = client.get("/api/kd/product-types", headers=HDR)
    assert types.status_code == 200
    assert types.json()["items"]

    ready = client.get("/api/kd/readiness", headers=HDR)
    assert ready.status_code == 200
    body = ready.json()
    assert "productionReadyScope" in body


def test_kd_post_apis(client: TestClient) -> None:
    sku = client.post("/api/kd/skus", headers=HDR, json={"kind": "BEDSIDE_CABINET", "render": False})
    assert sku.status_code == 200
    assert sku.json().get("spec")

    catalog = client.post("/api/kd/catalog", headers=HDR, json={"count": 4, "render": False})
    assert catalog.status_code == 200
    assert catalog.json().get("catalog")

    cand = client.post("/api/kd/candidates", headers=HDR, json={"count": 2})
    assert cand.status_code == 200
    assert cand.json().get("candidates")

    retail = client.post(
        "/api/retail/fixtures",
        headers=HDR,
        json={"family": "COUNTER_DISPLAY", "facing": 2, "render": False},
    )
    assert retail.status_code == 200
    assert retail.json().get("fixtureId") or retail.json().get("spec")

    pack = client.post(
        "/api/packaging/structures",
        headers=HDR,
        json={"family": "RSC_CARTON", "productDims": {"width": 120, "height": 80, "depth": 40}, "render": False},
    )
    assert pack.status_code == 200

    acr = client.post(
        "/api/acrylic/products",
        headers=HDR,
        json={"kind": "MENU_STAND", "sheetSku": "ACR_CLEAR_5", "render": False},
    )
    assert acr.status_code == 200
