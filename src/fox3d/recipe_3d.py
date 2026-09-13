"""Sonaqueen Recipe 3D Modeling & Preview Adapter.

Transforms supplier recipe facts and workbench drafts into parametric 3D cabinet specifications,
handles transparent preview assumptions, and drives headless Blender Cycles OptiX rendering
as well as .blend and .glb asset exports.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash


def resolve_recipe_preview_assumptions(draft_data: dict[str, Any]) -> dict[str, Any]:
    """Resolves missing engineering/manufacturing details with transparent preview assumptions."""
    values = draft_data.get("values") or {}
    family = str(draft_data.get("family") or "STAGGERED_OPEN_CUBBY")

    def _val(k: str, default: Any) -> Any:
        entry = values.get(k)
        if isinstance(entry, dict) and entry.get("value") is not None:
            return entry["value"]
        if draft_data.get(k) is not None:
            return draft_data[k]
        return default

    # Core dimensions
    width = float(_val("widthMm", 602.0))
    depth = float(_val("depthMm", 300.0))
    height = float(_val("heightMm", 1802.0))

    assumptions: list[dict[str, Any]] = []

    # Board thickness assumption
    board_thick_raw = values.get("boardThicknessMm", {}).get("value") if isinstance(values.get("boardThicknessMm"), dict) else draft_data.get("boardThicknessMm")
    if board_thick_raw is not None:
        board_thick = float(board_thick_raw)
    else:
        board_thick = 15.0
        assumptions.append({
            "field": "boardThicknessMm",
            "value": 15.0,
            "unit": "mm",
            "source": "PREVIEW_ASSUMPTION",
            "label": "板材厚度",
            "note": "預覽用假設：15 mm 塑合板，待工廠確認",
        })

    # Back panel assumption
    back_panel_raw = values.get("backPanel", {}).get("value") if isinstance(values.get("backPanel"), dict) else draft_data.get("backPanel")
    if back_panel_raw is not None:
        back_panel = bool(back_panel_raw)
    else:
        back_panel = False
        assumptions.append({
            "field": "backPanel",
            "value": False,
            "unit": "boolean",
            "source": "PREVIEW_ASSUMPTION",
            "label": "背板結構",
            "note": "預覽用假設：開放穿透式無背板（日系通風結構）",
        })

    # Rows and compartments
    row_count = int(_val("rowCount", 6))
    comp_count = int(_val("compartmentCount", 12))
    door_count = int(_val("doorCount", 0))

    # Opening widths
    narrow_w = float(_val("labelledNarrowOpeningWidthMm", 181.5))
    wide_w = float(_val("labelledWideOpeningWidthMm", 373.5))

    if family == "STAGGERED_OPEN_CUBBY":
        assumptions.append({
            "field": "staggerPattern",
            "value": "alternating_left_right",
            "unit": "text",
            "source": "PREVIEW_ASSUMPTION",
            "label": "垂直隔板排列",
            "note": "預覽用假設：奇偶層交錯對稱排列（窄隔 181.5mm / 寬隔 373.5mm）",
        })
    elif family in {"STACKED_HINGED_CABINET", "ROW_SLIDING_CABINET"} or door_count > 0:
        assumptions.append({
            "field": "doorGapMm",
            "value": 2.0,
            "unit": "mm",
            "source": "PREVIEW_ASSUMPTION",
            "label": "門縫間隙",
            "note": "預覽用假設：左右與中間門縫各預留 2 mm",
        })

    resolved = {
        "widthMm": width,
        "depthMm": depth,
        "heightMm": height,
        "boardThicknessMm": board_thick,
        "backPanel": back_panel,
        "rowCount": row_count,
        "compartmentCount": comp_count,
        "doorCount": door_count,
        "labelledNarrowOpeningWidthMm": narrow_w,
        "labelledWideOpeningWidthMm": wide_w,
        "material": str(_val("material", "高密度塑合板、五金")),
    }

    return {
        "resolved": resolved,
        "assumptions": assumptions,
    }


def build_recipe_spec(
    draft_data: dict[str, Any],
    *,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Constructs a deterministic 3D parametric specification from resolved recipe facts."""
    sku = str(draft_data.get("sku") or "CUSTOM")
    name = str(draft_data.get("name") or "收納櫃")
    family = str(draft_data.get("family") or "STAGGERED_OPEN_CUBBY")

    res_assumptions = resolve_recipe_preview_assumptions(draft_data)
    resolved = res_assumptions["resolved"]
    assumptions = res_assumptions["assumptions"]

    width = float(resolved["widthMm"])
    depth = float(resolved["depthMm"])
    height = float(resolved["heightMm"])
    t = float(resolved["boardThicknessMm"])
    rows = max(1, int(resolved.get("rowCount") or 6))

    components: list[dict[str, Any]] = []

    # 1. Outer Carcass Panels
    # Left side panel
    components.append({
        "componentId": "left_side",
        "partName": "左側板",
        "role": "left",
        "length": height,
        "width": depth,
        "thickness": t,
        "location": [-width / 2000.0 + t / 2000.0, 0.0, height / 2000.0],
        "size": [t / 1000.0, depth / 1000.0, height / 1000.0],
    })

    # Right side panel
    components.append({
        "componentId": "right_side",
        "partName": "右側板",
        "role": "right",
        "length": height,
        "width": depth,
        "thickness": t,
        "location": [width / 2000.0 - t / 2000.0, 0.0, height / 2000.0],
        "size": [t / 1000.0, depth / 1000.0, height / 1000.0],
    })

    # Top panel
    components.append({
        "componentId": "top_panel",
        "partName": "頂板",
        "role": "top",
        "length": width,
        "width": depth,
        "thickness": t,
        "location": [0.0, 0.0, (height - t / 2.0) / 1000.0],
        "size": [width / 1000.0, depth / 1000.0, t / 1000.0],
    })

    # Bottom panel
    inner_w = max(10.0, width - 2 * t)
    components.append({
        "componentId": "bottom_panel",
        "partName": "底板",
        "role": "bottom",
        "length": inner_w,
        "width": depth,
        "thickness": t,
        "location": [0.0, 0.0, (t / 2.0) / 1000.0],
        "size": [inner_w / 1000.0, depth / 1000.0, t / 1000.0],
    })

    # Back panel (if enabled)
    if resolved.get("backPanel"):
        components.append({
            "componentId": "back_panel",
            "partName": "背板",
            "role": "back",
            "length": height - 2 * t,
            "width": inner_w,
            "thickness": 3.0,
            "location": [0.0, (depth / 2.0 - 1.5) / 1000.0, height / 2000.0],
            "size": [inner_w / 1000.0, 0.003, (height - 2 * t) / 1000.0],
        })

    # 2. Shelves & Dividers based on family
    inner_h = max(10.0, height - 2 * t)
    num_shelves = rows - 1
    total_shelf_t = num_shelves * t
    opening_h = max(10.0, (inner_h - total_shelf_t) / rows)

    # Horizontal shelves
    curr_z = t
    for i in range(num_shelves):
        curr_z += opening_h
        shelf_center_z = curr_z + t / 2.0
        components.append({
            "componentId": f"shelf_{i+1}",
            "partName": f"第 {i+1} 層固定橫板",
            "role": "shelf",
            "length": inner_w,
            "width": depth,
            "thickness": t,
            "location": [0.0, 0.0, shelf_center_z / 1000.0],
            "size": [inner_w / 1000.0, depth / 1000.0, t / 1000.0],
        })
        curr_z += t

    # Vertical Dividers for Staggered Cubby (MY-012)
    if family == "STAGGERED_OPEN_CUBBY":
        narrow_w = float(resolved.get("labelledNarrowOpeningWidthMm") or 181.5)
        wide_w = float(resolved.get("labelledWideOpeningWidthMm") or 373.5)

        row_bottom_z = t
        for row_idx in range(rows):
            row_top_z = row_bottom_z + opening_h
            divider_center_z = (row_bottom_z + row_top_z) / 2.0

            if row_idx % 2 == 0:
                # Even row: narrow left, wide right
                div_x = -inner_w / 2.0 + narrow_w + t / 2.0
            else:
                # Odd row: wide left, narrow right
                div_x = -inner_w / 2.0 + wide_w + t / 2.0

            components.append({
                "componentId": f"divider_row_{row_idx+1}",
                "partName": f"第 {row_idx+1} 層直立交錯隔板",
                "role": "divider",
                "length": opening_h,
                "width": depth,
                "thickness": t,
                "location": [div_x / 1000.0, 0.0, divider_center_z / 1000.0],
                "size": [t / 1000.0, depth / 1000.0, opening_h / 1000.0],
            })
            row_bottom_z = row_top_z + t

    # Doors for Cabinet Families
    door_count = int(resolved.get("doorCount") or 0)
    if door_count > 0:
        door_w = (inner_w / door_count) - 2.0
        door_h = inner_h - 4.0
        for d_idx in range(door_count):
            dx = -inner_w / 2.0 + (d_idx + 0.5) * (inner_w / door_count)
            components.append({
                "componentId": f"door_{d_idx+1}",
                "partName": f"門片 {d_idx+1}",
                "role": "door",
                "length": door_h,
                "width": door_w,
                "thickness": t,
                "location": [dx / 1000.0, -depth / 2000.0 - t / 2000.0, height / 2000.0],
                "size": [door_w / 1000.0, t / 1000.0, door_h / 1000.0],
            })

    spec = {
        "productId": f"recipe_{sku}",
        "tenantId": tenant_id,
        "sku": sku,
        "name": name,
        "kind": family,
        "family": family,
        "width": width,
        "height": height,
        "depth": depth,
        "thickness": t,
        "boardThickness": t,
        "material": "white_wood",
        "components": components,
        "previewAssumptions": assumptions,
        "shelfCount": num_shelves,
        "doorCount": door_count,
        "compartmentCount": rows * (2 if family == "STAGGERED_OPEN_CUBBY" else 1),
    }
    spec["engineeringHash"] = stable_hash({k: spec[k] for k in spec if k != "productId"})
    return spec


