"""Serialized outer-state fencing: real write rejection, unit fixtures, no renderer."""
import hashlib
import json
from threading import Event
from types import SimpleNamespace

import pytest

from fox3d import recipe_preview_service as service_module
from fox3d.preview_ownership import PreviewOwnership
from fox3d.recipe_3d import atomic_json, read_json, get_recipe_3d_dir
from fox3d.recipe_preview_service import RecipePreviewService, _same_state_identity


ABSENT = object()


def state(version=ABSENT):
    result = {'taskId': 'T', 'inputHash': 'H', 'state': 'running', 'progress': 50}
    if version is not ABSENT:
        result['batchVersion'] = version
    return result


def blocked_write(path, expected, persisted):
    atomic_json(path, persisted)
    before = path.read_bytes()
    with PreviewOwnership(path.parent) as owner:
        with pytest.raises(ValueError, match='身分'):
            RecipePreviewService._write_owned(path, expected, owner)
    assert path.read_bytes() == before  # Never normalize or repair changed identity.
    return before


@pytest.mark.parametrize('case,expected_version,persisted_version', [
    ('S1', 1, True), ('false-vs-zero', 0, False), ('string', 1, '1'),
    ('float', 1, 1.0), ('null', 1, None), ('different-int', 1, 2),
    ('S2', ABSENT, None), ('extra-false', ABSENT, False),
    ('extra-zero', ABSENT, 0), ('extra-int', ABSENT, 1),
    ('missing-version', 1, ABSENT), ('expected-bool', True, 1),
    ('both-bool', True, True), ('both-float', 1.0, 1.0),
    ('both-string', '1', '1'), ('both-null', None, None),
])
def test_version_tamper_cannot_overwrite_state(tmp_path, case, expected_version, persisted_version, record_property):
    expected = state(expected_version)
    persisted = {**state(persisted_version), 'progress': 10}
    path = tmp_path / 'state.json'
    before = blocked_write(path, expected, persisted)
    if case in {'S1', 'S2'}:
        record_property('STRICT_IDENTITY', json.dumps({
            'case': case, 'status': 'PASS', 'expected': expected, 'persisted': persisted,
            'beforeBytes': before.decode(), 'afterBytes': path.read_bytes().decode(),
            'beforeSha256': hashlib.sha256(before).hexdigest(),
            'afterSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'unchangedBytes': path.read_bytes() == before, 'classification': 'REAL_LOGIC / unit fixture',
        }))


@pytest.mark.parametrize('version', [ABSENT, 0, 1])
def test_exact_identity_allows_normal_progress_write(tmp_path, version):
    path = tmp_path / 'state.json'
    expected = state(version)
    atomic_json(path, {**expected, 'progress': 10})
    with PreviewOwnership(tmp_path) as owner:
        RecipePreviewService._write_owned(path, expected, owner)
    assert read_json(path) == expected
    assert ('batchVersion' in read_json(path)) == (version is not ABSENT)


@pytest.mark.parametrize('key', ['taskId', 'inputHash'])
@pytest.mark.parametrize('side', ['current', 'expected'])
@pytest.mark.parametrize('value', [ABSENT, None, True, 1, 1.0, [], {}, 'different'])
def test_required_string_identity_rejects_missing_wrong_type_or_value(tmp_path, key, side, value):
    expected = state(1)
    persisted = {**expected, 'progress': 10}
    target = persisted if side == 'current' else expected
    if value is ABSENT:
        target.pop(key)
    else:
        target[key] = value
    blocked_write(tmp_path / 'state.json', expected, persisted)


@pytest.mark.parametrize('side', ['current', 'expected'])
@pytest.mark.parametrize('key', ['taskId', 'inputHash', 'batchVersion'])
def test_python_scalar_subclasses_are_not_exact_json_types(side, key):
    class String(str):
        pass
    class Integer(int):
        pass
    current, expected = state(1), state(1)
    target = current if side == 'current' else expected
    target[key] = Integer(1) if key == 'batchVersion' else String(target[key])
    assert not _same_state_identity(current, expected)


@pytest.mark.parametrize('side', ['current', 'expected'])
@pytest.mark.parametrize('value', [None, [], 'identity'])
def test_non_object_identity_fails_closed(side, value):
    assert not _same_state_identity(value if side == 'current' else state(), value if side == 'expected' else state())


@pytest.mark.parametrize('release', ['close-owner', 'close-stream'])
def test_identity_match_still_requires_live_open_owner(tmp_path, release):
    path = tmp_path / 'state.json'
    expected = state(1)
    atomic_json(path, {**expected, 'progress': 10})
    before = path.read_bytes()
    owner = PreviewOwnership(tmp_path)
    if release == 'close-owner':
        owner.close()
    else:
        owner.stream.close()  # held flag alone is insufficient.
    try:
        with pytest.raises(ValueError, match='身分'):
            RecipePreviewService._write_owned(path, expected, owner)
        assert path.read_bytes() == before
    finally:
        owner.close()


@pytest.mark.parametrize('missing', ['taskId', 'inputHash'])
def test_status_recovery_cannot_normalize_incomplete_identity(tmp_path, missing):
    path = get_recipe_3d_dir(tmp_path, 't', 'm') / 'state.json'
    malformed = state()
    malformed.pop(missing)
    atomic_json(path, malformed)
    before = path.read_bytes()
    service = RecipePreviewService(SimpleNamespace(root=tmp_path))
    try:
        with pytest.raises(ValueError, match='身分'):
            service.status('t', 'm', {})
        assert path.read_bytes() == before and not service.tasks
        with PreviewOwnership(path.parent):
            pass
    finally:
        service.executor.shutdown()


@pytest.mark.parametrize('case', ['S1', 'S2'])
@pytest.mark.parametrize('phase', ['on_job', 'finally'])
def test_run_callback_and_finally_preserve_serialized_tamper(tmp_path, case, phase, monkeypatch):
    expected = state(1 if case == 'S1' else ABSENT)
    path = tmp_path / 'state.json'
    atomic_json(path, {**expected, 'progress': 0})
    owner = PreviewOwnership(tmp_path)
    stop = Event()
    key = ('tenant', 'master')
    tampered = []
    attempts = []
    callback_rejected = []
    original_atomic = service_module.atomic_json

    def observe_write(target, value):
        if tampered:
            attempts.append(value.copy())
        return original_atomic(target, value)

    monkeypatch.setattr(service_module, 'atomic_json', observe_write)

    def generate(*args, on_job, **kwargs):
        altered = {**read_json(path), 'batchVersion': True if case == 'S1' else None}
        atomic_json(path, altered)
        tampered.append(path.read_bytes())
        if phase == 'on_job':
            try:
                on_job({'jobId': 'must-not-write'})
            except ValueError:
                callback_rejected.append(True)
                raise
            pytest.fail('serialized tamper passed on_job fence')

    service = RecipePreviewService(SimpleNamespace(root=tmp_path), generate_fn=generate)
    service.tasks[key] = (expected['taskId'], stop)
    try:
        with pytest.raises(ValueError, match='身分'):
            service._run(key, {'draft': {}, 'revision': 1}, path, expected, stop, owner)
        assert tampered and path.read_bytes() == tampered[0]
        assert attempts == []  # Neither callback nor terminal/finally writes repair it.
        assert bool(callback_rejected) == (phase == 'on_job')
        assert key not in service.tasks and not owner.held and owner.stream.closed
        with PreviewOwnership(tmp_path):
            pass
    finally:
        owner.close()
        service.executor.shutdown()
