"""Legacy /admin control page must load /api/assets with per-row X-Tenant-Id."""

from __future__ import annotations

import re
import socket
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from fox3d.api import create_app
from fox3d.platform import Platform
from fox3d.twin import ProductDigitalTwin

# 1×1 PNG
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _gpu(name: str, vram: float) -> dict[str, Any]:
    return {
        "blender": True,
        "blenderVersion": "mock-4.2",
        "cuda": True,
        "optix": True,
        "gpuCount": 1,
        "gpuName": name,
        "vramGb": vram,
        "driver": "mock",
        "gpus": [{"gpuIndex": 0, "name": name, "vramGb": vram, "freeVramGb": vram}],
    }


def _seed_multi_tenant_legacy_admin(platform: Platform) -> dict[str, str]:
    """Jobs and twins in demo + tenant-a with distinct preview assets."""
    platform.register_node(
        target_key="5080-1",
        name="RTX 5080 #1",
        detected=_gpu("NVIDIA GeForce RTX 5080", 16),
    )
    for tenant in ("demo", "tenant-a"):
        platform.tenants.ensure(tenant)

    demo_png = platform.dam.put(tenant_id="demo", kind="preview", name="job-demo.png", data=_TINY_PNG)
    ta_png = platform.dam.put(tenant_id="tenant-a", kind="preview", name="job-ta.png", data=_TINY_PNG)

    twin_demo_png = platform.dam.put(tenant_id="demo", kind="preview", name="twin-demo.png", data=_TINY_PNG)
    twin_ta_png = platform.dam.put(tenant_id="tenant-a", kind="preview", name="twin-ta.png", data=_TINY_PNG)

    platform.queue.enqueue(
        {
            "jobId": "legacy-job-demo",
            "tenantId": "demo",
            "jobType": "BLENDER_RENDER",
            "status": "succeeded",
            "outputAsset": demo_png.asset_id,
            "renderEngine": "CYCLES",
            "samples": 32,
            "renderTimeSec": 0.5,
        }
    )
    platform.queue.enqueue(
        {
            "jobId": "legacy-job-tenant-a",
            "tenantId": "tenant-a",
            "jobType": "BLENDER_RENDER",
            "status": "succeeded",
            "outputAsset": ta_png.asset_id,
            "renderEngine": "CYCLES",
            "samples": 16,
            "renderTimeSec": 1.1,
        }
    )

    platform.twins.create(
        ProductDigitalTwin(tenantId="demo", sku="LEGACY-DEMO", previewAssetId=twin_demo_png.asset_id),
        glb_bytes=b"glb-demo",
    )
    platform.twins.create(
        ProductDigitalTwin(tenantId="tenant-a", sku="LEGACY-TA", previewAssetId=twin_ta_png.asset_id),
        glb_bytes=b"glb-ta",
    )

    return {
        "demo_job_asset": demo_png.asset_id,
        "tenant_a_job_asset": ta_png.asset_id,
        "demo_twin_asset": twin_demo_png.asset_id,
        "tenant_a_twin_asset": twin_ta_png.asset_id,
    }


@pytest.fixture()
def legacy_admin_platform(tmp_path: Path) -> Platform:
    plat = Platform(root=tmp_path / "data", mock_blender=True)
    _seed_multi_tenant_legacy_admin(plat)
    return plat


@pytest.fixture()
def client(legacy_admin_platform: Platform) -> TestClient:  # noqa: ANN001 - overrides conftest
    return TestClient(create_app(legacy_admin_platform))


def _admin_html(client: TestClient) -> str:
    res = client.get("/admin")
    assert res.status_code == 200
    return res.text


def test_legacy_admin_html_has_no_direct_asset_urls(client: TestClient) -> None:
    html = _admin_html(client)
    assert 'src="/api/assets/' not in html
    assert 'href="/api/assets/' not in html
    assert 'class="thumb asset-img"' in html or "asset-img" in html
    assert "data-asset-id" in html
    assert 'data-tenant-id="demo"' in html
    assert 'data-tenant-id="tenant-a"' in html


