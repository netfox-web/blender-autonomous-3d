import copy
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject, DecodedStreamObject, NameObject

from fox3d import print_assets as assets, print_workspace as jobs, print_preview as preview, asset_usage
from fox3d.print_api import print_router
from fox3d.recipe_3d import atomic_json, read_json
from fox3d.ids import sha256_bytes


def pdf_bytes(*, offset=0, rotation=0, crop=False):
    writer=PdfWriter()
    for n in range(3):
        pg=writer.add_blank_page(width=286*jobs.PT,height=401*jobs.PT)
        pg.mediabox=RectangleObject([offset,offset,offset+286*jobs.PT,offset+401*jobs.PT])
        pg.trimbox=RectangleObject([offset+3*jobs.PT,offset+3*jobs.PT,offset+283*jobs.PT,offset+398*jobs.PT])
        if crop:pg.cropbox=RectangleObject(pg.trimbox)
        content=DecodedStreamObject();content.set_data(f'q 0 1 1 0 k {offset+10} {offset+20} 40 80 re f Q'.encode())
        pg[NameObject('/Contents')]=writer._add_object(content)
        pg.rotate(rotation)
    out=io.BytesIO();writer.write(out);return out.getvalue()


def setup_job(root, **kwargs):
    a=assets.import_asset(root,'test',pdf_bytes(**kwargs),'source.ai')
    asset_usage.classify(root,'test',a['id'],'ARTWORK','Synthetic vector pattern fixture',0)
    d={'sku':'TEST-001','name':'測試門櫃','layout':'THREE_DOOR','rip':'Test RIP','machine':'Test only machine','substrate':'Test board',
       'panels':[{'label':str(i+1),'assetId':a['id'],'page':i,'rotation':90} for i in range(3)]}
    j=jobs.save_job(root,'test',d);return j,jobs.plan(root,'test',j['draft'])


def release_data(j,p,b):
    return {'expectedRevision':j['revision'],'planHash':p['planHash'],'proofId':b['bundleId'],'operator':'TEST OPERATOR',
            'measurementRecord':'SYNTHETIC TEST ONLY measurement','testPrintRecord':'SYNTHETIC TEST ONLY print record',
            **{k:True for k in ['dimensionsChecked','orderAndOrientationChecked','bleedAndKeepOutChecked','colorWhiteVarnishTestPassed','ripScale100Confirmed']}}


@pytest.mark.parametrize('offset,rotation',[(0,0),(50,0),(50,90),(0,270)])
def test_native_pdf_mm_trim_rotation_and_vector_content(tmp_path,offset,rotation):
    j,p=setup_job(tmp_path,offset=offset,rotation=rotation)
    w,h=(401,286) if rotation in (0,180) else (286,401)
    row=p['panels'][0]
    assert [row['widthMm'],row['heightMm']]==pytest.approx([w,h])
    assert [row['trimWidthMm'],row['trimHeightMm']]==pytest.approx([w-6,h-6])
    b=jobs.export_bundle(tmp_path,'test',j['id'],expected_revision=1,plan_hash=p['planHash'])
    path,m=jobs.bundle_download(tmp_path,'test',j['id'],b['bundleId'])
    with zipfile.ZipFile(path) as z:
        handoff=json.loads(z.read('netfox-handoff.json'))
        assert handoff['integrationStatus']=='FILE_HANDOFF_ONLY_NOT_SUBMITTED'
        assert not handoff['liveMachineControl']
        pdf=PdfReader(io.BytesIO(z.read('PROOF_TEST-001_panel-1.pdf'))).pages[0]
        assert b' re' in pdf.get_contents().get_data() # vector content, not flattened pixels
        assert 'PROOF - NOT FOR PRINT' in pdf.extract_text()
        assert [float(v)/jobs.PT for v in pdf.trimbox]==pytest.approx([3,3,w-3,h-3])
    assert not m['productionReady']


def test_full_media_thumbnail_and_clockwise_orientation(tmp_path):
    raw=pdf_bytes(crop=True);a=assets.import_asset(tmp_path,'test',raw,'crop.pdf')
    thumb=Image.open(io.BytesIO(assets.thumbnail(tmp_path,'test',a['id'])))
    assert thumb.width/thumb.height==pytest.approx(286/401,abs=.002)
    # Match the screen preview rotation to the actual output PDF rendering.
    import pypdfium2 as pdfium
    pg,owner=jobs.panel_page(raw,a,jobs.Panel(label='x',assetId=a['id'],rotation=90))
    w=PdfWriter();w.add_page(pg);buf=io.BytesIO();w.write(buf)
    with pdfium.PdfDocument(buf.getvalue()) as doc:
        pg=doc[0];bitmap=pg.render(scale=1000/max(pg.get_size()));actual=bitmap.to_pil().convert('RGB').copy();bitmap.close();pg.close()
    rotated=thumb.rotate(-90,expand=True)
    def colored_center(im):
        im=im.resize((160,160));points=[(x,y) for y in range(160) for x in range(160) if im.getpixel((x,y))[0]>150 and im.getpixel((x,y))[1]<100]
        assert points
        return [sum(t[i] for t in points)/len(points) for i in range(2)]
    assert colored_center(actual)==pytest.approx(colored_center(rotated),abs=1)


