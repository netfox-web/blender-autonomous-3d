"""Versioned product-reference previews; never manufacturing authority."""
from __future__ import annotations

import json
import math
import re
import shutil
import struct
from pathlib import Path
from typing import Any

from fox3d.ids import new_id, stable_hash, sha256_bytes
from fox3d.infra import utcnow
from fox3d.recipe_workbench import ProductDraft, FIELD_LABELS
from fox3d.pngutil import is_png

ADAPTER_VERSION = "recipe-preview-2"
FILES = {"png": "beauty.png", "blend": "model.blend", "glb": "model.glb", "geometry": "geometry.json"}


def input_hash(draft):
    return stable_hash({"adapter": ADAPTER_VERSION, "draft": draft})


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + new_id()[:8] + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve_recipe_preview_assumptions(draft_data: dict[str, Any]) -> dict[str, Any]:
    draft = ProductDraft.model_validate(draft_data)
    values = {k: v.value for k, v in draft.values.items() if v.value is not None and v.value != ""}
    required = ["widthMm", "depthMm", "heightMm", "rowCount", "compartmentCount", "doorCount"]
    missing = [FIELD_LABELS[k] for k in required if k not in values]
    if missing:
        raise ValueError("生成前請先填寫：" + "、".join(missing))
    w, d, h = [float(values[k]) for k in required[:3]]
    rows, cells, doors = [values[k] for k in required[3:]]
    if not all(50 <= n <= 5000 for n in (w, d, h)) or not 1 <= rows <= 24:
        raise ValueError("預覽支援 50–5000 mm 外尺寸及 1–24 行")
    family = draft.family
    if family == "STAGGERED_OPEN_CUBBY" and (cells != rows * 2 or doors != 0):
        raise ValueError("交錯書櫃每行兩格，門片數須為 0")
    if family == "STACKED_HINGED_CABINET" and not rows == cells == doors:
        raise ValueError("上下門櫃每行一格、一片門，請核對行數、格位及門片數")
    if family == "ROW_SLIDING_CABINET" and (cells != rows * 2 or doors != rows):
        raise ValueError("滑門櫃每行兩格、一片滑門，請核對數量")
    assumptions = []
    def assume(key, default, label, note, unit="mm"):
        if key in values:
            return values[key]
        assumptions.append({"field": key, "value": default, "unit": unit, "label": label,
                            "note": note, "source": "PREVIEW_ASSUMPTION"})
        return default
    tkey = "sidePanelThicknessMm" if family == "ROW_SLIDING_CABINET" else "panelThicknessMm"
    t = float(assume(tkey, 15, "側板厚度", "預覽暫用 15 mm，待圖面確認"))
    fixed = float(values.get("fixedPanelThicknessMm", t))
    if "fixedPanelThicknessMm" not in values and family == "ROW_SLIDING_CABINET":
        assumptions.append({"field": "fixedPanelThicknessMm", "value": fixed, "unit": "mm", "label": "固定板厚度", "note": "頂板、底板與橫板暫採側板厚度", "source": "PREVIEW_ASSUMPTION"})
    back = float(assume("backThicknessMm", 0 if family == "STAGGERED_OPEN_CUBBY" else 3,
                        "背板", "未提供背板圖面；開放櫃暫不建背板，門櫃暫用 3 mm"))
    dt = float(assume("doorThicknessMm", t, "門板厚度", "預覽暫採側板厚度")) if doors else 0
    gap = float(assume("doorGapsMm", 2, "門片間隙", "預覽暫留 2 mm")) if doors else 0
    inner_w = w - 2*t
    opening = (h - (rows+1)*fixed) / rows
    if min(inner_w, opening, d-back-dt-gap) <= 10 or max(t, fixed, back, dt) > 100:
        raise ValueError("板件厚度與外尺寸不相容，請確認厚度或行數")
    dividers = []
    if family == "STAGGERED_OPEN_CUBBY":
        raw = values.get("rowDividerCoordinates", "")
        if raw:
            try:
                dividers = [float(v) for v in re.split(r"[,，;；\s]+", raw.strip()) if v]
            except ValueError as exc:
                raise ValueError("隔板座標請填每行隔板中心距左內壁的 mm，以逗號分隔，由下往上") from exc
            if len(dividers) != rows:
                raise ValueError(f"請填 {rows} 個隔板中心座標，由下往上，以逗號分隔")
        else:
            narrow = float(values.get("labelledNarrowOpeningWidthMm", (inner_w-t)/3))
            dividers = [narrow+t/2 if i%2 == 0 else inner_w-narrow-t/2 for i in range(rows)]
            assumptions.append({"field": "rowDividerCoordinates", "value": ", ".join(f"{x:.1f}" for x in dividers), "unit": "mm", "label": "各行隔板中心", "note": "由下往上，距左內壁；依窄格標示或三分之一比例交錯鏡像，待逐行圖面確認", "source": "PREVIEW_ASSUMPTION"})
        if any(not math.isfinite(x) or x-t/2 <= 0 or x+t/2 >= inner_w for x in dividers):
            raise ValueError("隔板座標超出內寬，請確認每行中心位置")
    elif family == "ROW_SLIDING_CABINET":
        dividers = [inner_w/2] * rows
        travel = float(assume("slideTravelMm", (inner_w-t)/2, "滑門行程", "僅供預覽；軌道與實際行程仍需圖面確認"))
        if travel > inner_w:
            raise ValueError("滑門行程不可超出櫃內寬")
    assumptions.extend([
        {"field": "rowHeights", "value": round(opening, 2), "unit": "mm", "label": "每行淨高", "note": "依外高與橫板厚度等分；局部圖示內徑保留為參考，未取代本次推導", "source": "PREVIEW_ASSUMPTION"},
        {"field": "hardware", "value": "簡化外觀", "unit": "", "label": "接合與五金", "note": "未模擬接合、鉸鏈、滑軌、開門行程與承重；滑門固定在左側，板件表不可直接作為裁切單", "source": "PREVIEW_ASSUMPTION"},
        {"field": "finish", "value": "淺木色", "unit": "", "label": "預覽材質", "note": "使用示意木色，未還原實際表面紋理", "source": "PREVIEW_ASSUMPTION"},
    ])
    return {"resolved": {"widthMm": w, "depthMm": d, "heightMm": h, "boardThicknessMm": t,
                        "fixedPanelThicknessMm": fixed, "backThicknessMm": back, "backPanel": back > 0,
                        "doorThicknessMm": dt, "doorGapsMm": gap, "rowCount": rows,
                        "compartmentCount": cells, "doorCount": doors, "dividerCentersMm": dividers,
                        "openingHeightMm": opening}, "assumptions": assumptions}


