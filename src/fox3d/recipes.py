"""Recipe intelligence + autonomous research (never overwrites PRODUCTION)."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id
from fox3d.infra import RECIPE_LIFECYCLE, Recipe, RecipeRegistry
from fox3d.rd import VisionJudge
from fox3d.studio import CAMERA_RECIPES, LIGHTING_RECIPES


class RecipeIntelligence:
    def __init__(self, registry: RecipeRegistry) -> None:
        self.registry = registry

    def record(self, recipe_id: str, *, success: bool) -> None:
        self.registry.record_usage(recipe_id, success=success)

    def snapshot(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = []
        for recipe in self.registry.find(tenant_id=tenant_id):
            rows.append(
                {
                    "recipeId": recipe.recipe_id,
                    "type": recipe.recipe_type,
                    "version": recipe.version,
                    "status": recipe.status,
                    "score": recipe.score,
                    "usageCount": recipe.usage_count,
                    "successRate": recipe.success_rate,
                    "tags": recipe.tags,
                    "compatibleCapabilities": recipe.compatible_capabilities,
                }
            )
        return rows


class BlenderRecipeResearchAgent:
    def __init__(self, registry: RecipeRegistry, judge: VisionJudge | None = None) -> None:
        self.registry = registry
        self.judge = judge or VisionJudge()

    def research_idle(self, *, tenant_id: str, gpu_idle: bool = True) -> list[Recipe]:
        if not gpu_idle:
            return []
        created: list[Recipe] = []
        for lighting in LIGHTING_RECIPES:
            for camera in ("HERO_SHOT", "MACRO", "TOP_DOWN"):
                recipe = Recipe(
                    recipe_id=new_id(),
                    recipe_key=f"{lighting}+{camera}.research",
                    recipe_type="PRODUCT",
                    status="EXPERIMENTAL",
                    tenant_id=tenant_id,
                    configuration={"lighting": lighting, "camera": camera, "preview": True, "samples": 8, "resolution": 256},
                    tags=["research", lighting, camera],
                    compatible_capabilities=["BLENDER_PREVIEW"],
                    name=f"Research {lighting} {camera}",
                )
                preview = {
                    "sceneGraph": {"camera": {"fill": 0.7}, "objects": [{"name": "Product"}]},
                    "dsl": {"scene": "WHITE_STUDIO"},
                    "variantId": recipe.recipe_id,
                }
                judged = self.judge.score(preview=preview, spec=None, quote={"estimatedCost": 1000}, report_ok=True)
                recipe.score = judged["overall"]
                self.registry.upsert(recipe)
                if recipe.score >= 0.7:
                    self.registry.promote(recipe.recipe_id, "CANDIDATE")
                created.append(recipe)
        return created

    def promote_candidate(self, recipe_id: str, *, to: str = "APPROVED") -> Recipe:
        recipe = self.registry.get(recipe_id)
        if not recipe:
            raise KeyError(recipe_id)
        if recipe.status == "PRODUCTION":
            raise ValueError("research must not overwrite PRODUCTION")
        return self.registry.promote(recipe_id, to)
