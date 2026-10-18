"""fleet_blender_task.py (GPU Fleet ``blender_scene_render`` executor): hermetic tests with a FAKE blender.

The fake is a Python file passed as ``--blender``; the executor's documented test hook runs any ``*.py``
"blender" under ``sys.executable`` with the real argv tail (``-b --factory-startup -P <script> -- job.json``).
No real Blender, no network, no GPU node.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fleet_blender_task.py"
BLENDER_JOB = ROOT / "scripts" / "blender_job.py"
PUBLIC_URL = "http://node.local:8188"
SCENE_HASH = "f" * 16
JOB_ID = "scene-001"

FAKE_BLENDER = r'''
"""Fake blender: honours only ``-- job.json``; behaviour is driven by job["fake"]."""
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[sys.argv.index("--") + 1 :]
job = json.loads(Path(args[0]).read_text(encoding="utf-8"))
work = Path(job["workDir"])
fake = job.get("fake") or {}
mode = fake.get("mode", "ok")
progress_file = Path(job["progressFile"])


def progress(value, stage):
    progress_file.write_text(json.dumps({"progress": value, "stage": stage}), encoding="utf-8")


progress(0.35, "built")
print("fake blender starting", flush=True)
print("fake warning on stderr", file=sys.stderr, flush=True)
if mode == "hang":
    time.sleep(60)
if mode == "exit2":
    sys.exit(2)
outputs = {}
if mode != "no_beauty":
    (work / "beauty.png").write_bytes(b"\x89PNG" + b"0" * 60)
    outputs["beauty.png"] = str(work / "beauty.png")
if fake.get("cutout", True):
    (work / "product_cutout.png").write_bytes(b"\x89PNG" + b"1" * 60)
    outputs["product_cutout.png"] = str(work / "product_cutout.png")
if not fake.get("skipModels"):
    if job.get("exportGlb"):
        (work / "model.glb").write_bytes(b"glTF" + b"2" * 60)
        outputs["model.glb"] = str(work / "model.glb")
    if job.get("exportBlend"):
        (work / "model.blend").write_bytes(b"BLENDER" + b"3" * 60)
        outputs["model.blend"] = str(work / "model.blend")
status = "failed" if mode == "fail_status" else "succeeded"
result = {
    "status": status,
    "error": "simulated render failure" if status == "failed" else None,
    "engine": "CYCLES",
    "device": "OPTIX",
    "samples": (job.get("render") or {}).get("samples", 32),
    "renderTimeSec": 5.2,
    "blenderVersion": "5.2.2 LTS",
    "outputs": outputs,
    "assetsRoot": os.environ.get("FOX3D_ASSETS_ROOT"),
    "argv": sys.argv,
    "cwd": os.getcwd(),
    "exportBlend": job.get("exportBlend"),
    "exportGlb": job.get("exportGlb"),
    "engineering": job.get("engineering"),
}
(work / "result.json").write_text(json.dumps(result), encoding="utf-8")
mirror = fake.get("mirror")
if mirror:
    Path(mirror).write_text(json.dumps(result), encoding="utf-8")
progress(1.0, "done")
if mode == "ok_exit1":
    sys.exit(1)
sys.exit(0 if status == "succeeded" else 1)
'''


@dataclass
class Harness:
    fake: Path
    work_root: Path
    out_dir: Path
    assets_root: Path
    mirror: Path

    def argv(self, *extra: str, timeout: str = "600") -> list[str]:
        return [
            "--blender",
            str(self.fake),
            "--script",
            str(BLENDER_JOB),
            "--assets-root",
            str(self.assets_root),
            "--work-root",
            str(self.work_root),
            "--out-dir",
            str(self.out_dir),
            "--public-url",
            PUBLIC_URL,
            "--timeout",
            timeout,
            *extra,
        ]

    def mirrored(self) -> dict[str, Any]:
        """What the fake blender saw (survives the work dir being deleted on success)."""
        data = json.loads(self.mirror.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        return data


def make_payload(
    harness: Harness,
    *,
    job_id: str | None = JOB_ID,
    export_models: bool | None = False,
    fake: dict[str, Any] | None = None,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    job: dict[str, Any] = {
        "jobId": "inner-job",
        "recipePreview": True,
        "goldenRecipe": False,
        "goldenIdentity": None,
        "engineering": {
            "width": 800,
            "height": 1800,
            "depth": 400,
            "sceneDefinition": {"photorealMode": True, "items": [{"id": "sofa", "pos": [1.5, 0.0]}]},
            "sceneHash": SCENE_HASH,
        },
        "camera": {"id": "front"},
        "render": {"width": 512, "height": 512, "samples": 32, "device": "OPTIX"},
        # Both true on purpose: the executor must force them to bool(payload.exportModels).
        "exportBlend": True,
        "exportGlb": True,
        "fake": {"mode": "ok", "mirror": str(harness.mirror), **(fake or {})},
    }
    payload: dict[str, Any] = {"job": job}
    if job_id is not None:
        payload["jobId"] = job_id
    if export_models is not None:
        payload["exportModels"] = export_models
    if timeout_sec is not None:
        payload["timeoutSec"] = timeout_sec
    return payload


def run_main(fbt: ModuleType, argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = fbt.main(argv)
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1, f"stdout must hold exactly the result line, got: {captured.out!r}"
    line = json.loads(lines[0])
    assert isinstance(line, dict)
    return code, line


@pytest.fixture(scope="module")
def fbt() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fleet_blender_task", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fleet_blender_task"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.delenv("FLEET_PROGRESS_URL", raising=False)
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    fake = tmp_path / "fake_blender.py"
    fake.write_text(FAKE_BLENDER, encoding="utf-8")
    harness = Harness(
        fake=fake,
        work_root=tmp_path / "work",
        out_dir=tmp_path / "out",
        assets_root=tmp_path / "assets",
        mirror=tmp_path / "mirror.json",
    )
    harness.assets_root.mkdir()
    return harness


# --------------------------------------------------------------------------- end to end: success


def test_success_shape_artifact_order_urls_and_cleanup(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    forwarded: list[tuple[float, str]] = []

    def record(percent: float, note: str) -> bool:
        forwarded.append((percent, note))
        return True

    monkeypatch.setattr(fbt, "progress", record)
    payload = make_payload(harness, export_models=True)

    code, line = run_main(fbt, harness.argv("--json", json.dumps(payload)), capsys)

    assert code == 0
    assert line["status"] == "succeeded"
    names = [item["name"] for item in line["artifacts"]]
    assert names == ["beauty.png", "product_cutout.png", "model.glb", "model.blend"]
    beauty_url = f"{PUBLIC_URL}/view?filename=beauty.png&subfolder=fox3d%2F{JOB_ID}&type=output"
    assert line["artifacts"][0]["url"] == beauty_url
    assert line["image"] == {"url": beauty_url, "mimeType": "image/png", "kind": "image", "storage": "url"}
    assert line["artifacts"][2]["url"] == f"{PUBLIC_URL}/view?filename=model.glb&subfolder=fox3d%2F{JOB_ID}&type=output"
    assert [item["mimeType"] for item in line["artifacts"]] == [
        "image/png",
        "image/png",
        "model/gltf-binary",
        "application/octet-stream",
    ]
    assert [item["kind"] for item in line["artifacts"]] == ["image", "image", "file", "file"]
    assert all(item["storage"] == "url" for item in line["artifacts"])
    assert line["hasCutout"] is True
    assert line["renderTimeSec"] == 5.2
    assert line["blenderVersion"] == "5.2.2 LTS"
    assert line["device"] == "OPTIX"
    assert line["engine"] == "CYCLES"
    assert line["samples"] == 32
    metrics = line["metrics"]
    assert metrics["renderSec"] == 5.2
    assert metrics["blenderSec"] > 0
    assert metrics["totalSec"] >= metrics["blenderSec"]

    dest = harness.out_dir / "fox3d" / JOB_ID
    assert sorted(path.name for path in dest.iterdir()) == sorted(names)
    assert (dest / "beauty.png").read_bytes().startswith(b"\x89PNG")
    assert not (harness.work_root / JOB_ID).exists(), "work dir must be deleted on success"

    seen = harness.mirrored()
    assert seen["assetsRoot"] == str(harness.assets_root.resolve()), "FOX3D_ASSETS_ROOT must reach blender"
    assert seen["exportBlend"] is True and seen["exportGlb"] is True
    assert os.path.normcase(seen["cwd"]) == os.path.normcase(str(harness.work_root.resolve() / JOB_ID))
    argv = seen["argv"]
    assert argv[1:4] == ["-b", "--factory-startup", "-P"]
    assert argv[4] == str(BLENDER_JOB)
    assert argv[5] == "--" and argv[6].endswith("job.json")
    assert seen["engineering"] == payload["job"]["engineering"], "sceneDefinition/sceneHash must not be modified"
    assert (100.0, "done") in forwarded


def test_export_models_default_false_forces_flags_and_omits_models(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = make_payload(harness, export_models=None)  # key absent -> default false

    code, line = run_main(fbt, harness.argv("--json", json.dumps(payload)), capsys)

    assert code == 0
    assert [item["name"] for item in line["artifacts"]] == ["beauty.png", "product_cutout.png"]
    assert line["hasCutout"] is True
    seen = harness.mirrored()
    assert seen["exportBlend"] is False and seen["exportGlb"] is False, "job flags must follow payload.exportModels"
    dest = harness.out_dir / "fox3d" / JOB_ID
    assert sorted(path.name for path in dest.iterdir()) == ["beauty.png", "product_cutout.png"]


def test_missing_cutout_yields_single_artifact(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = make_payload(harness, fake={"cutout": False})

    code, line = run_main(fbt, harness.argv("--json", json.dumps(payload)), capsys)

    assert code == 0
    assert line["hasCutout"] is False
    assert [item["name"] for item in line["artifacts"]] == ["beauty.png"]
    assert line["image"]["url"] == line["artifacts"][0]["url"]
    assert not (harness.out_dir / "fox3d" / JOB_ID / "product_cutout.png").exists()


def test_export_models_without_files_and_job_id_sanitised(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = make_payload(harness, job_id="../evil id", export_models=True, fake={"skipModels": True})

    code, line = run_main(fbt, harness.argv("--json", json.dumps(payload)), capsys)

    assert code == 0
    assert [item["name"] for item in line["artifacts"]] == ["beauty.png", "product_cutout.png"]
    assert "subfolder=fox3d%2F_evil_id&" in line["image"]["url"]
    assert (harness.out_dir / "fox3d" / "_evil_id" / "beauty.png").is_file()
    assert not (harness.out_dir.parent / "evil id").exists()
    assert sorted(path.name for path in harness.out_dir.iterdir()) == ["fox3d"]


def test_payload_file_flat_style_and_startup_prune(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    old = time.time() - 4 * 86400
    stale_nested = harness.out_dir / "fox3d" / "old-job"
    stale_flat = harness.out_dir / "fox3d_old-job"
    fresh = harness.out_dir / "fox3d" / "fresh-job"
    for path in (stale_nested, stale_flat, fresh):
        path.mkdir(parents=True)
        (path / "beauty.png").write_bytes(b"x" * 40)
    os.utime(stale_nested, (old, old))
    os.utime(stale_flat, (old, old))
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(make_payload(harness, export_models=True)), encoding="utf-8")

    code, line = run_main(fbt, harness.argv(f"--payload-file={payload_file}", "--subfolder-style", "flat"), capsys)

    assert code == 0
    assert line["image"]["url"] == f"{PUBLIC_URL}/view?filename=beauty.png&subfolder=fox3d_{JOB_ID}&type=output"
    assert (harness.out_dir / f"fox3d_{JOB_ID}" / "model.blend").is_file()
    assert not (harness.out_dir / "fox3d" / JOB_ID).exists()
    assert not stale_nested.exists() and not stale_flat.exists(), "dirs older than 3 days are pruned on startup"
    assert fresh.exists()


def test_succeeded_result_with_nonzero_exit_still_succeeds(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = make_payload(harness, fake={"mode": "ok_exit1"})

    code, line = run_main(fbt, harness.argv("--json", json.dumps(payload)), capsys)

    assert code == 0
    assert line["status"] == "succeeded"


# --------------------------------------------------------------------------- end to end: failures


@pytest.mark.parametrize(
    ("mode", "timeout", "expected"),
    [
        ("no_beauty", "600", "beauty.png missing"),
        ("exit2", "600", "blender exit 2: no result.json"),
        ("fail_status", "600", "blender failed: simulated render failure"),
        ("hang", "1", "timeout"),
    ],
)
def test_failures_report_json_and_keep_work_dir(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str], mode: str, timeout: str, expected: str
) -> None:
    payload = make_payload(harness, fake={"mode": mode})
    started = time.monotonic()

    code, line = run_main(fbt, harness.argv("--json", json.dumps(payload), timeout=timeout), capsys)

    assert code == 1
    assert line["status"] == "failed"
    assert line["error"] == expected
    assert "fake blender starting" in line["stderrTail"]
    assert "fake warning on stderr" in line["stderrTail"]
    work_dir = harness.work_root / JOB_ID
    assert work_dir.is_dir(), "work dir must be kept on failure"
    assert (work_dir / "blender.log").is_file() and (work_dir / "job.json").is_file()
    assert not (harness.out_dir / "fox3d" / JOB_ID).exists()
    if mode == "hang":
        assert time.monotonic() - started < 10


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (["--json", "{not json"], "payload is not valid JSON"),
        ([], "payload missing"),
        (["--json", "[]"], "payload must be a JSON object"),
        (["--json", '{"jobId": "x"}'], "payload.job must be an object"),
        (["--json", "{}", "--bogus"], "bad arguments"),
        (["--payload-file", "does-not-exist.json"], "payload file unreadable"),
    ],
)
def test_bad_payload_fails_before_blender(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str], extra: list[str], expected: str
) -> None:
    code, line = run_main(fbt, harness.argv(*extra), capsys)

    assert code == 1
    assert line["status"] == "failed"
    assert expected in line["error"]
    assert line["stderrTail"] == ""
    assert not harness.work_root.exists()


def test_missing_blender_or_script_fails_cleanly(
    fbt: ModuleType, harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    payload_json = json.dumps(make_payload(harness))
    argv = harness.argv("--json", payload_json)
    argv[argv.index("--blender") + 1] = str(tmp_path / "no-such-blender")

    code, line = run_main(fbt, argv, capsys)

    assert code == 1 and "blender not found" in line["error"]
    argv = harness.argv("--json", payload_json)
    argv[argv.index("--script") + 1] = str(tmp_path / "no-such-script.py")
    code, line = run_main(fbt, argv, capsys)
    assert code == 1 and "script not found" in line["error"]


# --------------------------------------------------------------------------- pure helpers


def test_parse_payload_args_json_and_payload_file_forms(fbt: ModuleType, harness: Harness, tmp_path: Path) -> None:
    payload = {"jobId": "p1", "job": {}}
    payload_file = tmp_path / "p.json"
    payload_file.write_text(json.dumps({"jobId": "from-file", "job": {}}), encoding="utf-8")

    args, loaded = fbt.parse_payload_args(harness.argv("--json", json.dumps(payload)))
    assert loaded == payload
    assert args.timeout == 600.0 and args.subfolder_style == "nested"

    _, loaded = fbt.parse_payload_args(harness.argv("--payload-file", str(payload_file)))
    assert loaded["jobId"] == "from-file"
    _, loaded = fbt.parse_payload_args(harness.argv(f"--payload-file={payload_file}"))
    assert loaded["jobId"] == "from-file"
    _, loaded = fbt.parse_payload_args(harness.argv("--json", json.dumps(payload), f"--payload-file={payload_file}"))
    assert loaded["jobId"] == "from-file", "an explicit payload file wins over inline JSON"
    with pytest.raises(fbt.TaskError, match="bad arguments"):
        fbt.parse_payload_args(["--json", "{}"])


def test_sanitize_and_resolve_job_id(fbt: ModuleType) -> None:
    assert fbt.sanitize_job_id("../etc/passwd") == "_etc_passwd"
    assert fbt.sanitize_job_id(" scene 001/ß ") == "scene_001__"
    assert fbt.sanitize_job_id(".hidden") == "hidden"
    assert fbt.sanitize_job_id("ok-ID_1.2") == "ok-ID_1.2"
    assert len(fbt.sanitize_job_id("a" * 100)) == 80
    assert fbt.sanitize_job_id("///") == "___"
    generated = {fbt.sanitize_job_id(value) for value in ("", None, "...", "   ")}
    assert len(generated) == 4, "empty ids fall back to a fresh uuid4 hex each time"
    for job_id in generated:
        assert len(job_id) == 32 and job_id.isalnum() and not job_id.startswith(".")
    assert fbt.sanitize_job_id(42) == "42"

    assert fbt.resolve_job_id({"jobId": "outer", "job": {"jobId": "inner"}}) == "outer"
    assert fbt.resolve_job_id({"jobId": "", "job": {"jobId": "inner"}}) == "inner"
    assert fbt.resolve_job_id({"job": {"jobId": "in ner"}}) == "in_ner"
    assert len(fbt.resolve_job_id({"job": {}})) == 32


def test_prune_outputs_only_old_fox3d_dirs(fbt: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "out"
    now = time.time()
    old = now - fbt.PRUNE_AGE_SEC - 60
    keep_dirs = [out / "fox3d" / "fresh", out / "fox3d_fresh", out / "other_old"]
    old_dirs = [out / "fox3d" / "stale", out / "fox3d_stale"]
    for path in keep_dirs + old_dirs:
        path.mkdir(parents=True)
    stray_file = out / "fox3d_stray.txt"
    stray_file.write_text("x", encoding="utf-8")
    for path in [*old_dirs, out / "other_old", stray_file]:
        os.utime(path, (old, old))

    pruned = fbt.prune_outputs(out, now=now)

    assert sorted(pruned) == sorted(old_dirs)
    assert all(not path.exists() for path in old_dirs)
    assert all(path.exists() for path in keep_dirs)
    assert stray_file.exists()
    assert fbt.prune_outputs(tmp_path / "missing", now=now) == []


def test_progress_posts_json_with_headers_and_never_raises(fbt: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[urllib.request.Request] = []

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        requests.append(request)
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.delenv("FLEET_PROGRESS_URL", raising=False)
    monkeypatch.delenv("FLEET_API_KEY", raising=False)
    assert fbt.progress(10, "no env") is False
    assert requests == []

    monkeypatch.setenv("FLEET_PROGRESS_URL", "http://agent.local/progress")
    monkeypatch.setenv("FLEET_API_KEY", "secret-key")
    assert fbt.progress(35.0, "built") is True
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == "http://agent.local/progress"
    assert request.get_method() == "POST"
    assert request.get_header("X-api-key") == "secret-key"
    assert request.get_header("User-agent") == fbt.USER_AGENT
    assert request.get_header("Content-type") == "application/json"
    assert isinstance(request.data, bytes)
    assert json.loads(request.data) == {"percent": 35.0, "note": "built"}

    def broken_urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        raise OSError("agent down")

    monkeypatch.setattr(urllib.request, "urlopen", broken_urlopen)
    assert fbt.progress(50.0, "render") is False


def test_read_progress_accepts_blender_job_and_percent_shapes(fbt: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    assert fbt.read_progress(path) is None
    path.write_text('{"progress": 0.35, "stage": "built"}', encoding="utf-8")
    assert fbt.read_progress(path) == (35.0, "built")
    path.write_text('{"percent": 40, "note": "rendering"}', encoding="utf-8")
    assert fbt.read_progress(path) == (40.0, "rendering")
    path.write_text('{"progress": 1.7}', encoding="utf-8")
    assert fbt.read_progress(path) == (100.0, "")
    path.write_text('{"progress": "soon"}', encoding="utf-8")
    assert fbt.read_progress(path) is None
    path.write_text("{truncated", encoding="utf-8")
    assert fbt.read_progress(path) is None

    sent: list[tuple[float, str]] = []

    def sink(percent: float, note: str) -> bool:
        sent.append((percent, note))
        return True

    forwarder = fbt.ProgressForwarder(path, sink=sink)
    forwarder.poll()
    path.write_text('{"progress": 0.5, "stage": "render"}', encoding="utf-8")
    forwarder.poll()
    forwarder.poll()
    assert sent == [(50.0, "render")], "unchanged progress is not re-sent"


def test_artifact_list_and_build_result_tolerate_missing(fbt: ModuleType) -> None:
    subfolder = "fox3d/j1"
    names = ["model.blend", "product_cutout.png", "beauty.png", "model.glb", "depth.png"]
    with_models = fbt.artifact_list(names, public_url=PUBLIC_URL + "/", subfolder=subfolder, export_models=True)
    assert [item["name"] for item in with_models] == ["beauty.png", "product_cutout.png", "model.glb", "model.blend"]
    assert with_models[0]["url"] == f"{PUBLIC_URL}/view?filename=beauty.png&subfolder=fox3d%2Fj1&type=output"
    without_models = fbt.artifact_list(names, public_url=PUBLIC_URL, subfolder=subfolder, export_models=False)
    assert [item["name"] for item in without_models] == ["beauty.png", "product_cutout.png"]

    result = fbt.build_result(None, without_models[:1], total_sec=11.04, blender_sec=9.8)
    assert result["status"] == "succeeded"
    assert result["hasCutout"] is False
    assert result["image"] == {key: value for key, value in without_models[0].items() if key != "name"}
    assert result["renderTimeSec"] is None and result["blenderVersion"] is None and result["samples"] is None
    assert result["metrics"] == {"totalSec": 11.04, "renderSec": None, "blenderSec": 9.8}

    partial = {"renderTimeSec": "5.2", "samples": 32.0, "device": "OPTIX"}
    full = fbt.build_result(partial, with_models, total_sec=1, blender_sec=1)
    assert full["renderTimeSec"] == 5.2 and full["samples"] == 32 and full["device"] == "OPTIX"
    assert full["hasCutout"] is True
    with pytest.raises(fbt.TaskError, match=r"beauty\.png missing"):
        fbt.build_result(None, [], total_sec=1, blender_sec=1)


def test_blender_command_hook_and_timeout_policy(fbt: ModuleType, tmp_path: Path) -> None:
    job_file = tmp_path / "job.json"
    assert fbt.blender_command("fake.PY", "blender_job.py", job_file) == [
        sys.executable,
        "fake.PY",
        "-b",
        "--factory-startup",
        "-P",
        "blender_job.py",
        "--",
        str(job_file),
    ]
    real = fbt.blender_command("/opt/blender/blender", "s.py", job_file)
    assert real[:3] == ["/opt/blender/blender", "-b", "--factory-startup"]

    assert fbt.effective_timeout(None, 600.0) == 600.0
    assert fbt.effective_timeout(30, 600.0) == 30.0
    assert fbt.effective_timeout(900, 600.0) == 600.0
    assert fbt.effective_timeout("abc", 600.0) == 600.0
    assert fbt.effective_timeout(-5, 600.0) == 600.0
    with pytest.raises(fbt.TaskError):
        fbt.effective_timeout(None, 0.0)
    assert fbt.output_subfolder("j1", "nested") == "fox3d/j1"
    assert fbt.output_subfolder("j1", "flat") == "fox3d_j1"
