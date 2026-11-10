"""Tests for POST /api/ecommerce-scenes/props/upload-glb validation and tenant isolation."""
from __future__ import annotations

import base64
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
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
