"""Phase 541–600 SKU portfolio factory acceptance. FIXTURE/REAL_LOGIC, not Production Ready."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.acceptance_gate import (  # noqa: E402
    PORTFOLIO_ACCEPTANCE_FILES,
    atomic_publish_canonical,
    read_portfolio_truth_set,
)
from fox3d.backup import backup_pilot, evaluate_tenant_restore_matrix, restore_pilot  # noqa: E402
from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402
from fox3d.portfolio import media_case_real, run_portfolio_scenario, validate_top10_lineage  # noqa: E402

ACCEPTANCE_FILES = PORTFOLIO_ACCEPTANCE_FILES


def _md(title: str, rows: list[dict], generated: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"generatedAt: {generated}",
        "pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.",
        "This is a scoped Phase 541–600 Small-Space KD SKU Portfolio Factory truth set.",
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
    prior = read_portfolio_truth_set(docs)
    if prior.get("ok") is True:
        print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "refusedOverwrite": True, "failures": failures}))
        return 1
    dest = docs / "SKU_PORTFOLIO_FACTORY_ACCEPTANCE.json"
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
        result = run_portfolio_scenario(plat, render=render, evidence_commit=sha)
    generated = datetime.now(timezone.utc).isoformat()
    missing: list[str] = []
    if result.get("ok") is not True:
        missing.append("scenario_ok")
    lineage_rows = list(result.get("top10Lineage") or [])
    missing.extend(validate_top10_lineage(lineage_rows))
    if result.get("candidateCount", 0) < 24:
        missing.append("candidate_count")
    if result.get("kindCount", 0) < 6:
        missing.append("kind_count")
    if result.get("top10") != 10:
        missing.append("top10")
    if int(result.get("top10") or 0) == 10 and len(lineage_rows) != 10:
        missing.append("top10_lineage_count")
    if result.get("invalidInTop10"):
        missing.append("invalid_in_top10")
    if result.get("demandLabel") == "REAL":
        missing.append("demand_mislabeled_real")
    if result.get("liveMachineControl") is not False:
        missing.append("liveMachineControl")
    if not result.get("tenantIsolation"):
        missing.append("tenant_isolation")
    if not result.get("conservationOk"):
        missing.append("conservation")
    if not result.get("prototypeReady"):
        missing.append("prototype_ready")
    if hooks.get("scenario"):
        backup = {"snapshotPathSetBound": True}
        matrix = {"tenantLeakageAbsent": True, "tenantRequiredStatePreserved": True, "tenantStateDigest": {"equal": True}}
    else:
        backup_dir = acc_root / "backup"
        restore_root = acc_root / "restore"
        if backup_dir.exists():
            import shutil

            shutil.rmtree(backup_dir)
        backup = backup_pilot(plat.root, backup_dir, tenant_ids=["pf-a"])
        restore_pilot(backup_dir, restore_root, tenant_id="pf-a")
        restored = Platform(root=restore_root, mock_blender=True)
        matrix = evaluate_tenant_restore_matrix(live=plat, restored=restored, tenant_a="pf-a", tenant_b="pf-b")
    if matrix.get("tenantLeakageAbsent") is not True:
        missing.append("tenant_leakage")
    if matrix.get("tenantRequiredStatePreserved") is not True:
        missing.append("tenant_semantic")
    if backup.get("snapshotPathSetBound") is not True:
        missing.append("snapshot")
    media = result.get("media") or []
    detailed_media = []
    for row in media:
        case = {k: row.get(k) for k in (
            "candidateId", "engineeringHash", "jobId", "alternateJobId", "previewArtifact", "alternateArtifact",
            "usedMock", "realBlender", "realOptix", "blenderVersion", "device", "gpu", "engine", "executedAt",
            "evidenceCodeCommit", "artifactSha256", "artifactSize", "label",
        )}
        detailed_media.append(case)
    real_media = [m for m in detailed_media if media_case_real(m, expected_commit=sha)]
    media_status = "REAL" if len(real_media) >= 4 else ("PARTIAL" if media else "BLOCKED")
    if args.real_media:
        if len(real_media) < 4:
            missing.append("real_media_4")
        for i, row in enumerate(detailed_media[:4]):
            if not media_case_real(row, expected_commit=sha):
                missing.append(f"real_media[{i}]")
    rows = [
        {"check": ">=24 candidates / >=6 kinds", "status": _status(result.get("candidateCount", 0) >= 24 and result.get("kindCount", 0) >= 6), "evidence": f"n={result.get('candidateCount')} kinds={result.get('kinds')}"},
        {"check": "invalid retained, not in Top 10", "status": _status(result.get("rejected", 0) >= 1 and not result.get("invalidInTop10")), "evidence": f"rejected={result.get('rejected')} invalidInTop={result.get('invalidInTop10')}"},
        {"check": "Top 10 deterministic", "status": _status(result.get("top10") == 10), "evidence": str(result.get("rankingPolicyHash"))},
        {"check": "DFM conservation", "status": _status(bool(result.get("conservationOk"))), "evidence": json.dumps({"conservationOk": result.get("conservationOk"), "toleranceMm2": 2.0}, default=str)},
        {"check": "cross-SKU planning no consume", "status": _status((result.get("plan") or {}).get("consumesInventory") is False), "evidence": json.dumps({k: (result.get("plan") or {}).get(k) for k in ("sheetCountDelta", "consumesInventory", "doubleAllocation")}, default=str)},
        {"check": "commercial truth labels", "status": "CONFIG_ESTIMATE", "evidence": str(result.get("demandLabel"))},
        {"check": "MOCK demand not REAL", "status": _status(result.get("demandLabel") != "REAL"), "evidence": str(result.get("demandLabel"))},
        {"check": "tenant isolation", "status": _status(bool(result.get("tenantIsolation"))), "evidence": str(result.get("tenantIsolation"))},
        {"check": "tenant backup semantic", "status": _status(bool(matrix.get("tenantRequiredStatePreserved") and matrix.get("tenantLeakageAbsent"))), "evidence": json.dumps(matrix.get("tenantStateDigest"), default=str)},
        {"check": "manual prototype approval", "status": _status(bool(result.get("prototypeReady"))), "evidence": str((result.get("pack") or {}).get("status"))},
        {"check": "Top 10 lineage", "status": _status(not validate_top10_lineage(lineage_rows)), "evidence": json.dumps(lineage_rows, default=str)[:800]},
        {"check": "REAL blender media", "status": media_status, "evidence": json.dumps([{k: m.get(k) for k in ("candidateId", "engineeringHash", "jobId", "artifactSha256", "artifactSize", "blenderVersion", "device", "gpu", "evidenceCodeCommit", "usedMock", "realBlender", "realOptix", "executedAt")} for m in detailed_media], default=str)},
        {"check": "evidenceCodeCommit", "status": "REAL_LOGIC" if matches_head else "BLOCKED", "evidence": sha},
        {"check": "workingTreeClean", "status": "REAL_LOGIC" if clean else "UNVERIFIED", "evidence": str(clean)},
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
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveProviderReady": False,
        "globalProductionReady": False,
        "liveMachineControl": False,
        "ok": gate_ok,
        "priorRealBlenderEvidence": {
            "commitSha": "018cc70997a420e82358c0bb37677aa6b4de7eeb",
            "generation": "c878d5f3-a3d2-44cd-8223-7b2b94d84af1",
            "reason": "ManufacturingRelease/Blender render path unchanged; portfolio media is additional scoped evidence",
        },
    }
    factory_doc = {
        **payload_common,
        "domain": "sku-portfolio-factory",
        "candidateCount": result.get("candidateCount"),
        "kindCount": result.get("kindCount"),
        "top10": result.get("top10"),
        "rejected": result.get("rejected"),
        "rankingPolicyHash": result.get("rankingPolicyHash"),
        "top10Lineage": lineage_rows,
        "realMediaCases": detailed_media,
        "rows": rows,
    }
    dfm_doc = {
        **payload_common,
        "domain": "portfolio-dfm",
        "conservationOk": result.get("conservationOk"),
        "conservationToleranceMm2": 2.0,
        "plan": {k: (result.get("plan") or {}).get(k) for k in ("sheetCountDelta", "trueScrapDelta", "consumesInventory", "doubleAllocation", "oversell", "remnantFirst")},
        "rows": [r for r in rows if r["check"] in {"DFM conservation", "cross-SKU planning no consume", "invalid retained, not in Top 10"}],
    }
    commercial_doc = {
        **payload_common,
        "domain": "portfolio-commercial",
        "demandLabel": result.get("demandLabel"),
        "prototypeReady": result.get("prototypeReady"),
        "realMediaCount": len(real_media),
        "realMediaCases": detailed_media,
        "rows": [r for r in rows if r["check"] in {"commercial truth labels", "MOCK demand not REAL", "manual prototype approval", "REAL blender media", "Top 10 lineage"}],
    }
    if not gate_ok:
        return _refuse_overwrite(docs, missing)
    mapping = {
        "SKU_PORTFOLIO_FACTORY_ACCEPTANCE": factory_doc,
        "PORTFOLIO_DFM_ACCEPTANCE": dfm_doc,
        "PORTFOLIO_COMMERCIAL_ACCEPTANCE": commercial_doc,
    }
    artifacts = {}
    for name, body in mapping.items():
        artifacts[f"{name}.json"] = json.dumps(body, indent=2, default=str)
        artifacts[f"{name}.md"] = _md(name, body["rows"], generated)
    published = atomic_publish_canonical(docs, artifacts, generation_id=generation_id, replace_fn=hooks.get("replace"))
    if published.get("ok") is not True:
        print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "failures": ["atomic_publish", published.get("error")], "rolledBack": True}))
        return 1
    bundle = read_portfolio_truth_set(docs)
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
                "candidateCount": result.get("candidateCount"),
                "top10": result.get("top10"),
                "realMedia": len(real_media),
                "failures": missing,
            },
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
