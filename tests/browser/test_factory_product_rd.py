"""Playwright browser E2E for /admin/factory#rd: generate -> list -> approve, locking, pagination, and XSS."""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.browser


def _force_click(page: Page, element_id: str) -> None:
    page.evaluate(
        """(id) => {
          const el = document.getElementById(id);
          if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }""",
        element_id,
    )


def _switch_tenant(page: Page, tenant: str) -> None:
    page.locator("#fc-tenant").fill(tenant)
    page.locator("#fc-tenant").dispatch_event("change")


def test_product_rd_generate_list_persist_and_approve_keeps_mock_badge(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    generate_posts: list[dict[str, Any]] = []
    approve_posts: list[dict[str, Any]] = []

    def spy_generate(route: Route) -> None:
        if route.request.method == "POST":
            generate_posts.append(json.loads(route.request.post_data or "{}"))
        route.continue_()

    def spy_approve(route: Route) -> None:
        if route.request.method == "POST":
            approve_posts.append(json.loads(route.request.post_data or "{}"))
        route.continue_()

    page.route("**/api/product-rd/generate", spy_generate)
    page.route("**/api/product-rd/results/*/approve", spy_approve)

    page.goto(admin_server["base_url"] + "/admin/factory#rd", wait_until="domcontentloaded")
    page.wait_for_selector("#rd-prepare-btn", timeout=20_000)
    expect(page.locator("#rd-history-empty")).to_contain_text("尚無歷史研發方案")

    # 1. Generate: snapshot inputs on confirm and lock controls while confirm box is open.
    prompt_text = "書房 寬100cm 高180cm 白木紋書櫃 雙門 四層"
    page.locator("#rd-text").fill(prompt_text)
    page.locator("#rd-count").fill("10")
    page.locator("#rd-prepare-btn").click()

    expect(page.locator("#rd-confirm-box")).to_be_visible()
    expect(page.locator("#rd-text")).to_be_disabled()
    expect(page.locator("#rd-count")).to_be_disabled()
    expect(page.locator("#rd-prepare-btn")).to_be_disabled()
    expect(page.locator(".fc-preset-btn").first).to_be_disabled()

    # Programmatically mutate input DOM value while locked: confirm must still send the snapshotted value.
    page.evaluate(
        """() => {
          document.getElementById('rd-text').value = 'TAMPERED AFTER CONFIRM';
          document.getElementById('rd-count').value = '49';
        }"""
    )

    page.locator("#rd-confirm-yes").click()
    expect(page.locator("#rd-body")).to_be_visible(timeout=20_000)
    assert len(generate_posts) == 1
    assert generate_posts[0]["text"] == prompt_text
    assert generate_posts[0]["variantCount"] == 10
    assert generate_posts[0]["idempotencyKey"].startswith("rd-gen-")

    # Extract generated rdId from summary card and verify history table lists it with WAITING_APPROVAL + MOCK.
    expect(page.locator("#rd-gate-badge")).to_contain_text("WAITING_APPROVAL")
    expect(page.locator("#rd-truth-badges")).to_contain_text("MOCK")
    expect(page.locator("#rd-history-wrap")).to_be_visible()

    first_row = page.locator("#rd-history-tbody tr").first
    rd_id = first_row.get_attribute("data-rd-id")
    assert rd_id
    expect(first_row).to_contain_text(rd_id)
    expect(first_row).to_contain_text("WAITING_APPROVAL")
    expect(first_row).to_contain_text("MOCK")

    # Switching to another tenant hides sonaqueen-home's scheme; reload boots sonaqueen-home with persisted scheme.
    _switch_tenant(page, "other-empty-tenant")
    expect(page.locator("#rd-history-empty")).to_contain_text("尚無歷史研發方案")

    # 2. Reload page to verify persisted list loads automatically from GET /api/product-rd/results on #rd.
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(f'#rd-history-tbody tr[data-rd-id="{rd_id}"]')).to_be_visible(timeout=20_000)
    page.locator(f'#rd-history-tbody tr[data-rd-id="{rd_id}"] button').click()
    expect(page.locator("#rd-intent-summary")).to_contain_text(rd_id)

    # 3. Approve: snapshot actor on confirm, lock input, send confirm=true, keep MOCK after APPROVED.
    page.locator("#rd-approve-actor").fill("qa-rd-approver")
    page.locator("#rd-approve-prepare").click()

    expect(page.locator("#rd-approve-confirm")).to_be_visible()
    expect(page.locator("#rd-approve-actor")).to_be_disabled()
    expect(page.locator("#rd-approve-prepare")).to_be_disabled()

    page.evaluate("() => { document.getElementById('rd-approve-actor').value = 'tampered-actor'; }")
    page.locator("#rd-approve-yes").click()

    expect(page.locator("#rd-gate-badge")).to_contain_text("APPROVED", timeout=20_000)
    assert len(approve_posts) == 1
    assert approve_posts[0] == {"actor": "qa-rd-approver", "confirm": True}

    # Detail view shows APPROVED + approvedAt + actor AND keeps MOCK badge.
    expect(page.locator("#rd-intent-summary")).to_contain_text("qa-rd-approver")
    expect(page.locator("#rd-intent-summary")).to_contain_text("approvedAt")
    expect(page.locator("#rd-truth-badges")).to_contain_text("MOCK")
    expect(page.locator("#rd-approve-prepare")).to_be_disabled()

    # History row shows APPROVED + actor + approvedAt AND keeps MOCK badge.
    updated_row = page.locator(f'#rd-history-tbody tr[data-rd-id="{rd_id}"]')
    expect(updated_row).to_contain_text("APPROVED")
    expect(updated_row).to_contain_text("qa-rd-approver")
    expect(updated_row).to_contain_text("MOCK")

    assert getattr(page, "_fox3d_console_errors", []) == []
    assert page.evaluate("window.__fox3dXss || 0") == 0


