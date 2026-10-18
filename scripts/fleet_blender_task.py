#!/usr/bin/env python3
# SPDX-License-Identifier: UNLICENSED
"""Node-side executor for the NetFox GPU Fleet task type ``blender_scene_render``.

The fleet agent on a Linux GPU node runs this as a subprocess, for example::

    python3 fleet_blender_task.py --json '{"jobId": "...", "job": {...}}' \
        --blender /opt/blender/blender --script /opt/fox3d/scripts/blender_job.py \
        --assets-root /data/fox3d/assets --work-root /data/fox3d/work \
        --out-dir /data/comfy/output --public-url http://node:8188 --timeout 600

Contract with the agent:

* standard library only (node Python is 3.14, no third-party packages);
* the LAST stdout line is exactly one JSON object, everything else goes to stderr;
* exit 0 with ``{"status": "succeeded", ...}`` or exit 1 with
  ``{"status": "failed", "error": ..., "stderrTail": ...}``.

Test hook: when ``--blender`` points at a ``*.py`` file it is executed with the current
interpreter (``sys.executable``) instead of as a Blender binary, with the same argv tail
(``-b --factory-startup -P <script> -- job.json``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

JsonDict = dict[str, Any]

TASK_TYPE = "blender_scene_render"
USER_AGENT = "fox3d-fleet-blender-task/1.0"
DEFAULT_TIMEOUT_SEC = 600.0
PRUNE_AGE_SEC = 3 * 24 * 3600.0
PROGRESS_INTERVAL_SEC = 2.0
PROGRESS_POST_TIMEOUT_SEC = 3.0
WAIT_SLICE_SEC = 0.25
TERMINATE_GRACE_SEC = 5.0
SCENE_DEFINITION_JSON_KEY = "sceneDefinitionJson"  # see fox3d.fleet_blender.fleet_job_payload
STDERR_TAIL_CHARS = 1500
LOG_TAIL_CHARS = 4000
MIN_OUTPUT_BYTES = 32
JOB_ID_MAX_LEN = 80
SUCCESS_STATUSES = frozenset({"succeeded", "completed"})

JOB_FILE = "job.json"
PROGRESS_FILE = "progress.json"
CANCEL_FILE = "cancel.flag"
RESULT_FILE = "result.json"
LOG_FILE = "blender.log"

BEAUTY = "beauty.png"
CUTOUT = "product_cutout.png"
MODEL_GLB = "model.glb"
MODEL_BLEND = "model.blend"
ARTIFACT_ORDER: tuple[str, ...] = (BEAUTY, CUTOUT, MODEL_GLB, MODEL_BLEND)
MODEL_ARTIFACTS = frozenset({MODEL_GLB, MODEL_BLEND})
ARTIFACT_MIME = {
    BEAUTY: "image/png",
    CUTOUT: "image/png",
    MODEL_GLB: "model/gltf-binary",
    MODEL_BLEND: "application/octet-stream",
}
ARTIFACT_KIND = {BEAUTY: "image", CUTOUT: "image", MODEL_GLB: "file", MODEL_BLEND: "file"}

_JOB_ID_BAD_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


class TaskError(Exception):
    """Failure with a short operator-facing reason; becomes the ``error`` field."""


def log(message: str) -> None:
    """All diagnostics go to stderr; stdout is reserved for the final JSON line."""
    print(message, file=sys.stderr, flush=True)


def emit(line: JsonDict) -> None:
    sys.stdout.write(json.dumps(line) + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------- arguments


class _Parser(argparse.ArgumentParser):
    """argparse that raises instead of printing usage and exiting 2 (keeps the JSON contract)."""

    def error(self, message: str) -> NoReturn:
        raise TaskError(f"bad arguments: {message}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="fleet_blender_task", description=f"Fleet executor for {TASK_TYPE}")
    parser.add_argument("--json", dest="payload_json", default=None, help="inline inputPayload JSON")
    parser.add_argument("--payload-file", dest="payload_file", default=None, help="file holding inputPayload JSON")
    parser.add_argument("--blender", required=True, help="Blender binary (a *.py path runs under sys.executable)")
    parser.add_argument("--script", required=True, help="path to scripts/blender_job.py")
    parser.add_argument("--assets-root", required=True, help="exported to Blender as FOX3D_ASSETS_ROOT")
    parser.add_argument("--work-root", required=True, help="per-job work dirs are created under here")
    parser.add_argument("--out-dir", required=True, help="output root served by --public-url /view")
    parser.add_argument("--public-url", required=True, help="http base used to build artifact URLs")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SEC, help="hard cap in seconds")
    parser.add_argument("--subfolder-style", choices=("nested", "flat"), default="nested")
    return parser


def load_payload(inline: str | None, payload_file: str | None) -> JsonDict:
    """Load inputPayload from ``--payload-file`` (preferred when both are given) or ``--json``."""
    if payload_file:
        try:
            raw = Path(payload_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise TaskError(f"payload file unreadable: {exc}") from None
        source = payload_file
    elif inline is not None:
        raw, source = inline, "--json"
    else:
        raise TaskError("payload missing: pass --json or --payload-file")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise TaskError(f"payload is not valid JSON ({source}): {exc}") from None
    if not isinstance(data, dict):
        raise TaskError("payload must be a JSON object")
    return data


def parse_payload_args(argv: list[str]) -> tuple[argparse.Namespace, JsonDict]:
    """Parse the CLI and load the payload; raises TaskError on any problem."""
    args = build_arg_parser().parse_args(argv)
    return args, load_payload(args.payload_json, args.payload_file)


# --------------------------------------------------------------------------- small pure helpers


def sanitize_job_id(raw: object) -> str:
    """``[A-Za-z0-9_.-]`` only, at most 80 chars, never empty, never starting with a dot."""
    text = "" if raw is None else str(raw).strip()
    text = _JOB_ID_BAD_CHARS.sub("_", text).lstrip(".")[:JOB_ID_MAX_LEN]
    return text or uuid.uuid4().hex


def resolve_job_id(payload: JsonDict) -> str:
    raw = payload.get("jobId")
    job = payload.get("job")
    if raw in (None, "") and isinstance(job, dict):
        raw = job.get("jobId")
    return sanitize_job_id(raw)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    number = _as_float(value)
    return None if number is None else int(number)


def _as_str(value: object) -> str | None:
    return None if value is None else str(value)


def effective_timeout(payload_value: object, cli_timeout: float) -> float:
    """``min(payload.timeoutSec, --timeout)``; the CLI value is the hard cap."""
    if cli_timeout <= 0:
        raise TaskError("--timeout must be positive")
    requested = _as_float(payload_value)
    if requested is None or requested <= 0:
        return cli_timeout
    return min(requested, cli_timeout)


def output_subfolder(job_id: str, style: str) -> str:
    return f"fox3d_{job_id}" if style == "flat" else f"fox3d/{job_id}"


def artifact_url(public_url: str, name: str, subfolder: str) -> str:
    query = urllib.parse.urlencode({"filename": name, "subfolder": subfolder, "type": "output"})
    return f"{public_url.rstrip('/')}/view?{query}"


def artifact_list(names: Iterable[str], *, public_url: str, subfolder: str, export_models: bool) -> list[JsonDict]:
    """Fixed order: beauty.png, product_cutout.png if present, then model.glb/model.blend when exporting."""
    present = set(names)
    artifacts: list[JsonDict] = []
    for name in ARTIFACT_ORDER:
        if name not in present or (name in MODEL_ARTIFACTS and not export_models):
            continue
        artifacts.append(
            {
                "name": name,
                "url": artifact_url(public_url, name, subfolder),
                "mimeType": ARTIFACT_MIME[name],
                "kind": ARTIFACT_KIND[name],
                "storage": "url",
            }
        )
    return artifacts


def build_result(
    result: JsonDict | None, artifacts: list[JsonDict], *, total_sec: float, blender_sec: float
) -> JsonDict:
    """Compose the success line from blender_job.py's result.json and the published artifacts."""
    if not artifacts or artifacts[0].get("name") != BEAUTY:
        raise TaskError(f"{BEAUTY} missing")
    source = result or {}
    render_sec = _as_float(source.get("renderTimeSec"))
    image = {key: value for key, value in artifacts[0].items() if key != "name"}
    return {
        "status": "succeeded",
        "image": image,
        "artifacts": artifacts,
        "renderTimeSec": render_sec,
        "blenderVersion": _as_str(source.get("blenderVersion")),
        "device": _as_str(source.get("device")),
        "engine": _as_str(source.get("engine")),
        "samples": _as_int(source.get("samples")),
        "hasCutout": any(item.get("name") == CUTOUT for item in artifacts),
        "metrics": {
            "totalSec": round(total_sec, 3),
            "renderSec": render_sec,
            "blenderSec": round(blender_sec, 3),
        },
    }


