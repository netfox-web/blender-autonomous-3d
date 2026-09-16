"""MOCK regression only; actual rendering is covered by the clean CODE runner."""
import copy
import io
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from fox3d import model_batches as b, model_compositions as c, product_models as m
from fox3d import print_assets, asset_usage
from fox3d import variant_authority as a, model_categories
from fox3d.ids import new_id, stable_hash, sha256_bytes
from fox3d.product_models_api import product_models_router
from fox3d.recipe_3d import atomic_json, read_json, input_hash
from fox3d.recipe_preview_service import RecipePreviewService


def setup(root):
    raw=io.BytesIO();Image.new('RGB',(100,100),'red').save(raw,'PNG')
    asset=print_assets.import_asset(root,'t',raw.getvalue(),'fixture.png')
    asset_usage.classify(root,'t',asset['id'],'ARTWORK','Synthetic regression artwork',0)
    model=m.save(root,'t',{'name':'fixture','family':'coaster','geometry':'RECTANGLE',
                         'widthMm':100.,'depthMm':5.,'heightMm':100.,
                         'dimensionEvidence':'fixture','structureEvidence':'fixture'},0)
    selections=[{'sku':'A','scene':scene,'placements':[{'componentId':'surface','assetId':asset['id']}]}
                for scene in ['STUDIO','WARM_ROOM']]
    return model,asset,{'name':'fixture batch','selections':selections}



def mock_publication(root, tenant, mid, draft, *, revision, generation_id, **kwargs):
    target=c.folder_for(root,tenant,mid)/'generations'/generation_id
    manifest={'generationId':generation_id,'historyVersion':1,'draft':draft,'sourceRevision':revision,
              'planHash':stable_hash(draft),'scene':draft['scene'],
              'package':{'placements':[{'originalAssetId':p['assetId']} for p in draft['placements']]}}
    if 'inputAuthority' in draft:
        manifest['inputAuthorityHash']=draft['inputAuthority']['hash']
    atomic_json(target/'manifest.json',manifest)
    atomic_json(target/'published.json',{'manifestSha256':sha256_bytes((target/'manifest.json').read_bytes())})
    (target/'beauty.png').write_bytes(b'MOCK regression, not render evidence')
    return {'generated':True,'stale':False,'generationId':generation_id}


def queue_state(root,model,draft,bid,state='succeeded'):
    atomic_json(c.folder_for(root,'t',model['id'])/'state.json',
                {'taskId':bid,'state':state,'inputHash':input_hash(draft),'batchVersion':1})


def mock_verifier(monkeypatch):
    # Only artifact bytes are stubbed. Real generation/publication/identity checks run.
    monkeypatch.setattr(c.print_preview,'validate',lambda p:read_json(p/'manifest.json'))


def test_preflight_all_or_nothing_and_immutable_snapshot(tmp_path):
    model,asset,batch=setup(tmp_path)
    frozen=b.snapshot(tmp_path,'t',model,batch)
    batch['selections'][0]['sku']='changed'
    assert frozen['selections'][0]['sku']=='A'
    batch['selections'][1]['placements'][0]['componentId']='unknown'
    with pytest.raises(ValueError): b.snapshot(tmp_path,'t',model,batch)
    assert not c.folder_for(tmp_path,'t',model['id']).exists()


@pytest.mark.parametrize('kind',['duplicate','empty','too_many','blank_name','wrong_tenant','revoked'])
def test_invalid_batches_rejected(tmp_path,kind):
    model,asset,batch=setup(tmp_path);tenant='t'
    if kind=='duplicate':batch['selections']*=2
    if kind=='empty':batch['selections']=[]
    if kind=='too_many':batch['selections']*=13
    if kind=='blank_name':batch['name']=' '
    if kind=='wrong_tenant':tenant='other'
    if kind=='revoked':asset_usage.classify(tmp_path,'t',asset['id'],'REFERENCE','revoked',1)
    with pytest.raises((ValueError,OSError)):b.snapshot(tmp_path,tenant,model,batch)


