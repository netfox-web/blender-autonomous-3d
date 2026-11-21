"""Playwright smoke for /admin/prototypes."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, Route, expect

from fox3d.portfolio import run_portfolio_scenario
from tests.browser.conftest import TENANT
from tests.test_prototype import _ops

pytestmark = pytest.mark.browser


def _goto(page: Page, base: str, path: str, sel: str) -> None:
    page.goto(base + path, wait_until="domcontentloaded")
    page.wait_for_selector(sel, timeout=15_000)


def _seed_unit(platform, tenant: str = TENANT) -> dict[str, str]:
    portfolio = run_portfolio_scenario(platform, tenant_a=tenant, tenant_b="browser-proto-b")
    ranking = platform.portfolio.rank(portfolio["portfolioId"], tenant_id=tenant)
    candidate_id = ranking["top10"][0]["candidateId"]
    fixture, shift, human, human_shift = _ops(platform, tenant=tenant)
    selected = platform.prototype.select(
        tenant_id=tenant,
        candidate_id=candidate_id,
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        reason="browser-proto",
    )
    unit = platform.prototype.create_unit(
        tenant_id=tenant,
        selection_id=selected["selectionId"],
        operator_id=fixture["operatorId"],
        shift_id=shift["shiftId"],
        seq=1,
    )
    return {
        "portfolioId": portfolio["portfolioId"],
        "unitId": unit["prototypeUnitId"],
        "operatorId": fixture["operatorId"],
        "shiftId": shift["shiftId"],
        "humanOperatorId": human["operatorId"],
        "humanShiftId": human_shift["shiftId"],
    }


def _pick_unit(page: Page, ctx: dict[str, str]) -> None:
    page.locator("#proto-operator").fill(ctx["operatorId"])
    page.locator("#proto-shift").fill(ctx["shiftId"])
    row = page.locator("#proto-units tr", has_text=ctx["unitId"])
    row.locator("button").click()
    page.wait_for_function("() => !document.getElementById('proto-start').disabled")


def test_prototypes_page_loads_shell(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    _goto(admin_page, base, "/admin/prototypes", "#proto-refresh")
    expect(admin_page.locator("h1")).to_contain_text("原型驗證看板")
    expect(admin_page.locator("#proto-board")).to_be_visible()


def test_prototypes_confirm_cancel_no_post(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    ctx = _seed_unit(admin_server["platform"])
    posts: list[Route] = []

    def on_start(route: Route) -> None:
        if route.request.method == "POST" and route.request.url.endswith("/start"):
            posts.append(route)
        route.fallback()

    admin_page.route("**/api/prototypes/**", on_start)
    _goto(admin_page, base, "/admin/prototypes", "#proto-refresh")
    _pick_unit(admin_page, ctx)
    admin_page.locator("#proto-start").click()
    assert admin_page.evaluate("() => document.getElementById('proto-confirm').open") is True
    admin_page.locator("#proto-confirm-cancel").click()
    assert len(posts) == 0


def test_prototypes_confirm_ok_posts_start(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    ctx = _seed_unit(admin_server["platform"])
    _goto(admin_page, base, "/admin/prototypes", "#proto-refresh")
    _pick_unit(admin_page, ctx)
    admin_page.locator("#proto-start").click()
    with admin_page.expect_request(
        lambda r: r.method == "POST" and f"/units/{ctx['unitId']}/start" in r.url
    ) as req_info:
        admin_page.locator("#proto-confirm-ok").click()
    body = req_info.value.post_data_json
    assert isinstance(body, dict)
    assert body["operatorId"] == ctx["operatorId"]
    assert body["shiftId"] == ctx["shiftId"]


def test_prototypes_confirm_reopen_after_cancel_posts(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    ctx = _seed_unit(admin_server["platform"])
    _goto(admin_page, base, "/admin/prototypes", "#proto-refresh")
    _pick_unit(admin_page, ctx)
    admin_page.locator("#proto-start").click()
    admin_page.locator("#proto-confirm-cancel").click()
    admin_page.locator("#proto-start").click()
    with admin_page.expect_request(
        lambda r: r.method == "POST" and f"/units/{ctx['unitId']}/start" in r.url
    ):
        admin_page.locator("#proto-confirm-ok").click()


def test_prototypes_labor_post_uses_operator_inputs(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    ctx = _seed_unit(admin_server["platform"])
    plat = admin_server["platform"]
    plat.prototype.start_unit(ctx["unitId"], tenant_id=TENANT, operator_id=ctx["operatorId"], shift_id=ctx["shiftId"])
    _goto(admin_page, base, "/admin/prototypes", "#proto-refresh")
    _pick_unit(admin_page, ctx)
    admin_page.locator("#proto-operator").fill(ctx["humanOperatorId"])
    admin_page.locator("#proto-shift").fill(ctx["humanShiftId"])
    admin_page.locator("#proto-labor-minutes").fill("17")
    admin_page.locator("#proto-labor-reason").fill("browser-assembly")
    admin_page.select_option("#proto-labor-source", "MANUAL")
    admin_page.locator("#proto-labor").click()
    with admin_page.expect_request(
        lambda r: r.method == "POST" and f"/units/{ctx['unitId']}/labor" in r.url
    ) as req_info:
        admin_page.locator("#proto-confirm-ok").click()
    body = req_info.value.post_data_json
    assert isinstance(body, dict)
    assert body["minutes"] == 17
    assert body["reason"] == "browser-assembly"
    assert body["source"] == "MANUAL"


def test_prototypes_labor_distinct_minutes_second_post(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    ctx = _seed_unit(admin_server["platform"])
    plat = admin_server["platform"]
    plat.prototype.start_unit(ctx["unitId"], tenant_id=TENANT, operator_id=ctx["operatorId"], shift_id=ctx["shiftId"])
    headers = {"X-Tenant-Id": TENANT}
    ops = {"operatorId": ctx["operatorId"], "shiftId": ctx["shiftId"]}
    first = httpx.post(
        f"{base}/api/prototypes/units/{ctx['unitId']}/labor",
        headers=headers,
        json={**ops, "minutes": 9, "reason": "setup", "source": "FIXTURE", "idempotencyKey": "browser-lab-1"},
    )
    assert first.status_code == 200
    _goto(admin_page, base, "/admin/prototypes", "#proto-refresh")
    _pick_unit(admin_page, ctx)
    admin_page.locator("#proto-labor-minutes").fill("14")
    admin_page.locator("#proto-labor-reason").fill("setup")
    admin_page.locator("#proto-labor").click()
    with admin_page.expect_request(
        lambda r: r.method == "POST" and f"/units/{ctx['unitId']}/labor" in r.url
    ) as req_info:
        admin_page.locator("#proto-confirm-ok").click()
    body = req_info.value.post_data_json
    assert isinstance(body, dict)
    assert body["minutes"] == 14
    second = httpx.post(
        f"{base}/api/prototypes/units/{ctx['unitId']}/labor",
        headers=headers,
        json={**ops, "minutes": 14, "reason": "setup", "source": "FIXTURE", "idempotencyKey": body["idempotencyKey"]},
    )
    assert second.status_code == 200
    assert second.json()["laborId"] != first.json()["laborId"]