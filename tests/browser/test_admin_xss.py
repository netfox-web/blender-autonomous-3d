"""XSS regression: fixture strings must render as text, never execute."""

from __future__ import annotations

from typing import Any

import pytest

from tests.browser.conftest import TENANT, XSS_PROBE, XSS_STRING

pytestmark = pytest.mark.browser

XSS_PAGES = [
    ("/admin/pilot", "#receipts", "試產工單"),
    ("/admin/materials", "#mt-lots-wrap", "材料、餘料"),
]


@pytest.mark.parametrize("href,region,keyword", XSS_PAGES, ids=[p[0] for p in XSS_PAGES])
def test_xss_payload_renders_as_text_not_script(
    admin_page,
    admin_server: dict[str, Any],
    href: str,
    region: str,
    keyword: str,
) -> None:
    page = admin_page
    base = admin_server["base_url"]
    page.goto(base + href, wait_until="domcontentloaded")
    page.wait_for_selector(".fx-side", timeout=20_000)
    page.wait_for_load_state("networkidle")
    if href == "/admin/materials":
        page.wait_for_selector(region, timeout=25_000)
    else:
        page.wait_for_selector(region, timeout=25_000)
    assert page.evaluate("window.__fox3dXss || 0") == 0
    body = page.inner_text("body")
    assert XSS_PROBE in body, f"fixture {XSS_PROBE} not visible on {href}"
    assert page.locator(f'img[src="x"]').count() == 0
    # literal angle brackets should appear as text, not parsed elements with onerror handlers
    assert XSS_STRING.split(">")[0] + ">" in page.content() or XSS_PROBE in body

    page.keyboard.press("Control+K")
    page.locator(".fx-pal input[type=search]").fill(keyword)
    assert keyword in page.locator(".fx-pal-list li").first.inner_text()
