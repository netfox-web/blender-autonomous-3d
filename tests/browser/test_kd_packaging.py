"""Playwright smoke for /admin/kd#structures packaging engineering panel."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def _goto_structures(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/admin/kd#structures", wait_until="domcontentloaded")
    page.wait_for_selector("#kdp-root", state="attached")


def _no_horizontal_overflow(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    metrics = page.evaluate(
        """() => ({
          docScrollWidth: document.documentElement.scrollWidth,
          docClientWidth: document.documentElement.clientWidth,
        })"""
    )
    assert metrics["docScrollWidth"] <= metrics["docClientWidth"] + 2


@pytest.mark.parametrize("width", [400, 1440])
def test_kd_packaging_panel_loads(admin_page, admin_server, width) -> None:
    page = admin_page
    _goto_structures(page, admin_server["base_url"])
    _no_horizontal_overflow(page, width)
    expect(page.locator("#kdp-head-h")).to_contain_text("包裝工程檢查")
    expect(page.locator("#kdp-grade option")).not_to_have_count(0)


def test_kd_packaging_compression_flow(admin_page, admin_server) -> None:
    page = admin_page
    _goto_structures(page, admin_server["base_url"])
    page.locator("#kdp-compress-btn").click()
    page.wait_for_function(
        """() => {
          const out = document.getElementById('kdp-compress-out');
          return out && !out.hidden && out.textContent.indexOf('允許載重') >= 0;
        }"""
    )
    text = page.locator("#kdp-compress-out").inner_text()
    assert "ENGINEERING_ESTIMATE" in text or "來源" in text


def test_kd_packaging_dieline_failure_shown(admin_page, admin_server) -> None:
    page = admin_page
    _goto_structures(page, admin_server["base_url"])
    bad = json.dumps({"panels": [{"id": "a", "w": 1, "h": 1}]})
    page.locator("#kdp-dieline-json").fill(bad)
    page.locator("#kdp-dieline-btn").click()
    page.wait_for_function(
        """() => {
          const msg = document.getElementById('kdp-dieline-msg');
          return msg && msg.textContent.indexOf('未通過') >= 0;
        }"""
    )
    expect(page.locator("#kdp-dieline-msg")).to_contain_text("未通過")


def test_kd_packaging_optimize_table(admin_page, admin_server) -> None:
    page = admin_page
    _goto_structures(page, admin_server["base_url"])
    page.locator("#kdp-opt-btn").click()
    page.wait_for_function(
        """() => {
          const t = document.getElementById('kdp-opt-table');
          return t && !t.hidden && document.querySelectorAll('#kdp-opt-tbody tr').length > 0;
        }"""
    )
    expect(page.locator("#kdp-opt-tbody tr").first).to_be_visible()