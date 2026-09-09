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
    raise SystemExit(f"unknown action {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())
