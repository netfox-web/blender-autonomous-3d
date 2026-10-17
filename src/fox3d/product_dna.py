"""Issue 18: read-only Product DNA export for the existing Golden Product.

Reuses EngineeringHash, ArtworkHash, BOM candidate and Final UV from the
Issue #4 / PR #7 Golden recipe. Does not render, does not call ERP, AI PRINT OS
or SpecPilot, and cannot set production readiness.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fox3d.artwork import crop_rgb, decode_png_rgb
from fox3d.golden_preview import HERO_CAMERA, LIVE_BLENDER_ORIGIN, PREVIEW_VIEWS, VIEW_FILES
from fox3d.golden_product import SKUS, GoldenRecipe, build_golden, fixture_pixels, materialize_package, package_plan
from fox3d.pngutil import encode_png
from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.recipe_3d import atomic_json, read_json

SCHEMA = "fox3d.product_dna.export.v1"
ENVELOPE_SCHEMA = "fox3d.product_dna.export-envelope.v1"
RECONCILE_SCHEMA = "fox3d.product_dna.reconcile.v1"
FAMILY_ID = "fox3d.family.three_tier_door_cabinet"
MOLD_ID = "fox3d.mold.three_tier_424x295x900.v1"
EXPORT_SKUS = SKUS[:3]
ARTWORK_VERSIONS = ("FIXTURE_MASTER_V1", "FIXTURE_SINGLE_V1")
CONSUMERS = ("FOXRECORDER", "IMAGEAI", "FOXSTUDIO")
ISSUE_4 = "https://github.com/netfox-web/blender-autonomous-3d/issues/4"
ISSUE_18 = "https://github.com/netfox-web/blender-autonomous-3d/issues/18"
SPECPILOT_58 = "https://github.com/netfox-web/AI-Project-Asset-Intelligence-Platform/issues/58"
SPECPILOT_59 = "https://github.com/netfox-web/AI-Project-Asset-Intelligence-Platform/issues/59"
PRINT_PROCESS = "PRINT_SURFACE_PREVIEW"
USAGE_LIMIT = "READ_ONLY_NON_PRODUCTION_PREVIEW"
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,118}$")
_HASH = r"^[a-f0-9]{64}$"
KNOWN_GAPS = (
    "ERP product family is UNBOUND; this service does not read or write ERP",
    "AI PRINT OS MasterProduct is UNBOUND; the local mold id is not an approved plate",
    "SpecPilot Product DNA id is UNBOUND; issue links are declarations only",
    "Historical artwork is BLOCKED; only non-IP calibration fixtures are exported",
    "Render media is ABSENT unless a LIVE_BLENDER_PROCESS generation is attached",
    "BOM is a candidate, not a cut list",
    "globalProductionReady, engineeringReady, manufacturingReady and physical print stay false",
)


class ProductDnaError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class TruthBadge(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    badge: Literal["PREVIEW_FIXTURE", "PREVIEW_REAL_BLENDER"]
    renderEvidenceClass: Literal["ABSENT", "MOCK_REGRESSION", "REAL_BLENDER"]
    renderUsedMock: bool
    realBlender: bool
    productionReady: Literal[False] = False
    engineeringReady: Literal[False] = False
    manufacturingReady: Literal[False] = False
    globalProductionReady: Literal[False] = False
    physicalPrintValidated: Literal[False] = False
    liveMachineControl: Literal[False] = False

    @model_validator(mode="after")
    def separate_evidence(self):
        if self.renderEvidenceClass == "REAL_BLENDER":
            ok = self.badge == "PREVIEW_REAL_BLENDER" and self.realBlender is True and self.renderUsedMock is False
        elif self.renderEvidenceClass == "MOCK_REGRESSION":
            ok = self.badge == "PREVIEW_FIXTURE" and self.realBlender is False and self.renderUsedMock is True
        else:
            ok = self.badge == "PREVIEW_FIXTURE" and self.realBlender is False and self.renderUsedMock is False
        if not ok:
            raise ValueError("truth badge does not match its evidence class")
        return self


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    system: Literal["FOX3D_GOLDEN", "ERP", "AI_PRINT_OS", "SPECPILOT_PRODUCT_DNA"]
    kind: Literal["ENGINEERING_TEMPLATE", "PRODUCT_FAMILY", "SKU", "MASTER_PRODUCT", "DIE_MOLD", "PRODUCT_DNA"]
    id: str | None
    binding: Literal["LOCAL_AUTHORITY", "LOCAL_SKU_CODE", "LOCAL_TEMPLATE_NOT_APPROVED_PLATE", "UNBOUND", "DECLARED_ISSUE_REF"]
    truth: Literal["REAL_LOGIC", "CONFIG", "DECLARED_REF_NOT_LIVE"]
    ref: str | None = None


class HashSet(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    engineeringHash: str = Field(pattern=_HASH)
    bomHash: str = Field(pattern=_HASH)
    artworkHash: str = Field(pattern=_HASH)
    finalUvHash: str = Field(pattern=_HASH)
    packageHash: str = Field(pattern=_HASH)
    bomScope: Literal["CANDIDATE_ONLY_NOT_A_CUT_LIST"]


class PlacementView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    componentId: Literal["door_1", "door_2", "door_3"]
    widthMm: float
    heightMm: float
    originTopMm: list[float]
    cropMm: dict[str, float]
    uvRect: dict[str, float]
    safeMm: float
    bleedMm: float
    placementHash: str = Field(pattern=_HASH)
    finalUvHash: str = Field(pattern=_HASH)
    surfaceHash: str = Field(pattern=_HASH)


class AngleMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Literal["HERO_45", "FRONT_CLOSED", "DOOR_DETAIL", "FRONT_OPEN"]
    filename: str | None
    status: Literal["DECLARED_PREVIEW_CAMERA", "BLOCKED"]
    units: Literal["m"] | None = None
    location: list[float] | None = None
    lookAt: list[float] | None = None
    focalLengthMm: float | None = None
    reason: str | None = None


class MediaRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["GLB", "PNG_HERO", "PNG_FRONT", "PNG_DETAIL", "ARTWORK_SOURCE", "PRODUCTION_TRIM"]
    filename: str
    sourceHash: str | None = None
    bytesPresent: bool
    sizeBytes: int | None = None
    evidenceClass: Literal["FIXTURE", "MOCK_REGRESSION", "REAL_BLENDER", "ABSENT"]
    entityAuthenticity: Literal["SYNTHETIC_FIXTURE", "REAL_BLENDER_PREVIEW", "ABSENT"]
    rightsStatus: Literal["NO_IP_FIXTURE", "RIGHTS_BLOCKED"]
    usageLimit: Literal["READ_ONLY_NON_PRODUCTION_PREVIEW"] = USAGE_LIMIT
    componentId: str | None = None


class EvidenceSeparation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    artworkPixels: Literal["FIXTURE"] = "FIXTURE"
    historicalArtwork: Literal["BLOCKED"] = "BLOCKED"
    geometryHashAndUv: Literal["REAL_LOGIC"] = "REAL_LOGIC"
    renderMedia: Literal["ABSENT", "MOCK_REGRESSION", "REAL_BLENDER"]
    automatedTestsAndCi: Literal["MOCK_REGRESSION"] = "MOCK_REGRESSION"
    externalSystems: Literal["DECLARED_REF_NOT_LIVE"] = "DECLARED_REF_NOT_LIVE"
    production: Literal["BLOCKED"] = "BLOCKED"


class RightsScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    authorizedCommercialArt: Literal[False] = False
    scope: Literal["FIXTURE_NON_IP"] = "FIXTURE_NON_IP"
    ipStatus: Literal["NO_IP_FIXTURE"] = "NO_IP_FIXTURE"
    usageLimits: list[str]


class Twin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal["fox3d.product_dna.export.v1"] = SCHEMA
    twinId: str
    familyId: Literal["fox3d.family.three_tier_door_cabinet"] = FAMILY_ID
    moldId: Literal["fox3d.mold.three_tier_424x295x900.v1"] = MOLD_ID
    engineeringTemplateId: Literal["THREE_TIER_DOOR_CABINET_424x295x900_V1"]
    engineeringVersion: Literal["THREE_TIER_DOOR_CABINET_424x295x900_V1"]
    tenantId: str
    sku: Literal["KU002101", "KT015101", "CN003701", "PN010201"]
    artworkVersion: Literal["FIXTURE_MASTER_V1", "FIXTURE_SINGLE_V1"]
    hashes: HashSet
    geometryMm: dict[str, Any]
    placements: list[PlacementView]
    angles: list[AngleMeta]
    media: list[MediaRef]
    rights: RightsScope
    sourceRefs: list[SourceRef]
    truth: TruthBadge
    evidenceSeparation: EvidenceSeparation


class FamilyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal["fox3d.product_dna.export.v1"] = SCHEMA
    familyId: Literal["fox3d.family.three_tier_door_cabinet"] = FAMILY_ID
    moldId: Literal["fox3d.mold.three_tier_424x295x900.v1"] = MOLD_ID
    engineeringTemplateId: Literal["THREE_TIER_DOOR_CABINET_424x295x900_V1"]
    engineeringVersion: Literal["THREE_TIER_DOOR_CABINET_424x295x900_V1"]
    tenantId: str
    inputHash: str = Field(pattern=_HASH)
    engineeringHash: str = Field(pattern=_HASH)
    bomHash: str = Field(pattern=_HASH)
    skuCount: Literal[3]
    twins: list[Twin]
    sourceRefs: list[SourceRef]
    knownGaps: list[str]
    truth: TruthBadge
    evidenceSeparation: EvidenceSeparation
    globalProductionReady: Literal[False] = False
    liveSystemRead: Literal[False] = False
    contentHash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def one_mold(self):
        if len(self.twins) != 3 or len({t.sku for t in self.twins}) != 3:
            raise ValueError("one mold requires three distinct artwork SKUs")
        if any(t.hashes.engineeringHash != self.engineeringHash or t.moldId != self.moldId for t in self.twins):
            raise ValueError("artwork SKUs must share one engineering template")
        expect = stable_hash(self.model_dump(mode="json", exclude={"contentHash"}))
        if self.contentHash != expect:
            raise ValueError("manifest content hash mismatch")
        return self


def check_tenant(tenant: str | None) -> str:
    if not tenant or not _TENANT.fullmatch(tenant) or tenant == "system":
        raise ProductDnaError("請提供有效工作區", 400)
    return tenant


def check_version(version: str) -> str:
    if version not in ARTWORK_VERSIONS:
        raise ProductDnaError("沒有圖稿授權時只能匯出非 IP 校驗圖", 422)
    return version


def check_skus(skus: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    chosen = tuple(skus) if skus is not None else EXPORT_SKUS
    if len(chosen) != 3 or len(set(chosen)) != 3 or any(sku not in SKUS for sku in chosen):
        raise ProductDnaError("一個模具必須對應三個不同的 Golden SKU", 422)
    return chosen


def _bom_hash(golden: dict) -> str:
    return stable_hash({"scope": golden["manufacturing"]["scope"], "bomCandidate": golden["manufacturing"]["bomCandidate"]})


def _final_uv_hash(package: dict) -> str:
    return stable_hash([row["finalUvHash"] for row in package["placements"]])


def _rights() -> dict:
    return {
        "authorizedCommercialArt": False,
        "scope": "FIXTURE_NON_IP",
        "ipStatus": "NO_IP_FIXTURE",
        "usageLimits": ["READ_ONLY", "NOT_PRODUCTION_PRINT", "NOT_HISTORICAL_ARTWORK", "NOT_MANUFACTURING_RELEASE"],
    }


def _preview_truth() -> dict:
    return {
        "badge": "PREVIEW_FIXTURE",
        "renderEvidenceClass": "ABSENT",
        "renderUsedMock": False,
        "realBlender": False,
        "productionReady": False,
        "engineeringReady": False,
        "manufacturingReady": False,
        "globalProductionReady": False,
        "physicalPrintValidated": False,
        "liveMachineControl": False,
    }


def _separation(render: str = "ABSENT") -> dict:
    return {
        "artworkPixels": "FIXTURE",
        "historicalArtwork": "BLOCKED",
        "geometryHashAndUv": "REAL_LOGIC",
        "renderMedia": render,
        "automatedTestsAndCi": "MOCK_REGRESSION",
        "externalSystems": "DECLARED_REF_NOT_LIVE",
        "production": "BLOCKED",
    }


def _angles() -> list[dict]:
    rows = [{
        "id": "HERO_45",
        "filename": VIEW_FILES["HERO_45"],
        "status": "DECLARED_PREVIEW_CAMERA",
        "units": "m",
        "location": list(HERO_CAMERA["location"]),
        "lookAt": list(HERO_CAMERA["lookAt"]),
        "focalLengthMm": HERO_CAMERA["focalLengthMm"],
        "reason": None,
    }]
    for view in PREVIEW_VIEWS:
        rows.append({
            "id": view["id"],
            "filename": view["filename"],
            "status": "DECLARED_PREVIEW_CAMERA",
            "units": "m",
            "location": list(view["location"]),
            "lookAt": list(view["lookAt"]),
            "focalLengthMm": view["focalLengthMm"],
            "reason": None,
        })
    rows.append({
        "id": "FRONT_OPEN",
        "filename": None,
        "status": "BLOCKED",
        "units": None,
        "location": None,
        "lookAt": None,
        "focalLengthMm": None,
        "reason": "articulation authority UNKNOWN",
    })
    return rows


def _family_refs() -> list[dict]:
    return [
        {"system": "FOX3D_GOLDEN", "kind": "ENGINEERING_TEMPLATE", "id": GoldenRecipe().recipeId, "binding": "LOCAL_AUTHORITY", "truth": "REAL_LOGIC", "ref": ISSUE_4},
        {"system": "ERP", "kind": "PRODUCT_FAMILY", "id": None, "binding": "UNBOUND", "truth": "DECLARED_REF_NOT_LIVE", "ref": ISSUE_18},
        {"system": "AI_PRINT_OS", "kind": "MASTER_PRODUCT", "id": None, "binding": "UNBOUND", "truth": "DECLARED_REF_NOT_LIVE", "ref": None},
        {"system": "AI_PRINT_OS", "kind": "DIE_MOLD", "id": MOLD_ID, "binding": "LOCAL_TEMPLATE_NOT_APPROVED_PLATE", "truth": "CONFIG", "ref": ISSUE_4},
        {"system": "SPECPILOT_PRODUCT_DNA", "kind": "PRODUCT_DNA", "id": None, "binding": "DECLARED_ISSUE_REF", "truth": "DECLARED_REF_NOT_LIVE", "ref": SPECPILOT_59},
    ]


def _sku_refs(sku: str) -> list[dict]:
    return _family_refs() + [
        {"system": "ERP", "kind": "SKU", "id": sku, "binding": "LOCAL_SKU_CODE", "truth": "CONFIG", "ref": ISSUE_4},
        {"system": "SPECPILOT_PRODUCT_DNA", "kind": "PRODUCT_DNA", "id": None, "binding": "DECLARED_ISSUE_REF", "truth": "DECLARED_REF_NOT_LIVE", "ref": SPECPILOT_58},
    ]


def _fixture_pngs(package: dict) -> dict[str, bytes]:
    master = package["version"] == "FIXTURE_MASTER_V1"
    images = {}
    for index, src in enumerate(package["sources"]):
        rgb = fixture_pixels(src["widthPx"], src["heightPx"], package["sku"], 0 if master else index + 1)
        png = encode_png(src["widthPx"], src["heightPx"], rgb)
        if sha256_bytes(png) != src["fileSha256"]:
            raise ProductDnaError("校驗圖身分重算失敗", 409)
        images[src["name"]] = png
    return images


def _trim_hash(package: dict, placement: dict, images: dict[str, bytes]) -> str:
    sw, sh, rgb = decode_png_rgb(images[placement["source"]["name"]])
    crop = placement["cropPx"]
    cropped = crop_rgb(rgb, sw, sh, crop["x"], crop["y"], crop["width"], crop["height"])
    return sha256_bytes(encode_png(crop["width"], crop["height"], cropped))


def _media_for(package: dict) -> list[dict]:
    rights = "NO_IP_FIXTURE"
    images = _fixture_pngs(package)
    rows = [
        {"role": "GLB", "filename": "model.glb", "sourceHash": None, "bytesPresent": False, "sizeBytes": None, "evidenceClass": "ABSENT", "entityAuthenticity": "ABSENT", "rightsStatus": rights, "usageLimit": USAGE_LIMIT, "componentId": None},
        {"role": "PNG_HERO", "filename": VIEW_FILES["HERO_45"], "sourceHash": None, "bytesPresent": False, "sizeBytes": None, "evidenceClass": "ABSENT", "entityAuthenticity": "ABSENT", "rightsStatus": rights, "usageLimit": USAGE_LIMIT, "componentId": None},
        {"role": "PNG_FRONT", "filename": VIEW_FILES["FRONT_CLOSED"], "sourceHash": None, "bytesPresent": False, "sizeBytes": None, "evidenceClass": "ABSENT", "entityAuthenticity": "ABSENT", "rightsStatus": rights, "usageLimit": USAGE_LIMIT, "componentId": None},
        {"role": "PNG_DETAIL", "filename": VIEW_FILES["DOOR_DETAIL"], "sourceHash": None, "bytesPresent": False, "sizeBytes": None, "evidenceClass": "ABSENT", "entityAuthenticity": "ABSENT", "rightsStatus": rights, "usageLimit": USAGE_LIMIT, "componentId": None},
    ]
    for src in package["sources"]:
        rows.append({
            "role": "ARTWORK_SOURCE", "filename": src["name"], "sourceHash": src["fileSha256"],
            "bytesPresent": False, "sizeBytes": None, "evidenceClass": "FIXTURE", "entityAuthenticity": "SYNTHETIC_FIXTURE",
            "rightsStatus": rights, "usageLimit": USAGE_LIMIT, "componentId": None,
        })
    for placement in package["placements"]:
        rows.append({
            "role": "PRODUCTION_TRIM", "filename": placement["componentId"] + "-production-trim.png",
            "sourceHash": _trim_hash(package, placement, images),
            "bytesPresent": False, "sizeBytes": None, "evidenceClass": "FIXTURE", "entityAuthenticity": "SYNTHETIC_FIXTURE",
            "rightsStatus": rights, "usageLimit": USAGE_LIMIT, "componentId": placement["componentId"],
        })
    return rows


def _geometry(golden: dict, recipe: GoldenRecipe) -> dict:
    door = golden["surfaces"][0]
    return {
        "units": "mm",
        "widthMm": recipe.widthMm.value,
        "depthMm": recipe.depthMm.value,
        "heightMm": recipe.heightMm.value,
        "doorWidthMm": door["widthMm"],
        "doorHeightMm": door["heightMm"],
        "safeMm": recipe.safeMm,
        "bleedMm": recipe.bleedMm,
        "dimensionTruth": "CONFIG",
        "thicknessTruth": "ESTIMATED",
    }


def project_twin(tenant: str, sku: str, version: str, golden: dict | None = None) -> dict:
    tenant = check_tenant(tenant)
    version = check_version(version)
    if sku not in SKUS:
        raise ProductDnaError("找不到 Golden SKU", 404)
    golden = golden or build_golden()
    recipe = GoldenRecipe()
    package = package_plan(sku, version, golden)
    if not package.get("ready") or package.get("truth") != "FIXTURE":
        raise ProductDnaError("沒有圖稿授權，不能匯出歷史原稿", 422)
    placements = []
    for surface, placement in zip(golden["surfaces"], package["placements"]):
        placements.append({
            "componentId": placement["componentId"],
            "widthMm": placement["cropMm"]["widthMm"],
            "heightMm": placement["cropMm"]["heightMm"],
            "originTopMm": list(surface["originTopMm"]),
            "cropMm": dict(placement["cropMm"]),
            "uvRect": dict(placement["uvRect"]),
            "safeMm": placement["safeMm"],
            "bleedMm": placement["bleedMm"],
            "placementHash": placement["placementHash"],
            "finalUvHash": placement["finalUvHash"],
            "surfaceHash": placement["surfaceHash"],
        })
    hashes = {
        "engineeringHash": golden["engineeringHash"],
        "bomHash": _bom_hash(golden),
        "artworkHash": package["artworkHash"],
        "finalUvHash": _final_uv_hash(package),
        "packageHash": package["packageHash"],
        "bomScope": "CANDIDATE_ONLY_NOT_A_CUT_LIST",
    }
    twin_id = "twin_" + stable_hash({
        "familyId": FAMILY_ID, "moldId": MOLD_ID, "tenantId": tenant, "sku": sku,
        "artworkVersion": version, "engineeringHash": hashes["engineeringHash"], "artworkHash": hashes["artworkHash"],
    })[:40]
    body = {
        "schemaVersion": SCHEMA,
        "twinId": twin_id,
        "familyId": FAMILY_ID,
        "moldId": MOLD_ID,
        "engineeringTemplateId": recipe.recipeId,
        "engineeringVersion": recipe.recipeId,
        "tenantId": tenant,
        "sku": sku,
        "artworkVersion": version,
        "hashes": hashes,
        "geometryMm": _geometry(golden, recipe),
        "placements": placements,
        "angles": _angles(),
        "media": _media_for(package),
        "rights": _rights(),
        "sourceRefs": _sku_refs(sku),
        "truth": _preview_truth(),
        "evidenceSeparation": _separation(),
    }
    return Twin.model_validate(body).model_dump(mode="json")


def project_manifest(tenant: str, *, version: str = "FIXTURE_MASTER_V1", skus: list[str] | tuple[str, ...] | None = None) -> dict:
    tenant = check_tenant(tenant)
    version = check_version(version)
    chosen = check_skus(skus)
    golden = build_golden()
    recipe = GoldenRecipe()
    twins = [project_twin(tenant, sku, version, golden) for sku in chosen]
    body = {
        "schemaVersion": SCHEMA,
        "familyId": FAMILY_ID,
        "moldId": MOLD_ID,
        "engineeringTemplateId": recipe.recipeId,
        "engineeringVersion": recipe.recipeId,
        "tenantId": tenant,
        "inputHash": stable_hash({"schema": SCHEMA, "tenantId": tenant, "version": version, "skus": list(chosen), "familyId": FAMILY_ID, "moldId": MOLD_ID}),
        "engineeringHash": golden["engineeringHash"],
        "bomHash": _bom_hash(golden),
        "skuCount": 3,
        "twins": twins,
        "sourceRefs": _family_refs(),
        "knownGaps": list(KNOWN_GAPS),
        "truth": _preview_truth(),
        "evidenceSeparation": _separation(),
        "globalProductionReady": False,
        "liveSystemRead": False,
        "contentHash": "0" * 64,
    }
    body["contentHash"] = stable_hash({k: v for k, v in body.items() if k != "contentHash"})
    try:
        return FamilyManifest.model_validate(body).model_dump(mode="json")
    except ValidationError as exc:
        raise ProductDnaError("契約無法通過型別檢查", 422) from exc


def catalog() -> dict:
    golden = build_golden()
    return {
        "schemaVersion": SCHEMA,
        "familyId": FAMILY_ID,
        "moldId": MOLD_ID,
        "engineeringTemplateId": GoldenRecipe().recipeId,
        "engineeringHash": golden["engineeringHash"],
        "bomHash": _bom_hash(golden),
        "skus": list(SKUS),
        "defaultExportSkus": list(EXPORT_SKUS),
        "artworkVersions": list(ARTWORK_VERSIONS),
        "historicalArtwork": "BLOCKED",
        "consumers": list(CONSUMERS),
        "globalProductionReady": False,
        "liveSystemRead": False,
        "knownGaps": list(KNOWN_GAPS),
    }


def require_current_engineering_version(proposed: GoldenRecipe) -> dict:
    """Size, structure and process changes must not keep the current template id."""
    current = build_golden()
    updated = build_golden(proposed)
    changed = updated["engineeringHash"] != current["engineeringHash"]
    if changed:
        raise ProductDnaError("尺寸、結構或工法已變更，必須使用新的工程版本，不能沿用目前模具", 409)
    return {"engineeringHash": current["engineeringHash"], "newEngineeringVersionRequired": False, "acceptedAsCurrentVersion": True}


def engineering_version_effect(proposed: GoldenRecipe) -> dict:
    current = build_golden()["engineeringHash"]
    updated = build_golden(proposed)["engineeringHash"]
    return {"currentEngineeringHash": current, "proposedEngineeringHash": updated, "newEngineeringVersionRequired": updated != current}


def label_render_evidence(*, evidence_origin: str | None, real_blender: bool, used_mock: bool, blender_version: str | None) -> str:
    """Classify an evidence envelope. Returning REAL_BLENDER does not create a render."""
    if evidence_origin == LIVE_BLENDER_ORIGIN:
        live = (
            real_blender is True
            and used_mock is False
            and isinstance(blender_version, str)
            and bool(blender_version.strip())
            and os.environ.get("FOX3D_MOCK_BLENDER") != "1"
        )
        if not live:
            raise ProductDnaError("REAL Blender 標籤被拒絕：環境或觀察不符合", 409)
        return "REAL_BLENDER"
    if evidence_origin == "FIXTURE":
        return "FIXTURE"
    if evidence_origin in {"MOCK_REGRESSION", "UNIT_SYNTHETIC", "ABSENT"}:
        return "MOCK_REGRESSION" if evidence_origin != "ABSENT" else "ABSENT"
    raise ProductDnaError("無法分類的證據來源，拒絕標成真實 Blender", 409)


def read_real_generation_media(folder: Path, *, sku: str, version: str) -> dict:
    """Attach real render hashes only from a stamped live Blender generation.

    Pytest fixtures that merely set realBlender=true are rejected.
    """
    from fox3d.golden_preview import validate_generation

    manifest = read_json(Path(folder) / "manifest.json")
    info = manifest.get("renderInfo") if isinstance(manifest, dict) else None
    if not isinstance(info, dict):
        raise ProductDnaError("缺少渲染觀察，不能標成真實 Blender", 409)
    label = label_render_evidence(
        evidence_origin=info.get("evidenceOrigin"),
        real_blender=info.get("realBlender") is True,
        used_mock=info.get("usedMock") is True,
        blender_version=info.get("blenderVersion") if isinstance(info.get("blenderVersion"), str) else None,
    )
    if label != "REAL_BLENDER":
        raise ProductDnaError("這份觀察不是真實 Blender", 409)
    try:
        validated = validate_generation(Path(folder), sku, version)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProductDnaError("真實 Blender 成果驗證失敗", 409) from exc
    files = validated.get("files") or {}
    media = []
    for role, filename in (("GLB", "model.glb"), ("PNG_HERO", "beauty.png"), ("PNG_FRONT", "front-closed.png"), ("PNG_DETAIL", "door-detail.png")):
        digest = files.get(filename) or {}
        media.append({
            "role": role,
            "filename": filename,
            "sourceHash": digest.get("sha256"),
            "bytesPresent": True,
            "sizeBytes": digest.get("sizeBytes"),
            "evidenceClass": "REAL_BLENDER",
            "entityAuthenticity": "REAL_BLENDER_PREVIEW",
            "rightsStatus": "NO_IP_FIXTURE",
            "usageLimit": USAGE_LIMIT,
            "componentId": None,
        })
    return {
        "evidenceClass": "REAL_BLENDER",
        "executedByThisModule": False,
        "media": media,
        "productionReady": False,
        "globalProductionReady": False,
    }


def semantic_view(manifest: dict) -> dict:
    twins = []
    for twin in manifest["twins"]:
        twins.append({
            "twinId": twin["twinId"],
            "sku": twin["sku"],
            "artworkVersion": twin["artworkVersion"],
            "hashes": twin["hashes"],
            "geometryMm": twin["geometryMm"],
            "placements": twin["placements"],
            "angles": twin["angles"],
            "rights": twin["rights"],
            "sourceRefs": twin["sourceRefs"],
            "mediaIdentity": [
                {"role": row["role"], "filename": row["filename"], "sourceHash": row["sourceHash"], "componentId": row.get("componentId"), "evidenceClass": row["evidenceClass"]}
                for row in twin["media"]
            ],
        })
    return {"familyId": manifest["familyId"], "moldId": manifest["moldId"], "engineeringHash": manifest["engineeringHash"], "bomHash": manifest["bomHash"], "twins": twins}


def _same_number(declared: Any, actual: float) -> bool:
    if isinstance(declared, bool) or not isinstance(declared, (int, float)) or not isinstance(actual, float):
        return False
    number = float(declared)
    return number == actual and number == number


def reconcile(snapshot: dict, *, tenant_id: str, version: str = "FIXTURE_MASTER_V1") -> dict:
    """Compare a declared external snapshot with local Golden authority. Nothing is written."""
    tenant_id = check_tenant(tenant_id)
    version = check_version(version)
    system = snapshot.get("system")
    if system not in {"ERP", "AI_PRINT_OS", "SPECPILOT_PRODUCT_DNA"}:
        raise ProductDnaError("未知的外部系統", 422)
    checks: list[dict] = []
    if snapshot.get("tenantId") != tenant_id:
        checks.append({"field": "tenantId", "status": "TENANT_MISMATCH"})
        return _report(system, tenant_id, checks, new_version=False)
    golden = build_golden()
    recipe = GoldenRecipe()
    sku = snapshot.get("skuId")
    package = package_plan(sku, version, golden) if sku in SKUS else None
    local = {
        "productFamilyId": FAMILY_ID,
        "dieMoldId": MOLD_ID,
        "engineeringVersion": recipe.recipeId,
        "widthMm": recipe.widthMm.value,
        "depthMm": recipe.depthMm.value,
        "heightMm": recipe.heightMm.value,
        "boardThicknessMm": recipe.boardThicknessMm.value,
        "backThicknessMm": recipe.backThicknessMm.value,
        "doorThicknessMm": recipe.doorThicknessMm.value,
        "doorGapMm": recipe.doorGapMm.value,
        "engineeringHash": golden["engineeringHash"],
        "bomHash": _bom_hash(golden),
    }
    required = (
        "productFamilyId", "skuId", "dieMoldId", "engineeringVersion", "widthMm", "depthMm", "heightMm",
        "engineeringHash", "bomHash", "artworkHash", "finalUvHash", "rightsScope",
    )
    optional = ("boardThicknessMm", "backThicknessMm", "doorThicknessMm", "doorGapMm", "processCode")
    external_only = ("masterProductId", "productDnaId")
    for field in required:
        incoming = snapshot.get(field)
        if incoming is None:
            checks.append({"field": field, "status": "UNBOUND"})
            continue
        checks.append({"field": field, "status": _match_field(field, incoming, local, sku, package)})
    for field in optional:
        if snapshot.get(field) is None:
            continue
        checks.append({"field": field, "status": _match_field(field, snapshot.get(field), local, sku, package)})
    for field in external_only:
        checks.append({"field": field, "status": "UNBOUND_LOCAL", "supplied": snapshot.get(field) is not None, "liveRead": False})
    mm_fields = ("widthMm", "depthMm", "heightMm", "boardThicknessMm", "backThicknessMm", "doorThicknessMm", "doorGapMm")
    mm_conflict = any(row["field"] in mm_fields and row["status"] == "MISMATCH" for row in checks)
    process_conflict = any(row["field"] == "processCode" and row["status"] == "STALE_ENGINEERING_VERSION" for row in checks)
    claimed_current = snapshot.get("engineeringVersion") in {None, recipe.recipeId} or snapshot.get("engineeringHash") == golden["engineeringHash"]
    if (mm_conflict or process_conflict) and claimed_current:
        checks.append({"field": "engineeringVersion", "status": "STALE_ENGINEERING_VERSION"})
    elif mm_conflict or process_conflict:
        checks.append({"field": "engineeringVersion", "status": "UNKNOWN_ENGINEERING_VERSION"})
    return _report(system, tenant_id, checks, new_version=mm_conflict or process_conflict)


def _match_field(field: str, incoming: Any, local: dict, sku: str | None, package: dict | None) -> str:
    if field == "skuId":
        return "MATCH" if incoming in SKUS else "MISMATCH"
    if field == "rightsScope":
        if incoming == "LICENSED_ARTWORK":
            return "BLOCKED_RIGHTS"
        if incoming in {"NONE", "FIXTURE_NON_IP"}:
            return "MATCH"
        return "MISMATCH"
    if field == "processCode":
        return "MATCH" if incoming == PRINT_PROCESS else "STALE_ENGINEERING_VERSION"
    if field in {"artworkHash", "finalUvHash"}:
        if package is None:
            return "MISMATCH"
        expected = package["artworkHash"] if field == "artworkHash" else _final_uv_hash(package)
        return "MATCH" if incoming == expected else "MISMATCH"
    if field in {"widthMm", "depthMm", "heightMm", "boardThicknessMm", "backThicknessMm", "doorThicknessMm", "doorGapMm"}:
        return "MATCH" if _same_number(incoming, local[field]) else "MISMATCH"
    return "MATCH" if incoming == local.get(field) else "MISMATCH"


def _report(system: str, tenant_id: str, checks: list[dict], *, new_version: bool) -> dict:
    statuses = {row["status"] for row in checks}
    bad = {"MISMATCH", "BLOCKED_RIGHTS", "STALE_ENGINEERING_VERSION", "TENANT_MISMATCH", "UNKNOWN_ENGINEERING_VERSION"}
    if statuses & bad:
        status = "REJECTED"
    elif "UNBOUND" in statuses:
        status = "PARTIAL"
    else:
        status = "LOCAL_MATCH_EXTERNAL_UNBOUND"
    return {
        "schemaVersion": RECONCILE_SCHEMA,
        "system": system,
        "tenantId": tenant_id,
        "status": status,
        "checks": checks,
        "newEngineeringVersionRequired": new_version,
        "liveRead": False,
        "liveWrite": False,
        "globalProductionReady": False,
        "persisted": False,
    }


def _safe_filename(name: str) -> str:
    if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
        raise ProductDnaError("不安全的檔名", 409)
    return name


class ExportService:
    """Local preview-contract publication. Not a production deploy."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._cancelled: set[tuple[str, str]] = set()

    def _tenant_dir(self, tenant: str) -> Path:
        return self.root / "product-dna" / stable_hash({"tenant": tenant})[:24]

    def _export_dir(self, tenant: str, export_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9-]{36}", export_id):
            raise ProductDnaError("找不到匯出", 404)
        return self._tenant_dir(tenant) / "exports" / export_id

    def begin(self, tenant: str, *, version: str = "FIXTURE_MASTER_V1", skus: list[str] | tuple[str, ...] | None = None, seal: bool = True, before_seal=None) -> dict:
        tenant = check_tenant(tenant)
        version = check_version(version)
        chosen = check_skus(skus)
        fresh = project_manifest(tenant, version=version, skus=chosen)
        if seal and before_seal is None:
            current = read_json(self._tenant_dir(tenant) / "current.json")
            if current.get("inputHash") == fresh["inputHash"] and current.get("exportId"):
                try:
                    return self.read(tenant, current["exportId"])
                except ProductDnaError:
                    pass
        export_id = new_id()
        folder = self._export_dir(tenant, export_id)
        folder.mkdir(parents=True, exist_ok=False)
        state = {"state": "running", "exportId": export_id, "tenantId": tenant, "version": version, "skus": list(chosen), "inputHash": fresh["inputHash"], "sealed": False}
        atomic_json(folder / "state.json", state)
        if before_seal is not None:
            before_seal(export_id)
        if (tenant, export_id) in self._cancelled or read_json(folder / "state.json").get("state") == "cancelled":
            state["state"] = "cancelled"
            atomic_json(folder / "state.json", state)
            return {"state": "cancelled", "exportId": export_id, "sealed": False, "tenantId": tenant, "inputHash": fresh["inputHash"]}
        if not seal:
            state["state"] = "staged"
            atomic_json(folder / "state.json", state)
            return {"state": "staged", "exportId": export_id, "sealed": False, "tenantId": tenant, "inputHash": fresh["inputHash"], "version": version, "skus": list(chosen)}
        return self._seal(tenant, export_id, fresh)

    def cancel(self, tenant: str, export_id: str) -> dict:
        tenant = check_tenant(tenant)
        folder = self._export_dir(tenant, export_id)
        self._cancelled.add((tenant, export_id))
        if not folder.exists():
            return {"state": "cancelled", "exportId": export_id, "sealed": False, "tenantId": tenant}
        if (folder / "seal.json").exists() or read_json(folder / "state.json").get("state") == "sealed":
            raise ProductDnaError("已封存的預覽契約不能取消", 409)
        state = read_json(folder / "state.json")
        state.update(state="cancelled", sealed=False, tenantId=tenant, exportId=export_id)
        atomic_json(folder / "state.json", state)
        return {"state": "cancelled", "exportId": export_id, "sealed": False, "tenantId": tenant, "inputHash": state.get("inputHash")}

    def retry(self, tenant: str, export_id: str) -> dict:
        tenant = check_tenant(tenant)
        folder = self._export_dir(tenant, export_id)
        state = read_json(folder / "state.json")
        if state.get("tenantId") not in {None, tenant} or not state:
            raise ProductDnaError("找不到匯出", 404)
        if state.get("state") == "sealed":
            return self.read(tenant, export_id)
        if state.get("state") == "cancelled":
            return self.begin(tenant, version=state["version"], skus=tuple(state["skus"]), seal=True)
        if state.get("state") == "staged":
            fresh = project_manifest(tenant, version=state["version"], skus=tuple(state["skus"]))
            return self._seal(tenant, export_id, fresh)
        raise ProductDnaError("匯出仍在進行", 409)

    def _seal(self, tenant: str, export_id: str, fresh: dict) -> dict:
        folder = self._export_dir(tenant, export_id)
        if (tenant, export_id) in self._cancelled:
            raise ProductDnaError("匯出已取消", 409)
        golden = build_golden()
        manifest = project_manifest(tenant, version=fresh["twins"][0]["artworkVersion"], skus=[twin["sku"] for twin in fresh["twins"]])
        for twin in manifest["twins"]:
            package = package_plan(twin["sku"], twin["artworkVersion"], golden)
            sku_dir = folder / "skus" / twin["sku"]
            _, production = materialize_package(sku_dir, package, golden)
            produced = {row["componentId"]: row for row in production}
            for media in twin["media"]:
                filename = _safe_filename(media["filename"])
                if media["role"] == "ARTWORK_SOURCE":
                    path = sku_dir / filename
                    raw = path.read_bytes()
                    digest = sha256_bytes(raw)
                    if digest != media["sourceHash"]:
                        raise ProductDnaError("校驗圖 SHA 與 Artwork 身分不符", 409)
                    media["bytesPresent"] = True
                    media["sizeBytes"] = len(raw)
                elif media["role"] == "PRODUCTION_TRIM":
                    record = produced[media["componentId"]]
                    path = sku_dir / _safe_filename(record["file"])
                    raw = path.read_bytes()
                    if sha256_bytes(raw) != record["productionArtworkHash"]:
                        raise ProductDnaError("裁圖 SHA 不符", 409)
                    media["filename"] = record["file"]
                    media["sourceHash"] = record["productionArtworkHash"]
                    media["bytesPresent"] = True
                    media["sizeBytes"] = len(raw)
        manifest["contentHash"] = stable_hash({k: v for k, v in manifest.items() if k != "contentHash"})
        FamilyManifest.model_validate(manifest)
        envelope = {
            "schemaVersion": ENVELOPE_SCHEMA,
            "exportId": export_id,
            "state": "sealed",
            "tenantId": tenant,
            "createdAt": utcnow().isoformat(),
            "manifest": manifest,
        }
        atomic_json(folder / "envelope.json", envelope)
        seal = {
            "exportId": export_id,
            "tenantId": tenant,
            "inputHash": manifest["inputHash"],
            "semanticHash": stable_hash(semantic_view(manifest)),
            "envelopeSha256": sha256_bytes((folder / "envelope.json").read_bytes()),
            "state": "sealed",
        }
        atomic_json(folder / "seal.json", seal)
        atomic_json(folder / "state.json", {"state": "sealed", "exportId": export_id, "tenantId": tenant, "version": manifest["twins"][0]["artworkVersion"], "skus": [twin["sku"] for twin in manifest["twins"]], "inputHash": manifest["inputHash"], "sealed": True})
        atomic_json(self._tenant_dir(tenant) / "current.json", {"exportId": export_id, "tenantId": tenant, "inputHash": manifest["inputHash"]})
        return self.read(tenant, export_id)

    def read(self, tenant: str, export_id: str) -> dict:
        tenant = check_tenant(tenant)
        folder = self._export_dir(tenant, export_id)
        seal = read_json(folder / "seal.json")
        envelope_path = folder / "envelope.json"
        if seal.get("tenantId") != tenant or seal.get("exportId") != export_id or not envelope_path.is_file():
            raise ProductDnaError("找不到匯出", 404)
        raw = envelope_path.read_bytes()
        if sha256_bytes(raw) != seal.get("envelopeSha256"):
            raise ProductDnaError("匯出 SHA 已被改寫", 409)
        try:
            envelope = FamilyEnvelope.model_validate_json(raw)
        except ValidationError as exc:
            raise ProductDnaError("匯出契約無法通過型別檢查", 409) from exc
        manifest = envelope.manifest.model_dump(mode="json")
        if envelope.tenantId != tenant or stable_hash(semantic_view(manifest)) != seal.get("semanticHash"):
            raise ProductDnaError("匯出語意與封存不符", 409)
        fresh = project_manifest(tenant, version=manifest["twins"][0]["artworkVersion"], skus=[twin["sku"] for twin in manifest["twins"]])
        if semantic_view(fresh) != semantic_view(manifest):
            raise ProductDnaError("匯出與目前工程母版不一致", 409)
        self._verify_files(folder, manifest)
        return envelope.model_dump(mode="json")

    def _verify_files(self, folder: Path, manifest: dict) -> None:
        for twin in manifest["twins"]:
            sku_dir = folder / "skus" / twin["sku"]
            for media in twin["media"]:
                if media["role"] in {"ARTWORK_SOURCE", "PRODUCTION_TRIM"} and media["bytesPresent"] is not True:
                    raise ProductDnaError("封存匯出缺少校驗檔 " + media["filename"], 409)
                if media["evidenceClass"] == "REAL_BLENDER":
                    raise ProductDnaError("這次封存沒有真實 Blender 檔案", 409)
                if media["bytesPresent"] is not True:
                    continue
                path = sku_dir / _safe_filename(media["filename"])
                if not path.is_file():
                    raise ProductDnaError("缺少檔案 " + media["filename"], 409)
                raw = path.read_bytes()
                if sha256_bytes(raw) != media.get("sourceHash") or len(raw) != media.get("sizeBytes"):
                    raise ProductDnaError("檔案 SHA 不符 " + media["filename"], 409)


class FamilyEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal["fox3d.product_dna.export-envelope.v1"]
    exportId: str
    state: Literal["sealed"]
    tenantId: str
    createdAt: str
    manifest: FamilyManifest


def media_refs(tenant: str, consumer: str, *, version: str = "FIXTURE_MASTER_V1") -> dict:
    if consumer not in CONSUMERS:
        raise ProductDnaError("未知的媒體讀取方", 404)
    manifest = project_manifest(tenant, version=version)
    return {
        "consumer": consumer,
        "readOnly": True,
        "liveSystemRead": False,
        "usageLimit": USAGE_LIMIT,
        "rightsStatus": "NO_IP_FIXTURE",
        "entityAuthenticity": "SYNTHETIC_FIXTURE",
        "renderEvidenceClass": "ABSENT",
        "automatedTestsAndCi": "MOCK_REGRESSION",
        "globalProductionReady": False,
        "twins": [{"sku": twin["sku"], "twinId": twin["twinId"], "media": twin["media"], "angles": twin["angles"], "hashes": twin["hashes"]} for twin in manifest["twins"]],
    }
