"""Unit tests for batch_process_recovery checkpoint I/O retries."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/helpers'))
import batch_process_recovery
from batch_process_recovery import read


@pytest.fixture
def win32(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')


def test_read_retries_transient_permission_error_then_succeeds(tmp_path, win32, monkeypatch):
    path = tmp_path / 'submit.json'
    path.write_text('{"ok": true}', encoding='utf-8')
    calls = {'n': 0}
    original_read_text = Path.read_text

    def read_text(self, encoding='utf-8'):
        calls['n'] += 1
        if calls['n'] < 3:
            raise PermissionError(13, 'Permission denied')
        return original_read_text(self, encoding=encoding)

    monkeypatch.setattr(Path, 'read_text', read_text)
    assert read(path) == {'ok': True}
    assert calls['n'] == 3


def test_read_retries_incomplete_json_then_succeeds(tmp_path, win32, monkeypatch):
    path = tmp_path / 'submit.json'
    path.write_text('{"ok": true}', encoding='utf-8')
    payloads = ['{"ok": ', '{"ok": true}']
    calls = {'n': 0}

    def read_text(self, encoding='utf-8'):
        calls['n'] += 1
        return payloads[min(calls['n'] - 1, len(payloads) - 1)]

    monkeypatch.setattr(Path, 'read_text', read_text)
    assert read(path) == {'ok': True}
    assert calls['n'] == 2


def test_read_raises_after_retry_budget_exhausted(tmp_path, win32, monkeypatch):
    path = tmp_path / 'submit.json'
    path.write_text('x', encoding='utf-8')
    monkeypatch.setattr(batch_process_recovery, '_READ_RETRY_SECONDS', 0.0)

    def read_text(self, encoding='utf-8'):
        raise PermissionError(13, 'Permission denied')

    monkeypatch.setattr(Path, 'read_text', read_text)
    with pytest.raises(PermissionError):
        read(path)


def test_read_does_not_retry_json_error_off_windows(tmp_path, monkeypatch):
    if sys.platform == 'win32':
        monkeypatch.setattr(sys, 'platform', 'linux')
    path = tmp_path / 'submit.json'
    path.write_text('{', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        read(path)