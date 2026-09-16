"""D3 fault injection with the unmocked verifier and copied accepted artifacts.

Manual clean-CODE acceptance helper, not a renderer. The source tree must contain
an already accepted synthetic/static fixture. All mutations occur in a new copy.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def save(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def inventory(root): return {p.relative_to(root).as_posix():digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def child(args):
    from fox3d import model_compositions as c, product_models as m, model_batches as b
    from types import SimpleNamespace
    data=args.root/'d'; item=m.get(data,args.tenant,args.model)
    target=c.folder_for(data,args.tenant,args.model)/'generations'/args.generation
    before=inventory(data); manifest=c.generation(data,args.tenant,args.model,args.generation,item)
    history=c.history(data,args.tenant,args.model,item)['items']
    available=next(row for row in history if row['generationId']==args.generation)['available']
    assert manifest['generationId']==args.generation and available
    # Existing generation ID must fail before preparation, renderer or publication.
    try:
        c.generate(SimpleNamespace(root=data,mock_blender=False,runtime=SimpleNamespace(available=lambda:True)),
                   args.tenant,args.model,manifest['draft'],revision=manifest['sourceRevision'],generation_id=args.generation)
    except FileExistsError:duplicate=True
    else:raise AssertionError('duplicate generation permitted')
    try:b._once(target/'published.json', {'invalid':'duplicate'})
    except FileExistsError:receipt_duplicate=True
    else:raise AssertionError('immutable overwrite permitted')
    assert inventory(data)==before
    # Verify absent and tampered states in separate copies; never modify accepted facts.
    controls={}
    for label in ['absent','tampered']:
        dest=args.root/label;shutil.copytree(data,dest)
        seal=c.folder_for(dest,args.tenant,args.model)/'generations'/args.generation/'published.json'
        if label=='absent':seal.unlink()
        else:save(seal,{'manifestSha256':'tampered'})
        try:c.generation(dest,args.tenant,args.model,args.generation,m.get(dest,args.tenant,args.model))
        except ValueError:controls[label]='REJECTED'
        else:raise AssertionError(label+' publication accepted')
    save(args.root/'recovered.json',{'pid':os.getpid(),'generationVerifierAccepted':True,'historyAvailable':available,
        'duplicateGenerationBlocked':duplicate,'duplicateReceiptBlocked':receipt_duplicate,
        'allBytesPreserved':inventory(data)==before,'controls':controls,'rendererCalled':False,
        'classification':'PARTIAL / COMMIT_INDETERMINATE_DURABILITY; existing full verifier, no replay or power-loss claim'})


def run(args):
    from fox3d import durability as d, recipe_3d as r, model_compositions as c, product_models as m
    sha=subprocess.check_output(['git','-C',str(args.code_root),'rev-parse','HEAD'],text=True).strip()
    assert sha==args.expected_code
    assert not subprocess.check_output(['git','-C',str(args.code_root),'status','--porcelain'],text=True).strip()
    args.root.mkdir(parents=True,exist_ok=False)
    source_before=inventory(args.source); data=args.root/'d';shutil.copytree(args.source,data)
    item=m.get(data,args.tenant,args.model);c.generation(data,args.tenant,args.model,args.generation,item)
    target=c.folder_for(data,args.tenant,args.model)/'generations'/args.generation/'published.json'
    value=read(target);initial=digest(target);target.unlink()
    try:c.generation(data,args.tenant,args.model,args.generation,item)
    except ValueError:pass
    else:raise AssertionError('unpublished control accepted')
    before=inventory(data);events=[];flush=d.flush_file;sync=d.sync_directory
    def observed_flush(stream):
        flush(stream);events.append({'operation':'file flush','success':True,'path':str(stream.name),
            'classification':'REAL_OS_IO_FLUSH'})
    def injected_sync(directory):
        if directory==target.parent:
            assert target.exists() and digest(target)==initial
            events.append({'operation':'post-replace namespace sync','error':'EIO',
                'classification':'MOCK / FAULT_INJECTION_LOGIC'})
            raise OSError(errno.EIO,'D3 injected namespace sync failure')
        return sync(directory)
    d.flush_file=observed_flush;d.sync_directory=injected_sync
    try:
        try:r.atomic_json(target,value)
        except d.CommitIndeterminate as exc:
            outcome={'type':type(exc).__name__,'operation':exc.operation,'message':str(exc),'cause':str(exc.__cause__)}
        else:raise AssertionError('indeterminate call returned success')
    finally:d.flush_file=flush;d.sync_directory=sync
    assert inventory(data)=={**before,target.relative_to(data).as_posix():initial}
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--recover',
        '--code-root',str(args.code_root),'--source',str(args.source),'--root',str(args.root),
        '--expected-code',args.expected_code,'--tenant',args.tenant,'--model',args.model,'--generation',args.generation]
    proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=120,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (args.root/'recover.log').write_text(proc.stdout+proc.stderr,encoding='utf-8');assert proc.returncode==0,proc.stderr
    recovered=read(args.root/'recovered.json');assert recovered['pid']!=os.getpid()
    assert inventory(args.source)==source_before
    report={'status':'PASS','codeCommit':sha,'workingTreeClean':True,'platform':platform.platform(),
        'pid':os.getpid(),'sourceRoot':str(args.source),'sourceInventorySha256':hashlib.sha256(json.dumps(source_before,sort_keys=True).encode()).hexdigest(),
        'sourceUnchanged':True,'usedNewRender':False,'inputTruth':'COPIED_ACCEPTED_SYNTHETIC_STATIC_FIXTURE',
        'callerOutcome':outcome,'events':events,'freshProcess':recovered,
        'classification':'D3 MOCK / FAULT_INJECTION_LOGIC; PARTIAL / COMMIT_INDETERMINATE_DURABILITY',
        'hardwarePowerLossTested':False,'harnessSha256':digest(Path(__file__))}
    save(args.root/'evidence.json',report);print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['code-root','source','root']:parser.add_argument('--'+name,type=Path,required=True)
    for name in ['expected-code','tenant','model','generation']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--recover',action='store_true');args=parser.parse_args()
    args.code_root=args.code_root.resolve();args.source=args.source.resolve();args.root=args.root.resolve()
    sys.path.insert(0,str(args.code_root/'src'))
    child(args) if args.recover else run(args)
