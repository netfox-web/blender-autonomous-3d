"""Legacy /admin control page must not load /api/assets without X-Tenant-Id."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app


@pytest.fixture()
def client(platform) -> TestClient:  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def _admin_html(client: TestClient) -> str:
    res = client.get("/admin")
    assert res.status_code == 200
    return res.text


def test_legacy_admin_html_has_no_direct_asset_urls(client: TestClient) -> None:
    html = _admin_html(client)
    assert 'src="/api/assets/' not in html
    assert 'href="/api/assets/' not in html
    assert "img.asset-img[data-asset-id]" in html or 'class="thumb asset-img"' in html
    assert "data-asset-id" in html


def test_legacy_admin_js_fetches_assets_with_tenant_header() -> None:
    admin_py = Path(__file__).resolve().parents[1] / "src" / "fox3d" / "admin.py"
    src = admin_py.read_text(encoding="utf-8")
    assert "URL.createObjectURL" in src
    assert "'X-Tenant-Id': ADMIN_TENANT" in src
    assert "res.blob()" in src
    assert "hydrateAssetImages" in src
    assert "wireAssetOpenLinks" in src
    assert "window.bindResultAsset" in src
    assert "document.getElementById('res-img').src = assetUrl" not in src


def test_legacy_admin_asset_endpoint_still_requires_tenant(client: TestClient) -> None:
    assert client.get("/api/assets/any-id").status_code == 400
