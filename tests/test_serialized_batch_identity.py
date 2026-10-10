"""MOCK regression: JSON type substitutions must not preserve persisted identity."""
import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from test_model_batches import completed_batch, setup
from fox3d import model_batches as b, model_compositions as c
from fox3d.ids import new_id, sha256_bytes
from fox3d.product_models_api import product_models_router
from fox3d.recipe_3d import atomic_json, read_json


def replace(value, path, kind):
    for key in path[:-1]:
        value = value[key]
    original = value[path[-1]]
    assert type(original) is int
    value[path[-1]] = {'bool': bool(original), 'float': float(original), 'string': str(original)}[kind]


REQUEST_FIELDS = [('identityVersion',), ('sourceRevision',), ('draft', 'batchVersion'),
                  ('draft', 'masterRevision'), ('draft', 'selections', 0, 'masterRevision')]


@pytest.mark.parametrize('field', REQUEST_FIELDS)
@pytest.mark.parametrize('kind', ['bool', 'float', 'string'])
def test_request_serialized_integer_identity(tmp_path, field, kind):
    model, asset, batch = setup(tmp_path)
    bid = new_id()
    request = {'identityVersion': 1, 'tenantId': 't', 'masterId': model['id'],
               'batchId': bid, 'sourceRevision': 1, 'draft': b.snapshot(tmp_path, 't', model, batch)}
    expected = b._identity(request, 't', model['id'], bid)
    changed = copy.deepcopy(request)
    replace(changed, field, kind)
    with pytest.raises(ValueError):
        b._identity(changed, 't', model['id'], bid)
    assert b._identity(request, 't', model['id'], bid) == expected


@pytest.mark.parametrize('boundary,field', [('request', f) for f in REQUEST_FIELDS] + [
    ('service', ('batchVersion',)), ('receipt0', ('row', 'index')), ('receipt1', ('row', 'index'))])
@pytest.mark.parametrize('kind', ['bool', 'float', 'string'])
def test_persisted_serialized_integer_current_api(tmp_path, completed_batch, boundary, field, kind):
    model, asset, draft, bid, folder = completed_batch
    anchor = folder / 'batches' / bid
    file = {'request': anchor/'request.json', 'service': folder/'state.json',
            'receipt0': anchor/'0.json', 'receipt1': anchor/'1.json'}[boundary]
    raw = file.read_bytes()
    value = read_json(file)
    replace(value, field, kind)
    app = FastAPI()
    app.include_router(product_models_router(lambda: SimpleNamespace(root=tmp_path, mock_blender=True)))
    with TestClient(app) as client:
        url = f'/api/product-models/{model["id"]}/composition'
        try:
            atomic_json(file, value)
            with pytest.raises(ValueError):
                b.current(tmp_path, 't', model['id'], bid, 'succeeded')
            assert client.get(url, headers={'X-Tenant-Id': 't'}).status_code == 422
        finally:
            file.write_bytes(raw)
        assert b.current(tmp_path, 't', model['id'], bid, 'succeeded')['available']
        restored = client.get(url, headers={'X-Tenant-Id': 't'})
        assert restored.status_code == 200 and restored.json()['batch']['available']
        assert not restored.json()['batch']['manufacturingReady']


@pytest.mark.parametrize('field', [('historyVersion',), ('sourceRevision',), ('draft', 'masterRevision')])
@pytest.mark.parametrize('kind', ['bool', 'float', 'string'])
def test_manifest_serialized_integer_with_resealed_publication(tmp_path, completed_batch, field, kind):
    model, asset, draft, bid, folder = completed_batch
    row = read_json(folder/'batches'/(bid+'.json'))['rows'][0]
    target = folder/'generations'/row['generationId']
    files = [target/'manifest.json', target/'published.json']
    original = {f: f.read_bytes() for f in files}
    manifest = read_json(files[0])
    replace(manifest, field, kind)
    app = FastAPI()
    app.include_router(product_models_router(lambda: SimpleNamespace(root=tmp_path, mock_blender=True)))
    with TestClient(app) as client:
        url = f'/api/product-models/{model["id"]}/composition'
        params = {'workspace': 't', 'generation': row['generationId']}
        try:
            atomic_json(files[0], manifest)
            atomic_json(files[1], {'manifestSha256': sha256_bytes(files[0].read_bytes())})
            with pytest.raises(ValueError):
                b._published(tmp_path, 't', model['id'], row, draft['selections'][0], 1, model)
            with pytest.raises(ValueError):
                c.generation(tmp_path, 't', model['id'], row['generationId'], model)
            response = client.get(url, headers={'X-Tenant-Id': 't'})
            assert response.status_code == 200
            assert response.json()['state'] == 'failed' and not response.json()['batch']['visualAssetReady']
            assert client.get(url+'/files/beauty.png', params=params).status_code == 409
        finally:
            for file, raw in original.items():
                file.write_bytes(raw)
        assert b.current(tmp_path, 't', model['id'], bid, 'succeeded')['available']
        assert client.get(url+'/files/beauty.png', params=params).status_code == 200


def test_authority_publication_cannot_drop_history_version(tmp_path, completed_batch):
    model, asset, draft, bid, folder = completed_batch
    row = read_json(folder/'batches'/(bid+'.json'))['rows'][0]
    target = folder/'generations'/row['generationId']
    manifest = read_json(target/'manifest.json')
    manifest.pop('historyVersion')
    atomic_json(target/'manifest.json', manifest)
    atomic_json(target/'published.json', {'manifestSha256': sha256_bytes((target/'manifest.json').read_bytes())})
    with pytest.raises(ValueError):
        c.generation(tmp_path, 't', model['id'], row['generationId'], model)


@pytest.mark.parametrize('version', [True, False, 1.0, '1'])
@pytest.mark.parametrize('state', ['queued', 'running'])
def test_pending_batch_service_type_without_request(tmp_path, version, state):
    model, asset, batch = setup(tmp_path)
    folder = c.folder_for(tmp_path, 't', model['id'])
    bid = new_id()
    atomic_json(folder/'state.json', {'taskId': bid, 'state': state, 'batchVersion': version})
    with pytest.raises(ValueError):
        b.current(tmp_path, 't', model['id'], bid, state)


@pytest.mark.parametrize('state', ['queued', 'running'])
def test_pending_exact_batch_can_wait_for_request(tmp_path, state):
    model, asset, batch = setup(tmp_path)
    folder = c.folder_for(tmp_path, 't', model['id'])
    bid = new_id()
    atomic_json(folder/'state.json', {'taskId': bid, 'state': state, 'batchVersion': 1})
    assert b.current(tmp_path, 't', model['id'], bid, state) is None
