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
