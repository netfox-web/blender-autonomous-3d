"""Admin POST flows: in-flight lock, confirm snapshot, BLOCKED/veto, network errors.

Requests are counted from the Playwright route callback. Nothing here asserts on
elapsed wall-clock time.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.browser

TENANT = "sonaqueen-home"


def _path(url: str) -> str:
    return urlparse(url).path


def _install(page: Page, path: str, on_post: Callable[[Route], None]) -> None:
    def handle(route: Route) -> None:
        if route.request.method == "POST" and _path(route.request.url) == path:
            on_post(route)
            return
        route.continue_()

    page.route(re.compile(re.escape(path) + r"$"), handle)


def _goto(page: Page, base: str, href: str, ready: str) -> None:
    page.goto(base + href, wait_until="domcontentloaded")
    page.wait_for_selector(ready, timeout=20_000, state="attached")


def _open_details(page: Page, element_id: str) -> None:
    page.evaluate(
        """(id) => {
          const el = document.getElementById(id);
          const box = el && el.closest('details');
          if (box) box.open = true;
        }""",
        element_id,
    )


def _click_anyway(page: Page, element_id: str) -> None:
    """Fire a click even when the control is disabled, so a missing in-flight guard fails."""
    page.evaluate(
        """(id) => {
          const el = document.getElementById(id);
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }""",
        element_id,
    )


def _release(pending: list[Route], body: dict[str, Any] | None = None) -> None:
    payload = body if body is not None else {"status": "FAILED"}
    for route in pending:
        try:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
        except Exception:
            pass


def test_render_final_disables_buttons_and_second_click_does_not_repost(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    pending: list[Route] = []
    _install(page, "/api/render/final", pending.append)
    _goto(page, admin_server["base_url"], "/admin/render", "#rd-quick-final")
    _open_details(page, "rd-quick-final")
    page.locator("#rd-quick-final").click()
    page.locator("#rd-confirm-job-yes").click()
    page.wait_for_function(
        """() => {
          const finalBtn = document.getElementById('rd-quick-final');
          const previewBtn = document.getElementById('rd-quick-preview');
          const yes = document.getElementById('rd-confirm-job-yes');
          return !!(finalBtn && finalBtn.disabled && previewBtn && previewBtn.disabled && yes && yes.disabled);
        }"""
    )
    assert len(pending) == 1
    _click_anyway(page, "rd-quick-final")
    _click_anyway(page, "rd-quick-preview")
    _click_anyway(page, "rd-confirm-job-yes")
    assert len(pending) == 1
    _release(pending, {"jobId": "job-held", "status": "queued"})
    page.wait_for_function(
        """() => {
          const finalBtn = document.getElementById('rd-quick-final');
          const yes = document.getElementById('rd-confirm-job-yes');
          return !!(finalBtn && !finalBtn.disabled && yes && !yes.disabled);
        }"""
    )


def test_render_confirm_sends_snapshot_not_later_edits(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    seen: dict[str, Any] = {}

    def on_post(route: Route) -> None:
        seen["body"] = json.loads(route.request.post_data or "{}")
        seen["tenant"] = route.request.headers.get("x-tenant-id")
        route.fulfill(json={"jobId": "job-snap", "status": "queued"})

    _install(page, "/api/3d/jobs", on_post)
    _goto(page, admin_server["base_url"], "/admin/render", "#rd-job-submit")
    _open_details(page, "rd-job-submit")
    page.locator("#rd-job-scene").select_option("WHITE_STUDIO")
    page.locator("#rd-job-submit").click()
    page.wait_for_selector("#rd-confirm-job:not([hidden])")
    assert page.locator("#rd-job-scene").is_disabled()
    assert page.locator("#rd-tenant").is_disabled()
    snap = page.locator("#rd-confirm-job-snap").inner_text()
    assert "WHITE_STUDIO" in snap and TENANT in snap
    page.evaluate(
        """() => {
          document.getElementById('rd-job-scene').value = 'BLACK_LUXURY';
          document.getElementById('rd-tenant').value = 'mutated-tenant';
        }"""
    )
    assert "WHITE_STUDIO" in page.locator("#rd-confirm-job-snap").inner_text()
    page.locator("#rd-confirm-job-yes").click()
    page.wait_for_function("() => (document.getElementById('rd-banner').textContent || '').includes('job-snap')")
    assert seen["body"]["scene"] == "WHITE_STUDIO"
    assert seen["body"]["jobType"] == "BLENDER_PREVIEW"
    assert "BLACK_LUXURY" not in json.dumps(seen["body"])
    assert seen["tenant"] == TENANT


def test_render_blocked_result_is_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def on_post(route: Route) -> None:
        route.fulfill(json={"status": "blocked", "error": "BLOCKED_NO_BLENDER"})

    _install(page, "/api/render/final", on_post)
    _goto(page, admin_server["base_url"], "/admin/render", "#rd-quick-final")
    _open_details(page, "rd-quick-final")
    page.locator("#rd-quick-final").click()
    page.locator("#rd-confirm-job-yes").click()
    page.wait_for_function("() => (document.getElementById('rd-banner').textContent || '').includes('已封鎖')")
    banner = page.locator("#rd-banner")
    text = banner.inner_text()
    assert "完成" not in text
    assert "blocked" in (banner.get_attribute("class") or "")
    assert page.locator("#rd-quick-final").is_enabled()


def test_render_network_error_shows_failure_and_restores_button(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def on_post(route: Route) -> None:
        route.abort("failed")

    _install(page, "/api/render/preview", on_post)
    _goto(page, admin_server["base_url"], "/admin/render", "#rd-quick-preview")
    _open_details(page, "rd-quick-preview")
    page.locator("#rd-quick-preview").click()
    page.locator("#rd-confirm-job-yes").click()
    page.wait_for_function(
        """() => {
          const banner = document.getElementById('rd-banner');
          const btn = document.getElementById('rd-quick-preview');
          return !!(banner && banner.textContent.includes('連線失敗') && btn && !btn.disabled);
        }"""
    )
    assert "error" in (page.locator("#rd-banner").get_attribute("class") or "")


def test_readiness_release_disables_buttons_and_second_click_does_not_repost(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    pending: list[Route] = []
    _install(page, "/api/release/advance", pending.append)
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-rel-run")
    page.locator("#rd-rel-run").click()
    page.locator("#rd-rel-ok").click()
    page.wait_for_function(
        """() => {
          const run = document.getElementById('rd-rel-run');
          const ok = document.getElementById('rd-rel-ok');
          return !!(run && run.disabled && ok && ok.disabled);
        }"""
    )
    assert len(pending) == 1
    _click_anyway(page, "rd-rel-run")
    _click_anyway(page, "rd-rel-ok")
    assert len(pending) == 1
    _release(pending, {"state": "ENGINEERING_VALID"})
    page.wait_for_function(
        """() => {
          const run = document.getElementById('rd-rel-run');
          const ok = document.getElementById('rd-rel-ok');
          return !!(run && !run.disabled && ok && !ok.disabled);
        }"""
    )


def test_readiness_confirm_sends_snapshot_not_later_edits(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    seen: dict[str, Any] = {}

    def on_post(route: Route) -> None:
        seen["body"] = json.loads(route.request.post_data or "{}")
        seen["tenant"] = route.request.headers.get("x-tenant-id")
        route.fulfill(json={"state": "ENGINEERING_VALID", "entityId": "snap-entity"})

    _install(page, "/api/release/advance", on_post)
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-rel-entity")
    page.locator("#rd-rel-entity").fill("snap-entity")
    page.locator("#rd-rel-run").click()
    page.wait_for_selector("#rd-rel-confirm:not([hidden])")
    assert page.locator("#rd-rel-entity").is_disabled()
    assert page.locator("#rd-tenant").is_disabled()
    assert "snap-entity" in page.locator("#rd-rel-snap").inner_text()
    page.evaluate(
        """() => {
          document.getElementById('rd-rel-entity').value = 'mutated-entity';
          document.getElementById('rd-rel-target').value = 'APPROVED_FOR_EXPORT';
          document.getElementById('rd-tenant').value = 'mutated-tenant';
        }"""
    )
    page.locator("#rd-rel-ok").click()
    page.wait_for_function("() => (document.getElementById('rd-notice').textContent || '').includes('操作完成')")
    assert seen["body"]["entityId"] == "snap-entity"
    assert seen["body"]["target"] == "ENGINEERING_VALID"
    assert seen["tenant"] == TENANT


def test_readiness_veto_and_blocked_are_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def on_post(route: Route) -> None:
        route.fulfill(json={"veto": True, "checks": [{"ruleId": "FURN_TEST", "veto": True, "label": "BLOCKED"}]})

    _install(page, "/api/safety/evaluate", on_post)
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-safe-run")
    page.locator("#rd-safe-run").click()
    page.locator("#rd-safe-ok").click()
    page.wait_for_function("() => (document.getElementById('rd-notice').textContent || '').includes('已阻擋')")
    notice = page.locator("#rd-notice").inner_text()
    assert "完成" not in notice
    assert "err" in (page.locator("#rd-notice").get_attribute("class") or "")
    assert page.locator("#rd-safe-run").is_enabled()


def test_readiness_http_error_and_network_error_are_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def on_http(route: Route) -> None:
        route.fulfill(status=500, json={"detail": "fixture"})

    _install(page, "/api/physical-os/approve", on_http)
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-phys-approve-run")
    page.locator("#rd-phys-approve-run").click()
    page.locator("#rd-phys-approve-ok").click()
    page.wait_for_function("() => (document.getElementById('rd-notice').textContent || '').includes('操作失敗')")
    assert "完成" not in page.locator("#rd-notice").inner_text()
    assert page.locator("#rd-phys-approve-run").is_enabled()

    def on_net(route: Route) -> None:
        route.abort("failed")

    page.unroute(re.compile(re.escape("/api/physical-os/approve") + r"$"))
    _install(page, "/api/evidence/verify", on_net)
    page.locator("#rd-evidence-json").fill('{"engineeringHash":"e"}')
    page.locator("#rd-evidence-run").click()
    page.locator("#rd-evidence-ok").click()
    page.wait_for_function(
        """() => {
          const note = document.getElementById('rd-notice');
          const run = document.getElementById('rd-evidence-run');
          return !!(note && note.textContent.includes('連線失敗') && run && !run.disabled);
        }"""
    )


def test_readiness_physical_entity_select_populates_and_approves(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    plat = admin_server["platform"]
    acr = plat.physical.acrylic.build(tenant_id=TENANT, kind="SIGN_HOLDER")
    acr_id = acr["productId"]

    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-phys-entity-select")
    assert page.locator("#rd-phys-entity").input_value() == ""
    page.wait_for_function(
        "(id) => Array.from(document.querySelectorAll('#rd-phys-entity-select option')).some(o => o.value === id)",
        arg=acr_id,
    )
    page.locator("#rd-phys-entity-select").select_option(acr_id)
    assert page.locator("#rd-phys-entity").input_value() == acr_id
    assert page.locator("#rd-phys-kind").input_value() == "acrylic"

    page.locator("#rd-phys-approve-run").click()
    page.wait_for_selector("#rd-phys-confirm:not([hidden])")
    assert page.locator("#rd-phys-entity-select").is_disabled()
    assert page.locator("#rd-phys-entity").is_disabled()
    assert page.locator("#rd-phys-kind").is_disabled()
    assert page.locator("#rd-tenant").is_disabled()
    assert acr_id in page.locator("#rd-phys-snap").inner_text()

    page.locator("#rd-phys-approve-ok").click()
    page.wait_for_function("() => (document.getElementById('rd-notice').textContent || '').includes('操作完成')")
    assert "HTTP 200" in page.locator("#rd-phys-out").inner_text()
    assert acr_id in page.locator("#rd-phys-out").inner_text()


def test_readiness_evidence_invalid_bundle_shows_verify_failure(admin_page: Page, admin_server: dict[str, Any]) -> None:
    """Real /api/evidence/verify answers HTTP 200 with ok:false. That must not look done."""
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-evidence-json")
    page.locator("#rd-evidence-json").fill("{}")
    page.locator("#rd-evidence-run").click()
    page.wait_for_selector("#rd-evidence-confirm:not([hidden])")
    page.locator("#rd-evidence-ok").click()
    page.wait_for_function(
        """() => {
          const note = document.getElementById('rd-notice');
          const text = note ? note.textContent || '' : '';
          return text.includes('驗證失敗')
            && text.includes('missing_artifact_path')
            && text.includes('missing_lineage');
        }"""
    )
    notice = page.locator("#rd-notice")
    text = notice.inner_text()
    assert "操作完成" not in text
    assert text == "證據驗證：驗證失敗（missing_artifact_path、missing_lineage）"
    assert "err" in (notice.get_attribute("class") or "")
    body = page.locator("#rd-evidence-out").inner_text()
    assert "HTTP 200" in body
    assert '"ok": false' in body
    assert "missing_artifact_path" in body
    assert "missing_lineage" in body
    assert page.locator("#rd-evidence-run").is_enabled()


def test_readiness_evidence_real_file_ok_is_success(
    admin_page: Page, admin_server: dict[str, Any], tmp_path: Any
) -> None:
    artifact = tmp_path / "evidence.bin"
    artifact.write_bytes(b"bundle-bytes")
    page = admin_page
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-evidence-json")
    page.locator("#rd-evidence-json").fill(
        json.dumps({"artifactPath": str(artifact), "engineeringHash": "eng-1"})
    )
    page.locator("#rd-evidence-run").click()
    page.locator("#rd-evidence-ok").click()
    page.wait_for_function("() => (document.getElementById('rd-notice').textContent || '').includes('操作完成')")
    notice = page.locator("#rd-notice")
    assert "驗證失敗" not in notice.inner_text()
    assert "err" not in (notice.get_attribute("class") or "")
    body = page.locator("#rd-evidence-out").inner_text()
    assert '"ok": true' in body
    assert page.locator("#rd-evidence-run").is_enabled()


def _click_id(page: Page, element_id: str) -> None:
    page.evaluate("(id) => { document.getElementById(id).click(); }", element_id)


def test_readiness_second_confirm_cannot_unlock_tenant(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    seen: dict[str, Any] = {"safety": 0}

    def on_release(route: Route) -> None:
        seen["body"] = json.loads(route.request.post_data or "{}")
        seen["tenant"] = route.request.headers.get("x-tenant-id")
        route.fulfill(json={"state": "ENGINEERING_VALID", "entityId": "gate-entity"})

    def on_safety(route: Route) -> None:
        seen["safety"] += 1
        route.fulfill(json={"veto": False, "checks": []})

    _install(page, "/api/release/advance", on_release)
    _install(page, "/api/safety/evaluate", on_safety)
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-rel-entity")
    page.locator("#rd-rel-entity").fill("gate-entity")
    page.locator("#rd-rel-run").click()
    page.wait_for_selector("#rd-rel-confirm:not([hidden])")
    assert page.locator("#rd-tenant").is_disabled()
    assert TENANT in page.locator("#rd-rel-snap").inner_text()

    for run_id, box_id in (
        ("rd-safe-run", "rd-safe-confirm"),
        ("rd-evidence-run", "rd-evidence-confirm"),
        ("rd-phys-approve-run", "rd-phys-confirm"),
        ("rd-com-run", "rd-com-confirm"),
    ):
        page.locator(f"#{run_id}").click()
        assert page.locator(f"#{box_id}").is_hidden()
    assert page.locator("#rd-rel-confirm").is_visible()
    assert page.locator("#rd-tenant").is_disabled()

    for cancel_id in ("rd-safe-cancel", "rd-evidence-cancel", "rd-phys-approve-cancel", "rd-com-cancel"):
        _click_id(page, cancel_id)
    _click_id(page, "rd-safe-ok")
    assert seen["safety"] == 0
    assert page.locator("#rd-tenant").is_disabled()
    assert page.locator("#rd-rel-confirm").is_visible()
    assert page.locator("#rd-safe-confirm").is_hidden()

    page.evaluate("() => { document.getElementById('rd-tenant').value = 'switched-tenant'; }")
    assert "switched-tenant" not in page.locator("#rd-rel-snap").inner_text()
    page.locator("#rd-rel-ok").click()
    page.wait_for_function("() => (document.getElementById('rd-notice').textContent || '').includes('操作完成')")
    assert seen["tenant"] == TENANT
    assert seen["body"]["entityId"] == "gate-entity"
    assert seen["body"]["target"] == "ENGINEERING_VALID"
    assert seen["safety"] == 0


def test_readiness_cancel_then_other_confirm_uses_switched_tenant(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    seen: dict[str, Any] = {"release": 0}

    def on_release(route: Route) -> None:
        seen["release"] += 1
        route.fulfill(json={"state": "ENGINEERING_VALID"})

    def on_safety(route: Route) -> None:
        seen["tenant"] = route.request.headers.get("x-tenant-id")
        seen["body"] = json.loads(route.request.post_data or "{}")
        route.fulfill(json={"veto": False, "checks": [], "notCertified": True})

    _install(page, "/api/release/advance", on_release)
    _install(page, "/api/safety/evaluate", on_safety)
    _goto(page, admin_server["base_url"], "/admin/readiness", "#rd-rel-run")
    page.locator("#rd-rel-run").click()
    page.wait_for_selector("#rd-rel-confirm:not([hidden])")
    page.locator("#rd-rel-cancel").click()
    page.wait_for_selector("#rd-rel-confirm", state="hidden")
    assert page.locator("#rd-tenant").is_enabled()
    assert page.locator("#rd-rel-entity").is_enabled()

    page.locator("#rd-tenant").fill("switched-tenant")
    page.locator("#rd-safe-run").click()
    page.wait_for_selector("#rd-safe-confirm:not([hidden])")
    assert page.locator("#rd-rel-confirm").is_hidden()
    assert page.locator("#rd-tenant").is_disabled()
    assert "switched-tenant" in page.locator("#rd-safe-snap").inner_text()
    page.locator("#rd-safe-ok").click()
    page.wait_for_function("() => (document.getElementById('rd-notice').textContent || '').includes('操作完成')")
    assert seen["tenant"] == "switched-tenant"
    assert seen["body"]["kind"] == "KD"
    assert seen["release"] == 0


def test_pilot_receipt_disables_confirm_and_second_click_does_not_repost(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    pending: list[Route] = []
    _install(page, "/api/pilot/receipts", pending.append)
    _goto(page, admin_server["base_url"], "/admin/pilot", "#receipt")
    page.locator("#receipt input[name=material]").fill("HOLD-MAT")
    page.locator("#receipt input[name=quantity]").fill("2")
    page.locator("#receipt input[name=supplierLot]").fill("lot-hold")
    page.locator("#receipt button").click()
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const confirm = document.getElementById('confirm');
          const trigger = document.querySelector('#receipt button');
          return !!(confirm && confirm.disabled && trigger && trigger.disabled);
        }"""
    )
    assert len(pending) == 1
    page.evaluate(
        """() => {
          document.getElementById('receipt').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }"""
    )
    _click_anyway(page, "confirm")
    assert len(pending) == 1
    _release(pending, {"receiptId": "r-held", "acceptedQty": 2, "truthLabel": "MANUAL"})
    page.wait_for_function(
        """() => {
          const confirm = document.getElementById('confirm');
          const trigger = document.querySelector('#receipt button');
          return !!(confirm && !confirm.disabled && trigger && !trigger.disabled);
        }"""
    )


