"""Actual platform flushes; injected errors are explicitly FAULT_INJECTION_LOGIC."""
import errno
import json
import os
from pathlib import Path
import platform
import sys
from types import SimpleNamespace

import pytest

from fox3d import durability as d, recipe_3d as r, model_batches as b
from fox3d.preview_ownership import PreviewOwnership
from fox3d.recipe_preview_service import scavenge_state_temps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests/helpers'))
from durability_recovery import run_case


@pytest.mark.parametrize('case', ['D1', 'D5'])
def test_actual_flush_kill_fresh_process(tmp_path, case, record_property):
    result = run_case(tmp_path/'case', ROOT, case)
    record_property('REAL_DURABILITY_RECOVERY', json.dumps(result))
    assert result['status'] == 'PASS'


def test_actual_host_flush_and_namespace_sequence(tmp_path, monkeypatch, record_property):
    events = []; flush = d.flush_file; sync = d.sync_directory; namespace = d.namespace_committed
    def file(stream):
        assert not stream.closed
        flush(stream); events.append(('file', Path(stream.name).name))
    def directory(path):
        sync(path); events.append(('directory', str(path)))
    def committed(path, operation):
        namespace(path, operation); events.append((operation, path.name))
    monkeypatch.setattr(d, 'flush_file', file); monkeypatch.setattr(d, 'sync_directory', directory)
    monkeypatch.setattr(d, 'namespace_committed', committed)
    final = tmp_path/'authority.json'; b._once(final, {'complete': '中文', 'revision': 1})
    assert json.loads(final.read_text(encoding='utf-8')) == {'complete': '中文', 'revision': 1}
    assert [e[0] for e in events] == ['file', 'directory', 'replace', 'directory', 'link', 'directory', 'unlink']
    assert list(tmp_path.glob('*.tmp')) == []
    record_property('REAL_OS_IO_FLUSH', json.dumps({'platform': platform.platform(), 'events': events,
        'fileAPI': 'FlushFileBuffers' if sys.platform=='win32' else 'fsync',
        'namespaceAPI': 'NTFS checked directory handle FlushFileBuffers' if sys.platform=='win32' else 'directory fd fsync',
        'classification': 'REAL_OS_IO_FLUSH on this path only; no power-loss test'}))


@pytest.mark.parametrize('writer', [r.atomic_json, b._once])
@pytest.mark.parametrize('exists', [False, True])
def test_precommit_flush_fault_never_exposes_new_authority(tmp_path, monkeypatch, writer, exists):
    final = tmp_path/'authority.json'
    if exists: final.write_bytes(b'EXISTING FACT')
    def fail(stream):
        stream.flush()
        raise OSError(errno.EIO, 'injected file flush failure')
    monkeypatch.setattr(d, 'flush_file', fail)
    with pytest.raises(OSError, match='injected file flush') as caught:
        writer(final, {'new': 'must not publish'})
    assert not isinstance(caught.value, d.CommitIndeterminate)
    assert final.read_bytes() == b'EXISTING FACT' if exists else not final.exists()
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('operation', ['replace', 'link', 'unlink'])
def test_post_namespace_fault_typed_no_rollback_or_retry(tmp_path, monkeypatch, operation):
    final = tmp_path/'authority.json'; events = []; original_sync = d.sync_directory
    original_committed = d.namespace_committed
    def failed_sync(path): raise OSError(errno.EIO, 'injected namespace sync failure')
    def committed(path, action):
        events.append(action)
        monkeypatch.setattr(d, 'sync_directory', failed_sync if action==operation else original_sync)
        return original_committed(path, action)
    monkeypatch.setattr(d, 'namespace_committed', committed)
    with pytest.raises(d.CommitIndeterminate) as caught:
        (r.atomic_json if operation=='replace' else b._once)(final, {'complete': True})
    assert caught.value.operation == operation and 'COMMIT_INDETERMINATE' in str(caught.value)
    assert isinstance(caught.value.__cause__, OSError)
    assert json.loads(final.read_text(encoding='utf-8')) == {'complete': True}
    assert events.count(operation) == 1
    original = final.read_bytes()
    monkeypatch.setattr(d, 'namespace_committed', original_committed)
    monkeypatch.setattr(d, 'sync_directory', original_sync)
    with pytest.raises(FileExistsError): b._once(final, {'duplicate': True})
    assert final.read_bytes() == original


