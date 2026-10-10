"""Test-only external hard-kill orchestration; no production crash API.

Mock mode tests actual process recovery with MOCK publications/artifact validation.
Real mode uses the existing Platform/Blender generation and full publication verifier.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    signal=path.with_name(path.name+'.signal')
    signal.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    signal.replace(path)  # publish test checkpoints whole before parent kills


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mock_artifacts():
    from fox3d import model_compositions as c
    from fox3d.recipe_3d import atomic_json, read_json
    from fox3d.ids import stable_hash, sha256_bytes
    def generate(platform, tenant, mid, draft, *, revision, generation_id, **kwargs):
        target=c.folder_for(platform.root,tenant,mid)/'generations'/generation_id
        target.mkdir(parents=True,exist_ok=False)
        manifest={'generationId':generation_id,'historyVersion':1,'draft':draft,'sourceRevision':revision,
                  'planHash':stable_hash(draft),'scene':draft['scene'],'inputAuthorityHash':draft['inputAuthority']['hash'],
                  'package':{'placements':[{'originalAssetId':p['assetId']} for p in draft['placements']]},
                  'renderInfo':{'realBlender':False,'usedMock':True}}
        atomic_json(target/'manifest.json',manifest)
        atomic_json(target/'published.json',{'manifestSha256':sha256_bytes((target/'manifest.json').read_bytes())})
        (target/'beauty.png').write_bytes(b'MOCK artifact, not REAL_RENDER')
        return {'generated':True,'stale':False,'generationId':generation_id}
    c.generate=generate
    c.print_preview.validate=lambda path:read_json(path/'manifest.json')


def child_run(args):
    from PIL import Image
    from fox3d import print_assets,asset_usage,product_models as m,model_compositions as c,model_batches as b,variant_authority as a
    from fox3d.recipe_preview_service import RecipePreviewService
    root=args.root/'d';tenant='t'
    model=m.save(root,tenant,{'name':'PROCESS RECOVERY SYNTHETIC FIXTURE','family':'coaster','geometry':'RECTANGLE',
                            'widthMm':100.,'heightMm':100.,'depthMm':5.,'dimensionEvidence':'SYNTHETIC, not measured',
                            'structureEvidence':'SYNTHETIC fixture'},0)
    a.declare(root,tenant,model,'SYNTHETIC_FIXTURE',actor='PROCESS_RECOVERY_HARNESS',reason='No physical truth')
    raw=io.BytesIO();Image.new('RGB',(100,100),'#b65030').save(raw,'PNG')
    asset=print_assets.import_asset(root,tenant,raw.getvalue(),'synthetic.png')
    asset_usage.classify(root,tenant,asset['id'],'ARTWORK','Synthetic process fixture',0)
    draft=b.snapshot(root,tenant,model,{'name':'process recovery','selections':[
        {'sku':sku,'scene':'STUDIO','placements':[{'componentId':'surface','assetId':asset['id']}]} for sku in ['A','B']]})
    save(args.root/'context.json',{'tenant':tenant,'model':model,'draft':draft,'case':args.case,'mockArtifacts':args.mock})
    if args.mock:
        mock_artifacts();platform=SimpleNamespace(root=root)
    else:
        from fox3d.platform import Platform
        platform=Platform(root)
        assert not platform.mock_blender and platform.runtime.available()
    def stop_at(path):
        save(args.root/'reached.json',{'case':args.case,'pid':os.getpid(),'committedPath':str(path)})
        threading.Event().wait()  # parent must hard-kill; never inject an exception
    original_once=b._once
    def observed_once(path,value):
        original_once(path,value)
        if (args.case=='A' and path.name=='request.json' or args.case=='B' and path.name=='0.json'
                or args.case=='C' and path.name=='1.json'):
            stop_at(path)
    b._once=observed_once
    original_atomic=b.atomic_json
    def observed_atomic(path,value):
        original_atomic(path,value)
        if args.case=='A_PROGRESS' and path.parent.name=='batches':stop_at(path)
    b.atomic_json=observed_atomic
    service=RecipePreviewService(platform,folder_fn=c.folder_for,status_fn=c.status,generate_fn=b.generate)
    submitted=service.submit(tenant,model['id'],{'draft':draft,'revision':model['revision']})
    save(args.root/'submitted.json',submitted)
    threading.Event().wait()


def child_recover(args):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fox3d import model_compositions as c,model_batches as b
    from fox3d.product_models_api import product_models_router
    from fox3d.recipe_3d import read_json,atomic_json
    context=read(args.root/'context.json');root=args.root/'d';tenant=context['tenant'];model=context['model']
    if args.mock:mock_artifacts()
    def unexpected_render(*a,**kw):
        save(args.root/'unexpected-replay.json',{'called':True})
        raise AssertionError('restart must not render')
    c.generate=unexpected_render
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=root,mock_blender=args.mock)))
    with TestClient(app) as client:
        path='/api/product-models/'+model['id'];headers={'X-Tenant-Id':tenant}
        first=client.get(path+'/composition',headers=headers)
        second=client.get(path+'/composition',headers=headers)
        history=client.get(path+'/compositions',headers=headers)
        result={'pid':os.getpid(),'status':first.status_code,'body':first.json(),
                'repeatStatus':second.status_code,'repeatBody':second.json(),'history':history.json(),
                'unexpectedReplay':(args.root/'unexpected-replay.json').exists()}
        base=c.folder_for(root,tenant,model['id']);anchors=list((base/'batches').glob('*/request.json'))
        assert len(anchors)==1
        anchor=anchors[0].parent
        result['requestIdentity']=b._identity(read_json(anchors[0]),tenant,model['id'],anchor.name)[0]
        result['terminalReceipt']=read_json(anchor/'terminal.json')
        result['outerServiceState']=read_json(base/'state.json')
        result['exclusiveReplayRejected']=[]
        for target in [anchors[0],*sorted(anchor.glob('[0-9]*.json'))]:
            before=target.read_bytes()
            try:b._once(target,read_json(target))
            except FileExistsError:result['exclusiveReplayRejected'].append(target.name)
            else:raise AssertionError('immutable receipt was overwritten')
            assert target.read_bytes()==before
        result['downloads']={}
        for row in result.get('body',{}).get('batch',{}).get('rows',[]):
            response=client.get(path+'/composition/files/beauty.png',headers=headers,
                                params={'workspace':tenant,'generation':row['generationId']})
            result['downloads'][row['generationId']]=response.status_code
        # Re-verification after restart must not trust a now-invalid publication seal.
        published=sorted((base/'generations').glob('*/published.json'))
        if published:
            target=published[0];original=target.read_bytes()
            try:
                atomic_json(target,{'manifestSha256':'tampered'})
                response=client.get(path+'/composition',headers=headers)
                result['tamperedPublicationStatus']=response.status_code
                invalid=[r for r in response.json().get('batch',{}).get('rows',[]) if r['generationId']==target.parent.name]
                result['tamperedPublicationUnavailable']=len(invalid)==1 and not invalid[0]['available']
            finally:target.write_bytes(original)
            response=client.get(path+'/composition',headers=headers)
            restored=[r for r in response.json().get('batch',{}).get('rows',[]) if r['generationId']==target.parent.name]
            result['restoredPublicationAvailable']=len(restored)==1 and restored[0]['available']
        save(args.root/'recovered.json',result)


def windows_lock(path):
    import ctypes
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    k.CreateFileW.restype=wintypes.HANDLE;k.CloseHandle.argtypes=[wintypes.HANDLE];k.CloseHandle.restype=wintypes.BOOL
    handle=k.CreateFileW(str(path),0x80000000,0x1|0x2,None,3,0x80,None)
    if handle==wintypes.HANDLE(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    def close():
        if not k.CloseHandle(handle):raise ctypes.WinError(ctypes.get_last_error())
    return close


def child_atomic(args):
    import logging
    from fox3d import recipe_3d as r
    class Marker(logging.Handler):
        def emit(self,record):
            if 'Transient Windows atomic replace contention' in record.getMessage():
                save(args.root/'reached.json',{'pid':os.getpid(),'message':record.getMessage(),'deleteSharingProbe':r._delete_sharing_error(args.root/'state.json')})
    logging.getLogger(r.__name__).addHandler(Marker())
    r.atomic_json(args.root/'state.json',{'value':'B'})


def child_atomic_recover(args):
    from fox3d import recipe_3d as r
    target=args.root/'state.json';before=read(target)
    temps={p.name:digest(p) for p in args.root.glob('*.tmp')}
    r.atomic_json(target,{'value':'B'})
    save(args.root/'recovered.json',{'pid':os.getpid(),'before':before,'after':read(target),
         'tempsBefore':temps,'tempsAfter':{p.name:digest(p) for p in args.root.glob('*.tmp')}})


def run_case(root,code_root,case,mock=True):
    root=Path(root).resolve();code_root=Path(code_root).resolve();root.mkdir(parents=True,exist_ok=False)
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--code-root',str(code_root),'--root',str(root),'--case',case]
    if mock:command.append('--mock')
    env={**os.environ,'FOX3D_MOCK_BLENDER':'1' if mock else '0','PYTHONIOENCODING':'utf-8'}
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    close=None
    if case=='D':
        assert sys.platform=='win32'
        save(root/'state.json',{'value':'A'})
        (root/'other-writer.tmp').write_bytes(b'owned by another writer; preserve')
        close=windows_lock(root/'state.json')
    with (root/'child.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(command+['--action','atomic' if case=='D' else 'run'],env=env,stdout=log,stderr=log,creationflags=flags)
        try:
            deadline=time.monotonic()+(900 if not mock else 45)
            while not (root/'reached.json').exists():
                if proc.poll() is not None:raise AssertionError('child exited before checkpoint: '+(root/'child.log').read_text(encoding='utf-8'))
                if time.monotonic()>deadline:raise TimeoutError('checkpoint timeout')
                time.sleep(.002 if case=='D' else .02)
            assert proc.poll() is None
            proc.kill()  # Windows TerminateProcess; POSIX SIGKILL, never graceful shutdown
            proc.wait(timeout=15)
            assert proc.returncode!=0
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=15)
            if close:close()
    assert read(root/'reached.json')['pid']==proc.pid
    facts=lambda:{str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file() and
                  ('generations' in p.parts or p.name=='request.json' or p.name in ['0.json','1.json'])}
    before=facts()
    pre={'facts':before,'orphanTemps':{str(p.relative_to(root)):digest(p) for p in root.rglob('*.tmp')},
         'terminalFiles':[str(p.relative_to(root)) for p in root.rglob('terminal.json')],
         'progress':[read(p) for p in (root/'d'/'master-compositions').glob('*/batches/*.json')]}
    save(root/'before-restart.json',pre)
    with (root/'restart.log').open('w',encoding='utf-8') as log:
        restarted=subprocess.run(command+['--action','atomic-recover' if case=='D' else 'recover'],env=env,stdout=log,stderr=log,timeout=90,creationflags=flags)
    assert restarted.returncode==0,(root/'restart.log').read_text(encoding='utf-8')
    recovered=read(root/'recovered.json')
    assert recovered['pid']!=proc.pid and before==facts()
    outcomes={'immutableFactsUnchanged':before==facts(),'noAutomaticReplay':not (root/'unexpected-replay.json').exists()}
    if case=='D':
        outcomes.update(parseValidOldOrNew=recovered['before'] in [{'value':'A'},{'value':'B'}],laterWriteExactB=recovered['after']=={'value':'B'},
                        orphanTempsIgnoredAndPreserved=recovered['tempsBefore']==recovered['tempsAfter'],
                        realSharingViolation=read(root/'reached.json')['deleteSharingProbe']==32)
    else:
        body=recovered['body'];batch=body.get('batch') or {};rows=batch.get('rows',[])
        wanted={'A':0,'A_PROGRESS':0,'B':1,'C':2}[case]
        outcomes.update(apiSuccess=recovered['status']==200,outerInterrupted=body.get('state')=='interrupted',
                        availableRowsExact=sum(r.get('available',False) for r in rows)==wanted and len(rows)==2,
                        downloadsExact=all(recovered['downloads'][r['generationId']]==(200 if r['available'] else 409) for r in rows),
                        immutableReplayRejected=len(recovered['exclusiveReplayRejected'])==1+wanted,
                        repeatStable=recovered['status']==recovered['repeatStatus'] and body==recovered['repeatBody'],
                        requestExact=recovered['requestIdentity']['batchId']==next((root/'d'/'master-compositions').glob('*/batches/*/request.json')).parent.name,
                        noPreKillTerminal=not pre['terminalFiles'])
        if wanted:outcomes.update(tamperedPublicationUnavailable=recovered['tamperedPublicationUnavailable'],restoredPublicationAvailable=recovered['restoredPublicationAvailable'])
    result={'case':case,'status':'PASS' if all(outcomes.values()) else 'FAIL','outcomes':outcomes,'os':sys.platform,
            'termination':'TerminateProcess' if sys.platform=='win32' else 'SIGKILL','childPid':proc.pid,'exitCode':proc.returncode,
            'restartPid':recovered['pid'],'classification':'REAL_PROCESS_RECOVERY',
            'artifactMode':'NOT_APPLICABLE' if case=='D' else ('MOCK_ARTIFACT_VALIDATION' if mock else 'REAL_BLENDER_FULL_PUBLICATION_VERIFIER'),
            'beforeRestart':pre,'recovered':recovered,'hardKillOrphanCleanup':'PARTIAL_NOT_SCAVENGED' if pre['orphanTemps'] else 'NO_ORPHAN_OBSERVED'}
    save(root/'result.json',result)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--code-root',type=Path,required=True);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--case',choices=['A','A_PROGRESS','B','C','D'],required=True);p.add_argument('--mock',action='store_true')
    p.add_argument('--action',choices=['run','recover','atomic','atomic-recover','parent'],default='parent');args=p.parse_args()
    sys.path.insert(0,str(args.code_root/'src'))
    if args.action=='parent':print(json.dumps(run_case(args.root,args.code_root,args.case,args.mock),ensure_ascii=False))
    else:{'run':child_run,'recover':child_recover,'atomic':child_atomic,'atomic-recover':child_atomic_recover}[args.action](args)


if __name__=='__main__':main()
