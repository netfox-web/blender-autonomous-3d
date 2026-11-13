"""Legacy /admin control page must load /api/assets with per-row X-Tenant-Id."""

from __future__ import annotations

import functools
import os
import re
import socket
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

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



@pytest.mark.parametrize(
    ("missing_field", "expected"),
    [
        ("renderEngine", "引擎: CYCLES (16 採樣)"),
        ("samples", "引擎: BLENDER_EEVEE (32 採樣)"),
        ("renderTimeSec", "耗時: 0.8 秒"),
    ],
)
def test_legacy_gallery_renders_missing_metadata_without_output(
    client: TestClient, legacy_admin_platform: Platform, missing_field: str, expected: str
) -> None:
    job = {
        "jobId": "missing-metadata",
        "outputAsset": "gallery-asset",
        "renderEngine": "BLENDER_EEVEE",
        "samples": 16,
        "renderTimeSec": 1.5,
    }
    del job[missing_field]
    legacy_admin_platform.queue.enqueue(job)

    html = _admin_html(client)
    card = html.split('任務: missing-metadata', 1)[1].split('</div>\n        </div>', 1)[0]
    assert expected in card
    assert 'data-asset-id="gallery-asset"' in html


def test_legacy_gallery_uses_output_metadata_when_top_level_missing(
    client: TestClient, legacy_admin_platform: Platform
) -> None:
    legacy_admin_platform.queue.enqueue({
        "jobId": "output-metadata",
        "outputAsset": "gallery-asset",
        "output": {"engine": "EEVEE", "samples": 8, "renderTimeSec": 2.5},
    })

    html = _admin_html(client)
    card = html.split('任務: output-metadata', 1)[1].split('</div>\n        </div>', 1)[0]
    assert "引擎: EEVEE (8 採樣)" in card
    assert "耗時: 2.5 秒" in card


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
    assert "window.fetchAdminAssetBlob" in src
    assert "document.getElementById('res-img').src = assetUrl" not in src


def test_generate_does_not_reference_asset_loader_private_default(client: TestClient) -> None:
    html = _admin_html(client)
    generate = html.split("function handleGenerate(e)", 1)[1].split("function ", 1)[0]
    assert "DEFAULT_TENANT" not in generate.replace("window.__FOX3D_DEFAULT_TENANT", "")
    assert "window.__FOX3D_DEFAULT_TENANT" in generate


def test_legacy_admin_asset_endpoint_still_requires_tenant(client: TestClient) -> None:
    assert client.get("/api/assets/any-id").status_code == 400


def test_legacy_admin_cross_tenant_asset_fetch_rejected(client: TestClient, legacy_admin_platform: Platform) -> None:
    asset_id = legacy_admin_platform.dam.put(
        tenant_id="tenant-a", kind="preview", name="iso.png", data=_TINY_PNG
    ).asset_id
    url = f"/api/assets/{asset_id}"
    assert client.get(url, headers={"X-Tenant-Id": "demo"}).status_code == 404
    assert client.get(url, headers={"X-Tenant-Id": "tenant-a"}).status_code == 200


def test_legacy_admin_asset_response_is_not_cacheable_across_tenants(
    client: TestClient, legacy_admin_platform: Platform
) -> None:
    """Issue #292: the URL alone does not identify the tenant, so caches must not reuse it."""
    asset_id = legacy_admin_platform.dam.put(
        tenant_id="tenant-a", kind="preview", name="cache.png", data=_TINY_PNG
    ).asset_id
    res = client.get(f"/api/assets/{asset_id}", headers={"X-Tenant-Id": "tenant-a"})
    assert res.status_code == 200
    cache_control = {part.strip() for part in res.headers["cache-control"].lower().split(",")}
    assert {"no-store", "private"} <= cache_control
    assert "x-tenant-id" in {part.strip() for part in res.headers["vary"].lower().split(",")}
    assert res.headers["x-content-type-options"] == "nosniff"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@functools.cache
def _chromium_usable() -> bool:
    require = os.environ.get("FOX3D_REQUIRE_LEGACY_BROWSER") == "1"
    if os.environ.get("FOX3D_SKIP_BROWSER") == "1" and not require:
        return False
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception as exc:
        if require:
            pytest.fail(f"Chromium is required for legacy admin browser tests: {exc}")
        return False


