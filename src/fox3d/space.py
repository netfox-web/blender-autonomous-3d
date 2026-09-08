"""Room / Space Digital Twin — data model + mock pipeline (no photogrammetry yet)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fox3d.ids import new_id

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
    walls: list[dict[str, Any]] = Field(default_factory=list)
    pipelineStatus: str = "mock"
    futureAdapters: tuple[str, ...] = FUTURE_ADAPTERS


class SpacePipeline:
    def ingest(self, payload: dict[str, Any]) -> SpaceDigitalTwin:
        twin = SpaceDigitalTwin.model_validate(payload)
        if not twin.walls and twin.width and twin.depth:
            twin.walls = [
                {"name": "N", "length": twin.width, "height": twin.height},
                {"name": "S", "length": twin.width, "height": twin.height},
                {"name": "E", "length": twin.depth, "height": twin.height},
                {"name": "W", "length": twin.depth, "height": twin.height},
            ]
        twin.pipelineStatus = "mock_ready"
        return twin