def build_recipe_spec(draft_data, *, tenant_id="default"):
    plan = resolve_recipe_preview_assumptions(draft_data)
    r = plan["resolved"]
    w,d,h,t,f,b,dt,g,rows = [r[k] for k in ("widthMm","depthMm","heightMm","boardThicknessMm","fixedPanelThicknessMm","backThicknessMm","doorThicknessMm","doorGapsMm","rowCount")]
    iw, oh = w-2*t, r["openingHeightMm"]
    front = dt+g if r["doorCount"] else 0
    inside_depth = d-b-front
    inside_y = (front-b)/2
    components = []
    def part(pid, label, role, size, loc, row=None):
        components.append({"componentId": pid, "partName": label, "role": role, "row": row,
                           "size": [v/1000 for v in size], "location": [v/1000 for v in loc],
                           "length": max(size), "width": sorted(size)[1], "thickness": min(size)})
    part("left_side","左側板","left",[t,d,h],[-w/2+t/2,0,h/2])
    part("right_side","右側板","right",[t,d,h],[w/2-t/2,0,h/2])
    part("top_panel","頂板","top",[iw,d,f],[0,0,h-f/2])
    part("bottom_panel","底板","bottom",[iw,d,f],[0,0,f/2])
    if b:
        part("back_panel","背板","back",[iw,b,h-2*f],[0,d/2-b/2,h/2])
    for row in range(rows):
        z = f + row*(oh+f) + oh/2
        if row < rows-1:
            part(f"shelf_{row+1}",f"橫板 {row+1}","shelf",[iw,inside_depth,f],[0,inside_y,z+oh/2+f/2])
        if r["dividerCentersMm"]:
            x = -iw/2+r["dividerCentersMm"][row]
            part(f"divider_row_{row+1}",f"第 {row+1} 行隔板","divider",[t,inside_depth,oh],[x,inside_y,z],row+1)
        if r["doorCount"]:
            sliding = draft_data["family"] == "ROW_SLIDING_CABINET"
            dw = (iw-t)/2-2*g if sliding else iw-2*g
            dh = oh-2*g
            if min(dw,dh) <= 5:
                raise ValueError("門片間隙過大，已無可用門片尺寸")
            x = -(iw+t)/4 if sliding else 0
            part(f"door_{row+1}",f"第 {row+1} 行"+("滑門" if sliding else "門片"),"door",[dw,dt,dh],[x,-d/2+dt/2,z],row+1)
    spec = {"productId": "recipe_"+draft_data["sku"], "tenantId": tenant_id, "sku": draft_data["sku"],
            "name": draft_data["name"], "kind": draft_data["family"], "family": draft_data["family"],
            "width": w, "depth": d, "height": h, "thickness": t, "material": "white_wood",
            "components": components, "previewAssumptions": plan["assumptions"], "recipePreview": True,
            "shelfCount": rows-1, "doorCount": r["doorCount"], "compartmentCount": r["compartmentCount"],
            "adapterVersion": ADAPTER_VERSION, "engineeringReady": False, "productionReady": False}
    spec["previewHash"] = stable_hash(spec)
    return spec


