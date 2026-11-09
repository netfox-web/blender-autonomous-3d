"""Admin feature directory: one place that lists every page and API group.

Six pages each carried their own nav and about 60 API routes had no page at all, so
functions were hard to find. This registry drives the shared sidebar
(static/fox3d-shell.js), the searchable directory page (/admin/features) and the
Ctrl+K palette. feature_index() also reports any route that no entry claims, so a new
route can never be silently unreachable (a test keeps that list empty).
"""

from __future__ import annotations

from typing import Any

# kind: "page" = has a screen; "api" = backend only (shown on /admin/features with a read
# button for GET routes); "blocked" = waits on data or a decision outside this repo.
GROUPS: list[dict[str, str]] = [
    {"id": "home", "title": "首頁"},
    {"id": "ecommerce", "title": "電商出圖"},
    {"id": "product", "title": "商品資料"},
    {"id": "print", "title": "圖稿與印刷"},
    {"id": "factory", "title": "工廠與報價"},
    {"id": "pilot", "title": "試產現場"},
    {"id": "render", "title": "3D 算圖與分身"},
    {"id": "release", "title": "上線就緒與放行"},
    {"id": "system", "title": "系統"},
]

FEATURES: list[dict[str, Any]] = [
    # ---- pages -----------------------------------------------------------------------
    {"id": "features", "group": "home", "kind": "page", "icon": "⌕", "title": "功能總覽",
     "href": "/admin/features", "summary": "所有功能的目錄：可搜尋、看狀態，沒有畫面的功能也能直接查資料。",
     "keywords": "目錄 搜尋 全部 功能 地圖", "prefixes": ["/admin/features", "/api/admin/features"]},
    {"id": "control", "group": "home", "kind": "page", "icon": "◎", "title": "系統與算力總控台",
     "href": "/admin", "summary": "Blender／OptiX 狀態、一鍵櫃體設計、算圖成品、數位分身、算圖機與工作列表。",
     "keywords": "總控台 算力 worker 工作 gpu blender optix smoke",
     "prefixes": ["/admin", "/api/e2e/smoke", "/api/parametric/products", "/api/assets"]},
    {"id": "scenes", "group": "ecommerce", "kind": "page", "icon": "▦", "title": "組合櫃 3D 場景工坊",
     "href": "/admin/recipes/scenes", "summary": "拼櫃體 → 擺 3D 房間 → Blender 光追或 GPU 艦隊 AI 實景，批次出多場景、多配色電商圖。",
     "keywords": "場景 電商圖 組合櫃 光追 flux ai 實景 批次 zip 配色",
     "prefixes": ["/admin/recipes/scenes", "/api/ecommerce-scenes"]},
    {"id": "recipes", "group": "product", "kind": "page", "icon": "①", "title": "商品規格庫（Recipe）",
     "href": "/admin/recipes", "summary": "商品尺寸、板材清單、來源資料的建立與編輯；匯入匯出 JSON；Blender 預覽與下載 PNG／GLB。",
     "keywords": "recipe 規格 尺寸 板材 bom 匯入 匯出 預覽 glb",
     "prefixes": ["/admin/recipes", "/api/recipe-library"]},
    {"id": "models", "group": "product", "kind": "page", "icon": "②", "title": "3D 模型與套圖庫",
     "href": "/admin/recipes/models", "summary": "商品 3D 母版的分類、NAS 掃描匯入、場景範本、換圖組合、批次變體與預覽。",
     "keywords": "模型 3d 母版 分類 nas 套圖 組合 批次 變體",
     "prefixes": ["/admin/recipes/models", "/api/product-models"]},
    {"id": "golden", "group": "product", "kind": "page", "icon": "③", "title": "三層櫃 Golden 與 Product DNA",
     "href": "/admin/recipes/golden", "summary": "424×295×900 三層櫃 4 個 SKU：多視角真實算圖、門片裁切、Product DNA 版本與匯出。",
     "keywords": "golden 三層櫃 sku dna 匯出 多視角",
     "prefixes": ["/admin/recipes/golden", "/api/recipe-library/golden", "/api/product-dna"]},
    {"id": "print", "group": "print", "kind": "page", "icon": "④", "title": "圖稿與 UV 印刷工作台",
     "href": "/admin/recipes/print", "summary": "圖稿來源庫、印刷工單、原尺寸 PDF 打樣、人工放行簽核、PrintFox 設計搜尋與生成。",
     "keywords": "印刷 uv 圖稿 打樣 pdf 放行 printfox",
     "prefixes": ["/admin/recipes/print", "/api/print-workspace"]},
    # ---- API only --------------------------------------------------------------------
    {"id": "factory", "group": "factory", "kind": "api", "icon": "⚙", "title": "工廠報價與改版",
     "summary": "依空間產生商品、跑報價、核准報價、改版。", "keywords": "工廠 報價 quote 空間 改版",
     "prefixes": ["/api/factory"]},
    {"id": "kd", "group": "factory", "kind": "api", "icon": "⚙", "title": "拆裝家具（KD）型錄與就緒",
     "summary": "KD 商品類型、SKU、型錄、候選與就緒狀態。", "keywords": "kd 拆裝 型錄 sku 候選 就緒",
     "prefixes": ["/api/kd"]},
    {"id": "materials", "group": "factory", "kind": "api", "icon": "⚙", "title": "材料、餘料與排版",
     "summary": "板材庫存批次、餘料預留、排版（nesting）基準測試。", "keywords": "材料 板材 餘料 庫存 排版 nesting",
     "prefixes": ["/api/materials", "/api/remnants", "/api/nesting"]},
    {"id": "structures", "group": "factory", "kind": "api", "icon": "⚙", "title": "陳列架、包裝結構、壓克力",
     "summary": "零售陳列架、包裝結構、壓克力商品的參數產生。", "keywords": "陳列 包裝 壓克力 retail packaging acrylic",
     "prefixes": ["/api/retail", "/api/packaging", "/api/acrylic"]},
    {"id": "product-rd", "group": "factory", "kind": "api", "icon": "⚙", "title": "商品研發產生",
     "summary": "從需求產生商品研發方案。", "keywords": "研發 rd 產生", "prefixes": ["/api/product-rd"]},
    {"id": "pilot", "group": "pilot", "kind": "api", "icon": "▣", "title": "試產工單與看板",
     "summary": "試產總覽、工單、批次看板、領料預留、收料、請購、匯入匯出。", "keywords": "試產 pilot 工單 看板 批次 收料 請購",
     "prefixes": ["/api/pilot/console", "/api/pilot/work-orders", "/api/pilot/batches", "/api/pilot/receipts",
                  "/api/pilot/purchase-requests", "/api/pilot/import", "/api/pilot/export", "/api/pilot/health"]},
    {"id": "pilot-floor", "group": "pilot", "kind": "api", "icon": "▣", "title": "現場站點、派工與掃碼",
     "summary": "作業員、工作站心跳、派工租約、掃碼、異常清單。", "keywords": "站點 派工 掃碼 作業員 異常 lease",
     "prefixes": ["/api/pilot/operator", "/api/pilot/scan", "/api/pilot/stations", "/api/pilot/dispatch",
                  "/api/pilot/leases", "/api/pilot/exceptions", "/api/pilot/scan-token"]},
    {"id": "physical-os", "group": "pilot", "kind": "api", "icon": "▣", "title": "實體作業 OS",
     "summary": "實體商品家族、就緒狀態、人工核准。", "keywords": "physical os 實體 家族 核准",
     "prefixes": ["/api/physical-os"]},
    {"id": "jobs", "group": "render", "kind": "api", "icon": "◇", "title": "3D 算圖工作排程",
     "summary": "送出、查詢、取消 Blender 算圖工作；預覽與正式算圖。", "keywords": "算圖 job 排程 render 預覽 正式",
     "prefixes": ["/api/3d/jobs", "/api/render"]},
    {"id": "twins", "group": "render", "kind": "api", "icon": "◇", "title": "數位分身",
     "summary": "建立或上傳數位分身、預覽、360 環繞。", "keywords": "數位分身 twin 360 上傳",
     "prefixes": ["/api/digital-twins"]},
    {"id": "readiness", "group": "release", "kind": "api", "icon": "✓", "title": "就緒、證據與放行",
     "summary": "整體就緒狀態、證據驗證、放行推進、安全評估、KPI。", "keywords": "就緒 readiness 證據 放行 安全 kpi",
     "prefixes": ["/api/readiness", "/api/evidence", "/api/release", "/api/safety", "/api/kpi"]},
    {"id": "commerce", "group": "release", "kind": "api", "icon": "✓", "title": "電商商品匯入",
     "summary": "把外部電商商品資料匯入。", "keywords": "電商 匯入 commerce", "prefixes": ["/api/commerce"]},
    {"id": "system", "group": "system", "kind": "api", "icon": "ⓘ", "title": "健康檢查與主機偵測",
     "summary": "服務健康、Blender／GPU 主機偵測結果、API 文件。", "keywords": "health probe 偵測 api 文件 openapi",
     "prefixes": ["/health", "/api/probe", "/docs", "/redoc", "/openapi.json"]},
    # ---- waiting on data or a decision -------------------------------------------------
    {"id": "golden-artwork", "group": "product", "kind": "blocked", "icon": "…", "title": "Golden 歷史圖稿與工程尺寸",
     "summary": "三層櫃 4 個 SKU 還是校正用假圖；板厚、鉸鍊、開孔是估計值，開門視角與排版待補。",
     "waitingFor": "原始圖稿檔、實際工程圖或量測值、板材規格與鋸路寬（Issue #4）", "keywords": "golden 圖稿 工程 板厚 鉸鍊"},
    {"id": "video-gt", "group": "render", "kind": "blocked", "icon": "…", "title": "Blender → 生成影片基準（開門、爆炸圖）",
     "summary": "環繞、細節、小房間三種已能跑；開門 8 秒與組裝爆炸 10 秒、影片供應商串接、商用解析度未完成。",
     "waitingFor": "鉸鍊／組裝的真實資料、Round 3B GO、H3／LTX 執行環境（Issue #6）", "keywords": "影片 video 開門 爆炸圖 h3 ltx"},
    {"id": "dna-live", "group": "product", "kind": "blocked", "icon": "…", "title": "Product DNA 對接外部系統",
     "summary": "匯出契約已完成；ERP、AI Print OS、SpecPilot 的正式編號尚未綁定，也還沒有真實 Blender 匯出。",
     "waitingFor": "ERP／AI Print OS／SpecPilot 的正式編號（Issue #18）", "keywords": "dna erp print os specpilot 對接"},
    {"id": "after-sales", "group": "product", "kind": "blocked", "icon": "…", "title": "售後照片視覺助理",
     "summary": "照片證據比對工程版本、找裝錯或缺件候選。程式在 PR #27，尚未合併。",
     "waitingFor": "PR #27 修完審查意見並通過 CI（Issue #25）", "keywords": "售後 照片 缺件 裝錯"},
]

