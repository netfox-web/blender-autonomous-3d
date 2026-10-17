'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const tenant = 'sonaqueen-home';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  let state = {
    overview: null,
    cabinet: null,
    currentScene: null,
    previewPlan: null,
    selectedTarget: { kind: 'cabinet', index: -1 },
    dragging: null,
    camOrbit: { yawOffset: 0, pitchOffset: 0, zoom: 1.0, dragging: false, lastX: 0, lastY: 0 },
    activeBatchId: null,
    pollTimer: null
  };

  async function api(url, options = {}) {
    const r = await fetch(url, {
      ...options,
      headers: { 'X-Tenant-Id': tenant, 'Content-Type': 'application/json', ...(options.headers || {}) }
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失敗，請檢查輸入設定');
    return data;
  }

  function notify(msg, isError = false) {
    const el = $('studio-notice');
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.textContent = msg;
    el.style.background = isError ? '#fef3f2' : '#fdf1ea';
    el.style.color = isError ? '#b42318' : '#7c3510';
  }

  function clone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  function syncCabinetHeaderBadge() {
    if (!state.cabinet) return;
    const totalW = state.cabinet.columns.reduce((acc, c) => acc + Number(c.widthMm || 424), 0);
    const maxH = Math.max(...state.cabinet.columns.map(c => Number(c.heightMm || 900)));
    const d = Number(state.cabinet.depthMm || 295);
    $('cab-dim-badge').textContent = `${Math.round(totalW)} × ${Math.round(d)} × ${Math.round(maxH)} mm (${state.cabinet.columns.length} 欄)`;
  }

  function renderCabinetPresets() {
    const presets = state.overview?.cabinetPresets || [];
    $('cabinet-presets').innerHTML = presets.map(p =>
      `<button type="button" class="chip-btn ${state.cabinet?.id === p.id ? 'active' : ''}" data-preset="${esc(p.id)}">${esc(p.label)}</button>`
    ).join('');
    $('cabinet-presets').querySelectorAll('[data-preset]').forEach(btn => {
      btn.addEventListener('click', () => {
        const found = presets.find(x => x.id === btn.dataset.preset);
        if (!found) return;
        state.cabinet = clone(found);
        state.cabinet.name = found.label.split(' ')[0];
        state.cabinet.sku = 'SQ-' + found.id.replace('MOD_', '');
        syncCabinetInputsFromState();
        refreshPreviewPlan();
      });
    });
  }

  function renderThemes() {
    const themes = state.overview?.styleThemes || [];
    $('theme-cards').innerHTML = themes.map(t => {
      const active = state.cabinet?.themeId === t.id ? 'active' : '';
      const swatches = [t.carcassHex, ...(t.doorPaletteHex || []).slice(0, 2)].map(h =>
        `<span class="swatch" style="background:${esc(h)}"></span>`
      ).join('');
      return `<button type="button" class="theme-card ${active}" data-theme="${esc(t.id)}">
        <span class="swatches">${swatches}</span>
        <span>${esc(t.label)}</span>
      </button>`;
    }).join('');
    $('theme-cards').querySelectorAll('[data-theme]').forEach(btn => {
      btn.addEventListener('click', () => {
        state.cabinet.themeId = btn.dataset.theme;
        renderThemes();
        refreshPreviewPlan();
      });
    });
  }

  function renderColumnsEditor() {
    const cols = state.cabinet?.columns || [];
    const modeLabel = { DOOR: '🚪 門片', OPEN: '📂 開放格', DRAWER: '🗄️ 雙抽屜' };
    const nextMode = { DOOR: 'OPEN', OPEN: 'DRAWER', DRAWER: 'DOOR' };
    $('columns-editor').innerHTML = cols.map((col, cIdx) => {
      const rows = Number(col.rows || 3);
      while (col.cells.length < rows) col.cells.push({ mode: 'DOOR' });
      col.cells = col.cells.slice(0, rows);
      const cellsHtml = col.cells.map((cell, rIdx) =>
        `<button type="button" class="cell-btn mode-${esc(cell.mode)}" data-col="${cIdx}" data-row="${rIdx}">
          第 ${rIdx + 1} 層 · ${modeLabel[cell.mode] || cell.mode}
        </button>`
      ).join('');
      return `<div class="col-card">
        <div class="col-card-head">
          <span>第 ${cIdx + 1} 欄櫃體</span>
          <span>${Math.round(col.widthMm)}×${Math.round(col.heightMm)}</span>
        </div>
        <div class="col-inputs">
          <label>寬(mm)<input type="number" min="240" max="900" step="10" value="${Number(col.widthMm)}" data-col-w="${cIdx}"></label>
          <label>高(mm)<input type="number" min="300" max="2100" step="50" value="${Number(col.heightMm)}" data-col-h="${cIdx}"></label>
          <label>層數<input type="number" min="1" max="6" step="1" value="${rows}" data-col-r="${cIdx}"></label>
        </div>
        <div class="cell-stack">${cellsHtml}</div>
      </div>`;
    }).join('');

    $('columns-editor').querySelectorAll('[data-col-w]').forEach(inp => {
      inp.addEventListener('change', () => {
        const idx = Number(inp.dataset.colW);
        state.cabinet.columns[idx].widthMm = Math.max(240, Math.min(900, Number(inp.value) || 424));
        renderColumnsEditor();
        refreshPreviewPlan();
      });
    });
    $('columns-editor').querySelectorAll('[data-col-h]').forEach(inp => {
      inp.addEventListener('change', () => {
        const idx = Number(inp.dataset.colH);
        state.cabinet.columns[idx].heightMm = Math.max(300, Math.min(2100, Number(inp.value) || 900));
        renderColumnsEditor();
        refreshPreviewPlan();
      });
    });
    $('columns-editor').querySelectorAll('[data-col-r]').forEach(inp => {
      inp.addEventListener('change', () => {
        const idx = Number(inp.dataset.colR);
        const r = Math.max(1, Math.min(6, Number(inp.value) || 3));
        state.cabinet.columns[idx].rows = r;
        renderColumnsEditor();
        refreshPreviewPlan();
      });
    });
    $('columns-editor').querySelectorAll('[data-row]').forEach(btn => {
      btn.addEventListener('click', () => {
        const cIdx = Number(btn.dataset.col);
        const rIdx = Number(btn.dataset.row);
        const cur = state.cabinet.columns[cIdx].cells[rIdx].mode || 'DOOR';
        state.cabinet.columns[cIdx].cells[rIdx].mode = nextMode[cur] || 'DOOR';
        renderColumnsEditor();
        refreshPreviewPlan();
      });
    });
    syncCabinetHeaderBadge();
  }

  function syncCabinetInputsFromState() {
    if (!state.cabinet) return;
    $('cab-name').value = state.cabinet.name || '收納王妃組合櫃';
    $('cab-sku').value = state.cabinet.sku || 'SQ-MOD-01';
    $('cab-depth').value = state.cabinet.depthMm || 295;
    $('cab-panel').value = state.cabinet.panelMm || 15;
    $('cab-door').value = state.cabinet.doorMm || 15;
    $('cab-gap').value = state.cabinet.gapMm || 2;
    renderCabinetPresets();
    renderThemes();
    renderColumnsEditor();
  }

  function renderSceneTabs() {
    const scenes = state.overview?.scenes || [];
    $('scene-tabs').innerHTML = scenes.map(s =>
      `<button type="button" class="chip-btn ${state.currentScene?.id === s.id ? 'active' : ''}" data-scene-id="${esc(s.id)}">
        ${s.builtin ? '🏠' : '✨'} ${esc(s.name)}
      </button>`
    ).join('');
    $('scene-tabs').querySelectorAll('[data-scene-id]').forEach(btn => {
      btn.addEventListener('click', () => {
        const found = scenes.find(x => x.id === btn.dataset.sceneId);
        if (!found) return;
        state.currentScene = clone(found);
        state.selectedTarget = { kind: 'cabinet', index: -1 };
        syncSceneInputsFromState();
        refreshPreviewPlan();
      });
    });
  }

  function syncSceneInputsFromState() {
    const s = state.currentScene;
    if (!s) return;
    $('scene-name').value = s.name || '';
    $('scene-category').value = s.category || '客廳空間';
    $('scene-lighting').value = s.lightingPreset || 'WARM_SUNLIGHT';
    $('room-w').value = s.roomWidthM || 5.6;
    $('room-d').value = s.roomDepthM || 4.2;
    $('room-h').value = s.roomHeightM || 3.0;
    $('wall-color').value = s.wallColorHex || '#b8ab96';
    $('side-color').value = s.sideWallColorHex || '#a3a89c';
    $('floor-color').value = s.floorColorHex || '#78583a';
    $('delete-scene-btn').hidden = Boolean(s.builtin);
    renderSceneTabs();
    syncSelectedBar();
    renderPolyhavenGallery();
  }

  function renderPropPalette() {
    const props = state.overview?.propCatalog || [];
    $('prop-palette').innerHTML = props.map(p =>
      `<button type="button" class="chip-btn" data-add-prop="${esc(p.type)}">＋ ${esc(p.label)}</button>`
    ).join('');
    $('prop-palette').querySelectorAll('[data-add-prop]').forEach(btn => {
      btn.addEventListener('click', () => {
        const tpl = props.find(x => x.type === btn.dataset.addProp);
        if (!tpl || !state.currentScene) return;
        const newProp = {
          id: 'prop_' + Date.now().toString(36),
          type: tpl.type,
          label: tpl.label.replace(/^[^\s]+\s/, ''),
          x: Number(((Math.random() - 0.5) * 1.6).toFixed(2)),
          y: tpl.type === 'WALL_ART' || tpl.type === 'WINDOW_FRAME' ? 1.52 : Number((0.2 + (Math.random() - 0.5) * 0.8).toFixed(2)),
          z: tpl.defaultZ || 0.0,
          widthM: tpl.widthM,
          depthM: tpl.depthM,
          heightM: tpl.heightM,
          rotationDeg: 0,
          colorHex: tpl.colorHex,
          accentColorHex: tpl.accentColorHex
        };
        state.currentScene.props = state.currentScene.props || [];
        state.currentScene.props.push(newProp);
        state.selectedTarget = { kind: 'prop', index: state.currentScene.props.length - 1 };
        syncSelectedBar();
        refreshPreviewPlan();
      });
    });
    renderPolyhavenGallery();
  }

  function renderPolyhavenGallery() {
    const box = $('polyhaven-gallery');
    if (!box) return;
    const models = state.overview?.polyhavenModels || [];
    const curProps = state.currentScene?.props || [];
    const curSofa = curProps.find(p => p.type === 'SOFA');
    const isProcSofa = curSofa && !curSofa.glbPath;

    const procCard = `
      <button type="button" data-ph-proc="SOFA" style="display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px;border-radius:8px;cursor:pointer;background:${isProcSofa ? 'rgba(16,185,129,0.25)' : 'rgba(15,23,42,0.75)'};border:1px solid ${isProcSofa ? '#10b981' : 'rgba(148,163,184,0.25)'};color:#f8fafc;text-align:center;">
        <div style="height:54px;display:flex;align-items:center;justify-content:center;font-size:26px;">🛋️✨</div>
        <strong style="font-size:11px;line-height:1.2;">方式 2：義式拉釦皺褶布沙發</strong>
        <span style="font-size:10px;color:#94a3b8;">可自由改色＋立體滾邊</span>
      </button>
    `;

    const modelCards = models.map(m => {
      const active = curProps.some(p => p.glbPath && p.glbPath === m.glbPath);
      return `
        <button type="button" data-ph-id="${esc(m.assetId)}" style="display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px;border-radius:8px;cursor:pointer;background:${active ? 'rgba(16,185,129,0.25)' : 'rgba(15,23,42,0.75)'};border:1px solid ${active ? '#10b981' : 'rgba(148,163,184,0.25)'};color:#f8fafc;text-align:center;">
          <img src="${esc(m.thumbUrl)}" alt="${esc(m.shortLabel || m.assetId)}" style="height:54px;width:100%;object-fit:contain;border-radius:4px;background:rgba(0,0,0,0.25);">
          <strong style="font-size:11px;line-height:1.2;">🏛️ ${esc(m.shortLabel || m.assetId)}</strong>
          <span style="font-size:10px;color:#6ee7b7;">Poly Haven 2K 高模</span>
        </button>
      `;
    }).join('');

    box.innerHTML = procCard + modelCards;

    box.querySelectorAll('[data-ph-proc]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (!state.currentScene) return;
        state.currentScene.props = state.currentScene.props || [];
        let idx = state.currentScene.props.findIndex(p => p.type === 'SOFA');
        if (idx >= 0) {
          delete state.currentScene.props[idx].glbPath;
          state.currentScene.props[idx].label = '雙人沙發 (義式皺褶布藝)';
          state.selectedTarget = { kind: 'prop', index: idx };
        }
        syncSelectedBar();
        renderPolyhavenGallery();
        refreshPreviewPlan();
        notify('✨ 已切換為「方式 2：義式圓潤拉釦皺褶布藝沙發」（支援自由改色＋實掃描法線貼圖）！');
      });
    });

    box.querySelectorAll('[data-ph-id]').forEach(btn => {
      btn.addEventListener('click', () => {
        const m = models.find(x => x.assetId === btn.dataset.phId);
        if (!m || !state.currentScene) return;
        state.currentScene.props = state.currentScene.props || [];
        let idx = state.currentScene.props.findIndex(p => p.type === m.propType);
        if (idx >= 0) {
          state.currentScene.props[idx].glbPath = m.glbPath;
          state.currentScene.props[idx].label = m.shortLabel || m.label;
          if (m.assetId === 'coffee_table_round_01') {
            state.currentScene.props[idx].widthM = 0.85;
            state.currentScene.props[idx].depthM = 0.85;
          }
        } else {
          state.currentScene.props.push({
            id: 'ph_' + m.assetId,
            type: m.propType,
            label: m.shortLabel || m.label,
            glbPath: m.glbPath,
            x: m.propType === 'SOFA' ? -1.45 : (m.propType === 'PLANT' ? 1.18 : -1.35),
            y: m.propType === 'SOFA' ? 1.05 : (m.propType === 'PLANT' ? 1.10 : -0.05),
            z: 0.0,
            widthM: m.propType === 'SOFA' ? 1.75 : (m.propType === 'PLANT' ? 0.45 : 0.95),
            depthM: m.propType === 'SOFA' ? 0.78 : (m.propType === 'PLANT' ? 0.45 : 0.60),
            heightM: m.propType === 'SOFA' ? 0.82 : (m.propType === 'PLANT' ? 0.95 : 0.43),
            rotationDeg: 0,
            colorHex: '#8a6b4e',
            accentColorHex: '#4a3520'
          });
          idx = state.currentScene.props.length - 1;
        }
        state.selectedTarget = { kind: 'prop', index: idx };
        syncSelectedBar();
        renderPolyhavenGallery();
        refreshPreviewPlan();
        notify(`🏛️ 已將房間內的家具切換為「${m.label}」！點右方「🔥 立即算這張 A+B 雙引擎逼真圖」即可渲染此 2K 掃描高模。`);
      });
    });
  }

  function renderCameraPills() {
    const views = state.overview?.cameraViews || [];
    const curView = $('scene-view').value || 'THREE_QUARTER';
    $('camera-quick-pills').innerHTML = views.map(v =>
      `<button type="button" class="chip-btn ${curView === v.id ? 'active' : ''}" data-cam-view="${esc(v.id)}">📷 ${esc(v.label)}</button>`
    ).join('');
    $('camera-quick-pills').querySelectorAll('[data-cam-view]').forEach(btn => {
      btn.addEventListener('click', () => {
        $('scene-view').value = btn.dataset.camView;
        state.camOrbit.yawOffset = 0;
        state.camOrbit.pitchOffset = 0;
        state.camOrbit.zoom = 1.0;
        renderCameraPills();
        refreshPreviewPlan();
      });
    });
  }

  function syncSelectedBar() {
    const s = state.currentScene;
    if (!s) return;
    if (state.selectedTarget.kind === 'cabinet' || state.selectedTarget.index < 0 || !s.props?.[state.selectedTarget.index]) {
      const pose = s.productPose || { x: 0, y: 1.1, z: 0, rotationDeg: 0 };
      $('sel-item-label').textContent = '🎯 已選中：組合櫃置放點（可在平面圖拖拉）';
      $('sel-rot').value = String(pose.rotationDeg || 0);
      if ($('sel-ph-wrap')) $('sel-ph-wrap').hidden = true;
      $('sel-color-wrap').hidden = true;
      $('sel-w-wrap').hidden = true;
      $('sel-d-wrap').hidden = true;
      $('sel-delete-btn').hidden = true;
      $('cab-pose-readout').textContent = `櫃位 X: ${Number(pose.x || 0).toFixed(2)}m, Y: ${Number(pose.y || 0).toFixed(2)}m, 角度: ${pose.rotationDeg || 0}°`;
    } else {
      const p = s.props[state.selectedTarget.index];
      $('sel-item-label').textContent = `🛋️ 已選中家具：${p.label || p.type}`;
      $('sel-rot').value = String(p.rotationDeg || 0);
      if ($('sel-ph-wrap') && $('sel-ph-model')) {
        $('sel-ph-wrap').hidden = false;
        $('sel-ph-model').value = p.glbPath || '';
      }
      $('sel-color-wrap').hidden = false;
      $('sel-color').value = p.colorHex || '#26534e';
      $('sel-w-wrap').hidden = false;
      $('sel-w').value = p.widthM || 1.0;
      $('sel-d-wrap').hidden = false;
      $('sel-d').value = p.depthM || 0.6;
      $('sel-delete-btn').hidden = false;
    }
  }

  // ==================== 2D FLOORPLAN INTERACTIVE CANVAS ====================
  function floorplanTransform(canvas) {
    const rw = Number(state.currentScene?.roomWidthM || 5.6);
    const rd = Number(state.currentScene?.roomDepthM || 4.2);
    const pad = 38;
    const scale = Math.min((canvas.width - pad * 2) / rw, (canvas.height - pad * 2) / rd);
    const cx = canvas.width / 2;
    const cy = canvas.height / 2 + 12;
    return {
      rw, rd, scale, cx, cy,
      toScreen(x, y) {
        return [cx + x * scale, cy - y * scale];
      },
      toWorld(sx, sy) {
        return [
          Number(((sx - cx) / scale).toFixed(2)),
          Number(((cy - sy) / scale).toFixed(2))
        ];
      }
    };
  }

  function drawFloorplan() {
    const canvas = $('floorplan-canvas');
    if (!canvas || !state.currentScene) return;
    const ctx = canvas.getContext('2d');
    const tf = floorplanTransform(canvas);
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Room floor rectangle (y from -rd/2 to +1.65)
    const [x0, y0] = tf.toScreen(-tf.rw / 2, 1.65);
    const [x1, y1] = tf.toScreen(tf.rw / 2, 1.65 - tf.rd);
    ctx.fillStyle = state.currentScene.floorColorHex || '#78583a';
    ctx.globalAlpha = 0.35;
    ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
    ctx.globalAlpha = 1.0;

    // Grid lines every 0.5m
    ctx.strokeStyle = 'rgba(255,255,255,0.10)';
    ctx.lineWidth = 1;
    for (let gx = -Math.floor(tf.rw); gx <= Math.floor(tf.rw); gx += 0.5) {
      const [sx] = tf.toScreen(gx, 0);
      if (sx >= x0 && sx <= x1) {
        ctx.beginPath(); ctx.moveTo(sx, y0); ctx.lineTo(sx, y1); ctx.stroke();
      }
    }
    for (let gy = -2.5; gy <= 1.65; gy += 0.5) {
      const [, sy] = tf.toScreen(0, gy);
      if (sy >= y0 && sy <= y1) {
        ctx.beginPath(); ctx.moveTo(x0, sy); ctx.lineTo(x1, sy); ctx.stroke();
      }
    }

    // Back wall & Side wall highlight
    ctx.strokeStyle = state.currentScene.wallColorHex || '#b8ab96';
    ctx.lineWidth = 6;
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y0); ctx.stroke();
    ctx.strokeStyle = state.currentScene.sideWallColorHex || '#a3a89c';
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0, y1); ctx.stroke();

    ctx.fillStyle = 'rgba(255,255,255,0.65)';
    ctx.font = '11px "Microsoft JhengHei", sans-serif';
    ctx.fillText('▲ 主背牆 (Back Wall Y=1.65m)', x0 + 10, y0 - 8);

    // Draw props
    (state.currentScene.props || []).forEach((p, idx) => {
      const [px, py] = tf.toScreen(Number(p.x || 0), Number(p.y || 0));
      const rot = Number(p.rotationDeg || 0);
      const pw = Number(p.widthM || 0.8) * tf.scale;
      const pd = Number(p.depthM || 0.6) * tf.scale;
      const isSel = state.selectedTarget.kind === 'prop' && state.selectedTarget.index === idx;
      ctx.save();
      ctx.translate(px, py);
      ctx.rotate((-rot * Math.PI) / 180);
      ctx.fillStyle = p.colorHex || '#5a6b65';
      ctx.globalAlpha = p.type === 'RUG' ? 0.45 : 0.88;
      ctx.fillRect(-pw / 2, -pd / 2, pw, pd);
      ctx.globalAlpha = 1.0;
      ctx.lineWidth = isSel ? 2.5 : 1.2;
      ctx.strokeStyle = isSel ? '#ffd166' : 'rgba(255,255,255,0.6)';
      ctx.strokeRect(-pw / 2, -pd / 2, pw, pd);
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 11px "Microsoft JhengHei", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(p.label || p.type, 0, 4);
      ctx.restore();
    });

    // Draw Cabinet Target Slot
    const pose = state.currentScene.productPose || { x: 0, y: 1.1, z: 0, rotationDeg: 0 };
    const cabW = (state.previewPlan?.cabinetSpec?.width || 424) / 1000;
    const cabD = (state.previewPlan?.cabinetSpec?.depth || 295) / 1000;
    const [cx, cy] = tf.toScreen(Number(pose.x || 0), Number(pose.y || 0));
    const cw = Math.max(28, cabW * tf.scale);
    const cd = Math.max(20, cabD * tf.scale);
    const isCabSel = state.selectedTarget.kind === 'cabinet';

    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate((-(Number(pose.rotationDeg || 0)) * Math.PI) / 180);
    ctx.fillStyle = '#e07a3c';
    ctx.fillRect(-cw / 2, -cd / 2, cw, cd);
    ctx.lineWidth = isCabSel ? 3 : 1.5;
    ctx.strokeStyle = isCabSel ? '#fff3b0' : '#ffffff';
    ctx.strokeRect(-cw / 2, -cd / 2, cw, cd);
    // Front direction arrow (+Y on screen is down = -Y in world)
    ctx.fillStyle = '#fff3b0';
    ctx.beginPath();
    ctx.moveTo(0, cd / 2 + 8);
    ctx.lineTo(-6, cd / 2);
    ctx.lineTo(6, cd / 2);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 11px "Microsoft JhengHei", sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('🎯 組合櫃', 0, 4);
    ctx.restore();
  }

  function setupFloorplanEvents() {
    const canvas = $('floorplan-canvas');
    if (!canvas) return;

    function getMousePos(e) {
      const rect = canvas.getBoundingClientRect();
      return [
        (e.clientX - rect.left) * (canvas.width / rect.width),
        (e.clientY - rect.top) * (canvas.height / rect.height)
      ];
    }

    canvas.addEventListener('mousedown', e => {
      if (!state.currentScene) return;
      const [mx, my] = getMousePos(e);
      const tf = floorplanTransform(canvas);
      const pose = state.currentScene.productPose || { x: 0, y: 1.1, z: 0, rotationDeg: 0 };
      const [cx, cy] = tf.toScreen(Number(pose.x || 0), Number(pose.y || 0));
      if (Math.hypot(mx - cx, my - cy) <= 28) {
        state.selectedTarget = { kind: 'cabinet', index: -1 };
        state.dragging = { kind: 'cabinet' };
        syncSelectedBar();
        drawFloorplan();
        return;
      }
      const props = state.currentScene.props || [];
      for (let i = props.length - 1; i >= 0; i--) {
        const p = props[i];
        const [px, py] = tf.toScreen(Number(p.x || 0), Number(p.y || 0));
        const pw = Math.max(24, Number(p.widthM || 0.8) * tf.scale);
        const pd = Math.max(24, Number(p.depthM || 0.6) * tf.scale);
        if (Math.abs(mx - px) <= pw / 2 && Math.abs(my - py) <= pd / 2) {
          state.selectedTarget = { kind: 'prop', index: i };
          state.dragging = { kind: 'prop', index: i };
          syncSelectedBar();
          drawFloorplan();
          return;
        }
      }
    });

    window.addEventListener('mousemove', e => {
      if (!state.dragging || !state.currentScene) return;
      const [mx, my] = getMousePos(e);
      const tf = floorplanTransform(canvas);
      const [wx, wy] = tf.toWorld(mx, my);
      const clampedX = Math.max(-tf.rw / 2 + 0.25, Math.min(tf.rw / 2 - 0.25, wx));
      const clampedY = Math.max(1.65 - tf.rd + 0.25, Math.min(1.54, wy));
      if (state.dragging.kind === 'cabinet') {
        state.currentScene.productPose = state.currentScene.productPose || { x: 0, y: 1.1, z: 0, rotationDeg: 0 };
        state.currentScene.productPose.x = clampedX;
        state.currentScene.productPose.y = clampedY;
      } else if (state.dragging.kind === 'prop') {
        const p = state.currentScene.props[state.dragging.index];
        if (p) {
          p.x = clampedX;
          p.y = clampedY;
        }
      }
      syncSelectedBar();
      drawFloorplan();
      renderLive3DScene($('scene3d-canvas'), state.currentScene, state.previewPlan?.cabinetSpec, $('scene-view').value, state.camOrbit);
    });

    window.addEventListener('mouseup', () => {
      if (state.dragging) {
        state.dragging = null;
        refreshPreviewPlan();
      }
    });
  }

  // ==================== 3D PERSPECTIVE ROOM & CABINET ENGINE ====================
  function hexToRgb01(hex) {
    const s = String(hex || '').replace('#', '');
    if (s.length !== 6) return [0.75, 0.7, 0.62];
    return [parseInt(s.slice(0, 2), 16) / 255, parseInt(s.slice(2, 4), 16) / 255, parseInt(s.slice(4, 6), 16) / 255];
  }

  function rgbCss(rgb, shade = 1.0, alpha = 1.0) {
    const r = Math.max(0, Math.min(255, Math.round((rgb[0] || 0) * 255 * shade)));
    const g = Math.max(0, Math.min(255, Math.round((rgb[1] || 0) * 255 * shade)));
    const b = Math.max(0, Math.min(255, Math.round((rgb[2] || 0) * 255 * shade)));
    return alpha < 1 ? `rgba(${r},${g},${b},${alpha})` : `rgb(${r},${g},${b})`;
  }

  function compileClientRoomBoxes(sceneCfg) {
    const rw = Number(sceneCfg.roomWidthM || 5.6);
    const rd = Number(sceneCfg.roomDepthM || 4.2);
    const rh = Number(sceneCfg.roomHeightM || 3.0);
    const floorRgb = hexToRgb01(sceneCfg.floorColorHex || '#78583a');
    const wallRgb = hexToRgb01(sceneCfg.wallColorHex || '#b8ab96');
    const sideRgb = hexToRgb01(sceneCfg.sideWallColorHex || '#a3a89c');

    const boxes = [
      { name: 'Floor', size: [rw + 1.0, rd + 1.2, 0.10], location: [0, 0.2, -0.05], color: floorRgb, rotDeg: 0 },
      { name: 'BackWall', size: [rw + 1.0, 0.10, rh], location: [0, 1.65, rh / 2], color: wallRgb, rotDeg: 0 },
      { name: 'Skirting', size: [rw + 1.0, 0.035, 0.09], location: [0, 1.58, 0.045], color: [0.88, 0.86, 0.82], rotDeg: 0 },
      { name: 'SideWall', size: [0.10, rd + 1.2, rh], location: [-rw / 2, 0.2, rh / 2], color: sideRgb, rotDeg: 0 }
    ];

    (sceneCfg.props || []).forEach(p => {
      const px = Number(p.x || 0), py = Number(p.y || 0), pz = Number(p.z || 0);
      let w = Number(p.widthM || 0.8), d = Number(p.depthM || 0.6), h = Number(p.heightM || 0.6);
      const rot = Number(p.rotationDeg || 0);
      const main = hexToRgb01(p.colorHex || '#26534e');
      const acc = hexToRgb01(p.accentColorHex || '#5a3821');
      if (p.type === 'SOFA') {
        boxes.push({ size: [w, d, h * 0.38], location: [px, py, pz + h * 0.25], color: main, rotDeg: rot });
        boxes.push({ size: [w, d * 0.24, h * 0.62], location: [px, py + d * 0.34, pz + h * 0.62], color: main, rotDeg: rot });
        boxes.push({ size: [w * 0.11, d * 0.9, h * 0.52], location: [px - w * 0.45, py, pz + h * 0.45], color: main, rotDeg: rot });
        boxes.push({ size: [w * 0.11, d * 0.9, h * 0.52], location: [px + w * 0.45, py, pz + h * 0.45], color: main, rotDeg: rot });
      } else if (p.type === 'COFFEE_TABLE' || p.type === 'DESK' || p.type === 'BENCH') {
        boxes.push({ size: [w, d, 0.05], location: [px, py, pz + h - 0.025], color: main, rotDeg: rot });
        boxes.push({ size: [0.06, d * 0.8, h - 0.05], location: [px - w * 0.4, py, pz + (h - 0.05) / 2], color: acc, rotDeg: rot });
        boxes.push({ size: [0.06, d * 0.8, h - 0.05], location: [px + w * 0.4, py, pz + (h - 0.05) / 2], color: acc, rotDeg: rot });
      } else if (p.type === 'RUG') {
        boxes.push({ size: [w, d, 0.015], location: [px, py, 0.008], color: main, rotDeg: rot });
      } else if (p.type === 'FLOOR_LAMP') {
        boxes.push({ size: [w * 0.7, d * 0.7, 0.04], location: [px, py, 0.02], color: acc, rotDeg: 0 });
        boxes.push({ size: [0.04, 0.04, h * 0.8], location: [px, py, h * 0.42], color: acc, rotDeg: 0 });
        boxes.push({ size: [w, d, h * 0.22], location: [px, py, h * 0.88], color: main, rotDeg: 0 });
      } else if (p.type === 'WALL_ART' || p.type === 'WINDOW_FRAME') {
        const z0 = pz > 0.1 ? pz : 1.42;
        boxes.push({ size: [w, 0.05, h], location: [px, py, z0], color: acc, rotDeg: rot });
        boxes.push({ size: [w * 0.86, 0.03, h * 0.86], location: [px, py - 0.02, z0], color: main, rotDeg: rot });
      } else if (p.type === 'PLANT') {
        boxes.push({ size: [w * 0.65, d * 0.65, h * 0.35], location: [px, py, h * 0.175], color: acc, rotDeg: 0 });
        boxes.push({ size: [w * 0.92, d * 0.92, h * 0.55], location: [px, py, h * 0.62], color: main, rotDeg: 0 });
      } else if (p.type === 'BED') {
        boxes.push({ size: [w, d, h * 0.26], location: [px, py, h * 0.13], color: acc, rotDeg: rot });
        boxes.push({ size: [w, 0.12, h], location: [px, py + d * 0.45, h * 0.5], color: acc, rotDeg: rot });
        boxes.push({ size: [w * 0.92, d * 0.88, h * 0.22], location: [px, py - 0.03, h * 0.35], color: main, rotDeg: rot });
      } else {
        boxes.push({ size: [w, d, h], location: [px, py, pz + h / 2], color: main, rotDeg: rot });
      }
    });
    return boxes;
  }

  function renderLive3DScene(canvas, sceneCfg, cabinetSpec, viewId = 'THREE_QUARTER', orbit = { yawOffset: 0, pitchOffset: 0, zoom: 1.0 }, themeOverride = null) {
    if (!canvas || !sceneCfg || !cabinetSpec) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;

    // Sky/World background gradient
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    if (sceneCfg.lightingPreset === 'COZY_EVENING') {
      grad.addColorStop(0, '#2a2630');
      grad.addColorStop(1, '#1a171e');
    } else {
      grad.addColorStop(0, '#3a464e');
      grad.addColorStop(1, '#20262a');
    }
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    const views = {
      THREE_QUARTER: { side: 0.58, distMult: 2.35, elev: 0.34, focal: 1.15 },
      LEFT: { side: -0.58, distMult: 2.35, elev: 0.34, focal: 1.15 },
      FRONT: { side: 0.0, distMult: 2.20, elev: 0.22, focal: 1.25 },
      WIDE: { side: 0.42, distMult: 3.05, elev: 0.42, focal: 0.95 },
      CLOSEUP: { side: 0.32, distMult: 1.55, elev: 0.20, focal: 1.38 }
    };
    const vcfg = views[viewId] || views.THREE_QUARTER;

    const pose = sceneCfg.productPose || { x: 0, y: 1.1, z: 0, rotationDeg: 0 };
    const px = Number(pose.x || 0), py = Number(pose.y || 1.1), pz = Number(pose.z || 0);
    const cabH = (cabinetSpec.height || 900) / 1000;
    const cabW = (cabinetSpec.width || 424) / 1000;
    const extent = Math.max(cabW, cabH, 0.9);
    const dist = Math.max(extent * vcfg.distMult, 2.0) / Math.max(0.5, orbit.zoom || 1.0);

    const target = [px * 0.55, py * 0.5, pz + cabH * 0.48];
    const baseYaw = Math.atan2(vcfg.side, -1.0) + (orbit.yawOffset || 0);
    const basePitch = Math.atan(vcfg.elev) + (orbit.pitchOffset || 0);

    const camPos = [
      target[0] + dist * Math.sin(baseYaw) * Math.cos(basePitch),
      target[1] - dist * Math.cos(baseYaw) * Math.cos(basePitch),
      target[2] + dist * Math.sin(basePitch)
    ];

    // Camera basis vectors
    const fwd = [target[0] - camPos[0], target[1] - camPos[1], target[2] - camPos[2]];
    const fLen = Math.hypot(...fwd) || 1;
    fwd[0] /= fLen; fwd[1] /= fLen; fwd[2] /= fLen;
    const upRef = [0, 0, 1];
    let right = [
      fwd[1] * upRef[2] - fwd[2] * upRef[1],
      fwd[2] * upRef[0] - fwd[0] * upRef[2],
      fwd[0] * upRef[1] - fwd[1] * upRef[0]
    ];
    const rLen = Math.hypot(...right) || 1;
    right[0] /= rLen; right[1] /= rLen; right[2] /= rLen;
    const up = [
      right[1] * fwd[2] - right[2] * fwd[1],
      right[2] * fwd[0] - right[0] * fwd[2],
      right[0] * fwd[1] - right[1] * fwd[0]
    ];

    const scale = Math.min(W, H) * vcfg.focal;
    function project(pt) {
      const dx = pt[0] - camPos[0], dy = pt[1] - camPos[1], dz = pt[2] - camPos[2];
      const cz = dx * fwd[0] + dy * fwd[1] + dz * fwd[2];
      if (cz <= 0.12) return null;
      const cx = dx * right[0] + dy * right[1] + dz * right[2];
      const cy = dx * up[0] + dy * up[1] + dz * up[2];
      return [W / 2 + (cx / cz) * scale, H / 2 - (cy / cz) * scale, cz];
    }

    const allBoxes = compileClientRoomBoxes(sceneCfg);

    // Add cabinet components transformed by productPose
    const rotRad = ((Number(pose.rotationDeg || 0)) * Math.PI) / 180;
    const cosR = Math.cos(rotRad), sinR = Math.sin(rotRad);
    const themeCarcass = themeOverride ? hexToRgb01(themeOverride.carcassHex) : null;
    const themeDoors = themeOverride ? (themeOverride.doorPaletteHex || []).map(hexToRgb01) : null;

    (cabinetSpec.components || []).forEach((part, idx) => {
      const lx = part.location[0], ly = part.location[1], lz = part.location[2];
      const wx = px + (lx * cosR - ly * sinR);
      const wy = py + (lx * sinR + ly * cosR);
      const wz = pz + lz;
      let col = part.colorRgb || [0.78, 0.62, 0.40];
      if (themeOverride) {
        col = part.role === 'door' ? themeDoors[idx % themeDoors.length] : themeCarcass;
      }
      allBoxes.push({
        name: part.componentId,
        size: part.size,
        location: [wx, wy, wz],
        color: col,
        rotDeg: Number(pose.rotationDeg || 0),
        isProduct: true,
        role: part.role
      });
    });

    const faces = [];
    const faceIndices = [
      { idx: [0, 1, 2, 3], shade: 0.72 }, // -Z bottom
      { idx: [4, 5, 6, 7], shade: 1.06 }, // +Z top
      { idx: [0, 1, 5, 4], shade: 0.98 }, // -Y front
      { idx: [2, 3, 7, 6], shade: 0.78 }, // +Y back
      { idx: [1, 2, 6, 5], shade: 0.88 }, // +X right
      { idx: [3, 0, 4, 7], shade: 0.83 }  // -X left
    ];

    allBoxes.forEach(box => {
      const [sx, sy, sz] = box.size;
      const [bx, by, bz] = box.location;
      const rad = ((box.rotDeg || 0) * Math.PI) / 180;
      const c = Math.cos(rad), s = Math.sin(rad);
      const localCorners = [
        [-sx / 2, -sy / 2, -sz / 2], [sx / 2, -sy / 2, -sz / 2],
        [sx / 2, sy / 2, -sz / 2], [-sx / 2, sy / 2, -sz / 2],
        [-sx / 2, -sy / 2, sz / 2], [sx / 2, -sy / 2, sz / 2],
        [sx / 2, sy / 2, sz / 2], [-sx / 2, sy / 2, sz / 2]
      ];
      const worldCorners = localCorners.map(([x, y, z]) => [
        bx + x * c - y * s,
        by + x * s + y * c,
        bz + z
      ]);
      const projected = worldCorners.map(project);
      if (projected.some(p => p === null)) return;

      faceIndices.forEach((f, fIdx) => {
        const pts2d = f.idx.map(i => projected[i]);
        const pts3d = f.idx.map(i => worldCorners[i]);
        const center3d = [
          (pts3d[0][0] + pts3d[2][0]) / 2,
          (pts3d[0][1] + pts3d[2][1]) / 2,
          (pts3d[0][2] + pts3d[2][2]) / 2
        ];
        // True Euclidean distance from camera to face center + slight room priority
        let distToCam = Math.hypot(
          center3d[0] - camPos[0],
          center3d[1] - camPos[1],
          center3d[2] - camPos[2]
        );
        if (box.name === 'Floor' || box.name === 'BackWall' || box.name === 'SideWall') {
          distToCam += 15.0; // Always draw room shell behind interior items
        }
        faces.push({
          pts: pts2d,
          depth: distToCam,
          color: box.color,
          shade: f.shade,
          isProduct: Boolean(box.isProduct),
          isFrontDoor: Boolean(box.isProduct && box.role === 'door' && fIdx === 2)
        });
      });
    });

    faces.sort((a, b) => b.depth - a.depth);
    faces.forEach(f => {
      ctx.beginPath();
      ctx.moveTo(f.pts[0][0], f.pts[0][1]);
      for (let i = 1; i < f.pts.length; i++) ctx.lineTo(f.pts[i][0], f.pts[i][1]);
      ctx.closePath();
      ctx.fillStyle = rgbCss(f.color, f.shade);
      ctx.fill();
      ctx.lineWidth = f.isProduct ? 1.1 : 0.6;
      ctx.strokeStyle = f.isProduct ? 'rgba(30,22,15,0.45)' : 'rgba(0,0,0,0.18)';
      ctx.stroke();
    });

    // Watermark badge on 3D preview
    ctx.fillStyle = 'rgba(18, 28, 25, 0.72)';
    ctx.fillRect(12, H - 34, 310, 24);
    ctx.fillStyle = '#e7f3ee';
    ctx.font = 'bold 11px "Microsoft JhengHei", sans-serif';
    ctx.fillText(`🏠 ${sceneCfg.name} · ${themeOverride?.label || cabinetSpec.themeLabel || ''}`, 20, H - 18);
  }

  function setup3DViewportEvents() {
    const canvas = $('scene3d-canvas');
    if (!canvas) return;
    canvas.addEventListener('mousedown', e => {
      state.camOrbit.dragging = true;
      state.camOrbit.lastX = e.clientX;
      state.camOrbit.lastY = e.clientY;
    });
    window.addEventListener('mousemove', e => {
      if (!state.camOrbit.dragging) return;
      const dx = e.clientX - state.camOrbit.lastX;
      const dy = e.clientY - state.camOrbit.lastY;
      state.camOrbit.lastX = e.clientX;
      state.camOrbit.lastY = e.clientY;
      state.camOrbit.yawOffset = Math.max(-1.1, Math.min(1.1, state.camOrbit.yawOffset + dx * 0.007));
      state.camOrbit.pitchOffset = Math.max(-0.35, Math.min(0.55, state.camOrbit.pitchOffset + dy * 0.005));
      renderLive3DScene(canvas, state.currentScene, state.previewPlan?.cabinetSpec, $('scene-view').value, state.camOrbit);
    });
    window.addEventListener('mouseup', () => {
      state.camOrbit.dragging = false;
    });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.08 : 0.08;
      state.camOrbit.zoom = Math.max(0.65, Math.min(1.85, state.camOrbit.zoom + delta));
      renderLive3DScene(canvas, state.currentScene, state.previewPlan?.cabinetSpec, $('scene-view').value, state.camOrbit);
    }, { passive: false });
  }

  async function refreshPreviewPlan() {
    if (!state.cabinet || !state.currentScene) return;
    try {
      const res = await api('/api/ecommerce-scenes/preview-plan', {
        method: 'POST',
        body: JSON.stringify({
          cabinet: state.cabinet,
          scene: state.currentScene,
          view: $('scene-view').value || 'THREE_QUARTER'
        })
      });
      state.previewPlan = res;
      drawFloorplan();
      renderLive3DScene($('scene3d-canvas'), state.currentScene, res.cabinetSpec, $('scene-view').value || 'THREE_QUARTER', state.camOrbit);
    } catch (e) {
      notify(e.message, true);
    }
  }

  // ==================== STEP 3: MATRIX SELECTORS & RENDERING ====================
  function renderMatrixChecklists() {
    const scenes = state.overview?.scenes || [];
    const themes = state.overview?.styleThemes || [];
    const views = state.overview?.cameraViews || [];

    $('matrix-scenes-list').innerHTML = scenes.map((s, idx) =>
      `<label class="check-item">
        <input type="checkbox" name="mat-scene" value="${esc(s.id)}" ${idx < 3 ? 'checked' : ''}>
        <span>${s.builtin ? '🏠' : '✨'} ${esc(s.name)}</span>
      </label>`
    ).join('');

    $('matrix-themes-list').innerHTML = themes.map((t, idx) =>
      `<label class="check-item">
        <input type="checkbox" name="mat-theme" value="${esc(t.id)}" ${idx < 2 ? 'checked' : ''}>
        <span>🎨 ${esc(t.label)}</span>
      </label>`
    ).join('');

    $('matrix-views-list').innerHTML = views.map((v, idx) =>
      `<label class="check-item">
        <input type="checkbox" name="mat-view" value="${esc(v.id)}" ${idx === 0 ? 'checked' : ''}>
        <span>📷 ${esc(v.label)}</span>
      </label>`
    ).join('');

    document.querySelectorAll('input[name="mat-scene"], input[name="mat-theme"], input[name="mat-view"]').forEach(cb => {
      cb.addEventListener('change', updateMatrixFormula);
    });
    updateMatrixFormula();
  }

  function getSelectedMatrix() {
    const sceneIds = [...document.querySelectorAll('input[name="mat-scene"]:checked')].map(el => el.value);
    const themeIds = [...document.querySelectorAll('input[name="mat-theme"]:checked')].map(el => el.value);
    const views = [...document.querySelectorAll('input[name="mat-view"]:checked')].map(el => el.value);
    return { sceneIds, themeIds, views, total: sceneIds.length * themeIds.length * views.length };
  }

  function updateMatrixFormula() {
    const { sceneIds, themeIds, views, total } = getSelectedMatrix();
    $('matrix-formula').textContent = `預計產出：${sceneIds.length} 個場景 × ${themeIds.length} 種配色 × ${views.length} 個視角 ＝ 共 ${total} 張電商情境圖`;
    $('matrix-count-pill').textContent = `矩陣預備：${total} 張`;
  }

  function generateInstant3DMatrixGallery() {
    const { sceneIds, themeIds, views, total } = getSelectedMatrix();
    if (!total) {
      notify('請至少勾選 1 個場景、1 種配色與 1 個視角', true);
      return;
    }
    if (!state.previewPlan?.cabinetSpec) return;

    const scenesById = Object.fromEntries((state.overview?.scenes || []).map(s => [s.id, s]));
    if (state.currentScene?.id) scenesById[state.currentScene.id] = state.currentScene;
    const themesById = Object.fromEntries((state.overview?.styleThemes || []).map(t => [t.id, t]));
    const viewsById = Object.fromEntries((state.overview?.cameraViews || []).map(v => [v.id, v]));

    const offCanvas = document.createElement('canvas');
    offCanvas.width = 720;
    offCanvas.height = 720;

    const cards = [];
    let count = 0;
    sceneIds.forEach(sid => {
      const scfg = scenesById[sid] || state.currentScene;
      themeIds.forEach(tid => {
        const tcfg = themesById[tid];
        views.forEach(vid => {
          count++;
          const vcfg = viewsById[vid];
          renderLive3DScene(offCanvas, scfg, state.previewPlan.cabinetSpec, vid, { yawOffset: 0, pitchOffset: 0, zoom: 1.0 }, tcfg);
          const dataUrl = offCanvas.toDataURL('image/png');
          const fileName = `${state.cabinet.sku || 'cabinet'}_${sid}_${tid}_${vid}.png`;
          cards.push(`<article class="gallery-card">
            <img src="${dataUrl}" alt="${esc(scfg.name)}">
            <div class="gallery-card-body">
              <strong>#${count} · ${esc(scfg.name)}</strong>
              <span>配色：${esc(tcfg?.label || tid)}</span>
              <span>視角：${esc(vcfg?.label || vid)}</span>
              <div class="gallery-links">
                <a href="${dataUrl}" download="${esc(fileName)}">⬇ 下載高畫質 PNG</a>
              </div>
            </div>
          </article>`);
        });
      });
    });

    $('instant-gallery-wrap').hidden = false;
    $('instant-gallery-meta').textContent = `已完成 ${count} 張 720×720 電商情境圖`;
    $('instant-gallery').innerHTML = cards.join('');
    notify(`⚡ 已即時生成 ${count} 張多場景電商情境圖！可直接預覽或點擊下載 PNG。`);
  }

  async function startRealBlenderBatch() {
    const { sceneIds, themeIds, views, total } = getSelectedMatrix();
    if (!total) {
      notify('請至少勾選 1 個場景、1 種配色與 1 個視角', true);
      return;
    }
    try {
      $('blender-matrix-btn').disabled = true;
      notify(`🔥 正在啟動 A+B 雙引擎光追批次算圖（共 ${total} 組，每組含 3D光追 + AI攝影棚合成 + 透明去背圖）…`);
      const batch = await api('/api/ecommerce-scenes/batches', {
        method: 'POST',
        body: JSON.stringify({
          cabinet: state.cabinet,
          currentScene: state.currentScene,
          sceneIds,
          themeIds,
          views,
          samples: Number($('matrix-samples').value || 32),
          aiStyleId: $('ai-style-select') ? $('ai-style-select').value : 'AI_NORDIC_SUNLIT_LOFT',
          aiPrompt: $('ai-prompt-input') ? $('ai-prompt-input').value : ''
        })
      });
      state.activeBatchId = batch.batchId;
      renderBlenderBatch(batch);
      pollBlenderBatch(batch.batchId);
    } catch (e) {
      notify(e.message, true);
    } finally {
      $('blender-matrix-btn').disabled = false;
    }
  }

  function renderBlenderBatch(batch) {
    if (!batch) return;
    $('blender-batch-status').textContent = `狀態：${batch.state === 'completed' ? '已完成' : 'A+B 雙引擎渲染中'} (${batch.completed}/${batch.total} · 成功 ${batch.succeeded})`;
    const zipLink = $('download-zip-link');
    if (batch.succeeded > 0) {
      zipLink.hidden = false;
      zipLink.href = `/api/ecommerce-scenes/batches/${encodeURIComponent(batch.batchId)}/zip?workspace=${encodeURIComponent(tenant)}`;
    } else {
      zipLink.hidden = true;
    }
    $('blender-gallery').innerHTML = (batch.items || []).map(item => {
      const base = `/api/ecommerce-scenes/batches/${encodeURIComponent(batch.batchId)}/items/${encodeURIComponent(item.itemId)}/download`;
      const qs = `?workspace=${encodeURIComponent(tenant)}`;
      const imgId = `bimg-${batch.batchId}-${item.itemId}`;
      const modeTabs = item.state === 'succeeded'
        ? `<div class="btn-group">
            <button type="button" class="btn-xs primary batch-img-tab" data-target="${imgId}" data-src="${base}/png${qs}&inline=true">🅰️ 3D 實景光追</button>
            <button type="button" class="btn-xs batch-img-tab" data-target="${imgId}" data-src="${base}/ai_png${qs}&inline=true">🅱️ AI 攝影棚合成</button>
            <button type="button" class="btn-xs batch-img-tab" data-target="${imgId}" data-src="${base}/cutout_png${qs}&inline=true">✂️ 透明去背地影</button>
          </div>`
        : '';
      const imgHtml = item.state === 'succeeded'
        ? `<img id="${imgId}" src="${base}/ai_png${qs}&inline=true" alt="${esc(item.sceneName)}">`
        : `<div class="photoreal-loading">
            ${item.state === 'running' ? '🔥 Blender Cycles GPU + AI 攝影棚雙引擎算圖中…' : (item.state === 'queued' ? '⏳ 排隊等待中…' : '⚠️ ' + esc(item.error || '失敗'))}
          </div>`;
      const linksHtml = item.state === 'succeeded'
        ? `<div class="gallery-links">
            <a href="${base}/ai_png${qs}">🅱️ AI合成圖 ↓</a>
            <a href="${base}/png${qs}">🅰️ 3D光追圖 ↓</a>
            <a href="${base}/cutout_png${qs}">✂️ 去背圖 ↓</a>
            <a href="${base}/glb${qs}">GLB ↓</a>
          </div>`
        : '';
      return `<article class="gallery-card">
        ${imgHtml}
        <div class="gallery-card-body">
          ${modeTabs}
          <strong>#${item.index} · ${esc(item.sceneName)}</strong>
          <span>配色：${esc(item.themeLabel)}</span>
          <span>視角：${esc(item.viewLabel)} ${item.renderTimeSec ? `(${item.renderTimeSec}s · ${item.device || 'GPU'})` : ''}</span>
          ${linksHtml}
        </div>
      </article>`;
    }).join('');

    document.querySelectorAll('.batch-img-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetImg = $(btn.dataset.target);
        if (targetImg) targetImg.src = btn.dataset.src;
        const parent = btn.parentElement;
        if (parent) {
          parent.querySelectorAll('.batch-img-tab').forEach(b => b.classList.remove('primary'));
        }
        btn.classList.add('primary');
      });
    });

    const first = (batch.items || [])[0];
    if (first && $('single-photoreal-box') && !$('single-photoreal-box').hidden) {
      const base = `/api/ecommerce-scenes/batches/${encodeURIComponent(batch.batchId)}/items/${encodeURIComponent(first.itemId)}/download`;
      const qs = `?workspace=${encodeURIComponent(tenant)}`;
      $('single-photoreal-status').textContent = first.state === 'succeeded'
        ? `🟢 A+B 雙引擎渲染完成 (${first.renderTimeSec || ''}s · Blender ${first.blenderVersion || ''} ${first.device || 'OPTIX'})`
        : (first.state === 'running' ? '🔥 Blender Cycles + AI 攝影棚渲染中（約 5~9 秒）…' : first.error || '排隊中…');
      if (first.state === 'succeeded') {
        $('single-photoreal-content').innerHTML = `
          <div class="photoreal-meta">
            <h4>🅰️ 方案 A：Blender 3D 高模實景光追圖</h4>
            <img class="photoreal-hero-img" src="${base}/png${qs}&inline=true" alt="方案 A 3D 實景光追圖">
            <div class="gallery-links">
              <a class="btn-sm primary" href="${base}/png${qs}">⬇ 下載方案 A (3D 光追 PNG)</a>
              <a class="btn-sm" href="${base}/glb${qs}">⬇ 下載 3D 場景 (.glb)</a>
            </div>
          </div>
          <div class="photoreal-meta">
            <h4>🅱️ 方案 B：AI 實景攝影棚合成圖（100% 鎖定櫃體與地影）</h4>
            <img class="photoreal-hero-img" src="${base}/ai_png${qs}&inline=true" alt="方案 B AI 攝影棚合成圖">
            <div class="gallery-links">
              <a class="btn-sm primary" href="${base}/ai_png${qs}">⬇ 下載方案 B (AI 實景合成 PNG)</a>
              <a class="btn-sm" href="${base}/cutout_png${qs}">⬇ 下載透明去背+光追地影圖 (PNG)</a>
            </div>
          </div>`;
      } else {
        $('single-photoreal-content').innerHTML = `<div class="photoreal-loading">🔥 正在呼叫本機 Blender 5.2 Cycles (NVIDIA OptiX GPU) 算圖並合成 AI 實景攝影棚，請稍候約 5～9 秒…</div>`;
      }
    }
  }

  async function startSinglePhotorealRender() {
    if (!state.cabinet || !state.currentScene) return;
    try {
      $('single-photoreal-box').hidden = false;
      $('single-photoreal-status').textContent = '🔥 啟動 A+B 雙引擎光追…';
      $('single-photoreal-content').innerHTML = `<div class="photoreal-loading">🔥 正在呼叫本機 Blender 5.2 Cycles (NVIDIA OptiX GPU) 算圖並合成 AI 實景攝影棚，請稍候約 5～9 秒…</div>`;
      const batch = await api('/api/ecommerce-scenes/batches', {
        method: 'POST',
        body: JSON.stringify({
          cabinet: state.cabinet,
          currentScene: state.currentScene,
          sceneIds: [state.currentScene.id],
          themeIds: [state.cabinet.themeId || 'THEME_NORDIC_OAK'],
          views: [$('scene-view').value || 'THREE_QUARTER'],
          samples: 36,
          aiStyleId: $('ai-style-select') ? $('ai-style-select').value : 'AI_NORDIC_SUNLIT_LOFT',
          aiPrompt: $('ai-prompt-input') ? $('ai-prompt-input').value : ''
        })
      });
      state.activeBatchId = batch.batchId;
      renderBlenderBatch(batch);
      pollBlenderBatch(batch.batchId);
    } catch (e) {
      notify(e.message, true);
    }
  }

  async function pollBlenderBatch(batchId) {
    clearTimeout(state.pollTimer);
    try {
      const batch = await api(`/api/ecommerce-scenes/batches/${encodeURIComponent(batchId)}`);
      renderBlenderBatch(batch);
      if (batch.state === 'running') {
        state.pollTimer = setTimeout(() => pollBlenderBatch(batchId), 2500);
      } else {
        notify(`🎉 A+B 雙引擎批次渲染完成！每組皆已產出 🅰️ 3D光追圖、🅱️ AI攝影棚合成圖 與 ✂️ 透明去背圖！`);
      }
    } catch (e) {
      notify(e.message, true);
    }
  }

  // ==================== WIRE UI EVENTS ====================
  function bindEvents() {
    ['cab-name', 'cab-sku', 'cab-depth', 'cab-panel', 'cab-door', 'cab-gap'].forEach(id => {
      $(id).addEventListener('change', () => {
        state.cabinet.name = $('cab-name').value;
        state.cabinet.sku = $('cab-sku').value;
        state.cabinet.depthMm = Number($('cab-depth').value || 295);
        state.cabinet.panelMm = Number($('cab-panel').value || 15);
        state.cabinet.doorMm = Number($('cab-door').value || 15);
        state.cabinet.gapMm = Number($('cab-gap').value || 2);
        syncCabinetHeaderBadge();
        refreshPreviewPlan();
      });
    });

    $('add-col-btn').addEventListener('click', () => {
      if (state.cabinet.columns.length >= 5) {
        notify('單組並排上限為 5 欄櫃體', true);
        return;
      }
      state.cabinet.columns.push({
        widthMm: 424,
        heightMm: 900,
        rows: 3,
        cells: [{ mode: 'DOOR' }, { mode: 'OPEN' }, { mode: 'DOOR' }]
      });
      renderColumnsEditor();
      refreshPreviewPlan();
    });

    $('remove-col-btn').addEventListener('click', () => {
      if (state.cabinet.columns.length <= 1) return;
      state.cabinet.columns.pop();
      renderColumnsEditor();
      refreshPreviewPlan();
    });

    ['scene-name', 'scene-category', 'scene-lighting', 'scene-view', 'room-w', 'room-d', 'room-h', 'wall-color', 'side-color', 'floor-color'].forEach(id => {
      $(id).addEventListener('change', () => {
        if (!state.currentScene) return;
        state.currentScene.name = $('scene-name').value;
        state.currentScene.category = $('scene-category').value;
        state.currentScene.lightingPreset = $('scene-lighting').value;
        state.currentScene.roomWidthM = Number($('room-w').value || 5.6);
        state.currentScene.roomDepthM = Number($('room-d').value || 4.2);
        state.currentScene.roomHeightM = Number($('room-h').value || 3.0);
        state.currentScene.wallColorHex = $('wall-color').value;
        state.currentScene.sideWallColorHex = $('side-color').value;
        state.currentScene.floorColorHex = $('floor-color').value;
        renderCameraPills();
        refreshPreviewPlan();
      });
    });

    $('sel-rot').addEventListener('change', () => {
      if (!state.currentScene) return;
      const deg = Number($('sel-rot').value || 0);
      if (state.selectedTarget.kind === 'cabinet') {
        state.currentScene.productPose.rotationDeg = deg;
      } else {
        const p = state.currentScene.props?.[state.selectedTarget.index];
        if (p) p.rotationDeg = deg;
      }
      syncSelectedBar();
      refreshPreviewPlan();
    });

    $('sel-color').addEventListener('input', () => {
      const p = state.currentScene?.props?.[state.selectedTarget.index];
      if (!p) return;
      p.colorHex = $('sel-color').value;
      drawFloorplan();
      renderLive3DScene($('scene3d-canvas'), state.currentScene, state.previewPlan?.cabinetSpec, $('scene-view').value, state.camOrbit);
    });

    $('sel-w').addEventListener('change', () => {
      const p = state.currentScene?.props?.[state.selectedTarget.index];
      if (!p) return;
      p.widthM = Math.max(0.2, Math.min(4.0, Number($('sel-w').value) || 1.0));
      refreshPreviewPlan();
    });

    $('sel-d').addEventListener('change', () => {
      const p = state.currentScene?.props?.[state.selectedTarget.index];
      if (!p) return;
      p.depthM = Math.max(0.1, Math.min(4.0, Number($('sel-d').value) || 0.6));
      refreshPreviewPlan();
    });

    $('sel-delete-btn').addEventListener('click', () => {
      if (state.selectedTarget.kind !== 'prop' || !state.currentScene?.props) return;
      state.currentScene.props.splice(state.selectedTarget.index, 1);
      state.selectedTarget = { kind: 'cabinet', index: -1 };
      syncSelectedBar();
      refreshPreviewPlan();
    });

    $('new-scene-btn').addEventListener('click', () => {
      state.currentScene = {
        id: 'SCENE_CUSTOM_' + Date.now().toString(36).toUpperCase(),
        name: '我的自訂電商場景',
        category: '自訂空間',
        builtin: false,
        roomWidthM: 5.4,
        roomDepthM: 4.0,
        roomHeightM: 3.0,
        wallColorHex: '#c9bfae',
        sideWallColorHex: '#b5bcb5',
        floorColorHex: '#826142',
        lightingPreset: 'WARM_SUNLIGHT',
        productPose: { x: 0.0, y: 1.12, z: 0.0, rotationDeg: 0 },
        props: [
          { id: 'p1', type: 'RUG', label: '地毯', x: 0.0, y: 0.3, z: 0.0, widthM: 2.2, depthM: 1.4, heightM: 0.015, rotationDeg: 0, colorHex: '#e5ddd0', accentColorHex: '#cabba6' },
          { id: 'p2', type: 'PLANT', label: '室內植栽', x: 1.1, y: 1.05, z: 0.0, widthM: 0.42, depthM: 0.42, heightM: 0.92, rotationDeg: 0, colorHex: '#2e6b47', accentColorHex: '#c87d55' }
        ]
      };
      syncSceneInputsFromState();
      refreshPreviewPlan();
      notify('✨ 已建立新房間！可點擊上方家具道具加入房間，並在 2D 平面圖直接拖拉擺放。');
    });

    $('save-scene-btn').addEventListener('click', async () => {
      if (!state.currentScene) return;
      try {
        const payload = clone(state.currentScene);
        if (payload.builtin) {
          payload.id = 'SCENE_CUSTOM_' + Date.now().toString(36).toUpperCase();
          payload.name = $('scene-name').value + ' (自訂版)';
          payload.builtin = false;
        }
        const saved = await api('/api/ecommerce-scenes/scenes', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        const ov = await api('/api/ecommerce-scenes/overview');
        state.overview = ov;
        state.currentScene = clone(saved);
        syncSceneInputsFromState();
        renderMatrixChecklists();
        notify(`💾 已儲存場景「${saved.name}」至場景庫！下方步驟 3 矩陣清單已同步更新。`);
      } catch (e) {
        notify(e.message, true);
      }
    });

    $('delete-scene-btn').addEventListener('click', async () => {
      if (!state.currentScene || state.currentScene.builtin) return;
      try {
        await api(`/api/ecommerce-scenes/scenes/${encodeURIComponent(state.currentScene.id)}`, { method: 'DELETE' });
        const ov = await api('/api/ecommerce-scenes/overview');
        state.overview = ov;
        state.currentScene = clone(ov.scenes[0]);
        syncSceneInputsFromState();
        renderMatrixChecklists();
        refreshPreviewPlan();
        notify('已刪除自訂場景。');
      } catch (e) {
        notify(e.message, true);
      }
    });

    $('reset-cam-btn').addEventListener('click', () => {
      state.camOrbit = { yawOffset: 0, pitchOffset: 0, zoom: 1.0, dragging: false, lastX: 0, lastY: 0 };
      renderLive3DScene($('scene3d-canvas'), state.currentScene, state.previewPlan?.cabinetSpec, $('scene-view').value, state.camOrbit);
    });

    $('snapshot-png-btn').addEventListener('click', () => {
      const canvas = $('scene3d-canvas');
      const url = canvas.toDataURL('image/png');
      const a = document.createElement('a');
      a.href = url;
      a.download = `${state.cabinet?.sku || 'cabinet'}_${state.currentScene?.id || 'scene'}.png`;
      a.click();
    });

    $('check-all-scenes').addEventListener('click', () => {
      document.querySelectorAll('input[name="mat-scene"]').forEach(cb => { cb.checked = true; });
      updateMatrixFormula();
    });

    $('check-all-themes').addEventListener('click', () => {
      document.querySelectorAll('input[name="mat-theme"]').forEach(cb => { cb.checked = true; });
      updateMatrixFormula();
    });

    $('instant-matrix-btn').addEventListener('click', generateInstant3DMatrixGallery);
    $('blender-matrix-btn').addEventListener('click', startRealBlenderBatch);
    if ($('render-single-photoreal-btn')) {
      $('render-single-photoreal-btn').addEventListener('click', startSinglePhotorealRender);
    }
    if ($('sel-ph-model')) {
      $('sel-ph-model').addEventListener('change', () => {
        const p = state.currentScene?.props?.[state.selectedTarget.index];
        if (!p) return;
        const val = $('sel-ph-model').value;
        if (val) {
          p.glbPath = val;
        } else {
          delete p.glbPath;
        }
        refreshPreviewPlan();
        notify('🏛️ 已切換此家具的 3D 高模資產設定！點「🔥 立即算這張 A+B 雙引擎逼真圖」即可套用。');
      });
    }
    if ($('upload-glb-btn') && $('upload-glb-input')) {
      $('upload-glb-btn').addEventListener('click', () => $('upload-glb-input').click());
      $('upload-glb-input').addEventListener('change', async (ev) => {
        const file = ev.target.files && ev.target.files[0];
        if (!file || !state.currentScene) return;
        try {
          notify(`📥 正在匯入 3D 家具模型「${file.name}」…`);
          const reader = new FileReader();
          const dataBase64 = await new Promise((resolve, reject) => {
            reader.onload = () => resolve(String(reader.result || ''));
            reader.onerror = () => reject(new Error('讀取檔案失敗'));
            reader.readAsDataURL(file);
          });
          const res = await api('/api/ecommerce-scenes/props/upload-glb', {
            method: 'POST',
            body: JSON.stringify({ filename: file.name, dataBase64 })
          });
          state.currentScene.props = state.currentScene.props || [];
          state.currentScene.props.push({
            id: res.propId,
            type: 'CUSTOM_BOX',
            label: res.label,
            glbPath: res.glbPath,
            x: -0.8,
            y: 0.4,
            z: 0.0,
            widthM: 0.75,
            depthM: 0.75,
            heightM: 0.85,
            rotationDeg: 0,
            colorHex: '#a38970',
            accentColorHex: '#5e4934'
          });
          state.selectedTarget = { kind: 'prop', index: state.currentScene.props.length - 1 };
          syncSelectedBar();
          await refreshPreviewPlan();
          notify(`🎉 已將「${res.label}」放入房間！可在 2D 平面圖拖拉位置，Blender 光追算圖時將自動載入此高模 GLB。`);
        } catch (err) {
          notify(err.message, true);
        } finally {
          ev.target.value = '';
        }
      });
    }

    // Step Tabs Switching Logic
    function switchTab(tabId) {
      document.querySelectorAll('.wf-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
      });
      document.querySelectorAll('.tab-section').forEach(sec => {
        sec.classList.toggle('active', sec.id === tabId);
      });
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    document.querySelectorAll('.wf-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    document.querySelectorAll('.next-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.go));
    });
  }

  async function init() {
    try {
      const ov = await api('/api/ecommerce-scenes/overview');
      state.overview = ov;
      $('blender-pill').textContent = ov.blenderAvailable ? '🟢 真實 Blender 已連線' : '🟡 Blender 未偵測（可使用即時 3D 矩陣）';

      $('scene-lighting').innerHTML = (ov.lightingPresets || []).map(l =>
        `<option value="${esc(l.id)}">${esc(l.label)}</option>`
      ).join('');
      $('scene-view').innerHTML = (ov.cameraViews || []).map(v =>
        `<option value="${esc(v.id)}">${esc(v.label)}</option>`
      ).join('');
      if ($('sel-ph-model') && ov.polyhavenModels) {
        $('sel-ph-model').innerHTML = `<option value="">✨ 預設（高擬真皺褶布藝滾邊沙發 / 自動匹配高模）</option>` +
          ov.polyhavenModels.map(m => `<option value="${esc(m.glbPath)}">🏛️ ${esc(m.label)}</option>`).join('');
      }

      state.cabinet = clone(ov.cabinetPresets[1] || ov.cabinetPresets[0]);
      state.cabinet.name = '收納王妃雙併六格組合櫃';
      state.cabinet.sku = 'SQ-MOD-6GRID';
      state.currentScene = clone(ov.scenes[0]);

      syncCabinetInputsFromState();
      syncSceneInputsFromState();
      renderPropPalette();
      renderCameraPills();
      renderMatrixChecklists();
      setupFloorplanEvents();
      setup3DViewportEvents();
      bindEvents();

      if (ov.batches?.length) {
        renderBlenderBatch(ov.batches[0]);
      }
      await refreshPreviewPlan();
    } catch (e) {
      notify('載入電商場景工坊失敗：' + e.message, true);
    }
  }

  // ---- AI interior designer (Claude Cloud OR Local Ollama/LM Studio) ----
  function updateAiProviderVisibility(provider) {
    const isLocal = provider === 'local';
    const antBox = $('ai-anthropic-box');
    const locBox = $('ai-local-box');
    if (antBox) antBox.hidden = isLocal;
    if (locBox) locBox.hidden = !isLocal;
  }

  document.querySelectorAll('input[name="ai-provider"]').forEach(r => {
    r.addEventListener('change', () => updateAiProviderVisibility(r.value));
  });

  async function refreshAiKeyStatus() {
    try {
      const s = await api('/api/ecommerce-scenes/ai-settings');
      const provider = s.provider || 'anthropic';
      const rad = document.querySelector(`input[name="ai-provider"][value="${provider}"]`);
      if (rad) rad.checked = true;
      updateAiProviderVisibility(provider);

      if ($('ai-local-url')) $('ai-local-url').value = s.localBaseUrl || 'http://127.0.0.1:11434/v1';
      if ($('ai-local-model')) $('ai-local-model').value = s.localModel || '';

      if (provider === 'local') {
        $('ai-key-status').textContent = `AI 來源：🖥️ 本機 AI (${s.localModel || '未指定模型'})`;
      } else {
        $('ai-key-status').textContent = s.hasKey
          ? 'AI 來源：☁️ Claude（✅ 金鑰已設定）'
          : 'AI 來源：☁️ Claude（⚠️ 尚未設定金鑰，點此填寫）';
      }
    } catch (e) {
      $('ai-key-status').textContent = 'AI 來源設定：讀取失敗';
    }
  }

  $('ai-local-scan')?.addEventListener('click', async () => {
    const btn = $('ai-local-scan');
    btn.disabled = true;
    btn.textContent = '掃描中…';
    try {
      const res = await api('/api/ecommerce-scenes/ai-local-models');
      if (res.ok && res.models?.length) {
        const dl = $('ai-local-model-list');
        if (dl) {
          dl.innerHTML = res.models.map(m => `<option value="${esc(m)}"></option>`).join('');
        }
        if ($('ai-local-model') && !$('ai-local-model').value) {
          $('ai-local-model').value = res.models[0];
        }
        notify(`🔍 找到本機模型：${res.models.join(', ')}`);
      } else {
        notify(`⚠️ ${res.error || '未偵測到本機模型，請先啟動 Ollama 或 LM Studio'}`, true);
      }
    } catch (e) {
      notify(`偵測失敗：${e.message}`, true);
    } finally {
      btn.disabled = false;
      btn.textContent = '🔍 偵測模型';
    }
  });

  $('ai-key-save').addEventListener('click', async () => {
    const provider = document.querySelector('input[name="ai-provider"]:checked')?.value || 'anthropic';
    const payload = {
      provider,
      anthropicApiKey: $('ai-key-input')?.value || '',
      localBaseUrl: $('ai-local-url')?.value || '',
      localModel: $('ai-local-model')?.value || ''
    };
    try {
      await api('/api/ecommerce-scenes/ai-settings', { method: 'POST', body: JSON.stringify(payload) });
      if ($('ai-key-input')) $('ai-key-input').value = '';
      notify('✅ 已成功儲存 AI 設定！');
      refreshAiKeyStatus();
    } catch (e) {
      notify(e.message, true);
    }
  });

  $('ai-layout-btn').addEventListener('click', async () => {
    const btn = $('ai-layout-btn');
    const resultBox = $('ai-result');
    const prompt = $('ai-prompt').value.trim();
    if (!prompt) { notify('請先輸入想要的空間風格。', true); return; }
    btn.disabled = true;
    const oldLabel = btn.textContent;
    btn.textContent = '🤖 AI 設計中…（約 10~30 秒）';
    try {
      const scene = await api('/api/ecommerce-scenes/ai-layout', { method: 'POST', body: JSON.stringify({ prompt, cabinet: state.cabinet }) });
      state.currentScene = scene;
      state.selectedTarget = { kind: 'cabinet', index: -1 };
      syncSceneInputsFromState();
      refreshPreviewPlan();
      const lines = [`✨ ${scene.name}：AI 擺了 ${scene.props.length} 件家具。${scene.aiRationale || ''}`];
      if (scene.aiDropped && scene.aiDropped.length) lines.push(`（已略過：${scene.aiDropped.join('、')}）`);
      lines.push('可在 2D 平面圖拖拉微調，滿意後按「儲存場景至場景庫」。');
      resultBox.textContent = lines.join(' ');
      resultBox.hidden = false;
      notify('✨ AI 已完成場景設計，預覽已更新。');
    } catch (e) {
      notify(e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = oldLabel;
    }
  });

  refreshAiKeyStatus();

  init();
})();