def build_recipe_bom(spec):
    return {"sku": spec["sku"], "previewHash": spec["previewHash"], "scope": "PREVIEW_PARTS_ONLY",
            "totalParts": len(spec["components"]), "lines": [
                {"partId": p["componentId"], "partName": p["partName"], "role": p["role"],
                 "lengthMm": p["length"], "widthMm": p["width"], "thicknessMm": p["thickness"],
                 "quantity": 1, "material": "示意木色"} for p in spec["components"]]}


def get_recipe_3d_dir(root, tenant_id, sku):
    # Hash the pair together to keep Windows paths short; no user text enters paths.
    return Path(root)/"recipe-previews"/stable_hash({"tenant": tenant_id, "sku": sku})[:32]


def verified_assets(folder, meta):
    result = {}
    for fmt,name in FILES.items():
        expected = (meta.get("files") or {}).get(fmt) or {}
        path = folder/name
        try:
            result[fmt] = bool(expected.get("sha256") and path.is_file() and path.stat().st_size == expected.get("sizeBytes") and sha256_bytes(path.read_bytes()) == expected["sha256"])
        except OSError:
            result[fmt] = False
    return result


def get_recipe_3d_status(root, tenant_id, sku, *, current_draft=None):
    folder = get_recipe_3d_dir(root,tenant_id,sku)
    meta = read_json(folder/"meta.json")
    gid = meta.get("generationId", "")
    valid_id = bool(re.fullmatch(r"[a-f0-9-]{36}", gid))
    assets = verified_assets(folder/"generations"/gid,meta) if valid_id else {k:False for k in FILES}
    generated = bool(all(assets.values()) and meta.get("renderInfo",{}).get("realBlender") and not meta.get("renderInfo",{}).get("usedMock"))
    state = read_json(folder/"state.json")
    if meta and not generated and state.get("state", "idle") in {"idle", "succeeded"}:
        state.update(state="failed", error="成果檔案驗證失敗，請重新生成。")
    stale = bool(current_draft and meta and meta.get("inputHash") != input_hash(current_draft))
    return {"sku":sku,"tenantId":tenant_id,"generated":generated,"assets":assets,"generationId":gid,
            "stale":stale,"state":state.get("state","idle"),"error":state.get("error"),
            "progress":state.get("progress",0),"taskId":state.get("taskId"),
            "assumptions":meta.get("assumptions",[]),"bom":meta.get("bom",{}),"spec":meta.get("spec",{}),
            "renderInfo":meta.get("renderInfo",{}),"updatedAt":meta.get("updatedAt"),
            "sourceRevision":meta.get("sourceRevision"),"inputHash":meta.get("inputHash"),
            "engineeringReady":False,"productionReady":False}


