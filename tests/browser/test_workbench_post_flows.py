"""Workbench POST flows: in-flight lock, confirm snapshot, failures, XSS inert data.

Covers /admin/kd, pilot-floor, print-workspace, printfox-bridge, recipe-library,
golden-product, product-models. Uses route call counts — no wall-clock timing assertions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Route

from tests.browser.conftest import TENANT, XSS_STRING

pytestmark = pytest.mark.browser


def _path(url: str) -> str:
    return urlparse(url).path


def _install(page: Page, path: str, on_post: Callable[[Route], None]) -> None:
    pattern = re.compile(re.escape(path) + r"$")

    def handle(route: Route) -> None:
        if route.request.method == "POST" and _path(route.request.url) == path:
            on_post(route)
            return
        route.continue_()

    page.route(pattern, handle)


def _wait_shell(page: Page) -> None:
    page.wait_for_selector(".fx-side", timeout=20_000)
    page.wait_for_function(
        "() => window.fox3dShell && typeof window.fox3dShell.data === 'function' && window.fox3dShell.data()",
        timeout=20_000,
    )


def _click_anyway(page: Page, element_id: str) -> None:
    page.evaluate(
        """(id) => {
          const el = document.getElementById(id);
          if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }""",
        element_id,
    )


def _release(pending: list[Route], body: dict[str, Any] | None = None, *, status: int = 200) -> None:
    payload = body if body is not None else {"status": "FAILED"}
    for route in pending:
        try:
            route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))
        except Exception:
            pass


def _assert_inert(page: Page) -> None:
    assert page.evaluate("() => window.__fox3dXss || 0") == 0
    assert page.locator('img[src="x"]').count() == 0
    assert page.locator("[onerror]").count() == 0


# --- KD ---


def test_kd_sku_inflight_disables_and_second_click_does_not_repost(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    pending: list[Route] = []
    _install(page, "/api/kd/skus", pending.append)
    page.goto(admin_server["base_url"] + "/admin/kd", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function("() => document.querySelector('#kd-sku-kind') && document.querySelector('#kd-sku-kind').options.length > 0", timeout=20_000)
    page.locator("#kd-sku-form").evaluate("form => form.requestSubmit()")
    page.wait_for_selector("#kd-sku-confirm:not([hidden])")
    page.locator("#kd-sku-go").click()
    page.wait_for_function("() => document.getElementById('kd-sku-go').disabled")
    assert len(pending) == 1
    _click_anyway(page, "kd-sku-go")
    assert len(pending) == 1
    _release(pending, {"productId": "kd-held", "status": "ok"})
    page.wait_for_function("() => !document.getElementById('kd-sku-go').disabled")


def test_kd_sku_confirm_snapshot_and_tenant(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    seen: dict[str, Any] = {}

    def on_post(route: Route) -> None:
        seen["body"] = json.loads(route.request.post_data or "{}")
        seen["tenant"] = route.request.headers.get("x-tenant-id")
        route.fulfill(json={"productId": "snap-kd", "kind": seen["body"].get("kind")})

    _install(page, "/api/kd/skus", on_post)
    page.goto(admin_server["base_url"] + "/admin/kd", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function("() => document.querySelector('#kd-sku-kind') && document.querySelector('#kd-sku-kind').options.length > 0", timeout=20_000)
    kind = page.locator("#kd-sku-kind").input_value()
    page.locator("#kd-sku-form").evaluate("form => form.requestSubmit()")
    page.wait_for_selector("#kd-sku-confirm:not([hidden])")
    assert page.locator("#kd-sku-kind").is_disabled()
    assert kind in page.locator("#kd-sku-payload").inner_text()
    assert TENANT in page.locator("#kd-sku-payload").inner_text()
    page.evaluate(
        """() => {
          const sel = document.getElementById('kd-sku-kind');
          if (sel) sel.value = sel.options[sel.options.length - 1].value;
          document.getElementById('kd-tenant').value = 'mutated-tenant';
        }"""
    )
    page.locator("#kd-sku-go").click()
    page.wait_for_function("() => (document.getElementById('kd-sku-result').textContent || '').includes('snap-kd')")
    assert seen["body"]["kind"] == kind
    assert seen["tenant"] == TENANT


def test_kd_sku_cancel_and_refresh_while_inflight_block_second_post(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    pending: list[Route] = []
    posts = {"n": 0}

    def on_post(route: Route) -> None:
        posts["n"] += 1
        pending.append(route)

    _install(page, "/api/kd/skus", on_post)
    page.goto(admin_server["base_url"] + "/admin/kd", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function(
        "() => document.querySelector('#kd-sku-kind') && document.querySelector('#kd-sku-kind').options.length > 0",
        timeout=20_000,
    )
    page.locator("#kd-sku-form").evaluate("form => form.requestSubmit()")
    page.wait_for_selector("#kd-sku-confirm:not([hidden])")
    page.locator("#kd-sku-go").click()
    page.wait_for_function("() => document.getElementById('kd-sku-go').disabled")
    assert posts["n"] == 1
    page.locator("#kd-sku-cancel").click(force=True)
    assert posts["n"] == 1
    page.locator("#kd-sku-form").evaluate("form => form.requestSubmit()")
    assert posts["n"] == 1
    assert page.locator("#kd-refresh").is_disabled()
    _click_anyway(page, "kd-refresh")
    assert posts["n"] == 1
    _release(pending, {"productId": "kd-after-cancel", "status": "ok"})
    page.wait_for_function(
        "() => !document.getElementById('kd-sku-go').disabled && !document.getElementById('kd-refresh').disabled"
    )
    assert posts["n"] == 1


def test_kd_sku_blocked_and_network_are_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def on_blocked(route: Route) -> None:
        route.fulfill(json={"status": "BLOCKED", "truthLabel": "BLOCKED"})

    _install(page, "/api/kd/skus", on_blocked)
    page.goto(admin_server["base_url"] + "/admin/kd", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function("() => document.querySelector('#kd-sku-kind') && document.querySelector('#kd-sku-kind').options.length > 0", timeout=20_000)
    page.locator("#kd-sku-form").evaluate("form => form.requestSubmit()")
    page.locator("#kd-sku-go").click()
    page.wait_for_function("() => document.getElementById('kd-sku-result').classList.contains('kd-err')")
    assert "完成" not in page.locator("#kd-sku-result").inner_text()

    def on_net(route: Route) -> None:
        route.abort("failed")

    page.unroute(re.compile(re.escape("/api/kd/skus") + r"$"))
    _install(page, "/api/kd/skus", on_net)
    page.locator("#kd-sku-form").evaluate("form => form.requestSubmit()")
    page.locator("#kd-sku-go").click()
    page.wait_for_function("() => document.getElementById('kd-sku-result').classList.contains('kd-err')")
    page.wait_for_selector("#kd-sku-confirm", state="hidden")
    assert page.locator("#kd-sku-kind").is_enabled()


def test_kd_catalog_blocked_does_not_show_generated_summary(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def on_post(route: Route) -> None:
        route.fulfill(json={"status": "BLOCKED", "catalog": []})

    _install(page, "/api/kd/catalog", on_post)
    page.goto(admin_server["base_url"] + "/admin/kd", wait_until="domcontentloaded")
    _wait_shell(page)
    page.locator("#kd-catalog-form").evaluate("form => form.requestSubmit()")
    page.locator("#kd-catalog-go").click()
    page.wait_for_function("() => (document.getElementById('kd-catalog-summary').textContent || '').includes('失敗')")
    assert "已產生" not in page.locator("#kd-catalog-summary").inner_text()


# --- Pilot floor ---


def _open_pilot_floor(page: Page, base: str) -> None:
    page.goto(base + "/admin/pilot-floor", wait_until="domcontentloaded")
    _wait_shell(page)
    page.locator("#tab-stations").click()
    page.wait_for_selector("#pf-station-form", timeout=20_000)


def _confirm_station_form(page: Page) -> None:
    page.locator("#pf-station-form input[name=stationId]").fill("pf-browser-station")
    page.locator("#pf-station-form .pf-confirm-box").check()
    page.wait_for_selector("#pf-station-form .pf-confirm-summary:not([hidden])")


def test_pilot_floor_station_inflight_single_post(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    pending: list[Route] = []
    _install(page, "/api/pilot/stations", pending.append)
    _open_pilot_floor(page, admin_server["base_url"])
    _confirm_station_form(page)
    page.locator("#pf-station-form button[type=submit]").click()
    page.wait_for_function("() => document.querySelector('#pf-station-form .pf-confirm-box').disabled")
    assert len(pending) == 1
    page.evaluate(
        """() => {
          document.getElementById('pf-station-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }"""
    )
    assert len(pending) == 1
    _release(pending, {"stationId": "pf-browser-station", "status": "ONLINE"})
    page.wait_for_function("() => (document.getElementById('pf-action-status').textContent || '').includes('完成')")


def test_pilot_floor_second_form_blocked_while_station_inflight(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    pending: list[Route] = []
    dispatch_posts = {"n": 0}

    def on_station(route: Route) -> None:
        pending.append(route)

    def on_dispatch(route: Route) -> None:
        dispatch_posts["n"] += 1
        route.fulfill(json={"leaseId": "should-not-happen", "status": "ok"})

    _install(page, "/api/pilot/stations", on_station)
    _install(page, "/api/pilot/dispatch", on_dispatch)
    _open_pilot_floor(page, admin_server["base_url"])
    page.locator("#tab-dispatch").click()
    page.wait_for_selector("#pf-dispatch-form")
    page.evaluate(
        """() => {
          const f = document.getElementById('pf-dispatch-form');
          f.elements.namedItem('workOrderId').value = 'WO-ghost';
          f.elements.namedItem('operation').value = 'CUT';
          f.elements.namedItem('stationId').value = 'ST-ghost';
          const box = f.querySelector('.pf-confirm-box');
          box.checked = true;
          box.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )
    page.locator("#tab-stations").click()
    _confirm_station_form(page)
    page.locator("#pf-station-form button[type=submit]").click()
    page.wait_for_function("() => document.querySelector('#pf-station-form .pf-confirm-box').disabled")
    assert len(pending) == 1
    page.wait_for_function("() => document.querySelector('#pf-dispatch-form button[type=submit]').disabled")
    page.wait_for_function("() => document.querySelector('#pf-dispatch-form .pf-confirm-box').disabled")
    page.locator("#tab-dispatch").click(force=True)
    assert page.locator("#panel-dispatch").is_hidden()
    page.evaluate(
        """() => {
          document.getElementById('pf-dispatch-form').dispatchEvent(
            new Event('submit', { bubbles: true, cancelable: true })
          );
        }"""
    )
    assert dispatch_posts["n"] == 0
    assert "仍在送出中" in page.locator("#pf-action-status").inner_text()
    _release(pending, {"stationId": "pf-browser-station", "status": "ONLINE"})
    page.wait_for_function("() => (document.getElementById('pf-action-status').textContent || '').includes('完成')")
    page.wait_for_function(
        """() => {
          const box = document.querySelector('#pf-dispatch-form .pf-confirm-box');
          const btn = document.querySelector('#pf-dispatch-form button[type=submit]');
          return box && !box.disabled && box.checked && btn && !btn.disabled;
        }"""
    )


def test_pilot_floor_confirm_snapshot_tenant_and_body(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    seen: dict[str, Any] = {}

    def on_post(route: Route) -> None:
        seen["body"] = json.loads(route.request.post_data or "{}")
        seen["tenant"] = route.request.headers.get("x-tenant-id")
        route.fulfill(json={"stationId": "snap-st", "status": "ONLINE"})

    _install(page, "/api/pilot/stations", on_post)
    _open_pilot_floor(page, admin_server["base_url"])
    page.locator("#pf-station-form input[name=stationId]").fill("snap-station")
    page.locator("#pf-station-form .pf-confirm-box").check()
    assert page.locator("#pf-station-form input[name=stationId]").is_disabled()
    assert TENANT in page.locator("#pf-station-form .pf-confirm-summary").inner_text()
    page.evaluate(
        """() => {
          document.querySelector('#pf-station-form input[name=stationId]').value = 'mutated-st';
          document.getElementById('pf-tenant').value = 'other-tenant';
        }"""
    )
    page.locator("#pf-station-form button[type=submit]").click()
    page.wait_for_function("() => (document.getElementById('pf-action-status').textContent || '').includes('完成')")
    assert seen["body"]["stationId"] == "snap-station"
    assert seen["tenant"] == TENANT


def test_pilot_floor_exception_ack_then_resolve(admin_page: Page, admin_server: dict[str, Any]) -> None:
    platform = admin_server["platform"]
    exc = platform.pilot.inbox.record(
        tenant_id=TENANT,
        code="MATERIAL_SHORTAGE",
        work_order_id="wo-browser",
        actor="seed",
        detail="browser exc",
    )
    exc_id = exc["exceptionId"]
    base = admin_server["base_url"]
    page = admin_page
    page.goto(base + "/admin/pilot-floor", wait_until="domcontentloaded")
    _wait_shell(page)
    page.locator("#tab-exceptions").click()
    page.wait_for_function(
        "() => (document.getElementById('pf-exc-status').textContent || '').includes('筆異常')",
        timeout=20_000,
    )
    row = page.locator("#pf-exc-table tbody tr").filter(has_text=exc_id)
    row.locator("button", has_text="確認").click()
    page.locator(".pf-inline-confirm .pf-confirm-box").last.check()
    page.locator(".pf-inline-confirm button.pf-btn-primary").last.click()
    page.wait_for_function(
        "() => (document.getElementById('pf-action-status').textContent || '').includes('異常確認：完成')",
        timeout=20_000,
    )
    page.wait_for_function(
        f"() => (document.getElementById('pf-exc-table').innerText || '').includes('{exc_id}') && (document.getElementById('pf-exc-table').innerText || '').includes('ACKNOWLEDGED')",
        timeout=20_000,
    )
    row = page.locator("#pf-exc-table tbody tr").filter(has_text=exc_id)
    row.locator("button", has_text="結案").click()
    page.locator(".pf-inline-confirm .pf-confirm-box").last.check()
    page.locator(".pf-inline-confirm button.pf-btn-primary").last.click()
    page.wait_for_function(
        "() => (document.getElementById('pf-action-status').textContent || '').includes('異常結案：完成')",
        timeout=20_000,
    )
    page.locator("#pf-exc-filter").select_option("RESOLVED")
    page.wait_for_function(
        f"() => (document.getElementById('pf-exc-table').innerText || '').includes('{exc_id}')",
        timeout=20_000,
    )
    assert platform.pilot.inbox.get(exc_id, tenant_id=TENANT)["status"] == "RESOLVED"


def test_pilot_floor_station_status_cycle_and_retry_lock(admin_page: Page, admin_server: dict[str, Any]) -> None:
    platform = admin_server["platform"]
    platform.pilot.stations.register(
        tenant_id=TENANT,
        capabilities=["PANEL_CUTTING_MANUAL"],
        station_id="st-browser",
        actor="seed",
        status="ONLINE",
    )
    seen_puts: list[dict[str, Any]] = []
    fail_once = {"pending": True}

    def on_status_put(route: Route) -> None:
        if route.request.method != "PUT":
            route.continue_()
            return
        body = json.loads(route.request.post_data or "{}")
        seen_puts.append(body)
        if fail_once["pending"]:
            fail_once["pending"] = False
            route.fulfill(status=503, json={"detail": "injected failure"})
            return
        route.continue_()

    page = admin_page
    page.route("**/api/pilot/stations/st-browser/status", on_status_put)
    page.goto(admin_server["base_url"] + "/admin/pilot-floor", wait_until="domcontentloaded")
    _wait_shell(page)
    page.locator("#tab-stations").click()
    page.wait_for_function(
        "() => (document.getElementById('pf-station-table').innerText || '').includes('st-browser')",
        timeout=20_000,
    )

    row = page.locator("#pf-station-table tbody tr").filter(has_text="st-browser")
    row.locator("button", has_text="狀態").click()
    inline = page.locator(".pf-inline-confirm").last
    inline.locator("select[name=status]").select_option("MAINTENANCE")
    inline.locator("input[name=note]").fill("first")
    inline.locator(".pf-confirm-box").check()
    assert inline.locator("select[name=status]").is_disabled()
    assert inline.locator("input[name=note]").is_disabled()
    inline.locator("button.pf-btn-primary").click()
    page.wait_for_function(
        "() => (document.getElementById('pf-action-status').textContent || '').includes('失敗')",
        timeout=20_000,
    )
    assert inline.locator(".pf-confirm-box").is_checked()
    assert inline.locator("select[name=status]").is_disabled()
    assert inline.locator("input[name=note]").is_disabled()

    # Retry sends the exact same snapshotted transitionId and payload.
    inline.locator("button.pf-btn-primary").click()
    page.wait_for_function(
        "() => (document.getElementById('pf-action-status').textContent || '').includes('站點狀態：完成')",
        timeout=20_000,
    )
    assert len(seen_puts) == 2
    assert seen_puts[0] == seen_puts[1]
    assert seen_puts[0]["status"] == "MAINTENANCE"
    assert seen_puts[0]["note"] == "first"
    assert seen_puts[0]["transitionId"]

    # Switch MAINTENANCE -> ACTIVE -> MAINTENANCE ("second")
    for status, note_text in (("ACTIVE", ""), ("MAINTENANCE", "second")):
        page.wait_for_function(
            "() => (document.getElementById('pf-station-table').innerText || '').includes('st-browser')",
            timeout=20_000,
        )
        row = page.locator("#pf-station-table tbody tr").filter(has_text="st-browser")
        row.locator("button", has_text="狀態").click()
        inline = page.locator(".pf-inline-confirm").last
        inline.locator("select[name=status]").select_option(status)
        inline.locator("input[name=note]").fill(note_text)
        inline.locator(".pf-confirm-box").check()
        inline.locator("button.pf-btn-primary").click()
        page.wait_for_function(
            "() => (document.getElementById('pf-action-status').textContent || '').includes('站點狀態：完成')",
            timeout=20_000,
        )

    events = [
        ev
        for ev in platform.pilot.journal.list(TENANT)
        if ev.get("eventType") == "station.status" and ev.get("aggregateId") == "st-browser"
    ]
    assert [(ev["payload"]["status"], ev["payload"]["note"]) for ev in events] == [
        ("MAINTENANCE", "first"),
        ("ACTIVE", None),
        ("MAINTENANCE", "second"),
    ]
    assert len({ev["payload"]["transitionId"] for ev in events}) == 3
    assert platform.pilot.journal.verify(TENANT)["ok"] is True


def test_pilot_floor_blocked_and_network_are_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def on_blocked(route: Route) -> None:
        route.fulfill(json={"status": "BLOCKED", "truthLabel": "BLOCKED"})

    _install(page, "/api/pilot/stations", on_blocked)
    _open_pilot_floor(page, admin_server["base_url"])
    _confirm_station_form(page)
    page.locator("#pf-station-form button[type=submit]").click()
    page.wait_for_function("() => (document.getElementById('pf-action-status').textContent || '').includes('失敗')")
    assert "：完成" not in page.locator("#pf-action-status").inner_text()

    def on_net(route: Route) -> None:
        route.abort("failed")

    page.unroute(re.compile(re.escape("/api/pilot/stations") + r"$"))
    _install(page, "/api/pilot/stations", on_net)
    _confirm_station_form(page)
    page.locator("#pf-station-form button[type=submit]").click()
    page.wait_for_function("() => (document.getElementById('pf-action-status').textContent || '').includes('網路錯誤')")
    assert page.locator("#pf-station-form .pf-confirm-box").is_enabled()


# --- Print workspace ---


def _minimal_print_job() -> dict[str, Any]:
    return {
        "id": "pw-flow-job",
        "revision": 1,
        "draft": {
            "sku": "PW-FLOW",
            "name": "Flow test job",
            "layout": "FLAT",
            "panels": [{"label": "front", "assetId": "", "page": 0, "rotation": 0, "quantity": 1}],
            "rip": "RasterLink 6",
            "machine": "fixture",
            "substrate": "fixture",
        },
        "plan": {"planHash": "fixture-hash", "panels": []},
        "spec": {
            "width": 600,
            "depth": 400,
            "height": 800,
            "components": [
                {
                    "role": "body",
                    "location": [0, 0, 400],
                    "size": [580, 380, 760],
                }
            ],
        },
        "lastProofId": "proof-1",
        "release": None,
        "blenderAvailable": True,
    }


def test_print_workspace_save_inflight_single_post(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    posts: list[Route] = []
    job = _minimal_print_job()

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "POST" and path == "/api/print-workspace/jobs":
            posts.append(route)
            return
        if route.request.method == "GET" and path == "/api/print-workspace/jobs":
            route.fulfill(json={"items": []})
            return
        if route.request.method == "GET" and path == "/api/print-workspace/assets":
            route.fulfill(json={"items": []})
            return
        if route.request.method == "GET" and path.endswith("/sources"):
            route.fulfill(json={"configured": False, "total": 0, "items": []})
            return
        route.fallback()

    page.route("**/api/print-workspace/**", intercept)
    page.goto(admin_server["base_url"] + "/admin/recipes/print", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function("() => (document.getElementById('notice').textContent || '').includes('工作台')", timeout=20_000)
    page.locator("#name").fill("New flow product")
    page.locator("#sku").fill("PW-NEW")
    page.locator("#save").click()
    page.wait_for_function("() => document.getElementById('save').disabled")
    assert len(posts) == 1
    _click_anyway(page, "save")
    assert len(posts) == 1
    created = dict(job)
    created["id"] = "pw-new-id"
    _release(posts, created)
    page.wait_for_function("() => !document.getElementById('save').disabled")


def test_print_workspace_release_network_and_blocked_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    job = _minimal_print_job()

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "GET" and path == "/api/print-workspace/jobs":
            route.fulfill(json={"items": [{"id": job["id"], "draft": job["draft"], "revision": 1}]})
            return
        if route.request.method == "GET" and path == f"/api/print-workspace/jobs/{job['id']}":
            route.fulfill(json=job)
            return
        if route.request.method == "GET" and path == f"/api/print-workspace/jobs/{job['id']}/preview":
            route.fulfill(json={"state": "idle", "generated": False, "stale": False})
            return
        if route.request.method == "GET" and path == "/api/print-workspace/assets":
            route.fulfill(json={"items": []})
            return
        if route.request.method == "GET" and path.endswith("/sources"):
            route.fulfill(json={"configured": False, "total": 0, "items": []})
            return
        if route.request.method == "POST" and path.endswith("/release"):
            route.fulfill(status=409, json={"detail": "blocked release fixture"})
            return
        route.fallback()

    page.route("**/api/print-workspace/**", intercept)
    page.goto(admin_server["base_url"] + "/admin/recipes/print", wait_until="domcontentloaded")
    _wait_shell(page)
    page.locator(f'button[data-id="{job["id"]}"]').click()
    page.wait_for_function("() => document.getElementById('save-state').textContent.includes('已儲存')", timeout=20_000)
    for box in ("c-size", "c-orientation", "c-hardware", "c-color"):
        page.locator(f"#{box}").check()
    page.locator("#by").fill("Checker Name")
    page.locator("#release").click()
    page.wait_for_function(
        """() => {
          const n = document.getElementById('notice');
          return !!(n && (n.textContent || '').includes('blocked release fixture'));
        }"""
    )
    assert "印刷下載包已完成" not in page.locator("#notice").inner_text()
    assert page.locator("#save").is_enabled()


# --- PrintFox bridge ---


def _open_printfox_connected(page: Page, base: str) -> None:
    def stub(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "GET" and path.endswith("/connection"):
            route.fulfill(json={"connected": True, "baseUrl": "http://127.0.0.1:9", "status": {}})
            return
        if route.request.method == "GET" and path.endswith("/tasks"):
            route.fulfill(json={"items": []})
            return
        if route.request.method == "GET" and path.endswith("/designs"):
            route.fulfill(json={"total": 0, "items": []})
            return
        route.fallback()

    page.route("**/api/print-workspace/printfox/**", stub)
    page.goto(base + "/admin/recipes/print", wait_until="domcontentloaded")
    _wait_shell(page)
    page.locator("#printfox-panel summary").click()
    page.wait_for_function("() => (document.getElementById('pf-connection-status').textContent || '').includes('已連接')", timeout=15_000)


def test_printfox_generate_rejected_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "GET" and path.endswith("/connection"):
            route.fulfill(json={"connected": True, "baseUrl": "http://127.0.0.1:9", "status": {}})
            return
        if route.request.method == "GET" and path.endswith("/tasks"):
            route.fulfill(json={"items": []})
            return
        if route.request.method == "GET" and path.endswith("/designs"):
            route.fulfill(json={"total": 0, "items": []})
            return
        if route.request.method == "POST" and path.endswith("/tasks"):
            route.fulfill(json={"state": "rejected", "message": "BLOCKED fixture"})
            return
        route.fallback()

    page.route("**/api/print-workspace/printfox/**", intercept)
    _open_printfox_connected(page, admin_server["base_url"])
    page.locator("#pf-prompt").fill("test prompt")
    page.locator("#pf-generate-btn").click()
    page.wait_for_function("() => document.getElementById('pf-message').className === 'error'")
    assert "已送出單次生圖" not in page.locator("#pf-message").inner_text()


def test_printfox_generate_inflight_single_post(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    posts: list[Route] = []

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "POST" and path.endswith("/tasks"):
            posts.append(route)
            return
        if route.request.method == "GET" and path.endswith("/connection"):
            route.fulfill(json={"connected": True, "baseUrl": "http://127.0.0.1:9", "status": {}})
            return
        if route.request.method == "GET" and path.endswith("/tasks"):
            route.fulfill(json={"items": []})
            return
        if route.request.method == "GET" and path.endswith("/designs"):
            route.fulfill(json={"total": 0, "items": []})
            return
        route.fallback()

    page.route("**/api/print-workspace/printfox/**", intercept)
    _open_printfox_connected(page, admin_server["base_url"])
    page.locator("#pf-prompt").fill("hold prompt")
    page.locator("#pf-generate-btn").click()
    page.wait_for_function("() => document.getElementById('pf-generate-btn').disabled")
    assert len(posts) == 1
    _click_anyway(page, "pf-generate-btn")
    assert len(posts) == 1
    posts[0].fulfill(json={"state": "pending", "remoteJobId": "remote-1"})
    page.wait_for_function("() => !document.getElementById('pf-generate-btn').disabled")


# --- Recipe library ---


def test_recipe_new_dialog_return_value_reset_and_inflight(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    pending: list[Route] = []

    def on_products(route: Route) -> None:
        pending.append(route)

    _install(page, "/api/recipe-library/products", on_products)
    page.goto(admin_server["base_url"] + "/admin/recipes", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_selector("#product-list", timeout=30_000)
    page.locator("#new-button").click()
    assert page.evaluate("() => document.getElementById('new-dialog').returnValue") == ""
    page.locator("#new-form input[name=sku]").fill("NEW-FLOW-SKU")
    page.locator("#new-form input[name=name]").fill("Flow draft")
    with page.expect_request(
        lambda r: r.method == "POST" and _path(r.url) == "/api/recipe-library/products"
    ):
        page.locator("#new-form").evaluate("form => form.requestSubmit()")
    page.wait_for_function("() => document.querySelector('#new-form [type=submit]').disabled")
    assert len(pending) == 1
    page.evaluate(
        """() => {
          document.getElementById('new-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }"""
    )
    assert len(pending) == 1
    _release(
        pending,
        {"draft": {"sku": "NEW-FLOW-SKU", "name": "Flow draft", "family": "cabinet", "values": {}}, "revision": 1},
    )
    page.wait_for_function("() => !document.querySelector('#new-form [type=submit]').disabled")


def test_recipe_validate_blocked_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "POST" and path.endswith("/validate"):
            route.fulfill(status=400, json={"detail": XSS_STRING})
            return
        route.fallback()

    page.route("**/api/recipe-library/**", intercept)
    page.goto(admin_server["base_url"] + "/admin/recipes", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_selector("#product-list button", timeout=30_000)
    page.locator("#product-list button").first.click()
    page.locator("#specs-tab").click()
    page.locator("#validate-button").click()
    page.wait_for_function("() => document.getElementById('notice').className === 'error'")
    assert "資料檢查完成" not in page.locator("#notice").inner_text()
    _assert_inert(page)


# --- Golden product ---


def test_golden_export_inflight_and_failure_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    pending: list[Route] = []

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "POST" and path == "/api/product-dna/v1/exports":
            pending.append(route)
            return
        if path == "/api/recipe-library/golden":
            route.fulfill(json={"skus": ["THREE_TIER_FIXTURE"], "versions": [{"id": "FIXTURE_MASTER_V1", "label": "Fixture"}]})
            return
        if path.endswith("/plan"):
            route.fulfill(json={"ready": False, "blenderAvailable": False, "package": {"reason": "fixture"}, "golden": {"spec": {"components": []}}, "planHash": "h"})
            return
        if path.endswith("/status"):
            route.fulfill(json={"state": "idle", "generated": False})
            return
        route.fallback()

    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/**", intercept)
    page.goto(admin_server["base_url"] + "/admin/recipes/golden", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_selector("#dna-export-btn", timeout=20_000)
    page.locator("#dna-export-btn").click()
    page.wait_for_function("() => document.getElementById('dna-export-btn').disabled")
    assert len(pending) == 1
    _click_anyway(page, "dna-export-btn")
    assert len(pending) == 1
    pending[0].fulfill(status=400, json={"detail": "export blocked"})
    page.wait_for_function("() => !document.getElementById('dna-export-btn').disabled")
    assert "已建立並封存" not in page.locator("#notice").inner_text()


# --- Product models ---


def test_product_models_save_inflight_single_post(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    page = admin_page
    pending: list[Route] = []

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "POST" and path == "/api/product-models":
            pending.append(route)
            return
        route.fallback()

    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/product-models**", intercept)
    page.goto(base + "/admin/recipes/models", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function("() => (document.getElementById('notice').textContent || '').includes('從左側分類')", timeout=30_000)
    page.locator("#new").click()
    page.wait_for_selector('#master-form input[name="name"]', timeout=15_000)
    page.locator('#master-form input[name="name"]').fill("Save inflight model")
    page.locator("#master-form").evaluate("form => form.requestSubmit()")
    page.wait_for_function("() => document.getElementById('save').disabled")
    assert len(pending) == 1
    _click_anyway(page, "save")
    assert len(pending) == 1
    _release(
        pending,
        {
            "id": "model-inflight",
            "draft": {
                "name": "Save inflight model",
                "family": "cabinet",
                "subtype": "open",
                "geometry": "OPEN_CABINET",
                "widthMm": 424,
                "depthMm": 295,
                "heightMm": 900,
                "variants": [],
            },
            "revision": 1,
            "readiness": {"previewReady": False, "missing": "fixture"},
            "classification": {"revision": 0, "categoryId": "unclassified"},
        },
    )
    page.wait_for_function("() => !document.getElementById('save').disabled")


def test_product_models_scan_network_and_4xx_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "POST" and path.endswith("/catalog/refresh"):
            route.fulfill(status=400, json={"detail": XSS_STRING})
            return
        if route.request.method == "GET" and path == "/api/product-models/catalog":
            route.fulfill(json={"configured": True, "fileCount": 0, "items": [], "total": 0, "families": {}, "subtypes": {}})
            return
        route.fallback()

    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/product-models**", intercept)
    page.goto(admin_server["base_url"] + "/admin/recipes/models", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function("() => (document.getElementById('notice').textContent || '').includes('從左側分類')", timeout=30_000)
    page.locator("#show-materials").click()
    page.locator("#scan").click()
    page.wait_for_function("() => document.getElementById('notice').className === 'error'")
    assert "掃描完成" not in page.locator("#notice").inner_text()
    assert page.locator("#scan").is_enabled()
    _assert_inert(page)


def test_print_workspace_and_product_models_over_100_items_pagination(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    from urllib.parse import parse_qs, urlparse

    page = admin_page
    base = admin_server["base_url"]
    total = 105
    assets_list = [
        {
            "id": f"{i + 1:064x}",
            "name": f"art-{i + 1:03d}.pdf",
            "provenance": {"type": "NAS_PRODUCT_CATALOG", "relativePath": f"folder/art-{i + 1:03d}.pdf"},
            "info": {"type": "PDF", "pages": [{}]},
            "usage": {
                "role": "ARTWORK" if i < 104 else "UNCLASSIFIED",
                "label": "印刷圖稿" if i < 104 else "待分類",
                "note": "confirmed" if i < 104 else "",
                "revision": 1 if i < 104 else 0,
                "canUseForPrint": i < 104,
                "canUseForModel": i < 104,
            },
        }
        for i in range(total)
    ]
    asset_104_id = assets_list[103]["id"]
    jobs_list = [
        {
            "id": f"00000000-0000-0000-0000-{i + 1:012d}",
            "revision": 1,
            "draft": {
                "sku": f"SKU-{i + 1:03d}",
                "name": f"商品-{i + 1:03d}",
                "layout": "FLAT",
                "panels": [{"label": "正面", "assetId": asset_104_id, "page": 0, "rotation": 0, "quantity": 1}],
                "rip": "RasterLink 6",
                "machine": "Mimaki",
                "substrate": "Birch",
            },
            "plan": {"planHash": "a" * 64, "panels": [], "warnings": []},
            "spec": {"width": 600, "depth": 400, "height": 800, "components": []},
            "lastProofId": None,
            "release": None,
            "blenderAvailable": False,
        }
        for i in range(total)
    ]
    job_105_id = jobs_list[104]["id"]

    def intercept_print(route: Route) -> None:
        parsed = urlparse(route.request.url)
        path = parsed.path
        qs = parse_qs(parsed.query)
        offset = int(qs.get("offset", ["0"])[0])
        limit = min(int(qs.get("limit", ["100"])[0]), 100)
        if route.request.method == "GET" and path == "/api/print-workspace/assets":
            route.fulfill(
                json={
                    "items": assets_list[offset : offset + limit],
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "skipped": 0,
                }
            )
            return
        if route.request.method == "GET" and path == "/api/print-workspace/jobs":
            route.fulfill(
                json={
                    "items": jobs_list[offset : offset + limit],
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "skipped": 0,
                }
            )
            return
        if route.request.method == "GET" and path == f"/api/print-workspace/jobs/{job_105_id}":
            route.fulfill(json=jobs_list[104])
            return
        if route.request.method == "GET" and path == f"/api/print-workspace/jobs/{job_105_id}/preview":
            route.fulfill(json={"state": "idle", "generated": False, "stale": False})
            return
        if route.request.method == "GET" and path.endswith("/sources"):
            route.fulfill(json={"configured": False, "total": 0, "items": []})
            return
        if route.request.method == "GET" and "/preview" in path and path.startswith("/api/print-workspace/assets/"):
            route.fulfill(status=404, json={"detail": "fixture"})
            return
        route.fallback()

    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/print-workspace/**", intercept_print)
    page.goto(base + "/admin/recipes/print", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function("() => (document.getElementById('job-count').textContent || '').includes('105 個商品')")
    job_btn = page.locator(f'#jobs button[data-id="{job_105_id}"]')
    assert job_btn.count() == 1
    job_btn.click()
    page.wait_for_function("() => document.getElementById('sku').value === 'SKU-105'")
    assert page.locator('#panels select[data-key="assetId"]').first.input_value() == asset_104_id

    model_item = {
        "id": "model-page2-asset",
        "revision": 1,
        "inputHash": "b" * 64,
        "templateState": "DRAFT",
        "classification": {"categoryId": "unclassified", "path": ["未分類"], "source": "AUTO", "revision": 0},
        "readiness": {"previewReady": False, "missing": "fixture", "assumptions": []},
        "draft": {
            "name": "超過百筆素材測試模型",
            "family": "cabinet",
            "subtype": "open",
            "geometry": "OPEN_CABINET",
            "widthMm": 424,
            "depthMm": 295,
            "heightMm": 900,
            "variants": [{"sku": "V-104", "artworkAssetId": asset_104_id, "note": ""}],
            "printFaces": [],
        },
    }

    def intercept_models(route: Route) -> None:
        parsed = urlparse(route.request.url)
        path = parsed.path
        qs = parse_qs(parsed.query)
        offset = int(qs.get("offset", ["0"])[0])
        limit = min(int(qs.get("limit", ["100"])[0]), 100)
        if route.request.method == "GET" and path == "/api/product-models/assets":
            route.fulfill(
                json={
                    "roles": {"UNCLASSIFIED": "待分類", "ARTWORK": "印刷圖稿"},
                    "items": assets_list[offset : offset + limit],
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "skipped": 0,
                }
            )
            return
        if route.request.method == "GET" and path == "/api/product-models":
            route.fulfill(json={"items": [model_item], "categoryTree": [{"id": "unclassified", "label": "未分類"}]})
            return
        if route.request.method == "GET" and path == "/api/product-models/model-page2-asset":
            route.fulfill(json=model_item)
            return
        if route.request.method == "GET" and path == "/api/product-models/model-page2-asset/classification":
            route.fulfill(json=model_item["classification"])
            return
        if route.request.method == "GET" and path == "/api/product-models/model-page2-asset/preview":
            route.fulfill(json={"state": "idle", "generated": False, "stale": False})
            return
        if route.request.method == "GET" and path == "/api/product-models/model-page2-asset/composition":
            route.fulfill(
                json={
                    "state": "idle",
                    "generated": False,
                    "stale": False,
                    "scenes": {"STUDIO": "白底棚拍"},
                    "surfaces": [{"componentId": "door-1", "label": "門片", "widthMm": 280, "heightMm": 395}],
                    "manifest": None,
                }
            )
            return
        route.fallback()

    page.route("**/api/product-models**", intercept_models)
    page.goto(base + "/admin/recipes/models", wait_until="domcontentloaded")
    _wait_shell(page)
    page.wait_for_function("() => (document.getElementById('notice').textContent || '').includes('從左側分類')", timeout=30_000)
    page.locator("#masters button").filter(has_text="超過百筆素材測試模型").click()
    page.wait_for_selector(".variant-art", timeout=15_000)
    assert page.locator(".variant-art").first.input_value() == asset_104_id
    assert "原關聯素材未確認或已改用途" not in page.locator(".variant-art").first.inner_text()

    page.locator("#show-materials").click()
    assert "105 筆素材；104 筆已確認印刷用途。" in page.locator("#usage-count").inner_text()
    page.locator("#usage-query").fill("art-105.pdf")
    page.locator("#usage-list button").filter(has_text="art-105.pdf").click()
    assert page.locator("#usage-name").inner_text() == "art-105.pdf"
