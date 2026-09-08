"""Immutable EvidenceBundle + verifier. Markdown is not evidence."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow

ACCEPTANCE_RUNNER_VERSION = "os-v2-e2e-lineage-1"


class DirtyTreeError(RuntimeError):
    """REAL acceptance may not run on a dirty working tree."""


def evidence_bundle(
    *,
    commit_sha: str | None = None,
    job: dict[str, Any] | None = None,
    artifact_path: str | Path | None = None,
    engineering_hash: str | None = None,
    bom_hash: str | None = None,
    recipe_version: str | int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = job or {}
    path = Path(artifact_path) if artifact_path else None
    digest = None
    size = None
    if path and path.exists() and path.is_file():
        data = path.read_bytes()
        digest = sha256_bytes(data)
        size = len(data)
    rec = {
        "bundleId": new_id(),
        "commitSha": commit_sha,
        "generatedAt": utcnow().isoformat(),
        "jobId": job.get("jobId"),
        "workerId": job.get("worker") or job.get("workerId"),
        "gpuUuid": job.get("gpuUuid"),
        "gpuName": job.get("gpu") or job.get("gpuName"),
        "blenderVersion": job.get("blenderVersion") or (job.get("output") or {}).get("blenderVersion"),
        "usedMock": bool(job.get("usedMock") if job.get("usedMock") is not None else (job.get("output") or {}).get("usedMock")),
        "artifactId": job.get("outputAsset"),
        "artifactPath": str(path) if path else None,
        "artifactHash": digest or job.get("outputHash"),
        "artifactSize": size or job.get("outputSize"),
        "engineeringHash": engineering_hash,
        "bomHash": bom_hash,
        "recipeVersion": recipe_version,
        "realBlender": bool(job.get("realBlender") or (job.get("output") or {}).get("realBlender")),
        "status": job.get("status"),
    }
    if extra:
        rec.update(extra)
    rec["evidenceHash"] = stable_hash({k: rec[k] for k in rec if k not in {"bundleId", "evidenceHash"}})
    return rec


def working_tree_clean(porcelain: str) -> bool:
    return not str(porcelain or "").strip()


def prepare_evidence_lineage(*, head_sha: str, porcelain: str, allow_dirty: bool = False) -> dict[str, Any]:
    """Bind REAL evidence to a committed SHA. Dirty trees cannot emit REAL labels."""
    clean = working_tree_clean(porcelain)
    if not clean and not allow_dirty:
        raise DirtyTreeError("REAL acceptance requires git status --porcelain empty")
    if allow_dirty and not clean:
        label = "UNVERIFIED"
        real_ok = False
    else:
        label = "REAL"
        real_ok = True
    return {
        "evidenceCodeCommit": head_sha,
        "workingTreeClean": clean,
        "acceptanceRunnerVersion": ACCEPTANCE_RUNNER_VERSION,
        "allowDirty": allow_dirty,
        "generatedAt": utcnow().isoformat(),
        "label": label,
        "realAcceptanceAllowed": real_ok,
    }


def git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def git_porcelain(root: Path) -> str:
    return subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)


def inspect_repo_lineage(root: Path, *, allow_dirty: bool = False) -> dict[str, Any]:
    return prepare_evidence_lineage(head_sha=git_head(root), porcelain=git_porcelain(root), allow_dirty=allow_dirty)


def verify_bundle(
    bundle: dict[str, Any],
    *,
    require_real: bool = True,
    expected_commit_sha: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    path = bundle.get("artifactPath")
    if not path:
        errors.append("missing_artifact_path")
    else:
        p = Path(path)
        if not p.exists() or not p.is_file():
            errors.append("artifact_missing")
        else:
            data = p.read_bytes()
            if bundle.get("artifactHash") and sha256_bytes(data) != bundle.get("artifactHash"):
                errors.append("hash_mismatch")
            if bundle.get("artifactSize") is not None and int(bundle["artifactSize"]) != len(data):
                errors.append("size_mismatch")
    if require_real and bundle.get("usedMock"):
        errors.append("used_mock")
    if require_real and not bundle.get("realBlender") and bundle.get("jobId"):
        errors.append("not_real_blender")
    if require_real and bundle.get("status") not in {None, "completed", "succeeded"}:
        errors.append("job_not_completed")
    if not bundle.get("engineeringHash") and not bundle.get("bomHash"):
        errors.append("missing_lineage")
    if expected_commit_sha:
        if bundle.get("commitSha") != expected_commit_sha:
            errors.append("commit_sha_mismatch")
    ok = not errors
    return {
        "ok": ok,
        "errors": errors,
        "bundleId": bundle.get("bundleId"),
        "evidenceHash": bundle.get("evidenceHash"),
        "expectedCommitSha": expected_commit_sha,
        "bundleCommitSha": bundle.get("commitSha"),
    }
