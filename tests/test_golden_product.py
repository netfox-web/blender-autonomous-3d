import copy
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.golden_product import (SKUS, GoldenRecipe, Measurement, build_golden, package_plan,
    validate_package, materialize_package, validate_worker_observation)
from fox3d.golden_preview import plan, folder_for, generate, status
from fox3d.golden_api import golden_router
from fox3d.ids import stable_hash
from fox3d.artwork import decode_png_rgb, crop_rgb
from fox3d.recipe_preview_service import RecipePreviewService
from fox3d.recipe_3d import atomic_json, input_hash


def test_mm_geometry_and_manufacturing_scope():
    g=build_golden();parts=g['spec']['components']
    assert len(parts)==10
    assert sum(p['role']=='shelf' for p in parts)==2
    doors=[p for p in parts if p['role']=='door']
    assert [p['componentId'] for p in doors]==['door_1','door_2','door_3']
    assert [p['locationMm'][2] for p in doors]==[745.,450.,155.]
    assert all(p['sizeMm']==[390.,15.,276.] for p in doors)
    assert [s['originTopMm'][1] for s in g['surfaces']]==[0.,295.,590.]
    assert not g['truth']['engineeringReady'] and not g['truth']['productionReady']
    assert not g['manufacturing']['manufacturingReady']
    assert g['manufacturing']['wasteRemnantInput']['wastePercent'] is None
    for axis,extent in enumerate([424,295,900]):
        positions=[p['locationMm'][axis]+sign*p['sizeMm'][axis]/2 for p in parts for sign in [-1,1]]
        assert max(positions)-min(positions)==extent


def test_measurement_schema_replacement_requires_evidence():
    with pytest.raises(ValueError):Measurement(value=15.,truth='VERIFIED',evidence='drawing')
    m=Measurement(value=18.,truth='VERIFIED',evidence='verified drawing',evidenceSha256='a'*64)
    g=build_golden(GoldenRecipe(boardThicknessMm=m))
    assert g['engineeringHash']!=build_golden()['engineeringHash']
    assert not g['truth']['engineeringReady'] # hardware still unknown


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1.,0.,6000.])
def test_invalid_measurements(value):
    with pytest.raises(ValueError):Measurement(value=value,evidence='config')


def test_impossible_configuration():
    with pytest.raises(ValueError):GoldenRecipe(boardThicknessMm=Measurement(value=225.,evidence='config'))


def test_four_skus_share_engineering_not_artwork():
    packages=[package_plan(s,'FIXTURE_MASTER_V1') for s in SKUS]
    assert len({p['engineeringHash'] for p in packages})==1
    assert len({p['artworkHash'] for p in packages})==4
    assert len({p['packageHash'] for p in packages})==4
    for s in SKUS:
        original=package_plan(s,'HISTORICAL_PENDING')
        assert not original['ready'] and original['truth']=='BLOCKED'
        assert all(row['sourcePath'] is None for row in original['slots'])


def test_print_policy_does_not_change_engineering():
    a=build_golden();b=build_golden(GoldenRecipe(safeMm=8.,bleedMm=4.))
    assert a['engineeringHash']==b['engineeringHash']
    assert a['spec']['components']==b['spec']['components']
    assert a['surfaces'][0]['surfaceHash']!=b['surfaces'][0]['surfaceHash']


@pytest.mark.parametrize('version',['FIXTURE_MASTER_V1','FIXTURE_SINGLE_V1'])
def test_crops_no_stretch_and_pixels(tmp_path,version):
    p=package_plan(SKUS[0],version)
    items,production=materialize_package(tmp_path,p)
    assert len(items)==3 and len(production)==3
    for item,record in zip(items,production):
        sw,sh,rgb=decode_png_rgb((tmp_path/item['source']['name']).read_bytes())
        c=item['cropPx'];w,h,actual=decode_png_rgb((tmp_path/record['file']).read_bytes())
        assert actual==crop_rgb(rgb,sw,sh,c['x'],c['y'],c['width'],c['height'])
        u=item['uvRect']
        assert (u['u1']-u['u0'])*sw==pytest.approx(w)
        assert (u['v1']-u['v0'])*sh==pytest.approx(h)
    if version=='FIXTURE_MASTER_V1':
        assert p['masterCanvasMm']==[390.,866.]
        assert p['seamsMm']==[19.,19.]
        for a,b in zip(p['placements'],p['placements'][1:]):
            assert (a['uvRect']['v0']-b['uvRect']['v1'])*866==pytest.approx(19.)
    else:
        assert len({p['artworkSha256'] for p in items})==3


