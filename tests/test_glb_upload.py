"""Tests for POST /api/ecommerce-scenes/props/upload-glb validation and tenant isolation."""
from __future__ import annotations

import base64
import struct
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.ecommerce_scene_studio import (
    CABINET_PRESETS,
    resolve_scene_glb_paths_for_blender,
    validate_glb_binary,
)
from fox3d.platform import Platform
from fox3d.pngutil import write_glb_stub


def _minimal_glb_bytes() -> bytes:
    path = Path("_minimal_fixture.glb")
    try:
        write_glb_stub(path, name="Prop")
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    plat = Platform(tmp_path / "data", mock_blender=True)
    return TestClient(create_app(plat)), Path(plat.root)


def test_upload_minimal_valid_glb(tmp_path: Path):
    client, root = _client(tmp_path)
    raw = _minimal_glb_bytes()
    res = client.post(
        "/api/ecommerce-scenes/props/upload-glb",
        headers={"X-Tenant-Id": "sonaqueen-home"},
        json={"filename": "sofa.glb", "dataBase64": _b64(raw)},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["propId"].startswith("glb_sofa_")
    assert body["sizeBytes"] == len(raw)
    glb_path = body["glbPath"]
    assert not Path(glb_path).is_absolute()
    assert "glb-props" in glb_path
    on_disk = root / glb_path
    assert on_disk.read_bytes() == raw


def test_upload_rejects_bad_magic(tmp_path: Path):
    client, _ = _client(tmp_path)
    raw = _minimal_glb_bytes()
    bad = b"XXXX" + raw[4:]
    res = client.post(
        "/api/ecommerce-scenes/props/upload-glb",
        headers={"X-Tenant-Id": "sonaqueen-home"},
        json={"filename": "x.glb", "dataBase64": _b64(bad)},
    )
    assert res.status_code == 422
    assert "magic" in res.json()["detail"]
    assert "Invalid base64" not in res.json()["detail"]


def test_upload_rejects_declared_length_mismatch(tmp_path: Path):
    client, _ = _client(tmp_path)
    raw = _minimal_glb_bytes()
    wrong_len = raw[:8] + struct.pack("<I", len(raw) + 99) + raw[12:]
    res = client.post(
        "/api/ecommerce-scenes/props/upload-glb",
        headers={"X-Tenant-Id": "sonaqueen-home"},
        json={"filename": "x.glb", "dataBase64": _b64(wrong_len)},
    )
    assert res.status_code == 422
    assert "長度" in res.json()["detail"]


def test_upload_rejects_over_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FOX3D_ECOMMERCE_GLB_MAX_BYTES", "64")
    client, _ = _client(tmp_path)
    raw = _minimal_glb_bytes()
    res = client.post(
        "/api/ecommerce-scenes/props/upload-glb",
        headers={"X-Tenant-Id": "sonaqueen-home"},
        json={"filename": "x.glb", "dataBase64": _b64(raw)},
    )
    assert res.status_code == 422
    assert "上限" in res.json()["detail"]


def test_upload_rejects_invalid_base64(tmp_path: Path):
    client, _ = _client(tmp_path)
    res = client.post(
        "/api/ecommerce-scenes/props/upload-glb",
        headers={"X-Tenant-Id": "sonaqueen-home"},
        json={"filename": "x.glb", "dataBase64": "!!!not-base64!!!"},
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "base64" in detail
    assert "Error" not in detail


def test_upload_tenant_isolation(tmp_path: Path):
    client, root = _client(tmp_path)
    raw = _minimal_glb_bytes()
    a = client.post(
        "/api/ecommerce-scenes/props/upload-glb",
        headers={"X-Tenant-Id": "tenant-alpha"},
        json={"filename": "chair.glb", "dataBase64": _b64(raw)},
    )
    b = client.post(
        "/api/ecommerce-scenes/props/upload-glb",
        headers={"X-Tenant-Id": "tenant-beta"},
        json={"filename": "chair.glb", "dataBase64": _b64(raw)},
    )
    assert a.status_code == 201 and b.status_code == 201
    path_a = root / a.json()["glbPath"]
    path_b = root / b.json()["glbPath"]
    assert path_a != path_b
    assert "tenant-alpha" in path_a.as_posix()
    assert "tenant-beta" in path_b.as_posix()
    assert path_a.read_bytes() == raw
    assert path_b.read_bytes() == raw


def test_validate_glb_rejects_header_only_container():
    raw = struct.pack("<4sII", b"glTF", 2, 12)
    with pytest.raises(ValueError, match="JSON chunk"):
        validate_glb_binary(raw)


def test_validate_glb_rejects_missing_json_chunk():
    chunk_len = 8
    total = 12 + 8 + chunk_len
    raw = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", chunk_len, 0x004E4942) + b"\x00" * chunk_len
    with pytest.raises(ValueError, match="JSON"):
        validate_glb_binary(raw)


def test_validate_glb_rejects_truncated_json_chunk():
    chunk_len = 32
    payload = b" " * 8
    total = 12 + 8 + len(payload)
    raw = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", chunk_len, 0x4E4F534A) + payload
    with pytest.raises(ValueError, match="JSON chunk"):
        validate_glb_binary(raw)


def test_validate_glb_rejects_invalid_json_payload():
    chunk_len = 16
    payload = b"{" + b" " * (chunk_len - 1)
    total = 12 + 8 + chunk_len
    raw = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", chunk_len, 0x4E4F534A) + payload
    with pytest.raises(ValueError, match="JSON"):
        validate_glb_binary(raw)


def test_resolve_scene_glb_paths_rejects_other_tenant_absolute_path(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    root = Path(plat.root).resolve()
    victim = root / "ecommerce-scene-studio/tenant-beta/glb-props/glb_chair_x.glb"
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_bytes(_minimal_glb_bytes())
    scene = {"boxes": [{"name": "Prop1_Custom_Box", "glbPath": str(victim.resolve())}]}
    with pytest.raises(ValueError, match="超出租戶允許範圍"):
        resolve_scene_glb_paths_for_blender(scene, platform_root=root, tenant_id="tenant-alpha")


def test_resolve_scene_glb_paths_rejects_other_tenant_relative_path(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    root = Path(plat.root).resolve()
    rel = "ecommerce-scene-studio/tenant-beta/glb-props/glb_chair_x.glb"
    glb_file = root / rel
    glb_file.parent.mkdir(parents=True, exist_ok=True)
    glb_file.write_bytes(_minimal_glb_bytes())
    scene = {"boxes": [{"name": "Prop1_Custom_Box", "glbPath": rel}]}
    with pytest.raises(ValueError, match="超出租戶允許範圍"):
        resolve_scene_glb_paths_for_blender(scene, platform_root=root, tenant_id="tenant-alpha")


def test_resolve_scene_glb_paths_maps_upload_ref_to_absolute(tmp_path: Path):
    plat = Platform(tmp_path / "data", mock_blender=True)
    root = Path(plat.root).resolve()
    rel = "ecommerce-scene-studio/tenant-alpha/glb-props/glb_chair_x.glb"
    glb_file = root / rel
    glb_file.parent.mkdir(parents=True, exist_ok=True)
    glb_file.write_bytes(_minimal_glb_bytes())
    scene = {"boxes": [{"name": "Prop1_Custom_Box", "glbPath": rel}]}
    resolved = resolve_scene_glb_paths_for_blender(scene, platform_root=root, tenant_id="tenant-alpha")
    abs_path = resolved["boxes"][0]["glbPath"]
    assert Path(abs_path).is_absolute() and Path(abs_path) == glb_file.resolve()


class _JobCapturingRuntime:
    blender_bin = "fake"

    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def available(self) -> bool:
        return True

    def run_job(self, job: dict) -> dict:
        self.jobs.append(job)
        work = Path(job["workDir"])
        work.mkdir(parents=True, exist_ok=True)
        (work / "beauty.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        (work / "product_cutout.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        return {"status": "succeeded", "outputs": {}, "renderTimeSec": 0.01, "device": "CPU", "blenderVersion": "local"}


def test_uploaded_glb_path_reaches_blender_job_as_absolute(tmp_path: Path):
    runtime = _JobCapturingRuntime()
    plat = Platform(tmp_path / "data", mock_blender=False)
    plat.runtime = runtime  # type: ignore[assignment]
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "sonaqueen-home"}
    raw = _minimal_glb_bytes()
    upload = client.post(
        "/api/ecommerce-scenes/props/upload-glb",
        headers=headers,
        json={"filename": "stool.glb", "dataBase64": _b64(raw)},
    )
    assert upload.status_code == 201
    rel_glb = upload.json()["glbPath"]
    scene_id = "SCENE_GLB_E2E"
    save = client.post(
        "/api/ecommerce-scenes/scenes",
        headers=headers,
        json={
            "id": scene_id,
            "name": "GLB e2e",
            "props": [
                {
                    "type": "CUSTOM_BOX",
                    "label": "stool",
                    "x": 1.0,
                    "y": 0.5,
                    "z": 0.0,
                    "widthM": 0.4,
                    "depthM": 0.4,
                    "heightM": 0.5,
                    "glbPath": rel_glb,
                }
            ],
        },
    )
    assert save.status_code == 201
    batch = client.post(
        "/api/ecommerce-scenes/batches",
        headers=headers,
        json={
            "cabinet": CABINET_PRESETS[0],
            "sceneIds": [scene_id],
            "themeIds": ["THEME_NORDIC_OAK"],
            "views": ["FRONT"],
            "aiEngine": "builtin",
            "blenderEngine": "local",
        },
    )
    assert batch.status_code == 202
    batch_id = batch.json()["batchId"]
    deadline = time.time() + 30.0
    while time.time() < deadline:
        doc = client.get(f"/api/ecommerce-scenes/batches/{batch_id}", headers=headers).json()
        if doc.get("state") in ("completed", "failed", "interrupted"):
            break
        time.sleep(0.05)
    assert doc["state"] == "completed", doc
    assert runtime.jobs, "expected local Blender job"
    boxes = runtime.jobs[0]["engineering"]["sceneDefinition"]["boxes"]
    glb_paths = [b["glbPath"] for b in boxes if b.get("glbPath")]
    assert glb_paths
    for path in glb_paths:
        p = Path(path)
        assert p.is_absolute() and p.is_file()
        assert "glb-props" in p.as_posix()
