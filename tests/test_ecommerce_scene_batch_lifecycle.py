import json
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.ecommerce_scene_api import ecommerce_scene_router
from fox3d.ecommerce_scene_studio import EcommerceSceneStore
from fox3d.recipe_3d import read_json as _read_json


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


@pytest.mark.parametrize('key', ['', 'x' * 201, 123, [], {}])
def test_invalid_idempotency_key_is_rejected(setup, key):
    client, _, futures = setup
    response = client.post('/api/ecommerce-scenes/batches', json={'idempotencyKey': key, 'aiEngine': 'off'})
    assert response.status_code == 422
    assert not futures


def test_submit_failure_replays_durable_batch(setup):
    _, store, futures = setup
    body = {'idempotencyKey': 'retry-submit', 'aiEngine': 'off', 'blenderEngine': 'local'}
    original_submit = store.executor.submit
    with patch.object(store.executor, 'submit', side_effect=RuntimeError('executor unavailable')):
        with pytest.raises(RuntimeError):
            store.start_matrix_batch('tenant', body)
    paths = list((store._tenant_dir('tenant') / 'batches').glob('*/batch.json'))
    assert len(paths) == 1
    assert not store._live_docs
    store.executor.submit = original_submit  # type: ignore[method-assign]
    replay = store.start_matrix_batch('tenant', body)
    assert replay['batchId'] == paths[0].parent.name
    assert len(futures) == 1
    assert store.start_matrix_batch('tenant', body)['batchId'] == replay['batchId']
    assert len(futures) == 1


def test_new_idempotency_key_skips_batch_glob_after_reconcile(setup):
    _, store, _ = setup
    body = {'aiEngine': 'off', 'blenderEngine': 'local'}
    for views in (['FRONT'], ['THREE_QUARTER'], ['FRONT', 'THREE_QUARTER']):
        store.start_matrix_batch('tenant', {**body, 'views': views})
    store.reconcile_idempotency_index('tenant')
    reads = []

    def track(path, *args, **kwargs):
        if isinstance(path, Path) and path.name == 'batch.json':
            reads.append(path)
        return _read_json(path, *args, **kwargs)

    with patch('fox3d.ecommerce_scene_studio.read_json', side_effect=track):
        store.start_matrix_batch('tenant', {**body, 'idempotencyKey': 'fresh-uuid-never-seen', 'views': ['FRONT']})
    assert not reads


def test_restart_recovers_pending_batch_before_index_write(setup):
    _, store, _ = setup
    body = {'idempotencyKey': 'restart-pending', 'aiEngine': 'off', 'blenderEngine': 'local'}
    with patch.object(store.executor, 'submit', side_effect=RuntimeError('stopped')):
        with pytest.raises(RuntimeError):
            store.start_matrix_batch('tenant', body)
    (store._tenant_dir('tenant') / 'batch-keys.json').unlink()
    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'):
        restarted = EcommerceSceneStore(store.platform)
    work = []
    restarted.executor.submit = lambda fn, *args: (work.append((fn, args)) or Future())  # type: ignore[method-assign]
    result = restarted.start_matrix_batch('tenant', body)
    assert len(work) == 1
    fn, args = work[0]
    restarted.platform.mock_blender = False
    restarted.platform.runtime = SimpleNamespace(available=lambda: True)
    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'), \
         patch.object(restarted, '_render_locally', return_value={}) as render:
        fn(*args)
    assert render.call_count == 1
    saved = restarted.get_batch('tenant', result['batchId'])
    assert saved['scheduleState'] == 'started'
    assert saved['state'] == 'completed'
    assert restarted.start_matrix_batch('tenant', body)['batchId'] == result['batchId']
    assert len(work) == 1
    restarted.executor.shutdown()
    restarted.ai_executor.shutdown()


def test_fleet_window_submits_before_collect_and_cancels_queued(setup):
    client, store, _ = setup
    work = []
    store.executor.submit = lambda fn, *args: (work.append((fn, args)) or Future())  # type: ignore[method-assign]
    response = client.post('/api/ecommerce-scenes/batches', json={
        'aiEngine': 'off', 'blenderEngine': 'fleet',
        'views': ['FRONT', 'THREE_QUARTER', 'FRONT', 'FRONT', 'FRONT', 'FRONT'],
    })
    batch_id = response.json()['batchId']
    submitted = []

    def submit(_client, job, **kwargs):
        submitted.append(job['jobId'])
        return {'id': job['jobId']}

    collected = []

    def collect(_client, job, item_dir, **kwargs):
        collected.append(job["jobId"])
        if len(collected) == 1:
            assert len(submitted) == 4
            result = client.post(f'/api/ecommerce-scenes/batches/{batch_id}/cancel').json()
            assert [x['state'] for x in result['items']] == ['running'] * 4 + ['cancelled'] * 2
        return {}

    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'), \
         patch('fox3d.ecommerce_scene_studio.FleetImageClient.from_settings', return_value=object()), \
         patch('fox3d.ecommerce_scene_studio.blender_fleet_status', return_value={'ready': True}), \
         patch('fox3d.ecommerce_scene_studio.submit_blender_job', side_effect=submit), \
         patch('fox3d.ecommerce_scene_studio.render_on_fleet', side_effect=collect):
        fn, args = work[0]
        fn(*args)
    result = client.get(f'/api/ecommerce-scenes/batches/{batch_id}').json()
    assert len(submitted) == 4
    assert [x['state'] for x in result['items']] == ['succeeded'] * 4 + ['cancelled'] * 2