def tail_text(path: Path | None, limit: int) -> str:
    if path is None:
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")[-limit:]


def failure_line(error: str, log_path: Path | None) -> JsonDict:
    return {"status": "failed", "error": error[:300], "stderrTail": tail_text(log_path, STDERR_TAIL_CHARS)}


def prune_outputs(out_dir: Path, *, max_age_sec: float = PRUNE_AGE_SEC, now: float | None = None) -> list[Path]:
    """Delete ``<out-dir>/fox3d/*`` and ``<out-dir>/fox3d_*`` directories older than ``max_age_sec``."""
    cutoff = (time.time() if now is None else now) - max_age_sec
    candidates: list[Path] = []
    try:
        nested_root = out_dir / "fox3d"
        if nested_root.is_dir():
            candidates.extend(path for path in nested_root.iterdir() if path.is_dir())
        if out_dir.is_dir():
            candidates.extend(path for path in out_dir.glob("fox3d_*") if path.is_dir())
    except OSError as exc:
        log(f"[prune] cannot list {out_dir}: {exc}")
        return []
    pruned: list[Path] = []
    for path in candidates:
        try:
            if path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(path, ignore_errors=True)
        pruned.append(path)
    return pruned


# --------------------------------------------------------------------------- progress


def progress(percent: float, note: str) -> bool:
    """POST ``{"percent","note"}`` to FLEET_PROGRESS_URL; never raises, returns True when delivered."""
    url = os.environ.get("FLEET_PROGRESS_URL")
    api_key = os.environ.get("FLEET_API_KEY")
    if not url or not api_key:
        return False
    body = json.dumps({"percent": round(float(percent), 2), "note": str(note)}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Api-Key": api_key, "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=PROGRESS_POST_TIMEOUT_SEC):
            pass
    except Exception:  # progress must never break the task
        return False
    return True


