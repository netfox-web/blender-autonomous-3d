"""Blender Cycles renders on the NetFox GPU fleet (task type ``blender_scene_render``).

The workbench used to run Blender on the office workstation for every matrix item. With this module the same job
document is submitted to the fleet console instead; a GPU node (5090-3 today) runs ``scripts/blender_job.py`` through
``scripts/fleet_blender_task.py`` and publishes ``beauty.png`` / ``product_cutout.png`` as task artifacts, which the
workbench downloads into the item directory so the rest of the pipeline (Plan B compositor, 地端 AI 實景, zip) is
unchanged.

Scene definitions reference bundled models as ``assets://models/...`` (see ``scripts/furnished_scene.py``), so the
scene hash the node verifies is identical to the one computed here. Tenant-uploaded props carry absolute workstation
paths the node cannot read; such items are not fleet-eligible and keep rendering locally.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fox3d.fleet_image_client import TERMINAL_BAD, TERMINAL_OK, FleetError, FleetImageClient, task_error, task_status

BLENDER_TASK_TYPE = "blender_scene_render"
ASSET_REF_PREFIX = "assets://"
BLENDER_ENGINES: dict[str, dict[str, str]] = {
    "auto": {"id": "auto", "label": "自動（艦隊可用就送艦隊，否則本機）"},
    "fleet": {"id": "fleet", "label": "GPU 艦隊 Blender"},
    "local": {"id": "local", "label": "本機 Blender"},
}
DEFAULT_BLENDER_ENGINE = "auto"
FLEET_JOB_STRIP_KEYS = ("workDir", "progressFile", "cancelFile")
# Fixed artifact order published by scripts/fleet_blender_task.py
ARTIFACT_BEAUTY = 0
ARTIFACT_CUTOUT = 1
DEFAULT_RENDER_TIMEOUT_SEC = 900.0


def normalize_blender_engine(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in BLENDER_ENGINES else DEFAULT_BLENDER_ENGINE


def local_fallback_allowed(engine: Any, *, local_available: bool) -> bool:
    """Auto (and an explicit local choice) may render on the workstation. Forced fleet must not."""
    return normalize_blender_engine(engine) != "fleet" and bool(local_available)


def fleet_eligible(scene_definition: dict[str, Any] | None) -> tuple[bool, str]:
    """A scene can be rendered on a node only when every model path is a machine-independent ``assets://`` ref."""
    boxes = (scene_definition or {}).get("boxes") or []
    for box in boxes:
        if not isinstance(box, dict):
            continue
        glb = box.get("glbPath")
        if glb and not str(glb).startswith(ASSET_REF_PREFIX):
            return False, f"道具「{box.get('name') or '?'}」使用工作站本機模型檔，艦隊節點讀不到，改用本機 Blender"
    return True, ""


def fleet_job_payload(job: dict[str, Any], *, job_id: str, export_models: bool = False, timeout_sec: int | None = None) -> dict[str, Any]:
    """``inputPayload`` for one ``blender_scene_render`` task (the node fills workDir/progressFile/cancelFile itself)."""
    clean = {k: v for k, v in job.items() if k not in FLEET_JOB_STRIP_KEYS}
    clean["exportBlend"] = bool(export_models)
    clean["exportGlb"] = bool(export_models)
    payload: dict[str, Any] = {"jobId": str(job_id)[:80], "job": clean, "exportModels": bool(export_models)}
    if timeout_sec:
        payload["timeoutSec"] = max(60, int(timeout_sec))
    return payload


def submit_blender_job(
    client: FleetImageClient,
    job: dict[str, Any],
    *,
    job_id: str,
    priority: int = 60,
    export_models: bool = False,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    payload = fleet_job_payload(job, job_id=job_id, export_models=export_models, timeout_sec=timeout_sec)
    return client.submit_task(BLENDER_TASK_TYPE, payload, priority=priority)


def task_result_data(task: dict[str, Any]) -> dict[str, Any]:
    """The executor's JSON result line: the console keeps it under ``outputPayload.data`` (older consoles: top level)."""
    payload = task.get("outputPayload") or task.get("output_payload") or {}
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict) and data:
        return data
    result = payload.get("result")
    if isinstance(result, dict) and result:
        return result
    return payload


