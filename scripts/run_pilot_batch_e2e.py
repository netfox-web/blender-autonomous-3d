"""Phase 721–780 pilot batch execution + commercial launch governance. FIXTURE/REAL_LOGIC, not Production Ready."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.acceptance_gate import atomic_publish_canonical, read_pilot_batch_truth_set  # noqa: E402
from fox3d.backup import backup_pilot, evaluate_tenant_restore_matrix, restore_pilot  # noqa: E402
from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402
from fox3d.pilot_batch import run_pilot_batch_scenario, validate_pilot_batch_acceptance_result  # noqa: E402
from fox3d.prototype import PRIOR_REAL_BLENDER, verify_prior_real_blender  # noqa: E402


def _md(title: str, rows: list[dict], generated: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"generatedAt: {generated}",
        "pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.",
        "This is a scoped Phase 721–780 FIXTURE/REAL_LOGIC pilot-batch truth set. Fixture ≠ physical batch.",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['check']} | {r['status']} | `{r['evidence']}` |")
    lines.append("")
    lines.append("`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`. `globalProductionReady=false`.")
    lines.append("`physicalPilotBatchValidated=false`. `HUMAN_BATCH_GO` is not issued on fixture evidence.")
    lines.append("")
    return "\n".join(lines)


def _restore_snapshot(docs: Path, snapshot: dict[str, bytes], names: list[str]) -> None:
    for name in names:
        path = docs / name
        if name in snapshot:
            path.write_bytes(snapshot[name])
        elif path.exists():
            path.unlink()


def _refuse_overwrite(docs: Path, failures: list[str]) -> int:
    prior = read_pilot_batch_truth_set(docs)
    if prior.get("ok") is True:
        print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "refusedOverwrite": True, "failures": failures}))
        return 1
    dest = docs / "PILOT_BATCH_EXECUTION_ACCEPTANCE.json"
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


def _status(ok: bool) -> str:
    return "REAL_LOGIC" if ok is True else "PARTIAL"


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
        result = run_pilot_batch_scenario(plat, evidence_commit=sha)
    generated = datetime.now(timezone.utc).isoformat()
    missing: list[str] = []
    if hooks.get("mutate_published"):
        result = hooks["mutate_published"](result)
    missing.extend(validate_pilot_batch_acceptance_result(result))
    prior_docs = Path(hooks["prior_docs"]) if hooks.get("prior_docs") else ROOT / "docs"
    prior_real = verify_prior_real_blender(prior_docs)
    if prior_real.get("ok") is not True:
        missing.extend(list(prior_real.get("failures") or ["prior_real_blender"]))
    if result.get("physicalPilotBatchValidated") is True:
        missing.append("fixture_physical_batch")
    if result.get("liveMachineControl") is not False:
        missing.append("liveMachineControl")
    if hooks.get("restore_matrix") is not None:
        backup = {"snapshotPathSetBound": True}
        matrix = hooks["restore_matrix"]
    elif hooks.get("scenario"):
        backup = {"snapshotPathSetBound": True}
        matrix = {"tenantLeakageAbsent": True, "tenantRequiredStatePreserved": True, "tenantStateDigest": {"equal": True}}
    else:
        import shutil

        backup_dir = acc_root / "backup"
        restore_root = acc_root / "restore"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        backup = backup_pilot(plat.root, backup_dir, tenant_ids=["pv-a"])
        restore_pilot(backup_dir, restore_root, tenant_id="pv-a")
        restored = Platform(root=restore_root, mock_blender=True)
        matrix = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="pv-a", tenant_b="pv-b")
    if matrix.get("tenantLeakageAbsent") is not True:
        missing.append("tenant_leakage")
    if matrix.get("tenantRequiredStatePreserved") is not True:
        missing.append("tenant_semantic")
    if backup.get("snapshotPathSetBound") is not True:
        missing.append("snapshot")
    batches = result.get("batches") or []
    units = result.get("units") or []
    rows = [
        {"check": "4 SKU fixture batches", "status": _status(len(batches) == 4), "evidence": json.dumps([{"batchId": b.get("batchId"), "qty": b.get("requestedQuantity"), "state": b.get("state")} for b in batches], default=str)},
        {"check": "unit executions", "status": _status(len(units) >= 20), "evidence": f"units={len(units)}"},
        {"check": "fixture cannot HUMAN_BATCH_GO", "status": _status((result.get("batchLaunchDecision") or "WAITING_HUMAN_EVIDENCE") != "HUMAN_BATCH_GO"), "evidence": str(result.get("batchLaunchDecision"))},
        {"check": "physicalPilotBatchValidated", "status": _status(result.get("physicalPilotBatchValidated") is False), "evidence": str(result.get("physicalPilotBatchValidated"))},
        {"check": "tenant backup semantic", "status": _status(bool(matrix.get("tenantRequiredStatePreserved") and matrix.get("tenantLeakageAbsent"))), "evidence": json.dumps(matrix.get("tenantStateDigest"), default=str)},
        {"check": "prior REAL blender", "status": "REAL" if prior_real.get("ok") else "BLOCKED", "evidence": json.dumps({k: prior_real.get(k) for k in ("commitSha", "generation", "cases", "failures")}, default=str)},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "LIVE_LASER", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
    ]
    gate_ok = not missing and clean and matches_head
    payload_common = {
        "generatedAt": generated,
        "acceptanceGenerationId": generation_id,
        "evidenceCodeCommit": sha,
        "workingTreeClean": clean,
        "evidenceCommitMatchesHead": matches_head,
        "label": "FIXTURE/REAL_LOGIC",
        "evidenceLabel": "FIXTURE",
        "physicalPilotBatchValidated": False,
        "physicalPrototypeValidated": False,
        "batchLaunchDecision": result.get("batchLaunchDecision") or "WAITING_HUMAN_EVIDENCE",
        "launchDecision": result.get("launchDecision") or "WAITING_HUMAN_EVIDENCE",
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "globalProductionReady": False,
        "liveMachineControl": False,
        "pilotBatchExecutionReady": "FIXTURE/REAL_LOGIC",
        "commercialLaunchGovernanceReady": "FIXTURE/REAL_LOGIC",
        "ok": gate_ok,
        "batches": result.get("batches") or [],
        "units": result.get("units") or [],
        "cartons": result.get("cartons") or [],
        "board": result.get("board"),
        "batchAuthority": result.get("batchAuthority") or {},
        "priorRealBlenderEvidence": {
            "commitSha": PRIOR_REAL_BLENDER["commitSha"],
            "generation": PRIOR_REAL_BLENDER["generation"],
            "verified": bool(prior_real.get("ok")),
            "cases": prior_real.get("cases"),
            "reason": "Render/engineering/media path unchanged; Phase 721–780 adds batch execution only.",
        },
    }
    batch_doc = {
        **payload_common,
        "domain": "pilot-batch-execution",
        "batchCount": len(batches),
        "unitCount": len(units),
        "rows": rows,
        "acceptanceFailures": missing,
    }
    launch_doc = {
        **payload_common,
        "domain": "commercial-launch-readiness",
        "rows": [r for r in rows if r["check"] in {"fixture cannot HUMAN_BATCH_GO", "physicalPilotBatchValidated", "LIVE_CNC", "LIVE_LASER", "prior REAL blender"}],
    }
    serialized = json.loads(json.dumps(batch_doc, indent=2, default=str))
    missing.extend(validate_pilot_batch_acceptance_result(serialized))
    gate_ok = not missing and clean and matches_head
    batch_doc["ok"] = gate_ok
    batch_doc["acceptanceFailures"] = missing
    launch_doc["ok"] = gate_ok
    payload_common["ok"] = gate_ok
    if not gate_ok:
        return _refuse_overwrite(docs, missing)
    artifacts = {}
    for name, body in (
        ("PILOT_BATCH_EXECUTION_ACCEPTANCE", batch_doc),
        ("COMMERCIAL_LAUNCH_READINESS_ACCEPTANCE", launch_doc),
    ):
        artifacts[f"{name}.json"] = json.dumps(body, indent=2, default=str)
        artifacts[f"{name}.md"] = _md(name, body["rows"], generated)
    snapshot = {name: (docs / name).read_bytes() for name in artifacts if (docs / name).exists()}
    published = atomic_publish_canonical(docs, artifacts, generation_id=generation_id, replace_fn=hooks.get("replace"))
    if published.get("ok") is not True:
        _restore_snapshot(docs, snapshot, list(artifacts))
        print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "failures": ["atomic_publish", published.get("error")], "rolledBack": True}))
        return 1
    bundle = read_pilot_batch_truth_set(docs)
    if bundle.get("ok") is not True:
        _restore_snapshot(docs, snapshot, list(artifacts))
        return _refuse_overwrite(docs, list(bundle.get("errors") or ["bundle_inconsistent"]))
    published_batch = (bundle.get("payloads") or {}).get("PILOT_BATCH_EXECUTION_ACCEPTANCE") or {}
    post_fail = validate_pilot_batch_acceptance_result(published_batch)
    if post_fail:
        _restore_snapshot(docs, snapshot, list(artifacts))
        return _refuse_overwrite(docs, post_fail + ["post_publish_semantic"])
    print(
        json.dumps(
            {
                "ok": True,
                "label": "FIXTURE/REAL_LOGIC",
                "generation": generation_id,
                "evidenceCodeCommit": sha,
                "workingTreeClean": clean,
                "batches": len(batches),
                "units": len(units),
                "physicalPilotBatchValidated": False,
                "failures": missing,
            },
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
