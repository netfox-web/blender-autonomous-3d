"""Offline logistics validation — EventJournal + CommitOutbox."""

from __future__ import annotations

import pytest

from fox3d.journal import EventJournal, SemanticKeyConflictError
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


@pytest.mark.parametrize("quantity", [0, -1, 1.9, 1.0000000001, True])
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


def test_instantiate_cartons_validates_quantity_before_idempotency_retry(tmp_path):
    log = _wired_logistics(tmp_path)
    key = "idem-key-1"
    first = log.instantiate_cartons(
        tenant_id="t",
        work_order_id="wo",
        batch_id="b",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=1,
        idempotency_key=key,
    )
    assert len(first) == 1
    with pytest.raises(ValueError, match="quantity"):
        log.instantiate_cartons(
            tenant_id="t",
            work_order_id="wo",
            batch_id="b",
            plan={"length": 400, "width": 300, "height": 200},
            quantity=0,
            idempotency_key=key,
        )
    with pytest.raises(ValueError, match="quantity"):
        log.instantiate_cartons(
            tenant_id="t",
            work_order_id="wo",
            batch_id="b",
            plan={"length": 400, "width": 300, "height": 200},
            quantity=1.9,
            idempotency_key=key,
        )
    with pytest.raises(ValueError, match="quantity"):
        log.instantiate_cartons(
            tenant_id="t",
            work_order_id="wo",
            batch_id="b",
            plan={"length": 400, "width": 300, "height": 200},
            quantity=1.0000000001,
            idempotency_key=key,
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


def test_record_measured_aba_audit_trail(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "acme")
    cid = cartons[0]["cartonId"]
    dims_a = {"length": 400.0, "width": 300.0, "height": 200.0, "weight_kg": 10.0}
    dims_b = {"length": 401.0, "width": 300.0, "height": 200.0, "weight_kg": 10.0}
    log.record_measured(cid, tenant_id="acme", **dims_a)
    log.record_measured(cid, tenant_id="acme", **dims_b)
    log.record_measured(cid, tenant_id="acme", **dims_a)
    events = [e for e in log.journal.list("acme") if e.get("eventType") == "carton.measured"]
    assert len(events) == 3
    weights = [e["payload"]["measured"]["length"] for e in events]
    assert weights == [400.0, 401.0, 400.0]


def test_record_measured_interleaved_retry_keeps_latest_state(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "acme")
    cid = cartons[0]["cartonId"]
    base = dict(tenant_id="acme", width=300, height=200, weight_kg=10)
    log.record_measured(cid, **base, length=400, measure_op_id="a")
    log.record_measured(cid, **base, length=401, measure_op_id="b")
    log.record_measured(cid, **base, length=400, measure_op_id="a")
    assert log.cartons[cid]["measured"]["length"] == 401.0
    events = [e for e in log.journal.list("acme") if e.get("eventType") == "carton.measured"]
    assert len(events) == 2
    assert [e["payload"]["measured"]["length"] for e in events] == [400.0, 401.0]


def test_record_measured_retry_rejects_conflicting_op_payload(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "acme")
    cid = cartons[0]["cartonId"]
    base = dict(tenant_id="acme", width=300, height=200, weight_kg=10)
    log.record_measured(cid, **base, length=400, measure_op_id="a")
    with pytest.raises(ValueError, match="measure op payload mismatch"):
        log.record_measured(cid, **base, length=402, measure_op_id="a")


def test_record_measured_idempotent_retry_single_audit(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "acme")
    cid = cartons[0]["cartonId"]
    op_id = "measure-op-retry-1"
    kwargs = dict(tenant_id="acme", length=400, width=300, height=200, weight_kg=10, measure_op_id=op_id)
    log.record_measured(cid, **kwargs)
    log.record_measured(cid, **kwargs)
    events = [e for e in log.journal.list("acme") if e.get("eventType") == "carton.measured"]
    assert len(events) == 1
    assert events[0]["payload"]["measureOpId"] == op_id


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
    acme_expected = log.packing_list(
        tenant_id="acme", work_order_id="shared", expected_batch={"product": 1.0}
    )
    assert acme_expected["contentsConserved"] is True
    assert acme["contentsConserved"] is None
    acme_ids = {c["cartonId"] for c in acme["cartons"]}
    other_ids = {c["cartonId"] for c in other["cartons"]}
    assert acme_ids.isdisjoint(other_ids)


def test_packing_list_contents_conserved_unknown_when_empty(tmp_path):
    log = _wired_logistics(tmp_path)
    lst = log.packing_list(tenant_id="t", work_order_id="missing-wo")
    assert lst["cartonCount"] == 0
    assert lst["contentsConserved"] is None


def test_packing_list_contents_conserved_shortage_and_overage(tmp_path):
    log = _wired_logistics(tmp_path)
    log.instantiate_cartons(
        tenant_id="t",
        work_order_id="wo",
        batch_id="b",
        plan={"length": 400, "width": 300, "height": 200},
        quantity=2,
        contents=[{"sku": "product", "qty": 1}],
    )
    ok = log.packing_list(tenant_id="t", work_order_id="wo", expected_batch={"product": 2.0})
    assert ok["contentsConserved"] is True
    short = log.packing_list(tenant_id="t", work_order_id="wo", expected_batch={"product": 3.0})
    assert short["contentsConserved"] is False
    over = log.packing_list(tenant_id="t", work_order_id="wo", expected_batch={"product": 1.0})
    assert over["contentsConserved"] is False


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


def test_logistics_quote_date_validation_and_shipment_draft_handoff_guard(tmp_path):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "t")
    cid = cartons[0]["cartonId"]

    for bad_date in ("9999-99-99", "2026-02-30", "2025-02-29", "2099-12-31extra", "not-a-date"):
        with pytest.raises(ValueError, match="validUntil"):
            log.import_carrier_quote(
                {"carrier": "C", "charge": 100, "validUntil": bad_date},
                source="MANUAL",
                tenant_id="t",
            )
        assert log.quote_stale({"service": "ground", "dimDivisor": 6000, "validUntil": bad_date}, service="ground") is True

    q_a = log.import_carrier_quote(
        {"quoteId": "q-owned-a", "carrier": "CA", "charge": 100, "validUntil": "2099-12-31"},
        source="MANUAL",
        tenant_id="t",
    )
    assert q_a["tenantId"] == "t"
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.import_carrier_quote(
            {"quoteId": "q-owned-a", "carrier": "CB", "charge": 50},
            source="MANUAL",
            tenant_id="other",
        )

    draft = log.shipment_draft(
        origin="TW",
        destination="TPE",
        carton_ids=[cid],
        service="ground",
        quote_id="q-owned-a",
        dim_divisor=6000,
    )
    with pytest.raises(SemanticKeyConflictError):
        log.shipment_draft(
            origin="TW",
            destination="TPE",
            carton_ids=[cid],
            service="ground",
            quote_id="other-quote",
            dim_divisor=6000,
        )
    with pytest.raises(SemanticKeyConflictError):
        log.shipment_draft(
            origin="TW",
            destination="TPE",
            carton_ids=[cid],
            service="ground",
            quote_id="q-owned-a",
            dim_divisor=5000,
        )

    log.shipment_handoff(draft["shipmentId"], tenant_id="t", carrier="CA", tracking="TRK-LOG-1", actor="ops")
    with pytest.raises(SemanticKeyConflictError):
        log.shipment_draft(
            origin="TW",
            destination="TPE",
            carton_ids=[cid],
            service="ground",
            quote_id="q-owned-a",
            dim_divisor=6000,
        )


