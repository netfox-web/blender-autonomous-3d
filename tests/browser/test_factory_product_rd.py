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
        "**/api/product-rd/results/rd-wait-01",
        lambda route: route.fulfill(json=waiting_item),
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


def test_tenant_switch_cancels_confirmations_and_ignores_inflight_responses(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    held: list[Route] = []
    item = {
        "rdId": "tenant-a-result",
        "text": "Tenant A plan",
        "baseSpec": {},
        "baseReport": {"ok": True},
        "top": [],
        "approval": {"status": "WAITING_APPROVAL"},
    }
    page.route(
        "**/api/product-rd/results?*",
        lambda route: route.fulfill(json={"items": [], "total": 0, "hasMore": False}),
    )
    page.route("**/api/product-rd/generate", lambda route: held.append(route))
    page.route("**/api/product-rd/results/tenant-a-result", lambda route: route.fulfill(json=item))
    page.route("**/api/product-rd/results/tenant-a-result/approve", lambda route: held.append(route))
    page.expose_function("__heldCount", lambda: len(held))
    page.goto(admin_server["base_url"] + "/admin/factory#rd")
    page.locator("#rd-text").fill("Tenant A requirement")
    page.locator("#rd-count").fill("10")
    page.locator("#rd-prepare-btn").click()
    expect(page.locator("#rd-confirm-msg")).to_contain_text("sonaqueen-home")
    _switch_tenant(page, "tenant-b")
    expect(page.locator("#rd-confirm-box")).to_be_hidden()
    _force_click(page, "rd-confirm-yes")
    assert len(held) == 0

    _switch_tenant(page, "sonaqueen-home")
    page.locator("#rd-prepare-btn").click()
    page.locator("#rd-confirm-yes").click()
    page.wait_for_function("async () => (await window.__heldCount()) === 1")
    assert held[0].request.headers["x-tenant-id"] == "sonaqueen-home"
    _switch_tenant(page, "tenant-b")
    _switch_tenant(page, "sonaqueen-home")
    held[0].fulfill(json=item)
    expect(page.locator("#rd-confirm-yes")).to_be_enabled()
    expect(page.locator("#rd-history-empty")).to_contain_text("尚無歷史研發方案")
    expect(page.locator("#rd-body")).to_be_hidden()

    # Load an A plan, then cancel approval on switching tenants.
    _switch_tenant(page, "tenant-b")
    page.unroute("**/api/product-rd/results?*")
    page.route(
        "**/api/product-rd/results?*",
        lambda route: route.fulfill(json={"items": [item] if route.request.headers.get("x-tenant-id") == "sonaqueen-home" else [], "total": 1, "hasMore": False}),
    )
    _switch_tenant(page, "sonaqueen-home")
    expect(page.locator("#rd-body")).to_be_visible()
    page.locator("#rd-approve-actor").fill("approver")
    page.locator("#rd-approve-prepare").click()
    expect(page.locator("#rd-approve-msg")).to_contain_text("sonaqueen-home")
    _switch_tenant(page, "tenant-b")
    _force_click(page, "rd-approve-yes")
    assert len(held) == 1
    _switch_tenant(page, "sonaqueen-home")
    expect(page.locator("#rd-body")).to_be_visible()
    page.locator("#rd-approve-actor").fill("approver")
    page.locator("#rd-approve-prepare").click()
    page.locator("#rd-approve-yes").click()
    page.wait_for_function("async () => (await window.__heldCount()) === 2")
    assert held[1].request.headers["x-tenant-id"] == "sonaqueen-home"
    _switch_tenant(page, "tenant-b")
    held[1].fulfill(json={**item, "approval": {"status": "APPROVED", "actor": "approver"}})
    expect(page.locator("#rd-approve-yes")).to_be_enabled()
    expect(page.locator("#rd-history-empty")).to_contain_text("尚無歷史研發方案")
    expect(page.locator("#rd-body")).to_be_hidden()


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_nested_render_job_failure_is_not_success(
    admin_page: Page, admin_server: dict[str, Any], status: str
) -> None:
    page = admin_page
    item = {
        "rdId": "partial-result", "text": "plan", "baseSpec": {}, "baseReport": {"ok": True},
        "top": [], "approval": {"status": "WAITING_APPROVAL"},
        "parametricRender": {"job": {"status": status, "realBlender": True, "usedMock": False}},
    }
    page.route("**/api/product-rd/generate", lambda route: route.fulfill(json=item))
    page.route("**/api/product-rd/results?*", lambda route: route.fulfill(json={"items": [item], "total": 1}))
    page.goto(admin_server["base_url"] + "/admin/factory#rd")
    expect(page.locator("#rd-truth-badges")).to_contain_text(status)
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：REAL")
    page.locator("#rd-text").fill("Test requirement")
    page.locator("#rd-count").fill("10")
    page.locator("#rd-prepare-btn").click()
    page.locator("#rd-confirm-yes").click()
    expect(page.locator("#fc-global-status")).to_have_class("fc-alert err")
    expect(page.locator("#fc-global-status")).to_contain_text(status)
    expect(page.locator("#fc-global-status")).to_contain_text("研發方案已儲存")


def test_queued_retry_render_job_from_fail_or_retry_not_shown_as_completed_preview(
    admin_page: Page, admin_server: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fox3d.blender import RuntimeResult

    page = admin_page
    platform = admin_server["platform"]
    orig_run_job = platform.runtime.run_job
    orig_submit_job = platform.submit_job
    mode_by_tenant: dict[str, str] = {}

    def _controlled_submit_job(payload: dict[str, Any]) -> dict[str, Any]:
        mode = mode_by_tenant.get(str(payload.get("tenantId") or ""), "")
        if mode == "terminal_fail":
            payload = {**payload, "maxAttempts": 1}
        return orig_submit_job(payload)

    def _controlled_run_job(job: dict[str, Any], **kwargs: Any) -> RuntimeResult:
        mode = mode_by_tenant.get(str(job.get("tenantId") or ""), "")
        if mode == "retry_real_crash":
            # Worst-case trap: realBlender=True & usedMock=False while _fail_or_retry requeues with error.
            return RuntimeResult(
                status="failed",
                outputs={},
                error="blender worker transient crash",
                real_blender=True,
                real_optix=True,
                real_cycles=True,
                real_render_output=False,
                used_mock=False,
                blender_version="4.2.0",
            )
        if mode == "terminal_fail":
            return RuntimeResult(
                status="failed",
                outputs={},
                error="optix kernel fatal error",
                real_blender=True,
                used_mock=False,
            )
        return orig_run_job(job, **kwargs)

    monkeypatch.setattr(platform, "submit_job", _controlled_submit_job)
    monkeypatch.setattr(platform.runtime, "run_job", _controlled_run_job)

    page.goto(admin_server["base_url"] + "/admin/factory#rd", wait_until="domcontentloaded")
    page.wait_for_selector("#rd-prepare-btn", timeout=20_000)
    _switch_tenant(page, "retry-render-tenant")
    expect(page.locator("#rd-history-empty")).to_contain_text("尚無歷史研發方案")

    # 1. Completed baseline (status == "succeeded", usedMock == True) -> ok alert + completed MOCK badge.
    page.locator("#rd-text").fill("客廳 寬150cm 電視櫃 雙門")
    page.locator("#rd-count").fill("10")
    page.locator("#rd-prepare-btn").click()
    with page.expect_response(
        lambda resp: resp.url.endswith("/api/product-rd/generate") and resp.request.method == "POST",
        timeout=20_000,
    ) as done_info:
        page.locator("#rd-confirm-yes").click()
    done_data = done_info.value.json()
    done_rd_id = done_data["rdId"]
    assert done_data["parametricRender"]["job"]["status"] == "succeeded"

    expect(page.locator("#fc-global-status")).to_have_class("fc-alert ok")
    expect(page.locator("#fc-global-status")).to_contain_text("商品研發方案產生完成")
    expect(page.locator("#rd-truth-badges")).to_contain_text("母版 3D 預覽：MOCK（模擬算圖已完成）")
    expect(page.locator("#rd-intent-summary")).to_contain_text("已完成（MOCK）")
    expect(
        page.locator(f'#rd-history-tbody tr[data-rd-id="{done_rd_id}"] [data-role="rd-preview-status"]')
    ).to_contain_text("已完成 · MOCK")

    # 2. Queued retry from real _fail_or_retry (attempts=1 < maxAttempts=3, realBlender=True, usedMock=False).
    mode_by_tenant["retry-render-tenant"] = "retry_real_crash"
    page.locator("#rd-text").fill("書房 寬90cm 高180cm 書櫃 四層")
    page.locator("#rd-count").fill("10")
    page.locator("#rd-prepare-btn").click()
    with page.expect_response(
        lambda resp: resp.url.endswith("/api/product-rd/generate") and resp.request.method == "POST",
        timeout=20_000,
    ) as generate_info:
        page.locator("#rd-confirm-yes").click()
    generate_resp = generate_info.value
    assert generate_resp.status == 200
    retry_body = generate_resp.json()
    retry_rd_id = retry_body["rdId"]
    actual_job = retry_body["parametricRender"]["job"]
    assert actual_job["status"] == "queued"
    assert actual_job["error"] == "blender worker transient crash"
    assert actual_job["attemptCount"] == 1
    assert actual_job["maxAttempts"] == 3
    assert actual_job["retryDelaySeconds"] > 0
    assert actual_job["realBlender"] is True
    assert actual_job["usedMock"] is False

    # Global status distinguishes retry-queued (warn) from completed (ok) and terminal failure (err).
    expect(page.locator("#fc-global-status")).to_have_class("fc-alert warn")
    expect(page.locator("#fc-global-status")).to_contain_text("排隊重試")
    expect(page.locator("#fc-global-status")).to_contain_text("第 1/3 次嘗試")
    expect(page.locator("#fc-global-status")).to_contain_text("blender worker transient crash")
    expect(page.locator("#fc-global-status")).not_to_contain_text("商品研發方案產生完成")
    expect(page.locator("#fc-global-status")).not_to_contain_text("算圖失敗")

    # Detail badge, summary KV, and history table row all show retry-queued, never completed MOCK/REAL or failed.
    expect(page.locator("#rd-truth-badges")).to_contain_text("排隊重試中")
    expect(page.locator("#rd-truth-badges")).to_contain_text("queued")
    expect(page.locator("#rd-truth-badges")).to_contain_text("第 1/3 次嘗試")
    expect(page.locator("#rd-truth-badges")).to_contain_text("blender worker transient crash")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：MOCK")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：REAL")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("已完成")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("算圖失敗")
    expect(page.locator("#rd-intent-summary")).to_contain_text("排隊重試中")
    expect(page.locator("#rd-intent-summary")).not_to_contain_text("已完成")

    retry_row_preview = page.locator(
        f'#rd-history-tbody tr[data-rd-id="{retry_rd_id}"] [data-role="rd-preview-status"]'
    )
    expect(retry_row_preview).to_contain_text("排隊重試中（queued · 第 1/3 次嘗試）")
    expect(retry_row_preview).not_to_contain_text("已完成")

    # Approving a retry-queued scheme warns in the confirm box and keeps the retry-queued preview badge after approval.
    page.locator("#rd-approve-actor").fill("rd-reviewer")
    page.locator("#rd-approve-prepare").click()
    expect(page.locator("#rd-approve-msg")).to_contain_text("排隊重試中")
    page.locator("#rd-approve-yes").click()
    expect(page.locator("#rd-gate-badge")).to_contain_text("APPROVED", timeout=20_000)
    expect(page.locator("#fc-global-status")).to_have_class("fc-alert warn")
    expect(page.locator("#fc-global-status")).to_contain_text("母版預覽：排隊重試中")
    expect(page.locator("#rd-truth-badges")).to_contain_text("排隊重試中")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：MOCK")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：REAL")

    # 3. Terminal failure from _fail_or_retry (attempts == maxAttempts == 1 -> status == "failed")
    # Select the earlier completed scheme first to verify failed generate switches selection and never leaves completed preview visible.
    page.locator(f'#rd-history-tbody tr[data-rd-id="{done_rd_id}"] button').click()
    expect(page.locator("#rd-truth-badges")).to_contain_text("母版 3D 預覽：MOCK（模擬算圖已完成）")

    mode_by_tenant["retry-render-tenant"] = "terminal_fail"
    page.locator("#rd-text").fill("臥室 寬120cm 高200cm 衣櫃 雙門")
    page.locator("#rd-count").fill("10")
    page.locator("#rd-prepare-btn").click()
    with page.expect_response(
        lambda resp: resp.url.endswith("/api/product-rd/generate") and resp.request.method == "POST",
        timeout=20_000,
    ) as fail_info:
        page.locator("#rd-confirm-yes").click()
    fail_body = fail_info.value.json()
    fail_rd_id = fail_body["rdId"]
    assert fail_body["parametricRender"]["job"]["status"] == "failed"
    assert fail_body["parametricRender"]["job"]["attemptCount"] == 1

    expect(page.locator("#fc-global-status")).to_have_class("fc-alert err")
    expect(page.locator("#fc-global-status")).to_contain_text("研發方案已儲存")
    expect(page.locator("#fc-global-status")).to_contain_text("optix kernel fatal error")
    expect(page.locator("#rd-intent-summary")).to_contain_text(fail_rd_id)
    expect(page.locator("#rd-truth-badges")).to_contain_text("optix kernel fatal error")
    expect(page.locator("#rd-truth-badges")).to_contain_text("算圖失敗")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：MOCK")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：REAL")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("排隊重試中")
    expect(
        page.locator(f'#rd-history-tbody tr[data-rd-id="{fail_rd_id}"] [data-role="rd-preview-status"]')
    ).to_contain_text("算圖失敗")

    # Reloading from GET /api/product-rd/results preserves all 3 distinct preview states in history.
    page.reload(wait_until="domcontentloaded")
    _switch_tenant(page, "retry-render-tenant")
    expect(
        page.locator(f'#rd-history-tbody tr[data-rd-id="{done_rd_id}"] [data-role="rd-preview-status"]')
    ).to_contain_text("已完成 · MOCK", timeout=20_000)
    expect(
        page.locator(f'#rd-history-tbody tr[data-rd-id="{retry_rd_id}"] [data-role="rd-preview-status"]')
    ).to_contain_text("排隊重試中")
    expect(
        page.locator(f'#rd-history-tbody tr[data-rd-id="{fail_rd_id}"] [data-role="rd-preview-status"]')
    ).to_contain_text("算圖失敗")
    assert getattr(page, "_fox3d_console_errors", []) == []


