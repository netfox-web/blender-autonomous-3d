"""MOCK error regressions plus three actual Windows handle-lock integrations."""
import ctypes
import errno
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from fox3d import recipe_3d as r
from fox3d.model_batches import _once

A = {'value': 'A', 'revision': 1}
B = {'value': 'B 中文', 'revision': 2}


def destination(tmp_path):
    target = tmp_path/'state.json'
    target.write_text(json.dumps(A), encoding='utf-8')
    return target, target.read_bytes()


def winerror(code):
    error = PermissionError(errno.EACCES, 'injected regression fault')
    error.winerror = code
    return error


@pytest.mark.parametrize('existing', [True, False])
def test_atomic_success_exact_json_and_no_temp(tmp_path, existing):
    target, original = destination(tmp_path)
    if not existing:
        target.unlink()
    r.atomic_json(target, B)
    assert json.loads(target.read_text(encoding='utf-8')) == B
    assert list(tmp_path.glob('*.tmp')) == []


@pytest.mark.parametrize('value', [{'bad': object()}, {'bad': '\ud800'}])
def test_serialization_or_encoding_failure_cleans_owned_temp(tmp_path, value):
    target, original = destination(tmp_path)
    with pytest.raises((TypeError, UnicodeEncodeError)):
        r.atomic_json(target, value)
    assert target.read_bytes() == original
    assert list(tmp_path.glob('*.tmp')) == []


def test_temp_collision_never_overwrites_or_removes_someone_elses_file(tmp_path, monkeypatch):
    target, original = destination(tmp_path)
    monkeypatch.setattr(r, 'new_id', lambda: '12345678')
    other = tmp_path/'state.json.12345678.tmp'
    other.write_bytes(b'other writer')
    with pytest.raises(FileExistsError):
        r.atomic_json(target, B)
    assert target.read_bytes() == original and other.read_bytes() == b'other writer'


@pytest.mark.parametrize('code', [errno.ENOSPC, errno.EINVAL, errno.EIO, errno.EACCES, errno.ENOENT])
def test_non_contention_replace_error_propagates_once(tmp_path, monkeypatch, code):
    target, original = destination(tmp_path)
    error = OSError(code, 'injected non-contention fault')
    calls = []
    def replace(source, dest):
        calls.append(source)
        raise error
    monkeypatch.setattr(Path, 'replace', replace)
    with pytest.raises(OSError) as caught:
        r.atomic_json(target, B)
    assert caught.value is error and len(calls) == 1
    assert target.read_bytes() == original and not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('code,probe,expected', [(5,0,False),(5,5,False),(5,32,True),(5,33,True),
                                              (32,None,True),(33,None,True),(112,None,False),
                                              (3,None,False),(None,None,False)])
def test_windows_contention_classification_is_narrow(monkeypatch, code, probe, expected):
    monkeypatch.setattr(r, 'sys', SimpleNamespace(platform='win32'))
    calls = []
    monkeypatch.setattr(r, '_delete_sharing_error', lambda p: calls.append(p) or probe)
    assert r._windows_replace_contention(winerror(code), Path('unused')) is expected
    assert len(calls) == (1 if code == 5 else 0)


def test_non_windows_does_not_retry_windows_shaped_error(monkeypatch):
    monkeypatch.setattr(r, 'sys', SimpleNamespace(platform='linux'))
    assert not r._windows_replace_contention(winerror(32), Path('unused'))


