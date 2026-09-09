"""Phase 421–480 pilot deployment. MOCK/unit/FIXTURE/REAL-logic — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.deploy_chaos import ChaosHarness, isolated_journal_tamper
from fox3d.evidence import prepare_evidence_lineage
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


def test_journal_prepare_fail_leaves_business_unchanged(platform):
    platform.pilot.outbox._fail_prepare = True
    product = platform.kd.build_sku(tenant_id="jf", kind="OPEN_SHELF")
    snap = __import__("fox3d.mfg_release", fromlist=["product_snapshot"]).product_snapshot(product, family="KD_FURNITURE")
    before = len(platform.pilot.releases.releases)
    with pytest.raises(JournalCommitError):
        platform.pilot.releases.create(snap, tenant_id="jf", created_by="eng", idempotency_key="jf-fail")
    assert len(platform.pilot.releases.releases) == before
    assert platform.pilot.outbox.list_open(tenant_id="jf") == []


def test_journal_finalize_fail_blocks_until_reconcile(platform):
    platform.pilot.journal._fail_next = True
    product = platform.kd.build_sku(tenant_id="jz", kind="OPEN_SHELF")
    snap = __import__("fox3d.mfg_release", fromlist=["product_snapshot"]).product_snapshot(product, family="KD_FURNITURE")
    with pytest.raises(JournalCommitError):
        platform.pilot.releases.create(snap, tenant_id="jz", created_by="eng", idempotency_key="jz-fail")
    committed = [e for e in platform.pilot.journal.list("jz") if e.get("eventType") == "release.create" and e.get("commitStatus") == "COMMITTED"]
    assert committed == []
    verify = platform.pilot.journal.verify("jz")
    assert verify["ok"] is False
    assert verify["status"] == "BLOCKED_EVIDENCE"
    platform.pilot._reconcile_startup()
    again = [e for e in platform.pilot.journal.list("jz") if e.get("eventType") == "release.create"]
    assert len(again) == 1
    assert platform.pilot.journal.verify("jz")["ok"] is True


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


def test_lots_prepare_then_business_fail_no_ghost(tmp_path):
    from fox3d.journal import EventJournal
    from fox3d.outbox import CommitOutbox

    root = tmp_path / "lots"
    lots = MaterialLotRegistry(root)
    lots.outbox = CommitOutbox(tmp_path / "tx")
    lots.journal = EventJournal(tmp_path / "journal")
    lots.journal.outbox = lots.outbox
    lot = lots.create(tenant_id="g", material="PB_18_WHITE", thickness=18, sheet_count=4)
    lots._fail_after_prepare = True
    with pytest.raises(JournalCommitError):
        lots.reserve_sheets(lot["lotId"], tenant_id="g", work_order_id="w", quantity=1)
    restarted = MaterialLotRegistry(root)
    q = restarted.quantities(lot["lotId"], tenant_id="g")
    assert q["reserved"] == 0 and q["conserved"]
    committed = [e for e in lots.journal.list("g") if e.get("eventType") == "material.reserve" and e.get("commitStatus") == "COMMITTED"]
    assert committed == []


def test_lots_journal_finalize_fail_then_reconcile(tmp_path):
    from fox3d.journal import EventJournal
    from fox3d.outbox import CommitOutbox
    from fox3d.platform import Platform

    data = tmp_path / "data"
    plat = Platform(root=data, mock_blender=True)
    lot = plat.lots.create(tenant_id="gf", material="PB_18_WHITE", thickness=18, sheet_count=3)
    plat.lots._fail_journal_finalize = True
    with pytest.raises(JournalCommitError):
        plat.lots.reserve_sheets(lot["lotId"], tenant_id="gf", work_order_id="w1", quantity=1)
    assert plat.lots.quantities(lot["lotId"], tenant_id="gf")["reserved"] == 1
    assert plat.pilot.journal.verify("gf")["ok"] is False
    plat2 = Platform(root=data, mock_blender=True)
    q = plat2.lots.quantities(lot["lotId"], tenant_id="gf")
    assert q["reserved"] == 1 and q["conserved"]
    reserved = [e for e in plat2.pilot.journal.list("gf") if e.get("eventType") == "material.reserve"]
    assert len(reserved) == 1
    assert plat2.pilot.journal.verify("gf")["ok"] is True
    plat2.lots.reserve_sheets(lot["lotId"], tenant_id="gf", work_order_id="w1", quantity=1)
    reserved2 = [e for e in plat2.pilot.journal.list("gf") if e.get("eventType") == "material.reserve"]
    assert len(reserved2) == 1


def test_subprocess_crash_after_staging(tmp_path):
    from fox3d.journal import EventJournal
    from fox3d.outbox import CommitOutbox

    root = tmp_path / "lots"
    tx = tmp_path / "tx"
    journal = tmp_path / "journal"
    lots = MaterialLotRegistry(root)
    lots.outbox = CommitOutbox(tx)
    lots.journal = EventJournal(journal)
    lots.journal.outbox = lots.outbox
    lots.create(tenant_id="sc", material="PB_18_WHITE", thickness=18, sheet_count=4)
    env = os.environ.copy()
    env["PYTHONPATH"] = _src() + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "fox3d.inventory",
            "--root",
            str(root),
            "--tenant",
            "sc",
            "--wo",
            "crash-wo",
            "--qty",
            "2",
            "--material",
            "PB_18_WHITE",
            "--thickness",
            "18",
            "--crash",
            "after-staging",
            "--tx",
            str(tx),
            "--journal",
            str(journal),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    restarted = MaterialLotRegistry(root)
    restarted.outbox = CommitOutbox(tx)
    restarted.journal = EventJournal(journal)
    restarted.journal.outbox = restarted.outbox
    lot = restarted.list(tenant_id="sc")[0]
    q = restarted.quantities(lot["lotId"], tenant_id="sc")
    assert q["reserved"] == 0 and q["conserved"]
    restarted.outbox.reconcile(
        journal=restarted.journal,
        business_committed=lambda tx: False,
    )
    committed = [e for e in restarted.journal.list("sc") if e.get("eventType") == "material.reserve"]
    assert committed == []
    q2 = restarted.quantities(lot["lotId"], tenant_id="sc")
    assert q2["sheetCount"] == q2["available"] + q2["reserved"] + q2["consumed"]


def test_subprocess_crash_after_business_reconciles_journal(tmp_path):
    root = tmp_path / "data"
    from fox3d.platform import Platform

    plat = Platform(root=root, mock_blender=True)
    plat.lots.create(tenant_id="ab", material="PB_18_WHITE", thickness=18, sheet_count=4)
    env = os.environ.copy()
    env["PYTHONPATH"] = _src() + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "fox3d.inventory",
            "--root",
            str(root / "lots"),
            "--tenant",
            "ab",
            "--wo",
            "wo-ab",
            "--qty",
            "1",
            "--material",
            "PB_18_WHITE",
            "--thickness",
            "18",
            "--crash",
            "after-business",
            "--tx",
            str(root / "tx"),
            "--journal",
            str(root / "journal"),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    plat2 = Platform(root=root, mock_blender=True)
    lot = plat2.lots.list(tenant_id="ab")[0]
    q = plat2.lots.quantities(lot["lotId"], tenant_id="ab")
    assert q["reserved"] == 1 and q["conserved"]
    reserved = [e for e in plat2.pilot.journal.list("ab") if e.get("eventType") == "material.reserve"]
    assert len(reserved) == 1
    assert plat2.pilot.journal.verify("ab")["ok"] is True


def test_manual_station_process_restart(tmp_path):
    from fox3d.platform import Platform

    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    wo, rel = _ready_wo(plat, tenant="rs")
    op = wo["traveler"]["steps"][0]["operation"]
    st = plat.pilot.stations.register(
        tenant_id="rs",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    lease = plat.pilot.dispatcher.dispatch(tenant_id="rs", work_order_id=wo["workOrderId"], operation=op, station_id=st["stationId"], actor="op")
    plat2 = Platform(root=root, mock_blender=True)
    recovered = plat2.pilot.dispatcher.leases[lease["leaseId"]]
    assert recovered["releaseHash"] == rel["releaseHash"]
    assert recovered["tenantId"] == "rs"
    ack1 = plat2.pilot.dispatcher.ack(lease["leaseId"], tenant_id="rs", actor="op")
    plat3 = Platform(root=root, mock_blender=True)
    ack2 = plat3.pilot.dispatcher.ack(lease["leaseId"], tenant_id="rs", actor="op")
    assert ack1["leaseId"] == ack2["leaseId"]
    started = plat3.pilot.dispatcher.start(lease["leaseId"], tenant_id="rs", actor="op")
    plat4 = Platform(root=root, mock_blender=True)
    done1 = plat4.pilot.dispatcher.complete(lease["leaseId"], tenant_id="rs", actor="op", confirm=True)
    plat5 = Platform(root=root, mock_blender=True)
    done2 = plat5.pilot.dispatcher.complete(lease["leaseId"], tenant_id="rs", actor="op", confirm=True)
    wo5 = plat5.pilot.workorders.get(wo["workOrderId"])
    completed_ops = [o for o in wo5["ops"] if o.get("status") == "COMPLETED" and o.get("operation") == op]
    assert len(completed_ops) == 1
    assert done1["opId"] == done2["opId"] == started["opId"]
    assert wo5["releaseHash"] == rel["releaseHash"]


def test_orphaned_current_lease_cleared_on_restart(tmp_path):
    from fox3d.platform import Platform

    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    st = plat.pilot.stations.register(
        tenant_id="or",
        capabilities=["PANEL_CUTTING_MANUAL"],
        actor="op",
    )
    st["currentLease"] = "missing-lease"
    plat.pilot.stations.persist()
    plat2 = Platform(root=root, mock_blender=True)
    rec = plat2.pilot.stations.get(st["stationId"], tenant_id="or")
    assert rec.get("currentLease") is None
    st2 = plat2.pilot.stations.register(
        tenant_id="or",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    assert st2["stationId"]


def test_expired_lease_across_restart(tmp_path):
    from fox3d.platform import Platform

    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    wo, _rel = _ready_wo(plat, tenant="ex")
    op = wo["traveler"]["steps"][0]["operation"]
    st = plat.pilot.stations.register(
        tenant_id="ex",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    lease = plat.pilot.dispatcher.dispatch(tenant_id="ex", work_order_id=wo["workOrderId"], operation=op, station_id=st["stationId"], actor="op")
    job = plat.queue.get(lease["jobId"])
    job["heartbeatAt"] = "2000-01-01T00:00:00+00:00"
    job["startedAt"] = "2000-01-01T00:00:00+00:00"
    plat.pilot.dispatcher.persist()
    plat2 = Platform(root=root, mock_blender=True)
    expired = plat2.pilot.dispatcher.expire_leases(max_age_seconds=1)
    assert lease["leaseId"] in expired
    st_after = plat2.pilot.stations.get(st["stationId"], tenant_id="ex")
    assert st_after.get("currentLease") is None


def test_cross_tenant_restart_cannot_attach(tmp_path):
    from fox3d.platform import Platform

    root = tmp_path / "data"
    plat = Platform(root=root, mock_blender=True)
    wo, _rel = _ready_wo(plat, tenant="ta")
    op = wo["traveler"]["steps"][0]["operation"]
    st_a = plat.pilot.stations.register(
        tenant_id="ta",
        capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
        actor="op",
    )
    lease = plat.pilot.dispatcher.dispatch(tenant_id="ta", work_order_id=wo["workOrderId"], operation=op, station_id=st_a["stationId"], actor="op")
    st_b = plat.pilot.stations.register(tenant_id="tb", capabilities=["PANEL_CUTTING_MANUAL"], actor="x")
    st_b["currentLease"] = lease["leaseId"]
    plat.pilot.stations.persist()
    plat2 = Platform(root=root, mock_blender=True)
    rec_b = plat2.pilot.stations.get(st_b["stationId"], tenant_id="tb")
    assert rec_b.get("currentLease") != lease["leaseId"]
    with pytest.raises(PermissionError):
        plat2.pilot.dispatcher.ack(lease["leaseId"], tenant_id="tb", actor="x")


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
    assert result["journalHealthyBeforeTamper"] is True
    assert result["tamperDetectionIsolated"] is True
    assert result["journalTamperDetected"] is True
    assert result["sharedJournalHealthyAfterAcceptance"] is True
    assert result["health"]["journalIntegrity"]["ok"] is True
    assert result["health"]["journalIntegrity"]["status"] != "BLOCKED_EVIDENCE"
    assert result["scanTenantSafe"] is True
    assert result["liveCnc"] is False
    assert result["liveLaser"] is False
    assert result["ok"] is True
    assert result["notFactoryThroughput"] is True


def test_isolated_tamper_does_not_break_shared_journal(tmp_path):
    j = EventJournal(tmp_path / "shared")
    j.append("seed", tenant_id="live", aggregate_type="WorkOrder", aggregate_id="w", actor="ops", payload={"k": 1})
    assert j.verify("live")["ok"] is True
    tamper = isolated_journal_tamper(tmp_path / "scratch" / "g1")
    assert tamper["journalHealthyBeforeTamper"] is True
    assert tamper["journalTamperDetected"] is True
    assert tamper["tamperDetectionIsolated"] is True
    assert j.verify("live")["ok"] is True


def test_poisoned_scratch_generation_does_not_poison_next(tmp_path):
    first = isolated_journal_tamper(tmp_path / "scratch" / "gen-old")
    assert first["journalTamperDetected"] is True
    second = isolated_journal_tamper(tmp_path / "scratch" / "gen-new")
    assert second["journalHealthyBeforeTamper"] is True
    assert second["journalTamperDetected"] is True
    shared = EventJournal(tmp_path / "shared-pilot")
    shared.append("ok", tenant_id="t", aggregate_type="Chaos", aggregate_id="c", actor="a", payload={})
    assert shared.verify("t")["ok"] is True


def test_shared_blocked_journal_fails_chaos(platform):
    platform.pilot.journal.append(
        "pre",
        tenant_id="blk-a",
        aggregate_type="Chaos",
        aggregate_id="x",
        actor="t",
        payload={"k": 1},
    )
    platform.pilot.journal.tamper("blk-a", 0, payload={"hacked": True})
    result = ChaosHarness(platform).run(n_orders=4, tenants=("blk-a", "blk-b"))
    assert result["ok"] is False
    assert result["journalHealthyBeforeTamper"] is False
    assert "journalHealthyBeforeTamper" in (result.get("gateFailures") or []) or result["sharedJournalHealthyAfterAcceptance"] is False


def _load_deploy_runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_pilot_deploy_e2e.py"
    spec = importlib.util.spec_from_file_location("run_pilot_deploy_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_pilot_deploy_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _FakePilot:
    def operator(self, *, tenant_id: str) -> dict:
        return {"tenantId": tenant_id, "workOrdersWaiting": [], "stationLeases": [], "exceptions": []}

    def health(self, *, tenant_id: str) -> dict:
        return {
            "journalIntegrity": {"ok": True, "status": "REAL"},
            "liveCnc": "BLOCKED",
            "liveLaser": "BLOCKED",
            "notFactorySla": True,
        }


class _FakePlat:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.mock_blender = True
        self.pilot = _FakePilot()


def _inspect(sha: str, *, clean: bool = True, empty: bool = False):
    def inspect(root, allow_dirty=False):
        if empty:
            return {"evidenceCodeCommit": "", "workingTreeClean": True}
        porcelain = "" if clean else " M src/fox3d/pilot.py\n"
        return prepare_evidence_lineage(head_sha=sha, porcelain=porcelain, allow_dirty=allow_dirty)

    return inspect


def test_deploy_runner_binds_clean_head(tmp_path):
    mod = _load_deploy_runner()
    docs = tmp_path / "docs"
    acc = tmp_path / "acc"
    sha = "a" * 40
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", sha],
        hooks={
            "inspect": _inspect(sha),
            "acceptance_root": acc,
            "platform": _FakePlat,
            "chaos": lambda plat: mod.passing_chaos_stub(),
        },
    )
    assert rc == 0
    deploy = json.loads((docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    operator = json.loads((docs / "OPERATOR_CONTROL_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert deploy["evidenceCodeCommit"] == sha
    assert operator["evidenceCodeCommit"] == sha
    assert deploy["workingTreeClean"] is True
    assert operator["workingTreeClean"] is True
    assert deploy["acceptanceGenerationId"] == operator["acceptanceGenerationId"]
    assert deploy["ok"] is True


def test_deploy_runner_mismatch_does_not_overwrite(tmp_path):
    mod = _load_deploy_runner()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", "b" * 40],
        hooks={"inspect": _inspect("a" * 40), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "chaos": lambda plat: mod.passing_chaos_stub()},
    )
    assert rc == 1
    prev = json.loads((docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert prev.get("keep") is True


def test_deploy_runner_dirty_does_not_overwrite(tmp_path):
    mod = _load_deploy_runner()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", "a" * 40],
        hooks={"inspect": _inspect("a" * 40, clean=False), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "chaos": lambda plat: mod.passing_chaos_stub()},
    )
    assert rc == 1
    prev = json.loads((docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert prev.get("keep") is True


def test_deploy_runner_missing_lineage(tmp_path):
    mod = _load_deploy_runner()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")
    rc = mod.main(
        ["--docs-root", str(docs)],
        hooks={"inspect": _inspect("", empty=True), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "chaos": lambda plat: mod.passing_chaos_stub()},
    )
    assert rc == 1
    prev = json.loads((docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert prev.get("keep") is True


def test_consecutive_chaos_fresh_roots(tmp_path):
    from fox3d.platform import Platform

    a = ChaosHarness(Platform(root=tmp_path / "g1", mock_blender=True)).run(n_orders=4, tenants=("a1", "b1"))
    b = ChaosHarness(Platform(root=tmp_path / "g2", mock_blender=True)).run(n_orders=4, tenants=("a2", "b2"))
    assert a["ok"] is True
    assert b["ok"] is True
    assert a["sharedJournalHealthyAfterAcceptance"] is True
    assert b["sharedJournalHealthyAfterAcceptance"] is True
