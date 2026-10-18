"""Blender renders on the GPU fleet: payload contract, artifact download, engine decision and the matrix worker flow
(pre-submit every eligible item, collect in order, fall back to the workstation when the fleet fails)."""
from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fox3d import fleet_blender as fb
from fox3d.api import create_app
from fox3d.ecommerce_scene_studio import BUILTIN_SCENES, CABINET_PRESETS, _ph_glb
from fox3d.fleet_image_client import FleetError, FleetImageClient
from fox3d.platform import Platform


class _Resp:
    def __init__(self, payload, status: int = 200):
        self._payload = payload

    def read(self):
        return self._payload if isinstance(self._payload, bytes) else json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _png(size=(64, 64), color=(120, 90, 60, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


BEAUTY = _png(color=(10, 200, 30, 255))
CUTOUT = _png(color=(200, 10, 30, 255))


class BlenderFleet:
    """Console double that advertises blender_scene_render and finishes every task right away (or fails them)."""

    def __init__(self, *, capable_nodes: int = 1, fail: bool = False, with_cutout: bool = True, hold: bool = False):
        self.capable_nodes = capable_nodes
        self.fail = fail
        self.with_cutout = with_cutout
        self.release = threading.Event()
        if not hold:
            self.release.set()
        self.tasks: dict[str, dict] = {}
        self.payloads: list[dict] = []
        self.artifact_hits: list[str] = []
        self.lock = threading.Lock()

    def opener(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        if url.endswith("/api/fleet/capabilities"):
            return _Resp([
                {"taskType": "image_flux3", "available": True, "capableNodes": 2},
                {"taskType": fb.BLENDER_TASK_TYPE, "available": self.capable_nodes > 0, "capableNodes": self.capable_nodes, "queueDepth": 0},
            ])
        if url.endswith("/api/fleet/tasks") and method == "POST":
            body = json.loads(req.data.decode("utf-8"))
            assert body["taskType"] == fb.BLENDER_TASK_TYPE
            self.payloads.append(body["inputPayload"])
            with self.lock:
                tid = f"b{len(self.tasks) + 1}"
                self.tasks[tid] = {"id": tid, "status": "queued", "progressNote": "等待 GPU 資源"}
            return _Resp({"task": self.tasks[tid]})
        if "/api/fleet/tasks/" in url and method == "GET":
            if "/artifacts/" in url:
                self.artifact_hits.append(url.rsplit("/api/fleet/", 1)[1])
                return _Resp(BEAUTY if url.endswith("/artifacts/0") else CUTOUT)
            tid = url.rsplit("/", 1)[-1]
            task = dict(self.tasks[tid])
            if self.release.is_set():
                if self.fail:
                    task.update(status="failed", error="OptiX device lost")
                else:
                    arts = [{"name": "beauty.png", "url": f"http://fleet.test/api/fleet/tasks/{tid}/artifacts/0"}]
                    if self.with_cutout:
                        arts.append({"name": "product_cutout.png", "url": f"http://fleet.test/api/fleet/tasks/{tid}/artifacts/1"})
                    task.update(status="success", nodeId="n-5090-3", outputPayload={"data": {
                        "status": "succeeded", "image": arts[0], "artifacts": arts, "hasCutout": self.with_cutout,
                        "renderTimeSec": 5.2, "blenderVersion": "5.2.2 LTS", "device": "OPTIX", "engine": "CYCLES",
                    }})
            return _Resp({"task": task})
        raise AssertionError(f"unexpected {method} {url}")

    def client(self) -> FleetImageClient:
        return FleetImageClient(base_url="http://fleet.test", token="tok", _opener=self.opener)


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
        (work / "beauty.png").write_bytes(_png())
        (work / "product_cutout.png").write_bytes(_png(color=(90, 60, 30, 255)))
        self.rendered.append(job["jobId"])
        return {"status": "succeeded", "outputs": {"beauty.png": str(work / "beauty.png")}, "renderTimeSec": 0.1, "device": "CPU", "blenderVersion": "local"}


def _wait(client: TestClient, batch_id: str, headers: dict, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        batch = client.get(f"/api/ecommerce-scenes/batches/{batch_id}", headers=headers).json()
        if batch.get("state") in ("completed", "failed", "interrupted"):
            return batch
        time.sleep(0.05)
    raise AssertionError("batch did not finish: " + json.dumps(batch, ensure_ascii=False)[:500])


def _patch_fleet(monkeypatch, fleet: BlenderFleet) -> None:
    # from_settings is a classmethod on the shared class object, so patching it here also covers the lazy import in the API
    monkeypatch.setattr("fox3d.ecommerce_scene_studio.FleetImageClient.from_settings", classmethod(lambda cls, settings=None: fleet.client()))


# --------------------------------------------------------------------------- unit: contract helpers
def test_polyhaven_models_are_machine_independent_refs():
    ref = _ph_glb("Ottoman_01")
    assert ref.startswith("assets://models/polyhaven/Ottoman_01/")
    assert "\\" not in ref and ":" not in ref.split("//", 1)[1]
    assert _ph_glb("no-such-asset") == ""


def test_fleet_eligible_rejects_workstation_paths():
    ok, _ = fb.fleet_eligible({"boxes": [{"name": "A", "glbPath": "assets://models/polyhaven/x/x_2k.gltf"}, {"name": "B"}]})
    assert ok
    bad, why = fb.fleet_eligible({"boxes": [{"name": "SOFA_CUSTOM", "glbPath": r"E:\data\tenants\sonaqueen\props\sofa.glb"}]})
    assert not bad and "SOFA_CUSTOM" in why
    assert fb.fleet_eligible(None) == (True, "")


def test_fleet_job_payload_strips_workstation_paths_and_pins_exports():
    job = {"jobId": "b_1", "workDir": r"E:\work\x", "progressFile": "p", "cancelFile": "c", "engineering": {"sceneHash": "h"}, "exportBlend": True, "exportGlb": True}
    payload = fb.fleet_job_payload(job, job_id="b_1", timeout_sec=30)
    assert payload["jobId"] == "b_1" and payload["exportModels"] is False and payload["timeoutSec"] == 60
    assert set(payload["job"]) == {"jobId", "engineering", "exportBlend", "exportGlb"}
    assert payload["job"]["exportBlend"] is False and payload["job"]["exportGlb"] is False
    assert payload["job"]["engineering"]["sceneHash"] == "h"  # the node verifies this hash untouched
    assert fb.fleet_job_payload(job, job_id="b_1", export_models=True)["job"]["exportGlb"] is True


def test_normalize_blender_engine():
    assert fb.normalize_blender_engine("fleet") == "fleet"
    assert fb.normalize_blender_engine(" LOCAL ") == "local"
    assert fb.normalize_blender_engine("nonsense") == "auto"
    assert fb.normalize_blender_engine(None) == "auto"


def test_blender_fleet_status_paths():
    assert fb.blender_fleet_status(None)["ready"] is False
    assert fb.blender_fleet_status(FleetImageClient(token=""))["error"].startswith("尚未設定")
    missing = BlenderFleet()
    missing.opener = lambda req, timeout=None: _Resp([{"taskType": "image_flux3", "available": True}])  # type: ignore[method-assign]
    st = fb.blender_fleet_status(missing.client())
    assert st["ready"] is False and fb.BLENDER_TASK_TYPE in (st["error"] or "")
    zero = fb.blender_fleet_status(BlenderFleet(capable_nodes=0).client())
    assert zero["ready"] is False and zero["capability"]["capableNodes"] == 0
    ready = fb.blender_fleet_status(BlenderFleet(capable_nodes=1).client())
    assert ready["ready"] is True and ready["capability"]["capableNodes"] == 1


def test_collect_blender_outputs_downloads_in_fixed_order(tmp_path: Path):
    fleet = BlenderFleet()
    client = fleet.client()
    task = fb.submit_blender_job(client, {"jobId": "j1", "engineering": {}}, job_id="j1")
    final = client.wait(task["id"], timeout=5, interval=0.01, sleep=lambda s: None)
    facts = fb.collect_blender_outputs(client, final, tmp_path / "item")
    assert (tmp_path / "item" / "beauty.png").read_bytes() == BEAUTY
    assert (tmp_path / "item" / "product_cutout.png").read_bytes() == CUTOUT
    assert facts["hasCutout"] is True and facts["renderTimeSec"] == 5.2 and facts["device"] == "OPTIX" and facts["nodeId"] == "n-5090-3"
    assert fleet.artifact_hits == ["tasks/b1/artifacts/0", "tasks/b1/artifacts/1"]


def test_collect_blender_outputs_without_cutout(tmp_path: Path):
    fleet = BlenderFleet(with_cutout=False)
    client = fleet.client()
    task = fb.submit_blender_job(client, {"jobId": "j2"}, job_id="j2")
    final = client.wait(task["id"], timeout=5, interval=0.01, sleep=lambda s: None)
    facts = fb.collect_blender_outputs(client, final, tmp_path / "item")
    assert facts["hasCutout"] is False and not (tmp_path / "item" / "product_cutout.png").exists()
    assert fleet.artifact_hits == ["tasks/b1/artifacts/0"]


def test_collect_blender_outputs_raises_on_failed_task(tmp_path: Path):
    fleet = BlenderFleet(fail=True)
    client = fleet.client()
    task = fb.submit_blender_job(client, {"jobId": "j3"}, job_id="j3")
    with pytest.raises(FleetError, match="OptiX"):
        client.wait(task["id"], timeout=5, interval=0.01, sleep=lambda s: None)
    failed = {"id": "x", "status": "failed", "error": "boom"}
    with pytest.raises(FleetError, match="boom"):
        fb.collect_blender_outputs(client, failed, tmp_path / "item")


# --------------------------------------------------------------------------- integration: the matrix worker
def _submit(client: TestClient, headers: dict, **extra) -> str:
    body = {"cabinet": CABINET_PRESETS[0], "sceneIds": [BUILTIN_SCENES[0]["id"]], "themeIds": ["THEME_NORDIC_OAK"], "views": ["FRONT"], "aiEngine": "builtin"}
    body.update(extra)
    r = client.post("/api/ecommerce-scenes/batches", headers=headers, json=body)
    assert r.status_code == 202, r.text
    return r.json()["batchId"]


def test_matrix_batch_renders_on_fleet_and_keeps_pipeline(tmp_path: Path, monkeypatch):
    fleet = BlenderFleet()
    _patch_fleet(monkeypatch, fleet)
    plat = Platform(tmp_path / "data", mock_blender=False)
    runtime = FakeRuntime()
    plat.runtime = runtime  # type: ignore[assignment]
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    batch_id = _submit(client, headers, blenderEngine="fleet", themeIds=["THEME_NORDIC_OAK", "THEME_WALNUT"])
    done = _wait(client, batch_id, headers)
    assert done["state"] == "completed" and done["blenderEngine"] == "fleet" and done["blenderEngineEffective"] == "fleet"
    assert len(done["items"]) == 2
    for item in done["items"]:
        assert item["state"] == "succeeded", item
        assert item["blenderEngine"] == "fleet" and item["fleetTaskId"] in fleet.tasks
        assert item["renderTimeSec"] == 5.2 and item["device"] == "OPTIX" and item["blenderVersion"] == "5.2.2 LTS"
        assert item["hasCutout"] is True and item["hasAiComposite"] is True  # Plan B still ran on the downloaded render
    assert runtime.rendered == []  # the workstation never rendered
    # both jobs were pre-submitted before the first one was collected, and carry no workstation paths
    assert len(fleet.payloads) == 2
    for payload in fleet.payloads:
        assert "workDir" not in payload["job"] and payload["exportModels"] is False
        boxes = payload["job"]["engineering"]["sceneDefinition"]["boxes"]
        assert all(str(b.get("glbPath", "assets://")).startswith("assets://") for b in boxes)
    item_dir = tmp_path / "data"
    assert any(p.name == "beauty.png" and p.read_bytes() == BEAUTY for p in item_dir.rglob("beauty.png"))


def test_matrix_batch_auto_uses_fleet_when_ready_and_local_otherwise(tmp_path: Path, monkeypatch):
    fleet = BlenderFleet(capable_nodes=0)
    _patch_fleet(monkeypatch, fleet)
    plat = Platform(tmp_path / "data", mock_blender=False)
    runtime = FakeRuntime()
    plat.runtime = runtime  # type: ignore[assignment]
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    done = _wait(client, _submit(client, headers), headers)  # default blenderEngine=auto, fleet has no Blender node
    assert done["blenderEngineEffective"] == "local" and "沒有節點" in (done.get("blenderFleetNote") or "")
    assert done["items"][0]["state"] == "succeeded" and done["items"][0]["blenderEngine"] == "local"
    assert runtime.rendered and fleet.payloads == []

    fleet.capable_nodes = 1
    done2 = _wait(client, _submit(client, headers), headers)
    assert done2["blenderEngineEffective"] == "fleet" and done2["items"][0]["blenderEngine"] == "fleet"
    assert len(fleet.payloads) == 1


def test_matrix_batch_fleet_failure_falls_back_to_local(tmp_path: Path, monkeypatch):
    fleet = BlenderFleet(fail=True)
    _patch_fleet(monkeypatch, fleet)
    plat = Platform(tmp_path / "data", mock_blender=False)
    runtime = FakeRuntime()
    plat.runtime = runtime  # type: ignore[assignment]
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    done = _wait(client, _submit(client, headers, blenderEngine="auto"), headers)
    item = done["items"][0]
    assert item["state"] == "succeeded" and item["blenderEngine"] == "local"
    assert "艦隊失敗" in (item["blenderNote"] or "") and "OptiX" in item["blenderNote"]
    assert runtime.rendered == [item["fleetTaskId"] and f"{done['batchId']}_{item['itemId']}"]


def test_matrix_batch_forced_fleet_without_capability_fails_clearly(tmp_path: Path, monkeypatch):
    fleet = BlenderFleet(capable_nodes=0)
    _patch_fleet(monkeypatch, fleet)
    plat = Platform(tmp_path / "data", mock_blender=False)
    runtime = FakeRuntime()
    plat.runtime = runtime  # type: ignore[assignment]
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    done = _wait(client, _submit(client, headers, blenderEngine="fleet"), headers)
    item = done["items"][0]
    assert item["state"] == "failed" and "沒有節點" in (item["error"] or "")
    assert runtime.rendered == []  # forced fleet never falls back to the workstation silently


def test_blender_engine_setting_roundtrip_and_status(tmp_path: Path, monkeypatch):
    fleet = BlenderFleet()
    _patch_fleet(monkeypatch, fleet)
    monkeypatch.setattr("fox3d.fleet_image_client.DEFAULT_TOKEN_FILE", tmp_path / "no-default-token")
    plat = Platform(tmp_path / "data", mock_blender=False)
    plat.runtime = FakeRuntime()  # type: ignore[assignment]
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    assert client.get("/api/ecommerce-scenes/ai-settings").json()["blenderEngine"] == "auto"
    r = client.post("/api/ecommerce-scenes/ai-settings", headers=headers, json={"blenderEngine": "fleet"})
    assert r.status_code == 200
    assert client.get("/api/ecommerce-scenes/ai-settings").json()["blenderEngine"] == "fleet"
    assert client.post("/api/ecommerce-scenes/ai-settings", headers=headers, json={"blenderEngine": "cloud"}).status_code == 422
    st = client.get("/api/ecommerce-scenes/ai-engine-status").json()
    assert st["blender"]["setting"] == "fleet" and st["blender"]["effective"] == "fleet"
    assert st["blender"]["fleet"]["ready"] is True and st["blender"]["localAvailable"] is True
