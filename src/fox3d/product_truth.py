"""Product Truth Render Pack + Scene/Camera recipes. REAL_LOGIC — not physical print."""

from __future__ import annotations

import math
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
REQUIRED_VIEWS = ("DOOR_DETAIL", "ASSEMBLED_FRONT")
WORKER_IDENTITY_KEYS = (
    "engineeringHash",
    "artworkId",
    "artworkHash",
    "artworkSha256",
    "placementId",
    "placementHash",
    "finalUvHash",
    "surfaceHash",
    "componentId",
    "objectName",
    "face",
    "cameraRecipeHash",
    "sceneRecipeHash",
)


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


def _exact_bool(value: Any) -> bool | None:
    if type(value) is bool:
        return value
    return None


def _is_strict_float(val: Any) -> bool:
    if type(val) is bool:
        return False
    if not isinstance(val, (int, float)):
        return False
    try:
        f = float(val)
        return math.isfinite(f)
    except (TypeError, ValueError, OverflowError):
        return False


def _is_strict_int(val: Any) -> bool:
    if type(val) is bool:
        return False
    if not isinstance(val, int):
        return False
    return True


def _is_strict_vec3(val: Any) -> bool:
    if not isinstance(val, (list, tuple)) or len(val) != 3:
        return False
    return all(_is_strict_float(x) for x in val)


