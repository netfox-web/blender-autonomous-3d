"""Offline unit tests for fox3d.ai_scene_layout (sanitize, JSON extract, settings, local LLM mock)."""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from fox3d.ai_scene_layout import (
    AiLayoutError,
    LIGHTING_PRESETS,
    _call_local_llm,
    _extract_json_object,
    load_settings,
    sanitize_layout,
    save_settings,
)


class _Resp:
    def __init__(self, payload: dict | bytes):
        self._payload = payload

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def glb_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    glb = tmp_path / "mock.gltf"
    glb.write_text("{}", encoding="utf-8")

    def _fake(_asset_id: str) -> str:
        return str(glb)

    monkeypatch.setattr("fox3d.ai_scene_layout._ph_glb", _fake)
    return glb


def _sofa_prop(**kw) -> dict:
    base = {
        "type": "SOFA",
        "assetId": "Sofa_01",
        "label": "沙發",
        "x": 0.0,
        "y": 0.5,
        "z": 0.0,
        "widthM": 1.9,
        "depthM": 0.9,
        "heightM": 0.85,
        "rotationDeg": 0,
    }
    base.update(kw)
    return base


def _minimal_raw(*, props: list | None = None, **overrides) -> dict:
    raw = {
        "name": "測試場景",
        "category": "客廳空間",
        "roomWidthM": 5.6,
        "roomDepthM": 4.2,
        "wallColorHex": "#d6cfc2",
        "sideWallColorHex": "#c8c1b4",
        "floorColorHex": "#8a6f55",
        "lightingPreset": "NORDIC_BRIGHT",
        "productX": 1.0,
        "rationale": "理由",
        "props": props if props is not None else [],
    }
    raw.update(overrides)
    return raw


# --- sanitize_layout: clamps ---


def test_sanitize_clamps_room_dimensions():
    out = sanitize_layout(_minimal_raw(roomWidthM=99, roomDepthM=-1), cabinet_w=1.2, cabinet_d=0.5)
    assert out["roomWidthM"] == 8.0
    assert out["roomDepthM"] == 3.0


def test_sanitize_clamps_product_x_within_cabinet_margin():
    raw = _minimal_raw(roomWidthM=5.6, productX=50.0)
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    half = out["roomWidthM"] / 2
    lo = -half + 1.0 / 2 + 0.3
    hi = half - 1.0 / 2 - 0.3
    assert lo <= out["productPose"]["x"] <= hi + 1e-9


def test_sanitize_clamps_prop_x_y():
    out = sanitize_layout(
        _minimal_raw(
            roomWidthM=5.6,
            props=[{"type": "RUG", "label": "地毯", "x": 99, "y": 99, "widthM": 2.0, "depthM": 1.5}],
        ),
        cabinet_w=1.0,
        cabinet_d=0.4,
    )
    prop = out["props"][0]
    half = out["roomWidthM"] / 2
    assert prop["x"] == pytest.approx(half - 0.25)
    assert prop["y"] == pytest.approx(1.42)


# --- sanitize_layout: catalog / drops ---


def test_sanitize_drops_unknown_asset_id():
    raw = _minimal_raw(props=[_sofa_prop(assetId="not_in_catalog")])
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert out["props"] == []
    assert any("未知素材" in d for d in out["aiDropped"])


def test_sanitize_drops_missing_asset_id_for_floor_furniture():
    raw = _minimal_raw(props=[{"type": "SOFA", "label": "無素材", "x": 0, "y": 0.5}])
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert out["props"] == []
    assert any("缺少 assetId" in d for d in out["aiDropped"])


