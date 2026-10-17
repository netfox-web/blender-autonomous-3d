"""Round 2 isolated clean-CODE sequences and durable candidate tamper acceptance."""
from __future__ import annotations
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'))
from scripts.run_video_ground_truth_e2e import source_fixture
from fox3d.evidence import inspect_repo_lineage
from fox3d.ids import new_id
from fox3d.platform import Platform
from fox3d.product_truth import inspect_instruction_sha
from fox3d.video_ground_truth import freeze_authority,execute_sequence,reopen_sequence,write_json
from fox3d.video_gateway import VideoCandidateStore,H3MaxAdapter,LTX25Adapter

KINDS=('HERO_ORBIT_8S','ARTWORK_DETAIL_6S','SMALL_ROOM_10S')


def durable_acceptance(plat,result,manifest,root):
    store=VideoCandidateStore(root,plat.dam,sequence_directory=result['directory'],
                              authority_seal=result['authoritySeal'],receipt_seal=result['receiptSeal'])
    candidate={'manifestHash':manifest['manifestHash'],'identity':copy.deepcopy(manifest['identity']),
               'frames':copy.deepcopy(manifest['frames']),'usedMock':True,'liveProviderReady':False,'visionQaReady':False}
    for frame in candidate['frames']:
        frame['artifacts']={k:v for k,v in frame['artifacts'].items() if k in ('beauty','product_mask','artwork_mask')}
    def record(key):
        return store.record(manifest,candidate,attempt_key=key,seed=42,model='FIXTURE_COPY',
                            model_version='2',provider='FUTURE_PROVIDER',config={})
    saved=record('accepted');assert saved['qa']['decision']=='PASS'
    assert record('accepted')==saved
    assert store.publish(manifest,'accepted',final=False)['state']=='QA_ACCEPTED_PREVIEW'
    parent=Path(root)/manifest['identity']['tenantId']/manifest['generationId']
    journal=parent/'accepted.json';original=journal.read_bytes();cases=[]
    def blocked(label):
        before=len(plat.dam._index)
        for operation in (lambda:record('next'),lambda:store.publish(manifest,'accepted',final=False),lambda:store.publish(manifest,'accepted',final=True)):
            try:operation()
            except ValueError:pass
            else:raise AssertionError('tamper_not_blocked:'+label)
        assert len(plat.dam._index)==before and not (parent/'next.json').exists()
        cases.append(label)
    for field in ('decision','model','modelVersion','provider','seed','config','identity','frame_reorder','frame_duplicate','frame_missing','matrix','qa_path','qa_sha','missing_field','corrupt_json','missing_file','renamed_file','mask_bytes'):
        changed=copy.deepcopy(saved);restore=None;foreign=parent/'foreign.json'
        try:
            if field=='decision':changed['qa']['decision']='REJECT'
            elif field in ('model','modelVersion','provider'):changed[field]='forged'
            elif field=='seed':changed['seed']=43
            elif field=='config':changed['config']={'forged':True}
            elif field=='identity':changed['candidate']['identity']['sku']='foreign'
            elif field=='frame_reorder':changed['candidate']['frames'].reverse()
            elif field=='frame_duplicate':changed['candidate']['frames'][1]=copy.deepcopy(changed['candidate']['frames'][0])
            elif field=='frame_missing':changed['candidate']['frames'].pop()
            elif field=='matrix':changed['candidate']['frames'][1]['cameraMatrix'][0][3]+=1
            elif field=='qa_path':changed['qaAsset']['path']=str(parent/'absent.json')
            elif field=='qa_sha':changed['qaAsset']['sha256']='0'*64
            elif field=='missing_field':changed.pop('modelVersion')
            elif field=='corrupt_json':journal.write_text('{broken')
            elif field=='missing_file':journal.unlink()
            elif field=='renamed_file':journal.rename(foreign)
            elif field=='mask_bytes':
                path=Path(saved['candidate']['frames'][1]['artifacts']['product_mask']['path'])
                restore=(path,path.read_bytes());path.write_bytes(b'corrupt')
            if changed!=saved:write_json(journal,changed)
            blocked(field)
        finally:
            if restore:restore[0].write_bytes(restore[1])
            if foreign.exists():foreign.unlink()
            journal.write_bytes(original)
    try:record('next')
    except ValueError as exc:assert 'accepted_lineage' in str(exc)
    else:raise AssertionError('verified_PASS_not_immutable')
    cases.append('verified_PASS_blocks_next')
    from fox3d.infra import DAM
    restarted=VideoCandidateStore(root,DAM(plat.dam.root),sequence_directory=result['directory'],
                                 authority_seal=result['authoritySeal'],receipt_seal=result['receiptSeal'])
    assert restarted.publish(manifest,'accepted',final=False)['state']=='QA_ACCEPTED_PREVIEW'
    try:restarted.publish(manifest,'accepted',final=True)
    except ValueError:pass
    else:raise AssertionError('final_commerce_not_blocked')
    return {'status':'PASS','cases':cases,'noDamWritesOnCorruption':True,'restartWithoutMemoryIndex':'PASS',
            'truth':'REAL_LOGIC / FIXTURE_COPY','liveProviderReady':False,'visionQaReady':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--instruction-sha',required=True)
    parser.add_argument('--expected-commit',required=True);parser.add_argument('--allow-dirty',action='store_true')
    parser.add_argument('--fps',type=int,default=12);args=parser.parse_args()
    if inspect_instruction_sha()!=args.instruction_sha:raise ValueError('wrong_instruction_SHA')
    lineage=inspect_repo_lineage(ROOT,allow_dirty=args.allow_dirty)
    if lineage['evidenceCodeCommit']!=args.expected_commit:raise ValueError('wrong_CODE_SHA')
    gid=new_id();dest=ROOT/'.fox3d-work/video-round2-e2e'/gid[:8];dest.mkdir(parents=True)
    print(json.dumps({'generationId':gid,'directory':str(dest),'stage':'source_product_truth'}),flush=True)
    plat=Platform(root=dest/'platform',mock_blender=False);source=source_fixture(plat,args.expected_commit)
    write_json(dest/'source.json',source);sequences={};product_identity=None;geometry=None
    for kind in KINDS:
        a=freeze_authority(plat,source,sku='VIDEO-REFERENCE-CABINET',product_version=1,instruction_sha=args.instruction_sha,
                           code_sha=args.expected_commit,generation_id=gid+'-'+kind.lower(),kind=kind,fps=args.fps,
                           code_tree_clean=lineage['workingTreeClean'],development_only=args.allow_dirty)
        product={k:v for k,v in a['identity'].items() if k not in ('videoRecipeHash','cameraRecipeHash','sceneRecipeHash')}
        if product_identity is None:product_identity=product;geometry=a['objects']
        if product!=product_identity or a['objects']!=geometry:raise ValueError('cross_recipe_product_drift')
        if kind=='ARTWORK_DETAIL_6S' and a['recipe']['detailObject']!=product['objectName']:raise ValueError('detail_wrong_component')
        print(json.dumps({'stage':kind,'frames':a['recipe']['frameCount']}),flush=True)
        result=execute_sequence(plat,a,dest/kind)
        m=reopen_sequence(result['directory'],authority_seal=result['authoritySeal'],receipt_seal=result['receiptSeal'])
        for adapter in (H3MaxAdapter(),LTX25Adapter()):
            write_json(dest/kind/(adapter.provider+'-request.json'),adapter.request_package(result['directory'],authority_seal=result['authoritySeal'],receipt_seal=result['receiptSeal']))
        sequences[kind]={'directory':result['directory'],'generationId':m['generationId'],'manifestHash':m['manifestHash'],
                         'authoritySeal':result['authoritySeal'],'receiptSeal':result['receiptSeal'],'blenderJobId':m['blenderJobId'],
                         'sceneRecipeHash':m['identity']['sceneRecipeHash'],'frameCount':len(m['frames']),
                         'frameArtifacts':len(m['frames'])*6,'contextArtifacts':sum('sceneContextMask' in f for f in m['frames']),
                         'videoGroundTruthReady':m['videoGroundTruthReady'],'usedMock':m['usedMock'],
                         'blenderVersion':m['blenderVersion'],'device':m['device'],'persistedReopen':'PASS'}
        if kind=='HERO_ORBIT_8S':
            durable=durable_acceptance(plat,result,m,dest/'candidates');write_json(dest/'durable-acceptance.json',durable)
    assert sequences['SMALL_ROOM_10S']['sceneRecipeHash']!=sequences['HERO_ORBIT_8S']['sceneRecipeHash']
    after=inspect_repo_lineage(ROOT,allow_dirty=args.allow_dirty)
    if after['evidenceCodeCommit']!=args.expected_commit or not args.allow_dirty and not after['workingTreeClean']:
        raise ValueError('code_changed_during_acceptance')
    ready=all(s['videoGroundTruthReady'] for s in sequences.values())
    e={'status':'PASS','generationId':gid,'instructionSha':args.instruction_sha,'codeCommit':args.expected_commit,
       'workingTreeClean':lineage['workingTreeClean'],'developmentOnly':args.allow_dirty,'realBlender':True,'usedMock':False,
       'sequences':sequences,'productIdentity':product_identity,'sameProductAcrossRecipes':True,
       'videoGroundTruthReady':ready,'heroOrbitReal':ready,'artworkDetailReal':ready,'smallRoomReal':ready,
       'durableCandidateLineageReady':durable['status']=='PASS','durableAcceptance':durable,
       'doorOpenReal':False,'visionQaReady':False,'liveProviderReady':False,'globalProductionReady':False,
       'sourceScope':'Synthetic explicit 800x295x900 four-door cabinet; generated asymmetric artwork; not physical truth.'}
    write_json(dest/'evidence.json',e);print(json.dumps(e),flush=True)


if __name__=='__main__':main()
