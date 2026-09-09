"""Phase 601–660 prototype validation acceptance. FIXTURE/REAL_LOGIC, not Production Ready."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.acceptance_gate import (  # noqa: E402
    PROTOTYPE_ACCEPTANCE_FILES,
    atomic_publish_canonical,
    read_prototype_truth_set,
)
from fox3d.backup import backup_pilot, evaluate_tenant_restore_matrix, restore_pilot  # noqa: E402
from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402
from fox3d.portfolio import media_case_real  # noqa: E402
from fox3d.prototype import run_prototype_scenario  # noqa: E402


def _md(title: str, rows: list[dict], generated: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"generatedAt: {generated}",
        "pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.",
        "This is a scoped Phase 601–660 prototype validation truth set. Fixture ≠ physical prototype.",
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
    prior = read_prototype_truth_set(docs)
    if prior.get("ok") is True:
        print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "refusedOverwrite": True, "failures": failures}))
        return 1
    dest = docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json"
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
    parser.add_argument("--real-media", action="store_true")
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
    factory = hooks.get("platform") or (lambda root: Platform(root=root, mock_blender=not args.real_media))
    plat = factory(acc_root / "live")
    if hooks.get("scenario"):
        result = hooks["scenario"](plat)
    else:
        render = bool(args.real_media)
        if render and not getattr(plat, "mock_blender", True):
            try:
                plat.register_detected_workers()
            except Exception:
                render = False
        result = run_prototype_scenario(plat, render=render, evidence_commit=sha)
    generated = datetime.now(timezone.utc).isoformat()
    missing: list[str] = []
    if result.get("ok") is not True:
        missing.append("scenario_ok")
    selected = result.get("selected") or []
    if len(selected) != 4:
        missing.append("selected_4")
    if result.get("physicalPrototypeValidated") is True:
        missing.append("fixture_physical")
    if result.get("demandLabel") == "REAL":
        missing.append("demand_mislabeled_real")
    if result.get("liveMachineControl") is not False:
        missing.append("liveMachineControl")
    if hooks.get("scenario"):
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
    media = result.get("media") or []
    real_media = [m for m in media if media_case_real(m, expected_commit=sha)]
    media_status = "REAL" if len(real_media) >= 4 else ("PARTIAL" if media else "BLOCKED")
    if args.real_media and len(real_media) < 4:
        missing.append("real_media_4")
    rows = [
        {"check": "4 prototype SKUs selected", "status": _status(len(selected) == 4), "evidence": json.dumps([s.get("candidateId") for s in selected])},
        {"check": "fixture cannot physically validate", "status": _status(result.get("physicalPrototypeValidated") is False), "evidence": f"physicalPrototypeValidated={result.get('physicalPrototypeValidated')}"},
        {"check": "MOCK demand not REAL", "status": _status(result.get("demandLabel") != "REAL"), "evidence": str(result.get("demandLabel"))},
        {"check": "tenant backup semantic", "status": _status(bool(matrix.get("tenantRequiredStatePreserved") and matrix.get("tenantLeakageAbsent"))), "evidence": json.dumps(matrix.get("tenantStateDigest"), default=str)},
        {"check": "REAL blender media", "status": media_status, "evidence": f"real={len(real_media)}/{len(media) or 0}"},
        {"check": "evidenceCodeCommit", "status": "REAL_LOGIC" if matches_head else "BLOCKED", "evidence": sha},
        {"check": "workingTreeClean", "status": "REAL_LOGIC" if clean else "UNVERIFIED", "evidence": str(clean)},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "LIVE_LASER", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "physical prototype", "status": "FIXTURE", "evidence": "CI measurements are FIXTURE; physicalPrototypeValidated=false"},
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
        "physicalPrototypeValidated": False,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "globalProductionReady": False,
        "liveMachineControl": False,
        "ok": gate_ok,
        "priorRealBlenderEvidence": {
            "commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14",
            "generation": "0b76b09e-02a8-45a6-b4fd-bf34849dd76c",
            "reason": "Portfolio/media/engineering render path unchanged; Phase 601–660 adds prototype workflow only",
        },
    }
    proto_doc = {
        **payload_common,
        "domain": "prototype-validation",
        "selectedCount": len(selected),
        "selected": [{k: s.get(k) for k in ("selectionId", "candidateId", "engineeringHash", "truthLabel")} for s in selected],
        "units": [{k: u.get(k) for k in ("prototypeUnitId", "candidateId", "engineeringHash", "state", "physicalPrototypeValidated")} for u in (result.get("units") or [])],
        "rows": rows,
    }
    launch_doc = {
        **payload_common,
        "domain": "sku-launch-readiness",
        "board": result.get("board"),
        "demandLabel": result.get("demandLabel"),
        "rows": [r for r in rows if r["check"] in {"MOCK demand not REAL", "fixture cannot physically validate", "LIVE_CNC", "LIVE_LASER"}],
    }
    if not gate_ok:
        return _refuse_overwrite(docs, missing)
    artifacts = {}
    for name, body in (
        ("PROTOTYPE_VALIDATION_ACCEPTANCE", proto_doc),
        ("SKU_LAUNCH_READINESS_ACCEPTANCE", launch_doc),
    ):
        artifacts[f"{name}.json"] = json.dumps(body, indent=2, default=str)
        artifacts[f"{name}.md"] = _md(name, body["rows"], generated)
    published = atomic_publish_canonical(docs, artifacts, generation_id=generation_id, replace_fn=hooks.get("replace"))
    if published.get("ok") is not True:
        print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "failures": ["atomic_publish", published.get("error")], "rolledBack": True}))
        return 1
    bundle = read_prototype_truth_set(docs)
    if bundle.get("ok") is not True:
        return _refuse_overwrite(docs, list(bundle.get("errors") or ["bundle_inconsistent"]))
    print(
        json.dumps(
            {
                "ok": True,
                "label": "FIXTURE/REAL_LOGIC",
                "generation": generation_id,
                "evidenceCodeCommit": sha,
                "workingTreeClean": clean,
                "selected": len(selected),
                "physicalPrototypeValidated": False,
                "failures": missing,
            },
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
