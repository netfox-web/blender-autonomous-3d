"""Playwright E2E tests for /admin/pilot-shipping: pallet -> shipment draft -> handoff, 400px layout, quote_stale UI, and network error recovery."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

from tests.browser.conftest import TENANT, XSS_PROBE, XSS_STRING
from tests.test_pilot_packing_api import _seed_release_receipt_and_wo

pytestmark = pytest.mark.browser


def _seed_shipping_cartons(admin_server: dict[str, Any], *, tenant: str = TENANT, count: int = 2) -> list[str]:
    plat = admin_server["platform"]
    _rel, wo = _seed_release_receipt_and_wo(plat, tenant=tenant)
    wo_id = wo["workOrderId"]
    base = admin_server["base_url"]
    headers = {"X-Tenant-Id": tenant, "Content-Type": "application/json"}

    req = urllib.request.Request(
        f"{base}/api/pilot/work-orders/{wo_id}/cartons",
        data=json.dumps({"quantity": count, "idempotencyKey": f"pw-ship-{wo_id}"}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        carton_ids = list(json.loads(resp.read().decode("utf-8"))["cartonIds"])

    for cid in carton_ids:
        m_req = urllib.request.Request(
            f"{base}/api/pilot/cartons/{cid}/measured",
            data=json.dumps(
                {"length": 400, "width": 300, "height": 200, "weightKg": 9.5, "source": "MANUAL"}
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(m_req) as resp:
            assert resp.status == 200
    return carton_ids


def _assert_no_horizontal_scroll_at_400px(page: Page) -> None:
    page.set_viewport_size({"width": 400, "height": 800})
    metrics = page.evaluate(
        """() => ({
          docScrollWidth: document.documentElement.scrollWidth,
          docClientWidth: document.documentElement.clientWidth,
          bodyScrollWidth: document.body.scrollWidth,
          bodyClientWidth: document.body.clientWidth,
        })"""
    )
    assert metrics["docScrollWidth"] <= metrics["docClientWidth"], f"400px horizontal overflow: {metrics}"
    assert metrics["bodyScrollWidth"] <= metrics["docClientWidth"], f"400px body overflow: {metrics}"


def test_pilot_shipping_pallet_to_draft_to_handoff_and_400px_no_horizontal_scroll(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    base = admin_server["base_url"]
    carton_ids = _seed_shipping_cartons(admin_server, count=2)

    page.goto(f"{base}/admin/pilot-shipping", wait_until="domcontentloaded")
    page.wait_for_selector(".fx-side", timeout=20_000)
    expect(page.locator("#ps-cartons-table")).to_contain_text(carton_ids[0])

    # Check 400px viewport width before actions.
    _assert_no_horizontal_scroll_at_400px(page)
    page.set_viewport_size({"width": 1280, "height": 900})

    # Step 1: Create pallet plan (建棧板).
    page.locator("#ps-pallet-carton-ids").fill(", ".join(carton_ids))
    page.locator("#ps-pallet-confirm-box").check()
    assert page.locator("#ps-pallet-carton-ids").is_disabled()
    expect(page.locator("#ps-pallet-confirm-summary")).to_contain_text(carton_ids[0])
    with page.expect_response(
        lambda r: "/api/pilot/pallets" in r.url and r.request.method == "POST"
    ) as pallet_resp:
        page.locator("#ps-pallet-submit").click()
    assert pallet_resp.value.status == 200
    pallet_data = pallet_resp.value.json()
    expect(page.locator("#ps-pallet-result")).to_contain_text(pallet_data["palletPlanId"])
    expect(page.locator("#ps-pallets-table")).to_contain_text(pallet_data["palletPlanId"])

    # Step 2: Create shipment draft (建出貨草稿).
    page.locator("#ps-ship-origin").fill("TW-TC")
    page.locator("#ps-ship-destination").fill("TW-TPE")
    page.locator("#ps-ship-carton-ids").fill(", ".join(carton_ids))
    page.locator("#ps-ship-confirm-box").check()
    assert page.locator("#ps-ship-origin").is_disabled()
    with page.expect_response(
        lambda r: r.url.endswith("/api/pilot/shipments") and r.request.method == "POST"
    ) as ship_resp:
        page.locator("#ps-ship-submit").click()
    assert ship_resp.value.status == 200
    ship_data = ship_resp.value.json()
    shipment_id = ship_data["shipmentId"]
    expect(page.locator("#ps-shipment-result")).to_contain_text(shipment_id)
    expect(page.locator("#ps-shipments-table")).to_contain_text("SHIPMENT_DRAFT")

    # Step 3: Manual handoff (交運).
    expect(page.locator("#ps-handoff-shipment-id")).to_have_value(shipment_id)
    page.locator("#ps-handoff-carrier").fill("MANUAL_VAN")
    page.locator("#ps-handoff-tracking").fill("TRK-PW-824")
    page.locator("#ps-handoff-confirm-box").check()
    assert page.locator("#ps-handoff-tracking").is_disabled()
    with page.expect_response(
        lambda r: f"/api/pilot/shipments/{shipment_id}/handoff" in r.url and r.request.method == "POST"
    ) as ho_resp:
        page.locator("#ps-handoff-submit").click()
    assert ho_resp.value.status == 200
    ho_data = ho_resp.value.json()
    assert ho_data["status"] == "HANDED_OFF_MANUAL"
    expect(page.locator("#ps-handoff-result")).to_contain_text("TRK-PW-824")
    expect(page.locator("#ps-shipments-table")).to_contain_text("HANDED_OFF_MANUAL")
    expect(page.locator("#ps-shipments-table")).to_contain_text("TRK-PW-824")

    # Step 4: Import a stale carrier quote and verify it is marked as expired/unavailable, never usable.
    page.locator("#ps-quote-carrier").fill("STALE-CARRIER")
    page.locator("#ps-quote-service").select_option("air")
    page.locator("#ps-quote-charge").fill("320")
    page.locator("#ps-quote-valid-until").fill("2020-01-01")
    page.locator("#ps-quote-confirm-box").check()
    with page.expect_response(
        lambda r: "/api/pilot/carrier-quotes" in r.url and r.request.method == "POST"
    ) as q_resp:
        page.locator("#ps-quote-submit").click()
    assert q_resp.value.status == 200
    expect(page.locator("#ps-quotes-table")).to_contain_text("報價過期（quote_stale，不可用）")

    # Step 5: Query carton label and verify PARTIAL badge.
    page.locator("#ps-label-carton-id").fill(carton_ids[0])
    with page.expect_response(
        lambda r: f"/api/pilot/cartons/{carton_ids[0]}/label" in r.url and r.request.method == "GET"
    ) as lbl_resp:
        page.locator("#ps-label-submit").click()
    assert lbl_resp.value.status == 200
    expect(page.locator("#ps-label-result")).to_contain_text("PARTIAL")
    expect(page.locator("#ps-label-result")).to_contain_text("CODE128")

    # Re-verify 400px viewport width after all tables and results are populated.
    _assert_no_horizontal_scroll_at_400px(page)


def test_pilot_shipping_network_failure_restores_controls(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    base = admin_server["base_url"]
    carton_ids = _seed_shipping_cartons(admin_server, count=1)

    page.goto(f"{base}/admin/pilot-shipping", wait_until="domcontentloaded")
    page.wait_for_selector(".fx-side", timeout=20_000)

    def abort_post(route: Route) -> None:
        if route.request.method == "POST":
            route.abort()
        else:
            route.continue_()

    page.route("**/api/pilot/pallets", abort_post)
    page.locator("#ps-pallet-carton-ids").fill(carton_ids[0])
    page.locator("#ps-pallet-confirm-box").check()
    page.locator("#ps-pallet-submit").click()

    expect(page.locator("#ps-action-status")).to_contain_text("連線失敗")
    expect(page.locator("#ps-pallet-confirm-box")).to_be_enabled()
    assert not page.locator("#ps-pallet-confirm-box").is_checked()


def test_pilot_shipping_xss_and_confirm_snapshot_survives_mutation(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    base = admin_server["base_url"]
    carton_ids = _seed_shipping_cartons(admin_server, count=1)

    headers = {"X-Tenant-Id": TENANT, "Content-Type": "application/json"}
    q_req = urllib.request.Request(
        f"{base}/api/pilot/carrier-quotes",
        data=json.dumps({"carrier": XSS_STRING, "service": "ground", "charge": 199}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(q_req) as resp:
        assert resp.status == 200

    page.goto(f"{base}/admin/pilot-shipping", wait_until="domcontentloaded")
    page.wait_for_selector(".fx-side", timeout=20_000)
    expect(page.locator("#ps-quotes-table")).to_contain_text(XSS_PROBE)
    assert page.evaluate("window.__fox3dXss || 0") == 0
    assert page.locator('img[src="x"]').count() == 0

    # Verify confirm snapshot ignores post-confirm DOM value mutation.
    page.locator("#ps-ship-origin").fill("SNAP-ORIGIN")
    page.locator("#ps-ship-destination").fill("SNAP-DEST")
    page.locator("#ps-ship-carton-ids").fill(carton_ids[0])
    page.locator("#ps-ship-confirm-box").check()
    page.evaluate(
        """() => {
          document.getElementById('ps-ship-origin').value = 'MUTATED-ORIGIN';
          document.getElementById('ps-ship-destination').value = 'MUTATED-DEST';
        }"""
    )
    with page.expect_response(
        lambda r: r.url.endswith("/api/pilot/shipments") and r.request.method == "POST"
    ) as ship_resp:
        page.locator("#ps-ship-submit").click()
    assert ship_resp.value.status == 200
    created = ship_resp.value.json()
    assert created["origin"] == "SNAP-ORIGIN"
    assert created["destination"] == "SNAP-DEST"
