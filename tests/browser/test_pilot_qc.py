"""QC operator panel handles failed results and network errors."""
import json
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect


@pytest.mark.browser
def test_qc_panel_single_post_and_network_failure(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    posts: list[str] = []
    order = {"workOrderId": "test-order", "state": "IN_PROGRESS"}

    def orders(route: Route) -> None:
        route.fulfill(json={"items": [order], "total": 1, "limit": 100, "offset": 0})

    def qc(route: Route) -> None:
        if route.request.method == "GET":
            route.fulfill(json={"plan": [{"checkId": "THICKNESS", "nominal": 18, "tol": .5}], "requiredFinalOk": {"ok": False}})
        else:
            posts.append(route.request.post_data or "")
            if len(posts) == 1:
                route.fulfill(json={"result": "FAIL", "state": "QC_HOLD"})
            else:
                route.abort()

    page.route("**/api/pilot/work-orders", orders)
    page.route("**/api/pilot/work-orders/test-order/qc", qc)
    page.goto(admin_server["base_url"] + "/admin/pilot")
    page.locator("#orders button").click()
    form = page.locator("#qc-checks form").first
    form.locator('input').first.fill('20')
    form.locator('button').click()
    page.locator('#confirm').click()
    expect(page.locator('#result')).to_contain_text('未通過')
    assert len(posts) == 1
    assert json.loads(posts[0])["measured"] == 20
    form.locator('input').first.fill('19')
    form.locator('button').click()
    page.locator('#confirm').click()
    expect(page.locator('#qc-status')).to_contain_text('連線失敗')
    expect(form.locator('button')).to_be_enabled()
    assert len(posts) == 2


@pytest.mark.browser
def test_consume_success_while_qc_hold_does_not_show_qc_fail(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    order = {"workOrderId": "test-order", "state": "QC_HOLD", "quantity": 1}

    def orders(route: Route) -> None:
        route.fulfill(json={"items": [order], "total": 1, "limit": 100, "offset": 0})

    def consume(route: Route) -> None:
        route.fulfill(json={"state": "QC_HOLD", "consumedFlag": True, "workOrderId": "test-order"})

    def noop_json(route: Route) -> None:
        route.fulfill(json={})

    page.route("**/api/pilot/work-orders", orders)
    page.route("**/api/pilot/work-orders/test-order/consume", consume)
    page.route("**/api/pilot/work-orders/test-order/qc", lambda r: r.fulfill(json={"plan": [], "requiredFinalOk": {"ok": False}}))
    page.route("**/api/pilot/console", noop_json)
    page.route("**/api/pilot/batches", noop_json)
    page.route("**/api/pilot/batches/board", noop_json)
    page.route("**/api/pilot/health", noop_json)
    page.goto(admin_server["base_url"] + "/admin/pilot")
    page.locator("#orders button").click()
    page.locator('[data-action="consume"]').click()
    page.locator("#confirm").click()
    expect(page.locator("#result")).not_to_contain_text("未通過")
    expect(page.locator("#result")).to_contain_text("consumedFlag")


@pytest.mark.browser
def test_packing_resolve_success_while_qc_hold_does_not_show_qc_fail(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    order = {"workOrderId": "test-order", "state": "QC_HOLD", "quantity": 1}

    def orders(route: Route) -> None:
        route.fulfill(json={"items": [order], "total": 1, "limit": 100, "offset": 0})

    def resolve(route: Route) -> None:
        route.fulfill(json={"state": "QC_HOLD", "mismatchHold": False, "workOrderId": "test-order"})

    def noop_json(route: Route) -> None:
        route.fulfill(json={})

    page.route("**/api/pilot/work-orders", orders)
    page.route("**/api/pilot/work-orders/test-order/packing-mismatch/resolve", resolve)
    page.route("**/api/pilot/work-orders/test-order/qc", lambda r: r.fulfill(json={"plan": [], "requiredFinalOk": {"ok": False}}))
    page.route("**/api/pilot/work-orders/test-order/cartons", lambda r: r.fulfill(json={"items": [], "mismatchHold": True}))
    page.route("**/api/pilot/console", noop_json)
    page.route("**/api/pilot/batches", noop_json)
    page.route("**/api/pilot/batches/board", noop_json)
    page.route("**/api/pilot/health", noop_json)
    page.goto(admin_server["base_url"] + "/admin/pilot")
    page.locator("#orders button").click()
    page.locator("#packing-resolve-btn").click()
    page.locator("#confirm").click()
    expect(page.locator("#result")).not_to_contain_text("未通過")
    expect(page.locator("#packing-status")).to_contain_text("人工確認")