def test_cancelled_pending_batch_is_not_rescheduled(setup):
    _, store, futures = setup
    body = {'idempotencyKey': 'cancel-before-start', 'aiEngine': 'off'}
    batch = store.start_matrix_batch('tenant', body)
    assert store.cancel_batch('tenant', batch['batchId'])['state'] == 'cancelled'
    futures[0].set_result(None)
    assert store.start_matrix_batch('tenant', body)['state'] == 'cancelled'
    assert len(futures) == 1


def test_fleet_window_refills_after_collection(setup):
    client, store, _ = setup
    work = []
    store.executor.submit = lambda fn, *args: (work.append((fn, args)) or Future())  # type: ignore[method-assign]
    batch = client.post('/api/ecommerce-scenes/batches', json={
        'aiEngine': 'off', 'blenderEngine': 'fleet', 'views': ['FRONT'] * 6,
    }).json()
    submitted = []
    counts = []

    def submit(_client, job, **kwargs):
        submitted.append(job['jobId'])
        return {'id': job['jobId']}

    def collect(_client, job, item_dir, **kwargs):
        counts.append(len(submitted))
        return {}

    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'), \
         patch('fox3d.ecommerce_scene_studio.FleetImageClient.from_settings', return_value=object()), \
         patch('fox3d.ecommerce_scene_studio.blender_fleet_status', return_value={'ready': True}), \
         patch('fox3d.ecommerce_scene_studio.submit_blender_job', side_effect=submit), \
         patch('fox3d.ecommerce_scene_studio.render_on_fleet', side_effect=collect):
        fn, args = work[0]
        fn(*args)
    assert counts == [4, 5, 6, 6, 6, 6]
    result = client.get('/api/ecommerce-scenes/batches/' + batch['batchId']).json()
    assert result['state'] == 'completed'
    assert all(item['state'] == 'succeeded' for item in result['items'])


def _restart(platform):
    """A fresh store on the same data directory whose executor records submissions instead of running them."""
    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'):
        restarted = EcommerceSceneStore(platform)
    work: list = []
    restarted.executor.submit = lambda fn, *args: (work.append((fn, args)) or Future())  # type: ignore[method-assign]
    return restarted, work


def _run(store, work_item):
    fn, args = work_item
    store.platform.mock_blender = False
    store.platform.runtime = SimpleNamespace(available=lambda: True)
    with patch('fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets'), \
         patch.object(store, '_render_locally', return_value={}) as render:
        fn(*args)
    return render.call_count


def test_restart_recovers_queued_batch_without_key_on_read(setup):
    _, store, futures = setup
    body = {'aiEngine': 'off', 'blenderEngine': 'local'}
    first = store.start_matrix_batch('tenant', body)
    queued = store.start_matrix_batch('tenant', {**body, 'views': ['FRONT', 'THREE_QUARTER']})
    assert len(futures) == 2  # both accepted; the process "dies" before any worker claims them
    restarted, work = _restart(store.platform)
    # Another tenant can neither see nor wake the batch.
    with pytest.raises(KeyError):
        restarted.get_batch('other', queued['batchId'])
    assert not work
    doc = restarted.get_batch('tenant', queued['batchId'])
    assert doc['state'] == 'running' and doc['scheduleState'] == 'pending'
    assert len(work) == 1
    # Reading again (and listing) does not schedule it a second time; listing also wakes the other batch.
    restarted.get_batch('tenant', queued['batchId'])
    listed = {b['batchId']: b for b in restarted.list_batches('tenant')}
    assert listed[first['batchId']]['state'] == 'running'
    assert len(work) == 2
    restarted.list_batches('tenant')
    assert len(work) == 2
    assert _run(restarted, work[0]) == 2
    saved = restarted.get_batch('tenant', queued['batchId'])
    assert saved['state'] == 'completed'
    assert saved['scheduleState'] == 'started'
    assert [i['state'] for i in saved['items']] == ['succeeded', 'succeeded']
    # Once claimed, a later restart never replays it.
    again, again_work = _restart(store.platform)
    assert again.get_batch('tenant', queued['batchId'])['state'] == 'completed'
    assert again.recover_pending_batches() == 1  # only the still-unclaimed first batch
    assert len(again_work) == 1
    for s in (restarted, again):
        s.executor.shutdown()
        s.ai_executor.shutdown()