def read_progress(path: Path) -> tuple[float, str] | None:
    """Accept blender_job.py's ``{"progress": 0..1, "stage"}`` or ``{"percent": 0..100, "note"}``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if "percent" in data:
        raw, scale = data.get("percent"), 1.0
    elif "progress" in data:
        raw, scale = data.get("progress"), 100.0
    else:
        return None
    number = _as_float(raw)
    if number is None:
        return None
    note = str(data.get("note") or data.get("stage") or "")
    return max(0.0, min(100.0, number * scale)), note


class ProgressForwarder:
    """Reads progress.json and forwards changes through ``sink`` (defaults to :func:`progress`)."""

    def __init__(self, progress_file: Path, sink: Callable[[float, str], bool] | None = None) -> None:
        self.progress_file = progress_file
        self.sink: Callable[[float, str], bool] = progress if sink is None else sink
        self.last: tuple[float, str] | None = None

    def poll(self) -> None:
        current = read_progress(self.progress_file)
        if current is None or current == self.last:
            return
        self.last = current
        try:
            self.sink(current[0], current[1])
        except Exception as exc:  # progress must never break the task
            log(f"[progress] forward failed: {exc}")


# --------------------------------------------------------------------------- blender subprocess


@dataclass(frozen=True)
class BlenderRun:
    returncode: int | None
    timed_out: bool
    elapsed_sec: float
    log_path: Path


def blender_command(blender: str, script: str, job_file: Path) -> list[str]:
    """Headless Blender argv; a ``*.py`` "blender" (test hook) runs under the current interpreter."""
    head = [sys.executable, blender] if blender.lower().endswith(".py") else [blender]
    return [*head, "-b", "--factory-startup", "-P", script, "--", str(job_file)]


def kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Stop Blender and (on POSIX) its whole process group, escalating to SIGKILL."""
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except OSError:
                proc.kill()
            try:
                proc.wait(timeout=TERMINATE_GRACE_SEC)
                return
            except subprocess.TimeoutExpired:
                continue
        return
    proc.kill()
    try:
        proc.wait(timeout=TERMINATE_GRACE_SEC)
    except subprocess.TimeoutExpired:
        pass


