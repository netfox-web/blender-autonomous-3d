"""Production REAL E2E runner. Never records mock as PASS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fox3d.blender import BLOCKED_NO_BLENDER, BLOCKED_NO_OPTIX, probe_host
from fox3d.platform import Platform


def _row(name: str, status: str, evidence: str) -> dict[str, str]:
    return {"check": name, "status": status, "evidence": evidence}


def _is_real_pass(job: dict[str, Any]) -> bool:
    out = job.get("output") or {}
    return bool(
        job.get("status") in {"completed", "succeeded"}
        and (job.get("realBlender") or out.get("realBlender"))
        and (job.get("realOptix") or out.get("realOptix"))
        and (job.get("realRenderOutput") or out.get("realRenderOutput"))
        and not (job.get("usedMock") or out.get("usedMock"))
    )


def run_real_acceptance(root: Path | None = None) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[2]
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    plat = Platform(root=root / ".fox3d-data", mock_blender=False)
    probe = plat.register_detected_workers()
    rows: list[dict[str, str]] = []

    rows.append(
        _row(
            "Blender executable",
            "REAL" if probe.realBlender else "BLOCKED",
            probe.blenderBinary or BLOCKED_NO_BLENDER,
        )
    )
    rows.append(
        _row(
            "blender --version",
            "REAL" if probe.blenderVersion and probe.realBlender else "BLOCKED",
            str(probe.blenderVersion or BLOCKED_NO_BLENDER),
        )
    )
    rows.append(
        _row(
            "NVIDIA GPU / VRAM",
            "REAL" if probe.realGPU else "BLOCKED",
            f"{probe.gpuName} {probe.vramGb}GB driver={probe.driver}",
        )
    )
    rows.append(
        _row(
            "Cycles devices",
            "REAL" if probe.realCycles else "BLOCKED",
            json.dumps(probe.cyclesDevices)[:500] or "no cycles probe",
        )
    )
    rows.append(
        _row(
            "OptiX",
            "REAL" if probe.realOptix else "BLOCKED",
            "realOptix=true" if probe.realOptix else BLOCKED_NO_OPTIX,
        )
    )

    smoke = plat.real_smoke_test()
    rows.append(
        _row(
            "REAL_SMOKE_TEST (cube/plane/camera/3-point/Cycles/OptiX/512 PNG)",
            "REAL" if _is_real_pass(smoke) else ("BLOCKED" if smoke.get("status") == "blocked" else "FAIL"),
            f"status={smoke.get('status')} error={smoke.get('error')} blender={smoke.get('blenderVersion')} device={(smoke.get('output') or {}).get('device')} mock={smoke.get('usedMock')}",
        )
    )

    product = plat.product_e2e(tenant_id="ops", sku="E2E-PRODUCT")
    product_job = product.get("job") or product
    rows.append(
        _row(
            "PRODUCT_E2E WHITE_STUDIO",
            "REAL" if _is_real_pass(product_job) else ("BLOCKED" if product_job.get("status") == "blocked" else "FAIL"),
            f"status={product_job.get('status')} error={product_job.get('error')} preview={(product.get('twin') or {}).get('previewAssetId')}",
        )
    )

    twin_id = (product.get("twin") or {}).get("twinId")
    if twin_id and _is_real_pass(product_job):
        p360 = plat.product_360_e2e(tenant_id="ops", twin_id=twin_id, frames=36)
        j360 = p360.get("job") or p360
        rows.append(
            _row(
                "PRODUCT_360_E2E 36 frames",
                "REAL" if j360.get("status") in {"completed", "succeeded"} and not j360.get("usedMock") else (
                    "BLOCKED" if j360.get("status") == "blocked" else "FAIL"
                ),
                f"status={j360.get('status')} frames={(j360.get('output') or {}).get('files')}",
            )
        )
    else:
        rows.append(_row("PRODUCT_360_E2E 36 frames", "BLOCKED", "skipped: product e2e not REAL"))

    cab = plat.create_parametric(
        {
            "tenantId": "ops",
            "kind": "STORAGE_CABINET",
            "width": 800,
            "height": 1800,
            "depth": 400,
            "boardThickness": 18,
            "shelfCount": 4,
            "doorCount": 2,
        }
    )
    pid = cab["spec"]["productId"]
    cab_render = plat.render_parametric(pid, tenant_id="ops")
    rows.append(
        _row(
            "PARAMETRIC STORAGE_CABINET 800x1800x400",
            "REAL" if _is_real_pass(cab_render.get("job") or {}) else (
                "BLOCKED" if (cab_render.get("job") or cab_render).get("status") == "blocked" or probe.blocked else "MOCK"
            ),
            f"hash={cab['engineeringHash']} job={(cab_render.get('job') or {}).get('status')}",
        )
    )
    resized = plat.resize_parametric(pid, tenant_id="ops", width=1200)
    assert resized["engineeringHash"] != cab["engineeringHash"]
    top_800 = next(p for p in cab["spec"]["components"] if p["partName"] == "TOP")
    top_1200 = next(p for p in resized["spec"]["components"] if p["partName"] == "TOP")
    bom_sync = top_800["length"] != top_1200["length"] or top_800.get("width") != top_1200.get("width")
    rows.append(
        _row(
            "Cabinet resize 800→1200 geometry+BOM sync",
            "REAL" if bom_sync else "FAIL",
            f"top800={top_800} top1200={top_1200} bomHashChanged={resized['engineeringHash'] != cab['engineeringHash']}",
        )
    )
    resize_render = plat.render_parametric(resized["spec"]["productId"], tenant_id="ops")
    rows.append(
        _row(
            "Cabinet resize rebuild render",
            "REAL" if _is_real_pass(resize_render.get("job") or {}) else (
                "BLOCKED" if (resize_render.get("job") or {}).get("status") == "blocked" or probe.blocked else "FAIL"
            ),
            f"status={(resize_render.get('job') or {}).get('status')}",
        )
    )

    explode = plat.render_parametric(resized["spec"]["productId"], tenant_id="ops", explode=True)
    rows.append(
        _row(
            "Exploded view / assembly placeholders",
            "REAL" if _is_real_pass(explode.get("job") or {}) else (
                "BLOCKED" if (explode.get("job") or {}).get("status") == "blocked" or probe.blocked else "FAIL"
            ),
            f"status={(explode.get('job') or {}).get('status')}",
        )
    )

    nl = plat.product_rd(
        tenant_id="ops",
        text="幫我做一個寬120公分、高180公分、深40公分，雙門、4層板、白色木紋收納櫃",
        variant_count=10,
    )
    rows.append(
        _row(
            "NL furniture → DesignIntent → validate → BOM → cost",
            "REAL" if nl.get("baseSpec") and nl.get("approval", {}).get("status") == "WAITING_APPROVAL" else "FAIL",
            f"kind={nl.get('intent', {}).get('kind')} width={nl.get('baseSpec', {}).get('width')} llmDirectManufacturing=false",
        )
    )

    required = (
        "Blender executable",
        "blender --version",
        "NVIDIA GPU / VRAM",
        "OptiX",
        "REAL_SMOKE_TEST (cube/plane/camera/3-point/Cycles/OptiX/512 PNG)",
        "PRODUCT_E2E WHITE_STUDIO",
    )
    by_name = {r["check"]: r["status"] for r in rows}
    production_ready = all(by_name.get(name) == "REAL" for name in required) and not any(
        r["status"] == "FAIL" for r in rows
    )
    report = {
        "productionReady": production_ready,
        "probe": probe.to_dict(),
        "rows": rows,
        "note": "MOCK rows are test-only. BLOCKED is not a pass. Do not ship as Production Ready unless REAL_SMOKE_TEST and PRODUCT_E2E are REAL.",
    }
    md = ["# REAL_E2E_ACCEPTANCE", "", f"productionReady: **{production_ready}**", "", "| Check | Status | Evidence |", "|---|---|---|"]
    for row in rows:
        ev = row["evidence"].replace("|", "\\|").replace("\n", " ")[:400]
        md.append(f"| {row['check']} | {row['status']} | `{ev}` |")
    md.extend(
        [
            "",
            "## Flags",
            f"- realBlender: {probe.realBlender}",
            f"- realGPU: {probe.realGPU}",
            f"- realCycles: {probe.realCycles}",
            f"- realOptix: {probe.realOptix}",
            f"- blocked: {probe.blocked}",
            "",
            "Mock Worker 僅供 `pytest`。Production acceptance 不得把 mock-4.2 寫成 PASS。",
        ]
    )
    (docs / "REAL_E2E_ACCEPTANCE.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (docs / "REAL_E2E_ACCEPTANCE.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
