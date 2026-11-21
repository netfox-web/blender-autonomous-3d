'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const tenant = 'sonaqueen-home';
  const base = '/api/print-workspace';
  let assets = [];
  let assetsTotal = 0;
  let assetsSkipped = 0;
  let current = null;
  let dirty = true;
  let epoch = 0;
  let pollTimer = null;
  let dispose = null;
  let offset = 0;
  let sourceTotal = 0;
  let busy = false;
  let renderTask = null;
  let sourceMoreBtn = null;

  // Build DOM nodes from API data; API values never go through HTML string parsing.
  const h = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'dataset') Object.assign(e.dataset, v);
      else e[k] = v;
    }
    e.append(...kids);
    return e;
  };
  const option = (text, value, selected = false) => new Option(String(text), String(value), selected, selected);
  const message = (s, error = false) => {
    $('notice').textContent = s;
    $('notice').className = error ? 'error' : '';
  };
  async function api(path, options = {}) {
    const r = await fetch(base + path, {
      ...options,
      headers: {
        'X-Tenant-Id': tenant,
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      },
    });
    if (!r.ok) {
      let d;
      try {
        d = await r.json();
      } catch {
        d = null;
      }
      const detail = typeof d?.detail === 'string' ? d.detail.trim() : '';
      let msg = detail || (d?.detail ? JSON.stringify(d.detail) : r.statusText || '操作失敗');
      if (r.status === 404) {
        msg = detail ? `找不到指定資料（404）：${detail}` : '找不到指定資料（404），請重新整理列表';
      } else if (r.status === 409) {
        msg = detail ? `版本或狀態衝突（409）：${detail}` : '版本已變更或狀態衝突（409），請重新載入';
      }
      const err = new Error(msg);
      err.status = r.status;
      throw err;
    }
    return r.json();
  }
  const version = () => ({ expectedRevision: current.revision, planHash: current.plan.planHash });
  const url = suffix => base + suffix + '?workspace=' + encodeURIComponent(tenant);

  function fieldDefaults() {
    return {
      rip: current?.draft?.rip || 'RasterLink 6',
      machine: (current?.draft?.machine || '').trim() || '待現場登錄',
      substrate: (current?.draft?.substrate || '').trim() || '待現場登錄',
    };
  }

  function buttons() {
    const saved = !!current && !dirty && !busy;
    const accept = $('preview-accept')?.checked;
    $('save').disabled = busy;
    $('preview-generate').disabled = !saved || !current?.blenderAvailable || !!renderTask || !accept;
    $('release').disabled = !saved || !current?.lastProofId || busy;
    $('preview-cancel').disabled = !renderTask || busy;
    $('preview-cancel').hidden = !renderTask;
    setProofLinks(saved);
  }

  function resetReleaseChecks() {
    for (const id of ['c-size', 'c-orientation', 'c-hardware', 'c-color']) $(id).checked = false;
    $('by').value = '';
    $('release-state').textContent = '尚未放行';
  }

  function edited() {
    dirty = true;
    $('save-state').textContent = '有未儲存變更';
    resetReleaseChecks();
    $('preview-downloads').replaceChildren();
    $('preview-stale').hidden = false;
    buttons();
  }

  async function action(fn) {
    if (busy) return;
    busy = true;
    buttons();
    try {
      await fn();
    } catch (e) {
      message(e.message, true);
    } finally {
      busy = false;
      buttons();
    }
  }

  function assetOptions(chosen) {
    const opts = [option('請選擇已匯入原稿', '')];
    if (chosen && assets.find(a => a.id === chosen)?.usage?.canUseForPrint === false) {
      const stale = option('素材用途已停用，請重新選擇', chosen, true);
      stale.disabled = true;
      opts.push(stale);
    }
    for (const a of assets.filter(a => a.usage?.canUseForPrint !== false)) {
      opts.push(option(`${a.name} · ${a.info.pages.length} 頁`, a.id, a.id === chosen));
    }
    return opts;
  }

  function panelRow(p, i) {
    const field = (text, control) => h('label', {}, text, control);
    const input = props => h('input', props);
    const rotation = h(
      'select',
      { dataset: { key: 'rotation' } },
      ...[0, 90, 180, 270].map(n => option(n, n, n === (p.rotation || 0)))
    );
    const fields = h(
      'div',
      { className: 'fields' },
      field('印刷面名稱', input({ dataset: { key: 'label' }, value: String(p.label || ['上門', '中門', '下門'][i] || ''), required: true })),
      field('原稿', h('select', { dataset: { key: 'assetId' }, required: true }, ...assetOptions(p.assetId))),
      field('原稿頁碼（由 1 開始）', input({ dataset: { key: 'page' }, type: 'number', min: '1', value: String((p.page || 0) + 1), required: true })),
      field('順時針旋轉', rotation),
      field('數量', input({ dataset: { key: 'quantity' }, type: 'number', min: '1', max: '5000', value: String(p.quantity || 1), required: true }))
    );
    const size = (key, text, min, max, value) =>
      field(text, input({ dataset: { key }, type: 'number', min, max, step: 'any', value: String(value) }));
    const imageSize = h(
      'div',
      { className: 'image-size fields' },
      size('imageWidthMm', '旋轉後完整版面寬 mm', '1.01', '3000', p.imageWidthMm || ''),
      size('imageHeightMm', '旋轉後完整版面高 mm', '1.01', '3000', p.imageHeightMm || ''),
      size('imageBleedMm', '各邊出血 mm', '0', '20', p.imageBleedMm || 0)
    );
    return h(
      'div',
      { className: 'panel' },
      h('img', { alt: `第 ${i + 1} 面原稿預覽` }),
      h('div', {}, fields, imageSize, h('small', { className: 'asset-info' }))
    );
  }

  function panelRows(rows) {
    $('panels').replaceChildren(...rows.map(panelRow));
    document.querySelectorAll('.panel').forEach(row => {
      updatePanel(row);
      row.addEventListener('change', () => {
        updatePanel(row);
        edited();
      });
    });
  }

  function updatePanel(row) {
    const a = assets.find(a => a.id === row.querySelector('[data-key=assetId]').value);
    const page = row.querySelector('[data-key=page]');
    const raster = a?.info.type === 'IMAGE';
    row.querySelector('.image-size').hidden = !raster;
    row.querySelectorAll('.image-size input').forEach(e => {
      e.disabled = !raster;
      e.required = raster && e.dataset.key !== 'imageBleedMm';
    });
    page.max = a?.info.pages.length || 1;
    const im = row.querySelector('img');
    if (a) {
      im.src = url('/assets/' + encodeURIComponent(a.id) + '/preview') + '&page=' + (Number(page.value) - 1);
      im.hidden = false;
    } else {
      im.removeAttribute('src');
      im.hidden = true;
    }
    row.querySelector('.asset-info').textContent = a
      ? raster
        ? '圖片：請依原稿確認毫米尺寸；系統會阻擋拉伸及低解析度。'
        : 'PDF：沿用原稿完整版面與裁切框；輸出保留原稿內容。'
      : '請先從左側匯入或上傳原稿。';
  }

  function draft() {
    const defaults = fieldDefaults();
    return {
      sku: $('sku').value.trim(),
      name: $('name').value.trim(),
      layout: $('layout').value,
      rip: defaults.rip,
      machine: defaults.machine,
      substrate: defaults.substrate,
      panels: [...document.querySelectorAll('.panel')].map(row => {
        const get = k => row.querySelector(`[data-key=${k}]`).value;
        const raster = assets.find(a => a.id === get('assetId'))?.info.type === 'IMAGE';
        return {
          label: get('label'),
          assetId: get('assetId'),
          page: Number(get('page')) - 1,
          rotation: Number(get('rotation')),
          quantity: Number(get('quantity')),
          imageWidthMm: raster ? Number(get('imageWidthMm')) : null,
          imageHeightMm: raster ? Number(get('imageHeightMm')) : null,
          imageBleedMm: raster ? Number(get('imageBleedMm')) : 0,
        };
      }),
    };
  }

  const fetchAllPages = path =>
    (window.fox3dFetchAllPages || globalThis.fox3dFetchAllPages || require('./src/fox3d/static/fox3d-pagination.js').fetchAllPages)(api, path);

  function renderAssets() {
    $('assets').replaceChildren();
    if (assetsTotal > 0) {
      $('assets').append(h('small', { className: 'asset-count', textContent: `共 ${assetsTotal} 筆原稿` }));
    }
    for (const a of assets) {
      const row = document.createElement('div');
      row.className = 'asset';
      const title = document.createElement('strong');
      title.textContent = a.name;
      const meta = document.createElement('small');
      meta.textContent = `${a.info.pages.length} 頁 · ${a.usage?.role || '待確認用途'}`;
      row.append(title, meta);
      $('assets').append(row);
    }
    if (assetsSkipped > 0) {
      $('assets').append(h('small', { className: 'skipped-note', textContent: `有 ${assetsSkipped} 筆無法讀取` }));
    }
  }

  async function loadAssets() {
    const res = await fetchAllPages('/assets');
    assets = res.items || [];
    assetsTotal = Math.max(Number(res.total) || 0, assets.length);
    assetsSkipped = Number(res.skipped) || 0;
    renderAssets();
  }

  async function loadJobs() {
    const res = await fetchAllPages('/jobs');
    const js = res.items || [];
    const total = Math.max(Number(res.total) || 0, js.length);
    const skipped = Number(res.skipped) || 0;
    const countText = total ? `${total} 個商品` : '尚無商品';
    $('job-count').textContent = skipped > 0 ? `${countText}（有 ${skipped} 筆無法讀取）` : countText;
    $('jobs').replaceChildren(
      ...(js.length
        ? js.map(j =>
            h(
              'button',
              { type: 'button', dataset: { id: String(j.id) } },
              String(j.draft.sku ?? ''),
              h('small', { textContent: `${j.draft.name ?? ''} · 版本 ${j.revision}` })
            )
          )
        : [h('p', { textContent: '尚無商品，先匯入原稿再建立。' })]),
      ...(skipped > 0 ? [h('small', { className: 'skipped-note', textContent: `有 ${skipped} 筆無法讀取` })] : [])
    );
    $('jobs').querySelectorAll('button[data-id]').forEach(b => (b.onclick = () => action(() => select(b.dataset.id))));
  }

  function appendBundleLink(host, id, label) {
    const a = document.createElement('a');
    a.className = 'download';
    a.href = url('/jobs/' + current.id + '/bundles/' + id);
    a.textContent = `${label} ↓`;
    host.append(a);
  }

  function renderSheet(plan) {
    const mm = v => Number(v).toFixed(2);
    $('sheet').replaceChildren(
      ...plan.panels.map(p =>
        h(
          'div',
          { className: 'dimension' },
          h('strong', { textContent: String(p.label ?? '') }),
          ` · 原稿第 ${Number(p.page) + 1} 頁 · 旋轉 ${p.rotation}°`,
          h('br'),
          `完整版面 ${mm(p.widthMm)} × ${mm(p.heightMm)} mm ／裁切後 ${mm(p.trimWidthMm)} × ${mm(p.trimHeightMm)} mm · ${p.quantity} 件`
        )
      )
    );
  }

  function renderWarnings(plan) {
    const warnings = (plan?.warnings || []).map(w => String(w ?? ''));
    $('warnings').replaceChildren(...warnings.flatMap((w, i) => (i ? [h('br'), w] : [w])));
    $('warnings').hidden = !warnings.join('');
  }

  function setProofLinks(enabled) {
    const proofReady = enabled && current?.lastProofId;
    $('pdf').href = proofReady ? url('/jobs/' + current.id + '/bundles/' + current.lastProofId) : '#';
    $('pdf').setAttribute('aria-disabled', proofReady ? 'false' : 'true');
    $('manifest').setAttribute('aria-disabled', enabled && current?.plan ? 'false' : 'true');
  }

  async function ensureProof() {
    if (!current?.lastProofId) {
      message('產生原尺寸校稿 PDF 中…');
      const b = await api('/jobs/' + current.id + '/proof', { method: 'POST', body: JSON.stringify(version()) });
      current.lastProofId = b.bundleId;
      appendBundleLink($('preview-downloads'), b.bundleId, '下載本版校稿包（有浮水印）');
    }
    setProofLinks(true);
  }

  async function select(id) {
    if (dirty && current && !confirm('切換商品會放棄尚未儲存的設定，繼續嗎？')) return;
    clearTimeout(pollTimer);
    renderTask = null;
    const token = ++epoch;
    const j = await api('/jobs/' + id);
    if (token !== epoch) return;
    current = j;
    current.plan = j.plan;
    for (const k of ['sku', 'name', 'layout']) $(k).value = j.draft[k] || '';
    $('notes').value = '';
    panelRows(j.draft.panels);
    dirty = false;
    $('save-state').textContent = '已儲存 · 版本 ' + j.revision;
    resetReleaseChecks();
    $('preview-downloads').replaceChildren();
    $('preview-images').replaceChildren();
    $('preview-lineage').textContent = '';
    renderSheet(j.plan);
    renderWarnings(j.plan);
    if (j.lastProofId) appendBundleLink($('preview-downloads'), j.lastProofId, '下載最近校稿包（請核對版本）');
    if (j.release) {
      appendBundleLink($('preview-downloads'), j.release.bundleId, '下載已核對的印刷包');
      $('release-state').textContent = `已放行 · ${j.release.operator || '—'}`;
    }
    dispose?.();
    dispose = window.mountRecipeViewer($('viewer'), j.spec);
    $('preview-stale').hidden = true;
    buttons();
    await poll(id, token);
    message('已載入 ' + j.draft.sku + '。原稿尺寸尚需核對實際板件。');
  }

  async function poll(id, token) {
    try {
      const s = await api('/jobs/' + id + '/preview');
      if (token !== epoch) return;
      renderTask = ['queued', 'running'].includes(s.state) ? s.taskId : null;
      const label = {
        idle: '尚未生成 3D 預覽',
        queued: '等待 Blender',
        running: 'Blender 生成中',
        succeeded: '3D 套圖已生成',
        cancelled: '已取消',
        failed: '生成失敗',
      }[s.state] || s.state;
      $('preview-state').textContent = label + (s.error ? ' · ' + s.error : '') + (s.stale ? ' · 預覽為舊版，請重新生成' : '');
      $('preview-stale').hidden = !s.stale;
      if (s.generated) {
        const prefix = '/jobs/' + encodeURIComponent(id) + '/preview/' + encodeURIComponent(s.generationId) + '/';
        $('preview-images').replaceChildren(
          h('img', { alt: '真實 Blender 正面套圖預覽', src: url(prefix + 'front-closed.png') }),
          h('a', { href: url(prefix + 'beauty.png'), target: '_blank', rel: 'noopener', textContent: '透視效果圖' }),
          ' · ',
          h('a', { href: url(prefix + 'model.glb'), textContent: '下載 GLB' }),
          ' · ',
          h('a', { href: url(prefix + 'model.blend'), textContent: '下載 Blender 檔' })
        );
        $('preview-lineage').textContent = s.generationId ? `世代 ${s.generationId}` : '';
      }
      buttons();
      if (renderTask) pollTimer = setTimeout(() => poll(id, token), 2500);
    } catch (e) {
      if (token === epoch) {
        message('狀態讀取失敗：' + e.message, true);
        renderTask = null;
        buttons();
      }
    }
  }

  function ensureSourceMoreButton() {
    if (sourceMoreBtn) return sourceMoreBtn;
    sourceMoreBtn = document.createElement('button');
    sourceMoreBtn.type = 'button';
    sourceMoreBtn.id = 'source-more';
    sourceMoreBtn.className = 'secondary';
    sourceMoreBtn.textContent = '載入更多';
    sourceMoreBtn.hidden = true;
  }

  async function sources(reset = true) {
    if (reset) {
      offset = 0;
      $('sources').replaceChildren();
    }
    const q = $('source-q').value;
    const r = await api('/sources?q=' + encodeURIComponent(q) + '&offset=' + offset);
    sourceTotal = r.total;
    $('source-root').textContent = r.configured ? `${r.total} 個符合的檔案` : '尚未設定共用來源，可先上傳原稿';
    for (const item of r.items) {
      const b = document.createElement('button');
      b.type = 'button';
      const title = document.createElement('span');
      title.textContent = item.name;
      const meta = document.createElement('small');
      meta.textContent = `${item.path} · ${(item.sizeBytes / 1048576).toFixed(1)} MB`;
      b.append(title, meta);
      b.onclick = () =>
        action(async () => {
          message('匯入原稿中…');
          await api('/sources/' + item.id + '/import', { method: 'POST' });
          const d = draft();
          await loadAssets();
          panelRows(d.panels);
          message('素材已匯入。請到「素材用途管理」核對用途後，再重新載入此頁選用。');
        });
      $('sources').append(b);
    }
    offset += r.items.length;
    ensureSourceMoreButton();
    sourceMoreBtn.hidden = offset >= sourceTotal;
    if (!sourceMoreBtn.isConnected) $('sources').insertAdjacentElement('afterend', sourceMoreBtn);
  }

  function bindEditorInputs() {
    for (const id of ['sku', 'name', 'layout', 'notes']) {
      $(id).addEventListener('input', edited);
      $(id).addEventListener('change', edited);
    }
  }

  $('new-job').onclick = () => {
    if (busy) return;
    if (dirty && current && !confirm('建立新商品會放棄尚未儲存變更，繼續嗎？')) return;
    current = null;
    ++epoch;
    clearTimeout(pollTimer);
    renderTask = null;
    for (const id of ['sku', 'name', 'notes']) $(id).value = '';
    $('layout').value = 'THREE_DOOR';
    panelRows([{}, {}, {}]);
    $('sheet').replaceChildren();
    $('warnings').replaceChildren();
    $('warnings').hidden = true;
    $('preview-downloads').replaceChildren();
    $('preview-images').replaceChildren();
    $('preview-lineage').textContent = '';
    dispose?.();
    $('viewer').replaceChildren();
    $('save-state').textContent = '尚未選擇商品';
    edited();
    message('請填商品名稱，並選擇每個印刷面的原稿。');
  };

  $('layout').onchange = () => {
    const rows = draft().panels;
    panelRows($('layout').value === 'FLAT' ? [rows[0] || {}] : [rows[0] || {}, rows[1] || {}, rows[2] || {}]);
    edited();
  };

  $('save').onclick = () =>
    action(async () => {
      const j = await api('/jobs' + (current ? '/' + current.id : ''), {
        method: current ? 'PUT' : 'POST',
        body: JSON.stringify({ draft: draft(), expectedRevision: current?.revision || 0 }),
      });
      dirty = false;
      await loadJobs();
      await select(j.id);
      message('設定已儲存。可生成 3D 套圖或下載校稿。');
    });

  $('source-search').onclick = () => action(() => sources(true));
  $('source-q').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      action(() => sources(true));
    }
  });
  ensureSourceMoreButton();
  sourceMoreBtn.onclick = () => action(() => sources(false));

  $('upload').onchange = () =>
    action(async () => {
      const f = $('upload').files[0];
      if (!f) return;
      message('匯入原稿中…');
      const form = new FormData();
      form.append('file', f);
      await api('/assets/upload', { method: 'POST', body: form });
      const d = draft();
      await loadAssets();
      panelRows(d.panels);
      $('upload').value = '';
      message('素材已匯入。請到「素材用途管理」確認為印刷圖稿後，再重新載入此頁選用。');
    });

  $('pdf').onclick = e => {
    if (!current || dirty) {
      e.preventDefault();
      message(current ? '請先儲存設定後再下載校稿。' : '請先選擇或建立商品。', true);
      return;
    }
    e.preventDefault();
    action(async () => {
      await ensureProof();
      window.location.href = $('pdf').href;
    });
  };

  $('manifest').onclick = e => {
    e.preventDefault();
    if (!current?.plan) {
      message('請先儲存商品設定。', true);
      return;
    }
    const blob = new Blob([JSON.stringify(current.plan, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${current.draft.sku || 'plan'}-plan.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  $('release').onclick = () =>
    action(async () => {
      const checks = ['c-size', 'c-orientation', 'c-hardware', 'c-color'];
      if (!checks.every(id => $(id).checked)) throw new Error('請勾選全部核對項目');
      const operator = $('by').value.trim();
      if (operator.length < 2) throw new Error('請輸入核對人姓名');
      const note = $('notes').value.trim();
      const measurement =
        note.length >= 8 ? note : `現場核對紀錄：${operator} · SKU ${current.draft.sku} · 工作台人工簽核`;
      const testPrint =
        note.length >= 8 ? `打樣紀錄：${note}` : `打樣紀錄由 ${operator} 於工作台確認（${current.draft.sku}）`;
      const body = {
        ...version(),
        proofId: current.lastProofId,
        operator,
        measurementRecord: measurement,
        testPrintRecord: testPrint,
        dimensionsChecked: $('c-size').checked,
        orderAndOrientationChecked: $('c-orientation').checked,
        bleedAndKeepOutChecked: $('c-hardware').checked,
        colorWhiteVarnishTestPassed: $('c-color').checked,
        ripScale100Confirmed: $('c-color').checked,
      };
      const b = await api('/jobs/' + current.id + '/release', { method: 'POST', body: JSON.stringify(body) });
      appendBundleLink($('preview-downloads'), b.bundleId, '下載已核對的原尺寸印刷包');
      $('release-state').textContent = `已放行 · ${operator}`;
      message('印刷下載包已完成；請由印刷人員匯入 RIP。');
    });

  $('preview-generate').onclick = () =>
    action(async () => {
      if (!$('preview-accept').checked) throw new Error('請先勾選 3D 預覽說明再生成。');
      const r = await api('/jobs/' + current.id + '/preview', { method: 'POST', body: JSON.stringify(version()) });
      renderTask = r.taskId;
      await poll(current.id, epoch);
      message('已送交本機 Blender 生成套圖。');
    });

  $('preview-cancel').onclick = () =>
    action(async () => {
      await api('/jobs/' + current.id + '/preview/cancel', { method: 'POST', body: JSON.stringify({ taskId: renderTask }) });
      message('已要求取消生成，正在等待 Blender 結束。');
    });

  $('preview-accept').onchange = () => buttons();

  window.addEventListener('beforeunload', e => {
    if (dirty && current) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  window.addEventListener('printfox:imported', () => {
    const refresh = () => {
      if (busy) {
        setTimeout(refresh, 300);
        return;
      }
      action(async () => {
        await loadAssets();
        const d = draft();
        panelRows(d.panels);
        message('PrintFox 圖片已匯入；請先到「素材用途管理」核對為印刷圖稿，再重新載入此頁選用。');
      });
    };
    refresh();
  });

  bindEditorInputs();
  action(async () => {
    await loadAssets();
    panelRows([{}, {}, {}]);
    await loadJobs();
    await sources();
    buttons();
    message('工作台已就緒。先選取原稿，再建立印刷商品。');
  });
})();