@pytest.mark.parametrize('code', [5, 32, 33])
def test_mock_transient_retry_keeps_exact_destination_until_success(tmp_path, monkeypatch, code):
    target, original = destination(tmp_path)
    monkeypatch.setattr(r, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(r, '_delete_sharing_error', lambda p: 32)
    pauses = []
    monkeypatch.setattr(r, 'time', SimpleNamespace(sleep=pauses.append))
    original_replace = Path.replace
    calls = []
    def replace(source, dest):
        calls.append(source)
        assert target.read_bytes() == original
        if len(calls) <= 2:
            raise winerror(code)
        return original_replace(source, dest)
    monkeypatch.setattr(Path, 'replace', replace)
    r.atomic_json(target, B)
    assert len(calls) == 3 and pauses == list(r._ATOMIC_RETRY_DELAYS[:2])
    assert json.loads(target.read_text(encoding='utf-8')) == B and not list(tmp_path.glob('*.tmp'))


def test_mock_sustained_contention_has_bounded_failure_and_cleanup(tmp_path, monkeypatch):
    target, original = destination(tmp_path)
    monkeypatch.setattr(r, 'sys', SimpleNamespace(platform='win32'))
    pauses = []
    monkeypatch.setattr(r, 'time', SimpleNamespace(sleep=pauses.append))
    error = winerror(32)
    calls = []
    def replace(source, dest):
        calls.append(source)
        raise error
    monkeypatch.setattr(Path, 'replace', replace)
    with pytest.raises(PermissionError) as caught:
        r.atomic_json(target, B)
    assert caught.value is error
    assert len(calls) == 8 and pauses == list(r._ATOMIC_RETRY_DELAYS)
    assert sum(pauses) == pytest.approx(.975)
    assert target.read_bytes() == original and not list(tmp_path.glob('*.tmp'))


def test_access_denied_without_sharing_evidence_is_not_retried(tmp_path, monkeypatch):
    target, original = destination(tmp_path)
    monkeypatch.setattr(r, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(r, '_delete_sharing_error', lambda p: 5)
    calls = []
    def replace(source, dest):
        calls.append(source)
        raise winerror(5)
    monkeypatch.setattr(Path, 'replace', replace)
    with pytest.raises(PermissionError):
        r.atomic_json(target, B)
    assert len(calls) == 1 and target.read_bytes() == original
    assert not list(tmp_path.glob('*.tmp'))


def test_write_enospc_cleans_temp_without_replace_or_retry(tmp_path, monkeypatch):
    target, original = destination(tmp_path)
    open_file = Path.open
    error = OSError(errno.ENOSPC, 'injected write failure')
    class BrokenWrite:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): self.stream.__enter__(); return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def write(self, value): raise error
    def open_temp(path, *args, **kwargs):
        stream = open_file(path, *args, **kwargs)
        return BrokenWrite(stream) if args and args[0] == 'x' else stream
    monkeypatch.setattr(Path, 'open', open_temp)
    with pytest.raises(OSError) as caught:
        r.atomic_json(target, B)
    assert caught.value is error and target.read_bytes() == original
    assert not list(tmp_path.glob('*.tmp'))


def test_immutable_once_still_rejects_replay_and_cleans_temp(tmp_path):
    target = tmp_path/'request.json'
    _once(target, A)
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        _once(target, B)
    assert target.read_bytes() == original and not list(tmp_path.glob('*.tmp'))


def windows_lock(path):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,
                                  wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path),0x80000000,0x1|0x2,None,3,0x80,None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    def close():
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    return close


@pytest.mark.skipif(sys.platform != 'win32', reason='REAL_OS_IO requires Windows')
@pytest.mark.parametrize('release_delay', [.05, .2])
def test_windows_real_transient_delete_sharing_lock(tmp_path, monkeypatch, record_property, release_delay):
    target, original = destination(tmp_path)
    close = windows_lock(target)
    assert r._delete_sharing_error(target) == 32
    failed = threading.Event()
    released = threading.Event()
    errors = []
    actual_replace = Path.replace
    def observed_replace(source, dest):
        try: return actual_replace(source, dest)
        except OSError as error:
            errors.append(error.winerror)
            assert target.read_bytes() == original
            failed.set()
            raise
    def release():
        try:
            failed.wait(timeout=3)
            time.sleep(release_delay)
        finally:
            close()
            released.set()
    monkeypatch.setattr(Path, 'replace', observed_replace)
    thread = threading.Thread(target=release)
    thread.start()
    started = time.monotonic()
    try: r.atomic_json(target, B)
    finally: thread.join(timeout=4)
    assert released.is_set() and errors and all(e in (5,32,33) for e in errors)
    assert len(errors) <= len(r._ATOMIC_RETRY_DELAYS)
    assert json.loads(target.read_text(encoding='utf-8')) == B
    assert not list(tmp_path.glob('*.tmp'))
    record_property('REAL_OS_IO', json.dumps({'kind':'transient','errors':errors,'releaseDelay':release_delay,
                    'elapsed':time.monotonic()-started,'exactB':True,'tempClean':True}))


@pytest.mark.skipif(sys.platform != 'win32', reason='REAL_OS_IO requires Windows')
def test_windows_real_sustained_delete_sharing_lock(tmp_path, monkeypatch, record_property):
    target, original = destination(tmp_path)
    close = windows_lock(target)
    actual_replace = Path.replace
    errors = []
    def observed_replace(source, dest):
        try: return actual_replace(source, dest)
        except OSError as error: errors.append(error.winerror); raise
    monkeypatch.setattr(Path, 'replace', observed_replace)
    started = time.monotonic()
    try:
        with pytest.raises(PermissionError) as caught:
            r.atomic_json(target, B)
        assert caught.value.winerror in (5,32,33)
        assert len(errors) == 8 and all(e in (5,32,33) for e in errors)
        assert target.read_bytes() == original and json.loads(target.read_text()) == A
        assert not list(tmp_path.glob('*.tmp'))
    finally: close()
    record_property('REAL_OS_IO', json.dumps({'kind':'sustained','errors':errors,
                    'elapsed':time.monotonic()-started,'oldAUnchanged':True,'tempClean':True}))
