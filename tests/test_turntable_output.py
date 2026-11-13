from __future__ import annotations

import json
from pathlib import Path

import pytest

from fox3d.blender import BlenderRuntime
from fox3d.pngutil import write_solid_png


@pytest.mark.parametrize("case,success", [("complete", True), ("short", False), ("empty", False), ("invalid", False), ("duplicate", False), ("extra", False)])
def test_turntable_runtime_requires_all_valid_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, success: bool) -> None:
    paths = []
    for i in range(3):
        path = tmp_path / f"{i}.png"
        write_solid_png(path, "123456", 2, 2)
        paths.append(str(path))
    if case == "short": paths.pop()
    if case == "empty": paths.clear()
    if case == "invalid": Path(paths[-1]).write_bytes(b"\x89PNG\r\n\x1a\n")
    if case == "duplicate": paths[-1] = paths[0]
    if case == "extra": paths.append(paths[0])

    class Process:
        def __init__(self, cmd, **kwargs):
            job_path = Path(cmd[-1])
            (job_path.parent / "result.json").write_text(json.dumps({"status": "succeeded", "realOptix": True, "outputs": {"frames": paths, "beauty.png": paths[0] if paths else None}}))
        def poll(self): return 0

    monkeypatch.setattr("fox3d.blender.subprocess.Popen", Process)
    runtime = BlenderRuntime(blender_bin="fake-blender", work_dir=tmp_path / "work", force_mock=False)
    result = runtime.run_job({"jobId": "test", "mode": "PRODUCT_360_E2E", "animation": {"type": "TURNTABLE", "frames": 3}})
    assert (result.status == "succeeded") is success
    assert result.real_render_output is success
