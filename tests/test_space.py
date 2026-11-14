"""Offline unit coverage for SpaceConstraintEngine and WallFitSolver.

No Platform, Blender, or network. Millimetre fixtures only.
"""

from __future__ import annotations

from typing import Any, Literal

import pytest

from fox3d.ids import stable_hash
from fox3d.space import (
    KeepOutZone,
    SpaceConstraintEngine,
    SpaceDigitalTwin,
    WallFitSolver,
    WallSegment,
)

KeepKind = Literal["door", "window", "column", "beam", "skirting", "outlet", "reserved"]


def _wall(wall_id: str, length: float, name: str = "N", height: float = 2600) -> WallSegment:
    return WallSegment(wallId=wall_id, name=name, length=length, height=height)


def _zone(
    kind: KeepKind,
    wall_id: str,
    start: float,
    end: float,
    *,
    z0: float = 0,
    z1: float = 2600,
) -> KeepOutZone:
    return KeepOutZone(kind=kind, wallId=wall_id, startMm=start, endMm=end, z0=z0, z1=z1)


def _space(*walls: WallSegment, keep_outs: list[KeepOutZone] | None = None, height: float = 2600) -> SpaceDigitalTwin:
    return SpaceDigitalTwin(
        tenantId="tenant-test",
        height=height,
        width=walls[0].length if walls else 0,
        depth=3000,
        walls=list(walls),
        keepOuts=list(keep_outs or []),
    )


def _codes(space: SpaceDigitalTwin, placement: dict[str, Any]) -> list[str]:
    return [item["code"] for item in SpaceConstraintEngine().validate(space, [placement])]


def test_validate_unknown_wall():
    space = _space(_wall("w", 2000))
    violations = SpaceConstraintEngine().validate(space, [{"wallId": "missing", "startMm": 0, "width": 100, "height": 100}])
    assert violations == [
        {"code": "UNKNOWN_WALL", "message": "wall missing not in space", "severity": "error"},
    ]
    both = SpaceConstraintEngine().validate(
        space,
        [
            {"wallId": "missing", "startMm": 0, "width": 100, "height": 100},
            {"wallId": "w", "startMm": 0, "width": 2500, "height": 100},
        ],
    )
    assert [item["code"] for item in both] == ["UNKNOWN_WALL", "THROUGH_WALL"]


def test_validate_through_wall_tolerance():
    space = _space(_wall("w", 1000))
    engine = SpaceConstraintEngine()

    # Both edges sit on the ±0.5 mm boundary and are still inside the wall.
    on_boundary = engine.validate(space, [{"wallId": "w", "startMm": -0.5, "width": 1001, "height": 100, "originZ": 0}])
    assert on_boundary == []

    past_start = engine.validate(space, [{"wallId": "w", "startMm": -0.501, "width": 100, "height": 100, "originZ": 0}])
    assert [item["code"] for item in past_start] == ["THROUGH_WALL"]
    assert past_start[0]["wallId"] == "w"
    assert past_start[0]["severity"] == "error"

    past_end = engine.validate(space, [{"wallId": "w", "startMm": 0, "width": 1000.501, "height": 100, "originZ": 0}])
    assert [item["code"] for item in past_end] == ["THROUGH_WALL"]

    flush = engine.validate(space, [{"wallId": "w", "startMm": 0, "width": 1000, "height": 100, "originZ": 0}])
    assert flush == []

    # THROUGH_WALL does not skip keep-out checks on the same placement.
    door_space = _space(_wall("w", 1000), keep_outs=[_zone("door", "w", 100, 400)])
    both = engine.validate(door_space, [{"wallId": "w", "startMm": 0, "width": 1200, "height": 1800, "originZ": 0}])
    assert [item["code"] for item in both] == ["THROUGH_WALL", "DOOR_COLLISION"]