def test_import_carrier_quote_requires_tenant_or_explicit_global_flag(tmp_path):
    log = _wired_logistics(tmp_path)

    # Without tenant_id, without row["tenantId"], and without explicit global flag -> rejected.
    with pytest.raises(ValueError, match="tenant_id"):
        log.import_carrier_quote({"carrier": "TCAT", "charge": 150}, source="MANUAL")
    assert log.carrier_quotes == {}

    # Invalid tenant_id / row["tenantId"] / flag values -> rejected.
    for bad_tid in ("", "   ", 123):
        with pytest.raises(ValueError, match="tenant_id"):
            log.import_carrier_quote({"carrier": "TCAT", "charge": 150}, source="MANUAL", tenant_id=bad_tid)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="tenantId"):
            log.import_carrier_quote({"carrier": "TCAT", "charge": 150, "tenantId": bad_tid}, source="MANUAL")

    with pytest.raises(ValueError, match="allow_global"):
        log.import_carrier_quote({"carrier": "TCAT", "charge": 150}, source="MANUAL", allow_global="yes")  # type: ignore[arg-type]

    # Combining tenant_id (or row tenantId) with explicit global flag -> rejected.
    with pytest.raises(ValueError, match="global"):
        log.import_carrier_quote(
            {"carrier": "TCAT", "charge": 150},
            source="MANUAL",
            tenant_id="tenant-a",
            allow_global=True,
        )
    with pytest.raises(ValueError, match="global"):
        log.import_carrier_quote(
            {"carrier": "TCAT", "charge": 150, "tenantId": "tenant-a"},
            source="MANUAL",
            global_quote=True,
        )

    # Mismatched tenant_id and row["tenantId"] -> PermissionError.
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.import_carrier_quote(
            {"carrier": "TCAT", "charge": 150, "tenantId": "tenant-b"},
            source="MANUAL",
            tenant_id="tenant-a",
        )
    assert log.carrier_quotes == {}

    # Explicit global flags (allow_global=True, global_quote=True, is_global=True) succeed.
    g1 = log.import_carrier_quote(
        {"quoteId": "g-allow", "carrier": "GLOBAL-1", "charge": 100},
        source="IMPORTED",
        allow_global=True,
    )
    assert g1.get("tenantId") is None
    assert g1["globalQuote"] is True
    assert g1["ownership"] == "GLOBAL_REFERENCE"

    g2 = log.import_carrier_quote(
        {"quoteId": "g-quote", "carrier": "GLOBAL-2", "charge": 110},
        source="MANUAL",
        global_quote=True,
    )
    assert g2.get("tenantId") is None
    assert g2["globalQuote"] is True

    g3 = log.import_carrier_quote(
        {"quoteId": "g-is", "carrier": "GLOBAL-3", "charge": 120},
        source="MANUAL",
        is_global=True,
    )
    assert g3.get("tenantId") is None
    assert g3["globalQuote"] is True

    # Tenant quote cannot overwrite global quoteId and vice versa.
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.import_carrier_quote(
            {"quoteId": "g-allow", "carrier": "HIJACK", "charge": 1},
            source="MANUAL",
            tenant_id="tenant-a",
        )

    t1 = log.import_carrier_quote(
        {"quoteId": "t-owned", "carrier": "TENANT-1", "charge": 200},
        source="MANUAL",
        tenant_id="tenant-a",
    )
    assert t1["tenantId"] == "tenant-a"
    assert t1["globalQuote"] is False
    assert t1["ownership"] == "TENANT_OWNED"

    with pytest.raises(PermissionError, match="tenant isolation"):
        log.import_carrier_quote(
            {"quoteId": "t-owned", "carrier": "HIJACK-GLOBAL", "charge": 1},
            source="MANUAL",
            allow_global=True,
        )


def test_logistics_persist_atomic_write_and_mid_write_failure_rollback(tmp_path, monkeypatch):
    import fox3d.inventory as inv_mod

    log = _wired_logistics(tmp_path)
    q_init = log.import_carrier_quote(
        {"quoteId": "q-init", "carrier": "INIT-C", "charge": 180},
        source="MANUAL",
        tenant_id="tenant-a",
    )
    assert (log.root / "logistics.json").exists()
    bytes_before = (log.root / "logistics.json").read_bytes()

    # Simulate failure inside atomic_write_json after writing the temporary file but before replace completes.
    def failing_replace(src, dst):
        assert src.exists()
        assert src.suffix == ".tmp"
        raise OSError("simulated mid-persist failure during atomic replace")

    monkeypatch.setattr(inv_mod, "_replace_with_retry", failing_replace)
    with pytest.raises(OSError, match="simulated mid-persist failure"):
        log.import_carrier_quote(
            {"quoteId": "q-fail", "carrier": "FAIL-C", "charge": 999},
            source="MANUAL",
            tenant_id="tenant-a",
        )

    # In-memory state is rolled back, temporary .tmp file is cleaned up, and disk file is untouched.
    assert set(log.carrier_quotes) == {"q-init"}
    assert log.carrier_quotes["q-init"]["charge"] == q_init["charge"]
    assert list(log.root.glob("*.tmp")) == []
    assert (log.root / "logistics.json").read_bytes() == bytes_before

    reloaded = LogisticsService(root=log.root)
    assert set(reloaded.carrier_quotes) == {"q-init"}
    assert reloaded.carrier_quotes["q-init"]["carrier"] == "INIT-C"


