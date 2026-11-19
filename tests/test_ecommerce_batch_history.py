"""Tests for E-Commerce Scene Studio batch history pagination, filtering, and read-only guarantees."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.ecommerce_scene_api import ecommerce_scene_router
from fox3d.ecommerce_scene_studio import EcommerceSceneStore, _tenant_slug


def _write_batch_fixture(
    batches_dir: Path,
    batch_id: str,
    *,
    created_at: str,
    state: str = "completed",
    tenant_id: str = "sonaqueen-home",
    total: int = 1,
    completed: int = 1,
    succeeded: int = 1,
    failed: int = 0,
    mtime: float | None = None,
    extra: dict | None = None,
) -> Path:
    bdir = batches_dir / batch_id
    bdir.mkdir(parents=True, exist_ok=True)
    doc = {
        "batchId": batch_id,
        "tenantId": tenant_id,
        "cabinetName": f"Cabinet {batch_id}",
        "cabinetSku": f"SKU-{batch_id}",
        "createdAt": created_at,
        "state": state,
        "total": total,
        "completed": completed,
        "succeeded": succeeded,
        "failed": failed,
        "items": [],
    }
    if extra:
        doc.update(extra)
    bpath = bdir / "batch.json"
    bpath.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    if mtime is not None:
        os.utime(bpath, (mtime, mtime))
        os.utime(bdir, (mtime, mtime))
    return bpath


@pytest.fixture
def env(tmp_path: Path):
    platform = SimpleNamespace(root=tmp_path, mock_blender=True)
    with patch("fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets"):
        store = EcommerceSceneStore(platform)
    app = FastAPI()
    with patch("fox3d.ecommerce_scene_api.EcommerceSceneStore", return_value=store):
        app.include_router(ecommerce_scene_router(lambda: platform))
        with TestClient(app) as client:
            yield client, store, tmp_path
    store.executor.shutdown(wait=True)
    store.ai_executor.shutdown(wait=True)


def _batches_dir(root: Path, tenant_id: str = "sonaqueen-home") -> Path:
    return root / "ecommerce-scene-studio" / _tenant_slug(tenant_id) / "batches"


def test_paginate_40_fixture_batches_complete_unique_and_sorted_by_created_at(env):
    client, _, root = env
    bdir = _batches_dir(root)
    expected_records: list[tuple[str, str]] = []
    base_mtime = 1_700_000_000.0

    for i in range(40):
        batch_id = f"batch_{i:02d}"
        # Share timestamps on some pairs to verify tie-breaking by batchId when createdAt is equal.
        minute = i // 2
        created_at = f"2026-11-18T10:{minute:02d}:00Z"
        # Deliberately invert mtime (older createdAt gets newer mtime) to prove mtime is not used.
        inv_mtime = base_mtime + (40 - i) * 60
        _write_batch_fixture(bdir, batch_id, created_at=created_at, mtime=inv_mtime)
        expected_records.append((created_at, batch_id))

    expected_ids = [bid for _, bid in sorted(expected_records, reverse=True)]

    collected_ids: list[str] = []
    for offset, expected_len in ((0, 15), (15, 15), (30, 10)):
        resp = client.get(f"/api/ecommerce-scenes/batches?offset={offset}&limit=15")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 40
        assert body["offset"] == offset
        assert body["limit"] == 15
        assert body["skipped"] == 0
        page_ids = [item["batchId"] for item in body["items"]]
        assert len(page_ids) == expected_len
        collected_ids.extend(page_ids)

    assert len(collected_ids) == 40
    assert len(set(collected_ids)) == 40
    assert collected_ids == expected_ids

    # overview.batches uses the same implementation for the first page of 15 items.
    ov = client.get("/api/ecommerce-scenes/overview")
    assert ov.status_code == 200
    ov_ids = [item["batchId"] for item in ov.json()["batches"]]
    assert ov_ids == expected_ids[:15]


def test_updating_old_batch_does_not_change_sort_order(env):
    client, _, root = env
    bdir = _batches_dir(root)
    base_mtime = 1_700_000_000.0
    for i in range(40):
        _write_batch_fixture(
            bdir,
            f"batch_{i:02d}",
            created_at=f"2026-11-18T11:{i:02d}:00Z",
            state="running" if i == 5 else "completed",
            mtime=base_mtime + i * 10,
        )

    def fetch_all_ids() -> list[str]:
        out: list[str] = []
        for offset in (0, 20):
            r = client.get(f"/api/ecommerce-scenes/batches?offset={offset}&limit=20")
            assert r.status_code == 200
            out.extend(x["batchId"] for x in r.json()["items"])
        return out

    before_ids = fetch_all_ids()
    assert len(before_ids) == 40

    # Update an older batch (batch_05) and give it the newest mtime on disk.
    old_path = bdir / "batch_05" / "batch.json"
    doc = json.loads(old_path.read_text(encoding="utf-8"))
    doc["state"] = "completed"
    doc["updatedAt"] = "2026-11-19T23:59:59Z"
    doc["completed"] = 1
    doc["succeeded"] = 1
    old_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    newest_mtime = base_mtime + 999_999
    os.utime(old_path, (newest_mtime, newest_mtime))

    after_ids = fetch_all_ids()
    assert after_ids == before_ids


def test_corrupt_batch_json_increments_skipped_without_500_or_path_leak(env):
    client, _, root = env
    bdir = _batches_dir(root)
    _write_batch_fixture(bdir, "batch_ok_1", created_at="2026-11-18T12:00:00Z")
    _write_batch_fixture(bdir, "batch_ok_2", created_at="2026-11-18T12:01:00Z")

    corrupt_dir = bdir / "batch_corrupt"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    corrupt_path = corrupt_dir / "batch.json"
    corrupt_path.write_text("{not valid json", encoding="utf-8")

    resp = client.get("/api/ecommerce-scenes/batches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped"] == 1
    assert body["total"] == 2
    assert [x["batchId"] for x in body["items"]] == ["batch_ok_2", "batch_ok_1"]
    assert str(root) not in resp.text
    assert str(corrupt_path) not in resp.text
    assert "batch.json" not in resp.text


def test_tenant_isolation_other_tenant_sees_total_zero(env):
    client, _, root = env
    bdir = _batches_dir(root, "sonaqueen-home")
    for i in range(5):
        _write_batch_fixture(bdir, f"batch_{i:02d}", created_at=f"2026-11-18T13:{i:02d}:00Z")

    r_header = client.get("/api/ecommerce-scenes/batches", headers={"X-Tenant-Id": "other-tenant"})
    assert r_header.status_code == 200
    assert r_header.json() == {"items": [], "total": 0, "offset": 0, "limit": 15, "skipped": 0}

    r_ws = client.get("/api/ecommerce-scenes/batches?workspace=other-tenant")
    assert r_ws.status_code == 200
    assert r_ws.json() == {"items": [], "total": 0, "offset": 0, "limit": 15, "skipped": 0}

    assert client.get("/api/ecommerce-scenes/batches", headers={"X-Tenant-Id": "system"}).status_code == 400
    assert client.get("/api/ecommerce-scenes/batches?workspace=system").status_code == 400


@pytest.mark.parametrize(
    "query",
    [
        "state=bogus",
        "state=done",
        "limit=0",
        "limit=-1",
        "limit=51",
        "offset=-1",
        "offset=abc",
        "limit=abc",
    ],
)
def test_invalid_offset_limit_or_state_returns_422(env, query: str):
    client, _, _ = env
    resp = client.get(f"/api/ecommerce-scenes/batches?{query}")
    assert resp.status_code == 422


def test_state_filter_matches_each_batch_state(env):
    client, _, root = env
    bdir = _batches_dir(root)
    _write_batch_fixture(bdir, "b_run", created_at="2026-11-18T14:01:00Z", state="running", completed=0, succeeded=0)
    _write_batch_fixture(bdir, "b_done", created_at="2026-11-18T14:02:00Z", state="completed", completed=1, succeeded=1, failed=0)
    _write_batch_fixture(bdir, "b_fail_direct", created_at="2026-11-18T14:03:00Z", state="failed", completed=1, succeeded=0, failed=1)
    _write_batch_fixture(bdir, "b_fail_counts", created_at="2026-11-18T14:04:00Z", state="completed", completed=1, succeeded=0, failed=1)
    _write_batch_fixture(bdir, "b_cancel", created_at="2026-11-18T14:05:00Z", state="cancelled", completed=1, succeeded=0)
    _write_batch_fixture(bdir, "b_intr", created_at="2026-11-18T14:06:00Z", state="interrupted", completed=1, succeeded=0, failed=1)

    for state, expected in (
        ("running", ["b_run"]),
        ("completed", ["b_done"]),
        ("failed", ["b_fail_counts", "b_fail_direct"]),
        ("cancelled", ["b_cancel"]),
        ("interrupted", ["b_intr"]),
    ):
        resp = client.get(f"/api/ecommerce-scenes/batches?state={state}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == len(expected)
        assert [x["batchId"] for x in body["items"]] == expected


def test_get_batches_does_not_touch_mtimes_or_trigger_recovery(tmp_path: Path):
    platform = SimpleNamespace(root=tmp_path, mock_blender=True)
    with patch("fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets"):
        store = EcommerceSceneStore(platform)

    bdir = _batches_dir(tmp_path)
    fixed_mtime = 1_650_000_000.0
    _write_batch_fixture(
        bdir,
        "b_done",
        created_at="2026-11-18T15:01:00Z",
        state="completed",
        mtime=fixed_mtime,
    )
    _write_batch_fixture(
        bdir,
        "b_stale_running",
        created_at="2026-11-18T15:00:00Z",
        state="running",
        mtime=fixed_mtime,
    )
    os.utime(bdir, (fixed_mtime, fixed_mtime))

    def snapshot_mtimes(base: Path) -> dict[str, int]:
        paths = [base, *sorted(base.rglob("*"))]
        return {str(p.relative_to(base)): p.stat().st_mtime_ns for p in paths}

    app = FastAPI()
    with patch("fox3d.ecommerce_scene_api.EcommerceSceneStore", return_value=store):
        app.include_router(ecommerce_scene_router(lambda: platform))
        with TestClient(app) as client:
            before_first = snapshot_mtimes(bdir)
            r0 = client.get("/api/ecommerce-scenes/batches")
            assert r0.status_code == 200
            assert snapshot_mtimes(bdir) == before_first

            # Even if an unscheduled pending batch appears on disk after startup, GET list/overview never recovers or writes it.
            _write_batch_fixture(
                bdir,
                "b_pending_after_startup",
                created_at="2026-11-18T15:02:00Z",
                state="running",
                mtime=fixed_mtime,
                extra={"scheduleState": "pending", "workerArgs": [{}] * 13},
            )
            os.utime(bdir, (fixed_mtime, fixed_mtime))
            before = snapshot_mtimes(bdir)
            with patch.object(store, "_recover_unscheduled") as recover_spy:
                r1 = client.get("/api/ecommerce-scenes/batches")
                r2 = client.get("/api/ecommerce-scenes/overview")
                assert r1.status_code == 200
                assert r2.status_code == 200
                assert recover_spy.call_count == 0
            after = snapshot_mtimes(bdir)
            assert after == before

    store.executor.shutdown(wait=True)
    store.ai_executor.shutdown(wait=True)


def test_restart_reports_stale_running_batches_as_interrupted_in_list_filters_and_allows_delete(env):
    """After a restart, running batches with no live worker must show as interrupted without opening each one."""
    client, store, root = env
    bdir = _batches_dir(root)
    stale_mtime = 1_650_000_000.0
    stale_ids = ["b_stale_1", "b_stale_2", "b_stale_3"]
    for i, batch_id in enumerate(stale_ids):
        _write_batch_fixture(
            bdir,
            batch_id,
            created_at=f"2026-11-18T16:0{i}:00Z",
            state="running",
            total=2,
            completed=1,
            succeeded=1,
            mtime=stale_mtime,
            extra={
                "items": [
                    {"itemId": "i1", "state": "succeeded", "stage": "done"},
                    {"itemId": "i2", "state": "running", "stage": "render"},
                ]
            },
        )
    # A running batch that was touched just now is still considered alive.
    _write_batch_fixture(bdir, "b_fresh_running", created_at="2026-11-18T16:10:00Z", state="running", completed=0, succeeded=0)
    # A running batch this process still owns stays running however old its file is.
    _write_batch_fixture(bdir, "b_owned_running", created_at="2026-11-18T16:11:00Z", state="running", mtime=stale_mtime)
    store._live_docs["b_owned_running"] = {"batchId": "b_owned_running", "state": "running"}

    def snapshot() -> dict[str, int]:
        return {str(p.relative_to(bdir)): p.stat().st_mtime_ns for p in sorted(bdir.rglob("*"))}

    before = snapshot()

    full = client.get("/api/ecommerce-scenes/batches").json()
    by_id = {x["batchId"]: x for x in full["items"]}
    for batch_id in stale_ids:
        row = by_id[batch_id]
        assert row["state"] == "interrupted"
        assert row["failed"] == 1 and row["succeeded"] == 1 and row["completed"] == 2
        assert [it["state"] for it in row["items"]] == ["succeeded", "failed"]
    assert by_id["b_fresh_running"]["state"] == "running"
    assert by_id["b_owned_running"]["state"] == "running"

    running = client.get("/api/ecommerce-scenes/batches?state=running").json()
    assert running["total"] == 2
    assert sorted(x["batchId"] for x in running["items"]) == ["b_fresh_running", "b_owned_running"]

    interrupted = client.get("/api/ecommerce-scenes/batches?state=interrupted").json()
    assert interrupted["total"] == 3
    assert [x["batchId"] for x in interrupted["items"]] == list(reversed(stale_ids))

    overview_states = {x["batchId"]: x["state"] for x in client.get("/api/ecommerce-scenes/overview").json()["batches"]}
    assert all(overview_states[b] == "interrupted" for b in stale_ids)

    # Listing is read-only: nothing on disk changed, the raw file still says running.
    assert snapshot() == before
    assert json.loads((bdir / "b_stale_1" / "batch.json").read_text(encoding="utf-8"))["state"] == "running"

    # The stale batch the list offers for deletion can actually be deleted; a live one cannot.
    resp = client.delete("/api/ecommerce-scenes/batches/b_stale_2")
    assert resp.status_code == 200, resp.text
    assert not (bdir / "b_stale_2").exists()
    assert client.delete("/api/ecommerce-scenes/batches/b_fresh_running").status_code == 409

    after = client.get("/api/ecommerce-scenes/batches?state=interrupted").json()
    assert after["total"] == 2
    assert [x["batchId"] for x in after["items"]] == ["b_stale_3", "b_stale_1"]
