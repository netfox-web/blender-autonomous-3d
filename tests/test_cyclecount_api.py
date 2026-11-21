"""HTTP API for manual material cycle counts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.cyclecount import BOOK_CHANGED_MSG, IDEMPOTENCY_CONFLICT_MSG, _explicit_idem_key
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


def test_materials_without_pagination_returns_all_lots(client: TestClient) -> None:
    for i in range(105):
        res = client.post(
            "/api/materials/lots",
            headers=_headers(TENANT),
            json={
                "material": "WOOD_WHITE",
                "thickness": 18,
                "sheetCount": 1,
                "actor": "ops",
                "idempotencyKey": f"legacy-page-{i}",
            },
        )
        assert res.status_code == 200
    legacy = client.get("/api/materials", headers=_headers())
    assert legacy.status_code == 200
    body = legacy.json()
    assert body["total"] >= 105
    assert len(body["lots"]) == body["total"]
    paged = client.get("/api/materials", headers=_headers(), params={"limit": 100})
    assert paged.status_code == 200
    assert len(paged.json()["lots"]) == 100


def test_create_cycle_count_idempotent_on_duplicate_post(client: TestClient) -> None:
    lot_id = _receive(client, sheets=8)
    body = {"counted": 4, "reason": "same", "idempotencyKey": "lost-resp", "actor": "ops"}
    first = client.post(f"/api/materials/lots/{lot_id}/cycle-counts", headers=_headers(), json=body)
    second = client.post(f"/api/materials/lots/{lot_id}/cycle-counts", headers=_headers(), json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["cycleCountId"] == second.json()["cycleCountId"]
    listing = client.get("/api/materials/cycle-counts", headers=_headers(), params={"status": "WAITING_HUMAN_APPROVAL"})
    assert listing.status_code == 200
    matches = [r for r in listing.json()["items"] if r["lotId"] == lot_id and r["reason"] == "same"]
    assert len(matches) == 1


def test_same_idempotency_key_across_lots_is_409_and_does_not_create(client: TestClient) -> None:
    lot_a = _receive(client, sheets=8)
    lot_b = _receive(client, sheets=6)
    body = {"counted": 4, "reason": "same", "idempotencyKey": "shared-key", "actor": "ops"}
    first = client.post(f"/api/materials/lots/{lot_a}/cycle-counts", headers=_headers(), json=body)
    second = client.post(f"/api/materials/lots/{lot_b}/cycle-counts", headers=_headers(), json=body)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"detail": IDEMPOTENCY_CONFLICT_MSG}
    assert first.json()["cycleCountId"] not in second.text
    assert lot_a not in second.text
    listing = client.get("/api/materials/cycle-counts", headers=_headers())
    assert listing.status_code == 200
    body_list = listing.json()
    assert body_list["total"] == 1
    assert body_list["items"][0]["cycleCountId"] == first.json()["cycleCountId"]
    assert body_list["items"][0]["lotId"] == lot_a
    retry = client.post(f"/api/materials/lots/{lot_a}/cycle-counts", headers=_headers(), json=body)
    assert retry.status_code == 200
    assert retry.json()["cycleCountId"] == first.json()["cycleCountId"]
    assert client.get("/api/materials/cycle-counts", headers=_headers()).json()["total"] == 1


def test_same_idempotency_key_different_body_is_409(client: TestClient) -> None:
    lot_id = _receive(client, sheets=8)
    first_body = {"counted": 4, "reason": "first", "idempotencyKey": "once", "actor": "ops"}
    first = client.post(f"/api/materials/lots/{lot_id}/cycle-counts", headers=_headers(), json=first_body)
    assert first.status_code == 200
    variants = [
        {"counted": 5, "reason": "first", "idempotencyKey": "once", "actor": "ops"},
        {"counted": 0, "reason": "first", "idempotencyKey": "once", "actor": "ops"},
        {"counted": 4, "reason": "other", "idempotencyKey": "once", "actor": "ops"},
        {"counted": 4, "reason": "first", "idempotencyKey": "once", "actor": "clerk"},
    ]
    for body in variants:
        res = client.post(f"/api/materials/lots/{lot_id}/cycle-counts", headers=_headers(), json=body)
        assert res.status_code == 409
        assert res.json() == {"detail": IDEMPOTENCY_CONFLICT_MSG}
        assert "Traceback" not in res.text
        assert first.json()["cycleCountId"] not in res.text
    listing = client.get("/api/materials/cycle-counts", headers=_headers())
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["counted"] == 4
    assert items[0]["reason"] == "first"
    assert items[0]["actor"] == "ops"


def test_idempotency_index_cannot_return_another_tenants_count(client: TestClient, platform) -> None:
    lot_b = _receive(client, tenant=OTHER, sheets=5)
    foreign = _create_cc(client, lot_b, tenant=OTHER, counted=1, reason="r", key="k")
    lot_a = _receive(client, tenant=TENANT, sheets=5)
    svc = platform.pilot.cyclecounts
    svc._idem[_explicit_idem_key(TENANT, "k")] = {
        "cycleCountId": foreign["cycleCountId"],
        "lotId": lot_a,
        "counted": 1,
        "reason": "r",
        "actor": "ops",
        "operatorId": None,
        "shiftId": None,
    }
    svc.persist()
    res = client.post(
        f"/api/materials/lots/{lot_a}/cycle-counts",
        headers=_headers(TENANT),
        json={"counted": 1, "reason": "r", "idempotencyKey": "k", "actor": "ops"},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "找不到盤點或批次"
    assert "tenant isolation" not in res.text
    assert foreign["cycleCountId"] not in res.text
    listing = client.get("/api/materials/cycle-counts", headers=_headers(TENANT))
    assert all(row["cycleCountId"] != foreign["cycleCountId"] for row in listing.json()["items"])
    assert all(row["lotId"] != lot_a for row in listing.json()["items"])
    assert platform.pilot.cyclecounts.counts[foreign["cycleCountId"]]["tenantId"] == OTHER


def test_same_idempotency_key_is_isolated_by_tenant(client: TestClient) -> None:
    lot_a = _receive(client, tenant=TENANT, sheets=5)
    lot_b = _receive(client, tenant=OTHER, sheets=5)
    body = {"counted": 3, "reason": "t", "idempotencyKey": "shared", "actor": "ops"}
    first = client.post(f"/api/materials/lots/{lot_a}/cycle-counts", headers=_headers(TENANT), json=body)
    second = client.post(f"/api/materials/lots/{lot_b}/cycle-counts", headers=_headers(OTHER), json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["cycleCountId"] != second.json()["cycleCountId"]
    assert first.json()["lotId"] == lot_a
    assert second.json()["lotId"] == lot_b
    own = client.get("/api/materials/cycle-counts", headers=_headers(OTHER))
    assert {row["cycleCountId"] for row in own.json()["items"]} == {second.json()["cycleCountId"]}
    denied = client.post(f"/api/materials/lots/{lot_a}/cycle-counts", headers=_headers(OTHER), json=body)
    assert denied.status_code == 404
    assert first.json()["cycleCountId"] not in denied.text


def test_invalid_body_does_not_stick_or_block_the_original_key(client: TestClient) -> None:
    lot_id = _receive(client, sheets=8)
    body = {"counted": 4, "reason": "ok", "idempotencyKey": "keep-key", "actor": "ops"}
    first = client.post(f"/api/materials/lots/{lot_id}/cycle-counts", headers=_headers(), json=body)
    assert first.status_code == 200
    invalid = [
        {"counted": -1, "reason": "ok", "idempotencyKey": "keep-key", "actor": "ops"},
        {"counted": "4", "reason": "ok", "idempotencyKey": "keep-key", "actor": "ops"},
        {"counted": 4, "reason": "", "idempotencyKey": "keep-key", "actor": "ops"},
        {"counted": 4, "reason": "x" * 201, "idempotencyKey": "keep-key", "actor": "ops"},
        {"counted": 4, "reason": "ok", "idempotencyKey": "", "actor": "ops"},
    ]
    for payload in invalid:
        res = client.post(f"/api/materials/lots/{lot_id}/cycle-counts", headers=_headers(), json=payload)
        assert res.status_code == 422
        assert "Traceback" not in res.text
    retry = client.post(f"/api/materials/lots/{lot_id}/cycle-counts", headers=_headers(), json=body)
    assert retry.status_code == 200
    assert retry.json()["cycleCountId"] == first.json()["cycleCountId"]
    listing = client.get("/api/materials/cycle-counts", headers=_headers())
    assert listing.json()["total"] == 1


@pytest.mark.parametrize("key", ["", "   ", "x" * 201, None, 12, True])
def test_malformed_idempotency_key_creates_nothing(client: TestClient, key: object) -> None:
    lot_id = _receive(client, sheets=4)
    res = client.post(
        f"/api/materials/lots/{lot_id}/cycle-counts",
        headers=_headers(),
        json={"counted": 1, "reason": "r", "idempotencyKey": key, "actor": "ops"},
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "idempotencyKey 格式錯誤"
    assert "Traceback" not in res.text
    listing = client.get("/api/materials/cycle-counts", headers=_headers())
    assert listing.json()["total"] == 0


def test_cyclecount_list_pagination_exposes_older_rows(client: TestClient) -> None:
    lot_ids = [_receive(client, sheets=2, tenant=TENANT) for _ in range(105)]
    for i, lot_id in enumerate(lot_ids):
        _create_cc(client, lot_id, counted=1, reason=f"page-{i}", key=f"page-{i}")
    page0 = client.get("/api/materials/cycle-counts", headers=_headers(), params={"offset": 0, "limit": 100})
    page1 = client.get("/api/materials/cycle-counts", headers=_headers(), params={"offset": 100, "limit": 100})
    assert page0.status_code == 200 and page1.status_code == 200
    assert page0.json()["total"] >= 105
    assert len(page0.json()["items"]) == 100
    assert len(page1.json()["items"]) >= 5
    first_batch_ids = {row["cycleCountId"] for row in page0.json()["items"]}
    older = [row for row in page1.json()["items"] if row["cycleCountId"] not in first_batch_ids]
    assert older
    assert all(row["status"] == "WAITING_HUMAN_APPROVAL" for row in older)


def test_cyclecount_list_reflects_other_instance_writes(tmp_path) -> None:
    root = tmp_path / "cyclecount-list-sync"
    writer_plat = Platform(root=root, mock_blender=True)
    writer = TestClient(create_app(writer_plat))
    lot_id = _receive(writer, sheets=10)
    created = _create_cc(writer, lot_id, counted=6, reason="sync", key="api-sync")
    reader_plat = Platform(root=root, mock_blender=True)
    reader = TestClient(create_app(reader_plat))
    stale = reader.get("/api/materials/cycle-counts", headers=_headers())
    assert stale.status_code == 200
    assert {row["cycleCountId"] for row in stale.json()["items"]} == {created["cycleCountId"]}
    writer_plat.pilot.cyclecounts.approve(
        created["cycleCountId"],
        tenant_id=TENANT,
        actor="sup",
        payload=CONFIRM,
    )
    applied = reader.get(
        "/api/materials/cycle-counts",
        headers=_headers(),
        params={"status": "APPLIED"},
    )
    assert applied.status_code == 200
    assert {row["cycleCountId"] for row in applied.json()["items"]} == {created["cycleCountId"]}


def test_cross_platform_concurrent_approve_via_api(client: TestClient, platform) -> None:
    import threading

    lot_id = _receive(client, sheets=15)
    cc = _create_cc(client, lot_id, counted=9, reason="api-dual", key="api-dual")
    barrier = threading.Barrier(2)

    def approve_once(_: int) -> int:
        other = Platform(root=platform.root, mock_blender=True)
        other_client = TestClient(create_app(other))
        barrier.wait()
        return other_client.post(
            f"/api/materials/cycle-counts/{cc['cycleCountId']}/approve",
            headers=_headers(),
            json={**CONFIRM, "actor": "sup"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(approve_once, range(2)))
    assert sorted(statuses) == [200, 200]
    plat_check = Platform(root=platform.root, mock_blender=True)
    adjs = [
        a
        for a in plat_check.lots.get(lot_id, tenant_id=TENANT).get("adjustments") or []
        if a.get("source") == "CYCLE_COUNT"
    ]
    assert len(adjs) == 1
    assert plat_check.lots.quantities(lot_id, tenant_id=TENANT)["available"] == 9