def test_inspect_and_migrate_tenantless_carrier_quotes_and_rollback(tmp_path):
    import json

    log = _wired_logistics(tmp_path)
    cartons_a = _carton(log, "tenant-a", wo="wo-a", qty=2)
    cartons_b = _carton(log, "tenant-b", wo="wo-b", qty=1)

    # Create one owned quote and one explicit global quote.
    log.import_carrier_quote(
        {"quoteId": "q-owned-a", "carrier": "CA", "charge": 100},
        source="MANUAL",
        tenant_id="tenant-a",
    )
    log.import_carrier_quote(
        {"quoteId": "q-explicit-global", "carrier": "CG", "charge": 150},
        source="IMPORTED",
        allow_global=True,
    )

    # Create shipments referencing legacy quoteIds for tenant-a and a conflicting quoteId across tenant-a & tenant-b.
    log.shipment_draft(
        origin="TW",
        destination="TPE",
        carton_ids=[cartons_a[0]["cartonId"]],
        quote_id="q-legacy-infer-a",
    )
    log.shipment_draft(
        origin="TW",
        destination="KH",
        carton_ids=[cartons_a[1]["cartonId"]],
        quote_id="q-legacy-conflict",
    )
    log.shipment_draft(
        origin="TW",
        destination="KH",
        carton_ids=[cartons_b[0]["cartonId"]],
        quote_id="q-legacy-conflict",
    )
    log.persist()

    # Inject 3 legacy tenantless quotes directly into logistics.json (simulating interrupted pre-fix writes).
    path = log.root / "logistics.json"
    disk = json.loads(path.read_text(encoding="utf-8"))
    for qid, charge in (
        ("q-legacy-infer-a", 210.0),
        ("q-legacy-unreferenced", 220.0),
        ("q-legacy-conflict", 230.0),
    ):
        disk["carrier_quotes"].append(
            {
                "quoteId": qid,
                "carrier": "LEGACY-C",
                "service": "ground",
                "charge": charge,
                "currency": "TWD",
                "dimDivisor": 6000.0,
                "validUntil": "2099-12-31",
                "source": "MANUAL",
                "truthLabel": "MANUAL",
                "liveProvider": False,
                "importedAt": "2026-11-19T00:00:00+00:00",
                "rawSourceHash": "legacy-raw",
                "quoteHash": "legacy-hash",
                "ownership": "GLOBAL_REFERENCE",
            }
        )
    path.write_text(json.dumps(disk, indent=2), encoding="utf-8")
    log.load()

    # 1. Inspect legacy tenantless quotes (excludes tenant-owned and explicit global by default).
    report = log.inspect_tenantless_carrier_quotes()
    assert report["tenantlessCount"] == 3
    assert set(report["quoteIds"]) == {"q-legacy-infer-a", "q-legacy-unreferenced", "q-legacy-conflict"}
    by_qid = {item["quoteId"]: item for item in report["items"]}
    assert by_qid["q-legacy-infer-a"]["inferredTenantId"] == "tenant-a"
    assert by_qid["q-legacy-infer-a"]["conflict"] is False
    assert by_qid["q-legacy-unreferenced"]["inferredTenantId"] is None
    assert by_qid["q-legacy-conflict"]["inferredTenantId"] is None
    assert by_qid["q-legacy-conflict"]["conflict"] is True
    assert by_qid["q-legacy-conflict"]["referencedByTenants"] == ["tenant-a", "tenant-b"]

    # Including explicit global quotes lists 4 items.
    report_with_global = log.inspect_tenantless_carrier_quotes(include_explicit_global=True)
    assert report_with_global["tenantlessCount"] == 4
    assert "q-explicit-global" in report_with_global["quoteIds"]

    # 2. Dry-run migration does not mutate memory or disk.
    dry = log.migrate_tenantless_carrier_quotes(default_tenant_id="tenant-b", dry_run=True)
    assert dry["dryRun"] is True
    assert dry["assignedCount"] == 2  # q-legacy-infer-a -> tenant-a, q-legacy-unreferenced -> tenant-b
    assert dry["conflictCount"] == 1  # q-legacy-conflict stays unresolved
    assert log.carrier_quotes["q-legacy-infer-a"].get("tenantId") is None

    # 3. Attempting to explicitly assign q-legacy-infer-a (referenced by tenant-a's shipment) to tenant-b fails.
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.migrate_tenantless_carrier_quotes(assignments={"q-legacy-infer-a": "tenant-b"})

    # Attempting to overwrite already-owned q-owned-a to tenant-b fails.
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.migrate_tenantless_carrier_quotes(assignments={"q-owned-a": "tenant-b"})

    # 4. Run actual migration with shipment inference + default_tenant_id="tenant-b".
    migrated = log.migrate_tenantless_carrier_quotes(default_tenant_id="tenant-b")
    assert migrated["assignedCount"] == 2
    assigned_map = {a["quoteId"]: a for a in migrated["assigned"]}
    assert assigned_map["q-legacy-infer-a"]["tenantId"] == "tenant-a"
    assert assigned_map["q-legacy-infer-a"]["attribution"] == "inferred_from_shipment"
    assert assigned_map["q-legacy-unreferenced"]["tenantId"] == "tenant-b"
    assert assigned_map["q-legacy-unreferenced"]["attribution"] == "default_tenant"
    assert migrated["conflictCount"] == 1
    assert migrated["conflicts"][0]["quoteId"] == "q-legacy-conflict"

    # Re-running migration is idempotent (0 newly assigned, only the multi-tenant conflict remains).
    again = log.migrate_tenantless_carrier_quotes(default_tenant_id="tenant-b")
    assert again["assignedCount"] == 0
    assert again["conflictCount"] == 1

    # 5. Rollback (unassign) works for quotes migrated from tenantless state, and refuses natively owned quotes.
    with pytest.raises(PermissionError, match="not migrated from tenantless"):
        log.unassign_migrated_carrier_quotes(["q-owned-a"])

    rb = log.unassign_migrated_carrier_quotes(["q-legacy-unreferenced"])
    assert rb["rolledBackCount"] == 1
    assert rb["rolledBack"][0] == {"quoteId": "q-legacy-unreferenced", "previousTenantId": "tenant-b"}
    assert log.carrier_quotes["q-legacy-unreferenced"].get("tenantId") is None

    reloaded = LogisticsService(root=log.root)
    assert reloaded.carrier_quotes["q-legacy-infer-a"]["tenantId"] == "tenant-a"
    assert reloaded.carrier_quotes["q-legacy-unreferenced"].get("tenantId") is None


