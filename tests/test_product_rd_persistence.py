"""Persistence, pagination, idempotency, concurrency, tenant isolation, and input validation tests for Product R&D."""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.ids import stable_hash
from fox3d.platform import Platform
from fox3d.storelock import CrashInjected

TENANT_A = {"X-Tenant-Id": "tenant-alpha"}
TENANT_B = {"X-Tenant-Id": "tenant-beta"}


def _make_client(root: Path) -> tuple[Platform, TestClient]:
    plat = Platform(root=root, mock_blender=True)
    return plat, TestClient(create_app(plat), raise_server_exceptions=False)


def test_generate_persists_per_tenant_across_restart(tmp_path: Path) -> None:
    _, client1 = _make_client(tmp_path)

    res_a1 = client1.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "玄關 寬80cm 高120cm 白木紋鞋櫃 雙門 四層", "variantCount": 10},
    )
    assert res_a1.status_code == 200, res_a1.text
    rd_a1 = res_a1.json()

    res_a2 = client1.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "書房 寬100cm 高180cm 書櫃 四層", "variantCount": 11},
    )
    assert res_a2.status_code == 200, res_a2.text
    rd_a2 = res_a2.json()

    res_b1 = client1.post(
        "/api/product-rd/generate",
        headers=TENANT_B,
        json={"text": "臥室 寬120cm 高220cm 衣櫃 雙門", "variantCount": 10},
    )
    assert res_b1.status_code == 200, res_b1.text
    rd_b1 = res_b1.json()

    # Recreate Platform + FastAPI app from the same disk root (simulated process restart).
    _, client2 = _make_client(tmp_path)

    list_a = client2.get("/api/product-rd/results", headers=TENANT_A)
    assert list_a.status_code == 200
    body_a = list_a.json()
    assert body_a["total"] == 2
    assert [item["rdId"] for item in body_a["items"]] == [rd_a2["rdId"], rd_a1["rdId"]]

    detail_a1 = client2.get(f"/api/product-rd/results/{rd_a1['rdId']}", headers=TENANT_A)
    assert detail_a1.status_code == 200
    d_a1 = detail_a1.json()
    assert d_a1["rdId"] == rd_a1["rdId"]
    assert d_a1["tenantId"] == "tenant-alpha"
    assert d_a1["text"] == "玄關 寬80cm 高120cm 白木紋鞋櫃 雙門 四層"
    assert d_a1["approval"]["status"] == "WAITING_APPROVAL"
    assert d_a1["approvedAt"] is None
    assert d_a1["baseSpec"] == rd_a1["baseSpec"]
    assert d_a1["parametricRender"]["job"]["jobId"] == rd_a1["parametricRender"]["job"]["jobId"]

    list_b = client2.get("/api/product-rd/results", headers=TENANT_B)
    assert list_b.status_code == 200
    assert [item["rdId"] for item in list_b.json()["items"]] == [rd_b1["rdId"]]

    list_empty = client2.get("/api/product-rd/results", headers={"X-Tenant-Id": "tenant-empty"})
    assert list_empty.status_code == 200
    assert list_empty.json()["items"] == []
    assert list_empty.json()["total"] == 0


def test_atomic_write_leaves_no_temp_files_and_survives_failed_write_or_corrupt_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat, client = _make_client(tmp_path)
    ok = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "客廳 寬180cm 電視櫃 雙門", "variantCount": 10},
    )
    assert ok.status_code == 200
    rd_id = ok.json()["rdId"]

    rd_root = tmp_path / "product_rd"
    assert list(rd_root.rglob("*.tmp")) == []

    # Simulate crash during publish_bytes on a second generate: store must have no partial file.
    import fox3d.product_rd_store as store_mod

    orig_publish = store_mod.publish_bytes

    def _crash_publish(writer: Any, target: Path, **kwargs: Any) -> dict[str, Any]:
        raise CrashInjected("simulated crash before os.replace")

    monkeypatch.setattr(store_mod, "publish_bytes", _crash_publish)
    with pytest.raises(CrashInjected):
        plat.product_rd(tenant_id="tenant-alpha", text="書櫃 90cm", variant_count=10)
    monkeypatch.setattr(store_mod, "publish_bytes", orig_publish)

    assert list(rd_root.rglob("*.tmp")) == []
    _, restarted = _make_client(tmp_path)
    listed = restarted.get("/api/product-rd/results", headers=TENANT_A).json()
    assert [item["rdId"] for item in listed["items"]] == [rd_id]

    # Corrupt sibling JSON file must be skipped cleanly without breaking list or valid get.
    tenant_dir = rd_root / stable_hash("tenant-alpha")
    (tenant_dir / "corrupt_record.json").write_text("{broken json", encoding="utf-8")
    _, restarted2 = _make_client(tmp_path)
    listed2 = restarted2.get("/api/product-rd/results", headers=TENANT_A)
    assert listed2.status_code == 200
    assert listed2.json()["skipped"] == 1
    assert [item["rdId"] for item in listed2.json()["items"]] == [rd_id]
    assert restarted2.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A).status_code == 200


