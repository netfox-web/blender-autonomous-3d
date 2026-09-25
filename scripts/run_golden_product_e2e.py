"""Issue 4: isolated HTTP and real Blender evidence on clean CODE."""
import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--allow-dirty',action='store_true')
    parser.add_argument('--one',action='store_true',help='Development smoke only')
    args=parser.parse_args()
    import httpx
    from fox3d.golden_product import SKUS
    from fox3d.golden_preview import folder_for,validate_generation,DOWNLOADS
    from fox3d.blender import find_blender
    from fox3d.ids import sha256_bytes
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    clean=not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    if (not clean or args.one) and not args.allow_dirty:
        raise SystemExit('Formal evidence requires clean CODE and all SKU cases')
    gid=str(uuid.uuid4());folder=ROOT/'.fox3d-work'/'golden-e2e'/gid
    folder.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    log=(folder/'server.log').open('w',encoding='utf-8')
    command=[sys.executable,str(ROOT/'scripts/run_recipe_admin.py'),'--port',str(port),'--data-root',str(folder/'data')]
    def start(client):
        process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(180):
            if process.poll() is not None:raise RuntimeError('Server stopped; see server.log')
            try:
                if client.get('/api/recipe-library/health').status_code==200:return process
            except httpx.HTTPError:pass
            time.sleep(1)
        process.terminate();raise RuntimeError('Startup timeout')
    evidence={'generationId':gid,'evidenceCodeCommit':sha,'workingTreeClean':clean,'developmentOnly':args.allow_dirty,
              'instructionIssue':4,'realBlender':False,'usedMock':False,'products':[],
              'historicalArtwork':'BLOCKED_MISSING_SOURCE','engineeringReady':False,'productionReady':False,'frontOpen':'BLOCKED_ARTICULATION_AUTHORITY'}
    process=None
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'X-Tenant-Id':'golden-e2e'},timeout=60) as client:
            process=start(client)
            assert client.get('/admin/recipes/golden').status_code==200
            cases=[(s,'FIXTURE_MASTER_V1') for s in SKUS]
            if args.one:cases=cases[:1]
            else:cases.append((SKUS[0],'FIXTURE_SINGLE_V1'))
            for sku,version in cases:
                base='/api/recipe-library/golden/'+sku
                plan=client.get(base+'/plan',params={'version':version}).json()
                assert plan['ready'] and plan['blenderAvailable']
                r=client.post(base+'/generate',json={'version':version,'planHash':plan['planHash'],'assumptionsAccepted':True})
                assert r.status_code==202,r.text
                deadline=time.monotonic()+1000
                while time.monotonic()<deadline:
                    state=client.get(base+'/status',params={'version':version}).json()
                    if state['state'] not in ('queued','running'):break
                    time.sleep(2)
                assert state['state']=='succeeded' and state['generated'],state
                source=folder_for(folder/'data','golden-e2e',sku)/'generations'/state['generationId']
                target=folder/(sku+'-'+version)
                shutil.copytree(source,target)
                manifest=validate_generation(target,sku,version)
                for fmt,name in DOWNLOADS.items():
                    r=client.get(base+'/download/'+fmt,params={'workspace':'golden-e2e','generation':state['generationId']})
                    assert r.status_code==200,r.text[:300]
                    assert sha256_bytes(r.content)==sha256_bytes((target/name).read_bytes())
                reopen=subprocess.run([find_blender(),'-b',str(target/'model.blend'),'--python-exit-code','1','--python',str(ROOT/'scripts/check_golden_blend.py'),'--',str(target)],
                    capture_output=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                (target/'reopen.log').write_bytes(reopen.stdout+reopen.stderr)
                assert reopen.returncode==0 and b'GOLDEN_BLEND_REOPEN_PASS' in reopen.stdout,reopen.stdout[-1500:]
                evidence['products'].append({'sku':sku,'version':version,'generationId':state['generationId'],
                    'engineeringHash':manifest['engineeringHash'],'artworkHash':manifest['package']['artworkHash'],
                    'packageHash':manifest['package']['packageHash'],'renderInfo':state['renderInfo'],
                    'manifestSha256':sha256_bytes((target/'manifest.json').read_bytes()),'manifest':manifest,'blendReopenVerified':True})
                print(json.dumps({'sku':sku,'version':version,'status':'REAL_VERIFIED'}),flush=True)
            assert len({p['engineeringHash'] for p in evidence['products']})==1
            if not args.one:assert len({p['artworkHash'] for p in evidence['products'][:4]})==4
            process.terminate();process.wait(timeout=30);process=start(client)
            latest={p['sku']:p for p in evidence['products']}
            for sku,p in latest.items():
                s=client.get('/api/recipe-library/golden/'+sku+'/status',params={'version':p['version']}).json()
                assert s['generated'] and s['generationId']==p['generationId']
            evidence.update(status='PASS',realBlender=True,restartPersistenceVerified=True)
    except Exception as exc:
        evidence.update(status='FAIL',error=str(exc));raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=30)
        log.close()
        (folder/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print(str(folder/'evidence.json'),flush=True)


if __name__=='__main__':main()
