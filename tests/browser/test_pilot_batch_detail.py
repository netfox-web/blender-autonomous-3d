"""Pilot batch detail renders warnings and request failures."""
import json

import pytest

pytestmark = pytest.mark.browser


def test_batch_detail_hold_and_failure(admin_page, admin_server):
    page = admin_page
    def route_request(route):
        path = route.request.url.split('?')[0]
        if path.endswith('/api/pilot/batches'):
            data = {'items': [{'batchId': 'batch-1', 'state': 'HOLD'}]}
        elif path.endswith('/batch-1/units'):
            data = {'items': [{'state': 'HOLD', 'cartonId': 'carton-1'}], 'total': 1}
        elif path.endswith('/batch-1/readiness'):
            data = {'decision': 'HOLD_REWORK', 'staleLineage': True, 'blockers': ['stale_lineage']}
        elif path.endswith('/batch-1/genealogy'):
            data = {'units': [{'unitExecutionId': 'unit-1'}]}
        elif path.endswith('/batch-1'):
            data = {'batchId': 'batch-1', 'state': 'HOLD'}
        else:
            route.continue_()
            return
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))
    page.route('**/api/pilot/batches**', route_request)
    page.goto(admin_server['base_url'] + '/admin/pilot')
    page.locator('#batches button').click()
    detail = page.locator('#batch-detail')
    detail.get_by_text('stale_lineage').wait_for()
    assert 'warn' in detail.get_attribute('class')
    assert detail.evaluate("el => getComputedStyle(el).borderTopStyle") == 'solid'
    assert 'unit-1' in detail.inner_text() and 'carton-1' in detail.inner_text()
    page.route('**/api/pilot/batches/batch-1/readiness', lambda route: route.abort())
    page.locator('#batches button').click()
    detail.get_by_text('批次明細讀取失敗').wait_for()
    assert 'warn' in detail.get_attribute('class')


def test_batch_list_shows_returned_count_and_total(admin_page, admin_server):
    page = admin_page
    items = [{'batchId': f'batch-{i}', 'state': 'PLANNED'} for i in range(100)]
    page.route('**/api/pilot/batches', lambda route: route.fulfill(
        status=200, content_type='application/json',
        body=json.dumps({'items': items, 'total': 101}),
    ))
    page.goto(admin_server['base_url'] + '/admin/pilot')
    page.get_by_text('顯示 100 / 共 101 筆', exact=True).wait_for()
    assert page.locator('#batches button').count() == 100
