"""In-process adapters that mirror FoxStudio + Fleet Console contracts.

Production wires these protocols to Postgres/MinIO/HTTP. Tests and local
dev use the memory implementations. The engine never reimplements a second
scheduler — it *calls* these ports.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.jobs import JobStatus

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "blocked": frozenset({"queued", "cancel_requested", "skipped", "expired"}),
    "queued": frozenset({"reserved", "leased", "cancel_requested", "expired", "blocked"}),
    "reserved": frozenset({"dispatched", "running", "retry_scheduled", "cancel_requested", "failed", "queued", "blocked"}),
    "dispatched": frozenset({"running", "retry_scheduled", "cancel_requested", "failed", "queued", "blocked"}),
    "leased": frozenset({"running", "reserved", "dispatched", "retry_scheduled", "cancel_requested", "failed", "queued"}),
    "running": frozenset(
        {
            "rendering",
            "uploading",
            "waiting_approval",
            "retry_scheduled",
            "cancel_requested",
            "failed",
            "succeeded",
            "completed",
            "blocked",
        }
    ),
    "rendering": frozenset(
        {"uploading", "retry_scheduled", "cancel_requested", "failed", "blocked", "completed"}
    ),
    "uploading": frozenset({"completed", "succeeded", "retry_scheduled", "cancel_requested", "failed"}),
    "waiting_approval": frozenset({"queued", "cancel_requested", "expired", "succeeded", "completed"}),
    "retry_scheduled": frozenset({"reserved", "leased", "queued", "cancel_requested", "expired"}),
    "cancel_requested": frozenset({"cancelled"}),
    "cancelled": frozenset(),
    "failed": frozenset(),
    "skipped": frozenset(),
    "succeeded": frozenset(),
    "completed": frozenset(),
    "expired": frozenset(),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def retry_delay_seconds(attempt_count: int, *, base_seconds: float = 5.0, maximum_seconds: float = 300.0) -> float:
    """Same capped exponential as FoxStudio foxworker.backoff."""
    if attempt_count < 1:
        raise ValueError("attempt_count must be at least 1")
    return min(maximum_seconds, base_seconds * (2 ** (attempt_count - 1)))


class TransitionError(ValueError):
    pass


def transition(current: str, target: str) -> str:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise TransitionError(f"illegal job transition: {current} -> {target}")
    return target


# ---------------------------------------------------------------------------
# Compute / capability / model / recipe registries
# ---------------------------------------------------------------------------

@dataclass
class ComputeNode:
    target_key: str
    name: str
    status: str = "offline"  # online|offline|draining|degraded
    capabilities: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)
    last_heartbeat_at: datetime | None = None
    gpus: list[dict[str, Any]] = field(default_factory=list)
    reserved_vram_gb: float = 0.0


class ComputeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, ComputeNode] = {}
        self._lock = threading.Lock()

    def upsert_heartbeat(self, node: ComputeNode) -> ComputeNode:
        with self._lock:
            existing = self._nodes.get(node.target_key)
            if existing and existing.status in {"draining", "degraded"} and node.status == "online":
                # Drain/disable is sticky until an explicit resume (FoxStudio 0041).
                node.status = existing.status
            node.last_heartbeat_at = utcnow()
            self._nodes[node.target_key] = node
            return node

    def get(self, target_key: str) -> ComputeNode | None:
        return self._nodes.get(target_key)

    def all(self) -> list[ComputeNode]:
        return list(self._nodes.values())

    def control(self, target_key: str, action: str, reason: str = "") -> ComputeNode:
        node = self._nodes[target_key]
        previous = node.status
        if action == "drain":
            node.status = "draining"
        elif action == "disable":
            node.status = "offline"
        elif action == "resume":
            node.status = "online"
        else:
            raise ValueError(f"unknown compute control: {action}")
        node.telemetry = {
            **node.telemetry,
            "lastControl": action,
            "reason": reason,
            "previousStatus": previous,
        }
        return node

    def touch_heartbeats(self) -> None:
        """Refresh liveness for already-registered nodes without a full re-probe.

        In production a separate worker process re-heartbeats continuously; this
        package's scheduler and local worker share one process, so the platform
        touches its own nodes right before placement instead of going stale.
        """
        now = utcnow()
        for node in self._nodes.values():
            if node.last_heartbeat_at is not None:
                node.last_heartbeat_at = now

    def mark_offline_stale(self, *, max_age_seconds: float = 60.0) -> list[str]:
        now = utcnow()
        recovered: list[str] = []
        for node in self._nodes.values():
            if node.last_heartbeat_at is None:
                continue
            age = (now - node.last_heartbeat_at).total_seconds()
            if age > max_age_seconds and node.status == "online":
                node.status = "offline"
                recovered.append(node.target_key)
        return recovered


class CapabilityRegistry:
    def __init__(self) -> None:
        self._by_node: dict[str, set[str]] = {}

    def declare(self, target_key: str, capabilities: list[str]) -> None:
        self._by_node[target_key] = set(capabilities)

    def nodes_with(self, capability: str) -> list[str]:
        return [key for key, caps in self._by_node.items() if capability in caps]


@dataclass
class ModelRecord:
    model_key: str
    kind: str
    provider: str
    version: str = "1"
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelRecord] = {}

    def register(self, model: ModelRecord) -> ModelRecord:
        self._models[model.model_key] = model
        return model

    def get(self, model_key: str) -> ModelRecord | None:
        return self._models.get(model_key)


RECIPE_TYPES = (
    "SCENE",
    "CAMERA",
    "LIGHTING",
    "MATERIAL",
    "ANIMATION",
    "PRODUCT",
    "FURNITURE",
    "PACKAGING",
    "RETAIL",
)

RECIPE_LIFECYCLE = ("EXPERIMENTAL", "CANDIDATE", "APPROVED", "PRODUCTION")


@dataclass
class Recipe:
    recipe_id: str
    recipe_key: str
    recipe_type: str
    version: int = 1
    status: str = "EXPERIMENTAL"
    tenant_id: str = "system"
    configuration: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    usage_count: int = 0
    success_count: int = 0
    tags: list[str] = field(default_factory=list)
    compatible_capabilities: list[str] = field(default_factory=list)
    name: str = ""

    @property
    def success_rate(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count


class RecipeRegistry:
    """Adapter over FoxStudio production_recipes — same versioning semantics."""

    def __init__(self) -> None:
        self._items: dict[str, Recipe] = {}

    def upsert(self, recipe: Recipe) -> Recipe:
        existing = self._items.get(recipe.recipe_id)
        if existing and existing.status == "PRODUCTION" and recipe.status == "PRODUCTION":
            # Research must never clobber a production recipe in place.
            raise ValueError("cannot overwrite PRODUCTION recipe; promote a new version")
        if existing and existing.recipe_key == recipe.recipe_key and existing.tenant_id == recipe.tenant_id:
            recipe.version = existing.version + 1
        self._items[recipe.recipe_id] = recipe
        return recipe

    def get(self, recipe_id: str) -> Recipe | None:
        return self._items.get(recipe_id)

    def find(self, *, tenant_id: str, recipe_type: str | None = None, status: str | None = None) -> list[Recipe]:
        out = []
        for recipe in self._items.values():
            if recipe.tenant_id not in {tenant_id, "system"}:
                continue
            if recipe_type and recipe.recipe_type != recipe_type:
                continue
            if status and recipe.status != status:
                continue
            out.append(recipe)
        return out

    def promote(self, recipe_id: str, to_status: str) -> Recipe:
        recipe = self._items[recipe_id]
        idx = RECIPE_LIFECYCLE.index(recipe.status)
        target = RECIPE_LIFECYCLE.index(to_status)
        if target < idx:
            raise ValueError("recipe lifecycle is forward-only")
        recipe.status = to_status
        return recipe

    def record_usage(self, recipe_id: str, *, success: bool) -> None:
        recipe = self._items.get(recipe_id)
        if not recipe:
            return
        recipe.usage_count += 1
        if success:
            recipe.success_count += 1


# ---------------------------------------------------------------------------
# DAM / tenant / operations / AI gateway
# ---------------------------------------------------------------------------

@dataclass
class DamObject:
    asset_id: str
    tenant_id: str
    kind: str
    path: str
    sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1


class DAM:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, DamObject] = {}

    def put(
        self,
        *,
        tenant_id: str,
        kind: str,
        name: str,
        data: bytes,
        metadata: dict[str, Any] | None = None,
        asset_id: str | None = None,
    ) -> DamObject:
        asset_id = asset_id or new_id()
        rel = Path(tenant_id) / kind / f"{asset_id}_{name}"
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        obj = DamObject(
            asset_id=asset_id,
            tenant_id=tenant_id,
            kind=kind,
            path=str(dest),
            sha256=sha256_bytes(data),
            metadata=metadata or {},
        )
        self._index[asset_id] = obj
        return obj

    def get(self, asset_id: str, *, tenant_id: str) -> DamObject:
        obj = self._index[asset_id]
        if obj.tenant_id != tenant_id:
            raise PermissionError("tenant isolation: asset leakage blocked")
        return obj

    def get_unchecked(self, asset_id: str) -> DamObject:
        return self._index[asset_id]

    def list(self, *, tenant_id: str, kind: str | None = None) -> list[DamObject]:
        return [
            obj
            for obj in self._index.values()
            if obj.tenant_id == tenant_id and (kind is None or obj.kind == kind)
        ]


class TenantRegistry:
    def __init__(self) -> None:
        self._tenants: dict[str, dict[str, Any]] = {}

    def ensure(self, tenant_id: str, name: str | None = None) -> dict[str, Any]:
        return self._tenants.setdefault(tenant_id, {"tenantId": tenant_id, "name": name or tenant_id, "status": "active"})

    def assert_access(self, tenant_id: str, resource_tenant_id: str) -> None:
        if tenant_id != resource_tenant_id:
            raise PermissionError("tenant isolation: cross-tenant access denied")


class Operations:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.reviews: list[dict[str, Any]] = []

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append({"kind": kind, "at": utcnow().isoformat(), **payload})

    def open_review(self, reason: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = {"reviewId": new_id(), "reason": reason, "status": "OPERATIONS_REVIEW", **payload}
        self.reviews.append(item)
        self.emit("operations.review", item)
        return item


class AIGateway:
    """Provider-neutral adapter port (FoxStudio ProviderAdapter shape)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._video_adapters: dict[str, Callable[..., dict[str, Any]]] = {}
        self._vision_adapters: dict[str, Callable[..., dict[str, Any]]] = {}

    def register_video_adapter(self, name: str, fn: Callable[..., dict[str, Any]]) -> None:
        self._video_adapters[name] = fn

    def register_vision_adapter(self, name: str, fn: Callable[..., dict[str, Any]]) -> None:
        self._vision_adapters[name] = fn

    def generate_video(self, *, adapter: str | None, request: dict[str, Any]) -> dict[str, Any]:
        name = adapter or next(iter(self._video_adapters), "mock")
        self.calls.append({"adapter": name, "request": request})
        fn = self._video_adapters.get(name)
        if fn:
            return fn(request)
        return {
            "provider": name,
            "status": "succeeded",
            "kind": "mock_video",
            "note": "No live video adapter bound; returning governed mock.",
            "output": {"duration": request.get("duration", 4), "fromKeyframes": True},
        }

    def suggest_materials(self, *, images: list[str], metadata: dict[str, Any]) -> dict[str, Any]:
        hint = str(metadata.get("category") or metadata.get("materialHint") or "plastic").lower()
        return {"suggested": hint, "confidence": 0.55, "images": images, "mustNotOverwriteTwin": True}


