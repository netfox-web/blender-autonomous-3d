"""Headless Blender worker: real detect + real subprocess. Mock is tests-only."""

from __future__ import annotations

import json
import os
import platform as py_platform
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from fox3d.ids import stable_hash
from fox3d.pngutil import is_png, write_exr_stub, write_png, write_solid_png, write_webp_stub

ProbeFn = Callable[[list[str]], str]
BLOCKED_NO_BLENDER = "BLOCKED_NO_BLENDER"
BLOCKED_NO_OPTIX = "BLOCKED_NO_OPTIX"


def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, str(exc)


def find_blender(explicit: str | None = None) -> str | None:
    if explicit and Path(explicit).exists():
        return explicit
    env = os.environ.get("BLENDER_PATH")
    if env and Path(env).exists():
        return env
    which = shutil.which("blender")
    if which:
        return which
    roots = [
        Path(r"C:\Program Files\Blender Foundation"),
        Path(r"C:\Program Files (x86)\Blender Foundation"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path("/usr/bin"),
        Path("/Applications/Blender.app/Contents/MacOS"),
    ]
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        pattern = "blender.exe" if os.name == "nt" else "blender"
        try:
            candidates.extend(p for p in root.rglob(pattern) if p.is_file())
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidates[0])


def _vram_gb(raw: str) -> float:
    value = float(raw)
    return round(value / 1024.0, 2) if value > 128 else value


def detect_gpu(probe: ProbeFn | None = None) -> dict[str, Any]:
    """NVIDIA GPU from nvidia-smi. Does NOT claim OptiX. Never hardcodes 5090/5080."""
    runner = probe or (lambda cmd: _run(cmd)[1])
    query = [
        "nvidia-smi",
        "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,driver_version",
        "--format=csv,noheader,nounits",
    ]
    raw = runner(query)
    source = "MOCK" if probe is not None else "REAL_DISCOVERY"
    gpus: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        joined = " ".join(parts).lower()
        if joined.startswith("failed") or "nvidia-smi" in parts[0].lower():
            continue
        try:
            if len(parts) >= 7:
                gpus.append(
                    {
                        "gpuIndex": int(float(parts[0])),
                        "uuid": parts[1],
                        "name": parts[2],
                        "vramGb": _vram_gb(parts[3]),
                        "vramUsedGb": _vram_gb(parts[4]),
                        "vramFreeGb": _vram_gb(parts[5]),
                        "driver": parts[6],
                    }
                )
            else:
                gpus.append(
                    {
                        "gpuIndex": len(gpus),
                        "uuid": None,
                        "name": parts[0],
                        "vramGb": _vram_gb(parts[1]),
                        "vramUsedGb": None,
                        "vramFreeGb": None,
                        "driver": parts[2],
                    }
                )
        except ValueError:
            continue
    if probe is None and not gpus:
        source = "MISSING"
    elif probe is None:
        source = "REAL_DISCOVERY"
    return {
        "gpus": gpus,
        "gpuCount": len(gpus),
        "gpuName": gpus[0]["name"] if gpus else None,
        "gpuUuid": gpus[0].get("uuid") if gpus else None,
        "vramGb": gpus[0]["vramGb"] if gpus else 0,
        "vramUsedGb": gpus[0].get("vramUsedGb") if gpus else None,
        "vramFreeGb": gpus[0].get("vramFreeGb") if gpus else None,
        "cuda": bool(gpus),
        "driver": gpus[0]["driver"] if gpus else None,
        "realGPU": bool(gpus),
        "discoverySource": source,
    }


def detect_blender(blender_bin: str | None = None, probe: ProbeFn | None = None) -> dict[str, Any]:
    binary = blender_bin or find_blender()
    if not binary:
        return {
            "blender": False,
            "blenderVersion": None,
            "cycles": False,
            "eevee": False,
            "binary": None,
            "versionRaw": "",
            "realBlender": False,
        }
    runner = probe or (lambda cmd: _run(cmd, timeout=30)[1])
    text = runner([binary, "-b", "--version"])
    version = None
    for line in text.splitlines():
        if line.strip().startswith("Blender "):
            bits = line.strip().split()
            if len(bits) >= 2:
                version = bits[1]
                break
        elif "Blender" in line and version is None:
            bits = line.strip().split()
            if len(bits) >= 2:
                version = bits[1]
    return {
        "blender": True,
        "blenderVersion": version or "unknown",
        "cycles": True,
        "eevee": True,
        "binary": binary,
        "versionRaw": text[:2000],
        "realBlender": True,
    }


