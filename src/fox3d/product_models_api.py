"""Local operator UI for NAS source discovery and versioned product models."""
from pathlib import Path
from threading import RLock

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from filelock import Timeout
from pydantic import Field
from pypdf.errors import PdfReadError
from PIL import Image

from fox3d import nas_catalog as nas, product_models as models, recipe_3d as render, asset_usage
from fox3d.recipe_preview_service import RecipePreviewService
from fox3d.recipe_workbench import DraftConflict
from fox3d import model_compositions as compositions, print_preview
from fox3d import model_batches
from fox3d import model_categories as categories

class Classification(models.Strict):
    categoryId: str = Field(min_length=1, max_length=80)
    expectedRevision: int = Field(ge=0)

class Compose(models.Strict):
    expectedRevision: int = Field(ge=1)
    inputHash: str = Field(pattern=r'^[a-f0-9]{64}$')
    assumptionsAccepted: bool
    selection: compositions.Selection


class BatchCompose(models.Strict):
    expectedRevision: int = Field(ge=1)
    inputHash: str = Field(pattern=r'^[a-f0-9]{64}$')
    assumptionsAccepted: bool
    batch: model_batches.Batch

class Save(models.Strict):
    draft: models.Master
    expectedRevision: int = Field(ge=0)

class Generate(models.Strict):
    expectedRevision: int = Field(ge=1)
    inputHash: str = Field(pattern=r'^[a-f0-9]{64}$')
    assumptionsAccepted: bool

class Cancel(models.Strict):
    taskId: str

class Usage(models.Strict):
    role: str
    note: str = Field(min_length=1,max_length=1500)
    expectedRevision: int = Field(ge=0)