def test_rd_render_status_boundary_shapes_and_xss_in_error_text(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    xss_err = '<img src=x onerror="window.__fox3dXss=1"> worker-retry-err'

    base = {
        "tenantId": "sonaqueen-home",
        "variantCount": 10,
        "scoredCount": 8,
        "judgeLabel": "REAL",
        "scoringStatus": "REAL",
        "truthLabel": "MOCK",
        "HUMAN_APPROVAL_REQUIRED": True,
        "baseSpec": {"kind": "BOOKCASE", "width": 800, "height": 1800, "depth": 350},
        "baseReport": {"ok": True},
        "top": [],
        "approvedAt": None,
        "approval": {"status": "WAITING_APPROVAL", "judgeLabel": "REAL"},
    }
    items = [
        {
            **base,
            "rdId": "rd-shape-queued-err",
            "createdAt": "2026-11-19T14:05:00.000000Z",
            "text": "最小 queued+error 形狀與 XSS 測試",
            "parametricRender": {"job": {"status": "queued", "error": xss_err, "realBlender": True, "usedMock": False}},
        },
        {
            **base,
            "rdId": "rd-shape-retry-no-err",
            "createdAt": "2026-11-19T14:04:00.000000Z",
            "text": "retry_scheduled 無錯誤文字",
            "parametricRender": {"job": {"status": "retry_scheduled", "attemptCount": 2}},
        },
        {
            **base,
            "rdId": "rd-shape-fresh-queued",
            "createdAt": "2026-11-19T14:03:00.000000Z",
            "text": "初次排隊尚未執行",
            "parametricRender": {"job": {"status": "queued", "attemptCount": 0, "error": None}},
        },
        {
            **base,
            "rdId": "rd-shape-running",
            "createdAt": "2026-11-19T14:02:00.000000Z",
            "text": "算圖執行中",
            "parametricRender": {"job": {"status": "rendering", "attemptCount": 1, "maxAttempts": 3}},
        },
        {
            **base,
            "rdId": "rd-shape-real-done",
            "createdAt": "2026-11-19T14:01:00.000000Z",
            "text": "真實算圖完成",
            "truthLabel": "REAL",
            "parametricRender": {"job": {"status": "completed", "realBlender": True, "usedMock": False}},
        },
        {
            **base,
            "rdId": "rd-shape-malformed-job",
            "createdAt": "2026-11-19T14:00:00.000000Z",
            "text": "空白或陣列 job 邊界",
            "parametricRender": {"job": []},
        },
    ]
    by_id = {item["rdId"]: item for item in items}

    page.route(
        "**/api/product-rd/results?*",
        lambda route: route.fulfill(
            json={"items": items, "total": len(items), "offset": 0, "limit": 10, "hasMore": False, "nextCursor": None}
        ),
    )
    page.route(
        "**/api/product-rd/results/*",
        lambda route: route.fulfill(json=by_id[route.request.url.rsplit("/", 1)[-1]])
        if route.request.url.rsplit("/", 1)[-1] in by_id
        else route.fulfill(status=404, json={"detail": "找不到研發方案"}),
    )

    page.goto(admin_server["base_url"] + "/admin/factory#rd", wait_until="domcontentloaded")
    expect(page.locator("#rd-body")).to_be_visible()

    # Item 1 (auto-selected): minimal {status: "queued", error: xss_err} -> retrying, XSS escaped, not REAL/MOCK completed.
    expect(page.locator("#rd-truth-badges")).to_contain_text("母版 3D 預覽：排隊重試中（queued · " + xss_err + "）")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：REAL")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：MOCK")
    assert page.evaluate("window.__fox3dXss || 0") == 0
    assert page.locator('img[src="x"]').count() == 0

    # Item 2: retry_scheduled without error -> no duplicate "retry_scheduled · retry_scheduled"
    page.locator('#rd-history-tbody tr[data-rd-id="rd-shape-retry-no-err"] button').click()
    expect(page.locator("#rd-truth-badges")).to_contain_text("母版 3D 預覽：排隊重試中（retry_scheduled · 第 2 次嘗試）")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("retry_scheduled · retry_scheduled")

    # Item 3: initial queued with attemptCount=0 and error=None -> pending ("排隊待算圖"), not retrying/completed
    page.locator('#rd-history-tbody tr[data-rd-id="rd-shape-fresh-queued"] button').click()
    expect(page.locator("#rd-truth-badges")).to_contain_text("母版 3D 預覽：排隊待算圖（queued）")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("排隊重試中")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("已完成")

    # Item 4: rendering with attemptCount=1 -> active retry execution ("重試算圖執行中"), not completed
    page.locator('#rd-history-tbody tr[data-rd-id="rd-shape-running"] button').click()
    expect(page.locator("#rd-truth-badges")).to_contain_text("母版 3D 預覽：重試算圖執行中（rendering · 第 1/3 次嘗試）")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("已完成")

    # Item 5: completed with realBlender=True & usedMock=False -> REAL completed
    page.locator('#rd-history-tbody tr[data-rd-id="rd-shape-real-done"] button').click()
    expect(page.locator("#rd-truth-badges")).to_contain_text("母版 3D 預覽：REAL（真實算圖已完成）")

    # Item 6: malformed array job -> handled gracefully as SKIPPED without console error or completed badge
    page.locator('#rd-history-tbody tr[data-rd-id="rd-shape-malformed-job"] button').click()
    expect(page.locator("#rd-intent-summary")).to_contain_text("SKIPPED（未算圖）")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：MOCK")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("母版 3D 預覽：REAL")
    assert getattr(page, "_fox3d_console_errors", []) == []


