"""Factory durable state, quote listing, and idempotent approval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform


def _run(client: TestClient, tenant: str) -> dict:
    res = client.post("/api/factory/run", json={"text": "鞋櫃", "render": False}, headers={"X-Tenant-Id": tenant})
    assert res.status_code == 200
    return res.json()


def test_run_approve_rebuild_platform_preserves_quote_and_approval(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    run = _run(client, "tenant-a")
    quote_id = run["quote"]["quoteId"]
    run_id = run["runId"]

    approved = client.post(
        f"/api/factory/quotes/{quote_id}/approve",
        json={"actor": "lead-a"},
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert approved.status_code == 200
    approved_at = approved.json()["gate"]["approvedAt"]
    assert approved.json()["gate"]["status"] == "APPROVED"

    state_file = root / "factory" / "state.json"
    assert state_file.is_file()

    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))

    got = client2.get(f"/api/factory/quotes/{quote_id}", headers={"X-Tenant-Id": "tenant-a"})
    assert got.status_code == 200
    assert got.json()["quoteId"] == quote_id

    again = client2.post(
        f"/api/factory/quotes/{quote_id}/approve",
        json={"actor": "someone-else"},
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert again.status_code == 200
    gate = again.json()["gate"]
    assert gate["status"] == "APPROVED"
    assert gate["actor"] == "lead-a"
    assert gate["approvedAt"] == approved_at
    assert gate["liveMachineControl"] is False
    assert gate["autoLiveCnc"] is False

    assert plat2.factory.run_id_for_quote(quote_id, "tenant-a") == run_id


def test_quote_list_is_tenant_scoped_and_other_tenant_gets_404(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    run_a = _run(client, "tenant-a")
    quote_a = run_a["quote"]["quoteId"]
    _run(client, "tenant-b")

    listed = client.get("/api/factory/quotes", headers={"X-Tenant-Id": "tenant-a"})
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["quoteId"] == quote_a

    other_list = client.get("/api/factory/quotes", headers={"X-Tenant-Id": "tenant-b"})
    assert other_list.status_code == 200
    b_items = other_list.json()["items"]
    assert len(b_items) == 1
    assert b_items[0]["quoteId"] != quote_a

    assert client.get(f"/api/factory/quotes/{quote_a}", headers={"X-Tenant-Id": "tenant-b"}).status_code == 404
    assert (
        client.post(
            f"/api/factory/quotes/{quote_a}/approve",
            json={"actor": "x"},
            headers={"X-Tenant-Id": "tenant-b"},
        ).status_code
        == 404
    )


def test_double_approve_returns_200_and_preserves_approved_at(tmp_path: Path) -> None:
    root = tmp_path / "data"
    client = TestClient(create_app(Platform(root=root, mock_blender=True)))
    quote_id = _run(client, "t1")["quote"]["quoteId"]

    first = client.post(
        f"/api/factory/quotes/{quote_id}/approve",
        json={"actor": "ops"},
        headers={"X-Tenant-Id": "t1"},
    )
    assert first.status_code == 200
    stamp = first.json()["gate"]["approvedAt"]

    second = client.post(
        f"/api/factory/quotes/{quote_id}/approve",
        json={"actor": "ops"},
        headers={"X-Tenant-Id": "t1"},
    )
    assert second.status_code == 200
    assert second.json()["gate"]["approvedAt"] == stamp


def test_corrupt_factory_state_starts_empty_without_500(tmp_path: Path) -> None:
    root = tmp_path / "data"
    factory_dir = root / "factory"
    factory_dir.mkdir(parents=True)
    state_file = factory_dir / "state.json"
    state_file.write_text("{not valid json", encoding="utf-8")

    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    assert client.get("/api/factory/quotes", headers={"X-Tenant-Id": "t1"}).status_code == 200
    assert client.get("/api/factory/quotes", headers={"X-Tenant-Id": "t1"}).json()["items"] == []

    backups = list(factory_dir.glob("state.json.corrupt.*.bak"))
    assert backups
    assert not state_file.exists()

    res = client.post("/api/factory/run", json={"text": "鞋櫃", "render": False}, headers={"X-Tenant-Id": "t1"})
    assert res.status_code == 200


@pytest.mark.parametrize("limit,expect_status", [(1, 200), (100, 200), (101, 422)])
def test_quote_list_limit_boundaries(tmp_path: Path, limit: int, expect_status: int) -> None:
    client = TestClient(create_app(Platform(root=tmp_path / "data", mock_blender=True)))
    _run(client, "t1")
    res = client.get(f"/api/factory/quotes?limit={limit}", headers={"X-Tenant-Id": "t1"})
    assert res.status_code == expect_status


def test_concurrent_runs_on_shared_root_preserve_both_quotes(tmp_path: Path) -> None:
    import threading

    root = tmp_path / "data"
    barrier = threading.Barrier(2)
    quotes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        plat = Platform(root=root, mock_blender=True)
        client = TestClient(create_app(plat))
        barrier.wait()
        run = _run(client, "tenant-shared")
        with lock:
            quotes.append(run["quote"]["quoteId"])

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
        assert not t.is_alive()

    assert len(quotes) == 2
    state = json.loads((root / "factory" / "state.json").read_text(encoding="utf-8"))
    for qid in quotes:
        assert qid in state["quotes"]
        assert qid in state["quoteRunIndex"]

    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    listed = client.get("/api/factory/quotes", headers={"X-Tenant-Id": "tenant-shared"})
    ids = {item["quoteId"] for item in listed.json()["items"]}
    assert set(quotes) <= ids


def test_two_platform_instances_merge_quotes_on_shared_root(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat_a = Platform(root=root, mock_blender=True)
    client_a = TestClient(create_app(plat_a))
    run_a = _run(client_a, "tenant-a")
    quote_a = run_a["quote"]["quoteId"]

    plat_b = Platform(root=root, mock_blender=True)
    client_b = TestClient(create_app(plat_b))
    run_b = _run(client_b, "tenant-a")
    quote_b = run_b["quote"]["quoteId"]
    assert quote_a != quote_b

    listed = client_b.get("/api/factory/quotes", headers={"X-Tenant-Id": "tenant-a"})
    assert listed.status_code == 200
    ids = {item["quoteId"] for item in listed.json()["items"]}
    assert quote_a in ids
    assert quote_b in ids

    state = json.loads((root / "factory" / "state.json").read_text(encoding="utf-8"))
    assert quote_a in state["quotes"]
    assert quote_b in state["quotes"]


def test_restart_restores_parametric_products_and_revision(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    client = TestClient(create_app(plat))
    run = _run(client, "tenant-a")
    cabinet_id = run["assembly"]["cabinets"][0]["cabinetId"]
    assert cabinet_id in plat.parametrics

    rev = client.post(
        f"/api/factory/products/{cabinet_id}/revise",
        json={"width": 920},
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert rev.status_code == 200
    child_id = rev.json()["spec"]["productId"]

    plat2 = Platform(root=root, mock_blender=True)
    client2 = TestClient(create_app(plat2))
    assert cabinet_id in plat2.parametrics
    assert child_id in plat2.parametrics
    assert len(plat2.factory.revisions) >= 1

    state = client2.get("/api/pages/factory/state", headers={"X-Tenant-Id": "tenant-a"})
    assert state.status_code == 200
    body = state.json()
    product_ids = {p["productId"] for p in body["products"]}
    assert cabinet_id in product_ids
    assert child_id in product_ids
    assert body["revisions"]

    again = client2.post(
        f"/api/factory/products/{child_id}/revise",
        json={"width": 940},
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert again.status_code == 200


def test_quote_list_returns_newest_when_over_limit(tmp_path: Path) -> None:
    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    fac = plat.factory
    tenant = "t-limit"
    for idx in range(105):
        stamp = f"2030-06-01T00:{idx // 60:02d}:{idx % 60:02d}+00:00"
        qid = f"quote-{idx:03d}"
        rid = f"run-{idx:03d}"
        fac.quotes[qid] = {"quoteId": qid, "estimatedCost": 1}
        fac.runs[rid] = {
            "runId": rid,
            "tenantId": tenant,
            "createdAt": stamp,
            "quote": {"quoteId": qid},
            "gate": {"status": "WAITING_APPROVAL"},
            "space": {},
            "assembly": {"cabinetCount": 1},
        }
        fac._quote_run_index[qid] = rid

    items = fac.list_quote_summaries(tenant, limit=100)
    assert len(items) == 100
    returned_ids = [item["quoteId"] for item in items]
    assert returned_ids[0] == "quote-104"
    assert "quote-000" not in returned_ids
    assert "quote-004" not in returned_ids