"""Tests for the E-Commerce Modular Cabinet Combiner, 3D Scene Builder, and Matrix API."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform
from fox3d.ecommerce_scene_studio import (
    CABINET_PRESETS,
    BUILTIN_SCENES,
    build_modular_cabinet_spec,
    compile_custom_scene,
)


def test_build_modular_cabinet_presets():
    for preset in CABINET_PRESETS:
        spec = build_modular_cabinet_spec(preset, tenant_id="sonaqueen-home")
        assert spec["kind"] == "MODULAR_CABINET"
        assert spec["family"] == "cabinet"
        assert spec["goldenRecipe"] is True
        assert spec["recipePreview"] is True
        assert len(spec["components"]) >= 5
        expected_w = sum(c["widthMm"] for c in preset["columns"])
        expected_h = max(c["heightMm"] for c in preset["columns"])
        assert spec["width"] == expected_w
        assert spec["height"] == expected_h


def _front_camera_distance(scene_def: dict) -> float:
    look = scene_def["camera"]["lookAt"]
    loc = scene_def["camera"]["location"]
    # FRONT side is 0, so the framing distance is the camera's -Y offset from the aim point.
    return float(look[1]) - float(loc[1])


def test_front_view_camera_distance_covers_furniture_span():
    """50 mm on a 36 mm sensor sees width dist * 0.72, so FRONT distance is span / 0.72."""
    scene = next(s for s in BUILTIN_SCENES if s["id"] == "SCENE_PH_FRENCH_CREAM_LIVING")
    cab = build_modular_cabinet_spec(CABINET_PRESETS[0], tenant_id="sonaqueen-home")
    scene_def, _scene_hash = compile_custom_scene(scene, cab, view="FRONT")

    px = float(scene["productPose"]["x"])
    prop_xs = [
        float(p.get("x") or 0.0)
        for p in scene["props"]
        if str(p.get("type") or "").upper() not in ("WINDOW_FRAME", "SHEER_CURTAIN")
    ]
    span = abs(px - min(prop_xs)) + 1.0
    assert span == 4.9

    dist = _front_camera_distance(scene_def)
    lens = 50.0
    # Camera coordinates are rounded to 0.0001 m.
    assert dist == pytest.approx(span / 0.72, abs=5e-4)
    field_width = dist * (36.0 / lens)
    assert field_width >= span - 5e-4
    # span * 0.72 (the inverted formula) yields ~3.528 m and a field only ~2.54 m wide.
    assert span * 0.72 * (36.0 / lens) < span * 0.6

    look_x = float(scene_def["camera"]["lookAt"][0])
    half_view = dist * (18.0 / lens)
    w_m = float(cab["width"]) / 1000.0
    assert look_x - half_view <= px - w_m / 2.0 + 1e-3
    assert look_x + half_view >= px + w_m / 2.0 - 1e-3
    assert scene_def["camera"]["focalLengthMm"] == lens
    assert scene_def["camera"]["location"][0] == pytest.approx(look_x, abs=5e-4)


def test_front_preview_uses_span_divided_by_field_ratio():
    js = Path(__file__).resolve().parents[1].joinpath("src/fox3d/static/scene-studio.js").read_text(encoding="utf-8")
    assert "span / 0.72" in js
    assert "span * 0.72" not in js


def test_compile_custom_scene_produces_furnished_scene_v1():
    cab_spec = build_modular_cabinet_spec(CABINET_PRESETS[1], tenant_id="sonaqueen-home")
    scene_cfg = dict(BUILTIN_SCENES[0])
    scene_Cfg_rot = {**scene_cfg, "productPose": {"x": 0.25, "y": 1.10, "z": 0.0, "rotationDeg": 45.0}}
    scene_def, scene_hash = compile_custom_scene(scene_Cfg_rot, cab_spec, view="THREE_QUARTER")
    assert scene_def["rendererContract"] == "FURNISHED_SCENE_V1"
    assert scene_def["photorealMode"] is True
    assert len(scene_hash) == 64
    assert len(scene_def["boxes"]) > 10
    assert len(scene_def["lights"]) == 3
    assert len(scene_def["productMatrix"]) == 4


def test_ecommerce_scene_studio_api_and_workbench(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}

    page = client.get("/admin/recipes/scenes")
    assert page.status_code == 200
    assert "組合櫃自由拼裝" in page.text
    assert "Content-Security-Policy" in page.headers

    for asset in ("scene-studio.css", "scene-studio.js"):
        r_asset = client.get(f"/admin/recipes/assets/{asset}")
        assert r_asset.status_code == 200

    ov = client.get("/api/ecommerce-scenes/overview", headers=headers)
    assert ov.status_code == 200
    body = ov.json()
    assert len(body["cabinetPresets"]) >= 5
    assert len(body["styleThemes"]) >= 6
    assert len(body["scenes"]) >= 6

    plan = client.post(
        "/api/ecommerce-scenes/preview-plan",
        headers=headers,
        json={
            "cabinet": body["cabinetPresets"][2],
            "sceneId": "SCENE_JAPANDI_BEDROOM",
            "view": "LEFT",
        },
    )
    assert plan.status_code == 200
    p_data = plan.json()
    assert p_data["cabinetSpec"]["width"] == 1272
    assert p_data["sceneDefinition"]["view"] == "LEFT"

    saved = client.post(
        "/api/ecommerce-scenes/scenes",
        headers=headers,
        json={
            "name": "測試自訂北歐書房",
            "category": "書房",
            "roomWidthM": 5.0,
            "roomDepthM": 3.8,
            "roomHeightM": 2.9,
            "wallColorHex": "#d0c8b8",
            "sideWallColorHex": "#b8c0b8",
            "floorColorHex": "#7a5c3e",
            "lightingPreset": "NORDIC_BRIGHT",
            "productPose": {"x": -0.2, "y": 1.05, "z": 0.0, "rotationDeg": 0.0},
            "props": [
                {"id": "p1", "type": "DESK", "label": "書桌", "x": 1.1, "y": 0.9, "z": 0.0, "widthM": 1.3, "depthM": 0.6, "heightM": 0.75}
            ],
        },
    )
    assert saved.status_code == 201
    custom_id = saved.json()["id"]
    assert custom_id.startswith("SCENE_CUSTOM_")

    ov2 = client.get("/api/ecommerce-scenes/overview", headers=headers).json()
    assert any(s["id"] == custom_id for s in ov2["scenes"])

    deleted = client.delete(f"/api/ecommerce-scenes/scenes/{custom_id}", headers=headers)
    assert deleted.status_code == 200
