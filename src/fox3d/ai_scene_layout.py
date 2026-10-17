"""Claude-powered room layout planner for the E-Commerce 3D Scene Studio.

Given a one-sentence style brief plus the cabinet footprint, ask Claude (tool use, forced JSON schema) to
choose furniture from the built-in Poly Haven library and lay it out in the room. The model output is never
trusted: every value is clamped, asset ids are checked against the catalog, glTF paths are resolved locally
and colliding floor furniture is nudged apart or dropped.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from fox3d.ecommerce_scene_studio import LIGHTING_PRESETS, PROP_CATALOG, _ph_glb
from fox3d.photoreal_assets import POLYHAVEN_CURATED_MODELS

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-5"

# Natural (width, depth, height) in metres for each library model, used as the size baseline.
ASSET_SIZES: dict[str, tuple[float, float, float]] = {
    "Sofa_01": (1.9, 0.9, 0.85), "sofa_02": (2.0, 0.95, 0.8), "sofa_03": (2.2, 0.95, 0.85),
    "mid_century_lounge_chair": (0.8, 0.85, 0.85), "modern_arm_chair_01": (0.8, 0.85, 0.85),
    "GreenChair_01": (0.85, 0.85, 0.95), "ArmChair_01": (0.85, 0.85, 0.9), "Ottoman_01": (0.7, 0.5, 0.42),
    "vintage_day_bed": (1.0, 2.0, 0.85), "modern_coffee_table_01": (1.0, 0.6, 0.42),
    "modern_coffee_table_02": (1.0, 0.6, 0.4), "coffee_table_round_01": (0.85, 0.85, 0.42),
    "round_wooden_table_01": (0.9, 0.9, 0.75), "side_table_01": (0.45, 0.45, 0.55),
    "ClassicNightstand_01": (0.5, 0.45, 0.55), "WoodenTable_01": (1.6, 0.75, 0.76),
    "ClassicConsole_01": (1.2, 0.4, 0.82), "potted_plant_01": (0.5, 0.5, 1.1), "potted_plant_02": (0.45, 0.45, 0.95),
    "potted_plant_04": (0.3, 0.3, 0.4), "modern_wooden_cabinet": (1.4, 0.45, 0.8), "drawer_cabinet": (0.9, 0.45, 0.8),
    "wooden_display_shelves_01": (0.9, 0.35, 1.6), "dining_chair_02": (0.5, 0.5, 0.9),
    "ceramic_vase_01": (0.2, 0.2, 0.35), "ceramic_vase_03": (0.2, 0.2, 0.4), "standing_picture_frame_01": (0.2, 0.05, 0.25),
}

# Procedural (non-glTF) prop types the planner may also use.
PROCEDURAL_TYPES = ("RUG", "WALL_ART", "FLOOR_LAMP", "WINDOW_FRAME", "SHEER_CURTAIN")
WALL_TYPES = ("WALL_ART", "WINDOW_FRAME", "SHEER_CURTAIN")
BACK_WALL_Y = 1.65
PLACE_Y_MAX = 1.42
PLACE_Y_MIN = -1.3


class AiLayoutError(ValueError):
    pass


# Fox AI Gateway on netfox-home is an Ollama drop-in with an OpenAI-compatible /v1 (qwen3.8:27b, qwen3:8b, qwen2.5vl:7b…).
# Override with FOX3D_LOCAL_LLM_URL / FOX3D_LOCAL_LLM_MODEL (e.g. a laptop running Ollama at http://127.0.0.1:11434/v1).
DEFAULT_LOCAL_URL = (os.environ.get("FOX3D_LOCAL_LLM_URL") or "http://192.168.66.101:11434/v1").strip().rstrip("/")
DEFAULT_LOCAL_MODEL = (os.environ.get("FOX3D_LOCAL_LLM_MODEL") or "qwen3.8:27b").strip()
IMAGE_ENGINES = ("fleet_flux3", "builtin", "off")
AI_VARIATIONS = ("faithful", "creative")
DEFAULT_IMAGE_ENGINE = "fleet_flux3"
MAX_AI_VARIANTS = 4


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _settings_file(settings_dir: Path) -> Path:
    return Path(settings_dir) / "ai_settings.json"


def load_settings(settings_dir: Path | None = None) -> dict[str, Any]:
    """Return persisted AI settings merged with defaults (the API key is never returned to the browser)."""
    data: dict[str, Any] = {}
    if settings_dir and _settings_file(settings_dir).exists():
        try:
            data = json.loads(_settings_file(settings_dir).read_text(encoding="utf-8"))
        except Exception:
            data = {}
    env_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    api_key = env_key or str(data.get("anthropicApiKey") or "").strip()
    # 地端優先：沒有 Anthropic 金鑰就用公司閘道的本機模型
    provider = data.get("provider") if data.get("provider") in ("anthropic", "local") else ("anthropic" if api_key else "local")
    try:
        variants = max(1, min(MAX_AI_VARIANTS, int(data.get("aiVariants") or 2)))
    except (TypeError, ValueError):
        variants = 2
    return {
        "provider": provider,
        "anthropicApiKey": api_key,
        "localBaseUrl": str(data.get("localBaseUrl") or DEFAULT_LOCAL_URL).strip().rstrip("/"),
        "localModel": str(data.get("localModel") or DEFAULT_LOCAL_MODEL).strip(),
        # 地端 AI 實景（GPU 艦隊 image_flux3）
        "imageEngine": data.get("imageEngine") if data.get("imageEngine") in IMAGE_ENGINES else DEFAULT_IMAGE_ENGINE,
        "fleetApiUrl": str(data.get("fleetApiUrl") or os.environ.get("FLEET_API_URL") or "").strip().rstrip("/"),
        "fleetToken": str(data.get("fleetToken") or "").strip(),
        "publicBaseUrl": str(data.get("publicBaseUrl") or os.environ.get("FOX3D_PUBLIC_BASE_URL") or "").strip().rstrip("/"),
        "aiVariants": variants,
        "aiVariation": data.get("aiVariation") if data.get("aiVariation") in AI_VARIATIONS else "faithful",
        "aiUpsample": _as_bool(data.get("aiUpsample"), True),
        "promptPolish": _as_bool(data.get("promptPolish"), False),
    }


def save_settings(settings_dir: Path, updates: dict[str, Any]) -> None:
    current: dict[str, Any] = {}
    if _settings_file(settings_dir).exists():
        try:
            current = json.loads(_settings_file(settings_dir).read_text(encoding="utf-8"))
        except Exception:
            current = {}
    for k in ("provider", "anthropicApiKey", "localBaseUrl", "localModel", "imageEngine", "fleetApiUrl", "fleetToken", "publicBaseUrl", "aiVariation"):
        if k in updates and updates[k] is not None:
            current[k] = str(updates[k]).strip()
    if updates.get("aiVariants") is not None:
        try:
            current["aiVariants"] = max(1, min(MAX_AI_VARIANTS, int(updates["aiVariants"])))
        except (TypeError, ValueError):
            pass
    for k in ("aiUpsample", "promptPolish"):
        if k in updates and updates[k] is not None:
            current[k] = _as_bool(updates[k], True)
    settings_dir.mkdir(parents=True, exist_ok=True)
    _settings_file(settings_dir).write_text(json.dumps(current), encoding="utf-8")


def load_api_key(settings_dir: Path | None = None) -> str:
    return load_settings(settings_dir)["anthropicApiKey"]


def save_api_key(settings_dir: Path, key: str) -> None:
    save_settings(settings_dir, {"anthropicApiKey": key})


def _catalog_for_prompt() -> list[dict[str, Any]]:
    rows = []
    for aid, cfg in POLYHAVEN_CURATED_MODELS.items():
        if aid not in ASSET_SIZES:
            continue
        w, d, h = ASSET_SIZES[aid]
        rows.append({"assetId": aid, "type": cfg.get("propType"), "name": cfg.get("shortLabel"), "sizeM": [w, d, h]})
    return rows


def _tool_schema() -> dict[str, Any]:
    num = {"type": "number"}
    return {
        "name": "submit_room_layout",
        "description": "Submit the designed room: styling plus the list of furniture placements.",
        "input_schema": {
            "type": "object",
            "required": ["name", "category", "roomWidthM", "roomDepthM", "wallColorHex", "sideWallColorHex", "floorColorHex",
                         "lightingPreset", "productX", "props", "rationale"],
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string", "description": "e.g. 客廳空間 / 臥室空間 / 書房工作室 / 餐廚空間 / 玄關走廊"},
                "roomWidthM": num, "roomDepthM": num,
                "wallColorHex": {"type": "string"}, "sideWallColorHex": {"type": "string"}, "floorColorHex": {"type": "string"},
                "lightingPreset": {"type": "string", "enum": list(LIGHTING_PRESETS.keys())},
                "productX": {"type": "number", "description": "X position of the cabinet centre (metres)."},
                "rationale": {"type": "string", "description": "2-3 sentences in Traditional Chinese explaining the design."},
                "props": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["type", "label", "x", "y"],
                        "properties": {
                            "type": {"type": "string", "enum": sorted({c.get("propType") for c in POLYHAVEN_CURATED_MODELS.values() if c.get("propType")} | set(PROCEDURAL_TYPES))},
                            "assetId": {"type": "string", "description": "Library model id; omit for RUG/WALL_ART/FLOOR_LAMP/WINDOW_FRAME/SHEER_CURTAIN."},
                            "label": {"type": "string", "description": "Short Traditional Chinese label."},
                            "x": num, "y": num, "z": {"type": "number", "description": "Height of the base above floor; >0 only for items resting on furniture or wall-mounted."},
                            "widthM": num, "depthM": num, "heightM": num,
                            "rotationDeg": {"type": "number"},
                            "colorHex": {"type": "string"}, "accentColorHex": {"type": "string"},
                        },
                    },
                },
            },
        },
    }


SYSTEM_PROMPT = """你是專業的室內設計師與電商場景造型師。使用者要為一件「組合櫃」商品拍電商情境圖，請替他設計房間並擺放家具。

