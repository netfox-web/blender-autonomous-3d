"""Room / Space Digital Twin + constraint engine + wall-fit solver.

Photogrammetry / Gaussian / SLAM remain future adapters (MOCK).
Manual millimetre JSON is a real, deterministic path.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from fox3d.ids import new_id, stable_hash

FUTURE_ADAPTERS = (
    "photogrammetry",
    "Gaussian Splatting",
    "depth estimation",
    "SLAM",
)


class Opening(BaseModel):
    kind: str  # door|window
    width: float
    height: float
    sill: float = 0
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    wallId: str | None = None
    startMm: float | None = None
    keepOutExtraMm: float = 40


class WallSegment(BaseModel):
    wallId: str = Field(default_factory=new_id)
    name: str
    length: float
    height: float
    thickness: float = 100
    origin: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    direction: list[float] = Field(default_factory=lambda: [1.0, 0.0])


class KeepOutZone(BaseModel):
    zoneId: str = Field(default_factory=new_id)
    kind: Literal["door", "window", "column", "beam", "skirting", "outlet", "reserved"]
    wallId: str
    startMm: float
    endMm: float
    z0: float = 0
    z1: float = 2600
    depthMm: float = 100
    reason: str = ""


class SpaceDigitalTwin(BaseModel):
    spaceId: str = Field(default_factory=new_id)
    tenantId: str
    photos: list[str] = Field(default_factory=list)
    floorplan: str | None = None
    width: float = 0
    depth: float = 0
    height: float = 2600
    doors: list[Opening] = Field(default_factory=list)
    windows: list[Opening] = Field(default_factory=list)
    columns: list[dict[str, Any]] = Field(default_factory=list)
    sockets: list[dict[str, Any]] = Field(default_factory=list)
    walls: list[WallSegment] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    obstacles: list[dict[str, Any]] = Field(default_factory=list)
    outlets: list[dict[str, Any]] = Field(default_factory=list)
    keepOuts: list[KeepOutZone] = Field(default_factory=list)
    room: dict[str, Any] = Field(default_factory=dict)
    pipelineStatus: str = "mock"
    photogrammetryStatus: str = "mock"
    manualDimensions: bool = False
    futureAdapters: tuple[str, ...] = FUTURE_ADAPTERS

    def space_hash(self) -> str:
        return stable_hash(
            {
                "width": self.width,
                "depth": self.depth,
                "height": self.height,
                "walls": [w.model_dump() for w in self.walls],
                "keepOuts": [k.model_dump(exclude={"zoneId"}) for k in self.keepOuts],
            }
        )


def _rect_walls(width: float, depth: float, height: float, thickness: float = 100) -> list[WallSegment]:
    return [
        WallSegment(name="N", length=width, height=height, thickness=thickness, origin=[0.0, depth, 0.0], direction=[1.0, 0.0]),
        WallSegment(name="E", length=depth, height=height, thickness=thickness, origin=[width, depth, 0.0], direction=[0.0, -1.0]),
        WallSegment(name="S", length=width, height=height, thickness=thickness, origin=[width, 0.0, 0.0], direction=[-1.0, 0.0]),
        WallSegment(name="W", length=depth, height=height, thickness=thickness, origin=[0.0, 0.0, 0.0], direction=[0.0, 1.0]),
    ]


def _inward(direction: list[float]) -> tuple[float, float]:
    dx, dy = float(direction[0]), float(direction[1])
    return dy, -dx


class SpacePipeline:
    def ingest(self, payload: dict[str, Any]) -> SpaceDigitalTwin:
        data = dict(payload)
        raw_walls = data.pop("walls", None)
        twin = SpaceDigitalTwin.model_validate(data)
        if raw_walls:
            twin.walls = [w if isinstance(w, WallSegment) else WallSegment.model_validate(w) for w in raw_walls]
        if not twin.walls and twin.width and twin.depth:
            twin.walls = _rect_walls(twin.width, twin.depth, twin.height)
        wall_by_name = {w.name: w for w in twin.walls}
        default_wall = twin.walls[0] if twin.walls else None
        keep: list[KeepOutZone] = list(twin.keepOuts)

        def _opening_keepout(op: Opening, kind: str) -> None:
            wall = wall_by_name.get(op.wallId or "") if op.wallId else None
            if wall is None and default_wall is not None:
                wall = default_wall
                op.wallId = wall.wallId
            if wall is None:
                return
            start = float(op.startMm if op.startMm is not None else (op.position[0] if op.position else 0))
            extra = float(op.keepOutExtraMm or 0)
            keep.append(
                KeepOutZone(
                    kind=kind,  # type: ignore[arg-type]
                    wallId=wall.wallId,
                    startMm=max(0.0, start - extra),
                    endMm=min(wall.length, start + op.width + extra),
                    z0=op.sill,
                    z1=op.sill + op.height,
                    depthMm=max(80.0, extra + 40),
                    reason=f"{kind} opening",
                )
            )

        for op in twin.doors:
            _opening_keepout(op, "door")
        for op in twin.windows:
            _opening_keepout(op, "window")
        for col in twin.columns:
            wall_id = col.get("wallId") or (default_wall.wallId if default_wall else "")
            start = float(col.get("startMm") or col.get("x") or 0)
            width = float(col.get("width") or 200)
            keep.append(
                KeepOutZone(
                    kind="column",
                    wallId=wall_id,
                    startMm=start,
                    endMm=start + width,
                    z0=0,
                    z1=twin.height,
                    depthMm=float(col.get("depth") or 200),
                    reason="column",
                )
            )
        for beam in twin.obstacles:
            if str(beam.get("kind") or "") == "beam":
                wall_id = beam.get("wallId") or (default_wall.wallId if default_wall else "")
                start = float(beam.get("startMm") or 0)
                keep.append(
                    KeepOutZone(
                        kind="beam",
                        wallId=wall_id,
                        startMm=start,
                        endMm=start + float(beam.get("width") or 400),
                        z0=float(beam.get("z0") or twin.height - 300),
                        z1=twin.height,
                        depthMm=float(beam.get("depth") or 200),
                        reason="beam",
                    )
                )
        for sock in list(twin.sockets) + list(twin.outlets):
            wall_id = sock.get("wallId") or (default_wall.wallId if default_wall else "")
            start = float(sock.get("startMm") or sock.get("x") or 0)
            keep.append(
                KeepOutZone(
                    kind="outlet",
                    wallId=wall_id,
                    startMm=start,
                    endMm=start + float(sock.get("width") or 80),
                    z0=float(sock.get("z0") or 300),
                    z1=float(sock.get("z1") or 400),
                    depthMm=40,
                    reason="outlet",
                )
            )
        # Skirting keep-out along every wall, 80mm high, does not block floor-standing cabinets
        # but is recorded for lineage.
        for wall in twin.walls:
            keep.append(
                KeepOutZone(
                    kind="skirting",
                    wallId=wall.wallId,
                    startMm=0,
                    endMm=wall.length,
                    z0=0,
                    z1=80,
                    depthMm=18,
                    reason="skirting",
                )
            )
        twin.keepOuts = keep
        twin.openings = list(twin.doors) + list(twin.windows)
        twin.room = {"width": twin.width, "depth": twin.depth, "height": twin.height}
        twin.manualDimensions = bool(twin.width and twin.depth)
        twin.photogrammetryStatus = "mock"
        # Keep existing ingest contract: photo pipeline is mock; JSON rooms still report mock_ready.
        twin.pipelineStatus = "mock_ready"
        return twin

    def create_manual(self, payload: dict[str, Any]) -> SpaceDigitalTwin:
        return self.ingest(payload)


class SpaceConstraintEngine:
    """Cabinets must not occupy walls, openings, columns, or reserved keep-outs."""

    def validate(self, space: SpaceDigitalTwin, placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        walls = {w.wallId: w for w in space.walls}
        walls_by_name = {w.name: w for w in space.walls}
        blocking = [k for k in space.keepOuts if k.kind in {"door", "window", "column", "reserved"}]
        for p in placements:
            wall = walls.get(p.get("wallId") or "") or walls_by_name.get(p.get("wallId") or "")
            if wall is None:
                violations.append({"code": "UNKNOWN_WALL", "message": f"wall {p.get('wallId')} not in space", "severity": "error"})
                continue
            start = float(p.get("startMm") or p.get("originX") or 0)
            width = float(p.get("width") or 0)
            end = start + width
            if start < -0.5 or end > wall.length + 0.5:
                violations.append({"code": "THROUGH_WALL", "message": f"cabinet {start:.0f}-{end:.0f} exceeds wall {wall.length:.0f}", "severity": "error", "wallId": wall.wallId})
            for zone in blocking:
                if zone.wallId != wall.wallId:
                    continue
                if start < zone.endMm - 0.5 and end > zone.startMm + 0.5:
                    z0 = float(p.get("originZ") or 0)
                    z1 = z0 + float(p.get("height") or space.height)
                    if z0 < zone.z1 - 0.5 and z1 > zone.z0 + 0.5:
                        violations.append(
                            {
                                "code": f"{zone.kind.upper()}_COLLISION",
                                "message": f"cabinet overlaps {zone.kind} keep-out {zone.startMm:.0f}-{zone.endMm:.0f}",
                                "severity": "error",
                                "wallId": wall.wallId,
                            }
                        )
        return violations


class LayoutCandidate(BaseModel):
    candidateId: str = Field(default_factory=new_id)
    wallId: str
    gapMm: float
    clearanceMm: float
    symmetric: bool
    placements: list[dict[str, Any]] = Field(default_factory=list)
    rejected: bool = False
    reasons: list[str] = Field(default_factory=list)
    spaceHash: str = ""
    layoutHash: str = ""


class WallFitSolver:
    def __init__(self, constraints: SpaceConstraintEngine | None = None) -> None:
        self.constraints = constraints or SpaceConstraintEngine()

    def available_intervals(self, space: SpaceDigitalTwin, wall: WallSegment, *, clearance: float) -> list[tuple[float, float]]:
        blocked: list[list[float]] = [[0.0, max(0.0, clearance)], [max(0.0, wall.length - clearance), wall.length]]
        for zone in space.keepOuts:
            if zone.wallId != wall.wallId:
                continue
            if zone.kind in {"skirting", "outlet", "beam"}:
                continue
            blocked.append([max(0.0, zone.startMm - clearance), min(wall.length, zone.endMm + clearance)])
        blocked.sort()
        merged: list[list[float]] = []
        for a, b in blocked:
            if not merged or a > merged[-1][1]:
                merged.append([a, b])
            else:
                merged[-1][1] = max(merged[-1][1], b)
        gaps: list[tuple[float, float]] = []
        for i in range(len(merged) - 1):
            start = merged[i][1]
            end = merged[i + 1][0]
            if end - start >= 400:
                gaps.append((start, end))
        if not gaps and wall.length >= 400:
            gaps.append((clearance, max(clearance, wall.length - clearance)))
        return gaps

    def solve(
        self,
        space: SpaceDigitalTwin,
        wall_id: str,
        *,
        product_types: list[str] | None = None,
        gap: float = 20,
        min_clearance: float = 10,
        symmetric: bool = False,
        count: int = 8,
    ) -> list[LayoutCandidate]:
        from fox3d.furniture import FurnitureProductTypeRegistry

        wall = next((w for w in space.walls if w.wallId == wall_id or w.name == wall_id), None)
        if wall is None:
            return []
        types = product_types or ["STORAGE_CABINET"]
        registry = FurnitureProductTypeRegistry()
        intervals = self.available_intervals(space, wall, clearance=min_clearance)
        space_hash = space.space_hash()
        raw: list[list[dict[str, Any]]] = []

        def fill_equal(n: int, kind: str, interval: tuple[float, float]) -> list[dict[str, Any]] | None:
            start, end = interval
            span = end - start
            defaults = registry.get(kind)
            n = max(1, n)
            total_gap = gap * (n - 1)
            each = (span - total_gap) / n
            if each < 400 or each > 2440:
                return None
            each = min(each, max(defaults.defaultWidth, 600))
            used = n * each + total_gap
            origin = start + ((span - used) / 2 if symmetric else 0)
            out = []
            cursor = origin
            for _ in range(n):
                out.append(
                    {
                        "kind": kind,
                        "width": round(each, 1),
                        "height": defaults.defaultHeight,
                        "depth": defaults.defaultDepth,
                        "startMm": round(cursor, 1),
                        "originX": round(cursor, 1),
                        "originY": 0,
                        "originZ": 0,
                        "wallId": wall.wallId,
                    }
                )
                cursor += each + gap
            return out

        largest = max(intervals, key=lambda it: it[1] - it[0]) if intervals else (0.0, wall.length)
        for n in (1, 2, 3, 4):
            for kind in types[:3]:
                row = fill_equal(n, kind, largest)
                if row:
                    raw.append(row)
        if len(intervals) >= 2:
            mixed = []
            for interval, kind in zip(intervals[:2], (types[0], types[-1])):
                row = fill_equal(1, kind, interval)
                if row:
                    mixed.extend(row)
            if mixed:
                raw.append(mixed)
        if len(types) >= 2:
            combo = fill_equal(2, types[0], largest) or []
            if combo:
                combo[0]["kind"] = types[0]
                combo[-1]["kind"] = types[1]
                d0 = registry.get(types[0])
                d1 = registry.get(types[1])
                combo[0]["height"] = d0.defaultHeight
                combo[0]["depth"] = d0.defaultDepth
                combo[-1]["height"] = d1.defaultHeight
                combo[-1]["depth"] = d1.defaultDepth
                raw.append(combo)
        # Fixed-gap vs min-clearance variants
        alt = fill_equal(3, types[0], largest)
        if alt:
            raw.append(alt)

        candidates: list[LayoutCandidate] = []
        seen: set[str] = set()
        for placements in raw:
            key = stable_hash([(p["kind"], p["width"], p["startMm"]) for p in placements])
            if key in seen:
                continue
            seen.add(key)
            violations = self.constraints.validate(space, placements)
            reasons = [v["code"] + ":" + v["message"] for v in violations]
            cand = LayoutCandidate(
                wallId=wall.wallId,
                gapMm=gap,
                clearanceMm=min_clearance,
                symmetric=symmetric,
                placements=placements,
                rejected=bool(violations),
                reasons=reasons,
                spaceHash=space_hash,
            )
            cand.layoutHash = stable_hash(placements)
            candidates.append(cand)
            if len(candidates) >= max(3, min(10, count)):
                break
        legal = [c for c in candidates if not c.rejected]
        if len(legal) < 3:
            # Pad with smaller equal fills if wall is clear enough.
            for n in range(1, 6):
                row = fill_equal(n, types[0], largest)
                if not row:
                    continue
                violations = self.constraints.validate(space, row)
                cand = LayoutCandidate(
                    wallId=wall.wallId,
                    gapMm=gap,
                    clearanceMm=min_clearance,
                    symmetric=symmetric,
                    placements=row,
                    rejected=bool(violations),
                    reasons=[v["code"] for v in violations],
                    spaceHash=space_hash,
                    layoutHash=stable_hash(row),
                )
                if cand.layoutHash not in {c.layoutHash for c in candidates}:
                    candidates.append(cand)
                if len([c for c in candidates if not c.rejected]) >= 3:
                    break
        return candidates[:10]
