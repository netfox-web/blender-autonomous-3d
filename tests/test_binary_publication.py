import hashlib
import os
from pathlib import Path

import pytest

from fox3d import durability


def test_publish_binary_hash_size_and_no_debris(tmp_path):
    source = tmp_path / 'dam.bin'; source.write_bytes(os.urandom(2_000_000))
    target = tmp_path / 'generation' / 'model.blend'
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    result = durability.publish_binary(source, target, expected_sha256=expected, expected_size=source.stat().st_size)
    assert result == {'sha256': expected, 'size': source.stat().st_size}
    assert target.read_bytes() == source.read_bytes()
    assert not list(target.parent.glob('*.tmp'))


@pytest.mark.parametrize('kind', ['sha', 'size'])
def test_publish_binary_mismatch_leaves_old_final(tmp_path, kind):
    source = tmp_path / 'dam.bin'; source.write_bytes(b'complete-artifact')
    target = tmp_path / 'generation' / 'beauty.png'; target.parent.mkdir(); target.write_bytes(b'old')
    kwargs = {'expected_sha256': '0' * 64} if kind == 'sha' else {'expected_size': 99}
    with pytest.raises(ValueError): durability.publish_binary(source, target, **kwargs)
    assert target.read_bytes() == b'old'
    assert not list(target.parent.glob('*.tmp'))


def test_publish_binary_pre_namespace_failure_is_indeterminate_and_final_is_valid(tmp_path, monkeypatch):
    source = tmp_path / 'dam.bin'; source.write_bytes(b'complete')
    target = tmp_path / 'generation' / 'model.glb'
    original = durability.namespace_committed
    def fail(path, operation):
        raise durability.CommitIndeterminate(path, operation, OSError(5, 'injected'))
    monkeypatch.setattr(durability, 'namespace_committed', fail)
    with pytest.raises(durability.CommitIndeterminate): durability.publish_binary(source, target)
    assert target.read_bytes() == b'complete'
    monkeypatch.setattr(durability, 'namespace_committed', original)


def test_publish_binary_wrong_source_and_symlink_target_fail_closed(tmp_path):
    target = tmp_path / 'generation' / 'geometry.json'
    with pytest.raises(FileNotFoundError): durability.publish_binary(tmp_path / 'missing', target)
    source = tmp_path / 'dam'; source.write_bytes(b'x')
    outside = tmp_path / 'outside'; outside.write_bytes(b'keep')
    target.parent.mkdir()
    try:
        target.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f'symlink privilege unavailable: {exc}')
    with pytest.raises(Exception): durability.publish_binary(source, target)
    assert outside.read_bytes() == b'keep'


def test_publish_bytes_streams_png_payload_without_final_write_window(tmp_path):
    target = tmp_path / 'generation' / 'derived-preview.png'
    payload = b'PNG-derived-bytes'
    result = durability.publish_bytes(lambda stream: stream.write(payload), target,
                                      expected_sha256=hashlib.sha256(payload).hexdigest(),
                                      expected_size=len(payload))
    assert result['size'] == len(payload)
    assert target.read_bytes() == payload
    assert not list(target.parent.glob('*.tmp'))


def test_publish_bytes_writer_error_preserves_old_final(tmp_path):
    target = tmp_path / 'generation' / 'derived-preview.png'; target.parent.mkdir(); target.write_bytes(b'old')
    def fail(stream):
        stream.write(b'partial')
        raise RuntimeError('writer failed')
    with pytest.raises(RuntimeError): durability.publish_bytes(fail, target)
    assert target.read_bytes() == b'old'
    assert not list(target.parent.glob('*.tmp'))
