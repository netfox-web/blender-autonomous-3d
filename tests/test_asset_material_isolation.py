from fastapi.testclient import TestClient

from fox3d.api import create_app


def test_assets_and_material_catalog_isolation(platform):
    client = TestClient(create_app(platform))
    assets = {}
    lots = {}
    for tenant in ("tenant-a", "tenant-b"):
        assets[tenant] = platform.dam.put(
            tenant_id=tenant, kind="test", name="image.png", data=tenant.encode()
        ).asset_id
        lots[tenant] = platform.lots.create(
            tenant_id=tenant, material="WOOD_WHITE", thickness=18, sheet_count=1
        )["lotId"]

    for tenant, asset_id in assets.items():
        path = f"/api/assets/{asset_id}"
        for headers in ({}, {"X-Tenant-Id": ""}, {"X-Tenant-Id": "../invalid"}):
            assert client.get(path, headers=headers).status_code == 400
        assert client.get(path, headers={"X-Tenant-Id": tenant}).content == tenant.encode()
        other = "tenant-b" if tenant == "tenant-a" else "tenant-a"
        foreign = client.get(path, headers={"X-Tenant-Id": other})
        missing = client.get("/api/assets/missing", headers={"X-Tenant-Id": other})
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        response = client.get("/api/materials", headers={"X-Tenant-Id": tenant})
        assert {lot["lotId"] for lot in response.json()["lots"]} == {lots[tenant]}

    assert client.get("/api/materials").status_code == 400
    catalog = client.get("/api/materials/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["sheets"]
    assert "lots" not in catalog.json()
    assert all(lot_id not in catalog.text for lot_id in lots.values())