def product_models_router(provider):
    r=APIRouter(); services={}; composition_services={}; lock=RLock()
    def root(): return provider().root
    def call(fn,*args,**kwargs):
        try: return fn(*args,**kwargs)
        except (DraftConflict,Timeout) as exc: raise HTTPException(409,str(exc)) from exc
        except KeyError as exc: raise HTTPException(404,'找不到指定資料') from exc
        except (ValueError,OSError,PdfReadError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc: raise HTTPException(422,str(exc)[:1000]) from exc
    def tid(value):
        call(models.directory,root(),value)
        return value
    def service():
        p=provider()
        with lock:
            if p.root not in services:
                services[p.root]=RecipePreviewService(p,folder_fn=models.folder,status_fn=models.status,generate_fn=models.generate)
            return services[p.root]
    def composition_service():
        p=provider()
        with lock:
            if p.root not in composition_services:
                composition_services[p.root]=RecipePreviewService(p,folder_fn=compositions.folder_for,
                    status_fn=compositions.status,generate_fn=model_batches.generate)
            return composition_services[p.root]
    @r.get('/admin/recipes/models',response_class=HTMLResponse)
    def page():
        return HTMLResponse((Path(__file__).with_name('static')/'product-models.html').read_text(encoding='utf-8'),
            headers={'Content-Security-Policy':"default-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"})
    @r.get('/api/product-models/catalog')
    def catalog(q:str=Query('',max_length=200),family:str='',subtype:str='',offset:int=Query(0,ge=0),x_tenant_id:str|None=Header(None)):
        tid(x_tenant_id); data=call(nas.checked_snapshot,root())
        groups=data.get('groups',[])
        filtered=[g for g in groups if (not family or g['family']==family) and (not subtype or g['subtype']==subtype)
            and q.casefold() in (g['folder']+' '+' '.join(g['skuCandidates'])).casefold()]
        return {'families':nas.FAMILIES,'subtypes':nas.SUBTYPES,'configured':bool(call(nas.config,root())),
            'scannedAt':data.get('scannedAt'),'fileCount':data.get('fileCount',0),'scope':data.get('scope'),
            'familyCounts':{f:sum(g['family']==f for g in groups) for f in nas.FAMILIES},
            'total':len(filtered),'offset':offset,'items':filtered[offset:offset+40]}
    @r.post('/api/product-models/catalog/refresh')
    def refresh(x_tenant_id:str|None=Header(None)):
        tid(x_tenant_id); return call(nas.scan,root())
    @r.get('/api/product-models/catalog/{gid}/files')
    def files(gid:str,q:str=Query('',max_length=200),offset:int=Query(0,ge=0),x_tenant_id:str|None=Header(None)):
        tid(x_tenant_id); data=call(nas.checked_snapshot,root())
        group=next((g for g in data.get('groups',[]) if g['id']==gid),None)
        if not group: raise HTTPException(404,'找不到來源群組')
        items=[f for f in data.get('files',[]) if f['groupId']==gid and q.casefold() in f['path'].casefold()]
        return {'group':group,'total':len(items),'items':items[offset:offset+40],'offset':offset}
    @r.post('/api/product-models/files/{sid}/import')
    def source_import(sid:str,x_tenant_id:str|None=Header(None)):
        return call(nas.import_file,root(),tid(x_tenant_id),sid)
    @r.get('/api/product-models/assets')
    def asset_list(x_tenant_id:str|None=Header(None)):
        return {'roles':asset_usage.ROLES,'items':call(asset_usage.listing,root(),tid(x_tenant_id))}
    @r.get('/api/product-models/recipe-references')
    def references(x_tenant_id:str|None=Header(None)):
        from fox3d.recipe_workbench import RecipeWorkbench
        items=call(RecipeWorkbench(root()).list,tid(x_tenant_id));result=[]
        for item in items:
            d=item['draft']
            try: spec=render.build_recipe_spec(d)
            except ValueError: continue
            draft={'name':d['name']+'（Recipe 參考母版，待實測）','family':'cabinet',
                'subtype':'bookcase' if d['family']=='STAGGERED_OPEN_CUBBY' else 'other',
                'geometry':'RECIPE_REFERENCE','recipeReference':{'revision':item['revision'],'draft':d},
                'widthMm':spec['width'],'depthMm':spec['depth'],'heightMm':spec['height'],
                'rows':spec['shelfCount']+1,'dimensionEvidence':'原有 Recipe '+d['sku']+' 的尺寸與依據完整保留於快照。',
                'structureEvidence':'沿用原有配方與明示假設；板厚、五金及各行結構仍待實物核對。',
                'notes':'原始 Recipe 不會被修改。修改原配方後需重新載入快照；此母版不自動同步。',
                'variants':[{'sku':d['sku']}]}
            result.append({'sku':d['sku'],'draft':models.Master.model_validate(draft).model_dump()})
        return {'items':result}
    @r.put('/api/product-models/assets/{aid}/usage')
    def classify(aid:str,body:Usage,x_tenant_id:str|None=Header(None)):
        return call(asset_usage.classify,root(),tid(x_tenant_id),aid,body.role,body.note,body.expectedRevision)
    @r.get('/api/product-models')
    def listing(x_tenant_id:str|None=Header(None)):
        return call(categories.inventory,root(),tid(x_tenant_id))
    @r.post('/api/product-models',status_code=201)
    def create(body:Save,x_tenant_id:str|None=Header(None)):
        return call(models.save,root(),tid(x_tenant_id),body.draft.model_dump(),body.expectedRevision)
    @r.get('/api/product-models/{mid}')
    def detail(mid:str,x_tenant_id:str|None=Header(None)):
        return call(models.get,root(),tid(x_tenant_id),mid)
    @r.get('/api/product-models/{mid}/classification')
    def classification(mid:str,x_tenant_id:str|None=Header(None)):
        return call(categories.get,root(),tid(x_tenant_id),mid)
    @r.put('/api/product-models/{mid}/classification')
    def classify_model(mid:str,body:Classification,x_tenant_id:str|None=Header(None)):
        return call(categories.save,root(),tid(x_tenant_id),mid,body.categoryId,body.expectedRevision)
    @r.put('/api/product-models/{mid}')
    def save(mid:str,body:Save,x_tenant_id:str|None=Header(None)):
        return call(models.save,root(),tid(x_tenant_id),body.draft.model_dump(),body.expectedRevision,mid)
    @r.post('/api/product-models/{mid}/preview',status_code=202)
    def preview(mid:str,body:Generate,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id); item=call(models.get,root(),t,mid)
        if item['revision']!=body.expectedRevision or item['inputHash']!=body.inputHash:
            raise HTTPException(409,'版本已變更，請重新載入')
        if not body.assumptionsAccepted: raise HTTPException(422,'請確認結構簡化說明')
        call(models.validate_artworks,root(),t,item['draft'])
        call(models.build_spec,item['draft'])
        p=provider()
        if p.mock_blender or not p.runtime.available(): raise HTTPException(503,'真實 Blender 不可用')
        return call(service().submit,t,mid,item)
    @r.get('/api/product-models/{mid}/preview')
    def preview_status(mid:str,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id); item=call(models.get,root(),t,mid)
        return call(service().status,t,mid,item['draft'])
    @r.post('/api/product-models/{mid}/cancel')
    def cancel(mid:str,body:Cancel,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id); call(models.get,root(),t,mid)
        return call(service().cancel,t,mid,body.taskId)
    @r.get('/api/product-models/{mid}/composition')
    def composition_status(mid:str,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);item=call(models.get,root(),t,mid)
        state=call(composition_service().status,t,mid,item)
        try: faces=compositions.surfaces(item['draft'])
        except ValueError: faces=[]
        batch=call(model_batches.current,root(),t,mid,state.get('taskId'),state['state'])
        if batch and state['state'] not in {'queued','running'}:
            state={**state,'state':batch['state'],
                   'error':next((r['error'] for r in batch['rows'] if r.get('error')),state.get('error'))}
        return {**state,'scenes':compositions.SCENES,'surfaces':faces,'batch':batch}

    @r.get('/api/product-models/{mid}/compositions')
    def composition_history(mid:str,offset:int=Query(0,ge=0),x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id); item=call(models.get,root(),t,mid)
        return call(compositions.history,root(),t,mid,item,offset)

    @r.post('/api/product-models/{mid}/composition/batch',status_code=202)
    def compose_batch(mid:str,body:BatchCompose,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id); item=call(models.get,root(),t,mid)
        if item['revision']!=body.expectedRevision or item['inputHash']!=body.inputHash:
            raise HTTPException(409,'母版版本已變更，請重新載入')
        if not body.assumptionsAccepted: raise HTTPException(422,'請確認母版尺寸與套圖用途')
        draft=call(model_batches.snapshot,root(),t,item,body.batch.model_dump())
        if provider().mock_blender or not provider().runtime.available():
            raise HTTPException(503,'真實 Blender 不可用')
        return call(composition_service().submit,t,mid,{'draft':draft,'revision':item['revision']})
    @r.post('/api/product-models/{mid}/composition',status_code=202)
    def compose(mid:str,body:Compose,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);item=call(models.get,root(),t,mid)
        if item['revision']!=body.expectedRevision or item['inputHash']!=body.inputHash:
            raise HTTPException(409,'母版版本已變更，請重新載入')
        if not body.assumptionsAccepted: raise HTTPException(422,'請確認母版尺寸與套圖用途')
        draft=call(compositions.snapshot,root(),t,item,body.selection.model_dump())
        if provider().mock_blender or not provider().runtime.available(): raise HTTPException(503,'真實 Blender 不可用')
        return call(composition_service().submit,t,mid,{'draft':draft,'revision':item['revision']})
    @r.post('/api/product-models/{mid}/composition/cancel')
    def composition_cancel(mid:str,body:Cancel,x_tenant_id:str|None=Header(None)):
        t=tid(x_tenant_id);call(models.get,root(),t,mid)
        return call(composition_service().cancel,t,mid,body.taskId)
    @r.get('/api/product-models/{mid}/composition/files/{name}')
    def composition_download(mid:str,name:str,workspace:str,generation:str):
        t=tid(workspace);item=call(models.get,root(),t,mid)
        if name not in print_preview.FILES:
            raise HTTPException(409,'尚無符合目前母版與素材用途的成果，請重新生成')
        try: compositions.generation(root(),t,mid,generation,item)
        except (ValueError,OSError,KeyError) as exc:
            raise HTTPException(409,'成果已失效或母版／圖稿用途已變更，請重新生成') from exc
        path=compositions.folder_for(root(),t,mid)/'generations'/generation/name
        return FileResponse(path,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    @r.get('/api/product-models/{mid}/files/{fmt}')
    def download(mid:str,fmt:str,workspace:str,generation:str):
        t=tid(workspace); item=call(models.get,root(),t,mid)
        state=call(models.status,root(),t,mid,current_draft=item['draft'])
        if fmt not in render.FILES or not state['generated'] or state['stale'] or generation!=state['generationId']:
            raise HTTPException(409,'尚無符合目前版本的有效成果，請重新生成')
        path=models.folder(root(),t,mid)/'generations'/state['generationId']/render.FILES[fmt]
        return FileResponse(path,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    return r
