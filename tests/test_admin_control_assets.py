"""Legacy /admin control page — tenant-scoped asset previews (blob URL loader)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from fox3d.admin import render_admin
from fox3d.api import create_app
from fox3d.twin import ProductDigitalTwin

TENANT = "demo"
H = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def _seed_demo_gallery(platform, png: bytes) -> str:
    asset_id = platform.dam.put(
        tenant_id=TENANT, kind="render", name="beauty.png", data=png
    ).asset_id
    platform.queue.enqueue(
        {
            "jobId": "admin-gallery-job",
            "tenantId": TENANT,
            "jobType": "BLENDER_PREVIEW",
            "status": "completed",
            "outputAsset": asset_id,
            "renderEngine": "CYCLES",
            "samples": 32,
            "renderTimeSec": 0.9,
        }
    )
    twin = ProductDigitalTwin(tenantId=TENANT, sku="ADMIN-TWIN", previewAssetId=asset_id)
    platform.twins.create(twin)
    return asset_id


def test_admin_control_page_asset_markup(client: TestClient, platform) -> None:
    asset_id = _seed_demo_gallery(platform, b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    html = client.get("/admin").text
    assert asset_id in html
    assert f'data-asset-id="{asset_id}"' in html
    assert 'class="asset-open"' in html
    assert re.search(r'<img[^>]+src="/api/assets/', html) is None
    assert re.search(r'<img[^>]+src=\'/api/assets/', html) is None


def test_admin_control_asset_loader_script() -> None:
    from fox3d.platform import Platform
    from pathlib import Path

    plat = Platform(Path("/tmp/fox3d-admin-script-check"))
    html = render_admin(plat)
    assert "fetchAdminAssetBlob" in html
    assert "URL.createObjectURL" in html
    assert "'X-Tenant-Id': ADMIN_TENANT" in html
    assert "wireAdminAssetImages" in html
    assert "res.blob()" in html
    assert "document.getElementById('res-img').src = assetUrl" not in html


def test_admin_control_assets_api_accessible_with_tenant(client: TestClient, platform) -> None:
    payload = b"demo-preview-bytes"
    asset_id = _seed_demo_gallery(platform, payload)
    assert client.get(f"/api/assets/{asset_id}").status_code == 400
    got = client.get(f"/api/assets/{asset_id}", headers=H)
    assert got.status_code == 200
    assert got.content == payload


def test_admin_control_handle_generate_uses_blob_loader() -> None:
    from fox3d.platform import Platform
    from pathlib import Path

    html = render_admin(Platform(Path("/tmp/fox3d-admin-gen-check")))
    segment = html[html.index("function handleGenerate") : html.index("</script>", html.index("function handleGenerate"))]
    assert "fetchAdminAssetBlob(assetId)" in segment
    assert "'/api/assets/' + data.render.job.outputAsset" not in segment
