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
    assert "'X-Tenant-Id': tenant" in html
    assert "data-tenant-id" in html
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


def _seed_tenant_gallery(platform, tenant: str, png: bytes, *, job_id: str) -> str:
    asset_id = platform.dam.put(
        tenant_id=tenant, kind="render", name="beauty.png", data=png
    ).asset_id
    platform.queue.enqueue(
        {
            "jobId": job_id,
            "tenantId": tenant,
            "jobType": "BLENDER_PREVIEW",
            "status": "completed",
            "outputAsset": asset_id,
        }
    )
    twin = ProductDigitalTwin(tenantId=tenant, sku=f"TWIN-{tenant}", previewAssetId=asset_id)
    platform.twins.create(twin)
    return asset_id


def test_admin_control_page_lists_tenant_a_with_matching_tenant_header(
    client: TestClient, platform
) -> None:
    payload = b"tenant-a-render-bytes"
    asset_id = _seed_tenant_gallery(platform, "tenant-a", payload, job_id="admin-tenant-a-job")
    html = client.get("/admin").text
    assert asset_id in html
    assert f'data-tenant-id="tenant-a"' in html
    assert client.get(f"/api/assets/{asset_id}", headers={"X-Tenant-Id": "demo"}).status_code == 404
    got = client.get(f"/api/assets/{asset_id}", headers={"X-Tenant-Id": "tenant-a"})
    assert got.status_code == 200
    assert got.content == payload


def test_admin_gallery_renders_without_output_metadata(client: TestClient, platform) -> None:
    png = b"\x89PNG\r\n\x1a\n"
    _seed_tenant_gallery(platform, "tenant-b", png, job_id="sparse-metadata-job")
    res = client.get("/admin")
    assert res.status_code == 200
    assert "sparse-metadata-job" in res.text
    assert "CYCLES" in res.text


def test_admin_control_handle_generate_uses_blob_loader() -> None:
    from fox3d.platform import Platform
    from pathlib import Path

    html = render_admin(Platform(Path("/tmp/fox3d-admin-gen-check")))
    segment = html[html.index("function handleGenerate") : html.index("</script>", html.index("function handleGenerate"))]
    assert "bindResultAsset(" in segment
    assert "data.render.job.tenantId || payload.tenantId" in segment
    assert "'/api/assets/' + data.render.job.outputAsset" not in segment
