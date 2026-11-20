from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from typing import Any

from fastapi.testclient import TestClient

from fox3d.api import create_app


def test_release_flow_tenant_idempotence_and_tamper(platform: Any) -> None:
    client = TestClient(create_app(platform))
    h = {'X-Tenant-Id': 'tenant-a'}
    other = {'X-Tenant-Id': 'tenant-b'}
    product = platform.kd.build_sku(tenant_id='tenant-a', kind='OPEN_SHELF')
    body = {'productId': product['productId'], 'idempotencyKey': 'one', 'actor': 'alice'}
    created = client.post('/api/pilot/releases', headers=h, json=body)
    assert created.status_code == 200, created.text
    rec = created.json()
    rid = rec['releaseId']
    base = '/api/pilot/releases/' + rid
    assert client.post('/api/pilot/releases', headers=h, json=body).json()['releaseId'] == rid
    assert client.post('/api/pilot/releases', headers=other, json=body).status_code == 404
    for path in (base, base + '/packet', base + '/verify', base + '/diff/' + rid):
        assert client.get(path, headers=other).status_code == 404
        assert client.get(path.replace(rid, 'unknown'), headers=h).status_code == 404
    for action in ('validate', 'submit', 'approve', 'release-manual', 'cancel'):
        assert client.post(base + '/' + action, headers=other, json={'confirm': True, 'expectedReleaseHash': 'x'}).status_code == 404
    assert client.get('/api/pilot/releases', headers=other).json()['total'] == 0
    assert client.get('/api/pilot/releases?status=DRAFT&limit=1', headers=h).json()['total'] == 1
    for action in ('validate', 'submit'):
        response = client.post(base + '/' + action, headers=h, json={'actor': 'alice'})
        assert response.status_code == 200, response.text
    before = client.get(base, headers=h).json()
    packet = client.get(base + '/packet', headers=h).json()
    assert json.loads(packet['release_manifest.json'])['releaseHash'] == before['releaseHash']
    assert client.post(base + '/approve', headers=h, json={'confirm': True, 'expectedReleaseHash': 'bad'}).status_code == 409
    after = client.get(base, headers=h).json()
    assert (after['status'], after['approvedBy'], after.get('approvedAt')) == (before['status'], before['approvedBy'], before.get('approvedAt'))
    assert client.post(base + '/approve', headers=h, json={'confirm': False, 'expectedReleaseHash': before['releaseHash']}).status_code == 403
    approval = {'confirm': True, 'expectedReleaseHash': before['releaseHash'], 'actor': 'alice'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(base + '/approve', headers=h, json=approval), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json()['approvedAt'] == responses[1].json()['approvedAt']
    assert client.post(base + '/release-manual', headers=h, json={'actor': 'alice'}).json()['status'] == 'RELEASED_FOR_MANUAL_EXECUTION'
    assert client.get(base + '/verify', headers=h).json()['verification'] == 'VALID'
    platform.pilot.releases.tamper(rid, 'bom.csv', 'tampered')
    assert client.get(base + '/verify', headers=h).json()['verification'] == 'TAMPERED'
    assert client.get(base + '/diff/' + rid, headers=h).json()['changed'] == {}
    payload: Any
    for payload in ([], None, {'productId': []}, {'productId': product['productId'], 'idempotencyKey': []}):
        assert client.post('/api/pilot/releases', headers=h, json=payload).status_code == 422
    assert client.post(base + '/approve', headers=h, json={'confirm': [], 'expectedReleaseHash': 'x'}).status_code == 422


def test_cancel_and_cross_tenant_diff(platform: Any) -> None:
    client = TestClient(create_app(platform))
    ids = []
    for tenant in ('a', 'b'):
        p = platform.kd.build_sku(tenant_id=tenant, kind='OPEN_SHELF')
        response = client.post('/api/pilot/releases', headers={'X-Tenant-Id': tenant}, json={'productId': p['productId'], 'idempotencyKey': 'key'})
        ids.append(response.json()['releaseId'])
    h = {'X-Tenant-Id': 'a'}
    assert client.get(f'/api/pilot/releases/{ids[0]}/diff/{ids[1]}', headers=h).status_code == 404
    path = f'/api/pilot/releases/{ids[0]}/cancel'
    assert client.post(path, headers=h, json={}).json()['status'] == 'CANCELLED'
    assert client.post(path, headers=h, json={}).json()['status'] == 'CANCELLED'
    assert client.post(f'/api/pilot/releases/{ids[0]}/validate', headers=h, json={}).status_code == 409
