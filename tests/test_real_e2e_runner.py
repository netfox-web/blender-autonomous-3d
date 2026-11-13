"""Offline tests for fox3d.e2e.run_real_acceptance (issue #354)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fox3d import blender, platform as platform_mod
from fox3d.e2e import _is_real_pass, run_real_acceptance
from fox3d.platform import Platform


def _patch_probe(monkeypatch: pytest.MonkeyPatch, probe: blender.HostProbe) -> None:
    monkeypatch.setattr(platform_mod, "probe_host", lambda **_: probe)


def _blocked_probe(*, gpu_evidence: str | None = None) -> blender.HostProbe:
    return blender.HostProbe(
        blender=False,
        blenderBinary=None,
        blenderVersion=None,
        blenderVersionRaw="",
        cycles=False,
        cuda=False,
        optix=False,
        cyclesDevices=[],
        gpus=[],
        gpuName=gpu_evidence or "none",
        vramGb=0,
        driver=None,
        blocked=[blender.BLOCKED_NO_BLENDER, blender.BLOCKED_NO_OPTIX],
        realBlender=False,
        realGPU=False,
        realCycles=False,
        realOptix=False,
    )


def _real_probe(*, gpu_name: str = "NVIDIA Test GPU") -> blender.HostProbe:
    return blender.HostProbe(
        blender=True,
        blenderBinary="/usr/bin/blender",
        blenderVersion="5.0.0",
        blenderVersionRaw="Blender 5.0.0",
        cycles=True,
        cuda=True,
        optix=True,
        cyclesDevices=[{"type": "OPTIX"}],
        gpus=[{"gpuIndex": 0, "name": gpu_name, "vramGb": 8}],
        gpuName=gpu_name,
        vramGb=8,
        driver="999.99",
        blocked=[],
        realBlender=True,
        realGPU=True,
        realCycles=True,
        realOptix=True,
    )


def _real_job(**over: Any) -> dict[str, Any]:
    out_over = over.pop("output", None)
    job: dict[str, Any] = {
        "status": "completed",
        "realBlender": True,
        "realOptix": True,
        "realRenderOutput": True,
        "usedMock": False,
    }
    job.update(over)
    out: dict[str, Any] = {
        "realBlender": bool(job.get("realBlender")),
        "realOptix": bool(job.get("realOptix")),
        "realRenderOutput": bool(job.get("realRenderOutput")),
        "device": "OPTIX",
    }
    if out_over is not None:
        out.update(out_over)
    job["output"] = out
    return job


def _blocked_job() -> dict[str, Any]:
    return {"status": "blocked", "error": "no blender"}


def _mock_render_job() -> dict[str, Any]:
    return {
        "job": {
            "status": "completed",
            "usedMock": True,
            "realBlender": False,
            "output": {"usedMock": True},
        }
    }


@pytest.mark.parametrize(
    "job,expected",
    [
        (_real_job(), True),
        (_real_job(status="succeeded"), True),
        (_real_job(realBlender=False), False),
        (_real_job(realOptix=False), False),
        (_real_job(realRenderOutput=False), False),
        (_real_job(usedMock=True), False),
        (_real_job(output={"realBlender": True, "realOptix": True, "realRenderOutput": True, "usedMock": True}), False),
        ({"status": "completed", "output": {"realBlender": True, "realOptix": True, "realRenderOutput": True}}, True),
        ({"status": "running"}, False),
    ],
)
def test_is_real_pass_truth_table(job: dict[str, Any], expected: bool) -> None:
    assert _is_real_pass(job) is expected


def test_offline_no_blender_writes_docs_all_blocked_deps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, _blocked_probe())

    def smoke(self: Platform, *, tenant_id: str = "ops") -> dict[str, Any]:
        return _blocked_job()

    def product(self: Platform, *, tenant_id: str, sku: str, **_: Any) -> dict[str, Any]:
        return {"job": _blocked_job()}

    def render(self: Platform, product_id: str, *, tenant_id: str, explode: bool = False) -> dict[str, Any]:
        return {"job": _blocked_job()}

    monkeypatch.setattr(Platform, "real_smoke_test", smoke)
    monkeypatch.setattr(Platform, "product_e2e", product)
    monkeypatch.setattr(Platform, "render_parametric", render)

    report = run_real_acceptance(tmp_path)
    assert report["productionReady"] is False

    docs = tmp_path / "docs"
    md = docs / "REAL_E2E_ACCEPTANCE.md"
    js = docs / "REAL_E2E_ACCEPTANCE.json"
    assert md.is_file() and js.is_file()

    by_name = {r["check"]: r["status"] for r in report["rows"]}
    for name in (
        "Blender executable",
        "blender --version",
        "NVIDIA GPU / VRAM",
        "OptiX",
        "REAL_SMOKE_TEST (cube/plane/camera/3-point/Cycles/OptiX/512 PNG)",
        "PRODUCT_E2E WHITE_STUDIO",
        "PRODUCT_360_E2E 36 frames",
        "PARAMETRIC STORAGE_CABINET 800x1800x400",
    ):
        assert by_name[name] == "BLOCKED"


def test_mock_row_forces_production_ready_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, _real_probe())

    def smoke(self: Platform, *, tenant_id: str = "ops") -> dict[str, Any]:
        return _real_job()

    def product(self: Platform, *, tenant_id: str, sku: str, **_: Any) -> dict[str, Any]:
        return {
            "job": _real_job(),
            "twin": {"twinId": "twin-e2e", "previewAssetId": "prev-1"},
        }

    def p360(self: Platform, *, tenant_id: str, twin_id: str, frames: int = 36) -> dict[str, Any]:
        return {"job": _real_job()}

    render_calls = {"n": 0}

    def render(self: Platform, product_id: str, *, tenant_id: str, explode: bool = False) -> dict[str, Any]:
        render_calls["n"] += 1
        if render_calls["n"] == 1:
            return _mock_render_job()
        return {"job": _real_job()}

    monkeypatch.setattr(Platform, "real_smoke_test", smoke)
    monkeypatch.setattr(Platform, "product_e2e", product)
    monkeypatch.setattr(Platform, "product_360_e2e", p360)
    monkeypatch.setattr(Platform, "render_parametric", render)

    report = run_real_acceptance(tmp_path)
    mock_rows = [r for r in report["rows"] if r["status"] == "MOCK"]
    assert mock_rows, "expected at least one MOCK row from parametric render"
    assert report["productionReady"] is False


def test_product_360_completed_without_real_blender_is_not_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, _real_probe())

    def smoke(self: Platform, *, tenant_id: str = "ops") -> dict[str, Any]:
        return _real_job()

    def product(self: Platform, *, tenant_id: str, sku: str, **_: Any) -> dict[str, Any]:
        return {"job": _real_job(), "twin": {"twinId": "twin-360"}}

    def p360(self: Platform, *, tenant_id: str, twin_id: str, frames: int = 36) -> dict[str, Any]:
        return {
            "job": {
                "status": "completed",
                "realBlender": False,
                "realOptix": False,
                "realRenderOutput": False,
                "usedMock": False,
                "output": {"files": ["f1.png"]},
            }
        }

    def render(self: Platform, product_id: str, *, tenant_id: str, explode: bool = False) -> dict[str, Any]:
        return {"job": _real_job()}

    monkeypatch.setattr(Platform, "real_smoke_test", smoke)
    monkeypatch.setattr(Platform, "product_e2e", product)
    monkeypatch.setattr(Platform, "product_360_e2e", p360)
    monkeypatch.setattr(Platform, "render_parametric", render)

    report = run_real_acceptance(tmp_path)
    row = next(r for r in report["rows"] if r["check"] == "PRODUCT_360_E2E 36 frames")
    assert row["status"] == "FAIL"
    assert report["productionReady"] is False


def test_resize_hash_unchanged_writes_fail_not_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, _blocked_probe())

    def smoke(self: Platform, *, tenant_id: str = "ops") -> dict[str, Any]:
        return _blocked_job()

    def product(self: Platform, *, tenant_id: str, sku: str, **_: Any) -> dict[str, Any]:
        return {"job": _blocked_job()}

    def render(self: Platform, product_id: str, *, tenant_id: str, explode: bool = False) -> dict[str, Any]:
        return {"job": _blocked_job()}

    orig_resize = Platform.resize_parametric

    def resize(self: Platform, product_id: str, *, tenant_id: str, **kw: Any) -> dict[str, Any]:
        base_hash = (self.parametrics.get(product_id) or {}).get("engineeringHash")
        out = orig_resize(self, product_id, tenant_id=tenant_id, **kw)
        if base_hash:
            return {**out, "engineeringHash": base_hash}
        return out

    monkeypatch.setattr(Platform, "real_smoke_test", smoke)
    monkeypatch.setattr(Platform, "product_e2e", product)
    monkeypatch.setattr(Platform, "render_parametric", render)
    monkeypatch.setattr(Platform, "resize_parametric", resize)

    report = run_real_acceptance(tmp_path)
    row = next(r for r in report["rows"] if "geometry+BOM sync" in r["check"])
    assert row["status"] == "FAIL"
    assert "unchanged" in row["evidence"]


def test_markdown_escapes_pipe_in_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, _blocked_probe(gpu_evidence="pipe|gpu|name"))

    def smoke(self: Platform, *, tenant_id: str = "ops") -> dict[str, Any]:
        return _blocked_job()

    def product(self: Platform, *, tenant_id: str, sku: str, **_: Any) -> dict[str, Any]:
        return {"job": _blocked_job()}

    def render(self: Platform, product_id: str, *, tenant_id: str, explode: bool = False) -> dict[str, Any]:
        return {"job": _blocked_job()}

    monkeypatch.setattr(Platform, "real_smoke_test", smoke)
    monkeypatch.setattr(Platform, "product_e2e", product)
    monkeypatch.setattr(Platform, "render_parametric", render)

    run_real_acceptance(tmp_path)
    md = (tmp_path / "docs" / "REAL_E2E_ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "pipe\\|gpu\\|name" in md
    assert "| NVIDIA GPU / VRAM | BLOCKED |" in md

    saved = json.loads((tmp_path / "docs" / "REAL_E2E_ACCEPTANCE.json").read_text(encoding="utf-8"))
    gpu_row = next(r for r in saved["rows"] if r["check"] == "NVIDIA GPU / VRAM")
    assert "|" in gpu_row["evidence"]

@pytest.mark.parametrize("case,expected_status", [
    ("complete", "REAL"), ("short", "FAIL"), ("empty", "FAIL"),
    ("duplicate", "FAIL"), ("invalid", "FAIL"), ("missing", "FAIL"),
    ("extra", "FAIL"), ("blocked", "BLOCKED"),
])
def test_product_360_acceptance_checks_stored_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, expected_status: str) -> None:
    from fox3d.pngutil import write_solid_png

    _patch_probe(monkeypatch, _real_probe())
    monkeypatch.setattr(Platform, "real_smoke_test", lambda self, **kw: _real_job())
    monkeypatch.setattr(Platform, "product_e2e", lambda self, **kw: {"job": _real_job(), "twin": {"twinId": "twin"}})
    monkeypatch.setattr(Platform, "render_parametric", lambda self, *a, **kw: {"job": _real_job()})

    def p360(self: Platform, **kw: Any) -> dict[str, Any]:
        assert kw["frames"] == 36
        if case == "blocked":
            return {"job": _blocked_job()}
        image = tmp_path / "frame.png"
        write_solid_png(image, "123456", 2, 2)
        data = image.read_bytes()
        ids = [self.dam.put(tenant_id="ops", kind="render", name=f"{i}.png", data=data).asset_id for i in range(36)]
        if case == "short": ids.pop()
        if case == "empty": ids.clear()
        if case == "duplicate": ids[-1] = ids[0]
        if case == "missing": ids[-1] = "missing"
        if case == "extra": ids.append("extra")
        if case == "invalid": Path(self.dam.get(ids[-1], tenant_id="ops").path).write_bytes(b"not a PNG")
        return {"job": _real_job(output={"files": {"frames": ids}})}

    monkeypatch.setattr(Platform, "product_360_e2e", p360)
    report = run_real_acceptance(tmp_path)
    row = next(r for r in report["rows"] if r["check"] == "PRODUCT_360_E2E 36 frames")
    assert row["status"] == expected_status
    if expected_status == "FAIL":
        assert report["productionReady"] is False
