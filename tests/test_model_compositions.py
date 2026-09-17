import copy
import hashlib
import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import RectangleObject

from fox3d import model_compositions as c, product_models as m, print_assets, asset_usage, durability
from fox3d.product_models_api import product_models_router


def setup(tmp_path, size=(400,200)):
    raw=io.BytesIO();Image.new('RGB',size,'red').save(raw,'PNG')
    asset=print_assets.import_asset(tmp_path,'t',raw.getvalue(),'fixture.png')
    asset_usage.classify(tmp_path,'t',asset['id'],'ARTWORK','Synthetic artwork fixture',0)
    model=m.save(tmp_path,'t',{'name':'fixture panel','family':'coaster','geometry':'RECTANGLE',
        'widthMm':100.,'depthMm':5.,'heightMm':50.,'dimensionEvidence':'Synthetic mm',
        'structureEvidence':'Synthetic rectangular flat panel'},0)
    selection={'sku':'A','scene':'STUDIO','placements':[{'componentId':'surface','assetId':asset['id']}]}
    return model,asset,selection


def test_art_and_scene_keep_geometry_identity(tmp_path):
    model,a,s=setup(tmp_path);first=c.snapshot(tmp_path,'t',model,s)
    s['scene']='WARM_ROOM';s['sku']='B';second=c.snapshot(tmp_path,'t',model,s)
    p,q=c.plan(tmp_path,'t',first),c.plan(tmp_path,'t',second)
    assert p['engineeringHash']==q['engineeringHash'] and p['selectionHash']!=q['selectionHash']
    assert p['spec']['components']==q['spec']['components']
    assert not p['physicalPrintValidated']
    out=tmp_path/'prepared';out.mkdir()
    _,spec,package,inputs,_=c.prepare(tmp_path,'t',second,out)
    assert len(inputs)==1 and package['placements'][0]['targetWidthMm']==100
    assert Image.open(out/'surface-preview.png').size==(400,200)


@pytest.mark.parametrize('change',[{'componentId':'bad'},{'page':1},{'rotation':90}])
def test_wrong_surface_page_and_aspect_are_rejected(tmp_path,change):
    model,a,s=setup(tmp_path);s['placements'][0].update(change)
    with pytest.raises(ValueError):c.snapshot(tmp_path,'t',model,s)


def test_rotation_can_match_without_stretch(tmp_path):
    model,a,s=setup(tmp_path,size=(200,400));s['placements'][0]['rotation']=90
    d=c.snapshot(tmp_path,'t',model,s);out=tmp_path/'out';out.mkdir()
    c.prepare(tmp_path,'t',d,out)
    assert Image.open(out/'surface-preview.png').size==(400,200)


def test_pdf_trim_and_rotation(tmp_path):
    model,a,s=setup(tmp_path);writer=PdfWriter();page=writer.add_blank_page(width=120,height=220)
    page.trimbox=RectangleObject([10,10,110,210]);page.rotate(90)
    stream=io.BytesIO();writer.write(stream)
    a=print_assets.import_asset(tmp_path,'t',stream.getvalue(),'trim.pdf')
    asset_usage.classify(tmp_path,'t',a['id'],'ARTWORK','Synthetic blank PDF trim fixture',0)
    s['placements'][0]['assetId']=a['id'];d=c.snapshot(tmp_path,'t',model,s)
    out=tmp_path/'out';out.mkdir();_,_,pkg,_,_=c.prepare(tmp_path,'t',d,out)
    box=pkg['placements'][0]['derivedPreviewCropPx']
    assert box[0]>0 and box[1]>0
    im=Image.open(out/'surface-preview.png');assert abs(im.width/im.height-2)<.01


def test_reference_revocation_and_other_tenant_denied(tmp_path):
    model,a,s=setup(tmp_path)
    with pytest.raises((ValueError,OSError)):c.snapshot(tmp_path,'other',model,s)
    asset_usage.classify(tmp_path,'t',a['id'],'REFERENCE','Revoked synthetic fixture',1)
    with pytest.raises(ValueError):c.snapshot(tmp_path,'t',model,s)


def test_duplicate_and_unrecognized_scene_rejected(tmp_path):
    model,a,s=setup(tmp_path);s['placements']*=2
    with pytest.raises(ValueError):c.snapshot(tmp_path,'t',model,s)
    s['placements']=[];s['scene']='AI_FREE_FORM'
    with pytest.raises(ValueError):c.snapshot(tmp_path,'t',model,s)