def test_conflicting_carrier_quotes_preflight_and_remediation_cli(tmp_path, capsys):
    import json
    from fox3d.logistics import (
        classify_carrier_quote,
        cli_main,
        is_explicit_global_carrier_quote,
        is_tenantless_carrier_quote,
        is_valid_tenant_carrier_quote,
    )

    q1 = {"quoteId": "q1", "tenantId": "ta", "globalQuote": True}
    q2 = {"quoteId": "q2", "ownership": "TENANT_OWNED", "globalQuote": True}

    for bad in (q1, q2):
        assert is_explicit_global_carrier_quote(bad) is False
        assert is_valid_tenant_carrier_quote(bad) is False
        assert is_tenantless_carrier_quote(bad) is True
        info = classify_carrier_quote(bad)
        assert info["requiresMigration"] is True
        assert info["metadataConflict"] is True

    log = _wired_logistics(tmp_path)
    log.import_carrier_quote(
        {"quoteId": "q-valid-ta", "carrier": "CA", "charge": 100},
        source="MANUAL",
        tenant_id="ta",
    )
    log.import_carrier_quote(
        {"quoteId": "q-valid-global", "carrier": "CG", "charge": 120},
        source="IMPORTED",
        allow_global=True,
    )
    path = log.root / "logistics.json"
    disk = json.loads(path.read_text(encoding="utf-8"))
    disk["carrier_quotes"].extend([dict(q1), dict(q2)])
    path.write_text(json.dumps(disk, indent=2), encoding="utf-8")
    log.load()

    # 1. CLI --check --require-zero detects both q1 and q2 and exits with code 1.
    capsys.readouterr()
    assert cli_main(["--root", str(log.root), "--check", "--require-zero"]) == 1
    out_check = json.loads(capsys.readouterr().out)
    assert out_check["ready"] is False
    assert out_check["tenantlessCount"] == 2
    assert out_check["conflictCount"] == 2
    assert out_check["quoteIds"] == ["q1", "q2"]
    assert out_check["conflictQuoteIds"] == ["q1", "q2"]

    # 2. Running migration without target tenant or --mark-global leaves both in unresolved & conflicts (exit 1).
    assert cli_main(["--root", str(log.root), "--require-zero"]) == 1
    out_unres = json.loads(capsys.readouterr().out)
    assert out_unres["assignedCount"] == 0
    assert out_unres["unresolvedCount"] == 2
    assert out_unres["conflictCount"] == 2

    # 3. Attempting to mark q1 (owned by 'ta') global or assign q1 to 'tb' raises PermissionError.
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.migrate_tenantless_carrier_quotes(quote_ids=["q1"], mark_global=True)
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.migrate_tenantless_carrier_quotes(assignments={"q1": "tb"})

    # 4. Remediate q1 to 'ta' and q2 to 'tb' via CLI --assign; verify idempotency on second run.
    assert cli_main(["--root", str(log.root), "--assign", "q1=ta", "--assign", "q2=tb", "--require-zero"]) == 0
    out_mig = json.loads(capsys.readouterr().out)
    assert out_mig["assignedCount"] == 2
    assert out_mig["unresolvedCount"] == 0
    assert out_mig["conflictCount"] == 0

    assert cli_main(["--root", str(log.root), "--check", "--require-zero"]) == 0
    out_after = json.loads(capsys.readouterr().out)
    assert out_after["ready"] is True
    assert out_after["tenantlessCount"] == 0

    # Re-running the exact same CLI assignment command is idempotent (alreadyAssignedCount == 2, assignedCount == 0).
    assert cli_main(["--root", str(log.root), "--assign", "q1=ta", "--assign", "q2=tb", "--require-zero"]) == 0
    out_idem = json.loads(capsys.readouterr().out)
    assert out_idem["assignedCount"] == 0
    assert out_idem["alreadyAssignedCount"] == 2
    assert out_idem["unresolvedCount"] == 0



def test_palletize_persist_false_and_rollback_on_persist_failure(tmp_path, monkeypatch):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "tenant-a", qty=1)
    cid = cartons[0]["cartonId"]

    orig_persist = log.persist
    persist_calls = 0

    def spy_persist() -> None:
        nonlocal persist_calls
        persist_calls += 1
        orig_persist()

    monkeypatch.setattr(log, "persist", spy_persist)

    # persist=False puts the pallet in memory without writing to disk.
    p_mem = log.palletize([cid], persist=False)
    assert persist_calls == 0
    assert p_mem["palletPlanId"] in log.pallets
    assert LogisticsService(root=log.root).pallets == {}

    log.pallets.pop(p_mem["palletPlanId"], None)

    # Default persist=True writes once; if persist raises OSError, memory is rolled back.
    def fail_persist() -> None:
        raise OSError("simulated palletize persist failure")

    monkeypatch.setattr(log, "persist", fail_persist)
    with pytest.raises(OSError, match="simulated palletize persist failure"):
        log.palletize([cid])
    assert log.pallets == {}
    assert LogisticsService(root=log.root).pallets == {}


