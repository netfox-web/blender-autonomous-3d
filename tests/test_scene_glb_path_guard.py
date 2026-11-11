from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fox3d.ecommerce_scene_studio import EcommerceSceneStore
from fox3d.pngutil import write_glb_stub


def _minimal_glb_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "fixture.glb"
    write_glb_stub(path, name="Prop")
    return path.read_bytes()


@pytest.fixture
def store(tmp_path):
    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'):
        return EcommerceSceneStore(SimpleNamespace(root=tmp_path, mock_blender=True))


def scene(path):
    return {'id': 'custom', 'name': 'Test', 'props': [{'type': 'CUSTOM_BOX', 'glbPath': path}]}


def test_allowed_upload_and_polyhaven(store, tmp_path):
    uploaded = store.upload_glb_prop('alice', 'chair.glb', _minimal_glb_bytes(tmp_path))['glbPath']
    poly = Path(__file__).resolve().parents[1] / 'assets/models/polyhaven/test/model.gltf'
    for path in (uploaded, str(poly), 'assets://models/polyhaven/test/model.gltf'):
        guarded, warnings = store.guard_scene_paths('alice', scene(path))
        assert guarded['props'][0]['glbPath'] == path
        assert warnings == []


def test_rejects_unsafe_paths_and_falls_back(store, tmp_path):
    upload = store._tenant_dir('alice') / 'glb-props'
    upload.mkdir()
    outside = tmp_path / 'outside.glb'
    outside.write_bytes(b'x')
    link = upload / 'escape.glb'
    try:
        link.symlink_to(outside)
    except OSError:
        link = None
    paths = ['/etc/passwd', r'C:\Windows\secret.glb', str(upload / '../../escape.glb'),
             str(store._tenant_dir('bob') / 'glb-props/model.glb'),
             'assets://models/polyhaven/../../../secret.glb',
             r'assets://models/polyhaven/..\..\..\secret.glb', str(upload / 'bad.txt')]
    if link:
        paths.append(str(link))
    for path in paths:
        result = store.preview_plan('alice', {'scene': scene(path)})
        assert 'glbPath' not in result['sceneConfig']['props'][0]
        assert all('glbPath' not in box for box in result['sceneDefinition']['boxes'])
        assert result['warnings']


def test_native_upload_path_and_traversal(store, tmp_path):
    uploaded = tmp_path / store.upload_glb_prop('alice', 'chair.glb', _minimal_glb_bytes(tmp_path))['glbPath']
    guarded, warnings = store.guard_scene_paths('alice', scene(str(uploaded)))
    assert guarded['props'][0]['glbPath'] == str(uploaded)
    assert not warnings
    escaped = uploaded.parent / '..' / '..' / 'bob' / 'glb-props' / 'model.glb'
    guarded, warnings = store.guard_scene_paths('alice', scene(str(escaped)))
    assert 'glbPath' not in guarded['props'][0]
    assert warnings


def test_save_and_batch_guard_existing_and_inline_scenes(store):
    saved = store.save_scene('alice', scene('/etc/passwd'))
    assert saved['warnings'] and 'glbPath' not in saved['props'][0]
    with patch.object(store.executor, 'submit') as submit:
        batch = store.start_matrix_batch('alice', {'sceneIds': ['custom'], 'currentScene': scene('/tmp/evil.glb'), 'aiEngine': 'off'})
    assert batch['warnings']
    assert 'glbPath' not in batch['request']['currentScene']['props'][0]
    scenes = submit.call_args.args[5]
    assert 'glbPath' not in scenes['custom']['props'][0]


def test_ai_layout_endpoint_guards_generated_paths(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fox3d.ecommerce_scene_api import ecommerce_scene_router

    app = FastAPI()
    app.include_router(ecommerce_scene_router(lambda: store.platform))
    generated = scene('/tmp/ai-escape.glb')
    with patch('fox3d.ai_scene_layout.generate_ai_layout', return_value=generated), \
         patch('fox3d.ai_scene_layout.load_settings', return_value={}), \
         patch('fox3d.ecommerce_scene_api.EcommerceSceneStore', return_value=store):
        response = TestClient(app).post('/api/ecommerce-scenes/ai-layout', json={'prompt': 'room'}, headers={'X-Tenant-Id': 'alice'})
    assert response.status_code == 200
    assert response.json()['warnings']
    assert 'glbPath' not in response.json()['props'][0]
def test_relative_upload_path_is_preserved(store, tmp_path):
    fixture = tmp_path / 'fixture.glb'
    write_glb_stub(fixture, name='Prop')
    uploaded = store.upload_glb_prop('alice', 'chair.glb', fixture.read_bytes())['glbPath']
    guarded, warnings = store.guard_scene_paths('alice', scene(uploaded))
    assert guarded['props'][0]['glbPath'] == uploaded
    assert not warnings


def test_relative_other_tenant_upload_is_rejected(store, tmp_path):
    fixture = tmp_path / 'fixture.glb'
    write_glb_stub(fixture, name='Prop')
    uploaded = store.upload_glb_prop('bob', 'chair.glb', fixture.read_bytes())['glbPath']
    guarded, warnings = store.guard_scene_paths('alice', scene(uploaded))
    assert 'glbPath' not in guarded['props'][0]
    assert warnings


def test_relative_unsafe_upload_paths_are_rejected(store, tmp_path):
    upload = store._tenant_dir('alice') / 'glb-props'
    upload.mkdir()
    outside = tmp_path / 'outside.glb'
    outside.write_bytes(b'x')
    link = upload / 'escape.glb'
    paths = [
        (upload / '..' / 'glb-props' / 'model.glb').relative_to(tmp_path).as_posix(),
        (upload / 'bad.txt').relative_to(tmp_path).as_posix(),
        r'ecommerce-scene-studio\alice\glb-props\model.glb',
    ]
    try:
        link.symlink_to(outside)
    except OSError:
        pass
    else:
        paths.append(link.relative_to(tmp_path).as_posix())
    for path in paths:
        guarded, warnings = store.guard_scene_paths('alice', scene(path))
        assert 'glbPath' not in guarded['props'][0]
        assert warnings
