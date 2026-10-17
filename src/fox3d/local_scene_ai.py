"""地端 AI 實景引擎 — turn a Blender Cycles render of the scene into photorealistic variations on our own GPU fleet.

Pipeline per matrix item:

1. Blender renders ``beauty.png`` (full room) and ``product_cutout.png`` (cabinet + shadow-catcher shadow, RGBA).
2. The studio publishes ``beauty.png`` on its LAN URL and asks the fleet (``image_flux3`` = FLUX 3 Image Klein with
   prompt upsampling) to re-photograph the same composition as a real interior photo, N seeds → N variations.
3. The locked cabinet cutout is composited back on top of every generated image, so the product pixels are always
   the exact Blender render (shape, colours, door layout) while the room around it becomes photographic.

Nothing here is ever "Product Truth": the outputs are marketing imagery.
"""
from __future__ import annotations

import json
import math
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageFilter

from fox3d.fleet_image_client import FleetError, FleetImageClient, IMAGE_TASK_TYPE, task_status

SCENE_AI_ENGINES: dict[str, dict[str, Any]] = {
    "fleet_flux3": {
        "id": "fleet_flux3",
        "label": "地端 AI 實景生成",
        "short": "地端 AI 實景",
        "description": "把 3D 光追圖交給公司 GPU 艦隊（FLUX 3 Klein）重拍成真實照片，櫃體像素 100% 鎖定不重畫，每張可出多個變化。",
        "needsFleet": True,
    },
    "builtin": {
        "id": "builtin",
        "label": "內建攝影棚合成",
        "short": "內建合成",
        "description": "不用 GPU，用光學景深、窗光與底片調色在本機合成，秒出圖但仍是 3D 質感。",
        "needsFleet": False,
    },
    "off": {
        "id": "off",
        "label": "只出 3D 光追圖",
        "short": "僅光追",
        "description": "只跑 Blender Cycles，不做任何 AI 後製。",
        "needsFleet": False,
    },
}
DEFAULT_ENGINE = "fleet_flux3"
MAX_VARIANTS = 4

PROP_PROMPT_WORDS: dict[str, str] = {
    "SOFA": "upholstered fabric sofa with soft cushions",
    "COFFEE_TABLE": "wooden coffee table",
    "RUG": "woven textured rug",
    "FLOOR_LAMP": "floor lamp with a fabric shade",
    "WALL_ART": "framed wall art",
    "PLANT": "potted indoor plant",
    "BED": "bed with linen bedding",
    "DESK": "wooden desk",
    "BENCH": "wooden entryway bench",
    "KITCHEN_COUNTER": "kitchen counter",
    "WINDOW_FRAME": "large window with daylight",
    "SHEER_CURTAIN": "sheer linen curtains",
    "CUSTOM_BOX": "decorative furniture piece",
    "CHAIR": "lounge chair",
    "ARMCHAIR": "armchair",
    "SIDE_TABLE": "side table",
    "NIGHTSTAND": "nightstand",
    "CONSOLE": "console table",
    "CABINET": "wooden cabinet",
    "SHELF": "open display shelves",
    "DINING_CHAIR": "dining chair",
    "VASE": "ceramic vase",
    "OTTOMAN": "ottoman",
    "DAYBED": "day bed",
    "TABLE": "wooden table",
    "PICTURE_FRAME": "standing picture frame",
}

LIGHTING_PROMPT_WORDS: dict[str, str] = {
    "WARM_SUNLIGHT": "warm afternoon sunlight streaming through a window, soft long shadows",
    "NORDIC_BRIGHT": "bright, soft, even Nordic daylight",
    "COZY_EVENING": "cozy warm evening lamp light, intimate mood",
    "STUDIO_CLEAN": "clean high-key studio lighting, neutral white balance",
}

