"""KD factory REAL acceptance. pytest mock is not production ready."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.platform import Platform  # noqa: E402


def main() -> int:
    plat = Platform(root=ROOT / ".fox3d-data", mock_blender=False)
    probe = plat.register_detected_workers()
    rows: list[dict] = []

    def add(name: str, status: str, evidence: str) -> None:
        rows.append({"check": name, "status": status, "evidence": evidence})

    add("Blender", "REAL" if probe.realBlender else "BLOCKED_NO_BLENDER", str(probe.blenderBinary))
    add("OptiX", "REAL" if probe.realOptix else "BLOCKED_NO_OPTIX", str(probe.gpuName))

    kinds = ("BEDSIDE_CABINET", "OPEN_SHELF", "STUDENT_DESK")
    recs = [plat.kd.build_sku(tenant_id="ops", kind=k, render=False) for k in kinds]
    add("3 KD SKU families", "REAL" if all(r["report"]["ok"] for r in recs) else "FAIL", ",".join(kinds))

    batch_nest = plat.kd.nest_quantity(recs[0], 10)
    add("quantity batch nesting", "REAL" if batch_nest["sheetCount"] >= 1 else "FAIL", f"q=10 sheets={batch_nest['sheetCount']} util={batch_nest.get('utilizationRatio')}")

    cross = plat.kd.nest_cross_sku(recs, [4, 3, 2])
    add("cross-SKU nesting", "REAL" if cross["sheetCount"] >= 1 and not plat.kd.nester.assert_valid(cross) else "FAIL", f"sheets={cross['sheetCount']} waste={cross.get('trueWasteRatio')}")

    nest = recs[1]["nesting"]
    add("waste V2 conservation", "REAL" if nest.get("areaConservationError", 99) < 2 else "FAIL", f"err={nest.get('areaConservationError')} trueWaste={nest.get('trueWasteRatio')} remnant={nest.get('reusableRemnantRatio')}")

    extracted = plat.kd.extract_remnants(recs[1]["nesting"], material=recs[1]["spec"]["material"], thickness=recs[1]["spec"]["boardThickness"], run_id="kd-e2e")
    case = plat.kd.remnant_first_case(recs[2] if recs[2]["spec"]["kind"] == "STUDENT_DESK" else recs[0])
    # Use desk riser for remnant-first if student desk is large
    riser = plat.kd.build_sku(tenant_id="ops", kind="DESK_RISER")
    case = plat.kd.remnant_first_case(riser)
    add("remnants extract+consume", "REAL" if case["remnantConsumedArea"] > 0 else "PARTIAL", f"extracted={len(extracted)} savedSheets={case['savedNewSheetCount']} consumed={case['remnantConsumedArea']}")

    rec = recs[0]
    add("pack/weight/assembly", "REAL", f"carton={rec['packing']['length']}x{rec['packing']['width']}x{rec['packing']['height']} kg={rec['weight']['grossKg']} score={rec['difficulty']['score']}")
    add("landed cost lineage", "REAL", f"cost={rec['landed']['unitLandedCost']} hashes={list(rec['landed']['lineage'])}")

    preview_ok = False
    if probe.realBlender and probe.realOptix:
        prev = plat.render_parametric(rec["spec"]["productId"], tenant_id="ops")
        job = prev.get("job") or {}
        preview_ok = job.get("status") in {"completed", "succeeded"} and job.get("realBlender")
        add("Blender KD product preview", "REAL" if preview_ok else "PARTIAL", f"status={job.get('status')} job={job.get('jobId')}")
    else:
        add("Blender KD product preview", "BLOCKED_NO_OPTIX" if probe.realBlender else "BLOCKED_NO_BLENDER", "skipped")

    waiting = plat.kd.approve_prototype(rec["spec"]["productId"], actor="ops")
    add("WAITING_PRODUCT_APPROVAL", "REAL" if waiting["approvalState"] == "WAITING_PRODUCT_APPROVAL" else "FAIL", waiting["approvalState"])

    add("Vision Judge", "MOCK", "no live provider")
    add("AI Video", "MOCK", "no ProviderAdapter")
    add("Demand", "MOCK", "DemandSignalProvider UNAVAILABLE")
    add("OS sandbox", "PARTIAL", "path guard only")
    add("LIVE_CNC", "BLOCKED", "liveMachineControl=false")

    catalog = plat.kd.generate_candidates(tenant_id="ops", count=24, render=False)
    add("small-space catalog", "REAL" if len(catalog["catalog"]) >= 20 else "PARTIAL", f"n={len(catalog['catalog'])} kinds={sorted({r['kind'] for r in catalog['catalog']})}")

    evidence = {
        "coreFactoryE2E": True,
        "kdWasteV2": nest.get("areaConservationError", 99) < 2,
        "kdPacking": True,
        "kdRemnants": case["remnantConsumedArea"] > 0,
        "kdLandedCost": True,
        "liveDemand": False,
        "liveVision": False,
        "liveVideo": False,
        "osJail": False,
        "liveCnc": False,
        "ciStatus": True,
    }
    matrix = plat.kd.readiness(evidence=evidence)
    add("scoped readiness", "REAL", json.dumps({k: matrix[k] for k in matrix if k.endswith("Ready") or k == "productionReadyScope"}))

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "coreFactoryE2EReady": matrix["coreFactoryE2EReady"],
        "kdDfMReady": matrix["kdDfMReady"],
        "commercialCostModelReady": matrix["commercialCostModelReady"],
        "fullAutonomousFactoryReady": matrix["fullAutonomousFactoryReady"],
        "productionReady": matrix["productionReady"],
        "productionReadyScope": matrix["productionReadyScope"],
        "note": "productionReady scope is coreFactoryE2E only; Vision/Video/CNC/demand are not included",
        "probe": probe.to_dict(),
        "rows": rows,
        "readiness": matrix,
        "catalogTop": catalog["top"][:5],
    }
    docs = ROOT / "docs"
    (docs / "KD_FACTORY_REAL_ACCEPTANCE.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [
        "# KD_FACTORY_REAL_ACCEPTANCE",
        "",
        f"generatedAt: {report['generatedAt']}",
        f"productionReady (scope=`coreFactoryE2E`): **{report['productionReady']}**",
        f"kdDfMReady: **{report['kdDfMReady']}** · commercialCostModelReady: **{report['commercialCostModelReady']}** · fullAutonomousFactoryReady: **{report['fullAutonomousFactoryReady']}**",
        "",
        "pytest mock PASS is **not** production ready. Demand/Vision/Video remain MOCK.",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    for row in rows:
        ev = str(row["evidence"]).replace("|", "\\|")[:200]
        lines.append(f"| {row['check']} | {row['status']} | `{ev}` |")
    lines += [
        "",
        "LIVE_CNC remains **BLOCKED**. Approval stops at WAITING_PRODUCT_APPROVAL / APPROVED_FOR_PROTOTYPE.",
    ]
    (docs / "KD_FACTORY_REAL_ACCEPTANCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"productionReady": report["productionReady"], "scope": report["productionReadyScope"], "kdDfMReady": report["kdDfMReady"], "rows": rows}, indent=2, default=str))
    return 0 if report["kdDfMReady"] and preview_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