@pytest.mark.parametrize('kind', ['state','once'])
def test_owned_cleanup_sync_failure_stops_before_later_write(tmp_path, monkeypatch, kind):
    if kind=='state':
        final=tmp_path/'state.json'; orphan=tmp_path/'state.json.1234abcd.tmp'
    else:
        final=tmp_path/'batches'/'12345678-1234-4234-8234-123456789012'/'request.json'
        final.parent.mkdir(parents=True); orphan=final.with_name(final.name+'.once.'+'a'*16+'.tmp')
    orphan.write_bytes(b'owned debris'); final.write_bytes(b'EXISTING FACT')
    def fail(path): raise OSError(errno.EIO, 'injected deletion sync failure')
    monkeypatch.setattr(d, 'sync_directory', fail)
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(d.CommitIndeterminate) as caught:
            if kind=='state': scavenge_state_temps(final, owner)
            else: b._once(final, {'unexpected':'overwrite'}, owner=owner)
    assert caught.value.operation=='unlink' and final.read_bytes()==b'EXISTING FACT'


def test_batch_propagates_indeterminate_without_next_row_or_receipt(tmp_path, monkeypatch):
    from batch_process_concurrency import fixture
    from batch_process_recovery import read
    fixture(tmp_path)
    ctx=read(tmp_path/'context.json'); draft=ctx['drafts']['same']; model=ctx['model']; calls=[]
    def fail(*a, **kw):
        calls.append(kw['generation_id'])
        raise d.CommitIndeterminate(tmp_path/'published.json', 'replace', OSError(errno.EIO, 'injected'))
    monkeypatch.setattr(b.compositions, 'generate', fail)
    bid='12345678-1234-4234-8234-123456789012'
    with pytest.raises(d.CommitIndeterminate):
        b.generate(SimpleNamespace(root=tmp_path/'d'),ctx['tenant'],model['id'],draft,
                   revision=model['revision'],generation_id=bid)
    anchor=b.compositions.folder_for(tmp_path/'d',ctx['tenant'],model['id'])/'batches'/bid
    assert len(calls)==1 and (anchor/'request.json').exists()
    assert not (anchor/'0.json').exists() and not (anchor/'terminal.json').exists()


