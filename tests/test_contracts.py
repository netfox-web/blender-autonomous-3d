"""Direct unit coverage for fox3d.contracts.ContractService via platform fixture."""

from __future__ import annotations

import pytest

import fox3d.contracts as contracts_mod
from fox3d.contracts import (
    SCHEMA_ADJUST,
    SCHEMA_CARRIER,
    SCHEMA_EXPORT,
    SCHEMA_RECEIPT,
    SCHEMA_SUPPLIER,
)
from tests.test_pilot_deploy import _ready_wo


def _contracts(platform):
    return platform.pilot.contracts


def test_import_receipt_schema_accept_and_reject(platform):
    cs = _contracts(platform)
    bundle = cs.import_bundle(
        {
            "schemaVersion": SCHEMA_RECEIPT,
            "rows": [
                {"material": "PB_18_WHITE", "quantity": 2, "thickness": 18, "supplierLot": "R1"},
                {"quantity": 3, "supplierLot": "BAD"},
            ],
        },
        tenant_id="cr",
        actor="ops",
        source="IMPORTED",
    )
    assert bundle["acceptedCount"] == 1
    assert bundle["rejectedCount"] == 1
    rej = bundle["rejected"][0]
    assert rej["index"] == 1
    assert "material" in rej["reasons"]


def test_import_supplier_schema_accept_and_reject(platform):
    cs = _contracts(platform)
    bundle = cs.import_bundle(
        {
            "schemaVersion": SCHEMA_SUPPLIER,
            "rows": [
                {"supplierId": "S-A", "material": 100},
                {"material": 50},
            ],
        },
        tenant_id="cs",
        actor="ops",
        source="IMPORTED",
    )
    assert bundle["acceptedCount"] == 1
    assert bundle["rejectedCount"] == 1
    rej = bundle["rejected"][0]
    assert rej["index"] == 1
    assert rej["reasons"] == ["supplierId"]


def test_import_carrier_schema_accept_and_reject(platform):
    cs = _contracts(platform)
    bundle = cs.import_bundle(
        {
            "schemaVersion": SCHEMA_CARRIER,
            "rows": [
                {"carrier": "DHL", "charge": 120, "service": "ground"},
                {"carrier": "DHL"},
            ],
        },
        tenant_id="cc",
        actor="ops",
        source="IMPORTED",
    )
    assert bundle["acceptedCount"] == 1
    assert bundle["rejectedCount"] == 1
    rej = bundle["rejected"][0]
    assert rej["index"] == 1
    assert "charge" in rej["reasons"]


def test_import_adjustment_schema_accept_and_reject(platform):
    wo, _rel = _ready_wo(platform, tenant="ca")
    lot_id = (wo.get("lineage") or {}).get("materialLots", [None])[0]
    assert lot_id
    cs = _contracts(platform)
    bundle = cs.import_bundle(
        {
            "schemaVersion": SCHEMA_ADJUST,
            "rows": [
                {"lotId": lot_id, "quantity": 1, "reason": "cycle count"},
                {"lotId": lot_id, "quantity": 2},
            ],
        },
        tenant_id="ca",
        actor="ops",
        source="MANUAL",
    )
    assert bundle["acceptedCount"] == 1
    assert bundle["rejectedCount"] == 1
    rej = bundle["rejected"][0]
    assert rej["index"] == 1
    assert "reason" in rej["reasons"]
    assert bundle["accepted"][0]["status"] == "WAITING_HUMAN_APPROVAL"


def test_import_unknown_schema_and_live_source_rejected(platform):
    cs = _contracts(platform)
    with pytest.raises(PermissionError, match="unknown schema"):
        cs.import_bundle({"schemaVersion": "fox3d.unknown.v9", "rows": []}, tenant_id="cu", actor="ops")
    with pytest.raises(PermissionError, match="MANUAL/IMPORTED"):
        cs.import_bundle(
            {"schemaVersion": SCHEMA_RECEIPT, "rows": [{"material": "PB_18_WHITE", "quantity": 1}]},
            tenant_id="cu",
            actor="ops",
            source="LIVE",
        )


