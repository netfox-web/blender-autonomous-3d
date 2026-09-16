"""Reusable master geometry with explicit surface artwork and deterministic scenes.

Screen previews only. Scene and artwork identities never certify physical dimensions.
"""
import io
import re
import shutil
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import Field

from fox3d import asset_usage, print_assets, product_models as models, print_preview
from fox3d.artwork import final_uv_identity
from fox3d.ids import stable_hash, sha256_bytes, new_id
from fox3d.recipe_3d import atomic_json, read_json
from fox3d import variant_authority as authority

SCENES = {'STUDIO': '白底棚拍', 'WARM_ROOM': '暖色室內展示', 'COOL_ROOM': '冷色室內展示'}


def valid_generation(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', value))


def generation(root, tenant, mid, gid, item):
    """Validate any retained result against current model and artwork permissions."""
    if not valid_generation(gid):
        raise ValueError('無效成果編號')
    target = folder_for(root, tenant, mid)/'generations'/gid
    manifest = print_preview.validate(target)
    draft = manifest['draft']
    # A JSON boolean/float is not the original integer identity, even after a
    # local publication seal is recomputed. Preserve only pre-V1 legacy absence.
    if 'historyVersion' in manifest or 'inputAuthority' in draft or 'inputAuthorityHash' in manifest:
        if (type(manifest.get('historyVersion')) is not int or manifest['historyVersion'] != 1
                or type(manifest.get('sourceRevision')) is not int
                or type(draft.get('masterRevision')) is not int
                or manifest['sourceRevision'] != draft['masterRevision']):
            raise ValueError('成果來源版本不符')
        published = read_json(target/'published.json')
        if published.get('manifestSha256') != sha256_bytes((target/'manifest.json').read_bytes()):
            raise ValueError('成果尚未完成發布核對')
    if manifest['generationId'] != gid or draft['masterId'] != mid:
        raise ValueError('成果不屬於此模型')
    if draft['masterInputHash'] != item['inputHash']:
        raise ValueError('母版已變更；此款保留為歷史紀錄，請重新生成')
    if 'inputAuthority' in draft or 'inputAuthorityHash' in manifest:
        authority.verify(root, tenant, draft, current=False)
        if manifest.get('inputAuthorityHash') != draft['inputAuthority']['hash']:
            raise ValueError('發布成果與來源權威不符')
    for placement in manifest['package']['placements']:
        asset_usage.require_artwork(root, tenant, placement['originalAssetId'])
    return manifest


def history(root, tenant, mid, item, offset=0):
    paths = sorted((folder_for(root, tenant, mid)/'generations').glob('*/manifest.json'),
                   key=lambda p: (p.stat().st_mtime_ns, p.parent.name), reverse=True)
    rows = []
    for path in paths[offset:offset+12]:
        stored = read_json(path)
        row = {'generationId': path.parent.name, 'sku': stored.get('draft', {}).get('sku', ''),
               'scene': stored.get('scene', ''), 'sourceRevision': stored.get('sourceRevision'),
               'available': False, 'error': None}
        row.update(authority.readiness())
        try:
            manifest = generation(root, tenant, mid, path.parent.name, item)
            row.update(available=True, renderInfo=manifest['renderInfo'])
            row.update(authority.readiness(True))
            if 'inputAuthority' in manifest['draft']:
                row['inputAuthorityHash'] = manifest['draft']['inputAuthority']['hash']
                row['geometryAuthorityKind'] = manifest['draft']['inputAuthority']['snapshot']['geometryAuthorityKind']
        except (ValueError, OSError, KeyError) as exc:
            row['error'] = str(exc)[:500]
        rows.append(row)
    return {'items': rows, 'total': len(paths), 'offset': offset}


class Placement(models.Strict):
    componentId: str = Field(min_length=1, max_length=100)
    assetId: str = Field(pattern=r'^[a-f0-9]{64}$')
    page: int = Field(default=0, ge=0, le=99)
    rotation: Literal[0, 90, 180, 270] = 0


class Selection(models.Strict):
    sku: str = Field(min_length=1, max_length=120)
    scene: Literal['STUDIO', 'WARM_ROOM', 'COOL_ROOM'] = 'STUDIO'
    placements: list[Placement] = Field(default_factory=list, max_length=30)


def folder_for(root, tenant, mid):
    # Keep Windows filenames below MAX_PATH even in isolated acceptance roots.
    print_assets.workspace(root,tenant)
    return Path(root)/'master-compositions'/stable_hash({'tenant':tenant,'master':mid})[:24]


def surfaces(draft):
    spec = models.build_spec(draft)
    # Front means the -Y face. Cabinet back is its visible interior face.
    result=[{'componentId': p['componentId'], 'label':
             ('上方第 '+str((draft.get('rows') or spec.get('doorCount'))-int(p['componentId'].split('_')[1])+1)+' 片門')
             if p['role']=='door' else ('背板內側' if p['role']=='back' else '平板正面'),
             'widthMm':p['sizeMm'][0], 'heightMm':p['sizeMm'][2]}
            for p in spec['components'] if p['role'] in {'door','back','panel'}]
    return sorted(result,key=lambda s:(s['componentId'].startswith('back'),
        -int(s['componentId'].split('_')[1]) if s['componentId'].startswith('door_') else 0))


def snapshot(root, tenant, item, selection):
    chosen=Selection.model_validate(selection).model_dump()
    if not chosen['sku'].strip(): raise ValueError('請填本次圖稿／SKU 名稱')
    value={'masterId':item['id'], 'masterInputHash':item['inputHash'],
           'masterRevision':item['revision'], 'master':item['draft'], **chosen}
    plan(root,tenant,value)
    return value


def plan(root, tenant, draft):
    if 'inputAuthority' in draft:
        authority.verify(root, tenant, draft, current=True)
    Selection.model_validate({k:draft[k] for k in ('sku','scene','placements')})
    spec=models.build_spec(draft['master'],tenant_id=tenant)
    spec['engineeringHash']=stable_hash({'adapter':'MASTER_COMPOSITION_V1','components':spec['components']})
    spec['nasScene']=draft['scene']
    spec['previewAssumptions']=[x for x in spec['previewAssumptions'] if x!='示意材質與棚拍燈光；尚未套入圖稿。']
    spec['previewAssumptions'].append('使用已分類圖稿與可重複場景；RGB 螢幕預覽，非實機色彩校樣。')
    allowed={s['componentId']:s for s in surfaces(draft['master'])}
    seen=set(); rows=[]
    for value in draft['placements']:
        p=Placement.model_validate(value).model_dump(); cid=p['componentId']
        if cid not in allowed or cid in seen: raise ValueError('請選不同且有效的貼圖面')
        seen.add(cid); asset_usage.require_artwork(root,tenant,p['assetId'])
        meta,raw=print_assets.asset(root,tenant,p['assetId'])
        if meta['info']['type']=='IMAGE':
            with Image.open(io.BytesIO(raw)) as im:
                if im.mode=='RGBA' and im.getextrema()[3]!=(255,255):
                    raise ValueError('透明圖稿請先確認底色並另存不透明版本')
        if p['page']>=len(meta['info']['pages']): raise ValueError('圖稿頁碼不存在')
        pg=meta['info']['pages'][p['page']]
        # PDF trim dimensions describe the source, never the physical product.
        sw,sh=(pg['trimWidthMm'],pg['trimHeightMm']) if meta['info']['type']=='PDF' else (pg['widthPx'],pg['heightPx'])
        rotation=p['rotation']+(pg.get('rotation',0) if meta['info']['type']=='PDF' else 0)
        if rotation%180: sw,sh=sh,sw
        face=allowed[cid]
        if abs((sw/sh)/(face['widthMm']/face['heightMm'])-1)>0.002:
            raise ValueError(f"{face['label']} 圖稿比例不符：貼圖面 {face['widthMm']:g}×{face['heightMm']:g} mm；請先裁成相同比例或調整旋轉，不會自動拉伸")
        rows.append({**p,**face,'sourceType':meta['info']['type'],'sourceAspect':sw/sh})
    return {'spec':spec,'rows':rows,'selectionHash':stable_hash(draft),
            'engineeringHash':spec['engineeringHash'],'scene':draft['scene'],
            'physicalDimensionsVerified':False,'physicalPrintValidated':False}


def prepare(root,tenant,draft,target):
    p=plan(root,tenant,draft);spec=p['spec'];placements=[]
    artwork_hash=stable_hash({'placements':draft['placements'],'contract':'MASTER_COMPOSITION_V1'})
    parts={x['componentId']:x for x in spec['components']}
    for row in p['rows']:
        meta,_=print_assets.asset(root,tenant,row['assetId'])
        # Shared print panel parser handles PDF origin, TrimBox and page rotation.
        from fox3d.print_workspace import Panel, panel_page
        raw=print_assets.asset(root,tenant,row['assetId'])[1]
        image=Image.open(io.BytesIO(print_assets.thumbnail(root,tenant,row['assetId'],row['page']))).rotate(-row['rotation'],expand=True)
        box=(0,0,image.width,image.height)
        if meta['info']['type']=='PDF':
            panel=Panel(label=row['label'],assetId=row['assetId'],page=row['page'],rotation=row['rotation'])
            page,_=panel_page(raw,meta,panel)
            left,bottom,right,top=map(float,page.trimbox);w,h=float(page.mediabox.width),float(page.mediabox.height)
            box=(round(left/w*image.width),round((h-top)/h*image.height),round(right/w*image.width),round((h-bottom)/h*image.height))
        if box[2]<=box[0] or box[3]<=box[1]: raise ValueError('圖稿裁切範圍為空')
        name=row['componentId']+'-preview.png';image.crop(box).save(target/name,'PNG')
        uv={'u0':0.,'v0':0.,'u1':1.,'v1':1.}
        item={'componentId':row['componentId'],'objectName':parts[row['componentId']]['partName'],
              'face':'FRONT','relation':'SINGLE_SURFACE','engineeringHash':spec['engineeringHash'],
              'artworkHash':artwork_hash,'surfaceHash':stable_hash(row),'uvRect':uv,'rotationDeg':0.,'mirrored':False,
              'source':{'name':name,'fileSha256':sha256_bytes((target/name).read_bytes())},
              'originalAssetId':row['assetId'],'sourcePage':row['page'],'sourceRotation':row['rotation'],
              'derivedPreviewCropPx':list(box),'targetWidthMm':row['widthMm'],'targetHeightMm':row['heightMm']}
        item['placementHash']=stable_hash(item);item['placementId']=item['placementHash']
        item.update(final_uv_identity(placement_id=item['placementId'],object_name=item['objectName'],
            component_id=item['componentId'],face='FRONT',relation='SINGLE_SURFACE',uv_rect=uv))
        placements.append(item)
    package={'sku':draft['sku'],'engineeringHash':spec['engineeringHash'],'placements':placements,'artworkHash':artwork_hash}
    package['packageHash']=stable_hash(package)
    inputs=[{**x,'imagePath':str((target/x['source']['name']).resolve()),
             'artworkSha256':x['source']['fileSha256'],'goldenObservedUv':True} for x in placements]
    return p,spec,package,inputs


def status(root,tenant,mid,*,current_draft=None):
    base=folder_for(root,tenant,mid); pointer=read_json(base/'latest.json');state=read_json(base/'state.json')
    manifest=None; error=state.get('error')
    if pointer:
        try:
            import re
            if not re.fullmatch(r'[a-f0-9-]{36}',pointer['generationId']): raise ValueError('無效預覽編號')
            manifest=print_preview.validate(base/'generations'/pointer['generationId'])
            if 'inputAuthority' in manifest['draft'] or 'inputAuthorityHash' in manifest:
                manifest=generation(root,tenant,mid,pointer['generationId'],models.get(root,tenant,mid))
            for x in manifest['package']['placements']: asset_usage.require_artwork(root,tenant,x['originalAssetId'])
        except (ValueError,OSError,KeyError) as exc: manifest=None;error=str(exc)
    return {'state':state.get('state','idle'),'taskId':state.get('taskId'),'progress':state.get('progress',0),
            'generated':bool(manifest),'generationId':pointer.get('generationId'),'error':error,
            'stale':bool(manifest and current_draft and manifest['draft']['masterInputHash']!=current_draft['inputHash']),
            'manifest':manifest}


def generate(platform,tenant,mid,draft,*,revision=0,generation_id=None,on_job=None,cancel_flag=None):
    def check():
        if cancel_flag and cancel_flag.is_set(): raise ValueError('已取消生成')
    check()
    if platform.mock_blender or not platform.runtime.available(): raise ValueError('需要真實 Blender')
    gid=generation_id or new_id();target=folder_for(platform.root,tenant,mid)/'generations'/gid
    target.mkdir(parents=True,exist_ok=False)
    p,spec,package,placements=prepare(platform.root,tenant,draft,target)
    h=spec['height']/1000;extent=max(spec['width'],spec['height'],spec['depth'])/1000
    payload={'tenantId':tenant,'jobType':'PARAMETRIC_3D','mode':'CABINET_PREVIEW','engineering':spec,
        'recipePreview':True,'goldenRecipe':True,'goldenIdentity':{'sku':draft['sku'],'packageHash':package['packageHash']},
        'artworkPlacements':placements,'assetHash':stable_hash({'package':package['packageHash'],'scene':draft['scene'],'contract':'MASTER_COMPOSITION_V1'}),
        'camera':{'location':[extent*1.5,-extent*2.,h*1.2],'lookAt':[0.,0.,h/2],'focalLengthMm':55.},
        'productTruthViews':[{'id':'FRONT_CLOSED','filename':'front-closed.png','location':[0.,-extent*2.6,h/2],'lookAt':[0.,0.,h/2],'focalLengthMm':70.}],
        'render':{'device':'OPTIX' if platform.probe and platform.probe.optix else 'CPU','width':800,'height':800,'samples':32},
        'exportBlend':True,'exportGlb':True,'maxAttempts':1,'timeoutSeconds':900}
    job=platform.submit_job(payload)
    if on_job: on_job(job)
    done=platform.execute_job(job,cancel_flag=cancel_flag);check()
    if done.get('status') not in {'completed','succeeded'} or done.get('realBlender') is not True or done.get('usedMock') is not False:
        raise ValueError('Blender 未完成：'+str(done.get('error') or done.get('status')))
    output=done.get('output',{})
    for name in print_preview.FILES:
        source=platform.dam.get(output['files'][name],tenant_id=tenant);shutil.copy2(source.path,target/name)
    manifest={'generationId':gid,'historyVersion':1,'draft':draft,'sourceRevision':revision,'planHash':p['selectionHash'],
        'spec':spec,'package':package,'scene':draft['scene'],'sceneHash':stable_hash({'scene':draft['scene'],'version':1}),
        'files':{f.name:sha256_bytes(f.read_bytes()) for f in target.iterdir() if f.is_file()},
        'renderInfo':{k:output.get(k,done.get(k)) for k in ('realBlender','usedMock','device','blenderVersion','realOptix')},
        'requestedJobId':job['jobId'],'jobId':read_json(target/'golden-observation.json')['jobId'],
        'cacheHit':done.get('cacheHit',False),'productionReady':False,'colorAuthority':'RGB_SCREEN_PREVIEW_NOT_PRINT_PROOF'}
    if 'inputAuthority' in draft:
        manifest['inputAuthorityHash'] = draft['inputAuthority']['hash']
    atomic_json(target/'manifest.json',manifest)
    atomic_json(target/'meta.json',{'manifestSha256':sha256_bytes((target/'manifest.json').read_bytes())})
    print_preview.validate(target);check()
    # An operator can edit the master or revoke artwork while Blender is working.
    current=models.get(platform.root,tenant,mid)
    if current['inputHash']!=draft['masterInputHash']: raise ValueError('母版已變更，請重新生成')
    for x in draft['placements']: asset_usage.require_artwork(platform.root,tenant,x['assetId'])
    if 'inputAuthority' in draft:
        authority.verify(platform.root,tenant,draft,current=True)
    check()
    atomic_json(target/'published.json',{'manifestSha256':sha256_bytes((target/'manifest.json').read_bytes())})
    atomic_json(target.parent.parent/'latest.json',{'generationId':gid})
    return status(platform.root,tenant,mid,current_draft=current)