@pytest.mark.parametrize('tamper',['wrong-door','uv-shift','crop-shift','door-order','engineering','artwork','seam','master-order','cross-sku','rehash'])
def test_package_tampers_fail_closed(tamper):
    p=package_plan(SKUS[0],'FIXTURE_MASTER_V1');q=copy.deepcopy(p)
    if tamper=='wrong-door':q['placements'][0]['componentId']='door_2'
    elif tamper=='uv-shift':q['placements'][0]['uvRect']['u0']+=.01
    elif tamper=='crop-shift':q['placements'][0]['cropPx']['y']+=1
    elif tamper=='door-order':q['placements'].reverse()
    elif tamper=='engineering':q['engineeringHash']='b'*64
    elif tamper=='artwork':q['artworkHash']='b'*64
    elif tamper=='seam':q['seamsMm'][0]=0
    elif tamper=='master-order':q['doorOrder']='BOTTOM_TO_TOP'
    elif tamper=='cross-sku':q=package_plan(SKUS[1],'FIXTURE_MASTER_V1')
    else:
        q['placements'][0]['cropMm']['yMm']+=1
        q['packageHash']=stable_hash({k:v for k,v in q.items() if k!='packageHash'})
    with pytest.raises(ValueError):validate_package(q,sku=SKUS[0],version='FIXTURE_MASTER_V1')


def observed_fixture():
    g=build_golden();p=package_plan(SKUS[0],'FIXTURE_MASTER_V1')
    o={'realBlender':True,'usedMock':False,'jobId':'unit-worker-job','sku':SKUS[0],'engineeringHash':p['engineeringHash'],'packageHash':p['packageHash'],
       'parts':[{'componentId':x['componentId'],'size':x['size'],'location':x['location']} for x in g['spec']['components']],
       'artwork':[{**x,'observedCorners':x['finalSampling'],'packedImageSha256':x['source']['fileSha256']} for x in p['placements']]}
    return g,p,o # synthetic contract fixture, not live evidence


@pytest.mark.parametrize('tamper',['uv','size','texture','mock','nan','duplicate','order'])
def test_worker_readback_tamper(tamper):
    g,p,o=observed_fixture();validate_worker_observation(o,p,g['spec'])
    o=copy.deepcopy(o)
    if tamper=='uv':o['artwork'][0]['observedCorners'][0][0]+=.001
    elif tamper=='size':o['parts'][0]['size'][0]/=2
    elif tamper=='texture':o['artwork'][0]['packedImageSha256']='0'*64
    elif tamper=='mock':o['usedMock']=True
    elif tamper=='nan':o['parts'][0]['location'][0]=float('nan')
    elif tamper=='duplicate':o['parts'][1]=o['parts'][0]
    else:o['artwork'].reverse()
    with pytest.raises(ValueError):validate_worker_observation(o,p,g['spec'])


def test_api_preflight_mock_and_isolation(tmp_path):
    plat=SimpleNamespace(root=tmp_path,mock_blender=True,runtime=SimpleNamespace(available=lambda:True))
    app=FastAPI();app.include_router(golden_router(lambda:plat))
    headers={'X-Tenant-Id':'test'};base='/api/recipe-library/golden/'+SKUS[0]
    with TestClient(app) as c:
        assert c.get('/admin/recipes/golden').status_code==200
        assert c.get(base+'/plan').status_code==400
        p=c.get(base+'/plan',headers=headers,params={'version':'FIXTURE_MASTER_V1'}).json()
        body={'version':'FIXTURE_MASTER_V1','planHash':p['planHash'],'assumptionsAccepted':True}
        assert c.post(base+'/generate',headers=headers,json=body).status_code==503
        body['planHash']='old'
        assert c.post(base+'/generate',headers=headers,json=body).status_code==409
        body['version']='HISTORICAL_PENDING'
        assert c.post(base+'/generate',headers=headers,json=body).status_code==422
        assert c.get(base+'/download/blend',params={'generation':'../bad','workspace':'test'}).status_code==404
        assert c.get(base+'/download/blend',params={'generation':'a'*36,'workspace':'other'}).status_code==409
    assert folder_for(tmp_path,'a',SKUS[0])!=folder_for(tmp_path,'b',SKUS[0])


def test_golden_lifecycle_cancel_and_restart(tmp_path):
    started=threading.Event()
    def render(*args,**kwargs):
        started.set();kwargs['cancel_flag'].wait(3);raise ValueError('cancelled')
    service=RecipePreviewService(SimpleNamespace(root=tmp_path),folder_fn=folder_for,status_fn=status,generate_fn=render)
    draft=plan(SKUS[0],'FIXTURE_MASTER_V1')['draft']
    task=service.submit('t',SKUS[0],{'draft':draft,'revision':0})
    assert started.wait(1)
    with pytest.raises(ValueError):service.submit('t',SKUS[0],{'draft':draft,'revision':0})
    service.cancel('t',SKUS[0],task['taskId']);service.executor.shutdown(wait=True)
    assert service.status('t',SKUS[0],draft)['state']=='cancelled'
    atomic_json(folder_for(tmp_path,'t',SKUS[0])/'state.json',
                {'state':'running','taskId':task['taskId'],'inputHash':input_hash(draft)})
    assert service.status('t',SKUS[0],draft)['state']=='failed'


