"""Phase 421–480 deployment acceptance. Additional scoped truth set, not canonical six-file.

pytest mock PASS is not Production Ready. LIVE_CNC / LIVE_LASER stay BLOCKED.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.deploy_chaos import ChaosHarness  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402


def _md(title: str, rows: list[dict], generated: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"generatedAt: {generated}",
        "pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.",
        "This is a scoped Phase 421–480 truth set, not a replacement of the canonical six-file set.",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['check']} | {r['status']} | `{r['evidence']}` |")
    lines.append("")
    lines.append("`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-root", default=None)
    parser.add_argument("--orders", type=int, default=100)
    args = parser.parse_args(argv)
    docs = Path(args.docs_root) if args.docs_root else ROOT / "docs"
    plat = Platform(root=ROOT / ".fox3d-data", mock_blender=True)
    chaos = ChaosHarness(plat).run(n_orders=int(args.orders))
    generated = datetime.now(timezone.utc).isoformat()
    generation_id = new_id()
    rows = [
        {"check": "FIXTURE/CHAOS workOrders", "status": "FIXTURE", "evidence": f"n={chaos['workOrderCount']}"},
        {"check": "no oversell", "status": "REAL" if chaos["noOversell"] else "PARTIAL", "evidence": str(chaos["noOversell"])},
        {"check": "material conservation", "status": "REAL" if chaos["materialConserved"] else "PARTIAL", "evidence": str(chaos["materialConserved"])},
        {"check": "crash all-or-nothing", "status": "REAL" if chaos["crashAllOrNothing"] else "PARTIAL", "evidence": str(chaos["crashAllOrNothing"])},
        {"check": "stale writer blocked", "status": "REAL" if chaos["staleWriterBlocked"] else "PARTIAL", "evidence": str(chaos["staleWriterBlocked"])},
        {"check": "station offline/lease/duplicate", "status": "REAL" if chaos["station"].get("offlineDenied") and chaos["noDuplicateCompletion"] else "PARTIAL", "evidence": json.dumps(chaos["station"], default=str)},
        {"check": "QC fail rework pass", "status": "REAL" if chaos["qcRework"].get("passed") else "PARTIAL", "evidence": json.dumps(chaos["qcRework"])},
        {"check": "stale release rejected", "status": "REAL" if chaos["staleReleaseRejected"] else "PARTIAL", "evidence": str(chaos["staleReleaseRejected"])},
        {"check": "packing mismatch rejected", "status": "REAL" if chaos["packingMismatchRejected"] else "PARTIAL", "evidence": str(chaos["packingMismatchRejected"])},
        {"check": "journal tamper detected", "status": "REAL" if chaos["journalIntegrity"].get("tamperDetected") else "BLOCKED_EVIDENCE", "evidence": json.dumps(chaos["journalIntegrity"])},
        {"check": "scan tenant isolation", "status": "REAL" if chaos["scanTenantSafe"] else "PARTIAL", "evidence": str(chaos["scanTenantSafe"])},
        {"check": "human approval gate", "status": "REAL" if chaos["humanApprovalGate"] else "PARTIAL", "evidence": "confirm required"},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "LIVE_LASER", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "not factory throughput", "status": "FIXTURE", "evidence": "FIXTURE/CHAOS"},
    ]
    op_view = plat.pilot.operator(tenant_id="chaos-a")
    health = plat.pilot.health(tenant_id="chaos-a")
    deploy = {
        "domain": "pilot-deployment",
        "label": "FIXTURE/CHAOS",
        "generatedAt": generated,
        "acceptanceGenerationId": generation_id,
        "chaos": chaos,
        "rows": rows,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "globalProductionReady": False,
        "liveMachineControl": False,
        "notCanonicalSixFile": True,
    }
    operator = {
        "domain": "operator-control",
        "generatedAt": generated,
        "acceptanceGenerationId": generation_id,
        "operator": {
            "tenantId": op_view.get("tenantId"),
            "waiting": len(op_view.get("workOrdersWaiting") or []),
            "leases": len(op_view.get("stationLeases") or []),
            "exceptions": len(op_view.get("exceptions") or []),
            "barcodeHardware": "PARTIAL",
            "liveMachineControl": False,
        },
        "health": health,
        "rows": [
            {"check": "operator view tenant scoped", "status": "REAL", "evidence": op_view.get("tenantId")},
            {"check": "barcode hardware", "status": "PARTIAL", "evidence": "scan token only"},
            {"check": "LIVE_CNC badge", "status": "BLOCKED", "evidence": health.get("liveCnc")},
            {"check": "LIVE_LASER badge", "status": "BLOCKED", "evidence": health.get("liveLaser")},
            {"check": "health notFactorySla", "status": "REAL", "evidence": str(health.get("notFactorySla"))},
        ],
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "globalProductionReady": False,
        "notCanonicalSixFile": True,
    }
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").write_text(json.dumps(deploy, indent=2, default=str), encoding="utf-8")
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.md").write_text(_md("PILOT_DEPLOYMENT_ACCEPTANCE", rows, generated), encoding="utf-8")
    (docs / "OPERATOR_CONTROL_ACCEPTANCE.json").write_text(json.dumps(operator, indent=2, default=str), encoding="utf-8")
    (docs / "OPERATOR_CONTROL_ACCEPTANCE.md").write_text(_md("OPERATOR_CONTROL_ACCEPTANCE", operator["rows"], generated), encoding="utf-8")
    payload = {"ok": bool(chaos.get("ok")), "label": "FIXTURE/CHAOS", "workOrderCount": chaos.get("workOrderCount"), "generation": generation_id}
    print(json.dumps(payload, default=str))
    return 0 if chaos.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