def test_product_rd_inflight_lock_network_retry_blocked_and_pagination_xss(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    held_posts: list[Route] = []
    xss_probe = '<img src=x onerror="window.__fox3dXss=1">-rd-xss'

    page1_items: list[dict[str, Any]] = [
        {
            "rdId": f"rd-hist-{i:02d}",
            "tenantId": "rd-mock-ui",
            "createdAt": f"2026-11-19T12:{20 - i:02d}:00.000000Z",
            "text": xss_probe if i == 0 else f"歷史方案 {i}",
            "variantCount": 12,
            "scoredCount": 10,
            "judgeLabel": "MOCK",
            "scoringStatus": "MOCK",
            "truthLabel": "MOCK",
            "HUMAN_APPROVAL_REQUIRED": True,
            "baseSpec": {"kind": "BOOKCASE", "width": 800, "height": 1800, "depth": 350},
            "baseReport": {"ok": True},
            "top": [],
            "approvedAt": "2026-11-19T12:30:00.000000Z" if i == 0 else None,
            "approval": {
                "status": "APPROVED" if i == 0 else "WAITING_APPROVAL",
                "actor": xss_probe if i == 0 else None,
                "approvedAt": "2026-11-19T12:30:00.000000Z" if i == 0 else None,
                "judgeLabel": "MOCK",
            },
        }
        for i in range(10)
    ]
    page2_items = [
        {
            **page1_items[1],
            "rdId": "rd-hist-10",
            "createdAt": "2026-11-19T12:05:00.000000Z",
            "text": "第二頁方案 10",
        }
    ]

    list_urls: list[str] = []

    def handle_results(route: Route) -> None:
        list_urls.append(route.request.url)
        if "cursor=cur-page-2" in route.request.url:
            route.fulfill(
                json={
                    "items": page2_items,
                    "total": 11,
                    "offset": 10,
                    "limit": 10,
                    "hasMore": False,
                    "nextCursor": None,
                }
            )
        else:
            route.fulfill(
                json={
                    "items": page1_items,
                    "total": 11,
                    "offset": 0,
                    "limit": 10,
                    "hasMore": True,
                    "nextCursor": "cur-page-2",
                }
            )

    def handle_generate(route: Route) -> None:
        held_posts.append(route)

    page.expose_function("__fox3dHeldRdPosts", lambda: len(held_posts))
    page.route("**/api/product-rd/results?*", handle_results)
    page.route("**/api/product-rd/generate", handle_generate)

    page.goto(admin_server["base_url"] + "/admin/factory#rd", wait_until="domcontentloaded")
    expect(page.locator("#rd-history-tbody tr")).to_have_count(10)
    expect(page.locator("#rd-history-more-btn")).to_be_visible()

    # Verify XSS string rendered as literal text, never executed as DOM element.
    assert page.evaluate("window.__fox3dXss || 0") == 0
    assert page.locator('img[src="x"]').count() == 0
    expect(page.locator("#rd-history-tbody")).to_contain_text("rd-xss")

    # Click load more -> uses cursor and appends page 2 item.
    page.locator("#rd-history-more-btn").click()
    expect(page.locator("#rd-history-tbody tr")).to_have_count(11)
    expect(page.locator("#rd-history-tbody")).to_contain_text("第二頁方案 10")
    expect(page.locator("#rd-history-more-wrap")).to_be_hidden()
    assert any("cursor=cur-page-2" in u for u in list_urls)

    # Test generate in-flight lock, network error recovery with same idempotencyKey, and BLOCKED non-success.
    page.locator("#rd-text").fill("客廳 寬180cm 電視櫃 雙門")
    page.locator("#rd-count").fill("12")
    page.locator("#rd-prepare-btn").click()
    page.locator("#rd-confirm-yes").click()

    page.wait_for_function("async () => (await window.__fox3dHeldRdPosts()) === 1")
    expect(page.locator("#rd-confirm-yes")).to_be_disabled()
    expect(page.locator("#rd-confirm-no")).to_be_disabled()

    # Synthetic clicks while in-flight must NOT trigger duplicate POSTs.
    _force_click(page, "rd-confirm-yes")
    _force_click(page, "rd-prepare-btn")
    assert len(held_posts) == 1
    first_key = json.loads(held_posts[0].request.post_data or "{}")["idempotencyKey"]

    # Simulate network failure -> error alert, button re-enabled, retry keeps same idempotencyKey.
    held_posts[0].abort()
    expect(page.locator("#fc-global-status")).to_contain_text("連線失敗")
    expect(page.locator("#rd-confirm-yes")).to_be_enabled()

    page.locator("#rd-confirm-yes").click()
    page.wait_for_function("async () => (await window.__fox3dHeldRdPosts()) === 2")
    second_key = json.loads(held_posts[1].request.post_data or "{}")["idempotencyKey"]
    assert second_key == first_key

    # Fulfill with BLOCKED status -> must NOT show ok/success alert.
    held_posts[1].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"status": "blocked", "error": "BLOCKED_NO_BLENDER"}),
    )
    expect(page.locator("#fc-global-status")).to_have_class("fc-alert err")
    expect(page.locator("#fc-global-status")).to_contain_text("BLOCKED_NO_BLENDER")