def test_batch_preserves_success_on_failure_and_cancellation(tmp_path,monkeypatch):
    model,asset,batch=setup(tmp_path);snapshot=b.snapshot(tmp_path,'t',model,batch)
    platform=SimpleNamespace(root=tmp_path);stop=Event();seen=[]
    def fake(*args,**kwargs):
        seen.append(kwargs['generation_id']);stop.set()
        return mock_publication(tmp_path,*args[1:],**kwargs)
    monkeypatch.setattr(c,'generate',fake)
    bid=new_id();queue_state(tmp_path,model,snapshot,bid,'cancelled');mock_verifier(monkeypatch)
    with pytest.raises(ValueError,match='取消'):b.generate(platform,'t',model['id'],snapshot,revision=1,generation_id=bid,cancel_flag=stop)
    record=b.current(tmp_path,'t',model['id'],bid,'cancelled')
    assert [r['state'] for r in record['rows']]==['succeeded','cancelled']
    assert len(seen)==1


@pytest.mark.parametrize('change',['master','artwork','failure'])
def test_each_row_rechecks_current_sources(tmp_path,monkeypatch,change):
    model,asset,batch=setup(tmp_path);snapshot=b.snapshot(tmp_path,'t',model,batch);seen=[]
    def fake(*args,**kwargs):
        seen.append(kwargs['generation_id'])
        if change=='master':m.save(tmp_path,'t',{**model['draft'],'widthMm':101.},1,model['id'])
        if change=='artwork':asset_usage.classify(tmp_path,'t',asset['id'],'REFERENCE','revoked',1)
        if change=='failure':raise ValueError('renderer failed')
        return mock_publication(tmp_path,*args[1:],**kwargs)
    monkeypatch.setattr(c,'generate',fake);bid=new_id();queue_state(tmp_path,model,snapshot,bid,'failed');mock_verifier(monkeypatch)
    with pytest.raises(ValueError):b.generate(SimpleNamespace(root=tmp_path),'t',model['id'],snapshot,revision=1,generation_id=bid)
    record=b.current(tmp_path,'t',model['id'],bid,'failed')
    assert record['rows'][-1]['state']=='failed'
    assert len(seen)==(2 if change=='failure' else 1)


def test_restart_does_not_resume_or_claim_success(tmp_path,monkeypatch):
    model,asset,batch=setup(tmp_path);bid=new_id();draft=b.snapshot(tmp_path,'t',model,batch)
    folder=c.folder_for(tmp_path,'t',model['id']);anchor=folder/'batches'/bid
    request={'identityVersion':1,'tenantId':'t','masterId':model['id'],'batchId':bid,'sourceRevision':1,'draft':draft}
    identity,rows=b._identity(request,'t',model['id'],bid)
    b._once(anchor/'request.json',request)
    mock_verifier(monkeypatch);mock_publication(tmp_path,'t',model['id'],draft['selections'][0],revision=1,generation_id=rows[0]['generationId'])
    b._once(anchor/'0.json',b._row_receipt(identity,rows[0],'succeeded'))
    atomic_json(folder/'batches'/(bid+'.json'),{**identity,'rows':[{**r,'state':'succeeded' if i==0 else 'running','error':None} for i,r in enumerate(rows)]})
    queue_state(tmp_path,model,draft,bid,'running')
    service=RecipePreviewService(SimpleNamespace(root=tmp_path),folder_fn=c.folder_for,status_fn=c.status)
    state=service.status('t',model['id'],model)
    assert state['state']=='failed'
    result=b.current(tmp_path,'t',model['id'],bid,state['state'])
    assert result['state']=='interrupted'
    assert [r['state'] for r in result['rows']]==['succeeded','interrupted']
    assert not service.tasks
    queue_state(tmp_path,model,draft,bid,'succeeded')
    with pytest.raises(ValueError):b.current(tmp_path,'t',model['id'],bid,'succeeded')
    service.executor.shutdown()