def validate_outputs(folder, spec):
    png = (folder/"beauty.png").read_bytes()
    if not is_png(png) or struct.unpack(">II",png[16:24]) != (800,800):
        raise ValueError("渲染圖片格式或尺寸錯誤")
    blend = (folder/"model.blend").read_bytes()
    if len(blend)<100 or not blend.startswith(b"BLENDER"):
        raise ValueError("Blender 模型檔案不完整")
    glb = (folder/"model.glb").read_bytes()
    if len(glb)<20 or struct.unpack("<4sII",glb[:12]) != (b"glTF",2,len(glb)):
        raise ValueError("GLB 模型檔案不完整")
    chunk_len, chunk_type = struct.unpack("<II",glb[12:20])
    graph = json.loads(glb[20:20+chunk_len])
    if chunk_type != 0x4e4f534a or not graph.get("meshes") or len(graph.get("meshes",[])) != len(spec["components"]):
        raise ValueError("GLB 缺少商品板件")
    actual = read_json(folder/"geometry.json")
    parts = {p["componentId"]:p for p in actual.get("parts",[])}
    if len(parts) != len(spec["components"]):
        raise ValueError("Blender 實際板件數量不一致")
    for p in spec["components"]:
        observed = parts.get(p["componentId"],{})
        for key in ("size","location"):
            if len(observed.get(key,[]))!=3 or any(abs(a-b)>1e-5 for a,b in zip(observed[key],p[key])):
                raise ValueError("Blender 實際板件尺寸或位置不一致："+p["partName"])
    return {fmt:{"sha256":sha256_bytes((folder/name).read_bytes()),"sizeBytes":(folder/name).stat().st_size} for fmt,name in FILES.items()}


def generate_recipe_3d_product(platform, tenant_id, sku, draft_data, *, revision=0, generation_id=None, on_job=None, cancel_flag=None,
                               spec_builder=build_recipe_spec, folder_builder=get_recipe_3d_dir, status_builder=get_recipe_3d_status):
    if getattr(platform,"mock_blender",True) or not platform.runtime.available():
        raise RuntimeError("找不到可用的 Blender。請安裝 Blender 後重新啟動工作台")
    gid = generation_id or new_id()
    folder = folder_builder(platform.root,tenant_id,sku)
    target = folder/"generations"/gid
    target.mkdir(parents=True,exist_ok=False)
    spec = spec_builder(draft_data,tenant_id=tenant_id)
    job = platform.submit_job({"tenantId":tenant_id,"jobType":"PARAMETRIC_3D","mode":"CABINET_PREVIEW",
        "engineering":spec,"render":{"device":"OPTIX" if platform.probe and platform.probe.optix else "CPU","samples":32,"width":800,"height":800},
        "exportBlend":True,"exportGlb":True,"recipePreview":True,"maxAttempts":1,"timeoutSeconds":600})
    if on_job:
        on_job(job)
    executed = platform.execute_job(job,cancel_flag=cancel_flag)
    if executed.get("status") not in {"succeeded","completed"} or not executed.get("realBlender") or executed.get("usedMock"):
        if executed.get("status")=="cancelled":
            raise RuntimeError("使用者已取消生成")
        raise RuntimeError("Blender 未完成生成："+str(executed.get("error") or executed.get("status")))
    files = (executed.get("output") or {}).get("files") or {}
    for name in FILES.values():
        asset_id = files.get(name)
        if not asset_id:
            raise ValueError("生成結果缺少 "+name)
        asset = platform.dam.get(asset_id,tenant_id=tenant_id)
        shutil.copy2(asset.path,target/name)
    hashes = validate_outputs(target,spec)
    output = executed.get("output") or {}
    info = {k:output.get(k,executed.get(k)) for k in ("realBlender","realOptix","usedMock","device","samples","renderTimeSec","blenderVersion")}
    meta = {"generationId":gid,"sku":sku,"tenantId":tenant_id,"sourceRevision":revision,
            "inputHash":input_hash(draft_data),"spec":spec,"bom":build_recipe_bom(spec),"files":hashes,
            "assumptions":spec["previewAssumptions"],"renderInfo":info,"updatedAt":str(utcnow()),
            "engineeringReady":False,"productionReady":False}
    atomic_json(target/"meta.json",meta)
    atomic_json(folder/"meta.json",meta)
    return status_builder(platform.root,tenant_id,sku,current_draft=draft_data)