def test_validate_collision_needs_horizontal_and_vertical_overlap():
    wall = _wall("w", 4000)
    window = _zone("window", "w", 1000, 2000, z0=1000, z1=2000)
    space = _space(wall, keep_outs=[window])

    # Beside the window: vertical overlap only.
    assert _codes(space, {"wallId": "w", "startMm": 0, "width": 500, "originZ": 1200, "height": 400}) == []
    # Under the sill: horizontal overlap only.
    assert _codes(space, {"wallId": "w", "startMm": 1200, "width": 400, "originZ": 0, "height": 500}) == []
    # Neither interval overlaps.
    assert _codes(space, {"wallId": "w", "startMm": 2500, "width": 200, "originZ": 0, "height": 100}) == []
    # Both intervals overlap.
    assert _codes(space, {"wallId": "w", "startMm": 1200, "width": 400, "originZ": 1200, "height": 400}) == ["WINDOW_COLLISION"]

    # ±0.5 mm edges of the keep-out are not an overlap.
    assert _codes(space, {"wallId": "w", "startMm": 500, "width": 500.5, "originZ": 1200, "height": 400}) == []
    assert _codes(space, {"wallId": "w", "startMm": 1999.5, "width": 400, "originZ": 1200, "height": 400}) == []
    assert _codes(space, {"wallId": "w", "startMm": 1200, "width": 400, "originZ": 0, "height": 1000.5}) == []
    assert _codes(space, {"wallId": "w", "startMm": 1200, "width": 400, "originZ": 1999.5, "height": 400}) == []

    assert _codes(space, {"wallId": "w", "startMm": 500, "width": 500.501, "originZ": 1200, "height": 400}) == ["WINDOW_COLLISION"]
    assert _codes(space, {"wallId": "w", "startMm": 1999.499, "width": 400, "originZ": 1200, "height": 400}) == ["WINDOW_COLLISION"]
    assert _codes(space, {"wallId": "w", "startMm": 1200, "width": 400, "originZ": 0, "height": 1000.501}) == ["WINDOW_COLLISION"]
    assert _codes(space, {"wallId": "w", "startMm": 1200, "width": 400, "originZ": 1999.499, "height": 400}) == ["WINDOW_COLLISION"]


def test_validate_omitted_height_uses_space_height():
    space = _space(_wall("w", 3000), keep_outs=[_zone("window", "w", 1000, 2000, z0=2000, z1=2600)], height=2600)
    assert _codes(space, {"wallId": "w", "startMm": 1200, "width": 400, "originZ": 0, "height": 1800}) == []
    assert _codes(space, {"wallId": "w", "startMm": 1200, "width": 400, "originZ": 0}) == ["WINDOW_COLLISION"]


@pytest.mark.parametrize("kind", ["door", "window", "column", "reserved"])
def test_validate_blocking_kinds(kind: KeepKind):
    space = _space(_wall("w", 3000), _wall("other", 3000, name="S"), keep_outs=[_zone(kind, "w", 500, 1500, z0=0, z1=2200)])
    hit = _codes(space, {"wallId": "w", "startMm": 800, "width": 400, "originZ": 0, "height": 1800})
    assert hit == [f"{kind.upper()}_COLLISION"]
    # Same numbers on the other wall do not see this keep-out.
    assert _codes(space, {"wallId": "other", "startMm": 800, "width": 400, "originZ": 0, "height": 1800}) == []


@pytest.mark.parametrize("kind", ["skirting", "outlet", "beam"])
def test_validate_skirting_outlet_and_beam_do_not_block(kind: KeepKind):
    space = _space(_wall("w", 3000), keep_outs=[_zone(kind, "w", 0, 3000, z0=0, z1=2600)])
    assert _codes(space, {"wallId": "w", "startMm": 100, "width": 800, "originZ": 0, "height": 1800}) == []


def test_validate_resolves_wall_by_name():
    space = _space(
        _wall("wall-n", 2000, name="North"),
        _wall("wall-s", 2000, name="South"),
        keep_outs=[_zone("door", "wall-n", 100, 800)],
    )
    assert _codes(space, {"wallId": "North", "startMm": 1000, "width": 400, "height": 1800, "originZ": 0}) == []
    hit = SpaceConstraintEngine().validate(
        space,
        [{"wallId": "North", "startMm": 200, "width": 400, "height": 1800, "originZ": 0}],
    )
    assert [item["code"] for item in hit] == ["DOOR_COLLISION"]
    assert hit[0]["wallId"] == "wall-n"


