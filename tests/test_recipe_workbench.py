"""Recipe admin CRUD and durable draft boundary tests (no Blender execution)."""
import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.recipe_admin_api import recipe_router
from fox3d.recipe_workbench import DEFAULT_CATALOG, RecipeWorkbench

HEADERS = {"X-Tenant-Id": "sonaqueen-home"}


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(recipe_router(lambda: SimpleNamespace(root=tmp_path)))
    with TestClient(app) as client:
        yield client


def create_payload(sku="NEW-001"):
    return {"expectedRevision": 0, "draft": {"sku": sku, "name": "新商品", "family": "STACKED_HINGED_CABINET",
            "pageUrl": "", "values": {"widthMm": {"value": 500, "evidence": "供應商圖面"}}, "notes": "待補資料"}}


def test_page_assets_and_seed_images(client):
    page = client.get("/admin/recipes")
    assert page.status_code == 200 and "商品 Recipe 庫" in page.text
    assert "frame-ancestors 'self'" in page.headers["content-security-policy"]
    for name, media in [("recipe-library.js", "javascript"), ("recipe-library.css", "text/css")]:
        response = client.get("/admin/recipes/assets/" + name)
        assert response.status_code == 200 and media in response.headers["content-type"]
    assert client.get("/admin/recipes/assets/other.py").status_code == 404
    data = client.get("/api/recipe-library", headers=HEADERS).json()
    assert len(data["items"]) == 3
    assert sum(len(i["validation"]["missingFields"]) for i in data["items"]) == 15
    assert all(i["renderReady"] is False and i["productionReady"] is False for i in data["items"])
    photo = client.get("/api/recipe-library/sources/LI-D40/dimensions")
    assert photo.status_code == 200 and photo.content.startswith(b"\xff\xd8\xff")
    assert client.get("/api/recipe-library/sources/LI-D40/page").status_code == 404


def test_create_edit_reload_and_immutable_seed(client, tmp_path):
    sku = "LI-D40"
    url = "/api/recipe-library/products/" + sku
    original_bytes = DEFAULT_CATALOG.read_bytes()
    old = client.get(url, headers=HEADERS).json()
    draft = copy.deepcopy(old["draft"])
    draft["values"]["panelThicknessMm"] = {"value": 12, "evidence": "待核對圖面，僅測試草稿"}
    response = client.put(url, headers=HEADERS, json={"expectedRevision": 0, "draft": draft})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] == 1 and "panelThicknessMm" not in saved["validation"]["missingFields"]
    assert saved["validation"]["changedFields"] == ["panelThicknessMm"]
    assert saved["originalReference"]["facts"] == old["originalReference"]["facts"]
    assert DEFAULT_CATALOG.read_bytes() == original_bytes
    reopened = RecipeWorkbench(tmp_path).get("sonaqueen-home", sku)
    assert reopened["draft"] == draft and reopened["revision"] == 1
    assert not reopened["engineeringReady"]
    conflict = client.put(url, headers=HEADERS, json={"expectedRevision": 0, "draft": draft})
    assert conflict.status_code == 409
    assert client.put(url, headers=HEADERS, json={"expectedRevision": 1, "draft": draft}).json()["revision"] == 2
    with RecipeWorkbench(tmp_path).connection() as con:
        assert con.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == 2


def test_new_incomplete_product_and_cross_tenant_isolation(client):
    created = client.post("/api/recipe-library/products", headers=HEADERS, json=create_payload())
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["revision"] == 1 and item["validation"]["missingFields"]
    assert not item["validation"]["sourceIntegrityVerified"]
    other = {"X-Tenant-Id": "other"}
    assert client.get("/api/recipe-library/products/NEW-001", headers=other).status_code == 404
    assert len(client.get("/api/recipe-library", headers=other).json()["items"]) == 3
    assert client.post("/api/recipe-library/products", headers=HEADERS, json=create_payload()).status_code == 409
    assert client.post("/api/recipe-library/products", headers=HEADERS, json=create_payload("LI-D40")).status_code == 409
    assert client.post("/api/recipe-library/products", headers=other, json=create_payload()).status_code == 201


@pytest.mark.parametrize("headers", [{}, {"X-Tenant-Id": "system"}, {"X-Tenant-Id": " x "}])
def test_workspace_header_required(client, headers):
    assert client.get("/api/recipe-library", headers=headers).status_code == 400


@pytest.mark.parametrize("value", [-1, 0, True, "500", "Infinity"])
def test_invalid_measurement_is_not_saved(client, value):
    payload = create_payload()
    payload["draft"]["values"]["widthMm"]["value"] = value
    assert client.post("/api/recipe-library/products", headers=HEADERS, json=payload).status_code == 422
    assert client.get("/api/recipe-library/products/NEW-001", headers=HEADERS).status_code == 404