@pytest.mark.parametrize('key',['dimensionsChecked','orderAndOrientationChecked','bleedAndKeepOutChecked','colorWhiteVarnishTestPassed','ripScale100Confirmed'])
def test_release_requires_every_human_check(tmp_path,key):
    j,p=setup_job(tmp_path);b=jobs.export_bundle(tmp_path,'test',j['id'],expected_revision=1,plan_hash=p['planHash'])
    r=release_data(j,p,b);r[key]=False
    with pytest.raises(ValueError,match='全部'):jobs.export_bundle(tmp_path,'test',j['id'],expected_revision=1,plan_hash=p['planHash'],release=r)


def test_release_proof_version_and_edit_invalidation(tmp_path):
    j,p=setup_job(tmp_path);b=jobs.export_bundle(tmp_path,'test',j['id'],expected_revision=1,plan_hash=p['planHash'])
    r=release_data(j,p,b)
    approved=jobs.export_bundle(tmp_path,'test',j['id'],expected_revision=1,plan_hash=p['planHash'],release=r)
    path,m=jobs.bundle_download(tmp_path,'test',j['id'],approved['bundleId'])
    assert m['approvalAuthority']=='USER_ATTESTATION'
    assert 'PROOF - NOT FOR PRINT' not in PdfReader(path.parent/'panel-1.pdf').pages[0].extract_text()
    d=copy.deepcopy(j['draft']);d['panels'][0]['rotation']=270
    jobs.save_job(tmp_path,'test',d,jid=j['id'],expected_revision=1)
    with pytest.raises(ValueError,match='過期'):jobs.bundle_download(tmp_path,'test',j['id'],approved['bundleId'])
    with pytest.raises(ValueError,match='版本已變更'):jobs.save_job(tmp_path,'test',d,jid=j['id'],expected_revision=1)
    p2=jobs.plan(tmp_path,'test',d);r.update(expectedRevision=2,planHash=p2['planHash'])
    with pytest.raises(ValueError,match='校稿'):jobs.export_bundle(tmp_path,'test',j['id'],expected_revision=2,plan_hash=p2['planHash'],release=r)


def test_artifact_tampering_and_tenant_isolation(tmp_path):
    j,p=setup_job(tmp_path);b=jobs.export_bundle(tmp_path,'test',j['id'],expected_revision=1,plan_hash=p['planHash'])
    with pytest.raises(ValueError):jobs.get_job(tmp_path,'other',j['id'])
    path,m=jobs.bundle_download(tmp_path,'test',j['id'],b['bundleId'])
    (path.parent/'panel-1.pdf').write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='已變更'):jobs.bundle_download(tmp_path,'test',j['id'],b['bundleId'])
    aid=j['draft']['panels'][0]['assetId'];folder=assets.workspace(tmp_path,'test')/'assets'/aid
    meta=read_json(folder/'asset.json');meta['info']['pages'][0]['widthMm']=1
    atomic_json(folder/'asset.json',meta)
    with pytest.raises(ValueError,match='紀錄'):assets.asset(tmp_path,'test',aid)


def test_source_paths_cannot_escape_config(tmp_path):
    src=tmp_path/'source';src.mkdir();(src/'a.pdf').write_bytes(pdf_bytes())
    root=tmp_path/'data';assert assets.scan_source(root,src)==1
    _,items=assets.source_catalog(root);assert assets.source_bytes(root,items[0]['id'])[0].startswith(b'%PDF')
    (tmp_path/'outside.pdf').write_bytes(pdf_bytes());items[0]['path']='../outside.pdf'
    atomic_json(root/'print-source-index.json',{'items':items})
    with pytest.raises(ValueError,match='範圍'):assets.source_bytes(root,items[0]['id'])
    for value in ['../x','a'*63,'/etc/passwd']:
        with pytest.raises(ValueError):assets.asset(root,'test',value)


