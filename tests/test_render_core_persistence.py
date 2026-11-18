from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform


def test_restart_and_tenant_isolation(tmp_path):
    first = Platform(tmp_path, mock_blender=True)
    client = TestClient(create_app(first))
    owner = {"X-Tenant-Id": "owner"}
    other = {"X-Tenant-Id": "other"}
    job = client.post('/api/3d/jobs', headers=owner, json={'jobType': 'BLENDER_PREVIEW'}).json()
    twin = client.post('/api/digital-twins', headers=owner, json={'sku': 'SKU-1'}).json()
    product = client.post('/api/parametric/products', headers=owner, json={}).json()
    assert 'spec' in product
    second = Platform(tmp_path, mock_blender=True)
    client = TestClient(create_app(second))
    assert client.get('/api/3d/jobs/' + job['jobId'], headers=owner).status_code == 200
    assert len(client.get('/api/3d/jobs', headers=owner).json()['items']) == 1
    assert client.get('/api/digital-twins/' + twin['twinId'], headers=owner).status_code == 200
    assert client.get('/api/assets/' + twin['damAssetId'], headers=owner).status_code == 200
    assert client.get('/api/parametric/products', headers=owner).json()['items'][0]['spec'] == product['spec']
    for path in ('/api/3d/jobs', '/api/digital-twins', '/api/parametric/products'):
        assert client.get(path, headers=other).json()['items'] == []
    for path in ('/api/3d/jobs/' + job['jobId'], '/api/digital-twins/' + twin['twinId'], '/api/assets/' + twin['damAssetId']):
        assert client.get(path, headers=other).status_code == 404


def test_missing_or_changed_asset_is_unavailable_after_restart(tmp_path):
    first = Platform(tmp_path, mock_blender=True)
    a = first.dam.put(tenant_id='owner', kind='test', name='a', data=b'original')
    b = first.dam.put(tenant_id='owner', kind='test', name='b', data=b'original')
    from pathlib import Path
    Path(a.path).write_bytes(b'changed')
    Path(b.path).unlink()
    client = TestClient(create_app(Platform(tmp_path, mock_blender=True)))
    for asset in (a, b):
        assert client.get('/api/assets/' + asset.asset_id, headers={'X-Tenant-Id': 'owner'}).status_code == 404


def test_idempotency_concurrency_restart_and_conflict(tmp_path):
    client = TestClient(create_app(Platform(tmp_path, mock_blender=True)))
    owner = {'X-Tenant-Id': 'owner'}
    body = {'jobType': 'BLENDER_PREVIEW', 'idempotencyKey': 'one'}
    def send(_):
        return client.post('/api/3d/jobs', headers=owner, json=body)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send, range(8)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()['jobId'] for r in responses}) == 1
    client = TestClient(create_app(Platform(tmp_path, mock_blender=True)))
    assert client.post('/api/3d/jobs', headers=owner, json=body).json()['jobId'] == responses[0].json()['jobId']
    assert client.post('/api/3d/jobs', headers=owner, json={**body, 'scene': 'other'}).status_code == 409
    assert len(client.get('/api/3d/jobs', headers=owner).json()['items']) == 1
    assert client.post('/api/3d/jobs', headers={'X-Tenant-Id': 'other'}, json=body).json()['jobId'] != responses[0].json()['jobId']


def test_invalid_sku(tmp_path):
    client = TestClient(create_app(Platform(tmp_path, mock_blender=True)))
    for sku in ('x' * 5000, 'a/b', 'a\\b', '', None, '界' * 128, 'a\x00b'):
        assert client.post('/api/digital-twins', headers={'X-Tenant-Id': 'owner'}, json={'sku': sku}).status_code == 422


def test_concurrent_platforms_and_cancel_survive_restart(tmp_path):
    clients = [TestClient(create_app(Platform(tmp_path, mock_blender=True))) for _ in range(2)]
    headers = {'X-Tenant-Id': 'owner'}
    body = {'jobType': 'BLENDER_PREVIEW', 'idempotencyKey': 'shared'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda c: c.post('/api/3d/jobs', headers=headers, json=body), clients))
    assert all(r.status_code == 200 for r in responses)
    job_id = responses[0].json()['jobId']
    assert responses[1].json()['jobId'] == job_id
    assert clients[0].post('/api/3d/jobs/' + job_id + '/cancel', headers=headers).status_code == 200
    restarted = TestClient(create_app(Platform(tmp_path, mock_blender=True)))
    assert restarted.get('/api/3d/jobs/' + job_id, headers=headers).json()['status'] == 'cancelled'
    assert len(restarted.get('/api/3d/jobs', headers=headers).json()['items']) == 1