def test_pilot_confirm_sends_snapshot_tenant_and_body(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    seen: dict[str, Any] = {}

    def on_post(route: Route) -> None:
        seen["body"] = json.loads(route.request.post_data or "{}")
        seen["tenant"] = route.request.headers.get("x-tenant-id")
        route.fulfill(json={"receiptId": "r-snap", "acceptedQty": 2, "truthLabel": "MANUAL"})

    _install(page, "/api/pilot/receipts", on_post)
    _goto(page, admin_server["base_url"], "/admin/pilot", "#receipt")
    page.locator("#receipt input[name=material]").fill("SNAP-MAT")
    page.locator("#receipt input[name=quantity]").fill("2")
    page.locator("#receipt input[name=supplierLot]").fill("lot-snap")
    page.locator("#receipt button").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    assert page.locator("#receipt input[name=material]").is_disabled()
    assert page.locator("#tenant").is_disabled()
    shown = page.locator("#confirm-data").inner_text()
    assert "SNAP-MAT" in shown and TENANT in shown
    page.evaluate(
        """() => {
          document.querySelector('#receipt input[name=material]').value = 'MUTATED-MAT';
          document.getElementById('tenant').value = 'mutated-tenant';
        }"""
    )
    page.locator("#confirm").click()
    page.wait_for_function("() => (document.getElementById('result').textContent || '').includes('r-snap')")
    assert seen["body"]["material"] == "SNAP-MAT"
    assert seen["body"]["supplierLot"] == "lot-snap"
    assert seen["tenant"] == TENANT


def test_pilot_blocked_and_network_error_are_not_success(admin_page: Page, admin_server: dict[str, Any]) -> None:
    page = admin_page

    def on_blocked(route: Route) -> None:
        route.fulfill(json={"status": "BLOCKED", "truthLabel": "BLOCKED"})

    _install(page, "/api/pilot/purchase-requests", on_blocked)
    _goto(page, admin_server["base_url"], "/admin/pilot", "#purchase")
    page.locator("#purchase input[name=material]").fill("BLOCK-MAT")
    page.locator("#purchase input[name=quantity]").fill("1")
    page.locator("#purchase button").click()
    page.locator("#confirm").click()
    page.wait_for_function("() => (document.getElementById('result').textContent || '').includes('已阻擋')")
    result = page.locator("#result").inner_text()
    assert "完成" not in result
    assert page.locator("#confirm").is_enabled()

    def on_net(route: Route) -> None:
        route.abort("failed")

    page.unroute(re.compile(re.escape("/api/pilot/purchase-requests") + r"$"))
    _install(page, "/api/pilot/receipts", on_net)
    page.locator("#receipt input[name=material]").fill("NET-MAT")
    page.locator("#receipt input[name=quantity]").fill("1")
    page.locator("#receipt input[name=supplierLot]").fill("lot-net")
    page.locator("#receipt button").click()
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const result = document.getElementById('result');
          const confirm = document.getElementById('confirm');
          return !!(result && result.textContent.includes('連線失敗') && confirm && !confirm.disabled);
        }"""
    )


def _seed_pilot_packing_work_order(admin_server: dict[str, Any]) -> str:
    plat = admin_server["platform"]
    product = plat.kd.build_sku(tenant_id=TENANT, kind="OPEN_SHELF")
    rel = plat.pilot.open_release(product, tenant_id=TENANT, family="KD_FURNITURE")
    wo = plat.pilot.workorders.create(tenant_id=TENANT, release=rel, quantity=1, actor="browser-test")
    plat.pilot.workorders.release_for_execution(wo["workOrderId"], actor="browser-test")
    plat.pilot.workorders.reserve_materials(
        wo["workOrderId"], actor="browser-test", tenant_id=TENANT, allocation_policy="FIXTURE_AUTO_SEED"
    )
    return str(wo["workOrderId"])


def test_pilot_packing_flow_snapshot_mismatch_and_abort_restores_button(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    wo_id = _seed_pilot_packing_work_order(admin_server)

    _goto(page, admin_server["base_url"], "/admin/pilot", "#orders")
    row_btn = page.locator("#orders tr", has_text=wo_id).locator("button")
    row_btn.wait_for(timeout=10_000)
    row_btn.click()
    page.wait_for_selector("#packing-panel:not([hidden])")
    page.wait_for_function(
        "() => Number(document.getElementById('packing-panel').getAttribute('data-carton-load-done') || '0') >= 1"
    )

    # 1. route.abort on carton creation shows error and restores buttons.
    create_path = f"/api/pilot/work-orders/{wo_id}/cartons"
    abort_first = {"abort": True}
    seen_create: dict[str, Any] = {}

    def on_create(route: Route) -> None:
        if abort_first["abort"]:
            abort_first["abort"] = False
            route.abort("failed")
            return
        seen_create["body"] = json.loads(route.request.post_data or "{}")
        seen_create["tenant"] = route.request.headers.get("x-tenant-id")
        route.continue_()

    _install(page, create_path, on_create)

    page.locator("#packing-quantity").fill("2")
    page.locator("#packing-idem").fill("browser-pack-idem-1")
    page.locator("#packing-create-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    assert page.locator("#packing-quantity").is_disabled()
    assert page.locator("#packing-idem").is_disabled()
    assert page.locator("#tenant").is_disabled()
    snap_text = page.locator("#confirm-data").inner_text()
    assert "browser-pack-idem-1" in snap_text and TENANT in snap_text

    # Mutating inputs while confirmation is open does not change the snapshotted payload.
    page.evaluate(
        """() => {
          document.getElementById('packing-quantity').value = '9';
          document.getElementById('packing-idem').value = 'mutated-idem';
          document.getElementById('tenant').value = 'mutated-tenant';
        }"""
    )
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const result = document.getElementById('result');
          const status = document.getElementById('packing-status');
          const createBtn = document.getElementById('packing-create-btn');
          const confirmBtn = document.getElementById('confirm');
          return !!(
            result && result.textContent.includes('連線失敗') &&
            status && status.textContent.includes('連線失敗') &&
            createBtn && !createBtn.disabled &&
            confirmBtn && !confirmBtn.disabled
          );
        }"""
    )

    # Restore inputs and submit carton creation successfully.
    page.locator("#tenant").fill(TENANT)
    page.locator("#packing-quantity").fill("2")
    page.locator("#packing-idem").fill("browser-pack-idem-1")
    page.locator("#packing-create-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const sel = document.getElementById('packing-carton-id');
          return !!(sel && sel.options.length === 2);
        }"""
    )
    assert seen_create["body"] == {"quantity": 2, "idempotencyKey": "browser-pack-idem-1"}
    assert seen_create["tenant"] == TENANT

    # 2. Record a mismatched measurement -> must show 尺寸不符待人工確認, not success.
    first_carton_id = page.locator("#packing-carton-id").input_value()
    assert first_carton_id
    page.locator("#packing-length").fill("999")
    page.locator("#packing-measure-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    assert page.locator("#packing-length").is_disabled()
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const status = document.getElementById('packing-status');
          const result = document.getElementById('result');
          return !!(
            status && status.textContent.includes('尺寸不符待人工確認') &&
            result && result.textContent.includes('尺寸不符待人工確認')
          );
        }"""
    )

    # 3. Generate packing checklist -> mismatchHold=true keeps 尺寸不符待人工確認 on panel.
    page.locator("#packing-checklist-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const chk = document.getElementById('packing-checklist');
          const status = document.getElementById('packing-status');
          return !!(
            chk && chk.textContent.includes('BLOCKED/NOT_CONNECTED') &&
            status && status.textContent.includes('尺寸不符待人工確認')
          );
        }"""
    )
    assert page.locator("#packing-checklist-btn").is_enabled()

    # 4. Human sign-off closes the PACKING_MISMATCH hold; carton stays flagged, panel no longer pending.
    resolve_path = f"/api/pilot/work-orders/{wo_id}/packing-mismatch/resolve"
    seen_resolve: dict[str, Any] = {}

    def on_resolve(route: Route) -> None:
        seen_resolve["body"] = json.loads(route.request.post_data or "{}")
        seen_resolve["tenant"] = route.request.headers.get("x-tenant-id")
        route.continue_()

    _install(page, resolve_path, on_resolve)
    page.locator("#packing-resolve-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const status = document.getElementById('packing-status');
          const btn = document.getElementById('packing-resolve-btn');
          const cartons = document.getElementById('packing-cartons');
          return !!(
            status && status.textContent.includes('已人工確認') &&
            !status.textContent.includes('待人工確認') &&
            cartons && cartons.textContent.includes('尺寸不符（已人工確認）') &&
            btn && !btn.disabled
          );
        }"""
    )
    assert seen_resolve["body"] == {"confirm": True}
    assert seen_resolve["tenant"] == TENANT
    plat = admin_server["platform"]
    rec = plat.pilot.workorders.get(wo_id)
    assert rec["mismatchHold"] is False
    assert all(not h["open"] for h in rec["holds"] if h["reason"] == "PACKING_MISMATCH")
    assert plat.pilot.logistics.cartons[first_carton_id]["mismatch"] is True