def test_history_download_exact_generation_and_revocation(tmp_path,monkeypatch):
    model,asset,batch=setup(tmp_path);gid=new_id();folder=c.folder_for(tmp_path,'t',model['id'])/'generations'/gid
    manifest={'generationId':gid,'draft':c.snapshot(tmp_path,'t',model,batch['selections'][0]),
              'scene':'STUDIO','sourceRevision':1,'package':{'placements':[{'originalAssetId':asset['id']}]},
              'renderInfo':{'realBlender':True,'usedMock':False}}
    atomic_json(folder/'manifest.json',manifest);(folder/'beauty.png').write_bytes(b'fixture')
    # Isolate API identity/lifecycle checks; no REAL evidence claimed by this stub.
    monkeypatch.setattr(c.print_preview,'validate',lambda p:copy.deepcopy(manifest))
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    client=TestClient(app);url=f'/api/product-models/{model["id"]}/composition/files/beauty.png';params={'workspace':'t','generation':gid}
    assert client.get(url,params=params).status_code==200  # no latest pointer needed
    assert client.get(url,params={**params,'generation':new_id()}).status_code==409
    assert client.get(url,params={**params,'generation':'../escape'}).status_code==409
    assert client.get(url,params={**params,'workspace':'other'}).status_code==404
    manifest['draft']['masterId']=new_id();assert client.get(url,params=params).status_code==409
    manifest['draft']['masterId']=model['id']
    manifest['historyVersion']=1
    assert client.get(url,params=params).status_code==409
    manifest.pop('historyVersion')
    m.save(tmp_path,'t',{**model['draft'],'widthMm':101.},1,model['id'])
    assert client.get(url,params=params).status_code==409
    current=m.save(tmp_path,'t',model['draft'],2,model['id'])
    assert c.history(tmp_path,'t',model['id'],current)['items'][0]['available']
    asset_usage.classify(tmp_path,'t',asset['id'],'REFERENCE','revoked',1)
    assert not c.history(tmp_path,'t',model['id'],current)['items'][0]['available']
    assert client.get(url,params=params).status_code==409


def test_batch_api_rejects_mock_stale_and_unconfirmed(tmp_path):
    model,asset,batch=setup(tmp_path)
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    client=TestClient(app);url=f'/api/product-models/{model["id"]}/composition/batch';h={'X-Tenant-Id':'t'}
    body={'expectedRevision':1,'inputHash':model['inputHash'],'assumptionsAccepted':True,'batch':batch}
    assert client.post(url,headers=h,json=body).status_code==503
    body['expectedRevision']=2;assert client.post(url,headers=h,json=body).status_code==409
    body['expectedRevision']=1;body['assumptionsAccepted']=False
    assert client.post(url,headers=h,json=body).status_code==422


def test_queue_rejects_single_job_while_batch_owns_model(tmp_path):
    model,asset,batch=setup(tmp_path)
    service=RecipePreviewService(SimpleNamespace(root=tmp_path),folder_fn=c.folder_for,status_fn=c.status)
    service.tasks[('t',model['id'])]=(new_id(),Event())
    with pytest.raises(ValueError,match='已有生成工作'):
        service.submit('t',model['id'],{'draft':b.snapshot(tmp_path,'t',model,batch),'revision':1})
    service.executor.shutdown()

@pytest.fixture
def completed_batch(tmp_path,monkeypatch):
    model,asset,value=setup(tmp_path);draft=b.snapshot(tmp_path,'t',model,value);bid=new_id()
    mock_verifier(monkeypatch)
    monkeypatch.setattr(c,'generate',lambda platform,*a,**kw:mock_publication(platform.root,*a,**kw))
    queue_state(tmp_path,model,draft,bid)
    b.generate(SimpleNamespace(root=tmp_path),'t',model['id'],draft,revision=1,generation_id=bid)
    folder=c.folder_for(tmp_path,'t',model['id'])
    return model,asset,draft,bid,folder


