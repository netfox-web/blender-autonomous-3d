import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from fox3d import asset_usage as usage, print_assets, product_models, print_workspace
from fox3d.product_models_api import product_models_router
from fox3d.recipe_3d import read_json
from fox3d.recipe_workbench import DraftConflict


def source(root, tenant='t', nas=True):
    out=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=300,height=400);writer.write(out)
    raw=out.getvalue()
    a=print_assets.import_asset(root,tenant,raw,'reference.pdf',{'type':'NAS_PRODUCT_CATALOG'} if nas else None)
    return a,raw


def model(a):
    return {'name':'fixture','family':'mat','variants':[{'sku':'A','artworkAssetId':a['id']}]}


def print_draft(a):
    return {'name':'fixture','sku':'A','layout':'FLAT','panels':[{'label':'front','assetId':a['id']}]}


@pytest.mark.parametrize('role',['UNCLASSIFIED','REFERENCE','DIMENSION','DIELINE','PACKAGING'])
def test_non_artwork_blocked_in_model_and_print_backend(tmp_path,role):
    a,raw=source(tmp_path)
    usage.classify(tmp_path,'t',a['id'],role,'Synthetic classification evidence',0)
    with pytest.raises(ValueError,match='不可作為套圖'):product_models.save(tmp_path,'t',model(a),0)
    with pytest.raises(ValueError,match='不可作為套圖'):print_workspace.plan(tmp_path,'t',print_draft(a))
    assert print_assets.asset(tmp_path,'t',a['id'])[1]==raw


def test_legacy_nas_default_deny_and_explicit_artwork_can_save(tmp_path):
    a,_=source(tmp_path)
    assert not usage.usage(tmp_path,'t',a)['canUseForPrint']
    assert not usage.usage(tmp_path,'t',a)['canUseForModel']
    usage.classify(tmp_path,'t',a['id'],'ARTWORK','Reviewed fixture pattern, no promotional layout',0)
    assert product_models.save(tmp_path,'t',model(a),0)['revision']==1
    assert print_workspace.plan(tmp_path,'t',print_draft(a))['panels']
    assert not usage.usage(tmp_path,'t',a)['physicalPrintValidated']


def test_revision_history_reimport_and_duplicate_upload_do_not_erase_classification(tmp_path):
    a,raw=source(tmp_path)
    usage.classify(tmp_path,'t',a['id'],'REFERENCE','Product photo with captions',0)
    with pytest.raises(DraftConflict):usage.classify(tmp_path,'t',a['id'],'ARTWORK','stale change',0)
    print_assets.import_asset(tmp_path,'t',raw,'renamed-artwork.pdf')
    assert usage.usage(tmp_path,'t',a)['role']=='REFERENCE'
    usage.classify(tmp_path,'t',a['id'],'DIMENSION','Photo contains reference dimensions',1)
    assert read_json(usage.folder(tmp_path,'t',a['id'])/'usage-history/1.json')['role']=='REFERENCE'
    assert usage.listing(tmp_path,'t')[0]['usage']['revision']==2


def test_upload_and_legacy_assets_require_classification_too(tmp_path):
    a,raw=source(tmp_path,nas=False)
    assert not usage.usage(tmp_path,'t',a)['canUseForPrint']
    with pytest.raises(ValueError):print_workspace.plan(tmp_path,'t',print_draft(a))
    usage.classify(tmp_path,'t',a['id'],'REFERENCE','Reviewed photograph',0)
    print_assets.import_asset(tmp_path,'t',raw,'renamed.pdf')
    with pytest.raises(ValueError):print_workspace.plan(tmp_path,'t',print_draft(a))


def test_reclassification_blocks_model_generation_and_existing_proof_download(tmp_path):
    a,_=source(tmp_path)
    usage.classify(tmp_path,'t',a['id'],'ARTWORK','Fixture pattern',0)
    j=print_workspace.save_job(tmp_path,'t',print_draft(a))
    plan=print_workspace.plan(tmp_path,'t',j['draft'])
    bundle=print_workspace.export_bundle(tmp_path,'t',j['id'],expected_revision=1,plan_hash=plan['planHash'])
    usage.classify(tmp_path,'t',a['id'],'REFERENCE','Correction: promotional image',1)
    with pytest.raises(ValueError):print_workspace.bundle_download(tmp_path,'t',j['id'],bundle['bundleId'])
    with pytest.raises(ValueError):product_models.generate(SimpleNamespace(root=tmp_path),'t','unused',model(a))


def test_api_tenant_conflict_invalid_purpose_and_no_direct_save_bypass(tmp_path):
    a,_=source(tmp_path)
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=tmp_path)))
    c=TestClient(app);h={'X-Tenant-Id':'t'};path='/api/product-models/assets/'+a['id']+'/usage'
    body={'role':'REFERENCE','note':'Observed promotional layout','expectedRevision':0}
    assert c.get('/api/product-models/assets').status_code==422
    assert c.put(path,headers={'X-Tenant-Id':'other'},json=body).status_code==422
    assert c.put(path,headers=h,json={**body,'role':'GUESSED'}).status_code==422
    assert c.put(path,headers=h,json={**body,'note':' '}).status_code==422
    assert c.put(path,headers=h,json=body).status_code==200
    assert c.put(path,headers=h,json=body).status_code==409
    assert c.post('/api/product-models',headers=h,json={'draft':model(a),'expectedRevision':0}).status_code==422
    rows=c.get('/api/product-models/assets',headers=h).json()
    assert len(rows['roles'])==6 and rows['items'][0]['usage']['role']=='REFERENCE'
