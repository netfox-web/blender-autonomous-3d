"""Revision list, restore, listing resilience, and create idempotency for product models and recipe drafts."""
from __future__ import annotations

import concurrent.futures
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d import product_models as models
from fox3d.ids import new_id, stable_hash
from fox3d.product_models_api import product_models_router
from fox3d.recipe_admin_api import recipe_router
from fox3d import recipe_3d as render
from fox3d.recipe_workbench import RecipeWorkbench

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
    other = recipe_client.get(f"{url}/revisions", headers={"X-Tenant-Id": "other"})
    assert other.status_code == 200
    assert other.json()["total"] == 0


def test_product_model_listing_pagination_total(tmp_path):
    for i in range(205):
        models.save(tmp_path, "t", {**cabinet(), "name": f"Cabinet {i:03d}"}, 0)
    first = models.listing(tmp_path, "t", offset=0, limit=200)
    second = models.listing(tmp_path, "t", offset=200, limit=200)
    assert first["total"] == 205
    assert len(first["items"]) == 200
    assert len(second["items"]) == 5


def test_product_model_listing_pagination_ids_unique_over_201(tmp_path):
    for i in range(201):
        models.save(tmp_path, "t", {**cabinet(), "name": f"Cabinet {i:03d}"}, 0)
    collected: list[str] = []
    page_offset = 0
    total = 1
    while page_offset < total:
        page = models.listing(tmp_path, "t", offset=page_offset, limit=200)
        collected.extend(row["id"] for row in page["items"])
        total = page["total"]
        page_offset += len(page["items"])
        assert page["items"] or page_offset >= total
    assert len(collected) == 201
    assert len(set(collected)) == 201


def test_product_model_revision_list_beyond_default_page(tmp_path):
    item = _save_versions(tmp_path, 1)
    for rev in range(1, 41):
        item = models.save(tmp_path, "t", {**item["draft"], "notes": f"n{rev}"}, rev, item["id"])
    head = models.list_revisions(tmp_path, "t", item["id"], offset=0, limit=40)
    tail = models.list_revisions(tmp_path, "t", item["id"], offset=40, limit=40)
    assert head["total"] == 41
    assert len(head["items"]) == 40
    assert len(tail["items"]) == 1
    assert tail["items"][0]["revision"] == 41


def test_create_idempotency_resumes_after_incomplete_record(tmp_path):
    draft = cabinet()
    payload_hash = render.input_hash(draft)
    key = "resume-create"
    store = models._idempotency_dir(tmp_path, "t")
    store.mkdir(parents=True, exist_ok=True)
    record_path = store / stable_hash(key)
    mid = new_id()
    render.atomic_json(record_path, {"id": mid, "inputHash": payload_hash, "key": key, "complete": False})
    models.save(tmp_path, "t", draft, 0, mid)
    resumed = models.create(tmp_path, "t", draft, 0, idempotency_key=key)
    assert resumed["id"] == mid
    again = models.create(tmp_path, "t", draft, 0, idempotency_key=key)
    assert again["id"] == mid
    record = render.read_json(record_path)
    assert record.get("complete") is True


def test_recipe_supplier_reference_empty_revision_list(recipe_client):
    response = recipe_client.get(
        "/api/recipe-library/products/LI-D40/revisions",
        headers=RECIPE_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_product_model_revision_diff_fields_only_save(tmp_path):
    item = models.save(
        tmp_path,
        "t",
        {**cabinet(), "variants": [{"sku": "SKU-A", "artworkAssetId": "", "note": ""}]},
        0,
    )
    item = models.save(
        tmp_path,
        "t",
        {**item["draft"], "variants": [{"sku": "SKU-B", "artworkAssetId": "", "note": ""}]},
        1,
        item["id"],
    )
    first = models.get_revision(tmp_path, "t", item["id"], 1)
    current = models.get(tmp_path, "t", item["id"])
    assert first["draft"]["variants"] != current["draft"]["variants"]


def test_product_model_revision_list_omits_corrupt_snapshots(tmp_path, model_client):
    item = _save_versions(tmp_path, 3)
    rev_dir = models.directory(tmp_path, "t") / item["id"] / "revisions"
    (rev_dir / "2.json").write_text("{broken", encoding="utf-8")
    body = models.list_revisions(tmp_path, "t", item["id"], offset=0, limit=40)
    assert body["total"] == 2
    assert body["skipped"] == 1
    assert [row["revision"] for row in body["items"]] == [1, 3]
    response = model_client.get(f"/api/product-models/{item['id']}/revisions", headers=HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 2


def test_product_model_revision_list_skips_non_object_json_outside_page(tmp_path, model_client):
    item = models.save(tmp_path, "t", cabinet(), 0)
    rev_dir = models.directory(tmp_path, "t") / item["id"] / "revisions"
    (rev_dir / "999.json").write_text("[1]", encoding="utf-8")
    body = models.list_revisions(tmp_path, "t", item["id"], offset=0, limit=1)
    assert body["total"] == 1
    assert body["skipped"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["revision"] == 1
    response = model_client.get(
        f"/api/product-models/{item['id']}/revisions?offset=0&limit=1",
        headers=HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["skipped"] == 1
    assert payload["items"][0]["revision"] == 1


def test_product_model_listing_template_state_only_for_page(tmp_path, monkeypatch):
    calls: list[str] = []

    def track(_root, _tid, item):
        calls.append(item["id"])
        return "DRAFT"

    monkeypatch.setattr(models, "_template_state", track)
    ids = []
    for i in range(5):
        row = models.save(tmp_path, "t", {**cabinet(), "name": f"Cabinet {i}"}, 0)
        ids.append(row["id"])
    models.listing(tmp_path, "t", offset=0, limit=2)
    models.listing(tmp_path, "t", offset=2, limit=2)
    assert len(calls) == 4
    assert set(calls).issubset(set(ids))


def test_recipe_revision_list_reads_payload_only_for_one_page(recipe_client, tmp_path, monkeypatch):
    sku = "LI-D40"
    url = f"/api/recipe-library/products/{sku}"
    base = recipe_client.get(url, headers=RECIPE_HEADERS).json()
    draft = base["draft"]
    revision = base["revision"]
    for i in range(12):
        draft = {**draft, "notes": f"note-{i}"}
        saved = recipe_client.put(
            url, headers=RECIPE_HEADERS, json={"expectedRevision": revision, "draft": draft}
        )
        assert saved.status_code == 200, saved.text
        revision = saved.json()["revision"]
    loads: list[str] = []
    real_loads = json.loads

    def counting_loads(text):
        loads.append(text)
        return real_loads(text)

    monkeypatch.setattr("fox3d.recipe_workbench.json.loads", counting_loads)
    store = RecipeWorkbench(tmp_path)
    listed = store.list_revisions(RECIPE_HEADERS["X-Tenant-Id"], sku, offset=0, limit=5)
    assert listed["total"] == 12
    assert len(listed["items"]) == 5
    assert len(loads) == 5