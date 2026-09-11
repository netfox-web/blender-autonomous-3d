"""Product Truth Render Pack + Scene/Camera recipes. REAL_LOGIC — not physical print."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fox3d.artwork import ArtworkError, decode_png_rgb
from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.pngutil import is_png, write_png

RECIPE_VERSION = 1
REQUIRED_AOV_ROLES = (
    "beauty",
    "depth",
    "normal",
    "product_mask",
    "artwork_mask",
    "alpha",
)
AOV_FILENAMES = {
    "beauty": "beauty.png",
    "depth": "depth.png",
    "normal": "normal.png",
    "product_mask": "product_mask.png",
    "artwork_mask": "artwork_mask.png",
    "alpha": "alpha.png",
}
OCCUPANCY_MIN = 0.02
OCCUPANCY_MAX = 0.98


def camera_recipe(
    *,
    camera_id: str = "HERO_FRONT",
    location: tuple[float, float, float] = (1.6, -2.4, 1.2),
    look_at: tuple[float, float, float] = (0.0, 0.0, 0.9),
    focal_length_mm: float = 85.0,
    sensor_width_mm: float = 36.0,
    width: int = 512,
    height: int = 512,
    safe_margin: float = 0.08,
) -> dict[str, Any]:
    rec = {
        "cameraId": str(camera_id),
        "target": list(look_at),
        "lookAt": list(look_at),
        "location": list(location),
        "rotation": None,
        "focalLengthMm": float(focal_length_mm),
        "sensorWidthMm": float(sensor_width_mm),
        "resolution": {"width": int(width), "height": int(height)},
        "aspectRatio": f"{int(width)}:{int(height)}",
        "framing": f"SAFE_MARGIN_{safe_margin}",
        "safeMargin": float(safe_margin),
        "recipeVersion": RECIPE_VERSION,
    }
    rec["cameraRecipeHash"] = stable_hash({k: rec[k] for k in rec if k != "cameraRecipeHash"})
    return rec


def scene_recipe(
    *,
    scene_id: str = "WHITE_STUDIO",
    lighting: str = "THREE_POINT",
    samples: int = 32,
    engine: str = "CYCLES",
) -> dict[str, Any]:
    rec = {
        "sceneId": str(scene_id),
        "backgroundPreset": "WHITE_CYC",
        "environmentPreset": "STUDIO",
        "lightingPreset": str(lighting),
        "studioRigId": "KEY_FILL_RIM_V1",
        "floorPolicy": "SHADOW_CATCHER",
        "shadowCatcher": True,
        "renderEngine": str(engine),
        "samples": int(samples),
        "colorManagement": "Filmic",
        "recipeVersion": RECIPE_VERSION,
    }
    rec["sceneRecipeHash"] = stable_hash({k: rec[k] for k in rec if k != "sceneRecipeHash"})
    return rec


def _png_meta(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    width, height, rgb = decode_png_rgb(data)
    return {
        "sha256": sha256_bytes(data),
        "size": len(data),
        "width": int(width),
        "height": int(height),
        "format": "PNG",
        "occupancy": _occupancy(rgb, width, height),
    }


def _occupancy(rgb: bytes, width: int, height: int) -> float:
    if width <= 0 or height <= 0:
        return 0.0
    lit = 0
    n = width * height
    for i in range(n):
        o = i * 3
        if rgb[o] > 12 or rgb[o + 1] > 12 or rgb[o + 2] > 12:
            lit += 1
    return lit / float(n)


def _strict_hash(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value


def artifact_record(
    *,
    role: str,
    path: Path,
    render_pack_id: str,
    lineage: dict[str, Any],
    dam_ref: str | None = None,
) -> dict[str, Any]:
    meta = _png_meta(path)
    rec = {
        "artifactId": new_id(),
        "damRef": dam_ref,
        "role": role,
        "semanticRole": role,
        "path": str(path),
        "format": "PNG",
        "renderPackId": render_pack_id,
        **meta,
        **{k: lineage.get(k) for k in (
            "engineeringHash",
            "artworkHash",
            "placementHash",
            "finalUvHash",
            "sceneRecipeHash",
            "cameraRecipeHash",
        )},
    }
    return rec


def validate_product_truth_render_pack(pack: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not isinstance(pack, dict):
        return ["pack_missing"]
    if pack.get("physicalPrintValidated") is True:
        failures.append("physical_print")
    for flag in ("globalProductionReady", "fullAutonomousFactoryReady", "liveFactoryExecutionReady"):
        if pack.get(flag) not in {None, False}:
            failures.append(flag)
    if pack.get("usedMock") is True and pack.get("realArtworkPreviewReady") is True:
        failures.append("mock_claimed_real_preview")
    if pack.get("usedMock") is True and pack.get("productTruthRenderPackReady") is True:
        failures.append("mock_claimed_real_pack")
    lineage_keys = (
        "engineeringHash",
        "artworkHash",
        "placementHash",
        "finalUvHash",
        "sceneRecipeHash",
        "cameraRecipeHash",
        "renderPackId",
    )
    for key in lineage_keys:
        if not _strict_hash(pack.get(key)):
            failures.append(f"missing_{key}")
    aovs = pack.get("aovs") if isinstance(pack.get("aovs"), dict) else {}
    dims: tuple[int, int] | None = None
    for role in REQUIRED_AOV_ROLES:
        row = aovs.get(role) if isinstance(aovs.get(role), dict) else None
        if not row:
            failures.append(f"missing_aov_{role}")
            continue
        if row.get("semanticRole") != role:
            failures.append(f"aov_role_{role}")
        if row.get("renderPackId") != pack.get("renderPackId"):
            failures.append(f"aov_pack_{role}")
        for key in ("engineeringHash", "artworkHash", "placementHash", "finalUvHash", "sceneRecipeHash", "cameraRecipeHash"):
            if row.get(key) != pack.get(key):
                failures.append(f"aov_lineage_{role}_{key}")
        try:
            width = int(row.get("width") or 0)
            height = int(row.get("height") or 0)
            size = int(row.get("size") or 0)
        except (TypeError, ValueError):
            failures.append(f"aov_meta_{role}")
            continue
        if width <= 0 or height <= 0 or size <= 0 or not row.get("sha256"):
            failures.append(f"aov_meta_{role}")
            continue
        if dims is None:
            dims = (width, height)
        elif dims != (width, height):
            failures.append("aov_dimension_mismatch")
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or not is_png(path):
            failures.append(f"aov_missing_file_{role}")
            continue
        live = path.read_bytes()
        if sha256_bytes(live) != str(row.get("sha256")) or len(live) != size:
            failures.append(f"aov_hash_{role}")
            continue
        try:
            lw, lh, rgb = decode_png_rgb(live)
        except ArtworkError:
            failures.append(f"aov_decode_{role}")
            continue
        if (lw, lh) != (width, height):
            failures.append(f"aov_pixels_{role}")
        if role in {"product_mask", "artwork_mask", "alpha"}:
            occ = _occupancy(rgb, lw, lh)
            if occ < OCCUPANCY_MIN or occ > OCCUPANCY_MAX:
                failures.append(f"aov_occupancy_{role}")
        if role == "product_mask" and not pack.get("objectManifest"):
            failures.append("object_manifest_missing")
    manifest = pack.get("objectManifest") if isinstance(pack.get("objectManifest"), dict) else {}
    comps = manifest.get("components") if isinstance(manifest.get("components"), list) else []
    if not comps or any(not isinstance(c, dict) or not c.get("componentId") for c in comps):
        failures.append("object_manifest_identity")
    cam = pack.get("cameraRecipe") if isinstance(pack.get("cameraRecipe"), dict) else {}
    scene = pack.get("sceneRecipe") if isinstance(pack.get("sceneRecipe"), dict) else {}
    if cam:
        expect = camera_recipe(
            camera_id=str(cam.get("cameraId") or "HERO_FRONT"),
            location=tuple(cam.get("location") or (1.6, -2.4, 1.2)),
            look_at=tuple(cam.get("lookAt") or cam.get("target") or (0.0, 0.0, 0.9)),
            focal_length_mm=float(cam.get("focalLengthMm") or 85.0),
            sensor_width_mm=float(cam.get("sensorWidthMm") or 36.0),
            width=int((cam.get("resolution") or {}).get("width") or 512),
            height=int((cam.get("resolution") or {}).get("height") or 512),
            safe_margin=float(cam.get("safeMargin") or 0.08),
        )
        if expect.get("cameraRecipeHash") != cam.get("cameraRecipeHash"):
            failures.append("camera_recipe_hash")
    if scene:
        expect_s = scene_recipe(
            scene_id=str(scene.get("sceneId") or "WHITE_STUDIO"),
            lighting=str(scene.get("lightingPreset") or "THREE_POINT"),
            samples=int(scene.get("samples") or 32),
            engine=str(scene.get("renderEngine") or "CYCLES"),
        )
        if expect_s.get("sceneRecipeHash") != scene.get("sceneRecipeHash"):
            failures.append("scene_recipe_hash")
    if pack.get("usedMock") is not True:
        if pack.get("realBlender") is not True or pack.get("usedMock") is True:
            if pack.get("realArtworkPreviewReady") is True:
                failures.append("preview_without_real_blender")
    return failures


def write_occupancy_png(
    path: Path,
    *,
    width: int,
    height: int,
    kind: str,
    seed: str = "truth",
) -> None:
    rgb = bytearray(width * height * 3)
    try:
        pr = int(seed[0:2], 16) if len(seed) >= 2 else 80
        pg = int(seed[2:4], 16) if len(seed) >= 4 else 90
        pb = int(seed[4:6], 16) if len(seed) >= 6 else 100
    except ValueError:
        pr, pg, pb = 80, 90, 100

    def product(x: int, y: int) -> bool:
        return width * 0.25 <= x <= width * 0.75 and height * 0.2 <= y <= height * 0.85

    def artwork(x: int, y: int) -> bool:
        return width * 0.35 <= x <= width * 0.65 and height * 0.35 <= y <= height * 0.65

    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 3
            if kind == "beauty":
                rgb[i : i + 3] = bytes((pr, pg, pb) if product(x, y) else (240, 240, 245))
            elif kind == "depth":
                v = 40 if product(x, y) else 200
                rgb[i : i + 3] = bytes((v, v, v))
            elif kind == "normal":
                rgb[i : i + 3] = bytes((128, 128, 255) if product(x, y) else (20, 20, 20))
            elif kind == "product_mask":
                rgb[i : i + 3] = bytes((255, 255, 255) if product(x, y) else (0, 0, 0))
            elif kind == "artwork_mask":
                rgb[i : i + 3] = bytes((255, 255, 255) if artwork(x, y) else (0, 0, 0))
            elif kind == "alpha":
                rgb[i : i + 3] = bytes((255, 255, 255) if product(x, y) else (0, 0, 0))
            else:
                rgb[i : i + 3] = bytes((pr, pg, pb))
    write_png(path, width, height, bytes(rgb))


class ProductTruthFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform

    def build_pack(
        self,
        *,
        tenant_id: str,
        placement: dict[str, Any],
        engineering: dict[str, Any],
        outputs: dict[str, Any],
        camera: dict[str, Any],
        scene: dict[str, Any],
        used_mock: bool,
        job: dict[str, Any] | None = None,
        object_names: list[str] | None = None,
        evidence_code_commit: str | None = None,
    ) -> dict[str, Any]:
        render_pack_id = new_id()
        lineage = {
            "engineeringHash": placement.get("engineeringHash") or engineering.get("engineeringHash"),
            "artworkHash": placement.get("artworkHash"),
            "placementHash": placement.get("placementHash"),
            "finalUvHash": placement.get("finalUvHash"),
            "sceneRecipeHash": scene.get("sceneRecipeHash"),
            "cameraRecipeHash": camera.get("cameraRecipeHash"),
            "renderPackId": render_pack_id,
        }
        aovs: dict[str, Any] = {}
        for role, filename in AOV_FILENAMES.items():
            raw_path = outputs.get(filename) or outputs.get(role)
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if not path.is_file():
                continue
            data = path.read_bytes()
            dam = self.platform.dam.put(
                tenant_id=tenant_id,
                kind="product_truth_aov",
                name=filename,
                data=data,
                metadata={"role": role, "renderPackId": render_pack_id},
            )
            aovs[role] = artifact_record(
                role=role,
                path=path,
                render_pack_id=render_pack_id,
                lineage=lineage,
                dam_ref=dam.asset_id,
            )
        components = []
        for name in object_names or []:
            components.append({"componentId": name, "objectName": name, "face": "FRONT"})
        if placement.get("componentId"):
            if not any(c.get("componentId") == placement.get("componentId") for c in components):
                components.append(
                    {
                        "componentId": placement.get("componentId"),
                        "objectName": placement.get("objectName"),
                        "face": placement.get("face") or "FRONT",
                    }
                )
        mock = bool(used_mock)
        real_blender = bool(job and job.get("realBlender") and not mock)
        pack = {
            "tenantId": tenant_id,
            "productId": placement.get("productId") or engineering.get("productId"),
            "candidateId": placement.get("candidateId") or engineering.get("candidateId"),
            "version": placement.get("version") or engineering.get("revision") or 1,
            "engineeringHash": lineage["engineeringHash"],
            "artworkId": placement.get("artworkId"),
            "artworkHash": lineage["artworkHash"],
            "artworkSha256": placement.get("artworkSha256"),
            "placementId": placement.get("placementId"),
            "placementHash": lineage["placementHash"],
            "finalUvHash": lineage["finalUvHash"],
            "sceneRecipeHash": lineage["sceneRecipeHash"],
            "cameraRecipeHash": lineage["cameraRecipeHash"],
            "renderPackId": render_pack_id,
            "sceneRecipe": scene,
            "cameraRecipe": camera,
            "aovs": aovs,
            "objectManifest": {"components": components},
            "blenderJobId": (job or {}).get("jobId"),
            "blenderVersion": (job or {}).get("blenderVersion"),
            "worker": (job or {}).get("worker"),
            "gpu": (job or {}).get("gpu") or (job or {}).get("device"),
            "evidenceCodeCommit": evidence_code_commit,
            "generatedAt": utcnow().isoformat(),
            "usedMock": mock,
            "realBlender": real_blender,
            "realOptix": bool(job and job.get("realOptix") and not mock),
            "truthLabel": "MOCK" if mock else ("REAL" if real_blender else "PARTIAL"),
            "realArtworkPreviewReady": False,
            "productTruthRenderPackReady": False,
            "productTruthAovPackReady": False,
            "physicalPrintValidated": False,
            "liveFactoryExecutionReady": False,
            "globalProductionReady": False,
            "fullAutonomousFactoryReady": False,
        }
        failures = validate_product_truth_render_pack({**pack, "realArtworkPreviewReady": False, "productTruthRenderPackReady": False})
        structure_ok = not [f for f in failures if f not in {"mock_claimed_real_preview", "mock_claimed_real_pack", "preview_without_real_blender"}]
        pack["productTruthAovPackReady"] = bool(structure_ok and len(aovs) == len(REQUIRED_AOV_ROLES))
        pack["realArtworkPreviewReady"] = bool(real_blender and pack["productTruthAovPackReady"] and pack.get("blenderJobId") and aovs.get("beauty"))
        pack["productTruthRenderPackReady"] = bool(pack["realArtworkPreviewReady"] and not mock)
        pack["acceptanceFailures"] = validate_product_truth_render_pack(pack)
        pack["ok"] = not pack["acceptanceFailures"]
        return pack


def render_product_truth(
    plat: Any,
    *,
    tenant_id: str,
    placement: dict[str, Any],
    engineering: dict[str, Any],
    width: int = 64,
    height: int = 64,
    evidence_code_commit: str | None = None,
) -> dict[str, Any]:
    camera = camera_recipe(width=width, height=height)
    mock = bool(getattr(plat, "mock_blender", True))
    scene = scene_recipe(samples=8 if mock else 32)
    factory = plat.artwork
    ident = factory.applied_identity(placement)
    payload = factory.blender_job_payload(
        tenant_id=tenant_id,
        engineering=engineering,
        placement_ids=[placement["placementId"]],
    )
    place_row = {
        **placement,
        "objectName": ident.get("objectName"),
        "componentId": ident.get("componentId") or placement.get("componentId"),
        "face": ident.get("face") or "FRONT",
        "finalUvHash": ident.get("finalUvHash") or placement.get("finalUvHash"),
        "artworkSha256": (payload.get("artworkPlacements") or [{}])[0].get("artworkSha256"),
    }
    if mock:
        job_dir = Path(plat.root) / "work" / new_id()
        job_dir.mkdir(parents=True, exist_ok=True)
        seed = str(placement.get("placementHash") or "truth")
        raw_outputs: dict[str, Any] = {}
        for role, filename in AOV_FILENAMES.items():
            dest = job_dir / filename
            write_occupancy_png(dest, width=width, height=height, kind=role, seed=seed)
            raw_outputs[filename] = str(dest)
        done = {
            "jobId": new_id(),
            "status": "succeeded",
            "usedMock": True,
            "realBlender": False,
            "realOptix": False,
            "blenderVersion": "mock-4.2",
            "worker": "fox3d-worker-local",
            "device": "CPU",
        }
        objects = [place_row.get("objectName") or place_row.get("componentId") or "DOOR_1"]
        return plat.product_truth.build_pack(
            tenant_id=tenant_id,
            placement=place_row,
            engineering=engineering,
            outputs=raw_outputs,
            camera=camera,
            scene=scene,
            used_mock=True,
            job=done,
            object_names=[n for n in objects if n],
            evidence_code_commit=evidence_code_commit,
        )
    if hasattr(plat, "register_detected_workers"):
        plat.register_detected_workers()
    payload.update(
        {
            "tenantId": tenant_id,
            "jobType": "BLENDER_RENDER",
            "mode": "ARTWORK_PREVIEW",
            "productTruthAovs": True,
            "aovs": True,
            "camera": {"location": camera["location"], "lookAt": camera["lookAt"], "focalLengthMm": camera["focalLengthMm"]},
            "lighting": {"preset": scene["lightingPreset"]},
            "render": {
                "width": width,
                "height": height,
                "engine": "CYCLES",
                "device": "OPTIX",
                "samples": scene["samples"],
            },
            "cameraRecipeHash": camera["cameraRecipeHash"],
            "sceneRecipeHash": scene["sceneRecipeHash"],
        }
    )
    job = plat.submit_job(payload)
    done = plat.execute_job(job)
    outputs = (done.get("output") if isinstance(done.get("output"), dict) else None) or {}
    files = outputs.get("files") if isinstance(outputs.get("files"), dict) else {}
    raw_outputs = {}
    for key in ("beauty.png", "depth.png", "normal.png", "product_mask.png", "artwork_mask.png", "alpha.png", "seg.png", "mask.png"):
        val = outputs.get(key) or files.get(key) or (done.get("outputs") or {}).get(key)
        if val:
            raw_outputs[key] = val
    if "product_mask.png" not in raw_outputs and raw_outputs.get("seg.png"):
        raw_outputs["product_mask.png"] = raw_outputs["seg.png"]
    if "alpha.png" not in raw_outputs and raw_outputs.get("mask.png"):
        raw_outputs["alpha.png"] = raw_outputs["mask.png"]
    used_mock = bool(done.get("usedMock"))
    objects = list(done.get("objects") or outputs.get("objects") or [])
    return plat.product_truth.build_pack(
        tenant_id=tenant_id,
        placement=place_row,
        engineering=engineering,
        outputs=raw_outputs,
        camera=camera,
        scene=scene,
        used_mock=used_mock,
        job=done,
        object_names=objects,
        evidence_code_commit=evidence_code_commit,
    )


def run_phase_841_scenario(plat: Any, *, tenant_id: str = "pt-a", evidence_code_commit: str | None = None) -> dict[str, Any]:
    from fox3d.generative_gateway import qa_product_consistency
    from fox3d.parametric import CabinetEngine
    from fox3d.pngutil import write_png

    engine = CabinetEngine()
    cab, _ = engine.create("STORAGE_CABINET", tenant_id=tenant_id, width=2400, height=1800, doorCount=4)
    doors = [s for s in plat.artwork.register_surfaces(cab, tenant_id=tenant_id) if "DOOR" in s["componentId"].upper()]
    png = Path(plat.root) / "truth-art.png"
    write_png(png, 48, 32, bytes([40, 80, 120]) * (48 * 32))
    art = plat.artwork.register_artwork(tenant_id=tenant_id, data=png.read_bytes(), name="truth-art.png", source="GENERATED")
    place = plat.artwork.place(
        tenant_id=tenant_id,
        surface_id=doors[0]["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    pack = render_product_truth(
        plat,
        tenant_id=tenant_id,
        placement=place,
        engineering=cab.model_dump(mode="json"),
        width=64,
        height=64,
        evidence_code_commit=evidence_code_commit,
    )
    gen = plat.generative.submit(
        {"mode": "IMAGE", "renderPackId": pack.get("renderPackId"), "productLocked": True, "requiredControls": ["depth", "normal", "product_mask"]},
        pack=pack,
    )
    qa = qa_product_consistency(
        pack=pack,
        generated={
            "inputRenderPackId": pack.get("renderPackId"),
            "masks": {
                "productOccupancy": ((pack.get("aovs") or {}).get("product_mask") or {}).get("occupancy"),
                "artworkOccupancy": ((pack.get("aovs") or {}).get("artwork_mask") or {}).get("occupancy"),
            },
        },
    )
    mock = bool(getattr(plat, "mock_blender", True) or pack.get("usedMock"))
    return {
        "ok": bool(pack.get("ok") and gen.get("ok")),
        "pack": pack,
        "generative": gen,
        "qa": qa,
        "realArtworkPreviewReady": bool(pack.get("realArtworkPreviewReady")) and not mock,
        "productTruthRenderPackReady": bool(pack.get("productTruthRenderPackReady")) and not mock,
        "productTruthAovPackReady": bool(pack.get("productTruthAovPackReady")),
        "generativeRenderGatewayLogicReady": bool(gen.get("generativeRenderGatewayLogicReady")),
        "liveH3MaxProviderReady": False,
        "liveLtx25ProviderReady": False,
        "productConsistencyQaLogicReady": qa.get("decision") in {
            "APPROVED_FOR_ASSET_REVIEW",
            "REJECT_PRODUCT_DRIFT",
            "REJECT_ARTWORK_DRIFT",
            "REJECT_MISSING_EVIDENCE",
        },
        "liveVisionJudgeReady": False,
        "physicalPrintValidated": False,
        "liveFactoryExecutionReady": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "usedMock": mock,
        "renderPackId": pack.get("renderPackId"),
        "acceptanceFailures": list(pack.get("acceptanceFailures") or []) + list(gen.get("acceptanceFailures") or []),
    }
