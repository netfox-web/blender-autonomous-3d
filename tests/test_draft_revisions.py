"""Revision list, restore, listing resilience, and create idempotency for product models and recipe drafts."""
from __future__ import annotations

import concurrent.futures
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d import product_models as models
from fox3d.product_models_api import product_models_router
from fox3d.recipe_admin_api import recipe_router

HEADERS = {"X-Tenant-Id": "t"}
RECIPE_HEADERS = {"X-Tenant-Id": "sonaqueen-home"}


def cabinet():
    return {
        "name": "TEST cabinet",
        "family": "cabinet",
        "subtype": "open",
        "geometry": "OPEN_CABINET",
        "widthMm": 424.0,
        "depthMm": 295.0,
        "heightMm": 900.0,
        "panelMm": 15.0,
        "backMm": 3.0,
        "rows": 3,
        "dimensionEvidence": "Synthetic engineering fixture, mm",
        "structureEvidence": "Single column, equal openings, inset back",
    }


@pytest.fixture
def model_client(tmp_path):
    app = FastAPI()
    app.include_router(product_models_router(lambda: SimpleNamespace(root=tmp_path, mock_blender=True)))
    return TestClient(app)


@pytest.fixture
def recipe_client(tmp_path):
    app = FastAPI()
    app.include_router(recipe_router(lambda: SimpleNamespace(root=tmp_path)))
    return TestClient(app)


def _save_versions(tmp_path, count=3):
    item = models.save(tmp_path, "t", cabinet(), 0)
    for rev in range(1, count):
        draft = {**item["draft"], "notes": f"v{rev + 1}"}
        item = models.save(tmp_path, "t", draft, rev, item["id"])
    return item


def test_product_model_three_revisions_listed(model_client, tmp_path):
    item = _save_versions(tmp_path, 3)
    response = model_client.get(f"/api/product-models/{item['id']}/revisions", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [row["revision"] for row in body["items"]] == [1, 2, 3]


def test_restore_first_revision_creates_fourth_matching_content(model_client, tmp_path):
    item = _save_versions(tmp_path, 3)
    first = models.get_revision(tmp_path, "t", item["id"], 1)
    response = model_client.post(
        f"/api/product-models/{item['id']}/revisions/1/restore",
        headers=HEADERS,
        json={"expectedRevision": item["revision"]},
    )
    assert response.status_code == 200, response.text
    restored = response.json()
    assert restored["revision"] == 4
    assert restored["draft"]["notes"] == first["draft"].get("notes", "")
    assert models.get_revision(tmp_path, "t", item["id"], 1)["draft"] == first["draft"]


def test_restore_expected_revision_mismatch_returns_409(model_client, tmp_path):
    item = _save_versions(tmp_path, 2)
    response = model_client.post(
        f"/api/product-models/{item['id']}/revisions/1/restore",
        headers=HEADERS,
        json={"expectedRevision": item["revision"] - 1},
    )
    assert response.status_code == 409


def test_product_model_revision_other_tenant_404(model_client, tmp_path):
    item = _save_versions(tmp_path, 1)
    url = f"/api/product-models/{item['id']}/revisions"
    assert model_client.get(url, headers={"X-Tenant-Id": "other"}).status_code == 404


def test_listing_skips_corrupt_master_and_reports_skipped(model_client, tmp_path):
    good = models.save(tmp_path, "t", cabinet(), 0)
    bad_dir = models.directory(tmp_path, "t") / "not-a-uuid"
    bad_dir.mkdir(parents=True)
    (bad_dir / "master.json").write_text("{broken", encoding="utf-8")
    corrupt = models.directory(tmp_path, "t") / good["id"] / "master.json"
    corrupt.write_text("{}", encoding="utf-8")
    response = model_client.get("/api/product-models", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["skipped"] >= 1
    assert all(row["id"] != good["id"] for row in body["items"]) or body["total"] == 0


def test_create_idempotency_same_key_and_concurrent_single_record(model_client, tmp_path):
    payload = {"expectedRevision": 0, "draft": cabinet(), "idempotencyKey": "create-once"}
    first = model_client.post("/api/product-models", headers=HEADERS, json=payload)
    second = model_client.post("/api/product-models", headers=HEADERS, json=payload)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    def attempt():
        client = model_client
        return client.post("/api/product-models", headers=HEADERS, json=payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: attempt(), range(4)))
    ids = {r.json()["id"] for r in results if r.status_code == 201}
    assert len(ids) == 1

    conflict = {**payload, "draft": {**cabinet(), "notes": "different body"}}
    assert model_client.post("/api/product-models", headers=HEADERS, json=conflict).status_code == 409


def test_invalid_revision_number_returns_404_or_422(model_client, tmp_path):
    item = models.save(tmp_path, "t", cabinet(), 0)
    mid = item["id"]
    assert model_client.get(f"/api/product-models/{mid}/revisions/99", headers=HEADERS).status_code == 404
    assert model_client.get(f"/api/product-models/{mid}/revisions/0", headers=HEADERS).status_code == 422


def test_recipe_revision_list_restore_and_tenant_isolation(recipe_client, tmp_path):
    sku = "LI-D40"
    url = f"/api/recipe-library/products/{sku}"
    base = recipe_client.get(url, headers=RECIPE_HEADERS).json()
    draft = base["draft"]
    draft["notes"] = "rev2"
    recipe_client.put(url, headers=RECIPE_HEADERS, json={"expectedRevision": 0, "draft": draft})
    draft["notes"] = "rev3"
    recipe_client.put(url, headers=RECIPE_HEADERS, json={"expectedRevision": 1, "draft": draft})
    listed = recipe_client.get(f"{url}/revisions", headers=RECIPE_HEADERS).json()
    assert listed["total"] == 2
    restore = recipe_client.post(
        f"{url}/revisions/1/restore",
        headers=RECIPE_HEADERS,
        json={"expectedRevision": 2},
    )
    assert restore.status_code == 200
    assert restore.json()["revision"] == 3
    assert recipe_client.get(f"{url}/revisions", headers={"X-Tenant-Id": "other"}).status_code == 404