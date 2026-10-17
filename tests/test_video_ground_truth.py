"""Adversarial frame/authority regressions. All image/worker fixtures are MOCK."""
import copy
import json
from dataclasses import asdict

import pytest
from fox3d.ids import stable_hash,sha256_bytes
from fox3d.platform import Platform
from fox3d.product_truth import run_phase_841_scenario,write_occupancy_png
from fox3d.video_recipe import make_recipe,validate_recipe,frame_plan,articulation_gate,ROLES
from fox3d.video_ground_truth import freeze_authority,validate_manifest,validate_observation,reopen_sequence,write_json
from fox3d.video_gateway import H3MaxAdapter,LTX25Adapter,qa_candidate,VideoCandidateStore


@pytest.fixture(scope='module')
def _base_bundle(tmp_path_factory):
    tmp_path=tmp_path_factory.mktemp('video-source')
    p=Platform(root=tmp_path/'platform',mock_blender=True)
    source=run_phase_841_scenario(p)
    a=freeze_authority(p,source,sku='TEST-SKU',product_version=1,instruction_sha='a'*40,code_sha='b'*40,
                       generation_id='test-video',fps=1,width=32,height=32,allow_mock=True)
    frames=[];jid='test-job'
    for i in range(a['recipe']['frameCount']):
        plan=frame_plan(a['recipe'],i);plan.pop('location')
        plan.update(objects=copy.deepcopy(a['objects']),identity=copy.deepcopy(a['identity']),blenderJobId=jid)
        artifacts={}
        for role,ext in ROLES.items():
            file=tmp_path/f'{i}_{role}.{ext}'
            if ext=='exr':file.write_bytes(b'v/1\x01'+role.encode()+b'MOCK_EXR')
            else:write_occupancy_png(file,width=32,height=32,kind=role,seed='fixture')
            data=file.read_bytes()
            obj=p.dam.put(tenant_id=a['identity']['tenantId'],kind='video_ground_truth',name=file.name,data=data,
                           metadata={'jobId':jid,'identity':a['identity'],'frame':i,'role':role,'authorityHash':a['authorityHash']})
            artifacts[role]={'path':obj.path,'sha256':obj.sha256,'size':len(data),'dam':asdict(obj)}
        plan['artifacts']=artifacts;frames.append(plan)
    obs={'identity':copy.deepcopy(a['identity']),'authorityHash':a['authorityHash'],'blenderJobId':jid,'frames':copy.deepcopy(frames),
         'appliedPlacements':[copy.deepcopy(a['identity'])],'usedMock':True,'realBlender':False,
         'reopened':[{'index':i,'cameraMatrix':frames[i]['cameraMatrix'],'objects':frames[i]['objects']} for i in (0,4,7)]}
    body={'frames':frames,'blenderJobId':jid,'blenderVersion':'MOCK','device':'MOCK','usedMock':True,
          'videoGroundTruthReady':False,'heroOrbitReal':False,'doorOpenReal':False,'visionQaReady':False,'liveProviderReady':False,'globalProductionReady':False}
    receipt={'authorityHash':a['authorityHash'],'jobId':jid,'observation':obs,'supportArtifacts':{},'manifestBody':body}
    rs=stable_hash(receipt)
    m={'schema':'VIDEO_GROUND_TRUTH_MANIFEST_V1','authorityHash':a['authorityHash'],'instructionSha':a['instructionSha'],'codeSha':a['codeSha'],
       'generationId':a['generationId'],'identity':a['identity'],'recipe':a['recipe'],'receiptHash':rs,**body}
    m['manifestHash']=stable_hash(m)
    directory=tmp_path/'sequence'
    for name,value in [('authority.json',a),('receipt.json',receipt),('VIDEO_GROUND_TRUTH_MANIFEST.json',m)]:write_json(directory/name,value)
    return dict(plat=p,source=source,a=a,receipt=receipt,rs=rs,m=m,directory=directory,tmp=tmp_path)


