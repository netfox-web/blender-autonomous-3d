"""Fail-closed REAL acceptance gate. Canonical truth files are written only on full PASS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_PREVIEW_COUNT = 5
CANONICAL_REAL_FILES = (
    "PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE",
    "RELEASE_GATE_REAL_ACCEPTANCE",
    "COMMERCIAL_COST_ACCEPTANCE",
    "PACKAGING_V2_ACCEPTANCE",
    "MATERIAL_REMNANT_REAL_ACCEPTANCE",
    "NESTING_V3_ACCEPTANCE",
)


def required_real_acceptance_ok(
    *,
    lineage: dict[str, Any],
    blender_real: bool,
    optix_real: bool,
    previews: list[dict[str, Any]],
    export_state: str | None,
    stale: bool,
    live_cnc_blocked: bool,
    live_laser_blocked: bool,
    expected_commit: str,
) -> dict[str, Any]:
    failures: list[str] = []
    if not lineage.get("workingTreeClean"):
        failures.append("working_tree_dirty")
    if not lineage.get("realAcceptanceAllowed"):
        failures.append("real_acceptance_not_allowed")
    if not blender_real:
        failures.append("blender_not_real")
    if not optix_real:
        failures.append("optix_not_real")
    if len(previews) != REQUIRED_PREVIEW_COUNT:
        failures.append(f"preview_count_{len(previews)}")
    for i, preview in enumerate(previews):
        if preview.get("label") != "REAL":
            failures.append(f"preview_{i}_not_real")
        ver = preview.get("verify") or {}
        if not ver.get("ok"):
            failures.append(f"preview_{i}_verify_fail:{','.join(ver.get('errors') or [])}")
        bun = preview.get("bundle") or {}
        if bun.get("commitSha") != expected_commit:
            failures.append(f"preview_{i}_commit_mismatch")
        if bun.get("usedMock") or preview.get("usedMock"):
            failures.append(f"preview_{i}_used_mock")
        if not (bun.get("realBlender") or preview.get("realBlender")):
            failures.append(f"preview_{i}_not_real_blender")
    if export_state != "APPROVED_FOR_EXPORT":
        failures.append("export_gate_failed")
    if not stale:
        failures.append("approval_not_stale")
    if not live_cnc_blocked:
        failures.append("live_cnc_not_blocked")
    if not live_laser_blocked:
        failures.append("live_laser_not_blocked")
    return {"ok": not failures, "failures": failures}


def write_canonical_if_ok(docs: Path, files: dict[str, dict[str, Any]], *, ok: bool) -> list[str]:
    """Write canonical REAL JSON only when the gate passed. Never overwrite on failure."""
    if not ok:
        return []
    docs.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, payload in files.items():
        path = docs / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        written.append(str(path))
    return written
