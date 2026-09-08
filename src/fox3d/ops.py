"""GPU drain/preemption, render cache, lineage, QA, script security."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import ComputeRegistry, JobQueue, Operations, job_cache_key
from fox3d.pngutil import EXR_MAGIC, is_png


def path_segments(raw: str) -> list[str]:
    """OS-agnostic segments: treat both `/` and `\\` as separators."""
    text = str(raw).replace("\\", "/")
    return [seg for seg in text.split("/") if seg not in {"", "."}]


def assert_job_paths_safe(job: dict[str, Any]) -> None:
    """Reject path traversal in worker-facing file fields. Does not restrict Blender binary.

    Host Path().parts is not used: Linux would treat Windows `\\` as a filename character.
    """
    for key in ("glbPath", "progressFile", "cancelFile"):
        raw = job.get(key)
        if not raw:
            continue
        if ".." in path_segments(str(raw)):
            raise PermissionError("path traversal blocked")


def cleanup_job_temp(job_dir: Path) -> list[str]:
    removed: list[str] = []
    if not job_dir.exists():
        return removed
    for path in job_dir.iterdir():
        if path.suffix.lower() in {".log", ".blend1", ".blend"} or path.name.endswith(".tmp"):
            try:
                path.unlink()
                removed.append(path.name)
            except OSError:
                continue
    return removed


class DrainController:
    """Maps to FoxStudio compute_targets.status=draining. Never SIGKILL mid-tile."""

    def __init__(self, compute: ComputeRegistry, queue: JobQueue) -> None:
        self.compute = compute
        self.queue = queue

    def request_drain(self, target_key: str, reason: str) -> dict[str, Any]:
        node = self.compute.control(target_key, "drain", reason)
        return {"targetKey": target_key, "status": node.status, "reason": reason}

    def finish_unit_and_release(self, job: dict[str, Any], *, frame: int, tile: int) -> dict[str, Any]:
        job["checkpoint"] = {"frame": frame, "tile": tile, "phase": "frame_complete"}
        return {
            "steps": ["frame_or_tile_complete", "checkpoint", "worker_drain", "release_gpu", "scheduler_dispatch"],
            "checkpoint": job["checkpoint"],
            "killed": False,
        }


class RenderCache:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def key_for(self, job: dict[str, Any], *, blender_version: str) -> str:
        return job_cache_key(job, blender_version=blender_version)

    def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    def put(self, key: str, outputs: dict[str, Any]) -> None:
        self._store[key] = outputs


@dataclass
class LineageRecord:
    lineage_id: str
    tenant_id: str
    source_asset: str | None
    digital_twin_version: int | None
    recipe_version: int | None
    job_id: str
    worker_id: str | None
    gpu: str | None
    blender_version: str | None
    ai_model: str | None
    prompt: str | None
    seed: str | None
    output: dict[str, Any] = field(default_factory=dict)


class LineageLog:
    def __init__(self) -> None:
        self._rows: list[LineageRecord] = []

    def record(self, row: LineageRecord) -> LineageRecord:
        self._rows.append(row)
        return row

    def for_job(self, job_id: str, *, tenant_id: str) -> list[LineageRecord]:
        return [r for r in self._rows if r.job_id == job_id and r.tenant_id == tenant_id]


class RenderQA:
    def inspect(self, outputs: dict[str, str], *, expected_size: tuple[int, int] | None = None) -> dict[str, Any]:
        failures: list[str] = []
        png = outputs.get("beauty.png")
        if not png or not Path(png).exists():
            failures.append("render_failure")
        else:
            data = Path(png).read_bytes()
            if data[:8] != b"\x89PNG\r\n\x1a\n":
                failures.append("NaN")
                failures.append("render_failure")
            elif _is_black_png(data):
                failures.append("black_frame")
            if expected_size and not _png_size_matches(data, expected_size):
                failures.append("wrong_resolution")
        if "missing_texture" in (outputs.get("flags") or []):
            failures.append("missing_texture")
        if "missing_object" in (outputs.get("flags") or []):
            failures.append("missing_object")
        if outputs.get("logoVisible") is False:
            failures.append("logo_visibility")
        if outputs.get("deformed"):
            failures.append("product_deformation")
        if outputs.get("cameraClipping"):
            failures.append("camera_clipping")
        if outputs.get("overexposed"):
            failures.append("overexposure")
        if outputs.get("underexposed"):
            failures.append("underexposure")
        exr = outputs.get("beauty.exr")
        if exr and Path(exr).exists() and Path(exr).read_bytes()[:4] != EXR_MAGIC:
            failures.append("NaN")
        ok = not failures
        return {"ok": ok, "failures": failures, "action": None if ok else "AUTO_RETRY"}


def _is_black_png(data: bytes) -> bool:
    import struct
    import zlib

    try:
        idx = 8
        idat = b""
        width = height = 0
        while idx + 8 <= len(data):
            (length,) = struct.unpack(">I", data[idx : idx + 4])
            tag = data[idx + 4 : idx + 8]
            chunk = data[idx + 8 : idx + 8 + length]
            idx += 12 + length
            if tag == b"IHDR":
                width, height = struct.unpack(">II", chunk[:8])
            if tag == b"IDAT":
                idat += chunk
            if tag == b"IEND":
                break
        raw = zlib.decompress(idat)
        stride = 1 + width * 3
        for y in range(height):
            row = raw[y * stride + 1 : (y + 1) * stride]
            if any(row):
                return False
        return height > 0
    except Exception:
        return False


def _png_size_matches(data: bytes, expected: tuple[int, int]) -> bool:
    import struct

    if len(data) < 24:
        return False
    w, h = struct.unpack(">II", data[16:24])
    return (w, h) == expected


class ScriptRegistry:
    """Blender Python is high-risk. Production worker only runs allowlisted+signed scripts."""

    def __init__(self) -> None:
        self._scripts: dict[str, dict[str, Any]] = {}

    def register(
        self,
        *,
        name: str,
        source: bytes,
        signature: str,
        allow_production: bool = False,
        sandbox: bool = True,
    ) -> dict[str, Any]:
        digest = sha256_bytes(source)
        rec = {
            "scriptId": new_id(),
            "name": name,
            "sha256": digest,
            "signature": signature,
            "allowlist": allow_production,
            "sandbox": sandbox,
            "status": "PRODUCTION" if allow_production else "EXPERIMENTAL",
            "resourceLimits": {"cpuSeconds": 120, "memoryMb": 4096},
            "filesystemRestrictions": ["work_dir_only"],
            "networkRestrictions": ["deny_all"],
        }
        self._scripts[digest] = rec
        return rec

    def authorize(self, source: bytes, *, production: bool) -> dict[str, Any]:
        digest = sha256_bytes(source)
        rec = self._scripts.get(digest)
        if rec is None:
            raise PermissionError("script not in registry")
        if production and not rec["allowlist"]:
            raise PermissionError("agent-generated script is EXPERIMENTAL SANDBOX ONLY")
        if rec["signature"] in {"", "unsigned"}:
            raise PermissionError("unsigned script")
        return rec


def qa_or_retry(qa: dict[str, Any], job: dict[str, Any], operations: Operations) -> str:
    if qa["ok"]:
        return "ok"
    attempts = int(job.get("attemptCount") or 0)
    max_attempts = int(job.get("maxAttempts") or 3)
    if attempts + 1 < max_attempts:
        return "AUTO_RETRY"
    operations.open_review("render QA exhausted retries", {"jobId": job.get("jobId"), "failures": qa["failures"]})
    return "OPERATIONS_REVIEW"
