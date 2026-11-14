"""Hostile PrintFox task fields and batch SKUs must stay text, and failed posts must look failed."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from playwright.sync_api import expect

from tests.browser.conftest import TENANT

pytestmark = pytest.mark.browser

PAYLOAD = '"><img src=x onerror=window.__fox3dXss=1>'
HOST_NAME = "batch-xss-host"
HOST_SKU = "SAFE-SKU-386"
SUCCESS_GENERATE = "已送出單次生圖"
SUCCESS_BATCH = "已送出批次"


def assert_inert(page) -> None:  # noqa: ANN001
    assert page.locator('img[src="x"]').count() == 0
    assert page.locator("[onerror]").count() == 0
    page.wait_for_timeout(300)
    assert page.evaluate("() => window.__fox3dXss || 0") == 0


def _printfox(route, items: list[dict[str, Any]], fail: dict[str, bool]) -> None:
    request = route.request
    path = urlparse(request.url).path
    if request.method == "GET" and path.endswith("/connection"):
        route.fulfill(json={
            "connected": True,
            "baseUrl": "http://127.0.0.1:9",
            "status": {"workers_online": 0, "queue": 0},
        })
        return
    if request.method == "GET" and path.endswith("/tasks"):
        route.fulfill(json={"items": items})
        return
    if request.method == "GET" and path.endswith("/designs"):
        route.fulfill(json={"total": 0, "items": []})
        return
    if fail.get("post") and request.method == "POST" and path.endswith("/tasks"):
        route.abort("failed")
        return
    if fail.get("refresh") and request.method == "GET" and "/tasks/" in path:
        route.abort("failed")
        return
    route.fallback()


def _watch_inflight(page) -> None:  # noqa: ANN001
    page.add_init_script(
        """
        window.__fox3dInflight = [];
        const orig = window.fetch;
        window.fetch = function(input, init) {
          const url = typeof input === 'string' ? input : (input && input.url) || '';
          const method = (init && init.method) || 'GET';
          const button = id => {
            const el = document.getElementById(id);
            return !!(el && el.disabled);
          };
          const refresh = document.querySelector('#pf-tasks [data-refresh]');
          window.__fox3dInflight.push({
            url, method,
            generateDisabled: button('pf-generate-btn'),
            refreshDisabled: !!(refresh && refresh.disabled),
            submitDisabled: button('batch-submit'),
            cancelDisabled: button('batch-cancel'),
          });
          return orig.apply(this, arguments);
        };
        """
    )


def _open_printfox(page, base: str, items: list[dict[str, Any]], fail: dict[str, bool] | None = None) -> None:
    flag = fail if fail is not None else {}
    page.route("**/api/print-workspace/printfox/**", lambda route: _printfox(route, items, flag))
    page.goto(base + "/admin/recipes/print", wait_until="domcontentloaded")
    page.locator("#printfox-panel summary").click()
    expect(page.locator("#pf-connection-status")).to_contain_text("已連接")
    expect(page.locator("#pf-generate-btn")).to_be_enabled()


@pytest.fixture(scope="module")
def batch_host(admin_server: dict[str, Any]) -> dict[str, Any]:
    base = admin_server["base_url"]
    draft = {
        "name": HOST_NAME,
        "family": "cabinet",
        "subtype": "open",
        "geometry": "OPEN_CABINET",
        "widthMm": 424.0,
        "depthMm": 295.0,
        "heightMm": 900.0,
        "panelMm": 15.0,
        "backMm": 3.0,
        "rows": 3,
        "dimensionEvidence": "Synthetic engineering fixture, mm",
        "structureEvidence": "Single column, equal openings, inset back",
        "variants": [{"sku": HOST_SKU}],
    }
    with httpx.Client(base_url=base, headers={"X-Tenant-Id": TENANT}, timeout=30.0) as client:
        response = client.post("/api/product-models", json={"expectedRevision": 0, "draft": draft})
        assert response.is_success, response.text
        saved = response.json()
    return {"base": base, "id": saved["id"], "name": HOST_NAME}


def _poison_sku(route, model_id: str) -> None:
    path = urlparse(route.request.url).path
    if route.request.method == "GET" and path == f"/api/product-models/{model_id}":
        response = route.fetch()
        data = response.json()
        variants = data.setdefault("draft", {}).setdefault("variants", [])
        if variants:
            variants[0]["sku"] = PAYLOAD
        else:
            variants.append({"sku": PAYLOAD, "artworkAssetId": "", "note": ""})
        route.fulfill(response=response, json=data)
        return
    route.fallback()


def _open_batch_model(page, batch_host: dict[str, Any]) -> None:  # noqa: ANN001
    page.goto(batch_host["base"] + "/admin/recipes/models", wait_until="domcontentloaded")
    expect(page.locator("#notice")).to_contain_text("從左側分類找模型", timeout=30_000)
    page.locator("#masters button").filter(has_text=HOST_NAME).click()


def test_printfox_task_fields_render_as_text(admin_page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    task = {
        "requestId": PAYLOAD,
        "state": "running",
        "progress": 1,
        "message": PAYLOAD,
        "remoteJobId": None,
        "params": {"styles": [{"desc": PAYLOAD}]},
    }
    _open_printfox(page, admin_server["base_url"], [task])
    tasks = page.locator("#pf-tasks")
    expect(tasks).to_contain_text(PAYLOAD)
    assert tasks.text_content().count(PAYLOAD) >= 3
    assert "生圖中 · 1%" in tasks.inner_text()
    refresh = tasks.get_by_role("button", name="更新狀態")
    cancel = tasks.get_by_role("button", name="取消這筆生圖")
    assert refresh.get_attribute("data-refresh") == PAYLOAD
    assert cancel.get_attribute("data-cancel") == PAYLOAD
    assert_inert(page)


def test_printfox_actions_disable_and_network_errors_are_failures(admin_page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    _watch_inflight(page)
    task = {"requestId": "11111111-1111-4111-8111-111111111111", "state": "done", "progress": 100, "message": ""}
    fail = {"refresh": False, "post": False}
    _open_printfox(page, admin_server["base_url"], [task], fail)

    fail["refresh"] = True
    page.locator("#pf-tasks").get_by_role("button", name="更新狀態").click()
    message = page.locator("#pf-message")
    expect(message).to_have_class("error")
    expect(message).to_contain_text("失敗")
    assert SUCCESS_GENERATE not in (message.text_content() or "")
    expect(page.locator("#pf-generate-btn")).to_be_enabled()
    refresh_calls = [
        row for row in page.evaluate("() => window.__fox3dInflight")
        if row["method"] == "GET" and "/tasks/" in row["url"]
    ]
    assert refresh_calls and refresh_calls[-1]["refreshDisabled"] is True

    fail["post"] = True
    page.locator("#pf-prompt").fill("藍色植物門片")
    page.locator("#pf-generate-btn").click()
    expect(message).to_contain_text("失敗")
    assert SUCCESS_GENERATE not in (message.text_content() or "")
    expect(page.locator("#pf-generate-btn")).to_be_enabled()
    posts = [
        row for row in page.evaluate("() => window.__fox3dInflight")
        if row["method"] == "POST" and row["url"].split("?", 1)[0].rstrip("/").endswith("/tasks")
    ]
    assert posts and posts[-1]["generateDisabled"] is True
    assert_inert(page)


def test_model_batch_pending_sku_renders_as_text(admin_page, batch_host: dict[str, Any]) -> None:
    page = admin_page
    page.route("**/api/product-models/**", lambda route: _poison_sku(route, batch_host["id"]))
    _open_batch_model(page, batch_host)
    sku = page.locator("#composition-sku")
    expect(sku).to_have_value(PAYLOAD, timeout=20_000)
    expect(page.locator("#batch-add")).to_be_enabled()
    page.locator("#batch-add").click()
    row = page.locator("#batch-pending li")
    expect(row).to_have_count(1)
    text = row.text_content() or ""
    assert PAYLOAD in text
    assert "白底棚拍" in text and "右前方" in text
    assert "<img" not in (row.inner_html() or "").lower()
    assert row.locator("img").count() == 0
    assert_inert(page)


def test_model_batch_submit_disables_and_network_error_is_failure(admin_page, batch_host: dict[str, Any]) -> None:
    page = admin_page
    _watch_inflight(page)

    def fail_submit(route) -> None:
        path = urlparse(route.request.url).path
        if route.request.method == "POST" and path.endswith("/composition/batch"):
            route.abort("failed")
            return
        route.fallback()

    page.route("**/api/product-models/**", fail_submit)
    _open_batch_model(page, batch_host)
    expect(page.locator("#composition-sku")).to_have_value(HOST_SKU, timeout=20_000)
    expect(page.locator("#batch-add")).to_be_enabled()
    page.locator("#batch-add").click()
    expect(page.locator("#batch-pending")).to_contain_text(HOST_SKU)
    page.locator("#batch-accept").check()
    submit = page.locator("#batch-submit")
    expect(submit).to_be_enabled()
    submit.click()
    message = page.locator("#batch-message")
    expect(message).to_contain_text("送出失敗")
    assert SUCCESS_BATCH not in (message.text_content() or "")
    assert re.search(r"\berror\b", message.get_attribute("class") or "")
    expect(submit).to_be_enabled()
    assert HOST_SKU in (page.locator("#batch-pending").text_content() or "")
    posts = [
        row for row in page.evaluate("() => window.__fox3dInflight")
        if row["method"] == "POST" and row["url"].endswith("/composition/batch")
    ]
    assert posts and posts[-1]["submitDisabled"] is True
    assert_inert(page)
