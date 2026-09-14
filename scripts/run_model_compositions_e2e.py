"""Actual HTTP + Blender composition/reopen acceptance on isolated synthetic data."""
import argparse
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


def main():
    import httpx
    from PIL import Image, ImageDraw
    from fox3d import print_assets, asset_usage, product_models, model_compositions
    from fox3d.recipe_3d import atomic_json, read_json
    from fox3d.blender import find_blender
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-dirty',action='store_true');parser.add_argument('--keep-server',action='store_true')
    args=parser.parse_args()
    clean=not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    if not clean and not args.allow_dirty:raise SystemExit('Formal evidence requires clean CODE')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    eid=str(uuid.uuid4());base=ROOT/'.fox3d-work'/'compositions-e2e'/eid[:8];base.mkdir(parents=True)
    data=base/'d';art=[];tenant='sonaqueen-home'
    for width,height in [(780,552),(400,400)]:
        im=Image.new('RGB',(width,height),'#debe78');draw=ImageDraw.Draw(im)
        draw.rectangle((0,0,width//3,height//2),fill='#264fb1');draw.rectangle((width//2,height//2,width-1,height-1),fill='#b82836')
        buf=io.BytesIO();im.save(buf,'PNG');a=print_assets.import_asset(data,tenant,buf.getvalue(),'synthetic-grid.png')
        asset_usage.classify(data,tenant,a['id'],'ARTWORK','Synthetic asymmetric placement fixture; not company artwork',0);art.append(a)
    models=[]
    for kind in ['HINGED_CABINET','RECTANGLE']:
        draft={'name':'FIXTURE '+kind,'family':'cabinet' if kind=='HINGED_CABINET' else 'coaster','geometry':kind,
            'widthMm':424. if kind=='HINGED_CABINET' else 100.,'depthMm':295. if kind=='HINGED_CABINET' else 5.,
            'heightMm':900. if kind=='HINGED_CABINET' else 100.,'panelMm':15.,'backMm':3.,'doorMm':15.,'gapMm':2.,'rows':3,
            'dimensionEvidence':'Synthetic dimensions; not actual product measurements','structureEvidence':'Synthetic rectangular geometry'}
        models.append(product_models.save(data,tenant,draft,0))
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    url=f'http://127.0.0.1:{port}';log=(base/'server.log').open('w',encoding='utf-8');proc=None
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    cmd=[sys.executable,str(ROOT/'scripts/run_recipe_admin.py'),'--port',str(port),'--data-root',str(data)]
    def start():
        process=subprocess.Popen(cmd,cwd=ROOT,env={**os.environ,'FOX3D_MOCK_BLENDER':'0','PYTHONIOENCODING':'utf-8'},stdout=log,stderr=log,creationflags=flags)
        for _ in range(120):
            if process.poll() is not None:raise RuntimeError('Server startup failed')
            try:
                if httpx.get(url+'/api/recipe-library/health',timeout=1,trust_env=False).status_code==200:return process
            except httpx.HTTPError:pass
            time.sleep(.5)
        process.terminate();raise RuntimeError('Server startup timeout')
    evidence={'evidenceId':eid,'codeCommit':sha,'workingTreeClean':clean,'developmentOnly':args.allow_dirty,
              'inputTruth':'TWO_SYNTHETIC_GEOMETRIES_PLUS_THREE_EXISTING_RECIPE_REFERENCE_SNAPSHOTS_NOT_PHYSICALLY_VALIDATED','physicalPrintValidated':False,'generations':[]}
    try:
        proc=start()
        with httpx.Client(base_url=url,headers={'X-Tenant-Id':tenant},timeout=120,trust_env=False) as client:
            def get(mid):
                r=client.get('/api/product-models/'+mid+'/composition');r.raise_for_status();return r.json()
            client.get('/admin/recipes/assets/model-compositions.js').raise_for_status()
            refs=client.get('/api/product-models/recipe-references');refs.raise_for_status()
            for ref in refs.json()['items']:
                r=client.post('/api/product-models',json={'draft':ref['draft'],'expectedRevision':0});r.raise_for_status();models.append(r.json())
            for index,item in enumerate(models):
                mid=item['id'];initial=get(mid)
                assert initial['surfaces'] or item['draft'].get('recipeReference',{}).get('draft',{}).get('family')=='STAGGERED_OPEN_CUBBY'
                placements=[{'componentId':f['componentId'],'assetId':art[index]['id'],'page':0,'rotation':0} for f in initial['surfaces'] if f['componentId']!='back'] if index<2 else []
                hashes=[];pixels=[];artwork_hashes=[]
                for scene in (['STUDIO','WARM_ROOM','COOL_ROOM'] if index<2 else ['STUDIO']):
                    selection={'sku':'FIXTURE-'+str(index),'scene':scene,'placements':placements}
                    payload={'expectedRevision':item['revision'],'inputHash':item['inputHash'],'assumptionsAccepted':True,'selection':selection}
                    r=client.post('/api/product-models/'+mid+'/composition',json=payload);r.raise_for_status()
                    deadline=time.monotonic()+920
                    while time.monotonic()<deadline:
                        state=get(mid)
                        if state['state'] not in {'queued','running'}:break
                        time.sleep(2)
                    assert state['state']=='succeeded' and state['generated'] and not state['stale'],state
                    folder=model_compositions.folder_for(data,tenant,mid)/'generations'/state['generationId']
                    reopen=subprocess.run([find_blender(),'-b',str(folder/'model.blend'),'--python-exit-code','1','--python',str(ROOT/'scripts/check_print_blend.py'),'--',str(folder)],capture_output=True,timeout=120,creationflags=flags)
                    (base/(str(index)+'-'+scene+'-reopen.log')).write_bytes(reopen.stdout+reopen.stderr)
                    assert reopen.returncode==0 and b'PRINT_BLEND_REOPEN_PASS' in reopen.stdout
                    m=state['manifest'];hashes.append(m['spec']['engineeringHash']);pixels.append(m['files']['beauty.png']);artwork_hashes.append(m['package']['artworkHash'])
                    for name in ['beauty.png','front-closed.png','model.glb','model.blend','geometry.json']:
                        client.get(f'/api/product-models/{mid}/composition/files/{name}',params={'workspace':tenant,'generation':state['generationId']}).raise_for_status()
                    evidence['generations'].append({'modelId':mid,'scene':scene,'generationId':state['generationId'],'renderInfo':m['renderInfo'],
                        'engineeringHash':m['spec']['engineeringHash'],'artworkHash':m['package']['artworkHash'],'files':m['files'],'blendReopen':True})
                    print(json.dumps({'geometry':item['draft']['geometry'],'scene':scene,'status':'PASS'}),flush=True)
                assert len(set(hashes))==1 and len(set(artwork_hashes))==1 and len(set(pixels))==(3 if index<2 else 1)
                assert any(x['id']==mid and x['templateState']=='PREVIEW_AVAILABLE' for x in client.get('/api/product-models').json()['items'])
                changed={**item['draft'],'widthMm':item['draft']['widthMm']+1}
                r=client.put('/api/product-models/'+mid,json={'draft':changed,'expectedRevision':1});r.raise_for_status()
                assert get(mid)['stale']
                assert client.get(f'/api/product-models/{mid}/composition/files/model.glb',params={'workspace':tenant,'generation':state['generationId']}).status_code==409
            proc.terminate();proc.wait(timeout=30);proc=start()
            for i,item in enumerate(models):
                assert get(item['id'])['stale']
                if i<2:
                    asset_usage.classify(data,tenant,art[i]['id'],'REFERENCE','Synthetic revocation after restart',1)
                    assert not get(item['id'])['generated']
                    assert print_assets.asset(data,tenant,art[i]['id'])[0]['id']==art[i]['id']
                    asset_usage.classify(data,tenant,art[i]['id'],'ARTWORK','Restore fixture for UI checks',2)
                restored=client.put('/api/product-models/'+item['id'],json={'draft':item['draft'],'expectedRevision':2});restored.raise_for_status()
                assert get(item['id'])['generated'] and not get(item['id'])['stale']
            evidence.update(status='PASS',sceneGeometryIdentity=True,sceneArtworkIdentity=True,scenePixelsDistinct=True,
                restartPreserved=True,revocationBlocked=True,staleDownloadsBlocked=True,originalsPreserved=True)
        if args.keep_server:atomic_json(base/'dev-server.json',{'url':url,'pid':proc.pid,'dataRoot':str(data)})
    except Exception as exc:evidence.update(status='FAIL',error=str(exc));raise
    finally:
        if proc and proc.poll() is None and (not args.keep_server or evidence.get('status')!='PASS'):
            proc.terminate();proc.wait(timeout=30)
        atomic_json(base/'evidence.json',evidence);log.close()
        print(json.dumps({'evidenceFile':str(base/'evidence.json'),'status':evidence.get('status'),'url':url}),flush=True)


if __name__=='__main__':main()
