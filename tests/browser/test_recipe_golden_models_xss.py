"""Hostile API values remain inert across the three product pages."""
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser
PAYLOAD = '\"><img src=x onerror=window.__xss=1>'


def inert(page):
    page.wait_for_timeout(250)
    assert page.evaluate('window.__xss || 0') == 0
    assert page.locator('img[src="x"], [onerror]').count() == 0


def test_recipe_family_and_product_fields(admin_page, admin_server):
    def intercept(route):
        if route.request.method == 'POST' and urlparse(route.request.url).path.endswith('/validate'):
            return route.fulfill(status=400, json={'detail': PAYLOAD})
        if route.request.method != 'GET' or urlparse(route.request.url).path != '/api/recipe-library':
            return route.fallback()
        response = route.fetch()
        data = response.json()
        key = next(iter(data['families']))
        data['families'][PAYLOAD] = data['families'].pop(key)
        data['families'][PAYLOAD]['name'] = PAYLOAD
        if data['items']:
            item = data['items'][0]
            item['draft']['family'] = PAYLOAD
            item['draft']['name'] = PAYLOAD
            item['draft']['sku'] = PAYLOAD
            data['fields'][PAYLOAD] = {'label': PAYLOAD, 'unit': 'text'}
            item['draft']['values'][PAYLOAD] = {'value': PAYLOAD, 'evidence': PAYLOAD}
            item['revision'] = PAYLOAD
            item['status'] = 'DRAFT'
        route.fulfill(response=response, json=data)

    page = admin_page
    page.add_init_script("""window.__validateDisabled = false; const originalFetch = window.fetch;
      window.fetch = function(url, init) { if (String(url).endsWith('/validate'))
        window.__validateDisabled = document.getElementById('validate-button').disabled;
        return originalFetch.apply(this, arguments); };""")
    page.route('**/api/recipe-library**', intercept)
    page.goto(admin_server['base_url'] + '/admin/recipes', wait_until='domcontentloaded')
    expect(page.locator('#family-filter option').filter(has_text=PAYLOAD)).to_have_count(1)
    expect(page.locator('#new-family option').filter(has_text=PAYLOAD)).to_have_attribute('value', PAYLOAD)
    expect(page.locator('#product-list')).to_contain_text(PAYLOAD)
    expect(page.locator('#detail')).to_contain_text(PAYLOAD)
    expect(page.locator('[data-field]').filter(has_text=PAYLOAD)).to_have_count(0)
    assert page.locator('[data-field]').evaluate_all('(els) => els.some(e => e.dataset.field === ' + repr(PAYLOAD) + ')')
    page.locator('#specs-tab').click()
    page.locator('#validate-button').click()
    expect(page.locator('#notice')).to_have_text(PAYLOAD)
    assert page.evaluate('window.__validateDisabled')
    expect(page.locator('#validate-button')).to_be_enabled()
    inert(page)


def test_golden_api_text_and_failed_export(admin_page, admin_server):
    page = admin_page
    page.add_init_script("""window.__postDisabled = false; const originalFetch = window.fetch;
      window.fetch = function(url, init) { if (String(url).includes('/exports') && init?.method === 'POST')
        window.__postDisabled = document.getElementById('dna-export-btn').disabled;
        return originalFetch.apply(this, arguments); };""")

    def intercept(route):
        path = urlparse(route.request.url).path
        if path == '/api/recipe-library/golden':
            return route.fulfill(json={'skus': [PAYLOAD], 'versions': [{'id': 'fixture', 'label': PAYLOAD}]})
        if path.endswith('/plan'):
            return route.fulfill(json={'ready': False, 'blenderAvailable': False, 'package': {'truth': PAYLOAD, 'reason': PAYLOAD}, 'golden': {'spec': {'components': []}}})
        if path.endswith('/exports'):
            return route.fulfill(status=400, json={'detail': PAYLOAD})
        if path.endswith('/status'):
            return route.fulfill(json={'state': 'failed', 'generated': False, 'error': PAYLOAD})
        return route.fallback()

    page.route('**/api/**', intercept)
    page.add_init_script('window.mountRecipeViewer = () => () => {};')
    page.goto(admin_server['base_url'] + '/admin/recipes/golden', wait_until='domcontentloaded')
    expect(page.locator('#sku')).to_have_value(PAYLOAD)
    expect(page.locator('#version')).to_contain_text(PAYLOAD)
    expect(page.locator('#truth')).to_contain_text(PAYLOAD)
    expect(page.locator('#progress')).to_contain_text(PAYLOAD)
    page.locator('#dna-export-btn').click()
    expect(page.locator('#notice')).to_have_text(PAYLOAD)
    assert page.evaluate('window.__postDisabled')
    expect(page.locator('#dna-export-btn')).to_be_enabled()
    inert(page)


def test_model_catalog_fields_and_failed_scan(admin_page, admin_server):
    page = admin_page
    fail_network = [False]
    page.add_init_script("""window.__postDisabled = false; const originalFetch = window.fetch;
      window.fetch = function(url, init) { if (String(url).includes('/catalog/refresh'))
        window.__postDisabled = document.getElementById('scan').disabled;
        return originalFetch.apply(this, arguments); };""")

    def intercept(route):
        path = urlparse(route.request.url).path
        if path == '/api/product-models':
            response = route.fetch()
            data = response.json()
            data['items'].append({'id': 'fixture-model', 'draft': {'name': PAYLOAD, 'variants': []}, 'classification': {'path': [PAYLOAD], 'categoryId': 'unclassified'}, 'templateState': 'DRAFT', 'readiness': {'previewReady': False}, 'revision': PAYLOAD})
            return route.fulfill(response=response, json=data)
        if path == '/api/product-models/catalog/refresh':
            if fail_network[0]:
                return route.abort('failed')
            return route.fulfill(status=400, json={'detail': PAYLOAD})
        if path == '/api/product-models/catalog':
            response = route.fetch()
            data = response.json()
            data.update(configured=True, items=[{'id': 'fixture', 'name': PAYLOAD, 'family': 'cabinet', 'subtype': 'open', 'fileCount': PAYLOAD}], total=1)
            return route.fulfill(response=response, json=data)
        if path == '/api/product-models/catalog/fixture/files':
            return route.fulfill(json={'group': {'folder': PAYLOAD}, 'items': [{'id': 'fixture', 'name': PAYLOAD, 'path': PAYLOAD, 'extension': '.txt'}], 'total': 1})
        return route.fallback()

    page.route('**/api/product-models**', intercept)
    page.goto(admin_server['base_url'] + '/admin/recipes/models', wait_until='domcontentloaded')
    expect(page.locator('#groups')).to_contain_text(PAYLOAD)
    expect(page.locator('#masters')).to_contain_text(PAYLOAD)
    page.locator('#show-materials').click()
    page.locator('#groups button').first.click()
    expect(page.locator('#source-files')).to_contain_text(PAYLOAD)
    page.locator('#scan').click()
    expect(page.locator('#notice')).to_have_text(PAYLOAD)
    assert page.evaluate('window.__postDisabled')
    expect(page.locator('#scan')).to_be_enabled()
    fail_network[0] = True
    page.locator('#scan').click()
    expect(page.locator('#notice')).to_have_class('error')
    assert '掃描完成' not in page.locator('#notice').inner_text()
    expect(page.locator('#scan')).to_be_enabled()
    inert(page)