VIEW_PROMPT_WORDS: dict[str, str] = {
    "THREE_QUARTER": "three-quarter view from the front right",
    "LEFT": "three-quarter view from the front left",
    "FRONT": "straight-on frontal view at eye level",
    "WIDE": "wide-angle view showing the whole room",
    "CLOSEUP": "close-up product shot",
}

CATEGORY_PROMPT_WORDS: dict[str, str] = {
    "客廳空間": "living room",
    "臥室空間": "bedroom",
    "書房工作室": "home office study",
    "餐廚空間": "dining and kitchen area",
    "玄關走廊": "entryway hallway",
    "兒童房": "kids room",
    "自訂空間": "interior room",
}

# Nearest-colour naming for walls / floors / cabinet finishes (sRGB hex → plain English). Matched with the
# "redmean" distance, a cheap perceptual approximation that keeps greens/greys/browns apart far better than raw RGB.
_COLOR_NAMES: list[tuple[str, tuple[int, int, int]]] = [
    ("white", (247, 246, 243)),
    ("off-white", (236, 232, 224)),
    ("cream", (242, 234, 214)),
    ("ivory", (248, 240, 220)),
    ("beige", (214, 200, 176)),
    ("tan", (210, 180, 140)),
    ("warm greige", (184, 171, 150)),
    ("light grey", (205, 205, 203)),
    ("warm grey", (181, 185, 180)),
    ("grey", (150, 150, 150)),
    ("slate grey", (74, 78, 82)),
    ("charcoal", (50, 53, 56)),
    ("black", (20, 20, 22)),
    ("sage green", (160, 172, 150)),
    ("soft green", (158, 197, 171)),
    ("eucalyptus green", (125, 150, 133)),
    ("forest green", (95, 122, 105)),
    ("teal", (38, 83, 78)),
    ("mint green", (190, 220, 200)),
    ("misty blue", (170, 190, 205)),
    ("dusty blue", (109, 142, 160)),
    ("steel blue", (77, 109, 128)),
    ("navy blue", (40, 55, 90)),
    ("blush pink", (232, 165, 152)),
    ("dusty rose", (200, 150, 150)),
    ("pale yellow", (249, 228, 152)),
    ("mustard yellow", (225, 180, 60)),
    ("terracotta", (181, 105, 53)),
    ("honey oak", (229, 201, 159)),
    ("light oak", (200, 157, 102)),
    ("natural oak", (184, 139, 90)),
    ("walnut", (110, 71, 43)),
    ("chestnut brown", (120, 88, 58)),
    ("dark brown", (70, 45, 30)),
    ("taupe", (150, 118, 86)),
]