def test_cabinet_surfaces_label_top_to_bottom_without_reordering_geometry():
    draft={'name':'cabinet','family':'cabinet','geometry':'HINGED_CABINET','widthMm':424.,'depthMm':295.,'heightMm':900.,
           'panelMm':15.,'backMm':3.,'doorMm':15.,'gapMm':2.,'rows':3,'dimensionEvidence':'fixture','structureEvidence':'fixture'}
    faces=c.surfaces(draft)
    assert faces[0]['componentId']=='door_3'
    assert next(f for f in faces if f['componentId']=='door_3')['label']=='上方第 1 片門'
    assert next(f for f in faces if f['componentId']=='door_1')['widthMm']==390.


def test_api_guards_before_submission(tmp_path):
    item,a,s=setup(tmp_path);app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    client=TestClient(app);path='/api/product-models/'+item['id']+'/composition';h={'X-Tenant-Id':'t'}
    state=client.get(path,headers=h).json();assert len(state['surfaces'])==1 and not state['generated']
    body={'expectedRevision':1,'inputHash':item['inputHash'],'assumptionsAccepted':True,'selection':s}
    assert client.post(path,headers=h,json=body).status_code==503
    body['expectedRevision']=2;assert client.post(path,headers=h,json=body).status_code==409
    body['expectedRevision']=1;body['assumptionsAccepted']=False
    assert client.post(path,headers=h,json=body).status_code==422
    assert client.get(path,headers={'X-Tenant-Id':'other'}).status_code==404
    assert client.get(path+'/files/model.glb?workspace=t&generation=bad').status_code==409


def test_corrupt_or_revoked_composition_never_downloadable(tmp_path,monkeypatch):
    model,a,s=setup(tmp_path);base=c.folder_for(tmp_path,'t',model['id'])
    from fox3d.recipe_3d import atomic_json
    gid='00000000-0000-0000-0000-000000000000';atomic_json(base/'latest.json',{'generationId':gid})
    assert not c.status(tmp_path,'t',model['id'],current_draft=model)['generated']
    manifest={'draft':{'masterInputHash':model['inputHash']},'package':{'placements':[{'originalAssetId':a['id']}]}}
    monkeypatch.setattr(c.print_preview,'validate',lambda folder:manifest)
    assert c.status(tmp_path,'t',model['id'],current_draft=model)['generated']
    changed={**model,'inputHash':'0'*64};assert c.status(tmp_path,'t',model['id'],current_draft=changed)['stale']
    asset_usage.classify(tmp_path,'t',a['id'],'REFERENCE','Revoked fixture after generation',1)
    assert not c.status(tmp_path,'t',model['id'],current_draft=model)['generated']


def test_commit_indeterminate_derived_publication_stops_before_authority(tmp_path, monkeypatch):
    model, asset, selection = setup(tmp_path)
    draft = c.snapshot(tmp_path, 't', model, selection)
    spec = {'width': 100., 'depth': 5., 'height': 50., 'components': []}
    monkeypatch.setattr(c, 'prepare', lambda *args: ({'selectionHash': 'plan'}, spec,
                                                       {'packageHash': 'package'}, [], {}))
    class Dam:
        def __init__(self, path):
            self.path = path
            self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            self.metadata = {'bytes': path.stat().st_size}
    files = {}
    for name in c.print_preview.FILES:
        path = tmp_path / ('source-' + name)
        path.write_bytes(b'complete-worker-artifact')
        files[name] = name
    platform = SimpleNamespace(root=tmp_path, mock_blender=False,
                               runtime=SimpleNamespace(available=lambda: True),
                               probe=SimpleNamespace(optix=True))
    platform.submit_job = lambda payload: {'jobId': 'worker-job'}
    platform.execute_job = lambda job, **kwargs: {'status': 'completed', 'realBlender': True,
        'usedMock': False, 'output': {'files': files, 'realBlender': True, 'usedMock': False,
                                      'device': 'OPTIX', 'blenderVersion': '5.2.1 LTS', 'realOptix': True}}
    platform.dam = SimpleNamespace(get=lambda ref, tenant_id: Dam(tmp_path / ('source-' + ref)))
    def indeterminate(source, target, **kwargs):
        raise durability.CommitIndeterminate(target, 'replace', OSError(5, 'injected sync'))
    monkeypatch.setattr(c, 'publish_binary', indeterminate)
    with pytest.raises(durability.CommitIndeterminate):
        c.generate(platform, 't', model['id'], draft, revision=0,
                   generation_id='11111111-1111-1111-1111-111111111111')
    base = c.folder_for(tmp_path, 't', model['id'])
    generation = base / 'generations' / '11111111-1111-1111-1111-111111111111'
    assert not (generation / 'manifest.json').exists()
    assert not (generation / 'published.json').exists()
    assert not (base / 'latest.json').exists()