# ---------------------------------------------------------------------------
# Reservation + GPU scheduler adapter (does not replace Fleet scheduler)
# ---------------------------------------------------------------------------

@dataclass
class Reservation:
    reservation_id: str
    target_key: str
    gpu_index: int
    vram_gb: float
    job_id: str
    status: str = "held"  # held|released|draining


class ReservationBook:
    def __init__(self) -> None:
        self._held: dict[str, Reservation] = {}

    def hold(self, *, target_key: str, gpu_index: int, vram_gb: float, job_id: str) -> Reservation:
        res = Reservation(new_id(), target_key, gpu_index, vram_gb, job_id)
        self._held[res.reservation_id] = res
        return res

    def release(self, reservation_id: str) -> None:
        if reservation_id in self._held:
            self._held[reservation_id].status = "released"

    def for_job(self, job_id: str) -> list[Reservation]:
        return [r for r in self._held.values() if r.job_id == job_id and r.status == "held"]

    def held_vram(self, target_key: str) -> float:
        return sum(r.vram_gb for r in self._held.values() if r.target_key == target_key and r.status == "held")


class Scheduler:
    """Placement policy adapter. Fleet/FoxStudio still own dispatch."""

    def __init__(self, compute: ComputeRegistry, reservations: ReservationBook) -> None:
        self.compute = compute
        self.reservations = reservations

    def place(self, job: dict[str, Any]) -> dict[str, Any]:
        capability = str(job.get("jobType") or "")
        min_vram = float((job.get("gpuRequirement") or {}).get("minVramGb") or 0)
        prefer_video = capability in {"BLENDER_TO_VIDEO"} or str(job.get("lane") or "") == "ai_video"
        preview = capability in {"BLENDER_PREVIEW", "BLENDER_SCENE", "PARAMETRIC_3D"}
        candidates: list[tuple[float, ComputeNode, dict[str, Any]]] = []
        for node in self.compute.all():
            if node.status != "online":
                continue
            if not node.last_heartbeat_at:
                continue
            age = (utcnow() - node.last_heartbeat_at).total_seconds()
            if age > 45:
                continue
            gpus = node.gpus or [
                {
                    "gpuIndex": 0,
                    "name": node.capabilities.get("gpu") or node.name,
                    "vramGb": float(node.capabilities.get("vramGb") or 0),
                    "freeVramGb": float(node.capabilities.get("vramGb") or 0) - node.reserved_vram_gb,
                }
            ]
            for gpu in gpus:
                name = str(gpu.get("name") or "")
                free = float(gpu.get("freeVramGb") or gpu.get("vramGb") or 0)
                if free < min_vram:
                    continue
                score = free
                if prefer_video and "5090" in name:
                    score += 1000
                if preview and "5080" in name:
                    score += 400
                if preview and "5090" in name:
                    score -= 50  # do not steal 5090 for previews when other GPUs exist
                if node.status == "draining":
                    continue
                candidates.append((score, node, gpu))
        if not candidates:
            return {"decision": "NO_ELIGIBLE_TARGET", "targetKey": None, "reason": "NO_ELIGIBLE_TARGET"}
        candidates.sort(key=lambda item: item[0], reverse=True)
        _score, node, gpu = candidates[0]
        return {
            "decision": "atomic_capability_claim",
            "targetKey": node.target_key,
            "gpuIndex": gpu.get("gpuIndex", 0),
            "gpuName": gpu.get("name"),
            "selection": "adapter_over_existing_scheduler",
        }


