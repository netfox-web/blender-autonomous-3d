import copy
import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from fox3d import nas_catalog as nas, product_models as m, recipe_3d as render
from fox3d.product_models_api import product_models_router
from fox3d.ids import sha256_bytes
from fox3d.recipe_workbench import DraftConflict

def cabinet():
    return {'name':'TEST cabinet','family':'cabinet','subtype':'open','geometry':'OPEN_CABINET',
        'widthMm':424.,'depthMm':295.,'heightMm':900.,'panelMm':15.,'backMm':3.,'rows':3,
        'dimensionEvidence':'Synthetic engineering fixture, mm','structureEvidence':'Single column, equal openings, inset back'}

def configured(tmp_path):
    source=tmp_path/'source';(source/'DN0123 cabinet'/'print').mkdir(parents=True)
    buf=io.BytesIO();Image.new('RGB',(100,100),'blue').save(buf,'PNG');raw=buf.getvalue()
    path=source/'DN0123 cabinet'/'print'/'65x45 貼紙.png';path.write_bytes(raw)
    data=tmp_path/'data';render.atomic_json(data/'nas-catalog-config.json',{'sources':[{'id':'wood','family':'cabinet','path':str(source)}]})
    return data,source,path,raw

def test_readonly_inventory_groups_no_inferred_dimensions(tmp_path):
    data,source,path,raw=configured(tmp_path)
    result=nas.scan(data);assert result['fileCount']==1
    snapshot=nas.checked_snapshot(data);g=snapshot['groups'][0]
    assert not g['isVerifiedProduct'] and g['skuCandidates']==['DN0123']
    assert 'widthMm' not in g
    asset=nas.import_file(data,'t',snapshot['files'][0]['id'])
    assert asset['id']==sha256_bytes(raw) and path.read_bytes()==raw
    assert not asset['provenance']['physicalDimensionsVerified']
    nas.scan(data);assert nas.snapshot(data)['files'][0]['id']==snapshot['files'][0]['id']

def test_changed_config_cannot_reuse_source_id(tmp_path):
    data,source,path,raw=configured(tmp_path);nas.scan(data);sid=nas.snapshot(data)['files'][0]['id']
    render.atomic_json(data/'nas-catalog-config.json',{'sources':[]})
    with pytest.raises(ValueError,match='設定已變更'):nas.import_file(data,'t',sid)

def test_failed_scan_preserves_last_complete_snapshot(tmp_path):
    data,source,path,raw=configured(tmp_path);nas.scan(data);before=(data/'nas-catalog-index.json').read_bytes()
    path.unlink();path.parent.rmdir();path.parent.parent.rmdir();source.rmdir()
    with pytest.raises(OSError):nas.scan(data)
    assert (data/'nas-catalog-index.json').read_bytes()==before

def test_source_escape_and_non_artwork_rejected(tmp_path):
    data,source,path,raw=configured(tmp_path);nas.scan(data);s=nas.snapshot(data)
    s['files'][0]['path']='../outside.png';(source.parent/'outside.png').write_bytes(raw)
    render.atomic_json(data/'nas-catalog-index.json',s)
    with pytest.raises(ValueError,match='超出'):nas.import_file(data,'t',s['files'][0]['id'])

@pytest.mark.parametrize('name,expected',[('兩抽床邊櫃','bedside'),('床頭櫃','bedside'),('三層門櫃','hinged'),('三層空櫃','open'),('書櫃','bookcase'),('未知','other')])
def test_wood_subtype(name,expected):assert nas.subtype(name)==expected

def test_drafts_missing_data_tenant_isolation_revision_history(tmp_path):
    a=m.save(tmp_path,'t',{'name':'噴瓶','family':'spray_bottle'},0)
    assert not a['readiness']['previewReady'] and not a['productionReady']
    with pytest.raises(KeyError):m.get(tmp_path,'other',a['id'])
    draft=a['draft'];draft['notes']='Need curved surface and actual dimensions'
    b=m.save(tmp_path,'t',draft,1,a['id']);assert b['revision']==2
    with pytest.raises(DraftConflict):m.save(tmp_path,'t',draft,1,a['id'])
    old=render.read_json(m.directory(tmp_path,'t')/a['id']/'revisions'/'1.json')
    assert old['draft']['notes']==''