def test_import_idempotency_same_tenant(platform):
    cs = _contracts(platform)
    payload = {
        "schemaVersion": SCHEMA_RECEIPT,
        "rows": [{"material": "PB_18_WHITE", "quantity": 1, "thickness": 18, "supplierLot": "IDEM"}],
    }
    first = cs.import_bundle(payload, tenant_id="ci", actor="ops", source="IMPORTED", idempotency_key="idem-1")
    second = cs.import_bundle(payload, tenant_id="ci", actor="ops", source="IMPORTED", idempotency_key="idem-1")
    assert second["importId"] == first["importId"]
    assert second["acceptedCount"] == first["acceptedCount"]


def test_import_idempotency_different_tenants_isolated(platform):
    cs = _contracts(platform)
    payload = {
        "schemaVersion": SCHEMA_RECEIPT,
        "rows": [{"material": "PB_18_WHITE", "quantity": 1, "thickness": 18, "supplierLot": "SHARED"}],
    }
    a = cs.import_bundle(payload, tenant_id="cia", actor="ops", source="IMPORTED", idempotency_key="shared-key")
    b = cs.import_bundle(payload, tenant_id="cib", actor="ops", source="IMPORTED", idempotency_key="shared-key")
    assert a["importId"] != b["importId"]
    assert a["tenantId"] == "cia"
    assert b["tenantId"] == "cib"


def test_approve_adjustment_requires_confirm(platform):
    wo, _rel = _ready_wo(platform, tenant="adj")
    lot_id = (wo.get("lineage") or {}).get("materialLots", [None])[0]
    cs = _contracts(platform)
    adj = cs.draft_adjustment({"lotId": lot_id, "quantity": 1, "reason": "recount"}, tenant_id="adj", actor="ops")
    with pytest.raises(PermissionError, match="human confirmation"):
        cs.approve_adjustment(adj["adjustmentId"], tenant_id="adj", actor="ops", confirm=False)


def test_approve_adjustment_cross_tenant_denied(platform):
    wo, _rel = _ready_wo(platform, tenant="adjx")
    lot_id = (wo.get("lineage") or {}).get("materialLots", [None])[0]
    cs = _contracts(platform)
    adj = cs.draft_adjustment({"lotId": lot_id, "quantity": 1, "reason": "x"}, tenant_id="adjx", actor="ops")
    with pytest.raises(PermissionError, match="tenant isolation"):
        cs.approve_adjustment(adj["adjustmentId"], tenant_id="other", actor="ops", confirm=True)


def test_approve_adjustment_idempotent_does_not_double_apply(platform):
    wo, _rel = _ready_wo(platform, tenant="adjy")
    lot_id = (wo.get("lineage") or {}).get("materialLots", [None])[0]
    lots = platform.pilot.platform.lots
    before = lots.quantities(lot_id, tenant_id="adjy")["sheetCount"]
    cs = _contracts(platform)
    adj = cs.draft_adjustment({"lotId": lot_id, "quantity": 3, "reason": "found"}, tenant_id="adjy", actor="ops")
    first = cs.approve_adjustment(adj["adjustmentId"], tenant_id="adjy", actor="ops", confirm=True)
    second = cs.approve_adjustment(adj["adjustmentId"], tenant_id="adjy", actor="ops", confirm=True)
    assert first["applied"] is True
    assert second["adjustmentId"] == first["adjustmentId"]
    after = lots.quantities(lot_id, tenant_id="adjy")["sheetCount"]
    assert after == before + 3


def test_approve_unknown_adjustment_raises_keyerror(platform):
    cs = _contracts(platform)
    with pytest.raises(KeyError):
        cs.approve_adjustment("missing-adj-id", tenant_id="adjz", actor="ops", confirm=True)