def test_generate_idempotency_concurrent_restart_conflict_and_tenant_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat1, client1 = _make_client(tmp_path)
    plat2, client2 = _make_client(tmp_path)

    run_count = 0
    count_lock = threading.Lock()
    orig_run = plat1.rd.run
    orig_run2 = plat2.rd.run

    def _counted_run_1(**kwargs: Any) -> dict[str, Any]:
        nonlocal run_count
        with count_lock:
            run_count += 1
        return orig_run(**kwargs)

    def _counted_run_2(**kwargs: Any) -> dict[str, Any]:
        nonlocal run_count
        with count_lock:
            run_count += 1
        return orig_run2(**kwargs)

    monkeypatch.setattr(plat1.rd, "run", _counted_run_1)
    monkeypatch.setattr(plat2.rd, "run", _counted_run_2)

    body = {
        "text": "客廳 寬160cm 奶油風電視櫃 雙門 掃地機器人",
        "variantCount": 10,
        "idempotencyKey": "idem-rd-001",
    }
    barrier = threading.Barrier(6)
    clients = [client1, client2, client1, client2, client1, client2]

    def _send(c: TestClient) -> Any:
        barrier.wait()
        return c.post("/api/product-rd/generate", headers=TENANT_A, json=body)

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(_send, clients))

    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    rd_ids = {r.json()["rdId"] for r in responses}
    assert len(rd_ids) == 1
    assert run_count == 1
    winner_id = next(iter(rd_ids))

    # Restart and resend the same idempotencyKey -> returns the exact same rdId, still no new run.
    plat3, client3 = _make_client(tmp_path)
    monkeypatch.setattr(
        plat3.rd,
        "run",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("should not re-run for idempotent replay")),
    )
    replay = client3.post("/api/product-rd/generate", headers=TENANT_A, json=body)
    assert replay.status_code == 200
    assert replay.json()["rdId"] == winner_id
    assert client3.get("/api/product-rd/results", headers=TENANT_A).json()["total"] == 1

    # Different parameters with same idempotencyKey -> 409 Conflict.
    conflict_text = client3.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={**body, "text": "書房 寬90cm 書櫃 四層"},
    )
    assert conflict_text.status_code == 409
    conflict_count = client3.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={**body, "variantCount": 12},
    )
    assert conflict_count.status_code == 409

    # Another tenant using the same idempotencyKey gets its own isolated record.
    _, client_other = _make_client(tmp_path)
    other_res = client_other.post("/api/product-rd/generate", headers=TENANT_B, json=body)
    assert other_res.status_code == 200
    assert other_res.json()["rdId"] != winner_id


def test_results_pagination_by_created_at_offset_and_cursor_and_approve_keeps_order(tmp_path: Path) -> None:
    plat, client = _make_client(tmp_path)
    template = plat.rd.run(tenant_id="tenant-alpha", text="書櫃 80cm", variant_count=10)

    tenant_dir = tmp_path / "product_rd" / stable_hash("tenant-alpha")
    tenant_dir.mkdir(parents=True, exist_ok=True)

    expected_pairs: list[tuple[str, str]] = []
    base_mtime = 1_700_000_000.0
    for i in range(25):
        rd_id = f"rd-item-{i:02d}"
        minute = i // 2  # Intentional timestamp ties to exercise deterministic rdId tie-breaking
        created_at = f"2026-11-19T10:{minute:02d}:00.000000Z"
        rec = {
            **template,
            "rdId": rd_id,
            "tenantId": "tenant-alpha",
            "createdAt": created_at,
            "text": f"方案 {i:02d}",
            "requestedVariantCount": 10,
            "judgeLabel": "MOCK",
            "scoringStatus": "MOCK",
            "truthLabel": "MOCK",
            "HUMAN_APPROVAL_REQUIRED": True,
            "liveMachineControl": False,
            "approvedAt": None,
            "approval": {
                "status": "WAITING_APPROVAL",
                "HUMAN_APPROVAL_REQUIRED": True,
                "autoApproveForbiddenForProduction": True,
                "liveMachineControl": False,
                "approvedAt": None,
                "actor": None,
                "judgeLabel": "MOCK",
            },
        }
        fpath = tenant_dir / f"{stable_hash(rd_id)}.json"
        fpath.write_text(json.dumps(rec, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        # Invert mtime so older createdAt has newer mtime on disk.
        inv_mtime = base_mtime + (30 - i) * 60
        os.utime(fpath, (inv_mtime, inv_mtime))
        expected_pairs.append((created_at, rd_id))

    expected_ids = [rid for _, rid in sorted(expected_pairs, reverse=True)]

    # 1. Offset pagination
    offset_ids: list[str] = []
    for offset, exp_len, exp_more in ((0, 10, True), (10, 10, True), (20, 5, False)):
        r = client.get(f"/api/product-rd/results?offset={offset}&limit=10", headers=TENANT_A)
        assert r.status_code == 200
        page = r.json()
        assert page["total"] == 25
        assert page["offset"] == offset
        assert page["limit"] == 10
        assert page["hasMore"] is exp_more
        assert (page["nextCursor"] is not None) is exp_more
        ids = [x["rdId"] for x in page["items"]]
        assert len(ids) == exp_len
        offset_ids.extend(ids)
    assert offset_ids == expected_ids

    # 2. Cursor pagination
    cursor_ids: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        qs = f"?limit=7&cursor={cursor}" if cursor else "?limit=7"
        r = client.get(f"/api/product-rd/results{qs}", headers=TENANT_A)
        assert r.status_code == 200
        body = r.json()
        cursor_ids.extend(x["rdId"] for x in body["items"])
        pages += 1
        assert pages <= 10
        if not body["nextCursor"]:
            assert body["hasMore"] is False
            break
        cursor = body["nextCursor"]
    assert cursor_ids == expected_ids

    # 3. Approving an older item updates its file mtime and approvedAt, but must NOT move its createdAt sort rank.
    oldest_id = expected_ids[-1]
    ap = client.post(
        f"/api/product-rd/results/{oldest_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "reviewer"},
    )
    assert ap.status_code == 200
    after_ids: list[str] = []
    for offset in (0, 10, 20):
        r = client.get(f"/api/product-rd/results?offset={offset}&limit=10", headers=TENANT_A)
        after_ids.extend(x["rdId"] for x in r.json()["items"])
    assert after_ids == expected_ids

    # 4. Cross-tenant cursor must never drop or leak Tenant B's items; bad pagination params -> 422.
    res_b = client.post(
        "/api/product-rd/generate",
        headers=TENANT_B,
        json={"text": "鞋櫃 80cm", "variantCount": 10},
    )
    assert res_b.status_code == 200
    first_a_cursor = client.get("/api/product-rd/results?limit=5", headers=TENANT_A).json()["nextCursor"]
    assert first_a_cursor
    b_with_a_cursor = client.get(
        f"/api/product-rd/results?limit=5&cursor={first_a_cursor}", headers=TENANT_B
    )
    assert b_with_a_cursor.status_code == 200
    assert [x["rdId"] for x in b_with_a_cursor.json()["items"]] == [res_b.json()["rdId"]]

    # Composite cursor whose anchor rdId exists in Tenant A but with a forged/mismatched timestamp falls back safely.
    tok_a = first_a_cursor.split("|")[0]
    forged_cursor = f"{tok_a}|1999-01-01T00:00:00.000000Z|{expected_ids[0]}"
    a_forged = client.get(f"/api/product-rd/results?offset=0&limit=5&cursor={forged_cursor}", headers=TENANT_A)
    assert a_forged.status_code == 200
    assert [x["rdId"] for x in a_forged.json()["items"]] == expected_ids[:5]

    for bad_qs in ("?limit=0", "?limit=101", "?offset=-1", f"?cursor={'c' * 201}"):
        bad_res = client.get(f"/api/product-rd/results{bad_qs}", headers=TENANT_A)
        assert bad_res.status_code == 422, bad_qs


def test_approve_requires_confirm_and_idempotent_resend_keeps_approved_at(tmp_path: Path) -> None:
    _, client = _make_client(tmp_path)
    gen = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "客廳 寬150cm 電視櫃 雙門", "variantCount": 10},
    )
    assert gen.status_code == 200
    rd_id = gen.json()["rdId"]

    bad_confirm_cases: tuple[dict[str, Any], ...] = (
        {},
        {"confirm": False},
        {"confirm": 0},
        {"confirm": ""},
        {"confirm": "false"},
        {"confirm": "yes"},
        {"confirm": None},
        {"confirm": []},
        {"confirm": {}},
        {"confirm": 1.0},
    )
    for bad_confirm in bad_confirm_cases:
        resp = client.post(
            f"/api/product-rd/results/{rd_id}/approve",
            headers=TENANT_A,
            json=bad_confirm,
        )
        assert resp.status_code == 422, f"expected 422 for {bad_confirm!r}, got {resp.status_code}"

    # Still WAITING_APPROVAL before valid confirm
    still_waiting = client.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A).json()
    assert still_waiting["approval"]["status"] == "WAITING_APPROVAL"
    assert still_waiting["approvedAt"] is None

    first = client.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "chief-designer"},
    )
    assert first.status_code == 200, first.text
    first_data = first.json()
    approved_at = first_data["approvedAt"]
    assert isinstance(approved_at, str) and approved_at.endswith("Z")
    assert first_data["approval"]["status"] == "APPROVED"
    assert first_data["approval"]["approvedAt"] == approved_at
    assert first_data["approval"]["actor"] == "chief-designer"
    assert first_data["productionAssets"]

    # Immediate resend with different actor returns original approvedAt and original actor.
    second = client.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "second-actor"},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["approvedAt"] == approved_at
    assert second_data["approval"]["approvedAt"] == approved_at
    assert second_data["approval"]["actor"] == "chief-designer"

    # Restart Platform and resend again -> still returns original approvedAt, and missing confirm still 422.
    _, restarted = _make_client(tmp_path)
    no_confirm_after = restarted.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={},
    )
    assert no_confirm_after.status_code == 422

    third = restarted.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "third-actor"},
    )
    assert third.status_code == 200
    assert third.json()["approvedAt"] == approved_at
    assert third.json()["approval"]["approvedAt"] == approved_at
    assert third.json()["approval"]["actor"] == "chief-designer"