_SKIP = ("/admin/recipes/assets", "/admin/pages/assets", "/docs/oauth2-redirect")


def _owns(prefix: str, path: str) -> bool:
    if prefix == "/admin":
        return path == "/admin"
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def resolved_features() -> list[dict[str, Any]]:
    """FEATURES with plug-in pages applied: an API group a page module claims becomes a page."""
    from fox3d.admin_pages import page_features

    pages = page_features()
    unknown = set(pages) - {f["id"] for f in FEATURES}
    if unknown:
        raise ValueError(f"plug-in page claims unknown feature ids: {sorted(unknown)}")
    out = []
    for f in FEATURES:
        href = pages.get(f["id"])
        if href:
            f = dict(f, kind="page", href=href, prefixes=[*f.get("prefixes", []), href.split("#")[0]])
        out.append(f)
    return out


def feature_index(routes: list[Any]) -> dict[str, Any]:
    """Registry plus the real routes each feature owns (longest prefix wins), and any route nobody owns."""
    features_now = resolved_features()
    by_feature: dict[str, list[dict[str, str]]] = {f["id"]: [] for f in features_now}
    unclaimed: list[dict[str, str]] = []
    for route in routes:
        path = getattr(route, "path", None)
        methods = sorted(m for m in (getattr(route, "methods", None) or []) if m != "HEAD")
        if not path or not methods or path == "/" or path.startswith(_SKIP):
            continue
        entry = {"path": path, "methods": ",".join(methods)}
        owner, best = None, -1
        for feature in features_now:
            for prefix in feature.get("prefixes", []):
                if _owns(prefix, path) and len(prefix) > best:
                    owner, best = feature["id"], len(prefix)
        if owner:
            by_feature[owner].append(entry)
        else:
            unclaimed.append(entry)
    features = [dict(f, routes=sorted(by_feature[f["id"]], key=lambda r: r["path"])) for f in features_now]
    return {"groups": GROUPS, "features": features, "unclaimed": unclaimed}
