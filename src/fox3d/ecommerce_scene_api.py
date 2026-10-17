"""FastAPI router for the E-Commerce Modular Cabinet & 3D Scene Studio workbench."""
from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

import os

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from fox3d.ecommerce_scene_studio import EcommerceSceneStore

STATIC = Path(__file__).with_name("static")
CSP = "default-src 'self'; img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"


def ecommerce_scene_router(provider) -> APIRouter:
    router = APIRouter()
    stores: dict[Path, EcommerceSceneStore] = {}
    lock = RLock()

    def store() -> EcommerceSceneStore:
        plat = provider()
        root = Path(plat.root).resolve()
        with lock:
            if root not in stores:
                stores[root] = EcommerceSceneStore(plat)
            return stores[root]

    def tenant(x_tenant_id: str | None) -> str:
        val = (x_tenant_id or "sonaqueen-home").strip()
        if not val or val == "system" or len(val) > 120:
            raise HTTPException(400, "請提供有效的工作區 X-Tenant-Id")
        return val

    @router.get("/admin/recipes/scenes", response_class=HTMLResponse)
    def scene_studio_page() -> HTMLResponse:
        return HTMLResponse(
            (STATIC / "scene-studio.html").read_text(encoding="utf-8"),
            headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store"},
        )

    @router.get("/api/ecommerce-scenes/overview")
    def overview(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        return store().overview(tenant(x_tenant_id))

    @router.post("/api/ecommerce-scenes/preview-plan")
    def preview_plan(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().preview_plan(tenant(x_tenant_id), payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/ecommerce-scenes/scenes", status_code=201)
    def save_scene(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().save_scene(tenant(x_tenant_id), payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.delete("/api/ecommerce-scenes/scenes/{scene_id}")
    def delete_scene(scene_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().delete_scene(tenant(x_tenant_id), scene_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/ecommerce-scenes/props/upload-glb", status_code=201)
    def upload_glb_prop(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        import base64

        try:
            raw_b64 = str(payload.get("dataBase64") or "").strip()
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            raw_bytes = base64.b64decode(raw_b64) if raw_b64 else b""
            return store().upload_glb_prop(tenant(x_tenant_id), str(payload.get("filename") or "model.glb"), raw_bytes)
        except Exception as exc:
            raise HTTPException(422, f"GLB 檔案解析失敗：{exc}") from exc

    @router.get("/api/ecommerce-scenes/polyhaven-thumb/{asset_id}")
    def polyhaven_thumb(asset_id: str) -> FileResponse:
        safe_id = "".join(c for c in asset_id if c.isalnum() or c in ("_", "-"))
        thumb = Path(__file__).resolve().parents[2] / "assets" / "models" / "polyhaven" / "thumbs" / f"{safe_id}.png"
        if not thumb.exists():
            raise HTTPException(404, "找不到預覽縮圖")
        return FileResponse(thumb, media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @router.post("/api/ecommerce-scenes/polyhaven-fetch", status_code=201)
    def polyhaven_fetch(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        from fox3d.photoreal_assets import download_custom_polyhaven_asset

        _ = tenant(x_tenant_id)
        try:
            item = download_custom_polyhaven_asset(
                asset_id_or_url=str(payload.get("assetIdOrUrl") or ""),
                prop_type=str(payload.get("propType") or "SOFA"),
                label=str(payload.get("label") or ""),
                root_dir=Path(provider().root).resolve(),
            )
            return item
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"Poly Haven 下載失敗：{exc}") from exc


    def _ai_public_settings() -> dict[str, Any]:
        from fox3d.ai_scene_layout import load_settings
        from fox3d.fleet_image_client import resolve_fleet_token, resolve_fleet_url

        s = load_settings(store().root)
        return {
            "provider": s["provider"],
            "hasKey": bool(s["anthropicApiKey"]),
            "localBaseUrl": s["localBaseUrl"],
            "localModel": s["localModel"],
            "imageEngine": s["imageEngine"],
            "fleetApiUrl": resolve_fleet_url(s["fleetApiUrl"]),
            "fleetTokenConfigured": bool(resolve_fleet_token(s["fleetToken"])),
            "publicBaseUrl": s["publicBaseUrl"],
            "aiVariants": s["aiVariants"],
            "aiVariation": s["aiVariation"],
            "aiUpsample": s["aiUpsample"],
            "aiPinProduct": s["aiPinProduct"],
            "promptPolish": s["promptPolish"],
        }

    def _public_base_url(request: Request) -> str:
        from fox3d.ai_scene_layout import load_settings
        from fox3d.fleet_image_client import resolve_fleet_url
        from fox3d.local_scene_ai import build_public_base_url

        s = load_settings(store().root)
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        return build_public_base_url(s["publicBaseUrl"], port, resolve_fleet_url(s["fleetApiUrl"]))

    @router.get("/api/ecommerce-scenes/ai-engine-status")
    def ai_engine_status(request: Request) -> dict[str, Any]:
        from fox3d.ai_scene_layout import load_settings
        from fox3d.local_scene_ai import engine_status

        s = load_settings(store().root)
        return engine_status(s, bind_host=(os.environ.get("FOX3D_BIND_HOST") or "").strip() or None, public_base_url=_public_base_url(request))

    @router.post("/api/ecommerce-scenes/ai-prompt")
    def ai_prompt_preview(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        """Show (and optionally LLM-polish) the exact prompt the fleet will receive for the current scene."""
        from fox3d.ai_scene_layout import load_settings
        from fox3d.ecommerce_scene_studio import CABINET_PRESETS, STYLE_THEMES, build_modular_cabinet_spec
        from fox3d.local_scene_ai import build_scene_prompt, polish_prompt_with_llm
        from fox3d.photoreal_assets import AI_STYLE_PRESETS

        tid = tenant(x_tenant_id)
        raw_scene = payload.get("scene")
        scene: dict[str, Any] = dict(raw_scene) if isinstance(raw_scene, dict) else {}
        raw_cabinet = payload.get("cabinet")
        cabinet: dict[str, Any] = dict(raw_cabinet) if isinstance(raw_cabinet, dict) else dict(CABINET_PRESETS[0])
        try:
            spec = build_modular_cabinet_spec(cabinet, tenant_id=tid)
        except Exception as exc:
            raise HTTPException(422, f"櫃體設定無效：{exc}") from exc
        style = AI_STYLE_PRESETS.get(str(payload.get("aiStyleId") or "")) or {}
        built = build_scene_prompt(
            scene,
            cabinet,
            cabinet_spec=spec,
            theme=STYLE_THEMES.get(str(payload.get("themeId") or cabinet.get("themeId") or "")),
            style_prompt=str(style.get("prompt") or ""),
            custom_prompt=str(payload.get("aiPrompt") or ""),
            view=str(payload.get("view") or "THREE_QUARTER"),
            variation=str(payload.get("aiVariation") or "faithful"),
        )
        polished = False
        if payload.get("polish"):
            s = load_settings(store().root)
            improved = polish_prompt_with_llm(built["prompt"], base_url=s["localBaseUrl"], model=s["localModel"], extra_direction=str(payload.get("aiPrompt") or ""))
            polished = improved != built["prompt"]
            built["prompt"] = improved
        return {**built, "polished": polished}

    @router.get("/api/ecommerce-scenes/ai-settings")
    def ai_settings() -> dict[str, Any]:
        return _ai_public_settings()

    @router.post("/api/ecommerce-scenes/ai-settings")
    def save_ai_settings(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        from fox3d.ai_scene_layout import save_settings

        _ = tenant(x_tenant_id)
        updates: dict[str, Any] = {}
        if "provider" in payload:
            if payload["provider"] not in ("anthropic", "local"):
                raise HTTPException(422, "不支援的 AI 來源")
            updates["provider"] = payload["provider"]
        key = str(payload.get("anthropicApiKey") or "").strip()
        if key:
            if not key.startswith("sk-ant-") or len(key) > 300:
                raise HTTPException(422, "金鑰格式不正確，Anthropic 金鑰應以 sk-ant- 開頭")
            updates["anthropicApiKey"] = key
        if "localBaseUrl" in payload:
            url = str(payload.get("localBaseUrl") or "").strip().rstrip("/")
            if not url.startswith(("http://", "https://")) or len(url) > 200:
                raise HTTPException(422, "本機伺服器網址須以 http:// 或 https:// 開頭，例如 http://127.0.0.1:11434/v1")
            updates["localBaseUrl"] = url
        if "localModel" in payload:
            updates["localModel"] = str(payload.get("localModel") or "").strip()[:120]
        if "imageEngine" in payload:
            from fox3d.ai_scene_layout import IMAGE_ENGINES

            if payload["imageEngine"] not in IMAGE_ENGINES:
                raise HTTPException(422, "不支援的 AI 實景引擎")
            updates["imageEngine"] = payload["imageEngine"]
        if "fleetApiUrl" in payload:
            furl = str(payload.get("fleetApiUrl") or "").strip().rstrip("/")
            if furl and (not furl.startswith(("http://", "https://")) or len(furl) > 200):
                raise HTTPException(422, "GPU 艦隊網址須以 http:// 或 https:// 開頭，例如 http://192.168.66.101:3004")
            updates["fleetApiUrl"] = furl
        ftoken = str(payload.get("fleetToken") or "").strip()
        if ftoken:
            if len(ftoken) > 300 or any(ch.isspace() for ch in ftoken):
                raise HTTPException(422, "GPU 艦隊服務金鑰格式不正確")
            updates["fleetToken"] = ftoken
        if payload.get("clearFleetToken"):
            updates["fleetToken"] = ""
        if "publicBaseUrl" in payload:
            purl = str(payload.get("publicBaseUrl") or "").strip().rstrip("/")
            if purl and (not purl.startswith(("http://", "https://")) or len(purl) > 200):
                raise HTTPException(422, "工作台對外網址須以 http:// 開頭，例如 http://192.168.66.21:8790")
            updates["publicBaseUrl"] = purl
        if "aiVariants" in payload:
            try:
                updates["aiVariants"] = int(payload.get("aiVariants") or 2)
            except (TypeError, ValueError):
                raise HTTPException(422, "變化張數必須是 1–4 的整數") from None
        for key in ("aiUpsample", "promptPolish", "aiPinProduct"):
            if key in payload:
                updates[key] = bool(payload.get(key))
        if "aiVariation" in payload:
            if payload["aiVariation"] not in ("faithful", "creative"):
                raise HTTPException(422, "變化幅度只能是 faithful 或 creative")
            updates["aiVariation"] = payload["aiVariation"]
        save_settings(store().root, updates)
        return _ai_public_settings()

    @router.get("/api/ecommerce-scenes/ai-local-models")
    def ai_local_models() -> dict[str, Any]:
        import json as _json
        import urllib.request as _ur

        from fox3d.ai_scene_layout import load_settings

        base = load_settings(store().root)["localBaseUrl"]
        try:
            with _ur.urlopen(f"{base}/models", timeout=5) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "models": [m.get("id") for m in data.get("data", []) if m.get("id")]}
        except Exception as exc:
            return {"ok": False, "models": [], "error": f"連不到 {base}：{exc}"}

    @router.post("/api/ecommerce-scenes/ai-layout")
    def ai_layout(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        from fox3d.ai_scene_layout import AiLayoutError, generate_ai_layout, load_settings
        from fox3d.ecommerce_scene_studio import CABINET_PRESETS, build_modular_cabinet_spec

        tid = tenant(x_tenant_id)
        try:
            spec = build_modular_cabinet_spec(payload.get("cabinet") or CABINET_PRESETS[0], tenant_id=tid)
            scene = generate_ai_layout(
                str(payload.get("prompt") or ""),
                float(spec["width"]) / 1000.0,
                float(spec["depth"]) / 1000.0,
                float(spec["height"]) / 1000.0,
                load_settings(store().root),
                model=str(payload.get("model") or "") or None,
            )
            return scene
        except AiLayoutError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/ecommerce-scenes/batches", status_code=202)
    def start_batch(payload: dict[str, Any], request: Request, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().start_matrix_batch(tenant(x_tenant_id), payload, public_base_url=_public_base_url(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/api/ecommerce-scenes/batches/{batch_id}")
    def get_batch(batch_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        try:
            return store().get_batch(tenant(x_tenant_id), batch_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/api/ecommerce-scenes/batches/{batch_id}/items/{item_id}/download/{fmt}")
    def download_item(
        batch_id: str,
        item_id: str,
        fmt: str,
        workspace: str | None = Query(default=None),
        inline: bool = Query(default=False),
        variant: int = Query(default=1, ge=1, le=4),
        x_tenant_id: str | None = Header(default=None),
    ) -> FileResponse:
        tid = tenant(x_tenant_id or workspace)
        try:
            target = store().item_asset_path(tid, batch_id, item_id, fmt, variant=variant)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        media = {
            "png": "image/png",
            "ai_png": "image/png",
            "ai_local_png": "image/png",
            "ai_local_raw_png": "image/png",
            "cutout_png": "image/png",
            "glb": "model/gltf-binary",
            "blend": "application/x-blender",
        }[fmt]
        ext = "png" if fmt.endswith("png") else fmt
        if inline and ext == "png":
            return FileResponse(target, media_type=media, headers={"Cache-Control": "no-store"})
        suffix = f"_v{variant}" if fmt.startswith("ai_local") else ""
        return FileResponse(
            target,
            media_type=media,
            filename=f"{batch_id[:8]}_{item_id}_{fmt}{suffix}.{ext}",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/api/ecommerce-scenes/batches/{batch_id}/zip")
    def download_zip(
        batch_id: str,
        workspace: str | None = Query(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> Response:
        tid = tenant(x_tenant_id or workspace)
        try:
            data = store().build_batch_zip(tid, batch_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="ecommerce-matrix-{batch_id[:8]}.zip"',
                "Cache-Control": "no-store",
            },
        )

    return router
