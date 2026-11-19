"""QC operator panel handles failed results and network errors."""
import json
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect


@pytest.mark.browser
def test_qc_panel_single_post_and_network_failure(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    posts: list[str] = []
    order_calls = {"n": 0}
    base_order = {"workOrderId": "test-order", "state": "IN_PROGRESS", "quantity": 1, "truthLabel": "MOCK"}

    def orders(route: Route) -> None:
        order_calls["n"] += 1
        state = "QC_HOLD" if order_calls["n"] > 1 else "IN_PROGRESS"
        route.fulfill(
            json={
                "items": [{**base_order, "state": state}],
                "total": 1,
                "limit": 100,
                "offset": 0,
            }
        )

    def qc(route: Route) -> None:
        if route.request.method == "GET":
            route.fulfill(json={"plan": [{"checkId": "THICKNESS", "nominal": 18, "tol": .5}], "requiredFinalOk": {"ok": False}})
        else:
            posts.append(route.request.post_data or "")
            if len(posts) == 1:
                route.fulfill(json={"result": "FAIL", "state": "QC_HOLD"})
            else:
                route.abort()

    page.route("**/api/pilot/work-orders*", orders)
    page.route("**/api/pilot/work-orders/test-order/qc", qc)
    page.goto(admin_server["base_url"] + "/admin/pilot")
    page.locator("#orders button").click()
    form = page.locator("#qc-checks form").first
    form.locator('input').first.fill('20')
    form.locator('button').click()
    page.locator('#confirm').click()
    expect(page.locator('#result')).to_contain_text('未通過')
    expect(page.locator('#detail')).to_contain_text('QC_HOLD')
    assert order_calls["n"] >= 2
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

    page.route("**/api/pilot/work-orders*", orders)
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

    page.route("**/api/pilot/work-orders*", orders)
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


@pytest.mark.browser
def test_pilot_work_orders_list_fetches_all_pages_over_100(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    requested: list[str] = []

    def orders(route: Route) -> None:
        requested.append(route.request.url)
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(route.request.url).query)
        offset = int((qs.get("offset") or ["0"])[0])
        limit = int((qs.get("limit") or ["100"])[0])
        total = 101
        if "offset" not in qs and "limit" not in qs:
            items = [
                {
                    "workOrderId": f"wo-{i:03d}",
                    "state": "DRAFT",
                    "quantity": 1,
                    "truthLabel": "MOCK",
                }
                for i in range(total)
            ]
            route.fulfill(json={"items": items, "total": total, "offset": 0, "limit": total})
            return
        end = min(offset + limit, total)
        items = [
            {
                "workOrderId": f"wo-{i:03d}",
                "state": "DRAFT",
                "quantity": 1,
                "truthLabel": "MOCK",
            }
            for i in range(offset, end)
        ]
        route.fulfill(json={"items": items, "total": total, "offset": offset, "limit": limit})

    def noop_json(route: Route) -> None:
        route.fulfill(json={})

    page.route("**/api/pilot/work-orders*", orders)
    page.route("**/api/pilot/console", noop_json)
    page.route("**/api/pilot/batches", lambda r: r.fulfill(json={"items": []}))
    page.route("**/api/pilot/batches/board", noop_json)
    page.route("**/api/pilot/health", noop_json)
    page.goto(admin_server["base_url"] + "/admin/pilot")
    expect(page.locator("#orders")).to_contain_text("wo-100")
    assert any("work-orders" in url and "offset=" not in url for url in requested)
