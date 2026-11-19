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


def _history_batch(idx: int, *, state: str = 'completed', succeeded: int = 1, failed: int = 0) -> dict[str, Any]:
    bid = f'hist_{idx:02d}'
    return {
        'batchId': bid,
        'cabinetName': f'櫃體 {bid}',
        'cabinetSku': f'SKU-{bid}',
        'createdAt': f'2026-11-18T10:{idx:02d}:00Z',
        'state': state,
        'total': 1,
        'completed': 1,
        'succeeded': succeeded,
        'failed': failed,
        'items': [],
    }


def test_batch_history_load_more_and_state_filter_single_inflight(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    page1 = [
        _history_batch(1, state='completed', succeeded=1, failed=0),
        _history_batch(2, state='failed', succeeded=0, failed=1),
        _history_batch(3, state='cancelled', succeeded=0, failed=0),
        *[_history_batch(i) for i in range(4, 16)],
    ]
    page2 = [_history_batch(i) for i in range(16, 19)]
    pending_more: list[Route] = []
    history_queries: list[str] = []

    def handle_history(route: Route) -> None:
        url = route.request.url
        if route.request.method != 'GET' or '/api/ecommerce-scenes/batches?' not in url:
            route.fallback()
            return
        q = url.split('?', 1)[1]
        history_queries.append(q)
        if 'state=failed' in q:
            route.fulfill(json={'items': [page1[1]], 'total': 1, 'offset': 0, 'limit': 15, 'skipped': 0})
            return
        if 'offset=15' in q:
            pending_more.append(route)
            return
        route.fulfill(json={'items': page1, 'total': 18, 'offset': 0, 'limit': 15, 'skipped': 1})

    page.route('**/api/ecommerce-scenes/batches?**', handle_history)
    page.route('**/api/ecommerce-scenes/batches/hist_02', lambda route: route.fulfill(json=page1[1]))
    page.route('**/api/ecommerce-scenes/batches/hist_01', lambda route: route.fulfill(json=page1[0]))
    open_studio(page, admin_server)
    page.wait_for_function("() => document.querySelectorAll('#batch-history-list .batch-history-row').length === 15")

    failed_row = page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_02"]')
    cancelled_row = page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_03"]')
    assert '失敗' in failed_row.locator('.batch-history-status').inner_text()
    assert '完成' not in failed_row.locator('.batch-history-status').inner_text()
    assert '已取消' in cancelled_row.locator('.batch-history-status').inner_text()
    assert '完成' not in cancelled_row.locator('.batch-history-status').inner_text()

    failed_row.locator('.history-open-btn').click()
    page.wait_for_function("() => document.querySelector('#blender-batch-status').textContent.includes('失敗')")
    assert '已完成' not in page.locator('#blender-batch-status').inner_text()
    assert page.locator('#blender-batch-status').evaluate("el => el.classList.contains('bad')")

    zip_href = page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_01"] .history-zip-link').get_attribute('href')
    assert zip_href == '/api/ecommerce-scenes/batches/hist_01/zip?workspace=sonaqueen-home'

    more_btn = page.locator('#batch-history-more')
    assert not more_btn.is_hidden()
    more_btn.click()
    page.wait_for_function("() => document.querySelector('#batch-history-more').disabled")
    assert len(pending_more) == 1
    more_btn.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles:true}))")
    assert len(pending_more) == 1

    pending_more[0].fulfill(json={'items': page2, 'total': 18, 'offset': 15, 'limit': 15, 'skipped': 1})
    page.wait_for_function("() => document.querySelectorAll('#batch-history-list .batch-history-row').length === 18")
    assert more_btn.is_hidden()

    page.select_option('#batch-history-state', 'failed')
    page.wait_for_function("() => document.querySelectorAll('#batch-history-list .batch-history-row').length === 1")
    assert any('state=failed' in q for q in history_queries)


def test_batch_history_delete_confirm_snapshot_and_single_inflight(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    b1 = _history_batch(1, state='completed', succeeded=1)
    b2 = _history_batch(2, state='completed', succeeded=1)
    pending_deletes: list[Route] = []

    page.route(
        '**/api/ecommerce-scenes/batches?**',
        lambda route: route.fulfill(json={'items': [b1, b2], 'total': 2, 'offset': 0, 'limit': 15, 'skipped': 0}),
    )
    page.route('**/api/ecommerce-scenes/batches/hist_01', lambda route: (
        pending_deletes.append(route) if route.request.method == 'DELETE' else route.fulfill(json=b1)
    ))
    page.route('**/api/ecommerce-scenes/batches/hist_02', lambda route: (
        pending_deletes.append(route) if route.request.method == 'DELETE' else route.fulfill(json=b2)
    ))

    open_studio(page, admin_server)
    page.wait_for_function("() => document.querySelectorAll('#batch-history-list .batch-history-row').length === 2")

    page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_01"] .history-delete-btn').click()
    assert page.evaluate("() => document.getElementById('batch-delete-dialog').open") is True
    assert page.evaluate("() => document.getElementById('batch-delete-dialog').returnValue") == ''
    assert page.evaluate("() => document.getElementById('batch-history-list').inert") is True

    # Attempt a late click on the second row's delete button while the modal is open; snapshot must stay on hist_01.
    page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_02"] .history-delete-btn').evaluate(
        "el => el.dispatchEvent(new MouseEvent('click', {bubbles:true}))"
    )

    confirm_btn = page.locator('#batch-delete-confirm')
    confirm_btn.click()
    page.wait_for_function("() => document.getElementById('batch-delete-confirm').disabled")
    assert len(pending_deletes) == 1
    assert pending_deletes[0].request.url.endswith('/api/ecommerce-scenes/batches/hist_01')

    # Second click while DELETE is in flight must not send another request.
    confirm_btn.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles:true}))")
    assert len(pending_deletes) == 1

    pending_deletes[0].fulfill(json={'deleted': 'hist_01'})
    page.wait_for_function("() => document.querySelectorAll('#batch-history-list .batch-history-row').length === 1")
    assert page.evaluate("() => document.getElementById('batch-delete-dialog').open") is False
    assert page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_02"]').count() == 1

    # Opening the dialog again resets returnValue to empty before showModal.
    page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_02"] .history-delete-btn').click()
    assert page.evaluate("() => document.getElementById('batch-delete-dialog').returnValue") == ''
    page.locator('#batch-delete-cancel').click()
    assert len(pending_deletes) == 1

    # Network error on DELETE keeps the row, shows error notice, and re-enables confirm button.
    page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_02"] .history-delete-btn').click()
    confirm_btn.click()
    page.wait_for_function("() => document.getElementById('batch-delete-confirm').disabled")
    assert len(pending_deletes) == 2
    pending_deletes[1].abort()
    page.wait_for_function("() => !document.getElementById('batch-delete-confirm').disabled")
    assert page.locator('#studio-notice').evaluate("el => el.classList.contains('error')")
    assert page.locator('#batch-history-list .batch-history-row[data-batch-id="hist_02"]').count() == 1