@pytest.mark.parametrize('kind',[
    'batchId','tenantId','masterId','masterInputHash','sourceRevision','selectionHash',
    'version_missing','version_unknown','insert','delete','reorder','duplicate_gid','malformed_gid',
    'sku','scene','row_hash','row_index','truncated','invalid_json','missing_field','request_tamper',
    'service_hash','service_task','success_without_receipt','cancelled_resurrection','interrupted_resurrection'])
def test_durable_identity_tamper_fail_closed(tmp_path,completed_batch,kind):
    model,asset,draft,bid,folder=completed_batch;path=folder/'batches'/(bid+'.json')
    record=read_json(path);anchor=folder/'batches'/bid
    if kind in ['batchId','tenantId','masterId','masterInputHash','selectionHash']:record[kind]='tampered'
    if kind=='sourceRevision':record[kind]=9
    if kind=='version_missing':record.pop('identityVersion')
    if kind=='version_unknown':record['identityVersion']=99
    if kind=='insert':record['rows'].append(copy.deepcopy(record['rows'][0]))
    if kind=='delete':record['rows'].pop()
    if kind=='reorder':record['rows'].reverse()
    if kind=='duplicate_gid':record['rows'][1]['generationId']=record['rows'][0]['generationId']
    if kind=='malformed_gid':record['rows'][0]['generationId']='../../x'
    if kind=='sku':record['rows'][0]['sku']='changed'
    if kind=='scene':record['rows'][0]['scene']='COOL_ROOM'
    if kind=='row_hash':record['rows'][0]['selectionHash']='0'*64
    if kind=='row_index':record['rows'][0]['index']=1
    if kind=='missing_field':record['rows'][0].pop('generationId')
    if kind=='request_tamper':
        req=read_json(anchor/'request.json');req['draft']['name']='tampered';atomic_json(anchor/'request.json',req)
    if kind in ['service_hash','service_task']:
        state=read_json(folder/'state.json');state['inputHash' if kind=='service_hash' else 'taskId']='changed';atomic_json(folder/'state.json',state)
    if kind=='success_without_receipt':(anchor/'0.json').unlink()
    if kind in ['cancelled_resurrection','interrupted_resurrection']:
        terminal=read_json(anchor/'terminal.json');terminal['state']=kind.split('_')[0];atomic_json(anchor/'terminal.json',terminal)
    atomic_json(path,record)
    if kind=='truncated':path.write_text('{"batchId":',encoding='utf-8')
    if kind=='invalid_json':path.write_text('[]',encoding='utf-8')
    with pytest.raises(ValueError):b.current(tmp_path,'t',model['id'],bid,'succeeded')


@pytest.mark.parametrize('kind',['no_manifest','no_publication','seal_tamper','manifest_tamper','wrong_master',
                                  'wrong_selection','wrong_revision','revoked','stale'])