def run_blender(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    timeout_sec: float,
    forwarder: ProgressForwarder,
) -> BlenderRun:
    """Run Blender with stdout+stderr in ``log_path``, polling progress every ~2 s, killing on timeout."""
    started = time.monotonic()
    timed_out = False
    popen_kwargs: dict[str, Any] = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True
    with log_path.open("ab") as log_fh:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )
        except OSError as exc:
            raise TaskError(f"cannot start blender: {exc}") from None
        deadline = started + timeout_sec
        next_poll = started + PROGRESS_INTERVAL_SEC
        while True:
            try:
                proc.wait(timeout=WAIT_SLICE_SEC)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                log(f"[{TASK_TYPE}] timeout after {timeout_sec:g}s, killing blender pid={proc.pid}")
                kill_process_tree(proc)
                break
            if now >= next_poll:
                forwarder.poll()
                next_poll = now + PROGRESS_INTERVAL_SEC
    elapsed = time.monotonic() - started
    forwarder.poll()
    return BlenderRun(returncode=proc.returncode, timed_out=timed_out, elapsed_sec=elapsed, log_path=log_path)


def echo_log_tail(log_path: Path) -> None:
    tail = tail_text(log_path, LOG_TAIL_CHARS)
    if tail:
        log(f"--- {LOG_FILE} tail ---\n{tail.rstrip()}\n--- end {LOG_FILE} ---")


# --------------------------------------------------------------------------- job plumbing