def test_product_rd_approve_inflight_network_error_and_lookup_404_clears_selection(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    held_approves: list[Route] = []

    waiting_item: dict[str, Any] = {
        "rdId": "rd-wait-01",
        "tenantId": "sonaqueen-home",
        "createdAt": "2026-11-19T13:00:00.000000Z",
        "text": "臥室 寬120cm 衣櫃 雙門",
        "variantCount": 12,
        "scoredCount": 10,
        "judgeLabel": "MOCK",
        "scoringStatus": "MOCK",
        "truthLabel": "MOCK",
        "HUMAN_APPROVAL_REQUIRED": True,
        "baseSpec": {"kind": "WARDROBE", "width": 1200, "height": 2100, "depth": 600},
        "baseReport": {"ok": True},
        "top": [],
        "approvedAt": None,
        "approval": {
            "status": "WAITING_APPROVAL",
            "actor": None,
            "approvedAt": None,
            "judgeLabel": "MOCK",
        },
    }

    page.expose_function("__fox3dHeldRdApproves", lambda: len(held_approves))
    page.route(
        "**/api/product-rd/results?*",
        lambda route: route.fulfill(
            json={
                "items": [waiting_item],
                "total": 1,
                "offset": 0,
                "limit": 10,
                "hasMore": False,
                "nextCursor": None,
            }
        ),
    )
    page.route(
        "**/api/product-rd/results/missing-id",
        lambda route: route.fulfill(status=404, json={"detail": "找不到研發方案"}),
    )
    page.route(
        "**/api/product-rd/results/rd-wait-01/approve",
        lambda route: held_approves.append(route),
    )

    page.goto(admin_server["base_url"] + "/admin/factory#rd", wait_until="domcontentloaded")
    expect(page.locator("#rd-body")).to_be_visible()
    expect(page.locator("#rd-approve-prepare")).to_be_enabled()

    page.locator("#rd-approve-actor").fill("lead-1")
    page.locator("#rd-approve-prepare").click()
    page.locator("#rd-approve-yes").click()

    page.wait_for_function("async () => (await window.__fox3dHeldRdApproves()) === 1")
    expect(page.locator("#rd-approve-yes")).to_be_disabled()
    expect(page.locator("#rd-approve-no")).to_be_disabled()

    # Duplicate forced clicks while approve is in flight must not emit a second POST.
    _force_click(page, "rd-approve-yes")
    _force_click(page, "rd-approve-prepare")
    assert len(held_approves) == 1

    # Network failure re-enables confirm button and displays error alert.
    held_approves[0].abort()
    expect(page.locator("#fc-global-status")).to_contain_text("連線失敗")
    expect(page.locator("#rd-approve-yes")).to_be_enabled()
    page.locator("#rd-approve-no").click()
    expect(page.locator("#rd-approve-confirm")).to_be_hidden()

    # Lookup of a 404 rdId hides #rd-body and clears selection so stale approve cannot run.
    page.locator("#rd-lookup-id").fill("missing-id")
    page.locator("#rd-lookup-btn").click()
    expect(page.locator("#rd-empty")).to_contain_text("HTTP 404")
    expect(page.locator("#rd-body")).to_be_hidden()

