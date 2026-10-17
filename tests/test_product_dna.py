"""Issue 18 contract tests.

This module does not run Blender. Its own evidence class is MOCK_REGRESSION.
FIXTURE labels describe synthetic calibration pixels. REAL_BLENDER is only a
rejected or classified envelope, never a render produced here.
"""
import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from types import SimpleNamespace

from fox3d.golden_product import SKUS, GoldenRecipe, Measurement, package_plan
from fox3d.ids import sha256_bytes
from fox3d.product_dna import (
    EXPORT_SKUS, FAMILY_ID, MOLD_ID, ProductDnaError, TruthBadge, ExportService,
    catalog, engineering_version_effect, label_render_evidence, project_manifest, project_twin,
    read_real_generation_media, reconcile, require_current_engineering_version,
)
from fox3d.product_dna_api import product_dna_router
from fox3d.recipe_3d import atomic_json, read_json

TEST_EVIDENCE_CLASS = "MOCK_REGRESSION"
TEST_EXECUTED_REAL_BLENDER = False
assert TEST_EXECUTED_REAL_BLENDER is False


def _client(tmp_path):
    app = FastAPI()
    app.include_router(product_dna_router(lambda: SimpleNamespace(root=tmp_path)))
    return TestClient(app)


def _local_snapshot(tenant="tenant-a"):
    manifest = project_manifest(tenant)
    twin = manifest["twins"][0]
    return {
        "system": "ERP",
        "tenantId": tenant,
        "productFamilyId": manifest["familyId"],
        "skuId": twin["sku"],
        "masterProductId": None,
        "dieMoldId": manifest["moldId"],
        "productDnaId": None,
        "engineeringVersion": manifest["engineeringVersion"],
        "widthMm": twin["geometryMm"]["widthMm"],
        "depthMm": twin["geometryMm"]["depthMm"],
        "heightMm": twin["geometryMm"]["heightMm"],
        "boardThicknessMm": 15.0,
        "engineeringHash": manifest["engineeringHash"],
        "bomHash": manifest["bomHash"],
        "artworkHash": twin["hashes"]["artworkHash"],
        "finalUvHash": twin["hashes"]["finalUvHash"],
        "rightsScope": "FIXTURE_NON_IP",
        "processCode": "PRINT_SURFACE_PREVIEW",
    }


def test_one_mold_three_artwork_skus_share_engineering():
    manifest = project_manifest("tenant-a")
    assert manifest["skuCount"] == 3
    assert [twin["sku"] for twin in manifest["twins"]] == list(EXPORT_SKUS)
    assert len({twin["hashes"]["engineeringHash"] for twin in manifest["twins"]}) == 1
    assert len({twin["hashes"]["artworkHash"] for twin in manifest["twins"]}) == 3
    assert len({twin["hashes"]["packageHash"] for twin in manifest["twins"]}) == 3
    assert len({twin["twinId"] for twin in manifest["twins"]}) == 3
    assert manifest["moldId"] == MOLD_ID
    assert manifest["familyId"] == FAMILY_ID
    assert manifest["globalProductionReady"] is False
    assert manifest["liveSystemRead"] is False
    assert manifest["evidenceSeparation"]["artworkPixels"] == "FIXTURE"
    assert manifest["evidenceSeparation"]["renderMedia"] == "ABSENT"
    assert manifest["evidenceSeparation"]["automatedTestsAndCi"] == "MOCK_REGRESSION"
    assert manifest["truth"]["realBlender"] is False
    assert manifest["truth"]["badge"] == "PREVIEW_FIXTURE"
    assert all(row["evidenceClass"] == "ABSENT" for twin in manifest["twins"] for row in twin["media"] if row["role"] == "GLB")


def test_artwork_swap_keeps_engineering_hash():
    master = project_manifest("tenant-a", version="FIXTURE_MASTER_V1")
    single = project_manifest("tenant-a", version="FIXTURE_SINGLE_V1")
    assert master["engineeringHash"] == single["engineeringHash"]
    assert [twin["hashes"]["artworkHash"] for twin in master["twins"]] != [twin["hashes"]["artworkHash"] for twin in single["twins"]]
    assert master["twins"][0]["hashes"]["finalUvHash"] != single["twins"][0]["hashes"]["finalUvHash"]


