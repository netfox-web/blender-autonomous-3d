"""Frame manifest and sealed pre-worker authority on existing Platform/DAM ports."""
from __future__ import annotations
import copy
import json
import re
from dataclasses import asdict
from pathlib import Path

from fox3d.artwork import decode_png_rgb
from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.product_truth import derive_canonical_expected_identity, validate_product_truth_render_pack, validate_frozen_authority_semantics
from fox3d.video_recipe import ROLES, expected_objects, make_recipe, validate_recipe, frame_plan, close_numbers, articulation_gate, integer,finite, scene_context_objects


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False, default=str)+"\n", encoding="utf-8")


def safe_id(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) or value in (".", ".."):
        raise ValueError("unsafe_identity")
    return value


def freeze_authority(plat, source, *, sku, product_version, instruction_sha, code_sha, generation_id,
                     kind="HERO_ORBIT_8S", fps=12, width=128, height=128, allow_mock=False,
                     code_tree_clean=False,development_only=True):
    if type(code_tree_clean) is not bool or type(development_only) is not bool:raise ValueError("strict_evidence_flags")
    for v in (sku, generation_id): safe_id(v)
    integer(product_version, 1, 1000000, "product_version")
    for v in (instruction_sha, code_sha):
        if type(v) is not str or not re.fullmatch(r"[0-9a-f]{40}", v): raise ValueError("commit_identity")
    frozen = copy.deepcopy(source["frozenAuthorityContext"])
    if validate_frozen_authority_semantics(frozen): raise ValueError("source_frozen_semantics")
    canonical = derive_canonical_expected_identity(plat, tenant_id=frozen["tenant_id"], placement=frozen["placement"],
                engineering=frozen["engineering"], camera=frozen["camera"], scene=frozen["scene"], view_recipes=frozen["view_recipes"], strict=True)
    if canonical.get("canonicalAuthorityValid") is not True: raise ValueError("source_canonical_authority")
    pack = source["pack"]
    if product_version != pack.get("version") or frozen["engineering"].get("tenantId") != frozen["tenant_id"]:
        raise ValueError("source_tenant_or_product_version")
    failures = validate_product_truth_render_pack(pack, expected_identity=canonical, plat=plat)
    if failures: raise ValueError("source_pack:"+",".join(failures))
    mock = pack.get("usedMock") is not False or pack.get("productTruthRenderPackReady") is not True
    if mock and not allow_mock: raise ValueError("BLOCKED_REAL_PRODUCT_TRUTH")
    engineering = frozen["engineering"]
    recipe = make_recipe(kind, engineering, fps=fps, width=width, height=height,artwork_object=canonical["objectName"])
    tenant = safe_id(frozen["tenant_id"])
    identity = {k: canonical[k] for k in ("engineeringHash", "artworkHash", "artworkId", "artworkSha256", "placementHash", "placementId", "finalUvHash", "surfaceHash", "componentId", "objectName")}
    identity.update(tenantId=tenant, sku=sku, productId=engineering["productId"], productVersion=product_version,
                    artworkVersion=plat.artwork.artworks[canonical["artworkId"]].get("version", 1),
                    productTruthHash=stable_hash(pack), productTruthGeneration=pack["renderPackId"],
                    cameraRecipeHash=recipe["cameraRecipeHash"], sceneRecipeHash=recipe["sceneRecipeHash"], videoRecipeHash=recipe["videoRecipeHash"])
    payload = plat.artwork.blender_job_payload(tenant_id=tenant, engineering=engineering, placement_ids=[canonical["placementId"]])
    authority = {"instructionSha": instruction_sha, "codeSha": code_sha, "generationId": generation_id,
                 "sourceFrozen": frozen, "sourcePack": copy.deepcopy(pack), "identity": identity,
                 "engineering": engineering, "recipe": recipe, "objects": expected_objects(engineering),
                 "payload": payload, "sourceUsedMock": mock, "articulationAuthority": None}
    authority.update(codeTreeClean=code_tree_clean,developmentOnly=development_only)
    authority["authorityHash"] = stable_hash(authority)
    return authority


