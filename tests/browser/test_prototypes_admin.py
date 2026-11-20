"""Playwright smoke for /admin/prototypes."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def _goto(page: Page, base: str, path: str, sel: str) -> None:
    page.goto(base + path, wait_until="domcontentloaded")
    page.wait_for_selector(sel, timeout=15_000)


def test_prototypes_page_loads_shell(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    _goto(admin_page, base, "/admin/prototypes", "#proto-refresh")
    expect(admin_page.locator("h1")).to_contain_text("原型驗證看板")
    expect(admin_page.locator("#proto-board")).to_be_visible()