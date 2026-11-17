"""Admin plug-in page: /admin/materials."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fox3d.admin_pages import page_features
from fox3d.api import create_app

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}


@pytest.fixture()
def client(platform):  # noqa: ANN001 - conftest fixture
    return TestClient(create_app(platform))


def test_materials_plugin_claims_feature() -> None:
    assert page_features().get("materials") == "/admin/materials"


def test_materials_page_serves_html_and_shell(client: TestClient) -> None:
    res = client.get("/admin/materials")
    assert res.status_code == 200
    assert "/admin/recipes/assets/fox3d-shell.js" in res.text
    assert "/admin/recipes/assets/fox3d-shell.css" in res.text
    assert "/admin/pages/assets/materials.js" in res.text
    assert "/admin/pages/assets/materials.css" in res.text
    assert 'aria-label="工作台導覽"' not in res.text


@pytest.mark.parametrize("asset", ["materials.js", "materials.css"])
def test_materials_assets(client: TestClient, asset: str) -> None:
    res = client.get(f"/admin/pages/assets/{asset}")
    assert res.status_code == 200
    assert res.content


def test_materials_apis_with_tenant(client: TestClient) -> None:
    mats = client.get("/api/materials", headers=HEADERS)
    assert mats.status_code == 200
    body = mats.json()
    assert "sheets" in body and "lots" in body

    lot = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 1, "actor": "test"},
    )
    assert lot.status_code == 200

    rem = client.get("/api/remnants", headers=HEADERS)
    assert rem.status_code == 200
    snap = rem.json()
    assert "items" in snap


def test_materials_lots_are_tenant_scoped(client: TestClient) -> None:
    lots = {}
    for tenant in ("tenant-a", "tenant-b"):
        response = client.post(
            "/api/materials/lots",
            headers={"X-Tenant-Id": tenant},
            json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 1},
        )
        assert response.status_code == 200
        lots[tenant] = response.json()["lotId"]

    for headers in ({}, {"X-Tenant-Id": ""}):
        response = client.get("/api/materials", headers=headers)
        assert response.status_code == 400
        assert response.json() == {"detail": "X-Tenant-Id 無效"}

    for tenant, lot_id in lots.items():
        response = client.get("/api/materials", headers={"X-Tenant-Id": tenant})
        assert response.status_code == 200
        assert {lot["lotId"] for lot in response.json()["lots"]} == {lot_id}


def test_remnant_reserve_round_trip(client: TestClient, platform) -> None:  # noqa: ANN001
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="admin-page-test",
        tenant_id=TENANT,
    )
    assert created
    rid = created[0]["remnantId"]
    res = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-test", "version": created[0]["version"]},
    )
    assert res.status_code == 200
    assert res.json().get("status") == "reserved"


@pytest.mark.parametrize(
    "bad_body",
    [
        {"by": "wo-test", "version": 1, "leaseSeconds": 1e12},
        {"by": "wo-test", "version": 1, "leaseSeconds": "x"},
        {"by": "wo-test", "version": 1, "leaseSeconds": -5},
        {"by": "wo-test", "version": 1, "leaseSeconds": 0},
        {"by": "wo-test", "version": 1, "leaseSeconds": 7 * 86400 + 1},
        {"by": "wo-test", "version": 1, "leaseSeconds": True},
        {"by": "wo-test", "version": 1, "leaseSeconds": None},
        {"by": "wo-test", "version": 1, "leaseSeconds": "inf"},
        {"by": "wo-test", "version": 1, "leaseSeconds": 10**400},
        {"by": "wo-test", "version": "abc"},
        {"by": "wo-test", "version": 0},
        {"by": "wo-test", "version": -1},
        {"by": "wo-test", "version": 1.5},
        {"by": "wo-test", "version": True},
        {"by": "wo-test", "version": None},
        {"by": "wo-test"},
        {"by": ["a"], "version": 1},
        {"by": "", "version": 1},
        {"by": "   ", "version": 1},
        {"by": None, "version": 1},
        {"by": 123, "version": 1},
        {"by": True, "version": 1},
        {"by": "x" * 121, "version": 1},
        {"version": 1},
    ],
)
def test_remnant_reserve_invalid_inputs_return_422(
    client: TestClient, platform, bad_body: dict[str, object]  # noqa: ANN001
) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="reserve-validation",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]
    res = client.post(f"/api/remnants/{rid}/reserve", headers=HEADERS, json=bad_body)
    assert res.status_code == 422, res.text
    assert platform.remnants.items[rid]["status"] == "available"


@pytest.mark.parametrize("lease_seconds", [1, 3600, 7 * 86400])
def test_remnant_reserve_valid_lease_boundaries(
    client: TestClient, platform, lease_seconds: int  # noqa: ANN001
) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 500, "h": 300, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="reserve-lease-bounds",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]
    res = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "x" * 120, "version": 1, "leaseSeconds": lease_seconds},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "reserved"
    assert body["reservedBy"] == "x" * 120
    assert body["reservedUntil"] is not None


def test_remnant_reserve_unknown_or_other_tenant_returns_404(client: TestClient, platform) -> None:  # noqa: ANN001
    missing = client.post(
        "/api/remnants/no-such-remnant/reserve",
        headers=HEADERS,
        json={"by": "wo-test", "version": 1},
    )
    assert missing.status_code == 404

    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="tenant-a-run",
        tenant_id="tenant-a",
    )
    rid = created[0]["remnantId"]
    other = client.post(
        f"/api/remnants/{rid}/reserve",
        headers={"X-Tenant-Id": "tenant-b"},
        json={"by": "wo-other", "version": 1},
    )
    assert other.status_code == 404
    assert platform.remnants.items[rid]["status"] == "available"


def test_remnant_reserve_requires_tenant_and_checks_body_tenant_conflict(
    client: TestClient, platform  # noqa: ANN001
) -> None:
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="tenant-guard-run",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]

    no_header = client.post(f"/api/remnants/{rid}/reserve", json={"by": "wo-1", "version": 1})
    assert no_header.status_code == 400

    bad_type = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "tenantId": 123},
    )
    assert bad_type.status_code == 422

    conflict = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "tenantId": "other-tenant"},
    )
    assert conflict.status_code == 403
    assert platform.remnants.items[rid]["status"] == "available"


def test_legacy_remnant_without_tenant_id_only_reservable_by_default_tenant(
    client: TestClient, platform  # noqa: ANN001
) -> None:
    legacy_id = "legacy-no-tenant"
    platform.remnants.items[legacy_id] = {
        "remnantId": legacy_id,
        "tenantId": None,
        "material": "WOOD_WHITE",
        "materialCode": "WOOD_WHITE",
        "thickness": 18,
        "w": 600,
        "h": 400,
        "grain": "length",
        "status": "available",
        "qualityState": "AVAILABLE",
        "version": 1,
    }
    platform.remnants.store.put(platform.remnants.items[legacy_id])

    non_default = client.post(
        f"/api/remnants/{legacy_id}/reserve",
        headers=HEADERS,
        json={"by": "wo-non-default", "version": 1},
    )
    assert non_default.status_code == 404
    assert platform.remnants.items[legacy_id]["status"] == "available"

    default_res = client.post(
        f"/api/remnants/{legacy_id}/reserve",
        headers={"X-Tenant-Id": "default"},
        json={"by": "wo-default", "version": 1},
    )
    assert default_res.status_code == 200
    assert default_res.json()["status"] == "reserved"


def test_remnant_reserve_conflict_and_idempotent_retry(client: TestClient, platform) -> None:  # noqa: ANN001
    created = platform.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600, "h": 400, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="conflict-test",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]

    stale = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 99},
    )
    assert stale.status_code == 409

    ok1 = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "idempotencyKey": "idem-res-1"},
    )
    assert ok1.status_code == 200

    retry_same = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "idempotencyKey": "idem-res-1"},
    )
    assert retry_same.status_code == 200
    assert retry_same.json()["version"] == ok1.json()["version"]

    second_confirm = client.post(
        f"/api/remnants/{rid}/reserve",
        headers=HEADERS,
        json={"by": "wo-1", "version": 1, "idempotencyKey": "idem-res-2"},
    )
    assert second_confirm.status_code == 409


def test_materials_lots_without_supplier_lot_create_distinct_lots_with_distinct_idempotency_keys(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 2, "idempotencyKey": "k-1"},
    )
    retry = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 2, "idempotencyKey": "k-1"},
    )
    second = client.post(
        "/api/materials/lots",
        headers=HEADERS,
        json={"material": "WOOD_WHITE", "thickness": 18, "sheetCount": 2, "idempotencyKey": "k-2"},
    )
    assert first.status_code == 200 and retry.status_code == 200 and second.status_code == 200
    assert first.json()["receiptId"] == retry.json()["receiptId"]
    assert first.json()["lotId"] == retry.json()["lotId"]
    assert first.json()["lotId"] != second.json()["lotId"]


def test_nesting_benchmark_api_caps_per_tenant(client: TestClient, platform) -> None:  # noqa: ANN001
    from fox3d.physical_os import MAX_BENCHMARKS_PER_TENANT

    res = client.post("/api/nesting/benchmarks", headers=HEADERS, json={})
    assert res.status_code == 200
    data = res.json()
    assert "cases" in data
    assert data.get("liveMachineControl") is False
    assert data.get("tenantId") == TENANT

    for i in range(MAX_BENCHMARKS_PER_TENANT + 5):
        platform.physical.record_benchmark({"seq": i}, tenant_id=TENANT)
    platform.physical.record_benchmark({"seq": 0}, tenant_id="other-tenant")

    tenant_rows = [b for b in platform.physical.benchmarks if b.get("tenantId") == TENANT]
    other_rows = [b for b in platform.physical.benchmarks if b.get("tenantId") == "other-tenant"]
    assert len(tenant_rows) == MAX_BENCHMARKS_PER_TENANT
    assert tenant_rows[-1]["seq"] == MAX_BENCHMARKS_PER_TENANT + 4
    assert tenant_rows[0]["seq"] == 5
    assert len(other_rows) == 1
    assert all(b.get("tenantId") for b in platform.physical.benchmarks)


def test_confirm_dialog_resets_return_value_before_opening() -> None:
    # Esc keeps the previous returnValue; without a reset, Esc after an earlier "ok" would confirm.
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/fox3d/static/pages/materials.js").read_text(encoding="utf-8")
    assert js.index("dlg.returnValue = '';") < js.index("dlg.showModal();")
    assert "innerHTML" not in js
    assert "crypto.randomUUID" in js


def test_remnant_reserve_concurrent_barrier_atomic_and_durable(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    import threading
    from fox3d import inventory as inv_mod
    from fox3d.inventory import DurableRemnantStore
    from fox3d.manufacturing import RemnantInventory
    from fox3d.platform import Platform

    root = tmp_path / "durable-platform"
    plat = Platform(root=root, mock_blender=True)
    created = plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 700, "h": 500, "sheetIndex": 0}]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="concurrent-reserve",
        tenant_id=TENANT,
    )
    rid = created[0]["remnantId"]

    orig_norm = inv_mod.normalize_status
    first_in_check = threading.Event()
    second_ready = threading.Event()
    hook_state = {"calls": 0}
    hook_lock = threading.Lock()

    def hooked_norm(status: str | None) -> str:
        res = orig_norm(status)
        with hook_lock:
            hook_state["calls"] += 1
            call_no = hook_state["calls"]
        if call_no == 1:
            first_in_check.set()
            second_ready.wait()
        return res

    monkeypatch.setattr(inv_mod, "normalize_status", hooked_norm)

    outcomes: list[str] = []
    reserved_by: list[str] = []
    errors: list[str] = []

    def worker_a() -> None:
        try:
            rec = plat.remnants.reserve(rid, by="worker-a", version=1, tenant_id=TENANT)
            outcomes.append("success")
            reserved_by.append(str(rec.get("reservedBy")))
        except PermissionError as exc:
            outcomes.append("error")
            errors.append(str(exc))

    def worker_b() -> None:
        first_in_check.wait()
        second_ready.set()
        try:
            rec = plat.remnants.reserve(rid, by="worker-b", version=1, tenant_id=TENANT)
            outcomes.append("success")
            reserved_by.append(str(rec.get("reservedBy")))
        except PermissionError as exc:
            outcomes.append("error")
            errors.append(str(exc))

    t1 = threading.Thread(target=worker_a)
    t2 = threading.Thread(target=worker_b)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(outcomes) == ["error", "success"]
    assert reserved_by == ["worker-a"]
    assert errors

    # Verify durable state on disk and cross-instance visibility
    reloaded = RemnantInventory(DurableRemnantStore(root / "remnants"), default_tenant="default")
    persisted = reloaded.get(rid, tenant_id=TENANT)
    assert persisted["status"] == "reserved"
    assert persisted["reservedBy"] == "worker-a"
    assert persisted["version"] == 2

    with pytest.raises(PermissionError):
        reloaded.reserve(rid, by="worker-c", version=1, tenant_id=TENANT)


def test_remnant_reserve_concurrent_overlapping_retry_and_competing_api_requests(
    tmp_path, monkeypatch  # noqa: ANN001
) -> None:
    import threading
    from fox3d import inventory as inv_mod
    from fox3d.platform import Platform

    plat = Platform(root=tmp_path / "api-race", mock_blender=True)
    app_client = TestClient(create_app(plat))
    created = plat.remnants.add_from_nesting(
        {
            "candidateRemnants": [
                {"w": 600, "h": 400, "sheetIndex": 0},
                {"w": 500, "h": 350, "sheetIndex": 1},
            ]
        },
        material="WOOD_WHITE",
        thickness=18,
        source_run="api-concurrent",
        tenant_id=TENANT,
    )
    rid_compete = created[0]["remnantId"]
    rid_retry = created[1]["remnantId"]

    # 1. Competing API requests for the same remnant (version 1): only one 200, one 409.
    barrier = threading.Barrier(2)
    compete_codes: list[int] = []
    compete_winners: list[str] = []

    def call_compete(who: str) -> None:
        barrier.wait()
        resp = app_client.post(
            f"/api/remnants/{rid_compete}/reserve",
            headers=HEADERS,
            json={"by": who, "version": 1, "idempotencyKey": f"key-{who}"},
        )
        compete_codes.append(resp.status_code)
        if resp.status_code == 200:
            compete_winners.append(resp.json()["reservedBy"])

    ta = threading.Thread(target=call_compete, args=("user-1",))
    tb = threading.Thread(target=call_compete, args=("user-2",))
    ta.start()
    tb.start()
    ta.join()
    tb.join()

    assert sorted(compete_codes) == [200, 409]
    assert len(compete_winners) == 1

    plat_check = Platform(root=tmp_path / "api-race", mock_blender=True)
    disk_compete = plat_check.remnants.get(rid_compete, tenant_id=TENANT)
    assert disk_compete["status"] == "reserved"
    assert disk_compete["reservedBy"] == compete_winners[0]
    assert disk_compete["version"] == 2

    # 2. Overlapping retry with identical (by, version, idempotencyKey): both 200, reserved once.
    orig_lease = inv_mod.lease_token
    first_in_flight = threading.Event()
    retry_sent = threading.Event()
    lease_calls = {"n": 0}

    def hooked_lease(remnant_id: str, version: int, by: str) -> str:
        if remnant_id == rid_retry:
            lease_calls["n"] += 1
            if lease_calls["n"] == 1:
                first_in_flight.set()
                retry_sent.wait()
        return orig_lease(remnant_id, version, by)

    monkeypatch.setattr(inv_mod, "lease_token", hooked_lease)

    retry_responses: list[tuple[int, dict[str, object]]] = []

    def first_req() -> None:
        r = app_client.post(
            f"/api/remnants/{rid_retry}/reserve",
            headers=HEADERS,
            json={"by": "retry-user", "version": 1, "idempotencyKey": "idem-overlap"},
        )
        retry_responses.append((r.status_code, r.json()))

    def retry_req() -> None:
        first_in_flight.wait()
        retry_sent.set()
        r = app_client.post(
            f"/api/remnants/{rid_retry}/reserve",
            headers=HEADERS,
            json={"by": "retry-user", "version": 1, "idempotencyKey": "idem-overlap"},
        )
        retry_responses.append((r.status_code, r.json()))

    t_first = threading.Thread(target=first_req)
    t_retry = threading.Thread(target=retry_req)
    t_first.start()
    t_retry.start()
    t_first.join()
    t_retry.join()

    assert [code for code, _ in retry_responses] == [200, 200]
    assert retry_responses[0][1]["version"] == 2
    assert retry_responses[1][1]["version"] == 2
    assert retry_responses[0][1]["leaseToken"] == retry_responses[1][1]["leaseToken"]
    assert lease_calls["n"] == 1

    plat_check_2 = Platform(root=tmp_path / "api-race", mock_blender=True)
    disk_retry = plat_check_2.remnants.get(rid_retry, tenant_id=TENANT)
    assert disk_retry["status"] == "reserved"
    assert disk_retry["reservedBy"] == "retry-user"
    assert disk_retry["version"] == 2


def test_workorder_remnant_reserve_avoids_multi_tenant_and_per_item_read_amplification(
    tmp_path, monkeypatch  # noqa: ANN001
) -> None:
    from pathlib import Path
    from typing import Any
    from fox3d import inventory as inv_mod
    from fox3d.inventory import DurableRemnantStore
    from fox3d.manufacturing import RemnantInventory
    from fox3d.platform import Platform

    root = tmp_path / "multi-tenant-io"
    plat = Platform(root=root, mock_blender=True)
    remnants_dir = (root / "remnants").resolve()

    tenants = ["ta", "tb", "tc", "td", "te", "tf"]
    remnants_per_tenant = 15
    by_tenant_ids: dict[str, list[str]] = {}
    for tid in tenants:
        plat.lots.create(tenant_id=tid, material="PB_18_WHITE", thickness=18, sheet_count=10)
        created = plat.remnants.add_from_nesting(
            {
                "candidateRemnants": [
                    {"w": 500 + i, "h": 300 + i, "sheetIndex": i}
                    for i in range(remnants_per_tenant)
                ]
            },
            material="WOOD_WHITE",
            thickness=18,
            source_run=f"seed-{tid}",
            tenant_id=tid,
        )
        by_tenant_ids[tid] = [r["remnantId"] for r in created]

    orig_read_json = inv_mod.read_json
    orig_write_json = inv_mod.atomic_write_json
    remnant_reads: list[str] = []
    remnant_writes: list[str] = []

    def counting_read_json(path: Path) -> Any:
        if path.resolve().parent == remnants_dir:
            remnant_reads.append(path.name)
        return orig_read_json(path)

    def counting_write_json(path: Path, payload: Any) -> None:
        if path.resolve().parent == remnants_dir:
            remnant_writes.append(path.name)
        orig_write_json(path, payload)

    monkeypatch.setattr(inv_mod, "read_json", counting_read_json)
    monkeypatch.setattr(inv_mod, "atomic_write_json", counting_write_json)

    from fox3d.release import safe_tenant_filename

    ta_file = f"{safe_tenant_filename('ta')}.json"
    tb_file = f"{safe_tenant_filename('tb')}.json"
    tc_file = f"{safe_tenant_filename('tc')}.json"
    tg_file = f"{safe_tenant_filename('tg')}.json"

    # 1. Batch add_from_nesting for a new tenant writes once and reads zero other tenant files.
    plat.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 450 + i, "h": 250 + i, "sheetIndex": i} for i in range(10)]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="seed-tg",
        tenant_id="tg",
    )
    assert remnant_reads == []
    assert remnant_writes == [tg_file]

    # 2. WorkOrder reserve_materials for "ta" (15 remnants, 7 tenants on disk) reads ta.json once and writes ta.json once.
    product_a = plat.kd.build_sku(tenant_id="ta", kind="OPEN_SHELF")
    rel_a = plat.pilot.open_release(product_a, tenant_id="ta", family="KD_FURNITURE", actor="eng")
    wo_a = plat.pilot.workorders.create(tenant_id="ta", release=rel_a, quantity=1, actor="ops")
    plat.pilot.workorders.release_for_execution(wo_a["workOrderId"], actor="ops")

    remnant_reads.clear()
    remnant_writes.clear()
    reserved_a = plat.pilot.workorders.reserve_materials(wo_a["workOrderId"], actor="ops", tenant_id="ta")
    assert remnant_reads == [ta_file]
    assert remnant_writes == [ta_file]
    assert set(reserved_a["lineage"]["remnants"]) == set(by_tenant_ids["ta"])
    assert len(reserved_a["lineage"]["remnants"]) == remnants_per_tenant

    # Idempotent second call does 0 remnant reads/writes.
    remnant_reads.clear()
    remnant_writes.clear()
    plat.pilot.workorders.reserve_materials(wo_a["workOrderId"], actor="ops", tenant_id="ta")
    assert remnant_reads == []
    assert remnant_writes == []

    # 3. consume_reserved for "ta" (15 reserved remnants) reads ta.json once and writes ta.json once.
    remnant_reads.clear()
    remnant_writes.clear()
    plat.pilot.workorders.consume_reserved(wo_a["workOrderId"], actor="ops")
    assert remnant_reads == [ta_file]
    assert remnant_writes == [ta_file]

    # 4. WorkOrder reserve + cancel for "tb" scopes all reads/writes to tb.json only.
    product_b = plat.kd.build_sku(tenant_id="tb", kind="OPEN_SHELF")
    rel_b = plat.pilot.open_release(product_b, tenant_id="tb", family="KD_FURNITURE", actor="eng")
    wo_b = plat.pilot.workorders.create(tenant_id="tb", release=rel_b, quantity=1, actor="ops")
    plat.pilot.workorders.release_for_execution(wo_b["workOrderId"], actor="ops")

    remnant_reads.clear()
    remnant_writes.clear()
    plat.pilot.workorders.reserve_materials(wo_b["workOrderId"], actor="ops", tenant_id="tb")
    assert remnant_reads == [tb_file]
    assert remnant_writes == [tb_file]

    remnant_reads.clear()
    remnant_writes.clear()
    plat.pilot.workorders.cancel(wo_b["workOrderId"], actor="ops")
    assert remnant_reads == [tb_file]
    assert remnant_writes == [tb_file]

    # 5. API snapshot and single-remnant reserve for "tb" also touch only tb.json once.
    app_client = TestClient(create_app(plat))
    remnant_reads.clear()
    remnant_writes.clear()
    snap_resp = app_client.get("/api/remnants", headers={"X-Tenant-Id": "tb"})
    assert snap_resp.status_code == 200
    assert snap_resp.json()["availableCount"] == remnants_per_tenant
    assert remnant_reads == [tb_file]
    assert remnant_writes == []

    remnant_reads.clear()
    remnant_writes.clear()
    rid_tb0 = by_tenant_ids["tb"][0]
    res_resp = app_client.post(
        f"/api/remnants/{rid_tb0}/reserve",
        headers={"X-Tenant-Id": "tb"},
        json={"by": "api-op", "version": 3},
    )
    assert res_resp.status_code == 200
    assert remnant_reads == [tb_file]
    assert remnant_writes == [tb_file]

    # 6. Fallback path (without reserve_available) and mid-batch stale-version skip for "tc" still do 1 read and 1 write.
    product_c = plat.kd.build_sku(tenant_id="tc", kind="OPEN_SHELF")
    rel_c = plat.pilot.open_release(product_c, tenant_id="tc", family="KD_FURNITURE", actor="eng")
    wo_c = plat.pilot.workorders.create(tenant_id="tc", release=rel_c, quantity=1, actor="ops")
    plat.pilot.workorders.release_for_execution(wo_c["workOrderId"], actor="ops")
    orig_reserve = plat.remnants.reserve
    rid_tc_skip = by_tenant_ids["tc"][0]

    def reserve_with_one_conflict(remnant_id: str, **kwargs: Any) -> dict[str, Any]:
        if remnant_id == rid_tc_skip:
            raise PermissionError("simulated concurrent version conflict")
        return orig_reserve(remnant_id, **kwargs)

    monkeypatch.setattr(plat.remnants, "reserve_available", None)
    monkeypatch.setattr(plat.remnants, "reserve", reserve_with_one_conflict)
    remnant_reads.clear()
    remnant_writes.clear()
    reserved_c = plat.pilot.workorders.reserve_materials(wo_c["workOrderId"], actor="ops", tenant_id="tc")
    assert remnant_reads == [tc_file]
    assert remnant_writes == [tc_file]
    assert set(reserved_c["lineage"]["remnants"]) == set(by_tenant_ids["tc"][1:])

    # Reload from disk and verify durable state across tenants.
    monkeypatch.setattr(inv_mod, "read_json", orig_read_json)
    reloaded = RemnantInventory(DurableRemnantStore(root / "remnants"), default_tenant="default")
    for rid in by_tenant_ids["ta"]:
        rec = reloaded.get(rid, tenant_id="ta")
        assert rec["status"] == "consumed"
        assert rec["consumedBy"] == wo_a["workOrderId"]
        assert rec["version"] == 3
    assert reloaded.get(rid_tb0, tenant_id="tb")["status"] == "reserved"
    for rid in by_tenant_ids["tb"][1:]:
        rec = reloaded.get(rid, tenant_id="tb")
        assert rec["status"] == "available"
        assert rec["version"] == 3
    assert reloaded.get(rid_tc_skip, tenant_id="tc")["status"] == "available"
    for rid in by_tenant_ids["tc"][1:]:
        rec = reloaded.get(rid, tenant_id="tc")
        assert rec["status"] == "reserved"
        assert rec["reservedBy"] == wo_c["workOrderId"]
        assert rec["version"] == 2
    for tid in ("td", "te", "tf"):
        for rid in by_tenant_ids[tid]:
            rec = reloaded.get(rid, tenant_id=tid)
            assert rec["status"] == "available"
            assert rec["version"] == 1


def test_workorder_remnant_reserve_cross_instance_and_concurrent_race(tmp_path) -> None:  # noqa: ANN001
    import threading
    from typing import Any
    from fox3d.inventory import DurableRemnantStore
    from fox3d.manufacturing import RemnantInventory
    from fox3d.platform import Platform

    root = tmp_path / "cross-instance-wo-race"
    plat1 = Platform(root=root, mock_blender=True)
    plat1.lots.create(tenant_id=TENANT, material="PB_18_WHITE", thickness=18, sheet_count=20)
    created = plat1.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 600 + i, "h": 400 + i, "sheetIndex": i} for i in range(12)]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="race-seed",
        tenant_id=TENANT,
    )
    rids = [r["remnantId"] for r in created]
    other_created = plat1.remnants.add_from_nesting(
        {"candidateRemnants": [{"w": 500 + i, "h": 300 + i, "sheetIndex": i} for i in range(6)]},
        material="WOOD_WHITE",
        thickness=18,
        source_run="other-seed",
        tenant_id="other-tenant",
    )

    product = plat1.kd.build_sku(tenant_id=TENANT, kind="OPEN_SHELF")
    rel = plat1.pilot.open_release(product, tenant_id=TENANT, family="KD_FURNITURE", actor="eng")
    wo1 = plat1.pilot.workorders.create(tenant_id=TENANT, release=rel, quantity=1, actor="ops")
    wo2 = plat1.pilot.workorders.create(tenant_id=TENANT, release=rel, quantity=1, actor="ops")
    plat1.pilot.workorders.release_for_execution(wo1["workOrderId"], actor="ops")
    plat1.pilot.workorders.release_for_execution(wo2["workOrderId"], actor="ops")

    # Separate store instance reserves rids[0] on disk BEFORE plat1's work orders reserve materials.
    external_inv = RemnantInventory(DurableRemnantStore(root / "remnants"), default_tenant="default")
    ext_res = external_inv.reserve(rids[0], by="external-worker", version=1, tenant_id=TENANT)
    assert ext_res["version"] == 2

    # Race wo1 (two concurrent calls for the same work order) and wo2 (competing work order) simultaneously.
    barrier = threading.Barrier(3)
    results: dict[str, list[dict[str, Any]]] = {"wo1": [], "wo2": []}
    lock = threading.Lock()

    def run_reserve(label: str, wo_id: str) -> None:
        barrier.wait()
        res = plat1.pilot.workorders.reserve_materials(wo_id, actor="ops", tenant_id=TENANT)
        with lock:
            results[label].append(res)

    threads = [
        threading.Thread(target=run_reserve, args=("wo1", wo1["workOrderId"])),
        threading.Thread(target=run_reserve, args=("wo1", wo1["workOrderId"])),
        threading.Thread(target=run_reserve, args=("wo2", wo2["workOrderId"])),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results["wo1"]) == 2
    assert results["wo1"][0]["lineage"]["remnants"] == results["wo1"][1]["lineage"]["remnants"]

    wo1_rems = set(plat1.pilot.workorders.get(wo1["workOrderId"])["lineage"]["remnants"])
    wo2_rems = set(plat1.pilot.workorders.get(wo2["workOrderId"])["lineage"]["remnants"])
    assert rids[0] not in wo1_rems
    assert rids[0] not in wo2_rems
    assert wo1_rems.isdisjoint(wo2_rems)
    assert wo1_rems | wo2_rems == set(rids[1:])

    # Verify durable state from a fresh store instance.
    reloaded = RemnantInventory(DurableRemnantStore(root / "remnants"), default_tenant="default")
    r0 = reloaded.get(rids[0], tenant_id=TENANT)
    assert r0["status"] == "reserved"
    assert r0["reservedBy"] == "external-worker"
    assert r0["version"] == 2

    winner_wo_id = wo1["workOrderId"] if wo1_rems else wo2["workOrderId"]
    for rid in rids[1:]:
        rec = reloaded.get(rid, tenant_id=TENANT)
        assert rec["status"] == "reserved"
        assert rec["reservedBy"] == winner_wo_id
        assert rec["version"] == 2

    for orec in other_created:
        disk_other = reloaded.get(orec["remnantId"], tenant_id="other-tenant")
        assert disk_other["status"] == "available"
        assert disk_other["version"] == 1