def test_export_bundle_tenant_scoped_work_orders_and_shipments(platform):
    wo_a, _rel_a = _ready_wo(platform, tenant="ex-a")
    log = platform.pilot.logistics
    cartons_a = log.instantiate_cartons(
        tenant_id="ex-a",
        work_order_id=wo_a["workOrderId"],
        batch_id=wo_a["batchId"],
        plan={"length": 10, "width": 10, "height": 10},
        quantity=1,
    )
    log.shipment_draft(origin="TW", destination="TPE", carton_ids=[c["cartonId"] for c in cartons_a])
    wo_b, _rel_b = _ready_wo(platform, tenant="ex-b")
    cartons_b = log.instantiate_cartons(
        tenant_id="ex-b",
        work_order_id=wo_b["workOrderId"],
        batch_id=wo_b["batchId"],
        plan={"length": 10, "width": 10, "height": 10},
        quantity=1,
    )
    log.shipment_draft(origin="TW", destination="KA", carton_ids=[c["cartonId"] for c in cartons_b])
    exported = _contracts(platform).export_bundle(tenant_id="ex-a")
    wo_ids = {w["workOrderId"] for w in exported["workOrders"]}
    assert wo_a["workOrderId"] in wo_ids
    assert wo_b["workOrderId"] not in wo_ids
    assert all(c.get("tenantId") == "ex-a" for c in exported["cartons"])
    assert all(s.get("tenantId") == "ex-a" for s in exported["shipmentDrafts"])


def test_export_bundle_release_hash_filter(platform):
    product1 = platform.kd.build_sku(tenant_id="exf", kind="OPEN_SHELF")
    product2 = platform.kd.build_sku(tenant_id="exf", kind="DESK_RISER")
    rel1 = platform.pilot.open_release(product1, tenant_id="exf", family="KD_FURNITURE")
    rel2 = platform.pilot.open_release(product2, tenant_id="exf", family="KD_FURNITURE")
    assert rel1["releaseHash"] != rel2["releaseHash"]
    row = {"supplierLot": "exf-lot", "material": "PB_18_WHITE", "thickness": 18, "quantity": 10}
    platform.pilot.receiving.import_receipt(row, tenant_id="exf", actor="recv", source="MANUAL", idempotency_key="exf-lot")
    wo1 = platform.pilot.workorders.create(tenant_id="exf", release=rel1, quantity=1, actor="ops")
    wo2 = platform.pilot.workorders.create(tenant_id="exf", release=rel2, quantity=1, actor="ops")
    rh = rel1["releaseHash"]
    exported = _contracts(platform).export_bundle(tenant_id="exf", release_hash=rh)
    assert exported["releaseHash"] == rh
    wo_ids = {w["workOrderId"] for w in exported["workOrders"]}
    assert wo1["workOrderId"] in wo_ids
    assert wo2["workOrderId"] not in wo_ids
    rel_ids = {p["releaseId"] for p in exported["releases"]}
    assert rel1["releaseId"] in rel_ids
    assert rel2["releaseId"] not in rel_ids


def test_export_bundle_live_machine_flags_false(platform):
    _ready_wo(platform, tenant="exm")
    exported = _contracts(platform).export_bundle(tenant_id="exm")
    assert exported["schemaVersion"] == SCHEMA_EXPORT
    assert exported["liveMachineControl"] is False
    assert exported["actuatesMachine"] is False
    assert exported["submitsCarrierBooking"] is False


def test_export_bundle_content_hash_stable_with_fixed_clock(platform, monkeypatch):
    from fox3d.ids import stable_hash

    _ready_wo(platform, tenant="exh")
    fixed = "2030-06-15T12:00:00+00:00"
    monkeypatch.setattr(contracts_mod, "_now", lambda: fixed)
    exported = _contracts(platform).export_bundle(tenant_id="exh")
    assert exported["exportedAt"] == fixed
    expect = stable_hash({k: exported[k] for k in exported if k != "contentHash"})
    assert exported["contentHash"] == expect
    again = stable_hash({k: exported[k] for k in exported if k != "contentHash"})
    assert again == exported["contentHash"]