@pytest.fixture
def bundle(_base_bundle,tmp_path):
    # Frozen source/ground-truth files are immutable except the explicit tamper
    # test, which restores bytes. Candidate journals remain isolated per test.
    return {**_base_bundle,'tmp':tmp_path}


def check(b,m=None):
    return validate_manifest(m or b['m'],authority=b['a'],authority_seal=b['a']['authorityHash'],receipt=b['receipt'],receipt_seal=b['rs'],dam=b['plat'].dam)


def test_valid_fixture_persists_without_real_claim(bundle):
    b=bundle
    assert check(b)==[]
    m=reopen_sequence(b['directory'],authority_seal=b['a']['authorityHash'],receipt_seal=b['rs'])
    assert m==b['m'] and m['videoGroundTruthReady'] is False
    for adapter in (H3MaxAdapter(),LTX25Adapter()):
        request=adapter.request_package(b['directory'],authority_seal=b['a']['authorityHash'],receipt_seal=b['rs'])
        assert len(request['frames'])==8 and request['liveProviderReady'] is False
        assert adapter.submit(request)['networkExecuted'] is False


@pytest.mark.parametrize('key',['tenantId','sku','productVersion','engineeringHash','productTruthHash','artworkHash','artworkVersion','placementHash','finalUvHash','cameraRecipeHash','sceneRecipeHash','videoRecipeHash'])
def test_identity_injection_rejected_even_with_new_manifest_hash(bundle,key):
    b=bundle;m=copy.deepcopy(b['m']);m['identity'][key]='foreign'
    m['manifestHash']=stable_hash({k:v for k,v in m.items() if k!='manifestHash'})
    assert check(b,m)


@pytest.mark.parametrize('change',['missing','duplicate','reorder','cross_video','time','camera','object','nan','inf','bool','job','path','size','hash','dam','mask_swap','mask_alias','articulation','recipe_body','ready'])
def test_frame_manifest_tampering(bundle,change):
    b=bundle;m=copy.deepcopy(b['m']);f=m['frames'][0];r=f['artifacts']['beauty']
    if change=='missing':m['frames'].pop()
    elif change=='duplicate':m['frames'][1]=copy.deepcopy(f)
    elif change=='reorder':m['frames'].reverse()
    elif change=='cross_video':f['identity']['productTruthGeneration']='other-video'
    elif change=='time':f['timestamp']=.1
    elif change=='camera':f['cameraMatrix'][0][3]+=1
    elif change=='object':next(iter(f['objects'].values()))['matrix'][0][3]+=1
    elif change in ('nan','inf'):f['cameraMatrix'][0][0]=float(change)
    elif change=='bool':f['index']=False
    elif change=='job':f['blenderJobId']='other-job'
    elif change=='path':r['path']='../outside.png'
    elif change=='size':r['size']+=1
    elif change=='hash':r['sha256']='0'*64
    elif change=='dam':r['dam']['metadata']['jobId']='other'
    elif change=='mask_swap':f['artifacts']['product_mask'],f['artifacts']['artwork_mask']=f['artifacts']['artwork_mask'],f['artifacts']['product_mask']
    elif change=='mask_alias':f['artifacts']['artwork_mask']=copy.deepcopy(f['artifacts']['product_mask'])
    elif change=='articulation':f['articulation']=[{'door':'invented','angle':90}]
    elif change=='recipe_body':m['recipe']['camera']['focalLengthMm']=70.
    elif change=='ready':m['videoGroundTruthReady']=True
    m['manifestHash']=stable_hash({k:v for k,v in m.items() if k!='manifestHash'})
    assert check(b,m)