// ---- Image lightbox: click any generated image to enlarge it in-page (no download) ----
(function initImageLightbox() {
  const style = document.createElement('style');
  style.textContent = `
    .gallery-card > img, .photoreal-hero-img, .gallery-card img { cursor: zoom-in; }
    #img-lightbox { position: fixed; inset: 0; z-index: 9999; background: rgba(12,12,12,0.92); display: none; overflow: auto; cursor: zoom-out; }
    #img-lightbox.open { display: flex; align-items: center; justify-content: center; }
    #img-lightbox img { max-width: 96vw; max-height: 94vh; object-fit: contain; box-shadow: 0 8px 40px rgba(0,0,0,0.6); border-radius: 6px; background: #fff; }
    #img-lightbox.full { display: block; }
    #img-lightbox.full img { max-width: none; max-height: none; cursor: zoom-out; }
    #img-lightbox .lb-hint { position: fixed; top: 12px; right: 18px; color: #eee; font-size: 13px; background: rgba(0,0,0,0.5); padding: 6px 12px; border-radius: 14px; pointer-events: none; }
  `;
  document.head.appendChild(style);

  const box = document.createElement('div');
  box.id = 'img-lightbox';
  box.innerHTML = '<img alt=""><div class="lb-hint">點圖放大／縮小 · 點背景或按 Esc 關閉</div>';
  document.body.appendChild(box);
  const big = box.querySelector('img');

  const close = () => { box.classList.remove('open', 'full'); big.removeAttribute('src'); };
  box.addEventListener('click', (e) => {
    if (e.target === big) { box.classList.toggle('full'); } else { close(); }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

  document.addEventListener('click', (e) => {
    const img = e.target.closest && e.target.closest('.gallery-card img, img.photoreal-hero-img');
    if (!img || !img.src) return;
    e.preventDefault();
    big.src = img.currentSrc || img.src;
    box.classList.remove('full');
    box.classList.add('open');
  });
})();
