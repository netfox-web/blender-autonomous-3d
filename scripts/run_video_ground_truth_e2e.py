"""Clean-CODE acceptance. Writes isolated raw evidence, never historical reports."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fox3d.evidence import inspect_repo_lineage
from fox3d.ids import new_id
from fox3d.platform import Platform
from fox3d.product_truth import camera_recipe,scene_recipe,render_product_truth,inspect_instruction_sha
from fox3d.parametric import CabinetEngine
from fox3d.artwork import landmark_grid_rgb
from fox3d.pngutil import write_png
from fox3d.video_ground_truth import freeze_authority,execute_sequence,reopen_sequence,write_json
from fox3d.video_gateway import H3MaxAdapter,LTX25Adapter,VideoCandidateStore
from fox3d.video_recipe import expected_objects


def source_fixture(plat,code_sha):
    """Reuse main CabinetSpec/Artwork/Render Pack with asymmetric synthetic art."""
    tenant='video-reference'
    cab,_=CabinetEngine().create('STORAGE_CABINET',tenant_id=tenant,width=800,height=900,depth=295,doorCount=4)
    # Existing main's explicit size/location route preserves full engineering
    # dimensions. Its legacy implicit cube route uses half-scale meshes.
    # Freeze this synthetic fixture's explicit geometry before hashing/rendering;
    # do not silently change product geometry in the video worker.
    implicit=expected_objects(cab.model_dump(mode='json'))
    for part in cab.components:
        obj=implicit[part['partName']]
        part['size']=[v*2 for v in obj['dimensions']]
        part['location']=[row[3] for row in obj['matrix'][:3]]
    cab.metadata['geometrySource']='SYNTHETIC_EXPLICIT_SIZE_LOCATION_FIXTURE'
    surfaces=plat.artwork.register_surfaces(cab,tenant_id=tenant)
    surface=next(s for s in surfaces if s['componentId'].lower()=='door_3')
    image=Path(plat.root)/'asymmetric-fixture.png';write_png(image,48,32,landmark_grid_rgb())
    art=plat.artwork.register_artwork(tenant_id=tenant,data=image.read_bytes(),name=image.name,source='GENERATED')
    place=plat.artwork.place(tenant_id=tenant,surface_id=surface['surfaceId'],artwork_id=art['artworkId'],engineering_hash=cab.engineering_hash(),product_id=cab.productId)
    camera=camera_recipe(width=128,height=128);scene=scene_recipe(samples=32)
    views={'DOOR_DETAIL':camera_recipe(camera_id='DOOR_DETAIL',location=(.35,-1.5,.95),look_at=(.3,0.,.9),width=128,height=128),
           'ASSEMBLED_FRONT':camera_recipe(camera_id='ASSEMBLED_FRONT',location=(2.6,-4.,1.5),look_at=(1.2,0.,.9),width=128,height=128)}
    frozen={'tenant_id':tenant,'placement':place,'placementId':place['placementId'],'surfaceId':surface['surfaceId'],
            'artworkId':art['artworkId'],'engineering':cab.model_dump(mode='json'),'engineeringHash':cab.engineering_hash(),
            'camera':camera,'scene':scene,'view_recipes':views}
    pack=render_product_truth(plat,tenant_id=tenant,placement=place,engineering=frozen['engineering'],width=128,height=128,evidence_code_commit=code_sha)
    return {'frozenAuthorityContext':frozen,'pack':pack}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--instruction-sha',required=True)
    parser.add_argument('--expected-commit',required=True)
    parser.add_argument('--allow-dirty',action='store_true')
    parser.add_argument('--fps',type=int,default=12)
    args=parser.parse_args()
    if inspect_instruction_sha()!=args.instruction_sha:raise ValueError('wrong_instruction_SHA')
    lineage=inspect_repo_lineage(ROOT,allow_dirty=args.allow_dirty)
    if lineage['evidenceCodeCommit']!=args.expected_commit:raise ValueError('wrong_CODE_SHA')
    gid=new_id();dest=ROOT/'.fox3d-work'/'video-e2e'/gid[:8]
    dest.mkdir(parents=True)
    print(json.dumps({'generationId':gid,'directory':str(dest),'stage':'source_product_truth'}),flush=True)
    plat=Platform(root=dest/'platform',mock_blender=False)
    source=source_fixture(plat,args.expected_commit)
    write_json(dest/'source.json',source)
    a=freeze_authority(plat,source,sku='VIDEO-REFERENCE-CABINET',product_version=1,
                       instruction_sha=args.instruction_sha,code_sha=args.expected_commit,generation_id=gid,fps=args.fps,
                       code_tree_clean=lineage['workingTreeClean'],development_only=args.allow_dirty)
    print(json.dumps({'stage':'real_video','frameCount':a['recipe']['frameCount']}),flush=True)
    result=execute_sequence(plat,a,dest/'sequence')
    m=reopen_sequence(dest/'sequence',authority_seal=result['authoritySeal'],receipt_seal=result['receiptSeal'])
    import copy
    for adapter in (H3MaxAdapter(),LTX25Adapter()):
        write_json(dest/(adapter.provider+'-request.json'),adapter.request_package(dest/'sequence',authority_seal=result['authoritySeal'],receipt_seal=result['receiptSeal']))
    candidate={'manifestHash':m['manifestHash'],'identity':copy.deepcopy(m['identity']),'frames':copy.deepcopy(m['frames']),
               'usedMock':True,'liveProviderReady':False,'visionQaReady':False}
    for frame in candidate['frames']:
        frame['artifacts']={k:v for k,v in frame['artifacts'].items() if k in ('beauty','product_mask','artwork_mask')}
    store=VideoCandidateStore(dest/'candidates',plat.dam,sequence_directory=dest/'sequence',authority_seal=result['authoritySeal'],receipt_seal=result['receiptSeal'])
    bad=copy.deepcopy(candidate);bad['identity']['sku']='wrong-sku'
    rejected=store.record(m,bad,attempt_key='rejected',seed=1,model='FIXTURE_COPY',model_version='1',provider='FUTURE_PROVIDER',config={})
    assert rejected['qa']['decision']=='REJECT'
    try:store.publish(m,'rejected',final=False)
    except ValueError:pass
    else:raise AssertionError('rejected_publish_not_blocked')
    accepted=store.record(m,candidate,attempt_key='accepted',seed=2,model='FIXTURE_COPY',model_version='1',provider='FUTURE_PROVIDER',config={})
    assert accepted['qa']['decision']=='PASS'
    assert store.record(m,candidate,attempt_key='accepted',seed=2,model='FIXTURE_COPY',model_version='1',provider='FUTURE_PROVIDER',config={})==accepted
    assert store.publish(m,'accepted',final=False)['state']=='QA_ACCEPTED_PREVIEW'
    try:store.publish(m,'accepted',final=True)
    except ValueError:pass
    else:raise AssertionError('fixture_final_publish_not_blocked')
    after=inspect_repo_lineage(ROOT,allow_dirty=args.allow_dirty)
    if after['evidenceCodeCommit']!=args.expected_commit or not args.allow_dirty and not after['workingTreeClean']:raise ValueError('code_changed_during_acceptance')
    evidence={'status':'PASS','generationId':gid,'codeCommit':args.expected_commit,'instructionSha':args.instruction_sha,
              'workingTreeClean':lineage['workingTreeClean'],'developmentOnly':bool(args.allow_dirty),
              'realBlender':True,'usedMock':False,'videoGroundTruthReady':m['videoGroundTruthReady'],
              'heroOrbitReal':m['heroOrbitReal'],'doorOpenReal':False,'doorBlocker':'BLOCKED_ARTICULATION_AUTHORITY',
              'visionQaReady':False,'liveProviderReady':False,'globalProductionReady':False,
              'frameCount':len(m['frames']),'artifactCount':len(m['frames'])*6,
              'blenderJobId':m['blenderJobId'],'blenderVersion':m['blenderVersion'],'device':m['device'],
              'authoritySeal':result['authoritySeal'],'receiptSeal':result['receiptSeal'],'manifestHash':m['manifestHash'],
              'sourceScope':'main Product Truth cabinet fixture; unmerged Golden Product PR is not imported',
              'providerPackages':['H3_MAX','LTX_2_5'],'candidateQaEvidence':'FIXTURE_COPY / REAL_LOGIC; PASS and REJECT, idempotency, publish gates verified',
              'persistedReopen':'PASS','directory':str(dest)}
    write_json(dest/'evidence.json',evidence)
    print(json.dumps(evidence),flush=True)


if __name__=='__main__':main()
