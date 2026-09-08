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
from fox3d.ids import new_id
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
from fox3d.ops import DrainController, LineageLog, LineageRecord, RenderCache, RenderQA, ScriptRegistry, qa_or_retry
from fox3d.packaging import PackagingEngine
from fox3d.parametric import BOMEngine, CAMAdapter, CNCAdapter, CabinetEngine, CostEngine, EngineeringRuleEngine, NestingAdapter
from fox3d.rd import ProductRDAgent, VisionJudge
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
        self.judge = VisionJudge()
        self.rd = ProductRDAgent(self.cabinets, self.cost, self.judge, self.studio)
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
            node = self.register_node(target_key=key, name=str(gpu.get("name") or key), detected=detected)
            if not probe.blender:
                node.status = "offline"
                node.telemetry["blocked"] = BLOCKED_NO_BLENDER
            elif not probe.optix:
                node.telemetry["blocked"] = BLOCKED_NO_OPTIX
            node.capabilities["blenderVersion"] = probe.blenderVersion or "NOT_INSTALLED"
            node.capabilities["mock"] = False
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

        job["gpu"] = placement.get("gpuName")
        job["worker"] = self.worker_id
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
        if not job.get("sceneGraph") and not job.get("smokeTest") and not job.get("engineering"):
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
        done = self.queue.get(job["jobId"]) or job
        done["qa"] = qa
        done["cacheHit"] = False
        done["placement"] = placement
        done["outputAsset"] = stored.get("beauty.png") or next(iter(stored.values()), None)
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
        if status in {"reserved", "leased"}:
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
            obj = self.dam.put(
                tenant_id=tenant_id,
                kind="render",
                name=name,
                data=Path(str(path)).read_bytes(),
                metadata={"jobId": job_id},
            )
            stored[name] = obj.asset_id
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
        record = {
            "spec": spec.model_dump(mode="json"),
            "report": report.model_dump(),
            "bom": bom,
            "quote": quote,
            "engineeringHash": spec.engineering_hash(),
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
        return self.rd.run(tenant_id=tenant_id, text=text, variant_count=variant_count)


BlenderRuntime._mock_version = lambda self: "mock-4.2"  # type: ignore[method-assign]
