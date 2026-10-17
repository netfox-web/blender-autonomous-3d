"""地端 AI stage must not block Blender: later items render while earlier items wait for the GPU fleet;
a batch whose worker died (workbench restart) is reported as interrupted instead of running forever."""
from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from fox3d.api import create_app
from fox3d.ecommerce_scene_studio import BUILTIN_SCENES, CABINET_PRESETS
from fox3d.fleet_image_client import FleetImageClient
from fox3d.platform import Platform


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload if isinstance(self._payload, bytes) else json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _png(size=(48, 48), color=(120, 90, 60, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


class HoldingFleet:
    """Fleet that keeps every task 'queued' (like 等待 GPU 資源) until ``release`` is set."""

    def __init__(self):
        self.release = threading.Event()
        self.tasks: dict[str, dict] = {}
        self.lock = threading.Lock()

    def opener(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        if url.endswith("/api/fleet/capabilities"):
            return _Resp([{"taskType": "image_flux3", "available": True}])
        if url.endswith("/api/fleet/tasks") and method == "POST":
            with self.lock:
                tid = f"t{len(self.tasks) + 1}"
                self.tasks[tid] = {"id": tid, "status": "queued", "progressNote": "等待 GPU 資源"}
            return _Resp({"task": self.tasks[tid]})
        if "/api/fleet/tasks/" in url and method == "GET":
            if url.endswith("/artifacts/0"):
                return _Resp(_png(color=(10, 200, 30, 255)))
            tid = url.rsplit("/", 1)[-1]
            task = dict(self.tasks[tid])
            if self.release.is_set():
                task.update(status="success", nodeHostname="5090-3", outputPayload={"data": {"image": {"url": "http://fleet.test/api/fleet/tasks/" + tid + "/artifacts/0"}}})
            return _Resp({"task": task})
        raise AssertionError(f"unexpected {method} {url}")


class FakeRuntime:
    blender_bin = "fake"
    script_path = None

    def __init__(self):
        self.rendered: list[str] = []

    def available(self) -> bool:
        return True

    def run_job(self, job: dict) -> dict:
        work = Path(job["workDir"])
        work.mkdir(parents=True, exist_ok=True)
        (work / "beauty.png").write_bytes(_png(size=(64, 64)))
        (work / "product_cutout.png").write_bytes(_png(size=(64, 64), color=(90, 60, 30, 255)))
        self.rendered.append(job["jobId"])
        return {"status": "succeeded", "outputs": {"beauty.png": str(work / "beauty.png"), "product_cutout.png": str(work / "product_cutout.png")}, "renderTimeSec": 0.1, "device": "CPU"}


def _poll(client: TestClient, batch_id: str, headers: dict, pred, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        batch = client.get(f"/api/ecommerce-scenes/batches/{batch_id}", headers=headers).json()
        if pred(batch):
            return batch
        time.sleep(0.05)
    raise AssertionError("condition not reached: " + json.dumps(batch, ensure_ascii=False)[:600])


def test_blender_keeps_rendering_while_ai_waits_for_gpu(tmp_path: Path, monkeypatch):
    plat = Platform(tmp_path / "data", mock_blender=False)
    runtime = FakeRuntime()
    plat.runtime = runtime  # type: ignore[assignment]
    fleet = HoldingFleet()
    monkeypatch.setattr("fox3d.ecommerce_scene_studio.FleetImageClient.from_settings", classmethod(lambda cls, settings=None: FleetImageClient(base_url="http://fleet.test", token="tok", _opener=fleet.opener)))
    real_sleep = time.sleep
    monkeypatch.setattr("fox3d.local_scene_ai.time.sleep", lambda s: real_sleep(0.01))
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    client.post("/api/ecommerce-scenes/ai-settings", headers=headers, json={"fleetToken": "tok", "publicBaseUrl": "http://192.168.66.21:8790"})

    r = client.post("/api/ecommerce-scenes/batches", headers=headers, json={"cabinet": CABINET_PRESETS[0], "sceneIds": [BUILTIN_SCENES[0]["id"], BUILTIN_SCENES[1]["id"]], "themeIds": ["THEME_NORDIC_OAK"], "views": ["FRONT"], "aiEngine": "fleet_flux3", "aiVariants": 2})
    assert r.status_code == 202, r.text
    batch_id = r.json()["batchId"]

    # Item 2's Blender render finishes while item 1 is still waiting for the fleet.
    batch = _poll(client, batch_id, headers, lambda b: b["items"][1]["stage"] in ("ai", "done"))
    assert batch["state"] == "running"
    assert batch["items"][0]["stage"] == "ai" and batch["items"][0]["state"] == "running"
    assert all(v["state"] in ("queued", "running") for v in batch["items"][0]["aiVariants"])
    assert len(runtime.rendered) == 2
    assert batch["completed"] == 0

    fleet.release.set()
    done = _poll(client, batch_id, headers, lambda b: b["state"] != "running")
    assert done["state"] == "completed" and done["succeeded"] == 2, done
    for item in done["items"]:
        assert item["stage"] == "done" and item["aiState"] == "succeeded"
        assert [v["state"] for v in item["aiVariants"]] == ["succeeded", "succeeded"]
    assert len(fleet.tasks) == 4


def test_stale_running_batch_is_reported_as_interrupted(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    bdir = Path(plat.root) / "ecommerce-scene-studio" / "sonaqueen-home" / "batches" / "deadbeef"
    bdir.mkdir(parents=True)
    doc = {
        "batchId": "deadbeef", "tenantId": "sonaqueen-home", "state": "running", "total": 2, "completed": 1, "succeeded": 1, "failed": 0,
        "createdAt": "2026-10-17T00:00:00Z", "aiEngine": "fleet_flux3",
        "items": [
            {"itemId": "item_01", "index": 1, "state": "succeeded", "stage": "done", "aiState": "succeeded", "aiVariants": [{"index": 0, "state": "succeeded"}]},
            {"itemId": "item_02", "index": 2, "state": "running", "stage": "ai", "aiState": "running", "aiVariants": [{"index": 0, "state": "queued"}, {"index": 1, "state": "running"}]},
        ],
    }
    (bdir / "batch.json").write_text(json.dumps(doc), encoding="utf-8")
    old = time.time() - 3600
    os.utime(bdir / "batch.json", (old, old))

    got = client.get("/api/ecommerce-scenes/batches/deadbeef", headers=headers).json()
    assert got["state"] == "interrupted"
    assert got["completed"] == 2 and got["failed"] == 1 and got["succeeded"] == 1
    item = got["items"][1]
    assert item["state"] == "failed" and "中斷" in item["error"]
    assert item["aiState"] == "failed" and all(v["state"] == "failed" for v in item["aiVariants"])
    assert got["items"][0]["state"] == "succeeded"
    # persisted, and listed the same way
    again = client.get("/api/ecommerce-scenes/overview", headers=headers).json()["batches"][0]
    assert again["state"] == "interrupted"


def test_fresh_running_batch_is_left_alone(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    bdir = Path(plat.root) / "ecommerce-scene-studio" / "sonaqueen-home" / "batches" / "fresh001"
    bdir.mkdir(parents=True)
    (bdir / "batch.json").write_text(json.dumps({"batchId": "fresh001", "state": "running", "total": 1, "completed": 0, "succeeded": 0, "failed": 0, "items": [{"itemId": "item_01", "index": 1, "state": "running", "stage": "blender"}]}), encoding="utf-8")
    got = client.get("/api/ecommerce-scenes/batches/fresh001", headers=headers).json()
    assert got["state"] == "running" and got["items"][0]["state"] == "running"


def test_batch_owned_by_this_process_is_never_marked_stale(tmp_path: Path, monkeypatch):
    """A batch queued behind another one writes no progress for a while; it must not be reported as interrupted."""
    import os as _os

    plat = Platform(tmp_path / "data", mock_blender=False)
    plat.runtime = FakeRuntime()  # type: ignore[assignment]
    fleet = HoldingFleet()
    monkeypatch.setattr("fox3d.ecommerce_scene_studio.FleetImageClient.from_settings", classmethod(lambda cls, settings=None: FleetImageClient(base_url="http://fleet.test", token="tok", _opener=fleet.opener)))
    real_sleep = time.sleep
    monkeypatch.setattr("fox3d.local_scene_ai.time.sleep", lambda s: real_sleep(0.01))
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    client.post("/api/ecommerce-scenes/ai-settings", headers=headers, json={"fleetToken": "tok", "publicBaseUrl": "http://192.168.66.21:8790"})
    r = client.post("/api/ecommerce-scenes/batches", headers=headers, json={"cabinet": CABINET_PRESETS[0], "sceneIds": [BUILTIN_SCENES[0]["id"]], "themeIds": ["THEME_NORDIC_OAK"], "views": ["FRONT"], "aiEngine": "fleet_flux3", "aiVariants": 1})
    batch_id = r.json()["batchId"]
    _poll(client, batch_id, headers, lambda b: b["items"][0]["stage"] == "ai")
    bpath = Path(plat.root) / "ecommerce-scene-studio" / "sonaqueen-home" / "batches" / batch_id / "batch.json"
    old = time.time() - 3600
    _os.utime(bpath, (old, old))  # pretend nothing was written for an hour while the fleet holds the task
    got = client.get(f"/api/ecommerce-scenes/batches/{batch_id}", headers=headers).json()
    assert got["state"] == "running" and got["items"][0]["state"] == "running"
    fleet.release.set()
    done = _poll(client, batch_id, headers, lambda b: b["state"] != "running")
    assert done["state"] == "completed"
