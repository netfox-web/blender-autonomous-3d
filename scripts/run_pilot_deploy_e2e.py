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
    def _fix(ok: bool) -> str:
        return "FIXTURE" if ok else "PARTIAL"

    def _logic(ok: bool) -> str:
        return "REAL_LOGIC" if ok else "PARTIAL"

    required = {
        "journalBusinessCommitConsistent": chaos.get("journalBusinessCommitConsistent"),
        "noCommittedGhostJournalEvents": chaos.get("noCommittedGhostJournalEvents"),
        "processRestartRecovery": chaos.get("processRestartRecovery"),
        "stationRestartRecovered": chaos.get("stationRestartRecovered"),
        "workOrderRestartRecovered": chaos.get("workOrderRestartRecovered"),
        "noDoubleCompletionAfterRestart": chaos.get("noDoubleCompletionAfterRestart"),
        "releaseHashPreservedAfterRestart": chaos.get("releaseHashPreservedAfterRestart"),
        "materialConservedAfterCrash": chaos.get("materialConservedAfterCrash"),
        "tenantIsolationAfterRestart": chaos.get("tenantIsolationAfterRestart"),
    }
    missing = [k for k, v in required.items() if v is not True]
    rows = [
        {"check": "FIXTURE/CHAOS workOrders", "status": "FIXTURE", "evidence": f"n={chaos['workOrderCount']}"},
        {"check": "no oversell", "status": _logic(bool(chaos.get("noOversell"))), "evidence": f"subprocess/persistence scope={chaos.get('noOversell')}"},
        {"check": "material conservation", "status": _logic(bool(chaos.get("materialConserved"))), "evidence": str(chaos.get("materialConserved"))},
        {"check": "crash all-or-nothing", "status": _logic(bool(chaos.get("crashAllOrNothing"))), "evidence": "in-process CrashInjected + subprocess after-staging"},
        {"check": "stale writer blocked", "status": _logic(bool(chaos.get("staleWriterBlocked"))), "evidence": str(chaos.get("staleWriterBlocked"))},
        {"check": "station offline/lease/duplicate", "status": _fix(bool(chaos.get("station", {}).get("offlineDenied") and chaos.get("noDuplicateCompletion"))), "evidence": json.dumps(chaos.get("station"), default=str)},
        {"check": "QC fail rework pass", "status": _fix(bool((chaos.get("qcRework") or {}).get("passed"))), "evidence": json.dumps(chaos.get("qcRework"))},
        {"check": "stale release rejected", "status": _fix(bool(chaos.get("staleReleaseRejected"))), "evidence": str(chaos.get("staleReleaseRejected"))},
        {"check": "packing mismatch rejected", "status": _fix(bool(chaos.get("packingMismatchRejected"))), "evidence": str(chaos.get("packingMismatchRejected"))},
        {"check": "journal tamper detected", "status": _logic(bool((chaos.get("journalIntegrity") or {}).get("tamperDetected"))), "evidence": json.dumps(chaos.get("journalIntegrity"))},
        {"check": "scan tenant isolation", "status": _fix(bool(chaos.get("scanTenantSafe"))), "evidence": str(chaos.get("scanTenantSafe"))},
        {"check": "human approval gate", "status": _fix(bool(chaos.get("humanApprovalGate"))), "evidence": "confirm required"},
        {"check": "journalBusinessCommitConsistent", "status": _logic(required["journalBusinessCommitConsistent"] is True), "evidence": str(required["journalBusinessCommitConsistent"])},
        {"check": "processRestartRecovery", "status": _logic(required["processRestartRecovery"] is True), "evidence": str(required["processRestartRecovery"])},
        {"check": "noDoubleCompletionAfterRestart", "status": _logic(required["noDoubleCompletionAfterRestart"] is True), "evidence": str(required["noDoubleCompletionAfterRestart"])},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "LIVE_LASER", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "not factory throughput", "status": "FIXTURE", "evidence": "FIXTURE/CHAOS"},
    ]
    gate_ok = bool(chaos.get("ok")) and not missing
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
            {"check": "operator view tenant scoped", "status": "FIXTURE", "evidence": op_view.get("tenantId")},
            {"check": "barcode hardware", "status": "PARTIAL", "evidence": "scan token only"},
            {"check": "LIVE_CNC badge", "status": "BLOCKED", "evidence": health.get("liveCnc")},
            {"check": "LIVE_LASER badge", "status": "BLOCKED", "evidence": health.get("liveLaser")},
            {"check": "health notFactorySla", "status": "FIXTURE", "evidence": str(health.get("notFactorySla"))},
        ],
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "globalProductionReady": False,
        "notCanonicalSixFile": True,
    }
    deploy["integrityGates"] = required
    deploy["ok"] = gate_ok
    docs.mkdir(parents=True, exist_ok=True)
    dest = docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json"
    if not gate_ok and dest.exists():
        try:
            prev = json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
        if prev.get("ok") is True or (prev.get("chaos") or {}).get("ok") is True:
            print(json.dumps({"ok": False, "label": "FIXTURE/CHAOS", "refusedOverwrite": True, "failures": missing + list(chaos.get("gateFailures") or [])}))
            return 1
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").write_text(json.dumps(deploy, indent=2, default=str), encoding="utf-8")
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.md").write_text(_md("PILOT_DEPLOYMENT_ACCEPTANCE", rows, generated), encoding="utf-8")
    (docs / "OPERATOR_CONTROL_ACCEPTANCE.json").write_text(json.dumps(operator, indent=2, default=str), encoding="utf-8")
    (docs / "OPERATOR_CONTROL_ACCEPTANCE.md").write_text(_md("OPERATOR_CONTROL_ACCEPTANCE", operator["rows"], generated), encoding="utf-8")
    payload = {"ok": gate_ok, "label": "FIXTURE/CHAOS", "workOrderCount": chaos.get("workOrderCount"), "generation": generation_id, "failures": missing}
    print(json.dumps(payload, default=str))
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