def test_shipment_draft_single_persist_and_rollback_preserves_existing_draft(tmp_path, monkeypatch):
    log = _wired_logistics(tmp_path)
    cartons = _carton(log, "tenant-a", qty=2)
    c1, c2 = cartons[0]["cartonId"], cartons[1]["cartonId"]

    orig_persist = log.persist

    # 1. Failing persist on a brand new shipment draft rolls back new shipment, content idem key, and API idem key.
    def fail_persist() -> None:
        raise OSError("simulated shipment draft persist failure")

    monkeypatch.setattr(log, "persist", fail_persist)
    with pytest.raises(OSError, match="simulated shipment draft persist failure"):
        log.shipment_draft(
            origin="TW",
            destination="TPE",
            carton_ids=[c1],
            service="ground",
            idempotency_key="idem-fail-1",
        )
    assert log.shipments == {}
    assert f"tenant-a::shipment::TW:TPE:{c1}:ground" not in log._idem
    assert "tenant-a::shipment-key::idem-fail-1" not in log._idem

    # 2. Succeeding shipment_draft with idempotency_key calls persist() exactly once with all keys in memory.
    persist_snapshots: list[tuple[set[str], set[str]]] = []

    def spy_persist() -> None:
        persist_snapshots.append((set(log.shipments), set(log._idem)))
        orig_persist()

    monkeypatch.setattr(log, "persist", spy_persist)
    draft1 = log.shipment_draft(
        origin="TW",
        destination="TPE",
        carton_ids=[c1],
        service="ground",
        idempotency_key="idem-ok-1",
    )
    assert len(persist_snapshots) == 1
    snap_shipments, snap_idem = persist_snapshots[0]
    assert draft1["shipmentId"] in snap_shipments
    assert f"tenant-a::shipment::TW:TPE:{c1}:ground" in snap_idem
    assert "tenant-a::shipment-key::idem-ok-1" in snap_idem

    # 3. Create an existing draft for c2 without idempotency_key, then fail persist when attaching a new idempotency_key:
    # the existing draft and content idem key must NOT be deleted.
    existing = log.shipment_draft(
        origin="TW",
        destination="KHH",
        carton_ids=[c2],
        service="ground",
    )
    existing_sid = existing["shipmentId"]
    content_key_c2 = f"tenant-a::shipment::TW:KHH:{c2}:ground"
    assert existing_sid in log.shipments
    assert log._idem.get(content_key_c2) == existing_sid

    monkeypatch.setattr(log, "persist", fail_persist)
    with pytest.raises(OSError, match="simulated shipment draft persist failure"):
        log.shipment_draft(
            origin="TW",
            destination="KHH",
            carton_ids=[c2],
            service="ground",
            idempotency_key="idem-attach-fail",
        )
    assert existing_sid in log.shipments
    assert log._idem.get(content_key_c2) == existing_sid
    assert "tenant-a::shipment-key::idem-attach-fail" not in log._idem



def _inject_raw_quotes(log: LogisticsService, extra: list) -> None:
    import json

    assert log.root is not None
    path = log.root / "logistics.json"
    disk = json.loads(path.read_text(encoding="utf-8"))
    disk["carrier_quotes"].extend(extra)
    path.write_text(json.dumps(disk, indent=2), encoding="utf-8")
    log.load()


def _raw_quotes(log: LogisticsService) -> list:
    import json

    assert log.root is not None
    return json.loads((log.root / "logistics.json").read_text(encoding="utf-8"))["carrier_quotes"]