def test_validate_start_mm_zero_is_not_replaced_by_origin_x():
    space = _space(_wall("w", 3000), keep_outs=[_zone("door", "w", 400, 900, z0=0, z1=2100)])
    # Occupies 0–300. originX would have put it on the door.
    assert _codes(
        space,
        {"wallId": "w", "startMm": 0, "originX": 500, "width": 300, "height": 1800, "originZ": 0},
    ) == []
    assert _codes(
        space,
        {"wallId": "w", "startMm": 0.0, "originX": -80, "width": 200, "height": 100, "originZ": 0},
    ) == []
    # Missing or explicit null startMm still falls back to originX.
    on_door = {"wallId": "w", "originX": 500, "width": 300, "height": 1800, "originZ": 0}
    assert _codes(space, on_door) == ["DOOR_COLLISION"]
    assert _codes(space, {**on_door, "startMm": None}) == ["DOOR_COLLISION"]


def test_available_intervals_expands_keepouts_merges_and_ignores_nonblocking():
    wall = _wall("w", 4000)
    other = _wall("other", 4000, name="S")
    space = _space(
        wall,
        other,
        keep_outs=[
            _zone("door", "w", 1000, 2000),
            _zone("column", "w", 1200, 1400),
            _zone("skirting", "w", 0, 4000, z0=0, z1=80),
            _zone("outlet", "w", 3000, 3200, z0=300, z1=1400),
            _zone("beam", "w", 3300, 3600, z0=2300, z1=2600),
            _zone("reserved", "other", 0, 4000),
        ],
    )
    intervals = WallFitSolver().available_intervals(space, wall, clearance=100)
    # Door grows by clearance to 900–2100. The column sits inside that span and
    # must not reopen a gap at its own end. Skirting, outlet, beam, and the
    # other wall do not block.
    assert intervals == [(100.0, 900.0), (2100.0, 3900.0)]


def test_available_intervals_drops_gaps_shorter_than_400mm():
    wall = _wall("w", 4000)
    solver = WallFitSolver()
    exact = _space(
        wall,
        keep_outs=[
            _zone("door", "w", 1000, 1400),
            _zone("window", "w", 1900, 2300, z0=900, z1=2100),
        ],
    )
    short = _space(
        wall,
        keep_outs=[
            _zone("door", "w", 1000, 1400),
            _zone("window", "w", 1899, 2300, z0=900, z1=2100),
        ],
    )
    # Clearance 50 leaves a 400 mm gap (kept) or a 399 mm gap (dropped).
    assert solver.available_intervals(exact, wall, clearance=50) == [
        (50.0, 950.0),
        (1450.0, 1850.0),
        (2350.0, 3950.0),
    ]
    assert solver.available_intervals(short, wall, clearance=50) == [
        (50.0, 950.0),
        (2350.0, 3950.0),
    ]


def test_available_intervals_fully_blocked_falls_back_to_whole_wall():
    solver = WallFitSolver()
    covered_wall = _wall("covered", 2500)
    covered = _space(covered_wall, keep_outs=[_zone("reserved", "covered", 0, 2500)])
    # The only crack is 399 mm, so it is discarded and the same fallback fires.
    crack_wall = _wall("crack", 2500)
    crack = _space(
        crack_wall,
        keep_outs=[
            _zone("column", "crack", 0, 1000),
            _zone("column", "crack", 1399, 2500),
        ],
    )
    short_wall = _wall("short", 399)
    short = _space(short_wall, keep_outs=[_zone("door", "short", 0, 399)])

    assert solver.available_intervals(covered, covered_wall, clearance=15) == [(15.0, 2485.0)]
    assert solver.available_intervals(crack, crack_wall, clearance=0) == [(0.0, 2500.0)]
    assert solver.available_intervals(short, short_wall, clearance=0) == []


def test_solve_unknown_wall_returns_empty_and_name_resolves():
    wall = _wall("wall-n", 2000, name="North")
    space = _space(wall)
    solver = WallFitSolver()
    assert solver.solve(space, "missing") == []
    assert solver.solve(space, "") == []
    found = solver.solve(space, "North", product_types=["STORAGE_CABINET"], min_clearance=0)
    assert found
    assert all(item.wallId == "wall-n" for item in found)


def test_solve_layout_hash_is_stable_for_the_same_input():
    wall = _wall("w", 2000)
    space = _space(wall)
    solver = WallFitSolver()
    kwargs: dict[str, Any] = {
        "product_types": ["STORAGE_CABINET"],
        "gap": 20,
        "min_clearance": 0,
        "symmetric": False,
    }
    first = solver.solve(space, wall.wallId, **kwargs)
    second = solver.solve(space, wall.wallId, **kwargs)
    assert first
    assert [item.layoutHash for item in first] == [item.layoutHash for item in second]
    assert len({item.layoutHash for item in first}) == len(first)
    assert {item.spaceHash for item in first} == {space.space_hash()}
    assert first[0].layoutHash == stable_hash(first[0].placements)
    assert first[0].gapMm == 20
    assert first[0].clearanceMm == 0
    assert first[0].symmetric is False


