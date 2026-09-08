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

    rows_nodes = "".join(
        f"<tr><td>{escape(n.target_key)}</td><td>{escape(n.status)}</td>"
        f"<td>{escape(str(n.capabilities.get('gpu')))}</td>"
        f"<td>{escape(str(n.capabilities.get('blenderVersion')))}</td>"
        f"<td>{escape(str(n.capabilities.get('optix')))}</td>"
        f"<td>{escape(str(n.capabilities.get('realBlender')))}</td></tr>"
        for n in nodes
    )
    rows_jobs = []
    for j in jobs:
        files = ((j.get("output") or {}).get("files") or {})
        asset = j.get("outputAsset") or files.get("beauty.png") or ""
        img = f'<img src="/api/assets/{escape(str(asset))}?x=" class="thumb"/>' if asset else ""
        log = escape((j.get("logs") or "")[-400:])
        rows_jobs.append(
            "<tr>"
            f"<td>{escape(str(j.get('jobId')))}</td>"
            f"<td>{escape(str(j.get('jobType')))}</td>"
            f"<td>{escape(str(j.get('status')))}</td>"
            f"<td>{escape(str(j.get('worker')))}</td>"
            f"<td>{escape(str(j.get('gpu') or j.get('assignedComputeTargetKey')))}</td>"
            f"<td>{escape(str(j.get('blenderVersion') or (j.get('output') or {}).get('blenderVersion')))}</td>"
            f"<td>{escape(str(j.get('renderEngine') or (j.get('output') or {}).get('engine')))}</td>"
            f"<td>{escape(str(j.get('samples') or (j.get('output') or {}).get('samples')))}</td>"
            f"<td>{escape(str(j.get('renderTimeSec') or (j.get('output') or {}).get('renderTimeSec')))}</td>"
            f"<td>{img}{escape(str(asset))}</td>"
            f"<td class='log'>{log}</td>"
            "</tr>"
        )
    twin_cards = []
    for t in twins:
        preview = t.previewAssetId
        img = f'<img src="/api/assets/{escape(str(preview))}" class="preview"/>' if preview else "<em>no preview</em>"
        twin_cards.append(
            f"<div class='card'><h3>{escape(t.sku)}</h3><p>{escape(t.twinId)}</p>{img}</div>"
        )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <title>Autonomous 3D Control Plane</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; background: #0f1115; color: #e8eaed; }}
    header {{ padding: 16px 24px; background: #161b22; border-bottom: 1px solid #30363d; }}
    section {{ padding: 24px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #30363d; padding: 8px; text-align: left; font-size: 12px; vertical-align: top; }}
    .banner {{ padding: 12px 24px; font-weight: 600; }}
    .banner.ok {{ background: #132; color: #8f8; }}
    .banner.blocked {{ background: #311; color: #f88; }}
    .banner.mock {{ background: #321; color: #fc6; }}
    .thumb, .preview {{ max-width: 128px; max-height: 128px; display: block; }}
    .log {{ max-width: 280px; white-space: pre-wrap; color: #8b949e; font-family: ui-monospace, monospace; font-size: 11px; }}
    .card {{ display: inline-block; margin: 8px; padding: 12px; border: 1px solid #30363d; min-width: 160px; }}
    .note {{ color: #8b949e; }}
  </style>
</head>
<body>
  <header>
    <strong>Autonomous 3D / Product R&amp;D Control Plane</strong>
    <span class="note"> — 系統操作台，不含 Blender UI</span>
  </header>
  {banner}
  <section>
    <h2>Blender Workers</h2>
    <table><thead><tr><th>target</th><th>status</th><th>GPU</th><th>Blender</th><th>OptiX</th><th>realBlender</th></tr></thead>
    <tbody>{rows_nodes or '<tr><td colspan="6">no workers registered</td></tr>'}</tbody></table>
    <h2>3D Jobs / Render Queue</h2>
    <table><thead><tr>
      <th>job</th><th>type</th><th>status</th><th>worker</th><th>GPU</th>
      <th>Blender version</th><th>engine</th><th>samples</th><th>render time</th>
      <th>output asset</th><th>logs</th>
    </tr></thead>
    <tbody>{''.join(rows_jobs) or '<tr><td colspan="11">queue empty</td></tr>'}</tbody></table>
    <p>
      <form method="post" action="/api/e2e/smoke" onsubmit="fetch(this.action,{{method:'POST'}}).then(()=>location.reload());return false;">
        <button type="submit">Run REAL_SMOKE_TEST</button>
      </form>
    </p>
    <h2>Digital Twins</h2>
    {''.join(twin_cards) or '<p class="note">no twins</p>'}
    <p class="note">Production acceptance 必須 realBlender / realGPU / realCycles / realOptix / realRenderOutput。Mock 僅限 automated tests。</p>
  </section>
</body>
</html>"""
