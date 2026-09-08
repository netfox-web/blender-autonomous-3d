"""GPU placement policy adapter — never pins Blender to a specific card."""

from __future__ import annotations

from typing import Any

from fox3d.capabilities import FINAL_RENDER_CAPABILITIES, PREVIEW_CAPABILITIES, VIDEO_CAPABILITIES
from fox3d.infra import Scheduler


class GpuPolicy:
    def lane(self, job_type: str) -> str:
        if job_type in VIDEO_CAPABILITIES:
            return "ai_video"
        if job_type in PREVIEW_CAPABILITIES:
            return "blender_preview"
        if job_type in FINAL_RENDER_CAPABILITIES:
            return "blender_final"
        return "general"

    def annotate(self, job: dict[str, Any]) -> dict[str, Any]:
        job = dict(job)
        job["lane"] = self.lane(str(job.get("jobType") or ""))
        job["pinForbidden"] = True
        return job

    def place(self, scheduler: Scheduler, job: dict[str, Any]) -> dict[str, Any]:
        annotated = self.annotate(job)
        decision = scheduler.place(annotated)
        if annotated.get("gpuRequirement", {}).get("exactTargetKey") and not job.get("operatorPinned"):
            # Capability match may *prefer* a target; the engine itself must not bind Blender to one GPU.
            pass
        decision["pinForbidden"] = True
        decision["lane"] = annotated["lane"]
        return decision
