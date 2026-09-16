"""MOCK regression of scene identity and placement; not REAL render evidence."""
import copy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from fox3d import model_compositions as c, model_batches as batches, scene_templates as scenes
from fox3d.product_models_api import product_models_router
from test_model_compositions import setup


def fixture(tmp_path, scene='LIVING_ROOM', **options):
    model, asset, selection=setup(tmp_path)
    selection.update(scene=scene,**options)
    draft=c.snapshot(tmp_path,'t',model,selection)
    plan=c.plan(tmp_path,'t',draft)
    return model,draft,plan


@pytest.mark.parametrize('scene',['LIVING_ROOM','KITCHEN'])
def test_room_changes_context_not_product_or_uv(tmp_path,scene):
    model,draft,p=fixture(tmp_path,scene)
    studio=c.snapshot(tmp_path,'t',model,{'sku':'A','scene':'STUDIO','placements':draft['placements']})
    q=c.plan(tmp_path,'t',studio)
    assert p['engineeringHash']==q['engineeringHash']
    assert p['spec']['components']==q['spec']['components']
    a,b=tmp_path/'room',tmp_path/'studio';a.mkdir();b.mkdir()
    _,_,pkg,_=c.prepare(tmp_path,'t',draft,a)
    _,_,pkg2,_=c.prepare(tmp_path,'t',studio,b)
    assert pkg==pkg2
    assert (a/'surface-preview.png').read_bytes()==(b/'surface-preview.png').read_bytes()
    definition=p['spec']['sceneDefinition']
    assert definition['slot']=='SURFACE' and definition['productScale']==1.
    assert definition['supportHeightM']==(.46 if scene=='LIVING_ROOM' else .9)
    assert definition['productMatrix'][2][1]==1  # artwork -Y normal faces upward


@pytest.mark.parametrize('change',['hash','version','pose','mesh','missing','scale','environment'])
def test_observation_tamper_fail_closed(tmp_path,change):
    _,draft,p=fixture(tmp_path);definition=p['spec']['sceneDefinition'];part=p['spec']['components'][0]
    pose=copy.deepcopy(definition['productMatrix']);loc=part['location']
    matrix=copy.deepcopy(pose)
    for i in range(3):matrix[i][3]=sum(pose[i][j]*loc[j] for j in range(3))+pose[i][3]
    m={'draft':draft,'spec':p['spec'],'sceneHash':draft['sceneHash']}
    actual={k:definition[k] for k in ['templateId','version','slot','view','productMatrix','productScale','physicalRoomTruth']}
    actual.update(sceneHash=draft['sceneHash'],environmentCount=len(definition['boxes']),
                  products=[{'componentId':part['componentId'],'linkedMesh':True,'matrixWorld':matrix}])
    scenes.validate_observation(m,{'presentationScene':actual})
    if change=='hash':actual['sceneHash']='0'*64
    if change=='version':m['spec']['sceneDefinition']['version']=2
    if change=='pose':actual['products'][0]['matrixWorld'][2][3]+=.1
    if change=='mesh':actual['products'][0]['linkedMesh']=False
    if change=='missing':actual['products']=[]
    if change=='scale':actual['productScale']=.8
    if change=='environment':actual['environmentCount']=0
    with pytest.raises(ValueError):scenes.validate_observation(m,{'presentationScene':actual})


def test_template_revision_invalidates_queued_snapshot(tmp_path,monkeypatch):
    model,draft,p=fixture(tmp_path);original=scenes.resolve
    def changed(*args,**kw):
        d=original(*args,**kw);d['version']=2;return d
    monkeypatch.setattr(scenes,'resolve',changed)
    with pytest.raises(ValueError,match='場景版本'):c.plan(tmp_path,'t',draft)


@pytest.mark.parametrize('scene',['LIVING_ROOM','KITCHEN'])
def test_mat_lies_on_floor_without_scaling(tmp_path,scene):
    model,a,s=setup(tmp_path);model['draft']['family']='mat'
    s.update(scene=scene,placement='FLOOR')
    draft=c.snapshot(tmp_path,'t',model,s)
    definition=c.plan(tmp_path,'t',draft)['spec']['sceneDefinition']
    assert definition['supportHeightM']==0. and definition['productScale']==1.
    pose=definition['productMatrix']
    # The two thickness faces become bottom/top exactly at z=0 and z=5 mm.
    assert pose[2][1]*(-.0025)+pose[2][3]==0.
    assert pose[2][1]*(.0025)+pose[2][3]==.005


@pytest.mark.parametrize('case',['wrong_slot','oversize','unsupported','invalid_view','unknown_scene'])
def test_invalid_room_placement_rejected(tmp_path,case):
    model,a,s=setup(tmp_path);s['scene']='KITCHEN'
    if case=='wrong_slot':s['placement']='FLOOR'
    if case=='oversize':model['draft']['widthMm']=1000.
    if case=='unsupported':model['draft']['family']='curtain'
    if case=='invalid_view':s['view']='BACK'
    if case=='unknown_scene':s['scene']='UNVERIFIED_UPLOAD'
    with pytest.raises(ValueError):c.snapshot(tmp_path,'t',model,s)


def test_batch_accepts_same_sku_different_views_rejects_exact_duplicate(tmp_path):
    model,a,s=setup(tmp_path);s['scene']='LIVING_ROOM'
    batch={'name':'room variants','selections':[s,{**s,'view':'LEFT'}]}
    result=batches.snapshot(tmp_path,'t',model,batch)
    assert result['selections'][0]['sceneHash']!=result['selections'][1]['sceneHash']
    batch['selections'].append(copy.deepcopy(s))
    with pytest.raises(ValueError):batches.snapshot(tmp_path,'t',model,batch)


def test_scene_library_and_submission_api_guards(tmp_path):
    model,a,s=setup(tmp_path)
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    client=TestClient(app);headers={'X-Tenant-Id':'t'}
    data=client.get('/api/product-models/scenes',headers=headers).json()
    assert {x['id'] for x in data['items']}=={'LIVING_ROOM','KITCHEN'}
    assert all(not x['physicalRoomTruth'] for x in data['items'])
    s.update(scene='KITCHEN',placement='FLOOR')
    url='/api/product-models/'+model['id']+'/composition'
    body={'expectedRevision':1,'inputHash':model['inputHash'],'assumptionsAccepted':True,'selection':s}
    assert client.post(url,headers=headers,json=body).status_code==422
    s['placement']='SURFACE'
    assert client.post(url,headers=headers,json=body).status_code==503  # no mock render through operator UI
