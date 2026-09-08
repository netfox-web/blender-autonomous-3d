"""Automatic product studio + camera / lighting / material recipe engines."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id
from fox3d.infra import RECIPE_TYPES, Recipe, RecipeRegistry
from fox3d.scene import STUDIO_PRESETS, CameraDSL, LightingDSL, SceneDSL, compile_scene_graph

CAMERA_RECIPES = (
    "STATIC",
    "ORBIT",
    "TURNTABLE",
    "PUSH_IN",
    "PULL_OUT",
    "DOLLY",
    "PAN",
    "TILT",
    "TOP_DOWN",
    "MACRO",
    "HERO_SHOT",
    "SLOW_PUSH_IN",
)

LIGHTING_RECIPES = (
    "SOFTBOX",
    "THREE_POINT",
    "RIM_LIGHT",
    "GOLD_RIM",
    "BEAUTY_SOFT",
    "PRODUCT_HARD",
    "NEON",
    "DAYLIGHT",
    "HDRI",
)

MATERIALS = (
    "plastic",
    "glass",
    "metal",
    "paper",
    "cardboard",
    "wood",
    "fabric",
    "liquid",
    "transparent",
    "glossy",
    "matte",
)

MATERIAL_BSDF: dict[str, dict[str, float]] = {
    "plastic": {"metallic": 0.0, "roughness": 0.35, "ior": 1.45},
    "glass": {"metallic": 0.0, "roughness": 0.02, "transmission": 1.0, "ior": 1.45},
    "metal": {"metallic": 1.0, "roughness": 0.2, "ior": 1.5},
    "paper": {"metallic": 0.0, "roughness": 0.7, "ior": 1.3},
    "cardboard": {"metallic": 0.0, "roughness": 0.75, "ior": 1.3},
    "wood": {"metallic": 0.0, "roughness": 0.55, "ior": 1.4},
    "fabric": {"metallic": 0.0, "roughness": 0.8, "sheen": 0.4},
    "liquid": {"metallic": 0.0, "roughness": 0.05, "transmission": 0.9, "ior": 1.33},
    "transparent": {"metallic": 0.0, "roughness": 0.05, "transmission": 0.85, "ior": 1.4},
    "glossy": {"metallic": 0.15, "roughness": 0.08, "ior": 1.5},
    "matte": {"metallic": 0.0, "roughness": 0.85, "ior": 1.4},
}


def seed_system_recipes(registry: RecipeRegistry, *, tenant_id: str = "system") -> None:
    for name in STUDIO_PRESETS:
        registry.upsert(
            Recipe(
                recipe_id=f"scene:{name}",
                recipe_key=name,
                recipe_type="SCENE",
                status="PRODUCTION",
                tenant_id=tenant_id,
                name=name,
                configuration={"preset": name},
                tags=["studio"],
                compatible_capabilities=["BLENDER_PRODUCT", "BLENDER_PREVIEW", "BLENDER_RENDER"],
            )
        )
    for name in CAMERA_RECIPES:
        params = _camera_params(name)
        registry.upsert(
            Recipe(
                recipe_id=f"camera:{name}",
                recipe_key=name,
                recipe_type="CAMERA",
                status="PRODUCTION",
                tenant_id=tenant_id,
                name=name,
                configuration=params,
                tags=["camera"],
                compatible_capabilities=["BLENDER_PRODUCT", "BLENDER_ANIMATION", "BLENDER_360"],
            )
        )
    for name in LIGHTING_RECIPES:
        registry.upsert(
            Recipe(
                recipe_id=f"lighting:{name}",
                recipe_key=name,
                recipe_type="LIGHTING",
                status="PRODUCTION",
                tenant_id=tenant_id,
                name=name,
                configuration={"preset": name},
                tags=["lighting"],
                compatible_capabilities=["BLENDER_PRODUCT", "BLENDER_RENDER"],
            )
        )
    for name, bsdf in MATERIAL_BSDF.items():
        registry.upsert(
            Recipe(
                recipe_id=f"material:{name}",
                recipe_key=name,
                recipe_type="MATERIAL",
                status="PRODUCTION",
                tenant_id=tenant_id,
                name=name,
                configuration=bsdf,
                tags=["material"],
                compatible_capabilities=["BLENDER_PRODUCT", "PARAMETRIC_3D"],
            )
        )


def _camera_params(name: str) -> dict[str, Any]:
    table: dict[str, dict[str, Any]] = {
        "STATIC": {"lens": 85, "movement": "STATIC", "degrees": 0, "duration": 0},
        "ORBIT": {"lens": 50, "movement": "ORBIT", "degrees": 360, "duration": 8},
        "TURNTABLE": {"lens": 85, "movement": "TURNTABLE", "degrees": 360, "duration": 8},
        "PUSH_IN": {"lens": 85, "movement": "PUSH_IN", "distanceDelta": -0.35, "duration": 4},
        "SLOW_PUSH_IN": {"lens": 85, "movement": "SLOW_PUSH_IN", "distanceDelta": -0.2, "duration": 6},
        "PULL_OUT": {"lens": 50, "movement": "PULL_OUT", "distanceDelta": 0.4, "duration": 4},
        "DOLLY": {"lens": 50, "movement": "DOLLY", "distanceDelta": 0.5, "duration": 5},
        "PAN": {"lens": 35, "movement": "PAN", "degrees": 30, "duration": 4},
        "TILT": {"lens": 50, "movement": "TILT", "degrees": 15, "duration": 3},
        "TOP_DOWN": {"lens": 50, "movement": "STATIC", "locationHint": "top"},
        "MACRO": {"lens": 100, "movement": "STATIC", "fill": 0.92},
        "HERO_SHOT": {"lens": 85, "movement": "STATIC", "fill": 0.7},
    }
    return table.get(name, {"lens": 50, "movement": name})


class MaterialEngine:
    def __init__(self, recipes: RecipeRegistry, gateway: Any | None = None) -> None:
        self.recipes = recipes
        self.gateway = gateway

    def suggest(self, *, tenant_id: str, images: list[str], metadata: dict[str, Any], twin_id: str | None = None) -> dict[str, Any]:
        """AI may suggest. It must not overwrite the official Digital Twin — a new version is created."""
        suggested = "plastic"
        if self.gateway:
            result = self.gateway.suggest_materials(images=images, metadata=metadata)
            suggested = str(result.get("suggested") or suggested)
        if suggested not in MATERIAL_BSDF:
            suggested = "plastic"
        recipe = Recipe(
            recipe_id=new_id(),
            recipe_key=f"{suggested}.suggested",
            recipe_type="MATERIAL",
            status="EXPERIMENTAL",
            tenant_id=tenant_id,
            configuration={**MATERIAL_BSDF[suggested], "sourceTwinId": twin_id, "images": images},
            tags=["ai-suggested", suggested],
            compatible_capabilities=["BLENDER_PRODUCT"],
            name=f"AI suggested {suggested}",
        )
        self.recipes.upsert(recipe)
        return {
            "suggested": suggested,
            "recipeId": recipe.recipe_id,
            "version": recipe.version,
            "status": recipe.status,
            "overwroteTwin": False,
        }

    def apply(self, name: str) -> dict[str, float]:
        return dict(MATERIAL_BSDF.get(name, MATERIAL_BSDF["plastic"]))


class ProductStudio:
    def build(
        self,
        *,
        twin: dict[str, Any],
        studio: str = "WHITE_STUDIO",
        camera: str = "HERO_SHOT",
        lighting: str = "SOFTBOX",
        output_formats: tuple[str, ...] = ("PNG", "WEBP", "EXR"),
    ) -> dict[str, Any]:
        if studio not in STUDIO_PRESETS and studio != "LUXURY_STUDIO":
            studio = "WHITE_STUDIO"
        cam = CameraDSL(recipe=camera, movement=_camera_params(camera).get("movement", "STATIC"), lens=_camera_params(camera).get("lens", 85))
        dsl = SceneDSL(scene=studio, product=twin.get("twinId"), camera=cam, lighting=LightingDSL(preset=lighting))
        graph = compile_scene_graph(dsl, product=twin)
        return {
            "steps": [
                "load_product",
                "center",
                "ground_placement",
                "camera_framing",
                "lighting",
                "shadow",
                "reflection",
                "dof",
                "render",
            ],
            "sceneGraph": graph,
            "outputFormats": list(output_formats),
            "dsl": dsl.model_dump(),
        }


assert set(CAMERA_RECIPES)
assert "SCENE" in RECIPE_TYPES