def test_restart_recovers_concurrent_reads_once(setup):
    _, store, _ = setup
    batch = store.start_matrix_batch('tenant', {'aiEngine': 'off'})
    restarted, work = _restart(store.platform)
    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(lambda _: restarted.get_batch('tenant', batch['batchId'])['state'], range(8)))
    assert states == ['running'] * 8
    assert len(work) == 1
    restarted.executor.shutdown()
    restarted.ai_executor.shutdown()


def test_recovered_pending_batch_can_be_cancelled(setup):
    _, store, _ = setup
    batch = store.start_matrix_batch('tenant', {'aiEngine': 'off', 'views': ['FRONT', 'THREE_QUARTER']})
    restarted, work = _restart(store.platform)
    result = restarted.cancel_batch('tenant', batch['batchId'])
    assert result['state'] == 'cancelled'
    assert [i['state'] for i in result['items']] == ['cancelled', 'cancelled']
    assert _run(restarted, work[0]) == 0  # the worker sees the cancellation and renders nothing
    assert restarted.get_batch('tenant', batch['batchId'])['state'] == 'cancelled'
    restarted.executor.shutdown()
    restarted.ai_executor.shutdown()


def test_startup_recovery_via_api_without_resend(setup, tmp_path):
    _, store, _ = setup
    older = store.start_matrix_batch('tenant-a', {'aiEngine': 'off'})
    newer = store.start_matrix_batch('tenant-b', {'aiEngine': 'off'})
    restarted, work = _restart(store.platform)
    app = FastAPI()
    with patch('fox3d.ecommerce_scene_api.EcommerceSceneStore', return_value=restarted):
        app.include_router(ecommerce_scene_router(lambda: store.platform))
        with TestClient(app) as client:
            # The first request of any kind creates the store, which schedules every unclaimed batch, oldest first.
            assert client.get('/api/ecommerce-scenes/batches/missing').status_code == 404
            assert [args[2]['batchId'] for _, args in work] == [older['batchId'], newer['batchId']]
            assert client.get('/api/ecommerce-scenes/batches/' + newer['batchId'],
                              headers={'X-Tenant-Id': 'tenant-b'}).json()['state'] == 'running'
            assert len(work) == 2
            assert _run(restarted, work[1]) == 1
            assert client.get('/api/ecommerce-scenes/batches/' + newer['batchId'],
                              headers={'X-Tenant-Id': 'tenant-b'}).json()['state'] == 'completed'
    restarted.executor.shutdown()
    restarted.ai_executor.shutdown()


def test_startup_recovery_skips_foreign_or_incomplete_batches(setup):
    _, store, _ = setup
    moved = store.start_matrix_batch('tenant-a', {'aiEngine': 'off'})
    broken = store.start_matrix_batch('tenant-a', {'aiEngine': 'off'})
    bdir = store._tenant_dir('tenant-a') / 'batches'
    doc = json.loads((bdir / moved['batchId'] / 'batch.json').read_text(encoding='utf-8'))
    doc['tenantId'] = 'tenant-b'  # claims another tenant than the directory it lives in
    (bdir / moved['batchId'] / 'batch.json').write_text(json.dumps(doc), encoding='utf-8')
    doc = json.loads((bdir / broken['batchId'] / 'batch.json').read_text(encoding='utf-8'))
    del doc['workerArgs']
    (bdir / broken['batchId'] / 'batch.json').write_text(json.dumps(doc), encoding='utf-8')
    restarted, work = _restart(store.platform)
    assert restarted.recover_pending_batches() == 0
    with pytest.raises(KeyError):
        restarted.get_batch('tenant-b', moved['batchId'])
    restarted.get_batch('tenant-a', moved['batchId'])
    assert not work
    # A pending batch without worker arguments cannot run; it ages out like any orphaned batch instead of hanging.
    old = time.time() - 10_000
    os.utime(bdir / broken['batchId'] / 'batch.json', (old, old))
    assert restarted.get_batch('tenant-a', broken['batchId'])['state'] == 'interrupted'
    assert not work
    restarted.executor.shutdown()
    restarted.ai_executor.shutdown()
