from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d import model_categories as categories, product_models as models
from fox3d.product_models_api import product_models_router
from fox3d.recipe_workbench import DraftConflict


def test_metadata_changes_preserve_geometry_revision_and_source(tmp_path):
    item = models.save(tmp_path, 't', {'name': 'Mat fixture', 'family': 'mat', 'geometry': 'RECTANGLE',
        'widthMm': 100., 'depthMm': 5., 'heightMm': 100.,
        'dimensionEvidence': 'Synthetic fixture', 'structureEvidence': 'Synthetic flat rectangle'}, 0)
    path = models.directory(tmp_path, 't') / item['id'] / 'master.json'
    before = path.read_bytes()
    spec = models.build_spec(item['draft'])
    result = categories.save(tmp_path, 't', item['id'], 'wash_mat', 0)
    assert result['source'] == 'OPERATOR' and result['revision'] == 1
    assert path.read_bytes() == before
    restored = models.get(tmp_path, 't', item['id'])
    assert restored['revision'] == item['revision'] and restored['inputHash'] == item['inputHash']
    assert models.build_spec(restored['draft']) == spec
    assert categories.inventory(tmp_path, 't')['items'][0]['classification']['categoryId'] == 'wash_mat'
    with pytest.raises(DraftConflict):
        categories.save(tmp_path, 't', item['id'], 'floor_mat', 0)
    categories.save(tmp_path, 't', item['id'], 'floor_mat', 1)
    assert (path.parent / 'classification-revisions' / '1.json').is_file()


def test_inference_uses_model_fields_not_names_or_artwork():
    assert categories.inferred({'name': '5層旋轉木櫃', 'family': 'coaster'}) == 'coaster'
    assert categories.inferred({'family': 'cabinet', 'subtype': 'open', 'rows': 3}) == 'open_3'
    assert categories.inferred({'family': 'cabinet', 'subtype': 'hinged', 'rows': None}) == 'hinged_other'
    assert categories.inferred({'family': 'cabinet', 'rows': 4,
        'recipeReference': {'draft': {'family': 'STACKED_HINGED_CABINET'}}}) == 'hinged_4'
    assert categories.inferred({'family': 'cabinet', 'rows': 3,
        'recipeReference': {'draft': {'family': 'ROW_SLIDING_CABINET'}}}) == 'sliding'


def test_empty_category_catalog_does_not_create_models_or_geometry(tmp_path):
    inventory = categories.inventory(tmp_path, 't')
    assert inventory['items'] == []
    nodes = categories.flatten(inventory['categoryTree'])
    for key in ['floor_mat', 'coaster', 'wash_mat', 'bedside', 'rotating'] + [
        f'{kind}_{n}' for kind in ['open', 'hinged'] for n in range(2, 6)]:
        assert nodes[key]['draftDefaults']['geometry'] == 'PENDING'
        assert not any(k in nodes[key]['draftDefaults'] for k in ['widthMm', 'panelMm', 'depthMm'])
    assert models.listing(tmp_path, 't') == []


@pytest.mark.parametrize('invalid', ['wood', 'does_not_exist', '../outside', 'coaster'])
def test_invalid_parent_path_or_family_cannot_be_saved(tmp_path, invalid):
    item = models.save(tmp_path, 't', {'name': 'Mat', 'family': 'mat'}, 0)
    with pytest.raises(ValueError):
        categories.save(tmp_path, 't', item['id'], invalid, 0)
    assert categories.get(tmp_path, 't', item['id'])['revision'] == 0


def test_http_classification_tenant_revision_and_reload(tmp_path):
    app = FastAPI()
    app.include_router(product_models_router(lambda: SimpleNamespace(root=tmp_path)))
    with TestClient(app) as client:
        headers = {'X-Tenant-Id': 't'}
        item = client.post('/api/product-models', headers=headers,
            json={'draft': {'name': 'Mat', 'family': 'mat'}, 'expectedRevision': 0}).json()
        url = '/api/product-models/' + item['id'] + '/classification'
        assert client.get(url, headers={'X-Tenant-Id': 'other'}).status_code == 404
        assert client.put(url, headers=headers, json={'categoryId': 'wash_mat', 'expectedRevision': 0}).status_code == 200
        assert client.put(url, headers=headers, json={'categoryId': 'floor_mat', 'expectedRevision': 0}).status_code == 409
        assert client.put(url, headers=headers, json={'categoryId': 'wash_mat', 'expectedRevision': True}).status_code == 422
    with TestClient(app) as client:
        assert client.get(url, headers=headers).json()['categoryId'] == 'wash_mat'
        rows = client.get('/api/product-models', headers=headers).json()
        assert len(rows['items']) == 1 and rows['items'][0]['inputHash'] == item['inputHash']
        assert not rows['items'][0]['readiness']['previewReady']
