"""Tests for 地端 AI 實景 generation: fleet client, prompt builder, product-locked compositing, API and worker."""
from __future__ import annotations

import io
import json
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fox3d.api import create_app
from fox3d.ecommerce_scene_studio import BUILTIN_SCENES, CABINET_PRESETS, STYLE_THEMES, build_modular_cabinet_spec
from fox3d.fleet_image_client import FleetError, FleetImageClient, task_image_url, task_status
from fox3d.local_scene_ai import (
    SCENE_AI_ENGINES,
    build_public_base_url,
    build_scene_prompt,
    color_name,
    composite_locked_product,
    describe_cabinet,
    engine_status,
    polish_prompt_with_llm,
    run_local_scene_variants,
)
from fox3d.platform import Platform


# --------------------------------------------------------------------------- helpers
class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def read(self):
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _png_bytes(size=(64, 64), color=(120, 90, 60, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeFleet:
    """Minimal in-memory fleet console: records submissions, completes tasks after one poll."""

    def __init__(self, *, fail_submit=False, fail_task=False):
        self.tasks: dict[str, dict] = {}
        self.submitted: list[dict] = []
        self.fail_submit = fail_submit
        self.fail_task = fail_task
        self.polls = 0

    def opener(self, req, timeout=None):
        url = req.full_url
        method = req.get_method()
        if url.endswith("/api/fleet/capabilities"):
            return _Resp([{"taskType": "image_flux3", "available": True, "status": "GA", "capableNodes": 1, "queueDepth": 0, "estimatedRuntimeSec": 15}])
        if url.endswith("/api/fleet/tasks") and method == "POST":
            if self.fail_submit:
                raise urllib.error.HTTPError(url, 422, "quota", {}, io.BytesIO(b'{"error":"quota exceeded","admission":{"message":"\xe9\x85\x8d\xe9\xa1\x8d"}}'))
            body = json.loads(req.data.decode("utf-8"))
            self.submitted.append(body)
            tid = f"task{len(self.submitted)}"
            self.tasks[tid] = {"id": tid, "status": "queued", "inputPayload": body["inputPayload"]}
            return _Resp({"ok": True, "task": self.tasks[tid]})
        if "/api/fleet/tasks/" in url and method == "GET":
            tid = url.rsplit("/", 1)[-1]
            if url.endswith("/artifacts/0"):
                return _Resp(_png_bytes())
            self.polls += 1
            task = dict(self.tasks[tid])
            if self.fail_task:
                task.update(status="failed", error="node exploded")
            else:
                task.update(status="success", nodeId="5090-3", progress=100, outputPayload={"data": {"image": {"url": "http://node.local/view?f=x.png"}, "caption": "a photo"}})
            self.tasks[tid] = task
            return _Resp({"task": task})
        if url.startswith("http://node.local/"):
            return _Resp(_png_bytes(color=(10, 200, 30, 255)))
        raise AssertionError(f"unexpected request {method} {url}")


def _client(fake: FakeFleet) -> FleetImageClient:
    return FleetImageClient(base_url="http://fleet.test", token="tok", _opener=fake.opener)


# --------------------------------------------------------------------------- fleet client
def test_fleet_client_requires_token():
    client = FleetImageClient(base_url="http://fleet.test", token="")
    with pytest.raises(FleetError):
        client.capability()


def test_fleet_client_submit_poll_and_download():
    fake = FakeFleet()
    client = _client(fake)
    cap = client.capability()
    assert cap and cap["taskType"] == "image_flux3"
    task = client.submit_flux3(prompt="hello", image_urls=["http://me/ref.png", "ftp://ignored"], seed=7, upsample=True, job_id="j1")
    assert task["id"] == "task1"
    sent = fake.submitted[0]
    assert sent["taskType"] == "image_flux3"
    assert sent["inputPayload"]["imageUrls"] == ["http://me/ref.png"]
    assert sent["inputPayload"]["seed"] == 7 and sent["inputPayload"]["upsample"] is True
    done = client.wait("task1", sleep=lambda s: None)
    assert task_status(done) == "success"
    assert task_image_url(done) == "http://node.local/view?f=x.png"
    assert client.artifact_bytes(done).startswith(b"\x89PNG")


def test_fleet_client_surfaces_refusal_message():
    fake = FakeFleet(fail_submit=True)
    with pytest.raises(FleetError) as exc:
        _client(fake).submit_flux3(prompt="x")
    assert "422" in str(exc.value) and "quota" in str(exc.value)


def test_fleet_client_wait_raises_on_failed_task():
    fake = FakeFleet(fail_task=True)
    client = _client(fake)
    client.submit_flux3(prompt="x")
    with pytest.raises(FleetError) as exc:
        client.wait("task1", sleep=lambda s: None)
    assert "node exploded" in str(exc.value)


# --------------------------------------------------------------------------- prompt builder
def test_color_name_and_cabinet_description():
    assert color_name("#ffffff") == "white"
    assert color_name("#78583a") in ("chestnut brown", "walnut", "natural oak")
    cab = CABINET_PRESETS[1]
    spec = build_modular_cabinet_spec(cab, tenant_id="t")
    desc = describe_cabinet(cab, spec, STYLE_THEMES["THEME_NORDIC_OAK"])
    assert "modular storage cabinet" in desc
    assert "mm" in desc and "handles" in desc


def test_build_scene_prompt_mentions_room_product_and_guards():
    cab = CABINET_PRESETS[1]
    spec = build_modular_cabinet_spec(cab, tenant_id="t")
    out = build_scene_prompt(BUILTIN_SCENES[0], cab, cabinet_spec=spec, theme=STYLE_THEMES["THEME_NORDIC_OAK"], style_prompt="Scandinavian loft", custom_prompt="多一點綠植", view="WIDE")
    p = out["prompt"]
    assert "photorealistic" in p.lower()
    assert "living room" in p
    assert "sofa" in p and "rug" in p
    assert "same camera angle" in p
    assert "Scandinavian loft" in p and "多一點綠植" in p
    assert "No text" in p and "no people" in p
    assert "whole room" in p  # WIDE view words
    assert out["productDescription"].startswith("2-column")


def test_polish_prompt_falls_back_when_llm_unreachable():
    def bad_opener(req, timeout=None):
        raise urllib.error.URLError("down")

    assert polish_prompt_with_llm("keep this", base_url="http://x/v1", model="m", opener=bad_opener) == "keep this"

    def good_opener(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "qwen3.8:27b"
        return _Resp({"choices": [{"message": {"content": "<think>hmm</think>\n\"A richer photographic brief that keeps the cabinet identical and the same camera, no text.\""}}]})

    polished = polish_prompt_with_llm("short", base_url="http://x/v1", model="qwen3.8:27b", opener=good_opener)
    assert polished.startswith("A richer") and "<think>" not in polished and not polished.startswith('"')


# --------------------------------------------------------------------------- compositing
def test_composite_locked_product_keeps_product_pixels_exact():
    gen = Image.new("RGBA", (40, 40), (0, 0, 255, 255))
    cut = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    for x in range(10, 30):
        for y in range(10, 30):
            cut.putpixel((x, y), (200, 150, 100, 255))
    out = composite_locked_product(gen, cut, feather_px=1.0)
    assert out.mode == "RGB" and out.size == (40, 40)
    assert out.getpixel((20, 20)) == (200, 150, 100)  # product pixel untouched
    assert out.getpixel((2, 2)) == (0, 0, 255)  # background untouched far from the product


def test_composite_resizes_cutout_to_generated_size():
    gen = Image.new("RGBA", (80, 80), (255, 255, 255, 255))
    cut = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    out = composite_locked_product(gen, cut, feather_px=0)
    assert out.size == (80, 80)


# --------------------------------------------------------------------------- variants runner
def test_run_local_scene_variants_writes_files_and_records(tmp_path: Path):
    fake = FakeFleet()
    client = _client(fake)
    cutout = tmp_path / "product_cutout.png"
    cutout.write_bytes(_png_bytes(color=(255, 0, 0, 255)))
    progress: list[int] = []
    records = run_local_scene_variants(
        client,
        item_dir=tmp_path,
        reference_url="http://me/ref.png",
        cutout_path=cutout,
        prompt="photo",
        variants=3,
        seed=100,
        upsample=False,
        on_progress=lambda recs: progress.append(sum(1 for r in recs if r["state"] == "succeeded")),
        sleep=lambda s: None,
    )
    assert [r["seed"] for r in records] == [100, 101, 102]
    assert all(r["state"] == "succeeded" for r in records)
    assert all((tmp_path / r["file"]).exists() for r in records)
    assert (tmp_path / "ai_local_01_raw.png").exists()
    assert (tmp_path / "ai_local.json").exists()
    manifest = json.loads((tmp_path / "ai_local.json").read_text(encoding="utf-8"))
    assert manifest["prompt"] == "photo" and len(manifest["variants"]) == 3
    assert records[0]["caption"] == "a photo" and records[0]["node"] == "5090-3"
    assert progress[-1] == 3
    # product pixels are locked (cutout is fully opaque red)
    img = Image.open(tmp_path / "ai_local_01.png").convert("RGB")
    assert img.getpixel((5, 5)) == (255, 0, 0)
    assert len(fake.submitted) == 3


def test_run_local_scene_variants_marks_failures_without_raising(tmp_path: Path):
    fake = FakeFleet(fail_task=True)
    records = run_local_scene_variants(_client(fake), item_dir=tmp_path, reference_url="http://me/ref.png", cutout_path=None, prompt="p", variants=2, sleep=lambda s: None)
    assert all(r["state"] == "failed" for r in records)
    assert "node exploded" in records[0]["error"]


# --------------------------------------------------------------------------- status / url helpers
def test_build_public_base_url_prefers_configured_value():
    assert build_public_base_url("http://10.0.0.5:8790/", 8792) == "http://10.0.0.5:8790"


def test_engine_status_reports_missing_token_and_loopback_bind():
    status = engine_status({"imageEngine": "fleet_flux3", "fleetApiUrl": "http://fleet.test", "fleetToken": ""}, bind_host="127.0.0.1", public_base_url="", client=FleetImageClient(base_url="http://fleet.test", token=""))
    assert status["ready"] is False
    assert status["tokenConfigured"] is False
    assert any("127.0.0.1" in w for w in status["warnings"])
    assert status["error"]


def test_engine_status_ready_with_fake_fleet():
    fake = FakeFleet()
    status = engine_status({"imageEngine": "fleet_flux3"}, bind_host="0.0.0.0", public_base_url="http://192.168.66.21:8790", client=_client(fake))
    assert status["ready"] is True
    assert status["capability"]["capableNodes"] == 1
    assert [e["id"] for e in status["engines"]] == list(SCENE_AI_ENGINES.keys())


# --------------------------------------------------------------------------- API + worker integration
class FakeRuntime:
    """Stands in for BlenderRuntime: writes beauty.png + product_cutout.png into the job workDir."""

    blender_bin = "fake-blender"
    script_path = None

    def available(self) -> bool:
        return True

    def run_job(self, job: dict) -> dict:
        work = Path(job["workDir"])
        work.mkdir(parents=True, exist_ok=True)
        (work / "beauty.png").write_bytes(_png_bytes(size=(96, 96), color=(180, 170, 150, 255)))
        (work / "product_cutout.png").write_bytes(_png_bytes(size=(96, 96), color=(90, 60, 30, 255)))
        return {"status": "succeeded", "outputs": {"beauty.png": str(work / "beauty.png"), "product_cutout.png": str(work / "product_cutout.png")}, "renderTimeSec": 1.2, "blenderVersion": "fake", "device": "CPU"}


def _wait_batch(client: TestClient, batch_id: str, headers: dict, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        batch = client.get(f"/api/ecommerce-scenes/batches/{batch_id}", headers=headers).json()
        if batch["state"] != "running":
            return batch
        time.sleep(0.05)
    raise AssertionError("batch did not finish")


def test_ai_settings_roundtrip_hides_token(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    base = client.get("/api/ecommerce-scenes/ai-settings").json()
    assert base["imageEngine"] == "fleet_flux3"
    assert base["provider"] == "local"
    assert base["localModel"]
    assert "fleetToken" not in base
    r = client.post("/api/ecommerce-scenes/ai-settings", headers=headers, json={"imageEngine": "builtin", "fleetToken": "abc123", "aiVariants": 9, "aiUpsample": False, "publicBaseUrl": "http://192.168.66.21:8790/"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imageEngine"] == "builtin"
    assert body["fleetTokenConfigured"] is True
    assert body["aiVariants"] == 4 and body["aiUpsample"] is False
    assert body["publicBaseUrl"] == "http://192.168.66.21:8790"
    assert "fleetToken" not in body
    assert client.post("/api/ecommerce-scenes/ai-settings", headers=headers, json={"imageEngine": "nope"}).status_code == 422
    assert client.post("/api/ecommerce-scenes/ai-settings", headers=headers, json={"fleetApiUrl": "ftp://x"}).status_code == 422


def test_ai_prompt_preview_endpoint(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    r = client.post("/api/ecommerce-scenes/ai-prompt", headers=headers, json={"scene": BUILTIN_SCENES[1], "cabinet": CABINET_PRESETS[0], "aiStyleId": "AI_JAPANDI_WABI_SABI", "aiPrompt": "暖光", "view": "FRONT"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "bedroom" in body["prompt"] and "Japandi" in body["prompt"] and "暖光" in body["prompt"]
    assert body["polished"] is False


def test_ai_engine_status_endpoint_never_raises(tmp_path: Path, monkeypatch):
    plat = Platform(tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(plat))
    monkeypatch.setenv("FOX3D_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("FLEET_SERVICE_TOKEN", "")
    monkeypatch.delenv("FLEET_SERVICE_TOKEN_FILE", raising=False)
    client.post("/api/ecommerce-scenes/ai-settings", headers={"X-Tenant-Id": "sonaqueen-home"}, json={"fleetApiUrl": "http://127.0.0.1:1"})
    r = client.get("/api/ecommerce-scenes/ai-engine-status")
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "fleet_flux3"
    assert body["ready"] is False
    assert body["bindHost"] == "127.0.0.1"


def test_matrix_batch_runs_local_ai_variants_and_serves_them(tmp_path: Path, monkeypatch):
    plat = Platform(tmp_path / "data", mock_blender=False)
    plat.runtime = FakeRuntime()
    fake = FakeFleet()
    monkeypatch.setattr("fox3d.ecommerce_scene_studio.FleetImageClient.from_settings", classmethod(lambda cls, settings=None: _client(fake)))
    monkeypatch.setattr("fox3d.local_scene_ai.time.sleep", lambda s: None)
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    client.post("/api/ecommerce-scenes/ai-settings", headers=headers, json={"fleetToken": "tok", "publicBaseUrl": "http://192.168.66.21:8790"})

    r = client.post("/api/ecommerce-scenes/batches", headers=headers, json={"cabinet": CABINET_PRESETS[1], "sceneIds": [BUILTIN_SCENES[0]["id"]], "themeIds": ["THEME_NORDIC_OAK"], "views": ["THREE_QUARTER"], "aiEngine": "fleet_flux3", "aiVariants": 2, "aiSeed": 500, "aiStyleId": "AI_NORDIC_SUNLIT_LOFT", "aiPrompt": "柔和窗光"})
    assert r.status_code == 202, r.text
    batch = r.json()
    assert batch["aiEngine"] == "fleet_flux3" and batch["aiVariantsPerItem"] == 2 and batch["aiSeed"] == 500
    assert batch["publicBaseUrl"] == "http://192.168.66.21:8790"

    done = _wait_batch(client, batch["batchId"], headers)
    item = done["items"][0]
    assert item["state"] == "succeeded", item
    assert item["stage"] == "done" and item["aiState"] == "succeeded"
    assert len(item["aiVariants"]) == 2 and all(v["state"] == "succeeded" for v in item["aiVariants"])
    assert item["aiVariants"][0]["seed"] == 600  # seed + index*100
    assert "柔和窗光" in item["aiPrompt"]
    ref = fake.submitted[0]["inputPayload"]["imageUrls"][0]
    assert ref.startswith("http://192.168.66.21:8790/api/ecommerce-scenes/batches/") and "download/png?workspace=sonaqueen-home&inline=true" in ref

    base = f"/api/ecommerce-scenes/batches/{batch['batchId']}/items/item_01/download"
    for fmt in ("png", "ai_png", "cutout_png"):
        assert client.get(f"{base}/{fmt}?workspace=sonaqueen-home").status_code == 200
    assert client.get(f"{base}/ai_local_png?workspace=sonaqueen-home&variant=1").status_code == 200
    assert client.get(f"{base}/ai_local_png?workspace=sonaqueen-home&variant=2&inline=true").status_code == 200
    assert client.get(f"{base}/ai_local_png?workspace=sonaqueen-home&variant=3").status_code == 404
    assert client.get(f"{base}/ai_local_raw_png?workspace=sonaqueen-home&variant=1").status_code == 200

    zipped = client.get(f"/api/ecommerce-scenes/batches/{batch['batchId']}/zip?workspace=sonaqueen-home")
    assert zipped.status_code == 200
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(zipped.content)).namelist()
    assert any(n.endswith("_C_AI_Local_v1.png") for n in names) and any(n.endswith("_C_AI_Local_v2.png") for n in names)


def test_matrix_batch_builtin_engine_skips_fleet(tmp_path: Path, monkeypatch):
    plat = Platform(tmp_path / "data", mock_blender=False)
    plat.runtime = FakeRuntime()
    called = []
    monkeypatch.setattr("fox3d.ecommerce_scene_studio.FleetImageClient.from_settings", classmethod(lambda cls, settings=None: called.append(1)))
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    r = client.post("/api/ecommerce-scenes/batches", headers=headers, json={"cabinet": CABINET_PRESETS[0], "sceneIds": [BUILTIN_SCENES[0]["id"]], "themeIds": ["THEME_NORDIC_OAK"], "views": ["FRONT"], "aiEngine": "builtin"})
    assert r.status_code == 202
    done = _wait_batch(client, r.json()["batchId"], headers)
    item = done["items"][0]
    assert item["state"] == "succeeded" and item["aiState"] == "builtin" and item["aiVariants"] == []
    assert called == []


def test_matrix_batch_without_token_fails_ai_but_keeps_render(tmp_path: Path, monkeypatch):
    plat = Platform(tmp_path / "data", mock_blender=False)
    plat.runtime = FakeRuntime()
    monkeypatch.setenv("FLEET_SERVICE_TOKEN", "")
    monkeypatch.setenv("FLEET_SERVICE_TOKEN_FILE", str(tmp_path / "missing-token"))
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    r = client.post("/api/ecommerce-scenes/batches", headers=headers, json={"cabinet": CABINET_PRESETS[0], "sceneIds": [BUILTIN_SCENES[0]["id"]], "themeIds": ["THEME_NORDIC_OAK"], "views": ["FRONT"], "aiEngine": "fleet_flux3"})
    assert r.status_code == 202
    done = _wait_batch(client, r.json()["batchId"], headers)
    item = done["items"][0]
    assert item["state"] == "succeeded"
    assert item["aiState"] == "failed" and "金鑰" in (item["aiError"] or "")


def test_overview_lists_scene_ai_engines(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    client = TestClient(create_app(plat))
    ov = client.get("/api/ecommerce-scenes/overview", headers={"X-Tenant-Id": "sonaqueen-home"}).json()
    assert [e["id"] for e in ov["sceneAiEngines"]] == ["fleet_flux3", "builtin", "off"]
    assert ov["maxAiVariants"] == 4