def test_sanitize_drops_asset_when_glb_missing_on_disk(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("fox3d.ai_scene_layout._ph_glb", lambda _aid: "/no/such/file.gltf")
    raw = _minimal_raw(props=[_sofa_prop()])
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert out["props"] == []
    assert any("尚未下載" in d for d in out["aiDropped"])


# --- sanitize_layout: wall types & colors ---


def test_sanitize_wall_art_fixed_wall_y():
    raw = _minimal_raw(
        props=[
            {
                "type": "WALL_ART",
                "label": "掛畫",
                "x": 0.5,
                "y": 0.2,
                "z": 1.4,
                "widthM": 0.8,
                "depthM": 0.05,
                "heightM": 0.85,
            }
        ]
    )
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert out["props"][0]["y"] == 1.52


def test_sanitize_invalid_hex_colors_use_defaults():
    raw = _minimal_raw(
        wallColorHex="red",
        sideWallColorHex="#gggggg",
        floorColorHex="#12345",
        props=[
            {
                "type": "RUG",
                "label": "地毯",
                "x": 0,
                "y": 0.3,
                "widthM": 2,
                "depthM": 1.5,
                "colorHex": "nope",
                "accentColorHex": "#zzz",
            }
        ],
    )
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert out["wallColorHex"] == "#d6cfc2"
    assert out["sideWallColorHex"] == "#c8c1b4"
    assert out["floorColorHex"] == "#8a6f55"
    assert out["props"][0]["colorHex"] == "#c4b6a6"
    assert out["props"][0]["accentColorHex"] == "#8c7a6b"


def test_sanitize_preserves_valid_hex_lowercase():
    raw = _minimal_raw(wallColorHex="#AABBCC", props=[])
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert out["wallColorHex"] == "#aabbcc"


def test_sanitize_unknown_lighting_preset_falls_back():
    preset = next(iter(LIGHTING_PRESETS))
    raw = _minimal_raw(lightingPreset=preset, props=[])
    assert sanitize_layout(raw, 1.0, 0.4)["lightingPreset"] == preset
    raw_bad = _minimal_raw(lightingPreset="NOT_A_PRESET", props=[])
    assert sanitize_layout(raw_bad, 1.0, 0.4)["lightingPreset"] == "NORDIC_BRIGHT"


# --- sanitize_layout: collision ---


def test_sanitize_nudges_sofa_off_product_footprint(glb_on_disk: Path):
    raw = _minimal_raw(productX=1.0, props=[_sofa_prop(x=1.0, y=1.05)])
    out = sanitize_layout(raw, cabinet_w=1.2, cabinet_d=0.6)
    assert len(out["props"]) == 1
    assert out["props"][0]["x"] < 1.0
    assert not out["aiDropped"]


def test_sanitize_drops_furniture_that_cannot_escape_collision(glb_on_disk: Path):
    """In a narrow room, the second sofa cannot nudge away from the first."""
    raw = _minimal_raw(
        roomWidthM=3.6,
        productX=0.0,
        props=[
            _sofa_prop(x=-0.5, y=1.05, label="沙發甲"),
            _sofa_prop(x=-0.48, y=1.05, label="沙發乙"),
        ],
    )
    out = sanitize_layout(raw, cabinet_w=1.2, cabinet_d=0.6)
    assert len(out["props"]) == 1
    assert any("位置衝突" in d for d in out["aiDropped"])


def test_sanitize_rug_skips_collision_resolution(glb_on_disk: Path):
    raw = _minimal_raw(
        props=[
            _sofa_prop(x=0.0, y=0.4),
            {"type": "RUG", "label": "地毯", "x": 0.0, "y": 0.4, "widthM": 2.5, "depthM": 1.6},
        ]
    )
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert len(out["props"]) == 2
    rug = next(p for p in out["props"] if p["type"] == "RUG")
    assert rug["x"] == 0.0 and rug["y"] == 0.4


def test_sanitize_elevated_props_skip_floor_collision(glb_on_disk: Path):
    raw = _minimal_raw(
        props=[
            _sofa_prop(x=0.0, y=0.4),
            {
                "type": "SIDE_TABLE",
                "assetId": "side_table_01",
                "label": "桌上物",
                "x": 0.0,
                "y": 0.4,
                "z": 0.55,
                "widthM": 0.2,
                "depthM": 0.2,
                "heightM": 0.35,
            },
        ]
    )
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert len(out["props"]) == 2


def test_sanitize_keeps_valid_asset_with_glb(glb_on_disk: Path):
    raw = _minimal_raw(props=[_sofa_prop(x=-1.2, y=0.5)])
    out = sanitize_layout(raw, cabinet_w=1.0, cabinet_d=0.4)
    assert len(out["props"]) == 1
    assert out["props"][0]["polyhavenId"] == "Sofa_01"
    assert out["props"][0]["glbPath"] == str(glb_on_disk)


# --- _extract_json_object ---


def test_extract_json_plain_object():
    assert _extract_json_object('{"a": 1, "b": "two"}') == {"a": 1, "b": "two"}


def test_extract_json_markdown_fence():
    text = "說明如下：\n```json\n{\"name\": \"場景\", \"n\": 3}\n```\n完"
    assert _extract_json_object(text) == {"name": "場景", "n": 3}


def test_extract_json_with_leading_trailing_noise():
    text = "Sure! Here you go:\n{\"ok\": true}\nThanks."
    assert _extract_json_object(text) == {"ok": True}


def test_extract_json_nested_braces_and_string_with_braces():
    text = 'noise {"outer": {"inner": 1}, "msg": "brace {not json}"} tail'
    assert _extract_json_object(text) == {"outer": {"inner": 1}, "msg": "brace {not json}"}


def test_extract_json_raises_when_no_object():
    with pytest.raises(AiLayoutError, match="不是有效的 JSON"):
        _extract_json_object("沒有任何大括號")


# --- load_settings / save_settings ---


def test_load_settings_defaults_without_file(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FOX3D_LOCAL_LLM_URL", raising=False)
    s = load_settings(None)
    assert s["provider"] == "local"
    assert s["aiVariants"] == 2
    assert s["aiUpsample"] is False
    assert s["aiPinProduct"] is True
    assert s["promptPolish"] is False
    assert s["blenderEngine"] == "auto"


def test_load_settings_reads_file_and_parses_bool_strings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "ai_settings.json").write_text(
        json.dumps(
            {
                "provider": "local",
                "aiUpsample": "yes",
                "aiPinProduct": "false",
                "promptPolish": "1",
                "aiVariants": "3",
                "localBaseUrl": "http://127.0.0.1:11434/v1/",
            }
        ),
        encoding="utf-8",
    )
    s = load_settings(tmp_path)
    assert s["provider"] == "local"
    assert s["aiUpsample"] is True
    assert s["aiPinProduct"] is False
    assert s["promptPolish"] is True
    assert s["aiVariants"] == 3
    assert s["localBaseUrl"] == "http://127.0.0.1:11434/v1"


def test_save_settings_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    save_settings(
        tmp_path,
        {
            "provider": "local",
            "localModel": "qwen2.5:7b",
            "aiUpsample": "on",
            "aiPinProduct": 0,
            "aiVariants": 4,
        },
    )
    path = tmp_path / "ai_settings.json"
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["provider"] == "local"
    assert on_disk["aiVariants"] == 4
    merged = load_settings(tmp_path)
    assert merged["aiUpsample"] is True
    assert merged["aiPinProduct"] is False
    assert merged["localModel"] == "qwen2.5:7b"


def test_load_settings_clamps_ai_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "ai_settings.json").write_text(json.dumps({"aiVariants": 99}), encoding="utf-8")
    assert load_settings(tmp_path)["aiVariants"] == 4
    (tmp_path / "ai_settings.json").write_text(json.dumps({"aiVariants": "not-a-number"}), encoding="utf-8")
    assert load_settings(tmp_path)["aiVariants"] == 2


