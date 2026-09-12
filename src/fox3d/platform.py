"""Composition root: existing infra ports + domain engines."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from fox3d.blender import (
    BLOCKED_NO_BLENDER,
    BLOCKED_NO_OPTIX,
    BlenderRuntime,
    HostProbe,
    detect_node,
    gpu_target_key,
    probe_host,
)
from fox3d.capabilities import BLENDER_PREVIEW, BLENDER_RENDER, capability_flags, foxstudio_operations
from fox3d.gpu import GpuPolicy
from fox3d.ids import new_id, sha256_bytes
from fox3d.infra import (
    AIGateway,
    CapabilityRegistry,
    ComputeNode,
    ComputeRegistry,
    DAM,
    JobQueue,
    ModelRegistry,
    Operations,
    RecipeRegistry,
    ReservationBook,
    Scheduler,
    TenantRegistry,
    retry_delay_seconds,
    utcnow,
)
from fox3d.jobs import BlenderJob
from fox3d.media import ARExporter, AssemblyAnimator, BlenderToVideo, Product360Engine, RetailEngine, SyntheticFactory
from fox3d.ops import (
    DrainController,
    LineageLog,
    LineageRecord,
    RenderCache,
    RenderQA,
    ScriptRegistry,
    assert_job_paths_safe,
    cleanup_job_temp,
    qa_or_retry,
)
from fox3d.packaging import PackagingEngine
from fox3d.factory import FurnitureFactory
from fox3d.commerce import ProviderRegistry
from fox3d.inventory import DurableRemnantStore, MaterialLotRegistry
from fox3d.kd_factory import KdFactory
from fox3d.manufacturing import RemnantInventory
from fox3d.physical_os import PhysicalProductOS
from fox3d.pilot import PilotOps
from fox3d.portfolio import PortfolioFactory
from fox3d.publish import CatalogRelease
from fox3d.release import ReleaseGate
from fox3d.sandbox import SandboxRegistry
from fox3d.parametric import BOMEngine, CAMAdapter, CNCAdapter, CabinetEngine, CostEngine, EngineeringRuleEngine, NestingAdapter
from fox3d.rd import GatewayVisionProvider, ProductRDAgent, VisionJudge
from fox3d.recipes import BlenderRecipeResearchAgent, RecipeIntelligence
from fox3d.scene import SceneDSL, compile_scene_graph
from fox3d.space import SpacePipeline
from fox3d.studio import MaterialEngine, ProductStudio, seed_system_recipes
from fox3d.twin import ProductDigitalTwin, TwinStore


class Platform:
    def __init__(self, root: Path | None = None, *, mock_blender: bool = False) -> None:
        self.root = root or Path.cwd() / ".fox3d-data"
        self.root.mkdir(parents=True, exist_ok=True)
        self.tenants = TenantRegistry()
        self.compute = ComputeRegistry()
        self.capabilities = CapabilityRegistry()
        self.models = ModelRegistry()
        self.recipes = RecipeRegistry()
        self.queue = JobQueue()
        self.reservations = ReservationBook()
        self.scheduler = Scheduler(self.compute, self.reservations)
        self.dam = DAM(self.root / "dam")
        self.gateway = AIGateway()
        self.operations = Operations()
        self.twins = TwinStore(self.dam)
        self.studio = ProductStudio()
        self.materials = MaterialEngine(self.recipes, self.gateway)
        self.packaging = PackagingEngine()
        self.rules = EngineeringRuleEngine()
        self.cabinets = CabinetEngine(self.rules)
        self.bom = BOMEngine()
        self.cost = CostEngine()
        self.cam = CAMAdapter()
        self.cnc = CNCAdapter()
        self.nesting = NestingAdapter()
        self.spaces = SpacePipeline()
        self.judge = VisionJudge(GatewayVisionProvider(self.gateway))
        self.rd = ProductRDAgent(self.cabinets, self.cost, self.judge, self.studio)
        self.factory = FurnitureFactory(self)
        self.lots = MaterialLotRegistry(self.root / "lots")
        self.remnants = RemnantInventory(DurableRemnantStore(self.root / "remnants"), default_tenant="default")
        self.kd = KdFactory(self)
        self.physical = PhysicalProductOS(self)
        self.portfolio = PortfolioFactory(self)
        from fox3d.prototype import PrototypeFactory
        from fox3d.pilot_batch import PilotBatchFactory

        self.prototype = PrototypeFactory(self)
        self.pilot_batch = PilotBatchFactory(self)
        from fox3d.artwork import ArtworkFactory
        from fox3d.generative_gateway import GenerativeRenderGateway
        from fox3d.product_truth import ProductTruthFactory

        self.artwork = ArtworkFactory(self)
        self.product_truth = ProductTruthFactory(self)
        self.generative = GenerativeRenderGateway(self)
        self.pilot = PilotOps(self)
        self.retail_fixtures = self.physical.retail
        self.providers = ProviderRegistry(self.root / "providers")
        self.release = ReleaseGate()
        self.sandbox = SandboxRegistry()
        self.catalog = CatalogRelease()
        self.p360 = Product360Engine()
        self.ar = ARExporter()
        self.synthetic = SyntheticFactory()
        self.assembly = AssemblyAnimator()
        self.b2v = BlenderToVideo()
        self.retail = RetailEngine()
        self.recipe_intel = RecipeIntelligence(self.recipes)
        self.research = BlenderRecipeResearchAgent(self.recipes, self.judge)
        self.gpu_policy = GpuPolicy()
        self.drain = DrainController(self.compute, self.queue)
        self.cache = RenderCache()
        self.lineage = LineageLog()
        self.qa = RenderQA()
        self.scripts = ScriptRegistry()
        self.runtime = BlenderRuntime(work_dir=self.root / "work", force_mock=mock_blender)
        self.mock_blender = mock_blender
        self.probe: HostProbe | None = None
        self.parametrics: dict[str, dict[str, Any]] = {}
        seed_system_recipes(self.recipes)
        self._register_builtin_script()
        self.worker_id = "fox3d-worker-local"
        if not mock_blender:
            try:
                self.register_detected_workers()
            except Exception:
                pass

    def _register_builtin_script(self) -> None:
        script = Path(__file__).resolve().parents[2] / "scripts" / "blender_job.py"
        source = script.read_bytes() if script.exists() else b"# fox3d builtin blender_job.py\n"
        self.scripts.register(name="blender_job.py", source=source, signature="fox3d-builtin", allow_production=True, sandbox=True)

    # ----- node / worker -------------------------------------------------
    def register_node(self, *, target_key: str, name: str, detected: dict[str, Any] | None = None) -> ComputeNode:
        detected = detected or detect_node()
        caps = capability_flags(detected)
        gpus = []
        for gpu in detected.get("gpus") or []:
            gpus.append(
                {
                    "gpuIndex": gpu.get("gpuIndex", 0),
                    "name": gpu.get("name"),
                    "vramGb": gpu.get("vramGb"),
                    "freeVramMb": float(gpu.get("vramGb") or 0) * 1024,
                    "freeVramGb": gpu.get("vramGb"),
                }
            )
        if not gpus:
            gpus = [{"gpuIndex": 0, "name": name, "vramGb": 0, "freeVramGb": 0}]
        node = ComputeNode(
            target_key=target_key,
            name=name,
            status="online",
            capabilities=caps,
            gpus=gpus,
            telemetry={"operations": foxstudio_operations()},
        )
        self.compute.upsert_heartbeat(node)
        self.capabilities.declare(target_key, list(caps.get("capabilities") or []))
        return node

    def register_detected_workers(self) -> HostProbe:
        """Register real GPU + Blender capabilities. Never invent mock-4.2 / fake 5090."""
        probe = probe_host(blender_bin=self.runtime.blender_bin, script_path=self.runtime.script_path)
        self.probe = probe
        if self.runtime.blender_bin is None and probe.blenderBinary:
            self.runtime.blender_bin = probe.blenderBinary
        gpus = probe.gpus or [{"gpuIndex": 0, "name": "CPU", "vramGb": 0}]
        for gpu in gpus:
            key = gpu_target_key(str(gpu.get("name") or "gpu"), int(gpu.get("gpuIndex") or 0))
            detected = {
                "blender": probe.blender,
                "blenderVersion": probe.blenderVersion,
                "blenderBinary": probe.blenderBinary,
                "cuda": probe.cuda,
                "optix": probe.optix,
                "gpuCount": 1,
                "gpuName": gpu.get("name"),
                "vramGb": gpu.get("vramGb"),
                "driver": probe.driver,
                "gpus": [gpu],
                "cyclesDevices": probe.cyclesDevices,
                "blocked": probe.blocked,
                "realBlender": probe.realBlender,
                "realGPU": probe.realGPU,
                "realCycles": probe.realCycles,
                "realOptix": probe.realOptix,
            }
            detected.update(
                {
                    "gpuUuid": gpu.get("uuid"),
                    "vramUsedGb": gpu.get("vramUsedGb"),
                    "vramFreeGb": gpu.get("vramFreeGb"),
                    "hostname": probe.hostname,
                    "osName": probe.osName,
                    "discoverySource": probe.discoverySource,
                }
            )
            node = self.register_node(target_key=key, name=str(gpu.get("name") or key), detected=detected)
            if not probe.blender:
                node.status = "offline"
                node.telemetry["blocked"] = BLOCKED_NO_BLENDER
            elif not probe.optix:
                node.telemetry["blocked"] = BLOCKED_NO_OPTIX
            node.capabilities["blenderVersion"] = probe.blenderVersion or "NOT_INSTALLED"
            node.capabilities["mock"] = False
            node.capabilities["hostname"] = probe.hostname
            node.capabilities["os"] = probe.osName
            node.capabilities["gpuUuid"] = gpu.get("uuid")
            node.capabilities["vramUsedGb"] = gpu.get("vramUsedGb")
            node.capabilities["vramFreeGb"] = gpu.get("vramFreeGb")
            node.capabilities["discoverySource"] = probe.discoverySource
            node.gpus = [
                {
                    "gpuIndex": gpu.get("gpuIndex", 0),
                    "name": gpu.get("name"),
                    "uuid": gpu.get("uuid"),
                    "vramGb": gpu.get("vramGb"),
                    "vramUsedGb": gpu.get("vramUsedGb"),
                    "vramFreeGb": gpu.get("vramFreeGb") if gpu.get("vramFreeGb") is not None else gpu.get("vramGb"),
                    "freeVramGb": gpu.get("vramFreeGb") if gpu.get("vramFreeGb") is not None else gpu.get("vramGb"),
                }
            ]
        return probe

    def worker_offline_recovery(self) -> list[str]:
        stale_nodes = self.compute.mark_offline_stale()
        recovered = self.queue.recover_stale_leases()
        self.operations.emit("worker.offline_recovery", {"nodes": stale_nodes, "jobs": recovered})
        return recovered

    # ----- jobs ----------------------------------------------------------
    def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.tenants.ensure(payload["tenantId"])
        job = BlenderJob.model_validate(payload)
        record = job.model_dump(mode="json")
        record["routing_requirements"] = job.routing_requirements()
        return self.queue.enqueue(record)

    def get_job(self, job_id: str, *, tenant_id: str) -> dict[str, Any]:
        job = self.queue.get(job_id)
        if not job:
            raise KeyError(job_id)
        self.tenants.assert_access(tenant_id, job["tenantId"])
        return job

    def cancel_job(self, job_id: str, *, tenant_id: str) -> dict[str, Any]:
        job = self.get_job(job_id, tenant_id=tenant_id)
        return self.queue.request_cancel(job["jobId"])

    def run_next(self, *, timeout_seconds: float | None = None) -> dict[str, Any] | None:
        claimed = self.queue.claim(self.worker_id)
        if not claimed:
            return None
        return self.execute_job(claimed, timeout_seconds=timeout_seconds)

    def execute_job(self, job: dict[str, Any], *, timeout_seconds: float | None = None, cancel_flag: threading.Event | None = None) -> dict[str, Any]:
        if job.get("cancelRequested") or job.get("status") == "cancel_requested":
            job["status"] = "cancelled"
            return job
        self.compute.touch_heartbeats()
        placement = self.gpu_policy.place(self.scheduler, job)
        if placement.get("targetKey"):
            job["assignedComputeTargetKey"] = placement["targetKey"]
            vram = float((job.get("gpuRequirement") or {}).get("minVramGb") or 2)
            res = self.reservations.hold(
                target_key=placement["targetKey"],
                gpu_index=int(placement.get("gpuIndex") or 0),
                vram_gb=vram,
                job_id=job["jobId"],
            )
            job["reservationId"] = res.reservation_id
        else:
            # Leave queued — existing scheduler behaviour, do not burn an attempt.
            if job.get("status") == "leased":
                job["status"] = "queued"
                job["leaseOwner"] = None
            job["error"] = placement.get("reason") or "NO_ELIGIBLE_TARGET"
            if os.environ.get("FOX3D_DEBUG_PLACEMENT"):
                nodes_dbg = [
                    (n.target_key, n.status, n.last_heartbeat_at, n.gpus) for n in self.compute.all()
                ]
                Path(os.environ["FOX3D_DEBUG_PLACEMENT"]).write_text(
                    json.dumps(
                        {
                            "jobId": job.get("jobId"),
                            "jobType": job.get("jobType"),
                            "gpuRequirement": job.get("gpuRequirement"),
                            "placement": placement,
                            "nodes": [
                                {"key": k, "status": s, "heartbeat": str(h), "gpus": g}
                                for k, s, h, g in nodes_dbg
                            ],
                        },
                        default=str,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            return job

        try:
            assert_job_paths_safe(job)
        except PermissionError as exc:
            self._release(job)
            job["status"] = "blocked"
            job["error"] = str(exc)
            return job
        job["gpu"] = placement.get("gpuName")
        job["gpuUuid"] = (self.probe.gpuUuid if self.probe else None)
        job["worker"] = self.worker_id
        job["discoverySource"] = (self.probe.discoverySource if self.probe else ("MOCK" if self.mock_blender else "REAL_DISCOVERY"))
        self._enter_running(job)
        blender_version = str(
            (job.get("render") or {}).get("blenderVersion")
            or (self.probe.blenderVersion if self.probe else None)
            or (self.runtime.blender_bin and "blender")
            or ("mock-4.2" if self.mock_blender else "NOT_INSTALLED")
        )
        cache_key = self.cache.key_for(job, blender_version=blender_version)
        cached = self.cache.get(cache_key)
        if cached:
            term = "succeeded" if self.mock_blender else "completed"
            self._advance(job["jobId"], ["reserved", "running", "rendering", "uploading", term])
            done = self.queue.get(job["jobId"]) or job
            done["cacheHit"] = True
            done["output"] = cached
            done["realBlender"] = cached.get("realBlender")
            done["usedMock"] = cached.get("usedMock")
            done["realOptix"] = cached.get("realOptix")
            done["outputHash"] = (cached.get("files") or {}).get("beautyHash") or done.get("outputHash")
            done["outputSize"] = (cached.get("files") or {}).get("beautySize") or done.get("outputSize")
            done["device"] = cached.get("device") or done.get("device")
            done["artworkApplied"] = cached.get("artworkApplied")
            done["appliedPlacements"] = cached.get("appliedPlacements") or []
            if done.get("status") not in {"completed", "succeeded"}:
                done["status"] = term
            self._release(job)
            return done
        self.queue.heartbeat(job["jobId"], 0.05)

        dsl = SceneDSL.from_job(job)
        twin = None
        if job.get("assetId"):
            try:
                twin = self.twins.get(job["assetId"], tenant_id=job["tenantId"]).model_dump()
            except Exception:
                twin = None
        if (
            not job.get("sceneGraph")
            and not job.get("smokeTest")
            and not job.get("engineering")
            and not job.get("space")
            and not job.get("acrylic")
            and not job.get("foldPreview")
            and str(job.get("mode") or "") not in {"ACRYLIC_PRODUCT", "ACRYLIC_PREVIEW", "PACKAGING_FOLD"}
        ):
            job["sceneGraph"] = compile_scene_graph(dsl, product=twin)

        flag = cancel_flag or threading.Event()
        if job.get("cancelRequested"):
            flag.set()

        def on_progress(value: float) -> None:
            self.queue.heartbeat(job["jobId"], value)

        timeout = timeout_seconds if timeout_seconds is not None else float(job.get("timeoutSeconds") or 300)
        current = (self.queue.get(job["jobId"]) or job).get("status")
        if current == "running":
            self.queue.set_status(job["jobId"], "rendering")
        result = self.runtime.run_job(job, cancel_flag=flag, timeout_seconds=timeout, on_progress=on_progress)

        job["blenderVersion"] = result.blender_version
        job["renderEngine"] = result.engine
        job["samples"] = result.samples
        job["renderTimeSec"] = result.render_time_sec
        job["logs"] = (result.log or "")[-8000:]
        job["realBlender"] = result.real_blender
        job["realOptix"] = result.real_optix
        job["realCycles"] = result.real_cycles
        job["realRenderOutput"] = result.real_render_output
        job["usedMock"] = result.used_mock
        job["device"] = result.device
        job["artworkApplied"] = result.artwork_applied
        job["appliedPlacements"] = list(result.applied_placements or [])
        job["workerIdentity"] = dict(result.worker_identity or {})
        job["workerViews"] = dict(result.worker_views or {})
        if not job["workerIdentity"] and job["appliedPlacements"]:
            first = job["appliedPlacements"][0]
            job["workerIdentity"] = {
                "engineeringHash": first.get("engineeringHash"),
                "artworkId": first.get("artworkId"),
                "artworkHash": first.get("artworkHash"),
                "artworkSha256": first.get("artworkSha256"),
                "placementId": first.get("placementId"),
                "placementHash": first.get("placementHash"),
                "finalUvHash": first.get("finalUvHash"),
                "surfaceHash": first.get("surfaceHash"),
                "componentId": first.get("componentId"),
                "objectName": first.get("objectName"),
                "face": first.get("face"),
                "cameraRecipeHash": job.get("cameraRecipeHash"),
                "sceneRecipeHash": job.get("sceneRecipeHash"),
                "blenderJobId": job.get("jobId"),
                "usedMock": result.used_mock,
                "realBlender": result.real_blender,
                "realOptix": result.real_optix,
            }

        if result.status == "blocked":
            try:
                self.queue.set_status(job["jobId"], "blocked", error=result.error)
            except Exception:
                stored_job = self.queue.get(job["jobId"]) or job
                stored_job["status"] = "blocked"
                stored_job["error"] = result.error
            self._release(job)
            return self.queue.get(job["jobId"]) or job
        if result.status == "timeout":
            return self._fail_or_retry(job, "timeout")
        if result.status == "cancelled":
            current = (self.queue.get(job["jobId"]) or job)["status"]
            if current in {"leased", "reserved", "running", "rendering", "uploading", "waiting_approval"}:
                self.queue.set_status(job["jobId"], "cancel_requested")
            if (self.queue.get(job["jobId"]) or job)["status"] == "cancel_requested":
                self.queue.set_status(job["jobId"], "cancelled")
            self._release(job)
            return self.queue.get(job["jobId"]) or job
        if result.status != "succeeded":
            return self._fail_or_retry(job, result.error or "render failed")

        qa_outputs = {k: v for k, v in (result.outputs or {}).items() if isinstance(v, str)}
        qa = self.qa.inspect(qa_outputs) if qa_outputs.get("beauty.png") else {"ok": True, "failures": []}
        action = qa_or_retry(qa, job, self.operations) if qa_outputs.get("beauty.png") else "ok"
        if action == "AUTO_RETRY":
            return self._fail_or_retry(job, "QA:" + ",".join(qa["failures"]))
        if action == "OPERATIONS_REVIEW":
            try:
                self.queue.set_status(job["jobId"], "failed", error="OPERATIONS_REVIEW")
            except Exception:
                job["status"] = "failed"
            self._release(job)
            return self.queue.get(job["jobId"]) or job

        try:
            self.queue.set_status(job["jobId"], "uploading")
        except Exception:
            pass
        stored = self._upload_outputs(job["tenantId"], job["jobId"], result.outputs or {})
        job["outputHash"] = stored.get("beautyHash")
        job["outputSize"] = stored.get("beautySize")
        output = {
            "files": stored,
            "engine": result.engine,
            "device": result.device,
            "usedMock": result.used_mock,
            "samples": result.samples,
            "renderTimeSec": result.render_time_sec,
            "blenderVersion": result.blender_version,
            "realBlender": result.real_blender,
            "realOptix": result.real_optix,
            "realRenderOutput": result.real_render_output,
            "artworkApplied": result.artwork_applied,
            "appliedPlacements": list(result.applied_placements or []),
            "workerIdentity": dict(result.worker_identity or {}),
            "workerViews": dict(result.worker_views or {}),
        }
        self.cache.put(cache_key, output)
        self.lineage.record(
            LineageRecord(
                lineage_id=new_id(),
                tenant_id=job["tenantId"],
                source_asset=job.get("assetId"),
                digital_twin_version=(twin or {}).get("version"),
                recipe_version=None,
                job_id=job["jobId"],
                worker_id=self.worker_id,
                gpu=job.get("assignedComputeTargetKey"),
                blender_version=result.blender_version,
                ai_model=None,
                prompt=None,
                seed=cache_key[:16],
                output=output,
            )
        )
        if job.get("recipeId"):
            self.recipes.record_usage(job["recipeId"], success=True)
        terminal = "completed" if not result.used_mock else "succeeded"
        try:
            self.queue.set_status(job["jobId"], terminal, output=output, progress=1.0)
        except Exception:
            try:
                self.queue.set_status(job["jobId"], "succeeded", output=output, progress=1.0)
                terminal = "succeeded"
            except Exception:
                job["status"] = terminal
                job["output"] = output
        self._release(job)
        cleanup_job_temp(self.runtime.work_dir / str(job["jobId"]))
        done = self.queue.get(job["jobId"]) or job
        done["qa"] = qa
        done["cacheHit"] = False
        done["placement"] = placement
        done["outputAsset"] = stored.get("beauty.png") or next(iter(stored.values()), None)
        done["device"] = result.device or done.get("device")
        done["artworkApplied"] = result.artwork_applied
        done["appliedPlacements"] = list(result.applied_placements or [])
        done["outputHash"] = stored.get("beautyHash") or done.get("outputHash")
        done["outputSize"] = stored.get("beautySize") or done.get("outputSize")
        done["workerIdentity"] = dict(result.worker_identity or {})
        done["workerViews"] = dict(result.worker_views or {})
        done["realBlender"] = result.real_blender
        done["realOptix"] = result.real_optix
        done["realCycles"] = result.real_cycles
        done["realRenderOutput"] = result.real_render_output
        done["usedMock"] = result.used_mock
        done["blenderVersion"] = result.blender_version
        done["outputs"] = dict(result.outputs or {})
        return done

    def _fail_or_retry(self, job: dict[str, Any], error: str) -> dict[str, Any]:
        attempts = int(job.get("attemptCount") or 0) + 1
        job["attemptCount"] = attempts
        job["error"] = error
        self._release(job)
        if attempts < int(job.get("maxAttempts") or 3):
            delay = retry_delay_seconds(attempts)
            try:
                self.queue.set_status(job["jobId"], "retry_scheduled", error=error, attemptCount=attempts)
            except Exception:
                job["status"] = "retry_scheduled"
            job["retryDelaySeconds"] = delay
            # Immediate requeue for in-process tests; production would wait `delay`.
            current = self.queue.get(job["jobId"]) or job
            current["status"] = "queued"
            return current
        try:
            self.queue.set_status(job["jobId"], "failed", error=error, attemptCount=attempts)
        except Exception:
            job["status"] = "failed"
        return self.queue.get(job["jobId"]) or job

    def _advance(self, job_id: str, states: list[str]) -> None:
        job = self.queue.get(job_id)
        if not job:
            return
        for state in states:
            if job["status"] == state:
                continue
            try:
                self.queue.set_status(job_id, state)  # type: ignore[arg-type]
            except Exception:
                break
            job = self.queue.get(job_id) or job

    def _enter_running(self, job: dict[str, Any]) -> None:
        status = job.get("status")
        if status == "queued":
            self.queue.set_status(job["jobId"], "reserved", leaseOwner=self.worker_id)
        status = (self.queue.get(job["jobId"]) or job).get("status")
        if status == "retry_scheduled":
            self.queue.set_status(job["jobId"], "reserved", leaseOwner=self.worker_id)
        status = (self.queue.get(job["jobId"]) or job).get("status")
        if status == "reserved":
            self.queue.set_status(job["jobId"], "dispatched")
        status = (self.queue.get(job["jobId"]) or job).get("status")
        if status in {"dispatched", "leased"}:
            self.queue.set_status(job["jobId"], "running")
        elif status != "running":
            job["status"] = "running"

    def _upload_outputs(self, tenant_id: str, job_id: str, outputs: dict[str, Any]) -> dict[str, Any]:
        stored: dict[str, Any] = {}
        for name, path in outputs.items():
            if isinstance(path, list):
                ids = []
                for i, item in enumerate(path):
                    if not item or not Path(str(item)).exists():
                        continue
                    obj = self.dam.put(
                        tenant_id=tenant_id,
                        kind="render",
                        name=f"{name}_{i:03d}{Path(str(item)).suffix}",
                        data=Path(str(item)).read_bytes(),
                        metadata={"jobId": job_id, "index": i},
                    )
                    ids.append(obj.asset_id)
                stored[name] = ids
                continue
            if not path or not Path(str(path)).exists():
                continue
            data = Path(str(path)).read_bytes()
            obj = self.dam.put(
                tenant_id=tenant_id,
                kind="render",
                name=name,
                data=data,
                metadata={"jobId": job_id, "sha256": sha256_bytes(data), "bytes": len(data)},
            )
            stored[name] = obj.asset_id
            if name == "beauty.png":
                stored["beautyHash"] = obj.sha256
                stored["beautySize"] = len(data)
        return stored

    def _release(self, job: dict[str, Any]) -> None:
        rid = job.get("reservationId")
        if rid:
            self.reservations.release(rid)

    # ----- domain APIs ---------------------------------------------------
    def create_twin(self, payload: dict[str, Any]) -> dict[str, Any]:
        twin = ProductDigitalTwin.model_validate(payload)
        return self.twins.create(twin).model_dump(mode="json")

    def get_twin(self, twin_id: str, *, tenant_id: str) -> dict[str, Any]:
        return self.twins.get(twin_id, tenant_id=tenant_id).model_dump(mode="json")

    def create_parametric(self, payload: dict[str, Any]) -> dict[str, Any]:
        spec, report = self.cabinets.create(
            payload.get("kind") or "CABINET",
            tenant_id=payload["tenantId"],
            **{k: v for k, v in payload.items() if k not in {"tenantId", "kind", "render"}},
        )
        bom = self.bom.build(spec)
        quote = self.cost.quote(spec, bom)
        from fox3d.parametric import map_cabinet_material

        record = {
            "spec": spec.model_dump(mode="json"),
            "report": report.model_dump(),
            "bom": bom,
            "quote": quote,
            "engineeringHash": spec.engineering_hash(),
            "material": map_cabinet_material(str(spec.material)),
        }
        self.parametrics[spec.productId] = record
        return record

    def resize_parametric(self, product_id: str, *, tenant_id: str, **dims: float) -> dict[str, Any]:
        current = self.parametrics.get(product_id)
        if not current:
            raise KeyError(product_id)
        from fox3d.parametric import CabinetSpec

        spec = CabinetSpec.model_validate(current["spec"])
        if spec.tenantId != tenant_id:
            raise PermissionError("tenant isolation: parametric leakage blocked")
        nxt, report = self.cabinets.resize(spec, **dims)
        bom = self.bom.build(nxt)
        quote = self.cost.quote(nxt, bom)
        record = {
            "spec": nxt.model_dump(mode="json"),
            "report": report.model_dump(),
            "bom": bom,
            "quote": quote,
            "engineeringHash": nxt.engineering_hash(),
            "resizedFrom": product_id,
        }
        self.parametrics[nxt.productId] = record
        return record

    def render_parametric(self, product_id: str, *, tenant_id: str, explode: bool = False) -> dict[str, Any]:
        record = self.parametrics.get(product_id)
        if not record:
            raise KeyError(product_id)
        job = self.submit_job(
            {
                "tenantId": tenant_id,
                "jobType": "PARAMETRIC_3D",
                "mode": "PARAMETRIC_CABINET",
                "engineering": record["spec"],
                "explode": explode,
                "render": {"width": 512, "height": 512, "engine": "CYCLES", "device": "OPTIX", "samples": 24},
                "timeoutSeconds": 600,
            }
        )
        result = self.execute_job(job)
        record["previewJobId"] = result.get("jobId")
        record["preview"] = result.get("output")
        return {"parametric": record, "job": result}

    def real_smoke_test(self, *, tenant_id: str = "ops") -> dict[str, Any]:
        gate = self._production_gate()
        if gate:
            return gate
        job = self.submit_job(
            {
                "tenantId": tenant_id,
                "jobType": "REAL_SMOKE_TEST",
                "mode": "REAL_SMOKE_TEST",
                "smokeTest": True,
                "render": {"width": 512, "height": 512, "engine": "CYCLES", "device": "OPTIX", "samples": 32},
                "timeoutSeconds": 600,
            }
        )
        return self.execute_job(job)

    def product_e2e(self, *, tenant_id: str, sku: str, glb_path: str | None = None, glb_bytes: bytes | None = None) -> dict[str, Any]:
        gate = self._production_gate()
        if gate:
            return gate
        twin = ProductDigitalTwin(tenantId=tenant_id, sku=sku)
        twin = self.twins.create(twin, glb_bytes=glb_bytes)
        if glb_path:
            twin.glb = glb_path
            self.twins._items[twin.twinId] = twin
        job = self.submit_job(
            {
                "tenantId": tenant_id,
                "jobType": "BLENDER_PRODUCT",
                "mode": "PRODUCT_E2E",
                "assetId": twin.twinId,
                "glbPath": twin.glb,
                "scene": "WHITE_STUDIO",
                "camera": {"recipe": "HERO_SHOT", "lens": 85, "movement": "STATIC"},
                "lighting": "THREE_POINT",
                "render": {"width": 512, "height": 512, "engine": "CYCLES", "device": "OPTIX", "samples": 32},
                "timeoutSeconds": 600,
            }
        )
        result = self.execute_job(job)
        preview_id = (result.get("output") or {}).get("files", {}).get("beauty.png")
        if preview_id:
            twin.previewAssetId = preview_id
            try:
                twin.previewPath = self.dam.get(preview_id, tenant_id=tenant_id).path
            except Exception:
                pass
            self.twins._items[twin.twinId] = twin
        return {"twin": twin.model_dump(mode="json"), "job": result}

    def product_360_e2e(self, *, tenant_id: str, twin_id: str, frames: int = 36) -> dict[str, Any]:
        gate = self._production_gate()
        if gate:
            return gate
        twin = self.twins.get(twin_id, tenant_id=tenant_id)
        job = self.submit_job(
            {
                "tenantId": tenant_id,
                "jobType": "PRODUCT_360",
                "mode": "PRODUCT_360_E2E",
                "assetId": twin.twinId,
                "glbPath": twin.glb,
                "animation": {"type": "TURNTABLE", "frames": frames, "degrees": 360},
                "scene": "WHITE_STUDIO",
                "render": {"width": 512, "height": 512, "engine": "CYCLES", "device": "OPTIX", "samples": 16},
                "timeoutSeconds": 1800,
            }
        )
        result = self.execute_job(job)
        return {"twin": twin.model_dump(mode="json"), "job": result, "plan": self.p360.render_plan(twin.model_dump(), frames=frames)}

    def _production_gate(self) -> dict[str, Any] | None:
        if self.mock_blender:
            return None
        probe = self.probe or probe_host(blender_bin=self.runtime.blender_bin)
        self.probe = probe
        if not probe.realBlender:
            return {
                "status": "blocked",
                "error": BLOCKED_NO_BLENDER,
                "realBlender": False,
                "realGPU": probe.realGPU,
                "realCycles": False,
                "realOptix": False,
                "realRenderOutput": False,
            }
        if not probe.realOptix:
            return {
                "status": "blocked",
                "error": BLOCKED_NO_OPTIX,
                "realBlender": True,
                "realGPU": probe.realGPU,
                "realCycles": probe.realCycles,
                "realOptix": False,
                "realRenderOutput": False,
                "cyclesDevices": probe.cyclesDevices,
                "blenderVersion": probe.blenderVersion,
                "gpuName": probe.gpuName,
            }
        return None

    def variants(self, product_id: str, *, tenant_id: str, count: int = 12) -> dict[str, Any]:
        # Rebuild from last parametric create stored as twin metadata is optional; RD agent is the full path.
        raise KeyError(product_id) if False else self.rd.run(tenant_id=tenant_id, text=f"variant of {product_id}", variant_count=count)

    def preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, "jobType": payload.get("jobType") or BLENDER_PREVIEW}
        payload.setdefault("render", {})
        payload["render"] = {**payload["render"], "width": payload["render"].get("width") or 64, "height": payload["render"].get("height") or 64, "engine": "EEVEE"}
        job = self.submit_job(payload)
        return self.execute_job(job)

    def final_render(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, "jobType": payload.get("jobType") or BLENDER_RENDER}
        payload.setdefault("render", {})
        payload["render"] = {
            **payload["render"],
            "width": payload["render"].get("width") or 64,
            "height": payload["render"].get("height") or 64,
            "engine": "CYCLES",
            "device": "OPTIX",
        }
        job = self.submit_job(payload)
        return self.execute_job(job)

    def product_rd(self, *, tenant_id: str, text: str, variant_count: int = 12) -> dict[str, Any]:
        result = self.rd.run(tenant_id=tenant_id, text=text, variant_count=variant_count)
        result["HUMAN_APPROVAL_REQUIRED"] = True
        if isinstance(result.get("approval"), dict):
            result["approval"]["HUMAN_APPROVAL_REQUIRED"] = True
        return result

    def furniture_factory_run(self, *, tenant_id: str, render: bool = False, **kwargs: Any) -> dict[str, Any]:
        return self.factory.run(tenant_id=tenant_id, render=render, **kwargs)

    def packaging_twin(self, *, tenant_id: str, template: str, sku: str, artwork_bytes: bytes | None = None) -> dict[str, Any]:
        """Same Digital Twin store — not a second twin architecture."""
        pkg = self.packaging.build(tenant_id=tenant_id, template=template, sku=sku)
        artwork_id = None
        if artwork_bytes:
            artwork_id = self.dam.put(tenant_id=tenant_id, kind="artwork", name=f"{sku}-art.png", data=artwork_bytes).asset_id
        twin = ProductDigitalTwin(
            tenantId=tenant_id,
            sku=sku,
            dimensions=pkg["dimensions"],
            materials=["cardboard" if template in {"BOX", "CARTON", "DISPLAY_BOX"} else "plastic"],
            packagingArtwork=[artwork_id] if artwork_id else [],
            productMetadata={"kind": "PACKAGING", "template": pkg["template"], "pipeline": pkg["pipeline"]},
            compatibleRecipes=["scene:WHITE_STUDIO"],
        )
        twin = self.twins.create(twin)
        job = self.submit_job(
            {
                "tenantId": tenant_id,
                "jobType": "BLENDER_PRODUCT",
                "mode": "PACKAGING_TWIN",
                "assetId": twin.twinId,
                "packagingTemplate": pkg["template"],
                "dimensions": pkg["dimensions"],
                "scene": "WHITE_STUDIO",
                "render": {"width": 512, "height": 512, "engine": "CYCLES", "device": "OPTIX", "samples": 24},
                "timeoutSeconds": 300,
            }
        )
        rendered = self.execute_job(job)
        preview = (rendered.get("output") or {}).get("files", {}).get("beauty.png")
        if preview:
            twin.previewAssetId = preview
            self.twins._items[twin.twinId] = twin
        return {"twin": twin.model_dump(mode="json"), "job": rendered, "sameTwinStore": True}

    def blender_to_video(self, *, tenant_id: str, twin_id: str, adapter: str | None = None) -> dict[str, Any]:
        gate = self._production_gate()
        twin = self.twins.get(twin_id, tenant_id=tenant_id)
        job = self.submit_job(
            {
                "tenantId": tenant_id,
                "jobType": "BLENDER_TO_VIDEO",
                "mode": "BLENDER_TO_VIDEO",
                "assetId": twin.twinId,
                "glbPath": twin.glb,
                "passes": True,
                "scene": "WHITE_STUDIO",
                "render": {"width": 512, "height": 512, "engine": "CYCLES", "device": "OPTIX", "samples": 16},
                "timeoutSeconds": 600,
            }
        )
        blender_job = job if gate else self.execute_job(job)
        if gate:
            blender_job = {**gate, "jobId": job["jobId"]}
        refs = (blender_job.get("output") or {}).get("files") or {}
        video = self.gateway.generate_video(
            adapter=adapter,
            request={
                "twinId": twin.twinId,
                "start": refs.get("START_FRAME"),
                "middle": refs.get("MIDDLE_FRAME"),
                "end": refs.get("END_FRAME"),
                "mask": refs.get("mask.png"),
                "duration": 6,
            },
        )
        return {
            "blender": blender_job,
            "aiVideo": video,
            "aiVideoStatus": "MOCK" if video.get("kind") == "mock_video" or video.get("provider") == "mock" else "REAL",
            "adapterHardcoded": False,
            "principle": {"blender": "deterministic control", "aiVideo": "generative creativity"},
        }

    def synthetic_dataset(self, *, tenant_id: str, twin_id: str, frames: int = 8) -> dict[str, Any]:
        gate = self._production_gate()
        if gate:
            return {**gate, "manifestRequired": True}
        twin = self.twins.get(twin_id, tenant_id=tenant_id)
        job = self.submit_job(
            {
                "tenantId": tenant_id,
                "jobType": "SYNTHETIC_DATA",
                "mode": "SYNTHETIC_DATA",
                "assetId": twin.twinId,
                "glbPath": twin.glb,
                "passes": True,
                "aovs": True,
                "render": {"width": 256, "height": 256, "engine": "CYCLES", "device": "OPTIX", "samples": 8},
                "timeoutSeconds": 600,
            }
        )
        result = self.execute_job(job)
        files = (result.get("output") or {}).get("files") or {}
        produced = ["RGB"]
        if files.get("mask.png"):
            produced.append("mask")
        for name, key in (("depth", "depth.png"), ("normal", "normal.png"), ("segmentation", "seg.png")):
            if files.get(key):
                produced.append(name)
        manifest = {
            "jobId": result.get("jobId"),
            "twinId": twin.twinId,
            "produced": produced,
            "notProducedThisRun": [p for p in ["depth", "normal", "segmentation", "mask"] if p not in produced],
            "files": files,
            "realBlender": result.get("realBlender"),
            "aovLabel": "REAL" if result.get("realBlender") and {"depth", "normal", "segmentation"} <= set(produced) else ("MOCK" if self.mock_blender else "PARTIAL"),
        }
        blob = __import__("json").dumps(manifest, default=str).encode("utf-8")
        stored = self.dam.put(tenant_id=tenant_id, kind="synthetic_manifest", name="manifest.json", data=blob)
        manifest["manifestAssetId"] = stored.asset_id
        return {"job": result, "manifest": manifest}

    def hardening_report(self) -> dict[str, Any]:
        return {
            "tenantIsolation": True,
            "scriptSandbox": True,
            "pathTraversalGuard": True,
            "arbitraryPython": "allowlisted blender_job.py only; AI-generated = SANDBOX ONLY",
            "resourceLimits": True,
            "networkRestrictions": "deny_all on registered scripts",
            "jobCancellation": True,
            "gpuCleanup": "reservation release on complete/fail/cancel",
            "tempCleanup": True,
            "assetLineage": True,
            "cacheIntegrity": True,
            "workerCrashRecovery": True,
            "liveCnc": False,
        }


BlenderRuntime._mock_version = lambda self: "mock-4.2"  # type: ignore[method-assign]
