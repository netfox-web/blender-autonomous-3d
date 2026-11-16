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
