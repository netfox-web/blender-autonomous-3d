"""Reuse the real Blender worker for source-sized print faces, without print release."""
import io
import re
import shutil
from pathlib import Path

from PIL import Image

from fox3d.artwork import final_uv_identity
from fox3d.golden_product import build_golden, GoldenRecipe, Measurement, validate_worker_observation
from fox3d.ids import stable_hash, sha256_bytes, new_id
from fox3d.recipe_3d import read_json, atomic_json, input_hash, validate_outputs
from fox3d.durability import publish_binary, publish_bytes
from fox3d.print_workspace import folder_for as job_folder, plan
from fox3d.print_assets import thumbnail

FILES=('beauty.png','front-closed.png','model.glb','model.blend','geometry.json','golden-observation.json')


def folder_for(root,tenant,jid):
    return job_folder(root,tenant,jid)/'preview'


def geometry(p):
    tw,th=p['panels'][0]['trimWidthMm'],p['panels'][0]['trimHeightMm']
    if p['draft']['layout']=='THREE_DOOR':
        # Frame is a configured visualization around the real artwork trim sizes.
        r=GoldenRecipe(widthMm=Measurement(value=tw+34,evidence='Print-face layout plus assumed 15 mm sides and 2 mm gaps'),
                       heightMm=Measurement(value=th*3+72,evidence='Three print faces plus assumed shelves and gaps'))
        spec=build_golden(r)['spec']
    else:
        part={'componentId':'print_panel','partName':'單片印刷面','role':'door','sizeMm':[tw,15.,th],
              'locationMm':[0.,0.,th/2],'size':[tw/1000,.015,th/1000],'location':[0.,0.,th/2000]}
        spec={'width':tw,'depth':15.,'height':th,'components':[part],'goldenRecipe':True,'recipePreview':True,
              'engineeringReady':False,'productionReady':False}
    spec['engineeringHash']=stable_hash({'components':spec['components'],'authority':'PRINT_LAYOUT_WITH_ASSUMED_FRAME'})
    spec['previewAuthority']='Print faces use source trim; cabinet frame, depth and thickness are unmeasured assumptions'
    return spec


def prepare(root,tenant,p,folder):
    spec=geometry(p);parts=[x for x in spec['components'] if x['role']=='door'];placements=[]
    art_hash=stable_hash({'planHash':p['planHash'],'purpose':'RGB_SCREEN_PREVIEW_ONLY'})
    for row,part in zip(p['panels'],parts):
        raw=thumbnail(root,tenant,row['assetId'],row['page'])
        im=Image.open(io.BytesIO(raw)).rotate(-row['rotation'],expand=True)
        left,bottom,right,top=row['trimBoxMm'];w,h=row['widthMm'],row['heightMm']
        box=(round(left/w*im.width),round((h-top)/h*im.height),round(right/w*im.width),round((h-bottom)/h*im.height))
        trim=im.crop(box);name=part['componentId']+'-preview.png';target=folder/name
        publish_bytes(lambda stream: trim.save(stream,format='PNG'), target)
        with Image.open(target) as decoded: decoded.verify()
        digest=sha256_bytes(target.read_bytes());uv={'u0':0.,'v0':0.,'u1':1.,'v1':1.}
        item={'componentId':part['componentId'],'objectName':part['partName'],'face':'FRONT',
              'engineeringHash':spec['engineeringHash'],'artworkHash':art_hash,'surfaceHash':stable_hash(row),
              'uvRect':uv,'rotationDeg':0.,'mirrored':False,'relation':'SINGLE_SURFACE',
              'source':{'name':name,'fileSha256':digest},'originalAssetId':row['assetId'],
              'sourcePage':row['page'],'sourceRotation':row['rotation'],'trimBoxMm':row['trimBoxMm'],
              'derivedPreviewCropPx':list(box),'colorAuthority':'RGB_APPROXIMATION'}
        item['placementHash']=stable_hash(item);item['placementId']=item['placementHash']
        item.update(final_uv_identity(placement_id=item['placementId'],object_name=item['objectName'],component_id=item['componentId'],face='FRONT',relation='SINGLE_SURFACE',uv_rect=uv))
        placements.append(item)
    package={'sku':p['draft']['sku'],'engineeringHash':spec['engineeringHash'],'placements':placements,'artworkHash':art_hash}
    package['packageHash']=stable_hash(package)
    inputs=[{**i,'imagePath':str((folder/i['source']['name']).resolve()),'artworkSha256':i['source']['fileSha256'],'goldenObservedUv':True} for i in placements]
    return spec,package,inputs