def test_concurrent_approve_executes_once_across_threads_and_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat1, client1 = _make_client(tmp_path)
    plat2, client2 = _make_client(tmp_path)

    created = client1.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "書房 寬100cm 書櫃 四層", "variantCount": 10},
    ).json()
    rd_id = created["rdId"]

    approve_calls = 0
    call_lock = threading.Lock()
    orig1 = plat1.rd.approve
    orig2 = plat2.rd.approve

    def _spy1(rec: dict[str, Any], *, actor: str) -> dict[str, Any]:
        nonlocal approve_calls
        with call_lock:
            approve_calls += 1
        return orig1(rec, actor=actor)

    def _spy2(rec: dict[str, Any], *, actor: str) -> dict[str, Any]:
        nonlocal approve_calls
        with call_lock:
            approve_calls += 1
        return orig2(rec, actor=actor)

    monkeypatch.setattr(plat1.rd, "approve", _spy1)
    monkeypatch.setattr(plat2.rd, "approve", _spy2)

    barrier = threading.Barrier(6)
    targets = [(client1, f"actor-{i}") if i % 2 == 0 else (client2, f"actor-{i}") for i in range(6)]

    def _fire(pair: tuple[TestClient, str]) -> Any:
        c, actor = pair
        barrier.wait()
        return c.post(
            f"/api/product-rd/results/{rd_id}/approve",
            headers=TENANT_A,
            json={"confirm": True, "actor": actor},
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_fire, targets))

    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert approve_calls == 1
    approved_ats = {r.json()["approvedAt"] for r in results}
    actors = {r.json()["approval"]["actor"] for r in results}
    assert len(approved_ats) == 1
    assert len(actors) == 1

    _, restarted = _make_client(tmp_path)
    persisted = restarted.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A).json()
    assert persisted["approvedAt"] == next(iter(approved_ats))
    assert persisted["approval"]["actor"] == next(iter(actors))


def test_mock_scored_scheme_remains_labeled_mock_after_approve_and_restart(tmp_path: Path) -> None:
    _, client = _make_client(tmp_path)
    gen = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "臥室 寬120cm 高200cm 衣櫃 雙門", "variantCount": 10},
    ).json()
    rd_id = gen["rdId"]
    assert gen["judgeLabel"] == "MOCK"
    assert gen["scoringStatus"] == "MOCK"
    assert gen["truthLabel"] == "MOCK"
    assert all(row["judge"]["label"] == "MOCK" for row in gen["top"])

    approved = client.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "rd-director"},
    ).json()
    assert approved["approval"]["status"] == "APPROVED"
    assert approved["approvedAt"]
    assert approved["judgeLabel"] == "MOCK"
    assert approved["scoringStatus"] == "MOCK"
    assert approved["truthLabel"] == "MOCK"
    assert approved["approval"]["judgeLabel"] == "MOCK"
    assert all(row["judge"]["label"] == "MOCK" for row in approved["top"])
    assert approved["productionAssets"]
    assert all(asset["judgeLabel"] == "MOCK" for asset in approved["productionAssets"])

    _, restarted = _make_client(tmp_path)
    fetched = restarted.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A).json()
    assert fetched["approval"]["status"] == "APPROVED"
    assert fetched["judgeLabel"] == "MOCK"
    assert fetched["approval"]["judgeLabel"] == "MOCK"
    assert all(row["judge"]["label"] == "MOCK" for row in fetched["top"])

    listed_item = restarted.get("/api/product-rd/results", headers=TENANT_A).json()["items"][0]
    assert listed_item["approval"]["status"] == "APPROVED"
    assert listed_item["judgeLabel"] == "MOCK"


