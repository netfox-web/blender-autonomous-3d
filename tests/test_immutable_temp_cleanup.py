"""Round 8 target-scoped cleanup; real process evidence is separate from MOCK artifacts."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from fox3d import model_batches as b
from fox3d.preview_ownership import PreviewOwnership
from fox3d.ids import new_id

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests/helpers'))
from immutable_temp_recovery import run_case


def target(root, name='request.json'):
    path = root/'batches'/'12345678-1234-4234-8234-123456789012'/name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def debris(path, token='a'*16, nested=False):
    return path.with_name(path.name+'.once.'+token+'.tmp'+('.1234abcd.tmp' if nested else ''))


@pytest.mark.parametrize('window', ['W1', 'W2', 'W3'])
@pytest.mark.parametrize('name', ['request.json', '0.json', 'terminal.json'])
def test_real_hard_kill_and_fresh_process(tmp_path, window, name, record_property):
    result = run_case(tmp_path/'case', ROOT, window, name)
    record_property('REAL_IMMUTABLE_TEMP_RECOVERY', json.dumps(result))
    assert result['status'] == 'PASS'
    assert result['orphanPreserved'] is (window == 'W2')
    if window == 'W2':
        assert result['recovered']['recoveryError']['type'] == 'ValueError'
        assert result['recovered']['finalVerified'] and result['recovered']['duplicateBlocked']


@pytest.mark.parametrize('name', ['request.json', '0.json', '23.json', 'terminal.json'])
@pytest.mark.parametrize('nested', [False, True])
def test_target_contract_cleanup_preserves_finals(tmp_path, name, nested, monkeypatch):
    path = target(tmp_path, name); path.write_bytes(b'IMMUTABLE')
    orphan = debris(path, nested=nested); orphan.write_bytes(b'not authoritative JSON')
    original = Path.read_bytes
    def no_read(p):
        if p == orphan: pytest.fail('debris content must never be read or adopted')
        return original(p)
    monkeypatch.setattr(Path, 'read_bytes', no_read)
    with PreviewOwnership(tmp_path) as owner:
        assert b.scavenge_once_temps([path], owner) == [str(orphan)]
    assert not orphan.exists() and path.read_bytes() == b'IMMUTABLE'


@pytest.mark.parametrize('name', [new_id()+'.tmp', 'unknown.tmp', 'request.json.once.'+'A'*16+'.tmp',
    'request.json.once.'+'a'*15+'.tmp', 'request.json.once.'+'a'*17+'.tmp',
    'request.json.once.'+'a'*16+'.tmp.extra', 'request.json.once.'+'a'*16+'.tmp.1234567.tmp'])
def test_unknown_legacy_names_preserved(tmp_path, name):
    path = target(tmp_path); unknown = path.with_name(name); unknown.write_bytes(b'KEEP')
    with PreviewOwnership(tmp_path) as owner: assert b.scavenge_once_temps([path], owner) == []
    assert unknown.read_bytes() == b'KEEP' and not path.exists()


def test_exact_targets_only_all_sentinels_unchanged(tmp_path):
    path = target(tmp_path); anchor = path.parent
    orphan = debris(path); orphan.write_bytes(b'DELETE')
    names = ['request.json', '0.json', 'terminal.json', 'unknown.tmp', 'nested/'+orphan.name,
             '0.json.once.'+'b'*16+'.tmp', 'unrelated.json']
    for name in names:
        p = anchor/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(('KEEP '+name).encode())
    with PreviewOwnership(tmp_path) as owner: assert b.scavenge_once_temps([path], owner) == [str(orphan)]
    for name in names: assert (anchor/name).read_bytes() == ('KEEP '+name).encode()


def test_relative_workspace_path_uses_same_exact_owner(tmp_path, monkeypatch):
    path = target(tmp_path); orphan = debris(path); orphan.write_bytes(b'ORPHAN')
    monkeypatch.chdir(tmp_path)
    with PreviewOwnership(Path('.')) as owner:
        assert b.scavenge_once_temps([path.relative_to(tmp_path)], owner) == [str(orphan)]
    assert not orphan.exists() and not path.exists()


@pytest.mark.parametrize('kind', ['none', 'fake', 'released', 'closed', 'other'])
def test_live_exact_owner_required(tmp_path, kind):
    path = target(tmp_path); orphan = debris(path); orphan.write_bytes(b'KEEP')
    owner = PreviewOwnership(tmp_path/'other' if kind == 'other' else tmp_path)
    try:
        supplied = owner
        if kind == 'none': supplied = None
        if kind == 'fake': supplied = SimpleNamespace(held=True, stream=SimpleNamespace(closed=False), folder=tmp_path)
        if kind == 'released': owner.close()
        if kind == 'closed': owner.stream.close()
        with pytest.raises(ValueError): b.scavenge_once_temps([path], supplied)
        assert orphan.read_bytes() == b'KEEP'
    finally: owner.close()


@pytest.mark.parametrize('relative', ['request.json', 'batches/no-uuid/request.json',
    'batches/12345678-1234-4234-8234-123456789012/24.json',
    'batches/12345678-1234-4234-8234-123456789012/00.json',
    'batches/12345678-1234-4234-8234-123456789012/latest.json',
    'nested/batches/12345678-1234-4234-8234-123456789012/request.json'])
def test_invalid_scope_rejected(tmp_path, relative):
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError): b.scavenge_once_temps([tmp_path/relative], owner)


@pytest.mark.parametrize('kind', ['directory', 'hardlink', 'symlink_metadata', 'reparse_metadata', 'fifo_metadata'])
def test_ambiguous_candidate_preserved_before_any_delete(tmp_path, kind, monkeypatch):
    path = target(tmp_path); first = debris(path, '0'*16); first.write_bytes(b'FIRST')
    ambiguous = debris(path, 'f'*16); sentinel = path.with_name('sentinel'); sentinel.write_bytes(b'KEEP')
    if kind == 'directory': ambiguous.mkdir(); (ambiguous/'child').write_bytes(b'KEEP')
    elif kind == 'hardlink': os.link(sentinel, ambiguous)
    else:
        ambiguous.write_bytes(b'KEEP'); original = Path.lstat
        def fake(p, *a, **kw):
            if p == ambiguous:
                return SimpleNamespace(st_mode=stat.S_IFLNK if kind == 'symlink_metadata' else
                    stat.S_IFIFO if kind == 'fifo_metadata' else stat.S_IFREG, st_nlink=1,
                    st_file_attributes=0x400 if kind == 'reparse_metadata' else 0)
            return original(p, *a, **kw)
        monkeypatch.setattr(Path, 'lstat', fake)
        monkeypatch.setattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400, raising=False)
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError): b.scavenge_once_temps([path], owner)
    assert first.read_bytes() == b'FIRST' and sentinel.read_bytes() == b'KEEP'


@pytest.mark.parametrize('part', ['batches', 'anchor'])
def test_reparse_parent_rejected(tmp_path, part, monkeypatch):
    path = target(tmp_path); orphan = debris(path); orphan.write_bytes(b'KEEP')
    directory = path.parent if part == 'anchor' else path.parent.parent
    original = Path.lstat
    def fake(p, *a, **kw):
        if p == directory: return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(p, *a, **kw)
    monkeypatch.setattr(Path, 'lstat', fake); monkeypatch.setattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400, raising=False)
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError): b.scavenge_once_temps([path], owner)
    assert orphan.read_bytes() == b'KEEP'


def test_cleanup_failure_blocks_new_immutable_write(tmp_path, monkeypatch):
    path = target(tmp_path); orphan = debris(path); orphan.write_bytes(b'KEEP')
    original = Path.unlink
    def denied(p, *a, **kw):
        if p == orphan: raise PermissionError('injected delete denial')
        return original(p, *a, **kw)
    monkeypatch.setattr(Path, 'unlink', denied)
    monkeypatch.setattr(b, 'atomic_json', lambda *a: pytest.fail('no replacement write after cleanup failure'))
    monkeypatch.setattr(os, 'link', lambda *a: pytest.fail('no publication after cleanup failure'))
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(PermissionError): b._once(path, {'new': True}, owner=owner)
    assert not path.exists() and orphan.read_bytes() == b'KEEP'


def test_duplicate_publication_after_safe_cleanup_still_blocked(tmp_path):
    path = target(tmp_path); b._once(path, {'original': True}); before = path.read_bytes()
    orphan = debris(path); orphan.write_bytes(b'not adopted')
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(FileExistsError): b._once(path, {'replacement': True}, owner=owner)
    assert path.read_bytes() == before and not orphan.exists()


def test_nonbatch_authority_keeps_existing_name_contract(tmp_path, monkeypatch):
    captured = []; original = os.link
    def observe(source, final): captured.append(source.name); return original(source, final)
    monkeypatch.setattr(os, 'link', observe)
    path = tmp_path/'declarations'/(new_id()+'.json'); b._once(path, {'authority': 'unchanged'})
    from uuid import UUID
    assert str(UUID(captured[0][:-4]))+'.tmp' == captured[0] and b._load(path) == {'authority': 'unchanged'}


def test_real_os_reparse_candidate_preserved(tmp_path, record_property):
    path = target(tmp_path); candidate = debris(path)
    outside = tmp_path/'outside'; outside.mkdir(); sentinel = outside/'sentinel'; sentinel.write_bytes(b'KEEP')
    if os.name == 'nt':
        p = subprocess.run(['cmd', '/c', 'mklink', '/J', str(candidate), str(outside)],
            capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert p.returncode == 0, p.stdout+p.stderr
        kind = 'actual Windows junction'
    else:
        candidate.symlink_to(outside, target_is_directory=True); kind = 'actual POSIX symlink'
    with PreviewOwnership(tmp_path) as owner:
        with pytest.raises(ValueError): b.scavenge_once_temps([path], owner)
    assert candidate.exists() and sentinel.read_bytes() == b'KEEP' and not path.exists()
    record_property('REAL_IMMUTABLE_OS_IO', json.dumps({'case': 'reparse', 'kind': kind, 'status': 'PASS'}))


def test_real_os_delete_denial_blocks_publication(tmp_path, record_property):
    path = target(tmp_path); orphan = debris(path); orphan.write_bytes(b'KEEP')
    with PreviewOwnership(tmp_path) as owner:
        if os.name == 'nt':
            from batch_process_recovery import windows_lock
            close = windows_lock(orphan); kind = 'actual Windows delete-sharing denial'
        else:
            if os.geteuid() == 0: pytest.skip('actual POSIX permission denial requires non-root')
            before = path.parent.stat().st_mode; path.parent.chmod(0o500)
            close = lambda: path.parent.chmod(before); kind = 'actual POSIX directory permission denial'
        try:
            with pytest.raises(PermissionError): b._once(path, {'never': 'published'}, owner=owner)
        finally: close()
    assert not path.exists() and orphan.read_bytes() == b'KEEP'
    record_property('REAL_IMMUTABLE_OS_IO', json.dumps({'case': 'delete-denial', 'kind': kind, 'status': 'PASS'}))