class LocalSceneAiError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- helpers
def _hex_to_rgb(hex_str: str | None) -> tuple[int, int, int] | None:
    s = str(hex_str or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def color_name(hex_str: str | None, default: str = "neutral") -> str:
    rgb = _hex_to_rgb(hex_str)
    if rgb is None:
        return default
    best, best_d = default, float("inf")
    r1, g1, b1 = rgb
    for name, (r2, g2, b2) in _COLOR_NAMES:
        rmean = (r1 + r2) / 2.0
        dr, dg, db = r1 - r2, g1 - g2, b1 - b2
        d = (2 + rmean / 256.0) * dr * dr + 4 * dg * dg + (2 + (255 - rmean) / 256.0) * db * db
        if d < best_d:
            best, best_d = name, d
    return best


def describe_cabinet(cabinet_cfg: dict[str, Any] | None, cabinet_spec: dict[str, Any] | None = None, theme: dict[str, Any] | None = None) -> str:
    """Human-readable product description used to anchor the generator on the locked product."""
    cfg = cabinet_cfg or {}
    columns = cfg.get("columns") or []
    n_cols = max(1, len(columns))
    cells = [c for col in columns for c in (col.get("cells") or [])]
    n_doors = sum(1 for c in cells if str(c.get("mode") or "DOOR").upper() == "DOOR")
    n_open = sum(1 for c in cells if str(c.get("mode") or "").upper() == "OPEN")
    n_drawers = sum(1 for c in cells if str(c.get("mode") or "").upper() == "DRAWER")
    total_cells = max(1, len(cells))
    parts = [f"{n_cols}-column {total_cells}-cube modular storage cabinet"]
    if cabinet_spec:
        try:
            w, d, h = (int(round(float(cabinet_spec.get(k) or 0))) for k in ("width", "depth", "height"))
            if w and d and h:
                parts.append(f"about {w}×{d}×{h} mm")
        except (TypeError, ValueError):
            pass
    if theme:
        carcass = color_name(theme.get("carcassHex"), "light oak")
        doors = [color_name(hx, "white") for hx in (theme.get("doorPaletteHex") or [])[:2]]
        door_txt = " and ".join(dict.fromkeys(doors)) if doors else "white"
        parts.append(f"{carcass} frame with {door_txt} doors")
    detail = []
    if n_doors:
        detail.append(f"{n_doors} door{'s' if n_doors != 1 else ''}")
    if n_open:
        detail.append(f"{n_open} open shelf cube{'s' if n_open != 1 else ''}")
    if n_drawers:
        detail.append(f"{n_drawers} drawer unit{'s' if n_drawers != 1 else ''}")
    if detail:
        parts.append(", ".join(detail))
    parts.append("slim black bar handles")
    return ", ".join(parts)


def describe_props(scene_cfg: dict[str, Any]) -> list[str]:
    seen: dict[str, int] = {}
    for prop in scene_cfg.get("props") or []:
        ptype = str(prop.get("type") or "").upper()
        words = PROP_PROMPT_WORDS.get(ptype) or ptype.replace("_", " ").lower() or "furniture"
        seen[words] = seen.get(words, 0) + 1
    out = []
    for words, count in seen.items():
        out.append(words if count == 1 else f"{count} {words}s" if not words.endswith("s") else f"{count} {words}")
    return out


def build_scene_prompt(
    scene_cfg: dict[str, Any],
    cabinet_cfg: dict[str, Any] | None,
    *,
    cabinet_spec: dict[str, Any] | None = None,
    theme: dict[str, Any] | None = None,
    style_prompt: str = "",
    custom_prompt: str = "",
    view: str = "THREE_QUARTER",
    variation: str = "faithful",
) -> dict[str, str]:
    """Compose the English generation prompt. Returns ``{"prompt", "productDescription", "roomBrief", "variation"}``.

    ``variation``: ``faithful`` keeps the whole layout and only makes materials/light real; ``creative`` lets the model
    restyle the room (finishes, window, decor, furniture style) while the product position/size stay locked.
    """
    category = CATEGORY_PROMPT_WORDS.get(str(scene_cfg.get("category") or ""), "interior room")
    lighting = LIGHTING_PROMPT_WORDS.get(str(scene_cfg.get("lightingPreset") or ""), LIGHTING_PROMPT_WORDS["WARM_SUNLIGHT"])
    view_words = VIEW_PROMPT_WORDS.get(str(view or "").upper(), VIEW_PROMPT_WORDS["THREE_QUARTER"])
    wall = color_name(scene_cfg.get("wallColorHex"), "warm greige")
    floor = color_name(scene_cfg.get("floorColorHex"), "natural oak")
    props = describe_props(scene_cfg)
    product = describe_cabinet(cabinet_cfg, cabinet_spec, theme)

    room_brief = f"{category} with {wall} plaster walls and {floor} wood flooring"
    if props:
        room_brief += ", furnished with " + ", ".join(props)
    style = (style_prompt or "").strip()
    custom = (custom_prompt or "").strip()

    creative = str(variation or "").lower() == "creative"
    sentences = [
        "Turn this 3D render into a photorealistic interior photograph.",
        (
            "Keep the same camera angle and framing and keep the product at exactly the same position and size, but restyle the room freely: "
            "wall finish, flooring, window, curtains, lighting mood, decor and the style of the other furniture may change, as long as nothing covers the product."
            if creative
            else "Keep exactly the same camera angle, framing, room layout, furniture placement and proportions as the reference image."
        ),
        f"The product is a {product}; it must stay exactly the same shape, size, position, door layout and colours.",
        f"Scene: {room_brief}. Lighting: {lighting}. Camera: {view_words}, 50mm lens, interior design magazine photo.",
        "Make every material real: fabric weave, wood grain, plaster texture, soft contact shadows, natural colour bounce.",
    ]
    if style:
        sentences.append(f"Style direction: {style}.")
    if custom:
        sentences.append(f"Extra direction: {custom}.")
    sentences.append("No text, no watermark, no logo, no people, no added furniture, no cropping.")
    prompt = " ".join(s.strip() for s in sentences if s.strip())
    return {"prompt": prompt, "productDescription": product, "roomBrief": room_brief, "variation": "creative" if creative else "faithful"}


def polish_prompt_with_llm(prompt: str, *, base_url: str, model: str, extra_direction: str = "", timeout: float = 60.0, opener: Callable[..., Any] = urllib.request.urlopen) -> str:
    """Ask the local OpenAI-compatible LLM (fox AI gateway) to rewrite the prompt as a richer English photo brief.

    Returns the original prompt untouched on any failure so generation never blocks on the LLM.
    """
    if not base_url or not model:
        return prompt
    system = (
        "You are an interior photographer writing prompts for an image-editing model that re-photographs a 3D render as a real photo. "
        "Rewrite the user's prompt into one richer English paragraph (max 120 words): concrete materials, light quality, lens, mood. "
        "You MUST keep every constraint about the product staying identical, keeping the same camera/layout, and no text/people/watermark. "
        "Output only the prompt text, no preamble, no quotes, no markdown."
    )
    user = prompt if not extra_direction.strip() else f"{prompt}\n\nUser's extra direction (Chinese allowed): {extra_direction.strip()}"
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.4, "max_tokens": 400, "stream": False}
    req = urllib.request.Request(f"{base_url.rstrip('/')}/chat/completions", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with opener(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    except Exception:
        return prompt
    if "<think>" in text:
        text = text.split("</think>")[-1].strip()
    text = text.strip().strip('"').strip()
    return text if 40 <= len(text) <= 2000 else prompt


# ----------------------------------------------------------------------------- compositing
def composite_locked_product(generated: Image.Image, cutout: Image.Image, *, feather_px: float = 0.8) -> Image.Image:
    """Paste the Blender cabinet cutout (RGBA, with its shadow-catcher shadow) over the AI image, pixel-locked."""
    base = generated.convert("RGBA")
    layer = cutout.convert("RGBA")
    if layer.size != base.size:
        layer = layer.resize(base.size, Image.Resampling.LANCZOS)
    if feather_px and feather_px > 0:
        alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(radius=feather_px))
        # Keep fully opaque product pixels opaque; only soften the rim so the paste has no hard halo.
        hard = layer.getchannel("A").point(lambda a: 255 if a >= 250 else 0)
        alpha = Image.composite(hard, alpha, hard)
        layer.putalpha(alpha)
    return Image.alpha_composite(base, layer).convert("RGB")


# ----------------------------------------------------------------------------- network helpers
def detect_lan_ip(probe_host: str = "192.168.66.101", probe_port: int = 3004) -> str | None:
    """Pick the local interface that routes to the fleet console (no packets are actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((probe_host, probe_port))
            ip = sock.getsockname()[0]
        return ip if ip and not ip.startswith("127.") else None
    except OSError:
        return None


def build_public_base_url(configured: str | None, port: int | None, fleet_url: str | None = None) -> str:
    """Base URL that GPU nodes use to fetch our reference renders."""
    if configured and configured.strip():
        return configured.strip().rstrip("/")
    host = None
    if fleet_url:
        try:
            parsed = urllib.parse.urlparse(fleet_url)
            host = parsed.hostname
            fleet_port = parsed.port or 80
        except Exception:
            host, fleet_port = None, 3004
    ip = detect_lan_ip(host or "192.168.66.101", fleet_port if host else 3004)
    if not ip:
        return ""
    return f"http://{ip}:{int(port or 8790)}"


def engine_status(settings: dict[str, Any], *, bind_host: str | None, public_base_url: str, client: FleetImageClient | None = None) -> dict[str, Any]:
    """Snapshot of whether 地端 AI generation can run right now (used by the studio header)."""
    engine = str(settings.get("imageEngine") or DEFAULT_ENGINE)
    client = client or FleetImageClient.from_settings(settings)
    out: dict[str, Any] = {
        "engine": engine,
        "engines": list(SCENE_AI_ENGINES.values()),
        "fleetUrl": client.base_url,
        "tokenConfigured": bool(client.token),
        "reachable": False,
        "capability": None,
        "error": None,
        "publicBaseUrl": public_base_url,
        "bindHost": bind_host,
        "warnings": [],
        "ready": False,
    }
    if bind_host in ("127.0.0.1", "localhost", "::1"):
        out["warnings"].append("工作台目前只綁在 127.0.0.1，GPU 節點抓不到參考圖；請用 --host 0.0.0.0 啟動（桌面捷徑已改好）。")
    if not public_base_url:
        out["warnings"].append("偵測不到可讓 GPU 節點連回來的區網位址，請在設定填 publicBaseUrl。")
    if not client.token:
        out["error"] = "尚未設定 GPU 艦隊服務金鑰"
        return out
    try:
        cap = client.capability(IMAGE_TASK_TYPE)
        out["reachable"] = True
        if cap is None:
            out["error"] = f"艦隊目前沒有 {IMAGE_TASK_TYPE} 能力"
        else:
            out["capability"] = {
                "available": bool(cap.get("available")),
                "status": cap.get("status"),
                "capableNodes": cap.get("capableNodes"),
                "capableGpuCount": cap.get("capableGpuCount"),
                "queueDepth": cap.get("queueDepth"),
                "runningCount": cap.get("runningCount"),
                "estimatedRuntimeSec": cap.get("estimatedRuntimeSec"),
                "estimatedWaitSec": cap.get("estimatedWaitSec"),
                "minimumVramMb": cap.get("minimumVramMb"),
            }
            if not cap.get("available"):
                out["warnings"].append("艦隊回報 FLUX 3 目前不可用（節點離線或顯存不足），任務會排隊等待。")
    except FleetError as exc:
        out["error"] = str(exc)
    out["ready"] = bool(out["reachable"] and out["capability"] and not out["error"] and public_base_url and bind_host not in ("127.0.0.1", "localhost", "::1"))
    return out


# ----------------------------------------------------------------------------- generation
def run_local_scene_variants(
    client: FleetImageClient,
    *,
    item_dir: Path,
    reference_url: str,
    cutout_path: Path | None,
    prompt: str,
    variants: int = 2,
    seed: int = 0,
    upsample: bool = True,
    job_prefix: str = "fox3d",
    width: int | None = None,
    height: int | None = None,
    on_progress: Callable[[list[dict[str, Any]]], None] | None = None,
    timeout: float = 900.0,
    poll_interval: float = 4.0,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Submit N ``image_flux3`` tasks for one item, wait for all of them, composite the locked product, write files.

    Returns the variant records (also persisted to ``ai_local.json``). Never raises for a single failed variant:
    each record carries its own ``state`` / ``error``.
    """
    n = max(1, min(MAX_VARIANTS, int(variants or 1)))
    item_dir = Path(item_dir)
    item_dir.mkdir(parents=True, exist_ok=True)
    cutout_img: Image.Image | None = None
    if cutout_path and Path(cutout_path).exists() and Path(cutout_path).stat().st_size > 64:
        try:
            cutout_img = Image.open(cutout_path).convert("RGBA")
        except Exception:
            cutout_img = None

    records: list[dict[str, Any]] = []
    for k in range(n):
        records.append({
            "index": k,
            "file": f"ai_local_{k + 1:02d}.png",
            "seed": int(seed) + k,
            "taskId": None,
            "state": "queued",
            "error": None,
            "node": None,
            "elapsedSec": None,
            "caption": None,
            "productLocked": cutout_img is not None,
        })

    def emit() -> None:
        try:
            (item_dir / "ai_local.json").write_text(json.dumps({"prompt": prompt, "referenceUrl": reference_url, "upsample": bool(upsample), "variants": records}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        if on_progress:
            try:
                on_progress(records)
            except Exception:
                pass

    emit()
    started: dict[int, float] = {}
    for rec in records:
        try:
            task = client.submit_flux3(
                prompt=prompt,
                image_urls=[reference_url],
                seed=rec["seed"],
                upsample=upsample,
                width=width,
                height=height,
                job_id=f"{job_prefix}-v{rec['index'] + 1}-{int(time.time())}",
            )
            rec["taskId"] = str(task.get("id"))
            rec["state"] = "running" if task_status(task) in ("running", "assigned") else "queued"
            started[rec["index"]] = time.monotonic()
        except FleetError as exc:
            rec["state"] = "failed"
            rec["error"] = str(exc)[:300]
        emit()

    pending = [r for r in records if r["taskId"] and r["state"] not in ("failed", "succeeded")]
    deadline = time.monotonic() + timeout
    while pending:
        for rec in list(pending):
            try:
                task = client.get_task(rec["taskId"])
            except FleetError as exc:
                rec["error"] = str(exc)[:300]
                continue
            status = task_status(task)
            rec["node"] = task.get("nodeHostname") or task.get("nodeId") or task.get("workerId") or rec["node"]
            progress = task.get("progressPercent", task.get("progress"))
            if isinstance(progress, (int, float)):
                rec["progress"] = int(progress)
            note = task.get("progressNote") or task.get("progress_note")
            if note:
                rec["progressNote"] = str(note)[:120]
            if status in ("success", "succeeded", "completed", "done"):
                try:
                    raw = client.artifact_bytes(task)
                    from io import BytesIO

                    gen = Image.open(BytesIO(raw)).convert("RGBA")
                    final = composite_locked_product(gen, cutout_img) if cutout_img is not None else gen.convert("RGB")
                    final.save(item_dir / rec["file"], format="PNG")
                    (item_dir / rec["file"].replace(".png", "_raw.png")).write_bytes(raw)
                    rec["state"] = "succeeded"
                    rec["width"], rec["height"] = final.size
                    payload = task.get("outputPayload") or {}
                    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
                    if isinstance(data, dict) and data.get("caption"):
                        rec["caption"] = str(data["caption"])[:600]
                except (FleetError, OSError, ValueError) as exc:
                    rec["state"] = "failed"
                    rec["error"] = str(exc)[:300]
                rec["elapsedSec"] = round(time.monotonic() - started.get(rec["index"], time.monotonic()), 1)
                pending.remove(rec)
            elif status in ("failed", "error", "errored", "cancelled", "canceled", "timeout", "timed_out", "refused"):
                rec["state"] = "failed"
                rec["error"] = (task.get("error") or task.get("errorMessage") or f"GPU 任務 {status}")
                rec["error"] = str(rec["error"])[:300]
                rec["elapsedSec"] = round(time.monotonic() - started.get(rec["index"], time.monotonic()), 1)
                pending.remove(rec)
            else:
                rec["state"] = "running" if status in ("running", "assigned", "dispatched", "in_progress") else "queued"
        emit()
        if not pending:
            break
        if time.monotonic() > deadline:
            for rec in pending:
                rec["state"] = "failed"
                rec["error"] = f"GPU 任務逾時（{int(timeout)} 秒）"
            pending = []
            emit()
            break
        sleep(poll_interval)
    emit()
    return records