def test_cross_tenant_and_unknown_ids_return_404(tmp_path: Path) -> None:
    _, client = _make_client(tmp_path)
    created = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "玄關 寬90cm 鞋櫃 雙門", "variantCount": 10},
    ).json()
    rd_id = created["rdId"]

    for target_id in (rd_id, "missing-rd-id", "..traversal", "id with spaces", "x" * 80):
        get_b = client.get(f"/api/product-rd/results/{target_id}", headers=TENANT_B)
        assert get_b.status_code == 404, target_id
        assert get_b.json() == {"detail": "找不到研發方案"}

        for body in ({}, {"confirm": True, "actor": "intruder"}):
            post_b = client.post(
                f"/api/product-rd/results/{target_id}/approve",
                headers=TENANT_B,
                json=body,
            )
            assert post_b.status_code == 404, (target_id, body)
            assert post_b.json() == {"detail": "找不到研發方案"}

    assert client.get("/api/product-rd/results/../traversal", headers=TENANT_B).status_code == 404

    # Tenant A's record was untouched by Tenant B's approve attempts.
    intact = client.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A).json()
    assert intact["approval"]["status"] == "WAITING_APPROVAL"

    # Body tenantId mismatch on approve -> 403; non-string tenantId -> 422.
    mismatch = client.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"tenantId": "tenant-beta", "confirm": True},
    )
    assert mismatch.status_code == 403
    non_str_tid = client.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"tenantId": ["bad"], "confirm": True},
    )
    assert non_str_tid.status_code == 422


@pytest.mark.parametrize(
    "bad_body",
    [
        {"text": 123},
        {"text": 0},
        {"text": True},
        {"text": False},
        {"text": ["書櫃"]},
        {"text": {"q": "書櫃"}},
        {"text": "書櫃\x00衣櫃"},
        {"text": "高" + ("9" * 400) + "cm"},
        {"text": "預算 " + ("9" * 400)},
        {"variantCount": 0},
        {"variantCount": -1},
        {"variantCount": 101},
        {"variantCount": 100000},
        {"variantCount": 12.5},
        {"variantCount": True},
        {"variantCount": False},
        {"variantCount": "12"},
        {"variantCount": [12]},
        {"variantCount": {"n": 12}},
        {"idempotencyKey": ""},
        {"idempotencyKey": "   "},
        {"idempotencyKey": "k" * 201},
        {"idempotencyKey": 99},
        {"idempotencyKey": True},
        {"idempotencyKey": ["k"]},
        {"idempotencyKey": "bad\nkey"},
    ],
)
def test_generate_bad_inputs_return_422_and_do_not_persist(tmp_path: Path, bad_body: dict[str, Any]) -> None:
    _, client = _make_client(tmp_path)
    res = client.post("/api/product-rd/generate", headers=TENANT_A, json=bad_body)
    assert res.status_code == 422, f"expected 422 for {bad_body!r}, got {res.status_code}: {res.text}"
    assert "traceback" not in res.text.lower()
    assert str(tmp_path) not in res.text
    assert client.get("/api/product-rd/results", headers=TENANT_A).json()["total"] == 0


def test_generate_backward_compatible_variant_count_null_and_empty_text(tmp_path: Path) -> None:
    _, client = _make_client(tmp_path)

    # Legacy range 1..100 (including <10 like 1, 5, 9 and >50 like 51, 100) must succeed and persist.
    for count in (1, 5, 9, 51, 100):
        res = client.post(
            "/api/product-rd/generate",
            headers=TENANT_A,
            json={"text": "書櫃", "variantCount": count},
        )
        assert res.status_code == 200, (count, res.text)
        data = res.json()
        assert data["requestedVariantCount"] == count
        assert data["text"] == "書櫃"
        assert data["approval"]["status"] == "WAITING_APPROVAL"
        assert client.get(f"/api/product-rd/results/{data['rdId']}", headers=TENANT_A).status_code == 200

    # Explicit null variantCount and omitted variantCount both default to 12.
    null_vc = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "書櫃", "variantCount": None},
    )
    assert null_vc.status_code == 200, null_vc.text
    assert null_vc.json()["requestedVariantCount"] == 12

    omitted_vc = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "書櫃"},
    )
    assert omitted_vc.status_code == 200, omitted_vc.text
    assert omitted_vc.json()["requestedVariantCount"] == 12

    # Empty, whitespace-only, explicit null, and omitted text are accepted per legacy contract.
    for legacy_body, expected_text in (
        ({}, ""),
        ({"text": None}, ""),
        ({"text": ""}, ""),
        ({"text": "   "}, "   "),
        ({"text": None, "variantCount": None}, ""),
        ({"text": "", "variantCount": 5}, ""),
    ):
        resp = client.post("/api/product-rd/generate", headers=TENANT_A, json=legacy_body)
        assert resp.status_code == 200, (legacy_body, resp.text)
        payload = resp.json()
        assert payload["text"] == expected_text
        assert payload["baseSpec"]["kind"] == "CABINET"

    # Normalized null/omitted/default inputs share the same idempotency fingerprint; different count conflicts.
    idem_null = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": None, "variantCount": None, "idempotencyKey": "legacy-idem-null"},
    )
    assert idem_null.status_code == 200
    idem_explicit = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "", "variantCount": 12, "idempotencyKey": "legacy-idem-null"},
    )
    assert idem_explicit.status_code == 200
    assert idem_explicit.json()["rdId"] == idem_null.json()["rdId"]

    idem_conflict = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "", "variantCount": 5, "idempotencyKey": "legacy-idem-null"},
    )
    assert idem_conflict.status_code == 409

    # Tenant isolation holds for legacy inputs as well.
    assert client.get(f"/api/product-rd/results/{idem_null.json()['rdId']}", headers=TENANT_B).status_code == 404