座標系（公尺）：
- 房間水平置中，x 範圍是 -房寬/2 到 +房寬/2；背牆在 y=1.65，鏡頭從 -y 方向看向背牆。可擺放的 y 範圍約 -1.3 到 1.42，靠背牆的家具 y 約 0.9~1.3。
- 家具的「背面」在 +y，正面朝向 -y（鏡頭）。rotationDeg=0 時沙發/椅子面向鏡頭；要面對面坐的椅子放在前方並設 rotationDeg=180；斜放的單椅可用 ±25~40 度。
- 組合櫃商品（主角）的中心位置是 (productX, 1.15)，貼背牆，請替它留出完整空間，不要被其他家具擋住或重疊，也要讓它在畫面上明顯。
- 其他家具請盡量集中在商品附近，形成一組好看的構圖，不要把房間排得太滿或太空；通常 4~8 件即可。
- 牆面物件 (WALL_ART/WINDOW_FRAME/SHEER_CURTAIN) y 設在 1.52，z 為離地高度（掛畫約 1.4）。
- 擺在家具上的小物（花瓶、相框、小盆栽）z 要等於該家具高度，x/y 對齊該家具。
- 家具請使用素材庫的 assetId，尺寸以素材庫 sizeM 為準，最多放大或縮小 25%。地毯 (RUG) 可自訂尺寸，約 1.8~3 公尺寬。
- 配色要和諧並襯托組合櫃；牆、地板顏色用 #RRGGBB。
務必呼叫 submit_room_layout 工具回覆，不要輸出其他文字。"""


def _hex(v: Any, default: str) -> str:
    s = str(v or "").strip()
    if len(s) == 7 and s[0] == "#":
        try:
            int(s[1:], 16)
            return s.lower()
        except ValueError:
            pass
    return default


def _num(v: Any, default: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = default
    return max(lo, min(hi, x))


def _footprint(p: dict[str, Any]) -> tuple[float, float, float, float]:
    w, d = float(p["widthM"]), float(p["depthM"])
    if round(float(p.get("rotationDeg") or 0)) % 180 == 90:
        w, d = d, w
    return p["x"] - w / 2, p["x"] + w / 2, p["y"] - d / 2, p["y"] + d / 2


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], pad: float = 0.04) -> bool:
    return a[0] < b[1] - pad and a[1] > b[0] + pad and a[2] < b[3] - pad and a[3] > b[2] + pad


def sanitize_layout(raw: dict[str, Any], cabinet_w: float, cabinet_d: float) -> dict[str, Any]:
    rw = _num(raw.get("roomWidthM"), 5.6, 3.6, 8.0)
    rd = _num(raw.get("roomDepthM"), 4.2, 3.0, 6.0)
    half = rw / 2
    prod_x = _num(raw.get("productX"), half * 0.45, -half + cabinet_w / 2 + 0.3, half - cabinet_w / 2 - 0.3)
    product_box = (prod_x - cabinet_w / 2, prod_x + cabinet_w / 2, 1.15 - cabinet_d / 2 - 0.1, 1.15 + cabinet_d / 2)
    catalog_by_type = {c["type"]: c for c in PROP_CATALOG}

    props: list[dict[str, Any]] = []
    placed_floor: list[tuple[float, float, float, float]] = []
    dropped: list[str] = []
    for idx, item in enumerate(raw.get("props") or [], start=1):
        if not isinstance(item, dict):
            continue
        ptype = str(item.get("type") or "").upper()
        aid = str(item.get("assetId") or "").strip()
        label = str(item.get("label") or ptype)[:40]
        if aid:
            if aid not in ASSET_SIZES:
                dropped.append(f"{label}（未知素材 {aid}）")
                continue
            base_w, base_d, base_h = ASSET_SIZES[aid]
            ptype = str(POLYHAVEN_CURATED_MODELS[aid].get("propType") or ptype)
            w = _num(item.get("widthM"), base_w, base_w * 0.75, base_w * 1.25)
            d = _num(item.get("depthM"), base_d, base_d * 0.75, base_d * 1.25)
            h = _num(item.get("heightM"), base_h, base_h * 0.75, base_h * 1.25)
        elif ptype in PROCEDURAL_TYPES:
            cat = catalog_by_type.get(ptype, {})
            w = _num(item.get("widthM"), cat.get("widthM", 1.0), 0.1, 3.5)
            d = _num(item.get("depthM"), cat.get("depthM", 0.5), 0.02, 2.5)
            h = _num(item.get("heightM"), cat.get("heightM", 0.5), 0.01, 3.0)
        else:
            dropped.append(f"{label}（缺少 assetId）")
            continue

        on_wall = ptype in WALL_TYPES
        x = _num(item.get("x"), 0.0, -half + 0.25, half - 0.25)
        y = 1.52 if on_wall else _num(item.get("y"), 0.6, PLACE_Y_MIN, PLACE_Y_MAX)
        z = _num(item.get("z"), 1.4 if ptype == "WALL_ART" else 0.0, 0.0, 2.2)
        prop = {
            "id": f"ai_{idx}", "type": ptype, "label": label, "x": round(x, 3), "y": round(y, 3), "z": round(z, 3),
            "widthM": round(w, 3), "depthM": round(d, 3), "heightM": round(h, 3),
            "rotationDeg": round(_num(item.get("rotationDeg"), 0.0, -360.0, 360.0), 1),
            "colorHex": _hex(item.get("colorHex"), "#c4b6a6"), "accentColorHex": _hex(item.get("accentColorHex"), "#8c7a6b"),
        }
        if aid:
            prop["glbPath"] = _ph_glb(aid)
            prop["polyhavenId"] = aid
            if not Path(prop["glbPath"]).exists():
                dropped.append(f"{label}（素材 {aid} 尚未下載）")
                continue

        # Floor furniture must not collide with the product or earlier furniture; resting items (z>0.2) and rugs are exempt.
        if not on_wall and ptype != "RUG" and z < 0.2:
            for _ in range(12):
                fp = _footprint(prop)
                if not _overlap(fp, product_box) and not any(_overlap(fp, o) for o in placed_floor):
                    break
                prop["x"] = round(max(-half + 0.25, min(half - 0.25, prop["x"] - 0.2)), 3)
            else:
                dropped.append(f"{label}（位置衝突已移除）")
                continue
            placed_floor.append(_footprint(prop))
        props.append(prop)

    return {
        "id": "SCENE_AI_" + uuid.uuid4().hex[:8].upper(),
        "name": str(raw.get("name") or "AI 設計場景")[:60],
        "category": str(raw.get("category") or "AI 場景")[:20],
        "builtin": False,
        "roomWidthM": round(rw, 2), "roomDepthM": round(rd, 2), "roomHeightM": 3.0,
        "wallColorHex": _hex(raw.get("wallColorHex"), "#d6cfc2"),
        "sideWallColorHex": _hex(raw.get("sideWallColorHex"), "#c8c1b4"),
        "floorColorHex": _hex(raw.get("floorColorHex"), "#8a6f55"),
        "lightingPreset": raw.get("lightingPreset") if raw.get("lightingPreset") in LIGHTING_PRESETS else "NORDIC_BRIGHT",
        "productPose": {"x": round(prod_x, 3), "y": 1.15, "z": 0.0, "rotationDeg": 0.0},
        "props": props,
        "aiRationale": str(raw.get("rationale") or "")[:600],
        "aiDropped": dropped,
    }


def _build_user_text(prompt: str, cabinet_w_m: float, cabinet_d_m: float, cabinet_h_m: float) -> str:
    return (
        f"使用者需求：{prompt}\n\n"
        f"組合櫃商品尺寸：寬 {cabinet_w_m:.2f}m × 深 {cabinet_d_m:.2f}m × 高 {cabinet_h_m:.2f}m。\n"
        f"素材庫（只能用這些 assetId）：\n{json.dumps(_catalog_for_prompt(), ensure_ascii=False)}\n"
        f"可用燈光預設：{json.dumps({k: v['label'] for k, v in LIGHTING_PRESETS.items()}, ensure_ascii=False)}"
    )


_LOCAL_JSON_HINT = """
請只輸出一個 JSON 物件（不要 markdown、不要其他文字），格式如下：
{"name":"場景名稱","category":"客廳空間","roomWidthM":5.6,"roomDepthM":4.2,
 "wallColorHex":"#d6cfc2","sideWallColorHex":"#c8c1b4","floorColorHex":"#8a6f55",
 "lightingPreset":"NORDIC_BRIGHT","productX":1.5,"rationale":"設計理由（繁體中文）",
 "props":[{"type":"SOFA","assetId":"Sofa_01","label":"沙發","x":-1.0,"y":1.0,"z":0,"widthM":1.9,"depthM":0.9,"heightM":0.85,"rotationDeg":0,"colorHex":"#c4b6a6","accentColorHex":"#8c7a6b"},
          {"type":"RUG","label":"地毯","x":-1.0,"y":0.3,"widthM":2.5,"depthM":1.6}]}