def test_executed_job_result_survives_restart(tmp_path):
    platform = Platform(tmp_path, mock_blender=True)
    job = platform.submit_job({'tenantId': 'owner', 'jobType': 'BLENDER_PREVIEW'})
    done = platform.execute_job(job)
    assert done['status'] == 'succeeded'
    assert done['outputAsset']
    restored = Platform(tmp_path, mock_blender=True).get_job(job['jobId'], tenant_id='owner')
    assert restored['status'] == done['status']
    assert restored['outputAsset'] == done['outputAsset']
    assert restored['output'] == done['output']


STALE_BEAT = '2000-01-01T00:00:00+00:00'


def _stale_in_flight_job(tmp_path, key, status):
    """Persist a claimed job stuck in ``status`` whose worker stopped beating."""
    platform = Platform(tmp_path, mock_blender=True)
    job = platform.submit_job({'tenantId': 'owner', 'jobType': 'BLENDER_PREVIEW', 'idempotencyKey': key})
    assert platform.queue.claim('worker')['jobId'] == job['jobId']
    platform.queue.set_status(job['jobId'], 'running', heartbeatAt=STALE_BEAT)
    if status == 'uploading':
        platform.queue.set_status(job['jobId'], 'uploading', heartbeatAt=STALE_BEAT)
    else:
        assert platform.cancel_job(job['jobId'], tenant_id='owner')['status'] == 'cancel_requested'
    assert platform.get_job(job['jobId'], tenant_id='owner')['status'] == status
    return job


def test_stale_uploading_job_is_claimable_again_after_restart(tmp_path):
    job = _stale_in_flight_job(tmp_path, 'upload-key', 'uploading')
    restarted = Platform(tmp_path, mock_blender=True)
    assert restarted.worker_offline_recovery() == [job['jobId']]
    recovered = restarted.get_job(job['jobId'], tenant_id='owner')
    assert recovered['status'] == 'retry_scheduled'
    assert recovered['attemptCount'] == 1
    assert recovered['leaseOwner'] is None
    resent = restarted.submit_job({'tenantId': 'owner', 'jobType': 'BLENDER_PREVIEW', 'idempotencyKey': 'upload-key'})
    assert resent['jobId'] == job['jobId']
    assert resent['status'] == 'retry_scheduled'
    # The recovered state is durable, and the job can be leased again.
    again = Platform(tmp_path, mock_blender=True)
    assert again.get_job(job['jobId'], tenant_id='owner')['status'] == 'retry_scheduled'
    claimed = again.queue.claim('worker-2')
    assert claimed is not None and claimed['jobId'] == job['jobId']
    assert claimed['status'] == 'reserved'


def test_stale_uploading_job_fails_when_attempts_are_used_up(tmp_path):
    job = _stale_in_flight_job(tmp_path, 'upload-exhausted', 'uploading')
    first = Platform(tmp_path, mock_blender=True)
    first.queue.get(job['jobId'])['attemptCount'] = 2
    assert first.worker_offline_recovery() == []
    assert Platform(tmp_path, mock_blender=True).get_job(job['jobId'], tenant_id='owner')['status'] == 'failed'


def test_fresh_uploading_job_is_not_recovered(tmp_path):
    platform = Platform(tmp_path, mock_blender=True)
    job = platform.submit_job({'tenantId': 'owner', 'jobType': 'BLENDER_PREVIEW'})
    platform.queue.claim('worker')
    platform.queue.set_status(job['jobId'], 'running')
    platform.queue.heartbeat(job['jobId'])
    platform.queue.set_status(job['jobId'], 'uploading')
    assert platform.worker_offline_recovery() == []
    assert platform.get_job(job['jobId'], tenant_id='owner')['status'] == 'uploading'


def test_stale_cancel_requested_job_is_cancelled_after_restart(tmp_path):
    job = _stale_in_flight_job(tmp_path, 'cancel-key', 'cancel_requested')
    restarted = Platform(tmp_path, mock_blender=True)
    assert restarted.worker_offline_recovery() == []
    assert restarted.get_job(job['jobId'], tenant_id='owner')['status'] == 'cancelled'
    resent = restarted.submit_job({'tenantId': 'owner', 'jobType': 'BLENDER_PREVIEW', 'idempotencyKey': 'cancel-key'})
    assert resent['jobId'] == job['jobId']
    assert resent['status'] == 'cancelled'
    assert Platform(tmp_path, mock_blender=True).get_job(job['jobId'], tenant_id='owner')['status'] == 'cancelled'


