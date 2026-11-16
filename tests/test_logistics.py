"""Offline logistics validation — EventJournal + CommitOutbox."""

from __future__ import annotations

import pytest

from fox3d.journal import EventJournal
from fox3d.logistics import LogisticsService
from fox3d.outbox import CommitOutbox


def _wired_logistics(tmp_path) -> LogisticsService:
    root = tmp_path / "logistics"
    log = LogisticsService(root=root)
    log.outbox = CommitOutbox(tmp_path / "tx")
    log.journal = EventJournal(tmp_path / "journal")
    log.journal.outbox = log.outbox
    return log


def _carton(log: LogisticsService, tenant: str, wo: str = "wo", qty: int = 1) -> list[dict]:
    return log.instantiate_cartons(
        tenant_id=tenant,
        work_order_id=wo,
        batch_id="b1",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=qty,
        contents=[{"sku": "product", "qty": 1}],
    )


@pytest.mark.parametrize("quantity", [0, -1])
def test_instantiate_cartons_rejects_non_positive_quantity(quantity):
    log = LogisticsService()
    with pytest.raises(ValueError, match="quantity"):
        log.instantiate_cartons(
            tenant_id="t",
            work_order_id="wo",
            batch_id="b",
            plan={"length": 400, "width": 300, "height": 200},
            quantity=quantity,
        )


def test_instantiate_cartons_rejects_non_integer_quantity():
    log = LogisticsService()
    with pytest.raises(ValueError, match="quantity"):
        log.instantiate_cartons(
            tenant_id="t",
            work_order_id="wo",
            batch_id="b",
            plan={"length": 400, "width": 300, "height": 200},
            quantity="abc",  # type: ignore[arg-type]
        )


def test_record_measured_two_audits_and_tenant_guard(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "acme")
    cid = cartons[0]["cartonId"]
    log.record_measured(cid, tenant_id="acme", length=400, width=300, height=200, weight_kg=10)
    log.record_measured(cid, tenant_id="acme", length=401, width=300, height=200, weight_kg=10)
    events = [e for e in log.journal.list("acme") if e.get("eventType") == "carton.measured"]
    assert len(events) == 2
    assert events[0]["eventId"] != events[1]["eventId"]
    with pytest.raises(PermissionError):
        log.record_measured(cid, tenant_id="other", length=400, width=300, height=200, weight_kg=10)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"length": float("nan"), "width": 1, "height": 1, "weight_kg": 1},
        {"length": 400, "width": -1, "height": 1, "weight_kg": 1},
        {"length": 400, "width": 300, "height": 1, "weight_kg": -3},
    ],
)
def test_record_measured_rejects_invalid_dims(kwargs):
    log = LogisticsService()
    cartons = _carton(log, "t")
    cid = cartons[0]["cartonId"]
    with pytest.raises(ValueError):
        log.record_measured(cid, tenant_id="t", **kwargs)


def test_palletize_flags_oversize_carton(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "t")
    cid = cartons[0]["cartonId"]
    log.record_measured(
        cid,
        tenant_id="t",
        length=400,
        width=300,
        height=2000,
        weight_kg=900,
        source="MANUAL",
    )
    plan = log.palletize([cid])
    assert plan["oversize"] is True
    assert plan["status"] == "NEEDS_HUMAN"
    assert cid in plan["heldCartonIds"]
    assert plan["pallets"] == []


def test_palletize_normal_carton_still_plans(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "t", qty=2)
    ids = [c["cartonId"] for c in cartons]
    plan = log.palletize(ids)
    assert plan["oversize"] is False
    assert plan["status"] == "PLANNING"
    assert plan["palletCount"] == 1
    assert len(plan["pallets"][0]["cartonIds"]) == 2


def test_shipping_request_duplicate_and_empty(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "t")
    cid = cartons[0]["cartonId"]
    with pytest.raises(ValueError, match="empty"):
        log.shipping_request(origin="TW", destination="TPE", carton_ids=[])
    with pytest.raises(ValueError, match="duplicate"):
        log.shipping_request(origin="TW", destination="TPE", carton_ids=[cid, cid])
    ship = log.shipping_request(origin="TW", destination="TPE", carton_ids=[cid])
    assert ship["pieces"] == 1


def test_shipping_request_idempotent_regardless_of_order(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "t", qty=2)
    a, b = cartons[0]["cartonId"], cartons[1]["cartonId"]
    first = log.shipping_request(origin="TW", destination="TPE", carton_ids=[a, b])
    second = log.shipping_request(origin="TW", destination="TPE", carton_ids=[b, a])
    assert first["shipmentId"] == second["shipmentId"]


def test_packing_list_tenant_isolated(tmp_path):
    log = _wired_logistics(tmp_path)
    _carton(log, "acme", wo="shared")
    _carton(log, "other", wo="shared")
    acme = log.packing_list(tenant_id="acme", work_order_id="shared")
    other = log.packing_list(tenant_id="other", work_order_id="shared")
    assert acme["cartonCount"] == 1
    assert other["cartonCount"] == 1
    assert acme["contentsConserved"] is True
    acme_ids = {c["cartonId"] for c in acme["cartons"]}
    other_ids = {c["cartonId"] for c in other["cartons"]}
    assert acme_ids.isdisjoint(other_ids)


def test_packing_list_contents_conserved_detects_zero_qty(tmp_path):
    log = _wired_logistics(tmp_path)
    log.instantiate_cartons(
        tenant_id="t",
        work_order_id="wo",
        batch_id="b",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=1,
        contents=[{"sku": "product", "qty": 0}],
    )
    lst = log.packing_list(tenant_id="t", work_order_id="wo")
    assert lst["contentsConserved"] is False


def test_reload_preserves_cartons_and_idempotency(tmp_path):
    root = tmp_path / "logistics"
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "t")
    cid = cartons[0]["cartonId"]
    ship_a = log.shipping_request(origin="TW", destination="TPE", carton_ids=[cid])
    log.persist()

    reloaded = LogisticsService(root=root)
    reloaded.outbox = CommitOutbox(tmp_path / "tx")
    reloaded.journal = EventJournal(tmp_path / "journal")
    reloaded.journal.outbox = reloaded.outbox
    ship_b = reloaded.shipping_request(origin="TW", destination="TPE", carton_ids=[cid])
    assert ship_b["shipmentId"] == ship_a["shipmentId"]
    assert reloaded.cartons[cid]["workOrderId"] == "wo"