@pytest.mark.parametrize(
    "long_text",
    [
        "書櫃" + ("甲" * 2000),
        "書櫃 " + ("x" * 5000),
        "客廳 寬180cm 電視櫃 " + ("奶油風 " * 1500),
    ],
)
def test_generate_accepts_long_text_like_legacy_contract(tmp_path: Path, long_text: str) -> None:
    """Legacy /api/product-rd/generate never capped text length; long requests must still succeed and persist."""
    plat, client = _make_client(tmp_path)

    # The legacy generator itself handles this text directly.
    direct = plat.rd.run(tenant_id="tenant-alpha", text=long_text, variant_count=1)
    assert direct["baseSpec"]["kind"]

    res = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": long_text, "variantCount": 1, "idempotencyKey": "long-text-1"},
    )
    assert res.status_code == 200, res.text[:500]
    data = res.json()
    assert data["requestedVariantCount"] == 1
    assert data["text"] == long_text
    assert data["baseSpec"]["kind"] == direct["baseSpec"]["kind"]

    # Persisted verbatim, survives restart, idempotent resend returns the same record, tenant-scoped.
    _, client2 = _make_client(tmp_path)
    detail = client2.get(f"/api/product-rd/results/{data['rdId']}", headers=TENANT_A)
    assert detail.status_code == 200
    assert detail.json()["text"] == long_text
    again = client2.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": long_text, "variantCount": 1, "idempotencyKey": "long-text-1"},
    )
    assert again.status_code == 200
    assert again.json()["rdId"] == data["rdId"]
    assert client2.get("/api/product-rd/results", headers=TENANT_A).json()["total"] == 1
    assert client2.get(f"/api/product-rd/results/{data['rdId']}", headers=TENANT_B).status_code == 404



def test_non_terminal_or_failed_render_job_never_marks_truth_label_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat, client = _make_client(tmp_path)
    monkeypatch.setattr(plat.gateway, "_vision_adapters", {"live": lambda _p: {"composition": 0.9}})

    for non_done_status in ("queued", "failed", "retry_scheduled"):
        monkeypatch.setattr(
            plat,
            "render_parametric",
            lambda pid, *, tenant_id: {
                "parametric": {"spec": {"productId": pid}},
                "job": {
                    "jobId": f"job-{non_done_status}",
                    "status": non_done_status,
                    "error": "worker transient crash",
                    "attemptCount": 1,
                    "realBlender": True,
                    "usedMock": False,
                },
            },
        )
        res = client.post(
            "/api/product-rd/generate",
            headers=TENANT_A,
            json={"text": "電視櫃 180cm", "variantCount": 5},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["judgeLabel"] == "REAL"
        assert body["truthLabel"] == "MOCK", f"status={non_done_status} must not claim REAL truthLabel"


def test_fail_or_retry_actual_render_job_shape_persists_across_restart_and_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fox3d.blender import RuntimeResult

    plat, client = _make_client(tmp_path)
    monkeypatch.setattr(plat.gateway, "_vision_adapters", {"live": lambda _p: {"composition": 0.9}})

    def _crash_real_blender(job: dict[str, Any], **kwargs: Any) -> RuntimeResult:
        return RuntimeResult(
            status="failed",
            outputs={},
            error="OPTIX_DEVICE_LOST",
            real_blender=True,
            real_optix=True,
            real_cycles=True,
            real_render_output=False,
            used_mock=False,
            blender_version="4.2.0",
        )

    monkeypatch.setattr(plat.runtime, "run_job", _crash_real_blender)

    gen = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "客廳 寬160cm 電視櫃 雙門", "variantCount": 10},
    )
    assert gen.status_code == 200, gen.text
    created = gen.json()
    rd_id = created["rdId"]
    job = created["parametricRender"]["job"]

    # Verify exact _fail_or_retry shape when attempts < maxAttempts.
    assert job["status"] == "queued"
    assert job["error"] == "OPTIX_DEVICE_LOST"
    assert job["attemptCount"] == 1
    assert job["maxAttempts"] == 3
    assert job["retryDelaySeconds"] > 0
    assert job["realBlender"] is True
    assert job["usedMock"] is False
    assert job["output"] == {}
    assert created["truthLabel"] == "MOCK"

    # Restart and verify list, get, approve, and cross-tenant isolation preserve the exact queued+error job shape.
    _, restarted = _make_client(tmp_path)
    listed = restarted.get("/api/product-rd/results", headers=TENANT_A).json()["items"]
    assert len(listed) == 1
    assert listed[0]["parametricRender"]["job"]["status"] == "queued"
    assert listed[0]["parametricRender"]["job"]["error"] == "OPTIX_DEVICE_LOST"
    assert listed[0]["parametricRender"]["job"]["attemptCount"] == 1

    approved = restarted.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "rd-supervisor"},
    )
    assert approved.status_code == 200
    app_body = approved.json()
    assert app_body["approval"]["status"] == "APPROVED"
    assert app_body["truthLabel"] == "MOCK"
    assert app_body["parametricRender"]["job"]["status"] == "queued"
    assert app_body["parametricRender"]["job"]["error"] == "OPTIX_DEVICE_LOST"
    assert app_body["parametricRender"]["job"]["attemptCount"] == 1

    assert restarted.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_B).status_code == 404


def _runtime_result(status: str, *, error: str | None = None, used_mock: bool = True) -> Any:
    from fox3d.blender import RuntimeResult

    return RuntimeResult(
        status=status,
        outputs={},
        error=error,
        real_blender=not used_mock,
        real_optix=not used_mock,
        real_cycles=not used_mock,
        real_render_output=False,
        used_mock=used_mock,
        blender_version="4.2.0",
    )


