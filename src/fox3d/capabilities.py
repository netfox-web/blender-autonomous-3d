"""Blender capabilities registered onto the existing Compute Node Registry.

FoxStudio matches jobs with `foxstudio_job_matches_compute_route` against
worker `operations` + `requiredCapabilities`. Fleet Console uses `taskType`.
Both maps live here so Blender is never a special-cased machine.
"""

from __future__ import annotations

from typing import Final

BLENDER_SCENE: Final = "BLENDER_SCENE"
BLENDER_PREVIEW: Final = "BLENDER_PREVIEW"
BLENDER_RENDER: Final = "BLENDER_RENDER"
BLENDER_ANIMATION: Final = "BLENDER_ANIMATION"
BLENDER_PRODUCT: Final = "BLENDER_PRODUCT"
BLENDER_360: Final = "BLENDER_360"
BLENDER_AR_ASSET: Final = "BLENDER_AR_ASSET"
BLENDER_SYNTHETIC_DATA: Final = "BLENDER_SYNTHETIC_DATA"
PARAMETRIC_3D: Final = "PARAMETRIC_3D"
BLENDER_TO_VIDEO: Final = "BLENDER_TO_VIDEO"
SYNTHETIC_DATA: Final = "SYNTHETIC_DATA"
PRODUCT_360: Final = "PRODUCT_360"

BLENDER_CAPABILITIES: tuple[str, ...] = (
    BLENDER_SCENE,
    BLENDER_PREVIEW,
    BLENDER_RENDER,
    BLENDER_ANIMATION,
    BLENDER_PRODUCT,
    BLENDER_360,
    BLENDER_AR_ASSET,
    BLENDER_SYNTHETIC_DATA,
    PARAMETRIC_3D,
    BLENDER_TO_VIDEO,
    SYNTHETIC_DATA,
    PRODUCT_360,
)

# FoxStudio worker `operations` (same namespace as image.generate.flux / video.generate.i2v).
FOXSTUDIO_OPERATION_BY_CAPABILITY: dict[str, str] = {
    BLENDER_SCENE: "blender.scene.build",
    BLENDER_PREVIEW: "blender.preview.render",
    BLENDER_RENDER: "blender.render.final",
    BLENDER_ANIMATION: "blender.animation.render",
    BLENDER_PRODUCT: "blender.product.studio",
    BLENDER_360: "blender.product.360",
    BLENDER_AR_ASSET: "blender.ar.export",
    BLENDER_SYNTHETIC_DATA: "blender.synthetic.dataset",
    PARAMETRIC_3D: "parametric.3d.build",
    BLENDER_TO_VIDEO: "blender.video.keyframes",
    SYNTHETIC_DATA: "blender.synthetic.dataset",
    PRODUCT_360: "blender.product.360",
}

# Fleet Console taskType values. Placement already forbids unified-memory for mesh_gen.
FLEET_TASK_TYPE_BY_CAPABILITY: dict[str, str] = {
    BLENDER_PREVIEW: "blender_preview",
    BLENDER_RENDER: "blender_render",
    BLENDER_ANIMATION: "blender_render",
    BLENDER_PRODUCT: "blender_render",
    BLENDER_360: "blender_render",
    BLENDER_TO_VIDEO: "video_generation",
    BLENDER_AR_ASSET: "mesh_gen",
    PARAMETRIC_3D: "mesh_gen",
    SYNTHETIC_DATA: "blender_render",
}

PREVIEW_CAPABILITIES = frozenset({BLENDER_PREVIEW, BLENDER_SCENE, PARAMETRIC_3D})
VIDEO_CAPABILITIES = frozenset({BLENDER_TO_VIDEO})
FINAL_RENDER_CAPABILITIES = frozenset(
    {
        BLENDER_RENDER,
        BLENDER_ANIMATION,
        BLENDER_PRODUCT,
        BLENDER_360,
        BLENDER_SYNTHETIC_DATA,
        SYNTHETIC_DATA,
        PRODUCT_360,
    }
)


def foxstudio_operations() -> list[str]:
    return sorted(set(FOXSTUDIO_OPERATION_BY_CAPABILITY.values()))


def capability_flags(detected: dict[str, object]) -> dict[str, object]:
    """JSON fragment stored on compute_targets.capabilities / Fleet heartbeat."""
    blender = bool(detected.get("blender"))
    gpu = bool(detected.get("gpuCount"))
    return {
        "blender": blender,
        "blenderVersion": detected.get("blenderVersion"),
        "cycles": blender,
        "eevee": blender,
        "cuda": bool(detected.get("cuda")),
        "optix": bool(detected.get("optix")),
        "gpu": detected.get("gpuName"),
        "gpuCount": int(detected.get("gpuCount") or 0),
        "vramGb": detected.get("vramGb"),
        "driver": detected.get("driver"),
        "acceptsCpuJobs": True,
        "operations": foxstudio_operations() if blender else [],
        "capabilities": list(BLENDER_CAPABILITIES) if blender else [],
        "kind": "gpu" if gpu else "cpu",
        "binary": detected.get("blenderBinary"),
        "realBlender": bool(detected.get("realBlender")),
        "realGPU": bool(detected.get("realGPU")),
        "realCycles": bool(detected.get("realCycles")),
        "realOptix": bool(detected.get("realOptix")),
        "blocked": detected.get("blocked") or [],
        "mock": bool(detected.get("mock")),
    }
