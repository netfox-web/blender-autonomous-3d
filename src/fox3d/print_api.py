"""Local Chinese artwork/print UI; never dispatches a production job."""
import re
from pathlib import Path
from threading import RLock

from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Query
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from pypdf.errors import PdfReadError
from PIL import Image

from fox3d import print_assets as assets, print_workspace as jobs, print_preview as preview, asset_usage
from fox3d.recipe_3d import read_json
from fox3d.recipe_preview_service import RecipePreviewService


class Save(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    draft:jobs.PrintDraft
    expectedRevision:int=Field(default=0,ge=0)


class Version(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    expectedRevision:int=Field(ge=1)
    planHash:str=Field(pattern=r'^[a-f0-9]{64}$')


class Cancel(BaseModel):
    taskId:str


def print_router(provider):
    r=APIRouter();services={};lock=RLock()
    from fox3d.printfox_api import printfox_router
    r.include_router(printfox_router(provider))
    def root():return provider().root
    def call(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except (ValueError,OSError,KeyError,TypeError,IndexError,PdfReadError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
            raise HTTPException(422,str(exc)[:500]) from exc
    def tid(value):
        call(assets.workspace,root(),value);return value
    def service():
        platform=provider()
        with lock:
            if platform.root not in services:
                services[platform.root]=RecipePreviewService(platform,folder_fn=preview.folder_for,status_fn=preview.status,generate_fn=preview.generate)
            return services[platform.root]
    def checked(jid,t,body):
        j=call(jobs.get_job,root(),t,jid);p=call(jobs.plan,root(),t,j['draft'])
        if j['revision']!=body.expectedRevision or p['planHash']!=body.planHash:raise HTTPException(409,'版本已變更，請重新載入')
        return j

    @r.get('/admin/recipes/print',response_class=HTMLResponse)
    def page():
        return HTMLResponse((Path(__file__).with_name('static')/'print-workspace.html').read_text(encoding='utf-8'),
                            headers={'Content-Security-Policy':"default-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"})

    @r.get('/api/print-workspace/sources')
    def sources(q:str='',offset:int=Query(0,ge=0),x_tenant_id:str|None=Header(None)):
        tid(x_tenant_id);config,items=assets.source_catalog(root())
        filtered=[i for i in items if q.casefold() in i['path'].casefold()]
        return {'configured':bool(config),'total':len(filtered),'offset':offset,'items':filtered[offset:offset+60]}

    @r.post('/api/print-workspace/sources/refresh')
    def refresh(x_tenant_id:str|None=Header(None)):
        tid(x_tenant_id);config,_=assets.source_catalog(root())
        if not config:raise HTTPException(422,'尚未設定來源資料夾')
        return {'total':call(assets.scan_source,root(),config['sourceRoot'])}

    @r.post('/api/print-workspace/sources/{sid}/import')
    def import_source(sid:str,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);raw,item=call(assets.source_bytes,root(),sid)
        return call(assets.import_asset,root(),t,raw,item['name'],{'type':'CONFIGURED_READ_ONLY_SOURCE','sourceId':sid,'relativePath':item['path']})

    @r.post('/api/print-workspace/assets/upload')
    async def upload(file:UploadFile=File(...),x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);raw=bytearray()
        while chunk:=await file.read(1024*1024):
            raw.extend(chunk)
            if len(raw)>assets.MAX_BYTES:raise HTTPException(413,'原稿上限 150 MB')
        return call(assets.import_asset,root(),t,bytes(raw),file.filename or 'artwork')

    @r.get('/api/print-workspace/assets')
    def listing(x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);folder=assets.workspace(root(),t)/'assets'
        return {'items':call(asset_usage.listing,root(),t)}

    @r.get('/api/print-workspace/assets/{aid}/preview')
    def image(aid:str,workspace:str,page:int=0):
        t=tid(workspace)
        return Response(call(assets.thumbnail,root(),t,aid,page),media_type='image/png',headers={'Cache-Control':'private, max-age=3600'})

    @r.get('/api/print-workspace/jobs')
    def listing_jobs(x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);folder=assets.workspace(root(),t)/'jobs'
        return {'items':sorted([read_json(f) for f in folder.glob('*/job.json')],key=lambda j:j['updatedAt'],reverse=True)}

    @r.post('/api/print-workspace/jobs')
    def create(body:Save,x_tenant_id:str|None=Header(None)):
        return call(jobs.save_job,root(),tid(x_tenant_id),body.draft.model_dump(),expected_revision=body.expectedRevision)

    @r.get('/api/print-workspace/jobs/{jid}')
    def get(jid:str,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);j=call(jobs.get_job,root(),t,jid)
        p=call(jobs.plan,root(),t,j['draft'])
        return {**j,'plan':p,'spec':preview.geometry(p),'blenderAvailable':not provider().mock_blender and provider().runtime.available()}

    @r.put('/api/print-workspace/jobs/{jid}')
    def save(jid:str,body:Save,x_tenant_id:str|None=Header(None)):
        return call(jobs.save_job,root(),tid(x_tenant_id),body.draft.model_dump(),jid=jid,expected_revision=body.expectedRevision)

    @r.post('/api/print-workspace/jobs/{jid}/proof')
    def proof(jid:str,body:Version,x_tenant_id:str|None=Header(None)):
        return call(jobs.export_bundle,root(),tid(x_tenant_id),jid,expected_revision=body.expectedRevision,plan_hash=body.planHash)

    @r.post('/api/print-workspace/jobs/{jid}/release')
    def release(jid:str,body:jobs.Release,x_tenant_id:str|None=Header(None)):
        return call(jobs.export_bundle,root(),tid(x_tenant_id),jid,expected_revision=body.expectedRevision,plan_hash=body.planHash,release=body.model_dump())

    @r.get('/api/print-workspace/jobs/{jid}/bundles/{bid}')
    def download(jid:str,bid:str,workspace:str):
        path,m=call(jobs.bundle_download,root(),tid(workspace),jid,bid)
        return FileResponse(path,filename=f'{m["kind"]}-{m["plan"]["draft"]["sku"]}-{bid[:8]}.zip',headers={'Cache-Control':'no-store'})

    @r.post('/api/print-workspace/jobs/{jid}/preview')
    def generate(jid:str,body:Version,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);j=checked(jid,t,body)
        if provider().mock_blender or not provider().runtime.available():raise HTTPException(503,'真實 Blender 不可用')
        return call(service().submit,t,jid,j)

    @r.get('/api/print-workspace/jobs/{jid}/preview')
    def preview_status(jid:str,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);j=call(jobs.get_job,root(),t,jid)
        return call(service().status,t,jid,j['draft'])

    @r.post('/api/print-workspace/jobs/{jid}/preview/cancel')
    def cancel(jid:str,body:Cancel,x_tenant_id:str|None=Header(None)):
        return call(service().cancel,tid(x_tenant_id),jid,body.taskId)

    @r.get('/api/print-workspace/jobs/{jid}/preview/{gid}/{name}')
    def preview_file(jid:str,gid:str,name:str,workspace:str):
        t=tid(workspace)
        if not re.fullmatch(r'[a-f0-9-]{36}',gid) or name not in preview.FILES:raise HTTPException(404)
        folder=preview.folder_for(root(),t,jid)/'generations'/gid
        j=call(jobs.get_job,root(),t,jid)
        call(jobs.plan,root(),t,j['draft'])
        manifest=call(preview.validate,folder)
        call(jobs.plan,root(),t,manifest['draft'])
        return FileResponse(folder/name,filename=None if name.endswith('.png') else name,headers={'Cache-Control':'no-store'})
    return r
