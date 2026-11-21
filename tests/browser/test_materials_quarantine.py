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


def test_quarantine_history_shows_local_timestamps(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
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

    def quarantine_and_confirm(reason: str) -> None:
        page.locator("#mt-quarantine-reason").fill(reason)
        visible = page.locator("#mt-quarantine-btn")
        release = page.locator("#mt-release-quarantine-btn")
        btn = visible if visible.is_visible() else release
        btn.wait_for(state="visible", timeout=10_000)
        btn.click()
        page.locator("dialog#mt-confirm[open]").wait_for(timeout=10_000)
        page.locator("#mt-confirm-ok").click()

    quarantine_and_confirm("browser-quarantine")
    page.wait_for_function(
        """() => {
          const rel = document.getElementById('mt-release-quarantine-btn');
          return rel && !rel.hidden;
        }""",
        timeout=60_000,
    )
    page.wait_for_function(
        """() => {
          const items = document.querySelectorAll('#mt-lot-detail-body .mt-list li');
          if (items.length < 1) return false;
          const t = items[0].textContent || '';
          return t.indexOf('Invalid Date') < 0 && /\\d/.test(t);
        }"""
    )

    quarantine_and_confirm("browser-release")
    page.wait_for_function(
        """() => {
          const qBtn = document.getElementById('mt-quarantine-btn');
          return qBtn && !qBtn.hidden;
        }""",
        timeout=60_000,
    )
    page.wait_for_function(
        """() => {
          const items = document.querySelectorAll('#mt-lot-detail-body .mt-list li');
          if (items.length < 2) return false;
          for (const li of items) {
            const t = li.textContent || '';
            if (t.indexOf('Invalid Date') >= 0 || !/\\d/.test(t)) return false;
          }
          return true;
        }"""
    )


def test_quarantine_history_missing_at_shows_dash(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    import re
    from urllib.parse import urlparse

    page = admin_page
    headers = {"X-Tenant-Id": TENANT}
    lot_id = _seed_lot(admin_server, headers)

    def inject_history(route) -> None:  # noqa: ANN001
        path = urlparse(route.request.url).path
        if route.request.method != "GET" or not path.endswith(f"/api/materials/lots/{lot_id}"):
            route.continue_()
            return
        response = route.fetch()
        data = response.json()
        data["quarantineHistory"] = [
            {
                "eventType": "material.quarantine",
                "actor": "fixture",
                "reason": "no-at",
                "at": None,
            },
            {
                "eventType": "material.release_quarantine",
                "actor": "fixture",
                "reason": "empty-at",
                "at": "",
            },
        ]
        route.fulfill(
            status=response.status,
            content_type="application/json",
            body=json.dumps(data),
        )

    page.route(re.compile(rf"/api/materials/lots/{re.escape(lot_id)}$"), inject_history)
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lots-wrap")
    page.wait_for_selector('button[data-cc-lot="' + lot_id + '"]', timeout=20_000)
    page.locator('button[data-cc-lot="' + lot_id + '"]').click()
    page.wait_for_function(
        """() => {
          const items = document.querySelectorAll('#mt-lot-detail-body .mt-list li');
          return items.length === 2;
        }""",
        timeout=20_000,
    )
    texts = page.locator("#mt-lot-detail-body .mt-list li").all_text_contents()
    assert len(texts) == 2
    for text in texts:
        assert "Invalid Date" not in text
        assert text.rstrip().endswith("—")