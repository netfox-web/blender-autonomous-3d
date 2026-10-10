"""Test-only hard-kill outer atomic writes and fresh-owner cleanup evidence.

Only processes/files/locks are real here. Any normal completed batch uses MOCK
publication artifacts; no cleanup case is claimed as REAL_RENDER.
"""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from batch_process_recovery import save,read,digest,mock_artifacts,windows_lock
from batch_process_concurrency import fixture,until

TOKEN=re.compile(r'state\.json\.[0-9a-f]{8}\.tmp\Z')


def setup(root,case):
    from fox3d import model_compositions as c,model_batches as b
    from fox3d.recipe_3d import atomic_json,input_hash
    from fox3d.ids import new_id
    fixture(root);ctx=read(root/'context.json');base=c.folder_for(root/'d',ctx['tenant'],ctx['model']['id']);base.mkdir(parents=True)
    if case!='A':
        original_generate,original_validate=c.generate,c.print_preview.validate
        try:
            mock_artifacts();bid=new_id();draft=ctx['drafts']['same']
            state={'taskId':bid,'state':'running','progress':10,'inputHash':input_hash(draft),'batchVersion':1,'error':None}
            atomic_json(base/'state.json',state)
            b.generate(SimpleNamespace(root=root/'d'),ctx['tenant'],ctx['model']['id'],draft,revision=ctx['model']['revision'],generation_id=bid)
            atomic_json(base/'state.json',{**state,'state':'succeeded','progress':100})
        finally:
            c.generate,c.print_preview.validate=original_generate,original_validate
    return base


def workspace(root):
    from fox3d import model_compositions as c
    ctx=read(root/'context.json');return c.folder_for(root/'d',ctx['tenant'],ctx['model']['id'])


def snapshot(base):
    destination=base/'state.json'
    files={p.relative_to(base).as_posix():{'sha256':digest(p),'size':p.stat().st_size} for p in base.rglob('*') if p.is_file() and p.name!='owner.lock'}
    return {'workspace':str(base.resolve()),'destination':str(destination.resolve()),
        'stateBytes':destination.read_text(encoding='utf-8') if destination.exists() else None,
        'stateSha256':digest(destination) if destination.exists() else None,
        'ownerLockExists':(base/'owner.lock').exists(),'files':files,
        'candidates':{n:v for n,v in files.items() if TOKEN.fullmatch(n)},
        'facts':{n:v for n,v in files.items() if n.startswith(('batches/','generations/'))}}


def child(args):
    from fox3d import recipe_preview_service as s,recipe_3d as r,model_compositions as c,model_batches as b
    ctx=read(args.root/'context.json');base=workspace(args.root);dest=base/'state.json';events=[]
    class EvidenceLog(logging.Handler):
        def emit(self,record):
            message=record.getMessage();events.append(message)
            save(args.root/(args.tag+'-logs.json'),events)
            if args.action=='kill-writer' and args.case=='C' and sys.platform=='win32' and 'Transient Windows atomic replace contention' in message:
                save(args.root/'reached.json',{'pid':os.getpid(),'window':'real_windows_retry','message':message,'deleteSharingProbe':r._delete_sharing_error(dest)})
    logging.getLogger('fox3d').setLevel(logging.INFO);logging.getLogger('fox3d').addHandler(EvidenceLog())
    mock_artifacts();original=c.generate
    def generate(*a,**kw):
        save(args.root/(args.tag+'-render.json'),{'pid':os.getpid(),'generationId':kw['generation_id'],'mode':'MOCK_ARTIFACT_VALIDATION'})
        return original(*a,**kw)
    c.generate=generate
    service=s.RecipePreviewService(SimpleNamespace(root=args.root/'d'),folder_fn=c.folder_for,
        status_fn=lambda root,tenant,mid,**kw:r.read_json(c.folder_for(root,tenant,mid)/'state.json'),generate_fn=b.generate)
    if args.action=='kill-writer':
        if args.case!='C' or sys.platform!='win32':
            original_replace=Path.replace
            def paused(path,target):
                if Path(target)==dest:
                    assert TOKEN.fullmatch(path.name)
                    save(args.root/'reached.json',{'pid':os.getpid(),'window':'temp_complete_before_replace','temp':str(path),'timeNs':time.time_ns()})
                    threading.Event().wait()  # external parent kill, no injected exception
                return original_replace(path,target)
            Path.replace=paused
        service.submit(ctx['tenant'],ctx['model']['id'],{'draft':ctx['drafts']['different'],'revision':ctx['model']['revision']})
        raise AssertionError('writer unexpectedly passed kill window')
    result={'pid':os.getpid(),'action':args.action,'before':snapshot(base)}
    try:
        if args.action=='submit':
            result['submit']=service.submit(ctx['tenant'],ctx['model']['id'],{'draft':ctx['drafts']['different'],'revision':ctx['model']['revision']})
            service.executor.shutdown()
            result['status']=service.status(ctx['tenant'],ctx['model']['id'],ctx['model'])
        elif args.action=='competitor':
            result['status']=service.status(ctx['tenant'],ctx['model']['id'],ctx['model'])
            try:result['submit']=service.submit(ctx['tenant'],ctx['model']['id'],{'draft':ctx['drafts']['different'],'revision':ctx['model']['revision']})
            except Exception as exc:result['submitError']={'type':type(exc).__name__,'message':str(exc)}
        else:result['status']=service.status(ctx['tenant'],ctx['model']['id'],ctx['model'])
        result['ok']=True
    except Exception as exc:result.update(ok=False,error={'type':type(exc).__name__,'message':str(exc)})
    finally:service.executor.shutdown()
    result.update(after=snapshot(base),logs=events,renderEntered=(args.root/(args.tag+'-render.json')).exists())
    save(args.root/(args.tag+'.json'),result)


