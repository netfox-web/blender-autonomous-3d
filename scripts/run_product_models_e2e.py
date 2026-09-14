"""Clean CODE acceptance: actual HTTP, real Blender, reopen, stale invalidation and restart.

Uses synthetic dimensions/artwork in isolated local storage. Never treats NAS filenames
or sticker dimensions as product measurements. Does not contact production services.
"""
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
    from PIL import Image
    from fox3d.recipe_3d import atomic_json
    from fox3d import nas_catalog, product_models
    from fox3d.blender import find_blender
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-dirty',action='store_true');p.add_argument('--keep-server',action='store_true')
    args=p.parse_args()
    clean=not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    if not clean and not args.allow_dirty:raise SystemExit('Formal evidence requires clean CODE')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    eid=str(uuid.uuid4());folder=ROOT/'.fox3d-work'/'models-e2e'/eid[:8];folder.mkdir(parents=True)
    data=folder/'d';source=folder/'sources';sources=[]
    buf=io.BytesIO();Image.new('RGB',(300,200),'#27664f').save(buf,'PNG');original=buf.getvalue()
    for family in nas_catalog.FAMILIES:
        group=source/family/'DN0123 FIXTURE';group.mkdir(parents=True)
        (group/'65x45 貼紙.png').write_bytes(original)
        sources.append({'id':family,'family':family,'path':str(group.parent)})
    atomic_json(data/'nas-catalog-config.json',{'sources':sources})
    nas_catalog.scan(data)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    url=f'http://127.0.0.1:{port}';proc=None;log=(folder/'server.log').open('w',encoding='utf-8')
    env={**os.environ,'FOX3D_MOCK_BLENDER':'0','PYTHONIOENCODING':'utf-8'}
    command=[sys.executable,str(ROOT/'scripts/run_recipe_admin.py'),'--port',str(port),'--data-root',str(data)]
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    def start():
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=flags)
        for _ in range(120):
            if process.poll() is not None:raise RuntimeError('Server failed to start')
            try:
                r=httpx.get(url+'/api/recipe-library/health',timeout=1,trust_env=False)
                if r.status_code==200:
                    assert r.json()['blenderAvailable'];return process
            except httpx.HTTPError:pass
            time.sleep(.5)
        process.terminate();process.wait(timeout=30);raise RuntimeError('Server startup timeout')
    evidence={'evidenceId':eid,'codeCommit':sha,'workingTreeClean':clean,'developmentOnly':args.allow_dirty,
        'inputTruth':'SYNTHETIC_FIXTURE_NOT_NAS_MEASUREMENT','physicalPrintValidated':False,'liveMachineControl':False,'models':[]}
    try:
        proc=start()
        with httpx.Client(base_url=url,headers={'X-Tenant-Id':'sonaqueen-home'},timeout=120,trust_env=False) as client:
            def get(path=''):r=client.get('/api/product-models'+path);r.raise_for_status();return r.json()
            def post(path,payload=None):r=client.post('/api/product-models'+path,json=payload);r.raise_for_status();return r.json()
            catalog=get('/catalog');assert catalog['fileCount']==7 and len(catalog['familyCounts'])==7
            files=get('/catalog/'+catalog['items'][0]['id']+'/files');a=post('/files/'+files['items'][0]['id']+'/import')
            assert not a['provenance']['physicalDimensionsVerified']
            assert not a['usage']['canUseForModel'] and not a['usage']['canUseForPrint']
            usage_url='/api/product-models/assets/'+a['id']+'/usage'
            blocked={'name':'Blocked fixture','family':'mat','variants':[{'sku':'B','artworkAssetId':a['id']}]}
            assert client.post('/api/product-models',json={'draft':blocked,'expectedRevision':0}).status_code==422
            r=client.put(usage_url,json={'role':'REFERENCE','note':'Synthetic reference fixture','expectedRevision':0});r.raise_for_status()
            assert client.post('/api/product-models',json={'draft':blocked,'expectedRevision':0}).status_code==422
            r=client.put(usage_url,json={'role':'ARTWORK','note':'Synthetic solid-color artwork fixture for role-gate acceptance only','expectedRevision':1});r.raise_for_status()
            assert r.json()['usage']['canUseForModel']
            evidence['assetUsage']={'unclassifiedBlocked':True,'referenceBlocked':True,'explicitArtworkAccepted':True,'assetId':a['id']}
            pending=post('',{'draft':{'name':'FIXTURE 噴瓶，待補曲面','family':'spray_bottle'},'expectedRevision':0})
            assert not pending['readiness']['previewReady']
            for geometry in ['OPEN_CABINET','HINGED_CABINET','RECTANGLE']:
                draft={'name':'FIXTURE '+geometry,'family':'cabinet' if geometry!='RECTANGLE' else 'mat',
                    'geometry':geometry,'widthMm':424. if geometry!='RECTANGLE' else 400.,
                    'depthMm':295. if geometry!='RECTANGLE' else 5.,'heightMm':900. if geometry!='RECTANGLE' else 600.,
                    'panelMm':15.,'backMm':3.,'doorMm':15.,'gapMm':2.,'rows':3,
                    'dimensionEvidence':'Synthetic mm fixture; NOT actual product measurements',
                    'structureEvidence':'Synthetic regular box components; no physical validation',
                    'variants':[{'sku':'FIXTURE-A','artworkAssetId':a['id']}],
                    'printFaces':[{'name':'reference','widthMm':100.,'heightMm':200.,'evidence':'Synthetic print face only'}]}
                item=post('',{'draft':draft,'expectedRevision':0});mid=item['id']
                post('/'+mid+'/preview',{'expectedRevision':1,'inputHash':item['inputHash'],'assumptionsAccepted':True})
                deadline=time.monotonic()+660
                while time.monotonic()<deadline:
                    state=get('/'+mid+'/preview')
                    if state['state'] not in {'queued','running'}:break
                    time.sleep(2)
                assert state['state']=='succeeded' and state['generated'],state
                out=product_models.folder(data,'sonaqueen-home',mid)/'generations'/state['generationId']
                reopen=subprocess.run([find_blender(),'-b',str(out/'model.blend'),'--python-exit-code','1','--python',str(ROOT/'scripts/check_product_model_blend.py'),'--',str(out)],capture_output=True,timeout=90,creationflags=flags)
                (folder/(geometry+'-reopen.log')).write_bytes(reopen.stdout+reopen.stderr)
                assert reopen.returncode==0 and b'PRODUCT_MODEL_BLEND_REOPEN_PASS' in reopen.stdout
                for fmt in ['png','blend','glb','geometry']:
                    client.get(f'/api/product-models/{mid}/files/{fmt}',params={'workspace':'sonaqueen-home','generation':state['generationId']}).raise_for_status()
                changed={**item['draft'],'widthMm':item['draft']['widthMm']+1}
                r=client.put('/api/product-models/'+mid,json={'draft':changed,'expectedRevision':1});r.raise_for_status()
                assert get('/'+mid+'/preview')['stale']
                assert client.get(f'/api/product-models/{mid}/files/glb',params={'workspace':'sonaqueen-home','generation':state['generationId']}).status_code==409
                evidence['models'].append({'id':mid,'geometry':geometry,'generationId':state['generationId'],'renderInfo':state['renderInfo'],'reopenPassed':True,'staleDownloadBlocked':True})
            proc.terminate();proc.wait(timeout=30);proc=start()
            assert len(get()['items'])==4
            assert get('/assets')['items'][0]['usage']['role']=='ARTWORK'
            r=client.put(usage_url,json={'role':'REFERENCE','note':'Revocation fixture after restart','expectedRevision':2});r.raise_for_status()
            for model in evidence['models']:
                assert client.get(f'/api/product-models/{model["id"]}/files/glb',params={'workspace':'sonaqueen-home','generation':model['generationId']}).status_code==422
            evidence['assetUsage'].update(restartPreserved=True,revokedDownloadsBlocked=True)
            r=client.put(usage_url,json={'role':'ARTWORK','note':'Restore synthetic fixture for stale checks','expectedRevision':3});r.raise_for_status()
            for model in evidence['models']:assert get('/'+model['id']+'/preview')['stale']
            assert all(f.read_bytes()==original for f in source.rglob('*.png'))
            evidence.update(status='PASS',restartVerified=True,originalsUnchanged=True,stickerSizesNeverPromoted=True)
        if args.keep_server:atomic_json(folder/'dev-server.json',{'url':url,'pid':proc.pid,'dataRoot':str(data)})
    except Exception as exc:
        evidence.update(status='FAIL',error=str(exc));raise
    finally:
        if proc and proc.poll() is None and (not args.keep_server or evidence.get('status')!='PASS'):
            proc.terminate();proc.wait(timeout=30)
        atomic_json(folder/'evidence.json',evidence);log.close()
        print(json.dumps({'evidenceFile':str(folder/'evidence.json'),'status':evidence.get('status'),'url':url}),flush=True)

if __name__=='__main__':main()