def test_dimension_or_structure_requires_new_engineering_version():
    changed = GoldenRecipe(boardThicknessMm=Measurement(value=18., truth="VERIFIED", evidence="drawing", evidenceSha256="a" * 64))
    effect = engineering_version_effect(changed)
    assert effect["newEngineeringVersionRequired"] is True
    assert effect["proposedEngineeringHash"] != effect["currentEngineeringHash"]
    with pytest.raises(ProductDnaError, match="新的工程版本"):
        require_current_engineering_version(changed)
    print_policy = GoldenRecipe(safeMm=8., bleedMm=4.)
    assert engineering_version_effect(print_policy)["newEngineeringVersionRequired"] is False
    assert require_current_engineering_version(print_policy)["acceptedAsCurrentVersion"] is True


def test_uv_mm_and_safe_zone():
    manifest = project_manifest("tenant-a")
    for twin in manifest["twins"]:
        package = package_plan(twin["sku"], twin["artworkVersion"])
        assert twin["geometryMm"]["safeMm"] == 5
        assert twin["geometryMm"]["bleedMm"] == 3
        for placement, view in zip(package["placements"], twin["placements"]):
            assert view["safeMm"] == 5
            assert view["widthMm"] > 2 * view["safeMm"]
            assert view["heightMm"] > 2 * view["safeMm"]
            src = placement["source"]
            uv = view["uvRect"]
            assert (uv["u1"] - uv["u0"]) * src["widthPx"] == pytest.approx(view["widthMm"])
            assert (uv["v1"] - uv["v0"]) * src["heightPx"] == pytest.approx(view["heightMm"])


def test_truth_badge_cannot_promote_production():
    payload = project_manifest("tenant-a")["truth"]
    with pytest.raises(ValidationError):
        TruthBadge.model_validate({**payload, "badge": "PRODUCTION"})
    with pytest.raises(ValidationError):
        TruthBadge.model_validate({**payload, "globalProductionReady": True})
    with pytest.raises(ValidationError):
        TruthBadge.model_validate({**payload, "renderEvidenceClass": "REAL_BLENDER"})


def test_render_labels_stay_separate(monkeypatch):
    assert TEST_EVIDENCE_CLASS == "MOCK_REGRESSION"
    monkeypatch.setenv("FOX3D_MOCK_BLENDER", "1")
    assert label_render_evidence(evidence_origin="UNIT_SYNTHETIC", real_blender=True, used_mock=False, blender_version="5.2.1") == "MOCK_REGRESSION"
    assert label_render_evidence(evidence_origin="FIXTURE", real_blender=False, used_mock=False, blender_version=None) == "FIXTURE"
    with pytest.raises(ProductDnaError):
        label_render_evidence(evidence_origin="LIVE_BLENDER_PROCESS", real_blender=True, used_mock=False, blender_version="5.2.1 LTS")
    monkeypatch.setenv("FOX3D_MOCK_BLENDER", "0")
    assert label_render_evidence(evidence_origin="LIVE_BLENDER_PROCESS", real_blender=True, used_mock=False, blender_version="5.2.1 LTS") == "REAL_BLENDER"
    with pytest.raises(ProductDnaError):
        label_render_evidence(evidence_origin="LIVE_BLENDER_PROCESS", real_blender=True, used_mock=True, blender_version="5.2.1 LTS")
    with pytest.raises(ProductDnaError):
        label_render_evidence(evidence_origin="MISSING", real_blender=True, used_mock=False, blender_version="5.2.1 LTS")


def test_synthetic_generation_is_not_real_media(tmp_path, monkeypatch):
    monkeypatch.setenv("FOX3D_MOCK_BLENDER", "0")
    atomic_json(tmp_path / "manifest.json", {"renderInfo": {"realBlender": True, "usedMock": False, "blenderVersion": "unit-synthetic"}})
    with pytest.raises(ProductDnaError):
        read_real_generation_media(tmp_path, sku=SKUS[0], version="FIXTURE_MASTER_V1")


