"""Issue 4: configured cabinet geometry and explicitly synthetic artwork fixtures.

No historical artwork or verified joinery is available. Readiness stays false.
All geometry is authored in mm; only the Blender/viewer boundary converts to m.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fox3d.artwork import crop_rgb, decode_png_rgb, final_uv_identity, mm_to_uv
from fox3d.ids import sha256_bytes, stable_hash
from fox3d.pngutil import write_png, encode_png

RECIPE_ID = "THREE_TIER_DOOR_CABINET_424x295x900_V1"
ISSUE_URL = "https://github.com/netfox-web/blender-autonomous-3d/issues/4"
SKUS = ("KU002101", "KT015101", "CN003701", "PN010201")
VERSIONS = ("HISTORICAL_PENDING", "FIXTURE_MASTER_V1", "FIXTURE_SINGLE_V1")


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    value: float = Field(gt=0, le=5000)
    truth: Literal["CONFIG", "ESTIMATED", "VERIFIED"] = "CONFIG"
    evidence: str = Field(min_length=1, max_length=2000)
    evidenceSha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def verified_reference(self):
        if self.truth == "VERIFIED" and not self.evidenceSha256:
            raise ValueError("verified measurement needs an evidence digest")
        return self


class GoldenRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    recipeId: Literal["THREE_TIER_DOOR_CABINET_424x295x900_V1"] = RECIPE_ID
    widthMm: Measurement = Field(default_factory=lambda: Measurement(value=424., evidence=ISSUE_URL))
    depthMm: Measurement = Field(default_factory=lambda: Measurement(value=295., evidence=ISSUE_URL))
    heightMm: Measurement = Field(default_factory=lambda: Measurement(value=900., evidence=ISSUE_URL))
    boardThicknessMm: Measurement = Field(default_factory=lambda: Measurement(value=15., truth="ESTIMATED", evidence="Preview assumption; no verified drawing"))
    backThicknessMm: Measurement = Field(default_factory=lambda: Measurement(value=3., truth="ESTIMATED", evidence="Preview assumption; no verified drawing"))
    doorThicknessMm: Measurement = Field(default_factory=lambda: Measurement(value=15., truth="ESTIMATED", evidence="Preview assumption; no verified drawing"))
    doorGapMm: Measurement = Field(default_factory=lambda: Measurement(value=2., evidence="Preview clearance policy"))
    tiers: Literal[3] = 3
    doors: Literal[3] = 3
    safeMm: float = Field(default=5., ge=0, le=20)
    bleedMm: float = Field(default=3., ge=0, le=20)
    hardwareAuthority: Literal["UNKNOWN"] = "UNKNOWN"
    articulationAuthority: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def dimensions(self):
        w,d,h,t,b,dt,g = [getattr(self,k).value for k in ("widthMm","depthMm","heightMm","boardThicknessMm","backThicknessMm","doorThicknessMm","doorGapMm")]
        if min(w-2*t-2*g, (h-4*t)/3-2*g, d-b-dt-g) < 20:
            raise ValueError("Thickness or gaps leave no usable opening")
        return self


def build_golden(recipe: GoldenRecipe | None = None):
    r = recipe or GoldenRecipe()
    w,d,h,t,b,dt,g = [getattr(r,k).value for k in ("widthMm","depthMm","heightMm","boardThicknessMm","backThicknessMm","doorThicknessMm","doorGapMm")]
    iw, oh = w-2*t, (h-4*t)/3
    parts = []
    def part(cid, label, role, size, location):
        parts.append({"componentId":cid,"partName":label,"role":role,
                      "sizeMm":size,"locationMm":location})
    part("left_side","左側板","left",[t,d,h],[-w/2+t/2,0.,h/2])
    part("right_side","右側板","right",[t,d,h],[w/2-t/2,0.,h/2])
    part("top_panel","頂板","top",[iw,d,t],[0.,0.,h-t/2])
    part("bottom_panel","底板","bottom",[iw,d,t],[0.,0.,t/2])
    part("back_panel","背板","back",[iw,b,h-2*t],[0.,d/2-b/2,h/2])
    for i in range(2):
        part(f"shelf_{i+1}",f"內層板 {i+1}","shelf",[iw,d-b-dt-g,t],[0.,(dt+g-b)/2,t+oh+(oh+t)*i+t/2])
    for i in range(3):
        part(f"door_{i+1}",f"門片 {i+1}（由上到下）","door",[iw-2*g,dt,oh-2*g],[0.,-d/2+dt/2,t+(2-i)*(oh+t)+oh/2])
    # Print policy belongs to surface/placement hashes, not EngineeringHash.
    truth = r.model_dump(mode="json",exclude={"safeMm","bleedMm"})
    authority = {"recipe":truth,"componentsMm":parts,"units":"mm","doorOrder":"TOP_TO_BOTTOM"}
    engineering_hash = stable_hash(authority)
    surfaces=[]
    doors = [p for p in parts if p["role"] == "door"]
    top = doors[0]["locationMm"][2]+doors[0]["sizeMm"][2]/2
    for p in doors:
        width,_,height=p["sizeMm"]
        surface={"componentId":p["componentId"],"objectName":p["partName"],"face":"FRONT",
                 "engineeringHash":engineering_hash,"widthMm":width,"heightMm":height,
                 "originTopMm":[0.,top-p["locationMm"][2]-height/2],
                 "safeMm":r.safeMm,"bleedMm":r.bleedMm,"trimTruth":"CONFIG",
                 "keepOuts":[],"keepOutAuthority":"UNKNOWN","hingeAuthority":"UNKNOWN"}
        surface["surfaceHash"]=stable_hash(surface)
        surfaces.append(surface)
    spec={"width":w,"depth":d,"height":h,"thickness":t,"material":"white_wood",
          "components":[{**p,"size":[v/1000 for v in p["sizeMm"]],"location":[v/1000 for v in p["locationMm"]]} for p in parts],
          "goldenRecipe":True,"recipePreview":True,"recipeId":RECIPE_ID,"engineeringHash":engineering_hash,
          "doorCount":3,"shelfCount":2,"engineeringReady":False,"productionReady":False}
    return {"authority":authority,"engineeringHash":engineering_hash,"spec":spec,"surfaces":surfaces,
            "manufacturing":manufacturing_inputs(parts,surfaces),
            "truth":{"dimensions":"CONFIG — Issue #4 declared dimensions","thickness":"ESTIMATED",
                     "hardware":"UNKNOWN","FRONT_OPEN":"BLOCKED — no verified hinge/articulation",
                     "engineeringReady":False,"productionReady":False,"manufacturingReady":False,"liveMachineControl":False}}


def manufacturing_inputs(parts,surfaces):
    boards=[{"componentId":p["componentId"],"quantity":1,"lengthMm":max(p["sizeMm"]),
             "widthMm":sorted(p["sizeMm"])[1],"thicknessMm":min(p["sizeMm"]),"truth":"ESTIMATED"} for p in parts]
    return {"scope":"CANDIDATE_ONLY_NOT_A_CUT_LIST","bomCandidate":boards,"boardList":boards,
            "printableSurfaces":surfaces,"nestingInput":{"parts":boards,"sheetSizeMm":None,"kerfMm":None,"grainDirection":"UNKNOWN"},
            "wasteRemnantInput":{"netBoardAreaMm2":sum(p["lengthMm"]*p["widthMm"] for p in boards),
                                  "stockSheets":None,"remnants":None,"wastePercent":None,"status":"BLOCKED_STOCK_AND_KERF_REQUIRED"},
            "manufacturingReady":False}


@lru_cache(maxsize=16)
def fixture_pixels(width, height, sku, door=0):
    """Asymmetric calibration image, not a recreation of historical SKU artwork."""
    marker = SKUS.index(sku)*37+door*23
    return bytes(channel for y in range(height) for x in range(width)
                 for channel in ((x+marker)%256,(y+marker)%256,((x//13+y//17)%2)*160+40))


def package_plan(sku, version, golden=None):
    if sku not in SKUS or version not in VERSIONS:
        raise ValueError("未知的 SKU 或 Artwork 版本")
    golden=golden or build_golden()
    if version=="HISTORICAL_PENDING":
        return {"sku":sku,"version":version,"ready":False,"truth":"BLOCKED",
                "engineeringHash":golden["engineeringHash"],"reason":"原始 Artwork 尚未提供，未偽造歷史圖稿",
                "slots":[{"componentId":f"door_{i+1}","sourcePath":None,"sha256":None,"sourceEvidence":None} for i in range(3)]}
    master=version=="FIXTURE_MASTER_V1"
    surfaces=golden["surfaces"]
    master_w=surfaces[0]["widthMm"]
    master_h=surfaces[-1]["originTopMm"][1]+surfaces[-1]["heightMm"]
    sources=[]
    # V1 diagnostics intentionally use exact one-pixel-per-mm grids. Other
    # calibrated measurements remain valid geometry but require a new artwork.
    for i in range(1 if master else 3):
        w,h=(master_w,master_h) if master else (surfaces[i]["widthMm"],surfaces[i]["heightMm"])
        if w!=int(w) or h!=int(h):
            raise ValueError("校驗圖僅支援整數毫米尺寸；請提供對應原稿")
        raw=fixture_pixels(int(w),int(h),sku,0 if master else i+1)
        sources.append({"name":f"fixture-{i+1}.png","widthPx":int(w),"heightPx":int(h),"rgbSha256":sha256_bytes(raw),
                        "fileSha256":sha256_bytes(encode_png(int(w),int(h),raw)),"truth":"FIXTURE"})
    identity={"sku":sku,"version":version,"engineeringHash":golden["engineeringHash"],"sources":sources,"truth":"FIXTURE"}
    artwork_hash=stable_hash(identity)
    placements=[]
    for i,surface in enumerate(surfaces):
        src=sources[0 if master else i]
        x,y=surface["originTopMm"] if master else (0.,0.)
        w,h=surface["widthMm"],surface["heightMm"]
        crop={"xMm":x,"yMm":y,"widthMm":w,"heightMm":h}
        if any(v!=int(v) for v in crop.values()):
            raise ValueError("校驗圖裁圖需要整數毫米")
        # Shared mm->UV authority; PNG rows run down, Blender v runs up.
        uv_surface={"widthMm":float(src["widthPx"]),"heightMm":float(src["heightPx"])}
        u0,v0=mm_to_uv(x,src["heightPx"]-y-h,uv_surface)
        u1,v1=mm_to_uv(x+w,src["heightPx"]-y,uv_surface)
        uv={"u0":u0,"v0":v0,"u1":u1,"v1":v1}
        placement={"sku":sku,"version":version,"engineeringHash":golden["engineeringHash"],"artworkHash":artwork_hash,
                   "surfaceHash":surface["surfaceHash"],"componentId":surface["componentId"],"objectName":surface["objectName"],
                   "face":"FRONT","order":i+1,"relation":"MASTER_SPLIT" if master else "SINGLE_SURFACE",
                   "source":src,"cropMm":crop,"cropPx":{"x":int(x),"y":int(y),"width":int(w),"height":int(h)},
                   "uvRect":uv,"rotationDeg":0.,"mirrored":False,"safeMm":surface["safeMm"],"bleedMm":surface["bleedMm"],
                   "keepOutAuthority":"UNKNOWN","fit":"EXACT_NO_STRETCH","pixelScalePxPerMm":1.}
        placement["placementHash"]=stable_hash(placement)
        placement["placementId"]=placement["placementHash"]
        placement.update(final_uv_identity(placement_id=placement["placementId"],object_name=placement["objectName"],
            component_id=placement["componentId"],face="FRONT",relation=placement["relation"],uv_rect=uv))
        placements.append(placement)
    package={**identity,"artworkHash":artwork_hash,"placements":placements,"ready":True,
             "doorOrder":"TOP_TO_BOTTOM","masterCanvasMm":[master_w,master_h] if master else None,
             "seamsMm":[surfaces[i+1]["originTopMm"][1]-surfaces[i]["originTopMm"][1]-surfaces[i]["heightMm"] for i in range(2)] if master else [],
             "productionReady":False,"productionCropScope":"TRIM_ONLY; bleed and unknown keep-outs need print authority"}
    package["packageHash"]=stable_hash(package)
    return package


def validate_package(package, *, sku, version, golden=None):
    expected=package_plan(sku,version,golden)
    if not expected["ready"] or stable_hash(package)!=stable_hash(expected):
        raise ValueError("Artwork identity / crop / seam / placement mismatch")


def materialize_package(folder: Path, package, golden=None):
    validate_package(package,sku=package["sku"],version=package["version"],golden=golden)
    folder.mkdir(parents=True,exist_ok=True)
    master=package["version"]=="FIXTURE_MASTER_V1"
    for i,src in enumerate(package["sources"]):
        rgb=fixture_pixels(src["widthPx"],src["heightPx"],package["sku"],0 if master else i+1)
        write_png(folder/src["name"],src["widthPx"],src["heightPx"],rgb)
    items=[]
    production=[]
    for p in package["placements"]:
        source=folder/p["source"]["name"]
        sw,sh,rgb=decode_png_rgb(source.read_bytes())
        c=p["cropPx"]
        cropped=crop_rgb(rgb,sw,sh,c["x"],c["y"],c["width"],c["height"])
        crop_path=folder/(p["componentId"]+"-production-trim.png")
        write_png(crop_path,c["width"],c["height"],cropped)
        record={"componentId":p["componentId"],"cropMm":p["cropMm"],"cropPx":c,"placementHash":p["placementHash"],
                "finalUvHash":p["finalUvHash"],"productionArtworkHash":sha256_bytes(crop_path.read_bytes()),"file":crop_path.name}
        production.append(record)
        items.append({**p,"imagePath":str(source.resolve()),"artworkSha256":sha256_bytes(source.read_bytes()),
                      "goldenObservedUv":True,"surfaceWidthMm":c["width"],"surfaceHeightMm":c["height"]})
    return items,production


def validate_worker_observation(observed, package, spec):
    if observed.get("realBlender") is not True or observed.get("usedMock") is not False:
        raise ValueError("REAL Blender observation required")
    if observed.get("sku")!=package["sku"] or observed.get("packageHash")!=package["packageHash"] or observed.get("engineeringHash")!=package["engineeringHash"]:
        raise ValueError("Worker package identity mismatch")
    actual=observed.get("parts",[])
    if len(actual)!=len(spec["components"]) or len({p.get("componentId") for p in actual})!=len(actual):
        raise ValueError("Worker component count mismatch")
    def near(a,b):
        return isinstance(a,list) and len(a)==len(b) and all(type(x) in (int,float) and math.isfinite(x) and abs(x-y)<1e-5 for x,y in zip(a,b))
    for want in spec["components"]:
        got=next((p for p in actual if p.get("componentId")==want["componentId"]),{})
        if not near(got.get("size"),want["size"]) or not near(got.get("location"),want["location"]):
            raise ValueError("Worker geometry differs from mm authority")
    rows=observed.get("artwork",[])
    if len(rows)!=3:
        raise ValueError("Worker artwork count mismatch")
    for want,got in zip(package["placements"],rows):
        for key in ("componentId","objectName","placementHash","finalUvHash","artworkHash","surfaceHash"):
            if got.get(key)!=want[key]:
                raise ValueError("Worker artwork lineage mismatch: "+key)
        loops=got.get("observedCorners",[])
        if len(loops)!=4 or not all(near(a,b) for a,b in zip(loops,want["finalSampling"])):
            raise ValueError("Worker final UV mismatch")
        if got.get("packedImageSha256")!=want["source"]["fileSha256"]:
            raise ValueError("Worker texture source mismatch")
