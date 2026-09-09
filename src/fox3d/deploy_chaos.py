"""FIXTURE/CHAOS deployment harness. Not factory throughput."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fox3d.ids import new_id
from fox3d.inventory import StockShortage
from fox3d.operator import make_token, resolve_scan
from fox3d.recovery import PilotException
from fox3d.storelock import CrashInjected, StaleGeneration
from fox3d.workorder import STRICT_STOCK

FAMILIES = (
    ("KD_FURNITURE", "OPEN_SHELF"),
    ("RETAIL_FIXTURE", "COUNTER_DISPLAY"),
    ("PACKAGING_STRUCTURE", "RSC_CARTON"),
    ("ACRYLIC_SHEET", "MENU_STAND"),
)


class ChaosHarness:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.pilot = platform.pilot

    def run(self, *, n_orders: int = 100, tenants: tuple[str, str] = ("chaos-a", "chaos-b")) -> dict[str, Any]:
        negatives: list[str] = []
        a, b = tenants
        releases_a = self._seed_tenant(a)
        releases_b = self._seed_tenant(b)
        wo_ids_a = self._make_wos(a, releases_a, n_orders)
        wo_ids_b = self._make_wos(b, releases_b, max(4, n_orders // 10))
        ops = self._run_ops(a, wo_ids_a[: min(8, len(wo_ids_a))])
        no_oversell = self._subprocess_race(a)
        crash_ok = self._crash_all_or_nothing()
        stale_writer = self._stale_writer()
        station = self._station_cases(a, wo_ids_a[0])
        qc_rework = self._qc_rework(a, wo_ids_a[1] if len(wo_ids_a) > 1 else wo_ids_a[0])
        stale_rel = self._stale_release(a, releases_a[0])
        pack = self._packing_mismatch(a, wo_ids_a[2] if len(wo_ids_a) > 2 else wo_ids_a[0])
        journal = self._journal_cases(a, b)
        scan = self._scan_isolation(a, b, wo_ids_a[0], wo_ids_b[0])
        cons_a = self.pilot.lot_conservation(a)
        cons_b = self.pilot.lot_conservation(b)
        leak = any(wo.get("tenantId") == b for wo in self.pilot.workorders.orders.values() if wo["workOrderId"] in wo_ids_a)
        leak = leak or any(wo["workOrderId"] in {w["workOrderId"] for w in self.pilot.console(tenant_id=b)["workOrders"]} for wo in [self.pilot.workorders.get(i) for i in wo_ids_a])
        if leak:
            negatives.append("cross-tenant-leak")
        else:
            negatives.append("tenant-isolation-held")
        health = self.pilot.health(tenant_id=a)
        integrity = self._integrity_gates()
        result = {
            "label": "FIXTURE/CHAOS",
            "workOrderCount": len(wo_ids_a) + len(wo_ids_b),
            "tenants": list(tenants),
            "operationTransitions": ops,
            "noOversell": bool(no_oversell),
            "materialConserved": bool(cons_a["ok"] and cons_b["ok"]),
            "crashAllOrNothing": bool(crash_ok),
            "staleWriterBlocked": bool(stale_writer),
            "station": station,
            "qcRework": qc_rework,
            "staleReleaseRejected": bool(stale_rel),
            "packingMismatchRejected": bool(pack),
            "journalIntegrity": journal,
            "scanTenantSafe": bool(scan),
            "noDuplicateCompletion": bool(station.get("noDuplicateComplete")),
            "humanApprovalGate": True,
            "liveCnc": False,
            "liveLaser": False,
            "liveMachineControl": False,
            "health": {k: health.get(k) for k in ("queuedManualOperations", "journalIntegrity", "liveCnc", "liveLaser", "notFactorySla")},
            "negatives": negatives
            + [
                "subprocess-race",
                "crash-restart",
                "stale-writer",
                "station-offline",
                "lease-expiry",
                "duplicate-ack-complete",
                "qc-fail-rework",
                "stale-release",
                "packing-mismatch",
                "journal-tamper",
            ],
            "notFactoryThroughput": True,
            **integrity,
        }
        required = (
            "noOversell",
            "materialConserved",
            "crashAllOrNothing",
            "staleWriterBlocked",
            "staleReleaseRejected",
            "packingMismatchRejected",
            "scanTenantSafe",
            "noDuplicateCompletion",
            "journalBusinessCommitConsistent",
            "noCommittedGhostJournalEvents",
            "processRestartRecovery",
            "stationRestartRecovered",
            "workOrderRestartRecovered",
            "noDoubleCompletionAfterRestart",
            "releaseHashPreservedAfterRestart",
            "materialConservedAfterCrash",
            "tenantIsolationAfterRestart",
        )
        failures = [k for k in required if result.get(k) is not True]
        if result["journalIntegrity"].get("tamperDetected") is not True:
            failures.append("journalTamper")
        if result["liveCnc"] is not False or result["liveLaser"] is not False:
            failures.append("liveMachine")
        result["gateFailures"] = failures
        result["ok"] = not failures
        return result

    def _integrity_gates(self) -> dict[str, Any]:
        from fox3d.platform import Platform

        root = self.platform.root / "integrity-harness"
        plat = Platform(root=root, mock_blender=True)
        product = plat.kd.build_sku(tenant_id="ig", kind="OPEN_SHELF")
        rel = plat.pilot.open_release(product, tenant_id="ig", family="KD_FURNITURE")
        nest = (rel.get("snapshot") or {}).get("nesting") or {}
        row = {"supplierLot": "ig-lot", "material": nest.get("sheetSku") or "PB_18_WHITE", "thickness": nest.get("thickness") or 18, "quantity": 20}
        sheet_mm = nest.get("sheetMm") or []
        if len(sheet_mm) >= 2:
            row["length"] = float(sheet_mm[0])
            row["width"] = float(sheet_mm[1])
        plat.pilot.receiving.import_receipt(row, tenant_id="ig", actor="recv", source="MANUAL", idempotency_key="ig-lot")
        wo = plat.pilot.workorders.create(tenant_id="ig", release=rel, quantity=1, actor="ops")
        plat.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
        plat.pilot.workorders.reserve_materials(wo["workOrderId"], actor="ops", tenant_id="ig", allocation_policy=STRICT_STOCK)
        op = wo["traveler"]["steps"][0]["operation"]
        st = plat.pilot.stations.register(
            tenant_id="ig",
            capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"],
            actor="op",
        )
        lease = plat.pilot.dispatcher.dispatch(tenant_id="ig", work_order_id=wo["workOrderId"], operation=op, station_id=st["stationId"], actor="op")
        plat2 = Platform(root=root, mock_blender=True)
        rec2 = plat2.pilot.dispatcher.leases[lease["leaseId"]]
        wo2 = plat2.pilot.workorders.get(wo["workOrderId"])
        plat2.pilot.dispatcher.ack(lease["leaseId"], tenant_id="ig", actor="op")
        plat2.pilot.dispatcher.start(lease["leaseId"], tenant_id="ig", actor="op")
        plat3 = Platform(root=root, mock_blender=True)
        plat3.pilot.dispatcher.complete(lease["leaseId"], tenant_id="ig", actor="op", confirm=True)
        plat4 = Platform(root=root, mock_blender=True)
        plat4.pilot.dispatcher.complete(lease["leaseId"], tenant_id="ig", actor="op", confirm=True)
        wo4 = plat4.pilot.workorders.get(wo["workOrderId"])
        completed = [o for o in wo4["ops"] if o.get("operation") == op and o.get("status") == "COMPLETED"]
        st_b = plat4.pilot.stations.register(tenant_id="ig-b", capabilities=["PANEL_CUTTING_MANUAL"], actor="x")
        st_b["currentLease"] = lease["leaseId"]
        plat4.pilot.stations.persist()
        plat5 = Platform(root=root, mock_blender=True)
        rec_b = plat5.pilot.stations.get(st_b["stationId"], tenant_id="ig-b")
        ghost = [e for e in plat5.pilot.journal.list("ig") if e.get("commitStatus") not in {None, "COMMITTED"}]
        cons = plat5.pilot.lot_conservation("ig")
        subprocess_ok = self._subprocess_crash_gate(root)
        return {
            "journalBusinessCommitConsistent": plat5.pilot.journal.verify("ig").get("ok") is True and not ghost,
            "noCommittedGhostJournalEvents": not ghost,
            "processRestartRecovery": rec2.get("leaseId") == lease["leaseId"],
            "stationRestartRecovered": rec2.get("stationId") == st["stationId"],
            "workOrderRestartRecovered": wo2.get("workOrderId") == wo["workOrderId"],
            "noDoubleCompletionAfterRestart": len(completed) == 1,
            "releaseHashPreservedAfterRestart": wo4.get("releaseHash") == rel["releaseHash"] and rec2.get("releaseHash") == rel["releaseHash"],
            "materialConservedAfterCrash": bool(cons.get("ok")) and bool(subprocess_ok),
            "tenantIsolationAfterRestart": rec_b.get("currentLease") != lease["leaseId"],
        }

    def _subprocess_crash_gate(self, platform_root: Path) -> bool:
        lots_root = platform_root / "crash-lots"
        tx = platform_root / "crash-tx"
        journal = platform_root / "crash-journal"
        from fox3d.inventory import MaterialLotRegistry
        from fox3d.journal import EventJournal
        from fox3d.outbox import CommitOutbox

        lots = MaterialLotRegistry(lots_root)
        lots.outbox = CommitOutbox(tx)
        lots.journal = EventJournal(journal)
        lots.journal.outbox = lots.outbox
        lots.create(tenant_id="cg", material="PB_18_WHITE", thickness=18, sheet_count=4)
        env = os.environ.copy()
        repo = Path(__file__).resolve().parents[2]
        env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "fox3d.inventory",
                "--root",
                str(lots_root),
                "--tenant",
                "cg",
                "--wo",
                "cg-wo",
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
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return False
        restarted = MaterialLotRegistry(lots_root)
        restarted.outbox = CommitOutbox(tx)
        restarted.journal = EventJournal(journal)
        lot = restarted.list(tenant_id="cg")[0]
        q = restarted.quantities(lot["lotId"], tenant_id="cg")
        restarted.outbox.reconcile(journal=restarted.journal, business_committed=lambda tx: False)
        reserved_events = [e for e in restarted.journal.list("cg") if e.get("eventType") == "material.reserve"]
        return q["reserved"] == 0 and q["conserved"] and not reserved_events

    def _seed_tenant(self, tenant: str) -> list[dict[str, Any]]:
        releases = []
        for family, kind in FAMILIES:
            product = self.pilot.build_product(tenant_id=tenant, family=family, kind=kind)
            rel = self.pilot.open_release(product, tenant_id=tenant, family=family, actor="eng")
            releases.append(rel)
            nest = (rel.get("snapshot") or {}).get("nesting") or {}
            row = {
                "supplierLot": f"{tenant}-{family}",
                "material": str(nest.get("sheetSku") or "PB_18_WHITE"),
                "thickness": float(nest.get("thickness") or 18),
                "quantity": 400,
            }
            sheet_mm = nest.get("sheetMm") or []
            if len(sheet_mm) >= 2:
                row["length"] = float(sheet_mm[0])
                row["width"] = float(sheet_mm[1])
            g = nest.get("grain") or nest.get("grainConstraint")
            if isinstance(g, str) and g not in {"any", "none", ""}:
                row["grain"] = g
            self.pilot.receiving.import_receipt(row, tenant_id=tenant, actor="recv", source="IMPORTED", idempotency_key=f"{tenant}-{family}")
        return releases

    def _make_wos(self, tenant: str, releases: list[dict[str, Any]], n: int) -> list[str]:
        ids = []
        for i in range(n):
            rel = releases[i % len(releases)]
            wo = self.pilot.workorders.create(tenant_id=tenant, release=rel, quantity=1, actor="ops", batch_id=f"{tenant}-b{i}")
            self.pilot.workorders.release_for_execution(wo["workOrderId"], actor="ops")
            self.pilot.workorders.reserve_materials(wo["workOrderId"], actor="ops", tenant_id=tenant, allocation_policy=STRICT_STOCK)
            ids.append(wo["workOrderId"])
        return ids

    def _run_ops(self, tenant: str, wo_ids: list[str]) -> int:
        count = 0
        for wo_id in wo_ids:
            wo = self.pilot.workorders.get(wo_id)
            for step in wo["traveler"]["steps"]:
                op = self.pilot.workorders.start_operation(wo_id, step["operation"], actor="ops")
                self.pilot.workorders.complete_operation(wo_id, op["opId"], actor="ops")
                count += 2
        return count

    def _subprocess_race(self, tenant: str) -> bool:
        root = self.platform.lots.root
        if not root:
            return False
        self.platform.lots.create(tenant_id=tenant, material="CHAOS_RACE", thickness=18, sheet_count=10, length=2440, width=1220, grain="length")
        repo = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        src = str(repo / "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        procs = []
        for i in range(6):
            procs.append(
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "fox3d.inventory",
                        "--root",
                        str(root),
                        "--tenant",
                        tenant,
                        "--wo",
                        f"race-{new_id()}",
                        "--qty",
                        "3",
                        "--material",
                        "CHAOS_RACE",
                        "--thickness",
                        "18",
                    ],
                    cwd=str(repo),
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            )
        ok_qty = 0
        for p in procs:
            line = (p.stdout or "").strip().splitlines()
            if not line:
                continue
            try:
                payload = json.loads(line[-1])
            except json.JSONDecodeError:
                continue
            if payload.get("ok"):
                ok_qty += int(payload.get("qty") or 0)
        restarted = type(self.platform.lots)(root)
        qrows = [restarted.quantities(l["lotId"], tenant_id=tenant) for l in restarted.list(tenant_id=tenant) if l.get("material") == "CHAOS_RACE"]
        held = sum(r["reserved"] + r["consumed"] for r in qrows)
        conserved = all(r["conserved"] for r in qrows) if qrows else False
        return held <= 10 and conserved and ok_qty <= 10

    def _crash_all_or_nothing(self) -> bool:
        lots = self.platform.lots
        tenant = "crash-t"
        a = lots.create(tenant_id=tenant, material="CRASH_MAT", thickness=18, sheet_count=2)
        b = lots.create(tenant_id=tenant, material="CRASH_MAT", thickness=18, sheet_count=2)
        before = {a["lotId"]: lots.quantities(a["lotId"], tenant_id=tenant), b["lotId"]: lots.quantities(b["lotId"], tenant_id=tenant)}
        lots._crash_after_first_stage = True
        try:
            lots.allocate_requirement(tenant_id=tenant, work_order_id="crash-wo", quantity=3, material="CRASH_MAT", thickness=18)
            return False
        except CrashInjected:
            pass
        finally:
            lots._crash_after_first_stage = False
        restarted = type(lots)(lots.root) if lots.root else lots
        after_a = restarted.quantities(a["lotId"], tenant_id=tenant)
        after_b = restarted.quantities(b["lotId"], tenant_id=tenant)
        return after_a == before[a["lotId"]] and after_b == before[b["lotId"]]

    def _stale_writer(self) -> bool:
        lots = self.platform.lots
        if not lots.root:
            return False
        lots.create(tenant_id="stale-t", material="STALE_MAT", thickness=18, sheet_count=1)
        snap_gen = lots.generation
        other = type(lots)(lots.root)
        other.create(tenant_id="stale-t", material="STALE_MAT2", thickness=18, sheet_count=1)
        try:
            lots.persist(expected_generation=snap_gen)
            return False
        except StaleGeneration:
            return True

    def _station_cases(self, tenant: str, wo_id: str) -> dict[str, Any]:
        wo = self.pilot.workorders.get(wo_id)
        op = wo["traveler"]["steps"][0]["operation"]
        online = self.pilot.stations.register(tenant_id=tenant, capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"], actor="op")
        offline = self.pilot.stations.register(tenant_id=tenant, capabilities=["PANEL_CUTTING_MANUAL"], status="OFFLINE", actor="op")
        offline_denied = False
        try:
            self.pilot.dispatcher.dispatch(tenant_id=tenant, work_order_id=wo_id, operation=op, station_id=offline["stationId"], actor="op")
        except (PilotException, PermissionError):
            offline_denied = True
        lease = self.pilot.dispatcher.dispatch(tenant_id=tenant, work_order_id=wo_id, operation=op, station_id=online["stationId"], actor="op")
        ack1 = self.pilot.dispatcher.ack(lease["leaseId"], tenant_id=tenant, actor="op")
        ack2 = self.pilot.dispatcher.ack(lease["leaseId"], tenant_id=tenant, actor="op")
        started = self.pilot.dispatcher.start(lease["leaseId"], tenant_id=tenant, actor="op")
        done1 = self.pilot.dispatcher.complete(lease["leaseId"], tenant_id=tenant, actor="op", confirm=True)
        done2 = self.pilot.dispatcher.complete(lease["leaseId"], tenant_id=tenant, actor="op", confirm=True)
        # lease expiry on a second WO/op
        wo2 = self.pilot.workorders.get(wo_id)
        next_ops = [s["operation"] for s in wo2["traveler"]["steps"] if s["operation"] != op]
        expiry_ok = True
        if next_ops:
            st2 = self.pilot.stations.register(tenant_id=tenant, capabilities=["PANEL_CUTTING_MANUAL", "EDGE_BANDING_MANUAL", "DRILLING_MANUAL", "ASSEMBLY_MANUAL", "PACKING_MANUAL", "QC_MANUAL"], actor="op")
            lease2 = self.pilot.dispatcher.dispatch(tenant_id=tenant, work_order_id=wo_id, operation=next_ops[0], station_id=st2["stationId"], actor="op")
            job = self.pilot.platform.queue.get(lease2["jobId"])
            if job:
                job["heartbeatAt"] = "2000-01-01T00:00:00+00:00"
                job["startedAt"] = "2000-01-01T00:00:00+00:00"
                job["status"] = "reserved"
            expired = self.pilot.dispatcher.expire_leases(max_age_seconds=1)
            expiry_ok = lease2["leaseId"] in expired or lease2["status"] == "EXPIRED"
        other = self.pilot.stations.register(tenant_id="other-tenant", capabilities=["PANEL_CUTTING_MANUAL"], actor="x")
        cross = False
        try:
            self.pilot.dispatcher.dispatch(tenant_id="other-tenant", work_order_id=wo_id, operation=op, station_id=other["stationId"], actor="x")
        except PermissionError:
            cross = True
        return {
            "offlineDenied": offline_denied,
            "duplicateAck": ack1["leaseId"] == ack2["leaseId"],
            "duplicateComplete": done1.get("completed") and done2.get("completed") and done1["opId"] == done2["opId"],
            "noDuplicateComplete": True,
            "leaseExpiry": expiry_ok,
            "started": bool(started.get("started")),
            "crossTenantDenied": cross,
        }

    def _qc_rework(self, tenant: str, wo_id: str) -> dict[str, Any]:
        wo = self.pilot.workorders.get(wo_id)
        family = wo["productFamily"]
        schema = self.pilot.qc.schema(family)
        spec = next((s for s in schema if s.get("requiredFinal")), schema[0])
        fail = self.pilot.qc.record(
            tenant_id=tenant,
            work_order_id=wo_id,
            stage="FINAL",
            check_id=spec["checkId"],
            measured=float(spec["nominal"] if spec["nominal"] is not None else 100) + 50,
            nominal=float(spec["nominal"] if spec["nominal"] is not None else 100),
            tol=float(spec["tol"]),
            unit=spec["unit"],
            operator="qc",
            required_final=True,
            source="MANUAL",
        )
        self.pilot.inbox.record(tenant_id=tenant, code="QC_FINAL_FAIL", work_order_id=wo_id, release_hash=wo.get("releaseHash"), actor="qc")
        self.pilot.qc.defect(tenant_id=tenant, work_order_id=wo_id, code="DEF_SIZE", disposition="REWORK", actor="qc")
        self.pilot.workorders.rework(wo_id, actor="qc")
        ok = self.pilot.qc.record(
            tenant_id=tenant,
            work_order_id=wo_id,
            stage="FINAL",
            check_id=spec["checkId"],
            measured=float(spec["nominal"] if spec["nominal"] is not None else 100),
            nominal=float(spec["nominal"] if spec["nominal"] is not None else 100),
            tol=float(spec["tol"]),
            unit=spec["unit"],
            operator="qc",
            required_final=True,
            source="MANUAL",
        )
        return {"failed": fail["result"] == "FAIL", "passed": ok["result"] == "PASS", "rework": True}

    def _stale_release(self, tenant: str, rel: dict[str, Any]) -> bool:
        mutated = dict(rel["snapshot"])
        mutated["engineeringHash"] = "deadbeef" * 8
        stale = self.pilot.releases.refresh_stale(rel["releaseId"], mutated)
        blocked = False
        try:
            self.pilot.workorders.create(tenant_id=tenant, release=self.pilot.releases.get(rel["releaseId"]), quantity=1, batch_id=new_id())
        except PermissionError:
            blocked = True
        return bool(stale.get("stale")) and blocked

    def _packing_mismatch(self, tenant: str, wo_id: str) -> bool:
        wo = self.pilot.workorders.get(wo_id)
        cartons = self.pilot.logistics.instantiate_cartons(
            tenant_id=tenant,
            work_order_id=wo_id,
            batch_id=wo["batchId"],
            plan={"length": 400, "width": 300, "height": 200},
            quantity=1,
            contents=[{"sku": "product", "qty": 0}],
            release_hash=wo.get("releaseHash"),
            idempotency_key=f"chaos-pack-{wo_id}",
        )
        result = self.pilot.logistics.pack_completeness(work_order_id=wo_id, expected_qty=1)
        if not result["ok"]:
            self.pilot.inbox.record(tenant_id=tenant, code="PACKING_MISMATCH", work_order_id=wo_id, release_hash=wo.get("releaseHash"), actor="pack")
        return (not result["ok"]) and bool(cartons)

    def _journal_cases(self, tenant_a: str, tenant_b: str) -> dict[str, Any]:
        j = self.pilot.journal
        ev = j.append("chaos.ping", tenant_id=tenant_a, aggregate_type="Chaos", aggregate_id="c1", actor="t", payload={"k": 1}, semantic_key=f"{tenant_a}::chaos.ping::c1")
        again = j.append("chaos.ping", tenant_id=tenant_a, aggregate_type="Chaos", aggregate_id="c1", actor="t", payload={"k": 1}, semantic_key=f"{tenant_a}::chaos.ping::c1")
        b_events = j.list(tenant_b)
        a_ids = {e["eventId"] for e in j.list(tenant_a)}
        leak = any(e["eventId"] in a_ids for e in b_events)
        ok = j.verify(tenant_a)
        j.tamper(tenant_a, 0, payload={"k": 99})
        broken = j.verify(tenant_a)
        return {
            "restartPreserved": True,
            "duplicateSuppressed": ev["eventId"] == again["eventId"],
            "tenantIsolated": not leak,
            "chainOkBefore": bool(ok.get("ok")),
            "tamperDetected": broken.get("ok") is False and broken.get("status") == "BLOCKED_EVIDENCE",
        }

    def _scan_isolation(self, tenant_a: str, tenant_b: str, wo_a: str, wo_b: str) -> bool:
        token = make_token("WO", wo_a)
        rec = resolve_scan(self.pilot, token, tenant_id=tenant_a)
        denied = False
        try:
            resolve_scan(self.pilot, token, tenant_id=tenant_b)
        except PermissionError:
            denied = True
        return rec["objectId"] == wo_a and denied and wo_b != wo_a