@pytest.mark.parametrize('key,value',[('widthMm',float('nan')),('heightMm',float('inf')),('depthMm',0.),('rows',1.5),('panelMm',-3.)])
def test_nonfinite_invalid_geometry_rejected(key,value):
    d=cabinet();d[key]=value
    with pytest.raises(ValueError):m.build_spec(d)

def test_no_generic_box_substituted_for_bottle_or_storage_box():
    for family in ['spray_bottle','mask_box','storage_box_50']:
        with pytest.raises(ValueError):m.Master(name='product',family=family,geometry='RECTANGLE')
    d=cabinet();d['structureEvidence']=' '
    assert not m.readiness(d)['previewReady']

def test_geometry_mm_identity_and_bounds():
    spec=m.build_spec(cabinet());assert len(spec['components'])==7
    for p in spec['components']:
        assert p['size']==[v/1000 for v in p['sizeMm']]
        assert p['location']==[v/1000 for v in p['locationMm']]
        for i,bound in enumerate([424,295,900]):
            lo=p['locationMm'][i]-p['sizeMm'][i]/2;hi=p['locationMm'][i]+p['sizeMm'][i]/2
            assert lo>=(-bound/2 if i<2 else 0)-1e-8
            assert hi<=(bound/2 if i<2 else bound)+1e-8
    d=cabinet();d.update(geometry='HINGED_CABINET',doorMm=15.,gapMm=2.)
    assert len(m.build_spec(d)['components'])==10
    d['widthMm']=25.
    assert not m.readiness(d)['previewReady']

def test_model_identity_changes_for_dimensions_but_not_claims_print_ready(tmp_path):
    d=cabinet();a=m.save(tmp_path,'t',d,0);d['widthMm']=425.;b=m.save(tmp_path,'t',d,1,a['id'])
    assert a['inputHash']!=b['inputHash']
    assert b['readiness']['previewReady'] and not b['readiness']['printReady']
    d['printFaces']=[{'name':'front','widthMm':100.,'heightMm':200.,'evidence':'drawing'}]
    c=m.save(tmp_path,'t',d,2,a['id']);assert not c['readiness']['printReady']

def test_foreign_artwork_and_duplicate_skus_rejected(tmp_path):
    d=cabinet();d['variants']=[{'sku':'A','artworkAssetId':'a'*64}]
    with pytest.raises((ValueError,KeyError,OSError)):m.save(tmp_path,'t',d,0)
    d['variants']=[{'sku':'A'},{'sku':'A'}]
    with pytest.raises(ValueError):m.save(tmp_path,'t',d,0)

def test_api_missing_tenant_stale_generation_and_mock_gate(tmp_path):
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path,mock_blender=True)))
    c=TestClient(app);h={'X-Tenant-Id':'t'}
    assert c.get('/admin/recipes/models').status_code==200
    assert c.get('/api/product-models').status_code==422
    a=c.post('/api/product-models',headers=h,json={'draft':cabinet(),'expectedRevision':0}).json()
    url='/api/product-models/'+a['id'];payload={'expectedRevision':1,'inputHash':a['inputHash'],'assumptionsAccepted':True}
    assert c.post(url+'/preview',headers=h,json=payload).status_code==503
    payload['expectedRevision']=2;assert c.post(url+'/preview',headers=h,json=payload).status_code==409
    assert c.get(url,headers={'X-Tenant-Id':'other'}).status_code==404
    assert c.get(url+'/files/glb?workspace=t&generation=../../x').status_code==409
    payload.update(expectedRevision=1,assumptionsAccepted=False)
    assert c.post(url+'/preview',headers=h,json=payload).status_code==422
