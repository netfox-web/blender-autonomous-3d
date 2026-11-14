"""Browser coverage for preview cancel races on product-models and recipe-library pages."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

HEADERS = {"X-Tenant-Id": "sonaqueen-home"}
TASK_A = "browser-cancel-task-a"
TASK_B = "browser-cancel-task-b"


def _cabinet_draft(name: str) -> dict[str, Any]:
    return {
        "name": name,
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
    }


def _create_models(base_url: str, label: str) -> tuple[str, str, str, str]:
    tag = label.replace(" ", "-")
    with httpx.Client(base_url=base_url, headers=HEADERS, timeout=30.0) as client:
        a = client.post(
            "/api/product-models",
            json={"draft": _cabinet_draft(f"{tag}-A"), "expectedRevision": 0},
        ).json()
        b = client.post(
            "/api/product-models",
            json={"draft": _cabinet_draft(f"{tag}-B"), "expectedRevision": 0},
        ).json()
    return a["id"], b["id"], f"{tag}-A", f"{tag}-B"


def _running_preview(task_id: str) -> dict[str, Any]:
    return {
        "state": "running",
        "taskId": task_id,
        "generated": False,
        "stale": False,
        "error": None,
        "generationId": None,
    }


def _idle_preview() -> dict[str, Any]:
    return {
        "state": "idle",
        "taskId": None,
        "generated": False,
        "stale": False,
        "error": None,
        "generationId": None,
    }


def _running_recipe_status(task_id: str, *, progress: float = 0.0) -> dict[str, Any]:
    return {
        "state": "running",
        "taskId": task_id,
        "generated": False,
        "stale": False,
        "error": None,
        "progress": progress,
        "generationId": "gen-fixture",
        "sourceRevision": 1,
        "renderInfo": {"device": "Cycles"},
        "bom": {"lines": []},
    }


def _idle_recipe_status() -> dict[str, Any]:
    return {
        "state": "idle",
        "taskId": None,
        "generated": False,
        "stale": False,
        "error": None,
        "progress": 0,
        "generationId": None,
        "sourceRevision": 1,
        "renderInfo": None,
        "bom": {"lines": []},
    }


def _terminal_recipe_status(state: str) -> dict[str, Any]:
    generated = state == "succeeded"
    return {
        "state": state,
        "taskId": None,
        "generated": generated,
        "stale": False,
        "error": None,
        "progress": 1.0 if generated else 0.0,
        "generationId": "gen-fixture" if generated else None,
        "sourceRevision": 1,
        "renderInfo": {"device": "Cycles"} if generated else None,
        "bom": {"lines": []},
    }


def _recipe_plan() -> dict[str, Any]:
    return {
        "ready": True,
        "blenderAvailable": True,
        "revision": 1,
        "planHash": "fixture-hash",
        "assumptions": [],
        "spec": None,
    }


def _console_errors(page) -> list[str]:
    errors = list(getattr(page, "_fox3d_console_errors", []))
    return [e for e in errors if "Failed to load resource" not in e and "favicon" not in e.lower()]


def _click_cancel(page, selector: str = "#cancel") -> None:
    page.evaluate("(sel) => document.querySelector(sel)?.click()", selector)


def test_product_models_cancel_stays_locked_during_poll(admin_page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    model_a, _, name_a, _ = _create_models(base, "cancel-lock")
    preview = _running_preview(TASK_A)
    pending: list[Any] = []
    cancel_posts = 0

    def intercept(route):
        nonlocal cancel_posts
        path = urlparse(route.request.url).path
        if model_a in path and path.endswith("/preview") and route.request.method == "GET":
            return route.fulfill(json=preview)
        if model_a in path and path.endswith("/cancel") and route.request.method == "POST":
            cancel_posts += 1
            pending.append(route)
            return
        return route.fallback()

    page = admin_page
    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/product-models/**", intercept)
    page.goto(f"{base}/admin/recipes/models", wait_until="domcontentloaded")
    page.wait_for_selector("#masters button")
    page.locator("#masters button").filter(has_text=name_a).first.click()
    expect(page.locator("#cancel")).to_be_enabled(timeout=10_000)
    _click_cancel(page)
    expect(page.locator("#cancel")).to_be_disabled()
    page.evaluate("() => document.getElementById('status').click()")
    expect(page.locator("#cancel")).to_be_disabled()
    assert cancel_posts == 1
    pending[0].fulfill(json={"taskId": TASK_A, "cancelRequested": True})
    page.wait_for_timeout(300)
    expect(page.locator("#cancel")).to_be_enabled()
    assert _console_errors(page) == []


def test_product_models_tracks_multiple_pending_cancellations(admin_page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    model_a, model_b, name_a, name_b = _create_models(base, "cancel-multiple")
    pending: dict[str, Any] = {}
    posts: list[str] = []

    def intercept(route):
        path = urlparse(route.request.url).path
        mid = path.split("/")[-2]
        if mid in (model_a, model_b) and path.endswith("/preview") and route.request.method == "GET":
            return route.fulfill(json=_running_preview(TASK_A if mid == model_a else TASK_B))
        if mid in (model_a, model_b) and path.endswith("/cancel") and route.request.method == "POST":
            posts.append(mid)
            pending[mid] = route
            return
        return route.fallback()

    page = admin_page
    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/product-models/**", intercept)
    page.goto(f"{base}/admin/recipes/models", wait_until="domcontentloaded")
    page.wait_for_selector("#masters button")
    for name in (name_a, name_b):
        page.locator("#masters button").filter(has_text=name).first.click()
        expect(page.locator("#cancel")).to_be_enabled(timeout=10_000)
        _click_cancel(page)
        expect(page.locator("#cancel")).to_be_disabled()
    page.locator("#masters button").filter(has_text=name_a).first.click()
    expect(page.locator("#render-state")).to_contain_text("Blender 生成中")
    expect(page.locator("#cancel")).to_be_disabled()
    _click_cancel(page)
    assert posts == [model_a, model_b]
    pending[model_b].fulfill(json={"taskId": TASK_B, "cancelRequested": True})
    page.wait_for_timeout(300)
    expect(page.locator("#cancel")).to_be_disabled()
    pending[model_a].fulfill(json={"taskId": TASK_A, "cancelRequested": True})
    expect(page.locator("#cancel")).to_be_enabled(timeout=10_000)
    assert _console_errors(page) == []


def test_product_models_failed_cancel_does_not_enable_other_model(admin_page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    model_a, model_b, name_a, name_b = _create_models(base, "cancel-race")
    pending: list[Any] = []

    def intercept(route):
        path = urlparse(route.request.url).path
        if path.endswith("/preview") and route.request.method == "GET":
            mid = path.split("/")[-2]
            if mid == model_a:
                return route.fulfill(json=_running_preview(TASK_A))
            if mid == model_b:
                return route.fulfill(json=_idle_preview())
        if model_a in path and path.endswith("/cancel") and route.request.method == "POST":
            pending.append(route)
            return
        return route.fallback()

    page = admin_page
    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/product-models/**", intercept)
    page.goto(f"{base}/admin/recipes/models", wait_until="domcontentloaded")
    page.wait_for_selector("#masters button")
    page.locator("#masters button").filter(has_text=name_a).first.click()
    expect(page.locator("#cancel")).to_be_enabled(timeout=10_000)
    _click_cancel(page)
    expect(page.locator("#cancel")).to_be_disabled()
    page.locator("#masters button").filter(has_text=name_b).first.click()
    expect(page.locator("#cancel")).to_be_disabled(timeout=10_000)
    pending[0].fulfill(status=400, json={"detail": "取消失敗（測試）"})
    page.wait_for_timeout(400)
    expect(page.locator("#cancel")).to_be_disabled()
    assert _console_errors(page) == []


def test_recipe_library_failed_cancel_after_product_switch(admin_page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    pending: list[Any] = []
    primary_sku = "LI-D40"
    other_sku = "MY-012"

    def intercept(route):
        path = urlparse(route.request.url).path
        if path.endswith("/3d/status") and route.request.method == "GET":
            sku = path.split("/")[-3]
            if sku == primary_sku:
                return route.fulfill(json=_running_recipe_status(TASK_A))
            return route.fulfill(json=_idle_recipe_status())
        if path.endswith("/3d/plan") and route.request.method == "GET":
            return route.fulfill(json=_recipe_plan())
        if path.endswith("/3d/cancel") and route.request.method == "POST" and primary_sku in path:
            pending.append(route)
            return
        return route.fallback()

    page = admin_page
    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/recipe-library/**", intercept)
    page.goto(f"{base}/admin/recipes", wait_until="domcontentloaded")
    page.locator(f'[data-sku="{primary_sku}"]').click()
    page.locator("#threed-tab").click()
    expect(page.locator("#cancel-preview")).to_be_enabled()
    _click_cancel(page, "#cancel-preview")
    expect(page.locator("#cancel-preview")).to_be_disabled()
    page.locator(f'[data-sku="{other_sku}"]').click()
    page.locator("#threed-tab").click()
    expect(page.locator("#cancel-preview")).to_have_count(0)
    pending[0].fulfill(status=400, json={"detail": "取消失敗（測試）"})
    page.wait_for_timeout(400)
    expect(page.locator("#cancel-preview")).to_have_count(0)
    assert _console_errors(page) == []


def test_recipe_library_failed_cancel_after_poll_rerender(admin_page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    pending: list[Any] = []
    sku = "LI-D40"

    def intercept(route):
        path = urlparse(route.request.url).path
        if path.endswith("/3d/status") and route.request.method == "GET":
            if pending:
                return route.fulfill(json=_terminal_recipe_status("succeeded"))
            return route.fulfill(json=_running_recipe_status(TASK_A, progress=0.15))
        if path.endswith("/3d/plan") and route.request.method == "GET":
            return route.fulfill(json=_recipe_plan())
        if path.endswith("/3d/cancel") and route.request.method == "POST":
            pending.append(route)
            return
        return route.fallback()

    page = admin_page
    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/recipe-library/**", intercept)
    page.goto(f"{base}/admin/recipes", wait_until="domcontentloaded")
    page.locator(f'[data-sku="{sku}"]').click()
    page.locator("#threed-tab").click()
    expect(page.locator("#cancel-preview")).to_be_enabled(timeout=10_000)
    _click_cancel(page, "#cancel-preview")
    expect(page.locator("#cancel-preview")).to_be_disabled()
    page.wait_for_timeout(100)
    assert pending, "cancel POST was not intercepted"
    page.wait_for_timeout(2800)
    expect(page.locator("#cancel-preview")).to_have_count(0)
    pending[0].fulfill(status=400, json={"detail": "取消失敗（測試）"})
    page.wait_for_timeout(400)
    expect(page.locator("#cancel-preview")).to_have_count(0)
    assert _console_errors(page) == []
