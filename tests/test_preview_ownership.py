"""Focused unit/fault regression plus actual local OS ownership isolation."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from fox3d.preview_ownership import PreviewOwnership, PreviewBusy
from fox3d.recipe_preview_service import RecipePreviewService
from fox3d.recipe_3d import atomic_json, read_json, get_recipe_3d_dir


def service(root, generate):
    return RecipePreviewService(SimpleNamespace(root=root),generate_fn=generate)


def test_same_workspace_two_service_instances_and_read(tmp_path):
    entered=threading.Event();release=threading.Event()
    def generate(*a,**kw):entered.set();assert release.wait(5)
    first=service(tmp_path,generate);other=service(tmp_path,lambda *a,**kw:pytest.fail('loser render'))
    item={'draft':{},'revision':1}
    try:
        task=first.submit('t','m',item);assert entered.wait(3)
        path=get_recipe_3d_dir(tmp_path,'t','m')/'state.json';before=path.read_bytes()
        with pytest.raises(PreviewBusy):other.submit('t','m',item)
        assert other.status('t','m',{})['state']=='running'
        assert path.read_bytes()==before and read_json(path)['taskId']==task['taskId']
    finally:
        release.set();first.executor.shutdown();other.executor.shutdown()


@pytest.mark.parametrize('field',['taskId','inputHash','batchVersion'])
def test_mutable_write_requires_exact_identity(tmp_path,field):
    path=tmp_path/'state.json';owned={'taskId':'old','inputHash':'hash','batchVersion':1,'state':'running'}
    newer={**owned,field:'different'};atomic_json(path,newer)
    before=path.read_bytes()
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError,match='身分'):
            RecipePreviewService._write_owned(path,owned,owner)
    assert path.read_bytes()==before


def test_released_owner_cannot_write_even_matching_task(tmp_path):
    path=tmp_path/'state.json';state={'taskId':'same','inputHash':'same','state':'running'};atomic_json(path,state)
    owner=PreviewOwnership(tmp_path);owner.close()
    with pytest.raises(ValueError,match='身分'):RecipePreviewService._write_owned(path,state,owner)
    assert read_json(path)==state


@pytest.mark.parametrize('err',[errno.EIO,errno.EACCES,errno.EAGAIN])
def test_acquisition_failure_never_writes_or_executes(tmp_path,monkeypatch,err):
    if os.name=='nt':
        import msvcrt
        monkeypatch.setattr(msvcrt,'locking',lambda *a:(_ for _ in ()).throw(OSError(err,'injected locking failure')))
    else:
        import fcntl
        monkeypatch.setattr(fcntl,'flock',lambda *a:(_ for _ in ()).throw(OSError(err,'injected locking failure')))
    path=get_recipe_3d_dir(tmp_path,'t','m')/'state.json';atomic_json(path,{'taskId':'prior','state':'succeeded'})
    before=path.read_bytes();s=service(tmp_path,lambda *a,**kw:pytest.fail('must not execute'))
    try:
        with pytest.raises((OSError,PreviewBusy)):s.submit('t','m',{'draft':{},'revision':1})
        assert not s.tasks and path.read_bytes()==before
        if err==errno.EIO:
            with pytest.raises(OSError):s.status('t','m',{})
    finally:s.executor.shutdown()


def test_open_failure_is_not_misclassified_as_active_owner(tmp_path,monkeypatch):
    original=Path.open
    def fail(path,*a,**kw):
        if path.name=='owner.lock':raise PermissionError('injected ACL denial')
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'open',fail)
    with pytest.raises(PermissionError,match='ACL'):PreviewOwnership(tmp_path)


def test_guard_bytes_are_not_owner_metadata_and_never_deleted(tmp_path):
    path=tmp_path/'owner.lock';path.write_bytes(b'not a metadata object')
    with PreviewOwnership(tmp_path):
        with pytest.raises(PreviewBusy):PreviewOwnership(tmp_path)
    assert path.read_bytes()==b'not a metadata object'
    with PreviewOwnership(tmp_path):pass
    assert path.exists()


def test_executor_rejection_releases_owner(tmp_path):
    s=service(tmp_path,lambda *a,**kw:None);s.executor.shutdown()
    with pytest.raises(RuntimeError):s.submit('t','m',{'draft':{},'revision':1})
    assert not s.tasks
    with PreviewOwnership(get_recipe_3d_dir(tmp_path,'t','m')):pass
    assert s.status('t','m',{})['state']=='failed'


def test_final_write_failure_still_releases_owner(tmp_path,monkeypatch):
    s=service(tmp_path,lambda *a,**kw:None)
    def fail(*a):raise OSError('injected final write failure')
    monkeypatch.setattr(s,'_write_owned',fail)
    s.submit('t','m',{'draft':{},'revision':1});s.executor.shutdown()
    assert not s.tasks
    with PreviewOwnership(get_recipe_3d_dir(tmp_path,'t','m')):pass


def test_stale_finally_does_not_remove_new_local_task(tmp_path):
    s=service(tmp_path,lambda *a,**kw:pytest.fail('stale render'))
    key=('t','m');path=get_recipe_3d_dir(tmp_path,*key)/'state.json'
    state={'taskId':'old','inputHash':'old','state':'running'}
    old=PreviewOwnership(path.parent);old.close();stop=threading.Event();stop.set()
    new_stop=threading.Event();s.tasks[key]=('new',new_stop);atomic_json(path,{'taskId':'new','inputHash':'new','state':'running'})
    try:
        with pytest.raises(ValueError,match='身分'):s._run(key,{'draft':{},'revision':1},path,state,stop,old)
        assert s.tasks[key]==('new',new_stop) and read_json(path)['taskId']=='new'
    finally:s.executor.shutdown()


@pytest.mark.parametrize('other',[('other-tenant','master'),('tenant','other-master')])
def test_independent_processes_different_workspaces(tmp_path,other,record_property):
    folder=get_recipe_3d_dir(tmp_path,'tenant','master');other_folder=get_recipe_3d_dir(tmp_path,*other)
    # A child holds a different tenant/master OS guard while parent still owns its own.
    script='''import sys,json,os
from pathlib import Path
from fox3d.preview_ownership import PreviewOwnership
with PreviewOwnership(Path(sys.argv[1])):
 print(json.dumps({'pid':os.getpid(),'acquired':True}),flush=True)
 sys.stdin.readline()
'''
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    with PreviewOwnership(folder):
        child=subprocess.Popen([sys.executable,'-c',script,str(other_folder)],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            result=json.loads(child.stdout.readline());assert result['acquired'] and result['pid']!=os.getpid()
            with pytest.raises(PreviewBusy):PreviewOwnership(other_folder)
            record_property('REAL_PROCESS_CONCURRENCY',json.dumps({'parentPid':os.getpid(),'childPid':result['pid'],'otherKey':other,'independent':True}))
        finally:
            child.communicate('\n',timeout=10)
        assert child.returncode==0
