"""Separate-process crash/restart fixtures. FIXTURE/REAL-LOGIC, not factory throughput."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fox3d.platform import Platform
from fox3d.workorder import STRICT_STOCK


def _plat(root: Path) -> Platform:
    return Platform(root=root, mock_blender=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--action", required=True)
    p.add_argument("--tenant", default="crash")
    p.add_argument("--wo", default="")
    p.add_argument("--qty", type=int, default=2)
    p.add_argument("--material", default="CRASH_MAT")
    p.add_argument("--crash", default="")
    p.add_argument("--station", default="")
    p.add_argument("--lease", default="")
    p.add_argument("--unit", default="")
    p.add_argument("--operator", default="")
    p.add_argument("--shift", default="")
    args = p.parse_args(argv)
    root = Path(args.root)
    plat = _plat(root)
    lots = plat.lots
    if args.crash:
        lots._crash_mode = args.crash
        lots._hard_crash = True
    if args.action == "reserve":
        items = lots.allocate_requirement(
            tenant_id=args.tenant,
            work_order_id=args.wo or "crash-wo",
            quantity=int(args.qty),
            material=args.material,
            thickness=18,
        )
        print(json.dumps({"ok": True, "qty": sum(int(i["quantity"]) for i in items)}))
        return 0
    if args.action == "ack":
        rec = plat.pilot.dispatcher.ack(args.lease, tenant_id=args.tenant, actor="op")
        if args.crash == "after-ack":
            os._exit(1)
        print(json.dumps({"ok": True, "leaseId": rec["leaseId"]}))
        return 0
    if args.action == "start":
        rec = plat.pilot.dispatcher.start(args.lease, tenant_id=args.tenant, actor="op")
        if args.crash == "after-start":
            os._exit(1)
        print(json.dumps({"ok": True, "leaseId": rec["leaseId"], "opId": rec.get("opId")}))
        return 0
    if args.action == "proto-consume":
        pf = plat.prototype
        pf._crash_mode = args.crash
        pf._hard_crash = bool(args.crash)
        rec = pf.consume_material_once(
            args.unit,
            tenant_id=args.tenant,
            sheets=int(args.qty),
            operator_id=args.operator,
            shift_id=args.shift,
            consumes_inventory=True,
        )
        print(json.dumps({"ok": True, "consumed": rec.get("consumedSheets"), "lineage": rec.get("inventoryLineage")}))
        return 0
    if args.action == "proto-package-create":
        pf = plat.prototype
        pf._crash_mode = args.crash
        pf._hard_crash = bool(args.crash)
        rec = pf.create_evidence_package(
            args.unit,
            tenant_id=args.tenant,
            operator_id=args.operator,
            shift_id=args.shift,
            source="MANUAL",
        )
        print(json.dumps({"ok": True, "evidencePackageId": rec.get("evidencePackageId"), "state": rec.get("state")}))
        return 0
    if args.action == "proto-package-finalize":
        pf = plat.prototype
        pf._crash_mode = args.crash
        pf._hard_crash = bool(args.crash)
        rec = pf.finalize_evidence_package(
            args.wo,
            tenant_id=args.tenant,
            operator_id=args.operator,
            shift_id=args.shift,
        )
        print(json.dumps({"ok": True, "evidencePackageId": rec.get("evidencePackageId"), "state": rec.get("state")}))
        return 0
    if args.action == "proto-launch-go":
        pf = plat.prototype
        pf._crash_mode = args.crash
        pf._hard_crash = bool(args.crash)
        rec = pf.record_launch_decision(
            args.wo,
            tenant_id=args.tenant,
            operator_id=args.operator,
            shift_id=args.shift,
            decision="HUMAN_GO",
            reason="crash-go",
        )
        print(json.dumps({"ok": True, "launchDecisionId": rec.get("launchDecisionId"), "decision": rec.get("decision")}))
        return 0
    if args.action == "proto-pilot-plan":
        pf = plat.prototype
        pf._crash_mode = args.crash
        pf._hard_crash = bool(args.crash)
        rec = pf.create_pilot_plan(
            args.wo,
            tenant_id=args.tenant,
            operator_id=args.operator,
            shift_id=args.shift,
            reason="crash-plan",
            quantity=1,
        )
        print(json.dumps({"ok": True, "planId": rec.get("planId"), "releaseId": rec.get("releaseId"), "workOrderId": rec.get("workOrderId")}))
        return 0
    raise SystemExit(f"unknown action {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())
