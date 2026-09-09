"""Phase 421–480 pilot deployment. MOCK/unit/FIXTURE/REAL-logic — not Production Ready."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.deploy_chaos import ChaosHarness
from fox3d.inventory import MaterialLotRegistry, StockShortage
from fox3d.journal import EventJournal, JournalCommitError
from fox3d.operator import make_token, require_confirm, resolve_scan
from fox3d.recovery import CATALOG, PilotException
from fox3d.storelock import CrashInjected, StaleGeneration
from fox3d.workorder import STRICT_STOCK


def _src() -> str:
    return str(Path(__file__).resolve().parents[1] / "src")


def test_journal_restart_tenant_duplicate_tamper(tmp_path):
    j = EventJournal(tmp_path / "journal")
    a1 = j.append("release.create", tenant_id="ta", aggregate_type="ManufacturingRelease", aggregate_id="r1", actor="eng", payload={"k": 1}, semantic_key="ta::r1")
    a2 = j.append("release.create", tenant_id="ta", aggregate_type="ManufacturingRelease", aggregate_id="r1", actor="eng", payload={"k": 1}, semantic_key="ta::r1")
    assert a1["eventId"] == a2["eventId"]
    j.append("workorder.create", tenant_id="ta", aggregate_type="WorkOrder", aggregate_id="w1", actor="ops", payload={"n": 2}, release_hash="rh")
    j.append("release.create", tenant_id="tb", aggregate_type="ManufacturingRelease", aggregate_id="r2", actor="eng", payload={"k": 1}, semantic_key="tb::r2")
    assert all(e["tenantId"] == "ta" for e in j.list("ta"))
    assert all(e["eventId"] not in {x["eventId"] for x in j.list("tb")} for e in j.list("ta"))
    seq = [e["sequence"] for e in j.list("ta")]
    assert seq == sorted(seq) and seq[0] == 1
    assert j.verify("ta")["ok"] is True
    j2 = EventJournal(tmp_path / "journal")
    assert [e["eventId"] for e in j2.list("ta")] == [e["eventId"] for e in j.list("ta")]
    j2.tamper("ta", 0, payload={"k": 99})
    broken = j2.verify("ta")
    assert broken["ok"] is False
    assert broken["status"] == "BLOCKED_EVIDENCE"
    exported = EventJournal(tmp_path / "journal").export_slice("tb")
    assert exported["truthLabel"] in {"REAL", "BLOCKED_EVIDENCE"}
    assert all(e["tenantId"] == "tb" for e in exported["events"])


def test_journal_failure_does_not_succeed(platform):
    platform.pilot.journal._fail_next = True
    product = platform.kd.build_sku(tenant_id="jf", kind="OPEN_SHELF")
    snap = __import__("fox3d.mfg_release", fromlist=["product_snapshot"]).product_snapshot(product, family="KD_FURNITURE")
    before = len(platform.pilot.releases.releases)
    with pytest.raises(JournalCommitError):
        platform.pilot.releases.create(snap, tenant_id="jf", created_by="eng", idempotency_key="jf-fail")
    assert len(platform.pilot.releases.releases) == before


def test_subprocess_scarce_stock_no_oversell(tmp_path):
    root = tmp_path / "lots"
    lots = MaterialLotRegistry(root)
    lots.create(tenant_id="race", material="PB_18_WHITE", thickness=18, sheet_count=10)
    env = os.environ.copy()
    env["PYTHONPATH"] = _src() + os.pathsep + env.get("PYTHONPATH", "")
    procs = []
    for i in range(6):
        procs.append(
            subprocess.run(
                [sys.executable, "-m", "fox3d.inventory", "--root", str(root), "--tenant", "race", "--wo", f"w{i}", "--qty", "3", "--material", "PB_18_WHITE", "--thickness", "18"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        )
    ok_qty = 0
    for p in procs:
        lines = (p.stdout or "").strip().splitlines()
        if not lines:
            continue
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError:
            continue
        if payload.get("ok"):
            ok_qty += int(payload.get("qty") or 0)
    restarted = MaterialLotRegistry(root)
    rows = [restarted.quantities(l["lotId"], tenant_id="race") for l in restarted.list(tenant_id="race")]
    held = sum(r["reserved"] + r["consumed"] for r in rows)
    assert held <= 10
    assert ok_qty <= 10
    assert all(r["conserved"] for r in rows)
    assert all(r["sheetCount"] == r["available"] + r["reserved"] + r["consumed"] for r in rows)


def test_two_process_same_wo_idempotent(tmp_path):
    root = tmp_path / "lots"
    lots = MaterialLotRegistry(root)
    lots.create(tenant_id="idem", material="PB_18_WHITE", thickness=18, sheet_count=4)
    env = os.environ.copy()
    env["PYTHONPATH"] = _src() + os.pathsep + env.get("PYTHONPATH", "")
    args = [sys.executable, "-m", "fox3d.inventory", "--root", str(root), "--tenant", "idem", "--wo", "same-wo", "--qty", "2", "--material", "PB_18_WHITE", "--thickness", "18"]
    a = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    b = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    restarted = MaterialLotRegistry(root)
    q = restarted.quantities(restarted.list(tenant_id="idem")[0]["lotId"], tenant_id="idem")
    assert q["reserved"] == 2
    assert q["conserved"]
    assert json.loads(a.stdout.strip().splitlines()[-1])["ok"] is True
    assert json.loads(b.stdout.strip().splitlines()[-1])["ok"] is True


def test_crash_after_first_lot_all_or_nothing(tmp_path):
    lots = MaterialLotRegistry(tmp_path / "lots")
    a = lots.create(tenant_id="cr", material="PB_18_WHITE", thickness=18, sheet_count=2)
    b = lots.create(tenant_id="cr", material="PB_18_WHITE", thickness=18, sheet_count=2)
    before = {a["lotId"]: lots.quantities(a["lotId"], tenant_id="cr"), b["lotId"]: lots.quantities(b["lotId"], tenant_id="cr")}
    lots._crash_after_first_stage = True
    with pytest.raises(CrashInjected):
        lots.allocate_requirement(tenant_id="cr", work_order_id="wo", quantity=3, material="PB_18_WHITE", thickness=18)
    lots._crash_after_first_stage = False
    restarted = MaterialLotRegistry(tmp_path / "lots")
    assert restarted.quantities(a["lotId"], tenant_id="cr") == before[a["lotId"]]
    assert restarted.quantities(b["lotId"], tenant_id="cr") == before[b["lotId"]]


def test_stale_generation_cannot_overwrite(tmp_path):
    root = tmp_path / "lots"
    lots = MaterialLotRegistry(root)
    lots.create(tenant_id="sg", material="PB_18_WHITE", thickness=18, sheet_count=1)
    snap = lots.generation
    other = MaterialLotRegistry(root)
    other.create(tenant_id="sg", material="OAK", thickness=18, sheet_count=1)
    with pytest.raises(StaleGeneration):
        lots.persist(expected_generation=snap)
    third = MaterialLotRegistry(root)
    mats = {l["material"] for l in third.list(tenant_id="sg")}
    assert "OAK" in mats and "PB_18_WHITE" in mats


def test_restart_conservation(tmp_path):
    root = tmp_path / "lots"
    lots = MaterialLotRegistry(root)
    lot = lots.create(tenant_id="cv", material="PB_18_WHITE", thickness=18, sheet_count=5)
    lots.reserve_sheets(lot["lotId"], tenant_id="cv", work_order_id="w1", quantity=2)
    restarted = MaterialLotRegistry(root)
    q = restarted.quantities(lot["lotId"], tenant_id="cv")
    assert q["sheetCount"] == q["available"] + q["reserved"] + q["consumed"]
    assert q["conserved"] is True


def test_quarantined_unavailable_under_lock(tmp_path):
    lots = MaterialLotRegistry(tmp_path / "lots")
    lot = lots.create(tenant_id="q", material="PB_18_WHITE", thickness=18, sheet_count=3)
    lots.quarantine(lot["lotId"], tenant_id="q", actor="ops", reason="bad")
    with pytest.raises(PermissionError):
        lots.reserve_sheets(lot["lotId"], tenant_id="q", work_order_id="w", quantity=1)


def _ready_wo(platform, tenant="st"):
    product = platform.kd.build_sku(tenant_id=tenant, kind="OPEN_SHELF")
    rel = platform.pilot.open_release(product, tenant_id=tenant, family="KD_FURNITURE")
    nest = (rel.get("snapshot") or {}).get("nesting") or {}
    row = {"supplierLot": f"{tenant}-lot", "material": nest.get("sheetSku") or "PB_18_WHITE", "thickness": nest.get("thickness") or 18, "quantity": 20}
    sheet_mm = nest.get("sheetMm") or []
    if len(sheet_mm) >= 2:
        row["length"] = float(sheet_mm[0])
        row["width"] = float(sheet_mm[1])
    platform.pilot.receiving.import_receipt(row, tenant_id=tenant, actor="recv", source="MANUAL", idempotency_key=f"{tenant}-lot")
    wo = platform.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops")
    platform.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
    platform.pilot.workorders.reserve_materials(wo["workOrderId"], actor="ops", tenant_id=tenant, allocation_policy=STRICT_STOCK)
    return wo, rel


def test_manual_station_dispatch_rules(platform):
    wo, rel = _ready_wo(platform, tenant="stn")
    op = wo["traveler"]["steps"][0]["operation"]
    online = platform.pilot.stations.register(
        tenant_id="stn",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    offline = platform.pilot.stations.register(tenant_id="stn", capabilities=["PANEL_CUTTING_MANUAL"], status="OFFLINE", actor="op")
    with pytest.raises((PilotException, PermissionError)):
        platform.pilot.dispatcher.dispatch(tenant_id="stn", work_order_id=wo["workOrderId"], operation=op, station_id=offline["stationId"], actor="op")
    lease = platform.pilot.dispatcher.dispatch(tenant_id="stn", work_order_id=wo["workOrderId"], operation=op, station_id=online["stationId"], actor="op")
    assert lease["releaseHash"] == rel["releaseHash"]
    ack1 = platform.pilot.dispatcher.ack(lease["leaseId"], tenant_id="stn", actor="op")
    ack2 = platform.pilot.dispatcher.ack(lease["leaseId"], tenant_id="stn", actor="op")
    assert ack1["leaseId"] == ack2["leaseId"]
    started = platform.pilot.dispatcher.start(lease["leaseId"], tenant_id="stn", actor="op")
    done1 = platform.pilot.dispatcher.complete(lease["leaseId"], tenant_id="stn", actor="op", confirm=True)
    done2 = platform.pilot.dispatcher.complete(lease["leaseId"], tenant_id="stn", actor="op", confirm=True)
    assert done1["opId"] == done2["opId"] == started["opId"]
    other = platform.pilot.stations.register(tenant_id="other", capabilities=["PANEL_CUTTING_MANUAL"], actor="x")
    with pytest.raises(PermissionError):
        platform.pilot.dispatcher.dispatch(tenant_id="other", work_order_id=wo["workOrderId"], operation=op, station_id=other["stationId"], actor="x")
    platform.pilot.workorders.cancel(wo["workOrderId"], actor="ops")
    st2 = platform.pilot.stations.register(
        tenant_id="stn",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    with pytest.raises(PermissionError):
        platform.pilot.dispatcher.dispatch(tenant_id="stn", work_order_id=wo["workOrderId"], operation=wo["traveler"]["steps"][1]["operation"], station_id=st2["stationId"], actor="op")


def test_station_lease_expiry_and_one_owner(platform):
    wo, _rel = _ready_wo(platform, tenant="lex")
    op = wo["traveler"]["steps"][0]["operation"]
    st = platform.pilot.stations.register(
        tenant_id="lex",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    lease = platform.pilot.dispatcher.dispatch(tenant_id="lex", work_order_id=wo["workOrderId"], operation=op, station_id=st["stationId"], actor="op")
    st2 = platform.pilot.stations.register(
        tenant_id="lex",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    with pytest.raises(PermissionError):
        platform.pilot.dispatcher.dispatch(tenant_id="lex", work_order_id=wo["workOrderId"], operation=op, station_id=st2["stationId"], actor="op")
    job = platform.queue.get(lease["jobId"])
    job["heartbeatAt"] = "2000-01-01T00:00:00+00:00"
    job["startedAt"] = "2000-01-01T00:00:00+00:00"
    expired = platform.pilot.dispatcher.expire_leases(max_age_seconds=1)
    assert lease["leaseId"] in expired
    again = platform.pilot.dispatcher.dispatch(tenant_id="lex", work_order_id=wo["workOrderId"], operation=op, station_id=st2["stationId"], actor="op")
    assert again["status"] == "LEASED"


def test_stale_release_cannot_dispatch(platform):
    wo, rel = _ready_wo(platform, tenant="stl")
    mutated = dict(rel["snapshot"])
    mutated["engineeringHash"] = "deadbeef" * 8
    platform.pilot.releases.refresh_stale(rel["releaseId"], mutated)
    st = platform.pilot.stations.register(
        tenant_id="stl",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    with pytest.raises(PermissionError):
        platform.pilot.dispatcher.dispatch(tenant_id="stl", work_order_id=wo["workOrderId"], operation=wo["traveler"]["steps"][0]["operation"], station_id=st["stationId"], actor="op")


def test_scan_and_confirm_tenant_safe(platform):
    wo, rel = _ready_wo(platform, tenant="sc")
    token = make_token("WO", wo["workOrderId"])
    rec = resolve_scan(platform.pilot, token, tenant_id="sc")
    assert rec["objectId"] == wo["workOrderId"]
    with pytest.raises(PermissionError):
        resolve_scan(platform.pilot, token, tenant_id="other")
    with pytest.raises(PermissionError):
        require_confirm({}, action="consume")
    lot_id = (wo.get("lineage") or {}).get("materialLots")[0]
    lot_tok = make_token("LOT", lot_id)
    assert resolve_scan(platform.pilot, lot_tok, tenant_id="sc")["kind"] == "MaterialLot"
    rel_tok = make_token("REL", rel["releaseId"])
    assert resolve_scan(platform.pilot, rel_tok, tenant_id="sc")["releaseHash"] == rel["releaseHash"]


def test_exception_catalog_fail_closed():
    for code, spec in CATALOG.items():
        assert spec["errorCode"] == code
        assert "retrySafe" in spec
        assert "humanRequired" in spec
        assert "allowedNextStates" in spec
        assert spec.get("silentSuccess") is not True
    err = PilotException("MATERIAL_SHORTAGE")
    assert err.silentSuccess is False


def test_versioned_import_export(platform):
    _ready_wo(platform, tenant="ie")
    bundle = platform.pilot.contracts.import_bundle(
        {
            "schemaVersion": "fox3d.receipt.v1",
            "idempotencyKey": "file-1",
            "rows": [
                {"material": "PB_18_WHITE", "quantity": 2, "thickness": 18, "supplierLot": "OK1"},
                {"quantity": 2},
            ],
        },
        tenant_id="ie",
        actor="ops",
        source="IMPORTED",
        idempotency_key="file-1",
    )
    assert bundle["rejectedCount"] == 1
    assert bundle["acceptedCount"] == 1
    again = platform.pilot.contracts.import_bundle(
        {"schemaVersion": "fox3d.receipt.v1", "rows": [{"material": "PB_18_WHITE", "quantity": 2, "thickness": 18, "supplierLot": "OK1"}]},
        tenant_id="ie",
        actor="ops",
        source="IMPORTED",
        idempotency_key="file-1",
    )
    assert again["importId"] == bundle["importId"]
    exported = platform.pilot.contracts.export_bundle(tenant_id="ie")
    assert exported["schemaVersion"] == "fox3d.export.v1"
    assert exported["actuatesMachine"] is False
    assert exported["submitsCarrierBooking"] is False
    assert exported["tenantId"] == "ie"
    adj = platform.pilot.contracts.draft_adjustment({"lotId": bundle["accepted"][0]["lotId"], "quantity": 1, "reason": "count"}, tenant_id="ie", actor="ops")
    assert adj["status"] == "WAITING_HUMAN_APPROVAL"
    with pytest.raises(PermissionError):
        platform.pilot.contracts.approve_adjustment(adj["adjustmentId"], tenant_id="ie", actor="ops", confirm=False)


def test_health_and_operator_api(platform):
    _ready_wo(platform, tenant="hz")
    health = platform.pilot.health(tenant_id="hz")
    assert health["liveCnc"] == "BLOCKED"
    assert health["liveLaser"] == "BLOCKED"
    assert health["notFactorySla"] is True
    view = platform.pilot.operator(tenant_id="hz")
    assert view["tenantId"] == "hz"
    client = TestClient(create_app(platform))
    a = client.get("/api/pilot/health", headers={"X-Tenant-Id": "hz"})
    b = client.get("/api/pilot/health", headers={"X-Tenant-Id": "other"})
    assert a.status_code == 200
    assert b.json()["tenantId"] == "other"
    assert a.json()["workOrdersByState"] != b.json()["workOrdersByState"] or b.json()["queuedManualOperations"] == 0
    denied = client.post("/api/pilot/scan", headers={"X-Tenant-Id": "other"}, json={"token": make_token("WO", platform.pilot.operator(tenant_id="hz")["workOrdersWaiting"][0]["workOrderId"])})
    assert denied.status_code == 403
    no_confirm = client.post(
        f"/api/pilot/work-orders/{platform.pilot.operator(tenant_id='hz')['workOrdersWaiting'][0]['workOrderId']}/consume",
        headers={"X-Tenant-Id": "hz"},
        json={"actor": "api"},
    )
    assert no_confirm.status_code == 403


def test_chaos_fixture_small(platform):
    result = ChaosHarness(platform).run(n_orders=8, tenants=("c-a", "c-b"))
    assert result["label"] == "FIXTURE/CHAOS"
    assert result["noOversell"] is True
    assert result["materialConserved"] is True
    assert result["crashAllOrNothing"] is True
    assert result["staleWriterBlocked"] is True
    assert result["staleReleaseRejected"] is True
    assert result["packingMismatchRejected"] is True
    assert result["journalIntegrity"]["tamperDetected"] is True
    assert result["scanTenantSafe"] is True
    assert result["liveCnc"] is False
    assert result["liveLaser"] is False
    assert result["ok"] is True
    assert result["notFactoryThroughput"] is True