def test_raster_cmyk_pixels_and_no_stretch(tmp_path):
    im=Image.new('CMYK',(1200,800),(30,40,50,60));buf=io.BytesIO();im.save(buf,format='TIFF')
    a=assets.import_asset(tmp_path,'test',buf.getvalue(),'CMYK.tif')
    panel=jobs.Panel(label='test',assetId=a['id'],rotation=90,imageWidthMm=80.,imageHeightMm=120.,imageBleedMm=3.)
    pg,owner=jobs.panel_page(buf.getvalue(),a,panel,raster=True)
    image=pg['/Resources']['/XObject']['/Im']
    assert image['/ColorSpace']=='/DeviceCMYK'
    assert image.get_data()==im.rotate(-90,expand=True).tobytes()
    assert float(pg.trimbox.width)/jobs.PT==pytest.approx(74)
    for bad in [{'imageWidthMm':100.},{'imageWidthMm':800.,'imageHeightMm':1200.}]:
        p=panel.model_copy(update=bad)
        with pytest.raises(ValueError):jobs.panel_page(buf.getvalue(),a,p,raster=True)


@pytest.mark.parametrize('field,value',[('rotation',45),('quantity',0),('imageWidthMm',float('nan')),('page',-1)])
def test_panel_rejects_invalid_values(field,value):
    with pytest.raises(ValueError):jobs.Panel.model_validate({'label':'test','assetId':'a'*64,field:value})


def test_transparency_and_unknown_physical_size_blocked(tmp_path):
    im=Image.new('RGBA',(1000,1000),(100,100,100,0));buf=io.BytesIO();im.save(buf,format='PNG')
    a=assets.import_asset(tmp_path,'test',buf.getvalue(),'alpha.png')
    with pytest.raises(ValueError,match='透明'):jobs.panel_page(buf.getvalue(),a,jobs.Panel(label='x',assetId=a['id'],imageWidthMm=100.,imageHeightMm=100.))


def test_preview_geometry_and_source_lineage(tmp_path):
    j,p=setup_job(tmp_path);folder=tmp_path/'preview';folder.mkdir()
    spec,package,inputs,_=preview.prepare(tmp_path,'test',p,folder)
    doors=[c for c in spec['components'] if c['role']=='door']
    assert all(c['sizeMm']==pytest.approx([395.,15.,280.]) for c in doors)
    assert len(inputs)==3
    assert [c['sourcePage'] for c in package['placements']]==[0,1,2]
    assert all(c['originalAssetId']==j['draft']['panels'][0]['assetId'] for c in package['placements'])
    d=copy.deepcopy(j['draft']);d['layout']='FLAT';d['panels']=d['panels'][:1]
    flat=preview.geometry(jobs.plan(tmp_path,'test',d))
    assert len(flat['components'])==1 and flat['components'][0]['sizeMm']==pytest.approx([395.,15.,280.])


def test_api_upload_job_proof_and_no_dispatch(tmp_path):
    platform=SimpleNamespace(root=tmp_path,mock_blender=True,runtime=SimpleNamespace(available=lambda:False))
    app=FastAPI();app.include_router(print_router(lambda:platform));c=TestClient(app,headers={'X-Tenant-Id':'test'})
    assert c.get('/admin/recipes/print').status_code==200
    assert c.get('/api/print-workspace/sources',headers={'X-Tenant-Id':''}).status_code==422
    a=c.post('/api/print-workspace/assets/upload',files={'file':('source.ai',pdf_bytes(),'application/pdf')}).json()
    assert c.get('/api/print-workspace/assets/'+a['id']+'/preview?workspace=test').headers['content-type']=='image/png'
    d={'sku':'API-TEST','name':'測試商品','layout':'FLAT','panels':[{'label':'門片','assetId':a['id'],'rotation':90}]}
    assert c.post('/api/print-workspace/jobs',json={'draft':d}).status_code==422
    asset_usage.classify(tmp_path,'test',a['id'],'ARTWORK','Synthetic API fixture, purpose reviewed',0)
    j=c.post('/api/print-workspace/jobs',json={'draft':d}).json();path='/api/print-workspace/jobs/'+j['id']
    j=c.get(path).json();version={'expectedRevision':1,'planHash':j['plan']['planHash']}
    assert c.post(path+'/preview',json=version).status_code==503
    assert c.post(path+'/proof',json={**version,'expectedRevision':2}).status_code==422
    b=c.post(path+'/proof',json=version);assert b.status_code==200,b.text
    assert c.get(path+'/bundles/'+b.json()['bundleId']+'?workspace=test').status_code==200
    assert c.get(path,headers={'X-Tenant-Id':'other'}).status_code==422
    assert all('dispatch' not in path and 'hotfolder' not in path for path in c.get('/openapi.json').json()['paths'])
