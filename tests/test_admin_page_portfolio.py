"""Admin page /admin/portfolio."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001
    return TestClient(create_app(platform))


def test_portfolio_page_and_assets(client: TestClient) -> None:
    page = client.get("/admin/portfolio")
    assert page.status_code == 200
    assert "/admin/pages/assets/portfolio.js" in page.text
    assert "需求為估計值" in page.text
    for name in ("portfolio.js", "portfolio.css"):
        res = client.get(f"/admin/pages/assets/{name}")
        assert res.status_code == 200 and res.content


def test_portfolio_feature_index(client: TestClient) -> None:
    index = client.get("/api/admin/features").json()
    pf = next(f for f in index["features"] if f["id"] == "portfolio")
    assert pf["kind"] == "page"
    assert pf["href"] == "/admin/portfolio"
    assert "/api/portfolio" in pf["prefixes"]
    assert index["unclaimed"] == []