def test_completed_rows_require_exact_publication(tmp_path,completed_batch,kind):
    model,asset,draft,bid,folder=completed_batch;record=read_json(folder/'batches'/(bid+'.json'))
    gid=record['rows'][0]['generationId'];target=folder/'generations'/gid
    if kind=='no_manifest':(target/'manifest.json').unlink()
    if kind=='no_publication':(target/'published.json').unlink()
    if kind=='seal_tamper':atomic_json(target/'published.json',{'manifestSha256':'bad'})
    if kind in ['manifest_tamper','wrong_master','wrong_selection','wrong_revision']:
        manifest=read_json(target/'manifest.json')
        if kind in ['manifest_tamper','wrong_master']:manifest['draft']['masterId']=new_id()
        if kind=='wrong_selection':manifest['draft']['sku']='wrong'
        if kind=='wrong_revision':manifest['sourceRevision']=55
        atomic_json(target/'manifest.json',manifest)
        if kind!='manifest_tamper':atomic_json(target/'published.json',{'manifestSha256':sha256_bytes((target/'manifest.json').read_bytes())})
    if kind=='revoked':asset_usage.classify(tmp_path,'t',asset['id'],'REFERENCE','revoked',1)
    if kind=='stale':m.save(tmp_path,'t',{**model['draft'],'widthMm':101.},1,model['id'])
    result=b.current(tmp_path,'t',model['id'],bid,'succeeded')
    assert result['state']=='failed' and not result['available']
    assert result['rows'][0]['state']=='failed' and not result['rows'][0]['available']
    # API must also report failed, not the stale outer service's succeeded state.
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    client=TestClient(app);response=client.get(f'/api/product-models/{model["id"]}/composition',headers={'X-Tenant-Id':'t'})
    assert response.status_code==200 and response.json()['state']=='failed'
    assert client.get(f'/api/product-models/{model["id"]}/composition/files/beauty.png',params={'workspace':'t','generation':gid}).status_code==409 or kind in ['wrong_selection','wrong_revision']


def test_valid_durable_history_and_exclusive_replay_guard(tmp_path,completed_batch):
    model,asset,draft,bid,folder=completed_batch
    first=b.current(tmp_path,'t',model['id'],bid,'succeeded')
    assert first['available'] and all(r['available'] for r in first['rows'])
    atomic_json(folder/'latest.json',{'generationId':first['rows'][-1]['generationId']})
    service=RecipePreviewService(SimpleNamespace(root=tmp_path),folder_fn=c.folder_for,status_fn=c.status)
    status=service.status('t',model['id'],model)
    assert b.current(tmp_path,'t',model['id'],bid,status['state'])==first
    assert c.generation(tmp_path,'t',model['id'],first['rows'][0]['generationId'],model)
    with pytest.raises(FileExistsError):b.generate(SimpleNamespace(root=tmp_path),'t',model['id'],draft,revision=1,generation_id=bid)
    service.executor.shutdown()


@pytest.mark.parametrize('state,expected',[('failed','interrupted'),('cancelled','cancelled')])
def test_outer_interruption_never_becomes_success(tmp_path,completed_batch,state,expected):
    model,asset,draft,bid,folder=completed_batch
    queue_state(tmp_path,model,draft,bid,state)
    result=b.current(tmp_path,'t',model['id'],bid,state)
    assert result['state']==expected and all(r['available'] for r in result['rows'])


@pytest.mark.parametrize('task_id',[None,'../escape','00000000-0000-0000-0000-000000000000'])
def test_api_outer_task_identity_cannot_hide_batch(tmp_path,completed_batch,task_id):
    model,asset,draft,bid,folder=completed_batch
    state=read_json(folder/'state.json');state['taskId']=task_id;atomic_json(folder/'state.json',state)
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    response=TestClient(app).get(f'/api/product-models/{model["id"]}/composition',headers={'X-Tenant-Id':'t'})
    assert response.status_code==422


def test_synthetic_authority_is_explicit_and_never_physical(tmp_path,monkeypatch):
    model,asset,batch=setup(tmp_path)
    a.declare(tmp_path,'t',model,'SYNTHETIC_FIXTURE',actor='TEST_FIXTURE',reason='Generated test data, not measurement')
    draft=b.snapshot(tmp_path,'t',model,batch);bid=new_id()
    assert draft['selections'][0]['inputAuthority']['snapshot']['geometryAuthorityKind']=='SYNTHETIC_FIXTURE'
    mock_verifier(monkeypatch)
    monkeypatch.setattr(c,'generate',lambda platform,*args,**kw:mock_publication(platform.root,*args,**kw))
    queue_state(tmp_path,model,draft,bid)
    b.generate(SimpleNamespace(root=tmp_path),'t',model['id'],draft,revision=1,generation_id=bid)
    result=b.current(tmp_path,'t',model['id'],bid,'succeeded')
    for value in [result,*result['rows']]:
        assert all(value[key]==expected for key,expected in a.readiness(True).items())
    assert a.verify(tmp_path,'t',draft['selections'][0],current=True)['dimensionAuthorityStatus']=='UNMEASURED'


