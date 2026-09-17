"""Test-only independent service processes and parent barriers, never a production API.

CI uses MOCK artifacts/validation. --real uses the unchanged Blender/publication
path. Signals, forced stale callbacks and delayed finally re-entry are test-only.
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

from batch_process_recovery import save, read, digest, mock_artifacts


def until(test, seconds=60):
    deadline=time.monotonic()+seconds
    while not test():
        if time.monotonic()>deadline:
            raise TimeoutError('test checkpoint timeout')
        time.sleep(.01)


def fixture(root):
    from PIL import Image
    from fox3d import print_assets, asset_usage, product_models as m, model_batches as b, variant_authority as a
    data=root/'d'; tenant='t'
    model=m.save(data,tenant,{'name':'CONCURRENCY SYNTHETIC FIXTURE','family':'coaster','geometry':'RECTANGLE',
        'widthMm':100.,'heightMm':100.,'depthMm':5.,'dimensionEvidence':'SYNTHETIC, not measured',
        'structureEvidence':'SYNTHETIC fixture'},0)
    a.declare(data,tenant,model,'SYNTHETIC_FIXTURE',actor='CONCURRENCY_HARNESS',reason='No physical truth')
    raw=io.BytesIO();Image.new('RGB',(100,100),'#b65030').save(raw,'PNG')
    asset=print_assets.import_asset(data,tenant,raw.getvalue(),'synthetic.png')
    asset_usage.classify(data,tenant,asset['id'],'ARTWORK','Synthetic race fixture',0)
    drafts={label:b.snapshot(data,tenant,model,{'name':label,'selections':[
        {'sku':label,'scene':'STUDIO','placements':[{'componentId':'surface','assetId':asset['id']}]}]}) for label in ['same','different']}
    save(root/'context.json',{'tenant':tenant,'model':model,'drafts':drafts})


def child(args):
    from fox3d import model_compositions as c, model_batches as b, recipe_preview_service as r
    from fox3d.recipe_3d import read_json
    context=read(args.root/'context.json');tenant=context['tenant'];model=context['model'];mid=model['id']
    tag=args.tag; out=args.root/tag;out.mkdir(exist_ok=True)
    if args.real:
        from fox3d.platform import Platform
        platform=Platform(args.root/'d')
        assert not platform.mock_blender and platform.runtime.available()
    else:
        mock_artifacts();platform=SimpleNamespace(root=args.root/'d')
    callbacks=[];run_calls=[];writes=[];renders=[];draft=context['drafts'][args.payload]
    original_atomic=r.atomic_json
    def observed_write(path,value):
        original_atomic(path,value)
        writes.append({'path':str(path),'value':dict(value),'timeNs':time.time_ns()})
        save(out/'writes.json',writes)
    r.atomic_json=observed_write
    original_generate=c.generate
    def render(*a,**kw):
        renders.append({'pid':os.getpid(),'generationId':kw['generation_id'],'timeNs':time.time_ns()})
        save(out/'renders.json',renders)
        callbacks.append(kw['on_job'])
        kw['on_job']({'jobId':'test-barrier-'+tag})
        save(out/'render-ready.json',{'pid':os.getpid(),'generationId':kw['generation_id']})
        until(lambda:(out/'render-release.json').exists(),1200)
        if kw['cancel_flag'].is_set():
            raise ValueError('test renderer stopped after cancellation')
        result=original_generate(*a,**kw)
        if not args.real:
            original_atomic(c.folder_for(platform.root,tenant,mid)/'latest.json',{'generationId':kw['generation_id']})
        return result
    c.generate=render
    original_once=b._once
    def once(path,value):
        if args.hold=='before-request' and path.name=='request.json':
            save(out/'checkpoint.json',{'pid':os.getpid(),'phase':'before-request','timeNs':time.time_ns()})
            threading.Event().wait()
        original_once(path,value)
    b._once=once
    original_progress=b.atomic_json
    def progress(path,value):
        original_progress(path,value)
        if args.hold=='after-progress' and path.parent.name=='batches':
            save(out/'checkpoint.json',{'pid':os.getpid(),'phase':'after-progress','timeNs':time.time_ns()})
            threading.Event().wait()
    b.atomic_json=progress
    service=r.RecipePreviewService(platform,folder_fn=c.folder_for,status_fn=c.status,generate_fn=b.generate)
    original_run=service._run
    def capture_run(*a,**kw):
        run_calls.append((a,kw))
        return original_run(*a,**kw)
    service._run=capture_run
    save(out/'ready.json',{'pid':os.getpid(),'timeNs':time.time_ns()})
    until(lambda:(args.root/args.barrier).exists())
    try:
        result=service.submit(tenant,mid,{'draft':draft,'revision':model['revision']})
        save(out/'submit.json',{'pid':os.getpid(),'accepted':True,'result':result,'payload':args.payload,'timeNs':time.time_ns()})
    except Exception as exc:
        save(out/'submit.json',{'pid':os.getpid(),'accepted':False,'errorType':type(exc).__name__,'error':str(exc),'payload':args.payload,'timeNs':time.time_ns()})
        service.executor.shutdown();return
    completed=False;cancelled=False;stale=False
    while not (out/'exit.json').exists():
        if (out/'cancel.json').exists() and not cancelled:
            try: value=service.cancel(tenant,mid,result['taskId'])
            except Exception as exc:value={'error':str(exc)}
            save(out/'cancel-result.json',value);cancelled=True
        if not service.tasks and not completed:
            service.executor.shutdown()
            save(out/'complete.json',{'state':read_json(c.folder_for(platform.root,tenant,mid)/'state.json'),'timeNs':time.time_ns()})
            completed=True
        if completed and (out/'stale.json').exists() and not stale:
            errors=[]
            for callback in callbacks:
                try:callback({'jobId':'STALE-JOB-MUST-NOT-WRITE'})
                except Exception as exc:errors.append(str(exc))
            for a,kw in run_calls:
                # A delayed old finally path: stop set prevents another generate.
                a[4].set()
                try:original_run(*a,**kw)
                except Exception as exc:errors.append(str(exc))
            save(out/'stale-result.json',{'errors':errors,'timeNs':time.time_ns()});stale=True
        time.sleep(.01)
    service.executor.shutdown()


def recover(args):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fox3d.product_models_api import product_models_router
    from fox3d import model_compositions as c
    ctx=read(args.root/'context.json')
    if not args.real:mock_artifacts()
    def unexpected(*a,**kw):raise AssertionError('recovery must not render')
    c.generate=unexpected
    app=FastAPI();app.include_router(product_models_router(lambda:SimpleNamespace(root=args.root/'d',mock_blender=not args.real)))
    with TestClient(app) as client:
        url='/api/product-models/'+ctx['model']['id'];headers={'X-Tenant-Id':ctx['tenant']}
        response=client.get(url+'/composition',headers=headers)
        history=client.get(url+'/compositions',headers=headers)
    save(args.root/(args.tag+'.json'),{'pid':os.getpid(),'status':response.status_code,'body':response.json(),'history':history.json()})


def snapshot(root):
    from fox3d import model_compositions as c
    ctx=read(root/'context.json');base=c.folder_for(root/'d',ctx['tenant'],ctx['model']['id'])
    # Windows byte-range ownership deliberately prevents reading the guard byte.
    # It has no metadata and is not included among product/request facts.
    files={p.relative_to(base).as_posix():{'sha256':digest(p),'bytes':p.stat().st_size} for p in base.rglob('*') if p.is_file() and p.name!='owner.lock'}
    state=base/'state.json'
    return {'state':read(state) if state.exists() else None,'stateBytes':state.read_text(encoding='utf-8') if state.exists() else None,
        'files':files,'requests':[str(p.relative_to(base)) for p in base.glob('batches/*/request.json')],
        'generations':[p.name for p in (base/'generations').glob('*') if p.is_dir()],
        'rows':[str(p.relative_to(base)) for p in base.glob('batches/*/[0-9]*.json')],
        'terminals':[str(p.relative_to(base)) for p in base.glob('batches/*/terminal.json')],
        'publications':[str(p.relative_to(base)) for p in base.glob('generations/*/published.json')],
        'latest':read(base/'latest.json') if (base/'latest.json').exists() else None}


def run_case(root,code_root,case,real=False):
    root=Path(root).resolve();code_root=Path(code_root).resolve();root.mkdir(parents=True,exist_ok=False)
    fixture(root);procs={};logs=[];points={};outcomes={};barriers={}
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    env={**os.environ,'FOX3D_MOCK_BLENDER':'0' if real else '1','PYTHONIOENCODING':'utf-8'}
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--root',str(root),'--code-root',str(code_root)]
    if real:command.append('--real')
    def start(tag,barrier,payload='same',hold='none'):
        log=(root/(tag+'.log')).open('w',encoding='utf-8');logs.append(log)
        procs[tag]=subprocess.Popen(command+['--action','child','--tag',tag,'--barrier',barrier,'--payload',payload,'--hold',hold],env=env,stdout=log,stderr=log,creationflags=flags)
        wait(tag,'ready')
    def wait(tag,mark,seconds=60):
        def ready():
            if (root/tag/(mark+'.json')).exists():return True
            if procs[tag].poll() is not None:raise AssertionError((root/(tag+'.log')).read_text(encoding='utf-8'))
            return False
        until(ready,seconds)
        return read(root/tag/(mark+'.json'))
    def signal(tag,mark):save(root/tag/(mark+'.json'),{'timeNs':time.time_ns()})
    def release(name):
        barriers[name]=time.time_ns();save(root/name,{'timeNs':barriers[name]})
    def submitted(tag):return read(root/tag/'submit.json')
    def fresh(name):
        p=subprocess.run(command+['--action','recover','--tag',name],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120,creationflags=flags)
        assert p.returncode==0,p.stdout+p.stderr
        return read(root/(name+'.json'))
    def point(name):points[name]=snapshot(root);return points[name]
    def accepted(tags):return [t for t in tags if submitted(t)['accepted']]
    def no_writes(tag):return not (root/tag/'writes.json').exists()
    def finish(tag):signal(tag,'render-release');wait(tag,'complete',1200 if real else 60)
    def kill(tag):procs[tag].kill();procs[tag].wait(timeout=15)
    try:
        if case in ['A','B']:
            start('a','start');start('b','start','different' if case=='B' else 'same');release('start')
            wait('a','submit');wait('b','submit');wins=accepted(['a','b'])
            for tag in wins:wait(tag,'render-ready')
            race=point('race');observed=fresh('active-read');point('after-active-read')
            outcomes['singleWinner']=len(wins)==1
            outcomes['loserNoWrites']=len(wins)==1 and no_writes(next(t for t in ['a','b'] if t not in wins))
            outcomes['oneRequest']=len(race['requests'])==1
            outcomes['activeReadDoesNotInterrupt']=observed['status']==200 and observed['body']['state']=='running'
            for tag in wins:finish(tag)
            last=point('completed');api=fresh('final-read')
            outcomes['coherentResult']=len(wins)==1 and api['status']==200 and api['body']['state']=='succeeded' and api['body']['taskId']==submitted(wins[0])['result']['taskId'] and api['body']['batch']['available']
            outcomes['oneGeneration']=len(last['generations'])==1 and len(last['publications'])==1
        elif case in ['C','D']:
            start('a','start',hold='before-request' if case=='C' else 'after-progress');release('start');wait('a','submit');wait('a','checkpoint')
            point('ownerHeld');start('b','contend');release('contend');wait('b','submit')
            if submitted('b')['accepted']:wait('b','render-ready')
            race=point('competitor');outcomes['activeCompetitorRejected']=not submitted('b')['accepted'] and no_writes('b')
            kill('a');points['afterKill']=snapshot(root)
            # Baseline loser may have become an owner; record its completion too.
            if submitted('b')['accepted']:finish('b')
            pre_recovery=point('before-recovery')
            recovery=fresh('after-kill-read');before=point('before-explicit-resubmit')
            outcomes['noAutomaticReplay']=pre_recovery['generations']==before['generations']
            outcomes['noCompetingGeneration']=len(before['generations'])==0
            outcomes['noFabricatedRequest']=len(before['requests'])==(0 if case=='C' else 1)
            if case=='D':outcomes['interruptedRecognized']=recovery['status']==200 and recovery['body']['state']=='interrupted'
            start('new','resubmit','different');release('resubmit');wait('new','submit')
            outcomes['deathReleasesOwnership']=submitted('new')['accepted']
            if submitted('new')['accepted']:wait('new','render-ready');finish('new')
            after=point('completed');api=fresh('final-read')
            historical={k:v for k,v in before['files'].items() if '/request.json' in k or '/terminal.json' in k or k.startswith('generations/') or k.split('/')[-1] in ['0.json']}
            outcomes['historicalFactsUnchanged']=all(after['files'].get(k)==v for k,v in historical.items())
            outcomes['newTaskExact']=api['status']==200 and api['body']['state']=='succeeded' and api['body']['taskId']==submitted('new').get('result',{}).get('taskId')
        else:
            start('a','start');release('start');wait('a','submit');wait('a','render-ready')
            if case=='F':
                # Cancellation and contender release share one parent barrier time.
                start('b','cancel-race');signal('a','cancel');release('cancel-race');wait('a','cancel-result');wait('b','submit')
                if submitted('b')['accepted']:wait('b','render-ready')
                point('cancel-race');outcomes['cancelCompetitorRejected']=not submitted('b')['accepted'] and no_writes('b')
            finish('a')
            if case=='F' and submitted('b')['accepted']:finish('b')
            point('oldTerminal');fresh('terminal-read')
            start('new','new-submit','different');release('new-submit');wait('new','submit');wait('new','render-ready')
            before=point('newActive');signal('a','stale');wait('a','stale-result');after=point('afterStale')
            outcomes['staleStateBytesUnchanged']=before['stateBytes']==after['stateBytes']
            outcomes['newTaskStillExact']=after['state']['taskId']==submitted('new')['result']['taskId']
            finish('new');point('completed');api=fresh('final-read')
            outcomes['finalCoherent']=api['status']==200 and api['body']['state']=='succeeded' and api['body']['taskId']==submitted('new')['result']['taskId'] and api['body']['batch']['available']
        children={tag:{'pid':p.pid,'submit':submitted(tag),'renderEntries':read(root/tag/'renders.json') if (root/tag/'renders.json').exists() else [],'writes':read(root/tag/'writes.json') if (root/tag/'writes.json').exists() else []} for tag,p in procs.items()}
        result={'case':case,'status':'PASS' if all(outcomes.values()) else 'FAIL','outcomes':outcomes,'children':children,'barriers':barriers,'checkpoints':points,'finalApi':api,'os':sys.platform,'classification':'REAL_PROCESS_CONCURRENCY','artifacts':'REAL_BLENDER_FULL_PUBLICATION_VERIFIER' if real else 'MOCK_ARTIFACT_VALIDATION','testOnlyStaleInjection':case in ['E','F'],'killMechanism':('TerminateProcess' if sys.platform=='win32' else 'SIGKILL') if case in ['C','D'] else None}
        save(root/'result.json',result);return result
    finally:
        for tag,p in procs.items():
            signal(tag,'render-release');signal(tag,'exit')
        for p in procs.values():
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=15)
        for log in logs:log.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--code-root',type=Path,required=True)
    parser.add_argument('--case',choices=list('ABCDEF'),default='A');parser.add_argument('--real',action='store_true')
    parser.add_argument('--action',choices=['parent','child','recover'],default='parent');parser.add_argument('--tag',default='a')
    parser.add_argument('--barrier',default='start');parser.add_argument('--payload',default='same');parser.add_argument('--hold',default='none')
    args=parser.parse_args();sys.path.insert(0,str(args.code_root/'src'))
    if args.action=='child':child(args)
    elif args.action=='recover':recover(args)
    else:
        result=run_case(args.root,args.code_root,args.case,args.real)
        print(json.dumps({k:result[k] for k in ['case','status','outcomes','classification','artifacts']}))


if __name__=='__main__':main()
