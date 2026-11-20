from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import TENANT

pytestmark = pytest.mark.browser


def test_create_approve_and_release(admin_page: Page, admin_server: dict[str, Any]) -> None:
    product = admin_server['platform'].kd.build_sku(tenant_id=TENANT, kind='OPEN_SHELF')
    page = admin_page
    page.goto(admin_server['base_url'] + '/admin/releases')
    page.locator('#product').fill(product['productId'])
    page.locator('#create').click()
    expect(page.locator('#detail')).to_contain_text('DRAFT')
    for action, status in [('validate', 'VALIDATED'), ('submit', 'WAITING_APPROVAL'),
                           ('approve', 'APPROVED_FOR_MANUAL_RELEASE'), ('release-manual', 'RELEASED_FOR_MANUAL_EXECUTION')]:
        page.locator(f'[data-action="{action}"]').click()
        assert page.locator('#tenant').is_disabled()
        page.locator('#confirm').click()
        expect(page.locator('#detail')).to_contain_text(status)
