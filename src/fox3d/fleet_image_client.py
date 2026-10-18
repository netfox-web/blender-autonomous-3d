"""Thin client for the NetFox GPU Fleet console (`/api/fleet/tasks`) used by the scene studio.

The studio never talks to a GPU node directly: it submits an ``image_flux3`` task to the fleet console with a
service token, polls the task until it reaches a terminal state and then downloads the produced PNG. Reference
images are passed as http(s) URLs that the node can fetch (the studio publishes its own render outputs for that).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

DEFAULT_FLEET_URL = "http://192.168.66.101:3004"
DEFAULT_TOKEN_FILE = Path.home() / ".netfox-secrets" / "fox3d.fleet-token"
IMAGE_TASK_TYPE = "image_flux3"

TERMINAL_OK = frozenset({"success", "succeeded", "completed", "done"})
TERMINAL_BAD = frozenset({"failed", "error", "errored", "cancelled", "canceled", "timeout", "timed_out", "refused"})


class FleetError(RuntimeError):
    """Raised for any fleet console failure (network, auth, refusal, task failure)."""


def resolve_fleet_token(explicit: str | None = None) -> str:
    """Token lookup order: explicit value, ``FLEET_SERVICE_TOKEN``, ``FLEET_SERVICE_TOKEN_FILE``, default token file."""
    if explicit and explicit.strip():
        return explicit.strip()
    env = (os.environ.get("FLEET_SERVICE_TOKEN") or "").strip()
    if env:
        return env
    for candidate in ((os.environ.get("FLEET_SERVICE_TOKEN_FILE") or "").strip(), str(DEFAULT_TOKEN_FILE)):
        if not candidate:
            continue
        try:
            value = Path(candidate).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def resolve_fleet_url(explicit: str | None = None) -> str:
    value = (explicit or "").strip() or (os.environ.get("FLEET_API_URL") or "").strip() or DEFAULT_FLEET_URL
    return value.rstrip("/")


def task_status(task: dict[str, Any]) -> str:
    return str(task.get("status") or task.get("state") or "").strip().lower()


def task_image_url(task: dict[str, Any]) -> str | None:
    """The fleet stores shell-executor JSON under ``outputPayload.data``; older consoles used the top level."""
    payload = task.get("outputPayload") or task.get("output_payload") or {}
    if not isinstance(payload, dict):
        return None
    for container in (payload.get("data"), payload):
        if isinstance(container, dict):
            image = container.get("image")
            if isinstance(image, dict) and image.get("url"):
                return str(image["url"])
            if isinstance(image, str) and image.startswith(("http://", "https://")):
                return image
    return None


def task_artifact_url(task: dict[str, Any], index: int) -> str | None:
    """URL of envelope artifact ``index`` as reported by the executor (``data.artifacts[i].url``) or the envelope."""
    payload = task.get("outputPayload") or task.get("output_payload") or {}
    if not isinstance(payload, dict):
        return None
    for container in (payload.get("data"), payload.get("result"), payload):
        if not isinstance(container, dict):
            continue
        arts = container.get("artifacts")
        if isinstance(arts, list) and 0 <= index < len(arts) and isinstance(arts[index], dict):
            url = arts[index].get("url") or arts[index].get("sourceUrl")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return url
    return None


def task_error(task: dict[str, Any]) -> str:
    for key in ("error", "errorMessage", "error_message", "failureReason", "reason"):
        val = task.get(key)
        if val:
            return str(val)
    payload = task.get("outputPayload") or {}
    if isinstance(payload, dict):
        for key in ("error", "stderr", "message"):
            if payload.get(key):
                return str(payload[key])[:400]
    return ""


@dataclass
class FleetImageClient:
    base_url: str = DEFAULT_FLEET_URL
    token: str = ""
    timeout: float = 30.0
    user_agent: str = "fox3d-scene-studio/1.0"
    _opener: Callable[..., Any] = field(default=urllib.request.urlopen, repr=False)

    @classmethod
    def from_settings(cls, settings: dict[str, Any] | None = None) -> "FleetImageClient":
        settings = settings or {}
        return cls(base_url=resolve_fleet_url(settings.get("fleetApiUrl")), token=resolve_fleet_token(settings.get("fleetToken")))

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float | None = None, raw: bool = False) -> Any:
        if not self.token:
            raise FleetError("尚未設定 GPU 艦隊服務金鑰（FLEET_SERVICE_TOKEN）")
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json", "User-Agent": self.user_agent}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener(req, timeout=timeout or self.timeout) as resp:
                content = resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            try:
                parsed = json.loads(detail) if detail else {}
                detail = str(parsed.get("error") or parsed.get("message") or detail)
                admission = parsed.get("admission") if isinstance(parsed, dict) else None
                if isinstance(admission, dict) and admission.get("message"):
                    detail = f"{detail}（{admission['message']}）"
            except Exception:
                pass
            if exc.code == 401:
                raise FleetError("GPU 艦隊拒絕此服務金鑰（401），請檢查金鑰是否正確") from exc
            raise FleetError(f"GPU 艦隊回應 {exc.code}：{detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise FleetError(f"連不到 GPU 艦隊中控 {self.base_url}：{getattr(exc, 'reason', exc)}") from exc
        if raw:
            return content
        try:
            return json.loads(content.decode("utf-8")) if content else {}
        except ValueError as exc:
            raise FleetError("GPU 艦隊回應不是 JSON") from exc

    # ------------------------------------------------------------ operations
    def capability(self, task_type: str = IMAGE_TASK_TYPE) -> dict[str, Any] | None:
        data = self._request("GET", "/api/fleet/capabilities")
        items = data if isinstance(data, list) else (data.get("capabilities") or data.get("taskTypes") or data.get("items") or [])
        for item in items:
            if isinstance(item, dict) and (item.get("taskType") or item.get("id")) == task_type:
                return item
        return None

    def submit_flux3(
        self,
        *,
        prompt: str,
        image_urls: list[str] | tuple[str, ...] = (),
        seed: int = 0,
        upsample: bool = True,
        width: int | None = None,
        height: int | None = None,
        job_id: str | None = None,
        priority: int = 50,
        boxes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": str(prompt)[:4000], "seed": int(seed), "upsample": bool(upsample)}
        urls = [u for u in image_urls if isinstance(u, str) and u.startswith(("http://", "https://"))]
        if urls:
            payload["imageUrls"] = urls
        if width and height:
            payload["width"], payload["height"] = int(width), int(height)
        if job_id:
            payload["jobId"] = str(job_id)[:80]
        if boxes:
            payload["boxes"] = boxes
        return self.submit_task(IMAGE_TASK_TYPE, payload, priority=priority)

    def submit_task(self, task_type: str, payload: dict[str, Any], *, priority: int = 50) -> dict[str, Any]:
        """POST one task of any registered type; returns the console task document (with ``id``)."""
        body = {"taskType": str(task_type), "priority": max(0, min(100, int(priority))), "inputPayload": payload}
        res = self._request("POST", "/api/fleet/tasks", body, timeout=60)
        task = res.get("task") if isinstance(res, dict) and isinstance(res.get("task"), dict) else res
        if not isinstance(task, dict) or not task.get("id"):
            raise FleetError(f"GPU 艦隊沒有回傳任務編號：{json.dumps(res, ensure_ascii=False)[:300]}")
        return task

    def get_task(self, task_id: str) -> dict[str, Any]:
        res = self._request("GET", f"/api/fleet/tasks/{urllib.parse.quote(str(task_id))}")
        task = res.get("task") if isinstance(res, dict) and isinstance(res.get("task"), dict) else res
        if not isinstance(task, dict):
            raise FleetError("GPU 艦隊任務查詢回應格式不正確")
        return task

    def wait(
        self,
        task_id: str,
        *,
        timeout: float = 900.0,
        interval: float = 4.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while True:
            last = self.get_task(task_id)
            if on_update:
                try:
                    on_update(last)
                except Exception:
                    pass
            status = task_status(last)
            if status in TERMINAL_OK:
                return last
            if status in TERMINAL_BAD:
                raise FleetError(f"GPU 任務 {status}：{task_error(last) or '節點未回報原因'}")
            if time.monotonic() > deadline:
                raise FleetError(f"GPU 任務逾時（{int(timeout)} 秒）仍在 {status or 'queued'}")
            sleep(interval)

    def artifact_bytes(self, task: dict[str, Any]) -> bytes:
        """Download the PNG: first the node URL (LAN), then the console artifact proxy as a fallback."""
        url = task_image_url(task)
        errors: list[str] = []
        # The console hands out its own artifact proxy URL (public hostname, token required): fetch that path through
        # our configured base_url (LAN) with the service token instead of going out to the public hostname.
        if url and "/api/fleet/tasks/" in url:
            try:
                path = url.split("/api/fleet/", 1)[1]
                data = self._request("GET", f"/api/fleet/{path}", timeout=180, raw=True)
                if data:
                    return data
            except FleetError as exc:
                errors.append(str(exc))
            url = None
        if url:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                with self._opener(req, timeout=120) as resp:
                    data = resp.read()
                if data:
                    return data
            except Exception as exc:  # pragma: no cover - network specific
                errors.append(f"節點直連 {url[:60]}…：{exc}")
        task_id = task.get("id")
        if task_id:
            try:
                data = self._request("GET", f"/api/fleet/tasks/{urllib.parse.quote(str(task_id))}/artifacts/0", timeout=180, raw=True)
                if data:
                    return data
            except FleetError as exc:
                errors.append(str(exc))
        raise FleetError("下載 GPU 生成圖失敗：" + "；".join(errors or ["任務沒有輸出圖片"]))

    def artifact_bytes_at(self, task: dict[str, Any], index: int) -> bytes:
        """Download envelope artifact ``index``: node URL first (LAN), then the console proxy ``/artifacts/<index>``."""
        errors: list[str] = []
        node_url = task_artifact_url(task, index)
        if node_url and "/api/fleet/tasks/" not in node_url:
            try:
                req = urllib.request.Request(node_url, headers={"User-Agent": self.user_agent})
                with self._opener(req, timeout=120) as resp:
                    data = resp.read()
                if data:
                    return bytes(data)
            except Exception as exc:  # pragma: no cover - network specific
                errors.append(f"節點直連 {node_url[:60]}…：{exc}")
        task_id = task.get("id")
        if task_id:
            try:
                data = self._request("GET", f"/api/fleet/tasks/{urllib.parse.quote(str(task_id))}/artifacts/{int(index)}", timeout=180, raw=True)
                if data:
                    return bytes(data)
            except FleetError as exc:
                errors.append(str(exc))
        raise FleetError(f"下載艦隊產出 #{index} 失敗：" + "；".join(errors or ["任務沒有這個產出"]))