def test_changed_file_and_rehashed_manifest_cannot_change_receipt(bundle):
    b=bundle;m=copy.deepcopy(b['m']);rec=m['frames'][0]['artifacts']['artwork_mask']
    from pathlib import Path
    path=Path(rec['path']);original=path.read_bytes()
    try:
        path.write_bytes(b'tamper');rec['sha256']=sha256_bytes(b'tamper');rec['size']=6
        assert check(b,m)
        assert check(b)
    finally:path.write_bytes(original)


@pytest.mark.parametrize('value',[True,'12',float('nan'),float('inf'),0,61])
def test_strict_fps(bundle,value):
    with pytest.raises(ValueError):make_recipe('HERO_ORBIT_8S',bundle['a']['engineering'],fps=value)


@pytest.mark.parametrize('value',[True,'45',float('nan'),float('inf'),46.])
def test_coordinated_camera_body_and_hash_rejected(bundle,value):
    b=bundle;r=copy.deepcopy(b['a']['recipe']);r['camera']['focalLengthMm']=value
    r['cameraRecipeHash']=stable_hash(r['camera']);r['videoRecipeHash']=stable_hash({k:v for k,v in r.items() if k!='videoRecipeHash'})
    with pytest.raises(ValueError):validate_recipe(r,b['a']['engineering'])


@pytest.mark.parametrize('bad',['wrong_door','swapped_door','wrong_pivot','wrong_axis','wrong_range','wrong_transform','wrong_job','wrong_sku','wrong_version','artwork_wrong_component'])
def test_articulation_cannot_be_invented(bundle,bad):
    b=bundle;r=make_recipe('DOOR_OPEN_8S',b['a']['engineering'])
    with pytest.raises(ValueError,match='BLOCKED_ARTICULATION_AUTHORITY'):
        articulation_gate(r,{'articulationAuthority':{'claim':'REAL','fault':bad,'pivot':[0,0,0],'axis':[0,0,1],'range':[0,90]}})


def test_assembly_and_source_real_gate(bundle):
    b=bundle
    with pytest.raises(ValueError,match='BLOCKED_ASSEMBLY'):
        articulation_gate(make_recipe('ASSEMBLY_EXPLODE_10S',b['a']['engineering']),{})
    with pytest.raises(ValueError,match='BLOCKED_REAL_PRODUCT_TRUTH'):
        freeze_authority(b['plat'],b['source'],sku='sku',product_version=1,instruction_sha='a'*40,code_sha='b'*40,generation_id='x')


@pytest.mark.parametrize('field',['cameraMatrix','productMatrix','intrinsics'])
def test_worker_observation_cannot_self_assert_camera(bundle,field):
    b=bundle;obs=copy.deepcopy(b['receipt']['observation']);obs['frames'][0][field][0][0]+=1
    assert validate_observation(b['a'],obs,job_id='test-job')


def candidate(b):
    m=b['m'];frames=copy.deepcopy(m['frames'])
    for f in frames:f['artifacts']={k:v for k,v in f['artifacts'].items() if k in ('beauty','product_mask','artwork_mask')}
    return {'manifestHash':m['manifestHash'],'identity':copy.deepcopy(m['identity']),'frames':frames,
            'usedMock':True,'liveProviderReady':False,'visionQaReady':False}


def store(b):
    return VideoCandidateStore(b['tmp']/'candidates',b['plat'].dam,sequence_directory=b['directory'],authority_seal=b['a']['authorityHash'],receipt_seal=b['rs'])


def record(s,b,c,key='attempt1'):
    return s.record(b['m'],c,attempt_key=key,seed=42,model='fixture',model_version='1',provider='H3_MAX',config={})


@pytest.mark.parametrize('flag',['liveProviderReady','visionQaReady','usedMock'])
def test_mock_promotion_rejected(bundle,flag):
    c=candidate(bundle);c[flag]=flag!='usedMock'
    assert qa_candidate(bundle['m'],c)['decision']=='REJECT'


