"""Real furniture-factory acceptance. Never treats mock pytest as production ready."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.blender import BLOCKED_NO_BLENDER, BLOCKED_NO_OPTIX  # noqa: E402
from fox3d.platform import Platform  # noqa: E402


def _label(ok: bool, real: bool, blocked: str | None = None) -> str:
    if blocked:
        return blocked
    if ok and real:
        return "REAL"
    if ok:
        return "PARTIAL"
    return "FAIL"


def main() -> int:
    plat = Platform(root=ROOT / ".fox3d-data", mock_blender=False)
    probe = plat.register_detected_workers()
    rows: list[dict] = []

    def add(name: str, status: str, evidence: str) -> None:
        rows.append({"check": name, "status": status, "evidence": evidence})

    add("Blender", "REAL" if probe.realBlender else BLOCKED_NO_BLENDER, str(probe.blenderBinary or probe.blenderVersion))
    add("GPU", "REAL" if probe.realGPU else "MISSING", f"{probe.gpuName} {probe.vramGb}GB")
    add("OptiX", "REAL" if probe.realOptix else BLOCKED_NO_OPTIX, str(probe.cyclesDevices)[:200])

    run = plat.furniture_factory_run(tenant_id="ops", render=bool(probe.realBlender and probe.realOptix), text="360cm 牆做收納櫃")
    add("3600mm wall space twin", "REAL", f"wall={run['space']['wallLength']} hash={run['space']['spaceHash'][:12]}")
    add("layout candidates", "REAL" if run["legalLayoutCount"] >= 3 else "PARTIAL", f"legal={run['legalLayoutCount']} total={len(run['layouts'])}")
    add("multi-cabinet assembly", "REAL" if run["assembly"]["cabinetCount"] >= 2 else "PARTIAL", f"count={run['assembly']['cabinetCount']} hash={run['assembly']['assemblyHash'][:12]}")
    add("BOM", "REAL", f"lines={len(run['bom']['lines'])} bomHash={run['bom']['bomHash'][:12]}")
    add("nesting", "REAL" if run["nesting"]["sheetCount"] >= 1 else "FAIL", f"sheets={run['nesting']['sheetCount']} util={run['nesting'].get('utilization')} wasteM2={run['nesting'].get('wasteAreaM2')}")
    add("quote", "REAL", f"price={run['quote']['suggestedPrice']} quoteHash={run['quote']['quoteHash'][:12]}")
    preview = run.get("preview") or {}
    preview_status = preview.get("status")
    real_preview = bool(preview.get("realBlender") and preview_status in {"completed", "succeeded"})
    blocked = preview.get("error") if preview.get("error") in {BLOCKED_NO_BLENDER, BLOCKED_NO_OPTIX} else None
    add("Blender space preview", _label(real_preview, bool(preview.get("realBlender")), blocked), f"status={preview_status} error={preview.get('error')} job={preview.get('jobId')}")
    add("WAITING_APPROVAL gate", "REAL" if run["gate"]["status"] == "WAITING_APPROVAL" else "FAIL", json.dumps(run["gate"]))
    add("liveMachineControl", "BLOCKED" if run["gate"]["liveMachineControl"] is False else "FAIL", "liveMachineControl=false")

    collision = plat.factory.collision_fixture(tenant_id="ops")
    add("door/window/column rejection", "REAL" if collision["doorRejected"] else "FAIL", json.dumps(collision["codes"]))

    ffmpeg = shutil.which("ffmpeg")
    asm_status = "PARTIAL"
    asm_evidence = "ffmpeg missing" if not ffmpeg else "not run"
    if probe.realBlender and probe.realOptix:
        created = plat.create_parametric({"tenantId": "ops", "kind": "STORAGE_CABINET", "width": 800, "height": 1800, "depth": 400, "doorCount": 2, "shelfCount": 3})
        job = plat.submit_job(
            {
                "tenantId": "ops",
                "jobType": "ASSEMBLY_ANIM",
                "mode": "ASSEMBLY_ANIM",
                "engineering": created["spec"],
                "assemblyAnimation": True,
                "animation": {"frames": 6},
                "aovs": True,
                "aovVersion": 2,
                "render": {"width": 384, "height": 384, "engine": "CYCLES", "device": "OPTIX", "samples": 8},
                "timeoutSeconds": 600,
            }
        )
        anim = plat.execute_job(job)
        files = (anim.get("output") or {}).get("files") or {}
        if files.get("assembly.mp4"):
            asm_status = "REAL"
            asm_evidence = f"mp4={files.get('assembly.mp4')} ffmpeg={bool(ffmpeg)}"
        elif files.get("assemblyFrames"):
            asm_status = "PARTIAL"
            asm_evidence = f"png sequence only; ffmpeg={bool(ffmpeg)} job={anim.get('status')}"
        else:
            asm_status = "PARTIAL"
            asm_evidence = f"status={anim.get('status')} error={anim.get('error')} ffmpeg={bool(ffmpeg)}"
        aov_ok = all(files.get(n) for n in ("depth.png", "normal.png", "seg.png"))
        add("Cycles AOV depth/normal/seg", "REAL" if aov_ok and anim.get("realBlender") else "PARTIAL", f"files={list(files)[:12]}")
    else:
        add("Cycles AOV depth/normal/seg", blocked or "BLOCKED", "skipped; no real OptiX worker")
    add("assembly animation MP4", asm_status, asm_evidence)
    add("Vision Judge", "MOCK", "heuristic provider; no live vision adapter registered")
    add("AI Video", "MOCK", "no FoxStudio ProviderAdapter registered")
    add("OS sandbox", "PARTIAL", "path guard + SANDBOX ONLY, not OS jail")

    production_ready = probe.realBlender and probe.realOptix and real_preview and run["gate"]["status"] == "WAITING_APPROVAL"
    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "productionReady": bool(production_ready),
        "note": "productionReady is host real Blender/OptiX factory preview, not pytest mock",
        "probe": probe.to_dict() if hasattr(probe, "to_dict") else {},
        "runId": run.get("runId"),
        "assemblyHash": run["assembly"]["assemblyHash"],
        "spaceHash": run["space"]["spaceHash"],
        "quoteHash": run["quote"]["quoteHash"],
        "gate": run["gate"],
        "rows": rows,
    }
    docs = ROOT / "docs"
    (docs / "FURNITURE_FACTORY_REAL_ACCEPTANCE.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [
        "# FURNITURE_FACTORY_REAL_ACCEPTANCE",
        "",
        f"generatedAt: {report['generatedAt']}",
        f"productionReady: **{report['productionReady']}**",
        "",
        "3600mm wall → multi-cabinet layout → BOM → nesting → cost/quote → Blender space preview → WAITING_APPROVAL.",
        "pytest mock PASS is **not** production ready.",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
    ]
    for row in rows:
        ev = str(row["evidence"]).replace("|", "\\|")[:180]
        lines.append(f"| {row['check']} | {row['status']} | `{ev}` |")
    lines += [
        "",
        f"- runId: `{run.get('runId')}`",
        f"- spaceHash: `{run['space']['spaceHash']}`",
        f"- assemblyHash: `{run['assembly']['assemblyHash']}`",
        f"- quoteHash: `{run['quote']['quoteHash']}`",
        f"- gate: `{run['gate']['status']}` liveMachineControl=`{run['gate']['liveMachineControl']}`",
        "",
        "LIVE_CNC remains **BLOCKED**. Human Approval Gate is mandatory.",
    ]
    (docs / "FURNITURE_FACTORY_REAL_ACCEPTANCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"productionReady": report["productionReady"], "rows": rows}, indent=2, default=str))
    return 0 if production_ready else (3 if blocked else 1)


if __name__ == "__main__":
    raise SystemExit(main())
