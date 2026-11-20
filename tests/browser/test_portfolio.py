"""Portfolio admin UI — responsive layout and confirm flows."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.browser.test_admin_post_flows import _goto

pytestmark = pytest.mark.browser


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
    page.locator("#po-segment").select_option("STUDENT")
    page.locator("#po-create-intent").click()
    page.wait_for_function("() => !!(document.getElementById('po-generate') && !document.getElementById('po-generate').disabled)")
    page.locator("#po-generate").click()
    page.locator("#po-rank").click()
    page.wait_for_selector("#po-ranking-table tbody tr", timeout=30_000)
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