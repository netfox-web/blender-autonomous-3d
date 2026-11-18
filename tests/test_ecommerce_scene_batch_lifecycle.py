from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.ecommerce_scene_api import ecommerce_scene_router
from fox3d.ecommerce_scene_studio import EcommerceSceneStore


@pytest.fixture
def setup(tmp_path: Path):
    platform = SimpleNamespace(root=tmp_path, mock_blender=True)
    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'):
        store = EcommerceSceneStore(platform)
    futures: list[Future] = []

    def hold(*args, **kwargs):
        future = Future()
        futures.append(future)
        return future

    store.executor.submit = hold  # type: ignore[method-assign]
    app = FastAPI()
    with patch('fox3d.ecommerce_scene_api.EcommerceSceneStore', return_value=store):
        app.include_router(ecommerce_scene_router(lambda: platform))
        with TestClient(app) as client:
            yield client, store, futures
    store.executor.shutdown(wait=True)
    store.ai_executor.shutdown(wait=True)


def test_invalid_identifiers_return_404(setup):
    client, _, _ = setup
    long_id = 'a' * 3000
    for path in (f'/batches/{long_id}', f'/batches/{long_id}/zip',
                 f'/batches/ok/items/{long_id}/download/png', f'/polyhaven-thumb/{long_id}',
                 '/batches/not.valid', '/polyhaven-thumb/not.valid'):
        assert client.get('/api/ecommerce-scenes' + path).status_code == 404
    assert client.post('/api/ecommerce-scenes/batches/' + long_id + '/cancel').status_code == 404
    assert client.delete('/api/ecommerce-scenes/batches/' + long_id).status_code == 404
    assert client.get('/api/ecommerce-scenes/batches/missing/zip').json()['detail'] == '找不到資源'


def test_idempotency_concurrent_and_persistent(setup):
    client, store, futures = setup
    url = '/api/ecommerce-scenes/batches'
    body = {'idempotencyKey': 'same-key', 'aiEngine': 'off', 'blenderEngine': 'local'}
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post(url, json=body), range(8)))
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()['batchId'] for r in responses}) == 1
    assert len(futures) == 1
    assert client.post(url, json={**body, 'samples': 40}).status_code == 409
    assert client.post(url, json=body, headers={'X-Tenant-Id': 'other'}).json()['batchId'] != responses[0].json()['batchId']
    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'):
        other_store = EcommerceSceneStore(store.platform)
    assert other_store.start_matrix_batch('sonaqueen-home', body)['batchId'] == responses[0].json()['batchId']
    other_store.executor.shutdown()
    other_store.ai_executor.shutdown()


def test_cancel_and_delete_are_tenant_scoped_and_idempotent(setup):
    client, store, futures = setup
    url = '/api/ecommerce-scenes/batches'
    response = client.post(url, json={'aiEngine': 'off', 'views': ['FRONT', 'THREE_QUARTER']})
    batch_id = response.json()['batchId']
    path = f'{url}/{batch_id}'
    assert client.post(path + '/cancel', headers={'X-Tenant-Id': 'other'}).status_code == 404
    assert client.delete(path, headers={'X-Tenant-Id': 'other'}).status_code == 404
    assert client.delete(path).status_code == 409
    live = store._live_docs[batch_id]
    live['items'][0]['state'] = 'succeeded'
    result = client.post(path + '/cancel')
    assert result.status_code == 200
    assert result.json()['state'] == 'cancelled'
    assert [i['state'] for i in result.json()['items']] == ['succeeded', 'cancelled']
    assert client.post(path + '/cancel').json() == result.json()
    assert client.delete(path).status_code == 409  # worker has not exited
    futures[0].set_result(None)
    assert client.delete(path).status_code == 200
    assert client.get(path).status_code == 404


def test_corrupt_scenes_are_never_overwritten(setup):
    client, store, _ = setup
    url = '/api/ecommerce-scenes/scenes'
    assert client.post(url, json={'id': 'first', 'name': 'First'}).status_code == 201
    path = store._tenant_dir('sonaqueen-home') / 'scenes.json'
    broken = b'{"items": [broken'
    path.write_bytes(broken)
    assert client.post(url, json={'name': 'Second'}).status_code == 503
    assert client.delete(url + '/first').status_code == 503
    assert path.read_bytes() == broken
    path.unlink()
    assert client.delete(url + '/missing').status_code == 404
    assert not path.exists()


def test_cancel_during_render_finishes_current_item_only(setup):
    client, store, _ = setup
    store.platform.mock_blender = False
    store.platform.runtime = SimpleNamespace(available=lambda: True)
    work = []
    store.executor.submit = lambda fn, *args: (work.append((fn, args)) or Future())  # type: ignore[method-assign]
    response = client.post('/api/ecommerce-scenes/batches', json={
        'aiEngine': 'off', 'blenderEngine': 'local', 'views': ['FRONT', 'THREE_QUARTER'],
    })
    batch_id = response.json()['batchId']
    calls = []

    def render(job, item_dir):
        calls.append(job)
        result = client.post(f'/api/ecommerce-scenes/batches/{batch_id}/cancel')
        assert [x['state'] for x in result.json()['items']] == ['running', 'cancelled']
        return {}

    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'), patch.object(store, '_render_locally', render):
        fn, args = work[0]
        fn(*args)
    result = client.get(f'/api/ecommerce-scenes/batches/{batch_id}').json()
    assert len(calls) == 1
    assert result['state'] == 'cancelled'
    assert [x['state'] for x in result['items']] == ['succeeded', 'cancelled']
