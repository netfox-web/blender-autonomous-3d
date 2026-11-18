from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.browser


def open_studio(page: Page, server: dict[str, Any]) -> None:
    page.goto(server['base_url'] + '/admin/recipes/scenes', wait_until='domcontentloaded')
    page.wait_for_function("() => document.querySelectorAll('#matrix-scenes-list input').length > 0")
    page.locator('[data-tab="tab-matrix"]').click()


def test_batch_inflight_and_network_error(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    pending: list[Route] = []
    page.route('**/api/ecommerce-scenes/batches', lambda route: pending.append(route))
    open_studio(page, admin_server)
    page.locator('#blender-matrix-btn').click()
    page.wait_for_function("() => document.querySelector('#blender-matrix-btn').disabled")
    assert len(pending) == 1
    page.locator('#blender-matrix-btn').evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles:true}))")
    assert len(pending) == 1
    first_key = json.loads(pending[0].request.post_data or '{}')['idempotencyKey']
    pending[0].abort()
    page.wait_for_function("() => document.querySelector('#blender-matrix-btn').disabled")
    # The automatic network retry carries the same key.
    page.wait_for_function("() => document.querySelector('#blender-matrix-btn').disabled")
    page.wait_for_event('request', predicate=lambda req: req.method == 'POST' and req.url.endswith('/batches')) if len(pending) < 2 else None
    assert len(pending) == 2
    assert json.loads(pending[1].request.post_data or '{}')['idempotencyKey'] == first_key
    pending[1].abort()
    page.wait_for_function("() => !document.querySelector('#blender-matrix-btn').disabled")
    assert page.locator('#studio-notice').evaluate("el => el.classList.contains('error')")


def test_cancelled_batch_is_not_reported_as_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    batch = {'batchId': 'batch1', 'state': 'cancelled', 'completed': 1, 'total': 1,
             'succeeded': 0, 'failed': 0, 'items': [{'itemId': 'item_01', 'state': 'cancelled',
             'sceneName': 'Scene', 'themeLabel': 'Theme', 'viewLabel': 'View', 'index': 1}]}
    seen: list[str] = []

    def handle(route: Route) -> None:
        seen.append(route.request.method)
        route.fulfill(json=batch)

    page.route('**/api/ecommerce-scenes/batches', handle)
    page.route('**/api/ecommerce-scenes/batches/batch1', handle)
    open_studio(page, admin_server)
    page.locator('#blender-matrix-btn').click()
    page.wait_for_function("() => document.querySelector('#blender-batch-status').textContent.includes('已取消')")
    assert '已完成' not in page.locator('#blender-batch-status').inner_text()
    assert page.locator('#blender-batch-status').evaluate("el => el.classList.contains('bad')")
    assert seen.count('POST') == 1


def test_cancel_button_posts_snapshot_and_shows_cancelled(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    running = {'batchId': 'batch2', 'state': 'running', 'completed': 0, 'total': 1,
               'succeeded': 0, 'failed': 0, 'items': []}
    cancelled = {**running, 'state': 'cancelled', 'completed': 1, 'cancelled': 1}
    calls: list[str] = []
    page.route('**/api/ecommerce-scenes/batches', lambda route: route.fulfill(json=running))
    page.route('**/api/ecommerce-scenes/batches/batch2', lambda route: route.fulfill(json=running))

    def cancel(route: Route) -> None:
        calls.append(route.request.url)
        route.fulfill(json=cancelled)

    page.route('**/api/ecommerce-scenes/batches/batch2/cancel', cancel)
    page.on('dialog', lambda dialog: dialog.accept())
    open_studio(page, admin_server)
    page.locator('#blender-matrix-btn').click()
    page.locator('#batch-cancel').click()
    page.wait_for_function("() => document.querySelector('#blender-batch-status').textContent.includes('已取消')")
    assert len(calls) == 1
    assert '已完成' not in page.locator('#blender-batch-status').inner_text()
