"""Direct unit coverage for fox3d.contracts.ContractService via platform fixture."""

from __future__ import annotations

import re

import pytest

import fox3d.contracts as contracts_mod
from fox3d.contracts import (
    SCHEMA_ADJUST,
    SCHEMA_CARRIER,
    SCHEMA_EXPORT,
    SCHEMA_RECEIPT,
    SCHEMA_SUPPLIER,
)
from tests.test_api_bad_input import CONTAINER_IMPORT_CASES
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


def _bundle_stores(platform, tenant_id: str) -> dict[str, set[str]]:
    return {
        "receipts": set(platform.pilot.receiving.receipts),
        "imports": set(platform.pilot.contracts.imports),
        "quotes": set(platform.pilot.suppliers.quotes),
        "carrier_quotes": set(platform.pilot.logistics.carrier_quotes),
        "adjustments": set(platform.pilot.contracts.adjustments),
        "lots": {lot["lotId"] for lot in platform.lots.list(tenant_id=tenant_id)},
    }


@pytest.mark.parametrize(
    "schema,rows,field",
    [(schema, rows, field) for schema, rows, field, _label in CONTAINER_IMPORT_CASES],
    ids=[f"{schema} {label}" for schema, _rows, _field, label in CONTAINER_IMPORT_CASES],
)
def test_import_container_required_field_writes_nothing(platform, schema: str, rows: list, field: str) -> None:
    tenant = "ctype"
    cs = _contracts(platform)
    before = _bundle_stores(platform, tenant)
    with pytest.raises(PermissionError, match=re.escape(f"rows[1] {field} 格式錯誤")):
        cs.import_bundle({"schemaVersion": schema, "rows": rows}, tenant_id=tenant, actor="ops")
    assert _bundle_stores(platform, tenant) == before


def test_container_required_field_does_not_poison_idempotency(platform):
    tenant = "idemc"
    cs = _contracts(platform)
    before = _bundle_stores(platform, tenant)
    payload = {
        "schemaVersion": SCHEMA_RECEIPT,
        "rows": [
            {"material": "PB_18_WHITE", "quantity": 1, "supplierLot": "good"},
            {"material": [], "quantity": 1},
        ],
    }
    with pytest.raises(PermissionError, match=re.escape("rows[1] material 格式錯誤")):
        cs.import_bundle(payload, tenant_id=tenant, actor="ops", idempotency_key="same-key")
    assert _bundle_stores(platform, tenant) == before
    bundle = cs.import_bundle(
        {
            "schemaVersion": SCHEMA_RECEIPT,
            "rows": [{"material": "PB_18_WHITE", "quantity": 1, "supplierLot": "good"}],
        },
        tenant_id=tenant,
        actor="ops",
        idempotency_key="same-key",
    )
    assert bundle["acceptedCount"] == 1
    assert bundle["rejectedCount"] == 0
    assert bundle["importId"] in cs.imports
    assert len(platform.pilot.receiving.receipts) == len(before["receipts"]) + 1
    assert len(_bundle_stores(platform, tenant)["lots"]) == len(before["lots"]) + 1


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