def test_qa_idempotency_restart_and_accepted_immutability(bundle):
    b=bundle;c=candidate(b);s=store(b)
    assert qa_candidate(b['m'],c)['decision']=='PASS'
    first=record(s,b,c);assert record(store(b),b,c)==first
    assert first['modelVersion']=='1'
    for f in first['candidate']['frames']:
        for rec in f['artifacts'].values():
            assert rec['dam']['kind']=='video_provider_candidate' and rec['dam']['path']==rec['path']
    assert store(b).publish(b['m'],'attempt1',final=False)['state']=='QA_ACCEPTED_PREVIEW'
    with pytest.raises(ValueError,match='BLOCKED_LIVE'):s.publish(b['m'],'attempt1')
    with pytest.raises(ValueError,match='accepted_lineage'):record(s,b,c,'attempt2')
    c['frames'][0]['timestamp']=1
    with pytest.raises(ValueError,match='idempotency_conflict'):record(s,b,c)


def test_rejected_candidate_no_publish_retry_bounded(bundle):
    b=bundle;c=candidate(b);c['identity']['sku']='foreign';s=store(b)
    assert record(s,b,c)['qa']['decision']=='REJECT'
    with pytest.raises(ValueError,match='rejected_candidate'):s.publish(b['m'],'attempt1',final=False)
    record(s,b,c,'attempt2');record(s,b,c,'attempt3')
    with pytest.raises(ValueError,match='retry_limit'):record(s,b,c,'attempt4')


def test_actual_candidate_pixels_trigger_retry(bundle):
    b=bundle;c=candidate(b)
    from fox3d.pngutil import write_png
    p=b['tmp']/'changed.png';write_png(p,32,32,bytes([255,0,0])*1024)
    data=p.read_bytes();c['frames'][0]['artifacts']['beauty']={'path':str(p),'sha256':sha256_bytes(data),'size':len(data)}
    assert qa_candidate(b['m'],c)['decision']=='RETRY'


def test_forged_manifest_cannot_enter_candidate_store(bundle):
    b=bundle;s=store(b);m=copy.deepcopy(b['m']);m['identity']['sku']='fake'
    with pytest.raises(ValueError,match='untrusted_ground_truth'):
        s.record(m,candidate(b),attempt_key='a',seed=1,model='fixture',model_version='1',provider='H3_MAX',config={})


def test_explicit_fixture_preserves_full_board_height(tmp_path,monkeypatch):
    import scripts.run_video_ground_truth_e2e as runner
    from fox3d.video_recipe import expected_objects
    monkeypatch.setattr(runner,'render_product_truth',lambda *args,**kwargs:{})
    source=runner.source_fixture(Platform(root=tmp_path/'source',mock_blender=True),'b'*40)
    eng=source['frozenAuthorityContext']['engineering']
    left=next(p for p in eng['components'] if p['role']=='left')
    assert expected_objects(eng)[left['partName']]['dimensions'][2]==pytest.approx(.9)
    assert expected_objects(eng)[left['partName']]['matrix'][2][3]==pytest.approx(.45)


def test_recipe_last_key_matches_last_sample_and_detail_targets_artwork(bundle):
    b=bundle;r=b['a']['recipe']
    assert r['camera']['keyframes'][-1]['t']==frame_plan(r,r['frameCount']-1)['timestamp']
    detail=make_recipe('ARTWORK_DETAIL_6S',b['a']['engineering'],artwork_object=b['a']['identity']['objectName'])
    assert detail['detailObject']==b['a']['identity']['objectName']
    room=make_recipe('SMALL_ROOM_10S',b['a']['engineering'])
    assert room['scene']['room'] and room['scene']['transparent'] is False


def test_retry_detects_journal_tamper(bundle):
    b=bundle;s=store(b);c=candidate(b);first=record(s,b,c)
    p=s.root/b['m']['identity']['tenantId']/b['m']['generationId']/'attempt1.json'
    first['modelVersion']='forged';write_json(p,first)
    with pytest.raises(ValueError,match='attempt_tampered'):record(s,b,c)