# ---------------------------------------------------------------------------
# Queue (FoxStudio state machine, in-memory for this engine + tests)
# ---------------------------------------------------------------------------

class JobQueue:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
        job = dict(job)
        job.setdefault("status", "queued")
        job.setdefault("attemptCount", 0)
        job.setdefault("maxAttempts", 3)
        job.setdefault("progress", 0.0)
        job.setdefault("createdAt", utcnow().isoformat())
        with self._lock:
            self._jobs[job["jobId"]] = job
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    def list(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        jobs = list(self._jobs.values())
        if tenant_id is not None:
            jobs = [j for j in jobs if j.get("tenantId") == tenant_id]
        return jobs

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        job = self._jobs[job_id]
        job["cancelRequested"] = True
        if job["status"] in {"queued", "retry_scheduled", "blocked"}:
            transition(job["status"], "cancel_requested")
            job["status"] = "cancel_requested"
            job["status"] = transition("cancel_requested", "cancelled")
            job["completedAt"] = utcnow().isoformat()
        elif job["status"] in {"leased", "reserved", "dispatched", "running", "rendering", "uploading", "waiting_approval"}:
            job["status"] = transition(job["status"], "cancel_requested")
        return job

    def heartbeat(self, job_id: str, progress: float | None = None) -> dict[str, Any]:
        job = self._jobs[job_id]
        job["heartbeatAt"] = utcnow().isoformat()
        if progress is not None:
            job["progress"] = progress
        return job

    def claim(self, owner: str, *, target_key: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            for job in self._jobs.values():
                if job["status"] not in {"queued", "retry_scheduled"}:
                    continue
                if job.get("cancelRequested"):
                    job["status"] = "cancelled"
                    continue
                if job["status"] == "queued":
                    job["status"] = transition("queued", "reserved")
                else:
                    job["status"] = transition("retry_scheduled", "reserved")
                job["leaseOwner"] = owner
                if target_key:
                    job["assignedComputeTargetKey"] = target_key
                job["startedAt"] = job.get("startedAt") or utcnow().isoformat()
                return job
        return None

    def set_status(self, job_id: str, status: JobStatus, **fields: Any) -> dict[str, Any]:
        job = self._jobs[job_id]
        job["status"] = transition(job["status"], status)
        job.update(fields)
        if status in {"succeeded", "completed", "failed", "cancelled", "expired", "blocked"}:
            job["completedAt"] = utcnow().isoformat()
        return job

    def recover_stale_leases(self, *, max_age_seconds: float = 30.0) -> list[str]:
        """Failed-job / worker-offline recovery: expired lease returns to queued."""
        now = utcnow()
        recovered: list[str] = []
        for job in self._jobs.values():
            if job["status"] not in {"leased", "reserved", "dispatched", "running", "rendering"}:
                continue
            beat = job.get("heartbeatAt") or job.get("startedAt")
            if not beat:
                continue
            ts = datetime.fromisoformat(beat)
            if (now - ts).total_seconds() > max_age_seconds:
                attempts = int(job.get("attemptCount") or 0) + 1
                job["attemptCount"] = attempts
                if attempts < int(job.get("maxAttempts") or 3):
                    job["status"] = "queued"
                    job["leaseOwner"] = None
                    job["error"] = "worker offline recovery: lease expired"
                    recovered.append(job["jobId"])
                else:
                    job["status"] = "failed"
                    job["error"] = "worker offline and retry exhausted"
                    job["completedAt"] = now.isoformat()
        return recovered


def job_cache_key(job: dict[str, Any], *, blender_version: str) -> str:
    payload = {
        "assetHash": job.get("assetHash") or stable_hash(job.get("inputAssets")),
        "scene": job.get("scene"),
        "camera": job.get("camera"),
        "lighting": job.get("lighting"),
        "materials": job.get("materials"),
        "render": job.get("render"),
        "blenderVersion": blender_version,
        "recipeId": job.get("recipeId"),
    }
    return stable_hash(payload)


class Clock:
    """Injectable clock so timeout tests do not sleep for real."""

    def __init__(self) -> None:
        self._now = time.monotonic()

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    def sleep(self, seconds: float) -> None:
        self._now += seconds
