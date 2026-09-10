"""Phase 781–840 artwork placement canonical runner. FIXTURE/REAL_LOGIC, not physical print."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.acceptance_gate import atomic_publish_canonical  # noqa: E402
from fox3d.artwork import run_artwork_scenario, validate_artwork_acceptance_result  # noqa: E402
from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402
from fox3d.prototype import PRIOR_REAL_BLENDER, verify_prior_real_blender  # noqa: E402


def _md(title: str, rows: list[dict], generated: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"generatedAt: {generated}",
        "pytest mock PASS is **not** production ready. Physical print is not validated.",
        "Artwork placement is millimetre REAL_LOGIC. Mock Blender preview is MOCK.",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['check']} | {r['status']} | `{r['evidence']}` |")
    lines.append("")
    lines.append("`fullAutonomousFactoryReady=false`. `globalProductionReady=false`. `physicalPrintValidated=false`.")
    lines.append("")
    return "\n".join(lines)


def _refuse(docs: Path, failures: list[str]) -> int:
    print(json.dumps({"ok": False, "label": "FIXTURE/REAL_LOGIC", "failures": failures}))
    return 1


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
        return _refuse(docs, ["working_tree_dirty", str(exc)])
    sha = str(lineage.get("evidenceCodeCommit") or "")
    if not sha:
        return _refuse(docs, ["missing_commit_lineage"])
    clean = bool(lineage.get("workingTreeClean"))
    if not clean and not args.allow_dirty:
        return _refuse(docs, ["working_tree_dirty"])
    expected = args.expected_commit
    if expected and expected != sha:
        return _refuse(docs, ["evidence_commit_mismatch", f"expected={expected}", f"head={sha}"])
    generation_id = new_id()
    factory = hooks.get("platform") or (lambda root: Platform(root=root, mock_blender=True))
    acc_root = Path(hooks["acceptance_root"]) if hooks.get("acceptance_root") else ROOT / ".fox3d-data" / "acceptance" / generation_id
    acc_root.mkdir(parents=True, exist_ok=True)
    plat = factory(acc_root / "live")
    result = (hooks.get("scenario") or run_artwork_scenario)(plat)
    generated = datetime.now(timezone.utc).isoformat()
    missing = list(validate_artwork_acceptance_result(result))
    prior_docs = Path(hooks["prior_docs"]) if hooks.get("prior_docs") else ROOT / "docs"
    prior_real = verify_prior_real_blender(prior_docs)
    mock = bool(getattr(plat, "mock_blender", True))
    if mock and result.get("realArtworkPreviewReady") is True:
        missing.append("mock_claimed_real_preview")
    rows = [
        {"check": "4-door master 2400mm", "status": "REAL_LOGIC", "evidence": json.dumps(result.get("scenarios", {}).get("cabinet4", {}).get("widthMm"))},
        {"check": "surfaceDecorationLogicReady", "status": "REAL_LOGIC" if result.get("surfaceDecorationLogicReady") else "MISSING", "evidence": result.get("surfaceDecorationLogicReady")},
        {"check": "productionArtworkFileReady", "status": "REAL_LOGIC" if result.get("productionArtworkFileReady") else "MISSING", "evidence": result.get("productionArtworkFileReady")},
        {"check": "realArtworkPreviewReady", "status": "MOCK" if mock else ("REAL" if result.get("realArtworkPreviewReady") else "BLOCKED_ENVIRONMENT"), "evidence": result.get("preview")},
        {"check": "physicalPrintValidated", "status": "BLOCKED", "evidence": False},
        {"check": "keep-out BLOCK", "status": "REAL_LOGIC", "evidence": (result.get("negatives") or {}).get("keepout")},
        {"check": "stale engineering", "status": "REAL_LOGIC", "evidence": (result.get("negatives") or {}).get("stale")},
        {"check": "prior REAL blender", "status": "REAL" if prior_real.get("ok") else "PARTIAL", "evidence": json.dumps({"commitSha": (PRIOR_REAL_BLENDER or {}).get("commitSha"), "ok": prior_real.get("ok")})},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
    ]
    body = {
        "ok": not missing and bool(result.get("ok")),
        "label": "FIXTURE/REAL_LOGIC",
        "acceptanceGenerationId": generation_id,
        "evidenceCodeCommit": sha,
        "workingTreeClean": clean,
        "evidenceCommitMatchesHead": True,
        "generatedAt": generated,
        "physicalPrintValidated": False,
        "realArtworkPreviewReady": False if mock else bool(result.get("realArtworkPreviewReady")),
        "surfaceDecorationLogicReady": bool(result.get("surfaceDecorationLogicReady")),
        "productionArtworkFileReady": bool(result.get("productionArtworkFileReady")),
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "liveFactoryExecutionReady": False,
        "liveMachineControl": False,
        "demandLabel": "MOCK",
        "printPreflight": "PARTIAL",
        "artworkContentAwarePlacementReady": False,
        "rows": rows,
        "scenarios": result.get("scenarios"),
        "lineage": result.get("lineage"),
        "negatives": result.get("negatives"),
        "preview": result.get("preview"),
        "priorRealBlender": prior_real,
        "acceptanceFailures": missing,
    }
    if not body["ok"]:
        return _refuse(docs, missing or ["scenario_failed"])
    artifacts = {
        "ARTWORK_PLACEMENT_ACCEPTANCE.json": json.dumps(body, indent=2, default=str),
        "ARTWORK_PLACEMENT_ACCEPTANCE.md": _md("ARTWORK_PLACEMENT_ACCEPTANCE", rows, generated),
    }
    published = atomic_publish_canonical(docs, artifacts, generation_id=generation_id, replace_fn=hooks.get("replace"))
    if published.get("ok") is not True:
        return _refuse(docs, ["atomic_publish", str(published.get("error"))])
    print(
        json.dumps(
            {
                "ok": True,
                "label": "FIXTURE/REAL_LOGIC",
                "generation": generation_id,
                "evidenceCodeCommit": sha,
                "workingTreeClean": clean,
                "physicalPrintValidated": False,
                "realArtworkPreviewReady": body["realArtworkPreviewReady"],
                "failures": [],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