@pytest.mark.parametrize('change',['hash','missing_version','unknown_version','cross_tenant','forged_measured','reference_hash','artwork_revision','declaration_hash'])
def test_authority_snapshot_corruption_blocks_exact_publication(tmp_path,completed_batch,change):
    model,asset,draft,bid,folder=completed_batch
    selection=draft['selections'][0];binding=selection['inputAuthority']
    stored=a.folder(tmp_path,'t',model['id'])/'snapshots'/(binding['hash']+'.json')
    value=read_json(stored)
    if change=='hash':value['masterInputHash']='0'*64
    if change=='missing_version':value.pop('authorityVersion')
    if change=='unknown_version':value['authorityVersion']=99
    if change=='cross_tenant':value['tenantId']='other'
    if change=='forged_measured':value['geometryAuthorityKind']='MEASURED_OR_CAD_AUTHORITY'
    if change=='reference_hash':value['geometryReferenceHashes']['dimensionEvidence']='0'*64
    if change=='artwork_revision':value['artworkAuthority'][asset['id']]['revision']+=1
    if change=='declaration_hash':value['declarationHash']='0'*64
    atomic_json(stored,value)
    result=b.current(tmp_path,'t',model['id'],bid,'succeeded')
    assert not result['available'] and not result['visualAssetReady']
    assert all(not row['available'] for row in result['rows'])
    with pytest.raises(ValueError):c.generation(tmp_path,'t',model['id'],result['rows'][0]['generationId'],model)


@pytest.mark.parametrize('change',['missing_binding','hash','missing_version','unknown_version','cross_tenant','forged_measured'])
def test_authority_in_request_rejects_self_consistent_forgery(tmp_path,change):
    model,asset,batch=setup(tmp_path);draft=b.snapshot(tmp_path,'t',model,batch)
    binding=draft['selections'][0]['inputAuthority'];value=binding['snapshot']
    if change=='missing_binding':draft['selections'][0].pop('inputAuthority')
    if change=='hash':binding['hash']='0'*64
    if change=='missing_version':value.pop('authorityVersion')
    if change=='unknown_version':value['authorityVersion']=99
    if change=='cross_tenant':value['tenantId']='other'
    if change=='forged_measured':
        value['geometryAuthorityKind']=value['declaration']['kind']='MEASURED_OR_CAD_AUTHORITY'
        value['declarationHash']=stable_hash(value['declaration'])
    if change not in {'missing_binding','hash'}:binding['hash']=stable_hash(value)
    if change!='missing_binding':draft['authorityHash']=stable_hash([s['inputAuthority']['hash'] for s in draft['selections']])
    request={'identityVersion':1,'tenantId':'t','masterId':model['id'],'batchId':new_id(),'sourceRevision':1,'draft':draft}
    with pytest.raises((ValueError,KeyError)):b._identity(request,'t',model['id'],request['batchId'])


@pytest.mark.parametrize('action',['revoke','downgrade','missing_snapshot','missing_control','changed_artwork'])
def test_authority_revocation_and_disappearance_block_download(tmp_path,completed_batch,action):
    model,asset,draft,bid,folder=completed_batch;base=a.folder(tmp_path,'t',model['id'])
    if action=='revoke':a.revoke(tmp_path,'t',model['id'])
    if action=='downgrade':a.declare(tmp_path,'t',model,'OPERATOR_DECLARED_UNMEASURED',actor='operator',reason='Independent authority removed')
    if action=='missing_snapshot':(base/'snapshots'/(draft['selections'][0]['inputAuthority']['hash']+'.json')).unlink()
    if action=='missing_control':(base/'control.json').unlink()
    if action=='changed_artwork':asset_usage.classify(tmp_path,'t',asset['id'],'ARTWORK','New classification revision',1)
    result=b.current(tmp_path,'t',model['id'],bid,'succeeded')
    assert not result['visualAssetReady'] and not result['manufacturingReady']
    assert not any(row['available'] for row in result['rows'])
    assert not any(row['available'] for row in c.history(tmp_path,'t',model['id'],model)['items'])