def run_case(root,code_root,case):
    root=Path(root).resolve();code_root=Path(code_root).resolve();root.mkdir(parents=True,exist_ok=False)
    base=setup(root,case);before=snapshot(base);flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    env={**os.environ,'FOX3D_MOCK_BLENDER':'1','PYTHONIOENCODING':'utf-8'}
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--root',str(root),'--code-root',str(code_root),'--case',case]
    def fresh(action,tag):
        p=subprocess.run(command+['--action',action,'--tag',tag],env=env,capture_output=True,text=True,encoding='utf-8',timeout=90,creationflags=flags)
        (root/(tag+'.log')).write_text(p.stdout+'\n'+p.stderr,encoding='utf-8');assert p.returncode==0,p.stdout+p.stderr
        return read(root/(tag+'.json'))
    close=windows_lock(base/'state.json') if case=='C' and sys.platform=='win32' else None
    with (root/'writer.log').open('w',encoding='utf-8') as log:
        writer=subprocess.Popen(command+['--action','kill-writer','--tag','writer'],env=env,stdout=log,stderr=log,creationflags=flags)
        try:
            def reached():
                if (root/'reached.json').exists():return True
                if writer.poll() is not None:raise AssertionError((root/'writer.log').read_text(encoding='utf-8'))
                return False
            until(reached,45);live=snapshot(base)
            assert len(live['candidates'])==1 and live['stateBytes']==before['stateBytes']
            competitor=fresh('competitor','competitor') if case=='D' else None
            writer.kill();writer.wait(timeout=15);assert writer.returncode!=0
        finally:
            if writer.poll() is None:writer.kill();writer.wait(timeout=15)
            if close:close()
    killed=snapshot(base);marker=read(root/'reached.json');assert marker['pid']==writer.pid
    assert killed['candidates']==live['candidates']
    lock_before=digest(base/'owner.lock');sentinels={}
    if case=='E':
        for name in ['state.json.0123abcd.tmp','state.json.fedcba98.tmp']:
            with (base/name).open('x',encoding='utf-8') as stream:stream.write('orphan payload must never become current state')
        for name in ['other-writer.tmp','state.json.BADTOKEN.tmp','state.json.1234567.tmp','state.json.123456789.tmp','latest.json.1234abcd.tmp','other/state.json.1234abcd.tmp','batches/sentinel/request.json','batches/sentinel/0.json','batches/sentinel/terminal.json','generations/sentinel/published.json','authority/sentinel.json']:
            target=base/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'UNRELATED SENTINEL; preserve byte-for-byte')
            sentinels[name]=digest(target)
    pre_cleanup=snapshot(base)
    denied=None
    if case=='F':
        candidate=base/next(iter(killed['candidates']))
        if sys.platform=='win32':release=windows_lock(candidate)
        else:
            assert os.geteuid()!=0,'Actual POSIX permission denial needs a non-root test user'
            old_mode=stat.S_IMODE(base.stat().st_mode);base.chmod(0o500)
            release=lambda:base.chmod(old_mode)
        try:denied=fresh('submit','denied')
        finally:release()
    # Baseline F may accept the explicit submission despite a locked orphan.
    # Compare recovery to its immediate input, not to the older pre-submit state;
    # a normal explicit submission is not adoption/replay of orphan bytes.
    before_recovery=snapshot(base)
    recovered=fresh('recover','recovered');after=snapshot(base)
    outcomes={'processDeathReleased':recovered['ok'],
        'preKillStateUnchanged':before['stateBytes']==live['stateBytes']==killed['stateBytes'],
        'cleanupExactCandidates':not after['candidates'],
        'orphanNotAdopted':after['stateBytes']==before_recovery['stateBytes'],
        'noAutomaticReplay':not recovered['renderEntered'],
        'immutableInventoryUnchanged':all(after['files'].get(k)==v for k,v in pre_cleanup['facts'].items()),
        'noFabricatedFacts':after['facts']==before_recovery['facts'],
        'unknownSentinelsUnchanged':all((base/n).is_file() and digest(base/n)==h for n,h in sentinels.items()),
        'ownerLockPreserved':(base/'owner.lock').exists() and digest(base/'owner.lock')==lock_before}
    if competitor:
        outcomes.update(liveCompetitorReadOnly=competitor['ok'] and competitor.get('submitError',{}).get('type')=='PreviewBusy' and competitor['before']==competitor['after'] and not competitor['renderEntered'],
                        liveTempPreserved=competitor['after']['candidates']==live['candidates'],
                        competitorZeroCleanup=not any('Scavenged' in m for m in competitor['logs']))
    if case=='C' and sys.platform=='win32':outcomes['realWindowsSharingViolation']=marker['deleteSharingProbe']==32
    if denied:
        outcomes['failureBeforeNewStateWrite']=not denied['ok'] and denied['before']==denied['after'] and not denied['renderEntered']
        outcomes['retryAfterExternalRelease']=recovered['ok'] and not after['candidates']
    submitted=fresh('submit','resubmitted');outcomes['explicitResubmitWorks']=submitted['ok'] and submitted['status']['state']=='succeeded' and submitted['renderEntered']
    result={'case':case,'status':'PASS' if all(outcomes.values()) else 'FAIL','outcomes':outcomes,'os':sys.platform,'childPid':writer.pid,
        'exitCode':writer.returncode,'termination':'TerminateProcess' if sys.platform=='win32' else 'SIGKILL','marker':marker,
        'before':before,'live':live,'postKill':killed,'preCleanup':pre_cleanup,'beforeRecovery':before_recovery,'recovered':recovered,'competitor':competitor,'denied':denied,
        'resubmitted':submitted,'sentinels':sentinels,'ownerLockSha256':lock_before,
        'classification':'REAL_PROCESS_RECOVERY / REAL_OS_IO','concurrency':case=='D','artifactMode':'MOCK_ARTIFACT_VALIDATION',
        'scope':'Only direct outer state.json temp debris; global temp cleanup unclaimed'}
    save(root/'result.json',result);return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--code-root',type=Path,required=True)
    p.add_argument('--case',choices=list('ABCDEF'),required=True);p.add_argument('--tag',default='child')
    p.add_argument('--action',choices=['parent','kill-writer','recover','submit','competitor'],default='parent');args=p.parse_args()
    sys.path.insert(0,str(args.code_root/'src'))
    if args.action=='parent':
        result=run_case(args.root,args.code_root,args.case);print(json.dumps({k:result[k] for k in ['case','status','outcomes','childPid','classification','artifactMode']}))
    else:child(args)


if __name__=='__main__':main()
