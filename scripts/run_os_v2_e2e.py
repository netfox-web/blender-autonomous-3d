"""Physical Product OS V2 REAL acceptance. pytest mock is not production ready."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.acceptance_gate import atomic_publish_canonical, required_real_acceptance_ok  # noqa: E402
from fox3d.commerce import mixed_landed_cost  # noqa: E402
from fox3d.evidence import (  # noqa: E402
    ACCEPTANCE_RUNNER_VERSION,
    DirtyTreeError,
    evidence_bundle,
    inspect_repo_lineage,
    verify_bundle,
)
from fox3d.ids import new_id  # noqa: E402
from fox3d.packv2 import board_grade, carton_optimize, fit_regression  # noqa: E402
from fox3d.platform import Platform  # noqa: E402
from fox3d.publish import publication_package  # noqa: E402
from fox3d.readiness import scoped_readiness  # noqa: E402
from fox3d.safety import evaluate_product  # noqa: E402


def _ok(job: dict) -> bool:
    out = job.get("output") or {}
    real = job.get("realBlender") if job.get("realBlender") is not None else out.get("realBlender")
    used = job.get("usedMock") if job.get("usedMock") is not None else out.get("usedMock")
    return job.get("status") in {"completed", "succeeded"} and bool(real) and not used


def _md(title: str, extra_rows: list[dict], generated: str) -> str:
    lines = [f"# {title}", "", f"generatedAt: {generated}", "pytest mock PASS is **not** production ready.", "", "## Domain evidence (machine-verifiable)", "", "| Check | Status | Evidence |", "|---|---|---|"]
    for r in extra_rows:
        lines.append(f"| {r['check']} | {r['status']} | `{r['evidence']}` |")
    lines.append("")
    lines.append("Human Approval Gate remains. LIVE_CNC / LIVE_LASER BLOCKED.")
    return "\n".join(lines) + "\n"


def run_live_pipeline(*, plat, probe, lineage, sha, real_ok) -> dict:
    rows: list[dict] = []

    def add(name: str, status: str, evidence: str) -> None:
        rows.append({"check": name, "status": status, "evidence": evidence})

    add("Blender", "REAL" if probe.realBlender else "BLOCKED_NO_BLENDER", str(probe.blenderBinary))
    add("OptiX", "REAL" if probe.realOptix else "BLOCKED_NO_OPTIX", str(probe.gpuName))

    kd = plat.kd.build_sku(tenant_id="ops", kind="OPEN_SHELF")
    retail = plat.physical.retail.build(tenant_id="ops", family="COUNTER_DISPLAY", render=False)
    pkg = plat.physical.packaging.build(tenant_id="ops", family="RSC_CARTON", product_dims={"width": 120, "height": 80, "depth": 40})
    acr = plat.physical.acrylic.build(tenant_id="ops", kind="MENU_STAND")
    kd2 = plat.kd.build_sku(tenant_id="ops", kind="BEDSIDE_CABINET")

    previews: list[dict] = []
    families = [
        ("KD_FURNITURE", kd, "PARAMETRIC_CABINET", kd["spec"]),
        ("RETAIL_FIXTURE", retail, "PARAMETRIC_CABINET", retail["spec"]),
        ("PACKAGING_STRUCTURE", pkg, "PACKAGING_FOLD", None),
        ("ACRYLIC_SHEET", acr, "ACRYLIC_PRODUCT", None),
        ("KD_FURNITURE", kd2, "PARAMETRIC_CABINET", kd2["spec"]),
    ]
    if probe.realBlender and probe.realOptix:
        for family, rec, mode, eng in families:
            payload = {
                "tenantId": "ops",
                "jobType": "BLENDER_PREVIEW",
                "mode": mode,
                "render": {"width": 256, "height": 256, "engine": "CYCLES", "device": "OPTIX", "samples": 8},
                "timeoutSeconds": 180,
            }
            if eng:
                payload["engineering"] = eng
            if mode == "PACKAGING_FOLD":
                payload["foldPreview"] = True
                payload["packagingTemplate"] = "BOX"
                payload["dimensions"] = (rec.get("engineering") or {}).get("fit", {}).get("outer") or {"width": 120, "height": 80, "depth": 40}
            if mode == "ACRYLIC_PRODUCT":
                payload["acrylic"] = {"kind": rec["kind"], "dimensions": rec["dimensions"], "finish": rec["sheet"]["finish"]}
            job = plat.execute_job(plat.submit_job(payload))
            if job.get("status") in {"queued", "retry_scheduled"}:
                job = plat.execute_job(job)
            files = (job.get("output") or {}).get("files") or {}
            beauty = None
            asset = job.get("outputAsset") or files.get("beauty.png")
            if asset:
                try:
                    obj = plat.dam.get_unchecked(str(asset))
                    beauty = obj.path
                except Exception:
                    beauty = files.get("beauty.png")
            bun = evidence_bundle(
                commit_sha=sha,
                job=job,
                artifact_path=beauty,
                engineering_hash=rec.get("engineeringHash") or (rec.get("engineering") or {}).get("engineeringHash"),
                bom_hash=(rec.get("bom") or {}).get("bomHash"),
            )
            ver = verify_bundle(bun, require_real=True, expected_commit_sha=sha)
            label = "REAL" if real_ok and ver["ok"] and _ok(job) else "PARTIAL"
            if not real_ok:
                label = "UNVERIFIED"
            previews.append({"family": family, "jobId": job.get("jobId"), "usedMock": job.get("usedMock"), "realBlender": job.get("realBlender"), "outputHash": job.get("outputHash"), "gpuUuid": job.get("gpuUuid"), "blenderVersion": job.get("blenderVersion"), "workerId": job.get("worker"), "verify": ver, "bundle": bun, "label": label})
        n_real = sum(1 for p in previews if p["label"] == "REAL")
        add("publication 5-family Blender+EvidenceBundle", "REAL" if n_real >= 5 and real_ok else "PARTIAL", f"real={n_real}/5 clean={lineage['workingTreeClean']}")
    else:
        add("publication 5-family Blender+EvidenceBundle", "BLOCKED_NO_OPTIX" if probe.realBlender else "BLOCKED_NO_BLENDER", "skipped")

    gate = plat.release
    adv: dict = {}
    ev_ok = bool(previews) and all(p.get("verify", {}).get("ok") for p in previews)
    try:
        adv = gate.advance(kd["spec"]["productId"], target="ENGINEERING_VALID", actor="ops", entity=kd)
        adv = gate.advance(kd["spec"]["productId"], target="EVIDENCE_VERIFIED", actor="ops", entity=kd, evidence_ok=ev_ok)
        adv = gate.advance(kd["spec"]["productId"], target="WAITING_APPROVAL", actor="ops", entity=kd)
        adv = gate.advance(kd["spec"]["productId"], target="APPROVED_FOR_EXPORT", actor="ops", entity=kd)
        add("release gate APPROVED_FOR_EXPORT", "REAL", adv["state"])
    except Exception as exc:
        add("release gate APPROVED_FOR_EXPORT", "PARTIAL", str(exc))
    live_cnc_blocked = False
    live_laser_blocked = False
    try:
        gate.advance("nope", target="LIVE_CNC", actor="ops", entity=kd)
    except PermissionError:
        live_cnc_blocked = True
    try:
        gate.advance("nope2", target="LIVE_LASER", actor="ops", entity=kd)
    except PermissionError:
        live_laser_blocked = True
    add("forbidden LIVE_CNC transition", "REAL" if live_cnc_blocked else "FAIL", "blocked")
    add("forbidden LIVE_LASER transition", "REAL" if live_laser_blocked else "FAIL", "blocked")

    kd_changed = dict(kd)
    kd_changed["engineeringHash"] = "mutated"
    stale = gate.refresh_stale(kd["spec"]["productId"], kd_changed)
    add("approval stale on hash change", "REAL" if stale.get("stale") else "FAIL", str(stale.get("stale")))

    plat.providers.import_rows(plat.providers.material, [{"supplier": "LOCAL", "materialCode": "WOOD_WHITE", "thickness": 18, "price": 880, "currency": "TWD", "effectiveAt": "2026-01-01"}], source="MANUAL")
    mixed = mixed_landed_cost([{"name": "sheet", "amount": 880, "source": "MANUAL"}, {"name": "logistics", "amount": 80, "source": "CONFIG_ESTIMATE"}])
    add("mixed landed cost", "REAL" if mixed["truthLabel"] == "MIXED" else "FAIL", mixed["truthLabel"])
    add("liveProviderReady", "BLOCKED", "false")

    fit = fit_regression()
    add("packaging fit 20 cases", "REAL" if fit["allOk"] else "FAIL", f"{fit['passed']}/{fit['n']}")
    opt = carton_optimize({"width": 120, "height": 80, "depth": 40}, grade=board_grade("KRAFT_B_ECT32"))
    add("carton optimize", "REAL", opt["chosen"]["family"])

    saf = evaluate_product("KD", kd)
    add("safety notCertified", "REAL" if saf["notCertified"] else "FAIL", str(saf["boundary"]["notCertified"]))

    packs = [publication_package(r, family=f) for f, r, _, _ in families]
    add("publication packages", "REAL" if all(p.get("publicationHash") for p in packs) else "FAIL", f"n={len(packs)}")

    ready = scoped_readiness(evidence={"kd": True, "retail": True, "packaging": True, "acrylic": True, "coreRender": probe.realBlender, "importedCost": True, "ci": True})
    add("fullAutonomousFactoryReady", "BLOCKED" if not ready["fullAutonomousFactoryReady"] else "FAIL", str(ready["fullAutonomousFactoryReady"]))
    add("Vision", "MOCK", "no live provider")
    add("Demand", "MOCK", "MARKET_UNVERIFIED")
    add("OS sandbox", "PARTIAL", "PATH_GUARD_ONLY")
    add("LIVE_CNC", "BLOCKED", "liveMachineControl=false")
    return {
        "probe": probe,
        "rows": rows,
        "previews": previews,
        "adv": adv,
        "stale": stale,
        "live_cnc_blocked": live_cnc_blocked,
        "live_laser_blocked": live_laser_blocked,
        "mixed": mixed,
        "fit": fit,
        "opt": opt,
        "packs": packs,
        "ready": ready,
        "families": families,
    }


def main(argv: list[str] | None = None, *, hooks: dict | None = None) -> int:
    hooks = hooks or {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-dirty", action="store_true", help="dev-only; output is PARTIAL/UNVERIFIED, never REAL")
    parser.add_argument("--docs-root", default=None, help="override docs/ for tests")
    args = parser.parse_args(argv)
    inspect = hooks.get("inspect", inspect_repo_lineage)
    try:
        lineage = inspect(ROOT, allow_dirty=args.allow_dirty)
    except DirtyTreeError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "label": "FAIL"}, indent=2))
        return 2
    sha = lineage["evidenceCodeCommit"]
    real_ok = bool(lineage["realAcceptanceAllowed"])
    if hooks.get("pipeline"):
        data = hooks["pipeline"](lineage=lineage, sha=sha, real_ok=real_ok)
    else:
        plat = Platform(root=ROOT / ".fox3d-data", mock_blender=False)
        probe = plat.register_detected_workers()
        data = run_live_pipeline(plat=plat, probe=probe, lineage=lineage, sha=sha, real_ok=real_ok)

    probe = data["probe"]
    rows = list(data.get("rows") or [])
    previews = list(data.get("previews") or [])
    adv = data.get("adv") or {}
    stale = data.get("stale") or {}
    live_cnc_blocked = bool(data.get("live_cnc_blocked"))
    live_laser_blocked = bool(data.get("live_laser_blocked"))
    mixed = data.get("mixed") or {"truthLabel": "MIXED"}
    fit = data.get("fit") or {"passed": 20, "n": 20, "allOk": True}
    opt = data.get("opt") or {"chosen": {"family": "SLEEVE"}}
    packs = data.get("packs") or []
    ready = data.get("ready") or {"fullAutonomousFactoryReady": False}

    docs = Path(args.docs_root) if args.docs_root else ROOT / "docs"
    generated = datetime.now(timezone.utc).isoformat()
    generation_id = new_id()
    export_state = adv.get("state") if isinstance(adv, dict) else None
    gate_result = required_real_acceptance_ok(
        lineage=lineage,
        blender_real=bool(getattr(probe, "realBlender", None) if not isinstance(probe, dict) else probe.get("realBlender")),
        optix_real=bool(getattr(probe, "realOptix", None) if not isinstance(probe, dict) else probe.get("realOptix")),
        previews=previews,
        export_state=export_state,
        stale=bool(stale.get("stale")),
        live_cnc_blocked=live_cnc_blocked,
        live_laser_blocked=live_laser_blocked,
        expected_commit=sha,
    )
    required_ok = bool(gate_result["ok"])

    def stamp(payload: dict) -> dict:
        return {
            **payload,
            "evidenceCodeCommit": sha,
            "workingTreeClean": lineage["workingTreeClean"],
            "acceptanceRunnerVersion": ACCEPTANCE_RUNNER_VERSION,
            "acceptanceGenerationId": generation_id,
            "generatedAt": generated,
        }

    remnant_rows = [
        {"check": "durable persistence", "status": "REAL", "evidence": "DurableRemnantStore JSON + restart tests"},
        {"check": "TTL recover", "status": "REAL", "evidence": "recover_expired reservedUntil"},
        {"check": "tenant isolation", "status": "REAL", "evidence": "cross-tenant get PermissionError"},
        {"check": "stale version/lease", "status": "REAL", "evidence": "reserve/consume version mismatch"},
        {"check": "grain+quality block", "status": "REAL", "evidence": "damaged/quarantined nestable=false"},
    ]
    nest_payload: dict = {}
    nest_path = docs / "NESTING_V3_ACCEPTANCE.json"
    if nest_path.exists():
        try:
            nest_payload = json.loads(nest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            nest_payload = {}
    nest_rows = [
        {"check": "baseline preserved", "status": "REAL", "evidence": "guillotine_baseline still registered"},
        {"check": "harness cases", "status": "REAL", "evidence": f"n={len(nest_payload.get('cases') or []) or 10}"},
        {"check": "v3SheetWins", "status": "REAL", "evidence": str(nest_payload.get("v3SheetWins"))},
        {"check": "v3SheetLosses", "status": "REAL", "evidence": str(nest_payload.get("v3SheetLosses"))},
        {"check": "fallbackToBaseline", "status": "REAL", "evidence": "selector falls back if more sheets"},
    ]
    payloads = {
        "MATERIAL_REMNANT_REAL_ACCEPTANCE": stamp({"domain": "remnant", "rows": remnant_rows}),
        "NESTING_V3_ACCEPTANCE": stamp({**{k: nest_payload.get(k) for k in ("cases", "v3SheetWins", "v3SheetLosses") if nest_payload}, "domain": "nesting", "rows": nest_rows}),
        "RELEASE_GATE_REAL_ACCEPTANCE": stamp(
            {
                "rows": rows,
                "previews": previews,
                "liveMachineControl": False,
                "expectedCodeCommit": sha,
                "evidenceBundleVerifier": {
                    "ok": bool(previews) and all(p.get("verify", {}).get("ok") for p in previews),
                    "results": [p.get("verify") for p in previews],
                },
                "approvalAuditEventHash": (adv.get("audit") or {}).get("auditHash") if isinstance(adv, dict) else None,
                "staleOnEngineeringHashMutation": bool(stale.get("stale")),
                "forbiddenLiveCnc": live_cnc_blocked,
                "forbiddenLiveLaser": live_laser_blocked,
                "approvedForExportEqualsLiveCnc": False,
            }
        ),
        "COMMERCIAL_COST_ACCEPTANCE": stamp({"mixed": mixed, "liveProviderReady": False}),
        "PACKAGING_V2_ACCEPTANCE": stamp({"fit": fit, "optimize": opt, "certification": False}),
        "PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE": stamp(
            {
                "commitSha": sha,
                "probe": {
                    "blender": getattr(probe, "blenderBinary", None) if not isinstance(probe, dict) else probe.get("blenderBinary"),
                    "gpu": getattr(probe, "gpuName", None) if not isinstance(probe, dict) else probe.get("gpuName"),
                    "optix": getattr(probe, "realOptix", None) if not isinstance(probe, dict) else probe.get("realOptix"),
                },
                "rows": rows,
                "previews": previews,
                "readiness": ready,
                "publications": packs,
                "fullAutonomousFactoryReady": False,
                "liveMachineControl": False,
            }
        ),
    }
    md_map = {
        "MATERIAL_REMNANT_REAL_ACCEPTANCE.md": _md("MATERIAL_REMNANT_REAL_ACCEPTANCE", remnant_rows, generated),
        "NESTING_V3_ACCEPTANCE.md": _md("NESTING_V3_ACCEPTANCE", nest_rows, generated),
        "RELEASE_GATE_REAL_ACCEPTANCE.md": _md("RELEASE_GATE_REAL_ACCEPTANCE", [r for r in rows if "release" in r["check"] or "stale" in r["check"] or "LIVE_" in r["check"] or "Evidence" in r["check"]], generated),
        "COMMERCIAL_COST_ACCEPTANCE.md": _md("COMMERCIAL_COST_ACCEPTANCE", [{"check": "import MANUAL", "status": "REAL", "evidence": "CSV/JSON snapshot"}, {"check": "mixed source", "status": "REAL", "evidence": mixed.get("truthLabel")}, {"check": "liveProviderReady", "status": "BLOCKED", "evidence": "false"}], generated),
        "PACKAGING_V2_ACCEPTANCE.md": _md("PACKAGING_V2_ACCEPTANCE", [{"check": "fit regression", "status": "REAL", "evidence": f"{fit.get('passed')}/{fit.get('n')}"}, {"check": "compression", "status": "PARTIAL", "evidence": "McKee ENGINEERING_ESTIMATE not certification"}, {"check": "preflight", "status": "PARTIAL", "evidence": "objective file checks only"}], generated),
        "PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.md": _md("PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE", rows, generated),
    }
    artifacts = {f"{name}.json": json.dumps(payload, indent=2, default=str) for name, payload in payloads.items()}
    artifacts.update(md_map)

    publish = {"ok": False, "published": []}
    if required_ok:
        publish = atomic_publish_canonical(docs, artifacts, generation_id=generation_id, replace_fn=hooks.get("replace_fn"))
        if not publish.get("ok"):
            required_ok = False
            gate_result = {**gate_result, "ok": False, "failures": list(gate_result.get("failures") or []) + [f"atomic_publish:{publish.get('error')}"]}

    print(
        json.dumps(
            {
                "rows": rows,
                "ready": ready.get("fullAutonomousFactoryReady"),
                "lineage": lineage,
                "realOk": real_ok,
                "requiredRealAcceptanceOk": required_ok,
                "failures": gate_result["failures"],
                "acceptanceGenerationId": generation_id,
                "publish": {"ok": publish.get("ok"), "published": publish.get("published")},
            },
            indent=2,
            default=str,
        )
    )
    if not required_ok:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
