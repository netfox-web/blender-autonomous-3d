"""Phase 421–480 deployment acceptance. Additional scoped truth set, not canonical six-file.

pytest mock PASS is not Production Ready. LIVE_CNC / LIVE_LASER stay BLOCKED.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.deploy_chaos import ChaosHarness  # noqa: E402
from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402

REQUIRED_GATES = (
    "journalBusinessCommitConsistent",
    "noCommittedGhostJournalEvents",
    "processRestartRecovery",
    "stationRestartRecovered",
    "workOrderRestartRecovered",
    "noDoubleCompletionAfterRestart",
    "releaseHashPreservedAfterRestart",
    "materialConservedAfterCrash",
    "tenantIsolationAfterRestart",
    "journalHealthyBeforeTamper",
    "tamperDetectionIsolated",
    "journalTamperDetected",
    "sharedJournalHealthyAfterAcceptance",
    "evidenceCommitMatchesHead",
    "workingTreeClean",
)


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


def _refuse_overwrite(docs: Path, failures: list[str]) -> int:
    dest = docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json"
    if dest.exists():
        try:
            prev = json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
        if prev.get("ok") is True or (prev.get("chaos") or {}).get("ok") is True:
            print(json.dumps({"ok": False, "label": "FIXTURE/CHAOS", "refusedOverwrite": True, "failures": failures}))
            return 1
    print(json.dumps({"ok": False, "label": "FIXTURE/CHAOS", "failures": failures}))
    return 1


def passing_chaos_stub() -> dict[str, Any]:
    return {
        "ok": True,
        "label": "FIXTURE/CHAOS",
        "workOrderCount": 8,
        "noOversell": True,
        "materialConserved": True,
        "crashAllOrNothing": True,
        "staleWriterBlocked": True,
        "staleReleaseRejected": True,
        "packingMismatchRejected": True,
        "scanTenantSafe": True,
        "noDuplicateCompletion": True,
        "humanApprovalGate": True,
        "liveCnc": False,
        "liveLaser": False,
        "journalBusinessCommitConsistent": True,
        "noCommittedGhostJournalEvents": True,
        "processRestartRecovery": True,
        "stationRestartRecovered": True,
        "workOrderRestartRecovered": True,
        "noDoubleCompletionAfterRestart": True,
        "releaseHashPreservedAfterRestart": True,
        "materialConservedAfterCrash": True,
        "tenantIsolationAfterRestart": True,
        "journalHealthyBeforeTamper": True,
        "tamperDetectionIsolated": True,
        "journalTamperDetected": True,
        "sharedJournalHealthyAfterAcceptance": True,
        "journalIntegrity": {"tamperDetected": True, "chainOkBefore": True, "tamperDetectionIsolated": True},
        "station": {"offlineDenied": True, "noDuplicateComplete": True},
        "qcRework": {"passed": True},
        "health": {"journalIntegrity": {"ok": True, "status": "REAL"}, "liveCnc": "BLOCKED", "liveLaser": "BLOCKED", "notFactorySla": True},
        "gateFailures": [],
        "notFactoryThroughput": True,
    }


def main(argv: list[str] | None = None, *, hooks: dict | None = None) -> int:
    hooks = hooks or {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-root", default=None)
    parser.add_argument("--orders", type=int, default=100)
    parser.add_argument("--expected-commit", default=None)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    docs = Path(args.docs_root) if args.docs_root else ROOT / "docs"
    inspect = hooks.get("inspect") or inspect_repo_lineage
    try:
        lineage = inspect(ROOT, allow_dirty=args.allow_dirty)
    except DirtyTreeError as exc:
        return _refuse_overwrite(docs, ["working_tree_dirty", str(exc)])
    except Exception as exc:
        return _refuse_overwrite(docs, ["missing_commit_lineage", str(exc)])
    sha = str(lineage.get("evidenceCodeCommit") or "")
    if not sha:
        return _refuse_overwrite(docs, ["missing_commit_lineage"])
    clean = bool(lineage.get("workingTreeClean"))
    if not clean and not args.allow_dirty:
        return _refuse_overwrite(docs, ["working_tree_dirty"])
    expected = args.expected_commit
    matches_head = True
    if expected:
        matches_head = expected == sha
        if not matches_head:
            return _refuse_overwrite(docs, ["evidence_commit_mismatch", f"expected={expected}", f"head={sha}"])
    generation_id = new_id()
    acc_root = Path(hooks["acceptance_root"]) if hooks.get("acceptance_root") else ROOT / ".fox3d-data" / "acceptance" / generation_id
    acc_root.mkdir(parents=True, exist_ok=True)
    if hooks.get("chaos"):
        plat = hooks.get("platform")(acc_root) if hooks.get("platform") else None
        chaos = hooks["chaos"](plat)
    else:
        factory = hooks.get("platform") or (lambda root: Platform(root=root, mock_blender=True))
        plat = factory(acc_root)
        chaos = ChaosHarness(plat).run(n_orders=int(args.orders))
    if plat is None:
        factory = hooks.get("platform") or (lambda root: Platform(root=root, mock_blender=True))
        plat = factory(acc_root)

    generated = datetime.now(timezone.utc).isoformat()

    def _fix(ok: bool) -> str:
        return "FIXTURE" if ok else "PARTIAL"

    def _logic(ok: bool) -> str:
        return "REAL_LOGIC" if ok else "PARTIAL"

    required = {k: chaos.get(k) for k in REQUIRED_GATES if k not in {"evidenceCommitMatchesHead", "workingTreeClean"}}
    required["evidenceCommitMatchesHead"] = bool(matches_head and sha)
    required["workingTreeClean"] = bool(clean)
    missing = [k for k, v in required.items() if v is not True]
    health = chaos.get("health") or plat.pilot.health(tenant_id="chaos-a")
    if (health.get("journalIntegrity") or {}).get("ok") is not True:
        missing.append("sharedHealthJournal")
    if (health.get("journalIntegrity") or {}).get("status") == "BLOCKED_EVIDENCE":
        missing.append("sharedHealthBlocked")
    rows = [
        {"check": "FIXTURE/CHAOS workOrders", "status": "FIXTURE", "evidence": f"n={chaos.get('workOrderCount')}"},
        {"check": "no oversell", "status": _logic(bool(chaos.get("noOversell"))), "evidence": f"subprocess/persistence scope={chaos.get('noOversell')}"},
        {"check": "material conservation", "status": _logic(bool(chaos.get("materialConserved"))), "evidence": str(chaos.get("materialConserved"))},
        {"check": "crash all-or-nothing", "status": _logic(bool(chaos.get("crashAllOrNothing"))), "evidence": "in-process CrashInjected + subprocess after-staging"},
        {"check": "stale writer blocked", "status": _logic(bool(chaos.get("staleWriterBlocked"))), "evidence": str(chaos.get("staleWriterBlocked"))},
        {"check": "station offline/lease/duplicate", "status": _fix(bool(chaos.get("station", {}).get("offlineDenied") and chaos.get("noDuplicateCompletion"))), "evidence": json.dumps(chaos.get("station"), default=str)},
        {"check": "QC fail rework pass", "status": _fix(bool((chaos.get("qcRework") or {}).get("passed"))), "evidence": json.dumps(chaos.get("qcRework"))},
        {"check": "stale release rejected", "status": _fix(bool(chaos.get("staleReleaseRejected"))), "evidence": str(chaos.get("staleReleaseRejected"))},
        {"check": "packing mismatch rejected", "status": _fix(bool(chaos.get("packingMismatchRejected"))), "evidence": str(chaos.get("packingMismatchRejected"))},
        {"check": "journal tamper detected", "status": _logic(bool(chaos.get("journalTamperDetected"))), "evidence": json.dumps(chaos.get("journalIntegrity"))},
        {"check": "journalHealthyBeforeTamper", "status": _logic(bool(chaos.get("journalHealthyBeforeTamper"))), "evidence": str(chaos.get("journalHealthyBeforeTamper"))},
        {"check": "sharedJournalHealthyAfterAcceptance", "status": _logic(bool(chaos.get("sharedJournalHealthyAfterAcceptance"))), "evidence": str(chaos.get("sharedJournalHealthyAfterAcceptance"))},
        {"check": "tamperDetectionIsolated", "status": _logic(bool(chaos.get("tamperDetectionIsolated"))), "evidence": str(chaos.get("tamperDetectionIsolated"))},
        {"check": "scan tenant isolation", "status": _fix(bool(chaos.get("scanTenantSafe"))), "evidence": str(chaos.get("scanTenantSafe"))},
        {"check": "human approval gate", "status": _fix(bool(chaos.get("humanApprovalGate"))), "evidence": "confirm required"},
        {"check": "evidenceCodeCommit", "status": "REAL_LOGIC" if required["evidenceCommitMatchesHead"] else "BLOCKED", "evidence": sha},
        {"check": "workingTreeClean", "status": "REAL_LOGIC" if clean else "UNVERIFIED", "evidence": str(clean)},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "LIVE_LASER", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "not factory throughput", "status": "FIXTURE", "evidence": "FIXTURE/CHAOS"},
    ]
    gate_ok = bool(chaos.get("ok")) and not missing
    op_view = plat.pilot.operator(tenant_id="chaos-a")
    deploy = {
        "domain": "pilot-deployment",
        "label": "FIXTURE/CHAOS",
        "generatedAt": generated,
        "acceptanceGenerationId": generation_id,
        "evidenceCodeCommit": sha,
        "workingTreeClean": clean,
        "evidenceCommitMatchesHead": required["evidenceCommitMatchesHead"],
        "chaos": chaos,
        "rows": rows,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "globalProductionReady": False,
        "liveMachineControl": False,
        "notCanonicalSixFile": True,
        "integrityGates": required,
        "ok": gate_ok,
    }
    operator = {
        "domain": "operator-control",
        "generatedAt": generated,
        "acceptanceGenerationId": generation_id,
        "evidenceCodeCommit": sha,
        "workingTreeClean": clean,
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
            {"check": "shared journal health", "status": "REAL_LOGIC" if (health.get("journalIntegrity") or {}).get("ok") else "BLOCKED_EVIDENCE", "evidence": json.dumps(health.get("journalIntegrity"))},
        ],
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "globalProductionReady": False,
        "notCanonicalSixFile": True,
        "ok": gate_ok and (health.get("journalIntegrity") or {}).get("ok") is True,
    }
    docs.mkdir(parents=True, exist_ok=True)
    dest = docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json"
    if not gate_ok:
        return _refuse_overwrite(docs, missing + list(chaos.get("gateFailures") or []))
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.json").write_text(json.dumps(deploy, indent=2, default=str), encoding="utf-8")
    (docs / "PILOT_DEPLOYMENT_ACCEPTANCE.md").write_text(_md("PILOT_DEPLOYMENT_ACCEPTANCE", rows, generated), encoding="utf-8")
    (docs / "OPERATOR_CONTROL_ACCEPTANCE.json").write_text(json.dumps(operator, indent=2, default=str), encoding="utf-8")
    (docs / "OPERATOR_CONTROL_ACCEPTANCE.md").write_text(_md("OPERATOR_CONTROL_ACCEPTANCE", operator["rows"], generated), encoding="utf-8")
    payload = {
        "ok": gate_ok,
        "label": "FIXTURE/CHAOS",
        "workOrderCount": chaos.get("workOrderCount"),
        "generation": generation_id,
        "evidenceCodeCommit": sha,
        "workingTreeClean": clean,
        "failures": missing,
    }
    print(json.dumps(payload, default=str))
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
