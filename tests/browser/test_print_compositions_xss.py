"""#502: hostile API values on /admin/recipes/print and the model-compositions panel stay plain text."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import pytest
from playwright.sync_api import expect

from tests.browser.conftest import TENANT

pytestmark = pytest.mark.browser

PAYLOAD = '"><img src=x onerror=window.__fox3dXss=1>'
JOB_ID = "job-xss-502"
ASSET_ID = 'asset"><img src=x onerror=window.__fox3dXss=2>'
GENERATION_ID = 'gen"><img src=x onerror=window.__fox3dXss=3>'
HOST_NAME = "composition-xss-host"
HOST_SKU = "SAFE-SKU-502"


def assert_inert(page) -> None:  # noqa: ANN001
    page.wait_for_timeout(300)
    assert page.locator('img[src="x"]').count() == 0
    assert page.locator("[onerror]").count() == 0
    assert page.evaluate("() => window.__fox3dXss || 0") == 0


def _stub_viewer(page) -> None:  # noqa: ANN001
    page.route(
        "**/admin/recipes/assets/recipe-viewer.js",
        lambda route: route.fulfill(
            content_type="application/javascript",
            body="window.mountRecipeViewer = () => () => {};",
        ),
    )


def _asset() -> dict[str, Any]:
    return {
        "id": ASSET_ID,
        "name": PAYLOAD,
        "info": {"type": "PDF", "pages": [{}, {}]},
        "usage": {"canUseForPrint": True, "canUseForModel": True, "role": PAYLOAD},
    }


def _job() -> dict[str, Any]:
    panels = [
        {
            "label": PAYLOAD,
            "assetId": ASSET_ID,
            "page": 0,
            "rotation": 0,
            "quantity": PAYLOAD,
            "imageWidthMm": PAYLOAD,
            "imageHeightMm": PAYLOAD,
            "imageBleedMm": PAYLOAD,
        },
        {"label": PAYLOAD, "assetId": "", "page": PAYLOAD, "rotation": 90, "quantity": 2},
        {"label": "下門", "assetId": "", "page": 0, "rotation": 0, "quantity": 1},
    ]
    plan_panels = [
        {
            "label": PAYLOAD,
            "page": 0,
            "rotation": PAYLOAD,
            "widthMm": 400.0,
            "heightMm": 300.0,
            "trimWidthMm": 396.0,
            "trimHeightMm": 296.0,
            "quantity": PAYLOAD,
        }
    ]
    return {
        "id": JOB_ID,
        "revision": PAYLOAD,
        "draft": {"sku": PAYLOAD, "name": PAYLOAD, "layout": "THREE_DOOR", "panels": panels},
        "plan": {"planHash": "fixture", "panels": plan_panels, "warnings": [PAYLOAD, "第二則" + PAYLOAD]},
        "spec": {},
        "lastProofId": None,
        "release": None,
        "blenderAvailable": False,
    }


def _print_workspace(route) -> None:  # noqa: ANN001
    request = route.request
    path = urlparse(request.url).path
    if "/printfox/" in path or request.method != "GET":
        route.fallback()
        return
    if path == "/api/print-workspace/assets":
        route.fulfill(json={"items": [_asset()]})
    elif path == "/api/print-workspace/jobs":
        job = _job()
        route.fulfill(json={"items": [{"id": job["id"], "draft": job["draft"], "revision": PAYLOAD}]})
    elif path == f"/api/print-workspace/jobs/{JOB_ID}":
        route.fulfill(json=_job())
    elif path == f"/api/print-workspace/jobs/{JOB_ID}/preview":
        route.fulfill(json={
            "state": "succeeded",
            "taskId": None,
            "generated": True,
            "generationId": GENERATION_ID,
            "error": PAYLOAD,
            "stale": False,
        })
    elif path == "/api/print-workspace/sources":
        route.fulfill(json={"configured": False, "total": 0, "items": []})
    elif "/preview" in path and path.startswith("/api/print-workspace/assets/"):
        route.fulfill(status=404, json={"detail": "fixture"})
    else:
        route.fallback()


def test_print_workspace_api_fields_render_as_text(admin_page, admin_server: dict[str, Any]) -> None:
    page = admin_page
    _stub_viewer(page)
    page.route("**/api/print-workspace/**", _print_workspace)
    page.goto(admin_server["base_url"] + "/admin/recipes/print", wait_until="domcontentloaded")

    jobs = page.locator("#jobs")
    job = jobs.locator(f'button[data-id="{JOB_ID}"]')
    expect(job).to_have_count(1)
    expect(job).to_contain_text(PAYLOAD)
    expect(job.locator("small")).to_have_text(f"{PAYLOAD} · 版本 {PAYLOAD}")
    assert jobs.locator("img").count() == 0

    job.click()
    expect(page.locator("#sku")).to_have_value(PAYLOAD)

    panels = page.locator("#panels .panel")
    expect(panels).to_have_count(3)
    first = panels.nth(0)
    expect(first.locator("[data-key=label]")).to_have_value(PAYLOAD)
    art = first.locator("[data-key=assetId]")
    expect(art).to_have_value(ASSET_ID)
    expect(art.locator("option:checked")).to_have_text(f"{PAYLOAD} · 2 頁")
    # Hostile "numbers" must not create markup; number inputs just drop them.
    assert first.locator("[data-key=quantity]").input_value() == ""
    assert first.locator("[data-key=imageWidthMm]").input_value() == ""
    expect(first.locator("img")).to_have_attribute("src", re.compile(re.escape(quote(ASSET_ID, safe=""))))
    expect(panels.nth(1).locator("[data-key=label]")).to_have_value(PAYLOAD)
    expect(panels.nth(1).locator("[data-key=rotation]")).to_have_value("90")
    assert page.locator("#panels img").count() == 3

    sheet = page.locator("#sheet .dimension")
    expect(sheet).to_have_count(1)
    expect(sheet.locator("strong")).to_have_text(PAYLOAD)
    expect(sheet).to_contain_text(f"旋轉 {PAYLOAD}°")
    expect(sheet).to_contain_text(f"{PAYLOAD} 件")
    expect(sheet).to_contain_text("完整版面 400.00 × 300.00 mm")
    assert sheet.locator("img").count() == 0

    warnings = page.locator("#warnings")
    expect(warnings).to_be_visible()
    assert (warnings.text_content() or "") == PAYLOAD + "第二則" + PAYLOAD
    expect(warnings.locator("br")).to_have_count(1)
    assert warnings.locator("img").count() == 0

    images = page.locator("#preview-images")
    expect(images.locator("img")).to_have_count(1)
    encoded = quote(GENERATION_ID, safe="")
    expect(images.locator("img")).to_have_attribute("src", re.compile(re.escape(f"/preview/{encoded}/front-closed.png")))
    links = images.locator("a")
    expect(links).to_have_count(3)
    for index, name in enumerate(("beauty.png", "model.glb", "model.blend")):
        expect(links.nth(index)).to_have_attribute("href", re.compile(re.escape(f"/preview/{encoded}/{name}")))
    expect(page.locator("#preview-state")).to_contain_text(PAYLOAD)
    expect(page.locator("#preview-lineage")).to_have_text(f"世代 {GENERATION_ID}")
    expect(page.locator("#assets")).to_contain_text(PAYLOAD)
    assert_inert(page)


@pytest.fixture(scope="module")
def composition_host(admin_server: dict[str, Any]) -> dict[str, Any]:
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
    return {"base": base, "id": saved["id"]}


def _poison_composition(route, model_id: str) -> None:  # noqa: ANN001
    path = urlparse(route.request.url).path
    if route.request.method != "GET":
        route.fallback()
        return
    if path == "/api/product-models/assets":
        response = route.fetch()
        data = response.json()
        asset = _asset()
        asset["usage"].update(role="MODEL_ARTWORK", revision=1)
        data["items"] = [*data.get("items", []), asset]
        route.fulfill(response=response, json=data)
        return
    if path != f"/api/product-models/{model_id}/composition":
        route.fallback()
        return
    response = route.fetch()
    data = response.json()
    surfaces = [{"componentId": "door-xss", "label": PAYLOAD, "widthMm": PAYLOAD, "heightMm": 300}]
    data.update(
        state="succeeded",
        taskId=None,
        generated=True,
        stale=False,
        error=None,
        generationId=GENERATION_ID,
        surfaces=surfaces,
        scenes={"STUDIO": PAYLOAD},
        manifest={
            "sourceRevision": PAYLOAD,
            "scene": "STUDIO",
            "draft": {
                "sku": PAYLOAD,
                "scene": "STUDIO",
                "placement": "AUTO",
                "view": "THREE_QUARTER",
                "placements": [{"componentId": "door-xss", "assetId": ASSET_ID, "page": 1, "rotation": 90}],
            },
            "spec": {"engineeringHash": PAYLOAD},
        },
    )
    route.fulfill(response=response, json=data)


def test_model_composition_fields_render_as_text(admin_page, composition_host: dict[str, Any]) -> None:
    page = admin_page
    model_id = composition_host["id"]
    page.route("**/api/print-workspace/assets/**", lambda route: route.fulfill(status=404, json={"detail": "fixture"}))
    page.route("**/api/product-models/**", lambda route: _poison_composition(route, model_id))
    page.goto(composition_host["base"] + "/admin/recipes/models", wait_until="domcontentloaded")
    expect(page.locator("#notice")).to_contain_text("從左側分類找模型", timeout=30_000)
    page.locator("#masters button").filter(has_text=HOST_NAME).click()

    face = page.locator("#composition-faces .composition-surface")
    expect(face).to_have_count(1, timeout=20_000)
    expect(face.locator("strong")).to_have_text(f"{PAYLOAD} · {PAYLOAD} × 300 mm")
    art = face.locator("select[data-art]")
    expect(art).to_have_value(ASSET_ID)
    expect(art.locator("option:checked")).to_have_text(PAYLOAD)
    expect(face.locator("select[data-page] option")).to_have_count(2)
    expect(face.locator("select[data-page]")).to_have_value("1")
    expect(face.locator("select[data-page] option").nth(1)).to_have_text("第 2 頁")
    expect(face.locator("select[data-rotation]")).to_have_value("90")
    source = face.locator("img.composition-source")
    expect(source).to_have_attribute("src", re.compile(re.escape(quote(ASSET_ID, safe="")) + r"/preview\?.*page=1"))

    downloads = page.locator("#composition-downloads a")
    expect(downloads).to_have_count(5)
    generation = re.escape("generation=" + quote(GENERATION_ID, safe="").replace("%20", "+"))
    for index, (name, label) in enumerate((
        ("beauty.png", "下載情境圖"),
        ("front-closed.png", "下載正面核對圖"),
        ("model.glb", "下載 GLB 模型"),
        ("model.blend", "下載 Blender 母版"),
        ("geometry.json", "下載尺寸紀錄"),
    )):
        link = downloads.nth(index)
        expect(link).to_have_text(label)
        expect(link).to_have_attribute("download", "")
        expect(link).to_have_attribute("href", re.compile(rf"/composition/files/{re.escape(name)}\?.*{generation}"))
    expect(page.locator("#composition-identity")).to_contain_text(PAYLOAD)
    assert page.locator("#composition-panel img").count() == 3
    assert_inert(page)