# --- _call_local_llm (mocked urlopen) ---


def test_call_local_llm_parses_mock_response(monkeypatch: pytest.MonkeyPatch):
    payload = {"choices": [{"message": {"content": '{"name":"本機場景","props":[]}'}}]}

    def _open(req, timeout=None):
        assert req.full_url.endswith("/chat/completions")
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "test-model"
        assert body["response_format"] == {"type": "json_object"}
        return _Resp(payload)

    monkeypatch.setattr("fox3d.ai_scene_layout.urllib.request.urlopen", _open)
    out = _call_local_llm("user", "http://127.0.0.1:11434/v1", "test-model")
    assert out["name"] == "本機場景"


def test_call_local_llm_requires_model_name():
    with pytest.raises(AiLayoutError, match="本機模型"):
        _call_local_llm("user", "http://127.0.0.1:11434/v1", "")


def test_call_local_llm_http_404(monkeypatch: pytest.MonkeyPatch):
    def _open(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "missing", {}, io.BytesIO(b'{"error":"no model"}'))

    monkeypatch.setattr("fox3d.ai_scene_layout.urllib.request.urlopen", _open)
    with pytest.raises(AiLayoutError, match="找不到模型"):
        _call_local_llm("user", "http://127.0.0.1:11434/v1", "ghost")


def test_call_local_llm_connection_error(monkeypatch: pytest.MonkeyPatch):
    def _open(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("fox3d.ai_scene_layout.urllib.request.urlopen", _open)
    with pytest.raises(AiLayoutError, match="連不到本機"):
        _call_local_llm("user", "http://127.0.0.1:11434/v1", "m")
