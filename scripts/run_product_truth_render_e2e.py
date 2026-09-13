"""Phase 841–900 Product Truth Render Pack + Generative Gateway canonical runner."""

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
from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402
from fox3d.product_truth import (  # noqa: E402
    REQUIRED_VIEWS,
    derive_canonical_expected_identity,
    run_phase_841_scenario,
    validate_frozen_authority_semantics,
    validate_product_truth_render_pack,
)


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
    result = (hooks.get("scenario") or run_phase_841_scenario)(plat, evidence_code_commit=sha)
    generated = datetime.now(timezone.utc).isoformat()
    mock = bool(getattr(plat, "mock_blender", True) or result.get("usedMock"))
    missing = list(result.get("acceptanceFailures") or [])
    if mock and result.get("realArtworkPreviewReady") is True:
        missing.append("mock_claimed_real_preview")
    if result.get("liveH3MaxProviderReady") or result.get("liveLtx25ProviderReady"):
        missing.append("fixture_live_provider")
    pack = result.get("pack") or {}
    gen = result.get("generative") or {}

    # 1. Strictly validate frozen pre-worker authority object with ZERO fallback to pack/worker/expectedIdentity
    frozen_authority = hooks.get("frozen_authority") or result.get("frozenAuthorityContext")
    if not frozen_authority or not isinstance(frozen_authority, dict):
        return _refuse(docs, ["missing_frozen_authority"])

    frozen_failures: list[str] = []
    f_tenant_id = frozen_authority.get("tenant_id")
    if not f_tenant_id or not isinstance(f_tenant_id, str):
        frozen_failures.append("missing_frozen_tenant_id")

    f_placement = frozen_authority.get("placement") if isinstance(frozen_authority.get("placement"), dict) else {}
    place_id = frozen_authority.get("placementId") or f_placement.get("placementId")
    if not place_id or not isinstance(place_id, str):
        frozen_failures.append("missing_frozen_placement_id")

    f_eng = frozen_authority.get("engineering") or ({"engineeringHash": frozen_authority.get("engineeringHash")} if frozen_authority.get("engineeringHash") else None)
    if not f_eng:
        frozen_failures.append("missing_frozen_engineering")

    f_cam = frozen_authority.get("camera")
    f_scene = frozen_authority.get("scene")
    f_view_recipes = frozen_authority.get("view_recipes")
    sem_failures = validate_frozen_authority_semantics(frozen_authority)
    frozen_failures.extend(sem_failures)

    # If any required frozen authority item is missing/invalid, refuse publication immediately without reading pack
    if frozen_failures:
        return _refuse(docs, frozen_failures)

    # 2. Re-resolve canonical placement strictly from store using frozen placement identity
    canonical_place = plat.artwork.placements.get(place_id) if (hasattr(plat, "artwork") and hasattr(plat.artwork, "placements")) else None
    if not canonical_place:
        missing.append("missing_canonical_placement")

    # 3. Derive canonical expected identity from frozen context + canonical store
    canonical_expected = derive_canonical_expected_identity(
        plat,
        tenant_id=str(f_tenant_id),
        placement=canonical_place or {"placementId": str(place_id)},
        engineering=f_eng,
        camera=f_cam,
        scene=f_scene,
        view_recipes=f_view_recipes,
        strict=True,
    ) if hasattr(plat, "artwork") else None

    if not canonical_expected:
        missing.append("missing_canonical_authority")
    elif canonical_expected.get("canonicalAuthorityValid") is False:
        missing.append(f"canonical_authority_{canonical_expected.get('canonicalFailure', 'invalid')}")

    # 4. Independent pack validation against canonical ground truth
    independent_failures = validate_product_truth_render_pack(
        pack,
        expected_identity=canonical_expected,
        plat=plat,
    )
    for f in independent_failures:
        if f not in missing:
            missing.append(f)
    rows = [
        {"check": "realArtworkPreviewReady", "status": "MOCK" if mock else ("REAL" if result.get("realArtworkPreviewReady") else "BLOCKED_ENVIRONMENT"), "evidence": result.get("realArtworkPreviewReady")},
        {"check": "productTruthRenderPackReady", "status": "REAL" if result.get("productTruthRenderPackReady") else ("FIXTURE" if result.get("productTruthAovPackReady") else "MISSING"), "evidence": result.get("productTruthRenderPackReady")},
        {"check": "productTruthAovPackReady", "status": "REAL_LOGIC" if result.get("productTruthAovPackReady") else "MISSING", "evidence": result.get("productTruthAovPackReady")},
        {"check": "generativeRenderGatewayLogicReady", "status": "REAL_LOGIC" if result.get("generativeRenderGatewayLogicReady") else "MISSING", "evidence": result.get("generativeRenderGatewayLogicReady")},
        {"check": "liveH3MaxProviderReady", "status": "BLOCKED", "evidence": False},
        {"check": "liveLtx25ProviderReady", "status": "BLOCKED", "evidence": False},
        {"check": "productConsistencyQaLogicReady", "status": "REAL_LOGIC" if result.get("productConsistencyQaLogicReady") else "MISSING", "evidence": (result.get("qa") or {}).get("decision")},
        {"check": "liveVisionJudgeReady", "status": "MOCK", "evidence": False},
        {"check": "physicalPrintValidated", "status": "BLOCKED", "evidence": False},
        {"check": "LIVE_CNC", "status": "BLOCKED", "evidence": "liveMachineControl=false"},
        {"check": "renderPackId", "status": "REAL_LOGIC", "evidence": result.get("renderPackId")},
        {"check": "usedMock", "status": "MOCK" if mock else "REAL", "evidence": mock},
    ]
    body = {
        "ok": not missing and bool(result.get("ok")),
        "label": "FIXTURE/REAL_LOGIC" if mock else "REAL_LOGIC",
        "acceptanceGenerationId": generation_id,
        "evidenceCodeCommit": sha,
        "workingTreeClean": clean,
        "generatedAt": generated,
        "realArtworkPreviewReady": False if mock else bool(result.get("realArtworkPreviewReady")),
        "productTruthRenderPackReady": False if mock else bool(result.get("productTruthRenderPackReady")),
        "productTruthAovPackReady": bool(result.get("productTruthAovPackReady")),
        "generativeRenderGatewayLogicReady": bool(result.get("generativeRenderGatewayLogicReady")),
        "liveH3MaxProviderReady": False,
        "liveLtx25ProviderReady": False,
        "productConsistencyQaLogicReady": bool(result.get("productConsistencyQaLogicReady")),
        "liveVisionJudgeReady": False,
        "physicalPrintValidated": False,
        "liveFactoryExecutionReady": False,
        "globalProductionReady": False,
        "fullAutonomousFactoryReady": False,
        "usedMock": mock,
        "renderPackId": result.get("renderPackId"),
        "frozenEngineering": frozen_authority.get("engineering"),
        "pack": pack,
        "generative": gen,
        "qa": result.get("qa"),
        "rows": rows,
        "acceptanceFailures": missing,
    }
    if not body["ok"]:
        return _refuse(docs, missing or ["scenario_failed"])
    artifacts = {
        "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.json": json.dumps(body, indent=2, default=str),
        "PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md": _md("PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE", rows, generated),
        "GENERATIVE_RENDER_GATEWAY_ACCEPTANCE.json": json.dumps(
            {
                "ok": bool(gen.get("ok")),
                "label": "FIXTURE/MOCK",
                "acceptanceGenerationId": generation_id,
                "evidenceCodeCommit": sha,
                "generativeRenderGatewayLogicReady": True,
                "liveH3MaxProviderReady": False,
                "liveLtx25ProviderReady": False,
                "routing": (gen.get("routing") or {}),
                "usedMock": True,
                "physicalPrintValidated": False,
                "globalProductionReady": False,
            },
            indent=2,
            default=str,
        ),
        "GENERATIVE_RENDER_GATEWAY_ACCEPTANCE.md": _md(
            "GENERATIVE_RENDER_GATEWAY_ACCEPTANCE",
            [
                {"check": "gateway logic", "status": "REAL_LOGIC", "evidence": True},
                {"check": "liveH3MaxProviderReady", "status": "BLOCKED", "evidence": False},
                {"check": "liveLtx25ProviderReady", "status": "BLOCKED", "evidence": False},
                {"check": "qualityClaim", "status": "UNVERIFIED", "evidence": (gen.get("routing") or {}).get("qualityClaim")},
            ],
            generated,
        ),
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
                "realArtworkPreviewReady": body["realArtworkPreviewReady"],
                "productTruthRenderPackReady": body["productTruthRenderPackReady"],
                "liveH3MaxProviderReady": False,
                "liveLtx25ProviderReady": False,
                "physicalPrintValidated": False,
                "failures": [],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