def build_recipe_bom(spec: dict[str, Any]) -> dict[str, Any]:
    """Builds a bill of materials (BOM) from parametric components."""
    lines = []
    for part in spec.get("components") or []:
        lines.append({
            "partId": part.get("componentId") or part.get("partName"),
            "partName": part.get("partName"),
            "role": part.get("role"),
            "lengthMm": part.get("length"),
            "widthMm": part.get("width"),
            "thicknessMm": part.get("thickness"),
            "quantity": 1,
            "material": spec.get("material", "white_wood"),
        })
    return {
        "sku": spec.get("sku"),
        "engineeringHash": spec.get("engineeringHash"),
        "totalParts": len(lines),
        "lines": lines,
    }


def get_recipe_3d_dir(root: Path, tenant_id: str, sku: str) -> Path:
    """Returns the dedicated directory for storing generated 3D assets for a recipe."""
    safe_sku = "".join(c if c.isalnum() or c in "-_" else "_" for c in sku)
    return root / "tenants" / tenant_id / "recipe_3d" / safe_sku


def get_recipe_3d_status(root: Path, tenant_id: str, sku: str) -> dict[str, Any]:
    """Inspects stored 3D assets and returns status, assumptions, and BOM."""
    d = get_recipe_3d_dir(root, tenant_id, sku)
    meta_path = d / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    png_path = d / "beauty.png"
    blend_path = d / "model.blend"
    glb_path = d / "model.glb"
    has_png = png_path.exists() and png_path.stat().st_size > 0
    has_blend = blend_path.exists() and blend_path.stat().st_size > 0
    has_glb = glb_path.exists() and glb_path.stat().st_size > 0
    generated = bool(has_png and meta.get("status") == "succeeded")
    return {
        "generated": generated,
        "sku": sku,
        "tenantId": tenant_id,
        "assets": {
            "png": has_png,
            "blend": has_blend,
            "glb": has_glb,
        },
        "assumptions": meta.get("assumptions") or [],
        "bom": meta.get("bom") or {},
        "spec": meta.get("spec") or {},
        "renderInfo": meta.get("renderInfo") or {},
        "updatedAt": meta.get("updatedAt"),
    }


