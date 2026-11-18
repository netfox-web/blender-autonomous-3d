"""Tests for pilot work order packing HTTP API and pure-HTTP dispatch-to-complete E2E."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.station import OP_CAPABILITY, STATION_CAPS
from fox3d.workorder import STRICT_STOCK

TENANT = "sonaqueen-home"
HEADERS = {"X-Tenant-Id": TENANT}


def _concurrent(count: int, fn: Any) -> list[Any]:
    barrier = Barrier(count)

    def _run(_: int) -> Any:
        barrier.wait()
        return fn()

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(_run, range(count)))


@pytest.fixture()
def client(platform: Any) -> TestClient:
    return TestClient(create_app(platform))


def _seed_release_receipt_and_wo(
    platform: Any, *, tenant: str = TENANT, product: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if product is None:
        product = platform.kd.build_sku(tenant_id=tenant, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    nest = (rel.get("snapshot") or {}).get("nesting") or {}
    sheet_mm = nest.get("sheetMm") or [2440, 1220]
    row: dict[str, Any] = {
        "supplierLot": f"{tenant}-lot-1",
        "material": nest.get("sheetSku") or "PB_18_WHITE",
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
        idempotency_key=f"{tenant}-receipt-1",
    )
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    platform.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    platform.pilot.workorders.reserve_materials(
        wo["workOrderId"],
        actor="ops",
        tenant_id=tenant,
        allocation_policy=STRICT_STOCK,
    )
    return rel, wo


def _complete_ops_and_qc(platform: Any, wo: dict[str, Any], *, tenant: str = TENANT) -> None:
    wo_id = wo["workOrderId"]
    for step in wo["traveler"]["steps"]:
        op = platform.pilot.workorders.start_operation(wo_id, step["operation"], actor="ops", tenant_id=tenant)
        platform.pilot.workorders.complete_operation(wo_id, op["opId"], actor="ops")
    for spec in platform.pilot.qc.schema(wo["productFamily"]):
        nominal = float(spec["nominal"] if spec["nominal"] is not None else 100.0)
        platform.pilot.qc.record(
            tenant_id=tenant,
            work_order_id=wo_id,
            stage="FINAL" if spec.get("requiredFinal") else "IN_PROCESS",
            check_id=spec["checkId"],
            measured=nominal,
            nominal=nominal,
            tol=float(spec["tol"]),
            unit=spec["unit"],
            operator="qc",
            required_final=bool(spec.get("requiredFinal")),
            source="MANUAL",
        )


def test_create_cartons_concurrent_idempotent_and_conflict(client: TestClient, platform: Any) -> None:
    rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    body = {"quantity": 3, "idempotencyKey": "carton-idem-key-1"}

    responses = _concurrent(
        6,
        lambda: client.post(f"/api/pilot/work-orders/{wo_id}/cartons", headers=HEADERS, json=body),
    )
    assert [r.status_code for r in responses] == [200] * 6
    id_tuples = {tuple(r.json()["cartonIds"]) for r in responses}
    assert len(id_tuples) == 1
    carton_ids = list(next(iter(id_tuples)))
    assert len(carton_ids) == 3

    # Only one set of 3 cartons created in logistics store and bound to the work order.
    tenant_cartons = [c for c in platform.pilot.logistics.cartons.values() if c.get("tenantId") == TENANT]
    assert len(tenant_cartons) == 3
    wo_fresh = platform.pilot.workorders.get(wo_id)
    assert wo_fresh["cartonIds"] == carton_ids
    assert wo_fresh["state"] == "PACKING"
    for c in responses[0].json()["items"]:
        assert c["releaseHash"] == rel["releaseHash"]
        assert c["batchId"] == wo["batchId"]
        assert c["expected"]["length"] > 0
        assert c["measured"] is None
        assert c["mismatch"] is False

    # Same key + different quantity returns 409.
    conflict = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 2, "idempotencyKey": "carton-idem-key-1"},
    )
    assert conflict.status_code == 409
    assert len([c for c in platform.pilot.logistics.cartons.values() if c.get("tenantId") == TENANT]) == 3

    # Boundary validation on quantity (1-50) and idempotencyKey.
    for bad_body in (
        {"quantity": 0, "idempotencyKey": "k-zero"},
        {"quantity": 51, "idempotencyKey": "k-over"},
        {"quantity": -1, "idempotencyKey": "k-neg"},
        {"quantity": 1.5, "idempotencyKey": "k-float"},
        {"quantity": "2", "idempotencyKey": "k-str"},
        {"quantity": True, "idempotencyKey": "k-bool"},
        {"quantity": 1, "idempotencyKey": ""},
        {"quantity": 1, "idempotencyKey": "   "},
        {"quantity": 1},
    ):
        res = client.post(f"/api/pilot/work-orders/{wo_id}/cartons", headers=HEADERS, json=bad_body)
        assert res.status_code == 422, f"{bad_body} -> {res.status_code} {res.text}"


def test_unknown_and_other_tenant_return_404(client: TestClient, platform: Any) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform, tenant=TENANT)
    wo_id = wo["workOrderId"]
    created = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "tenant-iso-1"},
    )
    assert created.status_code == 200
    carton_id = created.json()["cartonIds"][0]

    other_headers = {"X-Tenant-Id": "other-tenant"}

    # Unknown work order / carton returns 404.
    assert (
        client.post(
            "/api/pilot/work-orders/no-such-wo/cartons",
            headers=HEADERS,
            json={"quantity": 1, "idempotencyKey": "k1"},
        ).status_code
        == 404
    )
    assert client.get("/api/pilot/work-orders/no-such-wo/cartons", headers=HEADERS).status_code == 404
    assert (
        client.post(
            "/api/pilot/cartons/no-such-carton/measured",
            headers=HEADERS,
            json={"length": 400, "width": 300, "height": 200, "weightKg": 8},
        ).status_code
        == 404
    )
    assert client.post("/api/pilot/work-orders/no-such-wo/packing-checklist", headers=HEADERS, json={}).status_code == 404

    # Another tenant gets 404 on all four endpoints.
    assert (
        client.post(
            f"/api/pilot/work-orders/{wo_id}/cartons",
            headers=other_headers,
            json={"quantity": 1, "idempotencyKey": "k-other"},
        ).status_code
        == 404
    )
    assert client.get(f"/api/pilot/work-orders/{wo_id}/cartons", headers=other_headers).status_code == 404
    assert (
        client.post(
            f"/api/pilot/cartons/{carton_id}/measured",
            headers=other_headers,
            json={"length": 400, "width": 300, "height": 200, "weightKg": 8},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/pilot/work-orders/{wo_id}/packing-checklist",
            headers=other_headers,
            json={},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "bad_payload",
    [
        '{"length": NaN, "width": 300, "height": 200, "weightKg": 8}',
        '{"length": 400, "width": Infinity, "height": 200, "weightKg": 8}',
        '{"length": 400, "width": 300, "height": -Infinity, "weightKg": 8}',
        {"length": "NaN", "width": 300, "height": 200, "weightKg": 8},
        {"length": -1, "width": 300, "height": 200, "weightKg": 8},
        {"length": 400, "width": -0.5, "height": 200, "weightKg": 8},
        {"length": 400, "width": 300, "height": 0, "weightKg": 8},
        {"length": 400, "width": 300, "height": 200, "weightKg": -3},
        {"length": "400", "width": 300, "height": 200, "weightKg": 8},
        {"length": 400, "width": "abc", "height": 200, "weightKg": 8},
        {"length": 400, "width": 300, "height": 200, "weightKg": "heavy"},
        {"length": True, "width": 300, "height": 200, "weightKg": 8},
    ],
)
def test_measured_rejects_nan_negative_and_string_with_422(
    client: TestClient, platform: Any, bad_payload: Any
) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    carton_id = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "bad-dim-carton"},
    ).json()["cartonIds"][0]

    if isinstance(bad_payload, str):
        res = client.post(
            f"/api/pilot/cartons/{carton_id}/measured",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=bad_payload,
        )
    else:
        res = client.post(
            f"/api/pilot/cartons/{carton_id}/measured",
            headers=HEADERS,
            json=bad_payload,
        )
    assert res.status_code == 422, f"{bad_payload} -> {res.status_code} {res.text}"
    assert platform.pilot.logistics.cartons[carton_id]["measured"] is None


def test_measured_same_values_idempotent_and_mismatch_blocks_complete_with_409(
    client: TestClient, platform: Any
) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    _complete_ops_and_qc(platform, wo)

    created = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "mismatch-test-1"},
    )
    assert created.status_code == 200
    carton = created.json()["items"][0]
    carton_id = carton["cartonId"]
    exp = carton["expected"]

    # Record a mismatched measurement (>5 mm difference in length).
    bad_dims = {
        "length": float(exp["length"]) + 50.0,
        "width": float(exp["width"]),
        "height": float(exp["height"]),
        "weightKg": float(exp["weightKg"]),
    }
    m1 = client.post(f"/api/pilot/cartons/{carton_id}/measured", headers=HEADERS, json=bad_dims)
    assert m1.status_code == 200
    assert m1.json()["mismatch"] is True
    assert m1.json()["statusMessage"] == "尺寸不符待人工確認"

    # Resending identical values is idempotent (single journal event for this measurement).
    m2 = client.post(f"/api/pilot/cartons/{carton_id}/measured", headers=HEADERS, json=bad_dims)
    assert m2.status_code == 200
    assert m2.json()["measureSeq"] == m1.json()["measureSeq"] == 1
    measured_events = [
        e for e in platform.pilot.journal.list(TENANT) if e.get("eventType") == "carton.measured"
    ]
    assert len(measured_events) == 1

    # Listing cartons shows expected, measured, mismatch=True.
    listed = client.get(f"/api/pilot/work-orders/{wo_id}/cartons", headers=HEADERS)
    assert listed.status_code == 200
    assert listed.json()["cartonCount"] == 1
    item0 = listed.json()["items"][0]
    assert item0["expected"] == exp
    assert item0["measured"]["length"] == bad_dims["length"]
    assert item0["mismatch"] is True

    # Packing checklist sets mismatchHold=True and keeps carrierProvider BLOCKED/NOT_CONNECTED.
    chk = client.post(f"/api/pilot/work-orders/{wo_id}/packing-checklist", headers=HEADERS, json={})
    assert chk.status_code == 200
    chk_data = chk.json()
    assert chk_data["mismatchHold"] is True
    assert chk_data["carrierProvider"] == "BLOCKED/NOT_CONNECTED"
    assert chk_data["pinned"] is True
    assert chk_data["statusMessage"] == "尺寸不符待人工確認"
    assert platform.pilot.logistics.handoffs == {}

    # Attempting to complete the work order while mismatchHold is True returns 409.
    comp_blocked = client.post(
        f"/api/pilot/work-orders/{wo_id}/complete",
        headers=HEADERS,
        json={"confirm": True},
    )
    assert comp_blocked.status_code == 409
    assert "尺寸不符待人工確認" in comp_blocked.json()["detail"]
    assert platform.pilot.workorders.get(wo_id)["state"] != "COMPLETED"


def test_pure_http_e2e_from_dispatch_to_completed(client: TestClient, platform: Any) -> None:
    """Fixture only prepares release, work order, and receipt; everything else goes via TestClient."""
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]

    # Register manual station via HTTP.
    station_res = client.post(
        "/api/pilot/stations",
        headers=HEADERS,
        json={"capabilities": list(STATION_CAPS), "status": "ONLINE", "actor": "e2e"},
    )
    assert station_res.status_code == 200
    station_id = station_res.json()["stationId"]

    # 1. dispatch -> lease ack -> lease start -> lease complete for every traveler operation.
    for step in wo["traveler"]["steps"]:
        op_name = step["operation"]
        assert op_name in OP_CAPABILITY
        disp = client.post(
            "/api/pilot/dispatch",
            headers=HEADERS,
            json={"workOrderId": wo_id, "operation": op_name, "stationId": station_id, "actor": "e2e"},
        )
        assert disp.status_code == 200, disp.text
        lease_id = disp.json()["leaseId"]

        ack = client.post(f"/api/pilot/leases/{lease_id}/ack", headers=HEADERS, json={"actor": "e2e"})
        assert ack.status_code == 200, ack.text

        start = client.post(f"/api/pilot/leases/{lease_id}/start", headers=HEADERS, json={"actor": "e2e"})
        assert start.status_code == 200, start.text

        done = client.post(
            f"/api/pilot/leases/{lease_id}/complete",
            headers=HEADERS,
            json={"confirm": True, "actor": "e2e"},
        )
        assert done.status_code == 200, done.text

    # 2. QC: record a failing final check first (putting WO into QC_HOLD), then record passing final checks -> release-hold.
    qc_info = client.get(f"/api/pilot/work-orders/{wo_id}/qc", headers=HEADERS)
    assert qc_info.status_code == 200, qc_info.text
    plan = qc_info.json()["plan"]

    first_spec = plan[0]
    first_nom = float(first_spec["nominal"] if first_spec["nominal"] is not None else 100.0)
    fail_qc = client.post(
        f"/api/pilot/work-orders/{wo_id}/qc",
        headers=HEADERS,
        json={
            "stage": "FINAL",
            "checkId": first_spec["checkId"],
            "measured": first_nom + float(first_spec["tol"]) + 10.0,
            "nominal": first_nom,
            "tol": float(first_spec["tol"]),
            "unit": first_spec["unit"],
            "source": "MANUAL",
            "idempotencyKey": "e2e-qc-fail-0",
        },
    )
    assert fail_qc.status_code == 200, fail_qc.text
    assert fail_qc.json()["ok"] is False

    for idx, spec in enumerate(plan):
        nominal = float(spec["nominal"] if spec["nominal"] is not None else 100.0)
        qc_res = client.post(
            f"/api/pilot/work-orders/{wo_id}/qc",
            headers=HEADERS,
            json={
                "stage": "FINAL" if spec.get("requiredFinal") else "IN_PROCESS",
                "checkId": spec["checkId"],
                "measured": nominal,
                "nominal": nominal,
                "tol": float(spec["tol"]),
                "unit": spec["unit"],
                "source": "MANUAL",
                "idempotencyKey": f"e2e-qc-pass-{idx}",
            },
        )
        assert qc_res.status_code == 200, qc_res.text
        assert qc_res.json()["ok"] is True

    rel_hold = client.post(
        f"/api/pilot/work-orders/{wo_id}/qc/release-hold",
        headers=HEADERS,
        json={"confirm": True, "actor": "e2e"},
    )
    assert rel_hold.status_code == 200, rel_hold.text
    assert rel_hold.json()["state"] == "IN_PROGRESS"

    # 3. Instantiate cartons -> record measured -> packing checklist -> complete.
    cartons_res = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 2, "idempotencyKey": "e2e-cartons-key"},
    )
    assert cartons_res.status_code == 200, cartons_res.text
    cartons = cartons_res.json()["items"]
    assert len(cartons) == 2

    for c in cartons:
        exp = c["expected"]
        m_res = client.post(
            f"/api/pilot/cartons/{c['cartonId']}/measured",
            headers=HEADERS,
            json={
                "length": exp["length"],
                "width": exp["width"],
                "height": exp["height"],
                "weightKg": exp["weightKg"],
            },
        )
        assert m_res.status_code == 200, m_res.text
        assert m_res.json()["mismatch"] is False

    chk_res = client.post(
        f"/api/pilot/work-orders/{wo_id}/packing-checklist",
        headers=HEADERS,
        json={},
    )
    assert chk_res.status_code == 200, chk_res.text
    assert chk_res.json()["mismatchHold"] is False
    assert chk_res.json()["carrierProvider"] == "BLOCKED/NOT_CONNECTED"

    comp_res = client.post(
        f"/api/pilot/work-orders/{wo_id}/complete",
        headers=HEADERS,
        json={"confirm": True, "actor": "e2e"},
    )
    assert comp_res.status_code == 200, comp_res.text
    assert comp_res.json()["state"] == "COMPLETED"

    orders_res = client.get("/api/pilot/work-orders", headers=HEADERS)
    assert orders_res.status_code == 200
    found = next(item for item in orders_res.json()["items"] if item["workOrderId"] == wo_id)
    assert found["state"] == "COMPLETED"

    # Retrying the same carton idempotencyKey after COMPLETED is idempotent, while a new key is 409.
    retry_same = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 2, "idempotencyKey": "e2e-cartons-key"},
    )
    assert retry_same.status_code == 200
    assert retry_same.json()["cartonIds"] == [c["cartonId"] for c in cartons]

    new_key_after_done = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "e2e-cartons-after-complete"},
    )
    assert new_key_after_done.status_code == 409


def test_draft_work_order_cannot_create_orphan_cartons(client: TestClient, platform: Any) -> None:
    product = platform.kd.build_sku(tenant_id=TENANT, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=TENANT, family="KD_FURNITURE")
    draft_wo = platform.pilot.workorders.create(tenant_id=TENANT, release=rel, quantity=1, actor="ops")
    res = client.post(
        f"/api/pilot/work-orders/{draft_wo['workOrderId']}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "draft-attempt"},
    )
    assert res.status_code == 409
    assert list(platform.pilot.logistics.cartons.values()) == []



# --- Review fixes for PR #733 (issue #738) -------------------------------------------------


def _wo_carton_ids(platform: Any, wo_id: str) -> set[str]:
    return {
        c["cartonId"]
        for c in platform.pilot.logistics.cartons.values()
        if c.get("workOrderId") == wo_id and c.get("tenantId") == TENANT
    }


def test_open_shelf_expected_weight_is_product_gross_kg(client: TestClient, platform: Any) -> None:
    product = platform.kd.build_sku(tenant_id=TENANT, kind="OPEN_SHELF")
    gross = float(product["weight"]["grossKg"])
    assert gross > 0 and abs(gross - 8.0) > 1.0  # the old 8 kg default would be caught
    rel, wo = _seed_release_receipt_and_wo(platform, product=product)
    assert rel["snapshot"]["weight"]["grossKg"] == product["weight"]["grossKg"]
    wo_id = wo["workOrderId"]

    created = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "weight-truth"},
    )
    assert created.status_code == 200, created.text
    carton = created.json()["items"][0]
    exp = carton["expected"]
    assert exp["weightKg"] == gross
    assert exp["length"] == float(product["packing"]["length"])
    assert exp["width"] == float(product["packing"]["width"])
    assert exp["height"] == float(product["packing"]["height"])

    measured = client.post(
        f"/api/pilot/cartons/{carton['cartonId']}/measured",
        headers=HEADERS,
        json={"length": exp["length"], "width": exp["width"], "height": exp["height"], "weightKg": gross},
    )
    assert measured.status_code == 200, measured.text
    assert measured.json()["mismatch"] is False
    assert measured.json()["mismatchHold"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda snap: snap.pop("weight", None),
        lambda snap: snap.__setitem__("weight", {"grossKg": "heavy"}),
        lambda snap: snap.__setitem__("weight", {"grossKg": float("nan")}),
        lambda snap: snap.__setitem__("weight", {"grossKg": 0}),
        lambda snap: snap.__setitem__("packing", {}),
        lambda snap: snap["packing"].pop("height"),
        lambda snap: snap["packing"].__setitem__("width", -5),
    ],
    ids=["no-weight", "weight-str", "weight-nan", "weight-zero", "no-packing", "no-height", "neg-width"],
)
def test_create_cartons_without_release_truth_is_422_not_default(
    client: TestClient, platform: Any, mutate: Any
) -> None:
    rel, wo = _seed_release_receipt_and_wo(platform)
    snap = platform.pilot.releases.releases[rel["releaseId"]]["snapshot"]
    snap["packing"] = dict(snap["packing"])
    mutate(snap)
    res = client.post(
        f"/api/pilot/work-orders/{wo['workOrderId']}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "no-truth"},
    )
    assert res.status_code == 422, res.text
    assert _wo_carton_ids(platform, wo["workOrderId"]) == set()
    assert platform.pilot.workorders.get(wo["workOrderId"]).get("cartonIds") in (None, [])


def test_mismatch_hold_resolved_by_human_allows_complete(client: TestClient, platform: Any) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    _complete_ops_and_qc(platform, wo)
    created = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "mm-resolve"},
    ).json()
    carton = created["items"][0]
    exp = carton["expected"]
    bad = {"length": exp["length"] + 50.0, "width": exp["width"], "height": exp["height"], "weightKg": exp["weightKg"]}
    for _ in range(2):  # replaying the same measurement must not open a second hold
        m = client.post(f"/api/pilot/cartons/{carton['cartonId']}/measured", headers=HEADERS, json=bad)
        assert m.status_code == 200, m.text
        assert m.json()["mismatch"] is True
        assert m.json()["mismatchHold"] is True

    rec = platform.pilot.workorders.get(wo_id)
    pm_holds = [h for h in rec["holds"] if h["reason"] == "PACKING_MISMATCH"]
    assert len(pm_holds) == 1
    assert pm_holds[0]["open"] is True and pm_holds[0]["blocking"] is True
    assert rec["mismatchHold"] is True

    blocked = client.post(f"/api/pilot/work-orders/{wo_id}/complete", headers=HEADERS, json={"confirm": True})
    assert blocked.status_code == 409
    assert "尺寸不符待人工確認" in blocked.json()["detail"]

    # Sign-off needs confirm and the owning tenant.
    url = f"/api/pilot/work-orders/{wo_id}/packing-mismatch/resolve"
    assert client.post(url, headers=HEADERS, json={}).status_code == 403
    assert client.post(url, headers={"X-Tenant-Id": "other-tenant"}, json={"confirm": True}).status_code == 404
    assert platform.pilot.workorders.get(wo_id)["holds"][-1]["open"] is True

    resolved = client.post(url, headers=HEADERS, json={"confirm": True, "actor": "lead"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["mismatchHold"] is False
    assert resolved.json()["resolvedHoldIds"] == [pm_holds[0]["holdId"]]
    again = client.post(url, headers=HEADERS, json={"confirm": True, "actor": "lead"})
    assert again.status_code == 200 and again.json()["resolvedHoldIds"] == []
    hold_resolve_events = [
        e for e in platform.pilot.journal.list(TENANT) if e.get("eventType") == "workorder.hold_resolve"
    ]
    assert len(hold_resolve_events) == 1

    chk = client.post(f"/api/pilot/work-orders/{wo_id}/packing-checklist", headers=HEADERS, json={})
    assert chk.status_code == 200
    assert chk.json()["mismatch"] is True
    assert chk.json()["mismatchHold"] is False

    done = client.post(f"/api/pilot/work-orders/{wo_id}/complete", headers=HEADERS, json={"confirm": True})
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "COMPLETED"
    stored = platform.pilot.logistics.cartons[carton["cartonId"]]
    assert stored["mismatch"] is True
    assert stored["autoOverride"] is False


def test_mismatch_resolved_via_existing_hold_flow_allows_complete(client: TestClient, platform: Any) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    _complete_ops_and_qc(platform, wo)
    carton = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "mm-service"},
    ).json()["items"][0]
    exp = carton["expected"]
    client.post(
        f"/api/pilot/cartons/{carton['cartonId']}/measured",
        headers=HEADERS,
        json={"length": exp["length"], "width": exp["width"], "height": exp["height"], "weightKg": exp["weightKg"] + 5},
    )
    rec = platform.pilot.workorders.get(wo_id)
    hold = next(h for h in rec["holds"] if h["reason"] == "PACKING_MISMATCH" and h["open"])
    platform.pilot.workorders.resolve_hold(wo_id, hold["holdId"], actor="lead")
    assert rec["mismatchHold"] is False
    assert rec["state"] == "IN_PROGRESS"
    done = client.post(f"/api/pilot/work-orders/{wo_id}/complete", headers=HEADERS, json={"confirm": True})
    assert done.status_code == 200, done.text
    assert platform.pilot.logistics.cartons[carton["cartonId"]]["mismatch"] is True
    assert platform.pilot.logistics.cartons[carton["cartonId"]]["autoOverride"] is False


def test_new_mismatch_after_signoff_blocks_again(client: TestClient, platform: Any) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    _complete_ops_and_qc(platform, wo)
    carton = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers=HEADERS,
        json={"quantity": 1, "idempotencyKey": "mm-again"},
    ).json()["items"][0]
    exp = carton["expected"]
    url = f"/api/pilot/cartons/{carton['cartonId']}/measured"
    body = {"length": exp["length"] + 50.0, "width": exp["width"], "height": exp["height"], "weightKg": exp["weightKg"]}
    client.post(url, headers=HEADERS, json=body)
    client.post(f"/api/pilot/work-orders/{wo_id}/packing-mismatch/resolve", headers=HEADERS, json={"confirm": True})
    body2 = {**body, "length": exp["length"] + 90.0}
    m = client.post(url, headers=HEADERS, json=body2)
    assert m.status_code == 200 and m.json()["mismatchHold"] is True
    blocked = client.post(f"/api/pilot/work-orders/{wo_id}/complete", headers=HEADERS, json={"confirm": True})
    assert blocked.status_code == 409
    assert "尺寸不符待人工確認" in blocked.json()["detail"]


def test_second_idempotency_key_on_same_work_order_is_409(client: TestClient, platform: Any) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    url = f"/api/pilot/work-orders/{wo_id}/cartons"
    first = client.post(url, headers=HEADERS, json={"quantity": 2, "idempotencyKey": "k-a"})
    assert first.status_code == 200
    ids = first.json()["cartonIds"]
    assert len(ids) == 2

    second = client.post(url, headers=HEADERS, json={"quantity": 1, "idempotencyKey": "k-b"})
    assert second.status_code == 409, second.text
    # Replaying the first key still works.
    replay = client.post(url, headers=HEADERS, json={"quantity": 2, "idempotencyKey": "k-a"})
    assert replay.status_code == 200 and replay.json()["cartonIds"] == ids

    rec = platform.pilot.workorders.get(wo_id)
    listed = client.get(url, headers=HEADERS).json()
    listed_ids = {c["cartonId"] for c in listed["items"]}
    assert set(rec["cartonIds"]) == set(rec["lineage"]["package"]) == listed_ids == set(ids)
    assert _wo_carton_ids(platform, wo_id) == set(ids)
    assert rec["state"] == "PACKING"


def test_qc_release_hold_does_not_close_unrelated_blocking_hold(client: TestClient, platform: Any) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    hold = platform.pilot.workorders.hold(wo_id, actor="qa", reason="MATERIAL_QUARANTINE", blocking=True)
    assert platform.pilot.workorders.get(wo_id)["state"] == "QC_HOLD"
    for idx, spec in enumerate(platform.pilot.qc.schema(wo["productFamily"])):
        nominal = float(spec["nominal"] if spec["nominal"] is not None else 100.0)
        res = client.post(
            f"/api/pilot/work-orders/{wo_id}/qc",
            headers=HEADERS,
            json={
                "stage": "FINAL",
                "checkId": spec["checkId"],
                "measured": nominal,
                "nominal": nominal,
                "tol": float(spec["tol"]),
                "unit": spec["unit"],
                "idempotencyKey": f"quarantine-{idx}",
            },
        )
        assert res.status_code == 200, res.text
    resolve_before = [
        e for e in platform.pilot.journal.list(TENANT) if e.get("eventType") == "workorder.hold_resolve"
    ]
    rel_hold = client.post(
        f"/api/pilot/work-orders/{wo_id}/qc/release-hold",
        headers=HEADERS,
        json={"confirm": True, "actor": "e2e"},
    )
    assert rel_hold.status_code == 409, rel_hold.text
    assert "MATERIAL_QUARANTINE" in rel_hold.json()["detail"]
    rec = platform.pilot.workorders.get(wo_id)
    stored = next(h for h in rec["holds"] if h["holdId"] == hold["holdId"])
    assert stored["open"] is True
    assert "resolvedBy" not in stored
    assert rec["state"] == "QC_HOLD"
    resolve_after = [
        e for e in platform.pilot.journal.list(TENANT) if e.get("eventType") == "workorder.hold_resolve"
    ]
    assert len(resolve_after) == len(resolve_before)


def test_qc_routes_reject_draft_work_order(client: TestClient, platform: Any) -> None:
    product = platform.kd.build_sku(tenant_id=TENANT, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=TENANT, family="KD_FURNITURE")
    draft = platform.pilot.workorders.create(tenant_id=TENANT, release=rel, quantity=1, actor="ops")
    wo_id = draft["workOrderId"]
    spec = platform.pilot.qc.schema(draft["productFamily"])[0]
    nominal = float(spec["nominal"] if spec["nominal"] is not None else 100.0)
    fail = client.post(
        f"/api/pilot/work-orders/{wo_id}/qc",
        headers=HEADERS,
        json={
            "stage": "FINAL",
            "checkId": spec["checkId"],
            "measured": nominal + 10,
            "nominal": nominal,
            "tol": float(spec["tol"]),
            "unit": spec["unit"],
            "idempotencyKey": "draft-qc",
        },
    )
    assert fail.status_code == 409, fail.text
    assert platform.pilot.workorders.get(wo_id)["state"] == "DRAFT"
    assert [c for c in platform.pilot.qc.checks.values() if c["workOrderId"] == wo_id] == []
    rel_hold = client.post(
        f"/api/pilot/work-orders/{wo_id}/qc/release-hold", headers=HEADERS, json={"confirm": True}
    )
    assert rel_hold.status_code == 409
    assert platform.pilot.workorders.get(wo_id)["state"] == "DRAFT"

    released = platform.pilot.workorders.release_for_execution(wo_id, actor="ops")
    assert released["state"] == "RELEASED_FOR_MANUAL_EXECUTION"
    assert (
        client.post(
            f"/api/pilot/work-orders/{wo_id}/qc/release-hold", headers=HEADERS, json={"confirm": True}
        ).status_code
        == 409
    )


def test_qc_service_failed_check_uses_state_machine(platform: Any) -> None:
    product = platform.kd.build_sku(tenant_id=TENANT, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=TENANT, family="KD_FURNITURE")
    draft = platform.pilot.workorders.create(tenant_id=TENANT, release=rel, quantity=1, actor="ops")
    with pytest.raises(PermissionError):
        platform.pilot.qc.record(
            tenant_id=TENANT,
            work_order_id=draft["workOrderId"],
            stage="FINAL",
            check_id="THICKNESS",
            measured=30.0,
            nominal=18.0,
            tol=0.5,
            unit="mm",
            operator="qc",
        )
    assert platform.pilot.workorders.get(draft["workOrderId"])["state"] == "DRAFT"

    _rel, wo = _seed_release_receipt_and_wo(platform)
    platform.pilot.qc.record(
        tenant_id=TENANT,
        work_order_id=wo["workOrderId"],
        stage="FINAL",
        check_id="THICKNESS",
        measured=30.0,
        nominal=18.0,
        tol=0.5,
        unit="mm",
        operator="qc",
    )
    rec = platform.pilot.workorders.get(wo["workOrderId"])
    assert rec["state"] == "QC_HOLD"
    assert rec["audit"][-1]["to"] == "QC_HOLD"
    assert rec["audit"][-1]["from"] == "MATERIAL_RESERVED"


def test_qc_idempotency_survives_restart(platform: Any) -> None:
    _rel, wo = _seed_release_receipt_and_wo(platform)
    wo_id = wo["workOrderId"]
    body = {
        "stage": "FINAL",
        "checkId": "THICKNESS",
        "measured": 18.0,
        "nominal": 18.0,
        "tol": 0.5,
        "unit": "mm",
        "idempotencyKey": "qc-restart-key",
    }
    first = TestClient(create_app(platform)).post(f"/api/pilot/work-orders/{wo_id}/qc", headers=HEADERS, json=body)
    assert first.status_code == 200, first.text
    qc_id = first.json()["qcId"]

    def thickness_rows(plat: Any) -> list[dict[str, Any]]:
        return [c for c in plat.pilot.qc.checks.values() if c["workOrderId"] == wo_id and c["checkId"] == "THICKNESS"]

    # A brand-new platform on the same data directory == process restart.
    restarted = type(platform)(root=platform.root, mock_blender=True)
    client2 = TestClient(create_app(restarted))
    assert len(thickness_rows(restarted)) == 1

    conflict = client2.post(
        f"/api/pilot/work-orders/{wo_id}/qc", headers=HEADERS, json={**body, "measured": 38.5}
    )
    assert conflict.status_code == 409, conflict.text
    assert len(thickness_rows(restarted)) == 1
    assert restarted.pilot.qc.required_final_ok(wo_id, wo["productFamily"], tenant_id=TENANT)["failed"] == []

    replay = client2.post(f"/api/pilot/work-orders/{wo_id}/qc", headers=HEADERS, json=body)
    assert replay.status_code == 200
    assert replay.json()["qcId"] == qc_id
    assert len(thickness_rows(restarted)) == 1

    # Keys are scoped per tenant: another tenant cannot see or collide with this record.
    other = client2.post(
        f"/api/pilot/work-orders/{wo_id}/qc", headers={"X-Tenant-Id": "other-tenant"}, json=body
    )
    assert other.status_code == 404
