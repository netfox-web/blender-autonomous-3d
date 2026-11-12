"""Browser integration: legacy /admin loads tenant-scoped gallery thumbnails via blob URLs."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from fox3d.twin import ProductDigitalTwin
from tests.browser.conftest import TENANT

pytestmark = pytest.mark.browser

TENANT_A = "tenant-a"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"


def _seed_gallery(platform, tenant: str) -> str:
    asset_id = platform.dam.put(
        tenant_id=tenant, kind="render", name="beauty.png", data=PNG
    ).asset_id
    platform.queue.enqueue(
        {
            "jobId": f"browser-{tenant}-job",
            "tenantId": tenant,
            "jobType": "BLENDER_PREVIEW",
            "status": "completed",
            "outputAsset": asset_id,
        }
    )
    platform.twins.create(
        ProductDigitalTwin(tenantId=tenant, sku=f"BROWSER-{tenant}", previewAssetId=asset_id)
    )
    return asset_id


def test_admin_gallery_thumbs_load_for_non_demo_tenant(admin_server, admin_page) -> None:  # noqa: ANN001
    platform = admin_server["platform"]
    base = admin_server["base_url"]
    asset_id = _seed_gallery(platform, TENANT_A)
    _seed_gallery(platform, TENANT)

    page = admin_page
    page.goto(f"{base}/admin", wait_until="domcontentloaded")
    page.click("button.tab-btn:has-text('3D 渲染成品相簿')")
    thumb = page.locator(f'img.gallery-thumb[data-asset-id="{asset_id}"][data-tenant-id="{TENANT_A}"]')
    expect(thumb).to_be_visible(timeout=15_000)
    page.wait_for_function(
        f"""() => {{
          const img = document.querySelector('img.gallery-thumb[data-asset-id="{asset_id}"][data-tenant-id="{TENANT_A}"]');
          return img && img.src && img.src.startsWith('blob:');
        }}""",
        timeout=15_000,
    )


def test_admin_twin_preview_loads_with_tenant_header(admin_server, admin_page) -> None:  # noqa: ANN001
    platform = admin_server["platform"]
    base = admin_server["base_url"]
    asset_id = _seed_gallery(platform, TENANT_A)

    page = admin_page
    page.goto(f"{base}/admin", wait_until="domcontentloaded")
    page.click("button.tab-btn:has-text('數位孿生與規格')")
    preview = page.locator(f'img.preview[data-asset-id="{asset_id}"][data-tenant-id="{TENANT_A}"]')
    expect(preview).to_be_visible(timeout=15_000)
    page.wait_for_function(
        f"""() => {{
          const img = document.querySelector('img.preview[data-asset-id="{asset_id}"][data-tenant-id="{TENANT_A}"]');
          return img && img.src && img.src.startsWith('blob:');
        }}""",
        timeout=15_000,
    )
