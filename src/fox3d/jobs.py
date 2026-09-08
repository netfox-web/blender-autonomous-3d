"""BlenderJob — JSON-serializable, tenant-scoped, FoxStudio-queue compatible."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fox3d.capabilities import BLENDER_RENDER
from fox3d.ids import new_id

JobType = str
JobStatus = Literal[
    "blocked",
    "queued",
    "reserved",
    "dispatched",
    "leased",
    "running",
    "rendering",
    "uploading",
    "waiting_approval",
    "retry_scheduled",
    "cancel_requested",
    "cancelled",
    "failed",
    "skipped",
    "succeeded",
    "completed",
    "expired",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GpuRequirement(BaseModel):
    minVramGb: float | None = None
    preferGpuClass: Literal["discrete", "any"] = "discrete"
    allowCpu: bool = True
    preferTargetKeys: list[str] = Field(default_factory=list)
    # Never a hard pin unless the operator set exactTargetKey.
    exactTargetKey: str | None = None


class BlenderJob(BaseModel):
    model_config = ConfigDict(extra="allow")

    jobId: str = Field(default_factory=new_id)
    tenantId: str
    projectId: str = "default"
    assetId: str | None = None
    recipeId: str | None = None
    priority: int = 50
    jobType: JobType = BLENDER_RENDER
    inputAssets: list[str] = Field(default_factory=list)
    scene: dict[str, Any] = Field(default_factory=dict)
    camera: dict[str, Any] = Field(default_factory=dict)
    lighting: dict[str, Any] = Field(default_factory=dict)
    materials: dict[str, Any] = Field(default_factory=dict)
    animation: dict[str, Any] = Field(default_factory=dict)
    render: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    gpuRequirement: GpuRequirement = Field(default_factory=GpuRequirement)
    status: JobStatus = "queued"
    progress: float = 0.0
    createdAt: datetime = Field(default_factory=utcnow)
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    error: str | None = None
    attemptCount: int = 0
    maxAttempts: int = 3
    leaseOwner: str | None = None
    assignedComputeTargetKey: str | None = None
    heartbeatAt: datetime | None = None
    cancelRequested: bool = False
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    timeoutSeconds: float = 300.0

    @field_validator("scene", mode="before")
    @classmethod
    def _coerce_scene(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            return {"scene": value}
        return value or {}

    @field_validator("lighting", mode="before")
    @classmethod
    def _coerce_lighting(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            return {"preset": value}
        return value or {}

    def routing_requirements(self) -> dict[str, Any]:
        req: dict[str, Any] = {
            "blockType": _block_type(self.jobType),
            "requiredCapabilities": {"blender": True},
            "minVramGb": self.gpuRequirement.minVramGb,
        }
        if self.gpuRequirement.exactTargetKey:
            req["computeTargetKey"] = self.gpuRequirement.exactTargetKey
        if self.gpuRequirement.preferTargetKeys:
            req["allowedComputeTargets"] = self.gpuRequirement.preferTargetKeys
        return req


def _block_type(job_type: str) -> str:
    from fox3d.capabilities import FOXSTUDIO_OPERATION_BY_CAPABILITY

    return FOXSTUDIO_OPERATION_BY_CAPABILITY.get(job_type, "blender.render.final")
