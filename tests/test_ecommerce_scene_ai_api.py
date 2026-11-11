"""API tests for ai-local-models, ai-layout, polyhaven-thumb, and ai-prompt error surfaces."""
from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.ai_scene_layout import AiLayoutError
from fox3d.ecommerce_scene_api import ecommerce_scene_router
from fox3d.ecommerce_scene_studio import EcommerceSceneStore


class _UrlResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            return self._body
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def store(tmp_path):
    with patch("fox3d.ecommerce_scene_studio.ensure_pbr_texture_assets"):
        return EcommerceSceneStore(SimpleNamespace(root=tmp_path, mock_blender=True))


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(ecommerce_scene_router(lambda: store.platform))
    with patch("fox3d.ecommerce_scene_api.EcommerceSceneStore", return_value=store), patch(
        "fox3d.ai_scene_layout.load_settings",
        return_value={"localBaseUrl": "http://127.0.0.1:11434/v1", "localModel": "test"},
    ):
        yield TestClient(app)


def scene_with_glb(path: str) -> dict:
    return {"id": "custom", "name": "Test", "props": [{"type": "CUSTOM_BOX", "glbPath": path}]}


def test_ai_local_models_lists_string_ids_deduped(client):
    payload = {
        "data": [
            {"id": "qwen2.5:7b"},
            {"id": "qwen2.5:7b"},
            {"id": 42},
            {"id": "llama3"},
            {"name": "no-id"},
        ]
    }

    def fake_urlopen(url, timeout=5):
        assert url.endswith("/models")
        return _UrlResp(json.dumps(payload).encode("utf-8"))

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        r = client.get("/api/ecommerce-scenes/ai-local-models")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["models"] == ["qwen2.5:7b", "llama3"]


def test_ai_local_models_connection_failure_hides_internals(client):
    secret = "http://192.168.66.99:11434/v1 connection refused"

    def fake_urlopen(url, timeout=5):
        raise urllib.error.URLError(secret)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        r = client.get("/api/ecommerce-scenes/ai-local-models")
    body = r.json()
    assert body["ok"] is False
    assert body["models"] == []
    assert "192.168" not in body.get("error", "")
    assert "connection refused" not in body.get("error", "")
    assert "連不到本機模型伺服器" in body["error"]
    assert "URLError" in body["error"]


def test_ai_local_models_oversized_response(client):
    huge = b"x" * (1024 * 1024 + 1)

    def fake_urlopen(url, timeout=5):
        return _UrlResp(huge)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        r = client.get("/api/ecommerce-scenes/ai-local-models")
    body = r.json()
    assert body["ok"] is False
    assert "回應過大" in body["error"]


def test_ai_local_models_non_json(client):
    def fake_urlopen(url, timeout=5):
        return _UrlResp(b"not-json{{{")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        r = client.get("/api/ecommerce-scenes/ai-local-models")
    body = r.json()
    assert body["ok"] is False
    assert "不是有效的 JSON" in body["error"]


def test_ai_layout_strips_unsafe_glb_path(client, store):
    generated = scene_with_glb("/etc/passwd")
    with patch("fox3d.ai_scene_layout.generate_ai_layout", return_value=generated):
        r = client.post(
            "/api/ecommerce-scenes/ai-layout",
            json={"prompt": "room"},
            headers={"X-Tenant-Id": "alice"},
        )
    assert r.status_code == 200
    data = r.json()
    assert "glbPath" not in data["props"][0]
    assert data["warnings"]


def test_ai_layout_ai_layout_error_returns_422(client):
    with patch("fox3d.ai_scene_layout.generate_ai_layout", side_effect=AiLayoutError("請先輸入想要的空間風格")):
        r = client.post(
            "/api/ecommerce-scenes/ai-layout",
            json={"prompt": ""},
            headers={"X-Tenant-Id": "alice"},
        )
    assert r.status_code == 422
    assert r.json()["detail"] == "請先輸入想要的空間風格"


def test_polyhaven_thumb_traversal_and_missing_are_404(client):
    assert client.get("/api/ecommerce-scenes/polyhaven-thumb/../x").status_code == 404
    assert client.get("/api/ecommerce-scenes/polyhaven-thumb/does_not_exist_xyz").status_code == 404


def test_ai_prompt_invalid_cabinet_422_without_exception_text(client):
    r = client.post(
        "/api/ecommerce-scenes/ai-prompt",
        json={
            "cabinet": {"columns": [], "themeId": "THEME_NORDIC_OAK"},
            "scene": {"id": "custom", "props": []},
            "aiStyleId": "AI_JAPANDI_WABI_SABI",
        },
        headers={"X-Tenant-Id": "alice"},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail == "櫃體設定無效"
    assert "validation" not in detail.lower()
