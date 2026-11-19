"""Tests for pilot shipping HTTP API (/api/pilot/pallets, shipments, handoff, carrier-quotes, carton label) and Playwright flow."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform
from tests.test_pilot_packing_api import HEADERS, TENANT, _concurrent, _seed_release_receipt_and_wo

OTHER_TENANT = "other-shipping-tenant"
OTHER_HEADERS = {"X-Tenant-Id": OTHER_TENANT}


@pytest.fixture()
def client(platform: Any) -> TestClient:
    return TestClient(create_app(platform))


def _create_cartons(
    client: TestClient,
    platform: Any,
    *,
    tenant: str = TENANT,
    quantity: int = 2,
    idem_key: str = "ship-cartons-1",
    stackable_dims: bool = True,
) -> tuple[str, list[str]]:
    _rel, wo = _seed_release_receipt_and_wo(platform, tenant=tenant)
    wo_id = wo["workOrderId"]
    res = client.post(
        f"/api/pilot/work-orders/{wo_id}/cartons",
        headers={"X-Tenant-Id": tenant},
        json={"quantity": quantity, "idempotencyKey": idem_key},
    )
    assert res.status_code == 200, res.text
    carton_ids = list(res.json()["cartonIds"])
    if stackable_dims:
        for cid in carton_ids:
            m = client.post(
                f"/api/pilot/cartons/{cid}/measured",
                headers={"X-Tenant-Id": tenant},
                json={"length": 400, "width": 300, "height": 200, "weightKg": 10.0, "source": "MANUAL"},
            )
            assert m.status_code == 200, m.text
    return wo_id, carton_ids


def test_palletize_and_cross_tenant_carton_rejected_all_or_nothing(
    client: TestClient, platform: Any
) -> None:
    _wo_a, cartons_a = _create_cartons(client, platform, tenant=TENANT, quantity=2, idem_key="pal-a")
    _wo_b, cartons_b = _create_cartons(client, platform, tenant=OTHER_TENANT, quantity=1, idem_key="pal-b")

    # Mixed batch containing one caller carton and one cross-tenant carton must fail 404 with zero writes.
    mixed = client.post(
        "/api/pilot/pallets",
        headers=HEADERS,
        json={"cartonIds": [cartons_a[0], cartons_b[0]]},
    )
    assert mixed.status_code == 404
    assert mixed.json() == {"detail": "找不到紙箱"}
    assert platform.pilot.logistics.pallets == {}

    # Mixed batch with one valid carton and one unknown carton must also fail 404 with zero writes.
    unknown_mix = client.post(
        "/api/pilot/pallets",
        headers=HEADERS,
        json={"cartonIds": [cartons_a[0], "non-existent-carton"]},
    )
    assert unknown_mix.status_code == 404
    assert platform.pilot.logistics.pallets == {}

    # Pure caller cartons succeed.
    ok = client.post(
        "/api/pilot/pallets",
        headers=HEADERS,
        json={"cartonIds": cartons_a, "idempotencyKey": "pal-idem-1"},
    )
    assert ok.status_code == 200, ok.text
    plan = ok.json()
    assert plan["tenantId"] == TENANT
    assert plan["cartonIds"] == cartons_a
    assert plan["palletCount"] >= 1
    assert plan["carrierCertification"] is False
    assert plan["label"] == "PLANNING"
    assert plan["status"] == "PLANNING"
    assert plan["oversize"] is False

    # Same idempotencyKey + same cartonIds returns the same palletPlanId.
    retry = client.post(
        "/api/pilot/pallets",
        headers=HEADERS,
        json={"cartonIds": cartons_a, "idempotencyKey": "pal-idem-1"},
    )
    assert retry.status_code == 200
    assert retry.json()["palletPlanId"] == plan["palletPlanId"]
    assert len(platform.pilot.logistics.pallets) == 1

    # Same idempotencyKey + different cartonIds returns 409.
    conflict = client.post(
        "/api/pilot/pallets",
        headers=HEADERS,
        json={"cartonIds": [cartons_a[0]], "idempotencyKey": "pal-idem-1"},
    )
    assert conflict.status_code == 409

    # Oversize measured carton is flagged as NEEDS_HUMAN and held.
    measured = client.post(
        f"/api/pilot/cartons/{cartons_a[0]}/measured",
        headers=HEADERS,
        json={"length": 1500, "width": 1200, "height": 1600, "weightKg": 600, "source": "MANUAL"},
    )
    assert measured.status_code == 200
    oversize_plan = client.post(
        "/api/pilot/pallets",
        headers=HEADERS,
        json={"cartonIds": [cartons_a[0]]},
    )
    assert oversize_plan.status_code == 200
    assert oversize_plan.json()["oversize"] is True
    assert oversize_plan.json()["status"] == "NEEDS_HUMAN"
    assert cartons_a[0] in oversize_plan.json()["heldCartonIds"]

    # Listing pallets is tenant-isolated.
    list_a = client.get("/api/pilot/pallets", headers=HEADERS)
    assert list_a.status_code == 200
    assert list_a.json()["total"] == 2
    list_b = client.get("/api/pilot/pallets", headers=OTHER_HEADERS)
    assert list_b.status_code == 200
    assert list_b.json()["items"] == []


def test_shipment_draft_cross_tenant_carton_rejected_all_or_nothing(
    client: TestClient, platform: Any
) -> None:
    _wo_a, cartons_a = _create_cartons(client, platform, tenant=TENANT, quantity=2, idem_key="ship-a")
    _wo_b, cartons_b = _create_cartons(client, platform, tenant=OTHER_TENANT, quantity=1, idem_key="ship-b")

    events_before = len(platform.pilot.journal.list(TENANT))

    # One valid carton + one cross-tenant carton -> 404 and zero shipments created.
    mixed = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={
            "origin": "TW",
            "destination": "TW-TPE",
            "cartonIds": [cartons_a[0], cartons_b[0]],
            "service": "ground",
        },
    )
    assert mixed.status_code == 404
    assert mixed.json() == {"detail": "找不到紙箱"}
    assert platform.pilot.logistics.shipments == {}
    assert len(platform.pilot.journal.list(TENANT)) == events_before

    # One valid carton + one unknown carton -> 404 and zero shipments created.
    missing = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={
            "origin": "TW",
            "destination": "TW-TPE",
            "cartonIds": [cartons_a[0], "missing-carton-id"],
            "service": "ground",
        },
    )
    assert missing.status_code == 404
    assert platform.pilot.logistics.shipments == {}

    # All cartons belonging to caller tenant -> 200 SHIPMENT_DRAFT.
    ok = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={
            "origin": "TW",
            "destination": "TW-TPE",
            "cartonIds": cartons_a,
            "service": "ground",
        },
    )
    assert ok.status_code == 200, ok.text
    draft = ok.json()
    assert draft["tenantId"] == TENANT
    assert draft["status"] == "SHIPMENT_DRAFT"
    assert draft["booked"] is False
    assert draft["submittedToCarrier"] is False
    assert draft["shipped"] is False
    assert draft["liveCarrier"] is False
    assert draft["pieces"] == 2
    assert draft["cartonIds"] == cartons_a

    # Re-posting same draft with reversed carton order is idempotent.
    replay = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={
            "origin": "TW",
            "destination": "TW-TPE",
            "cartonIds": list(reversed(cartons_a)),
            "service": "ground",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["shipmentId"] == draft["shipmentId"]
    assert len(platform.pilot.logistics.shipments) == 1

    # Detail endpoint works for owner and returns 404 for another tenant or unknown id.
    detail = client.get(f"/api/pilot/shipments/{draft['shipmentId']}", headers=HEADERS)
    assert detail.status_code == 200
    assert detail.json()["shipmentId"] == draft["shipmentId"]
    assert client.get(f"/api/pilot/shipments/{draft['shipmentId']}", headers=OTHER_HEADERS).status_code == 404
    assert client.get("/api/pilot/shipments/unknown-shipment", headers=HEADERS).status_code == 404


def test_handoff_idempotent_retry_and_concurrent_single_execution(
    client: TestClient, platform: Any
) -> None:
    _wo, cartons = _create_cartons(client, platform, tenant=TENANT, quantity=2, idem_key="ho-cartons")
    draft_res = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={"origin": "TW", "destination": "TW-TPE", "cartonIds": [cartons[0]], "service": "ground"},
    )
    assert draft_res.status_code == 200
    shipment_id = draft_res.json()["shipmentId"]

    draft2_res = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={"origin": "TW", "destination": "TW-KHH", "cartonIds": [cartons[1]], "service": "ground"},
    )
    assert draft2_res.status_code == 200
    shipment2_id = draft2_res.json()["shipmentId"]

    payload = {"carrier": "MANUAL_VAN", "tracking": "TRK-CONC-001", "actor": "ship-op"}

    # Fire 6 concurrent handoff requests with the same tracking code.
    responses = _concurrent(
        6,
        lambda: client.post(
            f"/api/pilot/shipments/{shipment_id}/handoff",
            headers=HEADERS,
            json=payload,
        ),
    )
    assert [r.status_code for r in responses] == [200] * 6
    handoff_ids = {r.json()["handoff"]["handoffId"] for r in responses}
    assert len(handoff_ids) == 1
    handoff_timestamps = {r.json()["handoff"]["at"] for r in responses}
    assert len(handoff_timestamps) == 1

    first_handoff = responses[0].json()
    assert first_handoff["status"] == "HANDED_OFF_MANUAL"
    assert first_handoff["booked"] is False
    assert first_handoff["submittedToCarrier"] is False
    assert first_handoff["handoff"]["liveProvider"] is False
    assert first_handoff["handoff"]["deliveryConfirmed"] is False
    assert first_handoff["handoff"]["tracking"] == "TRK-CONC-001"

    # Only 1 handoff record and 1 journal event were created.
    assert len(platform.pilot.logistics.handoffs) == 1
    handoff_events = [
        e
        for e in platform.pilot.journal.list(TENANT)
        if e.get("eventType") == "shipment.handoff" and e.get("aggregateId") == shipment_id
    ]
    assert len(handoff_events) == 1

    # Sequential retry with same tracking returns original result without creating another handoff.
    again = client.post(
        f"/api/pilot/shipments/{shipment_id}/handoff",
        headers=HEADERS,
        json=payload,
    )
    assert again.status_code == 200
    assert again.json()["handoff"] == first_handoff["handoff"]
    assert len(platform.pilot.logistics.handoffs) == 1

    # Reusing the same tracking on a different shipment is rejected with 409.
    reuse_on_other_ship = client.post(
        f"/api/pilot/shipments/{shipment2_id}/handoff",
        headers=HEADERS,
        json=payload,
    )
    assert reuse_on_other_ship.status_code == 409
    assert platform.pilot.logistics.shipments[shipment2_id]["status"] == "SHIPMENT_DRAFT"

    # Handing off an already handed-off shipment with a different tracking is rejected with 409.
    different_tracking = client.post(
        f"/api/pilot/shipments/{shipment_id}/handoff",
        headers=HEADERS,
        json={"carrier": "MANUAL_VAN", "tracking": "TRK-DIFFERENT-999"},
    )
    assert different_tracking.status_code == 409
    assert platform.pilot.logistics.shipments[shipment_id]["handoff"]["tracking"] == "TRK-CONC-001"

    # Other tenant or unknown shipment returns 404.
    assert (
        client.post(
            f"/api/pilot/shipments/{shipment_id}/handoff",
            headers=OTHER_HEADERS,
            json=payload,
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/pilot/shipments/unknown-shipment/handoff",
            headers=HEADERS,
            json=payload,
        ).status_code
        == 404
    )


def test_shipments_pagination_by_created_at_and_status_filter(
    client: TestClient, platform: Any
) -> None:
    _wo, cartons = _create_cartons(client, platform, tenant=TENANT, quantity=5, idem_key="page-cartons")
    shipment_ids: list[str] = []
    for idx, cid in enumerate(cartons):
        res = client.post(
            "/api/pilot/shipments",
            headers=HEADERS,
            json={
                "origin": "TW",
                "destination": f"DEST-{idx}",
                "cartonIds": [cid],
                "service": "ground",
            },
        )
        assert res.status_code == 200
        sid = res.json()["shipmentId"]
        # Assign deterministic createdAt timestamps (with a shared pair to verify shipmentId tie-breaking).
        minute = idx // 2
        platform.pilot.logistics.shipments[sid]["createdAt"] = f"2026-11-19T10:{minute:02d}:00+00:00"
        shipment_ids.append(sid)

    # Hand off 2 of the 5 shipments.
    for idx in (1, 3):
        ho = client.post(
            f"/api/pilot/shipments/{shipment_ids[idx]}/handoff",
            headers=HEADERS,
            json={"carrier": "VAN", "tracking": f"TRK-PAGE-{idx}"},
        )
        assert ho.status_code == 200

    platform.pilot.logistics.persist()

    expected_order = [
        sid
        for _, sid in sorted(
            ((platform.pilot.logistics.shipments[s]["createdAt"], s) for s in shipment_ids),
            reverse=True,
        )
    ]

    collected: list[str] = []
    for offset, expected_count in ((0, 2), (2, 2), (4, 1)):
        page = client.get(
            "/api/pilot/shipments",
            headers=HEADERS,
            params={"offset": offset, "limit": 2},
        )
        assert page.status_code == 200
        body = page.json()
        assert body["total"] == 5
        assert body["offset"] == offset
        assert body["limit"] == 2
        ids = [item["shipmentId"] for item in body["items"]]
        assert len(ids) == expected_count
        collected.extend(ids)

    assert collected == expected_order

    # Filter by status=SHIPMENT_DRAFT vs status=HANDED_OFF_MANUAL.
    drafts = client.get("/api/pilot/shipments", headers=HEADERS, params={"status": "SHIPMENT_DRAFT"})
    assert drafts.status_code == 200
    assert drafts.json()["total"] == 3
    assert all(item["status"] == "SHIPMENT_DRAFT" for item in drafts.json()["items"])

    handed = client.get("/api/pilot/shipments", headers=HEADERS, params={"status": "HANDED_OFF_MANUAL"})
    assert handed.status_code == 200
    assert handed.json()["total"] == 2
    assert {item["shipmentId"] for item in handed.json()["items"]} == {shipment_ids[1], shipment_ids[3]}

    # Other tenant sees an empty list.
    other_list = client.get("/api/pilot/shipments", headers=OTHER_HEADERS)
    assert other_list.status_code == 200
    assert other_list.json()["items"] == []
    assert other_list.json()["total"] == 0


def test_carrier_quotes_manual_json_csv_and_quote_stale_flagging(
    client: TestClient, platform: Any
) -> None:
    _wo, cartons = _create_cartons(client, platform, tenant=TENANT, quantity=2, idem_key="quote-cartons")

    # 1. Manual quote for ground / dimDivisor 6000 (valid).
    manual = client.post(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        json={
            "carrier": "TCAT",
            "service": "ground",
            "charge": 180,
            "currency": "TWD",
            "dimDivisor": 6000,
            "validUntil": "2099-12-31",
            "source": "MANUAL",
        },
    )
    assert manual.status_code == 200, manual.text
    q_ground = manual.json()
    assert q_ground["source"] == "MANUAL"
    assert q_ground["liveProvider"] is False
    assert q_ground["stale"] is False
    assert q_ground["quoteStale"] is False
    assert q_ground["usable"] is True
    assert q_ground["status"] == "VALID_REFERENCE"

    # 2. CSV import (via JSON wrapper and via multipart file upload).
    csv_text = "carrier,service,charge,dimDivisor,validUntil\nHCT,air,420,5000,2099-12-31\nEXPIRED-EXP,ground,150,6000,2020-01-01\n"
    csv_res = client.post(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        json={"format": "csv", "content": csv_text},
    )
    assert csv_res.status_code == 200, csv_res.text
    assert csv_res.json()["count"] == 2
    q_air = csv_res.json()["items"][0]
    q_expired = csv_res.json()["items"][1]
    assert q_air["source"] == "IMPORTED"
    # Expired validUntil is immediately flagged stale and never usable.
    assert q_expired["stale"] is True
    assert q_expired["quoteStale"] is True
    assert q_expired["usable"] is False
    assert q_expired["available"] is False
    assert q_expired["status"] == "QUOTE_STALE"
    assert "過期" in q_expired["statusLabel"] and "不可用" in q_expired["statusLabel"]

    # 3. Multipart JSON file upload.
    json_bytes = json.dumps([{"carrier": "KERRY", "service": "ground", "charge": 210, "dimDivisor": 5000}]).encode("utf-8")
    file_res = client.post(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        files={"file": ("quotes.json", io.BytesIO(json_bytes), "application/json")},
    )
    assert file_res.status_code == 200, file_res.text
    q_wrong_div = file_res.json()["items"][0]

    # 4. Query quotes against service="ground" & dimDivisor=6000:
    # - q_ground is valid (stale=False)
    # - q_air has service="air" != "ground" -> stale=True
    # - q_wrong_div has dimDivisor=5000 != 6000 -> stale=True
    # - q_expired has validUntil="2020-01-01" -> stale=True
    check_list = client.get(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        params={"service": "ground", "dimDivisor": 6000},
    )
    assert check_list.status_code == 200
    by_id = {q["quoteId"]: q for q in check_list.json()["items"]}
    assert by_id[q_ground["quoteId"]]["stale"] is False
    assert by_id[q_ground["quoteId"]]["usable"] is True
    for stale_id in (q_air["quoteId"], q_wrong_div["quoteId"], q_expired["quoteId"]):
        sq = by_id[stale_id]
        assert sq["stale"] is True
        assert sq["quoteStale"] is True
        assert sq["usable"] is False
        assert sq["available"] is False
        assert sq["status"] == "QUOTE_STALE"
        assert "不可用" in sq["statusLabel"]

    # 5. Shipment draft bound to a stale quote (service mismatch: ground shipment + air quote) flags quoteStale=True.
    ship_stale = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={
            "origin": "TW",
            "destination": "TW-TXG",
            "cartonIds": [cartons[0]],
            "service": "ground",
            "quoteId": q_air["quoteId"],
        },
    )
    assert ship_stale.status_code == 200
    s_body = ship_stale.json()
    assert s_body["quoteStale"] is True
    assert s_body["quoteUsable"] is False
    assert s_body["quoteStatus"] == "QUOTE_STALE"
    assert s_body["quote"]["stale"] is True
    assert s_body["quote"]["usable"] is False
    assert "不可用" in s_body["quoteStatusLabel"]

    # Shipment bound to a matching quote (ground + dimDivisor 6000) has quoteStale=False.
    ship_valid = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={
            "origin": "TW",
            "destination": "TW-HSZ",
            "cartonIds": [cartons[1]],
            "service": "ground",
            "quoteId": q_ground["quoteId"],
        },
    )
    assert ship_valid.status_code == 200
    assert ship_valid.json()["quoteStale"] is False
    assert ship_valid.json()["quoteUsable"] is True
    assert ship_valid.json()["quoteStatus"] == "VALID_REFERENCE"

    # Re-evaluating ship_valid with dimDivisor=5000 on GET marks the quote stale!
    recheck = client.get(
        f"/api/pilot/shipments/{ship_valid.json()['shipmentId']}",
        headers=HEADERS,
        params={"dimDivisor": 5000},
    )
    assert recheck.status_code == 200
    assert recheck.json()["quoteStale"] is True
    assert recheck.json()["quoteUsable"] is False

    # Other tenant cannot see or bind caller tenant's HTTP-imported quotes.
    assert client.get("/api/pilot/carrier-quotes", headers=OTHER_HEADERS).json()["items"] == []
    _wo_b, cartons_b = _create_cartons(client, platform, tenant=OTHER_TENANT, quantity=1, idem_key="quote-b")
    cross_quote_ship = client.post(
        "/api/pilot/shipments",
        headers=OTHER_HEADERS,
        json={
            "origin": "TW",
            "destination": "TW-TPE",
            "cartonIds": cartons_b,
            "quoteId": q_ground["quoteId"],
        },
    )
    assert cross_quote_ship.status_code == 404


def test_carton_label_payload_and_tenant_isolation(
    client: TestClient, platform: Any
) -> None:
    _wo, cartons = _create_cartons(client, platform, tenant=TENANT, quantity=1, idem_key="lbl-cartons")
    cid = cartons[0]

    res = client.get(f"/api/pilot/cartons/{cid}/label", headers=HEADERS)
    assert res.status_code == 200
    label = res.json()
    assert label["cartonId"] == cid
    assert label["barcode"]["symbology"] == "CODE128"
    assert label["barcode"]["printVerified"] is False
    assert label["barcode"]["label"] == "PARTIAL"
    assert label["qr"]["printVerified"] is False
    assert label["qr"]["label"] == "PARTIAL"
    assert label["printerPath"] is None
    assert label["scannerPath"] is None
    assert cid[:8] in label["barcode"]["payload"]

    # Cross-tenant and unknown carton return 404.
    assert client.get(f"/api/pilot/cartons/{cid}/label", headers=OTHER_HEADERS).status_code == 404
    assert client.get("/api/pilot/cartons/missing-carton/label", headers=HEADERS).status_code == 404


def test_bad_inputs_return_422_and_never_partial_write(
    client: TestClient, platform: Any
) -> None:
    _wo, cartons = _create_cartons(client, platform, tenant=TENANT, quantity=2, idem_key="bad-in-cartons")
    cid = cartons[0]

    # Invalid X-Tenant-Id header -> 400; mismatched body tenantId -> 403.
    assert client.get("/api/pilot/shipments").status_code == 400
    assert client.get("/api/pilot/shipments", headers={"X-Tenant-Id": "../bad"}).status_code == 400
    assert (
        client.post(
            "/api/pilot/pallets",
            headers=HEADERS,
            json={"tenantId": OTHER_TENANT, "cartonIds": [cid]},
        ).status_code
        == 403
    )

    # Bad POST /api/pilot/pallets payloads -> 422.
    bad_pallets: tuple[Any, ...] = (
        None,
        [],
        "not-a-dict",
        {},
        {"cartonIds": []},
        {"cartonIds": "not-a-list"},
        {"cartonIds": [""]},
        {"cartonIds": ["   "]},
        {"cartonIds": [123]},
        {"cartonIds": [None]},
        {"cartonIds": [cid, cid]},
        {"cartonIds": [cid], "idempotencyKey": "   "},
        {"cartonIds": [cid], "idempotencyKey": 123},
        {"cartonIds": [cid], "tenantId": 123},
    )
    for bad_pallet in bad_pallets:
        res = client.post("/api/pilot/pallets", headers=HEADERS, json=bad_pallet)
        assert res.status_code == 422, f"pallet {bad_pallet!r} -> {res.status_code} {res.text}"
        assert "Traceback" not in res.text

    # Bad POST /api/pilot/shipments payloads -> 422.
    for bad_ship in (
        {},
        {"origin": "", "destination": "TPE", "cartonIds": [cid]},
        {"origin": "   ", "destination": "TPE", "cartonIds": [cid]},
        {"origin": 123, "destination": "TPE", "cartonIds": [cid]},
        {"origin": "TW", "destination": "", "cartonIds": [cid]},
        {"origin": "TW", "destination": None, "cartonIds": [cid]},
        {"origin": "TW", "destination": "TPE", "cartonIds": []},
        {"origin": "TW", "destination": "TPE", "cartonIds": [cid, cid]},
        {"origin": "TW", "destination": "TPE", "cartonIds": [cid], "service": "   "},
        {"origin": "TW", "destination": "TPE", "cartonIds": [cid], "service": 123},
        {"origin": "TW", "destination": "TPE", "cartonIds": [cid], "dimDivisor": 0},
        {"origin": "TW", "destination": "TPE", "cartonIds": [cid], "dimDivisor": -6000},
        {"origin": "TW", "destination": "TPE", "cartonIds": [cid], "dimDivisor": "bad"},
        {"origin": "TW", "destination": "TPE", "cartonIds": [cid], "dimDivisor": True},
        {"origin": "TW", "destination": "TPE", "cartonIds": [cid], "quoteId": 123},
    ):
        res = client.post("/api/pilot/shipments", headers=HEADERS, json=bad_ship)
        assert res.status_code == 422, f"ship {bad_ship!r} -> {res.status_code} {res.text}"
        assert "Traceback" not in res.text

    # Bad GET /api/pilot/shipments query params -> 422.
    for bad_query in (
        {"offset": -1},
        {"limit": 0},
        {"limit": 101},
        {"limit": "abc"},
        {"status": "BOGUS_STATUS"},
        {"state": "UNKNOWN"},
    ):
        res = client.get("/api/pilot/shipments", headers=HEADERS, params=bad_query)
        assert res.status_code == 422, f"list query {bad_query!r} -> {res.status_code}"

    # Create one valid shipment to test bad handoff inputs.
    ship = client.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={"origin": "TW", "destination": "TPE", "cartonIds": [cid]},
    ).json()
    sid = ship["shipmentId"]

    for bad_handoff in (
        {},
        {"carrier": "", "tracking": "T1"},
        {"carrier": "   ", "tracking": "T1"},
        {"carrier": 123, "tracking": "T1"},
        {"carrier": "VAN", "tracking": ""},
        {"carrier": "VAN", "tracking": "   "},
        {"carrier": "VAN", "tracking": None},
        {"carrier": "VAN", "tracking": ["T1"]},
        {"carrier": "VAN", "tracking": "T1", "actor": 123},
        {"carrier": "VAN", "tracking": "T1", "confirm": False},
    ):
        res = client.post(f"/api/pilot/shipments/{sid}/handoff", headers=HEADERS, json=bad_handoff)
        assert res.status_code == 422, f"handoff {bad_handoff!r} -> {res.status_code} {res.text}"
        assert "Traceback" not in res.text

    # Bad POST /api/pilot/carrier-quotes payloads -> 422 and atomic rollback on batch error.
    quotes_before = set(platform.pilot.logistics.carrier_quotes)
    bad_quotes: tuple[dict[str, Any], ...] = (
        {},
        {"carrier": "", "charge": 100},
        {"carrier": 123, "charge": 100},
        {"carrier": "DHL"},
        {"carrier": "DHL", "charge": 0},
        {"carrier": "DHL", "charge": -50},
        {"carrier": "DHL", "charge": "bad"},
        {"carrier": "DHL", "charge": True},
        {"carrier": "DHL", "charge": [100]},
        {"carrier": "DHL", "charge": 100, "dimDivisor": 0},
        {"carrier": "DHL", "charge": 100, "dimDivisor": -10},
        {"carrier": "DHL", "charge": 100, "dimDivisor": "bad"},
        {"carrier": "DHL", "charge": 100, "source": "LIVE_PROVIDER"},
        {"carrier": "DHL", "charge": 100, "liveProvider": True},
        {"carrier": "DHL", "charge": 100, "validUntil": "not-a-date"},
        {"carrier": "DHL", "charge": 100, "validUntil": "9999-99-99"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2026-02-30"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2025-02-29"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2026-13-01"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2026-00-10"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2026-04-31"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2026-01-00"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2099-12-31extra"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2099-12-31T00:00:00"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2099-12-31 12:00"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2099/12/31"},
        {"carrier": "DHL", "charge": 100, "validUntil": "2099-1-1"},
        {"rows": []},
        {"rows": [{"carrier": "GOOD", "charge": 100}, {"carrier": "BAD", "charge": "not-a-number"}]},
        {
            "rows": [
                {"quoteId": "dup-q1", "carrier": "GOOD", "charge": 100},
                {"quoteId": "dup-q1", "carrier": "GOOD2", "charge": 120},
            ]
        },
        {"csv": ""},
        {"csv": "carrier,charge\nGOOD,100\nBAD,negative-text"},
        {"json": "{malformed json"},
    )
    for bad_quote in bad_quotes:
        res = client.post("/api/pilot/carrier-quotes", headers=HEADERS, json=bad_quote)
        assert res.status_code == 422, f"quote {bad_quote!r} -> {res.status_code} {res.text}"
        assert "Traceback" not in res.text
        assert set(platform.pilot.logistics.carrier_quotes) == quotes_before


def test_carrier_quote_cross_tenant_id_collision_and_crash_recovery(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "quote-isolation-root"
    plat = Platform(root=root, mock_blender=True)
    c1 = TestClient(create_app(plat))

    # 1. Tenant A creates a quote with an explicit quoteId and another with server-generated quoteId.
    q_a1 = c1.post(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        json={
            "quoteId": "quote-tenant-a-1",
            "carrier": "TCAT-A",
            "service": "ground",
            "charge": 180,
            "dimDivisor": 6000,
            "validUntil": "2028-02-29",
        },
    )
    assert q_a1.status_code == 200, q_a1.text
    q_a2 = c1.post(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        json={"carrier": "HCT-A", "service": "air", "charge": 350, "dimDivisor": 5000},
    )
    assert q_a2.status_code == 200, q_a2.text
    qid_a2 = q_a2.json()["quoteId"]

    # 2. Tenant B attempts to overwrite Tenant A's quoteId (both explicit and server-generated).
    for target_qid in ("quote-tenant-a-1", qid_a2):
        steal = c1.post(
            "/api/pilot/carrier-quotes",
            headers=OTHER_HEADERS,
            json={"quoteId": target_qid, "carrier": "STEAL-B", "service": "ground", "charge": 1},
        )
        assert steal.status_code == 409, steal.text

    # 3. Tenant B sends a multi-row batch where row 0 is new and row 1 collides with Tenant A's quoteId.
    # The entire batch must be rejected atomically with zero writes.
    batch_collision = c1.post(
        "/api/pilot/carrier-quotes",
        headers=OTHER_HEADERS,
        json={
            "rows": [
                {"quoteId": "quote-tenant-b-clean", "carrier": "KERRY-B", "charge": 210},
                {"quoteId": "quote-tenant-a-1", "carrier": "STEAL-B", "charge": 1},
            ]
        },
    )
    assert batch_collision.status_code == 409, batch_collision.text
    assert "quote-tenant-b-clean" not in plat.pilot.logistics.carrier_quotes

    # Tenant A's list still has both original quotes untouched; Tenant B has none.
    list_a = c1.get("/api/pilot/carrier-quotes", headers=HEADERS).json()
    assert list_a["total"] == 2
    by_id_a = {q["quoteId"]: q for q in list_a["items"]}
    assert by_id_a["quote-tenant-a-1"]["carrier"] == "TCAT-A"
    assert by_id_a["quote-tenant-a-1"]["charge"] == 180.0
    assert by_id_a[qid_a2]["carrier"] == "HCT-A"
    assert c1.get("/api/pilot/carrier-quotes", headers=OTHER_HEADERS).json()["items"] == []

    # 4. Simulate an interruption right after the first persist() inside import_carrier_quote:
    # tenantId must ALREADY be set before any disk write, so reloading never leaks a tenantless global quote.
    orig_persist = plat.pilot.logistics.persist
    persisted_snapshots: list[dict[str, Any]] = []

    def spy_persist() -> None:
        for q in plat.pilot.logistics.carrier_quotes.values():
            persisted_snapshots.append(dict(q))
        orig_persist()

    monkeypatch.setattr(plat.pilot.logistics, "persist", spy_persist)
    direct = plat.pilot.logistics.import_carrier_quote(
        {"quoteId": "quote-direct-a", "carrier": "DIRECT-A", "charge": 260},
        source="MANUAL",
        tenant_id=TENANT,
    )
    assert direct["tenantId"] == TENANT
    assert all(s.get("tenantId") == TENANT for s in persisted_snapshots)

    # Simulate mid-batch crash on the 2nd row before batch persist completes.
    orig_import = plat.pilot.logistics.import_carrier_quote
    call_count = 0

    def crashing_import(row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated mid-batch crash")
        return orig_import(row, **kwargs)

    monkeypatch.setattr(plat.pilot.logistics, "import_carrier_quote", crashing_import)
    with pytest.raises(RuntimeError, match="simulated mid-batch crash"):
        c1.post(
            "/api/pilot/carrier-quotes",
            headers=HEADERS,
            json={
                "rows": [
                    {"quoteId": "batch-crash-row-1", "carrier": "C1", "charge": 100},
                    {"quoteId": "batch-crash-row-2", "carrier": "C2", "charge": 200},
                ]
            },
        )
    assert "batch-crash-row-1" not in plat.pilot.logistics.carrier_quotes
    assert "batch-crash-row-2" not in plat.pilot.logistics.carrier_quotes

    # Reload a fresh Platform from disk and verify tenant isolation and atomic recovery.
    reloaded = Platform(root=root, mock_blender=True)
    c2 = TestClient(create_app(reloaded))
    reloaded_a = {q["quoteId"] for q in c2.get("/api/pilot/carrier-quotes", headers=HEADERS).json()["items"]}
    assert reloaded_a == {"quote-tenant-a-1", qid_a2, "quote-direct-a"}
    assert c2.get("/api/pilot/carrier-quotes", headers=OTHER_HEADERS).json()["items"] == []


def test_shipment_draft_conflict_on_quote_divisor_and_post_handoff_immutable(
    client: TestClient, platform: Any
) -> None:
    _wo, cartons = _create_cartons(client, platform, tenant=TENANT, quantity=2, idem_key="ship-conflict-cartons")

    q1 = client.post(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        json={"carrier": "TCAT", "service": "ground", "charge": 180, "dimDivisor": 6000},
    ).json()
    q2 = client.post(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        json={"carrier": "HCT", "service": "ground", "charge": 220, "dimDivisor": 5000},
    ).json()

    # Create draft with quoteId=q1 and dimDivisor=6000.
    base_req = {
        "origin": "TW",
        "destination": "TW-TPE",
        "cartonIds": [cartons[0]],
        "service": "ground",
        "quoteId": q1["quoteId"],
        "dimDivisor": 6000,
    }
    first = client.post("/api/pilot/shipments", headers=HEADERS, json=base_req)
    assert first.status_code == 200, first.text
    sid = first.json()["shipmentId"]
    assert first.json()["quoteId"] == q1["quoteId"]
    assert first.json()["dimDivisor"] == 6000.0

    # Exact same full request is idempotent -> 200 and same shipmentId.
    same = client.post("/api/pilot/shipments", headers=HEADERS, json=base_req)
    assert same.status_code == 200
    assert same.json()["shipmentId"] == sid

    # Re-sending same cartons/route/service with a different quoteId, omitted quoteId,
    # different dimDivisor, or omitted dimDivisor must return 409 without mutating the draft.
    for conflicting_patch in (
        {"quoteId": q2["quoteId"]},
        {"quoteId": None},
        {"dimDivisor": 5000},
        {"dimDivisor": None},
        {"quoteId": q2["quoteId"], "dimDivisor": 5000},
    ):
        attempt = dict(base_req)
        for k, v in conflicting_patch.items():
            if v is None:
                attempt.pop(k, None)
            else:
                attempt[k] = v
        conflict = client.post("/api/pilot/shipments", headers=HEADERS, json=attempt)
        assert conflict.status_code == 409, f"patch {conflicting_patch!r} -> {conflict.status_code} {conflict.text}"
        stored = platform.pilot.logistics.shipments[sid]
        assert stored["quoteId"] == q1["quoteId"]
        assert stored["dimDivisor"] == 6000.0

    # Hand off the shipment manually.
    ho = client.post(
        f"/api/pilot/shipments/{sid}/handoff",
        headers=HEADERS,
        json={"carrier": "TCAT", "tracking": "TRK-IMMUTABLE-1"},
    )
    assert ho.status_code == 200
    assert ho.json()["status"] == "HANDED_OFF_MANUAL"

    # Once handed off, attempting to create/overwrite draft (either with a different quote/divisor
    # or with the original parameters) is rejected with 409 and leaves the handed-off shipment intact.
    for post_handoff_body in (
        {**base_req, "quoteId": q2["quoteId"]},
        {**base_req, "dimDivisor": 5000},
        base_req,
    ):
        res = client.post("/api/pilot/shipments", headers=HEADERS, json=post_handoff_body)
        assert res.status_code == 409, res.text
        after = client.get(f"/api/pilot/shipments/{sid}", headers=HEADERS).json()
        assert after["status"] == "HANDED_OFF_MANUAL"
        assert after["quoteId"] == q1["quoteId"]
        assert after["dimDivisor"] == 6000.0
        assert after["handoff"]["tracking"] == "TRK-IMMUTABLE-1"


def test_shipping_state_survives_platform_reload(tmp_path: Any) -> None:
    root = tmp_path / "persist-root"
    plat1 = Platform(root=root, mock_blender=True)
    c1 = TestClient(create_app(plat1))
    _wo, cartons = _create_cartons(c1, plat1, tenant=TENANT, quantity=2, idem_key="reload-cartons")

    pal = c1.post("/api/pilot/pallets", headers=HEADERS, json={"cartonIds": cartons}).json()
    quote = c1.post(
        "/api/pilot/carrier-quotes",
        headers=HEADERS,
        json={"carrier": "TCAT", "service": "ground", "charge": 200, "dimDivisor": 6000},
    ).json()
    ship = c1.post(
        "/api/pilot/shipments",
        headers=HEADERS,
        json={
            "origin": "TW",
            "destination": "TW-TPE",
            "cartonIds": cartons,
            "service": "ground",
            "quoteId": quote["quoteId"],
        },
    ).json()
    handed = c1.post(
        f"/api/pilot/shipments/{ship['shipmentId']}/handoff",
        headers=HEADERS,
        json={"carrier": "TCAT", "tracking": "TRK-PERSIST-1"},
    ).json()

    # Reload a fresh Platform instance from disk.
    plat2 = Platform(root=root, mock_blender=True)
    c2 = TestClient(create_app(plat2))

    pallets2 = c2.get("/api/pilot/pallets", headers=HEADERS).json()["items"]
    assert any(p["palletPlanId"] == pal["palletPlanId"] for p in pallets2)

    ship2 = c2.get(f"/api/pilot/shipments/{ship['shipmentId']}", headers=HEADERS).json()
    assert ship2["status"] == "HANDED_OFF_MANUAL"
    assert ship2["handoff"]["handoffId"] == handed["handoff"]["handoffId"]

    # Retrying handoff with same tracking after restart still returns original handoffId.
    retry = c2.post(
        f"/api/pilot/shipments/{ship['shipmentId']}/handoff",
        headers=HEADERS,
        json={"carrier": "TCAT", "tracking": "TRK-PERSIST-1"},
    ).json()
    assert retry["handoff"]["handoffId"] == handed["handoff"]["handoffId"]
    assert len(plat2.pilot.logistics.handoffs) == 1