def _generate_with_queued_retry(
    plat: Platform, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, Any]:
    """Generate an R&D scheme whose base render fails once and is requeued by _fail_or_retry."""
    monkeypatch.setattr(plat.gateway, "_vision_adapters", {"live": lambda _p: {"composition": 0.9}})
    orig_run_job = plat.runtime.run_job
    monkeypatch.setattr(
        plat.runtime,
        "run_job",
        lambda job, **kw: _runtime_result("failed", error="OPTIX_DEVICE_LOST", used_mock=False),
    )
    gen = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "客廳 寬160cm 電視櫃 雙門", "variantCount": 10},
    )
    assert gen.status_code == 200, gen.text
    body = gen.json()
    job = body["parametricRender"]["job"]
    assert job["status"] == "queued"
    assert job["attemptCount"] == 1
    assert body["parametricRender"]["jobStatusSource"] == "LIVE"
    return body["rdId"], job["jobId"], orig_run_job


def _render_job(body: dict[str, Any]) -> dict[str, Any]:
    job = body["parametricRender"]["job"]
    assert isinstance(job, dict)
    return job


def test_rd_reads_show_live_render_status_after_queued_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat, client = _make_client(tmp_path)
    rd_id, job_id, orig_run_job = _generate_with_queued_retry(plat, client, monkeypatch)

    # The worker retries the queued job and this time the (mock) render succeeds.
    monkeypatch.setattr(plat.runtime, "run_job", orig_run_job)
    retried = plat.run_next()
    assert retried is not None and retried["jobId"] == job_id
    assert retried["status"] == "succeeded"

    # The stored R&D record still holds the generation-time snapshot ...
    stored = plat.rd_store.get("tenant-alpha", rd_id)
    assert stored["parametricRender"]["job"]["status"] == "queued"

    # ... but list, get and approve report the current queue state.
    listed = client.get("/api/product-rd/results", headers=TENANT_A).json()["items"]
    assert len(listed) == 1
    assert _render_job(listed[0])["status"] == "succeeded"
    assert listed[0]["parametricRender"]["jobStatusSource"] == "LIVE"

    got = client.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A).json()
    assert _render_job(got)["status"] == "succeeded"

    approved = client.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "rd-supervisor"},
    )
    assert approved.status_code == 200, approved.text
    app_body = approved.json()
    assert app_body["approval"]["status"] == "APPROVED"
    assert _render_job(app_body)["status"] == "succeeded"
    assert app_body["parametricRender"]["jobStatusSource"] == "LIVE"
    # truthLabel is never upgraded by a later retry; it stays the conservative generation-time value.
    assert app_body["truthLabel"] == "MOCK"

    # Restart: the queue is reloaded from disk, so the live state survives a process restart.
    _, restarted = _make_client(tmp_path)
    after = restarted.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A).json()
    assert _render_job(after)["status"] == "succeeded"
    assert after["approval"]["status"] == "APPROVED"

    # Another tenant still gets nothing.
    assert restarted.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_B).status_code == 404
    assert restarted.get("/api/product-rd/results", headers=TENANT_B).json()["items"] == []


def test_rd_reads_use_another_queue_instances_persisted_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fox3d.infra import JobQueue

    plat, client = _make_client(tmp_path)
    rd_id, job_id, _ = _generate_with_queued_retry(plat, client, monkeypatch)
    worker = JobQueue(tmp_path / "render_core" / "jobs")
    worker.set_status(job_id, "reserved")
    worker.set_status(job_id, "running")
    worker.set_status(job_id, "succeeded")
    cached = plat.queue.get(job_id)
    assert cached is not None and cached["status"] == "queued"
    body = client.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A).json()
    assert _render_job(body)["status"] == "succeeded"
    assert body["parametricRender"]["jobStatusSource"] == "LIVE"
    assert client.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_B).status_code == 404


def test_rd_reads_show_terminal_failure_after_retries_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat, client = _make_client(tmp_path)
    rd_id, job_id, _ = _generate_with_queued_retry(plat, client, monkeypatch)

    # Attempts 2 and 3 fail as well -> the job ends terminally failed.
    second = plat.run_next()
    assert second is not None and second["status"] == "queued" and second["attemptCount"] == 2
    third = plat.run_next()
    assert third is not None and third["jobId"] == job_id
    assert third["status"] == "failed" and third["attemptCount"] == 3

    _, restarted = _make_client(tmp_path)
    listed = restarted.get("/api/product-rd/results", headers=TENANT_A).json()["items"]
    job = _render_job(listed[0])
    assert job["status"] == "failed"
    assert job["error"] == "OPTIX_DEVICE_LOST"
    assert job["attemptCount"] == 3

    approved = restarted.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "rd-supervisor"},
    )
    assert approved.status_code == 200, approved.text
    assert _render_job(approved.json())["status"] == "failed"
    assert approved.json()["truthLabel"] == "MOCK"


def test_rd_render_status_falls_back_to_marked_snapshot_when_job_missing_or_foreign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat, client = _make_client(tmp_path)
    rd_id, job_id, _ = _generate_with_queued_retry(plat, client, monkeypatch)

    # Job disappears from the queue (e.g. purged): reads keep the snapshot and say so.
    live_job = plat.queue._jobs.pop(job_id)
    assert plat.queue._store is not None
    plat.queue._store.delete("tenant-alpha", job_id)
    got = client.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A)
    assert got.status_code == 200
    body = got.json()
    assert body["parametricRender"]["jobStatusSource"] == "SNAPSHOT"
    assert _render_job(body)["status"] == "queued"
    assert _render_job(body)["jobId"] == job_id

    # A job ID that resolves to another tenant's job is never overlaid onto this record.
    plat.queue._store.write("tenant-beta", job_id, {**live_job, "tenantId": "tenant-beta", "status": "succeeded", "error": "beta-secret"})
    listed = client.get("/api/product-rd/results", headers=TENANT_A).json()["items"]
    assert listed[0]["parametricRender"]["jobStatusSource"] == "SNAPSHOT"
    assert _render_job(listed[0])["status"] == "queued"
    assert "beta-secret" not in json.dumps(listed[0])

    # Malformed snapshot job IDs are handled without errors.
    for bad_job_id in (None, "", 123, ["x"]):
        record = plat.rd_store.get("tenant-alpha", rd_id)
        record["parametricRender"]["job"]["jobId"] = bad_job_id
        with plat.rd_store.tenant_lock("tenant-alpha"):
            plat.rd_store._write_record_unlocked("tenant-alpha", record)
        res = client.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A)
        assert res.status_code == 200, (bad_job_id, res.text)
        assert res.json()["parametricRender"]["jobStatusSource"] == "SNAPSHOT"