def prepare_work_dir(work_root: Path, job_id: str, job: JsonDict, *, export_models: bool) -> Path:
    """Fresh ``<work-root>/<jobId>`` with job.json; only top-level keys are touched (engineering is kept as is)."""
    work_dir = work_root / job_id
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    doc = dict(job)
    engineering = doc.get("engineering")
    if isinstance(engineering, dict) and isinstance(engineering.get(SCENE_DEFINITION_JSON_KEY), str):
        # authoritative copy: the console round trip may have turned 0.0 into 0 inside the object form
        engineering = dict(engineering)
        engineering["sceneDefinition"] = json.loads(engineering.pop(SCENE_DEFINITION_JSON_KEY))
        doc["engineering"] = engineering
    doc.setdefault("jobId", job_id)
    doc["workDir"] = str(work_dir)
    doc["progressFile"] = str(work_dir / PROGRESS_FILE)
    doc["cancelFile"] = str(work_dir / CANCEL_FILE)
    doc["exportBlend"] = export_models
    doc["exportGlb"] = export_models
    (work_dir / JOB_FILE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return work_dir


def read_result(work_dir: Path) -> JsonDict | None:
    try:
        data = json.loads((work_dir / RESULT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def locate_output(work_dir: Path, name: str, result: JsonDict | None) -> Path | None:
    """``<workDir>/<name>`` or the path in ``result.outputs[name]``; must hold at least MIN_OUTPUT_BYTES."""
    candidates = [work_dir / name]
    outputs = (result or {}).get("outputs")
    if isinstance(outputs, dict):
        hinted = outputs.get(name)
        if isinstance(hinted, str) and hinted:
            hinted_path = Path(hinted)
            candidates.append(hinted_path if hinted_path.is_absolute() else work_dir / hinted_path)
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size >= MIN_OUTPUT_BYTES:
                return candidate
        except OSError:
            continue
    return None


def collect_outputs(work_dir: Path, result: JsonDict | None, *, export_models: bool) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for name in ARTIFACT_ORDER:
        if name in MODEL_ARTIFACTS and not export_models:
            continue
        path = locate_output(work_dir, name, result)
        if path is not None:
            found[name] = path
    return found


def failure_reason(run: BlenderRun, result: JsonDict | None, found: dict[str, Path]) -> str | None:
    """None when blender_job.py reported success and beauty.png is present; otherwise a short reason."""
    if result is None:
        return f"blender exit {run.returncode}: no {RESULT_FILE}"
    status = str(result.get("status") or "")
    if status in SUCCESS_STATUSES:
        return None if BEAUTY in found else f"{BEAUTY} missing"
    detail = str(result.get("error") or "").strip()
    reason = f"blender {status or 'failed'}"
    return f"{reason}: {detail}" if detail else f"{reason} (exit {run.returncode})"


def publish_outputs(found: dict[str, Path], out_dir: Path, subfolder: str) -> Path:
    dest = out_dir.joinpath(*subfolder.split("/"))
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    for name, src in found.items():
        shutil.copy2(src, dest / name)
    return dest


# --------------------------------------------------------------------------- entry point


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    log_path: Path | None = None
    work_dir: Path | None = None
    try:
        args, payload = parse_payload_args(sys.argv[1:] if argv is None else argv)
        out_dir = Path(args.out_dir).expanduser().resolve()
        work_root = Path(args.work_root).expanduser().resolve()
        assets_root = Path(args.assets_root).expanduser().resolve()
        try:
            pruned = prune_outputs(out_dir)
        except Exception as exc:  # housekeeping never fails the task
            pruned = []
            log(f"[prune] skipped: {exc}")
        if pruned:
            log(f"[prune] removed {len(pruned)} output dir(s) older than {PRUNE_AGE_SEC / 86400:g} days")

        job = payload.get("job")
        if not isinstance(job, dict):
            raise TaskError("payload.job must be an object")
        export_models = bool(payload.get("exportModels", False))
        timeout_sec = effective_timeout(payload.get("timeoutSec"), float(args.timeout))
        job_id = resolve_job_id(payload)
        subfolder = output_subfolder(job_id, str(args.subfolder_style))

        script = Path(args.script)
        if not script.is_file():
            raise TaskError(f"script not found: {script}")
        blender = str(args.blender)
        if not (Path(blender).is_file() or shutil.which(blender)):
            raise TaskError(f"blender not found: {blender}")

        work_dir = prepare_work_dir(work_root, job_id, job, export_models=export_models)
        log_path = work_dir / LOG_FILE
        env = dict(os.environ)
        env["FOX3D_ASSETS_ROOT"] = str(assets_root)
        cmd = blender_command(blender, str(script), work_dir / JOB_FILE)
        log(f"[{TASK_TYPE}] job={job_id} timeout={timeout_sec:g}s exportModels={export_models}")
        log(f"[{TASK_TYPE}] cmd: {' '.join(cmd)}")

        run = run_blender(
            cmd,
            cwd=work_dir,
            env=env,
            log_path=log_path,
            timeout_sec=timeout_sec,
            forwarder=ProgressForwarder(work_dir / PROGRESS_FILE),
        )
        echo_log_tail(log_path)
        if run.timed_out:
            raise TaskError("timeout")
        result = read_result(work_dir)
        found = collect_outputs(work_dir, result, export_models=export_models)
        reason = failure_reason(run, result, found)
        if reason is not None:
            raise TaskError(reason)
        if run.returncode != 0:
            log(f"[{TASK_TYPE}] blender exited {run.returncode} but result.json reports success; continuing")

        dest = publish_outputs(found, out_dir, subfolder)
        artifacts = artifact_list(
            found, public_url=str(args.public_url), subfolder=subfolder, export_models=export_models
        )
        final = build_result(result, artifacts, total_sec=time.monotonic() - started, blender_sec=run.elapsed_sec)
        log(f"[{TASK_TYPE}] published {len(artifacts)} artifact(s) to {dest}")
        emit(final)
        shutil.rmtree(work_dir, ignore_errors=True)
        return 0
    except TaskError as exc:
        reason = str(exc)
    except Exception as exc:  # the agent must always get a JSON line
        reason = f"{type(exc).__name__}: {exc}"
    log(f"[{TASK_TYPE}] FAILED: {reason}")
    if work_dir is not None:
        log(f"[{TASK_TYPE}] work dir kept for debugging: {work_dir}")
    emit(failure_line(reason, log_path))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
