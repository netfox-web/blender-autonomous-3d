"""Unit tests for RecipeIntelligence and BlenderRecipeResearchAgent."""

from __future__ import annotations

from typing import Any

import pytest

from fox3d.infra import Recipe, RecipeRegistry
from fox3d.recipes import BlenderRecipeResearchAgent, RecipeIntelligence


class _FixedJudge:
    def score(self, **kwargs: Any) -> dict[str, float]:
        return {"overall": 0.5}


class _HighJudge:
    def score(self, **kwargs: Any) -> dict[str, float]:
        return {"overall": 0.85}


def _sample_recipe(*, tenant_id: str = "tenant-a", status: str = "EXPERIMENTAL", recipe_id: str = "r1") -> Recipe:
    return Recipe(
        recipe_id=recipe_id,
        recipe_key="product.demo",
        recipe_type="PRODUCT",
        status=status,
        tenant_id=tenant_id,
        configuration={"samples": 8},
        tags=["demo"],
        compatible_capabilities=["BLENDER_PREVIEW"],
        name="Demo",
    )


def test_research_idle_returns_empty_when_gpu_busy():
    agent = BlenderRecipeResearchAgent(RecipeRegistry(), judge=_FixedJudge())
    assert agent.research_idle(tenant_id="t1", gpu_idle=False) == []


def test_research_idle_creates_tenant_scoped_experimental_or_candidate():
    registry = RecipeRegistry()
    agent = BlenderRecipeResearchAgent(registry, judge=_HighJudge())
    created = agent.research_idle(tenant_id="shop-z", gpu_idle=True)
    assert created
    assert all(r.tenant_id == "shop-z" for r in created)
    assert all(r.status in {"EXPERIMENTAL", "CANDIDATE"} for r in created)


def test_snapshot_includes_tenant_and_system_with_expected_fields():
    registry = RecipeRegistry()
    intel = RecipeIntelligence(registry)
    registry.upsert(_sample_recipe(tenant_id="t1", recipe_id="tenant-recipe"))
    registry.upsert(
        _sample_recipe(tenant_id="system", recipe_id="system-recipe", status="PRODUCTION")
    )
    registry.upsert(_sample_recipe(tenant_id="other", recipe_id="hidden"))
    rows = {row["recipeId"]: row for row in intel.snapshot("t1")}
    assert set(rows) == {"tenant-recipe", "system-recipe"}
    expected_keys = {
        "recipeId",
        "type",
        "version",
        "status",
        "score",
        "usageCount",
        "successRate",
        "tags",
        "compatibleCapabilities",
    }
    for row in rows.values():
        assert set(row) == expected_keys


def test_record_increments_usage_and_success_rate():
    registry = RecipeRegistry()
    intel = RecipeIntelligence(registry)
    registry.upsert(_sample_recipe())
    intel.record("r1", success=True)
    intel.record("r1", success=False)
    intel.record("r1", success=True)
    row = intel.snapshot("tenant-a")[0]
    assert row["usageCount"] == 3
    assert row["successRate"] == pytest.approx(2 / 3)


def test_promote_candidate_to_approved():
    registry = RecipeRegistry()
    agent = BlenderRecipeResearchAgent(registry, judge=_FixedJudge())
    recipe = _sample_recipe(status="CANDIDATE")
    registry.upsert(recipe)
    promoted = agent.promote_candidate("r1", to="APPROVED")
    assert promoted.status == "APPROVED"


def test_promote_candidate_rejects_production_target():
    registry = RecipeRegistry()
    agent = BlenderRecipeResearchAgent(registry, judge=_FixedJudge())
    registry.upsert(_sample_recipe(status="CANDIDATE"))
    with pytest.raises(ValueError, match="CANDIDATE or APPROVED"):
        agent.promote_candidate("r1", to="PRODUCTION")


def test_promote_candidate_rejects_unknown_target():
    registry = RecipeRegistry()
    agent = BlenderRecipeResearchAgent(registry, judge=_FixedJudge())
    registry.upsert(_sample_recipe(status="CANDIDATE"))
    with pytest.raises(ValueError, match="CANDIDATE or APPROVED"):
        agent.promote_candidate("r1", to="BROKEN")


def test_promote_candidate_missing_recipe_raises_key_error():
    agent = BlenderRecipeResearchAgent(RecipeRegistry(), judge=_FixedJudge())
    with pytest.raises(KeyError):
        agent.promote_candidate("missing-id")


def test_registry_promote_unknown_status_has_clear_message():
    registry = RecipeRegistry()
    recipe = _sample_recipe(status="EXPERIMENTAL")
    recipe.status = "RETIRED"
    registry.upsert(recipe)
    with pytest.raises(ValueError, match="unknown recipe status: RETIRED"):
        registry.promote("r1", "APPROVED")
    registry.upsert(_sample_recipe(status="EXPERIMENTAL"))
    with pytest.raises(ValueError, match="unknown recipe status: FOO"):
        registry.promote("r1", "FOO")