def validate(folder):
    meta=read_json(folder/'meta.json');m=read_json(folder/'manifest.json')
    if not m or sha256_bytes((folder/'manifest.json').read_bytes())!=meta.get('manifestSha256'):
        raise ValueError('3D 預覽紀錄驗證失敗')
    expected=set(FILES)|{p['source']['name'] for p in m['package']['placements']}
    if set(m['files'])!=expected:raise ValueError('3D 預覽檔案清單不符')
    for name,digest in m['files'].items():
        if Path(name).name!=name or sha256_bytes((folder/name).read_bytes())!=digest:
            raise ValueError('3D 預覽檔案已變更')
    validate_outputs(folder,m['spec'])
    validate_worker_observation(read_json(folder/'golden-observation.json'),m['package'],m['spec'])
    if m['renderInfo'].get('realBlender') is not True or m['renderInfo'].get('usedMock') is not False:
        raise ValueError('需要真實 Blender 成果')
    return m


def status(root,tenant,jid,*,current_draft=None):
    base=folder_for(root,tenant,jid);pointer=read_json(base/'latest.json');s=read_json(base/'state.json')
    m=None;error=s.get('error')
    if pointer:
        try:
            if not re.fullmatch(r'[a-f0-9-]{36}',pointer['generationId']):raise ValueError('無效預覽編號')
            m=validate(base/'generations'/pointer['generationId'])
        except (ValueError,OSError,KeyError) as exc:error=str(exc)
    return {'state':s.get('state','idle'),'progress':s.get('progress',0),'taskId':s.get('taskId'),
            'generated':bool(m),'generationId':pointer.get('generationId'),'error':error,
            'stale':bool(m and current_draft and m['draft']!=current_draft),'manifest':m}


def generate(platform,tenant,jid,draft,*,revision=0,generation_id=None,on_job=None,cancel_flag=None):
    def check():
        if cancel_flag and cancel_flag.is_set():raise ValueError('已取消 3D 生成')
    check()
    if platform.mock_blender or not platform.runtime.available():raise ValueError('需要真實 Blender')
    p=plan(platform.root,tenant,draft);gid=generation_id or new_id()
    folder=folder_for(platform.root,tenant,jid)/'generations'/gid;folder.mkdir(parents=True,exist_ok=False)
    spec,package,placements=prepare(platform.root,tenant,p,folder);check()
    h=spec['height']/1000;extent=max(spec['width'],spec['height'])/1000
    payload={'tenantId':tenant,'jobType':'PARAMETRIC_3D','mode':'CABINET_PREVIEW','engineering':spec,
             'recipePreview':True,'goldenRecipe':True,'goldenIdentity':{'sku':draft['sku'],'packageHash':package['packageHash']},
             'artworkPlacements':placements,'assetHash':stable_hash({'package':package['packageHash'],'contract':'print-preview-v1'}),
             'camera':{'location':[extent*1.5,-extent*2.,h*1.2],'lookAt':[0.,0.,h/2],'focalLengthMm':55.},
             'productTruthViews':[{'id':'FRONT_CLOSED','filename':'front-closed.png','location':[0.,-extent*2.6,h/2],'lookAt':[0.,0.,h/2],'focalLengthMm':70.}],
             'render':{'device':'OPTIX' if platform.probe and platform.probe.optix else 'CPU','width':800,'height':800,'samples':32},
             'exportBlend':True,'exportGlb':True,'maxAttempts':1,'timeoutSeconds':900}
    job=platform.submit_job(payload)
    if on_job:on_job(job)
    done=platform.execute_job(job,cancel_flag=cancel_flag);check()
    if done.get('status') not in ('completed','succeeded') or done.get('realBlender') is not True or done.get('usedMock') is not False:
        raise ValueError('Blender 未完成：'+str(done.get('error') or done.get('status')))
    output=done.get('output',{})
    for name in FILES:
        source=platform.dam.get(output['files'][name],tenant_id=tenant)
        publish_binary(source.path, folder/name)
    m={'generationId':gid,'draft':draft,'sourceRevision':revision,'planHash':p['planHash'],'spec':spec,'package':package,
       'files':{f.name:sha256_bytes(f.read_bytes()) for f in folder.iterdir() if f.is_file()},
       'renderInfo':{k:output.get(k,done.get(k)) for k in ('realBlender','usedMock','device','blenderVersion','realOptix')},
       'requestedJobId':job['jobId'],'jobId':read_json(folder/'golden-observation.json')['jobId'],'cacheHit':done.get('cacheHit',False),
       'productionReady':False,'colorAuthority':'RGB_APPROXIMATION_NOT_RIP_COLOR_PROOF'}
    atomic_json(folder/'manifest.json',m);atomic_json(folder/'meta.json',{'manifestSha256':sha256_bytes((folder/'manifest.json').read_bytes())})
    validate(folder);check();atomic_json(folder.parent.parent/'latest.json',{'generationId':gid})
    return status(platform.root,tenant,jid,current_draft=draft)
