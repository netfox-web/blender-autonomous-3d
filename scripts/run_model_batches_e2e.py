"""Clean CODE HTTP/REAL Blender batch, retained-result and restart acceptance."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main(*, scene_mode=False):
    import httpx
    from PIL import Image, ImageDraw
    from fox3d import print_assets, asset_usage, product_models, model_compositions as c
    from fox3d.blender import find_blender
    from fox3d.recipe_3d import atomic_json
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
        raise SystemExit('Formal acceptance requires clean CODE')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    eid=str(uuid.uuid4());base=ROOT/'.fox3d-work'/('scenes' if scene_mode else 'batches')/eid[:8];base.mkdir(parents=True)
    data=base/'d';tenant='sonaqueen-home';models=[];assets=[]
    for kind,size in [('HINGED_CABINET',(780,552)),('RECTANGLE',(400,400))]:
        model=product_models.save(data,tenant,{'name':'FIXTURE '+kind,
            'family':'cabinet' if kind=='HINGED_CABINET' else 'coaster','geometry':kind,
            'widthMm':424. if kind=='HINGED_CABINET' else 100.,
            'depthMm':295. if kind=='HINGED_CABINET' else 5.,
            'heightMm':900. if kind=='HINGED_CABINET' else 100.,
            'panelMm':15.,'backMm':3.,'doorMm':15.,'gapMm':2.,'rows':3,
            'dimensionEvidence':'SYNTHETIC FIXTURE dimensions, not physical product truth',
            'structureEvidence':'SYNTHETIC rectangular static geometry'},0)
        models.append(model);group=[]
        for color in ['#ce923a','#8d51a8']:
            im=Image.new('RGB',size,color);draw=ImageDraw.Draw(im)
            draw.rectangle((0,0,size[0]//3,size[1]//2),fill='#1559c4')
            draw.rectangle((size[0]//2,size[1]//2,size[0]-1,size[1]-1),fill='#df3340')
            buf=io.BytesIO();im.save(buf,'PNG')
            a=print_assets.import_asset(data,tenant,buf.getvalue(),'synthetic-pattern.png')
            asset_usage.classify(data,tenant,a['id'],'ARTWORK','Synthetic asymmetric fixture',0);group.append(a)
        assets.append(group)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}';log=(base/'server.log').open('w',encoding='utf-8');proc=None
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    def start():
        p=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_recipe_admin.py'),'--port',str(port),'--data-root',str(data)],
            cwd=ROOT,env={**os.environ,'FOX3D_MOCK_BLENDER':'0','PYTHONIOENCODING':'utf-8'},stdout=log,stderr=log,creationflags=flags)
        for _ in range(120):
            if p.poll() is not None:raise RuntimeError('Server exited')
            try:
                if httpx.get(url+'/api/recipe-library/health',timeout=1,trust_env=False).status_code==200:return p
            except httpx.HTTPError:pass
            time.sleep(.5)
        p.terminate();raise RuntimeError('Server timeout')
    evidence={'evidenceId':eid,'codeCommit':sha,'workingTreeClean':True,'inputTruth':'SYNTHETIC_STATIC_FIXTURE',
              'physicalPrintValidated':False,'productionReady':False,'generations':[],'sceneMode':scene_mode}
    try:
        proc=start()
        with httpx.Client(base_url=url,headers={'X-Tenant-Id':tenant},timeout=180,trust_env=False) as client:
            client.get('/admin/recipes/assets/model-batches.js').raise_for_status()
            for index,item in enumerate(models):
                mid=item['id'];path='/api/product-models/'+mid
                surfaces=client.get(path+'/composition').json()['surfaces'];selections=[]
                for aindex,asset in enumerate(assets[index]):
                    for scene in (['LIVING_ROOM','KITCHEN'] if scene_mode else (['STUDIO','WARM_ROOM'] if index==0 else ['STUDIO'])):
                        selections.append({'sku':f'FIXTURE-{aindex+1}','scene':scene,
                            **({'view':'LEFT' if aindex else 'THREE_QUARTER'} if scene_mode else {}),
                            'placements':[{'componentId':f['componentId'],'assetId':asset['id']} for f in surfaces if f['componentId']!='back']})
                body={'expectedRevision':item['revision'],'inputHash':item['inputHash'],'assumptionsAccepted':True,
                      'batch':{'name':'REAL batch fixture','selections':selections}}
                response=client.post(path+'/composition/batch',json=body);response.raise_for_status()
                task=response.json()['taskId']
                duplicate=client.post(path+'/composition',json={k:v for k,v in {**body,'selection':selections[0]}.items() if k!='batch'})
                assert duplicate.status_code==422,duplicate.text
                deadline=time.monotonic()+len(selections)*930
                while time.monotonic()<deadline:
                    response=client.get(path+'/composition');response.raise_for_status();state=response.json()
                    if state['state'] not in {'queued','running'}:break
                    time.sleep(3)
                assert state['state']=='succeeded' and state['taskId']==task,state
                assert all(r['state']=='succeeded' for r in state['batch']['rows'])
                history=client.get(path+'/compositions').json()
                assert history['total']==len(selections) and all(r['available'] for r in history['items'])
                hashes=[];pixels=[];actual_geometry=[]
                for row in history['items']:
                    gid=row['generationId'];folder=c.folder_for(data,tenant,mid)/'generations'/gid
                    manifest=c.generation(data,tenant,mid,gid,item)
                    reopen=subprocess.run([find_blender(),'-b',str(folder/'model.blend'),'--python-exit-code','1','--python',str(ROOT/'scripts/check_print_blend.py'),'--',str(folder)],capture_output=True,timeout=180,creationflags=flags)
                    (base/(gid[:8]+'-reopen.log')).write_bytes(reopen.stdout+reopen.stderr)
                    assert reopen.returncode==0 and b'PRINT_BLEND_REOPEN_PASS' in reopen.stdout
                    for name in ['beauty.png','front-closed.png','model.glb','model.blend','geometry.json']:
                        client.get(path+'/composition/files/'+name,params={'workspace':tenant,'generation':gid}).raise_for_status()
                    assert manifest['renderInfo']['realBlender'] is True and manifest['renderInfo']['usedMock'] is False
                    hashes.append(manifest['spec']['engineeringHash']);pixels.append(manifest['files']['beauty.png'])
                    actual_geometry.append((folder/'geometry.json').read_bytes())
                    if scene_mode:
                        import math
                        from PIL import ImageStat
                        from fox3d.scene_templates import validate_observation
                        observation=json.loads((folder/'golden-observation.json').read_text(encoding='utf-8'))
                        validate_observation(manifest,observation)
                        image=Image.open(folder/'beauty.png')
                        stats=ImageStat.Stat(image)
                        assert image.size==(800,800) and all(math.isfinite(v) for pair in stats.extrema for v in pair) and max(stats.stddev)>5
                        assert manifest['renderInfo']['realOptix'] is True
                    evidence['generations'].append({'modelId':mid,'generationId':gid,'sku':row['sku'],'scene':row['scene'],
                        'renderInfo':manifest['renderInfo'],'files':manifest['files'],
                        'sizes':{n:(folder/n).stat().st_size for n in manifest['files']},
                        'geometryHash':hashes[-1],'jobId':manifest['jobId'],'requestedJobId':manifest['requestedJobId'],
                        'cacheHit':manifest['cacheHit'],'blendReopen':True,
                        **({'sceneHash':manifest['sceneHash'],'sceneObservation':observation['presentationScene'],'finitePixels':True} if scene_mode else {})})
                assert len(set(hashes))==1 and len(set(pixels))==len(selections)
                assert len(set(actual_geometry))==1
                print(json.dumps({'model':index,'generations':len(selections),'history':'PASS'}),flush=True)
            proc.terminate();proc.wait(timeout=30);proc=start()
            for index,item in enumerate(models):
                path='/api/product-models/'+item['id'];history=client.get(path+'/compositions').json()
                assert all(r['available'] for r in history['items'])
                gid=history['items'][0]['generationId']
                # Change geometry after restart: all old variants become unavailable.
                r=client.put(path,json={'expectedRevision':1,'draft':{**item['draft'],'widthMm':item['draft']['widthMm']+1}});r.raise_for_status()
                assert all(not r['available'] for r in client.get(path+'/compositions').json()['items'])
                assert client.get(path+'/composition/files/model.glb',params={'workspace':tenant,'generation':gid}).status_code==409
                r=client.put(path,json={'expectedRevision':2,'draft':item['draft']});r.raise_for_status()
                assert all(r['available'] for r in client.get(path+'/compositions').json()['items'])
                asset_usage.classify(data,tenant,assets[index][0]['id'],'REFERENCE','Revoked fixture',1)
                rows=client.get(path+'/compositions').json()['items']
                assert all(r['available']==(r['sku']=='FIXTURE-2') for r in rows)
                invalid=next(r for r in rows if not r['available'])
                assert client.get(path+'/composition/files/beauty.png',params={'workspace':tenant,'generation':invalid['generationId']}).status_code==409
                assert client.get(path+'/compositions',headers={'X-Tenant-Id':'other'}).status_code==404
            evidence.update(status='PASS',geometryPreserved=True,variantPixelsDistinct=True,
                            restartPreserved=True,staleBlocked=True,revokedBlocked=True,serialQueue=True)
    except Exception as exc:evidence.update(status='FAIL',error=str(exc));raise
    finally:
        if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=30)
        atomic_json(base/'evidence.json',evidence);log.close()
        print(json.dumps({'evidenceFile':str(base/'evidence.json'),'status':evidence.get('status')}),flush=True)


if __name__=='__main__':main()