def test_validation_detects_structure_and_missing_evidence(client):
    payload = create_payload()
    payload["draft"]["values"].update({"doorCount": {"value": 4}, "rowCount": {"value": 2}, "compartmentCount": {"value": 4}})
    assert client.post("/api/recipe-library/products", headers=HEADERS, json=payload).status_code == 201
    result = client.post("/api/recipe-library/products/NEW-001/validate", headers=HEADERS).json()
    assert result["issues"] and "doorCount" in result["unreferencedFields"] and not result["dataComplete"]
    assert not result["renderReady"]


def test_export_import_recomputes_status_and_is_atomic(client):
    export = client.get("/api/recipe-library/export", headers=HEADERS)
    assert "attachment" in export.headers["content-disposition"]
    data = export.json()
    assert data["format"] == "fox3d.recipe-workbench.v1"
    assert len(data["products"]) == 3
    data["tenantId"] = "foreign"
    data["productionReady"] = True
    data["products"][0]["renderReady"] = True
    imported = client.post("/api/recipe-library/import", headers=HEADERS, json=data)
    assert imported.status_code == 200, imported.text
    assert all(not i["renderReady"] and not i["productionReady"] for i in imported.json()["items"])
    assert all(i["revision"] == 1 for i in imported.json()["items"])
    extra = {"draft": create_payload("UNIQUE")["draft"]}
    data["products"].insert(0, extra)
    assert client.post("/api/recipe-library/import", headers=HEADERS, json=data).status_code == 409
    assert client.get("/api/recipe-library/products/UNIQUE", headers=HEADERS).status_code == 404
    single = client.get("/api/recipe-library/export?sku=LI-D40", headers=HEADERS).json()
    assert len(single["products"]) == 1


@pytest.mark.parametrize("payload", [[], {}, {"format": "fox3d.recipe-workbench.v1", "products": [None]}, {"format": "fox3d.recipe-workbench.v1", "products": []}])
def test_malformed_import_refused(client, payload):
    assert client.post("/api/recipe-library/import", headers=HEADERS, json=payload).status_code == 422
    assert len(client.get("/api/recipe-library", headers=HEADERS).json()["items"]) == 3


def test_invalid_json_and_oversized_import(client):
    assert client.post("/api/recipe-library/import", headers=HEADERS, content="{").status_code == 422
    assert client.post("/api/recipe-library/import", headers=HEADERS, content=b"x" * (8*1024*1024+1)).status_code == 413


def test_photo_upload_tenant_scope_and_byte_integrity(client, tmp_path):
    data = (DEFAULT_CATALOG.parent / "sources/LI-D40-03.jpg").read_bytes()
    upload = client.post("/api/recipe-library/products/LI-D40/images", headers=HEADERS, files={"file": ("門櫃.jpg", data, "image/jpeg")})
    assert upload.status_code == 201, upload.text
    digest = upload.json()["digest"]
    url = f"/api/recipe-library/products/LI-D40/images/{digest}"
    photo = client.get(url + "?workspace=sonaqueen-home")
    assert photo.status_code == 200 and photo.content == data
    assert photo.headers["x-content-type-options"] == "nosniff"
    assert client.get(url + "?workspace=other").status_code == 404
    assert client.get(url.replace("LI-D40", "MY-012") + "?workspace=sonaqueen-home").status_code == 404
    path, _ = RecipeWorkbench(tmp_path).image("sonaqueen-home", "LI-D40", digest)
    path.write_bytes(b"changed")
    assert client.get(url + "?workspace=sonaqueen-home").status_code == 422
    bad = client.post("/api/recipe-library/products/LI-D40/images", headers=HEADERS, files={"file": ("x.html", b"<script>alert(1)</script>", "image/jpeg")})
    assert bad.status_code == 422


def test_corrupted_seed_cannot_be_verified_or_exported(tmp_path):
    catalog = tmp_path / "source"
    shutil.copytree(DEFAULT_CATALOG.parent, catalog)
    (catalog / "sources/LI-D40-03.jpg").write_bytes(b"tampered")
    app = FastAPI()
    app.include_router(recipe_router(lambda: SimpleNamespace(root=tmp_path / "data"), catalog=catalog / "catalog.json"))
    with TestClient(app) as client:
        assert client.get("/api/recipe-library", headers=HEADERS).status_code == 422
        assert client.get("/api/recipe-library/export", headers=HEADERS).status_code == 422


def test_unknown_fields_and_readiness_injection_refused(client):
    payload = create_payload()
    payload["draft"]["productionReady"] = True
    assert client.post("/api/recipe-library/products", headers=HEADERS, json=payload).status_code == 422