def _twin_fields(twin):
    return {k: twin[k] for k in ('glb', 'previewAssetId', 'previewPath')}


def test_product_e2e_twin_preview_survives_restart(tmp_path):
    platform = Platform(tmp_path, mock_blender=True)
    out = platform.product_e2e(tenant_id='owner', sku='SKU-1', glb_bytes=b'glb-bytes')
    assert out['twin']['previewAssetId']
    assert out['twin']['previewPath']
    restored = Platform(tmp_path, mock_blender=True).get_twin(out['twin']['twinId'], tenant_id='owner')
    assert _twin_fields(restored) == _twin_fields(out['twin'])


def test_product_e2e_glb_path_override_survives_restart(tmp_path):
    platform = Platform(tmp_path, mock_blender=True)
    source = platform.create_twin({'tenantId': 'owner', 'sku': 'SKU-SRC'})
    out = platform.product_e2e(tenant_id='owner', sku='SKU-SRC', glb_path=source['glb'])
    assert out['twin']['glb'] == source['glb']
    assert out['twin']['previewAssetId']
    restored = Platform(tmp_path, mock_blender=True).get_twin(out['twin']['twinId'], tenant_id='owner')
    assert restored['glb'] == source['glb']
    assert _twin_fields(restored) == _twin_fields(out['twin'])


def test_packaging_twin_preview_survives_restart(tmp_path):
    platform = Platform(tmp_path, mock_blender=True)
    out = platform.packaging_twin(tenant_id='owner', template='BOX', sku='BOX-01')
    assert out['twin']['previewAssetId']
    restored = Platform(tmp_path, mock_blender=True).get_twin(out['twin']['twinId'], tenant_id='owner')
    assert _twin_fields(restored) == _twin_fields(out['twin'])


def test_twin_update_rejects_identity_and_foreign_tenant(tmp_path):
    import pytest
    from fox3d.twin import ProductDigitalTwin
    platform = Platform(tmp_path, mock_blender=True)
    twin = platform.twins.create(ProductDigitalTwin(tenantId='owner', sku='SKU-1'))
    with pytest.raises(ValueError):
        platform.twins.update(twin, tenantId='other')
    with pytest.raises(ValueError):
        platform.twins.update(twin, notAField=1)
    impostor = twin.model_copy(update={'tenantId': 'other'})
    with pytest.raises(KeyError):
        platform.twins.update(impostor, previewAssetId='x')
    assert platform.twins.get(twin.twinId, tenant_id='owner').previewAssetId is None


def test_upload_rejects_overlong_safe_sku_with_422(tmp_path):
    client = TestClient(create_app(Platform(tmp_path, mock_blender=True)))
    headers = {'X-Tenant-Id': 'owner'}
    for sku in ('U' * 300, 'U' * 129, '界' * 67, 'a/' * 65):
        response = client.post('/api/digital-twins/upload', headers=headers,
                               data={'sku': sku}, files={'file': ('m.glb', b'glb')})
        assert response.status_code == 422, sku
    assert client.get('/api/digital-twins', headers=headers).json()['items'] == []
    ok = client.post('/api/digital-twins/upload', headers=headers,
                     data={'sku': '界' * 66}, files={'file': ('m.glb', b'glb')})
    assert ok.status_code == 200
    assert ok.json()['twin']['sku'] == '界' * 66
    # Upload keeps encoding path separators instead of rejecting them.
    slashed = client.post('/api/digital-twins/upload', headers=headers,
                          data={'sku': 'a/' * 64}, files={'file': ('m.glb', b'glb')})
    assert slashed.status_code == 200


def test_product_e2e_overlong_safe_sku_writes_short_filename(tmp_path):
    from pathlib import Path
    platform = Platform(tmp_path, mock_blender=True)
    out = platform.product_e2e(tenant_id='owner', sku='U' * 300, glb_bytes=b'glb')
    name = Path(out['twin']['glb']).name
    assert len(name.encode('utf-8')) <= 255
    assert '_enc~=' in name
    restored = Platform(tmp_path, mock_blender=True).get_twin(out['twin']['twinId'], tenant_id='owner')
    assert restored['sku'] == 'U' * 300
