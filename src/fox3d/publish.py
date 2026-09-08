"""Commerce / Web3D / publication packages. Reuses TwinStore + DAM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow


class CatalogRelease:
    def __init__(self) -> None:
        self.releases: dict[str, dict[str, Any]] = {}
        self.skus: dict[str, dict[str, Any]] = {}

    def add_sku(self, rec: dict[str, Any], *, family: str) -> dict[str, Any]:
        sku = {
            "skuId": rec.get("productId") or rec.get("fixtureId") or rec.get("packageId") or new_id(),
            "family": family,
            "engineeringHash": rec.get("engineeringHash") or (rec.get("engineering") or {}).get("engineeringHash"),
            "version": rec.get("spec", {}).get("revision") if isinstance(rec.get("spec"), dict) else 1,
            "status": "active",
            "immutable": True,
        }
        self.skus[sku["skuId"]] = sku
        return sku

    def release(self, *, name: str, sku_ids: list[str]) -> dict[str, Any]:
        rec = {
            "releaseId": new_id(),
            "name": name,
            "skuIds": list(sku_ids),
            "createdAt": utcnow().isoformat(),
            "status": "active",
            "supersededBy": None,
        }
        rec["releaseHash"] = stable_hash({k: rec[k] for k in rec if k != "releaseHash"})
        self.releases[rec["releaseId"]] = rec
        return rec

    def supersede(self, release_id: str, *, successor: str) -> dict[str, Any]:
        rec = self.releases[release_id]
        rec["status"] = "superseded"
        rec["supersededBy"] = successor
        rec["stale"] = True
        return rec


def glb_publication(twin: dict[str, Any], path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "label": "BLOCKED", "error": "missing_glb"}
    data = path.read_bytes()
    dims = twin.get("dimensions") or {}
    return {
        "ok": True,
        "path": str(path),
        "hash": sha256_bytes(data),
        "size": len(data),
        "dimensions": dims,
        "dimsValid": all(float(dims.get(k) or 0) >= 0 for k in ("width", "height", "depth") if k in dims or True),
        "label": "REAL",
        "store": "DAM",
    }


def web360_package(job: dict[str, Any]) -> dict[str, Any]:
    out = job.get("output") or {}
    files = out.get("files") or {}
    frames = files.get("frames") or out.get("frames") or []
    return {
        "frameCount": len(frames) if isinstance(frames, list) else int(job.get("frameCount") or 0),
        "thumb": files.get("beauty.png") or job.get("outputAsset"),
        "jobId": job.get("jobId"),
        "workerId": job.get("worker"),
        "recipe": job.get("recipeId") or job.get("scene"),
        "lineage": {"jobId": job.get("jobId"), "worker": job.get("worker"), "blenderVersion": job.get("blenderVersion")},
        "targetFrames": 36,
    }


def web3d_manifest(*, twin: dict[str, Any], glb: dict[str, Any] | None, variants: list[str] | None = None) -> dict[str, Any]:
    dims = twin.get("dimensions") or {}
    return {
        "format": "viewer-neutral-v1",
        "glbRef": (glb or {}).get("path") or twin.get("glb"),
        "glbHash": (glb or {}).get("hash"),
        "cameraBounds": {"near": 0.1, "far": 20, "units": "m"},
        "units": "mm",
        "dimensions": dims,
        "materials": twin.get("materials") or [],
        "variantIds": variants or [],
        "arRuntime": "PARTIAL",
        "note": "manifest only is not a live AR session",
    }


def ar_export_boundary(exporter_result: dict[str, Any] | None) -> dict[str, Any]:
    usdz = str((exporter_result or {}).get("usdz") or "")
    if usdz and Path(usdz).is_file():
        return {"label": "REAL", "artifact": usdz}
    return {
        "label": "PARTIAL",
        "adapter": True,
        "usdzProduced": False,
        "note": "USDZ/AR artifact not produced — reserved only. No fake filename.",
        "usdzReserved": True,
    }


ECOM_RECIPES = ("WHITE_STUDIO", "DETAIL", "SCALE_REFERENCE", "DIMENSION_OVERLAY", "MATERIAL_CLOSEUP")


def ecommerce_recipe_pack(twin_id: str) -> dict[str, Any]:
    return {
        "twinId": twin_id,
        "recipes": [{"recipe": r, "jobRequired": True} for r in ECOM_RECIPES],
        "renders": [],
        "label": "MANIFEST",
        "note": "REAL only after actual render jobs",
    }


def assembly_asset_pack(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "partLabels": rec.get("partLabels"),
        "steps": (rec.get("instructionsV2") or rec.get("instructions") or {}),
        "exploded": rec.get("preview"),
        "hash": stable_hash(
            {
                "labels": (rec.get("partLabels") or {}).get("manifestHash"),
                "steps": (rec.get("instructionsV2") or {}).get("manifestHash"),
            }
        ),
    }


def packaging_artwork_export(pkg: dict[str, Any]) -> dict[str, Any]:
    eng = pkg.get("engineering") or {}
    die = eng.get("dieline") or {}
    return {
        "family": pkg.get("family"),
        "engineeringHash": eng.get("engineeringHash"),
        "svgBytes": eng.get("dielineSvgBytes"),
        "dxfFriendly": die.get("dxfFriendly") or {"units": "mm", "liveMachineControl": False},
        "artworkZones": (eng.get("bleed") or {}).get("zones"),
        "lineage": pkg.get("lineage"),
    }


def publication_package(rec: dict[str, Any], *, family: str, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    artifacts = artifacts or []
    pack = {
        "publicationId": new_id(),
        "family": family,
        "productVersion": rec.get("spec", {}).get("revision") if isinstance(rec.get("spec"), dict) else 1,
        "spec": rec.get("spec") or rec.get("engineering") or rec.get("dimensions"),
        "bomSummary": {"bomHash": (rec.get("bom") or {}).get("bomHash") or rec.get("bomHash"), "lines": len((rec.get("bom") or {}).get("lines") or rec.get("parts") or [])},
        "packingSummary": rec.get("packing") or rec.get("shipping"),
        "previewAssets": [a for a in artifacts],
        "assembly": rec.get("instructionsV2") or rec.get("instructions"),
        "warnings": (rec.get("safety") or {}).get("boundary") or rec.get("misassembly"),
        "engineeringHash": rec.get("engineeringHash") or (rec.get("engineering") or {}).get("engineeringHash"),
        "liveMachineControl": False,
    }
    pack["publicationHash"] = stable_hash({k: pack[k] for k in pack if k not in {"publicationId", "publicationHash"}})
    return pack
