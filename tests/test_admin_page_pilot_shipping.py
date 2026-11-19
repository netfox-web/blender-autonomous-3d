"""Admin page /admin/pilot-shipping: shell, assets, feature declaration, and static UI checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.admin_pages.pilot_shipping import FEATURES
from fox3d.api import create_app
from tests.test_pilot_packing_api import HEADERS, TENANT, _seed_release_receipt_and_wo

STATIC_PAGES = Path(__file__).resolve().parents[1] / "src" / "fox3d" / "static" / "pages"


@pytest.fixture()
def client(platform: Any) -> TestClient:
    return TestClient(create_app(platform))


def test_pilot_shipping_page_and_assets(client: TestClient) -> None:
    assert FEATURES == {"pilot-shipping": "/admin/pilot-shipping"}
    page = client.get("/admin/pilot-shipping")
    assert page.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in page.text
    assert "/admin/recipes/assets/fox3d-shell.css" in page.text
    assert "/admin/pages/assets/pilot-shipping.js" in page.text
    assert "/admin/pages/assets/pilot-shipping.css" in page.text
    assert 'aria-label="工作台導覽"' not in page.text
    assert "<style" not in page.text

    for name in ("pilot-shipping.js", "pilot-shipping.css"):
        res = client.get(f"/admin/pages/assets/{name}")
        assert res.status_code == 200 and res.content


def test_pilot_shipping_feature_becomes_page(client: TestClient) -> None:
    index = client.get("/api/admin/features").json()
    ps = next(f for f in index["features"] if f["id"] == "pilot-shipping")
    assert ps["kind"] == "page"
    assert ps["href"] == "/admin/pilot-shipping"
    assert "/admin/pilot-shipping" in ps["prefixes"]
    assert "/api/pilot/pallets" in ps["prefixes"]
    assert "/api/pilot/shipments" in ps["prefixes"]
    assert "/api/pilot/carrier-quotes" in ps["prefixes"]


def test_pilot_shipping_page_apis_with_tenant_header(client: TestClient, platform: Any) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform, tenant=TENANT)
    created = client.post(
        f"/api/pilot/work-orders/{wo['workOrderId']}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "page-smoke-1"},
    )
    assert created.status_code == 200
    cid = created.json()["cartonIds"][0]

    for path in (
        "/api/pilot/cartons",
        "/api/pilot/pallets",
        "/api/pilot/shipments",
        "/api/pilot/carrier-quotes",
        f"/api/pilot/cartons/{cid}/label",
    ):
        res = client.get(path, headers=HEADERS)
        assert res.status_code == 200, f"{path} -> {res.status_code}"


def test_pilot_shipping_js_habits_and_html_ids() -> None:
    import re

    html = (STATIC_PAGES / "pilot-shipping.html").read_text(encoding="utf-8")
    js = (STATIC_PAGES / "pilot-shipping.js").read_text(encoding="utf-8")

    # Never use innerHTML; use textContent / DOM nodes.
    assert "innerHTML" not in js

    # Confirm blocks snapshot tenant + payload and lock inputs.
    assert "ctl.snapshot = {" in js
    assert "tenant: activeTenant" in js
    assert "lockInputs(true)" in js and "lockInputs(false)" in js

    # In-flight disable and network error handling.
    assert "actionInFlight" in js
    assert "el.disabled = true" in js and "el.disabled = false" in js
    assert "連線失敗" in js and "網路錯誤" in js

    # quote_stale must be explicitly marked as expired/unavailable, never usable.
    assert "報價過期（quote_stale，不可用）" in js

    # Every $('...') id in JS exists in pilot-shipping.html.
    html_ids = {m.group(1) for m in re.finditer(r'\bid="([^"]+)"', html)}
    js_ids = {m.group(1) for m in re.finditer(r"""\$\(['"]([a-zA-Z0-9_-]+)['"]\)""", js)}
    missing = sorted(js_ids - html_ids)
    assert not missing, f"pilot-shipping.js references missing HTML ids: {missing}"
