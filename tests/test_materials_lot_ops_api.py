"""HTTP API: material lot quarantine/detail and remnant release/consume."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
TENANT = "lot-ops-a"
OTHER = "lot-ops-b"
CONFIRM = {"confirm": True, "reason": "quality hold", "actor": "ops"}


@pytest.fixture()
def client(platform):  # noqa: ANN001
    return TestClient(create_app(platform))


def _headers(tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant}


def _receive(client: TestClient, *, tenant: str = TENANT, sheets: int = 10, material: str = "WOOD_WHITE") -> str:
    res = client.post(
        "/api/materials/lots",
        headers=_headers(tenant),
        json={"material": material, "thickness": 18, "sheetCount": sheets, "actor": "ops"},
    )
    assert res.status_code == 200, res.text
    return res.json()["lotId"]


def _seed_wo_ready(platform, *, tenant: str = TENANT):
    product = platform.kd.build_sku(tenant_id=tenant, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    nest = (rel.get("snapshot") or {}).get("nesting") or {}
    sheet_mm = nest.get("sheetMm") or [2440, 1220]
    material = nest.get("sheetSku") or "PB_18_WHITE"
    row: dict = {
        "supplierLot": f"{tenant}-stock",
        "material": material,
        "thickness": nest.get("thickness") or 18,
        "quantity": 20,
    }
    if len(sheet_mm) >= 2:
        row["length"] = float(sheet_mm[0])
        row["width"] = float(sheet_mm[1])
    platform.pilot.receiving.import_receipt(
        row,
        tenant_id=tenant,
        actor="recv",
        source="MANUAL",
        idempotency_key=f"{tenant}-stock",
    )
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    platform.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    return wo, rel, material, float(nest.get("thickness") or 18)


def test_lot_detail_and_other_tenant_404(client: TestClient, platform) -> None:
    lot_id = _receive(client)
    detail = client.get(f"/api/materials/lots/{lot_id}", headers=_headers())
    assert detail.status_code == 200
    body = detail.json()
    assert body["lotId"] == lot_id
    assert body["quantities"]["available"] == 10
    assert isinstance(body["reservations"], list)
    assert body["version"] >= 1
    denied = client.get(f"/api/materials/lots/{lot_id}", headers=_headers(OTHER))
    assert denied.status_code == 404


def test_quarantine_reserve_release_flow(client: TestClient, platform) -> None:
    wo, _rel, material, thickness = _seed_wo_ready(platform, tenant=TENANT)
    receipts = [r for r in platform.pilot.receiving.receipts.values() if r.get("tenantId") == TENANT]
    assert receipts
    lot_id = str(receipts[-1]["lotId"])
    detail = client.get(f"/api/materials/lots/{lot_id}", headers=_headers()).json()
    q = client.post(
        f"/api/materials/lots/{lot_id}/quarantine",
        headers=_headers(),
        json={**CONFIRM, "expectedVersion": detail["version"]},
    )
    assert q.status_code == 200
    assert q.json().get("quarantined") is True
    blocked = client.post(
        f"/api/pilot/work-orders/{wo['workOrderId']}/reserve",
        headers=_headers(),
        json={"actor": "ops"},
    )
    assert blocked.status_code == 409
    released = client.post(
        f"/api/materials/lots/{lot_id}/release-quarantine",
        headers=_headers(),
        json={**CONFIRM, "reason": "cleared", "expectedVersion": q.json().get("version")},
    )
    assert released.status_code == 200
    assert released.json().get("quarantined") is False
    ok = client.post(
        f"/api/pilot/work-orders/{wo['workOrderId']}/reserve",
        headers=_headers(),
        json={"actor": "ops"},
    )
    assert ok.status_code == 200
    assert ok.json().get("materialReserved") is True


def test_quarantine_requires_confirm_and_reason(client: TestClient) -> None:
    lot_id = _receive(client)
    no_confirm = client.post(
        f"/api/materials/lots/{lot_id}/quarantine",
        headers=_headers(),
        json={"reason": "x"},
    )
    assert no_confirm.status_code == 422
    bad_reason = client.post(
        f"/api/materials/lots/{lot_id}/quarantine",
        headers=_headers(),
        json={**CONFIRM, "reason": ""},
    )
    assert bad_reason.status_code == 422


def test_quarantine_stale_expected_version_409(client: TestClient) -> None:
    lot_id = _receive(client)
    stale = client.post(
        f"/api/materials/lots/{lot_id}/quarantine",
        headers=_headers(),
        json={**CONFIRM, "expectedVersion": 9999},
    )
    assert stale.status_code == 409


def test_remnant_release_reserve_and_consume_idempotent(client: TestClient, platform) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="lot-ops-rem",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]
    reserved = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=_headers(),
        json={"by": "wo-a", "version": created[0]["version"]},
    )
    assert reserved.status_code == 200
    denied = client.post(
        f"/api/remnants/{rid}/release-reservation",
        headers=_headers(),
        json={"by": "other", "version": reserved.json()["version"]},
    )
    assert denied.status_code == 409
    released = client.post(
        f"/api/remnants/{rid}/release-reservation",
        headers=_headers(),
        json={"by": "wo-a", "version": reserved.json()["version"]},
    )
    assert released.status_code == 200
    assert released.json().get("status") == "available"
    again = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=_headers(),
        json={"by": "wo-b", "version": released.json()["version"]},
    )
    assert again.status_code == 200
    key = "consume-once-key"
    first = client.post(
        f"/api/remnants/{rid}/consume",
        headers=_headers(),
        json={"by": "wo-b", "version": again.json()["version"], "idempotencyKey": key},
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/remnants/{rid}/consume",
        headers=_headers(),
        json={"by": "wo-b", "version": first.json()["version"], "idempotencyKey": key},
    )
    assert second.status_code == 200
    assert second.json().get("remnantId") == rid
    assert platform.remnants.items[rid]["status"] == "consumed"


def test_remnant_release_after_lease_expiry(client: TestClient, platform) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 500, "h": 300, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="lease-exp",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]
    reserved = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=_headers(),
        json={"by": "lease-holder", "version": 1, "leaseSeconds": 3600},
    )
    assert reserved.status_code == 200
    denied = client.post(
        f"/api/remnants/{rid}/release-reservation",
        headers=_headers(),
        json={"by": "not-holder", "version": reserved.json()["version"]},
    )
    assert denied.status_code == 409
    rec = dict(platform.remnants.items[rid])
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    rec["reservedUntil"] = past
    platform.remnants.store.put(rec)
    platform.remnants.items[rid] = rec
    freed = client.post(
        f"/api/remnants/{rid}/release-reservation",
        headers=_headers(),
        json={"by": "expired-operator", "version": rec["version"]},
    )
    assert freed.status_code == 200
    assert freed.json().get("status") == "available"


def test_remnant_other_tenant_is_404(client: TestClient, platform) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 400, "h": 300, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="tenant-iso",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]
    assert client.post(
        f"/api/remnants/{rid}/consume",
        headers=_headers(OTHER),
        json={"by": "x", "idempotencyKey": "k1"},
    ).status_code == 404
    lot_id = _receive(client)
    assert client.post(
        f"/api/materials/lots/{lot_id}/quarantine",
        headers=_headers(OTHER),
        json=CONFIRM,
    ).status_code == 404