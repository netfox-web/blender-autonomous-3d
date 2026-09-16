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
from fox3d.ids import new_id
from fox3d.product_models_api import product_models_router
from fox3d.recipe_3d import atomic_json
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
        return {'generated':True,'stale':False,'generationId':kwargs['generation_id']}
    monkeypatch.setattr(c,'generate',fake)
    bid=new_id()
    with pytest.raises(ValueError,match='取消'):b.generate(platform,'t',model['id'],snapshot,generation_id=bid,cancel_flag=stop)
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
        return {'generated':True,'stale':False,'generationId':kwargs['generation_id']}
    monkeypatch.setattr(c,'generate',fake);bid=new_id()
    with pytest.raises(ValueError):b.generate(SimpleNamespace(root=tmp_path),'t',model['id'],snapshot,generation_id=bid)
    record=b.current(tmp_path,'t',model['id'],bid,'failed')
    assert record['rows'][-1]['state']=='failed'
    assert len(seen)==(2 if change=='failure' else 1)


def test_restart_does_not_resume_or_claim_success(tmp_path):
    model,asset,batch=setup(tmp_path);bid=new_id();folder=c.folder_for(tmp_path,'t',model['id'])
    atomic_json(folder/'state.json',{'taskId':bid,'state':'running'})
    atomic_json(folder/'batches'/(bid+'.json'),{'rows':[{'state':'succeeded'},{'state':'running'},{'state':'queued'}]})
    service=RecipePreviewService(SimpleNamespace(root=tmp_path),folder_fn=c.folder_for,status_fn=c.status)
    state=service.status('t',model['id'],model)
    assert state['state']=='failed'
    assert [r['state'] for r in b.current(tmp_path,'t',model['id'],bid,state['state'])['rows']]==['succeeded','interrupted','interrupted']
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
