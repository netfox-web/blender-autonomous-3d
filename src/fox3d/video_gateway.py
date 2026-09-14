"""Narrow provider packages and deterministic candidate QA; no live provider claim."""
from __future__ import annotations
import copy
import json
from dataclasses import asdict
from pathlib import Path

from fox3d.artwork import decode_png_rgb
from fox3d.ids import stable_hash
from fox3d.storelock import FileLock
from fox3d.video_ground_truth import artifact_bytes, reopen_sequence, safe_id, write_json
from fox3d.video_recipe import close_numbers, integer


class VideoAdapter:
    provider = "FUTURE_PROVIDER"

    def request_package(self, directory, *, authority_seal, receipt_seal, style_brief=""):
        m = reopen_sequence(directory,authority_seal=authority_seal,receipt_seal=receipt_seal)
        if type(style_brief) is not str or len(style_brief)>8000: raise ValueError("style_brief")
        return {"provider":self.provider,"status":"BLOCKED_PROVIDER_RUNTIME","liveProviderReady":False,
                "liveH3MaxProviderReady":False,"liveLtx25ProviderReady":False,"manifestHash":m["manifestHash"],
                "identity":m["identity"],"duration":m["recipe"]["duration"],"fps":m["recipe"]["fps"],
                "frames":[{"index":f["index"],"timestamp":f["timestamp"],"artifacts":f["artifacts"],
                           "cameraMatrix":f["cameraMatrix"],"intrinsics":f["intrinsics"]} for f in m["frames"]],
                "styleBrief":style_brief,"constraints":{"productLocked":True,"geometryEditable":False,
                "artworkEditable":False,"manufacturingAuthority":False},"generativePixelsAreProductTruth":False}

    def submit(self, package):
        return {"status":"BLOCKED_PROVIDER_RUNTIME","provider":self.provider,"outputArtifacts":[],
                "liveProviderReady":False,"usedMock":False,"networkExecuted":False}


class H3MaxAdapter(VideoAdapter):
    provider = "H3_MAX"


class LTX25Adapter(VideoAdapter):
    provider = "LTX_2_5"


def _pixels(record):
    return decode_png_rgb(artifact_bytes(record))


def _mask(rgb):
    return [max(rgb[j:j+3])>127 for j in range(0,len(rgb),3)]


def _iou(a,b):
    union=sum(x or y for x,y in zip(a,b))
    return sum(x and y for x,y in zip(a,b))/union if union else 0.


