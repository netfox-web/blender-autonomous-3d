"""Portfolio admin UI — responsive layout and confirm flows."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Route, expect

from tests.browser.test_admin_post_flows import _goto, _release

pytestmark = pytest.mark.browser


def _path(url: str) -> str:
    return urlparse(url).path


def _install_post_counter(
    page: Page, path_pattern: str, store: list[Route], on_capture: Callable[[Route], None] | None = None
) -> None:
    pattern = re.compile(path_pattern)

    def handle(route: Route) -> None:
        if route.request.method == "POST" and pattern.search(_path(route.request.url)):
            store.append(route)
            if on_capture:
                on_capture(route)
            return
        route.continue_()

    page.route(pattern, handle)


def _portfolio_bootstrap(page: Page, *, min_ranked: int = 1) -> None:
    page.locator("#po-segment").select_option("STUDENT")
    page.locator("#po-create-intent").click()
    page.wait_for_function("() => !!(document.getElementById('po-generate') && !document.getElementById('po-generate').disabled)")
    page.locator("#po-generate").click()
    page.wait_for_function(
        """() => document.querySelectorAll('#po-candidates-wrap .po-card').length > 0"""
    )
    page.locator("#po-rank").click()
    page.wait_for_function(
        f"""() => document.querySelectorAll('#po-ranking-table tbody button').length >= {min_ranked}"""
    )


@pytest.mark.parametrize("width", [400, 1440])
def test_portfolio_page_loads_and_shows_demand_estimate(admin_page, admin_server, width) -> None:
    page = admin_page
    page.set_viewport_size({"width": width, "height": 900})
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    expect(page.locator("#po-demand-label")).to_contain_text("需求為估計值")
    expect(page.locator("#po-candidates-wrap")).to_be_attached()
    expect(page.locator("#po-ranking-table")).to_be_attached()


def test_override_dialog_snapshots_fields(admin_page, admin_server) -> None:
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    page.locator("#po-ranking-table button").first.click()
    page.locator("#po-override-actor").fill("snap-actor")
    page.locator("#po-override-reason").fill("snap-reason")
    page.locator("#po-override-ok").click()
    page.wait_for_function(
        """() => {
          const snap = document.getElementById('po-override-snapshot');
          return snap && !snap.hidden && snap.textContent.indexOf('snap-actor') >= 0;
        }"""
    )
    snap = page.locator("#po-override-snapshot").inner_text()
    assert "snap-reason" in snap


def test_override_cancel_does_not_post(admin_page, admin_server) -> None:
    page = admin_page
    pending: list[Route] = []
    _install_post_counter(page, r"/api/portfolio/rankings/.+/override$", pending)
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    page.locator("#po-ranking-table button").first.click()
    page.locator("#po-override-cancel").click()
    page.wait_for_function("() => !document.getElementById('po-override-dialog').open")
    assert len(pending) == 0


def test_override_reorders_top_candidate(admin_page, admin_server) -> None:
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page, min_ranked=2)
    rows = page.locator("#po-ranking-table tbody tr")
    first_id = rows.nth(0).locator("td").nth(1).inner_text()
    second_id = rows.nth(1).locator("td").nth(1).inner_text()
    page.locator("#po-ranking-table button").nth(1).click()
    page.locator("#po-override-actor").fill("reorder-actor")
    page.locator("#po-override-reason").fill("reorder-reason")
    page.locator("#po-override-ok").click()
    page.wait_for_function(
        """() => {
          const banner = document.getElementById('po-banner');
          return banner && banner.textContent.indexOf('排名已依人工改排更新') >= 0;
        }"""
    )
    new_first = page.locator("#po-ranking-table tbody tr").nth(0).locator("td").nth(1).inner_text()
    assert new_first == second_id
    assert new_first != first_id


def test_approval_cleared_when_switching_candidates(admin_page, admin_server) -> None:
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    page.locator("#po-ranking-table tbody tr").nth(0).click()
    page.locator("#po-submit-approval").click()
    page.wait_for_function("() => !document.getElementById('po-approve').disabled")
    page.locator("#po-ranking-table tbody tr").nth(1).click()
    expect(page.locator("#po-approve")).to_be_disabled()


def test_approve_confirm_shows_candidate_snapshot(admin_page, admin_server) -> None:
    page = admin_page
    pending: list[Route] = []
    _install_post_counter(page, r"/api/portfolio/approvals/.+/approve$", pending)
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    page.locator("#po-ranking-table tbody tr").nth(0).click()
    candidate_id = page.locator("#po-ranking-table tbody tr").nth(0).locator("td").nth(1).inner_text()
    page.locator("#po-submit-approval").click()
    page.wait_for_function("() => !document.getElementById('po-approve').disabled")
    page.locator("#po-approve").click()
    confirm_text = page.locator("#po-confirm-text").inner_text()
    assert candidate_id in confirm_text
    assert "核准 ID：" in confirm_text
    page.locator("#po-confirm-cancel").click()
    assert len(pending) == 0


def test_submit_stale_response_after_switching_candidate(admin_page, admin_server) -> None:
    page = admin_page
    pending: list[Route] = []
    _install_post_counter(page, r"/api/portfolio/candidates/.+/submit-approval$", pending)
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page, min_ranked=2)
    candidate_a = page.locator("#po-ranking-table tbody tr").nth(0).locator("td").nth(1).inner_text()
    page.locator("#po-ranking-table tbody tr").nth(0).click()
    page.locator("#po-submit-approval").click()
    page.wait_for_function("() => document.getElementById('po-submit-approval').disabled")
    page.locator("#po-ranking-table tbody tr").nth(1).click()
    expect(page.locator("#po-approve")).to_be_disabled()
    _release(
        pending,
        {
            "approvalId": "appr-stale-bind-test",
            "candidateId": candidate_a,
            "status": "WAITING_PRODUCT_APPROVAL",
        },
    )
    page.wait_for_function("() => !document.getElementById('po-submit-approval').disabled")
    expect(page.locator("#po-approve")).to_be_disabled()
    expect(page.locator("#po-banner")).to_contain_text("畫面已切換")


def test_submit_stale_response_after_new_intent(admin_page, admin_server) -> None:
    page = admin_page
    pending: list[Route] = []
    _install_post_counter(page, r"/api/portfolio/candidates/.+/submit-approval$", pending)
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    candidate_id = page.locator("#po-ranking-table tbody tr").nth(0).locator("td").nth(1).inner_text()
    page.locator("#po-ranking-table tbody tr").nth(0).click()
    page.locator("#po-submit-approval").click()
    page.wait_for_function("() => document.getElementById('po-submit-approval').disabled")
    page.locator("#po-segment").select_option("STUDENT")
    page.locator("#po-create-intent").click()
    page.wait_for_function(
        """() => {
          const banner = document.getElementById('po-banner');
          return banner && banner.textContent.indexOf('已建立組合需求') >= 0;
        }"""
    )
    _release(
        pending,
        {
            "approvalId": "appr-stale-intent-test",
            "candidateId": candidate_id,
            "status": "WAITING_PRODUCT_APPROVAL",
        },
    )
    page.wait_for_function(
        """() => {
          const banner = document.getElementById('po-banner');
          return banner && banner.textContent.indexOf('畫面已切換') >= 0;
        }"""
    )
    expect(page.locator("#po-approve")).to_be_disabled()


def test_approve_posts_tenant_from_confirm_snapshot(admin_page, admin_server) -> None:
    page = admin_page
    captured_tenants: list[str] = []

    def on_approve_post(route: Route) -> None:
        captured_tenants.append(
            (route.request.headers.get("x-tenant-id") or route.request.headers.get("X-Tenant-Id") or "")
        )
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": "APPROVED_FOR_PROTOTYPE"}),
        )

    page.route(re.compile(r"/api/portfolio/approvals/.+/approve$"), on_approve_post)
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    page.locator("#po-ranking-table tbody tr").nth(0).click()
    page.locator("#po-submit-approval").click()
    page.wait_for_function("() => !document.getElementById('po-approve').disabled")
    page.locator("#po-approve").click()
    page.wait_for_function("() => document.getElementById('po-confirm').open")
    page.locator("#po-tenant").fill("tampered-tenant-id")
    page.locator("#po-confirm-ok").click()
    page.wait_for_function(
        """() => {
          const banner = document.getElementById('po-banner');
          return banner && banner.textContent.indexOf('原型已核准') >= 0;
        }"""
    )
    assert len(captured_tenants) == 1
    assert captured_tenants[0] == "sonaqueen-home"
    assert captured_tenants[0] != "tampered-tenant-id"


def test_approve_uses_snapshot_on_delayed_response(admin_page, admin_server) -> None:
    page = admin_page
    pending: list[Route] = []
    _install_post_counter(page, r"/api/portfolio/approvals/.+/approve$", pending)
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    page.locator("#po-ranking-table tbody tr").nth(0).click()
    snapped = page.locator("#po-ranking-table tbody tr").nth(0).locator("td").nth(1).inner_text()
    page.locator("#po-submit-approval").click()
    page.wait_for_function("() => !document.getElementById('po-approve').disabled")
    page.locator("#po-approve").click()
    page.locator("#po-confirm-ok").click()
    page.wait_for_function("() => document.getElementById('po-approve').disabled")
    page.locator("#po-ranking-table tbody tr").nth(1).click()
    _release(
        pending,
        {"status": "APPROVED_FOR_PROTOTYPE", "approvalId": "fake-delayed", "candidateId": snapped},
    )
    page.wait_for_function(
        """() => {
          const banner = document.getElementById('po-banner');
          return banner && banner.textContent.indexOf('原型已核准') >= 0;
        }"""
    )
    assert len(pending) == 1
    body = json.loads(pending[0].request.post_data or "{}")
    assert body.get("confirm") is True
    url = pending[0].request.url
    assert "/api/portfolio/approvals/" in url and url.rstrip("/").endswith("approve")


def test_ranking_cost_column_shows_numbers(admin_page, admin_server) -> None:
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    cost_cell = page.locator("#po-ranking-table tbody tr").first.locator("td").nth(5).inner_text()
    assert cost_cell
    assert cost_cell != "有效"
    assert cost_cell != "排除"
    assert re.match(r"^-?\d", cost_cell)


def test_new_intent_clears_old_candidates_and_ranking(admin_page, admin_server) -> None:
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    old_id = page.locator("#po-ranking-table tbody tr").first.locator("td").nth(1).inner_text()
    old_status = page.locator("#po-intent-status").inner_text()
    page.locator("#po-create-intent").click()
    expect(page.locator("#po-intent-status")).not_to_have_text(old_status)
    expect(page.locator("#po-ranking-table")).not_to_contain_text(old_id)
    expect(page.locator("#po-ranking-table tbody button")).to_have_count(0)
    expect(page.locator("#po-candidates-wrap .po-card")).to_have_count(0)
    expect(page.locator("#po-submit-approval")).to_be_disabled()
    expect(page.locator("#po-approve")).to_be_disabled()


@pytest.mark.parametrize("kind", ["candidates", "rankings"])
@pytest.mark.parametrize("switch", ["intent", "tenant"])
def test_delayed_portfolio_response_cannot_restore_old_rows(admin_page, admin_server, kind, switch) -> None:
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    pending: list[Route] = []
    pattern = re.compile(r"/api/portfolio/intents/.+/" + kind + r"$")

    def capture(route: Route) -> None:
        if route.request.method == ("GET" if kind == "candidates" else "POST"):
            pending.append(route)
        else:
            route.continue_()

    page.route(pattern, capture)
    page.evaluate("""kind => {
      const original = window.fetch;
      window.testResponseHandled = false;
      window.fetch = function(url, options) {
        const promise = original.apply(this, arguments);
        if (url.endsWith('/' + kind) && (options.method || 'GET') === (kind === 'candidates' ? 'GET' : 'POST')) {
          promise.then(response => {
            const read = response.text.bind(response);
            response.text = () => read().then(text => { window.testResponseHandled = true; return text; });
          });
        }
        return promise;
      };
    }""", kind)
    page.locator("#po-refresh" if kind == "candidates" else "#po-rank").click()
    # A subsequent browser interaction dispatches the intercepted request before releasing it.
    if switch == "intent":
        old_status = page.locator("#po-intent-status").inner_text()
        page.locator("#po-create-intent").click()
        expect(page.locator("#po-intent-status")).not_to_have_text(old_status)
    else:
        page.locator("#po-tenant").fill("other-tenant")
    payload = {"items": [{"candidateId": "old-candidate"}]} if kind == "candidates" else {
        "rankingId": "old-ranking", "top10": [{"candidateId": "old-candidate"}]
    }
    _release(pending, payload)
    assert len(pending) == 1
    page.wait_for_function("() => window.testResponseHandled")
    expect(page.locator("#po-candidates-wrap")).not_to_contain_text("old-candidate")
    expect(page.locator("#po-ranking-table")).not_to_contain_text("old-candidate")
    expect(page.locator("#po-submit-approval")).to_be_disabled()


def test_tenant_switch_closes_old_override_dialog(admin_page, admin_server) -> None:
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/portfolio", "#po-create-intent")
    _portfolio_bootstrap(page)
    page.locator("#po-ranking-table button").first.click()
    expect(page.locator("#po-override-dialog")).to_have_js_property("open", True)
    page.evaluate("""() => {
      const input = document.getElementById('po-tenant');
      input.value = 'other-tenant';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    expect(page.locator("#po-override-dialog")).to_have_js_property("open", False)
    expect(page.locator("#po-ranking-table tbody button")).to_have_count(0)
    expect(page.locator("#po-submit-approval")).to_be_disabled()