@pytest.fixture
def serialized_generation(tmp_path,monkeypatch):
    # Synthetic file contract only. The real runner separately reopens .blend.
    from fox3d import golden_preview as gp
    from fox3d.ids import sha256_bytes
    from fox3d.pngutil import write_png
    g,p,o=observed_fixture()
    _,production=materialize_package(tmp_path,p,g)
    atomic_json(tmp_path/'golden-observation.json',o)
    atomic_json(tmp_path/'geometry.json',{'parts':o['parts']})
    for name in ['beauty.png','front-closed.png','door-detail.png']:
        write_png(tmp_path/name,800,800,bytes([80,100,120])*800*800)
    for name in ['model.blend','model.glb']:(tmp_path/name).write_bytes(b'SYNTHETIC_CONTRACT_FIXTURE')
    files={f.name:{'sha256':sha256_bytes(f.read_bytes()),'sizeBytes':f.stat().st_size} for f in tmp_path.iterdir()}
    m={'sku':SKUS[0],'version':'FIXTURE_MASTER_V1','engineeringHash':g['engineeringHash'],
       'package':p,'spec':g['spec'],'production':production,'files':files,'truth':g['truth'],'jobId':'unit-worker-job',
       'manufacturing':g['manufacturing'],'artworkTruth':'FIXTURE','renderInfo':{'realBlender':True,'usedMock':False},
       'views':{'HERO_45':'beauty.png','FRONT_CLOSED':'front-closed.png','DOOR_DETAIL':'door-detail.png','FRONT_OPEN':'BLOCKED'}}
    atomic_json(tmp_path/'manifest.json',m)
    monkeypatch.setattr(gp,'validate_outputs',lambda *args:None)
    gp.validate_generation(tmp_path,SKUS[0],'FIXTURE_MASTER_V1')
    return tmp_path,m


@pytest.mark.parametrize('tamper',['bytes','missing','crop-lineage','truth-promotion','mock-promotion','open-view','cross-sku','rehashed-crop'])
def test_serialized_artifacts_fail_closed(serialized_generation,tamper):
    from fox3d.golden_preview import validate_generation
    from fox3d.ids import sha256_bytes
    folder,m=serialized_generation
    if tamper=='bytes':(folder/'model.glb').write_bytes(b'broken')
    elif tamper=='missing':(folder/'front-closed.png').unlink()
    elif tamper=='crop-lineage':m['production'][0]['finalUvHash']='0'*64
    elif tamper=='truth-promotion':m['truth']['engineeringReady']=True
    elif tamper=='mock-promotion':m['renderInfo']['usedMock']=True
    elif tamper=='open-view':m['views']['FRONT_OPEN']='front-closed.png'
    elif tamper=='cross-sku':m['package']['sku']=SKUS[1]
    else:
        destination=folder/'door_1-production-trim.png'
        destination.write_bytes((folder/'door_2-production-trim.png').read_bytes())
        m['files'][destination.name]={'sha256':sha256_bytes(destination.read_bytes()),'sizeBytes':destination.stat().st_size}
    atomic_json(folder/'manifest.json',m)
    with pytest.raises((ValueError,OSError)):validate_generation(folder,SKUS[0],'FIXTURE_MASTER_V1')


def test_render_cache_binds_sku_and_artwork(tmp_path):
    from fox3d.infra import job_cache_key
    jobs=[]
    plat=SimpleNamespace(root=tmp_path,mock_blender=False,runtime=SimpleNamespace(available=lambda:True),probe=None)
    def submit(job):
        jobs.append(job);return {**job,'jobId':'test-job'}
    plat.submit_job=submit
    plat.execute_job=lambda *a,**k:{'status':'failed','error':'test-stop'}
    for sku,version in [(SKUS[0],'FIXTURE_MASTER_V1'),(SKUS[1],'FIXTURE_MASTER_V1'),(SKUS[0],'FIXTURE_SINGLE_V1')]:
        with pytest.raises(ValueError,match='test-stop'):
            generate(plat,'t',sku,plan(sku,version)['draft'])
    assert len({job_cache_key(j,blender_version='fixture') for j in jobs})==3


def test_cancel_during_cache_return_never_publishes(tmp_path):
    stop=threading.Event()
    plat=SimpleNamespace(root=tmp_path,mock_blender=False,runtime=SimpleNamespace(available=lambda:True),probe=None)
    plat.submit_job=lambda j:{**j,'jobId':'cached-request'}
    def cached(*a,**k):
        stop.set();return {'status':'completed','realBlender':True,'usedMock':False,'cacheHit':True}
    plat.execute_job=cached
    with pytest.raises(ValueError,match='取消'):
        generate(plat,'t',SKUS[0],plan(SKUS[0],'FIXTURE_MASTER_V1')['draft'],cancel_flag=stop)
    assert not (folder_for(tmp_path,'t',SKUS[0])/'meta.json').exists()