def test_generate_boundary_inputs_and_bad_approve_actor(tmp_path: Path) -> None:
    _, client = _make_client(tmp_path)

    min_vc = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "書櫃 " + ("甲" * 1997), "variantCount": 1},
    )
    assert len("書櫃 " + ("甲" * 1997)) == 2000
    assert min_vc.status_code == 200, min_vc.text
    assert min_vc.json()["requestedVariantCount"] == 1

    max_vc = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": "電視櫃 180cm", "variantCount": 100},
    )
    assert max_vc.status_code == 200, max_vc.text
    assert max_vc.json()["requestedVariantCount"] == 100
    rd_id = max_vc.json()["rdId"]

    for bad_actor in ("", "   ", "a" * 121, 123, True, ["a"], {"a": 1}, "bad\nactor"):
        bad_ap = client.post(
            f"/api/product-rd/results/{rd_id}/approve",
            headers=TENANT_A,
            json={"confirm": True, "actor": bad_actor},
        )
        assert bad_ap.status_code == 422, f"expected 422 for actor={bad_actor!r}"
        assert "traceback" not in bad_ap.text.lower()


def test_v2_generate_enforces_server_side_text_cap_while_legacy_remains_uncapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat, client = _make_client(tmp_path)

    # Exact 2000-char boundaries (ASCII, CJK 3-byte UTF-8, and 4-byte emoji) succeed on v2.
    for idx, ok_text in enumerate(
        (
            "書櫃 " + ("x" * 1997),
            "書櫃" + ("甲" * 1998),
            "🪑" * 2000,
        )
    ):
        assert len(ok_text) == 2000
        res = client.post(
            "/api/v2/product-rd/generate",
            headers=TENANT_A,
            json={"text": ok_text, "variantCount": 1, "idempotencyKey": f"v2-boundary-{idx}"},
        )
        assert res.status_code == 200, (idx, res.text[:300])
        body = res.json()
        assert body["text"] == ok_text
        assert body["textLength"] == 2000
        assert body["textTruncated"] is False
        assert len(body["textSummary"]) == 201

    # 2001+ chars, empty/null/whitespace, and malformed inputs fail 422 on v2 without running rd.run or persisting.
    before_total = client.get("/api/product-rd/results", headers=TENANT_A).json()["total"]
    orig_run = plat.rd.run

    def _forbid_run(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("v2 invalid input must not execute rd.run")

    monkeypatch.setattr(plat.rd, "run", _forbid_run)
    for bad_v2_body in (
        {},
        {"text": None},
        {"text": ""},
        {"text": "   "},
        {"text": "x" * 2001},
        {"text": "櫃" * 2001},
        {"text": "🪑" * 2001},
        {"text": " " * 2001},
        {"text": 123},
        {"text": True},
        {"text": ["書櫃"]},
        {"text": "書櫃\x00衣櫃"},
        {"text": "書櫃", "variantCount": 0},
        {"text": "書櫃", "variantCount": 101},
        {"text": "書櫃", "variantCount": True},
        {"text": "書櫃", "idempotencyKey": ""},
        {"text": "書櫃", "idempotencyKey": "k" * 201},
        # Reusing an existing valid idempotencyKey with >2000 chars on v2 must still fail validation first.
        {"text": "櫃" * 2001, "variantCount": 1, "idempotencyKey": "v2-boundary-0"},
    ):
        bad_res = client.post("/api/v2/product-rd/generate", headers=TENANT_A, json=bad_v2_body)
        assert bad_res.status_code == 422, (bad_v2_body, bad_res.status_code, bad_res.text)
        assert "traceback" not in bad_res.text.lower()
        assert str(tmp_path) not in bad_res.text

    assert client.get("/api/product-rd/results", headers=TENANT_A).json()["total"] == before_total
    monkeypatch.setattr(plat.rd, "run", orig_run)

    # Meanwhile legacy /api/product-rd/generate still accepts >2000 chars without cap.
    over_2000 = "客廳 寬180cm 電視櫃 " + ("甲" * 2200)
    legacy_ok = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": over_2000, "variantCount": 1},
    )
    assert legacy_ok.status_code == 200, legacy_ok.text[:300]
    assert legacy_ok.json()["text"] == over_2000


def test_v2_generate_idempotency_concurrency_and_tenant_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat1, client1 = _make_client(tmp_path)
    plat2, client2 = _make_client(tmp_path)

    run_count = 0
    lock = threading.Lock()
    orig1 = plat1.rd.run
    orig2 = plat2.rd.run

    def _spy1(**kw: Any) -> dict[str, Any]:
        nonlocal run_count
        with lock:
            run_count += 1
        return orig1(**kw)

    def _spy2(**kw: Any) -> dict[str, Any]:
        nonlocal run_count
        with lock:
            run_count += 1
        return orig2(**kw)

    monkeypatch.setattr(plat1.rd, "run", _spy1)
    monkeypatch.setattr(plat2.rd, "run", _spy2)

    body = {"text": "臥室 寬120cm 衣櫃 雙門 四層", "variantCount": 10, "idempotencyKey": "v2-idem-concurrent"}
    barrier = threading.Barrier(6)
    clients = [client1, client2, client1, client2, client1, client2]

    def _fire(c: TestClient) -> Any:
        barrier.wait()
        return c.post("/api/v2/product-rd/generate", headers=TENANT_A, json=body)

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(_fire, clients))

    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert run_count == 1
    rd_ids = {r.json()["rdId"] for r in responses}
    assert len(rd_ids) == 1
    rd_id = next(iter(rd_ids))

    # Parameter conflict on same idempotencyKey -> 409.
    conflict = client1.post(
        "/api/v2/product-rd/generate",
        headers=TENANT_A,
        json={**body, "text": "玄關 鞋櫃 80cm"},
    )
    assert conflict.status_code == 409

    # Tenant B cannot see or approve Tenant A's v2 record, and gets its own isolated record for the same key.
    assert client1.get("/api/product-rd/results", headers=TENANT_B).json()["total"] == 0
    assert client1.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_B).status_code == 404
    assert (
        client1.post(
            f"/api/product-rd/results/{rd_id}/approve",
            headers=TENANT_B,
            json={"confirm": True, "actor": "other"},
        ).status_code
        == 404
    )
    other_created = client2.post("/api/v2/product-rd/generate", headers=TENANT_B, json=body)
    assert other_created.status_code == 200
    assert other_created.json()["rdId"] != rd_id