def test_same_geometry_new_revision_is_not_current_but_exact_history_retained(tmp_path,completed_batch):
    model,asset,draft,bid,folder=completed_batch
    updated=m.save(tmp_path,'t',model['draft'],1,model['id'])
    result=b.current(tmp_path,'t',model['id'],bid,'succeeded')
    assert not result['available'] and not result['visualAssetReady']
    old=result['rows'][0]['generationId'];binding=copy.deepcopy(draft['selections'][0]['inputAuthority'])
    assert c.generation(tmp_path,'t',model['id'],old,updated)['draft']['inputAuthority']==binding
    # Submitting a new revision never rewrites historical authority.
    fresh=b.snapshot(tmp_path,'t',updated,{'name':'new','selections':[{'sku':'new','placements':[]}]})
    assert fresh['selections'][0]['inputAuthority']['hash']!=binding['hash']
    assert c.generation(tmp_path,'t',model['id'],old,updated)['draft']['inputAuthority']==binding


def test_category_metadata_does_not_upgrade_or_revoke_authority(tmp_path,completed_batch):
    model,asset,draft,bid,folder=completed_batch
    model_categories.save(tmp_path,'t',model['id'],'unclassified',0)
    result=b.current(tmp_path,'t',model['id'],bid,'succeeded')
    assert result['visualAssetReady'] and not result['physicalGeometryAuthorityReady']
    value=a.verify(tmp_path,'t',draft['selections'][0],current=True)
    assert value['classificationMetadata']['revision']==0 and not value['classificationMetadata']['geometryAuthority']
    assert value['geometryAuthorityKind']=='OPERATOR_DECLARED_UNMEASURED'


def test_measured_declaration_has_no_unreviewed_upgrade_path(tmp_path):
    model,asset,batch=setup(tmp_path)
    with pytest.raises(ValueError,match='CAD'):
        a.declare(tmp_path,'t',model,'MEASURED_OR_CAD_AUTHORITY',actor='AI / mock worker',reason='Blender dimensions and render SHA')


def test_reference_recipe_preserves_unmeasured_snapshot(tmp_path):
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    rows=TestClient(app).get('/api/product-models/recipe-references',headers={'X-Tenant-Id':'t'}).json()['items']
    model=m.save(tmp_path,'t',rows[0]['draft'],0)
    draft=b.snapshot(tmp_path,'t',model,{'name':'reference','selections':[{'sku':'reference','placements':[]}]})
    value=a.verify(tmp_path,'t',draft['selections'][0],current=True)
    assert value['geometryAuthorityKind']=='REFERENCE_RECIPE'
    assert value['dimensionAuthorityStatus']=='UNMEASURED'
    assert value['geometryReferenceHashes']['recipeReference']==stable_hash(model['draft']['recipeReference'])
    assert value['declaration']['provenance']['approvedBy'] is None


def test_mutable_progress_cannot_invent_physical_readiness(tmp_path,completed_batch):
    model,asset,draft,bid,folder=completed_batch;path=folder/'batches'/(bid+'.json');record=read_json(path)
    for value in [record,*record['rows']]:value.update({key:True for key in a.readiness()})
    atomic_json(path,record)
    result=b.current(tmp_path,'t',model['id'],bid,'succeeded')
    for value in [result,*result['rows']]:assert all(value[k]==v for k,v in a.readiness(True).items())