def test_duplicate_quote_id_blocks_preflight_and_is_preserved_until_resolved(tmp_path, capsys):
    import json
    from fox3d.logistics import carrier_quote_record_fingerprint, cli_main

    log = _wired_logistics(tmp_path)
    log.import_carrier_quote({"quoteId": "q-ok", "carrier": "CA", "charge": 1}, source="MANUAL", tenant_id="ta")
    first = {"quoteId": "q1", "tenantId": "ta", "globalQuote": True}
    second = {"quoteId": "q1", "tenantId": "ta"}
    _inject_raw_quotes(log, [first, second])

    # Neither copy is usable as a quote (the later one no longer silently wins).
    assert "q1" not in log.carrier_quotes

    rep = log.inspect_tenantless_carrier_quotes()
    assert rep["ready"] is False
    assert rep["totalQuotes"] == 3
    assert rep["tenantlessCount"] == 2
    assert rep["blockingCount"] == 2
    assert rep["conflictCount"] == 2
    assert rep["duplicateQuoteIds"] == ["q1"]
    assert rep["duplicateRecordCount"] == 2
    assert rep["quoteIds"] == ["q1", "q1"]
    fps = [item["recordFingerprint"] for item in rep["items"]]
    assert fps == [carrier_quote_record_fingerprint(first), carrier_quote_record_fingerprint(second)]
    for item in rep["items"]:
        assert item["issue"] == "duplicate_quote_id"
        assert item["duplicateCount"] == 2
        assert item["conflict"] is True
        assert "--keep-duplicate q1=" in item["remediation"]
    assert [item["rawIndex"] for item in rep["items"]] == [1, 2]

    capsys.readouterr()
    assert cli_main(["--root", str(log.root), "--check", "--require-zero"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["duplicateQuoteIds"] == ["q1"]
    assert out["tenantlessCount"] == 2

    # Migration without a quote filter reports both copies as unresolved; --require-zero fails.
    assert cli_main(["--root", str(log.root), "--tenant", "ta", "--require-zero"]) == 1
    mig = json.loads(capsys.readouterr().out)
    assert mig["unresolvedCount"] == 2
    assert {e["reason"] for e in mig["unresolved"]} == {"duplicate_quote_id"}

    # Writes that target the duplicated quoteId are refused instead of picking one copy.
    with pytest.raises(PermissionError, match="duplicate records"):
        log.import_carrier_quote({"quoteId": "q1", "carrier": "X", "charge": 2}, source="MANUAL", tenant_id="ta")
    with pytest.raises(PermissionError, match="duplicate records"):
        log.migrate_tenantless_carrier_quotes(assignments={"q1": "ta"})
    with pytest.raises(PermissionError, match="duplicate records"):
        log.migrate_tenantless_carrier_quotes(quote_ids=["q1"], tenant_id="ta")
    with pytest.raises(PermissionError, match="duplicate records"):
        log.unassign_migrated_carrier_quotes(["q1"])

    # Unrelated logistics writes persist both copies verbatim.
    log.import_carrier_quote({"quoteId": "q-other", "carrier": "CB", "charge": 3}, source="MANUAL", tenant_id="ta")
    raw = _raw_quotes(log)
    assert raw.count(first) == 1 and raw.count(second) == 1
    assert LogisticsService(root=log.root).inspect_tenantless_carrier_quotes()["duplicateQuoteIds"] == ["q1"]

    # Wrong fingerprint is refused and changes nothing; dry-run changes nothing.
    with pytest.raises(KeyError, match="does not match"):
        log.resolve_carrier_quote_records(keep={"q1": "0" * 64})
    with pytest.raises(KeyError, match="no duplicate"):
        log.resolve_carrier_quote_records(keep={"q-ok": fps[0]})
    with pytest.raises(ValueError, match="nothing to resolve"):
        log.resolve_carrier_quote_records()
    dry = log.resolve_carrier_quote_records(keep={"q1": fps[1]}, dry_run=True)
    assert dry["removedCount"] == 1 and dry["remainingAnomalyCount"] == 0
    assert _raw_quotes(log).count(first) == 1

    # Explicit resolution via CLI keeps the chosen copy and prints the removed one.
    assert cli_main(["--root", str(log.root), "--keep-duplicate", f"q1={fps[1]}", "--require-zero"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["keptCount"] == 1
    # rawIndex shifted after the intervening write; the fingerprint still identifies the record.
    assert [{k: v for k, v in r.items() if k != "rawIndex"} for r in res["removed"]] == [
        {"reason": "duplicate_quote_id", "quoteId": "q1", "recordFingerprint": fps[0], "record": first}
    ]
    raw_after = _raw_quotes(log)
    assert [q for q in raw_after if q.get("quoteId") == "q1"] == [second]
    assert cli_main(["--root", str(log.root), "--check", "--require-zero"]) == 0
    capsys.readouterr()
    log.load()
    assert log.carrier_quotes["q1"] == second


def test_non_object_carrier_quote_fails_closed_and_survives_other_writes(tmp_path, capsys):
    import json
    from fox3d.logistics import carrier_quote_record_fingerprint, cli_main

    log = _wired_logistics(tmp_path)
    log.import_carrier_quote({"quoteId": "q-ok", "carrier": "CA", "charge": 1}, source="MANUAL", tenant_id="ta")
    _inject_raw_quotes(log, ["bad", 7])

    rep = log.inspect_tenantless_carrier_quotes()
    assert rep["ready"] is False
    assert rep["invalidRecordCount"] == 2
    assert rep["tenantlessCount"] == 2
    assert rep["quoteIds"] == ["<non-object:1>", "<non-object:2>"]
    assert [item["rawRecord"] for item in rep["items"]] == ["bad", 7]
    assert all(item["issue"] == "non_object" for item in rep["items"])
    capsys.readouterr()
    assert cli_main(["--root", str(log.root), "--check", "--require-zero"]) == 1
    capsys.readouterr()

    # Subsequent logistics writes keep the raw entries instead of dropping them.
    log.import_carrier_quote({"quoteId": "q-two", "carrier": "CB", "charge": 2}, source="MANUAL", tenant_id="ta")
    cartons = _carton(log, "ta")
    assert cartons
    raw = _raw_quotes(log)
    assert "bad" in raw and 7 in raw
    assert LogisticsService(root=log.root).inspect_tenantless_carrier_quotes()["invalidRecordCount"] == 2

    with pytest.raises(KeyError, match="non-object"):
        log.resolve_carrier_quote_records(drop=[carrier_quote_record_fingerprint("other")])

    fp_bad = carrier_quote_record_fingerprint("bad")
    assert cli_main(["--root", str(log.root), "--drop-invalid", fp_bad, "--require-zero"]) == 1
    res = json.loads(capsys.readouterr().out)
    assert res["removed"][0]["record"] == "bad"
    assert res["remainingAnomalyCount"] == 1
    assert "bad" not in _raw_quotes(log) and 7 in _raw_quotes(log)

    fp_seven = carrier_quote_record_fingerprint(7)
    assert cli_main(["--root", str(log.root), "--drop-invalid", fp_seven, "--require-zero"]) == 0
    capsys.readouterr()
    assert cli_main(["--root", str(log.root), "--check", "--require-zero"]) == 0
    capsys.readouterr()
    assert {q["quoteId"] for q in _raw_quotes(log)} == {"q-ok", "q-two"}


def test_conflicting_or_invalid_tenant_fields_stay_unresolved_until_explicit_repair(tmp_path, capsys):
    import json
    import threading

    from fox3d.logistics import classify_carrier_quote, cli_main
    from fox3d.pilot_shipping_api import _quote_visible_to_tenant

    conflict = {"quoteId": "q1", "tenantId": "ta", "tenant_id": "tb", "charge": 123}
    invalid = {"quoteId": "q-invalid", "tenantId": "  ", "tenant_id": 12, "charge": 9}
    half_invalid = {"quoteId": "q-half", "tenantId": "ta", "tenant_id": "   ", "charge": 8}
    legacy = {
        "quoteId": "q-legacy",
        "carrier": "LEGACY",
        "charge": 50,
        "ownership": "GLOBAL_REFERENCE",
        "service": "ground",
    }

    conflict_info = classify_carrier_quote(conflict)
    assert conflict_info["issue"] == "conflicting_tenant_id"
    assert conflict_info["tenantId"] is None
    assert conflict_info["tenantFieldConflict"] is True
    assert conflict_info["claimedTenantIds"] == ["ta", "tb"]
    assert conflict_info["validTenantOwned"] is False
    assert conflict_info["explicitGlobal"] is False

    invalid_info = classify_carrier_quote(invalid)
    assert invalid_info["issue"] == "invalid_tenant_id"
    assert invalid_info["tenantId"] is None
    assert invalid_info["tenantFieldConflict"] is True
    assert invalid_info["claimedTenantIds"] == []

    half_info = classify_carrier_quote(half_invalid)
    assert half_info["issue"] == "invalid_tenant_id"
    assert half_info["tenantFieldConflict"] is True
    assert half_info["claimedTenantIds"] == ["ta"]
    assert half_info["tenantId"] is None

    log = _wired_logistics(tmp_path)
    log.import_carrier_quote({"quoteId": "q-owned", "carrier": "CA", "charge": 1}, source="MANUAL", tenant_id="ta")
    cartons_ta = _carton(log, "ta", wo="wo-ta")
    cartons_tc = _carton(log, "tc", wo="wo-tc")
    log.shipment_draft(origin="TW", destination="TPE", carton_ids=[cartons_ta[0]["cartonId"]], quote_id="q-legacy")
    log.shipment_draft(origin="TW", destination="KHH", carton_ids=[cartons_tc[0]["cartonId"]], quote_id="q1")
    log.persist()
    _inject_raw_quotes(log, [dict(conflict), dict(invalid), dict(half_invalid), dict(legacy)])

    report = log.inspect_tenantless_carrier_quotes()
    by_qid = {item["quoteId"]: item for item in report["items"]}
    assert by_qid["q1"]["inferredTenantId"] is None
    assert by_qid["q1"]["conflict"] is True
    assert by_qid["q1"]["rawTenantFields"] == {"tenantId": "ta", "tenant_id": "tb"}
    assert by_qid["q1"]["claimedTenantIds"] == ["ta", "tb"]
    assert "--repair-tenant q1=ta" in by_qid["q1"]["remediation"]
    assert "--repair-tenant q1=tb" in by_qid["q1"]["remediation"]
    assert by_qid["q-legacy"]["inferredTenantId"] == "ta"
    assert by_qid["q-legacy"]["tenantFieldConflict"] is False

    for tenant in ("ta", "tb", "tc"):
        assert _quote_visible_to_tenant(log.carrier_quotes["q1"], tenant) is False
        assert _quote_visible_to_tenant(log.carrier_quotes["q-invalid"], tenant) is False
        assert _quote_visible_to_tenant(log.carrier_quotes["q-half"], tenant) is False

    original_q1 = json.loads(json.dumps(log.carrier_quotes["q1"]))
    original_invalid = json.loads(json.dumps(log.carrier_quotes["q-invalid"]))
    original_half = json.loads(json.dumps(log.carrier_quotes["q-half"]))
    path = log.root / "logistics.json"
    bytes_before = path.read_bytes()

    marked = log.migrate_tenantless_carrier_quotes(mark_global=True)
    assert marked["markedGlobalCount"] == 0
    assert {row["quoteId"] for row in marked["unresolved"]} >= {"q1", "q-invalid", "q-half"}
    assert log.carrier_quotes["q1"] == original_q1
    assert log.carrier_quotes["q-invalid"] == original_invalid
    assert log.carrier_quotes["q-half"] == original_half
    assert path.read_bytes() == bytes_before
    assert _quote_visible_to_tenant(log.carrier_quotes["q1"], "tc") is False

    assigned = log.migrate_tenantless_carrier_quotes(tenant_id="tc")
    assert assigned["assignedCount"] == 1
    assert {row["quoteId"] for row in assigned["assigned"]} == {"q-legacy"}
    assert assigned["assigned"][0]["tenantId"] == "ta"
    assert assigned["assigned"][0]["attribution"] == "inferred_from_shipment"
    assert {row["quoteId"] for row in assigned["unresolved"]} >= {"q1", "q-invalid", "q-half"}
    assert log.carrier_quotes["q1"] == original_q1
    assert log.carrier_quotes["q-invalid"] == original_invalid
    assert log.carrier_quotes["q-half"] == original_half
    assert log.carrier_quotes["q-legacy"]["tenantId"] == "ta"
    assert _quote_visible_to_tenant(log.carrier_quotes["q1"], "tc") is False

    # Explicit requests are refused. Batch requests leave the raw fields untouched.
    refused = (
        lambda: log.migrate_tenantless_carrier_quotes(quote_ids=["q1"], mark_global=True),
        lambda: log.migrate_tenantless_carrier_quotes(quote_ids=["q1"], tenant_id="tc"),
        lambda: log.migrate_tenantless_carrier_quotes(assignments={"q1": "tc"}),
        lambda: log.migrate_tenantless_carrier_quotes(assignments={"q1": "ta"}),
        lambda: log.migrate_tenantless_carrier_quotes(assignments={"q-invalid": "tc"}),
        lambda: log.migrate_tenantless_carrier_quotes(assignments={"q-half": "tb"}),
    )
    for call in refused:
        with pytest.raises(PermissionError, match="tenant isolation") as raised:
            call()
        assert "--repair-tenant" in str(raised.value)
    still_batch = log.migrate_tenantless_carrier_quotes(mark_global=True)
    assert still_batch["markedGlobalCount"] == 0
    assert log.migrate_tenantless_carrier_quotes(tenant_id="tc")["assignedCount"] == 0
    assert log.carrier_quotes["q1"] == original_q1
    assert log.carrier_quotes["q-invalid"] == original_invalid
    assert log.carrier_quotes["q-half"] == original_half

    with pytest.raises(PermissionError, match="tenant isolation"):
        log.repair_conflicting_carrier_quote_tenants(assignments={"q1": "tc"})
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.repair_conflicting_carrier_quote_tenants(mark_global_ids=["q1"])
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.repair_conflicting_carrier_quote_tenants(assignments={"q-half": "tb"})
    assert log.carrier_quotes["q1"] == original_q1
    assert log.carrier_quotes["q-half"] == original_half

    dry = log.repair_conflicting_carrier_quote_tenants(assignments={"q1": "ta"}, dry_run=True)
    assert dry["dryRun"] is True
    assert dry["repairedCount"] == 1
    assert dry["repaired"][0]["preservedTenantFields"] == {"tenantId": "ta", "tenant_id": "tb"}
    assert log.carrier_quotes["q1"] == original_q1

    capsys.readouterr()
    assert cli_main(["--root", str(log.root), "--mark-global", "--require-zero"]) == 1
    cli_marked = json.loads(capsys.readouterr().out)
    assert cli_marked["markedGlobalCount"] == 0
    assert any(row["quoteId"] == "q1" and row["rawTenantFields"] == {"tenantId": "ta", "tenant_id": "tb"} for row in cli_marked["unresolved"])
    assert cli_main(["--root", str(log.root), "--tenant", "tc", "--require-zero"]) == 1
    cli_assigned = json.loads(capsys.readouterr().out)
    assert cli_assigned["assignedCount"] == 0
    assert log.carrier_quotes["q1"] == original_q1

    assert cli_main(["--root", str(log.root), "--repair-tenant", "q1=ta"]) == 0
    repaired = json.loads(capsys.readouterr().out)
    assert repaired["repairedCount"] == 1
    assert repaired["repaired"][0]["tenantId"] == "ta"
    assert repaired["repaired"][0]["preservedTenantFields"] == {"tenantId": "ta", "tenant_id": "tb"}
    log.load()
    stored = log.carrier_quotes["q1"]
    assert stored["charge"] == 123
    assert stored["tenantId"] == "ta"
    assert "tenant_id" not in stored
    assert stored["ownership"] == "TENANT_OWNED"
    assert stored["globalQuote"] is False
    assert stored.get("migratedFromTenantless") is not True
    assert _quote_visible_to_tenant(stored, "ta") is True
    assert _quote_visible_to_tenant(stored, "tb") is False
    assert _quote_visible_to_tenant(stored, "tc") is False
    with pytest.raises(PermissionError, match="not migrated from tenantless"):
        log.unassign_migrated_carrier_quotes(["q1"])

    bytes_after_repair = path.read_bytes()
    again = log.repair_conflicting_carrier_quote_tenants(assignments={"q1": "ta"})
    assert again["repairedCount"] == 0
    assert again["alreadyRepairedCount"] == 1
    assert path.read_bytes() == bytes_after_repair

    invalid_repair = log.repair_conflicting_carrier_quote_tenants(assignments={"q-invalid": "ops"})
    assert invalid_repair["repaired"][0]["preservedTenantFields"] == {"tenantId": "  ", "tenant_id": 12}
    assert log.carrier_quotes["q-invalid"]["tenantId"] == "ops"
    assert log.carrier_quotes["q-invalid"]["charge"] == 9
    assert "tenant_id" not in log.carrier_quotes["q-invalid"]
    assert _quote_visible_to_tenant(log.carrier_quotes["q-invalid"], "ops") is True
    assert _quote_visible_to_tenant(log.carrier_quotes["q-invalid"], "tc") is False

    half_repair = log.repair_conflicting_carrier_quote_tenants(assignments={"q-half": "ta"})
    assert half_repair["repaired"][0]["preservedTenantFields"] == {"tenantId": "ta", "tenant_id": "   "}
    assert log.carrier_quotes["q-half"]["tenantId"] == "ta"
    assert "tenant_id" not in log.carrier_quotes["q-half"]
    assert _quote_visible_to_tenant(log.carrier_quotes["q-half"], "tb") is False

    blank = {"quoteId": "q-blank", "tenantId": "   ", "charge": 4}
    _inject_raw_quotes(log, [blank])
    assert _quote_visible_to_tenant(log.carrier_quotes["q-blank"], "tc") is False
    with pytest.raises(PermissionError, match="tenant isolation"):
        log.migrate_tenantless_carrier_quotes(quote_ids=["q-blank"], mark_global=True)
    assert log.carrier_quotes["q-blank"] == blank
    blank_global = log.repair_conflicting_carrier_quote_tenants(mark_global_ids=["q-blank"])
    assert blank_global["repaired"][0]["preservedTenantFields"] == {"tenantId": "   "}
    assert blank_global["repaired"][0]["globalQuote"] is True
    assert log.carrier_quotes["q-blank"]["globalQuote"] is True
    assert "tenantId" not in log.carrier_quotes["q-blank"]
    assert log.carrier_quotes["q-blank"]["charge"] == 4
    assert _quote_visible_to_tenant(log.carrier_quotes["q-blank"], "tc") is True
    again_global = log.repair_conflicting_carrier_quote_tenants(mark_global_ids=["q-blank"])
    assert again_global["repairedCount"] == 0
    assert again_global["alreadyRepairedCount"] == 1

    with pytest.raises(ValueError, match="nothing to repair"):
        log.repair_conflicting_carrier_quote_tenants()
    with pytest.raises(ValueError, match="mark_global_ids"):
        log.repair_conflicting_carrier_quote_tenants(mark_global_ids="q-blank")  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="not found"):
        log.repair_conflicting_carrier_quote_tenants(assignments={"missing-quote": "ta"})
    with pytest.raises(SystemExit):
        cli_main(["--root", str(log.root), "--repair-tenant", "not-a-pair"])
    with pytest.raises(SystemExit):
        cli_main(["--root", str(log.root), "--repair-tenant", "q1=ta", "--mark-global"])

    # A second disputed quote is repaired once even if two callers arrive together.
    q2 = {"quoteId": "q2", "tenantId": "ta", "tenant_id": "tb", "charge": 7}
    _inject_raw_quotes(log, [q2])
    results: list[dict] = []
    errors: list[BaseException] = []

    def _repair_once() -> None:
        try:
            results.append(log.repair_conflicting_carrier_quote_tenants(assignments={"q2": "tb"}))
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=_repair_once), threading.Thread(target=_repair_once)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sum(row["repairedCount"] for row in results) == 1
    assert sum(row["alreadyRepairedCount"] for row in results) == 1
    assert log.carrier_quotes["q2"]["tenantId"] == "tb"
    assert log.carrier_quotes["q2"]["charge"] == 7
    assert "tenant_id" not in log.carrier_quotes["q2"]
    preserved = [row["repaired"][0]["preservedTenantFields"] for row in results if row["repaired"]]
    assert preserved == [{"tenantId": "ta", "tenant_id": "tb"}]
    assert _quote_visible_to_tenant(log.carrier_quotes["q2"], "ta") is False
    assert _quote_visible_to_tenant(log.carrier_quotes["q2"], "tb") is True
    assert _quote_visible_to_tenant(log.carrier_quotes["q2"], "tc") is False


def test_non_list_carrier_quotes_container_fails_closed_without_rewrite(tmp_path):
    import json

    root = tmp_path / "logistics"
    root.mkdir()
    path = root / "logistics.json"
    path.write_text(json.dumps({"carrier_quotes": {"q1": {"quoteId": "q1", "tenantId": "ta"}}}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="carrier_quotes must be a list"):
        LogisticsService(root=root)
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["keep-duplicate", "drop-invalid", "unassign"])
def test_require_zero_checks_all_tenantless_quotes_after_record_operations(tmp_path, capsys, operation):
    import json
    from fox3d.logistics import carrier_quote_record_fingerprint, cli_main

    log = _wired_logistics(tmp_path)
    log.persist()
    legacy = {"quoteId": "legacy", "charge": 123}
    duplicate = {"quoteId": "duplicate", "tenantId": "ta"}
    if operation == "keep-duplicate":
        _inject_raw_quotes(log, [legacy, duplicate, {**duplicate, "charge": 1}])
        flags = ["--keep-duplicate", f"duplicate={carrier_quote_record_fingerprint(duplicate)}"]
    elif operation == "drop-invalid":
        _inject_raw_quotes(log, [legacy, "bad"])
        flags = ["--drop-invalid", carrier_quote_record_fingerprint("bad")]
    else:
        _inject_raw_quotes(log, [legacy, "bad", {"quoteId": "migrated", "tenantId": "ta", "migratedFromTenantless": True}])
        flags = ["--unassign", "migrated"]

    assert cli_main(["--root", str(log.root), *flags, "--require-zero"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert cli_main(["--root", str(log.root), "--check", "--require-zero"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert result["remainingTenantlessCount"] == report["tenantlessCount"]
    assert "legacy" in report["quoteIds"]
    if operation == "unassign":
        assert "migrated" in report["quoteIds"]
