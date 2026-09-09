"""Phase 481–540 Manual Factory Pilot acceptance. FIXTURE/REAL_LOGIC, not Production Ready."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.manual_pilot import REQUIRED_GATES, run_manual_factory_scenario  # noqa: E402
from fox3d.platform import Platform  # noqa: E402

ACCEPTANCE_FILES = (
    "MANUAL_FACTORY_PILOT_ACCEPTANCE",
    "OPERATOR_SHIFT_ACCEPTANCE",
    "INVENTORY_RECONCILIATION_ACCEPTANCE",
    "PILOT_BACKUP_RESTORE_ACCEPTANCE",
)


def _md(title: str, rows: list[dict], generated: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"generatedAt: {generated}",
        "pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.",
        "This is a scoped Phase 481–540 Manual Factory Pilot truth set.",
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
    dest = docs / "MANUAL_FACTORY_PILOT_ACCEPTANCE.json"
    if dest.exists():
        try:
            prev = json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
        if prev.get("ok") is True:
            print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "refusedOverwrite": True, "failures": failures}))
            return 1
    print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "failures": failures}))
    return 1


def _status(ok: bool, *, true_label: str = "REAL_LOGIC") -> str:
    return true_label if ok is True else "PARTIAL"


def main(argv: list[str] | None = None, *, hooks: dict | None = None) -> int:
    hooks = hooks or {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-root", default=None)
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
    factory = hooks.get("platform") or (lambda root: Platform(root=root, mock_blender=True))
    plat = factory(acc_root / "live")
    if hooks.get("scenario"):
        result = hooks["scenario"](plat)
    else:
        result = run_manual_factory_scenario(
            plat,
            backup_dir=acc_root / "backup",
            restore_root=acc_root / "restore",
        )
    generated = datetime.now(timezone.utc).isoformat()
    gates = dict(result.get("gates") or {})
    gates["workingTreeClean"] = bool(clean)
    gates["evidenceCommitMatchesHead"] = bool(matches_head and sha)
    missing = [k for k in REQUIRED_GATES if gates.get(k) is not True and k not in {"liveMachineControl", "globalProductionReady", "liveFactoryExecutionReady", "fullAutonomousFactoryReady"}]
    for k in ("liveMachineControl", "globalProductionReady", "liveFactoryExecutionReady", "fullAutonomousFactoryReady"):
        if gates.get(k) is not False:
            missing.append(k)
    if gates.get("workingTreeClean") is not True:
        missing.append("workingTreeClean")
    if gates.get("evidenceCommitMatchesHead") is not True:
        missing.append("evidenceCommitMatchesHead")
    health = result.get("health") or {}
    if (health.get("journalIntegrity") or {}).get("ok") is not True and "journalHealthyAfterRestore" not in missing:
        if gates.get("journalHealthyAfterRestore") is not True:
            missing.append("journalHealthyAfterRestore")
    rows = [
        {"check": "four-family FIXTURE e2e", "status": "FIXTURE", "evidence": str((result.get("families") or {}).get("ok"))},
        {"check": "operator/shift isolation", "status": _status(bool(gates.get("operatorTenantIsolation"))), "evidence": "disabled/closed/cross-tenant fail closed"},
        {"check": "shift restart", "status": _status(bool(gates.get("shiftRestartRecovery"))), "evidence": str(gates.get("shiftRestartRecovery"))},
        {"check": "traveler releaseHash pin", "status": _status(bool(gates.get("travelerReleasePinned"))), "evidence": str(result.get("releaseHash"))},
        {"check": "scan token tenant-safe", "status": _status(bool(gates.get("scanTokenTenantSafe"))), "evidence": "authorizesOperation=false"},
        {"check": "cycle-count approval", "status": _status(bool(gates.get("cycleCountApprovalRequired"))), "evidence": "WAITING_HUMAN_APPROVAL"},
        {"check": "inventory conserved", "status": _status(bool(gates.get("inventoryConservedAfterAdjustment"))), "evidence": "consumed/reserved unchanged"},
        {"check": "labor append-only", "status": _status(bool(gates.get("laborHistoryAppendOnly"))), "evidence": "CONFIG_ESTIMATE vs MANUAL; accounting NOT_IMPLEMENTED"},
        {"check": "blocking hold", "status": _status(bool(gates.get("blockingHoldPreventsCompletion"))), "evidence": str(gates.get("blockingHoldPreventsCompletion"))},
        {"check": "rework lineage", "status": _status(bool(gates.get("reworkLineagePreserved"))), "evidence": str(gates.get("reworkLineagePreserved"))},
        {"check": "packing pin", "status": _status(bool(gates.get("packingReleasePinned"))), "evidence": str(gates.get("packingReleasePinned"))},
        {"check": "manual shipment", "status": _status(bool(gates.get("manualShipmentNoProviderClaim"))), "evidence": "MANUAL/IMPORTED, no provider"},
        {"check": "backup checksum", "status": _status(bool(gates.get("backupChecksumVerified"))), "evidence": str(gates.get("backupChecksumVerified"))},
        {"check": "restore releaseHash", "status": _status(bool(gates.get("restoreReleaseHashPreserved"))), "evidence": str(gates.get("restoreReleaseHashPreserved"))},
        {"check": "restore no double consume/complete", "status": _status(bool(gates.get("restoreNoDoubleConsume") and gates.get("restoreNoDoubleCompletion"))), "evidence": json.dumps(result.get("restart"), default=str)},
        {"check": "journal after restore", "status": _status(bool(gates.get("journalHealthyAfterRestore"))), "evidence": str(gates.get("journalHealthyAfterRestore"))},
        {"check": "cross-tenant restore", "status": _status(bool(gates.get("crossTenantRestoreRejected"))), "evidence": str(gates.get("crossTenantRestoreRejected"))},
        {"check": "evidenceCodeCommit", "status": "REAL_LOGIC" if gates["evidenceCommitMatchesHead"] else "BLOCKED", "evidence": sha},
        {"check": "workingTreeClean", "status": "REAL_LOGIC" if clean else "UNVERIFIED", "evidence": str(clean)},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "LIVE_LASER", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "REAL blender refresh", "status": "REAL", "evidence": "unchanged render/release path; reuse 4/4 T1000 OptiX CODE 018cc70 generation c878d5f3-a3d2-44cd-8223-7b2b94d84af1"},
    ]
    gate_ok = bool(result.get("ok")) and not missing
    payload_common = {
        "generatedAt": generated,
        "acceptanceGenerationId": generation_id,
        "evidenceCodeCommit": sha,
        "workingTreeClean": clean,
        "evidenceCommitMatchesHead": gates["evidenceCommitMatchesHead"],
        "label": "FIXTURE/REAL_LOGIC",
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "globalProductionReady": False,
        "liveMachineControl": False,
        "realBlenderRefreshRequired": False,
        "priorRealBlenderEvidence": {
            "commitSha": "018cc70997a420e82358c0bb37677aa6b4de7eeb",
            "generation": "c878d5f3-a3d2-44cd-8223-7b2b94d84af1",
            "reason": "ManufacturingRelease/Blender render code unchanged in Phase 481-540",
        },
        "ok": gate_ok,
    }
    factory_doc = {
        **payload_common,
        "domain": "manual-factory-pilot",
        "gates": gates,
        "scenario": {k: result.get(k) for k in ("workOrderId", "releaseHash", "labor", "liveCnc", "liveLaser")},
        "familiesOk": (result.get("families") or {}).get("ok"),
        "rows": rows,
    }
    shift_doc = {
        **payload_common,
        "domain": "operator-shift",
        "operatorTenantIsolation": gates.get("operatorTenantIsolation"),
        "shiftRestartRecovery": gates.get("shiftRestartRecovery"),
        "scanTokenTenantSafe": gates.get("scanTokenTenantSafe"),
        "rows": [r for r in rows if r["check"] in {"operator/shift isolation", "shift restart", "scan token tenant-safe", "LIVE_CNC", "LIVE_LASER"}],
    }
    inv_doc = {
        **payload_common,
        "domain": "inventory-reconciliation",
        "cycleCountApprovalRequired": gates.get("cycleCountApprovalRequired"),
        "inventoryConservedAfterAdjustment": gates.get("inventoryConservedAfterAdjustment"),
        "rows": [r for r in rows if r["check"] in {"cycle-count approval", "inventory conserved", "labor append-only"}],
    }
    bak_doc = {
        **payload_common,
        "domain": "pilot-backup-restore",
        "backupChecksumVerified": gates.get("backupChecksumVerified"),
        "restoreReleaseHashPreserved": gates.get("restoreReleaseHashPreserved"),
        "restoreNoDoubleConsume": gates.get("restoreNoDoubleConsume"),
        "restoreNoDoubleCompletion": gates.get("restoreNoDoubleCompletion"),
        "journalHealthyAfterRestore": gates.get("journalHealthyAfterRestore"),
        "crossTenantRestoreRejected": gates.get("crossTenantRestoreRejected"),
        "rows": [r for r in rows if "restore" in r["check"] or "backup" in r["check"] or r["check"] == "journal after restore"],
    }
    docs.mkdir(parents=True, exist_ok=True)
    if not gate_ok:
        return _refuse_overwrite(docs, missing)
    mapping = {
        "MANUAL_FACTORY_PILOT_ACCEPTANCE": factory_doc,
        "OPERATOR_SHIFT_ACCEPTANCE": shift_doc,
        "INVENTORY_RECONCILIATION_ACCEPTANCE": inv_doc,
        "PILOT_BACKUP_RESTORE_ACCEPTANCE": bak_doc,
    }
    for name, body in mapping.items():
        (docs / f"{name}.json").write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
        (docs / f"{name}.md").write_text(_md(name, body["rows"], generated), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": gate_ok,
                "label": "FIXTURE/REAL_LOGIC",
                "generation": generation_id,
                "evidenceCodeCommit": sha,
                "workingTreeClean": clean,
                "failures": missing,
            },
            default=str,
        )
    )
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
