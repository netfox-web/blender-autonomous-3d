"""HTTP API for manual material cycle counts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.cyclecount import BOOK_CHANGED_MSG
from fox3d.platform import Platform

TENANT = "cc-api-a"
OTHER = "cc-api-b"
CONFIRM = {"confirm": True}


@pytest.fixture()
def client(platform):  # noqa: ANN001
    return TestClient(create_app(platform))


def _headers(tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant}


def _receive(client: TestClient, *, tenant: str = TENANT, sheets: int = 10) -> str:
    res = client.post(
        "/api/materials/lots",
        headers=_headers(tenant),
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": sheets, "actor": "ops"},
    )
    assert res.status_code == 200
    return res.json()["lotId"]


def _create_cc(
    client: TestClient,
    lot_id: str,
    *,
    tenant: str = TENANT,
    counted: int = 5,
    reason: str = "floor count",
    key: str = "idem-1",
) -> dict:
    res = client.post(
        f"/api/materials/lots/{lot_id}/cycle-counts",
        headers=_headers(tenant),
        json={"counted": counted, "reason": reason, "idempotencyKey": key, "actor": "ops"},
    )
    assert res.status_code == 200
    return res.json()


def test_other_tenant_list_empty_and_approve_is_404(client: TestClient) -> None:
    lot_id = _receive(client, tenant=TENANT)
    created = _create_cc(client, lot_id)
    listing = client.get("/api/materials/cycle-counts", headers=_headers(OTHER))
    assert listing.status_code == 200
    assert listing.json()["items"] == []
    denied = client.post(
        f"/api/materials/cycle-counts/{created['cycleCountId']}/approve",
        headers=_headers(OTHER),
        json=CONFIRM,
    )
    assert denied.status_code == 404


def test_approve_after_issue_material_returns_409_and_inventory_unchanged(client: TestClient, platform) -> None:
    lot_id = _receive(client, sheets=10)
    cc = _create_cc(client, lot_id, counted=4, reason="short")
    platform.lots.reserve_sheets(lot_id, tenant_id=TENANT, work_order_id="wo-after-cc", quantity=2)
    unchanged = platform.lots.quantities(lot_id, tenant_id=TENANT)
    res = client.post(
        f"/api/materials/cycle-counts/{cc['cycleCountId']}/approve",
        headers=_headers(),
        json={**CONFIRM, "actor": "sup"},
    )
    assert res.status_code == 409
    assert BOOK_CHANGED_MSG in res.json()["detail"]
    assert platform.lots.quantities(lot_id, tenant_id=TENANT) == unchanged
    assert platform.pilot.cyclecounts.counts[cc["cycleCountId"]]["applied"] is False


def test_concurrent_approve_applies_once(client: TestClient, platform, monkeypatch) -> None:
    lot_id = _receive(client, sheets=12)
    cc = _create_cc(client, lot_id, counted=7, reason="lock", key="cc-lock")
    calls: list[int] = []
    orig = platform.lots.apply_counted_available

    def wrapped(*args, **kwargs):
        calls.append(1)
        return orig(*args, **kwargs)

    monkeypatch.setattr(platform.lots, "apply_counted_available", wrapped)

    def approve_once() -> int:
        return client.post(
            f"/api/materials/cycle-counts/{cc['cycleCountId']}/approve",
            headers=_headers(),
            json={**CONFIRM, "actor": "sup"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: approve_once(), range(2)))
    assert sorted(statuses) == [200, 200]
    assert len(calls) == 1
    journal = [
        e for e in platform.pilot.journal.list(TENANT) if e.get("eventType") == "cyclecount.approve"
    ]
    assert len(journal) == 1
    assert platform.lots.quantities(lot_id, tenant_id=TENANT)["available"] == 7


def test_cyclecount_state_survives_platform_reload(client: TestClient, platform) -> None:
    lot_id = _receive(client, sheets=8)
    waiting = _create_cc(client, lot_id, counted=6, reason="wait", key="cc-wait")
    applied = _create_cc(client, lot_id, counted=5, reason="apply", key="cc-apply")
    client.post(
        f"/api/materials/cycle-counts/{applied['cycleCountId']}/approve",
        headers=_headers(),
        json=CONFIRM,
    )
    rejected = _create_cc(client, lot_id, counted=3, reason="reject", key="cc-reject")
    client.post(f"/api/materials/cycle-counts/{rejected['cycleCountId']}/reject", headers=_headers(), json={})

    plat2 = Platform(root=platform.root, mock_blender=True)
    client2 = TestClient(create_app(plat2))
    listing = client2.get(
        "/api/materials/cycle-counts",
        headers=_headers(),
        params={"status": "WAITING_HUMAN_APPROVAL"},
    )
    assert listing.status_code == 200
    ids = {row["cycleCountId"] for row in listing.json()["items"]}
    assert waiting["cycleCountId"] in ids
    assert applied["cycleCountId"] not in ids
    assert plat2.lots.quantities(lot_id, tenant_id=TENANT)["available"] == 5


@pytest.mark.parametrize(
    "counted",
    [-1, "bad", 1e20],
)
def test_create_rejects_invalid_counted(client: TestClient, counted) -> None:
    lot_id = _receive(client)
    res = client.post(
        f"/api/materials/lots/{lot_id}/cycle-counts",
        headers=_headers(),
        json={"counted": counted, "reason": "x", "idempotencyKey": f"k-{counted}"},
    )
    assert res.status_code == 422


def test_materials_lots_pagination(client: TestClient) -> None:
    for i in range(3):
        _receive(client, sheets=1 + i, tenant=TENANT)
    page = client.get("/api/materials", headers=_headers(), params={"offset": 0, "limit": 2})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] >= 3
    assert len(body["lots"]) == 2
    assert body["offset"] == 0
    assert body["limit"] == 2