def collect_blender_outputs(client: FleetImageClient, task: dict[str, Any], item_dir: Path) -> dict[str, Any]:
    """Download beauty.png (+ product_cutout.png) of a finished task into ``item_dir`` and return the render facts."""
    status = task_status(task)
    if status in TERMINAL_BAD:
        raise FleetError(task_error(task) or "艦隊 Blender 算圖失敗")
    if status not in TERMINAL_OK:
        raise FleetError(f"艦隊 Blender 任務尚未完成（{status or '未知狀態'}）")
    data = task_result_data(task)
    if str(data.get("status") or "succeeded").lower() not in ("succeeded", "completed", "success"):
        raise FleetError(str(data.get("error") or "艦隊 Blender 回報失敗")[:300])
    item_dir.mkdir(parents=True, exist_ok=True)
    beauty = client.artifact_bytes_at(task, ARTIFACT_BEAUTY)
    if len(beauty) < 32:
        raise FleetError("艦隊 Blender 沒有回傳 beauty.png")
    (item_dir / "beauty.png").write_bytes(beauty)
    raw_artifacts = data.get("artifacts")
    artifacts: list[Any] = list(raw_artifacts) if isinstance(raw_artifacts, list) else []
    has_cutout = data.get("hasCutout") is not False and (len(artifacts) > ARTIFACT_CUTOUT or data.get("hasCutout") is True)
    if has_cutout:
        try:
            cutout = client.artifact_bytes_at(task, ARTIFACT_CUTOUT)
            if len(cutout) >= 32:
                (item_dir / "product_cutout.png").write_bytes(cutout)
            else:
                has_cutout = False
        except FleetError:
            has_cutout = False
    return {
        "hasCutout": bool(has_cutout and (item_dir / "product_cutout.png").exists()),
        "renderTimeSec": data.get("renderTimeSec"),
        "blenderVersion": data.get("blenderVersion"),
        "device": data.get("device"),
        "engine": data.get("engine"),
        "nodeId": task.get("nodeId") or task.get("node_id"),
        "taskId": task.get("id"),
    }


def blender_fleet_status(client: FleetImageClient | None) -> dict[str, Any]:
    """Can the fleet take Blender renders right now? (used by the studio header and by the matrix worker)."""
    out: dict[str, Any] = {"taskType": BLENDER_TASK_TYPE, "ready": False, "tokenConfigured": bool(client and client.token),
                           "capability": None, "error": None}
    if client is None or not client.token:
        out["error"] = "尚未設定 GPU 艦隊服務金鑰"
        return out
    try:
        cap = client.capability(BLENDER_TASK_TYPE)
    except FleetError as exc:
        out["error"] = str(exc)[:300]
        return out
    if cap is None:
        out["error"] = f"艦隊中控尚未登錄 {BLENDER_TASK_TYPE}（要先部署新版中控）"
        return out
    nodes = cap.get("capableNodes")
    try:
        node_count = int(nodes) if nodes is not None else 0
    except (TypeError, ValueError):
        node_count = 0
    out["capability"] = {
        "available": bool(cap.get("available")),
        "status": cap.get("status"),
        "capableNodes": node_count,
        "queueDepth": cap.get("queueDepth"),
        "runningCount": cap.get("runningCount"),
        "estimatedWaitSec": cap.get("estimatedWaitSec"),
    }
    if node_count <= 0:
        out["error"] = "艦隊目前沒有節點宣告 Blender 執行器"
    else:
        out["ready"] = True
    return out


def render_on_fleet(
    client: FleetImageClient,
    job: dict[str, Any],
    item_dir: Path,
    *,
    job_id: str,
    task: dict[str, Any] | None = None,
    timeout: float = DEFAULT_RENDER_TIMEOUT_SEC,
    on_update: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Submit (unless ``task`` was pre-submitted), wait, download. Raises FleetError on any fleet-side failure."""
    if task is None:
        task = submit_blender_job(client, job, job_id=job_id)
    task_id = str(task.get("id"))
    final = client.wait(task_id, timeout=timeout, interval=3.0, on_update=on_update)
    return collect_blender_outputs(client, final, item_dir)
