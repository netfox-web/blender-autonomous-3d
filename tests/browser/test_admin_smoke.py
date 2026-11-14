"""Browser smoke for every admin feature page (Playwright + live uvicorn)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.browser.conftest import admin_page_features

pytestmark = pytest.mark.browser


def _path(href: str) -> str:
    return urlsplit(href).path or href


def _console_errors(page) -> list[str]:  # noqa: ANN001
    return list(getattr(page, "_fox3d_console_errors", []))


def _wait_shell(page, base_url: str) -> None:
    page.wait_for_selector(".fx-side", timeout=20_000)
    page.wait_for_function(
        "() => window.fox3dShell && typeof window.fox3dShell.data === 'function' && window.fox3dShell.data()",
        timeout=20_000,
    )


def _assert_no_console_errors(page, feature_id: str) -> None:  # noqa: ANN001
    errors = _console_errors(page)
    # benign: favicon; golden may 422 until operator supplies real DNA fixtures
    errors = [e for e in errors if "favicon" not in e.lower()]
    if feature_id == "golden":
        errors = [e for e in errors if "422" not in e]
    assert not errors, f"{feature_id}: console errors: {errors}"


def _assert_content_ready(page, feature_id: str) -> None:  # noqa: ANN001
    timeout = 60_000 if feature_id == "scenes" else 30_000
    page.wait_for_load_state("domcontentloaded")
    if feature_id == "scenes":
        page.wait_for_selector("#scene-app, #cabinet-studio, main", timeout=timeout)
        return
    page.wait_for_load_state("networkidle")
    page.wait_for_function(
        """() => {
          const body = document.body.innerText || '';
          if (body.includes('載入失敗') || body.includes('功能清單載入失敗')) return true;
          if (document.querySelector('table tbody tr')) return true;
          if (document.querySelector('.card b, .fd-card, #overview, .mt-empty, .kd-table tbody tr, .pf-table tbody tr, pre, #jobs, #product-list')) return true;
          if (/沒有|尚無|尚未|請選/.test(body)) return true;
          return false;
        }""",
        timeout=timeout,
    )
    text = page.inner_text("body")
    assert "載入中…" not in text or any(x in text for x in ("沒有", "尚無", "尚未", "請選", "HTTP")), (
        f"{feature_id}: page stuck loading"
    )


def _sidebar_has(page, href: str, title: str) -> None:  # noqa: ANN001
    path = _path(href)
    link = page.locator(f'aside.fx-side a.fx-link[href="{href}"]')
    if link.count() == 0:
        link = page.locator(f'aside.fx-side a.fx-link[href="{path}"]')
    if link.count() == 0:
        # hash-only feature entries share one page href
        link = page.locator("aside.fx-side a.fx-link").filter(has_text=title)
    assert link.count() >= 1, f"sidebar missing {title} -> {href}"


def _palette_finds(page, keyword: str, title: str) -> None:  # noqa: ANN001
    page.keyboard.press("Control+K")
    page.wait_for_selector(".fx-pal:not([hidden])", timeout=5_000)
    search = page.locator(".fx-pal input[type=search]")
    search.fill(keyword)
    page.wait_for_timeout(150)
    hit = page.locator(".fx-pal-list li").filter(has_text=title)
    assert hit.count() >= 1, f"palette missing {title} for query {keyword!r}"


@pytest.mark.parametrize("feature", admin_page_features(), ids=lambda f: f["id"])
def test_admin_page_smoke(
    admin_page,
    admin_server: dict[str, Any],
    feature: dict[str, Any],
) -> None:
    base = admin_server["base_url"]
    href = feature["href"]
    page = admin_page
    response = page.goto(base + href, wait_until="domcontentloaded")
    assert response is not None and response.status == 200, feature["id"]
    _wait_shell(page, base)
    _assert_content_ready(page, feature["id"])
    _assert_no_console_errors(page, feature["id"])

    keyword = feature["title"]
    if feature["id"] == "features":
        keyword = "功能總覽"
    _sidebar_has(page, href, feature["title"])
    _palette_finds(page, keyword, feature["title"])

    # BLOCKED registry rows must not read as completed success on the directory page.
    if feature["id"] == "features":
        page.goto(f"{base}/admin/features#golden-artwork", wait_until="domcontentloaded")
        card = page.locator("#golden-artwork")
        card.wait_for(timeout=10_000)
        tag = card.locator(".fd-tag.blocked")
        assert tag.count() == 1 and "待資料" in tag.inner_text()
        assert "完成" not in card.inner_text().replace("待資料", "")


def test_materials_bench_confirm_cancel_and_single_post(admin_page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    base = admin_server["base_url"]
    page.goto(f"{base}/admin/materials", wait_until="domcontentloaded")
    _wait_shell(page, base)
    page.locator("#tab-nesting").click()
    counts: list[int] = []

    def track(request) -> None:  # noqa: ANN001
        if request.method == "POST" and "/api/nesting/benchmarks" in request.url:
            counts.append(1)

    page.on("request", track)
    page.locator("#mt-bench-run").click()
    page.wait_for_selector("#mt-confirm[open]", timeout=5_000)
    page.locator("#mt-confirm-cancel").click()
    page.wait_for_timeout(200)
    assert counts == []

    page.locator("#mt-bench-run").click()
    page.wait_for_selector("#mt-confirm[open]", timeout=5_000)
    with page.expect_response(lambda r: "/api/nesting/benchmarks" in r.url and r.request.method == "POST") as resp:
        page.locator("#mt-confirm-ok").click()
    assert resp.value.ok
    assert len(counts) == 1


def test_kd_sku_confirm_cancel_and_single_post(admin_page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    base = admin_server["base_url"]
    page.goto(f"{base}/admin/kd", wait_until="domcontentloaded")
    _wait_shell(page, base)
    page.wait_for_function("() => document.querySelector('#kd-sku-kind') && document.querySelector('#kd-sku-kind').options.length > 0", timeout=20_000)
    counts: list[int] = []

    def track(request) -> None:  # noqa: ANN001
        if request.method == "POST" and request.url.rstrip("/").endswith("/api/kd/skus"):
            counts.append(1)

    page.on("request", track)
    page.locator("#kd-sku-form").evaluate("form => form.requestSubmit()")
    page.wait_for_selector("#kd-sku-confirm:not([hidden])", timeout=5_000)
    page.locator("#kd-sku-cancel").click()
    assert counts == []

    page.locator("#kd-sku-form").evaluate("form => form.requestSubmit()")
    page.wait_for_selector("#kd-sku-confirm:not([hidden])", timeout=5_000)
    with page.expect_response(lambda r: r.url.rstrip("/").endswith("/api/kd/skus") and r.request.method == "POST"):
        page.locator("#kd-sku-go").click()
    page.wait_for_timeout(300)
    assert len(counts) == 1


def test_pilot_purchase_confirm_cancel_and_single_post(admin_page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    base = admin_server["base_url"]
    page.goto(f"{base}/admin/pilot", wait_until="domcontentloaded")
    _wait_shell(page, base)
    counts: list[int] = []

    def track(request) -> None:  # noqa: ANN001
        if request.method == "POST" and "/api/pilot/purchase-requests" in request.url:
            counts.append(1)

    page.on("request", track)
    page.locator("#purchase input[name=material]").fill("PB_18_WHITE")
    page.locator("#purchase input[name=quantity]").fill("1")
    page.locator("#purchase").evaluate("form => form.requestSubmit()")
    page.wait_for_selector("#confirmation:not([hidden])", timeout=5_000)
    page.locator("#cancel").click()
    assert counts == []

    page.locator("#purchase input[name=material]").fill("PB_18_WHITE")
    page.locator("#purchase input[name=quantity]").fill("1")
    page.locator("#purchase").evaluate("form => form.requestSubmit()")
    page.wait_for_selector("#confirmation:not([hidden])", timeout=5_000)
    with page.expect_response(lambda r: "/api/pilot/purchase-requests" in r.url and r.request.method == "POST"):
        page.locator("#confirm").click()
    page.wait_for_timeout(300)
    assert len(counts) == 1


def test_recipes_new_dialog_cancel_and_single_post(admin_page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    base = admin_server["base_url"]
    page.goto(f"{base}/admin/recipes", wait_until="domcontentloaded")
    _wait_shell(page, base)
    page.wait_for_selector("#product-list", timeout=30_000)
    counts: list[int] = []

    def track(request) -> None:  # noqa: ANN001
        if request.method == "POST" and "/api/recipe-library/products" in request.url:
            counts.append(1)

    page.on("request", track)
    page.locator("#new-button").click()
    page.wait_for_function("() => document.getElementById('new-dialog').open", timeout=5_000)
    page.locator("#cancel-new").click()
    page.wait_for_function("() => !document.getElementById('new-dialog').open")
    assert counts == []

    sku = "BROWSER-SMOKE-38"
    page.locator("#new-button").click()
    page.wait_for_function("() => document.getElementById('new-dialog').open")
    page.locator("#new-form input[name=sku]").fill(sku)
    page.locator("#new-form input[name=name]").fill("瀏覽器煙霧測試")
    page.locator("#new-family").select_option(index=0)
    with page.expect_response(lambda r: "/api/recipe-library/products" in r.url and r.request.method == "POST") as resp:
        page.locator("#new-form button[type=submit]").click()
    assert resp.value.ok or resp.value.status == 409
    assert len(counts) == 1


def test_blocked_status_never_renders_as_success(admin_page, admin_server: dict[str, Any]) -> None:
    """MOCK/BLOCKED badges on pilot overview must not be styled as plain success copy."""
    page = admin_page
    base = admin_server["base_url"]
    page.goto(f"{base}/admin/pilot", wait_until="domcontentloaded")
    _wait_shell(page, base)
    page.wait_for_selector("#overview .card", timeout=25_000)
    warn = page.locator("#overview .card.warn b")
    assert warn.count() >= 1
    for i in range(warn.count()):
        val = warn.nth(i).inner_text()
        assert re.match(r"^(BLOCKED|MOCK|PARTIAL)", val), val
        assert val != "完成"
