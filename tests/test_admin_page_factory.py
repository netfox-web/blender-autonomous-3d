"""Tests for /admin/factory page and its factory + product-rd API workflows."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.admin_pages.factory import FEATURES
from fox3d.api import create_app

TENANT = {"X-Tenant-Id": "sonaqueen-home"}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def test_factory_module_declares_features(client: TestClient) -> None:
    assert FEATURES == {
        "factory": "/admin/factory",
        "product-rd": "/admin/factory#rd",
    }
    index = client.get("/api/admin/features").json()
    assert index["unclaimed"] == []
    by_id = {f["id"]: f for f in index["features"]}
    assert by_id["factory"]["kind"] == "page"
    assert by_id["factory"]["href"] == "/admin/factory"
    assert by_id["product-rd"]["kind"] == "page"
    assert by_id["product-rd"]["href"] == "/admin/factory#rd"


def test_factory_page_and_assets_load_shared_shell(client: TestClient) -> None:
    res = client.get("/admin/factory")
    assert res.status_code == 200
    assert "default-src 'self'" in res.headers.get("content-security-policy", "")
    html = res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in html
    assert "/admin/recipes/assets/fox3d-shell.js" in html
    assert "/admin/pages/assets/factory.css" in html
    assert "/admin/pages/assets/factory.js" in html
    assert 'id="rd"' in html
    assert "<style" not in html

    for asset in ("factory.css", "factory.js"):
        asset_res = client.get(f"/admin/pages/assets/{asset}")
        assert asset_res.status_code == 200
        assert asset_res.content


def test_factory_and_product_rd_apis_work_end_to_end(client: TestClient) -> None:
    # 1. Product types
    types_res = client.get("/api/factory/product-types", headers=TENANT)
    assert types_res.status_code == 200
    types = types_res.json()["items"]
    assert "WARDROBE" in types and "STORAGE_CABINET" in types

    # 2. Initial state requires X-Tenant-Id
    assert client.get("/api/pages/factory/state").status_code == 400
    st0 = client.get("/api/pages/factory/state", headers=TENANT)
    assert st0.status_code == 200
    assert len(st0.json()["productTypes"]) == len(types)

    # 3. Create space
    sp_res = client.post(
        "/api/factory/spaces",
        headers=TENANT,
        json={"width": 3600, "depth": 3000, "height": 2600},
    )
    assert sp_res.status_code == 200
    space = sp_res.json()
    assert space["spaceId"]
    assert space["width"] == 3600

    # 4. Run factory layout + quote
    run_res = client.post(
        "/api/factory/run",
        headers=TENANT,
        json={
            "space": {"width": 3600, "depth": 3000, "height": 2600},
            "wallName": "N",
            "productTypes": ["STORAGE_CABINET", "WARDROBE"],
            "text": "客廳 360cm 白木紋收納櫃",
            "render": False,
        },
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    quote_id = run_data["quote"]["quoteId"]
    assert run_data["gate"]["status"] == "WAITING_APPROVAL"
    assert run_data["gate"]["liveMachineControl"] is False
    cabinet_id = run_data["assembly"]["cabinets"][0]["cabinetId"]

    # 5. Read quote detail
    q_res = client.get(f"/api/factory/quotes/{quote_id}", headers=TENANT)
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert q_data["quoteId"] == quote_id
    assert q_data["estimatedCost"] > 0
    assert "SheetCost" in q_data["breakdown"]

    # 6. Approve quote
    ap_res = client.post(
        f"/api/factory/quotes/{quote_id}/approve",
        headers=TENANT,
        json={"actor": "sales-lead"},
    )
    assert ap_res.status_code == 200
    ap_data = ap_res.json()
    assert ap_data["gate"]["status"] == "APPROVED"
    assert ap_data["gate"]["actor"] == "sales-lead"
    assert ap_data["gate"]["liveMachineControl"] is False

    # 7. Revise cabinet
    rev_res = client.post(
        f"/api/factory/products/{cabinet_id}/revise",
        headers=TENANT,
        json={
            "width": 900,
            "height": 1800,
            "depth": 420,
            "doorCount": 2,
            "shelfCount": 4,
            "drawerCount": 0,
            "material": "WOOD_OAK",
        },
    )
    assert rev_res.status_code == 200
    rev_data = rev_res.json()
    assert rev_data["resizedFrom"] == cabinet_id
    assert rev_data["spec"]["revision"] == 2
    assert rev_data["lineage"]["parentProductId"] == cabinet_id

    # 8. Product R&D generate (#rd)
    rd_res = client.post(
        "/api/product-rd/generate",
        headers=TENANT,
        json={
            "text": "客廳 寬180cm 奶油風電視櫃 雙門 掃地機器人 預算 25000",
            "variantCount": 12,
        },
    )
    assert rd_res.status_code == 200
    rd_data = rd_res.json()
    assert rd_data["rdId"]
    assert rd_data["HUMAN_APPROVAL_REQUIRED"] is True
    assert rd_data["approval"]["status"] == "WAITING_APPROVAL"
    assert len(rd_data["top"]) > 0

    # 9. Verify state aggregation and tenant isolation
    st1 = client.get("/api/pages/factory/state", headers=TENANT).json()
    assert len(st1["spaces"]) >= 2
    assert len(st1["runs"]) == 1
    assert st1["quotes"][0]["gateStatus"] == "APPROVED"
    assert len(st1["products"]) >= 2
    assert len(st1["revisions"]) == 1

    other = client.get("/api/pages/factory/state", headers={"X-Tenant-Id": "other-tenant"}).json()
    assert other["spaces"] == []
    assert other["runs"] == []
    assert other["quotes"] == []
    assert other["products"] == []
    assert other["revisions"] == []
