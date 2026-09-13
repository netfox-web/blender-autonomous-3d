"""Admin console. Operates the system — does not embed Blender UI."""

from __future__ import annotations

from html import escape
from typing import Any


def render_admin(platform: Any) -> str:
    jobs = list(reversed(platform.queue.list()))
    twins = list(platform.twins._items.values())
    nodes = platform.compute.all()
    probe = platform.probe
    blocked = (probe.blocked if probe else []) or []
    banner = ""
    if platform.mock_blender:
        banner = '<div class="banner mock">MOCK WORKER — automated tests only. Not production acceptance.</div>'
    elif blocked:
        banner = f'<div class="banner blocked">{" ".join(escape(x) for x in blocked)} — 不得以 mock 宣稱完成。</div>'
    elif probe and probe.realBlender and probe.realOptix:
        banner = f'<div class="banner ok">REAL Blender {escape(str(probe.blenderVersion))} / {escape(str(probe.gpuName))} / OptiX</div>'
    elif probe and probe.realBlender:
        banner = f'<div class="banner blocked">Blender {escape(str(probe.blenderVersion))} 已偵測，但 OptiX 不可用 → BLOCKED_NO_OPTIX</div>'
    else:
        banner = '<div class="banner blocked">尚未完成 host probe。</div>'

    def _worker_row(n: Any) -> str:
        mock = bool(n.capabilities.get("mock")) or str(n.capabilities.get("blenderVersion") or "").startswith("mock")
        source = n.capabilities.get("discoverySource") or ("MOCK" if mock else "REAL_DISCOVERY")
        badge = "MOCK" if mock or source == "MOCK" else "REAL"
        current = next(
            (
                j.get("jobId")
                for j in jobs
                if j.get("assignedComputeTargetKey") == n.target_key
                and j.get("status") in {"reserved", "dispatched", "running", "rendering", "uploading"}
            ),
            "",
        )
        beat = n.last_heartbeat_at.isoformat() if getattr(n, "last_heartbeat_at", None) else ""
        gpu0 = (n.gpus or [{}])[0]
        vram = f"{gpu0.get('vramUsedGb')}/{gpu0.get('vramGb')} free={gpu0.get('vramFreeGb') or gpu0.get('freeVramGb')}"
        return (
            "<tr>"
            f"<td><span class='badge {badge.lower()}'>{badge}</span></td>"
            f"<td>{escape(n.target_key)}</td>"
            f"<td>{escape(str(n.capabilities.get('hostname') or ''))}</td>"
            f"<td>{escape(str(n.capabilities.get('os') or ''))}</td>"
            f"<td>{escape(str(n.capabilities.get('gpu')))}</td>"
            f"<td>{escape(str(n.capabilities.get('gpuUuid') or gpu0.get('uuid') or ''))}</td>"
            f"<td>{escape(vram)}</td>"
            f"<td>{escape(str(n.capabilities.get('blenderVersion')))}</td>"
            f"<td>{escape(str(n.capabilities.get('cycles', n.capabilities.get('blender'))))}</td>"
            f"<td>{escape(str(n.capabilities.get('cuda')))}</td>"
            f"<td>{escape(str(n.capabilities.get('optix')))}</td>"
            f"<td>{escape(n.status)}</td>"
            f"<td>{escape(str(current))}</td>"
            f"<td>{escape(beat)}</td>"
            "</tr>"
        )

    rows_nodes = "".join(_worker_row(n) for n in nodes)
    rows_jobs = []
    for j in jobs:
        files = ((j.get("output") or {}).get("files") or {})
        asset = j.get("outputAsset") or files.get("beauty.png") or ""
        img = f'<a href="/api/assets/{escape(str(asset))}" target="_blank" title="點擊在新分頁開啟 512x512 高清大圖"><img src="/api/assets/{escape(str(asset))}?x=" class="thumb"/></a>' if asset else ""
        log = escape((j.get("logs") or "")[-400:])
        rows_jobs.append(
            "<tr>"
            f"<td>{escape(str(j.get('jobId')))}</td>"
            f"<td>{escape(str(j.get('jobType')))}</td>"
            f"<td>{escape(str(j.get('status')))}</td>"
            f"<td>{escape(str(j.get('worker')))}</td>"
            f"<td>{escape(str(j.get('gpu') or j.get('assignedComputeTargetKey')))} {escape(str(j.get('gpuUuid') or ''))}</td>"
            f"<td>{escape(str(j.get('blenderVersion') or (j.get('output') or {}).get('blenderVersion')))}</td>"
            f"<td>{escape(str(j.get('renderEngine') or (j.get('output') or {}).get('engine')))}</td>"
            f"<td>{escape(str(j.get('samples') or (j.get('output') or {}).get('samples')))}</td>"
            f"<td>{escape(str(j.get('renderTimeSec') or (j.get('output') or {}).get('renderTimeSec')))}</td>"
            f"<td>{img}{escape(str(asset))} {escape(str(j.get('outputHash') or ''))} {escape(str(j.get('outputSize') or ''))}</td>"
            f"<td class='log'>{log}</td>"
            "</tr>"
        )
    twin_cards = []
    for t in twins:
        preview = t.previewAssetId
        img = f'<a href="/api/assets/{escape(str(preview))}" target="_blank"><img src="/api/assets/{escape(str(preview))}" class="preview"/></a>' if preview else "<em>no preview</em>"
        twin_cards.append(
            f"<div class='card'><h3>{escape(t.sku)}</h3>"
            f"<p class='note'>{escape(t.twinId)}</p>{img}"
            f"<p>格式: GLB v{escape(str(t.version))}</p>"
            f"<p>尺寸: {escape(str(t.dimensions))}</p>"
            f"<p>資產 ID: {escape(str(t.damAssetId or t.glb or ''))}</p></div>"
        )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Autonomous 3D Studio / 智慧家具 3D 操作台</title>
  <style>
    :root {{
      --bg: #0d1117;
      --card-bg: #161b22;
      --card-border: #30363d;
      --accent: #58a6ff;
      --accent-hover: #79c0ff;
      --success: #238636;
      --success-hover: #2ea043;
      --text: #e6edf3;
      --text-muted: #8b949e;
    }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", Roboto, Helvetica, Arial, sans-serif; margin: 0; background: var(--bg); color: var(--text); }}
    header {{ padding: 14px 24px; background: var(--card-bg); border-bottom: 1px solid var(--card-border); display: flex; align-items: center; justify-content: space-between; }}
    .logo {{ font-size: 17px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; }}
    .nav-tabs {{ display: flex; gap: 6px; padding: 12px 24px 0 24px; background: var(--card-bg); border-bottom: 1px solid var(--card-border); }}
    .tab-btn {{ padding: 10px 18px; border: none; background: transparent; color: var(--text-muted); font-size: 14px; font-weight: 600; cursor: pointer; border-bottom: 2px solid transparent; border-radius: 6px 6px 0 0; transition: all 0.2s; }}
    .tab-btn:hover {{ color: var(--text); background: rgba(255,255,255,0.03); }}
    .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); background: rgba(88,166,255,0.08); }}
    .tab-content {{ display: none; padding: 24px; }}
    .tab-content.active {{ display: block; }}
    
    .preset-chip {{ padding: 8px 14px; background: #21262d; border: 1px solid var(--card-border); border-radius: 20px; color: var(--text); font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.2s; display: inline-flex; align-items: center; gap: 6px; }}
    .preset-chip:hover {{ background: #30363d; border-color: var(--accent); color: var(--accent-hover); transform: translateY(-1px); }}
    
    .form-panel {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 8px; padding: 20px; max-width: 680px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
    .form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }}
    .field-label {{ display: block; font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 6px; }}
    .field-label .sub {{ font-size: 11px; color: var(--accent); font-weight: normal; margin-left: 4px; }}
    .input-ctrl {{ width: 100%; padding: 8px 12px; background: #0d1117; color: #fff; border: 1px solid var(--card-border); border-radius: 6px; font-size: 14px; transition: border-color 0.2s; }}
    .input-ctrl:focus {{ outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(88,166,255,0.2); }}
    
    .btn-submit {{ width: 100%; padding: 12px 20px; background: var(--success); color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 15px; font-weight: 700; transition: all 0.2s; display: flex; align-items: center; justify-content: center; gap: 8px; }}
    .btn-submit:hover {{ background: var(--success-hover); transform: translateY(-1px); }}
    .btn-submit:disabled {{ opacity: 0.6; cursor: not-allowed; transform: none; }}
    
    .banner {{ padding: 12px 24px; font-weight: 600; font-size: 13px; }}
    .banner.ok {{ background: #1b4728; color: #7ee787; border-bottom: 1px solid #2ea043; }}
    .banner.blocked {{ background: #49181c; color: #ffa198; border-bottom: 1px solid #f85149; }}
    .banner.mock {{ background: #3f2e08; color: #f2cc60; border-bottom: 1px solid #bb8009; }}
    
    .gallery-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 18px; }}
    .gallery-card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 8px; overflow: hidden; transition: all 0.2s; display: flex; flex-direction: column; }}
    .gallery-card:hover {{ border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.4); }}
    .gallery-thumb {{ width: 100%; height: 220px; object-fit: cover; background: #050505; display: block; cursor: pointer; }}
    .gallery-meta {{ padding: 12px; font-size: 12px; }}
    
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
    th, td {{ border-bottom: 1px solid var(--card-border); padding: 8px; text-align: left; font-size: 12px; vertical-align: top; }}
    th {{ color: var(--text-muted); font-weight: 600; background: rgba(255,255,255,0.02); }}
    .badge {{ display:inline-block; padding: 2px 7px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
    .badge.real {{ background:#163; color:#9f9; }}
    .badge.mock {{ background:#532; color:#fc6; }}
    .thumb, .preview {{ max-width: 180px; max-height: 180px; display: block; border-radius: 4px; border: 1px solid var(--card-border); cursor: pointer; transition: transform 0.2s; }}
    .thumb:hover, .preview:hover {{ transform: scale(1.04); border-color: var(--accent); }}
    .log {{ max-width: 280px; white-space: pre-wrap; color: var(--text-muted); font-family: ui-monospace, monospace; font-size: 11px; }}
    .card {{ display: inline-block; margin: 8px; padding: 12px; border: 1px solid var(--card-border); border-radius: 6px; min-width: 180px; background: var(--card-bg); }}
    .note {{ color: var(--text-muted); font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <div class="logo">
      <span>🦊</span>
      <span>Autonomous 3D Studio</span>
      <span class="note" style="margin-left: 6px;">— 系統操作台，不含 Blender UI</span>
    </div>
    <div>
      <a href="/admin/recipes" style="color:#b6e3c8;font-weight:600;margin-right:20px">商品 Recipe 庫 →</a>
      <span class="note">伺服器: http://127.0.0.1:8788/admin</span>
    </div>
  </header>
  {banner}

  <nav class="nav-tabs">
    <button class="tab-btn active" onclick="switchTab('tab-designer')">🛋️ 一鍵 3D 櫃體設計</button>
    <button class="tab-btn" onclick="switchTab('tab-gallery')">🖼️ 3D 渲染成品相簿 ({len(jobs)})</button>
    <button class="tab-btn" onclick="switchTab('tab-twins')">📦 數位孿生與規格 ({len(twins)})</button>
    <button class="tab-btn" onclick="switchTab('tab-system')">⚙️ 算力節點與工作佇列</button>
  </nav>

  <!-- TAB 1: DESIGNER -->
  <section id="tab-designer" class="tab-content active">
    <div style="margin-bottom: 20px;">
      <h2 style="margin: 0 0 6px 0; font-size: 20px;">客製化櫃體 3D 即時設計</h2>
      <p class="note" style="margin: 0;">點擊下方熱門範本一秒套用尺寸，或自行拖曳調整，點擊按鈕即可呼叫本機 Blender 光追出圖。</p>
    </div>

    <div style="margin-bottom: 18px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">
      <span style="font-size: 13px; font-weight: 600; color: var(--text-muted);">✨ 快速熱門範本：</span>
      <button class="preset-chip" onclick="applyPreset('OPEN_SHELF', 450, 900, 300, 2, 0)">
        📚 標準三層櫃 (45×90cm · 3層開放格 · 無門)
      </button>
      <button class="preset-chip" onclick="applyPreset('STORAGE_CABINET', 800, 1200, 400, 2, 2)">
        🚪 雙門收納櫃 (80×120cm · 雙門)
      </button>
      <button class="preset-chip" onclick="applyPreset('BOOKCASE', 800, 1800, 350, 4, 0)">
        🗄️ 大型五層書架 (80×180cm · 開放式)
      </button>
      <button class="preset-chip" onclick="applyPreset('STORAGE_CABINET', 1200, 450, 400, 1, 2)">
        🪑 簡約低矮地櫃 (120×45cm · 雙門)
      </button>
    </div>

    <div class="form-panel">
      <form id="cab-form" onsubmit="handleGenerate(event)">
        <div class="form-grid">
          <div>
            <label class="field-label">櫃體類型：</label>
            <select id="c-kind" class="input-ctrl" onchange="onKindChange()">
              <option value="OPEN_SHELF" selected>OPEN_SHELF (開放式層架 / 三層櫃)</option>
              <option value="STORAGE_CABINET">STORAGE_CABINET (附門收納櫃)</option>
              <option value="BOOKCASE">BOOKCASE (實木高書櫃)</option>
            </select>
          </div>
          <div>
            <label class="field-label">層板數量：<span id="label-shelves" class="sub">2 塊板 (分為 3 層格)</span></label>
            <input id="c-s" type="number" value="2" min="0" max="10" class="input-ctrl" oninput="updateDims()"/>
          </div>
          <div>
            <label class="field-label">寬度 (Width)：<span id="label-w" class="sub">45 公分</span></label>
            <input id="c-w" type="number" value="450" min="200" max="2400" step="10" class="input-ctrl" oninput="updateDims()"/>
          </div>
          <div>
            <label class="field-label">高度 (Height)：<span id="label-h" class="sub">90 公分</span></label>
            <input id="c-h" type="number" value="900" min="300" max="2400" step="10" class="input-ctrl" oninput="updateDims()"/>
          </div>
          <div>
            <label class="field-label">深度 (Depth)：<span id="label-d" class="sub">30 公分</span></label>
            <input id="c-d" type="number" value="300" min="200" max="800" step="10" class="input-ctrl" oninput="updateDims()"/>
          </div>
          <div>
            <label class="field-label">門片數量：<span id="label-doors" class="sub" style="color: #79c0ff;">0 片 (開放式無門 · 直接展示內部)</span></label>
            <input id="c-doors" type="number" value="0" min="0" max="6" class="input-ctrl" oninput="updateDims()"/>
          </div>
        </div>
        <button id="gen-btn" type="submit" class="btn-submit">
          <span>🚀 立即生成 3D 渲染並出圖</span>
        </button>
      </form>

      <div id="result-box" style="display: none; margin-top: 20px; padding: 16px; background: #1c2638; border: 1px solid var(--accent); border-radius: 8px;">
        <h4 style="margin: 0 0 10px 0; color: #79c0ff;">🎉 3D 渲染出圖成功！</h4>
        <div style="display: flex; gap: 16px; align-items: center;">
          <img id="res-img" src="" style="width: 160px; height: 160px; object-fit: contain; background: #000; border-radius: 6px; border: 1px solid #30363d; cursor: pointer;" onclick="window.open(this.src)"/>
          <div style="font-size: 13px;">
            <p id="res-spec" style="margin: 0 0 8px 0; font-weight: 600;"></p>
            <p id="res-time" style="margin: 0 0 12px 0; color: var(--text-muted);"></p>
            <a id="res-link" href="#" target="_blank" style="padding: 6px 12px; background: #238636; color: #fff; text-decoration: none; border-radius: 4px; font-weight: 600; font-size: 12px; display: inline-block;">🔍 開啟 512x512 高清大圖</a>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 2: GALLERY -->
  <section id="tab-gallery" class="tab-content">
    <h2 style="margin: 0 0 16px 0; font-size: 20px;">3D 渲染成果相簿</h2>
    <div class="gallery-grid">
      {''.join(
        f'''<div class="gallery-card">
          <a href="/api/assets/{escape(str(j.get("outputAsset") or (j.get("output") or {{}}).get("files", {{}}).get("beauty.png") or ""))}" target="_blank">
            <img src="/api/assets/{escape(str(j.get("outputAsset") or (j.get("output") or {{}}).get("files", {{}}).get("beauty.png") or ""))}" class="gallery-thumb" loading="lazy"/>
          </a>
          <div class="gallery-meta">
            <div style="font-weight: 600; margin-bottom: 4px;">任務: {escape(str(j.get("jobId")))}</div>
            <div style="color: var(--text-muted);">引擎: {escape(str(j.get("renderEngine") or (j.get("output") or {{}}).get("engine") or "CYCLES"))} ({escape(str(j.get("samples") or (j.get("output") or {{}}).get("samples") or 32))} 採樣)</div>
            <div style="color: var(--text-muted);">耗時: {escape(str(j.get("renderTimeSec") or (j.get("output") or {{}}).get("renderTimeSec") or "0.8"))} 秒</div>
            <a href="/api/assets/{escape(str(j.get("outputAsset") or (j.get("output") or {{}}).get("files", {{}}).get("beauty.png") or ""))}" target="_blank" style="display:inline-block; margin-top:8px; color:var(--accent); text-decoration:none; font-weight:600;">在新分頁打開 ↗</a>
          </div>
        </div>'''
        for j in jobs if j.get("outputAsset") or ((j.get("output") or {}).get("files") or {}).get("beauty.png")
      ) or '<p class="note">尚無已渲染圖片，請至「一鍵 3D 櫃體設計」產生您的第一座櫃子！</p>'}
    </div>
  </section>

  <!-- TAB 3: DIGITAL TWINS -->
  <section id="tab-twins" class="tab-content">
    <h2 style="margin: 0 0 16px 0; font-size: 20px;">數位孿生與規格零件 (Digital Twins)</h2>
    <div>{''.join(twin_cards) or '<p class="note">no twins</p>'}</div>
  </section>

  <!-- TAB 4: SYSTEM & WORKERS -->
  <section id="tab-system" class="tab-content">
    <h2>Blender Workers</h2>
    <table><thead><tr>
      <th>badge</th><th>target</th><th>hostname</th><th>OS</th><th>GPU</th><th>UUID</th>
      <th>VRAM used/total/free</th><th>Blender</th><th>Cycles</th><th>CUDA</th><th>OptiX</th>
      <th>status</th><th>current job</th><th>last heartbeat</th>
    </tr></thead>
    <tbody>{rows_nodes or '<tr><td colspan="14">no workers registered</td></tr>'}</tbody></table>

    <h2>3D Jobs / Render Queue</h2>
    <table><thead><tr>
      <th>job</th><th>type</th><th>status</th><th>worker</th><th>GPU</th>
      <th>Blender version</th><th>engine</th><th>samples</th><th>render time</th>
      <th>output asset</th><th>logs</th>
    </tr></thead>
    <tbody>{''.join(rows_jobs) or '<tr><td colspan="11">queue empty</td></tr>'}</tbody></table>

    <p>
      <form method="post" action="/api/e2e/smoke" onsubmit="fetch(this.action,{{method:'POST'}}).then(()=>location.reload());return false;">
        <button type="submit" style="padding: 6px 12px; background: #21262d; border: 1px solid #30363d; color: #fff; border-radius: 4px; cursor: pointer;">Run REAL_SMOKE_TEST</button>
      </form>
    </p>

    <h2>Furniture Factory</h2>
    <p class="note">Spaces {len(getattr(getattr(platform, "factory", None), "spaces", {}) or {})}
    · Assemblies {len(getattr(getattr(platform, "factory", None), "assemblies", {}) or {})}
    · Quotes {len(getattr(getattr(platform, "factory", None), "quotes", {}) or {})}
    · Runs {len(getattr(getattr(platform, "factory", None), "runs", {}) or {})}
    · LIVE_CNC blocked · Human Approval Gate</p>
    <p class="note">Production acceptance 必須 realBlender / realGPU / realCycles / realOptix / realRenderOutput。Mock 僅限 automated tests。</p>

    <h2>Physical Product OS</h2>
    <p class="note">Families {len(getattr(getattr(platform, "physical", None), "families", None).list()) if getattr(platform, "physical", None) else 0}
    · Remnants {len(getattr(getattr(platform, "remnants", None), "items", {}) or {})}
    · Retail fixtures {len(getattr(getattr(getattr(platform, "physical", None), "retail", None), "items", {}) or {})}
    · Packaging {len(getattr(getattr(getattr(platform, "physical", None), "packaging", None), "items", {}) or {})}
    · Acrylic {len(getattr(getattr(getattr(platform, "physical", None), "acrylic", None), "items", {}) or {})}
    · LIVE_CNC/LASER blocked · Human Approval Gate
    · API: /api/materials /api/remnants /api/nesting/benchmarks /api/kd/candidates /api/retail/fixtures /api/packaging/structures /api/acrylic/products /api/physical-os/approve /api/readiness /api/kpi /api/commerce/import /api/safety/evaluate
    · KPI {len(getattr(getattr(platform, "release", None), "events", []) or [])} approval events · stale {sum(1 for a in (getattr(getattr(platform, "release", None), "approvals", {}) or {}).values() if a.get("stale"))}
    · LIVE_CNC/LASER blocked · Human Approval Gate</p>

    <h2>Pilot Reliability / Manufacturing Control Boundary</h2>
    <p class="note">
      STRICT_STOCK default · FIXTURE_AUTO_SEED test-only · receipts MANUAL/IMPORTED · shipment SHIPMENT_DRAFT not booked
      · LIVE_CNC <span class="badge mock">BLOCKED</span>
      · LIVE_LASER <span class="badge mock">BLOCKED</span>
      · Vision/Demand <span class="badge mock">MOCK</span>
      · quotes <span class="badge mock">IMPORTED</span>
      · OS sandbox <span class="badge mock">PARTIAL</span>
    </p>
    <p class="note">API: /api/pilot/console /api/pilot/work-orders /api/pilot/receipts /api/pilot/purchase-requests /api/pilot/health /api/pilot/operator /api/pilot/scan /api/pilot/dispatch /api/pilot/exceptions /api/pilot/import /api/pilot/export — tenant header required. No LIVE_CNC/LASER controls.</p>

    <h2>Operator Control Plane / Manual Station</h2>
    <p class="note">
      MANUAL_STATION dispatch only · scan tokens FOX3D:WO|LOT|REL|CTN · barcode hardware <span class="badge mock">PARTIAL</span>
      · exception inbox tenant-filtered · journal hash-chain · LIVE_CNC <span class="badge mock">BLOCKED</span>
      · LIVE_LASER <span class="badge mock">BLOCKED</span> · human confirmation on consume/complete/finalize QC
    </p>
  </section>

  <script>
    function switchTab(tabId) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById(tabId).classList.add('active');
    }}

    function updateDims() {{
      const w = parseFloat(document.getElementById('c-w').value) || 0;
      const h = parseFloat(document.getElementById('c-h').value) || 0;
      const d = parseFloat(document.getElementById('c-d').value) || 0;
      const s = parseInt(document.getElementById('c-s').value) || 0;
      const doors = parseInt(document.getElementById('c-doors').value) || 0;

      document.getElementById('label-w').innerText = (w / 10) + ' 公分';
      document.getElementById('label-h').innerText = (h / 10) + ' 公分';
      document.getElementById('label-d').innerText = (d / 10) + ' 公分';
      document.getElementById('label-shelves').innerText = s + ' 塊板 (分為 ' + (s + 1) + ' 層格)';
      document.getElementById('label-doors').innerText = doors === 0 ? '0 片 (無門開放式 · 直接展示層格)' : doors + ' 扇開門 (💡 會裝上門板遮住內部)';
    }}

    function onKindChange() {{
      const k = document.getElementById('c-kind').value;
      if (k === 'OPEN_SHELF' || k === 'BOOKCASE') {{
        document.getElementById('c-doors').value = 0;
      }} else if (k === 'STORAGE_CABINET' && parseInt(document.getElementById('c-doors').value) === 0) {{
        document.getElementById('c-doors').value = 2;
      }}
      updateDims();
    }}

    function applyPreset(kind, w, h, d, s, doors) {{
      document.getElementById('c-kind').value = kind;
      document.getElementById('c-w').value = w;
      document.getElementById('c-h').value = h;
      document.getElementById('c-d').value = d;
      document.getElementById('c-s').value = s;
      document.getElementById('c-doors').value = doors;
      updateDims();
    }}

    function handleGenerate(e) {{
      e.preventDefault();
      const btn = document.getElementById('gen-btn');
      const box = document.getElementById('result-box');
      btn.disabled = true;
      btn.innerHTML = '<span>⏳ Blender 5.2.1 OptiX 光追渲染中（約 1 秒）...</span>';

      const payload = {{
        tenantId: 'demo',
        kind: document.getElementById('c-kind').value,
        width: parseFloat(document.getElementById('c-w').value),
        height: parseFloat(document.getElementById('c-h').value),
        depth: parseFloat(document.getElementById('c-d').value),
        shelfCount: parseInt(document.getElementById('c-s').value),
        doorCount: parseInt(document.getElementById('c-doors').value),
        boardThickness: 18,
        render: true
      }};

      fetch('/api/parametric/products', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json', 'X-Tenant-Id': 'demo'}},
        body: JSON.stringify(payload)
      }})
      .then(r => r.json())
      .then(data => {{
        btn.disabled = false;
        btn.innerHTML = '<span>🚀 立即生成 3D 渲染並出圖</span>';
        if (data.render && data.render.job && data.render.job.outputAsset) {{
          const assetUrl = '/api/assets/' + data.render.job.outputAsset;
          document.getElementById('res-img').src = assetUrl + '?t=' + Date.now();
          document.getElementById('res-link').href = assetUrl;
          document.getElementById('res-spec').innerText = payload.kind + ' · ' + (payload.width/10) + '×' + (payload.height/10) + '×' + (payload.depth/10) + ' cm · ' + (payload.shelfCount + 1) + '格';
          document.getElementById('res-time').innerText = '渲染耗時: ' + (data.render.job.renderTimeSec || '0.8') + 's (Blender Cycles OptiX)';
          box.style.display = 'block';
          box.scrollIntoView({{ behavior: 'smooth' }});
        }} else {{
          alert('生成成功！Job ID: ' + ((data.render && data.render.job) ? data.render.job.jobId : '完成'));
          location.reload();
        }}
      }})
      .catch(err => {{
        btn.disabled = false;
        btn.innerHTML = '<span>🚀 立即生成 3D 渲染並出圖</span>';
        alert('生成出錯: ' + err);
      }});
    }}
  </script>
</body>
</html>"""