def test_posix_raw_file_and_directory_errors_close_handles(monkeypatch, tmp_path):
    if sys.platform=='win32':
        # MOCK platform surface, not a claim about actual POSIX calls on Windows.
        monkeypatch.setattr(d, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(os, 'O_DIRECTORY', getattr(os,'O_DIRECTORY',0), raising=False)
    closed=[]
    monkeypatch.setattr(os,'open',lambda *a:123)
    monkeypatch.setattr(os,'close',closed.append)
    def fail(fd): raise OSError(errno.EIO,'injected fsync')
    monkeypatch.setattr(os,'fsync',fail)
    with pytest.raises(OSError): d.sync_directory(tmp_path)
    assert closed==[123]


@pytest.mark.parametrize('filesystem', ['NTFS', 'OTHER'])
def test_windows_directory_filesystem_contract_has_no_success_fallback(tmp_path, monkeypatch, filesystem):
    # MOCK Win32 return values; real Win32 is exercised by every atomic test on Windows.
    calls=[]
    def open_dir(*args): calls.append('open'); return 42
    def volume(handle, name, size, serial, component, flags, fs, count):
        fs.value=filesystem; return True
    def flush(handle): calls.append('flush'); return True
    def close(handle): calls.append('close'); return True
    kernel=SimpleNamespace(CreateFileW=open_dir,GetVolumeInformationByHandleW=volume,
                           FlushFileBuffers=flush,CloseHandle=close)
    monkeypatch.setattr(d,'sys',SimpleNamespace(platform='win32'))
    monkeypatch.setattr(d,'_kernel',lambda:kernel)
    if filesystem=='NTFS':
        d.sync_directory(tmp_path)
        assert calls==['open','flush','close']
    else:
        with pytest.raises(OSError) as caught: d.sync_directory(tmp_path)
        assert caught.value.errno==errno.ENOTSUP and calls==['open','close']


def test_submit_namespace_failure_returns_no_success_and_releases_owner(tmp_path, monkeypatch):
    from fox3d.recipe_preview_service import RecipePreviewService
    generated=[]
    service=RecipePreviewService(SimpleNamespace(root=tmp_path),folder_fn=lambda *a:tmp_path,
                                 generate_fn=lambda *a,**kw:generated.append(True))
    def fail(path): raise OSError(errno.EIO,'injected queue commit sync')
    monkeypatch.setattr(d,'sync_directory',fail)
    try:
        with pytest.raises(d.CommitIndeterminate):
            service.submit('tenant','model',{'draft':{'test':True},'revision':1})
        assert not service.tasks and not generated
        with PreviewOwnership(tmp_path) as owner: assert owner.held
    finally:
        service.executor.shutdown()


@pytest.mark.parametrize('request_committed', [False, True])
def test_live_initial_metadata_flush_is_pending_not_corrupt(tmp_path, request_committed):
    from batch_process_concurrency import fixture
    from batch_process_recovery import read
    fixture(tmp_path);ctx=read(tmp_path/'context.json');draft=ctx['drafts']['same'];model=ctx['model']
    bid='12345678-1234-4234-8234-123456789012'
    base=b.compositions.folder_for(tmp_path/'d',ctx['tenant'],model['id']);anchor=base/'batches'/bid
    with PreviewOwnership(base):
        anchor.mkdir(parents=True)
        r.atomic_json(base/'state.json',{'taskId':bid,'inputHash':r.input_hash(draft),'batchVersion':1,'state':'running'})
        if request_committed:
            b._once(anchor/'request.json',{'identityVersion':1,'tenantId':ctx['tenant'],'masterId':model['id'],
                'batchId':bid,'sourceRevision':model['revision'],'draft':draft})
        else:
            # The actual new flush enlarges this existing initial-temp-only window.
            (anchor/('request.json.once.'+'a'*16+'.tmp.1234abcd.tmp')).write_bytes(b'not authority')
        before={str(p):p.read_bytes() for p in base.rglob('*') if p.is_file() and p.name!='owner.lock'}
        assert b.current(tmp_path/'d',ctx['tenant'],model['id'],bid,'running') is None
        assert {str(p):p.read_bytes() for p in base.rglob('*') if p.is_file() and p.name!='owner.lock'}==before
    # No live owner: preserve the previous fail-closed missing-record behavior.
    with pytest.raises(ValueError):b.current(tmp_path/'d',ctx['tenant'],model['id'],bid,'running')


@pytest.mark.parametrize('kind', ['task','hash','version_bool','state','malformed_request','request_missing_field','terminal','row','missing_state','cross_product'])
def test_pending_flush_view_does_not_hide_corruption_or_completed_facts(tmp_path, kind):
    from batch_process_concurrency import fixture
    from batch_process_recovery import read
    fixture(tmp_path);ctx=read(tmp_path/'context.json');draft=ctx['drafts']['same'];model=ctx['model']
    bid='12345678-1234-4234-8234-123456789012'
    base=b.compositions.folder_for(tmp_path/'d',ctx['tenant'],model['id']);anchor=base/'batches'/bid
    state={'taskId':bid,'inputHash':r.input_hash(draft),'batchVersion':1,'state':'running'}
    if kind=='task':state['taskId']='wrong'
    if kind=='hash':state['inputHash']='wrong'
    if kind=='version_bool':state['batchVersion']=True
    if kind=='state':state['state']='succeeded'
    with PreviewOwnership(base):
        r.atomic_json(base/'state.json',state)
        request={'identityVersion':1,'tenantId':ctx['tenant'],'masterId':model['id'],
                 'batchId':bid,'sourceRevision':model['revision'],'draft':draft}
        if kind=='cross_product':request['masterId']='wrong'
        if kind=='request_missing_field':request.pop('draft')
        b._once(anchor/'request.json',request)
        if kind=='malformed_request':(anchor/'request.json').write_bytes(b'{broken')
        if kind=='missing_state':(base/'state.json').unlink()
        if kind in {'terminal','row'}:(anchor/('terminal.json' if kind=='terminal' else '0.json')).write_bytes(b'FACT')
        before={str(p):p.read_bytes() for p in base.rglob('*') if p.is_file() and p.name!='owner.lock'}
        with pytest.raises(ValueError):b.current(tmp_path/'d',ctx['tenant'],model['id'],bid,'running')
        assert {str(p):p.read_bytes() for p in base.rglob('*') if p.is_file() and p.name!='owner.lock'}==before