def test_reconcile_local_match_external_unbound_and_rejections(tmp_path):
    before = list(tmp_path.rglob("*"))
    matched = reconcile(_local_snapshot(), tenant_id="tenant-a")
    assert matched["status"] == "LOCAL_MATCH_EXTERNAL_UNBOUND"
    assert matched["liveRead"] is False and matched["persisted"] is False
    assert matched["globalProductionReady"] is False
    assert list(tmp_path.rglob("*")) == before
    partial = reconcile({"system": "AI_PRINT_OS", "tenantId": "tenant-a", "dieMoldId": MOLD_ID}, tenant_id="tenant-a")
    assert partial["status"] == "PARTIAL"
    assert any(row["field"] == "masterProductId" and row["status"] == "UNBOUND_LOCAL" for row in partial["checks"])
    stale = _local_snapshot()
    stale["widthMm"] = 500
    stale["system"] = "SPECPILOT_PRODUCT_DNA"
    rejected = reconcile(stale, tenant_id="tenant-a")
    assert rejected["status"] == "REJECTED"
    assert rejected["newEngineeringVersionRequired"] is True
    assert any(row["status"] == "STALE_ENGINEERING_VERSION" for row in rejected["checks"])
    licensed = _local_snapshot()
    licensed["rightsScope"] = "LICENSED_ARTWORK"
    blocked = reconcile(licensed, tenant_id="tenant-a")
    assert blocked["status"] == "REJECTED"
    assert any(row["status"] == "BLOCKED_RIGHTS" for row in blocked["checks"])
    process = _local_snapshot()
    process["processCode"] = "APPROVED_DIE_PLATE"
    assert reconcile(process, tenant_id="tenant-a")["newEngineeringVersionRequired"] is True
    leaked = reconcile(_local_snapshot("tenant-a"), tenant_id="tenant-b")
    assert leaked["status"] == "REJECTED"
    assert leaked["checks"] == [{"field": "tenantId", "status": "TENANT_MISMATCH"}]
    assert "twins" not in leaked


def test_cancel_before_seal_then_retry(tmp_path):
    service = ExportService(tmp_path)

    def hook(export_id):
        service.cancel("tenant-a", export_id)

    first = service.begin("tenant-a", before_seal=hook)
    assert first["state"] == "cancelled"
    assert first["sealed"] is False
    assert not (service._tenant_dir("tenant-a") / "current.json").exists()
    second = service.retry("tenant-a", first["exportId"])
    assert second["state"] == "sealed"
    assert second["exportId"] != first["exportId"]
    again = service.retry("tenant-a", second["exportId"])
    assert again["exportId"] == second["exportId"]
    assert again["manifest"]["contentHash"] == second["manifest"]["contentHash"]
    assert again["manifest"]["evidenceSeparation"]["renderMedia"] == "ABSENT"
    assert again["manifest"]["evidenceSeparation"]["automatedTestsAndCi"] == "MOCK_REGRESSION"


def test_missing_file_and_sha_tamper_fail_closed(tmp_path):
    service = ExportService(tmp_path)
    sealed = service.begin("tenant-a")
    export_id = sealed["exportId"]
    folder = service._export_dir("tenant-a", export_id)
    artwork = folder / "skus" / EXPORT_SKUS[0] / "fixture-1.png"
    artwork.unlink()
    with pytest.raises(ProductDnaError, match="缺少檔案"):
        service.read("tenant-a", export_id)
    service2 = ExportService(tmp_path)
    other = service2.begin("tenant-b")
    other_folder = service2._export_dir("tenant-b", other["exportId"])
    envelope = other_folder / "envelope.json"
    raw = bytearray(envelope.read_bytes())
    raw[-3] = raw[-3] ^ 1
    envelope.write_bytes(raw)
    with pytest.raises(ProductDnaError, match="SHA"):
        service2.read("tenant-b", other["exportId"])
    fresh = project_manifest("tenant-c")
    third = ExportService(tmp_path).begin("tenant-c")
    third_folder = ExportService(tmp_path)._export_dir("tenant-c", third["exportId"])
    body = read_json(third_folder / "envelope.json")
    body["manifest"]["twins"][0]["hashes"]["artworkHash"] = "b" * 64
    body["manifest"]["contentHash"] = "c" * 64
    atomic_json(third_folder / "envelope.json", body)
    seal = read_json(third_folder / "seal.json")
    seal["envelopeSha256"] = sha256_bytes((third_folder / "envelope.json").read_bytes())
    atomic_json(third_folder / "seal.json", seal)
    with pytest.raises(ProductDnaError):
        ExportService(tmp_path).read("tenant-c", third["exportId"])
    assert fresh["twins"][0]["hashes"]["artworkHash"] != "b" * 64