def test_worker_receipt_tamper_before_manifest_fails_closed(tmp_path, monkeypatch):
    model, asset, selection = setup(tmp_path)
    draft = c.snapshot(tmp_path, 't', model, selection)
    spec = {'width': 100., 'depth': 5., 'height': 50., 'components': []}
    monkeypatch.setattr(c, 'prepare', lambda *args: ({'selectionHash': 'plan'}, spec,
                                                       {'packageHash': 'package'}, [], {}))
    class Dam:
        def __init__(self, path):
            self.path = path; self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            self.metadata = {'bytes': path.stat().st_size}
    files = {}
    for name in c.print_preview.FILES:
        path = tmp_path / ('source-' + name)
        path.write_bytes(b'{"jobId":"worker-job"}' if name == 'golden-observation.json' else b'complete-worker-artifact')
        files[name] = name
    platform = SimpleNamespace(root=tmp_path, mock_blender=False,
                               runtime=SimpleNamespace(available=lambda: True),
                               probe=SimpleNamespace(optix=True))
    platform.submit_job = lambda payload: {'jobId': 'worker-job'}
    platform.execute_job = lambda job, **kwargs: {'status': 'completed', 'realBlender': True,
        'usedMock': False, 'output': {'files': files, 'realBlender': True, 'usedMock': False,
                                      'device': 'OPTIX', 'blenderVersion': '5.2.1 LTS', 'realOptix': True}}
    platform.dam = SimpleNamespace(get=lambda ref, tenant_id: Dam(tmp_path / ('source-' + ref)))
    original = c.publish_binary
    def tamper(source, target, **kwargs):
        receipt = original(source, target, **kwargs)
        target.write_bytes(b'tampered-after-receipt')
        return receipt
    monkeypatch.setattr(c, 'publish_binary', tamper)
    monkeypatch.setattr(c.print_preview, 'validate', lambda folder: {'status': 'test'})
    with pytest.raises(ValueError, match='receipt'):
        c.generate(platform, 't', model['id'], draft, generation_id='22222222-2222-2222-2222-222222222222')
    generation = c.folder_for(tmp_path, 't', model['id']) / 'generations' / '22222222-2222-2222-2222-222222222222'
    assert not (generation / 'manifest.json').exists()
    assert not (generation / 'published.json').exists()
    assert not (c.folder_for(tmp_path, 't', model['id']) / 'latest.json').exists()


def test_derived_receipt_tamper_before_package_fails_closed(tmp_path, monkeypatch):
    model, asset, selection = setup(tmp_path)
    draft = c.snapshot(tmp_path, 't', model, selection)
    out = tmp_path / 'out'; out.mkdir()
    original = c.publish_bytes
    def tamper(writer, target, **kwargs):
        receipt = original(writer, target, **kwargs)
        target.write_bytes(b'tampered-derived')
        return receipt
    monkeypatch.setattr(c, 'publish_bytes', tamper)
    with pytest.raises(ValueError, match='receipt'):
        c.prepare(tmp_path, 't', draft, out)

def test_existing_recipe_snapshots_keep_original_geometry_and_assumptions(tmp_path):
    from fox3d.recipe_3d import build_recipe_spec
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    client=TestClient(app);rows=client.get('/api/product-models/recipe-references',headers={'X-Tenant-Id':'t'}).json()['items']
    assert len(rows)==3
    for row in rows:
        draft=row['draft'];before=copy.deepcopy(draft['recipeReference'])
        original=build_recipe_spec(draft['recipeReference']['draft']);spec=m.build_spec(draft)
        assert [(p['size'],p['location']) for p in original['components']]==[(p['size'],p['location']) for p in spec['components']]
        assert draft['recipeReference']==before and not spec['productionReady']
        assert any('假設' in x or '暫' in x for x in spec['previewAssumptions'])
        draft['widthMm']+=1
        with pytest.raises(ValueError,match='外尺寸不可分開修改'):m.build_spec(draft)
