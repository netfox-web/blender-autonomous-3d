"""Offline VideoRecipe checks. No provider and no Blender render."""
from __future__ import annotations

import copy

import pytest

from fox3d.parametric import CabinetEngine
from fox3d.video_recipe import (
    MAX_EXTENT_MM,
    articulation_gate,
    expected_objects,
    frame_plan,
    make_recipe,
)

PRESETS = {
    "HERO_ORBIT_8S": 8,
    "DOOR_OPEN_8S": 8,
    "ARTWORK_DETAIL_6S": 6,
    "SMALL_ROOM_10S": 10,
    "ASSEMBLY_EXPLODE_10S": 10,
}


@pytest.fixture(scope="module")
def cabinet():
    spec, _ = CabinetEngine().create(
        "STORAGE_CABINET", tenant_id="recipe-test", width=2400, height=1800, doorCount=4
    )
    engineering = spec.model_dump(mode="json")
    return {"engineering": engineering, "artwork": next(iter(expected_objects(engineering)))}


def _recipe(cabinet, kind, **kwargs):
    if kind == "ARTWORK_DETAIL_6S":
        kwargs.setdefault("artwork_object", cabinet["artwork"])
    return make_recipe(kind, cabinet["engineering"], width=32, height=32, **kwargs)


@pytest.mark.parametrize("kind,duration", list(PRESETS.items()))
@pytest.mark.parametrize("fps", [1, 12, 60])
def test_preset_duration_fps_and_frame_count_agree(cabinet, kind, duration, fps):
    recipe = _recipe(cabinet, kind, fps=fps)
    assert recipe["duration"] == duration
    assert recipe["fps"] == fps
    assert type(recipe["frameCount"]) is int
    assert recipe["frameCount"] == duration * fps
    assert recipe["frameCount"] == recipe["duration"] * recipe["fps"]
    last = frame_plan(recipe, recipe["frameCount"] - 1)
    assert last["index"] == recipe["frameCount"] - 1
    assert last["timestamp"] == (recipe["frameCount"] - 1) / fps
    with pytest.raises(ValueError, match="strict_integer:frame"):
        frame_plan(recipe, recipe["frameCount"])


def test_resolution_and_extent_at_cap_are_accepted(cabinet):
    recipe = make_recipe(
        "HERO_ORBIT_8S", cabinet["engineering"], fps=60, width=2048, height=2048
    )
    assert recipe["frameCount"] == 8 * 60
    engineering = copy.deepcopy(cabinet["engineering"])
    for key in ("width", "height", "depth"):
        engineering[key] = MAX_EXTENT_MM
    capped = make_recipe("HERO_ORBIT_8S", engineering, fps=1, width=32, height=32)
    assert capped["duration"] == 8 and capped["frameCount"] == 8


@pytest.mark.parametrize(
    "field,value",
    [
        ("fps", 0),
        ("fps", -1),
        ("fps", float("nan")),
        ("fps", 10**9),
        ("width", 0),
        ("width", -5),
        ("width", float("nan")),
        ("width", 10**7),
        ("height", 0),
        ("height", -8),
        ("height", float("nan")),
        ("height", 99999),
    ],
)
def test_recipe_rejects_zero_negative_nan_and_huge_numbers(cabinet, field, value):
    kwargs = {"fps": 12, "width": 128, "height": 128}
    kwargs[field] = value
    with pytest.raises(ValueError, match="strict_integer"):
        make_recipe("HERO_ORBIT_8S", cabinet["engineering"], **kwargs)


@pytest.mark.parametrize("key", ["width", "height", "depth"])
@pytest.mark.parametrize(
    "value,match",
    [
        (0, "engineering_dimensions"),
        (-1, "engineering_dimensions"),
        (float("nan"), "strict_finite"),
        (1e12, "engineering_dimensions"),
        (MAX_EXTENT_MM + 1, "engineering_dimensions"),
    ],
)
def test_engineering_extent_rejects_zero_negative_nan_and_huge(cabinet, key, value, match):
    engineering = copy.deepcopy(cabinet["engineering"])
    engineering[key] = value
    with pytest.raises(ValueError, match=match):
        make_recipe("HERO_ORBIT_8S", engineering, fps=1, width=32, height=32)


@pytest.mark.parametrize(
    "kind,token",
    [
        ("DOOR_OPEN_8S", "BLOCKED_ARTICULATION_AUTHORITY"),
        ("ASSEMBLY_EXPLODE_10S", "BLOCKED_ASSEMBLY_AUTHORITY"),
    ],
)
def test_insufficient_authority_preset_is_blocked(cabinet, kind, token):
    recipe = _recipe(cabinet, kind, fps=1)
    forged = {"ready": True, "claim": "REAL", "pivot": [0, 0, 0], "axis": [0, 0, 1], "range": [0, 90]}
    with pytest.raises(ValueError, match=token):
        articulation_gate(recipe, forged)


@pytest.mark.parametrize("kind", ["HERO_ORBIT_8S", "ARTWORK_DETAIL_6S", "SMALL_ROOM_10S"])
def test_presets_with_current_authority_are_not_blocked(cabinet, kind):
    recipe = _recipe(cabinet, kind, fps=1)
    articulation_gate(recipe, None)
    articulation_gate(recipe, {"ready": True, "claim": "REAL"})