def test_retry_detects_candidate_byte_tamper(bundle):
    from pathlib import Path
    b=bundle;s=store(b);c=candidate(b);first=record(s,b,c)
    Path(first['candidate']['frames'][0]['artifacts']['beauty']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='artifact_bytes'):record(s,b,c)


def test_candidate_extra_artifact_not_ingested(bundle):
    b=bundle;c=candidate(b);c['frames'][0]['artifacts']['unrequested']=c['frames'][0]['artifacts']['beauty']
    assert qa_candidate(b['m'],c)['decision']=='REJECT'


@pytest.mark.parametrize('change',[
    'decision','model','provider','modelVersion','seed','config','identity','frame_reorder',
    'frame_duplicate','frame_missing','matrix','artifact','qa_path','qa_sha','mask_bytes',
    'missing_file','renamed_file','foreign_copy','duplicate_number','missing_field','corrupt_json',
    'missing_index','index_tamper',
])
def test_round2_prior_corruption_blocks_new_attempt_and_publish(bundle,change):
    from pathlib import Path
    b=bundle;s=store(b);c=candidate(b);first=record(s,b,c)
    parent=s.root/b['m']['identity']['tenantId']/b['m']['generationId'];path=parent/'attempt1.json'
    changed=copy.deepcopy(first)
    if change=='decision':changed['qa']['decision']='REJECT'
    elif change in ('model','provider','modelVersion'):changed[change]='foreign'
    elif change=='seed':changed['seed']=43
    elif change=='config':changed['config']={'changed':True}
    elif change=='identity':changed['candidate']['identity']['sku']='foreign'
    elif change=='frame_reorder':changed['candidate']['frames'].reverse()
    elif change=='frame_duplicate':changed['candidate']['frames'][1]=copy.deepcopy(changed['candidate']['frames'][0])
    elif change=='frame_missing':changed['candidate']['frames'].pop()
    elif change=='matrix':changed['candidate']['frames'][1]['cameraMatrix'][0][3]+=1
    elif change=='artifact':changed['candidate']['frames'][1]['artifacts']['beauty']['sha256']='0'*64
    elif change=='qa_path':changed['qaAsset']['path']=str(parent/'missing.json')
    elif change=='qa_sha':changed['qaAsset']['sha256']='0'*64
    elif change=='duplicate_number':changed['attemptNumber']=2
    elif change=='missing_field':changed.pop('modelVersion')
    elif change=='mask_bytes':Path(first['candidate']['frames'][1]['artifacts']['product_mask']['path']).write_bytes(b'changed')
    elif change=='missing_file':path.unlink()
    elif change=='renamed_file':path.rename(parent/'foreign.json')
    elif change=='foreign_copy':write_json(parent/'foreign.json',first)
    elif change=='corrupt_json':path.write_text('{bad json')
    elif change=='missing_index':(parent/'.attempt-set.json').unlink()
    elif change=='index_tamper':write_json(parent/'.attempt-set.json',{})
    if changed!=first:write_json(path,changed)
    count=len(b['plat'].dam._index);before={p.name:p.read_bytes() for p in parent.glob('*.json')}
    with pytest.raises(ValueError):record(s,b,c,'new-key')
    with pytest.raises(ValueError):s.publish(b['m'],'attempt1',final=False)
    assert len(b['plat'].dam._index)==count
    assert {p.name:p.read_bytes() for p in parent.glob('*.json')}==before


def test_round2_deleted_last_rejected_attempt_blocks_retry(bundle):
    b=bundle;s=store(b);c=candidate(b);c['identity']['sku']='foreign'
    record(s,b,c);record(s,b,c,'attempt2')
    parent=s.root/b['m']['identity']['tenantId']/b['m']['generationId']
    (parent/'attempt2.json').unlink();count=len(b['plat'].dam._index)
    with pytest.raises(ValueError,match='missing_duplicate'):record(s,b,c,'attempt3')
    assert len(b['plat'].dam._index)==count