class _AssetFetchLog:
    """Record /api/assets fetches so a failed wait reports asset id, tenant and status."""

    def __init__(self, page: Any) -> None:
        self.entries: list[str] = []
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_failed)

    @staticmethod
    def _asset_id(url: str) -> str:
        return url.rsplit("/", 1)[-1].split("?", 1)[0]

    def _on_response(self, response: Any) -> None:
        if "/api/assets/" not in response.url:
            return
        tenant = response.request.headers.get("x-tenant-id", "")
        self.entries.append(f"asset={self._asset_id(response.url)} tenant={tenant!r} status={response.status}")

    def _on_failed(self, request: Any) -> None:
        if "/api/assets/" not in request.url:
            return
        tenant = request.headers.get("x-tenant-id", "")
        self.entries.append(f"asset={self._asset_id(request.url)} tenant={tenant!r} failed={request.failure}")

    def wait(self, page: Any, expression: str, *, arg: Any = None, timeout: float = 20_000) -> None:
        try:
            page.wait_for_function(expression, arg=arg, timeout=timeout)
        except Exception as exc:
            raise AssertionError(f"{exc}\nasset fetches: {self.describe()}") from exc

    def describe(self) -> str:
        return "; ".join(self.entries) or "(none)"

    def wait_all_thumbnails_settled(self, page: Any, *, timeout: float = 20_000) -> None:
        """Wait until every legacy thumbnail has blob src or 載入失敗 (hydration finished)."""
        self.wait(
            page,
            """() => {
              const imgs = Array.from(document.querySelectorAll('img.asset-img[data-asset-id]'));
              if (!imgs.length) return false;
              const loaded = imgs.filter((img) => img.src && img.src.startsWith('blob:'));
              const failed = imgs.filter((img) => img.alt === '載入失敗');
              return loaded.length + failed.length >= imgs.length;
            }""",
            timeout=timeout,
        )


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
        fetch_log = _AssetFetchLog(page)
        response = page.goto(f"{base}/admin", wait_until="domcontentloaded")
        assert response is not None and response.status == 200

        fetch_log.wait(
            page,
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
        assert blob_count >= 4, fetch_log.describe()

        # Use a real user click and observe the new page, rather than merely
        # dispatching an event (which can pass even if window.open is broken).
        page.get_by_role("button", name=re.compile("算力節點與工作佇列")).click()
        anchor = page.locator(
            f'#tab-system a.asset-open[data-asset-id="{ids["tenant_a_job_asset"]}"]'
            '[data-tenant-id="tenant-a"]'
        ).first
        # A blob URL alone does not prove that the browser can display the image.
        thumb = anchor.locator("img")
        assert thumb.evaluate("async img => { await img.decode(); return img.naturalWidth > 0; }")
        with page.expect_popup() as popup_info:
            anchor.click()
        popup = popup_info.value
        popup.wait_for_url("**/admin/asset-viewer?*")
        popup.wait_for_function("() => document.querySelector('#asset').naturalWidth > 0")
        assert popup.evaluate("() => window.opener === null")

        for asset_key in ("tenant_a_job_asset", "demo_job_asset", "tenant_a_twin_asset", "demo_twin_asset"):
            asset_id = ids[asset_key]
            expected = "tenant-a" if "tenant_a" in asset_key else "demo"
            assert asset_id in asset_tenants, f"no fetch for {asset_id}: {fetch_log.describe()}"
            assert asset_tenants[asset_id] == {expected}, fetch_log.describe()

        context.close()
        browser.close()


@pytest.mark.browser
def test_legacy_admin_failed_asset_response_shows_failure(legacy_admin_browser_server: dict[str, Any]) -> None:
    """A 400 response must leave the actual thumbnail in a failed state."""
    if not _chromium_usable():
        pytest.skip("Chromium not available")

    base = legacy_admin_browser_server["base_url"]
    asset_id = legacy_admin_browser_server["ids"]["tenant_a_job_asset"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route(f"**/api/assets/{asset_id}", lambda route: route.fulfill(status=400, body="missing tenant"))
        fetch_log = _AssetFetchLog(page)
        page.goto(f"{base}/admin", wait_until="domcontentloaded")
        img = page.locator(f'img.asset-img[data-asset-id="{asset_id}"]').first
        img.wait_for(state="attached")
        fetch_log.wait(
            page,
            "assetId => document.querySelector(`img.asset-img[data-asset-id=\"${assetId}\"]`).alt === '載入失敗'",
            arg=asset_id,
        )
        assert not img.get_attribute("src"), fetch_log.describe()
        browser.close()


@pytest.mark.browser
def test_legacy_admin_wrong_tenant_thumbnail_shows_failure(
    legacy_admin_browser_server: dict[str, Any],
) -> None:
    """Issue #293: wrong per-thumbnail tenant during initial hydration must fail without a preview.

    The served HTML marks the target asset with a cross-tenant id before ``hydrateAssetImages`` runs
    so the test asserts DOM failure state and a 404 without calling fetch helpers itself.
    """
    if not _chromium_usable():
        pytest.skip("Chromium not available")

    base = legacy_admin_browser_server["base_url"]
    asset_id = legacy_admin_browser_server["ids"]["tenant_a_job_asset"]
    wrong_tenant_attr = f'data-asset-id="{asset_id}" data-tenant-id="demo"'
    correct_tenant_attr = f'data-asset-id="{asset_id}" data-tenant-id="tenant-a"'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        fetch_log = _AssetFetchLog(page)

        def serve_admin_with_wrong_tenant(route: Any) -> None:
            response = route.fetch()
            html = response.text()
            patched, count = re.subn(re.escape(correct_tenant_attr), wrong_tenant_attr, html)
            assert count >= 1, "expected at least one tenant-a thumbnail for target asset in /admin HTML"
            route.fulfill(response=response, body=patched)

        page.route("**/admin", serve_admin_with_wrong_tenant)
        page.goto(f"{base}/admin", wait_until="domcontentloaded")
        img = page.locator(f'img.asset-img[data-asset-id="{asset_id}"]').first
        img.wait_for(state="attached")
        fetch_log.wait(
            page,
            'assetId => document.querySelector(`img.asset-img[data-asset-id="${assetId}"]`).alt === "載入失敗"',
            arg=asset_id,
        )
        detail = fetch_log.describe()
        assert not img.get_attribute("src"), detail
        assert img.get_attribute("alt") == "載入失敗", detail
        assert img.evaluate("el => el.naturalWidth") == 0, detail
        assert f"asset={asset_id} tenant='demo' status=404" in fetch_log.entries, detail
        browser.close()


@pytest.mark.browser
def test_legacy_admin_blob_url_lifecycle(legacy_admin_browser_server: dict[str, Any]) -> None:
    if not _chromium_usable():
        pytest.skip("Chromium not available")
    base = legacy_admin_browser_server["base_url"]
    ids = legacy_admin_browser_server["ids"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script("""(() => {
          window.revokedUrls = [];
          window.openedUrls = [];
          const revoke = URL.revokeObjectURL.bind(URL);
          URL.revokeObjectURL = (url) => { window.revokedUrls.push(url); revoke(url); };
          window.open = (url) => { window.openedUrls.push(url); };
        })();""")
        page.goto(f"{base}/admin")
        page.wait_for_function("() => [...document.querySelectorAll('img.asset-img')].every(i => i.src.startsWith('blob:') || i.alt === '載入失敗')")
        first = ids["tenant_a_job_asset"]
        second = ids["demo_job_asset"]
        page.evaluate("([a, b]) => { bindResultAsset(a, 'tenant-a'); bindResultAsset(b, 'demo'); }", [first, second])
        page.wait_for_function("() => document.getElementById('res-img').src.startsWith('blob:')")
        url = page.locator("#res-img").get_attribute("src")
        assert page.evaluate("url => fetch(url).then(r => r.ok)", url)
        page.locator("#res-link").evaluate("a => a.click()")
        page.wait_for_function("() => window.openedUrls.length === 1")
        assert page.evaluate("() => window.openedUrls[0].startsWith('/admin/asset-viewer?')")
        # The viewer fetches its own copy, so the preview URL can be reclaimed.
        page.evaluate("a => bindResultAsset(a, 'tenant-a')", first)
        page.wait_for_function("url => document.getElementById('res-img').src.startsWith('blob:') && document.getElementById('res-img').src !== url", arg=url)
        page.evaluate("url => document.querySelectorAll('img').forEach(i => { if (i.src === url) i.remove(); })", url)
        page.wait_for_function("url => window.revokedUrls.includes(url)", arg=url)
        assert not page.evaluate("url => fetch(url).then(() => true, () => false)", url)

        # An unopened URL remains eligible for cleanup after its final image disappears.
        current = page.locator("#res-img").get_attribute("src")
        page.evaluate("url => { const img = document.createElement('img'); img.id = 'shared-test'; img.src = url; document.body.appendChild(img); }", current)
        page.evaluate("url => document.querySelectorAll('img:not(#shared-test)').forEach(i => { if (i.src === url) i.remove(); })", current)
        page.evaluate("() => new Promise(resolve => setTimeout(resolve, 100))")
        assert page.evaluate("url => fetch(url).then(r => r.ok)", current)
        page.locator("#shared-test").evaluate("img => img.remove()")
        page.wait_for_function("url => window.revokedUrls.includes(url)", arg=current)
        assert not page.evaluate("url => fetch(url).then(() => true, () => false)", current)
        page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        browser.close()


@pytest.mark.browser
def test_result_popup_remains_loadable_after_preview_switch(legacy_admin_browser_server: dict[str, Any]) -> None:
    """A real popup can reload its image after the opener releases the preview."""
    if not _chromium_usable():
        pytest.skip("Chromium not available")

    base = legacy_admin_browser_server["base_url"]
    ids = legacy_admin_browser_server["ids"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.add_init_script("""(() => {
          window.revokedUrls = [];
          const revoke = URL.revokeObjectURL.bind(URL);
          URL.revokeObjectURL = url => { window.revokedUrls.push(url); revoke(url); };
        })();""")
        page.route("**/api/parametric/products", lambda route: route.fulfill(json={
            "render": {"job": {"outputAsset": ids["tenant_a_job_asset"], "tenantId": "tenant-a"}}
        }))
        page.goto(f"{base}/admin", wait_until="networkidle")
        page.locator("#gen-btn").click()
        page.wait_for_function("document.querySelector('#res-img').src.startsWith('blob:')")
        url = page.locator("#res-img").get_attribute("src")
        assert url is not None
        with page.expect_popup() as popup_info:
            page.locator("#res-link").click()
        popup = popup_info.value
        popup.wait_for_url("**/admin/asset-viewer?*")
        parsed_url = urlparse(popup.url)
        assert parsed_url.path == "/admin/asset-viewer"
        assert parse_qs(parsed_url.query) == {"asset": [ids["tenant_a_job_asset"]], "tenant": ["tenant-a"]}
        popup_image = popup.locator("#asset")
        popup.wait_for_function("() => document.querySelector('#asset').src.startsWith('blob:') && "
                                "document.querySelector('#asset').naturalWidth > 0")
        assert popup_image.evaluate("async img => { await img.decode(); return img.naturalWidth > 0; }")

        page.evaluate("asset => bindResultAsset(asset, 'demo')", ids["demo_job_asset"])
        page.wait_for_function(
            "url => document.querySelector('#res-img').src.startsWith('blob:') && "
            "document.querySelector('#res-img').src !== url", arg=url
        )
        # The viewer must not depend on the opener's object URL.
        page.evaluate("url => URL.revokeObjectURL(url)", url)
        assert page.evaluate("url => window.revokedUrls.includes(url)", url)
        assert not page.evaluate("url => fetch(url).then(() => true, () => false)", url)
        assert popup_image.evaluate("async img => { await img.decode(); return img.naturalWidth > 0; }")
        popup.reload()
        assert urlparse(popup.url) == parsed_url
        popup.wait_for_function("() => document.querySelector('#asset').src.startsWith('blob:') && "
                                "document.querySelector('#asset').naturalWidth > 0")
        assert popup_image.evaluate("async img => { await img.decode(); return img.naturalWidth > 0; }")
        context.close()
        browser.close()


@pytest.mark.browser
def test_open_popup_keeps_result_blob_after_asset_change(legacy_admin_browser_server: dict[str, Any]) -> None:
    if not _chromium_usable():
        pytest.skip("Chromium not available")
    base = legacy_admin_browser_server["base_url"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"{base}/admin", wait_until="networkidle")
        first, second = "popup-result-first", "popup-result-second"
        page.context.route("**/api/assets/popup-result-*", lambda route: route.fulfill(content_type="image/png", body=_TINY_PNG))
        page.evaluate("asset => bindResultAsset(asset, 'demo')", first)
        page.wait_for_function("document.querySelector('#res-img').src.startsWith('blob:')")
        url = page.locator("#res-img").get_attribute("src")
        with page.expect_popup() as popup_info:
            page.locator("#res-link").evaluate("a => a.click()")
        popup = popup_info.value
        popup.wait_for_load_state()
        page.evaluate("asset => bindResultAsset(asset, 'demo')", second)
        page.wait_for_function("url => document.querySelector('#res-img').src.startsWith('blob:') && document.querySelector('#res-img').src !== url", arg=url)
        popup.wait_for_function("() => document.querySelector('#asset').naturalWidth > 0")
        assert popup.evaluate("window.opener === null")
        assert popup.evaluate("document.querySelector('#asset').src !== ''")
        assert popup.evaluate("() => document.querySelector('#asset').decode().then(() => true)")
        browser.close()


@pytest.mark.browser
def test_many_viewers_release_blobs_on_close(legacy_admin_browser_server: dict[str, Any]) -> None:
    if not _chromium_usable():
        pytest.skip("Chromium not available")
    base = legacy_admin_browser_server["base_url"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        events: list[tuple[str, str]] = []
        context.expose_binding("recordBlob", lambda _source, action, url: events.append((action, url)))
        context.add_init_script("""(() => {
          const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
          URL.createObjectURL = blob => { const url = create(blob); window.recordBlob('create', url); return url; };
          URL.revokeObjectURL = url => { window.recordBlob('revoke', url); revoke(url); };
        })();""")
        context.route("**/api/assets/stress-*", lambda route: route.fulfill(content_type="image/png", body=_TINY_PNG))
        page = context.new_page()
        page.goto(f"{base}/admin", wait_until="networkidle")
        viewers = []
        urls = []
        for index in range(12):
            page.evaluate("asset => bindResultAsset(asset, 'tenant-a')", f"stress-{index}")
            page.wait_for_function("document.querySelector('#res-img').src.startsWith('blob:')")
            with page.expect_popup() as popup_info:
                page.locator("#res-link").evaluate("a => a.click()")
            popup = popup_info.value
            popup.wait_for_function("() => document.querySelector('#asset').naturalWidth > 0")
            assert popup.evaluate("window.opener === null")
            urls.append(popup.locator("#asset").get_attribute("src"))
            viewers.append(popup)
        for popup in viewers[:-1]:
            popup.close(run_before_unload=True)
        page.wait_for_function("() => true")
        assert all(("revoke", url) in events for url in urls[:-1])
        assert ("revoke", urls[-1]) not in events
        assert viewers[-1].evaluate("() => document.querySelector('#asset').decode().then(() => true)")
        viewers[-1].close(run_before_unload=True)
        page.wait_for_timeout(100)
        assert ("revoke", urls[-1]) in events
        browser.close()


@pytest.mark.browser
def test_generate_without_tenant_uses_demo_and_loads_result(legacy_admin_browser_server: dict[str, Any]) -> None:
    if not _chromium_usable():
        pytest.skip("Chromium not available")

    base = legacy_admin_browser_server["base_url"]
    asset_id = "generated-demo-asset"
    requests: list[tuple[str, str]] = []
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        def omit_payload_tenant(route) -> None:  # noqa: ANN001
            response = route.fetch()
            html = response.text()
            before, generate = html.split("function handleGenerate(e)", 1)
            assert "tenantId: window.__FOX3D_DEFAULT_TENANT," in generate
            generate = generate.replace("tenantId: window.__FOX3D_DEFAULT_TENANT,", "", 1)
            route.fulfill(response=response, body=before + "function handleGenerate(e)" + generate)

        page.route("**/admin", omit_payload_tenant)
        page.route(f"**/api/assets/{asset_id}", lambda route: route.fulfill(content_type="image/png", body=_TINY_PNG))
        page.route("**/api/parametric/products", lambda route: route.fulfill(json={
            "render": {"job": {"outputAsset": asset_id}}
        }))
        def on_dialog(dialog) -> None:  # noqa: ANN001
            errors.append(dialog.message)
            dialog.dismiss()

        page.on("request", lambda req: requests.append((req.url, req.headers.get("x-tenant-id", ""))))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", on_dialog)
        page.goto(f"{base}/admin", wait_until="networkidle")
        requests.clear()
        page.locator("#gen-btn").click()
        page.wait_for_function("document.querySelector('#res-img').src.startsWith('blob:')")
        assert page.locator("#result-box").is_visible()
        assert any(url.endswith('/api/assets/' + asset_id) and tenant == 'demo' for url, tenant in requests)
        assert not errors
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


@pytest.mark.browser
def test_asset_viewer_shows_fetch_failure(legacy_admin_browser_server: dict[str, Any]) -> None:
    if not _chromium_usable():
        pytest.skip("Chromium not available")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/api/assets/missing-test", lambda route: route.fulfill(status=404))
        page.goto(f"{legacy_admin_browser_server['base_url']}/admin/asset-viewer?asset=missing-test&tenant=tenant-a")
        page.wait_for_function("() => document.querySelector('#status').textContent.includes('HTTP 404')")
        assert page.locator('#asset').is_hidden()
        browser.close()
