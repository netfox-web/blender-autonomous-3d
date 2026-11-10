"""Stored and hostile API data must remain inert on the legacy workspaces."""
from __future__ import annotations

import io
import os
from pathlib import Path

import httpx
import pytest
from PIL import Image
from playwright.sync_api import expect

from tests.browser.conftest import TENANT

pytestmark = pytest.mark.browser
PAYLOAD = '<img src=x onerror=window.__fox3dXss=1>-legacy-xss'
ATTRIBUTE = '" onmouseover="window.__fox3dXss=1" data-injected="'


@pytest.fixture(scope="module")
def legacy_data(admin_server):
    base = admin_server['base_url']
    with httpx.Client(base_url=base, headers={'X-Tenant-Id': TENANT}) as client:
        def post(path, **kwargs):
            response = client.post(path, **kwargs)
            assert response.is_success, response.text
            return response.json()

        recipe = post('/api/recipe-library/products', json={'expectedRevision': 0, 'draft': {
            'sku': PAYLOAD, 'name': PAYLOAD, 'family': 'STACKED_HINGED_CABINET'}})
        model = post('/api/product-models', json={'expectedRevision': 0, 'draft': {
            'name': PAYLOAD, 'family': 'cabinet', 'variants': [{'sku': PAYLOAD}]}})
        image = io.BytesIO()
        Image.new('RGB', (500, 500), 'blue').save(image, 'PNG')
        asset = post('/api/print-workspace/assets/upload', files={'file': (PAYLOAD + '.png', image.getvalue(), 'image/png')})
        response = client.put('/api/product-models/assets/' + asset['id'] + '/usage', json={
            'role': 'ARTWORK', 'note': 'Synthetic test artwork', 'expectedRevision': 0})
        assert response.is_success, response.text
        job = post('/api/print-workspace/jobs', json={'draft': {
            'sku': 'LEGACY-XSS', 'name': PAYLOAD, 'layout': 'THREE_DOOR',
            'panels': [{'label': PAYLOAD, 'assetId': asset['id'], 'page': 0, 'rotation': 0,
                        'imageWidthMm': 100, 'imageHeightMm': 100} for _ in range(3)]}})
    return {'base': base, 'recipe': recipe, 'model': model, 'asset': asset, 'job': job}


def assert_inert(page):
    assert page.evaluate('window.__fox3dXss || 0') == 0
    assert page.locator('img[src="x"]').count() == 0
    assert page.locator('[data-injected]').count() == 0


@pytest.mark.parametrize('width', [400, 1440])
@pytest.mark.parametrize('kind', ['recipes', 'models', 'print', 'golden'])
def test_legacy_pages(admin_page, legacy_data, kind, width, tmp_path):
    page = admin_page
    page.set_viewport_size({'width': width, 'height': 900})
    paths = {'recipes': '/admin/recipes', 'models': '/admin/recipes/models',
             'print': '/admin/recipes/print', 'golden': '/admin/recipes/golden'}
    if kind == 'golden':
        # Golden SKUs are a fixed server catalog; exercise the same rendering with hostile API data.
        def golden_catalog(route):
            response = route.fetch()
            data = response.json()
            data['versions'][0]['label'] = PAYLOAD
            data['versions'].append({'id': ATTRIBUTE, 'label': PAYLOAD})
            route.fulfill(response=response, json=data)
        page.route('**/api/recipe-library/golden', golden_catalog)
    page.goto(legacy_data['base'] + paths[kind], wait_until='domcontentloaded')
    if kind == 'recipes':
        page.locator('#product-list').get_by_text(PAYLOAD, exact=True).first.wait_for()
        assert page.locator('#product-list').get_by_text(PAYLOAD, exact=True).count() >= 1
    elif kind == 'models':
        page.locator('#masters').get_by_text(PAYLOAD, exact=False).first.wait_for()
        page.locator('#masters').get_by_text(PAYLOAD, exact=False).first.click()
        assert page.locator('.variant-sku').first.input_value() == PAYLOAD
    elif kind == 'print':
        page.locator('#jobs').get_by_text(PAYLOAD, exact=False).first.wait_for()
        assert PAYLOAD in page.locator('#assets').inner_text()
        page.locator('#jobs button').filter(has_text=PAYLOAD).click()
        expect(page.locator('#panels input[data-key=label]').first).to_have_value(PAYLOAD)
    else:
        page.locator('#version option').first.wait_for(state='attached')
        assert page.locator('#version option').first.text_content() == PAYLOAD
        assert page.locator('#version option').last.get_attribute('value') == ATTRIBUTE
        page.locator('#boards table').wait_for()
    assert_inert(page)
    assert page.evaluate('document.documentElement.scrollWidth') <= width
    output = Path(os.environ.get('FOX3D_XSS_SCREENSHOTS', tmp_path))
    output.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output / f'{kind}-{width}.png'), full_page=True)


def test_print_hostile_ids_are_attribute_values(admin_page, legacy_data):
    page = admin_page
    asset = {**legacy_data['asset'], 'id': ATTRIBUTE}
    job = {**legacy_data['job'], 'id': ATTRIBUTE}
    page.route('**/api/print-workspace/assets', lambda route: route.fulfill(json={'items': [asset]}))
    page.route('**/api/print-workspace/jobs', lambda route: route.fulfill(json={'items': [job]}))
    page.goto(legacy_data['base'] + '/admin/recipes/print')
    button = page.locator('#jobs button').first
    button.wait_for()
    assert button.get_attribute('data-id') == ATTRIBUTE
    button.hover()
    # New panels are built from the asset list on initial load.
    option = page.locator('#panels select[data-key=assetId] option').nth(1)
    assert option.get_attribute('value') == ATTRIBUTE
    assert_inert(page)