def test_pilot_packing_flow_locks_buttons_during_refresh_and_ignores_stale_responses(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    wo_id = _seed_pilot_packing_work_order(admin_server)
    cartons_path = f"/api/pilot/work-orders/{wo_id}/cartons"

    _goto(page, admin_server["base_url"], "/admin/pilot", "#orders")
    row_btn = page.locator("#orders tr", has_text=wo_id).locator("button")
    row_btn.wait_for(timeout=10_000)
    row_btn.click()
    page.wait_for_selector("#packing-panel:not([hidden])")
    page.wait_for_function(
        "() => Number(document.getElementById('packing-panel').getAttribute('data-carton-load-done') || '0') >= 1"
    )

    page.locator("#packing-quantity").fill("1")
    page.locator("#packing-idem").fill("browser-pack-sync-1")
    page.locator("#packing-create-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const sel = document.getElementById('packing-carton-id');
          const btn = document.getElementById('packing-measure-btn');
          return !!(sel && sel.options.length === 1 && btn && !btn.disabled);
        }"""
    )
    carton_id = page.locator("#packing-carton-id").input_value()
    assert carton_id

    # Hold the post-measurement refresh GET /cartons to verify panel stability and button locking.
    hold_next_get = {"hold_during_edit": True, "hold": False, "capture_stale": False}
    edit_cartons_get: list[Route] = []
    held_refresh_get: list[Route] = []
    stale_cartons_get: list[Route] = []

    def on_cartons_route(route: Route) -> None:
        if route.request.method == "GET" and _path(route.request.url) == cartons_path:
            if hold_next_get["hold_during_edit"]:
                hold_next_get["hold_during_edit"] = False
                edit_cartons_get.append(route)
                return
            if hold_next_get["hold"]:
                hold_next_get["hold"] = False
                held_refresh_get.append(route)
                return
            if hold_next_get["capture_stale"]:
                hold_next_get["capture_stale"] = False
                stale_cartons_get.append(route)
                return
        route.continue_()

    page.route(re.compile(re.escape(cartons_path) + r"$"), on_cartons_route)

    # User edits #packing-length while a background GET /cartons is in flight; completion must not overwrite "999".
    before_edit_done = int(page.locator("#packing-panel").get_attribute("data-carton-load-done") or "0")
    with page.expect_request(lambda req: req.method == "GET" and _path(req.url) == cartons_path):
        page.locator("#orders tr", has_text=wo_id).locator("button").click()
    page.evaluate("() => true")
    assert len(edit_cartons_get) == 1
    page.locator("#packing-length").fill("999")
    edit_cartons_get.pop().continue_()
    page.wait_for_function(
        "(prev) => Number(document.getElementById('packing-panel').getAttribute('data-carton-load-done') || '0') > prev",
        arg=before_edit_done,
    )
    assert page.locator("#packing-length").input_value() == "999"

    hold_next_get["hold"] = True
    page.locator("#packing-measure-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    with page.expect_request(lambda req: req.method == "GET" and _path(req.url) == cartons_path):
        page.locator("#confirm").click()
    page.evaluate("() => true")
    assert len(held_refresh_get) == 1

    # While post-action refresh is in flight, packing panel stays visible and all action buttons stay disabled.
    assert page.locator("#packing-panel").is_visible()
    for btn_id in (
        "packing-create-btn",
        "packing-measure-btn",
        "packing-checklist-btn",
        "packing-resolve-btn",
        "confirm",
        "refresh",
    ):
        assert page.locator(f"#{btn_id}").is_disabled(), btn_id

    _click_anyway(page, "packing-checklist-btn")
    assert page.locator("#confirmation").is_hidden()

    held_refresh_get.pop().continue_()
    page.wait_for_function(
        """() => {
          const status = document.getElementById('packing-status');
          const result = document.getElementById('result');
          const chkBtn = document.getElementById('packing-checklist-btn');
          return !!(
            status && status.textContent.includes('尺寸不符待人工確認') &&
            result && result.textContent.includes('尺寸不符待人工確認') &&
            chkBtn && !chkBtn.disabled
          );
        }"""
    )

    # Capture an in-flight GET /cartons before checklist + sign-off, then fulfill it out of order after sign-off.
    hold_next_get["capture_stale"] = True
    with page.expect_request(lambda req: req.method == "GET" and _path(req.url) == cartons_path):
        page.locator("#orders tr", has_text=wo_id).locator("button").click()
    page.evaluate("() => true")
    assert len(stale_cartons_get) == 1

    page.locator("#packing-checklist-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const chk = document.getElementById('packing-checklist');
          const status = document.getElementById('packing-status');
          const resolveBtn = document.getElementById('packing-resolve-btn');
          return !!(
            chk && chk.textContent.includes('BLOCKED/NOT_CONNECTED') &&
            status && status.textContent.includes('尺寸不符待人工確認') &&
            resolveBtn && !resolveBtn.disabled
          );
        }"""
    )

    page.locator("#packing-resolve-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    page.locator("#confirm").click()
    page.wait_for_function(
        """() => {
          const status = document.getElementById('packing-status');
          const cartons = document.getElementById('packing-cartons');
          const btn = document.getElementById('packing-resolve-btn');
          return !!(
            status && status.textContent.includes('已人工確認') &&
            !status.textContent.includes('待人工確認') &&
            cartons && cartons.textContent.includes('尺寸不符（已人工確認）') &&
            btn && !btn.disabled
          );
        }"""
    )

    # Fulfill the stale pre-resolve GET /cartons with mismatchHold=True; UI must ignore it.
    before_stale_done = int(page.locator("#packing-panel").get_attribute("data-carton-load-done") or "0")
    stale_carton = dict(admin_server["platform"].pilot.logistics.cartons[carton_id])
    stale_cartons_get.pop().fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(
            {
                "workOrderId": wo_id,
                "tenantId": TENANT,
                "mismatchHold": True,
                "cartonCount": 1,
                "items": [stale_carton],
                "cartons": [stale_carton],
            }
        ),
    )
    page.wait_for_function(
        "(prev) => Number(document.getElementById('packing-panel').getAttribute('data-carton-load-done') || '0') > prev",
        arg=before_stale_done,
    )
    status_text = page.locator("#packing-status").inner_text()
    assert "已人工確認" in status_text and "待人工確認" not in status_text
    assert "尺寸不符（已人工確認）" in page.locator("#packing-cartons").inner_text()
    assert "BLOCKED/NOT_CONNECTED" in page.locator("#packing-checklist").inner_text()