def generate_recipe_3d_product(
    platform: Any,
    tenant_id: str,
    sku: str,
    draft_data: dict[str, Any],
) -> dict[str, Any]:
    """Generates Blender 3D Cycles rendering, .blend and .glb exports for a recipe product."""
    from fox3d.infra import utcnow

    target_dir = get_recipe_3d_dir(platform.root, tenant_id, sku)
    target_dir.mkdir(parents=True, exist_ok=True)
    spec = build_recipe_spec(draft_data, tenant_id=tenant_id)
    bom = build_recipe_bom(spec)

    is_mock = getattr(platform, "mock_blender", False)
    if is_mock:
        from fox3d.pngutil import write_glb_stub, write_solid_png
        write_solid_png(target_dir / "beauty.png", stable_hash(sku), 800, 800)
        (target_dir / "model.blend").write_bytes(b"BLENDER_MOCK_BLEND")
        write_glb_stub(target_dir / "model.glb", sku)
        render_info = {
            "realBlender": False,
            "realCycles": False,
            "realOptix": False,
            "device": "MOCK",
            "samples": 32,
            "renderTimeSec": 0.05,
        }
    else:
        job = {
            "jobId": f"recipe_3d_{new_id()}",
            "tenantId": tenant_id,
            "mode": "CABINET_PREVIEW",
            "engineering": spec,
            "render": {
                "device": "OPTIX" if (platform.probe and platform.probe.optix) else "CPU",
                "samples": 32,
                "width": 800,
                "height": 800,
            },
            "exportBlend": True,
            "exportGlb": True,
            "workDir": str(target_dir),
        }
        submitted = platform.submit_job(job)
        executed = platform.execute_job(submitted)
        if executed.get("status") not in {"succeeded", "completed"}:
            err = executed.get("error") or "3D rendering failed"
            raise RuntimeError(f"Blender 渲染失敗: {err}")
        render_info = {
            "realBlender": executed.get("realBlender", True),
            "realCycles": executed.get("realCycles", True),
            "realOptix": executed.get("realOptix", False),
            "device": executed.get("device", "CPU"),
            "samples": executed.get("samples", 32),
            "renderTimeSec": executed.get("renderTimeSec", 0.0),
        }
        files = (executed.get("output") or {}).get("files") or {}
        for key, target_filename in [("beauty.png", "beauty.png"), ("model.blend", "model.blend"), ("model.glb", "model.glb")]:
            asset_id = files.get(key)
            if asset_id and hasattr(platform, "dam"):
                try:
                    dam_obj = platform.dam.get(asset_id, tenant_id=tenant_id)
                    if Path(dam_obj.path).exists():
                        shutil.copy2(dam_obj.path, target_dir / target_filename)
                except Exception:
                    pass
            out_path = (executed.get("outputs") or {}).get(key)
            if not (target_dir / target_filename).exists() and out_path and Path(out_path).exists():
                shutil.copy2(out_path, target_dir / target_filename)

    meta = {
        "status": "succeeded",
        "sku": sku,
        "tenantId": tenant_id,
        "spec": spec,
        "bom": bom,
        "assumptions": spec.get("previewAssumptions", []),
        "renderInfo": render_info,
        "updatedAt": str(utcnow()),
    }
    (target_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_recipe_3d_status(platform.root, tenant_id, sku)