@pytest.mark.parametrize('field',['tenant','jobId','frame','role'])
def test_round2_valid_bytes_with_foreign_dam_lineage_blocked(bundle,field):
    b=bundle;s=store(b);first=record(s,b,candidate(b));changed=copy.deepcopy(first)
    rec=changed['candidate']['frames'][0]['artifacts']['beauty'];ref=rec['dam']
    meta=copy.deepcopy(ref['metadata']);tenant=ref['tenant_id']
    if field=='tenant':tenant='foreign'
    else:meta[field]='foreign'
    obj=b['plat'].dam.put(tenant_id=tenant,kind=ref['kind'],name='foreign.png',data=__import__('pathlib').Path(rec['path']).read_bytes(),metadata=meta)
    rec.update(path=obj.path,dam=asdict(obj))
    qa_ref=changed.pop('qaAsset')
    qa=b['plat'].dam.put(tenant_id=qa_ref['tenant_id'],kind=qa_ref['kind'],name='resealed.json',data=json.dumps(changed).encode(),metadata=qa_ref['metadata'])
    changed['qaAsset']=asdict(qa)
    parent=s.root/b['m']['identity']['tenantId']/b['m']['generationId']
    write_json(parent/'attempt1.json',changed);s._persist_attempt_set(b['m'],[],changed,parent)
    count=len(b['plat'].dam._index)
    with pytest.raises(ValueError,match='candidate_dam_lineage'):record(s,b,candidate(b),'next')
    with pytest.raises(ValueError,match='candidate_dam_lineage'):s.publish(b['m'],'attempt1',final=False)
    assert len(b['plat'].dam._index)==count


def test_round2_restart_validates_durable_set_without_memory_index(bundle):
    from fox3d.infra import DAM
    b=bundle;s=store(b);first=record(s,b,candidate(b))
    restarted=store(b);restarted.dam=DAM(b['plat'].dam.root)
    assert restarted.publish(b['m'],'attempt1',final=False)['state']=='QA_ACCEPTED_PREVIEW'
    assert record(restarted,b,candidate(b))==first
    with pytest.raises(ValueError,match='accepted_lineage'):record(restarted,b,candidate(b),'new')


def test_round2_cross_generation_preview_rejected(bundle):
    b=bundle;s=store(b);record(s,b,candidate(b));other=copy.deepcopy(b['m']);other['generationId']='foreign'
    with pytest.raises(ValueError,match='untrusted_ground_truth'):s.publish(other,'attempt1',final=False)


@pytest.mark.parametrize('mode',['valid','overlap','empty','wrong_size','alias'])
def test_round2_room_context_pixels_independently_excluded(bundle,mode):
    from fox3d.video_ground_truth import check_frame_pixels
    from fox3d.pngutil import write_png
    from fox3d.artwork import decode_png_rgb
    from pathlib import Path
    b=bundle;frame=copy.deepcopy(b['m']['frames'][0]);recipe=make_recipe('SMALL_ROOM_10S',b['a']['engineering'],fps=1,width=32,height=32)
    _,_,rgb=decode_png_rgb(Path(frame['artifacts']['product_mask']['path']).read_bytes())
    data=bytes(0 if max(rgb[i:i+3])>127 else 255 for i in range(0,len(rgb),3) for _ in range(3))
    if mode=='overlap':data=bytes([255])*len(data)
    if mode=='empty':data=bytes(len(data))
    path=b['tmp']/'context.png';width=16 if mode=='wrong_size' else 32
    write_png(path,width,32,data[:width*32*3]);raw=path.read_bytes()
    frame['sceneContextMask']={'path':str(path),'sha256':sha256_bytes(raw),'size':len(raw)}
    if mode=='alias':frame['sceneContextMask']=frame['artifacts']['product_mask']
    if mode=='valid':check_frame_pixels(frame,recipe)
    else:
        with pytest.raises(ValueError):check_frame_pixels(frame,recipe)