def test_legacy_admin_html_pairs_assets_with_tenant(client: TestClient) -> None:
    html = _admin_html(client)
    pairs = re.findall(r'data-asset-id="([^"]+)"[^>]*data-tenant-id="([^"]+)"', html)
    by_asset = {aid: tid for aid, tid in pairs}
    assert by_asset  # at least job + gallery + twin thumbnails

    ta_assets = {aid for aid, tid in by_asset.items() if tid == "tenant-a"}
    demo_assets = {aid for aid, tid in by_asset.items() if tid == "demo"}
    assert ta_assets and demo_assets


def test_legacy_admin_js_uses_per_element_tenant_for_assets() -> None:
    admin_py = Path(__file__).resolve().parents[1] / "src" / "fox3d" / "admin.py"
    src = admin_py.read_text(encoding="utf-8")
    assert "URL.createObjectURL" in src
    assert "data-tenant-id" in src
    assert "getAttribute('data-tenant-id')" in src
    assert "'X-Tenant-Id': tenant" in src
    assert "const ADMIN_TENANT = 'demo'" not in src
    assert "hydrateAssetImages" in src
    assert "wireAssetOpenLinks" in src
    assert "window.bindResultAsset" in src
    assert "document.getElementById('res-img').src = assetUrl" not in src


def test_legacy_admin_asset_endpoint_still_requires_tenant(client: TestClient) -> None:
    assert client.get("/api/assets/any-id").status_code == 400


def test_legacy_admin_cross_tenant_asset_fetch_rejected(client: TestClient, legacy_admin_platform: Platform) -> None:
    asset_id = legacy_admin_platform.dam.put(
        tenant_id="tenant-a", kind="preview", name="iso.png", data=_TINY_PNG
    ).asset_id
    url = f"/api/assets/{asset_id}"
    assert client.get(url, headers={"X-Tenant-Id": "demo"}).status_code == 404
    assert client.get(url, headers={"X-Tenant-Id": "tenant-a"}).status_code == 200


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _chromium_usable() -> bool:
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def legacy_admin_browser_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[dict[str, Any], None, None]:
    data_root = tmp_path_factory.mktemp("legacy-admin-browser")
    platform = Platform(root=data_root / "data", mock_blender=True)
    ids = _seed_multi_tenant_legacy_admin(platform)
    port = _free_port()
    config = uvicorn.Config(create_app(platform), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="legacy-admin-uvicorn", daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=1.0).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        pytest.fail("legacy admin uvicorn did not become ready")
    try:
        yield {"base_url": base, "platform": platform, "ids": ids}
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.browser
def test_legacy_admin_page_hydrates_thumbnails_with_correct_tenant_headers(
    legacy_admin_browser_server: dict[str, Any],
) -> None:
    if not _chromium_usable():
        pytest.skip("Chromium not available")

    base = legacy_admin_browser_server["base_url"]
    ids = legacy_admin_browser_server["ids"]
    asset_tenants: dict[str, set[str]] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        def on_request(request) -> None:  # noqa: ANN001
            if "/api/assets/" not in request.url:
                return
            asset_id = request.url.rsplit("/", 1)[-1].split("?", 1)[0]
            tenant = (request.headers.get("x-tenant-id") or request.headers.get("X-Tenant-Id") or "").strip()
            asset_tenants.setdefault(asset_id, set()).add(tenant)

        page.on("request", on_request)
        response = page.goto(f"{base}/admin", wait_until="domcontentloaded")
        assert response is not None and response.status == 200

        page.wait_for_function(
            """() => {
              const imgs = Array.from(document.querySelectorAll('img.asset-img[data-asset-id]'));
              if (!imgs.length) return false;
              const loaded = imgs.filter((img) => img.src && img.src.startsWith('blob:'));
              const failed = imgs.filter((img) => img.alt === '載入失敗');
              return loaded.length + failed.length >= imgs.length;
            }""",
            timeout=20_000,
        )

        thumbs = page.locator("img.asset-img[data-asset-id]")
        assert thumbs.count() >= 4
        blob_count = page.evaluate(
            "() => document.querySelectorAll('img.asset-img[src^=\"blob:\"]').length"
        )
        assert blob_count >= 4

        opened = page.evaluate(
            """() => {
              const anchor = document.querySelector(
                'a.asset-open[data-tenant-id="tenant-a"]'
              );
              if (!anchor) return false;
              anchor.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
              return true;
            }"""
        )
        assert opened is True

        for asset_key in ("tenant_a_job_asset", "demo_job_asset", "tenant_a_twin_asset", "demo_twin_asset"):
            asset_id = ids[asset_key]
            expected = "tenant-a" if "tenant_a" in asset_key else "demo"
            assert asset_id in asset_tenants, f"no fetch for {asset_id}"
            assert asset_tenants[asset_id] == {expected}, asset_tenants[asset_id]

        context.close()
        browser.close()


