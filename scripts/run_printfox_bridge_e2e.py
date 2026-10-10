"""Isolated real PrintFox HTTP + Fox3D bridge test, with synthetic art/jobs.

Exports committed PrintFox app code only; never reads its .env or local data.
No worker, AI provider, Illustrator, production print queue or machine is used.
"""
from __future__ import annotations

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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
TEST_TOKEN = 'SYNTHETIC-BRIDGE-ACCEPTANCE-ONLY'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--printfox-repo', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true')
    parser.add_argument('--keep-servers', action='store_true')
    args = parser.parse_args()
    import httpx
    from PIL import Image, ImageDraw
    from fox3d.ids import sha256_bytes
    from fox3d.print_assets import workspace
    from fox3d.recipe_3d import atomic_json
    from fox3d import print_preview
    from fox3d.blender import find_blender

    sha = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    clean = not subprocess.check_output(['git','status','--porcelain'], cwd=ROOT, text=True).strip()
    if not clean and not args.allow_dirty:
        raise SystemExit('Formal evidence requires clean CODE')
    eid = str(uuid.uuid4()); folder = ROOT / '.fox3d-work' / 'pfb-e2e' / eid[:8]
    pf = folder/'pf'; data = folder/'d'; pf.mkdir(parents=True); data.mkdir()
    pf_sha = subprocess.check_output(['git','rev-parse','HEAD'], cwd=args.printfox_repo, text=True).strip()
    archive = subprocess.check_output(['git','archive','--format=zip',pf_sha,'app'], cwd=args.printfox_repo)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for info in z.infolist():
            if not (pf/info.filename).resolve().is_relative_to(pf.resolve()): raise RuntimeError('Unsafe archive path')
        z.extractall(pf)
    def port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); return sock.getsockname()[1]
    pf_port, bridge_port = port(), port()
    pf_url, bridge_url = f'http://127.0.0.1:{pf_port}', f'http://127.0.0.1:{bridge_port}'
    atomic_json(data/'printfox-connection.json', {'baseUrl':pf_url})
    inherited = {k:v for k,v in os.environ.items() if k.upper() in {
        'SYSTEMROOT','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','HOME'}}
    env = {**inherited, 'PYTHONIOENCODING':'utf-8','PRINTFOX_TOKEN':TEST_TOKEN,
           'PRINTFOX_DATA_DIR':str(pf/'data'),'PRINTFOX_DB_PATH':str(pf/'data'/'db.sqlite3'),
           'PRINTFOX_TEMPLATE_DIR':str(pf/'templates'),'PRINTFOX_BLANK_DIR':str(pf/'blanks'),
           'PRINTFOX_GENERATED_DIR':str(pf/'generated'),'PRINTFOX_COMFY_URL':'http://127.0.0.1:1',
           'PRINTFOX_FLEET_ENABLED':'0'}
    log=(folder/'servers.log').open('w',encoding='utf-8'); processes=[]
    def start(command,cwd,process_env,url,health):
        proc=subprocess.Popen(command,cwd=cwd,env=process_env,stdout=log,stderr=log,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));processes.append(proc)
        for _ in range(90):
            if proc.poll() is not None:raise RuntimeError('Test server failed; inspect servers.log')
            try:
                if httpx.get(url+health,timeout=1,trust_env=False).status_code==200:return proc
            except httpx.HTTPError:pass
            time.sleep(.5)
        raise RuntimeError('Server startup timed out')
    evidence={'evidenceId':eid,'codeCommit':sha,'workingTreeClean':clean,'developmentOnly':args.allow_dirty,
              'printfoxCodeCommit':pf_sha,'printfoxSource':'COMMITTED_APP_ARCHIVE_NO_LOCAL_MODIFICATIONS',
              'artworkTruth':'SYNTHETIC_FIXTURE','aiGenerationExecuted':False,'productionAuthenticated':False,
              'liveMachineControl':False,'physicalPrintValidated':False}
    command=[sys.executable,str(ROOT/'scripts/run_recipe_admin.py'),'--port',str(bridge_port),'--data-root',str(data)]
    try:
        start([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(pf_port)],pf,env,pf_url,'/api/health')
        proc=start(command,ROOT,inherited,bridge_url,'/api/recipe-library/health')
        with httpx.Client(base_url=pf_url,headers={'X-Console-Token':TEST_TOKEN},timeout=30,trust_env=False) as remote, \
             httpx.Client(base_url=bridge_url,headers={'X-Tenant-Id':'bridge-e2e'},timeout=120,trust_env=False) as client:
            im=Image.new('RGB',(1200,800),'#eadfca');draw=ImageDraw.Draw(im);draw.rectangle((50,80,400,600),fill='#177465');draw.ellipse((650,120,1060,530),fill='#dd7733')
            buf=io.BytesIO();im.save(buf,'PNG');original=buf.getvalue()
            r=remote.post('/api/designs/upload',files={'file':('FIXTURE-bridge.png',original,'image/png')},data={'title':'FIXTURE · geometry / color blocks'});r.raise_for_status();did=r.json()['design']['id']
            base='/api/print-workspace/printfox'
            assert client.get(base+'/designs').status_code==401
            r=client.post(base+'/connection',json={'token':TEST_TOKEN});r.raise_for_status()
            assert TEST_TOKEN not in r.text and 'HttpOnly' in r.headers['set-cookie']
            assert client.get(base+'/designs').json()['items'][0]['id']==did
            thumb=client.get(base+f'/designs/{did}/preview?workspace=bridge-e2e');thumb.raise_for_status()
            r=client.post(base+f'/designs/{did}/import');r.raise_for_status();aid=r.json()['id'];assert aid==sha256_bytes(original)
            request={'requestId':str(uuid.uuid4()),'prompt':'SYNTHETIC CONTRACT TEST DO NOT RUN WORKER','size':'wide','count':1,'engine':'comfyui'}
            r=client.post(base+'/tasks',json=request);r.raise_for_status();task=r.json();assert task['state']=='pending'
            job=remote.get('/api/jobs/'+task['remoteJobId']).json()['job']
            assert job['params']['continuous'] is False and job['params']['per_style']==1
            r=client.post(base+'/tasks/'+task['requestId']+'/cancel');r.raise_for_status();assert r.json()['state']=='canceled'
            draft={'sku':'FIXTURE-BRIDGE','name':'隔離測試圖稿（非生產）','layout':'FLAT',
                   'panels':[{'label':'測試印刷面','assetId':aid,'imageWidthMm':101.6,'imageHeightMm':67.7333333333333}]}
            j=client.post('/api/print-workspace/jobs',json={'draft':draft});j.raise_for_status();jid=j.json()['id']
            jobbase='/api/print-workspace/jobs/'+jid;j=client.get(jobbase).json()
            version={'expectedRevision':j['revision'],'planHash':j['plan']['planHash']}
            proof=client.post(jobbase+'/proof',json=version);proof.raise_for_status();bid=proof.json()['bundleId']
            bundle=client.get(jobbase+'/bundles/'+bid,params={'workspace':'bridge-e2e'});bundle.raise_for_status()
            assert client.post(jobbase+'/release',json=version).status_code==422
            r=client.post(jobbase+'/preview',json=version);r.raise_for_status()
            for _ in range(300):
                preview=client.get(jobbase+'/preview').json()
                if preview['state'] not in ('queued','running'):break
                time.sleep(1)
            assert preview['state']=='succeeded' and preview['generated'],preview
            out=print_preview.folder_for(data,'bridge-e2e',jid)/'generations'/preview['generationId']
            manifest=print_preview.validate(out)
            reopen=subprocess.run([find_blender(),'-b',str(out/'model.blend'),'--python-exit-code','1','--python',str(ROOT/'scripts/check_print_blend.py'),'--',str(out)],capture_output=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (folder/'reopen.log').write_bytes(reopen.stdout+reopen.stderr)
            assert reopen.returncode==0 and b'PRINT_BLEND_REOPEN_PASS' in reopen.stdout
            proc.terminate();proc.wait(timeout=30);start(command,ROOT,inherited,bridge_url,'/api/recipe-library/health')
            assert client.get(base+'/designs').status_code==401
            client.post(base+'/connection',json={'token':TEST_TOKEN}).raise_for_status()
            replay=client.post(base+'/tasks',json=request);replay.raise_for_status();assert replay.json()['remoteJobId']==task['remoteJobId']
            assert len(remote.get('/api/jobs').json()['jobs'])==1
            assert client.get(jobbase+'/preview').json()['generationId']==preview['generationId']
            assert (workspace(data,'bridge-e2e')/'assets'/aid/'original.bin').read_bytes()==original
            for p in data.rglob('*.json'):assert TEST_TOKEN not in p.read_text(encoding='utf-8')
            evidence.update(status='PASS',originalSha256=aid,proofZipSha256=sha256_bytes(bundle.content),proofZipBytes=len(bundle.content),
                            designId=did,bridgeRequestId=task['requestId'],remoteJobId=task['remoteJobId'],printJobId=jid,
                            generationId=preview['generationId'],renderInfo=manifest['renderInfo'],reopenVerified=True,
                            restartVerified=True,sessionDiscardedOnRestart=True,duplicateRemoteJobs=0,
                            previewManifestSha256=sha256_bytes((out/'manifest.json').read_bytes()))
        if args.keep_servers:
            atomic_json(folder/'dev-servers.json',{'printfoxUrl':pf_url,'bridgeUrl':bridge_url,'pids':[p.pid for p in processes if p.poll() is None], 'fixtureTokenConstant':'TEST_TOKEN in this script; not a real credential'})
    except Exception as exc:
        evidence.update(status='FAIL',error=str(exc));raise
    finally:
        if not args.keep_servers or evidence.get('status')!='PASS':
            for p in processes:
                if p.poll() is None:p.terminate();p.wait(timeout=30)
        log.close();atomic_json(folder/'evidence.json',evidence)
        print(json.dumps({'evidenceFile':str(folder/'evidence.json'),'status':evidence.get('status'),'bridgeUrl':bridge_url,'printfoxUrl':pf_url}),flush=True)


if __name__=='__main__':main()
