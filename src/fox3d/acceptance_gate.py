"""Fail-closed REAL acceptance gate. Canonical truth files are written only on full PASS."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

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
    """Compat helper: JSON-only atomic publish when the gate passed."""
    if not ok:
        return []
    artifacts = {f"{name}.json": json.dumps(payload, indent=2, default=str) for name, payload in files.items()}
    result = atomic_publish_canonical(docs, artifacts, generation_id=str((next(iter(files.values()), {}) or {}).get("acceptanceGenerationId") or "compat"))
    return result.get("published") or []


def atomic_publish_canonical(
    docs: Path,
    artifacts: dict[str, str],
    *,
    generation_id: str,
    replace_fn: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Stage all canonical files, then os.replace each. Rollback on any failure.

    artifacts maps filename (e.g. PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.json) to full text.
    """
    replace = replace_fn or os.replace
    docs.mkdir(parents=True, exist_ok=True)
    staging = docs / f".acceptance-staging-{generation_id}"
    backup = docs / f".acceptance-backup-{generation_id}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    backup.mkdir(parents=True, exist_ok=True)
    published: list[str] = []
    try:
        for name, content in artifacts.items():
            (staging / name).write_text(content, encoding="utf-8")
        missing = [name for name in artifacts if not (staging / name).exists() or (staging / name).stat().st_size < 1]
        if missing:
            raise RuntimeError(f"staging incomplete: {missing}")
        for name in artifacts:
            canon = docs / name
            if canon.exists():
                (backup / name).write_bytes(canon.read_bytes())
        for name in artifacts:
            replace(str(staging / name), str(docs / name))
            published.append(name)
        return {"ok": True, "published": published, "generationId": generation_id}
    except Exception as exc:
        for name in published:
            b = backup / name
            canon = docs / name
            if b.exists():
                os.replace(str(b), str(canon))
            elif canon.exists():
                canon.unlink()
        return {"ok": False, "error": str(exc), "published": published, "rolledBack": True, "generationId": generation_id}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def generations_consistent(docs: Path, names: list[str], *, generation_id: str, evidence_commit: str) -> dict[str, Any]:
    errors: list[str] = []
    for name in names:
        path = docs / f"{name}.json"
        if not path.exists():
            errors.append(f"missing:{name}")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("acceptanceGenerationId") != generation_id:
            errors.append(f"generation_mismatch:{name}")
        if payload.get("evidenceCodeCommit") != evidence_commit:
            errors.append(f"commit_mismatch:{name}")
    return {"ok": not errors, "errors": errors}