def test_rd_render_status_after_retry_succeeds_or_fails_is_current_on_reload_and_approve(
    admin_page: Page, admin_server: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued retry that later succeeds or fails terminally must not keep showing "排隊重試中"."""
    from fox3d.blender import RuntimeResult

    page = admin_page
    platform = admin_server["platform"]
    tenant = "retry-live-tenant"
    orig_run_job = platform.runtime.run_job
    fail_render = {"on": True}

    def _controlled_run_job(job: dict[str, Any], **kwargs: Any) -> RuntimeResult:
        if job.get("tenantId") == tenant and fail_render["on"]:
            return RuntimeResult(
                status="failed",
                outputs={},
                error="optix transient device lost",
                real_blender=True,
                used_mock=False,
            )
        return orig_run_job(job, **kwargs)

    monkeypatch.setattr(platform.runtime, "run_job", _controlled_run_job)

    def _generate(text: str) -> dict[str, Any]:
        page.locator("#rd-text").fill(text)
        page.locator("#rd-count").fill("10")
        page.locator("#rd-prepare-btn").click()
        with page.expect_response(
            lambda resp: resp.url.endswith("/api/product-rd/generate") and resp.request.method == "POST",
            timeout=20_000,
        ) as info:
            page.locator("#rd-confirm-yes").click()
        body = info.value.json()
        assert body["parametricRender"]["job"]["status"] == "queued"
        assert body["parametricRender"]["job"]["attemptCount"] == 1
        expect(page.locator("#rd-truth-badges")).to_contain_text("排隊重試中")
        return body

    def _worker_retry(job_id: str) -> dict[str, Any]:
        result = platform.execute_job(platform.queue.get(job_id))
        assert isinstance(result, dict)
        return result

    page.goto(admin_server["base_url"] + "/admin/factory#rd", wait_until="domcontentloaded")
    page.wait_for_selector("#rd-prepare-btn", timeout=20_000)
    _switch_tenant(page, tenant)
    expect(page.locator("#rd-history-empty")).to_contain_text("尚無歷史研發方案")

    # 1. Retry later succeeds; the page is NOT reloaded before opening the approve confirm.
    ok_body = _generate("書房 寬90cm 高180cm 書櫃 四層")
    ok_rd_id = ok_body["rdId"]
    fail_render["on"] = False
    assert _worker_retry(ok_body["parametricRender"]["job"]["jobId"])["status"] == "succeeded"

    page.locator("#rd-approve-actor").fill("rd-reviewer")
    page.locator("#rd-approve-prepare").click()
    expect(page.locator("#rd-approve-confirm")).to_be_visible()
    expect(page.locator("#rd-approve-msg")).to_contain_text(ok_rd_id)
    expect(page.locator("#rd-approve-msg")).not_to_contain_text("排隊重試中")
    expect(page.locator("#rd-approve-msg")).not_to_contain_text("尚未完成算圖")
    expect(page.locator("#rd-truth-badges")).to_contain_text("母版 3D 預覽：MOCK（模擬算圖已完成）")
    expect(page.locator("#rd-truth-badges")).not_to_contain_text("排隊重試中")
    page.locator("#rd-approve-no").click()
    expect(page.locator("#rd-approve-confirm")).to_be_hidden()

    # 2. Retries exhausted -> terminal failure.
    fail_render["on"] = True
    fail_body = _generate("臥室 寬120cm 高200cm 衣櫃 雙門")
    fail_rd_id = fail_body["rdId"]
    fail_job_id = fail_body["parametricRender"]["job"]["jobId"]
    assert _worker_retry(fail_job_id)["status"] == "queued"
    final = _worker_retry(fail_job_id)
    assert final["status"] == "failed" and final["attemptCount"] == 3

    # Reload: history shows the current states, never the stale "排隊重試中".
    page.reload(wait_until="domcontentloaded")
    _switch_tenant(page, tenant)
    ok_row = page.locator(f'#rd-history-tbody tr[data-rd-id="{ok_rd_id}"] [data-role="rd-preview-status"]')
    fail_row = page.locator(f'#rd-history-tbody tr[data-rd-id="{fail_rd_id}"] [data-role="rd-preview-status"]')
    expect(ok_row).to_contain_text("已完成 · MOCK", timeout=20_000)
    expect(ok_row).not_to_contain_text("排隊重試中")
    expect(fail_row).to_contain_text("算圖失敗")
    expect(fail_row).not_to_contain_text("排隊重試中")
    expect(fail_row).not_to_contain_text("產生時快照")

    # Approving the terminally failed scheme warns about the failure, not about a pending retry.
    page.locator(f'#rd-history-tbody tr[data-rd-id="{fail_rd_id}"] button').click()
    expect(page.locator("#rd-truth-badges")).to_contain_text("算圖失敗")
    expect(page.locator("#rd-truth-badges")).to_contain_text("第 3/3 次嘗試")
    page.locator("#rd-approve-actor").fill("rd-reviewer")
    page.locator("#rd-approve-prepare").click()
    expect(page.locator("#rd-approve-msg")).to_contain_text("母版 3D 預覽算圖失敗")
    expect(page.locator("#rd-approve-msg")).not_to_contain_text("排隊重試中")
    page.locator("#rd-approve-yes").click()
    expect(page.locator("#rd-gate-badge")).to_contain_text("APPROVED", timeout=20_000)
    expect(page.locator("#fc-global-status")).to_have_class("fc-alert warn")
    expect(page.locator("#fc-global-status")).to_contain_text("母版預覽：算圖失敗")
    expect(page.locator("#fc-global-status")).not_to_contain_text("排隊重試中")
    assert getattr(page, "_fox3d_console_errors", []) == []


def test_rd_approve_prepare_rereads_scheme_handles_errors_and_marks_snapshot(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    held_reads: list[Route] = []
    item: dict[str, Any] = {
        "rdId": "rd-snap-01",
        "tenantId": "sonaqueen-home",
        "createdAt": "2026-11-19T15:00:00.000000Z",
        "text": "工作找不到的快照方案",
        "variantCount": 10,
        "scoredCount": 8,
        "judgeLabel": "MOCK",
        "scoringStatus": "MOCK",
        "truthLabel": "MOCK",
        "baseSpec": {"kind": "BOOKCASE", "width": 800, "height": 1800, "depth": 350},
        "baseReport": {"ok": True},
        "top": [],
        "approvedAt": None,
        "approval": {"status": "WAITING_APPROVAL", "judgeLabel": "MOCK"},
        "parametricRender": {
            "jobStatusSource": "SNAPSHOT",
            "job": {"status": "queued", "error": "worker crash", "attemptCount": 1, "maxAttempts": 3},
        },
    }
    page.route(
        "**/api/product-rd/results?*",
        lambda route: route.fulfill(
            json={"items": [item], "total": 1, "offset": 0, "limit": 10, "hasMore": False, "nextCursor": None}
        ),
    )
    page.route("**/api/product-rd/results/rd-snap-01", lambda route: held_reads.append(route))
    page.expose_function("__fox3dHeldRdReads", lambda: len(held_reads))

    page.goto(admin_server["base_url"] + "/admin/factory#rd", wait_until="domcontentloaded")
    expect(page.locator("#rd-body")).to_be_visible()

    # Snapshot status is labelled as such in the detail badge, summary and history row.
    expect(page.locator("#rd-truth-badges")).to_contain_text("排隊重試中")
    expect(page.locator("#rd-truth-badges")).to_contain_text("產生時快照，目前算圖狀態無法取得")
    expect(page.locator("#rd-intent-summary")).to_contain_text("產生時快照")
    expect(
        page.locator('#rd-history-tbody tr[data-rd-id="rd-snap-01"] [data-role="rd-preview-status"]')
    ).to_contain_text("產生時快照")

    page.locator("#rd-approve-actor").fill("lead-2")

    # Prepare re-reads the scheme; button is locked while in flight and a forced click sends nothing extra.
    page.locator("#rd-approve-prepare").click()
    page.wait_for_function("async () => (await window.__fox3dHeldRdReads()) === 1")
    expect(page.locator("#rd-approve-prepare")).to_be_disabled()
    _force_click(page, "rd-approve-prepare")
    assert held_reads[0].request.headers["x-tenant-id"] == "sonaqueen-home"

    # HTTP error: no confirm box, error alert, button usable again.
    held_reads[0].fulfill(status=500, json={"detail": "internal"})
    expect(page.locator("#fc-global-status")).to_contain_text("無法讀取研發方案目前狀態")
    expect(page.locator("#fc-global-status")).to_have_class("fc-alert err")
    expect(page.locator("#rd-approve-confirm")).to_be_hidden()
    expect(page.locator("#rd-approve-prepare")).to_be_enabled()
    assert len(held_reads) == 1

    # Network error: same.
    page.locator("#rd-approve-prepare").click()
    page.wait_for_function("async () => (await window.__fox3dHeldRdReads()) === 2")
    held_reads[1].abort()
    expect(page.locator("#fc-global-status")).to_contain_text("連線失敗")
    expect(page.locator("#rd-approve-confirm")).to_be_hidden()
    expect(page.locator("#rd-approve-prepare")).to_be_enabled()

    # Success: confirm shows the retry warning and that it is a generation-time snapshot.
    page.locator("#rd-approve-prepare").click()
    page.wait_for_function("async () => (await window.__fox3dHeldRdReads()) === 3")
    held_reads[2].fulfill(json=item)
    expect(page.locator("#rd-approve-confirm")).to_be_visible()
    expect(page.locator("#rd-approve-msg")).to_contain_text("排隊重試中")
    expect(page.locator("#rd-approve-msg")).to_contain_text("產生時快照")
    expect(page.locator("#rd-approve-prepare")).to_be_disabled()
    # The injected 500 / aborted request log "Failed to load resource"; no script error may appear.
    script_errors = [
        msg for msg in getattr(page, "_fox3d_console_errors", []) if not msg.startswith("Failed to load resource")
    ]
    assert script_errors == []