def derive_canonical_expected_identity(
    plat: Any,
    *,
    tenant_id: str,
    placement: dict[str, Any] | str,
    engineering: dict[str, Any] | None = None,
    camera: dict[str, Any] | None = None,
    scene: dict[str, Any] | None = None,
    view_recipes: dict[str, Any] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    factory = getattr(plat, "artwork", None)

    if strict:
        if not factory or not hasattr(factory, "placements"):
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_artwork_factory"}
        p_id = placement.get("placementId") if isinstance(placement, dict) else str(placement or "")
        if not p_id or p_id not in factory.placements:
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_placement"}
        canonical_place = factory.placements[p_id]
        s_id = canonical_place.get("surfaceId")
        if not s_id or not hasattr(factory, "surfaces") or s_id not in factory.surfaces:
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_surface"}
        try:
            ident = factory.applied_identity(canonical_place)
        except Exception:
            return {"canonicalAuthorityValid": False, "canonicalFailure": "canonical_identity_derivation_failed"}

        art_id = canonical_place.get("artworkId")
        if not art_id or not hasattr(factory, "artworks") or art_id not in factory.artworks:
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_artwork"}
        art_rec = factory.artworks[art_id]
        art_path = Path(str(art_rec.get("path") or ""))
        if not art_path.is_file():
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_artwork_file"}
        file_bytes = art_path.read_bytes()
        file_sha = sha256_bytes(file_bytes)
        if art_rec.get("sha256") and art_rec.get("sha256") != file_sha:
            return {"canonicalAuthorityValid": False, "canonicalFailure": "canonical_artwork_tampered"}
        art_sha = file_sha
        art_hash = art_rec.get("artworkHash")
        if not art_hash:
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_artwork_hash"}

        if not engineering:
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_engineering"}
        eng_hash = None
        if isinstance(engineering, dict):
            eng_hash = engineering.get("engineeringHash")
            if not eng_hash and "kind" in engineering:
                try:
                    from fox3d.parametric import CabinetSpec
                    eng_hash = CabinetSpec.model_validate(engineering).engineering_hash()
                except Exception:
                    pass
        elif engineering is not None:
            eng_hash = getattr(engineering, "engineering_hash", lambda: None)()
        if not eng_hash:
            eng_hash = canonical_place.get("engineeringHash") or ident.get("engineeringHash")
        if not eng_hash:
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_engineering_hash"}
        if canonical_place.get("engineeringHash") and eng_hash != canonical_place.get("engineeringHash"):
            return {"canonicalAuthorityValid": False, "canonicalFailure": "canonical_engineering_mismatch"}

        if not camera or not isinstance(camera, dict) or not camera.get("cameraRecipeHash"):
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_camera_recipe"}
        cam_hash = camera.get("cameraRecipeHash")

        if not scene or not isinstance(scene, dict) or not scene.get("sceneRecipeHash"):
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_scene_recipe"}
        scene_hash = scene.get("sceneRecipeHash")

        if not view_recipes or not isinstance(view_recipes, dict):
            return {"canonicalAuthorityValid": False, "canonicalFailure": "missing_canonical_view_recipes"}
        view_hashes: dict[str, str] = {}
        for req_view in REQUIRED_VIEWS:
            vrec = view_recipes.get(req_view)
            if not isinstance(vrec, dict) or not vrec.get("cameraRecipeHash"):
                return {"canonicalAuthorityValid": False, "canonicalFailure": f"missing_canonical_view_recipe_{req_view}"}
            view_hashes[req_view] = str(vrec["cameraRecipeHash"])

        return {
            "canonicalAuthorityValid": True,
            "engineeringHash": eng_hash,
            "artworkId": art_id,
            "artworkHash": art_hash,
            "artworkSha256": art_sha,
            "placementId": p_id,
            "placementHash": canonical_place.get("placementHash") or ident.get("placementHash"),
            "finalUvHash": canonical_place.get("finalUvHash") or ident.get("finalUvHash"),
            "surfaceHash": canonical_place.get("surfaceHash") or ident.get("surfaceHash"),
            "componentId": canonical_place.get("componentId") or ident.get("componentId"),
            "objectName": canonical_place.get("objectName") or ident.get("objectName"),
            "face": canonical_place.get("face") or ident.get("face") or "FRONT",
            "sceneRecipeHash": scene_hash,
            "cameraRecipeHash": cam_hash,
            "viewRecipes": view_hashes,
        }

    ident = {}
    if factory and hasattr(factory, "applied_identity"):
        try:
            ident = factory.applied_identity(placement if isinstance(placement, dict) else {"placementId": str(placement)})
        except Exception:
            ident = {}

    p_id = placement.get("placementId") if isinstance(placement, dict) else str(placement or "")
    canonical_place = factory.placements.get(p_id) if (factory and hasattr(factory, "placements") and p_id) else None
    source_placement = canonical_place or (placement if isinstance(placement, dict) else {"placementId": p_id})

    art_id = source_placement.get("artworkId")
    art_sha = None
    art_hash = None
    if art_id and factory and hasattr(factory, "require_artwork"):
        try:
            art_rec = factory.require_artwork(art_id, tenant_id=tenant_id)
            art_sha = art_rec.get("sha256")
            art_hash = art_rec.get("artworkHash")
        except Exception:
            art_rec = factory.artworks.get(art_id) if hasattr(factory, "artworks") else None
            if art_rec:
                art_sha = art_rec.get("sha256")
                art_hash = art_rec.get("artworkHash")
    if not art_sha:
        art_sha = source_placement.get("artworkSha256")
    if not art_hash:
        art_hash = ident.get("artworkHash") or source_placement.get("artworkHash")

    eng_hash = None
    if isinstance(engineering, dict):
        eng_hash = engineering.get("engineeringHash")
        if not eng_hash and "kind" in engineering:
            try:
                from fox3d.parametric import CabinetSpec
                eng_hash = CabinetSpec.model_validate(engineering).engineering_hash()
            except Exception:
                pass
    elif engineering is not None:
        eng_hash = getattr(engineering, "engineering_hash", lambda: None)()
    if not eng_hash:
        eng_hash = ident.get("engineeringHash") or source_placement.get("engineeringHash")
    cam_hash = (camera or {}).get("cameraRecipeHash")
    scene_hash = (scene or {}).get("sceneRecipeHash")

    view_hashes = {}
    for vname, vrec in (view_recipes or {}).items():
        if isinstance(vrec, dict) and vrec.get("cameraRecipeHash"):
            view_hashes[vname] = str(vrec["cameraRecipeHash"])

    return {
        "engineeringHash": eng_hash,
        "artworkId": art_id,
        "artworkHash": art_hash,
        "artworkSha256": art_sha,
        "placementId": source_placement.get("placementId"),
        "placementHash": ident.get("placementHash") or source_placement.get("placementHash"),
        "finalUvHash": ident.get("finalUvHash") or source_placement.get("finalUvHash"),
        "surfaceHash": ident.get("surfaceHash") or source_placement.get("surfaceHash"),
        "componentId": ident.get("componentId") or source_placement.get("componentId"),
        "objectName": ident.get("objectName") or source_placement.get("objectName"),
        "face": ident.get("face") or source_placement.get("face") or "FRONT",
        "sceneRecipeHash": scene_hash,
        "cameraRecipeHash": cam_hash,
        "viewRecipes": view_hashes,
    }


def _artwork_subset_of_product(art_rgb: bytes, prod_rgb: bytes, width: int, height: int) -> bool:
    art_lit = prod_lit = overlap = 0
    n = width * height
    for i in range(n):
        o = i * 3
        art = art_rgb[o] > 12 or art_rgb[o + 1] > 12 or art_rgb[o + 2] > 12
        prod = prod_rgb[o] > 12 or prod_rgb[o + 1] > 12 or prod_rgb[o + 2] > 12
        if art:
            art_lit += 1
            if prod:
                overlap += 1
        if prod:
            prod_lit += 1
    if art_lit <= 0 or prod_lit <= 0 or art_lit >= prod_lit:
        return False
    return overlap / float(art_lit) >= 0.9


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


def validate_product_truth_render_pack(
    pack: dict[str, Any],
    expected_identity: dict[str, Any] | None = None,
    *,
    plat: Any = None,
) -> list[str]:
    failures: list[str] = []
    if not isinstance(pack, dict):
        return ["pack_missing"]
    authoritative_expected = dict(expected_identity or {})
    serialized_expected = pack.get("expectedIdentity") if isinstance(pack.get("expectedIdentity"), dict) else {}

    if authoritative_expected and authoritative_expected.get("canonicalAuthorityValid") is False:
        failures.append(f"canonical_authority_{authoritative_expected.get('canonicalFailure', 'invalid')}")

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
        if role == "artwork_mask":
            prod = aovs.get("product_mask") if isinstance(aovs.get("product_mask"), dict) else {}
            if prod.get("sha256") and row.get("sha256") == prod.get("sha256"):
                failures.append("artwork_mask_alias")
            prod_path = Path(str(prod.get("path") or ""))
            if prod_path.is_file():
                try:
                    pw, ph, prgb = decode_png_rgb(prod_path.read_bytes())
                    if (pw, ph) == (lw, lh) and not _artwork_subset_of_product(rgb, prgb, lw, lh):
                        failures.append("artwork_mask_not_subset")
                except ArtworkError:
                    failures.append("artwork_mask_subset_decode")
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
    REQUIRED_VIEW_FILENAMES = {
        "DOOR_DETAIL": "door_detail.png",
        "ASSEMBLED_FRONT": "assembled_front.png",
    }
    views = pack.get("views") if isinstance(pack.get("views"), dict) else {}
    worker_views_dict = pack.get("workerViews") if isinstance(pack.get("workerViews"), dict) else {}
    for name in REQUIRED_VIEWS:
        row = views.get(name) if isinstance(views.get(name), dict) else None
        if not row:
            failures.append(f"missing_view_{name}")
            continue
        if not _strict_hash(row.get("sha256")) or not row.get("blenderJobId") or not _strict_hash(row.get("cameraRecipeHash")):
            failures.append(f"view_meta_{name}")
            continue
        vpath = Path(str(row.get("path") or ""))
        if not vpath.is_file() or not is_png(vpath):
            failures.append(f"view_missing_file_{name}")
            continue
        live = vpath.read_bytes()
        live_sha = sha256_bytes(live)
        live_size = len(live)
        if live_sha != str(row.get("sha256")):
            failures.append(f"view_hash_{name}")
            continue
        if live_size != int(row.get("size") or 0):
            failures.append(f"view_size_{name}")
            continue

        top_worker_view = worker_views_dict.get(name) if isinstance(worker_views_dict, dict) else None
        nested_worker_view = row.get("workerView") if isinstance(row.get("workerView"), dict) else None
        if top_worker_view and nested_worker_view and top_worker_view != nested_worker_view:
            failures.append(f"view_worker_view_conflict_{name}")
        worker_view = nested_worker_view or top_worker_view
        if not isinstance(worker_view, dict) or not worker_view:
            failures.append(f"missing_worker_view_{name}")
            continue

        expected_fn = REQUIRED_VIEW_FILENAMES.get(name)
        if row.get("viewId") != name:
            failures.append(f"view_id_mismatch_{name}")
        if worker_view.get("viewId") != name:
            failures.append(f"view_worker_id_mismatch_{name}")
        if Path(str(row.get("path") or "")).name != expected_fn:
            failures.append(f"view_filename_mismatch_{name}")
        if worker_view.get("filename") and worker_view.get("filename") != expected_fn:
            failures.append(f"view_worker_filename_mismatch_{name}")
        if worker_view.get("path") and Path(str(worker_view.get("path"))).name != expected_fn:
            failures.append(f"view_worker_path_filename_mismatch_{name}")

        if worker_view.get("sha256") and str(worker_view.get("sha256")) != live_sha:
            failures.append(f"view_worker_hash_{name}")
        if worker_view.get("size") and int(worker_view.get("size")) != live_size:
            failures.append(f"view_worker_size_{name}")

        norm_row = str(Path(str(row.get("path") or "")).resolve())
        if worker_view.get("path"):
            norm_worker = str(Path(str(worker_view.get("path") or "")).resolve())
            if norm_row != norm_worker:
                failures.append(f"view_path_mismatch_{name}")

        meta = _png_meta(vpath)
        if (row.get("width"), row.get("height")) != (meta["width"], meta["height"]):
            failures.append(f"view_dimension_mismatch_{name}")
        vw = worker_view.get("width")
        vh = worker_view.get("height")
        if _is_strict_int(vw) and int(vw) != meta["width"]:
            failures.append(f"view_worker_dimension_mismatch_{name}")
        if _is_strict_int(vh) and int(vh) != meta["height"]:
            failures.append(f"view_worker_dimension_mismatch_{name}")

        expected_job_id = pack.get("blenderJobId") or (pack.get("job") or {}).get("jobId")
        if not row.get("blenderJobId"):
            failures.append(f"view_missing_jobId_{name}")
        elif expected_job_id and row.get("blenderJobId") != expected_job_id:
            failures.append(f"view_job_id_mismatch_{name}")
        if not worker_view.get("blenderJobId"):
            failures.append(f"view_worker_missing_jobId_{name}")
        elif expected_job_id and worker_view.get("blenderJobId") != expected_job_id:
            failures.append(f"view_worker_job_id_mismatch_{name}")
        if row.get("blenderJobId") and worker_view.get("blenderJobId") and row.get("blenderJobId") != worker_view.get("blenderJobId"):
            failures.append(f"view_job_id_conflict_{name}")

        dam_ref = row.get("damRef") or row.get("artifactId")
        if not dam_ref:
            failures.append(f"view_missing_dam_ref_{name}")
        if row.get("damRef") and row.get("artifactId") and row.get("damRef") != row.get("artifactId"):
            failures.append(f"view_dam_ref_mismatch_{name}")
        if plat and hasattr(plat, "dam"):
            dam_obj = getattr(plat.dam, "_index", {}).get(dam_ref)
            if not dam_obj:
                failures.append(f"view_dam_asset_missing_{name}")
            else:
                if dam_obj.tenant_id != pack.get("tenantId"):
                    failures.append(f"view_dam_tenant_mismatch_{name}")
                if dam_obj.sha256 != live_sha:
                    failures.append(f"view_dam_sha_mismatch_{name}")
                if (dam_obj.metadata or {}).get("view") != name:
                    failures.append(f"view_dam_role_mismatch_{name}")
                if (dam_obj.metadata or {}).get("renderPackId") and dam_obj.metadata.get("renderPackId") != pack.get("renderPackId"):
                    failures.append(f"view_dam_pack_mismatch_{name}")
                dam_path = Path(dam_obj.path)
                if not dam_path.is_file() or sha256_bytes(dam_path.read_bytes()) != live_sha:
                    failures.append(f"view_dam_file_corrupt_{name}")

        loc = worker_view.get("location")
        look = worker_view.get("lookAt") if worker_view.get("lookAt") is not None else worker_view.get("target")
        focal = worker_view.get("focalLengthMm")
        sensor = worker_view.get("sensorWidthMm")
        margin = worker_view.get("safeMargin")
        vsz = worker_view.get("size")
        v_sha = worker_view.get("sha256")

        camera_valid = True
        if not _is_strict_vec3(loc):
            failures.append(f"view_worker_location_invalid_{name}")
            camera_valid = False
        if not _is_strict_vec3(look):
            failures.append(f"view_worker_lookAt_invalid_{name}")
            camera_valid = False
        if not _is_strict_float(focal) or float(focal) <= 0:
            failures.append(f"view_worker_focalLength_invalid_{name}")
            camera_valid = False
        if not _is_strict_float(sensor) or float(sensor) <= 0:
            failures.append(f"view_worker_sensorWidth_invalid_{name}")
            camera_valid = False
        if not _is_strict_float(margin) or float(margin) < 0:
            failures.append(f"view_worker_safeMargin_invalid_{name}")
            camera_valid = False
        if not _is_strict_int(vw) or int(vw) <= 0:
            failures.append(f"view_worker_width_invalid_{name}")
            camera_valid = False
        if not _is_strict_int(vh) or int(vh) <= 0:
            failures.append(f"view_worker_height_invalid_{name}")
            camera_valid = False
        if not _is_strict_int(vsz) or int(vsz) <= 0:
            failures.append(f"view_worker_size_invalid_{name}")
            camera_valid = False
        if not _strict_hash(v_sha):
            failures.append(f"view_worker_sha_invalid_{name}")
            camera_valid = False

        if camera_valid:
            observed_camera = camera_recipe(
                camera_id=str(worker_view.get("viewId") or name),
                location=tuple(float(x) for x in loc),
                look_at=tuple(float(x) for x in look),
                focal_length_mm=float(focal),
                sensor_width_mm=float(sensor),
                width=int(vw),
                height=int(vh),
                safe_margin=float(margin),
            )
            observed_cam_hash = observed_camera["cameraRecipeHash"]
            if worker_view.get("cameraRecipeHash") != observed_cam_hash:
                failures.append(f"view_worker_camera_hash_mismatch_{name}")
            if row.get("cameraRecipeHash") != observed_cam_hash:
                failures.append(f"view_camera_mismatch_{name}")
            if worker_view.get("cameraRecipeHash") != row.get("cameraRecipeHash"):
                failures.append(f"view_camera_mismatch_{name}")

        if row.get("cameraRecipe") and isinstance(row["cameraRecipe"], dict):
            req_c = row["cameraRecipe"]
            recomputed = camera_recipe(
                camera_id=str(req_c.get("cameraId") or name),
                location=tuple(req_c.get("location") or (1.6, -2.4, 1.2)),
                look_at=tuple(req_c.get("lookAt") or req_c.get("target") or (0.0, 0.0, 0.9)),
                focal_length_mm=float(req_c.get("focalLengthMm") or 85.0),
                sensor_width_mm=float(req_c.get("sensorWidthMm") or 36.0),
                width=int((req_c.get("resolution") or {}).get("width") or row.get("width") or 512),
                height=int((req_c.get("resolution") or {}).get("height") or row.get("height") or 512),
                safe_margin=float(req_c.get("safeMargin") or 0.08),
            )
            if recomputed.get("cameraRecipeHash") != row.get("cameraRecipeHash"):
                failures.append(f"view_camera_recipe_hash_{name}")
            if camera_valid and observed_cam_hash != recomputed.get("cameraRecipeHash"):
                failures.append(f"view_camera_recipe_mismatch_{name}")

        if authoritative_expected.get("viewRecipes") and isinstance(authoritative_expected["viewRecipes"], dict):
            exp_view_hash = authoritative_expected["viewRecipes"].get(name)
            if exp_view_hash:
                if row.get("cameraRecipeHash") != exp_view_hash:
                    failures.append(f"view_canonical_camera_mismatch_{name}")
                if camera_valid and observed_cam_hash != exp_view_hash:
                    failures.append(f"worker_view_canonical_camera_mismatch_{name}")

        if pack.get("realArtworkPreviewReady") is True or pack.get("productTruthRenderPackReady") is True or pack.get("usedMock") is False:
            if _exact_bool(worker_view.get("usedMock")) is not False:
                failures.append(f"real_worker_view_usedMock_{name}")
            if _exact_bool(worker_view.get("realBlender")) is not True:
                failures.append(f"real_worker_view_realBlender_{name}")
            if _exact_bool(worker_view.get("realOptix")) is not True:
                failures.append(f"real_worker_view_realOptix_{name}")

    worker = pack.get("workerEvidence") if isinstance(pack.get("workerEvidence"), dict) else {}
    for key in WORKER_IDENTITY_KEYS:
        if key not in worker:
            failures.append(f"worker_missing_{key}")
        elif key != "face" and not worker.get(key) and key not in {"artworkId"}:
            failures.append(f"worker_missing_{key}")
    if worker.get("face") != "FRONT":
        failures.append("worker_face")

    for key in (
        "engineeringHash",
        "artworkHash",
        "artworkSha256",
        "placementHash",
        "finalUvHash",
        "surfaceHash",
        "componentId",
        "objectName",
    ):
        if worker.get(key) and pack.get(key) and worker.get(key) != pack.get(key):
            failures.append(f"worker_mismatch_{key}")
        if authoritative_expected and authoritative_expected.get(key) is not None:
            if worker.get(key) and worker.get(key) != authoritative_expected.get(key):
                failures.append(f"worker_mismatch_{key}")
            if pack.get(key) and pack.get(key) != authoritative_expected.get(key):
                failures.append(f"pack_mismatch_{key}")
            if serialized_expected.get(key) and serialized_expected.get(key) != authoritative_expected.get(key):
                failures.append(f"serialized_expected_mismatch_{key}")
        elif serialized_expected and serialized_expected.get(key) is not None:
            if worker.get(key) and worker.get(key) != serialized_expected.get(key):
                failures.append(f"worker_mismatch_{key}")
            if pack.get(key) and pack.get(key) != serialized_expected.get(key):
                failures.append(f"pack_mismatch_{key}")

    if worker.get("cameraRecipeHash") and pack.get("cameraRecipeHash") and worker.get("cameraRecipeHash") != pack.get("cameraRecipeHash"):
        failures.append("worker_mismatch_cameraRecipeHash")
    if authoritative_expected and authoritative_expected.get("cameraRecipeHash"):
        if worker.get("cameraRecipeHash") and worker.get("cameraRecipeHash") != authoritative_expected.get("cameraRecipeHash"):
            failures.append("worker_mismatch_cameraRecipeHash")
        if pack.get("cameraRecipeHash") and pack.get("cameraRecipeHash") != authoritative_expected.get("cameraRecipeHash"):
            failures.append("pack_mismatch_cameraRecipeHash")
        if serialized_expected.get("cameraRecipeHash") and serialized_expected.get("cameraRecipeHash") != authoritative_expected.get("cameraRecipeHash"):
            failures.append("serialized_expected_mismatch_cameraRecipeHash")
    elif serialized_expected and serialized_expected.get("cameraRecipeHash"):
        if worker.get("cameraRecipeHash") and worker.get("cameraRecipeHash") != serialized_expected.get("cameraRecipeHash"):
            failures.append("worker_mismatch_cameraRecipeHash")
        if pack.get("cameraRecipeHash") and pack.get("cameraRecipeHash") != serialized_expected.get("cameraRecipeHash"):
            failures.append("pack_mismatch_cameraRecipeHash")

    if worker.get("sceneRecipeHash") and pack.get("sceneRecipeHash") and worker.get("sceneRecipeHash") != pack.get("sceneRecipeHash"):
        failures.append("worker_mismatch_sceneRecipeHash")
    if authoritative_expected and authoritative_expected.get("sceneRecipeHash"):
        if worker.get("sceneRecipeHash") and worker.get("sceneRecipeHash") != authoritative_expected.get("sceneRecipeHash"):
            failures.append("worker_mismatch_sceneRecipeHash")
        if pack.get("sceneRecipeHash") and pack.get("sceneRecipeHash") != authoritative_expected.get("sceneRecipeHash"):
            failures.append("pack_mismatch_sceneRecipeHash")
        if serialized_expected.get("sceneRecipeHash") and serialized_expected.get("sceneRecipeHash") != authoritative_expected.get("sceneRecipeHash"):
            failures.append("serialized_expected_mismatch_sceneRecipeHash")
    elif serialized_expected and serialized_expected.get("sceneRecipeHash"):
        if worker.get("sceneRecipeHash") and worker.get("sceneRecipeHash") != serialized_expected.get("sceneRecipeHash"):
            failures.append("worker_mismatch_sceneRecipeHash")
        if pack.get("sceneRecipeHash") and pack.get("sceneRecipeHash") != serialized_expected.get("sceneRecipeHash"):
            failures.append("pack_mismatch_sceneRecipeHash")

    aov_beauty = aovs.get("beauty") if isinstance(aovs.get("beauty"), dict) else {}
    if worker and aov_beauty.get("placementHash") and worker.get("placementHash") and aov_beauty.get("placementHash") != worker.get("placementHash"):
        failures.append("aov_worker_inconsistent")
    for flag in ("usedMock", "realBlender", "realOptix"):
        if _exact_bool(pack.get(flag)) is None:
            failures.append(f"bool_schema_{flag}")
    if pack.get("realArtworkPreviewReady") is True or pack.get("productTruthRenderPackReady") is True:
        if _exact_bool(pack.get("usedMock")) is not False:
            failures.append("real_usedMock")
        if _exact_bool(pack.get("realBlender")) is not True:
            failures.append("real_realBlender")
        if _exact_bool(pack.get("realOptix")) is not True:
            failures.append("real_realOptix")
        if not pack.get("blenderJobId") or not pack.get("blenderVersion") or not pack.get("worker") or not pack.get("gpu"):
            failures.append("real_job_identity")
        if "artwork_mask_alias" in failures:
            failures.append("real_artwork_mask")
        if any(f.startswith("missing_view_") or f.startswith("view_worker_") or f.startswith("real_worker_view_") for f in failures):
            failures.append("real_views")
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
        view_recipes: dict[str, Any] | None = None,
        expected_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        render_pack_id = new_id()
        worker = dict((job or {}).get("workerIdentity") or {})

        if expected_identity:
            authoritative_expected = dict(expected_identity)
        else:
            authoritative_expected = derive_canonical_expected_identity(
                self.platform,
                tenant_id=tenant_id,
                placement=placement,
                engineering=engineering,
                camera=camera,
                scene=scene,
                view_recipes=view_recipes,
            )

        canonical_eng_hash = authoritative_expected.get("engineeringHash") or engineering.get("engineeringHash") or placement.get("engineeringHash")
        canonical_art_hash = authoritative_expected.get("artworkHash") or placement.get("artworkHash")
        canonical_art_id = authoritative_expected.get("artworkId") or placement.get("artworkId")
        canonical_art_sha = authoritative_expected.get("artworkSha256") or placement.get("artworkSha256")
        canonical_placement_id = authoritative_expected.get("placementId") or placement.get("placementId")
        canonical_placement_hash = authoritative_expected.get("placementHash") or placement.get("placementHash")
        canonical_final_uv_hash = authoritative_expected.get("finalUvHash") or placement.get("finalUvHash")
        canonical_surface_hash = authoritative_expected.get("surfaceHash") or placement.get("surfaceHash")
        canonical_component_id = authoritative_expected.get("componentId") or placement.get("componentId")
        canonical_object_name = authoritative_expected.get("objectName") or placement.get("objectName")
        canonical_face = authoritative_expected.get("face") or placement.get("face") or "FRONT"
        canonical_scene_hash = authoritative_expected.get("sceneRecipeHash") or scene.get("sceneRecipeHash")
        canonical_camera_hash = authoritative_expected.get("cameraRecipeHash") or camera.get("cameraRecipeHash")

        lineage = {
            "engineeringHash": canonical_eng_hash,
            "artworkHash": canonical_art_hash,
            "placementHash": canonical_placement_hash,
            "finalUvHash": canonical_final_uv_hash,
            "sceneRecipeHash": canonical_scene_hash,
            "cameraRecipeHash": canonical_camera_hash,
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
        views: dict[str, Any] = {}
        worker_views = dict((job or {}).get("workerViews") or {})
        for name, filename in (("DOOR_DETAIL", "door_detail.png"), ("ASSEMBLED_FRONT", "assembled_front.png")):
            raw_path = outputs.get(filename)
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if not path.is_file():
                continue
            data = path.read_bytes()
            dam = self.platform.dam.put(
                tenant_id=tenant_id,
                kind="product_truth_view",
                name=filename,
                data=data,
                metadata={"view": name, "renderPackId": render_pack_id},
            )
            meta = _png_meta(path)
            worker_view = worker_views.get(name) or {}
            req_cam = (view_recipes or {}).get(name) or {}
            canonical_view_cam_hash = req_cam.get("cameraRecipeHash") or (outputs.get(f"{name}_cameraRecipeHash") if not worker_view else None) or worker_view.get("cameraRecipeHash")
            views[name] = {
                "viewId": name,
                "artifactId": dam.asset_id,
                "damRef": dam.asset_id,
                "path": str(path),
                "blenderJobId": worker_view.get("blenderJobId") or (job or {}).get("jobId") or worker.get("blenderJobId"),
                "cameraRecipeHash": canonical_view_cam_hash,
                "cameraRecipe": req_cam,
                "workerView": worker_view,
                **meta,
            }
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
        used_m = used_mock if type(used_mock) is bool else used_mock
        real_b = (job or {}).get("realBlender") if job and "realBlender" in job else False
        real_o = (job or {}).get("realOptix") if job and "realOptix" in job else False
        pack = {
            "tenantId": tenant_id,
            "productId": placement.get("productId") or engineering.get("productId"),
            "candidateId": placement.get("candidateId") or engineering.get("candidateId"),
            "version": placement.get("version") or engineering.get("revision") or 1,
            "engineeringHash": canonical_eng_hash,
            "artworkId": canonical_art_id,
            "artworkHash": canonical_art_hash,
            "artworkSha256": canonical_art_sha,
            "placementId": canonical_placement_id,
            "placementHash": canonical_placement_hash,
            "finalUvHash": canonical_final_uv_hash,
            "surfaceHash": canonical_surface_hash,
            "componentId": canonical_component_id,
            "objectName": canonical_object_name,
            "face": canonical_face,
            "sceneRecipeHash": canonical_scene_hash,
            "cameraRecipeHash": canonical_camera_hash,
            "renderPackId": render_pack_id,
            "sceneRecipe": scene,
            "cameraRecipe": camera,
            "aovs": aovs,
            "views": views,
            "workerViews": worker_views,
            "expectedIdentity": authoritative_expected,
            "workerEvidence": worker,
            "objectManifest": {"components": components},
            "blenderJobId": (job or {}).get("jobId") or worker.get("blenderJobId"),
            "blenderVersion": (job or {}).get("blenderVersion"),
            "worker": (job or {}).get("worker"),
            "gpu": (job or {}).get("gpu") or (job or {}).get("device"),
            "evidenceCodeCommit": evidence_code_commit,
            "generatedAt": utcnow().isoformat(),
            "usedMock": used_m,
            "realBlender": real_b,
            "realOptix": real_o,
            "truthLabel": "MOCK" if used_m is True else ("REAL" if real_b is True else "PARTIAL"),
            "realArtworkPreviewReady": False,
            "productTruthRenderPackReady": False,
            "productTruthAovPackReady": False,
            "physicalPrintValidated": False,
            "liveFactoryExecutionReady": False,
            "globalProductionReady": False,
            "fullAutonomousFactoryReady": False,
        }
        trial = {**pack, "realArtworkPreviewReady": False, "productTruthRenderPackReady": False}
        failures = validate_product_truth_render_pack(trial, expected_identity=authoritative_expected, plat=self.platform)
        blocked_real = {
            "mock_claimed_real_preview",
            "mock_claimed_real_pack",
            "preview_without_real_blender",
            "real_usedMock",
            "real_realBlender",
            "real_realOptix",
            "real_job_identity",
            "real_artwork_mask",
            "real_views",
            "real_worker_view_usedMock_DOOR_DETAIL",
            "real_worker_view_usedMock_ASSEMBLED_FRONT",
            "real_worker_view_realBlender_DOOR_DETAIL",
            "real_worker_view_realBlender_ASSEMBLED_FRONT",
            "real_worker_view_realOptix_DOOR_DETAIL",
            "real_worker_view_realOptix_ASSEMBLED_FRONT",
        }
        structure_ok = not [f for f in failures if f not in blocked_real]
        pack["productTruthAovPackReady"] = bool(structure_ok and len(aovs) == len(REQUIRED_AOV_ROLES) and len(views) == 2)
        identity_ok = not any(
            f.startswith("worker_")
            or f.startswith("pack_mismatch_")
            or f.startswith("serialized_expected_mismatch_")
            or f.startswith("view_worker_")
            or f.startswith("view_camera_")
            or f == "artwork_mask_alias"
            or f == "aov_worker_inconsistent"
            for f in failures
        )
        pack["realArtworkPreviewReady"] = bool(
            _exact_bool(pack["usedMock"]) is False
            and _exact_bool(pack["realBlender"]) is True
            and _exact_bool(pack["realOptix"]) is True
            and pack["productTruthAovPackReady"]
            and identity_ok
            and pack.get("blenderJobId")
            and pack.get("blenderVersion")
            and pack.get("worker")
            and pack.get("gpu")
        )
        pack["productTruthRenderPackReady"] = bool(pack["realArtworkPreviewReady"])
        pack["acceptanceFailures"] = validate_product_truth_render_pack(pack, expected_identity=authoritative_expected, plat=self.platform)
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
    expected_identity: dict[str, Any] | None = None,
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
    door_cam = camera_recipe(
        camera_id="DOOR_DETAIL",
        location=(0.35, -1.5, 0.95),
        look_at=(0.3, 0.0, 0.9),
        width=width,
        height=height,
    )
    assembled_cam = camera_recipe(
        camera_id="ASSEMBLED_FRONT",
        location=(2.6, -4.0, 1.5),
        look_at=(1.2, 0.0, 0.9),
        width=width,
        height=height,
    )
    view_recipes = {"DOOR_DETAIL": door_cam, "ASSEMBLED_FRONT": assembled_cam}
    canonical_expected = expected_identity or derive_canonical_expected_identity(
        plat,
        tenant_id=tenant_id,
        placement=place_row,
        engineering=engineering,
        camera=camera,
        scene=scene,
        view_recipes=view_recipes,
    )
    if mock:
        job_dir = Path(plat.root) / "work" / new_id()
        job_dir.mkdir(parents=True, exist_ok=True)
        seed = str(placement.get("placementHash") or "truth")
        raw_outputs: dict[str, Any] = {}
        for role, filename in AOV_FILENAMES.items():
            dest = job_dir / filename
            write_occupancy_png(dest, width=width, height=height, kind=role, seed=seed)
            raw_outputs[filename] = str(dest)
        write_occupancy_png(job_dir / "door_detail.png", width=width, height=height, kind="beauty", seed=seed + "d")
        write_occupancy_png(job_dir / "assembled_front.png", width=width, height=height, kind="beauty", seed=seed + "a")
        raw_outputs["door_detail.png"] = str(job_dir / "door_detail.png")
        raw_outputs["assembled_front.png"] = str(job_dir / "assembled_front.png")
        job_id = new_id()
        door_bytes = Path(str(job_dir / "door_detail.png")).read_bytes()
        front_bytes = Path(str(job_dir / "assembled_front.png")).read_bytes()
        worker_views = {
            "DOOR_DETAIL": {
                "viewId": "DOOR_DETAIL",
                "filename": "door_detail.png",
                "cameraRecipeHash": door_cam["cameraRecipeHash"],
                "location": list(door_cam["location"]),
                "lookAt": list(door_cam["lookAt"]),
                "target": list(door_cam["target"]),
                "focalLengthMm": door_cam["focalLengthMm"],
                "sensorWidthMm": door_cam["sensorWidthMm"],
                "safeMargin": door_cam["safeMargin"],
                "width": width,
                "height": height,
                "path": str(job_dir / "door_detail.png"),
                "sha256": sha256_bytes(door_bytes),
                "size": len(door_bytes),
                "blenderJobId": job_id,
                "usedMock": True,
                "realBlender": False,
                "realOptix": False,
            },
            "ASSEMBLED_FRONT": {
                "viewId": "ASSEMBLED_FRONT",
                "filename": "assembled_front.png",
                "cameraRecipeHash": assembled_cam["cameraRecipeHash"],
                "location": list(assembled_cam["location"]),
                "lookAt": list(assembled_cam["lookAt"]),
                "target": list(assembled_cam["target"]),
                "focalLengthMm": assembled_cam["focalLengthMm"],
                "sensorWidthMm": assembled_cam["sensorWidthMm"],
                "safeMargin": assembled_cam["safeMargin"],
                "width": width,
                "height": height,
                "path": str(job_dir / "assembled_front.png"),
                "sha256": sha256_bytes(front_bytes),
                "size": len(front_bytes),
                "blenderJobId": job_id,
                "usedMock": True,
                "realBlender": False,
                "realOptix": False,
            },
        }
        done = {
            "jobId": job_id,
            "status": "succeeded",
            "usedMock": True,
            "realBlender": False,
            "realOptix": False,
            "blenderVersion": "mock-4.2",
            "worker": "fox3d-worker-local",
            "device": "CPU",
            "gpu": "CPU",
            "workerViews": worker_views,
            "workerIdentity": {
                "engineeringHash": place_row.get("engineeringHash"),
                "artworkId": place_row.get("artworkId"),
                "artworkHash": place_row.get("artworkHash"),
                "artworkSha256": place_row.get("artworkSha256"),
                "placementId": place_row.get("placementId"),
                "placementHash": place_row.get("placementHash"),
                "finalUvHash": place_row.get("finalUvHash"),
                "surfaceHash": place_row.get("surfaceHash"),
                "componentId": place_row.get("componentId"),
                "objectName": place_row.get("objectName"),
                "face": place_row.get("face") or "FRONT",
                "cameraRecipeHash": camera.get("cameraRecipeHash"),
                "sceneRecipeHash": scene.get("sceneRecipeHash"),
                "blenderJobId": job_id,
                "usedMock": True,
                "realBlender": False,
                "realOptix": False,
            },
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
            view_recipes=view_recipes,
            expected_identity=canonical_expected,
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
            "productTruthViews": [
                {
                    "id": "ASSEMBLED_FRONT",
                    "filename": "assembled_front.png",
                    "location": assembled_cam["location"],
                    "lookAt": assembled_cam["lookAt"],
                    "focalLengthMm": assembled_cam["focalLengthMm"],
                },
                {
                    "id": "DOOR_DETAIL",
                    "filename": "door_detail.png",
                    "location": door_cam["location"],
                    "lookAt": door_cam["lookAt"],
                    "focalLengthMm": door_cam["focalLengthMm"],
                },
            ],
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
    raw_outputs: dict[str, Any] = {}

    def _resolve(val: Any) -> str | None:
        if not val:
            return None
        path = Path(str(val))
        if path.is_file():
            return str(path)
        try:
            obj = plat.dam.get_unchecked(str(val))
            if obj and Path(obj.path).is_file():
                return obj.path
        except Exception:
            return None
        return None

    for key in (
        "beauty.png",
        "depth.png",
        "normal.png",
        "product_mask.png",
        "artwork_mask.png",
        "alpha.png",
        "seg.png",
        "mask.png",
        "door_detail.png",
        "assembled_front.png",
    ):
        got = _resolve(outputs.get(key) or files.get(key) or (done.get("outputs") or {}).get(key))
        if got:
            raw_outputs[key] = got
    if "product_mask.png" not in raw_outputs and raw_outputs.get("seg.png"):
        raw_outputs["product_mask.png"] = raw_outputs["seg.png"]
    if "alpha.png" not in raw_outputs and raw_outputs.get("mask.png"):
        raw_outputs["alpha.png"] = raw_outputs["mask.png"]
    used_mock = done.get("usedMock") is True
    objects = list(done.get("objects") or outputs.get("objects") or [])
    complete = (
        all(AOV_FILENAMES[role] in raw_outputs for role in REQUIRED_AOV_ROLES)
        and "door_detail.png" in raw_outputs
        and "assembled_front.png" in raw_outputs
        and raw_outputs.get("artwork_mask.png")
        and raw_outputs.get("artwork_mask.png") != raw_outputs.get("product_mask.png")
    )
    if not complete or used_mock or done.get("realBlender") is not True:
        job_dir = Path(plat.root) / "work" / new_id()
        job_dir.mkdir(parents=True, exist_ok=True)
        seed = str(placement.get("placementHash") or "truth")
        fixture_outputs: dict[str, Any] = {}
        for role, filename in AOV_FILENAMES.items():
            dest = job_dir / filename
            write_occupancy_png(dest, width=width, height=height, kind=role, seed=seed)
            fixture_outputs[filename] = str(dest)
        write_occupancy_png(job_dir / "door_detail.png", width=width, height=height, kind="beauty", seed=seed + "d")
        write_occupancy_png(job_dir / "assembled_front.png", width=width, height=height, kind="beauty", seed=seed + "a")
        fixture_outputs["door_detail.png"] = str(job_dir / "door_detail.png")
        fixture_outputs["assembled_front.png"] = str(job_dir / "assembled_front.png")
        job_id = (done or {}).get("jobId") or new_id()
        f_door_bytes = Path(str(job_dir / "door_detail.png")).read_bytes()
        f_front_bytes = Path(str(job_dir / "assembled_front.png")).read_bytes()
        fixture_views = {
            "DOOR_DETAIL": {
                "viewId": "DOOR_DETAIL",
                "filename": "door_detail.png",
                "cameraRecipeHash": door_cam["cameraRecipeHash"],
                "location": list(door_cam["location"]),
                "lookAt": list(door_cam["lookAt"]),
                "target": list(door_cam["target"]),
                "focalLengthMm": door_cam["focalLengthMm"],
                "sensorWidthMm": door_cam["sensorWidthMm"],
                "safeMargin": door_cam["safeMargin"],
                "width": width,
                "height": height,
                "path": str(job_dir / "door_detail.png"),
                "sha256": sha256_bytes(f_door_bytes),
                "size": len(f_door_bytes),
                "blenderJobId": job_id,
                "usedMock": True,
                "realBlender": False,
                "realOptix": False,
            },
            "ASSEMBLED_FRONT": {
                "viewId": "ASSEMBLED_FRONT",
                "filename": "assembled_front.png",
                "cameraRecipeHash": assembled_cam["cameraRecipeHash"],
                "location": list(assembled_cam["location"]),
                "lookAt": list(assembled_cam["lookAt"]),
                "target": list(assembled_cam["target"]),
                "focalLengthMm": assembled_cam["focalLengthMm"],
                "sensorWidthMm": assembled_cam["sensorWidthMm"],
                "safeMargin": assembled_cam["safeMargin"],
                "width": width,
                "height": height,
                "path": str(job_dir / "assembled_front.png"),
                "sha256": sha256_bytes(f_front_bytes),
                "size": len(f_front_bytes),
                "blenderJobId": job_id,
                "usedMock": True,
                "realBlender": False,
                "realOptix": False,
            },
        }
        done = {
            **(done if isinstance(done, dict) else {}),
            "jobId": job_id,
            "status": "succeeded",
            "usedMock": True,
            "realBlender": False,
            "realOptix": False,
            "blenderVersion": (done or {}).get("blenderVersion") or "mock-4.2",
            "worker": "fox3d-worker-local",
            "device": (done or {}).get("device") or "CPU",
            "gpu": (done or {}).get("gpu") or "CPU",
            "workerViews": fixture_views,
            "workerIdentity": {
                "engineeringHash": place_row.get("engineeringHash"),
                "artworkId": place_row.get("artworkId"),
                "artworkHash": place_row.get("artworkHash"),
                "artworkSha256": place_row.get("artworkSha256"),
                "placementId": place_row.get("placementId"),
                "placementHash": place_row.get("placementHash"),
                "finalUvHash": place_row.get("finalUvHash"),
                "surfaceHash": place_row.get("surfaceHash"),
                "componentId": place_row.get("componentId"),
                "objectName": place_row.get("objectName"),
                "face": place_row.get("face") or "FRONT",
                "cameraRecipeHash": camera.get("cameraRecipeHash"),
                "sceneRecipeHash": scene.get("sceneRecipeHash"),
                "blenderJobId": job_id,
                "usedMock": True,
                "realBlender": False,
                "realOptix": False,
            },
        }
        return plat.product_truth.build_pack(
            tenant_id=tenant_id,
            placement=place_row,
            engineering=engineering,
            outputs=fixture_outputs,
            camera=camera,
            scene=scene,
            used_mock=True,
            job=done,
            object_names=objects or [place_row.get("objectName") or "DOOR_1"],
            evidence_code_commit=evidence_code_commit,
            view_recipes=view_recipes,
            expected_identity=canonical_expected,
        )
    # REAL mode: wire observed workerViews from done
    if "workerViews" not in done and isinstance(done.get("output"), dict) and "workerViews" in done["output"]:
        done["workerViews"] = done["output"]["workerViews"]
    return plat.product_truth.build_pack(
        tenant_id=tenant_id,
        placement=place_row,
        engineering=engineering,
        outputs=raw_outputs,
        camera=camera,
        scene=scene,
        used_mock=False,
        job=done,
        object_names=objects,
        evidence_code_commit=evidence_code_commit,
        view_recipes=view_recipes,
        expected_identity=canonical_expected,
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
    target_door = next((s for s in doors if s.get("componentId") in {"door_3", "DOOR_3"}), doors[0])
    place = plat.artwork.place(
        tenant_id=tenant_id,
        surface_id=target_door["surfaceId"],
        artwork_id=art["artworkId"],
        engineering_hash=cab.engineering_hash(),
        product_id=cab.productId,
    )
    mock_plat = bool(getattr(plat, "mock_blender", True))
    width = 64 if mock_plat else 128
    height = 64 if mock_plat else 128
    camera = camera_recipe(width=width, height=height)
    scene = scene_recipe(samples=8 if mock_plat else 32)
    view_recipes = {
        "DOOR_DETAIL": camera_recipe(
            camera_id="DOOR_DETAIL",
            location=(0.35, -1.5, 0.95),
            look_at=(0.3, 0.0, 0.9),
            width=width,
            height=height,
        ),
        "ASSEMBLED_FRONT": camera_recipe(
            camera_id="ASSEMBLED_FRONT",
            location=(2.6, -4.0, 1.5),
            look_at=(1.2, 0.0, 0.9),
            width=width,
            height=height,
        ),
    }
    frozen_authority = {
        "tenant_id": tenant_id,
        "placement": place,
        "placementId": place["placementId"],
        "surfaceId": target_door["surfaceId"],
        "artworkId": art["artworkId"],
        "engineering": cab.model_dump(mode="json"),
        "engineeringHash": cab.engineering_hash(),
        "camera": camera,
        "scene": scene,
        "view_recipes": view_recipes,
    }
    canonical_expected = derive_canonical_expected_identity(
        plat,
        tenant_id=tenant_id,
        placement=place,
        engineering=cab.model_dump(mode="json"),
        camera=camera,
        scene=scene,
        view_recipes=view_recipes,
        strict=True,
    )
    pack = render_product_truth(
        plat,
        tenant_id=tenant_id,
        placement=place,
        engineering=cab.model_dump(mode="json"),
        width=width,
        height=height,
        evidence_code_commit=evidence_code_commit,
        expected_identity=canonical_expected,
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
        "canonicalExpectedIdentity": pack.get("expectedIdentity"),
        "frozenAuthorityContext": frozen_authority,
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