def test_carrier_quote_bundle_holds_logistics_lock_and_preserves_concurrent_commit_on_failure(
    platform, monkeypatch
):
    import threading
    from fox3d.logistics import LogisticsService

    cs = _contracts(platform)
    logistics = platform.pilot.logistics

    # Seed an initial quote before the batch.
    logistics.import_carrier_quote(
        {"quoteId": "q-seed-initial", "carrier": "SEED", "charge": 100},
        source="MANUAL",
        tenant_id="tenant-seed",
    )

    orig_require = contracts_mod._require
    row_index = 0
    other_thread_acquired_between_rows: list[bool] = []
    worker_thread: threading.Thread | None = None
    worker_attempted = threading.Event()

    def concurrent_tenant_b_write() -> None:
        # Attempt a non-blocking acquire between row 0 and row 1; must fail because import_bundle holds logistics._lock.
        can_steal = logistics._lock.acquire(blocking=False)
        if can_steal:
            logistics._lock.release()
        other_thread_acquired_between_rows.append(can_steal)
        worker_attempted.set()
        # Now perform the real blocking import_carrier_quote (with default persist=True) for tenant-b.
        logistics.import_carrier_quote(
            {"quoteId": "q-concurrent-tenant-b", "carrier": "TCAT-B", "charge": 260},
            source="MANUAL",
            tenant_id="tenant-b",
        )

    def hooked_require(row: dict, fields: tuple[str, ...]) -> list[str]:
        nonlocal row_index, worker_thread
        row_index += 1
        if row_index == 2:
            # Right after row 0's import_carrier_quote returned and before row 1 runs:
            worker_thread = threading.Thread(target=concurrent_tenant_b_write)
            worker_thread.start()
            assert worker_attempted.wait(timeout=5.0)
        return orig_require(row, fields)

    monkeypatch.setattr(contracts_mod, "_require", hooked_require)

    # Row 0 is valid; Row 1 has an invalid validUntil date so import_carrier_quote raises ValueError mid-batch.
    with pytest.raises(ValueError, match="validUntil"):
        cs.import_bundle(
            {
                "schemaVersion": SCHEMA_CARRIER,
                "rows": [
                    {"quoteId": "q-batch-a-row0", "carrier": "DHL-A", "charge": 150},
                    {"quoteId": "q-batch-a-row1", "carrier": "DHL-A", "charge": 180, "validUntil": "not-a-date"},
                ],
            },
            tenant_id="tenant-a",
            actor="ops",
            source="IMPORTED",
        )

    assert worker_thread is not None
    worker_thread.join(timeout=5.0)
    assert not worker_thread.is_alive()

    # Because import_bundle held logistics._lock across the whole batch, the other thread could NOT acquire the lock mid-batch.
    assert other_thread_acquired_between_rows == [False]

    # Row 0 from the failed batch was rolled back, while tenant-b's quote committed after the rollback is preserved in memory and on disk.
    assert "q-batch-a-row0" not in logistics.carrier_quotes
    assert "q-batch-a-row1" not in logistics.carrier_quotes
    assert set(logistics.carrier_quotes) == {"q-seed-initial", "q-concurrent-tenant-b"}

    # A subsequent persist() and reload from disk must preserve tenant-b's committed quote.
    logistics.persist()
    reloaded = LogisticsService(root=logistics.root)
    assert set(reloaded.carrier_quotes) == {"q-seed-initial", "q-concurrent-tenant-b"}
    assert reloaded.carrier_quotes["q-concurrent-tenant-b"]["tenantId"] == "tenant-b"

    # Also verify that if a re-entrant hook inserts another tenant's persisted quote right after row 0 returns
    # and row 1 raises, the inserted quote is still preserved after rollback, persist(), and reload.
    monkeypatch.setattr(contracts_mod, "_require", orig_require)
    orig_import_quote = logistics.import_carrier_quote
    call_seq = 0

    def reentrant_hook(row: dict, **kwargs):
        nonlocal call_seq
        call_seq += 1
        if call_seq == 1:
            res = orig_import_quote(row, **kwargs)
            orig_import_quote(
                {"quoteId": "q-reentrant-tenant-c", "carrier": "HCT-C", "charge": 310},
                source="MANUAL",
                tenant_id="tenant-c",
            )
            return res
        raise RuntimeError("row 2 failed after re-entrant commit")

    monkeypatch.setattr(logistics, "import_carrier_quote", reentrant_hook)
    with pytest.raises(RuntimeError, match="row 2 failed after re-entrant commit"):
        cs.import_bundle(
            {
                "schemaVersion": SCHEMA_CARRIER,
                "rows": [
                    {"quoteId": "q-batch-a2-row0", "carrier": "DHL-A2", "charge": 155},
                    {"quoteId": "q-batch-a2-row1", "carrier": "DHL-A2", "charge": 185},
                ],
            },
            tenant_id="tenant-a",
            actor="ops",
            source="IMPORTED",
        )

    assert "q-batch-a2-row0" not in logistics.carrier_quotes
    assert "q-reentrant-tenant-c" in logistics.carrier_quotes
    logistics.persist()
    reloaded2 = LogisticsService(root=logistics.root)
    assert set(reloaded2.carrier_quotes) == {
        "q-seed-initial",
        "q-concurrent-tenant-b",
        "q-reentrant-tenant-c",
    }


