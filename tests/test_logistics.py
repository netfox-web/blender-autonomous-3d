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

