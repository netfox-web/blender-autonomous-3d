"""Phase 901–960 Product Content Factory V1 / Deterministic Commerce Asset Pack canonical runner."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.acceptance_gate import atomic_publish_canonical  # noqa: E402
from fox3d.blender import probe_host  # noqa: E402
from fox3d.content_factory import (  # noqa: E402
    REQUIRED_COMMERCE_VIEW_ROLES,
    qa_commerce_pack,
    run_product_content_scenario,
)
from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402


def _md(title: str, rows: list[dict], generated: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"generatedAt: {generated}",
        "pytest mock PASS is **not** production ready. Physical print is not validated.",
        "Generative output is never Product Truth. Live H3 MAX / LTX 2.5 stay BLOCKED without runtime.",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['check']} | {r['status']} | `{r['evidence']}` |")
    lines.append("")
    lines.append("`commercialAssetProductionReady=false`. `fullAutonomousFactoryReady=false`. `globalProductionReady=false`. `physicalPrintValidated=false`.")
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
    env_mock = os.environ.get("FOX3D_MOCK_BLENDER", "").lower() in {"1", "true", "yes"}
    want_mock = True
    if hooks.get("platform"):
        factory = hooks["platform"]
    else:
        probe = probe_host()
        want_mock = env_mock or not (probe.realBlender and probe.realOptix)
        factory = lambda root, mock=want_mock: Platform(root=root, mock_blender=mock)
    acc_root = Path(hooks["acceptance_root"]) if hooks.get("acceptance_root") else ROOT / ".fox3d-data" / "acceptance" / generation_id
    acc_root.mkdir(parents=True, exist_ok=True)
    plat = factory(acc_root / "live")
    scenario_fn = hooks.get("scenario") or run_product_content_scenario
    result = scenario_fn(plat, evidence_code_commit=sha)
    generated = datetime.now(timezone.utc).isoformat()
    mock = bool(getattr(plat, "mock_blender", True) or result.get("usedMock"))
    missing = list(result.get("failures") or [])

    pack = result.get("contentPack") or {}
    views = pack.get("views") or {}

    # 1. Independent QA validation against canonical ground truth
    eng = hooks.get("engineering") or result.get("frozenEngineering") or {}
    upstream_pack = hooks.get("product_truth_pack") or result.get("productTruthPack") or {}
    pt_authority = hooks.get("product_truth_authority") or result.get("productTruthAuthority")
    independent_qa = qa_commerce_pack(pack, eng, upstream_pack, plat, product_truth_authority=pt_authority)
    for f in independent_qa.get("failures") or []:
        if f not in missing:
            missing.append(f)

    # 2. Check derivative generative lifestyle briefs do not claim Product Truth
    briefs = pack.get("lifestyleBriefs") or {}
    for b_name, b_data in briefs.items():
        if b_data.get("isProductTruth") or b_data.get("productionReady"):
            missing.append(f"generative_brief_{b_name}_claimed_truth")

    # Strict readiness checks
    if mock and result.get("realCommerceRenderPackReady") is True:
        missing.append("mock_claimed_real_commerce_pack")
    if result.get("liveGenerativeCommerceReady"):
        missing.append("fixture_claimed_live_generative")
    if result.get("commercialAssetProductionReady"):
        missing.append("fixture_claimed_commercial_production_ready")
    if result.get("physicalPrintValidated"):
        missing.append("fixture_claimed_physical_print")

    # Verify all required views exist in views
    for r in REQUIRED_COMMERCE_VIEW_ROLES:
        if r not in views:
            missing.append(f"missing_view_{r}")

    rows = [
        {"check": "productContentFactoryLogicReady", "status": "REAL_LOGIC" if result.get("productContentFactoryLogicReady") else "MISSING", "evidence": result.get("productContentFactoryLogicReady")},
        {"check": "realCommerceRenderPackReady", "status": "MOCK" if mock else ("REAL" if result.get("realCommerceRenderPackReady") else "BLOCKED_ENVIRONMENT"), "evidence": result.get("realCommerceRenderPackReady")},
        {"check": "liveGenerativeCommerceReady", "status": "BLOCKED", "evidence": False},
        {"check": "commercialAssetProductionReady", "status": "BLOCKED", "evidence": False},
        {"check": "physicalPrintValidated", "status": "BLOCKED", "evidence": False},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "contentPackId", "status": "REAL_LOGIC", "evidence": pack.get("contentPackId")},
        {"check": "sourceRenderPackId", "status": "REAL_LOGIC", "evidence": pack.get("sourceRenderPackId")},
        {"check": "sourceAcceptanceGenerationId", "status": "REAL_LOGIC", "evidence": pack.get("sourceAcceptanceGenerationId")},
        {"check": "dimensionLabelAuthority", "status": "REAL_LOGIC", "evidence": (views.get("DIMENSION_FRONT") or {}).get("dimensionMetadata", {}).get("dimensionLabelLayerHash")},
        {"check": "usedMock", "status": "MOCK" if mock else "REAL", "evidence": mock},
    ]

    body = {
        "ok": not missing and bool(result.get("ok")),
        "label": "FIXTURE/REAL_LOGIC" if mock else "REAL_LOGIC",
        "acceptanceGenerationId": generation_id,
        "evidenceCodeCommit": sha,
        "workingTreeClean": clean,
        "generatedAt": generated,
        "productContentFactoryLogicReady": bool(result.get("productContentFactoryLogicReady")),
        "realCommerceRenderPackReady": False if mock else bool(result.get("realCommerceRenderPackReady")),
        "liveGenerativeCommerceReady": False,
        "commercialAssetProductionReady": False,
        "physicalPrintValidated": False,
        "liveFactoryExecutionReady": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "usedMock": mock,
        "contentPackId": pack.get("contentPackId"),
        "sourceRenderPackId": pack.get("sourceRenderPackId"),
        "sourceAcceptanceGenerationId": pack.get("sourceAcceptanceGenerationId"),
        "contentPack": pack,
        "qa": pack.get("qa"),
        "rows": rows,
        "acceptanceFailures": missing,
    }

    if not body["ok"]:
        return _refuse(docs, missing or ["scenario_failed"])

    artifacts = {
        "PRODUCT_CONTENT_FACTORY_ACCEPTANCE.json": json.dumps(body, indent=2, default=str),
        "PRODUCT_CONTENT_FACTORY_ACCEPTANCE.md": _md("PRODUCT_CONTENT_FACTORY_ACCEPTANCE", rows, generated),
    }

    published = atomic_publish_canonical(docs, artifacts, generation_id=generation_id, replace_fn=hooks.get("replace"))
    if published.get("ok") is not True:
        return _refuse(docs, ["atomic_publish", str(published.get("error"))])

    print(
        json.dumps(
            {
                "ok": True,
                "label": body["label"],
                "generation": generation_id,
                "evidenceCodeCommit": sha,
                "workingTreeClean": clean,
                "productContentFactoryLogicReady": body["productContentFactoryLogicReady"],
                "realCommerceRenderPackReady": body["realCommerceRenderPackReady"],
                "liveGenerativeCommerceReady": False,
                "commercialAssetProductionReady": False,
                "physicalPrintValidated": False,
                "failures": [],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