def probe_cycles_devices(blender_bin: str, script_path: Path) -> dict[str, Any]:
    out = Path(os.environ.get("TEMP") or ".") / f"fox3d-cycles-probe-{os.getpid()}.json"
    cmd = [blender_bin, "-b", "--factory-startup", "-P", str(script_path), "--", "--probe", str(out)]
    code, text = _run(cmd, timeout=90)
    payload: dict[str, Any] = {}
    if out.exists():
        try:
            payload = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        try:
            out.unlink()
        except OSError:
            pass
    if not payload:
        payload = {"optix": False, "cuda": False, "devices": [], "error": text[-1500:], "exitCode": code}
    payload["probeLog"] = text[-2000:]
    payload["realCycles"] = bool(payload.get("cycles") or payload.get("devices"))
    payload["realOptix"] = bool(payload.get("optix"))
    return payload


def gpu_target_key(gpu_name: str, gpu_index: int = 0) -> str:
    lower = gpu_name.lower()
    if "5090" in lower:
        return "local-5090"
    if "5080" in lower:
        return "local-5080"
    slug = re.sub(r"[^a-z0-9]+", "-", lower)
    for token in ("nvidia", "geforce", "rtx", "quadro"):
        slug = slug.replace(token, "")
    slug = re.sub(r"-+", "-", slug).strip("-") or f"gpu{gpu_index}"
    return f"local-{slug}"


@dataclass
class HostProbe:
    blender: bool
    blenderBinary: str | None
    blenderVersion: str | None
    blenderVersionRaw: str
    cycles: bool
    cuda: bool
    optix: bool
    cyclesDevices: list[dict[str, Any]] = field(default_factory=list)
    gpus: list[dict[str, Any]] = field(default_factory=list)
    gpuName: str | None = None
    gpuUuid: str | None = None
    vramGb: float = 0
    vramUsedGb: float | None = None
    vramFreeGb: float | None = None
    driver: str | None = None
    hostname: str | None = None
    osName: str | None = None
    discoverySource: str = "MISSING"
    blocked: list[str] = field(default_factory=list)
    realBlender: bool = False
    realGPU: bool = False
    realCycles: bool = False
    realOptix: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_host(*, blender_bin: str | None = None, script_path: Path | None = None) -> HostProbe:
    script = script_path or Path(__file__).resolve().parents[2] / "scripts" / "blender_job.py"
    gpu = detect_gpu()
    blender = detect_blender(blender_bin)
    cycles: dict[str, Any] = {}
    if blender.get("binary"):
        cycles = probe_cycles_devices(str(blender["binary"]), script)
    blocked: list[str] = []
    if not blender.get("blender"):
        blocked.append(BLOCKED_NO_BLENDER)
    elif not cycles.get("optix"):
        blocked.append(BLOCKED_NO_OPTIX)
    return HostProbe(
        blender=bool(blender.get("blender")),
        blenderBinary=blender.get("binary"),
        blenderVersion=blender.get("blenderVersion"),
        blenderVersionRaw=str(blender.get("versionRaw") or ""),
        cycles=bool(cycles.get("realCycles") or blender.get("cycles")),
        cuda=bool(gpu.get("cuda") or cycles.get("cuda")),
        optix=bool(cycles.get("optix")),
        cyclesDevices=list(cycles.get("devices") or []),
        gpus=list(gpu.get("gpus") or []),
        gpuName=gpu.get("gpuName"),
        gpuUuid=gpu.get("gpuUuid"),
        vramGb=float(gpu.get("vramGb") or 0),
        vramUsedGb=gpu.get("vramUsedGb"),
        vramFreeGb=gpu.get("vramFreeGb"),
        driver=gpu.get("driver"),
        hostname=socket.gethostname(),
        osName=py_platform.system(),
        discoverySource=str(gpu.get("discoverySource") or "MISSING"),
        blocked=blocked,
        realBlender=bool(blender.get("realBlender")),
        realGPU=bool(gpu.get("realGPU")),
        realCycles=bool(cycles.get("realCycles")),
        realOptix=bool(cycles.get("realOptix")),
    )


