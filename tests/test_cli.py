import json

import pytest

from fox3d import cli
from fox3d.blender import BLOCKED_NO_BLENDER, HostProbe
from fox3d.platform import Platform


@pytest.fixture
def job_file(tmp_path):
    path = tmp_path / 'job.json'
    path.write_text(json.dumps({'tenantId': 'test', 'render': {'width': 16, 'height': 16}}))
    return path


@pytest.fixture
def no_blender(monkeypatch):
    monkeypatch.delenv('FOX3D_MOCK_BLENDER', raising=False)
    monkeypatch.setattr('fox3d.blender.find_blender', lambda explicit=None: None)
    monkeypatch.setattr('fox3d.platform.probe_host', lambda **kwargs: HostProbe(
        blender=False, blenderBinary=None, blenderVersion=None, blenderVersionRaw='',
        cycles=False, cuda=False, optix=False, gpus=[], gpuName=None, vramGb=0,
        driver=None, blocked=[BLOCKED_NO_BLENDER], realBlender=False, realGPU=False,
        realCycles=False, realOptix=False,
    ))


def test_detect_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'detect_node', lambda: {'blender': False})
    assert cli.main(['detect']) == 0
    assert json.loads(capsys.readouterr().out) == {'blender': False}


def test_job_without_blender(job_file, tmp_path, no_blender, monkeypatch, capsys):
    nodes = []
    register = Platform.register_node
    def capture(self, **kwargs):
        nodes.append(kwargs['target_key'])
        return register(self, **kwargs)
    monkeypatch.setattr(Platform, 'register_node', capture)
    root = tmp_path / 'custom'
    assert cli.main(['job', str(job_file), '--root', str(root)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'blocked'
    assert result['error'] == BLOCKED_NO_BLENDER
    assert 'cli' not in nodes
    assert result['assignedComputeTargetKey'] is None
    assert root.is_dir()


def test_mock_job(job_file, tmp_path, no_blender, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(['job', str(job_file), '--mock']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'succeeded'
    assert result['usedMock'] is True
    assert result['assignedComputeTargetKey'] is None
    assert (tmp_path / '.fox3d-data').is_dir()


@pytest.mark.parametrize(('status', 'code'), [('completed', 0), ('succeeded', 0), ('blocked', 1), ('failed', 1), ('queued', 1)])
def test_exit_status(job_file, tmp_path, no_blender, monkeypatch, capsys, status, code):
    monkeypatch.setattr(Platform, 'execute_job', lambda self, job: {'status': status})
    assert cli.main(['job', str(job_file), '--root', str(tmp_path / 'data')]) == code
    assert json.loads(capsys.readouterr().out)['status'] == status


def test_argument_error():
    with pytest.raises(SystemExit) as exc:
        cli.main(['job'])
    assert exc.value.code == 2