def test_round2_detail_canonical_component_binding(bundle):
    from fox3d.video_ground_truth import check_authority
    b=bundle;a=freeze_authority(b['plat'],b['source'],sku='TEST-SKU',product_version=1,instruction_sha='a'*40,
        code_sha='b'*40,generation_id='detail',kind='ARTWORK_DETAIL_6S',fps=1,width=32,height=32,allow_mock=True)
    check_authority(a,a['authorityHash'])
    a['identity']['objectName']='foreign';a['authorityHash']=stable_hash({k:v for k,v in a.items() if k!='authorityHash'})
    with pytest.raises(ValueError,match='detail_wrong_artwork_component'):check_authority(a,a['authorityHash'])


@pytest.mark.parametrize('mode',['product_injection','context_pass_index','context_geometry','reopen_context'])
def test_round2_room_context_observation_tamper_rejected(bundle,mode):
    from fox3d.video_recipe import scene_context_objects
    b=bundle;a=copy.deepcopy(b['a']);a['recipe']=make_recipe('SMALL_ROOM_10S',a['engineering'],fps=1,width=32,height=32)
    obs=copy.deepcopy(b['receipt']['observation']);frames=[]
    for i in range(10):
        f=copy.deepcopy(obs['frames'][0]);plan=frame_plan(a['recipe'],i);plan.pop('location');f.update(plan)
        f['sceneContextObjects']=scene_context_objects(a['recipe']);frames.append(f)
    obs['frames']=frames
    obs['reopened']=[{'index':i,'cameraMatrix':frames[i]['cameraMatrix'],'objects':copy.deepcopy(frames[i]['objects']),
                      'sceneContextObjects':copy.deepcopy(frames[i]['sceneContextObjects'])} for i in (0,5,9)]
    assert not validate_observation(a,obs,job_id='test-job')
    if mode=='product_injection':frames[0]['objects']['VideoRoomFloor']=frames[0]['sceneContextObjects']['VideoRoomFloor']
    elif mode=='context_pass_index':frames[0]['sceneContextObjects']['VideoRoomFloor']['passIndex']=1
    elif mode=='context_geometry':frames[0]['sceneContextObjects']['VideoRoomFloor']['dimensions'][0]+=1
    else:obs['reopened'][0]['sceneContextObjects']={}
    assert validate_observation(a,obs,job_id='test-job')


def test_round2_acceptance_tamper_matrix_with_mock_bundle(bundle):
    from scripts.run_video_round2_e2e import durable_acceptance
    b=bundle;result={'directory':str(b['directory']),'authoritySeal':b['a']['authorityHash'],'receiptSeal':b['rs']}
    evidence=durable_acceptance(b['plat'],result,b['m'],b['tmp']/'evidence-candidates')
    assert evidence['status']=='PASS' and len(evidence['cases'])==19 and evidence['noDamWritesOnCorruption']


@pytest.mark.parametrize('change',['recipe','generation'])
def test_round2_existing_platform_cache_separates_video_authority(bundle,change):
    from fox3d.infra import job_cache_key
    from fox3d.video_ground_truth import video_job_payload
    b=bundle;a=copy.deepcopy(b['a']);first=video_job_payload(a)
    assert job_cache_key(first,blender_version='real')==job_cache_key(video_job_payload(a),blender_version='real')
    if change=='recipe':a['recipe']=make_recipe('ARTWORK_DETAIL_6S',a['engineering'],fps=1,width=32,height=32,artwork_object=a['identity']['objectName'])
    else:a['generationId']='new-generation'
    a['authorityHash']=stable_hash({k:v for k,v in a.items() if k!='authorityHash'})
    assert job_cache_key(first,blender_version='real')!=job_cache_key(video_job_payload(a),blender_version='real')