def test_rd_store_summarizes_list_results_and_compacts_duplicate_text_copies(tmp_path: Path) -> None:
    plat, client = _make_client(tmp_path)
    unique_tail = ("極長需求說明段落_" * 800) + "TAIL_MARKER_END"
    long_text = "書房 寬100cm 高180cm 白木紋書櫃 雙門 四層 " + unique_tail
    assert len(long_text) > 7000

    gen = client.post(
        "/api/product-rd/generate",
        headers=TENANT_A,
        json={"text": long_text, "variantCount": 10},
    )
    assert gen.status_code == 200
    gen_data = gen.json()
    rd_id = gen_data["rdId"]
    assert gen_data["text"] == long_text
    assert gen_data["textLength"] == len(long_text)
    assert gen_data["textTruncated"] is False
    assert len(gen_data["textSummary"]) == 201
    assert gen_data["textSummary"].endswith("…")

    # On disk, the full long_text is stored only once (in record["text"]), not duplicated across nested metadata/notes.
    record_file = tmp_path / "product_rd" / stable_hash("tenant-alpha") / f"{stable_hash(rd_id)}.json"
    raw_disk = record_file.read_text(encoding="utf-8")
    assert raw_disk.count("TAIL_MARKER_END") == 1

    # List endpoint summarizes text and strips long tail so list responses stay small.
    _, restarted = _make_client(tmp_path)
    list_res = restarted.get("/api/product-rd/results", headers=TENANT_A)
    assert list_res.status_code == 200
    assert "TAIL_MARKER_END" not in list_res.text
    list_item = list_res.json()["items"][0]
    assert list_item["rdId"] == rd_id
    assert list_item["textTruncated"] is True
    assert list_item["textLength"] == len(long_text)
    assert list_item["text"] == gen_data["textSummary"]
    assert list_item["textSummary"] == gen_data["textSummary"]

    # Detail and approve endpoints still return the full verbatim text.
    detail_res = restarted.get(f"/api/product-rd/results/{rd_id}", headers=TENANT_A)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["text"] == long_text
    assert detail["textTruncated"] is False
    assert detail["textLength"] == len(long_text)

    ap_res = restarted.post(
        f"/api/product-rd/results/{rd_id}/approve",
        headers=TENANT_A,
        json={"confirm": True, "actor": "rd-approver"},
    )
    assert ap_res.status_code == 200
    assert ap_res.json()["text"] == long_text
    assert ap_res.json()["textTruncated"] is False

    # Pre-existing legacy un-compacted record on disk is also summarized cleanly when listed.
    legacy_id = "rd-legacy-bloated-01"
    legacy_tail = ("舊版重複長字串_" * 500) + "LEGACY_BLOATED_TAIL_END"
    legacy_long = "玄關 鞋櫃 80cm " + legacy_tail
    legacy_rec = plat.rd.run(tenant_id="tenant-alpha", text=legacy_long, variant_count=10)
    legacy_rec.update(
        {
            "rdId": legacy_id,
            "tenantId": "tenant-alpha",
            "createdAt": "2026-11-20T00:00:00.000000Z",
            "text": legacy_long,
            "approval": {
                "status": "WAITING_APPROVAL",
                "HUMAN_APPROVAL_REQUIRED": True,
                "autoApproveForbiddenForProduction": True,
                "liveMachineControl": False,
                "approvedAt": None,
                "actor": None,
                "judgeLabel": "MOCK",
            },
        }
    )
    legacy_path = tmp_path / "product_rd" / stable_hash("tenant-alpha") / f"{stable_hash(legacy_id)}.json"
    legacy_path.write_text(json.dumps(legacy_rec, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    _, restarted2 = _make_client(tmp_path)
    list_res2 = restarted2.get("/api/product-rd/results", headers=TENANT_A)
    assert list_res2.status_code == 200
    assert "LEGACY_BLOATED_TAIL_END" not in list_res2.text
    by_id = {item["rdId"]: item for item in list_res2.json()["items"]}
    assert by_id[legacy_id]["textTruncated"] is True
    assert by_id[legacy_id]["textLength"] == len(legacy_long)
    assert restarted2.get(f"/api/product-rd/results/{legacy_id}", headers=TENANT_A).json()["text"] == legacy_long

    # Optional max_record_bytes cap rejects oversized writes atomically without leaving temp files.
    from fox3d.product_rd_store import ProductRDStore

    capped_root = tmp_path / "capped_rd"
    capped_store = ProductRDStore(capped_root, max_record_bytes=4096)
    with pytest.raises(ValueError, match="超過大小上限"):
        capped_store.create_or_get(
            tenant_id="tenant-alpha",
            text="書櫃 " + ("超長內容" * 1500),
            variant_count=1,
            idempotency_key=None,
            fingerprint="fp-oversized",
            default_judge_status="MOCK",
            builder=lambda: {"rdId": "rd-too-big", "top": [], "approval": {"status": "WAITING_APPROVAL"}},
        )
    assert capped_store.list_results("tenant-alpha")["total"] == 0
    assert list(capped_root.rglob("*.tmp")) == []
