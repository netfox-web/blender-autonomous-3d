"""Browser coverage for draft revision restore confirm snapshot and network failure recovery."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from playwright.sync_api import Page, Route

from tests.browser.conftest import TENANT

pytestmark = pytest.mark.browser


def _path(url: str) -> str:
    return urlparse(url).path


def _cabinet_draft(name: str = "Revision browser fixture", notes: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "family": "cabinet",
        "subtype": "open",
        "geometry": "OPEN_CABINET",
        "widthMm": 424,
        "depthMm": 295,
        "heightMm": 900,
        "panelMm": 15,
        "backMm": 3,
        "rows": 3,
        "dimensionEvidence": "fixture",
        "structureEvidence": "fixture",
        "notes": notes,
        "variants": [],
    }


def _seed_three_revisions(base: str) -> tuple[str, str]:
    client = httpx.Client(base_url=base, headers={"X-Tenant-Id": TENANT}, timeout=30.0)
    created = client.post("/api/product-models", json={"expectedRevision": 0, "draft": _cabinet_draft()}).json()
    mid = created["id"]
    item = created
    for expected, notes in ((1, "note-v2"), (2, "note-v3")):
        item = client.put(
            f"/api/product-models/{mid}",
            json={"expectedRevision": expected, "draft": {**item["draft"], "notes": notes}},
        ).json()
    client.close()
    return mid, item["draft"]["name"]


def _open_model(page: Page, base: str, model_name: str) -> None:
    page.goto(base + "/admin/recipes/models", wait_until="domcontentloaded")
    page.wait_for_selector(".fx-side", timeout=20_000)
    page.wait_for_function(
        "() => window.fox3dShell && typeof window.fox3dShell.data === 'function' && window.fox3dShell.data()",
        timeout=20_000,
    )
    page.wait_for_function(
        "() => (document.getElementById('notice').textContent || '').includes('從左側分類')",
        timeout=30_000,
    )
    page.locator("#masters button, #generated-masters button").filter(has_text=model_name).first.click()
    page.wait_for_selector("#revision-history-card:not([hidden])", timeout=20_000)


def test_product_models_restore_confirm_snapshot_ignores_late_pick(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    _, model_name = _seed_three_revisions(base)
    restore_paths: list[str] = []
    page = admin_page

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "POST" and path.endswith("/restore"):
            restore_paths.append(path)
            route.fulfill(
                json={
                    "id": path.split("/")[-3],
                    "revision": 99,
                    "draft": _cabinet_draft(model_name, "restored"),
                    "inputHash": "a" * 64,
                    "readiness": {"previewReady": True, "missing": None, "assumptions": [], "printReady": False},
                }
            )
            return
        route.fallback()

    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/product-models**", intercept)
    _open_model(page, base, model_name)
    page.locator("#revision-list button").first.click()
    page.locator("#revision-restore").click()
    assert page.evaluate("() => document.getElementById('restore-revision-dialog').returnValue") == ""
    page.locator("#revision-list button").nth(1).click(force=True)
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/restore")) as captured:
        page.locator("#restore-revision-confirm").click()
    assert captured.value.url.endswith("/revisions/1/restore")
    assert len(restore_paths) == 1


def test_product_models_restore_abort_shows_error_and_reenables_button(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    _, model_name = _seed_three_revisions(base)
    page = admin_page

    def intercept(route: Route) -> None:
        if route.request.method == "POST" and _path(route.request.url).endswith("/restore"):
            route.abort("failed")
            return
        route.fallback()

    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/product-models**", intercept)
    _open_model(page, base, model_name)
    page.locator("#revision-list button").first.click()
    page.locator("#revision-restore").click()
    page.locator("#restore-revision-confirm").click()
    page.wait_for_function("() => document.getElementById('notice').className === 'error'")
    assert "另存為第" not in page.locator("#notice").inner_text()
    page.wait_for_function("() => !document.getElementById('restore-revision-confirm').disabled")


def test_product_models_revision_detail_race_keeps_latest_selection(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    base = admin_server["base_url"]
    _, model_name = _seed_three_revisions(base)
    page = admin_page
    held: list[Route] = []

    def intercept(route: Route) -> None:
        path = _path(route.request.url)
        if route.request.method == "GET" and path.endswith("/revisions/1"):
            held.append(route)
            return
        route.fallback()

    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    page.route("**/api/product-models/**", intercept)
    _open_model(page, base, model_name)
    buttons = page.locator("#revision-list button")
    buttons.first.click()
    buttons.nth(1).click()
    for route in held:
        route.fallback()
    page.wait_for_function(
        "() => document.getElementById('revision-diff').textContent.includes('note-v2')",
        timeout=15_000,
    )


def test_product_models_variant_only_revision_shows_diff(admin_page: Page, admin_server: dict[str, Any]) -> None:
    base = admin_server["base_url"]
    client = httpx.Client(base_url=base, headers={"X-Tenant-Id": TENANT}, timeout=30.0)
    draft = _cabinet_draft("Variant diff fixture")
    draft["variants"] = [{"sku": "SKU-ONE", "artworkAssetId": "", "note": ""}]
    created = client.post("/api/product-models", json={"expectedRevision": 0, "draft": draft}).json()
    mid = created["id"]
    next_draft = {**created["draft"], "variants": [{"sku": "SKU-TWO", "artworkAssetId": "", "note": ""}]}
    client.put(f"/api/product-models/{mid}", json={"expectedRevision": 1, "draft": next_draft})
    client.close()
    page = admin_page
    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    _open_model(page, base, draft["name"])
    page.locator("#revision-list button").first.click()
    page.wait_for_function(
        "() => document.getElementById('revision-diff').textContent.includes('關聯 SKU')",
        timeout=15_000,
    )
    assert "與目前版本相同" not in page.locator("#revision-diff").inner_text()


def test_product_models_restore_confirms_unsaved_classification(
    admin_page: Page, admin_server: dict[str, Any]
) -> None:
    base = admin_server["base_url"]
    _, model_name = _seed_three_revisions(base)
    page = admin_page
    page.add_init_script("window.mountRecipeViewer = () => () => {};")
    _open_model(page, base, model_name)
    dialogs: list[str] = []

    def on_dialog(dialog) -> None:
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", on_dialog)
    options = page.locator("#model-category option")
    if options.count() < 2:
        pytest.skip("fixture category tree has fewer than two leaf options")
    current = page.locator("#model-category").input_value()
    alt = None
    for i in range(options.count()):
        value = options.nth(i).get_attribute("value")
        if value and value != current:
            alt = value
            break
    assert alt is not None
    page.select_option("#model-category", alt)
    page.locator("#revision-list button").first.click()
    page.locator("#revision-restore").click()
    assert any("分類" in message for message in dialogs)