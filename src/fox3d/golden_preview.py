"""Golden product adapter to the existing Recipe lifecycle, Blender and DAM."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from fox3d.golden_product import (SKUS, VERSIONS, build_golden, package_plan,
    validate_package, materialize_package, validate_worker_observation)
from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.recipe_3d import atomic_json, input_hash, read_json, validate_outputs
from fox3d.artwork import decode_png_rgb, crop_rgb

OUTPUTS={"png":"beauty.png","front":"front-closed.png","detail":"door-detail.png",
         "glb":"model.glb","blend":"model.blend","geometry":"geometry.json",
         "observation":"golden-observation.json","manifest":"manifest.json"}
DOWNLOADS={**OUTPUTS,**{f"trim{i}":f"door_{i}-production-trim.png" for i in range(1,4)}}


def folder_for(root,tenant,sku):
    return Path(root)/"golden-previews"/stable_hash({"tenant":tenant,"sku":sku})[:24]


def plan(sku,version):
    golden=build_golden()
    package=package_plan(sku,version,golden)
    draft={"sku":sku,"version":version,"packageHash":package.get("packageHash"),"engineeringHash":golden["engineeringHash"]}
    return {"golden":golden,"package":package,"draft":draft,"planHash":input_hash(draft),"ready":package["ready"]}


def validate_generation(folder,sku,version):
    manifest=read_json(folder/"manifest.json")
    if not manifest:
        raise ValueError("Missing Golden manifest")
    expected=plan(sku,version)
    if manifest.get("sku")!=sku or manifest.get("version")!=version or manifest.get("engineeringHash")!=expected["golden"]["engineeringHash"]:
        raise ValueError("Manifest identity mismatch")
    validate_package(manifest["package"],sku=sku,version=version,golden=expected["golden"])
    if manifest.get("spec")!=expected["golden"]["spec"]:
        raise ValueError("Generation geometry authority mismatch")
    if manifest.get("truth")!=expected["golden"]["truth"] or manifest.get("manufacturing")!=expected["golden"]["manufacturing"] or manifest.get("artworkTruth")!="FIXTURE":
        raise ValueError("Truth classification mismatch")
    if manifest.get("renderInfo",{}).get("realBlender") is not True or manifest.get("renderInfo",{}).get("usedMock") is not False:
        raise ValueError("REAL render evidence required")
    if manifest.get("views")!={"HERO_45":"beauty.png","FRONT_CLOSED":"front-closed.png","DOOR_DETAIL":"door-detail.png","FRONT_OPEN":"BLOCKED"}:
        raise ValueError("Camera view scope mismatch")
    required={"beauty.png","front-closed.png","door-detail.png","model.glb","model.blend","geometry.json","golden-observation.json"}
    required.update(src["name"] for src in manifest["package"]["sources"])
    required.update(f"door_{i}-production-trim.png" for i in range(1,4))
    if set(manifest.get("files",{}))!=required:
        raise ValueError("Golden artifact set mismatch")
    for name,digest in manifest["files"].items():
        if Path(name).name!=name or name not in required:
            raise ValueError("Unsafe artifact name")
        raw=(folder/name).read_bytes()
        if sha256_bytes(raw)!=digest.get("sha256") or len(raw)!=digest.get("sizeBytes"):
            raise ValueError("Golden artifact checksum mismatch: "+name)
    validate_outputs(folder,manifest["spec"])
    observation=read_json(folder/"golden-observation.json")
    validate_worker_observation(observation,manifest["package"],manifest["spec"])
    if not observation.get("jobId") or observation.get("jobId")!=manifest.get("jobId"):
        raise ValueError("Worker job identity mismatch")
    # Independently derive every trim from the decoded immutable source image.
    production=manifest.get("production",[])
    if len(production)!=3:
        raise ValueError("Production crop count mismatch")
    for p,record in zip(manifest["package"]["placements"],production):
        source=folder/p["source"]["name"]
        if sha256_bytes(source.read_bytes())!=p["source"]["fileSha256"]:
            raise ValueError("Artwork source changed")
        sw,sh,rgb=decode_png_rgb(source.read_bytes())
        c=p["cropPx"]
        crop_path=folder/(p["componentId"]+"-production-trim.png")
        cw,ch,actual=decode_png_rgb(crop_path.read_bytes())
        if (cw,ch)!=(c["width"],c["height"]) or actual!=crop_rgb(rgb,sw,sh,c["x"],c["y"],c["width"],c["height"]):
            raise ValueError("Production crop differs from UV source region")
        expected_record={"componentId":p["componentId"],"cropMm":p["cropMm"],"cropPx":c,
            "placementHash":p["placementHash"],"finalUvHash":p["finalUvHash"],
            "productionArtworkHash":sha256_bytes(crop_path.read_bytes()),"file":crop_path.name}
        if record!=expected_record:
            raise ValueError("Production crop lineage mismatch")
    for name in ("front-closed.png","door-detail.png"):
        w,h,_=decode_png_rgb((folder/name).read_bytes())
        if (w,h)!=(800,800):
            raise ValueError("Missing camera view")
    return manifest


def status(root,tenant,sku,*,current_draft=None):
    base=folder_for(root,tenant,sku)
    meta=read_json(base/"meta.json")
    state=read_json(base/"state.json")
    generated=False
    manifest={}
    if meta:
        try:
            gid=meta["generationId"]
            if not re.fullmatch(r"[a-f0-9-]{36}",gid) or meta["sku"]!=sku or meta["tenantId"]!=tenant:
                raise ValueError("Generation identity mismatch")
            folder=base/"generations"/gid
            if sha256_bytes((folder/"manifest.json").read_bytes())!=meta["manifestSha256"]:
                raise ValueError("Manifest checksum mismatch")
            manifest=validate_generation(folder,sku,meta["version"])
            generated=True
        except (OSError,ValueError,KeyError,TypeError) as exc:
            if state.get("state") not in {"queued","running"}:
                state.update(state="failed",error="成果驗證失敗，請重新生成："+str(exc))
    return {"sku":sku,"generated":generated,"generationId":meta.get("generationId"),"version":meta.get("version"),
            "stale":bool(meta and current_draft and meta.get("inputHash")!=input_hash(current_draft)),
            "state":state.get("state","idle"),"taskId":state.get("taskId"),"error":state.get("error"),
            "progress":state.get("progress",0),"renderInfo":meta.get("renderInfo",{}),
            "manifest":manifest if generated else {},"engineeringReady":False,"productionReady":False}


def generate(platform,tenant,sku,draft,*,revision=0,generation_id=None,on_job=None,cancel_flag=None):
    def check_cancelled():
        if cancel_flag is not None and cancel_flag.is_set():
            raise ValueError("使用者已取消生成")
    check_cancelled()
    if platform.mock_blender or not platform.runtime.available():
        raise ValueError("找不到真實 Blender；不使用 mock 代替")
    selected=plan(sku,draft["version"])
    if not selected["ready"] or draft!=selected["draft"]:
        raise ValueError("圖稿待補或設定已變更，請重新確認")
    golden,package=selected["golden"],selected["package"]
    gid=generation_id or new_id()
    folder=folder_for(platform.root,tenant,sku)/"generations"/gid
    folder.mkdir(parents=True,exist_ok=False)
    placements,production=materialize_package(folder,package,golden)
    check_cancelled()
    views=[{"id":"FRONT_CLOSED","filename":"front-closed.png","location":[0.,-2.4,.45],"lookAt":[0.,0.,.45],"focalLengthMm":70.},
           {"id":"DOOR_DETAIL","filename":"door-detail.png","location":[.12,-1.0,.74],"lookAt":[0.,-.1475,.74],"focalLengthMm":65.}]
    job=platform.submit_job({"tenantId":tenant,"jobType":"PARAMETRIC_3D","mode":"CABINET_PREVIEW",
        "assetHash":stable_hash({"packageHash":package["packageHash"],"workerContract":"golden-mm-uv-v1","views":views}),
        "engineering":golden["spec"],"recipePreview":True,"goldenRecipe":True,
        "goldenIdentity":{"sku":sku,"packageHash":package["packageHash"]},"artworkPlacements":placements,
        "camera":{"location":[1.35,-1.65,1.1],"lookAt":[0.,0.,.45],"focalLengthMm":55.},
        "productTruthViews":views,"render":{"device":"OPTIX" if platform.probe and platform.probe.optix else "CPU","width":800,"height":800,"samples":32},
        "exportGlb":True,"exportBlend":True,"maxAttempts":1,"timeoutSeconds":900})
    if on_job:
        on_job(job)
    done=platform.execute_job(job,cancel_flag=cancel_flag)
    check_cancelled()
    if done.get("status") not in {"succeeded","completed"} or done.get("realBlender") is not True or done.get("usedMock") is not False:
        raise ValueError("Blender 生成未完成："+str(done.get("error") or done.get("status")))
    output=done.get("output") or {}
    assets=output.get("files") or {}
    for name in OUTPUTS.values():
        if name=="manifest.json":
            continue
        if name not in assets:
            raise ValueError("Missing Blender artifact "+name)
        asset=platform.dam.get(assets[name],tenant_id=tenant)
        shutil.copy2(asset.path,folder/name)
    files={p.name:{"sha256":sha256_bytes(p.read_bytes()),"sizeBytes":p.stat().st_size} for p in folder.iterdir() if p.is_file()}
    info={k:output.get(k,done.get(k)) for k in ("realBlender","usedMock","realOptix","device","samples","blenderVersion")}
    observed=read_json(folder/"golden-observation.json")
    manifest={"generationId":gid,"sku":sku,"version":draft["version"],"engineeringHash":golden["engineeringHash"],
        "package":package,"production":production,"spec":golden["spec"],"files":files,"jobId":observed.get("jobId"),
        "requestedJobId":job["jobId"],"cacheHit":done.get("cacheHit",False),
        "views":{"HERO_45":"beauty.png","FRONT_CLOSED":"front-closed.png","DOOR_DETAIL":"door-detail.png","FRONT_OPEN":"BLOCKED"},
        "renderInfo":info,"truth":golden["truth"],"artworkTruth":"FIXTURE","manufacturing":golden["manufacturing"]}
    atomic_json(folder/"manifest.json",manifest)
    validate_generation(folder,sku,draft["version"])
    check_cancelled()
    meta={"generationId":gid,"sku":sku,"tenantId":tenant,"version":draft["version"],"inputHash":input_hash(draft),
          "manifestSha256":sha256_bytes((folder/"manifest.json").read_bytes()),"renderInfo":info,"updatedAt":str(utcnow())}
    atomic_json(folder/"meta.json",meta)
    atomic_json(folder.parent.parent/"meta.json",meta)
    return status(platform.root,tenant,sku,current_draft=draft)