"""


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first balanced {...} object out of a model reply (local models often wrap JSON in prose or fences)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        start = text.find("{", start + 1)
    raise AiLayoutError("本機 AI 的回覆不是有效的 JSON，請換個說法、或改用較大的模型再試")


def _call_local_llm(user_text: str, base_url: str, model: str) -> dict[str, Any]:
    """Call any OpenAI-compatible local server (Ollama, LM Studio, llama.cpp server, vLLM)."""
    if not model:
        raise AiLayoutError("請先填寫本機模型名稱（例如 Ollama 的 qwen2.5:7b）")
    body = {
        "model": model,
        "temperature": 0.4,
        "stream": False,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.replace("務必呼叫 submit_room_layout 工具回覆，不要輸出其他文字。", "") + _LOCAL_JSON_HINT},
            {"role": "user", "content": user_text},
        ],
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": "Bearer local"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 404:
            raise AiLayoutError(f"本機伺服器找不到模型「{model}」，請先下載（ollama pull {model}）或檢查名稱：{detail}") from exc
        raise AiLayoutError(f"本機 AI 伺服器錯誤 {exc.code}：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise AiLayoutError(f"連不到本機 AI 伺服器 {base_url}，請確認 Ollama / LM Studio 已啟動：{getattr(exc, 'reason', exc)}") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiLayoutError("本機 AI 伺服器回傳格式異常") from exc
    return _extract_json_object(str(content))


def generate_ai_layout(prompt: str, cabinet_w_m: float, cabinet_d_m: float, cabinet_h_m: float, settings: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        raise AiLayoutError("請先輸入想要的空間風格，例如：日系原木風臥室，暖光，擺在床邊")
    user_text = _build_user_text(prompt, cabinet_w_m, cabinet_d_m, cabinet_h_m)
    if settings.get("provider") == "local":
        raw = _call_local_llm(user_text, settings.get("localBaseUrl") or DEFAULT_LOCAL_URL, model or settings.get("localModel") or "")
        return sanitize_layout(raw, cabinet_w_m, cabinet_d_m)
    api_key = settings.get("anthropicApiKey") or ""
    if not api_key:
        raise AiLayoutError("尚未設定 Anthropic API 金鑰，請先在 AI 面板貼上金鑰，或改用本機 AI")
    body = {
        "model": model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL,
        "max_tokens": 3000,
        "system": SYSTEM_PROMPT,
        "tools": [_tool_schema()],
        "tool_choice": {"type": "tool", "name": "submit_room_layout"},
        "messages": [{"role": "user", "content": user_text}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code in (401, 403):
            raise AiLayoutError("Anthropic API 金鑰無效或沒有權限，請重新確認金鑰") from exc
        if exc.code == 404:
            raise AiLayoutError(f"找不到模型「{body['model']}」，可用環境變數 ANTHROPIC_MODEL 指定其他模型") from exc
        raise AiLayoutError(f"Anthropic API 錯誤 {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise AiLayoutError(f"無法連線到 Anthropic API：{exc.reason}") from exc

    tool_input = next((b.get("input") for b in data.get("content", []) if b.get("type") == "tool_use"), None)
    if not isinstance(tool_input, dict):
        raise AiLayoutError("AI 沒有回傳有效的場景設計，請換個說法再試一次")
    return sanitize_layout(tool_input, cabinet_w_m, cabinet_d_m)
