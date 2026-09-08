"""Unified Scene JSON DSL. Workers build scenes from JSON — never a hand-edited .blend."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

STUDIO_PRESETS = (
    "WHITE_STUDIO",
    "BLACK_LUXURY",
    "BEAUTY",
    "FOOD",
    "TECH",
    "LIFESTYLE",
    "IP_PRODUCT",
    "REFLECTIVE",
    "SOFT_LIGHT",
    "LUXURY_STUDIO",
    "GOLD_RIM",
)


class CameraDSL(BaseModel):
    lens: float = 85
    movement: str = "STATIC"
    location: list[float] | None = None
    look_at: list[float] | None = None
    fill: float = 0.7
    recipe: str = "HERO_SHOT"


class LightingDSL(BaseModel):
    preset: str = "SOFTBOX"
    energy: float = 1.0
    recipe_id: str | None = None


class AnimationDSL(BaseModel):
    type: str = "NONE"
    degrees: float = 0
    duration: float = 0
    fps: int = 24


class SceneDSL(BaseModel):
    scene: str = "WHITE_STUDIO"
    product: str | None = None
    camera: CameraDSL = Field(default_factory=CameraDSL)
    lighting: str | LightingDSL = "SOFTBOX"
    animation: AnimationDSL = Field(default_factory=AnimationDSL)
    materials: dict[str, Any] = Field(default_factory=dict)
    extras: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_job(cls, payload: dict[str, Any]) -> "SceneDSL":
        scene = payload.get("scene") or {}
        if isinstance(scene, str):
            scene = {"scene": scene}
        merged = {
            **scene,
            "camera": payload.get("camera") or scene.get("camera") or {},
            "lighting": payload.get("lighting") or scene.get("lighting") or "SOFTBOX",
            "animation": payload.get("animation") or scene.get("animation") or {},
            "materials": payload.get("materials") or scene.get("materials") or {},
            "product": scene.get("product") or payload.get("product"),
        }
        if isinstance(merged["lighting"], dict) and "preset" not in merged["lighting"]:
            # allow {"preset": "GOLD_RIM"} or a raw string
            pass
        if isinstance(merged.get("lighting"), str):
            merged["lighting"] = {"preset": merged["lighting"]}
        return cls.model_validate(merged)


def _camera_distance(height_m: float, lens_mm: float, fill: float) -> float:
    # Full-frame 36mm sensor. Distance so object height fills `fill` of the frame.
    fov = 2 * math.atan((36.0 / 2.0) / max(lens_mm, 1.0))
    half = math.tan(fov / 2.0)
    if half <= 0:
        return 1.5
    return (height_m / 2.0) / (half * max(fill, 0.2))


def compile_scene_graph(
    dsl: SceneDSL,
    *,
    product: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure-Python scene graph consumed by bpy worker and the mock renderer."""
    dims = (product or {}).get("dimensions") or {}
    width = float(dims.get("width") or 0.2)
    height = float(dims.get("height") or 0.2)
    depth = float(dims.get("depth") or 0.2)
    # DSL / parametric data is millimetres for furniture; products may already be metres.
    if width > 5:
        width /= 1000.0
        height /= 1000.0
        depth /= 1000.0
    lighting = dsl.lighting if isinstance(dsl.lighting, LightingDSL) else LightingDSL(preset=str(dsl.lighting))
    distance = _camera_distance(height, dsl.camera.lens, dsl.camera.fill)
    cam_loc = dsl.camera.location or [0.0, -distance, height * 0.55]
    look = dsl.camera.look_at or [0.0, 0.0, height / 2.0]
    ground_y = 0.0
    objects = [
        {
            "name": "Ground",
            "type": "plane",
            "size": [4.0, 4.0, 0.01],
            "location": [0.0, 0.0, ground_y],
            "material": "studio_ground",
        },
        {
            "name": "Product",
            "type": "box",
            "size": [width, depth, height],
            "location": [0.0, 0.0, height / 2.0],
            "material": (dsl.materials or {}).get("product") or (product or {}).get("material") or "plastic",
            "asset": dsl.product,
        },
        {
            "name": "Camera",
            "type": "camera",
            "lens": dsl.camera.lens,
            "location": cam_loc,
            "look_at": look,
            "movement": dsl.camera.movement,
            "recipe": dsl.camera.recipe,
        },
    ]
    objects.extend(_lights_for_preset(lighting.preset, height, lighting.energy))
    return {
        "scene": dsl.scene,
        "studio": dsl.scene,
        "productId": dsl.product,
        "objects": objects,
        "world": {"preset": dsl.scene, "background": _world_color(dsl.scene)},
        "animation": dsl.animation.model_dump(),
        "lighting": lighting.model_dump(),
        "camera": dsl.camera.model_dump(),
        "framing": {
            "distance": distance,
            "groundPlacement": True,
            "centered": True,
        },
    }


def _world_color(preset: str) -> list[float]:
    table = {
        "WHITE_STUDIO": [0.92, 0.92, 0.94],
        "BLACK_LUXURY": [0.02, 0.02, 0.025],
        "BEAUTY": [0.86, 0.82, 0.80],
        "FOOD": [0.55, 0.42, 0.30],
        "TECH": [0.08, 0.10, 0.14],
        "LIFESTYLE": [0.75, 0.72, 0.68],
        "IP_PRODUCT": [0.15, 0.16, 0.22],
        "REFLECTIVE": [0.18, 0.18, 0.2],
        "SOFT_LIGHT": [0.88, 0.88, 0.86],
        "LUXURY_STUDIO": [0.12, 0.10, 0.08],
        "GOLD_RIM": [0.08, 0.07, 0.05],
    }
    return table.get(preset, [0.5, 0.5, 0.5])


def _lights_for_preset(preset: str, height: float, energy: float) -> list[dict[str, Any]]:
    z = max(height * 1.6, 0.6)
    key = {"name": "Light.Key", "type": "area", "size": [1.2, 1.2, 0], "location": [1.2, -1.4, z], "energy": 250 * energy, "color": [1, 0.98, 0.94]}
    fill = {"name": "Light.Fill", "type": "area", "size": [1.6, 1.6, 0], "location": [-1.4, -0.8, z * 0.8], "energy": 80 * energy, "color": [0.9, 0.95, 1]}
    rim = {"name": "Light.Rim", "type": "spot", "size": [0.4, 0.4, 0], "location": [0.2, 1.6, z], "energy": 180 * energy, "color": [1, 1, 1]}
    presets: dict[str, list[dict[str, Any]]] = {
        "SOFTBOX": [key, fill],
        "THREE_POINT": [key, fill, rim],
        "RIM_LIGHT": [fill, {**rim, "energy": 260 * energy}],
        "GOLD_RIM": [key, {**rim, "color": [1.0, 0.78, 0.35], "energy": 300 * energy}],
        "BEAUTY_SOFT": [{**key, "size": [2.0, 2.0, 0], "energy": 180 * energy}, {**fill, "energy": 140 * energy}],
        "PRODUCT_HARD": [{**key, "type": "spot", "energy": 400 * energy}, fill],
        "NEON": [
            {**key, "color": [0.2, 0.8, 1.0], "energy": 200 * energy},
            {**rim, "color": [1.0, 0.2, 0.7], "energy": 200 * energy},
        ],
        "DAYLIGHT": [{**key, "color": [0.85, 0.92, 1.0], "energy": 320 * energy}],
        "HDRI": [{**key, "energy": 40 * energy}],
    }
    return presets.get(preset, [key, fill])
