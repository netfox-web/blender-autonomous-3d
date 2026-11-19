"""Materials admin: lot quarantine confirm flow."""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.browser.test_admin_post_flows import TENANT, _goto

pytestmark = pytest.mark.browser


def _seed_lot(admin_server: dict[str, Any], headers: dict[str, str]) -> str:
    import urllib.request

    req = urllib.request.Request(
        admin_server["base_url"] + "/api/materials/lots",
        data=json.dumps(
            {"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 4, "actor": "browser"}
        ).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.loads(resp.read().decode())
    return payload["lotId"]


def test_lot_quarantine_confirm_snapshot(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    headers = {"X-Tenant-Id": TENANT}
    lot_id = _seed_lot(admin_server, headers)
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lots-wrap")
    page.wait_for_selector('button[data-cc-lot="' + lot_id + '"]', timeout=20_000)
    page.locator('button[data-cc-lot="' + lot_id + '"]').click()
    page.wait_for_function(
        """() => {
          const body = document.getElementById('mt-lot-detail-body');
          return !!(body && (body.textContent || '').indexOf('可用') >= 0);
        }"""
    )
    page.locator("#mt-quarantine-reason").fill("browser-quarantine")
    page.locator("#mt-quarantine-btn").wait_for(state="visible", timeout=10_000)
    page.locator("#mt-quarantine-btn").click()
    page.locator("dialog#mt-confirm[open]").wait_for(timeout=10_000)
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function(
        """() => {
          const rel = document.getElementById('mt-release-quarantine-btn');
          return rel && !rel.hidden;
        }""",
        timeout=60_000,
    )
    page.wait_for_function(
        """() => {
          const body = document.getElementById('mt-lot-detail-body');
          return !!(body && (body.textContent || '').indexOf('隔離') >= 0 && body.textContent.indexOf('是') >= 0);
        }"""
    )