def check_authority(a, seal):
    if a.get("authorityHash") != seal or stable_hash({k:v for k,v in a.items() if k != "authorityHash"}) != seal:
        raise ValueError("authority_seal")
    validate_recipe(a["recipe"], a["engineering"])
    if a["recipe"]["recipeId"]=="ARTWORK_DETAIL_6S" and a["recipe"]["detailObject"]!=a["identity"]["objectName"]:raise ValueError("detail_wrong_artwork_component")
    if a["objects"] != expected_objects(a["engineering"]): raise ValueError("geometry_authority")
    if stable_hash(a["sourcePack"]) != a["identity"]["productTruthHash"]: raise ValueError("product_truth_hash")
    for key in ("cameraRecipeHash", "sceneRecipeHash", "videoRecipeHash"):
        if a["identity"][key] != a["recipe"][key]: raise ValueError("identity_recipe")
    articulation_gate(a["recipe"], a)


def validate_observation(a, observation, *, job_id):
    errors = []; r = a["recipe"]
    if observation.get("identity") != a["identity"]: errors.append("worker_identity")
    if observation.get("authorityHash") != a["authorityHash"]: errors.append("worker_authority")
    if observation.get("blenderJobId") != job_id: errors.append("worker_job")
    if observation.get("usedMock") is False:
        camera=observation.get("cameraObserved",{});scene=observation.get("sceneObserved",{})
        for key,expected in {"lens":r["camera"]["focalLengthMm"],"sensor":r["camera"]["sensorWidthMm"],"clipStart":r["camera"]["clipStart"],
                             "clipEnd":r["camera"]["clipEnd"],"width":r["width"],"height":r["height"],"fps":r["fps"]}.items():
            if not close_numbers(camera.get(key),expected):errors.append("camera_optics")
        if camera.get("sensorFit")!="HORIZONTAL":errors.append("camera_sensor_fit")
        for key in ("engine","samples","transparent","colorManagement"):
            if type(scene.get(key)) is not type(r["scene"][key]) or scene[key]!=r["scene"][key]:errors.append("scene_configuration")
        for key in ("worldColor","worldStrength","exposure"):
            if not close_numbers(scene.get(key),r["scene"][key]):errors.append("scene_world")
        lights=scene.get("lights",[])
        if len(lights)!=len(r["scene"]["lights"]):errors.append("scene_lights")
        for actual,expected in zip(lights,r["scene"]["lights"]):
            if any(actual.get(k)!=expected[k] for k in ("name","type")):errors.append("scene_lights")
            if any(not close_numbers(actual.get(k),expected[k]) for k in ("location","energy","color")):errors.append("scene_lights")
    frames = observation.get("frames", [])
    if type(frames) is not list or len(frames) != r["frameCount"]: return errors+["frame_count"]
    applied = observation.get("appliedPlacements", [])
    if len(applied) != 1: errors.append("artwork_application")
    else:
        for k in ("objectName", "componentId", "artworkHash", "placementHash", "finalUvHash", "artworkSha256"):
            if applied[0].get(k) != a["identity"][k]: errors.append("applied_"+k)
    for i, frame in enumerate(frames):
        p = frame_plan(r, i)
        if type(frame.get("index")) is not int or frame["index"] != i: errors.append("frame_order")
        if not close_numbers(frame.get("timestamp"), p["timestamp"], 1e-9): errors.append("timestamp")
        for key in ("cameraMatrix", "intrinsics", "productMatrix"):
            if not close_numbers(frame.get(key), p[key]): errors.append(key)
        if frame.get("articulation") != []: errors.append("articulation")
        if frame.get("identity") != a["identity"] or frame.get("blenderJobId") != job_id: errors.append("frame_identity_job")
        if observation.get("usedMock") is False and any(not frame.get("artifacts",{}).get(role,{}).get("decoded") for role in ("depth","normal")):
            errors.append("missing_decoded_EXR")
        objects = frame.get("objects", {})
        expected_context=scene_context_objects(r)
        context=frame.get('sceneContextObjects',{})
        if context.keys()!=expected_context.keys():errors.append('scene_context_objects')
        for name,expected in expected_context.items():
            actual=context.get(name,{})
            if any(not close_numbers(actual.get(k),expected[k]) for k in ('matrix','dimensions')):errors.append('scene_context_geometry')
            if any(type(actual.get(k)) is not type(expected[k]) or actual[k]!=expected[k] for k in ('vertices','polygons','passIndex','materialIndices')):errors.append('scene_context_mask_assignment')
        if objects.keys() != a["objects"].keys(): errors.append("object_topology")
        for name, expected in a["objects"].items():
            obj = objects.get(name, {})
            for key in ("matrix", "dimensions"):
                if not close_numbers(obj.get(key), expected[key]): errors.append("object_"+key)
            for key in ("vertices", "polygons"):
                if type(obj.get(key)) is not int or obj[key] != expected[key]: errors.append("object_topology")
    reopened = observation.get("reopened", [])
    want = sorted({0, r["frameCount"]//2, r["frameCount"]-1})
    if [v.get("index") for v in reopened] != want: errors.append("reopen_frames")
    else:
        for item in reopened:
            if not close_numbers(item.get("cameraMatrix"), frame_plan(r,item["index"])["cameraMatrix"]): errors.append("reopen_camera")
            if item.get("objects") != frames[item["index"]].get("objects"): errors.append("reopen_objects")
            if item.get('sceneContextObjects',{})!=frames[item['index']].get('sceneContextObjects',{}):errors.append('reopen_scene_context')
    return sorted(set(errors))


def artifact_bytes(record):
    path = Path(record["path"])
    if path.is_symlink() or not path.is_file(): raise ValueError("artifact_path")
    data = path.read_bytes()
    if type(record.get("size")) is not int or len(data) != record["size"] or sha256_bytes(data) != record["sha256"]:
        raise ValueError("artifact_bytes")
    return data


def check_frame_pixels(frame, recipe):
    art = frame["artifacts"]; masks = {}
    if set(art) != set(ROLES): raise ValueError("artifact_roles")
    if len({v["path"] for v in art.values()}) != len(ROLES): raise ValueError("artifact_alias")
    for role, ext in ROLES.items():
        data = artifact_bytes(art[role])
        if ext == "exr":
            if data[:4] != b'v/1\x01': raise ValueError("exr_header")
            decoded=art[role].get("decoded")
            if decoded:
                if decoded.get("finite") is not True or (decoded.get("width"),decoded.get("height"))!=(recipe["width"],recipe["height"]):raise ValueError("exr_decoded_shape")
                lo,hi=finite(decoded.get("min")),finite(decoded.get("max"))
                if lo>hi or role=="normal" and (lo < -1.001 or hi > 1.001) or role=="depth" and lo<0:raise ValueError("exr_encoding_range")
        else:
            w,h,rgb = decode_png_rgb(data)
            if (w,h) != (recipe["width"],recipe["height"]): raise ValueError("frame_resolution")
            if role.endswith("mask"): masks[role] = [max(rgb[j:j+3])>127 for j in range(0,len(rgb),3)]
    prod, artmask = masks["product_mask"], masks["artwork_mask"]
    if not any(prod) or not any(artmask) or prod == artmask: raise ValueError("mask_empty_or_alias")
    if any(v and not p for v,p in zip(artmask,prod)): raise ValueError("artwork_outside_product")
    if recipe['scene']['room']:
        context=frame['sceneContextMask']
        if context['path'] in {v['path'] for v in frame['artifacts'].values()}:raise ValueError('context_mask_alias')
        w,h,rgb=decode_png_rgb(artifact_bytes(context))
        if (w,h)!=(recipe['width'],recipe['height']):raise ValueError('context_resolution')
        mask=[max(rgb[j:j+3])>127 for j in range(0,len(rgb),3)]
        if not any(mask) or any(c and (p or a) for c,p,a in zip(mask,prod,artmask)):
            raise ValueError('room_pixels_enter_product_mask')
    elif 'sceneContextMask' in frame:raise ValueError('unexpected_scene_context')


def frame_artifacts(frame):
    return {**frame['artifacts'],**({'context_mask':frame['sceneContextMask']} if 'sceneContextMask' in frame else {})}


def validate_manifest(manifest, *, authority, authority_seal, receipt, receipt_seal, dam=None):
    try:
        check_authority(authority, authority_seal)
        if stable_hash(receipt) != receipt_seal: raise ValueError("receipt_seal")
        if receipt["authorityHash"] != authority_seal: raise ValueError("receipt_authority")
        expected = {"schema": "VIDEO_GROUND_TRUTH_MANIFEST_V1", "authorityHash": authority_seal,
                    "instructionSha": authority["instructionSha"], "codeSha": authority["codeSha"],
                    "generationId": authority["generationId"], "identity": authority["identity"],
                    "recipe": authority["recipe"], "receiptHash": receipt_seal, **receipt["manifestBody"]}
        expected["manifestHash"] = stable_hash(expected)
        if stable_hash(manifest) != stable_hash(expected): raise ValueError("manifest_receipt_or_identity")
        for flag in ("doorOpenReal","visionQaReady","liveProviderReady","globalProductionReady"):
            if manifest.get(flag) is not False:raise ValueError("unsupported_readiness_promotion")
        if type(manifest.get("videoGroundTruthReady")) is not bool or type(manifest.get("usedMock")) is not bool:raise ValueError("strict_readiness_bool")
        errors = validate_observation(authority, receipt["observation"], job_id=receipt["jobId"])
        if errors: raise ValueError(",".join(errors))
        for frame in manifest["frames"]:
            check_frame_pixels(frame, authority["recipe"])
            for role, rec in frame_artifacts(frame).items():
                ref = rec["dam"]
                kind='video_scene_context' if role=='context_mask' else 'video_ground_truth'
                if ref["tenant_id"] != authority["identity"]["tenantId"] or ref["kind"] != kind: raise ValueError("dam_tenant_kind")
                meta = ref["metadata"]
                if meta != {"jobId": receipt["jobId"], "identity": authority["identity"], "frame": frame["index"], "role": role, "authorityHash": authority_seal}: raise ValueError("dam_lineage")
                if ref["path"] != rec["path"] or ref["sha256"] != rec["sha256"]: raise ValueError("dam_path_hash")
                if dam is not None and asdict(dam.get(ref["asset_id"], tenant_id=ref["tenant_id"])) != ref: raise ValueError("dam_index")
        for rec in receipt["supportArtifacts"].values(): artifact_bytes(rec)
        if manifest["videoGroundTruthReady"] and (authority["sourceUsedMock"] or not authority["codeTreeClean"] or authority["developmentOnly"] or receipt["observation"]["usedMock"] is not False or receipt["observation"]["realBlender"] is not True): raise ValueError("mock_or_development_promotion")
        return []
    except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
        return [str(exc)]


def video_job_payload(authority):
    a=authority;payload=copy.deepcopy(a['payload'])
    payload.update(videoAuthority=a,render={'width':a['recipe']['width'],'height':a['recipe']['height'],
                   'samples':4,'device':'OPTIX','videoRecipeHash':a['recipe']['videoRecipeHash'],
                   'videoAuthorityHash':a['authorityHash']},timeoutSeconds=14400,
                   recipeId=a['recipe']['recipeId'],idempotencyKey=a['generationId'],mode='VIDEO_GROUND_TRUTH',jobId=new_id())
    return payload


def execute_sequence(plat, authority, directory):
    a = copy.deepcopy(authority); seal = a["authorityHash"]; check_authority(a, seal)
    if plat.mock_blender: raise ValueError("BLOCKED_REAL_BLENDER_SEQUENCE")
    directory = Path(directory); directory.mkdir(parents=True,exist_ok=True)
    if (directory/"authority.json").exists(): raise ValueError("generation_already_exists")
    write_json(directory/"authority.json", a)
    payload = video_job_payload(a)
    job = plat.submit_job(payload); job_id = job["jobId"]
    write_json(directory/"submitted-job.json",job)
    old = plat.runtime.script_path
    plat.runtime.script_path = Path(__file__).resolve().parents[2]/"scripts/blender_video_job.py"
    try: done = plat.execute_job(job, timeout_seconds=14400)
    finally: plat.runtime.script_path = old
    write_json(directory/"completed-job.json",done)
    if done.get("usedMock") is not False or done.get("status") not in ("completed","succeeded") or done.get("cacheHit"):
        raise ValueError("sequence_job_failed:"+str(done.get("error")))
    obs = json.loads(Path(done["outputs"]["worker_sequence.json"]).read_text(encoding="utf-8"))
    errors = validate_observation(a,obs,job_id=job_id)
    if errors: raise ValueError("worker_validation:"+",".join(errors))
    frames = copy.deepcopy(obs["frames"])
    worker_root = (plat.runtime.work_dir/job_id).resolve()
    for frame in frames:
        check_frame_pixels(frame,a["recipe"])
        for role, rec in frame_artifacts(frame).items():
            ext='png' if role=='context_mask' else ROLES[role]
            expected = worker_root/"frames"/f'{frame["index"]:04d}'/f'{role}.{ext}'
            if Path(rec["path"]).resolve() != expected: raise ValueError("worker_artifact_path")
            data = artifact_bytes(rec)
            kind='video_scene_context' if role=='context_mask' else 'video_ground_truth'
            obj = plat.dam.put(tenant_id=a["identity"]["tenantId"],kind=kind,name=f'{frame["index"]:04d}_{role}.{ext}', data=data,
                              metadata={"jobId":job_id,"identity":a["identity"],"frame":frame["index"],"role":role,"authorityHash":seal})
            rec.update(path=obj.path,dam=asdict(obj))
    supports = {}
    for name in ("sequence.blend","worker_sequence.json"):
        asset=plat.dam.get(done["output"]["files"][name],tenant_id=a["identity"]["tenantId"])
        if asset.metadata.get("jobId")!=job_id:raise ValueError("support_job_lineage")
        path=Path(asset.path);data=path.read_bytes()
        supports[name]={"path":str(path),"sha256":sha256_bytes(data),"size":len(data),"dam":asdict(asset)}
    ready = not a["sourceUsedMock"] and a["codeTreeClean"] and not a["developmentOnly"] and obs["usedMock"] is False and obs["realBlender"] is True
    body={"frames":frames,"blenderJobId":job_id,"blenderVersion":obs["blenderVersion"],"device":obs["device"],
          "usedMock":obs["usedMock"],"videoGroundTruthReady":ready,"heroOrbitReal":ready and a["recipe"]["recipeId"]=="HERO_ORBIT_8S",
          "doorOpenReal":False,"visionQaReady":False,"liveProviderReady":False,"globalProductionReady":False}
    receipt={"authorityHash":seal,"jobId":job_id,"observation":obs,"supportArtifacts":supports,"manifestBody":body}
    receipt_seal=stable_hash(receipt)
    manifest={"schema":"VIDEO_GROUND_TRUTH_MANIFEST_V1","authorityHash":seal,"instructionSha":a["instructionSha"],"codeSha":a["codeSha"],
              "generationId":a["generationId"],"identity":a["identity"],"recipe":a["recipe"],"receiptHash":receipt_seal,**body}
    manifest["manifestHash"]=stable_hash(manifest)
    errors=validate_manifest(manifest,authority=a,authority_seal=seal,receipt=receipt,receipt_seal=receipt_seal,dam=plat.dam)
    if errors: raise ValueError("manifest_validation:"+",".join(errors))
    write_json(directory/"receipt.json",receipt);write_json(directory/"VIDEO_GROUND_TRUTH_MANIFEST.json",manifest)
    return {"manifest":manifest,"authoritySeal":seal,"receiptSeal":receipt_seal,"directory":str(directory)}


def reopen_sequence(directory, *, authority_seal, receipt_seal):
    directory=Path(directory)
    load=lambda name:json.loads((directory/name).read_text(encoding="utf-8"))
    m=load("VIDEO_GROUND_TRUTH_MANIFEST.json")
    errors=validate_manifest(m,authority=load("authority.json"),authority_seal=authority_seal,receipt=load("receipt.json"),receipt_seal=receipt_seal)
    if errors: raise ValueError("persisted_sequence:"+",".join(errors))
    return m
