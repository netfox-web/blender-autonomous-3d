"""Readiness history and snapshot panels, including a 400px width check."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import TENANT

pytestmark = pytest.mark.browser

XSS = '<img src=x onerror="window.__fox3dXss=1">'


def _row_text(page: Page, table_id: str, needle: str) -> str:
    row = page.locator(f"#{table_id} tr", has_text=needle)
    row.first.wait_for()
    return row.first.inner_text()


def test_readiness_panels_load_live_data_without_horizontal_scroll(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    base = admin_server["base_url"]
    with httpx.Client(base_url=base, headers={"X-Tenant-Id": TENANT}) as client:
        advanced = client.post(
            "/api/release/advance",
            json={
                "entityId": "hist-live-1",
                "target": "ENGINEERING_VALID",
                "actor": "browser-history",
                "entity": {"skuId": "hist-live-1", "engineeringHash": "eng-live"},
            },
        )
        assert advanced.status_code == 200, advanced.text
        imported = client.post(
            "/api/commerce/import",
            json={
                "kind": "logistics",
                "source": "MANUAL",
                "rows": [{"snapshotId": "snap-live-1", "zone": "TW-HIST", "baseFee": 80}],
            },
        )
        assert imported.status_code == 200, imported.text

    page.set_viewport_size({"width": 400, "height": 900})
    page.goto(base + "/admin/readiness", wait_until="domcontentloaded")
    page.wait_for_selector("#rd-history-table td", timeout=20_000)
    page.wait_for_selector("#rd-snap-table td", timeout=20_000)
    assert "hist-live-1" in page.locator("#rd-history-table").inner_text()
    assert "snap-live-1" in page.locator("#rd-snap-table").inner_text()
    assert "hist-live-1" in page.locator("#rd-approvals-table").inner_text()
    for element_id in ("rd-history-table", "rd-approvals-table", "rd-snap-table"):
        overflow = page.eval_on_selector(f"#{element_id}", "el => getComputedStyle(el).overflowX")
        assert overflow in {"auto", "scroll"}
    assert page.evaluate("document.documentElement.scrollWidth") <= 400


def test_stale_and_blocked_are_not_shown_as_released(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    long_id = "H" * 180

    def fulfill(route, payload: dict[str, Any]) -> None:  # noqa: ANN001
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route(
        "**/api/release/events**",
        lambda route: fulfill(
            route,
            {
                "items": [
                    {
                        "entityId": long_id,
                        "decision": "STALE",
                        "stale": True,
                        "actor": XSS,
                        "approvedAt": "2026-01-01T00:00:00+00:00",
                    },
                    {
                        "entityId": "blocked-1",
                        "decision": "BLOCKED",
                        "blocked": True,
                        "actor": "ops",
                        "approvedAt": "2026-01-02T00:00:00+00:00",
                    },
                    {
                        "entityId": "ok-1",
                        "decision": "APPROVED_FOR_EXPORT",
                        "stale": False,
                        "released": True,
                        "actor": "ops",
                        "approvedAt": "2026-01-03T00:00:00+00:00",
                    },
                ],
                "total": 3,
                "offset": 0,
                "limit": 20,
                "hasMore": False,
            },
        ),
    )
    page.route(
        "**/api/release/approvals**",
        lambda route: fulfill(
            route,
            {
                "items": [
                    {
                        "entityId": "stale-ok",
                        "state": "APPROVED_FOR_EXPORT",
                        "stale": True,
                        "released": False,
                        "actor": "ops",
                        "approvedAt": "2026-01-04T00:00:00+00:00",
                    },
                    {
                        "entityId": "live-ok",
                        "state": "APPROVED_FOR_EXPORT",
                        "stale": False,
                        "released": True,
                        "actor": "ops",
                        "approvedAt": "2026-01-05T00:00:00+00:00",
                    },
                ],
                "total": 2,
            },
        ),
    )
    page.route(
        "**/api/commerce/snapshots**",
        lambda route: fulfill(
            route,
            {
                "items": [
                    {
                        "kind": "fx",
                        "snapshotId": "S" * 180,
                        "source": "MANUAL",
                        "effectiveAt": "2020-01-01",
                        "expiresAt": "2099-01-01",
                        "importedAt": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "total": 1,
                "offset": 0,
                "limit": 20,
                "hasMore": False,
            },
        ),
    )

    page.set_viewport_size({"width": 400, "height": 900})
    page.goto(admin_server["base_url"] + "/admin/readiness", wait_until="domcontentloaded")
    page.wait_for_selector("#rd-history-table [data-verdict=stale]", timeout=20_000)
    page.wait_for_selector("#rd-snap-table td", timeout=20_000)

    stale_event = _row_text(page, "rd-history-table", long_id)
    assert "已過期" in stale_event
    assert "已放行" not in stale_event
    blocked = _row_text(page, "rd-history-table", "blocked-1")
    assert "已封鎖" in blocked
    assert "已放行" not in blocked
    released = _row_text(page, "rd-history-table", "ok-1")
    assert "已放行" in released

    stale_approval = _row_text(page, "rd-approvals-table", "stale-ok")
    assert "已過期" in stale_approval
    assert "已放行" not in stale_approval
    assert page.locator("#rd-approvals-table [data-verdict=stale]").count() >= 1
    live = _row_text(page, "rd-approvals-table", "live-ok")
    assert "已放行" in live

    assert page.evaluate("window.__fox3dXss || 0") == 0
    assert page.locator('img[src="x"]').count() == 0
    assert page.evaluate("document.documentElement.scrollWidth") <= 400


def test_switch_tenant_network_failure_clears_old_tables(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    def handle(route):  # noqa: ANN001
        if route.request.headers.get("x-tenant-id") == "tenant-new":
            route.abort()
        else:
            row = {"entityId": "old-private", "state": "APPROVED_FOR_EXPORT", "released": True, "snapshotId": "old-private"}
            route.fulfill(json={"items": [row], "total": 1, "offset": 0, "hasMore": False})
    for pattern in ("**/api/release/events**", "**/api/release/approvals**", "**/api/commerce/snapshots**"):
        page.route(pattern, handle)
    page.goto(admin_server["base_url"] + "/admin/readiness", wait_until="domcontentloaded")
    for table in ("rd-history-table", "rd-approvals-table", "rd-snap-table"):
        page.locator(f"#{table} td").first.wait_for()
    page.locator("#rd-tenant").fill("tenant-new")
    page.locator("#rd-tenant").dispatch_event("change")
    for status in ("rd-history-status", "rd-approvals-status", "rd-snap-status"):
        expect(page.locator(f"#{status}")).to_contain_text("載入失敗")
    for table in ("rd-history-table", "rd-approvals-table", "rd-snap-table"):
        assert page.locator(f"#{table}").is_hidden()
        assert "old-private" not in (page.locator(f"#{table}").text_content() or "")