def detect_node(*, blender_bin: str | None = None, gpu_probe: ProbeFn | None = None, blender_probe: ProbeFn | None = None) -> dict[str, Any]:
    gpu = detect_gpu(gpu_probe)
    blender = detect_blender(blender_bin, blender_probe)
    merged = {**gpu, **blender}
    merged["optix"] = False if blender_probe is None and gpu_probe is None else merged.get("optix", False)
    return merged


@dataclass
class RuntimeResult:
    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    progress: float = 0.0
    engine: str = "CYCLES"
    device: str = "CPU"
    error: str | None = None
    used_mock: bool = False
    blender_version: str | None = None
    log: str = ""
    samples: int | None = None
    render_time_sec: float | None = None
    real_blender: bool = False
    real_optix: bool = False
    real_cycles: bool = False
    real_render_output: bool = False
    artwork_applied: bool | None = None
    applied_placements: list[dict[str, Any]] = field(default_factory=list)
    worker_identity: dict[str, Any] = field(default_factory=dict)
    worker_views: dict[str, Any] = field(default_factory=dict)


class BlenderRuntime:
    """Host-side launcher. Production never falls back to mock."""

    def __init__(
        self,
        *,
        blender_bin: str | None = None,
        script_path: Path | None = None,
        work_dir: Path | None = None,
        force_mock: bool | None = None,
    ) -> None:
        self.script_path = script_path or Path(__file__).resolve().parents[2] / "scripts" / "blender_job.py"
        self.work_dir = work_dir or Path.cwd() / ".fox3d-work"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        if force_mock is None:
            self.force_mock = os.environ.get("FOX3D_MOCK_BLENDER", "").lower() in {"1", "true", "yes"}
        else:
            self.force_mock = force_mock
        self.blender_bin = None if self.force_mock else (blender_bin or find_blender())

    def available(self) -> bool:
        return bool(self.blender_bin) and not self.force_mock

    def run_job(
        self,
        job: dict[str, Any],
        *,
        cancel_flag: threading.Event | None = None,
        timeout_seconds: float = 300.0,
        on_progress: Callable[[float], None] | None = None,
        clock_monotonic: Callable[[], float] | None = None,
        clock_sleep: Callable[[float], None] | None = None,
    ) -> RuntimeResult:
        if self.force_mock:
            return self._mock_render(job, cancel_flag=cancel_flag, on_progress=on_progress)
        if not self.blender_bin:
            return RuntimeResult(
                status="blocked",
                error=BLOCKED_NO_BLENDER,
                used_mock=False,
                real_blender=False,
            )
        return self._real_render(
            job,
            cancel_flag=cancel_flag,
            timeout_seconds=timeout_seconds,
            on_progress=on_progress,
            clock_monotonic=clock_monotonic,
            clock_sleep=clock_sleep,
        )

    def _real_render(
        self,
        job: dict[str, Any],
        *,
        cancel_flag: threading.Event | None,
        timeout_seconds: float,
        on_progress: Callable[[float], None] | None,
        clock_monotonic: Callable[[], float] | None,
        clock_sleep: Callable[[float], None] | None,
    ) -> RuntimeResult:
        job_dir = (self.work_dir / str(job["jobId"])).resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
        job_path = (job_dir / "job.json").resolve()
        progress_path = (job_dir / "progress.json").resolve()
        cancel_path = (job_dir / "cancel.flag").resolve()
        result_path = (job_dir / "result.json").resolve()
        job_payload = {
            **job,
            "workDir": str(job_dir),
            "progressFile": str(progress_path),
            "cancelFile": str(cancel_path),
        }
        job_path.write_text(json.dumps(job_payload, default=str), encoding="utf-8")
        cmd = [
            self.blender_bin or "blender",
            "-b",
            "--factory-startup",
            "-P",
            str(self.script_path),
            "--",
            str(job_path),
        ]
        log_path = job_dir / "blender.log"
        log_fh = open(log_path, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT, text=True)
        start = (clock_monotonic or time.monotonic)()
        last_progress_at = start
        last_progress_val = -1.0
        log: list[str] = []
        try:
            while True:
                if cancel_flag and cancel_flag.is_set():
                    cancel_path.write_text("1", encoding="utf-8")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return RuntimeResult(status="cancelled", error="cancel requested", log="".join(log), real_blender=True)
                now = (clock_monotonic or time.monotonic)()
                if now - start > timeout_seconds:
                    proc.kill()
                    return RuntimeResult(status="timeout", error="timeout", log="".join(log), real_blender=True)
                rc = proc.poll()
                if progress_path.exists() and on_progress:
                    try:
                        payload = json.loads(progress_path.read_text(encoding="utf-8"))
                        value = float(payload.get("progress") or 0)
                        on_progress(value)
                        if value != last_progress_val:
                            last_progress_val = value
                            last_progress_at = now
                    except (json.JSONDecodeError, OSError, ValueError):
                        pass
                if now - last_progress_at > 120:
                    proc.kill()
                    return RuntimeResult(
                        status="timeout",
                        error="stall watchdog: no progress for 120s",
                        log="".join(log),
                        real_blender=True,
                    )
                if rc is not None:
                    log_fh.flush()
                    try:
                        log.append(log_path.read_text(encoding="utf-8", errors="replace")[-12000:])
                    except OSError:
                        pass
                    payload: dict[str, Any] = {}
                    if result_path.exists():
                        try:
                            payload = json.loads(result_path.read_text(encoding="utf-8"))
                        except json.JSONDecodeError:
                            payload = {}
                    if payload.get("status") == "blocked" or rc == 3:
                        return RuntimeResult(
                            status="blocked",
                            error=str(payload.get("error") or BLOCKED_NO_OPTIX),
                            log="".join(log),
                            blender_version=payload.get("blenderVersion"),
                            device=str(payload.get("device") or ""),
                            engine="CYCLES",
                            real_blender=True,
                            real_cycles=True,
                            real_optix=False,
                        )
                    outputs = payload.get("outputs") or {}
                    if not outputs:
                        for name in ("beauty.png", "beauty.webp", "beauty.exr"):
                            candidate = job_dir / name
                            if candidate.exists():
                                outputs[name] = str(candidate)
                    png = outputs.get("beauty.png")
                    real_png = bool(png and Path(str(png)).exists() and is_png(Path(str(png))))
                    if rc != 0 and payload.get("status") != "succeeded":
                        return RuntimeResult(
                            status="failed",
                            error=payload.get("error") or f"blender exit {rc}",
                            log="".join(log),
                            outputs=outputs,
                            real_blender=True,
                        )
                    return RuntimeResult(
                        status="succeeded" if real_png or outputs.get("frames") else "failed",
                        outputs=outputs,
                        progress=1.0,
                        engine=str(payload.get("engine") or "CYCLES"),
                        device=str(payload.get("device") or ""),
                        blender_version=str(payload.get("blenderVersion") or ""),
                        log="".join(log),
                        samples=payload.get("samples"),
                        render_time_sec=payload.get("renderTimeSec"),
                        real_blender=True,
                        real_cycles=True,
                        real_optix=bool(payload.get("realOptix")),
                        real_render_output=real_png or bool(outputs.get("frames")),
                        error=None if real_png or outputs.get("frames") else "no real PNG",
                        artwork_applied=payload.get("artworkApplied"),
                        applied_placements=list(payload.get("appliedPlacements") or []),
                        worker_identity=dict(payload.get("workerIdentity") or {}),
                        worker_views=dict(payload.get("workerViews") or {}),
                    )
                (clock_sleep or time.sleep)(0.2)
        finally:
            try:
                log_fh.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.kill()

    def _mock_render(
        self,
        job: dict[str, Any],
        *,
        cancel_flag: threading.Event | None,
        on_progress: Callable[[float], None] | None,
    ) -> RuntimeResult:
        if cancel_flag and cancel_flag.is_set():
            return RuntimeResult(status="cancelled", error="cancel requested", used_mock=True)
        render = job.get("render") or {}
        if render.get("injectFailure") == "timeout":
            return RuntimeResult(status="timeout", error="timeout", used_mock=True)
        job_dir = self.work_dir / str(job["jobId"])
        job_dir.mkdir(parents=True, exist_ok=True)
        if on_progress:
            on_progress(0.15)
        seed = stable_hash({"scene": job.get("scene"), "camera": job.get("camera"), "lighting": job.get("lighting")})
        width = int(render.get("width") or 64)
        height = int(render.get("height") or 64)
        engine = str(render.get("engine") or "CYCLES")
        device = str(render.get("device") or ("OPTIX" if render.get("optix", True) else "CPU"))
        if render.get("injectFailure") == "black_frame":
            write_png(job_dir / "beauty.png", width, height, bytes([0, 0, 0]) * (width * height))
        elif render.get("injectFailure") == "nan":
            write_solid_png(job_dir / "beauty.png", "ffffff", width, height)
            (job_dir / "beauty.png").write_bytes(b"not-a-png")
        else:
            rgb = bytearray(width * height * 3)
            pr, pg, pb = (int(seed[0:2], 16), int(seed[2:4], 16), int(seed[4:6], 16))
            for y in range(height):
                for x in range(width):
                    i = (y * width + x) * 3
                    in_product = width * 0.25 <= x <= width * 0.75 and height * 0.2 <= y <= height * 0.85
                    rgb[i : i + 3] = bytes((pr, pg, pb) if in_product else (240, 240, 245))
            write_png(job_dir / "beauty.png", width, height, bytes(rgb))
        write_webp_stub(job_dir / "beauty.webp")
        write_exr_stub(job_dir / "beauty.exr", seed)
        outputs = {
            "beauty.png": str(job_dir / "beauty.png"),
            "beauty.webp": str(job_dir / "beauty.webp"),
            "beauty.exr": str(job_dir / "beauty.exr"),
        }
        if job.get("productTruthAovs"):
            from fox3d.product_truth import write_occupancy_png

            for role, name in (
                ("depth", "depth.png"),
                ("normal", "normal.png"),
                ("product_mask", "product_mask.png"),
                ("artwork_mask", "artwork_mask.png"),
                ("alpha", "alpha.png"),
            ):
                write_occupancy_png(job_dir / name, width=width, height=height, kind=role, seed=seed + name)
                outputs[name] = str(job_dir / name)
            write_occupancy_png(job_dir / "assembled_front.png", width=width, height=height, kind="beauty", seed=seed + "assembled")
            write_occupancy_png(job_dir / "door_detail.png", width=width, height=height, kind="beauty", seed=seed + "detail")
            outputs["assembled_front.png"] = str(job_dir / "assembled_front.png")
            outputs["door_detail.png"] = str(job_dir / "door_detail.png")
        elif job.get("aovs") or job.get("passes") or job.get("mode") in {"SYNTHETIC_DATA", "SPACE_PREVIEW"}:
            for name in ("depth.png", "normal.png", "seg.png", "mask.png"):
                write_solid_png(job_dir / name, seed + name, max(8, width // 4), max(8, height // 4))
                outputs[name] = str(job_dir / name)
        if job.get("assemblyAnimation"):
            frame_dir = job_dir / "assembly"
            frame_dir.mkdir(parents=True, exist_ok=True)
            frames = []
            for i in range(4):
                p = frame_dir / f"{i:03d}.png"
                write_solid_png(p, seed + f"asm{i}", 32, 32)
                frames.append(str(p))
            mp4 = job_dir / "assembly.mp4"
            mp4.write_bytes(b"ftypisom")
            outputs["assembly.mp4"] = str(mp4)
            outputs["assemblyFrames"] = frames
        if on_progress:
            on_progress(1.0)
        png = job_dir / "beauty.png"
        ok = png.exists() and is_png(png)
        return RuntimeResult(
            status="succeeded" if ok else "failed",
            outputs=outputs,
            progress=1.0 if ok else 0.0,
            engine=engine,
            device=device,
            used_mock=True,
            blender_version="mock-4.2",
            error=None if ok else "mock render failure",
            samples=int(render.get("samples") or 0),
            render_time_sec=0.0,
            real_blender=False,
            real_optix=False,
            real_cycles=False,
            real_render_output=False,
        )
