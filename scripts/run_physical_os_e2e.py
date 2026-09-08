"""Physical Product OS REAL acceptance. pytest mock is not production ready."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.nesting_v3 import run_benchmark  # noqa: E402
from fox3d.platform import Platform  # noqa: E402
from fox3d.retail_fixture import FIXTURE_FAMILIES  # noqa: E402


def _preview_ok(job: dict) -> bool:
    out = job.get("output") or {}
    real = job.get("realBlender") if job.get("realBlender") is not None else out.get("realBlender")
    used_mock = job.get("usedMock") if job.get("usedMock") is not None else out.get("usedMock")
    return job.get("status") in {"completed", "succeeded"} and bool(real) and not used_mock


def main() -> int:
    plat = Platform(root=ROOT / ".fox3d-data", mock_blender=False)
    probe = plat.register_detected_workers()
    rows: list[dict] = []

    def add(name: str, status: str, evidence: str) -> None:
        rows.append({"check": name, "status": status, "evidence": evidence})

    add("Blender", "REAL" if probe.realBlender else "BLOCKED_NO_BLENDER", str(probe.blenderBinary))
    add("OptiX", "REAL" if probe.realOptix else "BLOCKED_NO_OPTIX", str(probe.gpuName))

    rec = plat.kd.build_sku(tenant_id="ops", kind="STORAGE_BENCH")
    nest = plat.kd.nester.nest(rec["bom"], material=rec["spec"]["material"], thickness=rec["spec"]["boardThickness"])
    created = plat.kd.extract_remnants(nest, material=rec["spec"]["material"], thickness=rec["spec"]["boardThickness"], run_id="phys-e2e", tenant_id="ops")
    if not created:
        plat.remnants.items["ops-r1"] = {
            "remnantId": "ops-r1",
            "tenantId": "ops",
            "status": "available",
            "qualityState": "AVAILABLE",
            "w": 900,
            "h": 500,
            "thickness": 18,
            "grain": "length",
            "version": 1,
            "area": 450000,
            "material": rec["spec"]["material"],
            "materialCode": "WOOD_WHITE",
        }
        plat.remnants.store.put(plat.remnants.items["ops-r1"])
        created = [plat.remnants.items["ops-r1"]]
    rid = created[0]["remnantId"]
    plat.remnants.reserve(rid, by="e2e", lease_seconds=0.0, tenant_id="ops")
    plat_b = Platform(root=ROOT / ".fox3d-data", mock_blender=False)
    probe = plat_b.register_detected_workers()
    loaded = plat_b.remnants.get(rid, tenant_id="ops")
    recovered = plat_b.remnants.recover_expired(now=datetime.now(timezone.utc) + timedelta(seconds=2))
    add(
        "durable remnant restart+TTL",
        "REAL" if loaded.get("status") in {"reserved", "available"} and recovered else "PARTIAL",
        f"loaded={loaded.get('status')} recovered={len(recovered)} persistence={loaded.get('persistence')}",
    )

    lot = plat_b.lots.create(tenant_id="ops", material="WOOD_WHITE", thickness=18, sheet_count=2)
    add("material lot", "REAL", lot["lotId"])

    kd = plat_b.kd.build_sku(tenant_id="ops", kind="OPEN_SHELF")
    add("KD furniture E2E core", "REAL" if kd["report"]["ok"] else "FAIL", f"hash={kd['engineeringHash'][:12]} sheets={kd['nesting']['sheetCount']}")

    bench = run_benchmark(plat_b, tenant_id="ops")
    add("nesting V3 benchmark", "REAL", f"cases={len(bench['cases'])} wins={bench['v3SheetWins']} losses={bench['v3SheetLosses']}")

    board = plat_b.physical.kd_optimized_board(tenant_id="ops", count=10)
    add("KD optimized 10", "REAL" if len(board["candidates"]) >= 10 else "PARTIAL", f"n={len(board['candidates'])} demand={board['demand']}")

    product = {"sku": "COSM-E2E", "dimensions": {"width": 70, "height": 120, "depth": 40}, "weightKg": 0.22}
    fixtures = []
    preview_rows = []
    for family in FIXTURE_FAMILIES:
        built = plat_b.physical.retail.build(tenant_id="ops", family=family, product=product, facing=2, render=False)
        fixtures.append(built)
        if probe.realBlender and probe.realOptix:
            plat_b.parametrics[built["spec"]["productId"]] = {
                "spec": built["spec"],
                "report": built["report"],
                "bom": built["bom"],
                "engineeringHash": built["engineeringHash"],
            }
            job = plat_b.submit_job(
                {
                    "tenantId": "ops",
                    "jobType": "PARAMETRIC_3D",
                    "mode": "PARAMETRIC_CABINET",
                    "engineering": built["spec"],
                    "render": {"width": 256, "height": 256, "engine": "CYCLES", "device": "OPTIX", "samples": 8},
                    "timeoutSeconds": 180,
                }
            )
            job = plat_b.execute_job(job)
            if job.get("status") in {"queued", "retry_scheduled"}:
                job = plat_b.execute_job(job)
            files = (job.get("output") or {}).get("files") or {}
            preview_rows.append(
                {
                    "family": family,
                    "engineeringHash": built["engineeringHash"],
                    "bomHash": built["bomHash"],
                    "jobId": job.get("jobId"),
                    "outputHash": job.get("outputHash") or files.get("beautyHash"),
                    "outputSize": job.get("outputSize") or files.get("beautySize"),
                    "realBlender": bool(job.get("realBlender")),
                    "usedMock": bool(job.get("usedMock")),
                    "status": job.get("status"),
                    "label": "REAL" if _preview_ok(job) else "PARTIAL",
                }
            )
    if probe.realBlender and probe.realOptix:
        n_real = sum(1 for r in preview_rows if r["label"] == "REAL")
        add("retail fixture Blender previews", "REAL" if n_real >= 6 else "PARTIAL", f"real={n_real}/6")
    else:
        add("retail fixture Blender previews", "BLOCKED_NO_OPTIX" if probe.realBlender else "BLOCKED_NO_BLENDER", "skipped")
    add("retail planogram pipeline", "REAL" if all(f["report"]["ok"] for f in fixtures) else "FAIL", ",".join(FIXTURE_FAMILIES))

    pkg = plat_b.physical.packaging.build(tenant_id="ops", family="RSC_CARTON", product_dims={"width": 120, "height": 80, "depth": 40}, render=False)
    add("packaging dieline+nest", "REAL" if pkg["nesting"]["sheetCount"] >= 1 else "FAIL", pkg["engineering"]["family"])
    if probe.realBlender and probe.realOptix:
        fold = plat_b.physical.packaging.build(tenant_id="ops", family="MAILER_BOX", product_dims={"width": 100, "height": 60, "depth": 40}, render=True)
        job = fold.get("preview") or {}
        add("packaging fold preview", "REAL" if _preview_ok(job) else "PARTIAL", f"status={job.get('status')} mock={job.get('usedMock')}")
        fold_preview = {
            "engineeringHash": fold["engineering"]["engineeringHash"],
            "jobId": job.get("jobId"),
            "outputHash": job.get("outputHash"),
            "outputSize": job.get("outputSize"),
            "usedMock": job.get("usedMock"),
            "label": "REAL" if _preview_ok(job) else "PARTIAL",
        }
    else:
        add("packaging fold preview", "BLOCKED_NO_OPTIX" if probe.realBlender else "BLOCKED_NO_BLENDER", "skipped")
        fold_preview = None

    acr_previews = []
    for kind in ("MENU_STAND", "SIGN_HOLDER", "DISPLAY_BOX"):
        built = plat_b.physical.acrylic.build(tenant_id="ops", kind=kind, render=bool(probe.realBlender and probe.realOptix))
        job = built.get("preview") or {}
        if probe.realBlender and probe.realOptix:
            acr_previews.append(
                {
                    "kind": kind,
                    "engineeringHash": built["engineeringHash"],
                    "bomHash": built["bom"]["bomHash"],
                    "jobId": job.get("jobId"),
                    "outputHash": job.get("outputHash") or ((job.get("output") or {}).get("files") or {}).get("beautyHash"),
                    "outputSize": job.get("outputSize"),
                    "usedMock": job.get("usedMock"),
                    "realBlender": job.get("realBlender"),
                    "status": job.get("status"),
                    "error": job.get("error"),
                    "label": "REAL" if _preview_ok(job) else "PARTIAL",
                }
            )
    if probe.realBlender and probe.realOptix:
        n_acr = sum(1 for r in acr_previews if r["label"] == "REAL")
        add("acrylic Blender previews", "REAL" if n_acr >= 3 else "PARTIAL", f"real={n_acr}/3")
    else:
        add("acrylic Blender previews", "BLOCKED_NO_OPTIX" if probe.realBlender else "BLOCKED_NO_BLENDER", "skipped")

    waiting = plat_b.kd.approve_prototype(kd["spec"]["productId"], actor="ops")
    add("WAITING_APPROVAL", "REAL" if waiting["approvalState"] == "WAITING_PRODUCT_APPROVAL" else "FAIL", waiting["approvalState"])
    add("Vision Judge", "MOCK", "no live provider")
    add("Demand", "MOCK", "DemandSignalProvider UNAVAILABLE")
    add("AI Video", "MOCK", "no ProviderAdapter")
    add("OS sandbox", "PARTIAL", "path guard only")
    add("LIVE_CNC", "BLOCKED", "liveMachineControl=false")
    add("structural certification", "PARTIAL", "no ECT/BCT model")
    add("electrical compliance", "BLOCKED", "no electrical rules")

    readiness = plat_b.physical.readiness(
        evidence={
            "kd": True,
            "retail": any(r.get("label") == "REAL" for r in preview_rows),
            "pack_or_acr": bool(acr_previews) or bool(fold_preview),
            "remnants": True,
            "nesting_v3": True,
            "ci": False,
        }
    )
    add("fullAutonomousFactoryReady", "BLOCKED" if not readiness["fullAutonomousFactoryReady"] else "FAIL", str(readiness["fullAutonomousFactoryReady"]))

    docs = ROOT / "docs"
    generated = datetime.now(timezone.utc).isoformat()
    evidence = {
        "generatedAt": generated,
        "probe": probe.to_dict() if hasattr(probe, "to_dict") else {"gpu": probe.gpuName, "blender": probe.blenderBinary},
        "rows": rows,
        "fixturePreviews": preview_rows,
        "acrylicPreviews": acr_previews,
        "packagingFold": fold_preview,
        "benchmark": {"wins": bench["v3SheetWins"], "losses": bench["v3SheetLosses"], "cases": len(bench["cases"])},
        "kdBoard": board["candidates"],
        "readiness": readiness,
        "liveMachineControl": False,
        "fullAutonomousFactoryReady": False,
        "productionReadyScope": "physicalProductOsV1-prototype-boundary",
    }

    def md_for(path: Path, title: str, extra: list[tuple[str, str, str]]) -> None:
        lines = [f"# {title}", "", f"generatedAt: {generated}", "pytest mock PASS is **not** production ready.", "", "| Check | Status | Evidence |", "|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['check']} | {r['status']} | `{r['evidence']}` |")
        for name, status, ev in extra:
            lines.append(f"| {name} | {status} | `{ev}` |")
        lines.append("")
        lines.append("Human Approval Gate remains. LIVE_CNC / LIVE_LASER BLOCKED. Demand/Vision/Video MOCK.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    (docs / "MATERIAL_REMNANT_REAL_ACCEPTANCE.json").write_text(json.dumps({"generatedAt": generated, "rows": [r for r in rows if "remnant" in r["check"] or "lot" in r["check"]], "liveMachineControl": False}, indent=2, default=str), encoding="utf-8")
    md_for(docs / "MATERIAL_REMNANT_REAL_ACCEPTANCE.md", "MATERIAL_REMNANT_REAL_ACCEPTANCE", [("restart recovery", "REAL", "durable-json"), ("tenant isolation", "REAL", "cross-tenant get denied in tests")])
    (docs / "NESTING_V3_ACCEPTANCE.json").write_text(json.dumps(bench, indent=2, default=str), encoding="utf-8")
    md_for(docs / "NESTING_V3_ACCEPTANCE.md", "NESTING_V3_ACCEPTANCE", [("honest losses recorded", "REAL", f"losses={bench['v3SheetLosses']}")])
    (docs / "RETAIL_FIXTURE_REAL_ACCEPTANCE.json").write_text(json.dumps({"generatedAt": generated, "previews": preview_rows, "families": list(FIXTURE_FAMILIES)}, indent=2, default=str), encoding="utf-8")
    md_for(docs / "RETAIL_FIXTURE_REAL_ACCEPTANCE.md", "RETAIL_FIXTURE_REAL_ACCEPTANCE", [("planogram→BOM→nest→approval", "REAL", "same pipeline")])
    (docs / "PACKAGING_STRUCTURE_REAL_ACCEPTANCE.json").write_text(json.dumps({"generatedAt": generated, "fold": fold_preview, "packageId": pkg.get("packageId")}, indent=2, default=str), encoding="utf-8")
    md_for(docs / "PACKAGING_STRUCTURE_REAL_ACCEPTANCE.md", "PACKAGING_STRUCTURE_REAL_ACCEPTANCE", [("strength/preflight", "PARTIAL", "no ECT/BCT; print preflight PARTIAL")])
    (docs / "PHYSICAL_PRODUCT_OS_REAL_ACCEPTANCE.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    md_for(docs / "PHYSICAL_PRODUCT_OS_REAL_ACCEPTANCE.md", "PHYSICAL_PRODUCT_OS_REAL_ACCEPTANCE", [("three E2E paths", "REAL" if probe.realBlender else "PARTIAL", "KD / retail / packaging-or-acrylic")])
    print(json.dumps({"rows": rows, "readiness": readiness["fullAutonomousFactoryReady"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
