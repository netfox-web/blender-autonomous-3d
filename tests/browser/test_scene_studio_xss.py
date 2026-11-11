"""XSS regression for /admin/recipes/scenes (scene tabs + batch gallery)."""

from __future__ import annotations

import copy
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from fox3d.ecommerce_scene_studio import CABINET_PRESETS
from tests.browser.conftest import TENANT, XSS_PROBE, XSS_STRING

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def scene_studio_xss(admin_server: dict[str, Any]) -> dict[str, Any]:
    base = admin_server["base_url"]
    headers = {"X-Tenant-Id": TENANT}
    with httpx.Client(base_url=base, headers=headers, timeout=60.0) as client:
        def post(path: str, **kwargs: Any) -> dict[str, Any]:
            response = client.post(path, **kwargs)
            assert response.is_success, response.text
            return response.json()

        scene = post(
            "/api/ecommerce-scenes/scenes",
            json={
                "name": XSS_STRING,
                "category": f"{XSS_PROBE}-scene-category",
                "roomWidthM": 5.0,
                "roomDepthM": 3.8,
                "roomHeightM": 2.9,
                "wallColorHex": "#d0c8b8",
                "sideWallColorHex": "#b8c0b8",
                "floorColorHex": "#7a5c3e",
                "lightingPreset": "NORDIC_BRIGHT",
                "productPose": {"x": -0.2, "y": 1.05, "z": 0.0, "rotationDeg": 0.0},
                "props": [
                    {
                        "id": "p1",
                        "type": "DESK",
                        "label": XSS_PROBE,
                        "x": 1.1,
                        "y": 0.9,
                        "z": 0.0,
                        "widthM": 1.3,
                        "depthM": 0.6,
                        "heightM": 0.75,
                    }
                ],
            },
        )
        scene_id = scene["id"]

        cabinet = copy.deepcopy(CABINET_PRESETS[0])
        cabinet["name"] = XSS_STRING
        batch = post(
            "/api/ecommerce-scenes/batches",
            json={
                "cabinet": cabinet,
                "sceneIds": [scene_id],
                "themeIds": ["THEME_NORDIC_OAK"],
                "views": ["FRONT"],
                "aiEngine": "off",
                "blenderEngine": "local",
            },
        )
        batch_id = batch["batchId"]

        deadline = time.time() + 90.0
        while time.time() < deadline:
            doc = client.get(f"/api/ecommerce-scenes/batches/{batch_id}").json()
            if doc.get("state") in ("completed", "failed", "interrupted"):
                assert doc.get("state") == "completed", doc
                break
            time.sleep(0.25)
        else:
            pytest.fail("scene-studio XSS batch did not complete in time")

    return {"base": base, "scene_id": scene_id, "batch_id": batch_id}


def assert_inert(page) -> None:  # noqa: ANN001
    assert page.evaluate("window.__fox3dXss || 0") == 0
    assert page.locator('img[src="x"]').count() == 0


@pytest.mark.parametrize("width", [400, 1440])
def test_scene_studio_xss_payload_renders_as_text(
    admin_page,
    scene_studio_xss: dict[str, Any],
    width: int,
    tmp_path: Path,
) -> None:
    page = admin_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(scene_studio_xss["base"] + "/admin/recipes/scenes", wait_until="domcontentloaded")
    page.locator('.wf-tab-btn[data-tab="tab-scene"]').click()
    page.wait_for_selector("#scene-tabs .scene-card", state="attached", timeout=30_000)
    scene_card = page.locator("#scene-tabs .scene-card").filter(has_text=XSS_PROBE).first
    scene_card.wait_for(timeout=30_000)
    scene_card.click()
    assert XSS_PROBE in scene_card.inner_text()
    assert_inert(page)

    page.locator('.wf-tab-btn[data-tab="tab-matrix"]').click()
    page.wait_for_selector("#blender-gallery .gallery-card", timeout=30_000)
    gallery = page.locator("#blender-gallery")
    assert XSS_PROBE in gallery.inner_text()
    picker = page.locator("#batch-picker")
    picker.wait_for()
    assert XSS_PROBE in picker.inner_text()

    body = page.inner_text("body")
    assert XSS_PROBE in body
    assert_inert(page)

    output = Path(os.environ.get("FOX3D_XSS_SCREENSHOTS", tmp_path))
    output.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output / f"scene-studio-{width}.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth") <= width + 2
