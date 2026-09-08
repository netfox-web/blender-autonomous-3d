"""Phase 301–360 manufacturing release / pilot REAL acceptance.

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

from fox3d.acceptance_gate import aggregate_canonical_consistency, atomic_publish_canonical  # noqa: E402
from fox3d.evidence import DirtyTreeError, inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id  # noqa: E402
from fox3d.platform import Platform  # noqa: E402

ACCEPTANCE_FILES = (
    "MANUFACTURING_RELEASE_REAL_ACCEPTANCE",
    "PILOT_OPERATIONS_ACCEPTANCE",
    "QC_TRACEABILITY_ACCEPTANCE",
)


def _md(title: str, rows: list[dict], generated: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"generatedAt: {generated}",
        "pytest mock PASS is **not** production ready. LIVE_CNC / LIVE_LASER remain BLOCKED.",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['check']} | {r['status']} | `{r['evidence']}` |")
    lines.append("")
    lines.append("`fullAutonomousFactoryReady=false`. `liveFactoryExecutionReady=false`.")
    lines.append("")
    return "\n".join(lines)


def _ok_job(p: dict) -> bool:
    bun = p.get("bundle") or {}
    return (
        p.get("label") == "REAL"
        and bool((p.get("verify") or {}).get("ok"))
        and not p.get("usedMock")
        and bool(bun.get("releaseHash") or p.get("releaseHash"))
    )


def _release_bound_ok(previews: list[dict], families: list[dict]) -> bool:
    expected = {f["family"]: f.get("releaseHash") for f in families}
    if len(previews) < 4:
        return False
    for p in previews:
        bun = p.get("bundle") or {}
        rh = bun.get("releaseHash") or p.get("releaseHash")
        want = expected.get(p.get("family"))
        if not rh or not want or rh != want:
            return False
        if not (p.get("verify") or {}).get("ok"):
            return False
    return True


def main(argv: list[str] | None = None, *, hooks: dict | None = None) -> int:
    hooks = hooks or {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-root", default=None)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    docs = Path(args.docs_root) if args.docs_root else ROOT / "docs"
    inspect = hooks.get("inspect") or inspect_repo_lineage
    try:
        lineage = inspect(ROOT, allow_dirty=args.allow_dirty)
    except DirtyTreeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 4
    sha = lineage["evidenceCodeCommit"]
    real_ok = bool(lineage.get("realAcceptanceAllowed"))
    rows: list[dict] = []

    def add(name: str, status: str, evidence: str) -> None:
        rows.append({"check": name, "status": status, "evidence": evidence})

    if hooks.get("pipeline"):
        data = hooks["pipeline"](lineage=lineage, sha=sha, real_ok=real_ok)
        probe = data["probe"]
        four = data["four"]
        previews = list(data.get("previews") or [])
        quotes = data.get("quotes") or {"quotes": [{}, {}, {}], "staleOnReleaseChange": True, "fxSource": "MANUAL"}
        ready = data.get("ready") or {
            "fullAutonomousFactoryReady": False,
            "liveFactoryExecutionReady": False,
        }
        stress = data.get("stress") or {"label": "FIXTURE", "workOrderCount": 0, "operationTransitions": 0}
        rows.extend(data.get("rows") or [])
    else:
        plat = Platform(root=ROOT / ".fox3d-data", mock_blender=False)
        probe = plat.register_detected_workers()
        add("Blender", "REAL" if probe.realBlender else "BLOCKED_NO_BLENDER", str(probe.blenderBinary))
        add("OptiX", "REAL" if probe.realOptix else "BLOCKED_NO_OPTIX", str(probe.gpuName))
        add("workingTreeClean", "REAL" if lineage["workingTreeClean"] else "UNVERIFIED", str(lineage["workingTreeClean"]))

        four = plat.pilot.run_four_family_e2e(tenant_id="pilot-real")
        add("four-family manual E2E", "REAL" if four["ok"] else "PARTIAL", f"ok={four['ok']} n={len(four['families'])}")
        for fam in four["families"]:
            add(f"{fam['family']} packet checksum", "REAL" if fam["verify"]["ok"] else "PARTIAL", fam["releaseHash"][:12])
            add(f"{fam['family']} WO COMPLETED", "REAL" if fam["workOrderState"] == "COMPLETED" else "PARTIAL", fam["workOrderState"])

        quotes = plat.pilot.supplier_fixture(plat.pilot.releases.get(four["families"][0]["releaseId"]))
        add("supplier quote import/compare logic", "REAL", f"n={len(quotes['quotes'])} parser=REAL")
        add("supplier quote business data", "IMPORTED", "IMPORTED snapshots, not LIVE_PROVIDER")
        add("supplier compare stale", "REAL" if quotes["staleOnReleaseChange"] else "PARTIAL", str(quotes["staleOnReleaseChange"]))
        add("FX business data", "MANUAL", quotes["fxSource"])
        stress = plat.pilot.reliability.run(tenant_id="pilot-real-fix", n_orders=50)
        add("reliability fixture stress", "FIXTURE", f"wo={stress['workOrderCount']} ops={stress['operationTransitions']} oversell={not stress['noOversell']}")

        log = plat.pilot.logistics
        carrier = log.import_carrier_quote({"carrier": "TW-POST", "service": "ground", "charge": 180, "dimDivisor": 6000}, source="IMPORTED")
        add("carrier quote", carrier["truthLabel"], carrier["quoteId"][:8])

        previews = []
        if probe.realBlender and probe.realOptix:
            previews = plat.pilot.render_family_previews(
                tenant_id="pilot-real", commit_sha=sha, real_ok=real_ok, families=four["families"]
            )
            n_real = sum(1 for p in previews if _ok_job(p))
            add(
                "pilot 4-family Blender EvidenceBundle",
                "REAL" if n_real >= 4 and real_ok else "PARTIAL",
                f"real={n_real}/4 clean={lineage['workingTreeClean']}",
            )
        else:
            add("pilot 4-family Blender EvidenceBundle", "BLOCKED_NO_OPTIX" if probe.realBlender else "BLOCKED_NO_BLENDER", "skipped")

        ready = plat.pilot.readiness(
            evidence={
                "releasePackage": True,
                "pilotOps": four["ok"],
                "qc": True,
                "supplierQuotes": True,
                "carrierQuotes": True,
                "coreRender": probe.realBlender,
                "reliability": stress.get("noOversell") and stress.get("materialConserved"),
                "strictStock": True,
            }
        )
        add("liveFactoryExecutionReady", "BLOCKED", str(ready["liveFactoryExecutionReady"]))
        add("fullAutonomousFactoryReady", "BLOCKED", str(ready["fullAutonomousFactoryReady"]))
        add("LIVE_CNC", "BLOCKED", "liveMachineControl=false")
        add("LIVE_LASER", "BLOCKED", "liveMachineControl=false")

    canon = aggregate_canonical_consistency(docs)
    add("canonical six-file reader", "REAL" if canon["canonicalTruthSetOk"] else "PARTIAL", ",".join(canon["errors"]) or "ok")

    blender_real = bool(getattr(probe, "realBlender", None) if not isinstance(probe, dict) else probe.get("realBlender"))
    optix_real = bool(getattr(probe, "realOptix", None) if not isinstance(probe, dict) else probe.get("realOptix"))
    n_real = sum(1 for p in previews if _ok_job(p))
    release_bound = _release_bound_ok(previews, four.get("families") or [])
    required_ok = (
        real_ok
        and blender_real
        and optix_real
        and four["ok"]
        and n_real >= 4
        and all((p.get("verify") or {}).get("ok") for p in previews)
        and release_bound
        and bool(canon.get("canonicalTruthSetOk"))
        and ready["fullAutonomousFactoryReady"] is False
        and ready["liveFactoryExecutionReady"] is False
    )
    generated = datetime.now(timezone.utc).isoformat()
    generation_id = new_id()

    def stamp(payload: dict) -> dict:
        return {
            **payload,
            "evidenceCodeCommit": sha,
            "workingTreeClean": lineage["workingTreeClean"],
            "acceptanceGenerationId": generation_id,
            "generatedAt": generated,
            "fullAutonomousFactoryReady": False,
            "liveFactoryExecutionReady": False,
            "liveMachineControl": False,
        }

    mfg_rows = [r for r in rows if "packet" in r["check"] or r["check"] in {"Blender", "OptiX", "four-family manual E2E", "pilot 4-family Blender EvidenceBundle"}]
    qc_rows = [r for r in rows if "WO" in r["check"] or "canonical" in r["check"] or r["check"].startswith("LIVE_")]
    ops_rows = rows
    payloads = {
        "MANUFACTURING_RELEASE_REAL_ACCEPTANCE": stamp(
            {
                "domain": "manufacturing-release",
                "rows": mfg_rows,
                "previews": previews,
                "families": [{k: fam[k] for k in ("family", "kind", "releaseHash", "workOrderState", "verify") if k in fam} for fam in four["families"]],
                "note": "REAL means deterministic packet+hash+Blender evidence, not machine execution",
            }
        ),
        "PILOT_OPERATIONS_ACCEPTANCE": stamp(
            {
                "domain": "pilot-ops",
                "rows": ops_rows,
                "readiness": ready,
                "fourFamilyOk": four["ok"],
                "supplier": {"n": len(quotes["quotes"]), "stale": quotes["staleOnReleaseChange"], "fx": quotes["fxSource"]},
                "canonicalTruthSet": canon,
            }
        ),
        "QC_TRACEABILITY_ACCEPTANCE": stamp(
            {
                "domain": "qc-traceability",
                "rows": qc_rows,
                "traces": [fam.get("trace", {}).get("workOrderId") for fam in four["families"]],
            }
        ),
        "PILOT_RELIABILITY_ACCEPTANCE": stamp(
            {
                "domain": "pilot-reliability",
                "label": "FIXTURE",
                "stress": stress,
                "rows": [r for r in rows if "reliability" in r["check"] or r["status"] in {"FIXTURE", "IMPORTED", "MANUAL"}],
                "note": "FIXTURE stress is not factory throughput. Supplier/carrier data remains IMPORTED/MANUAL.",
            }
        ),
    }
    artifacts = {f"{name}.json": json.dumps(payload, indent=2, default=str) for name, payload in payloads.items()}
    artifacts["MANUFACTURING_RELEASE_REAL_ACCEPTANCE.md"] = _md("MANUFACTURING_RELEASE_REAL_ACCEPTANCE", mfg_rows, generated)
    artifacts["PILOT_OPERATIONS_ACCEPTANCE.md"] = _md("PILOT_OPERATIONS_ACCEPTANCE", ops_rows, generated)
    artifacts["QC_TRACEABILITY_ACCEPTANCE.md"] = _md("QC_TRACEABILITY_ACCEPTANCE", qc_rows, generated)
    artifacts["PILOT_RELIABILITY_ACCEPTANCE.md"] = _md("PILOT_RELIABILITY_ACCEPTANCE", [r for r in rows if r["status"] in {"FIXTURE", "IMPORTED", "MANUAL", "BLOCKED"} or "reliability" in r["check"]], generated)

    publish = {"ok": False, "published": []}
    if required_ok:
        publish = atomic_publish_canonical(docs, artifacts, generation_id=generation_id, replace_fn=hooks.get("replace_fn"))
        if not publish.get("ok"):
            required_ok = False

    def _pg(key: str):
        return probe.get(key) if isinstance(probe, dict) else getattr(probe, key, None)

    print(
        json.dumps(
            {
                "requiredRealAcceptanceOk": required_ok,
                "evidenceCodeCommit": sha,
                "acceptanceGenerationId": generation_id,
                "previews": [
                    {
                        "family": p.get("family"),
                        "label": p.get("label"),
                        "verify": (p.get("verify") or {}).get("ok"),
                        "releaseHash": (p.get("bundle") or {}).get("releaseHash") or p.get("releaseHash"),
                    }
                    for p in previews
                ],
                "fourFamilyOk": four["ok"],
                "canonicalTruthSetOk": bool(canon.get("canonicalTruthSetOk")),
                "releaseBoundOk": release_bound,
                "probe": {"blender": _pg("blenderBinary"), "gpu": _pg("gpuName"), "optix": _pg("realOptix")},
                "publish": {"ok": publish.get("ok"), "published": publish.get("published")},
                "fullAutonomousFactoryReady": False,
            },
            indent=2,
            default=str,
        )
    )
    return 0 if required_ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