def _bounds(mask,w):
    points=[(i%w,i//w) for i,v in enumerate(mask) if v]
    if not points: raise ValueError("empty_candidate_mask")
    return [min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)]


def _edges(rgb,mask,w):
    values=[sum(rgb[j:j+3])/3 for j in range(0,len(rgb),3)]
    return [bool(mask[i] and i%w and mask[i-1] and abs(v-values[i-1])>22) for i,v in enumerate(values)]


def qa_candidate(manifest,candidate):
    metrics=[];errors=[]
    try:
        if candidate.get("liveProviderReady") is not False or candidate.get("visionQaReady") is not False or candidate.get("usedMock") is not True:
            raise ValueError("unverified_provider_or_vision_promotion")
        if candidate.get("manifestHash")!=manifest["manifestHash"] or candidate.get("identity")!=manifest["identity"]:
            raise ValueError("candidate_identity")
        frames=candidate["frames"]
        if len(frames)!=len(manifest["frames"]):raise ValueError("candidate_frame_count")
        previous=None
        for truth,frame in zip(manifest["frames"],frames):
            if type(frame.get("index")) is not int or frame["index"]!=truth["index"]:raise ValueError("candidate_frame_order")
            if not close_numbers(frame.get("timestamp"),truth["timestamp"],1e-9):raise ValueError("candidate_timestamp")
            if not close_numbers(frame.get("cameraMatrix"),truth["cameraMatrix"]):raise ValueError("candidate_camera")
            if frame.get("objects")!=truth["objects"]:raise ValueError("candidate_component_metadata")
            refs=truth["artifacts"];got=frame["artifacts"]
            if set(got)!={"beauty","product_mask","artwork_mask"}:raise ValueError("candidate_artifact_roles")
            decoded={k:_pixels(got[k]) for k in ("beauty","product_mask","artwork_mask")}
            baseline={k:_pixels(refs[k]) for k in decoded}
            w,h,_=baseline["beauty"]
            if any(v[:2]!=(w,h) for v in decoded.values()):raise ValueError("candidate_resolution")
            pm,am=(_mask(decoded[k][2]) for k in ("product_mask","artwork_mask"))
            pt,at=(_mask(baseline[k][2]) for k in ("product_mask","artwork_mask"))
            if pm==am or any(a and not p for a,p in zip(am,pm)):raise ValueError("candidate_mask_alias_or_outside")
            pb,tb=_bounds(pm,w),_bounds(pt,w)
            drift=max(abs(x-y) for x,y in zip(pb,tb))/max(w,h)
            ca,ta=decoded["beauty"][2],baseline["beauty"][2]
            artdiff=sum(abs(ca[i*3+c]-ta[i*3+c]) for i,on in enumerate(at) if on for c in range(3))/(max(1,sum(at))*3*255)
            edge_a,edge_b=_edges(ca,pm,w),_edges(ta,pt,w)
            # Panel/door edge similarity is a pixel proxy, not inferred engineering topology.
            topology=1-sum(x!=y for x,y in zip(edge_a,edge_b))/max(1,sum(pt))
            delta=sum((sum(ca[i*3:i*3+3])-sum(ta[i*3:i*3+3]))/765 for i,on in enumerate(pt) if on)/max(1,sum(pt))
            flicker=abs(delta-previous) if previous is not None else 0.;previous=delta
            metrics.append({"frame":frame["index"],"silhouetteIoU":_iou(pm,pt),"artworkIoU":_iou(am,at),
                            "boundsDrift":drift,"artworkPixelDifference":artdiff,"panelEdgeAgreement":topology,
                            "temporalResidual":flicker})
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
        errors.append(str(exc))
    severe=any(m["silhouetteIoU"]<.65 or m["artworkIoU"]<.65 or m["boundsDrift"]>.15 for m in metrics)
    retry=any(m["silhouetteIoU"]<.95 or m["artworkIoU"]<.95 or m["boundsDrift"]>.025 or
              m["artworkPixelDifference"]>.12 or m["panelEdgeAgreement"]<.9 or m["temporalResidual"]>.08 for m in metrics)
    decision="REJECT" if errors or severe else "RETRY" if retry else "PASS"
    return {"decision":decision,"errors":errors,"metrics":metrics,"visionQaReady":False,
            "truthLabel":"REAL_LOGIC","engineeringAuthority":False,"humanReviewRequired":True,
            "limitations":["Pixel proxies cannot prove hidden topology, physical dimensions or semantic logo fidelity.",
                            "Candidate control images are provider evidence, not independent Vision observations."]}


class VideoCandidateStore:
    def __init__(self,root,dam,*,sequence_directory,authority_seal,receipt_seal):
        self.root=Path(root);self.dam=dam
        self.sequence_directory=sequence_directory;self.authority_seal=authority_seal;self.receipt_seal=receipt_seal

    def _require_manifest(self,manifest):
        verified=reopen_sequence(self.sequence_directory,authority_seal=self.authority_seal,receipt_seal=self.receipt_seal)
        if stable_hash(verified)!=stable_hash(manifest):raise ValueError("untrusted_ground_truth_manifest")

    def _load_attempt(self,path):
        saved=json.loads(path.read_text(encoding="utf-8"))
        qa=saved["qaAsset"];data=Path(qa["path"]).read_bytes()
        from fox3d.ids import sha256_bytes
        if sha256_bytes(data)!=qa["sha256"]:raise ValueError("qa_lineage_tampered")
        if {k:v for k,v in saved.items() if k!="qaAsset"}!=json.loads(data):raise ValueError("attempt_tampered")
        for frame in saved["candidate"].get("frames",[]) if not saved["qa"]["errors"] else []:
            for rec in frame["artifacts"].values():
                artifact_bytes(rec)
                if rec.get("dam",{}).get("path")!=rec["path"] or rec["dam"].get("sha256")!=rec["sha256"]:raise ValueError("candidate_dam_reference")
        return saved

    def record(self,manifest,candidate,*,attempt_key,seed,model,provider,config,model_version,max_attempts=3):
        manifest=copy.deepcopy(manifest);candidate=copy.deepcopy(candidate)
        self._require_manifest(manifest)
        safe_id(attempt_key);integer(seed,0,2**32-1,"seed");integer(max_attempts,1,10,"max_attempts")
        safe_id(manifest["identity"]["tenantId"])
        if provider not in ("H3_MAX","LTX_2_5","FUTURE_PROVIDER"):raise ValueError("provider")
        if type(model) is not str or not model:raise ValueError("model")
        if type(model_version) is not str or not model_version:raise ValueError("model_version")
        # Strict JSON refuses NaN/Inf in provider settings; no credentials enter this contract.
        json.dumps(config,allow_nan=False)
        parent=self.root/manifest["identity"]["tenantId"]/manifest["generationId"]
        fingerprint=stable_hash({"candidate":candidate,"seed":seed,"model":model,"modelVersion":model_version,"provider":provider,"config":config})
        with FileLock(parent/"attempts.lock"):
            path=parent/(attempt_key+".json")
            if path.exists():
                saved=self._load_attempt(path)
                if saved["requestHash"]!=fingerprint:raise ValueError("idempotency_conflict")
                return saved
            prior=[json.loads(p.read_text(encoding="utf-8")) for p in parent.glob("*.json")]
            if any(p["qa"]["decision"]=="PASS" for p in prior):raise ValueError("accepted_lineage_immutable")
            if len(prior)>=max_attempts:raise ValueError("retry_limit")
            qa=qa_candidate(manifest,candidate)
            durable=copy.deepcopy(candidate);assets=[]
            if not qa["errors"]:
                for frame in durable["frames"]:
                    for role,rec in frame["artifacts"].items():
                        data=artifact_bytes(rec)
                        obj=self.dam.put(tenant_id=manifest["identity"]["tenantId"],kind="video_provider_candidate",name=f'{attempt_key}_{frame["index"]}_{role}.png',data=data,
                                         metadata={"manifestHash":manifest["manifestHash"],"attemptKey":attempt_key,"role":role,"frame":frame["index"],"usedMock":True})
                        rec.update(path=obj.path,dam=asdict(obj));assets.append(asdict(obj))
            saved={"requestHash":fingerprint,"attemptKey":attempt_key,"attemptNumber":len(prior)+1,
                   "manifestHash":manifest["manifestHash"],"provider":provider,"model":model,"modelVersion":model_version,"seed":seed,"config":config,
                   "candidate":durable,"assets":assets,"qa":qa,"retryReason":qa["errors"] or (["product_lock_proxy_drift"] if qa["decision"]!="PASS" else []),
                   "publishState":"QA_ACCEPTED" if qa["decision"]=="PASS" else "QA_REJECTED" if qa["decision"]=="REJECT" else "RETRY",
                   "usedMock":True,"liveProviderReady":False,"visionQaReady":False,"finalCommerceVideo":False}
            qa_asset=self.dam.put(tenant_id=manifest["identity"]["tenantId"],kind="video_qa_accepted" if qa["decision"]=="PASS" else "video_qa_rejected",name=attempt_key+".json",
                                 data=json.dumps(saved,allow_nan=False).encode(),metadata={"manifestHash":manifest["manifestHash"],"decision":qa["decision"],"attemptKey":attempt_key})
            saved["qaAsset"]=asdict(qa_asset)
            temp=path.with_suffix(".tmp");write_json(temp,saved);temp.replace(path)
            return saved

    def publish(self,manifest,attempt_key,*,final=True):
        manifest=copy.deepcopy(manifest)
        self._require_manifest(manifest)
        safe_id(attempt_key)
        path=self.root/manifest["identity"]["tenantId"]/manifest["generationId"]/(attempt_key+".json")
        saved=self._load_attempt(path);qa=saved["qaAsset"]
        if saved["manifestHash"]!=manifest["manifestHash"] or saved["qa"]["decision"]!="PASS":raise ValueError("rejected_candidate_cannot_publish")
        if qa_candidate(manifest,saved["candidate"])["decision"]!="PASS":raise ValueError("candidate_changed_after_qa")
        if final:raise ValueError("BLOCKED_LIVE_PROVIDER_AND_FINAL_REVIEW")
        return {"state":"QA_ACCEPTED_PREVIEW","asset":qa,"finalCommerceVideo":False,"liveProviderReady":False}
