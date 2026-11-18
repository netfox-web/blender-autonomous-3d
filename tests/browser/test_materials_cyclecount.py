"""Materials admin: cycle count confirm snapshot, network recovery, 409 messaging."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from playwright.sync_api import Page, Route

from tests.browser.test_admin_post_flows import TENANT, _goto

pytestmark = pytest.mark.browser


def _install_held_post(page: Page, path: str, pending: list[Route]) -> None:
    pattern = re.compile(re.escape(path) + r"$")

    def handle(route: Route) -> None:
        if route.request.method == "POST":
            pending.append(route)
            return
        route.continue_()

    page.route(pattern, handle)


def _seed_lot(admin_server: dict[str, Any], headers: dict[str, str]) -> str:
    import urllib.request

    req = urllib.request.Request(
        admin_server["base_url"] + "/api/materials/lots",
        data=json.dumps(
            {"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 6, "actor": "browser"}
        ).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode())
    return payload["lotId"]


def test_cycle_count_confirm_snapshot_survives_input_mutation(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    headers = {"X-Tenant-Id": TENANT}
    lot_id = _seed_lot(admin_server, headers)
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lots-wrap")
    page.locator('button[data-cc-lot="' + lot_id + '"]').click()
    page.locator("#mt-cc-counted").fill("4")
    page.locator("#mt-cc-reason").fill("snap-cc")
    page.locator("#mt-cc-submit").click()
    page.locator("#mt-confirm-ok").click()
    page.evaluate(
        """() => {
          document.getElementById('mt-cc-counted').value = '99';
          document.getElementById('mt-cc-reason').value = 'mutated';
        }"""
    )
    page.wait_for_function(
        """() => {
          const out = document.getElementById('mt-cc-lot-result');
          return !!(out && (out.textContent || '').indexOf('cycleCountId') >= 0);
        }"""
    )
    text = page.locator("#mt-cc-lot-result").inner_text()
    assert '"counted": 4' in text or "counted\": 4" in text
    assert "mutated" not in text


def test_cycle_count_post_abort_restores_submit_button(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    pending: list[Route] = []
    lot_id = _seed_lot(admin_server, {"X-Tenant-Id": TENANT})
    suffix = "/cycle-counts"
    _install_held_post(page, f"/api/materials/lots/{lot_id}{suffix}", pending)
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lots-wrap")
    page.locator('button[data-cc-lot="' + lot_id + '"]').click()
    page.locator("#mt-cc-counted").fill("3")
    page.locator("#mt-cc-reason").fill("net-cc")
    page.locator("#mt-cc-submit").click()
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => document.getElementById('mt-cc-submit').disabled")
    assert len(pending) == 1
    pending[0].abort()
    page.wait_for_function("() => !document.getElementById('mt-cc-submit').disabled")
    text = page.locator("#mt-banner").inner_text()
    assert "失敗" in text or "連線" in text


def test_cycle_count_approve_409_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    headers = {"X-Tenant-Id": TENANT}
    lot_id = _seed_lot(admin_server, headers)

    def fulfill_409(route: Route) -> None:
        if route.request.method == "POST" and route.request.url.endswith("/approve"):
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"detail": "帳面已變動，請重新盤點"}),
            )
            return
        route.continue_()

    page.route(re.compile(r"/api/materials/cycle-counts/.+/approve$"), fulfill_409)
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-cc-wrap")
    # Create pending row through API so the table has an approve button.
    import urllib.request

    create_req = urllib.request.Request(
        admin_server["base_url"] + f"/api/materials/lots/{lot_id}/cycle-counts",
        data=json.dumps(
            {"counted": 2, "reason": "ui-409", "idempotencyKey": "ui-409", "actor": "browser"}
        ).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(create_req) as resp:
        cc = json.loads(resp.read().decode())
    page.reload(wait_until="domcontentloaded")
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-cc-wrap")
    page.wait_for_selector('button[data-cc-approve="' + cc["cycleCountId"] + '"]', timeout=20_000)
    page.locator('button[data-cc-approve="' + cc["cycleCountId"] + '"]').click()
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function(
        """() => {
          const b = document.getElementById('mt-banner');
          return !!(b && !b.hidden && (b.textContent || '').indexOf('帳面已變動') >= 0);
        }"""
    )
    banner = page.locator("#mt-banner").inner_text()
    assert "成功" not in banner
    assert "帳面已變動" in banner

def test_resubmit_after_response_lost_creates_only_one_count(admin_page: Page, admin_server: dict[str, Any]) -> None:
    import urllib.request

    page = admin_page
    lot_id = _seed_lot(admin_server, {"X-Tenant-Id": TENANT})
    requests: list[dict[str, Any]] = []

    def lose_first_response(route: Route) -> None:
        if route.request.method != "POST":
            route.continue_()
            return
        requests.append(json.loads(route.request.post_data or "{}"))
        if len(requests) == 1:
            route.fetch()
            route.abort()
        else:
            route.continue_()

    page.route(re.compile(r"/api/materials/lots/" + re.escape(lot_id) + r"/cycle-counts$"), lose_first_response)
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lots-wrap")
    page.locator(f'button[data-cc-lot="{lot_id}"]').click()
    page.locator("#mt-cc-counted").fill("3")
    page.locator("#mt-cc-reason").fill("lost response")
    for attempt in range(2):
        page.locator("#mt-cc-submit").click()
        page.locator("#mt-confirm-ok").click()
        if attempt == 0:
            page.locator("#mt-cc-retry").wait_for(state="visible")
            page.locator("#mt-cc-reason").fill("temporary edit")
            page.locator("#mt-cc-reason").fill("lost response")
        else:
            page.wait_for_function("() => document.getElementById('mt-cc-lot-result').textContent.includes('cycleCountId')")
    assert len(requests) == 2
    assert requests[0]["idempotencyKey"] == requests[1]["idempotencyKey"]
    req = urllib.request.Request(admin_server["base_url"] + "/api/materials/cycle-counts", headers={"X-Tenant-Id": TENANT})
    with urllib.request.urlopen(req) as resp:
        rows = json.load(resp)["items"]
    assert len([row for row in rows if row["lotId"] == lot_id and row["reason"] == "lost response"]) == 1


def test_old_count_beyond_first_page_can_be_rejected(admin_page: Page, admin_server: dict[str, Any]) -> None:
    import urllib.request

    lot_id = _seed_lot(admin_server, {"X-Tenant-Id": TENANT})
    ids = []
    for i in range(101):
        req = urllib.request.Request(
            admin_server["base_url"] + f"/api/materials/lots/{lot_id}/cycle-counts",
            data=json.dumps({"counted": 3, "reason": f"page-{i}", "idempotencyKey": f"page-{i}", "actor": "browser"}).encode(),
            headers={"X-Tenant-Id": TENANT, "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            ids.append(json.load(resp)["cycleCountId"])
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-cc-wrap")
    page.locator(f'button[data-cc-reject="{ids[0]}"]').click()
    page.locator("#mt-confirm-ok").click()
    page.locator(f'button[data-cc-reject="{ids[0]}"]').wait_for(state="detached")
    assert admin_server["platform"].pilot.cyclecounts.counts[ids[0]]["status"] == "REJECTED"