@pytest.mark.browser
def test_legacy_admin_wrong_tenant_thumbnail_shows_failure(legacy_admin_browser_server: dict[str, Any]) -> None:
    """Simulate stale markup: wrong data-tenant-id must not hydrate as success."""
    if not _chromium_usable():
        pytest.skip("Chromium not available")

    base = legacy_admin_browser_server["base_url"]
    ids = legacy_admin_browser_server["ids"]
    ta_asset = ids["tenant_a_job_asset"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"{base}/admin", wait_until="domcontentloaded")
        state = page.evaluate(
            """async (assetId) => {
              const img = document.querySelector(
                `img.asset-img[data-asset-id="${assetId}"][data-tenant-id="tenant-a"]`
              );
              if (!img) throw new Error('missing img');
              img.setAttribute('data-tenant-id', 'demo');
              const tenantId = img.getAttribute('data-tenant-id') || 'demo';
              try {
                const res = await fetch('/api/assets/' + encodeURIComponent(assetId), {
                  headers: { 'X-Tenant-Id': tenantId },
                });
                if (!res.ok) throw new Error('HTTP ' + res.status);
                img.src = URL.createObjectURL(await res.blob());
              } catch (err) {
                img.alt = '載入失敗';
                img.removeAttribute('src');
              }
              return { alt: img.alt || '', src: img.getAttribute('src') || '' };
            }""",
            ta_asset,
        )
        assert state["alt"] == "載入失敗"
        assert not state["src"].startswith("blob:")
        browser.close()


@pytest.mark.browser
def test_parametric_result_loads_and_clears_failed_preview(legacy_admin_browser_server: dict[str, Any]) -> None:
    if not _chromium_usable():
        pytest.skip("Chromium not available")

    base = legacy_admin_browser_server["base_url"]
    asset_id = legacy_admin_browser_server["ids"]["tenant_a_job_asset"]
    requests: list[tuple[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", lambda req: requests.append((req.url, req.headers.get("x-tenant-id", ""))))
        page.route("**/api/parametric/products", lambda route: route.fulfill(json={
            "render": {"job": {"outputAsset": asset_id, "tenantId": "tenant-a"}}
        }))
        page.goto(f"{base}/admin", wait_until="networkidle")
        page.locator("#gen-btn").click()
        page.wait_for_function("document.querySelector('#res-img').src.startsWith('blob:')")
        assert page.locator("#result-box").is_visible()
        assert any(url.endswith('/api/assets/' + asset_id) and tenant == 'tenant-a' for url, tenant in requests)
        page.evaluate("assetId => window.bindResultAsset(assetId, 'demo')", asset_id)
        page.wait_for_function("document.querySelector('#res-img').alt === '載入失敗'")
        assert page.locator("#res-img").get_attribute("src") is None
        browser.close()
