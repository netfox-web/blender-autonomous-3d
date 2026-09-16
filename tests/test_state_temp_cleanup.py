"""Scoped cleanup unit/fault tests and actual subprocess/OS evidence."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import stat
import sys
from types import SimpleNamespace

import pytest

from fox3d import recipe_3d as r,recipe_preview_service as s
from fox3d.preview_ownership import PreviewOwnership

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/helpers'))
spec=importlib.util.spec_from_file_location('state_temp_recovery',ROOT/'tests/helpers/state_temp_recovery.py')
harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)


@pytest.mark.parametrize('case',list('ABCDEF'))
def test_real_killed_outer_writer_and_fresh_owner(tmp_path,case,record_property):
    if case=='F' and os.name!='nt' and os.geteuid()==0:
        pytest.skip('POSIX permission-denial integration requires non-root user')
    result=harness.run_case(tmp_path/'case',ROOT,case)
    record_property('REAL_STATE_TEMP_RECOVERY',json.dumps(result))
    assert result['status']=='PASS',result
    assert result['childPid']!=result['recovered']['pid']
    assert result['postKill']['candidates'] and not result['recovered']['after']['candidates']


@pytest.mark.parametrize('name',[
    'other.tmp','latest.json.1234abcd.tmp','state.json.1234567.tmp','state.json.123456789.tmp',
    'state.json.ABCD1234.tmp','state.json.1234-abcd.tmp','state.json.1234abcd.tmp.extra','state.json.1234abcd.tmp\n'])
def test_unknown_names_preserved(tmp_path,name):
    # Newline is a parser-only negative on Windows, whose filesystem rejects it.
    if '\n' in name:
        p=SimpleNamespace(name=name)
        from unittest.mock import patch
        with PreviewOwnership(tmp_path) as owner,patch.object(Path,'iterdir',return_value=iter([p])):
            assert s.scavenge_state_temps(tmp_path/'state.json',owner)==[]
        return
    p=tmp_path/name;p.write_bytes(b'UNKNOWN')
    with PreviewOwnership(tmp_path) as owner:
        assert s.scavenge_state_temps(tmp_path/'state.json',owner)==[]
    assert p.read_bytes()==b'UNKNOWN'


@pytest.mark.parametrize('existing',[False,True])
def test_exact_orphans_do_not_become_state(tmp_path,existing,caplog,monkeypatch):
    path=tmp_path/'state.json'
    if existing:path.write_bytes(b'{"state":"succeeded","taskId":"prior"}')
    before=path.read_bytes() if existing else None
    orphan=tmp_path/'state.json.0123abcd.tmp';orphan.write_bytes(b'not even valid JSON')
    original=Path.read_bytes
    def reject_read(candidate):
        if candidate==orphan:raise AssertionError('orphan bytes must not be read')
        return original(candidate)
    monkeypatch.setattr(Path,'read_bytes',reject_read)
    with caplog.at_level(logging.INFO),PreviewOwnership(tmp_path) as owner:
        assert s.scavenge_state_temps(path,owner)==[orphan.name]
    assert not orphan.exists() and (path.read_bytes() if path.exists() else None)==before
    assert any('Scavenged outer-state temp debris' in message for message in caplog.messages)


def test_match_comes_from_actual_atomic_name_contract(tmp_path,monkeypatch):
    captured=[];original=Path.replace
    def observe(path,target):captured.append(path.name);return original(path,target)
    monkeypatch.setattr(Path,'replace',observe)
    path=tmp_path/'state.json';r.atomic_json(path,{'prior':True})
    assert len(captured)==1 and re.fullmatch(r'state\.json\.[0-9a-f]{8}\.tmp',captured[0])
    (tmp_path/captured[0]).write_bytes(b'orphan')
    with PreviewOwnership(tmp_path) as owner:assert s.scavenge_state_temps(path,owner)==captured
    assert r.read_json(path)=={'prior':True}


@pytest.mark.parametrize('invalid',['missing','released','wrong-workspace','closed-stream','fake'])
def test_requires_live_ownership_of_exact_workspace(tmp_path,invalid):
    path=tmp_path/'state.json';orphan=tmp_path/'state.json.1234abcd.tmp';orphan.write_bytes(b'KEEP')
    owner=PreviewOwnership(tmp_path/'other' if invalid=='wrong-workspace' else tmp_path)
    try:
        supplied=owner
        if invalid=='missing':supplied=None
        if invalid=='released':owner.close()
        if invalid=='closed-stream':owner.stream.close()
        if invalid=='fake':supplied=SimpleNamespace(held=True,folder=tmp_path,stream=SimpleNamespace(closed=False))
        with pytest.raises(ValueError):s.scavenge_state_temps(path,supplied)
        assert orphan.read_bytes()==b'KEEP'
    finally:owner.close()


@pytest.mark.parametrize('target',['latest.json','nested/state.json','../outside/state.json'])
def test_rejects_other_destination_or_nested_workspace(tmp_path,target):
    orphan=tmp_path/'state.json.1234abcd.tmp';orphan.write_bytes(b'KEEP')
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError):s.scavenge_state_temps(tmp_path/target,owner)
    assert orphan.read_bytes()==b'KEEP'


def test_directory_ambiguity_stops_before_any_delete(tmp_path):
    first=tmp_path/'state.json.00000000.tmp';first.write_bytes(b'KEEP UNTIL ALL TYPES VALID')
    directory=tmp_path/'state.json.ffffffff.tmp';directory.mkdir();(directory/'sentinel').write_bytes(b'KEEP')
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError,match='型態'):s.scavenge_state_temps(tmp_path/'state.json',owner)
    assert first.exists() and (directory/'sentinel').read_bytes()==b'KEEP'


def test_hardlink_candidate_is_ambiguous(tmp_path):
    source=tmp_path/'unknown';source.write_bytes(b'KEEP');candidate=tmp_path/'state.json.1234abcd.tmp';os.link(source,candidate)
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError,match='型態'):s.scavenge_state_temps(tmp_path/'state.json',owner)
    assert source.read_bytes()==candidate.read_bytes()==b'KEEP'


@pytest.mark.parametrize('kind',['symlink','fifo','reparse'])
def test_nonregular_or_reparse_metadata_rejected(tmp_path,kind,monkeypatch):
    candidate=tmp_path/'state.json.1234abcd.tmp';candidate.write_bytes(b'KEEP');original=Path.lstat
    def ambiguous(path,*a,**kw):
        if path==candidate:return SimpleNamespace(st_mode=stat.S_IFLNK if kind=='symlink' else stat.S_IFIFO if kind=='fifo' else stat.S_IFREG,st_nlink=1,st_file_attributes=0x400 if kind=='reparse' else 0)
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'lstat',ambiguous);monkeypatch.setattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400,raising=False)
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError,match='型態'):s.scavenge_state_temps(tmp_path/'state.json',owner)
    assert candidate.read_bytes()==b'KEEP'


def test_multiple_candidates_sorted_and_all_other_facts_preserved(tmp_path):
    names=['state.json.ffffffff.tmp','state.json.00000000.tmp']
    for name in names:(tmp_path/name).write_bytes(b'ORPHAN')
    sentinels=['unknown.tmp','state.json','batches/x/request.json','batches/x/0.json','batches/x/terminal.json','generations/g/published.json','latest.json','authority/declaration.json','nested/state.json.1234abcd.tmp']
    for name in sentinels:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'KEEP '+name.encode())
    with PreviewOwnership(tmp_path) as owner:
        assert s.scavenge_state_temps(tmp_path/'state.json',owner)==sorted(names)
    assert (tmp_path/'owner.lock').exists()
    assert all((tmp_path/n).read_bytes()==b'KEEP '+n.encode() for n in sentinels)


@pytest.mark.parametrize('operation',['status','submit'])
def test_delete_failure_blocks_state_transition_and_releases_owner(tmp_path,operation,monkeypatch):
    path=r.get_recipe_3d_dir(tmp_path,'t','m')/'state.json';r.atomic_json(path,{'taskId':'prior','state':'running'})
    orphan=path.with_name('state.json.1234abcd.tmp');orphan.write_bytes(b'ORPHAN');before=path.read_bytes()
    original=Path.unlink
    def fail(candidate,*a,**kw):
        if candidate==orphan:raise PermissionError('injected deletion denial')
        return original(candidate,*a,**kw)
    monkeypatch.setattr(Path,'unlink',fail)
    service=s.RecipePreviewService(SimpleNamespace(root=tmp_path),generate_fn=lambda *a,**kw:pytest.fail('must not render'))
    try:
        with pytest.raises(PermissionError):
            if operation=='submit':service.submit('t','m',{'draft':{},'revision':1})
            else:service.status('t','m',{})
        assert not service.tasks and path.read_bytes()==before and orphan.exists()
        with PreviewOwnership(path.parent):pass
    finally:service.executor.shutdown()


def test_partial_cleanup_failure_is_not_reported_as_success(tmp_path,monkeypatch):
    a=tmp_path/'state.json.00000000.tmp';b=tmp_path/'state.json.ffffffff.tmp'
    a.write_bytes(b'A');b.write_bytes(b'B');original=Path.unlink
    def fail(candidate,*args,**kw):
        if candidate==b:raise PermissionError('second removal denied')
        return original(candidate,*args,**kw)
    monkeypatch.setattr(Path,'unlink',fail)
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(PermissionError):s.scavenge_state_temps(tmp_path/'state.json',owner)
    assert not a.exists() and b.read_bytes()==b'B' and not (tmp_path/'state.json').exists()
    monkeypatch.setattr(Path,'unlink',original)
    with PreviewOwnership(tmp_path) as owner:assert s.scavenge_state_temps(tmp_path/'state.json',owner)==[b.name]
