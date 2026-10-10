"""Local source PDF, HTTP proof, real Blender/reopen and restart evidence on clean CODE."""
import argparse
import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--allow-dirty',action='store_true')
    parser.add_argument('--artwork-review-note',required=True,help='Operator purpose review for the supplied source; no print calibration claim')
    args=parser.parse_args()
    import httpx
    from fox3d import print_assets, print_workspace, print_preview, asset_usage
    from fox3d.blender import find_blender
    from fox3d.ids import sha256_bytes
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    clean=not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    if not clean and not args.allow_dirty:raise SystemExit('Formal evidence requires clean CODE')
    eid=str(uuid.uuid4());folder=ROOT/'.fox3d-work'/'print-e2e'/eid[:8];folder.mkdir(parents=True)
    root=folder/'d';a=print_assets.import_asset(root,'print-e2e',args.source.read_bytes(),args.source.name)
    asset_usage.classify(root,'print-e2e',a['id'],'ARTWORK',args.artwork_review_note,0)
    assert a['info']['type']=='PDF' and len(a['info']['pages'])>=3
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    log=(folder/'server.log').open('w',encoding='utf-8')
    command=[sys.executable,str(ROOT/'scripts/run_recipe_admin.py'),'--port',str(port),'--data-root',str(root)]
    process=None
    def start(c):
        proc=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(180):
            if proc.poll() is not None:raise RuntimeError('Server stopped')
            try:
                if c.get('/api/recipe-library/health').status_code==200:return proc
            except httpx.HTTPError:pass
            time.sleep(1)
        proc.terminate();raise RuntimeError('Startup timeout')
    evidence={'evidenceId':eid,'codeCommit':sha,'workingTreeClean':clean,'developmentOnly':args.allow_dirty,
              'originalAssetSha256':a['id'],'sourceName':args.source.name,'cases':[],
              'liveMachineControl':False,'netfoxIntegration':'FILE_HANDOFF_ONLY_NOT_SUBMITTED',
              'physicalMeasurementsVerified':False,'actualArtworkReleased':False}
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'X-Tenant-Id':'print-e2e'},timeout=180) as c:
            process=start(c)
            assert c.get('/admin/recipes/print').status_code==200
            for layout in ['THREE_DOOR','FLAT']:
                d={'sku':'SOURCE-E2E-'+layout,'name':'原稿驗收（非印刷放行）','layout':layout,
                   'panels':[{'label':f'原稿第 {i+1} 頁','assetId':a['id'],'page':i,'rotation':90} for i in range(3 if layout=='THREE_DOOR' else 1)]}
                r=c.post('/api/print-workspace/jobs',json={'draft':d});assert r.status_code==200,r.text
                jid=r.json()['id'];base='/api/print-workspace/jobs/'+jid
                j=c.get(base).json();p=j['plan'];v={'expectedRevision':j['revision'],'planHash':p['planHash']}
                for row in p['panels']:
                    assert abs(row['trimWidthMm']-395)<.01 and abs(row['trimHeightMm']-280)<.01
                b=c.post(base+'/proof',json=v);assert b.status_code==200,b.text
                proof=b.json();download=c.get(base+'/bundles/'+proof['bundleId'],params={'workspace':'print-e2e'})
                assert download.status_code==200
                assert c.post(base+'/release',json={**v,'proofId':proof['bundleId']}).status_code==422
                generated=c.post(base+'/preview',json=v);assert generated.status_code==200,generated.text
                for _ in range(500):
                    s=c.get(base+'/preview').json()
                    if s['state'] not in ('queued','running'):break
                    time.sleep(2)
                assert s['state']=='succeeded' and s['generated'],s
                out=print_preview.folder_for(root,'print-e2e',jid)/'generations'/s['generationId']
                m=print_preview.validate(out)
                for name in print_preview.FILES:
                    r=c.get(base+'/preview/'+s['generationId']+'/'+name,params={'workspace':'print-e2e'})
                    assert r.status_code==200 and sha256_bytes(r.content)==m['files'][name]
                reopen=subprocess.run([find_blender(),'-b',str(out/'model.blend'),'--python-exit-code','1','--python',str(ROOT/'scripts/check_print_blend.py'),'--',str(out)],capture_output=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                (folder/(layout+'-reopen.log')).write_bytes(reopen.stdout+reopen.stderr)
                assert reopen.returncode==0 and b'PRINT_BLEND_REOPEN_PASS' in reopen.stdout,reopen.stdout[-1500:]
                case={'layout':layout,'jobId':jid,'generationId':s['generationId'],'planHash':p['planHash'],
                      'panels':p['panels'],'renderInfo':m['renderInfo'],'packedTextureAndUvReopen':True,
                      'proofBundleId':proof['bundleId'],'proofZipSha256':sha256_bytes(download.content),
                      'manifestSha256':sha256_bytes((out/'manifest.json').read_bytes())}
                evidence['cases'].append(case);print(json.dumps(case,ensure_ascii=False),flush=True)
            process.terminate();process.wait(timeout=30);process=start(c)
            for case in evidence['cases']:
                s=c.get('/api/print-workspace/jobs/'+case['jobId']+'/preview').json()
                assert s['generated'] and s['generationId']==case['generationId']
            evidence.update(status='PASS',restartVerified=True)
    except Exception as exc:
        evidence.update(status='FAIL',error=str(exc));raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=30)
        log.close();(folder/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print(str(folder/'evidence.json'),flush=True)


if __name__=='__main__':main()