def test_api_catalog_reconcile_media_and_tenant_isolation(tmp_path):
    with _client(tmp_path) as client:
        catalog_body = client.get("/api/product-dna/v1/catalog").json()
        assert catalog_body["globalProductionReady"] is False
        assert catalog_body["defaultExportSkus"] == list(EXPORT_SKUS)
        assert catalog_body["historicalArtwork"] == "BLOCKED"
        headers = {"X-Tenant-Id": "tenant-a"}
        assert client.get(f"/api/product-dna/v1/families/{FAMILY_ID}/manifest").status_code == 400
        manifest = client.get(f"/api/product-dna/v1/families/{FAMILY_ID}/manifest", headers=headers).json()
        assert manifest["skuCount"] == 3
        assert client.get(f"/api/product-dna/v1/families/other/manifest", headers=headers).status_code == 404
        historical = client.get(f"/api/product-dna/v1/families/{FAMILY_ID}/manifest", headers=headers, params={"version": "HISTORICAL_PENDING"})
        assert historical.status_code == 422
        twin = client.get(f"/api/product-dna/v1/families/{FAMILY_ID}/skus/{EXPORT_SKUS[0]}/twin", headers=headers).json()
        assert twin["hashes"]["engineeringHash"] == manifest["engineeringHash"]
        media = client.get("/api/product-dna/v1/media-refs", headers=headers, params={"consumer": "FOXSTUDIO"}).json()
        assert media["readOnly"] is True
        assert media["renderEvidenceClass"] == "ABSENT"
        assert media["automatedTestsAndCi"] == "MOCK_REGRESSION"
        assert client.get("/api/product-dna/v1/media-refs", headers=headers, params={"consumer": "ERP"}).status_code == 404
        report = client.post("/api/product-dna/v1/reconcile", headers=headers, json=_local_snapshot()).json()
        assert report["status"] == "LOCAL_MATCH_EXTERNAL_UNBOUND"
        assert report["persisted"] is False
        assert not (tmp_path / "product-dna").exists()
        created = client.post("/api/product-dna/v1/exports", headers=headers, json={"version": "FIXTURE_MASTER_V1", "seal": True})
        assert created.status_code == 201
        export_id = created.json()["exportId"]
        replay = client.post("/api/product-dna/v1/exports", headers=headers, json={"version": "FIXTURE_MASTER_V1", "seal": True})
        assert replay.json()["exportId"] == export_id
        assert client.get(f"/api/product-dna/v1/exports/{export_id}", headers={"X-Tenant-Id": "tenant-b"}).status_code == 404
        assert client.post(f"/api/product-dna/v1/exports/{export_id}/cancel", headers=headers).status_code == 409
        staged = client.post("/api/product-dna/v1/exports", headers=headers, json={"version": "FIXTURE_SINGLE_V1", "seal": False})
        staged_id = staged.json()["exportId"]
        assert staged.json()["state"] == "staged"
        assert client.post(f"/api/product-dna/v1/exports/{staged_id}/cancel", headers=headers).json()["state"] == "cancelled"
        retried = client.post(f"/api/product-dna/v1/exports/{staged_id}/retry", headers=headers).json()
        assert retried["state"] == "sealed"
        assert retried["exportId"] != staged_id
        assert retried["manifest"]["twins"][0]["artworkVersion"] == "FIXTURE_SINGLE_V1"
        assert client.post("/api/product-dna/v1/exports", headers=headers, json={"version": "FIXTURE_MASTER_V1", "skus": ["KU002101", "KU002101", "KT015101"]}).status_code == 422


def test_catalog_matches_public_gaps():
    body = catalog()
    assert body["engineeringHash"] == project_twin("tenant-a", EXPORT_SKUS[0], "FIXTURE_MASTER_V1")["hashes"]["engineeringHash"]
    assert "globalProductionReady" in body and body["globalProductionReady"] is False
    assert copy.deepcopy(body)["liveSystemRead"] is False


def test_committed_schema_keeps_closed_readiness():
    import json
    from pathlib import Path
    committed = json.loads(Path("data/product_dna/export.schema.json").read_text(encoding="utf-8"))
    family = committed["familyManifest"]["properties"]
    twin = committed["twin"]["properties"]
    for key in ("familyId", "moldId", "engineeringHash", "bomHash", "twins", "contentHash", "globalProductionReady"):
        assert key in family
    for key in ("sku", "hashes", "placements", "angles", "media", "truth", "rights"):
        assert key in twin
    assert family["globalProductionReady"]["const"] is False
    assert committed["familyManifest"]["$defs"]["TruthBadge"]["properties"]["globalProductionReady"]["const"] is False
    assert "PRODUCTION" not in json.dumps(committed["familyManifest"]["$defs"]["TruthBadge"]["properties"]["badge"])
