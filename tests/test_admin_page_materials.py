"""Admin plug-in page: /admin/materials."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.admin_pages import page_features
from fox3d.api import create_app

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def test_materials_plugin_claims_feature() -> None:
    assert page_features().get("materials") == "/admin/materials"


def test_materials_page_serves_html_and_shell(client: TestClient) -> None:
    res = client.get("/admin/materials")
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in res.text
    assert "/admin/pages/assets/materials.js" in res.text
    assert "/admin/pages/assets/materials.css" in res.text
    assert 'aria-label="工作台導覽"' not in res.text


@pytest.mark.parametrize("asset", ["materials.js", "materials.css"])
def test_materials_assets(client: TestClient, asset: str) -> None:
    res = client.get(f"/admin/pages/assets/{asset}")
    assert res.status_code == 200
    assert res.content


def test_materials_apis_with_tenant(client: TestClient) -> None:
    mats = client.get("/api/materials", headers=HEADERS)
    assert mats.status_code == 200
    body = mats.json()
    assert "sheets" in body and "lots" in body

    lot = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 1, "actor": "test"},
    )
    assert lot.status_code == 200

    rem = client.get("/api/remnants", headers=HEADERS)
    assert rem.status_code == 200
    snap = rem.json()
    assert "items" in snap


def test_remnant_reserve_round_trip(client: TestClient, platform) -> None:  # noqa: ANN001
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="admin-page-test",
        tenant_id=TENANT,
    )
    assert created
    rid = created[0]["remnantId"]
    res = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-test", "version": created[0]["version"]},
    )
    assert res.status_code == 200
    assert res.json().get("status") == "reserved"


def test_nesting_benchmark_api(client: TestClient) -> None:
    res = client.post("/api/nesting/benchmarks", headers=HEADERS, json={})
    assert res.status_code == 200
    data = res.json()
    assert "cases" in data
    assert data.get("liveMachineControl") is False


def test_confirm_dialog_resets_return_value_before_opening() -> None:
    # Esc keeps the previous returnValue; without a reset, Esc after an earlier "ok" would confirm.
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/materials.js").read_text(encoding="utf-8")
    assert js.index("dlg.returnValue = '';") < js.index("dlg.showModal();")