def test_solve_symmetric_centers_in_the_open_interval():
    # Door occupies 0–800, leaving 800–2800. Centering is inside that interval,
    # so the single 800 mm cabinet starts at 1400 rather than the wall centre.
    wall = _wall("w", 2800)
    space = _space(wall, keep_outs=[_zone("door", "w", 0, 800)])
    solver = WallFitSolver()
    common: dict[str, Any] = {"product_types": ["STORAGE_CABINET"], "gap": 20, "min_clearance": 0}
    centered = solver.solve(space, wall.wallId, symmetric=True, **common)
    flush = solver.solve(space, wall.wallId, symmetric=False, **common)
    centered_by_count = {len(item.placements): item for item in centered}
    flush_by_count = {len(item.placements): item for item in flush}

    one = centered_by_count[1]
    assert one.symmetric is True
    assert one.rejected is False
    assert one.placements[0]["startMm"] == 1400
    assert one.placements[0]["width"] == 800
    assert one.placements[0]["startMm"] - 800 == 2800 - (one.placements[0]["startMm"] + 800) == 600

    two = centered_by_count[2]
    last = two.placements[-1]
    left = two.placements[0]["startMm"] - 800
    right = 2800 - (last["startMm"] + last["width"])
    assert left == right == 190
    assert flush_by_count[1].placements[0]["startMm"] == 800
    assert one.layoutHash != flush_by_count[1].layoutHash


def test_solve_returns_at_most_ten_candidates():
    wall = _wall("w", 2200)
    space = _space(wall)
    candidates = WallFitSolver().solve(
        space,
        wall.wallId,
        product_types=["TV_CABINET", "WARDROBE", "DISPLAY_CABINET"],
        gap=20,
        min_clearance=0,
        count=50,
    )
    assert len(candidates) == 10
    assert len({item.layoutHash for item in candidates}) == 10
    assert all(not item.rejected for item in candidates)


def test_solve_pads_when_fewer_than_three_legal():
    # Equal splits for n=1..3 exceed 2440 mm, so the primary pass only emits
    # the two n=4 rows. Padding then adds the n=5 row of the first type.
    wall = _wall("w", 8000)
    space = _space(wall)
    candidates = WallFitSolver().solve(
        space,
        wall.wallId,
        product_types=["STORAGE_CABINET", "TV_CABINET"],
        gap=20,
        min_clearance=0,
        symmetric=False,
    )
    assert len(candidates) == 3
    assert all(not item.rejected for item in candidates)
    assert sorted(len(item.placements) for item in candidates) == [4, 4, 5]
    padded = next(item for item in candidates if len(item.placements) == 5)
    assert [placement["kind"] for placement in padded.placements] == ["STORAGE_CABINET"] * 5
    assert len({item.layoutHash for item in candidates}) == 3


def test_solve_does_not_pad_when_three_legal_already_exist():
    wall = _wall("w", 2200)
    space = _space(wall)
    candidates = WallFitSolver().solve(
        space,
        wall.wallId,
        product_types=["STORAGE_CABINET"],
        gap=20,
        min_clearance=0,
    )
    # n=5 would fit (424 mm) but the primary pass already has four legal rows.
    assert len(candidates) == 4
    assert sorted(len(item.placements) for item in candidates) == [1, 2, 3, 4]
    assert all(not item.rejected for item in candidates)


def test_solve_rejects_candidates_on_fully_blocked_fallback():
    wall = _wall("w", 3000)
    space = _space(wall, keep_outs=[_zone("reserved", "w", 0, 3000)])
    solver = WallFitSolver()
    assert solver.available_intervals(space, wall, clearance=10) == [(10.0, 2990.0)]
    candidates = solver.solve(
        space,
        wall.wallId,
        product_types=["STORAGE_CABINET"],
        gap=20,
        min_clearance=10,
        symmetric=False,
    )
    assert candidates
    assert all(item.rejected for item in candidates)
    assert all(item.placements[0]["startMm"] == 10.0 for item in candidates)
    assert all(any("RESERVED_COLLISION" in reason for reason in item.reasons) for item in candidates)