def test_pilot_health_null_isolates_render_error_and_updates_other_sections(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    wo_id = _seed_pilot_packing_work_order(admin_server)

    page.route(
        re.compile(re.escape("/api/pilot/health") + r"$"),
        lambda route: route.fulfill(status=200, content_type="application/json", body="null"),
    )

    _goto(page, admin_server["base_url"], "/admin/pilot", "#orders")
    page.wait_for_function(
        """(expectedWo) => {
          const health = document.getElementById('health');
          const overview = document.getElementById('overview');
          const orders = document.getElementById('orders');
          const board = document.getElementById('board');
          const refreshBtn = document.getElementById('refresh');
          return !!(
            health && health.textContent.includes('讀取失敗') &&
            overview && overview.textContent.includes('材料批號') &&
            orders && orders.textContent.includes(expectedWo) &&
            board && board.textContent.includes('整體判定') &&
            refreshBtn && !refreshBtn.disabled
          );
        }""",
        arg=wo_id,
    )

    row_btn = page.locator("#orders tr", has_text=wo_id).locator("button")
    row_btn.click()
    page.wait_for_selector("#packing-panel:not([hidden])")
    page.wait_for_function(
        "() => Number(document.getElementById('packing-panel').getAttribute('data-carton-load-done') || '0') >= 1"
    )

    # POST carton creation while /api/pilot/health returns null must succeed and unlock buttons.
    before_create_done = int(page.locator("#packing-panel").get_attribute("data-carton-load-done") or "0")
    page.locator("#packing-quantity").fill("1")
    page.locator("#packing-idem").fill("browser-health-null-1")
    page.locator("#packing-create-btn").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    page.locator("#confirm").click()
    page.wait_for_function(
        """(prev) => {
          const panel = document.getElementById('packing-panel');
          const done = Number((panel && panel.getAttribute('data-carton-load-done')) || '0');
          const sel = document.getElementById('packing-carton-id');
          const createBtn = document.getElementById('packing-create-btn');
          const confirmBtn = document.getElementById('confirm');
          return !!(done > prev && sel && sel.options.length === 1 && createBtn && !createBtn.disabled && confirmBtn && !confirmBtn.disabled);
        }""",
        arg=before_create_done,
    )
    assert "讀取失敗" in page.locator("#health").inner_text()
    assert "操作失敗" not in page.locator("#result").inner_text()
    assert wo_id in page.locator("#result").inner_text()
    assert "已建立 1 個紙箱並綁定工單。" in page.locator("#packing-status").inner_text()

    # Mutate carton on backend and submit a receipt POST: both overview (#receipts, before health)
    # and cartons (#packing-cartons, after health in refresh) must update, and buttons must unlock.
    carton_id = page.locator("#packing-carton-id").input_value()
    admin_server["platform"].pilot.logistics.cartons[carton_id]["measured"] = {
        "length": 777.0,
        "width": 400.0,
        "height": 200.0,
        "weightKg": 12.0,
    }
    before_receipt_done = int(page.locator("#packing-panel").get_attribute("data-carton-load-done") or "0")
    page.locator("#receipt input[name=material]").fill("HEALTH-NULL-MAT")
    page.locator("#receipt input[name=quantity]").fill("3")
    page.locator("#receipt input[name=supplierLot]").fill("lot-health-null")
    page.locator("#receipt button").click()
    page.wait_for_selector("#confirmation:not([hidden])")
    page.locator("#confirm").click()
    page.wait_for_function(
        """(prev) => {
          const panel = document.getElementById('packing-panel');
          const done = Number((panel && panel.getAttribute('data-carton-load-done')) || '0');
          const receipts = document.getElementById('receipts');
          const cartons = document.getElementById('packing-cartons');
          const receiptBtn = document.querySelector('#receipt button');
          return !!(
            done > prev &&
            receipts && receipts.textContent.includes('HEALTH-NULL-MAT') &&
            cartons && cartons.textContent.includes('777×400×200 mm / 12 kg') &&
            receiptBtn && !receiptBtn.disabled
          );
        }""",
        arg=before_receipt_done,
    )
    assert "讀取失敗" in page.locator("#health").inner_text()
    assert "操作失敗" not in page.locator("#result").inner_text()
    for btn_id in (
        "packing-create-btn",
        "packing-measure-btn",
        "packing-checklist-btn",
        "packing-resolve-btn",
        "confirm",
        "refresh",
    ):
        assert page.locator(f"#{btn_id}").is_enabled(), btn_id


def test_pilot_packing_flow_repeated_cycles_under_concurrent_refresh_load(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    wo_ids = [_seed_pilot_packing_work_order(admin_server) for _ in range(3)]
    _goto(page, admin_server["base_url"], "/admin/pilot", "#orders")

    for idx, wo_id in enumerate(wo_ids):
        row_btn = page.locator("#orders tr", has_text=wo_id).locator("button")
        row_btn.wait_for(timeout=10_000)
        row_btn.click()
        page.wait_for_function(
            """(expectedWo) => {
              const panel = document.getElementById('packing-panel');
              const detail = document.getElementById('detail');
              const chk = document.getElementById('packing-checklist');
              return !!(
                panel && !panel.hidden &&
                detail && detail.textContent.includes(expectedWo) &&
                chk && chk.textContent.includes('尚未產生裝箱檢查表')
              );
            }""",
            arg=wo_id,
        )

        # Fire concurrent background console/health reads while running the packing cycle to simulate load.
        page.evaluate(
            """() => {
              fetch('/api/pilot/console', { headers: { 'X-Tenant-Id': 'sonaqueen-home' } });
              fetch('/api/pilot/health', { headers: { 'X-Tenant-Id': 'sonaqueen-home' } });
              fetch('/api/pilot/batches/board', { headers: { 'X-Tenant-Id': 'sonaqueen-home' } });
            }"""
        )

        page.locator("#packing-quantity").fill("1")
        page.locator("#packing-idem").fill(f"browser-repeat-idem-{idx}")
        page.locator("#packing-create-btn").click()
        page.wait_for_selector("#confirmation:not([hidden])")
        page.locator("#confirm").click()
        page.wait_for_function(
            """() => {
              const sel = document.getElementById('packing-carton-id');
              const btn = document.getElementById('packing-measure-btn');
              return !!(sel && sel.options.length === 1 && btn && !btn.disabled);
            }"""
        )

        page.locator("#packing-length").fill("999")
        page.locator("#packing-measure-btn").click()
        page.wait_for_selector("#confirmation:not([hidden])")
        page.locator("#confirm").click()
        page.wait_for_function(
            """() => {
              const status = document.getElementById('packing-status');
              const result = document.getElementById('result');
              const chkBtn = document.getElementById('packing-checklist-btn');
              return !!(
                status && status.textContent.includes('尺寸不符待人工確認') &&
                result && result.textContent.includes('尺寸不符待人工確認') &&
                chkBtn && !chkBtn.disabled
              );
            }"""
        )

        page.locator("#packing-checklist-btn").click()
        page.wait_for_selector("#confirmation:not([hidden])")
        page.locator("#confirm").click()
        page.wait_for_function(
            """(expectedWo) => {
              const chk = document.getElementById('packing-checklist');
              const status = document.getElementById('packing-status');
              const resolveBtn = document.getElementById('packing-resolve-btn');
              return !!(
                chk && chk.textContent.includes(expectedWo) &&
                chk.textContent.includes('BLOCKED/NOT_CONNECTED') &&
                status && status.textContent.includes('尺寸不符待人工確認') &&
                resolveBtn && !resolveBtn.disabled
              );
            }""",
            arg=wo_id,
        )

        page.locator("#packing-resolve-btn").click()
        page.wait_for_selector("#confirmation:not([hidden])")
        page.locator("#confirm").click()
        page.wait_for_function(
            """() => {
              const status = document.getElementById('packing-status');
              const cartons = document.getElementById('packing-cartons');
              const btn = document.getElementById('packing-resolve-btn');
              return !!(
                status && status.textContent.includes('已人工確認') &&
                !status.textContent.includes('待人工確認') &&
                cartons && cartons.textContent.includes('尺寸不符（已人工確認）') &&
                btn && !btn.disabled
              );
            }"""
        )
        rec = admin_server["platform"].pilot.workorders.get(wo_id)
        assert rec["mismatchHold"] is False



def _seed_available_remnant(admin_server: dict[str, Any], remnant_id: str = "rem-browser-1") -> str:
    plat = admin_server["platform"]
    rec = {
        "remnantId": remnant_id,
        "tenantId": TENANT,
        "material": "WOOD_WHITE",
        "materialCode": "WOOD_WHITE",
        "thickness": 18,
        "w": 600,
        "h": 400,
        "grain": "length",
        "status": "available",
        "qualityState": "AVAILABLE",
        "version": 1,
        "area": 240000,
    }
    plat.remnants.items[remnant_id] = rec
    plat.remnants.store.put(rec)
    return remnant_id


def test_materials_lot_and_reserve_disable_buttons_and_second_click_does_not_repost(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    rid = _seed_available_remnant(admin_server, "rem-in-flight")
    pending_lots: list[Route] = []
    pending_reserve: list[Route] = []
    _install(page, "/api/materials/lots", pending_lots.append)
    _install(page, f"/api/remnants/{rid}/reserve", pending_reserve.append)

    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lot-submit")
    _open_details(page, "mt-lot-submit")
    page.locator("#mt-lot-submit").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function(
        """() => {
          const submit = document.getElementById('mt-lot-submit');
          const ok = document.getElementById('mt-confirm-ok');
          return !!(submit && submit.disabled && ok && ok.disabled);
        }"""
    )
    assert len(pending_lots) == 1
    _click_anyway(page, "mt-lot-submit")
    _click_anyway(page, "mt-confirm-ok")
    page.evaluate(
        """() => {
          document.getElementById('mt-lot-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }"""
    )
    assert len(pending_lots) == 1
    _release(pending_lots, {"receiptId": "r-lot-held", "lotId": "lot-held", "acceptedQty": 1})
    page.wait_for_function(
        """() => {
          const submit = document.getElementById('mt-lot-submit');
          const ok = document.getElementById('mt-confirm-ok');
          return !!(submit && !submit.disabled && ok && !ok.disabled);
        }"""
    )

    page.locator("#tab-remnants").click()
    row = page.locator("#mt-remnants-wrap tr[data-selectable]", has_text=rid)
    row.wait_for(timeout=10_000)
    row.click()
    assert page.locator("#mt-reserve-btn").is_enabled()
    page.locator("#mt-reserve-btn").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function(
        """() => {
          const btn = document.getElementById('mt-reserve-btn');
          const ok = document.getElementById('mt-confirm-ok');
          return !!(btn && btn.disabled && ok && ok.disabled);
        }"""
    )
    assert len(pending_reserve) == 1
    _click_anyway(page, "mt-reserve-btn")
    _click_anyway(page, "mt-confirm-ok")
    page.evaluate(
        """() => {
          document.getElementById('mt-reserve-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }"""
    )
    assert len(pending_reserve) == 1
    _release(pending_reserve, {"remnantId": rid, "status": "reserved", "version": 2})
    page.wait_for_function(
        """() => {
          const btn = document.getElementById('mt-reserve-btn');
          const ok = document.getElementById('mt-confirm-ok');
          return !!(btn && !btn.disabled && ok && !ok.disabled);
        }"""
    )


def test_materials_idempotency_key_differs_across_confirms_and_reused_on_retry(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    rid = _seed_available_remnant(admin_server, "rem-idem")
    lot_bodies: list[dict[str, Any]] = []
    reserve_bodies: list[dict[str, Any]] = []

    def on_lot(route: Route) -> None:
        body = json.loads(route.request.post_data or "{}")
        lot_bodies.append(body)
        if len(lot_bodies) == 1:
            route.abort("failed")
            return
        route.fulfill(json={"receiptId": f"r-{len(lot_bodies)}", "lotId": f"l-{len(lot_bodies)}", "acceptedQty": 1})

    def on_reserve(route: Route) -> None:
        body = json.loads(route.request.post_data or "{}")
        reserve_bodies.append(body)
        if len(reserve_bodies) == 1:
            route.abort("failed")
            return
        route.fulfill(json={"remnantId": rid, "status": "reserved", "version": 2})

    _install(page, "/api/materials/lots", on_lot)
    _install(page, f"/api/remnants/{rid}/reserve", on_reserve)

    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lot-submit")
    _open_details(page, "mt-lot-submit")

    # Confirm #1 fails with network error -> button recovers and retry reuses the same idempotencyKey.
    page.locator("#mt-lot-submit").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function(
        """() => {
          const out = document.getElementById('mt-lot-result');
          const submit = document.getElementById('mt-lot-submit');
          const retry = document.getElementById('mt-lot-retry');
          return !!(out && out.textContent.includes('連線失敗') && submit && !submit.disabled && retry && !retry.hidden && !retry.disabled);
        }"""
    )
    assert len(lot_bodies) == 1
    first_key = lot_bodies[0].get("idempotencyKey")
    assert isinstance(first_key, str) and len(first_key) > 0

    page.locator("#mt-lot-retry").click()
    page.wait_for_function("() => (document.getElementById('mt-lot-result').textContent || '').includes('r-2')")
    assert len(lot_bodies) == 2
    assert lot_bodies[1]["idempotencyKey"] == first_key

    # Confirm #2 generates a fresh idempotencyKey even when randomUUID falls back to timestamp+random.
    page.evaluate("() => { try { Object.defineProperty(window.crypto, 'randomUUID', { value: null, configurable: true }); } catch (e) {} }")
    page.locator("#mt-lot-submit").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => (document.getElementById('mt-lot-result').textContent || '').includes('r-3')")
    assert len(lot_bodies) == 3
    second_key = lot_bodies[2].get("idempotencyKey")
    assert isinstance(second_key, str) and len(second_key) > 0
    assert second_key != first_key

    # Reserve flow: confirm #1 fails -> retry reuses key; confirm #2 uses a new key.
    page.locator("#tab-remnants").click()
    row = page.locator("#mt-remnants-wrap tr[data-selectable]", has_text=rid)
    row.wait_for(timeout=10_000)
    row.click()
    page.locator("#mt-reserve-btn").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function(
        """() => {
          const out = document.getElementById('mt-reserve-result');
          const btn = document.getElementById('mt-reserve-btn');
          const retry = document.getElementById('mt-reserve-retry');
          return !!(out && out.textContent.includes('連線失敗') && btn && !btn.disabled && retry && !retry.hidden && !retry.disabled);
        }"""
    )
    assert len(reserve_bodies) == 1
    res_key_1 = reserve_bodies[0].get("idempotencyKey")
    assert isinstance(res_key_1, str) and len(res_key_1) > 0

    page.locator("#mt-reserve-retry").click()
    page.wait_for_function("() => (document.getElementById('mt-reserve-result').textContent || '').includes('HTTP 200')")
    assert len(reserve_bodies) == 2
    assert reserve_bodies[1]["idempotencyKey"] == res_key_1

    page.locator("#mt-reserve-btn").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => !document.getElementById('mt-reserve-btn').disabled")
    assert len(reserve_bodies) == 3
    assert reserve_bodies[2]["idempotencyKey"] != res_key_1


def test_materials_409_and_blocked_show_failure_and_network_error_restores_button(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    rid = _seed_available_remnant(admin_server, "rem-409")

    def on_reserve_409(route: Route) -> None:
        route.fulfill(status=409, json={"detail": "stale remnant version 1 != 2"})

    def on_lot_blocked(route: Route) -> None:
        route.fulfill(status=200, json={"status": "BLOCKED", "truthLabel": "BLOCKED"})

    _install(page, f"/api/remnants/{rid}/reserve", on_reserve_409)
    _install(page, "/api/materials/lots", on_lot_blocked)

    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lot-submit")
    _open_details(page, "mt-lot-submit")
    page.locator("#mt-lot-submit").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => (document.getElementById('mt-lot-result').textContent || '').includes('已阻擋')")
    lot_text = page.locator("#mt-lot-result").inner_text()
    assert "失敗" in lot_text and "完成" not in lot_text
    assert "err" in (page.locator("#mt-banner").get_attribute("class") or "")
    assert page.locator("#mt-lot-submit").is_enabled()

    page.locator("#tab-remnants").click()
    row = page.locator("#mt-remnants-wrap tr[data-selectable]", has_text=rid)
    row.wait_for(timeout=10_000)
    row.click()
    page.locator("#mt-reserve-btn").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => (document.getElementById('mt-reserve-result').textContent || '').includes('HTTP 409')")
    res_text = page.locator("#mt-reserve-result").inner_text()
    banner_text = page.locator("#mt-banner").inner_text()
    assert "失敗" in res_text and "完成" not in res_text
    assert "失敗" in banner_text and "409" in banner_text
    assert "err" in (page.locator("#mt-banner").get_attribute("class") or "")
    assert page.locator("#mt-reserve-btn").is_enabled()


def test_materials_confirm_sends_snapshot_not_later_edits(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    seen: dict[str, Any] = {}

    def on_lot(route: Route) -> None:
        seen["body"] = json.loads(route.request.post_data or "{}")
        seen["tenant"] = route.request.headers.get("x-tenant-id")
        route.fulfill(json={"receiptId": "r-snap-lot", "lotId": "lot-snap", "acceptedQty": 3})

    _install(page, "/api/materials/lots", on_lot)
    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lot-submit")
    _open_details(page, "mt-lot-submit")
    page.locator("#mt-lot-material").select_option("WOOD_OAK")
    page.locator("#mt-lot-qty").fill("3")
    page.locator("#mt-lot-supplier").fill("snap-sup")
    page.locator("#mt-lot-submit").click()
    page.wait_for_selector("#mt-confirm[open]")
    assert page.locator("#mt-lot-material").is_disabled()
    assert page.locator("#mt-lot-qty").is_disabled()
    assert page.locator("#mt-tenant").is_disabled()
    assert "WOOD_OAK" in page.locator("#mt-confirm-text").inner_text()
    assert TENANT in page.locator("#mt-confirm-text").inner_text()
    page.evaluate(
        """() => {
          document.getElementById('mt-lot-material').value = 'WOOD_BLACK';
          document.getElementById('mt-lot-qty').value = '99';
          document.getElementById('mt-lot-supplier').value = 'mutated-sup';
          document.getElementById('mt-tenant').value = 'mutated-tenant';
        }"""
    )
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => (document.getElementById('mt-lot-result').textContent || '').includes('r-snap-lot')")
    assert seen["body"]["material"] == "WOOD_OAK"
    assert seen["body"]["sheetCount"] == 3
    assert seen["body"]["supplierLot"] == "snap-sup"
    assert seen["tenant"] == TENANT


def test_materials_switching_remnant_or_tenant_invalidates_retry(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    rid_a = _seed_available_remnant(admin_server, "rem-switch-a")
    rid_b = _seed_available_remnant(admin_server, "rem-switch-b")
    calls_a: list[tuple[str | None, dict[str, Any]]] = []
    calls_b: list[tuple[str | None, dict[str, Any]]] = []
    lot_calls: list[tuple[str | None, dict[str, Any]]] = []

    def on_res_a(route: Route) -> None:
        calls_a.append((route.request.headers.get("x-tenant-id"), json.loads(route.request.post_data or "{}")))
        route.abort("failed")

    def on_res_b(route: Route) -> None:
        calls_b.append((route.request.headers.get("x-tenant-id"), json.loads(route.request.post_data or "{}")))
        if len(calls_b) == 1:
            route.abort("failed")
            return
        route.fulfill(json={"remnantId": rid_b, "status": "reserved", "version": 2})

    def on_lot(route: Route) -> None:
        lot_calls.append((route.request.headers.get("x-tenant-id"), json.loads(route.request.post_data or "{}")))
        route.abort("failed")

    _install(page, f"/api/remnants/{rid_a}/reserve", on_res_a)
    _install(page, f"/api/remnants/{rid_b}/reserve", on_res_b)
    _install(page, "/api/materials/lots", on_lot)

    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lot-submit")
    page.locator("#tab-remnants").click()

    row_a = page.locator("#mt-remnants-wrap tr[data-selectable]", has_text=rid_a)
    row_b = page.locator("#mt-remnants-wrap tr[data-selectable]", has_text=rid_b)
    row_a.wait_for(timeout=10_000)
    row_a.click()
    page.locator("#mt-reserve-btn").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function(
        """() => {
          const retry = document.getElementById('mt-reserve-retry');
          return !!(retry && !retry.hidden && !retry.disabled);
        }"""
    )
    assert len(calls_a) == 1

    # Selecting remnant B invalidates retry for A.
    row_b.click()
    assert page.locator("#mt-reserve-retry").is_hidden()
    _click_anyway(page, "mt-reserve-retry")
    assert len(calls_a) == 1
    assert len(calls_b) == 0

    # Reserve B fails -> retry shown; Lot fails -> retry shown; switching tenant invalidates both.
    page.locator("#mt-reserve-btn").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => !document.getElementById('mt-reserve-retry').hidden")
    assert len(calls_b) == 1

    page.locator("#tab-sheets").click()
    _open_details(page, "mt-lot-submit")
    page.locator("#mt-lot-submit").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => !document.getElementById('mt-lot-retry').hidden")
    assert len(lot_calls) == 1

    page.locator("#mt-tenant").fill("other-tenant")
    page.locator("#mt-tenant").dispatch_event("change")
    assert page.locator("#mt-lot-retry").is_hidden()
    assert page.locator("#mt-reserve-retry").is_hidden()
    assert page.locator("#mt-rem-detail").is_hidden()
    assert page.locator("#mt-reserve-btn").is_disabled()
    _click_anyway(page, "mt-lot-retry")
    _click_anyway(page, "mt-reserve-retry")
    assert len(lot_calls) == 1
    assert len(calls_a) == 1
    assert len(calls_b) == 1


def test_materials_edits_and_switches_during_delayed_response_invalidate_retry(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    page = admin_page
    rid_a = _seed_available_remnant(admin_server, "rem-delay-a")
    rid_b = _seed_available_remnant(admin_server, "rem-delay-b")
    pending_lots: list[Route] = []
    pending_res_a: list[Route] = []

    _install(page, "/api/materials/lots", pending_lots.append)
    _install(page, f"/api/remnants/{rid_a}/reserve", pending_res_a.append)

    _goto(page, admin_server["base_url"], "/admin/materials", "#mt-lot-submit")
    _open_details(page, "mt-lot-submit")

    # 1. Edit lot form while request is in flight -> when it fails, retry stays hidden.
    page.locator("#mt-lot-qty").fill("2")
    page.locator("#mt-lot-submit").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => document.getElementById('mt-lot-submit').disabled")
    assert len(pending_lots) == 1

    page.locator("#mt-lot-qty").fill("5")
    pending_lots.pop().abort("failed")
    page.wait_for_function(
        """() => {
          const submit = document.getElementById('mt-lot-submit');
          const out = document.getElementById('mt-lot-result');
          return !!(submit && !submit.disabled && out && out.textContent.includes('連線失敗'));
        }"""
    )
    assert page.locator("#mt-lot-retry").is_hidden()
    _click_anyway(page, "mt-lot-retry")
    assert len(pending_lots) == 0

    # 2. Edit reserve form while request is in flight -> when it fails, retry stays hidden.
    page.locator("#tab-remnants").click()
    row_a = page.locator("#mt-remnants-wrap tr[data-selectable]", has_text=rid_a)
    row_b = page.locator("#mt-remnants-wrap tr[data-selectable]", has_text=rid_b)
    row_a.wait_for(timeout=10_000)
    row_a.click()
    page.locator("#mt-reserve-by").fill("op-1")
    page.locator("#mt-reserve-btn").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => document.getElementById('mt-reserve-btn').disabled")
    assert len(pending_res_a) == 1

    page.locator("#mt-reserve-by").fill("op-2")
    pending_res_a.pop().abort("failed")
    page.wait_for_function(
        """() => {
          const btn = document.getElementById('mt-reserve-btn');
          const out = document.getElementById('mt-reserve-result');
          return !!(btn && !btn.disabled && out && out.textContent.includes('連線失敗'));
        }"""
    )
    assert page.locator("#mt-reserve-retry").is_hidden()
    _click_anyway(page, "mt-reserve-retry")
    assert len(pending_res_a) == 0

    # 3. Switch remnant selection while reserve request for A is in flight -> retry stays hidden.
    page.locator("#mt-reserve-btn").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => document.getElementById('mt-reserve-btn').disabled")
    assert len(pending_res_a) == 1

    row_b.click()
    assert page.locator("#mt-reserve-btn").is_disabled()
    pending_res_a.pop().abort("failed")
    page.wait_for_function("() => !document.getElementById('mt-reserve-btn').disabled")
    assert page.locator("#mt-reserve-retry").is_hidden()
    _click_anyway(page, "mt-reserve-retry")
    assert len(pending_res_a) == 0

    # 4. Switch tenant while lot request is in flight -> retry stays hidden.
    page.locator("#tab-sheets").click()
    page.locator("#mt-lot-submit").click()
    page.wait_for_selector("#mt-confirm[open]")
    page.locator("#mt-confirm-ok").click()
    page.wait_for_function("() => document.getElementById('mt-lot-submit').disabled")
    assert len(pending_lots) == 1

    page.locator("#mt-tenant").fill("tenant-in-flight")
    page.locator("#mt-tenant").dispatch_event("change")
    pending_lots.pop().abort("failed")
    page.wait_for_function("() => !document.getElementById('mt-lot-submit').disabled")
    assert page.locator("#mt-lot-retry").is_hidden()
    _click_anyway(page, "mt-lot-retry")
    assert len(pending_lots) == 0

