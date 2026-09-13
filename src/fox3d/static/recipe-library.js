'use strict';
const API = '/api/recipe-library';
const workspace = 'sonaqueen-home';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const urlSku = sku => encodeURIComponent(sku);
let items = [], families = {}, fields = {}, selected = null, dirty = false, activeTab = 'specs', busy = false;
const core = ['widthMm','depthMm','heightMm','material','doorCount','rowCount','compartmentCount','handles'];

function message(text, error = false) {
  $('notice').textContent = text;
  $('notice').className = error ? 'error' : '';
  $('notice').hidden = false;
}
function errorText(error) {
  if (Array.isArray(error)) return error.map(e => e.msg || '請檢查輸入格式').join('；');
  return typeof error === 'string' ? error : '操作未完成，請稍後重試';
}
async function request(path = '', options = {}) {
  const headers = {'X-Tenant-Id': workspace, ...options.headers};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  let response;
  try { response = await fetch(API + path, {...options, headers}); }
  catch { throw new Error('無法連線至後台，請確認服務正在執行後重新載入。'); }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(errorText(data.detail));
  }
  return response;
}
async function json(path = '', options = {}) { return (await request(path, options)).json(); }
function allowLeave() { return !dirty || window.confirm('尚有未儲存的修改，確定要離開目前商品嗎？'); }
function markDirty() { dirty = true; const status = $('save-state'); if (status) status.textContent = '有未儲存的修改'; }
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });

function imageUrl(item) {
  const sku = urlSku(item.draft.sku);
  if (item.uploads.length) return `${API}/products/${sku}/images/${item.uploads[0].digest}?workspace=${encodeURIComponent(workspace)}`;
  return item.previewSourceId ? `${API}/sources/${sku}/${encodeURIComponent(item.previewSourceId)}` : '';
}
function imageMarkup(item, className) {
  const src = imageUrl(item);
  return src ? `<img class="${className}" src="${esc(src)}" alt="${esc(item.draft.name)}">` : `<span class="${className} card-placeholder" aria-label="尚無圖片">SQ</span>`;
}
function renderList() {
  const search = $('search').value.trim().toLowerCase(), filter = $('family-filter').value;
  const filtered = items.filter(item => (!filter || item.draft.family === filter) && `${item.draft.sku} ${item.draft.name}`.toLowerCase().includes(search));
  $('total-stat').textContent = items.length;
  $('draft-stat').textContent = items.filter(i => i.status === 'DRAFT').length;
  $('missing-stat').textContent = items.reduce((n,i) => n + i.validation.missingFields.length, 0);
  $('product-list').innerHTML = filtered.map(item => `<button type="button" class="product-card ${selected?.draft.sku === item.draft.sku ? 'active' : ''}" data-sku="${esc(item.draft.sku)}" aria-label="開啟 ${esc(item.draft.name)}" aria-pressed="${selected?.draft.sku === item.draft.sku}">${imageMarkup(item,'card-img')}<span class="card-copy"><span class="card-sku">${esc(item.draft.sku)}</span><span class="card-name">${esc(item.draft.name)}</span><span class="card-meta">${item.status === 'DRAFT' ? '草稿 · ' : ''}待補 ${item.validation.missingFields.length} 項</span></span></button>`).join('') || '<p class="muted loading">找不到符合條件的商品。<br>試試其他名稱或商品編號。</p>';
  $('product-list').querySelectorAll('[data-sku]').forEach(button => button.addEventListener('click', () => {
    if (selected?.draft.sku === button.dataset.sku || !allowLeave()) return;
    selected = items.find(item => item.draft.sku === button.dataset.sku); dirty = false; activeTab = 'specs'; renderList(); renderDetail();
  }));
}
async function load(preferredSku) {
  const data = await json();
  items = data.items; families = data.families; fields = data.fields;
  const previousFilter = $('family-filter').value;
  $('family-filter').innerHTML = '<option value="">所有結構配方</option>' + Object.entries(families).map(([key,value]) => `<option value="${key}">${esc(value.name)}</option>`).join('');
  $('family-filter').value = previousFilter;
  $('new-family').innerHTML = Object.entries(families).map(([key,value]) => `<option value="${key}">${esc(value.name)}</option>`).join('');
  selected = items.find(i => i.draft.sku === (preferredSku || selected?.draft.sku)) || items[0] || null;
  dirty = false; renderList(); renderDetail();
}
function fieldMarkup(key) {
  const definition = fields[key], entry = selected.draft.values[key] || {value:null,evidence:''};
  const id = `field-${key}`, value = entry.value;
  let input;
  if (definition.unit === 'boolean') input = `<select id="${id}" data-field="${key}"><option value="">尚未提供</option><option value="true" ${value === true ? 'selected' : ''}>是</option><option value="false" ${value === false ? 'selected' : ''}>否</option></select>`;
  else if (definition.unit === 'mm' || definition.unit === 'count') input = `<input id="${id}" data-field="${key}" type="number" step="${definition.unit === 'count' ? '1' : 'any'}" min="${key === 'doorCount' ? '0' : definition.unit === 'count' ? '1' : '0.000001'}" value="${esc(value)}" placeholder="尚未提供">`;
  else input = `<input id="${id}" data-field="${key}" type="text" maxlength="4000" value="${esc(value)}" placeholder="尚未提供">`;
  const modified = selected.validation.changedFields.includes(key);
  return `<div class="field"><label for="${id}" class="field-title"><span class="field-label">${esc(definition.label)}</span><span class="field-unit">${definition.unit === 'mm' ? 'mm' : definition.unit === 'count' ? '個' : ''}</span></label>${input}<details><summary class="${modified ? 'changed' : ''}">${modified ? '草稿修改 · ' : ''}${entry.evidence ? '查看／編輯資料依據' : '補充資料依據'}</summary><label class="sr-only" for="evidence-${key}">${esc(definition.label)}的資料依據</label><input id="evidence-${key}" data-evidence="${key}" value="${esc(entry.evidence)}" placeholder="填寫圖面、規格書或量測依據" maxlength="2000"></details></div>`;
}
function validationMarkup(v, expanded = false) {
  const labels = keys => keys.map(k => fields[k]?.label || k).join('、');
  return `<div class="validation-box"><strong>${v.dataComplete ? '基本資料已填妥，下一步為工程與建模驗證。' : `還有 ${v.missingFields.length} 項資料待補齊。`}</strong>${expanded && v.missingFields.length ? `<p>待補：${esc(labels(v.missingFields))}</p>` : ''}${v.unreferencedFields.length ? `<p>待補資料依據：${esc(labels(v.unreferencedFields))}</p>` : ''}${v.issues.length ? `<ul>${v.issues.map(i => `<li>${esc(i)}</li>`).join('')}</ul>` : ''}${expanded ? `<p>${v.sourceIntegrityVerified ? '原始供應商快照完整性：核對通過。草稿修改仍待確認。' : '此商品尚未綁定已驗證的供應商快照。'}<br>${esc(v.nextStep)}</p>` : ''}</div>`;
}
function renderDetail() {
  if (!selected) { $('detail').innerHTML = '<div class="empty"><h2>尚無商品</h2><p>點擊「新增商品」建立第一份草稿。</p></div>'; return; }
  const d = selected.draft, pending = families[d.family].missing;
  const extras = Object.keys(d.values).filter(k => !core.includes(k) && !pending.includes(k));
  $('detail').innerHTML = `<div class="detail-header"><div class="detail-top">${imageMarkup(selected,'hero-image')}<div class="product-identity"><div class="sku-line">${esc(d.sku)} · ${esc(families[d.family].name)}</div><h2>${esc(d.name)}</h2><div class="badges"><span class="badge green">${selected.status === 'DRAFT' ? '草稿 v' + selected.revision : '供應商參考'}</span><span class="badge amber">待補 ${selected.validation.missingFields.length} 項</span><span class="badge neutral" id="badge-3d">3D 模型狀態查詢中…</span></div></div></div></div>
  <div class="tabs" role="tablist" aria-label="商品資訊"><button class="tab" id="specs-tab" role="tab" aria-controls="specs-panel">規格與缺漏</button><button class="tab" id="sources-tab" role="tab" aria-controls="sources-panel">圖片與來源</button><button class="tab" id="threed-tab" role="tab" aria-controls="threed-panel">3D 預覽與下載</button></div>
  <div id="specs-panel" role="tabpanel" aria-labelledby="specs-tab"><form id="edit-form"><div class="panel"><div id="validation-result">${validationMarkup(selected.validation)}</div><div class="section-title"><h3>基本資料</h3><span class="muted">尺寸單位：毫米</span></div><div class="form-grid"><label>商品名稱<input id="edit-name" value="${esc(d.name)}" required maxlength="240"></label><label>商品來源網址<input id="edit-url" type="url" value="${esc(d.pageUrl)}" placeholder="https://…"></label></div><div class="form-grid three extra-section">${['widthMm','depthMm','heightMm'].map(fieldMarkup).join('')}</div><div class="form-grid extra-section">${core.filter(k => !['widthMm','depthMm','heightMm'].includes(k)).map(fieldMarkup).join('')}</div><div class="gap-section"><div class="section-title"><h3>工程與機構資料</h3><span>依商品圖面逐項補齊</span></div><div class="form-grid">${pending.map(fieldMarkup).join('')}</div></div>${extras.length ? `<div class="extra-section"><div class="section-title"><h3>供應商補充規格</h3></div><div class="form-grid">${extras.map(fieldMarkup).join('')}</div></div>` : ''}<label class="notes-label">備註<textarea id="edit-notes" rows="4" maxlength="10000">${esc(d.notes)}</textarea></label></div><div class="form-actions"><span id="save-state" class="save-state">${selected.updatedAt ? '上次儲存 ' + esc(new Date(selected.updatedAt).toLocaleString('zh-TW')) : '原始供應商參考資料'}</span><button id="validate-button" type="button" class="secondary">驗證資料</button><button id="export-one" type="button" class="secondary">匯出此商品</button><button id="save-button" type="submit" class="primary">儲存草稿</button></div></form></div>
  <div id="sources-panel" class="panel" role="tabpanel" aria-labelledby="sources-tab" hidden><div class="upload-row"><div><h3>商品圖片與原始來源</h3><p class="muted">上傳圖片作為參考，保留供應商來源供核對。</p></div><button id="upload-button" class="secondary">上傳圖片</button><input id="upload-file" type="file" accept="image/png,image/jpeg" hidden></div><div class="source-grid">${sourceCards()}</div></div>
  <div id="threed-panel" class="panel" role="tabpanel" aria-labelledby="threed-tab" hidden><div class="threed-header"><div><h3>3D 參數化模型與光影預覽</h3><p class="muted">讀取商品尺寸、格位與門片配置，依交錯書櫃／門櫃結構透過 Blender Cycles 生成真實 3D 並提供工程檔下載。</p></div><div class="threed-header-actions"><button id="generate-3d-btn" type="button" class="primary">⚡ 生成 3D 預覽</button></div></div><div id="assumptions-card" class="assumptions-box"></div><div id="threed-stage" class="threed-stage"></div><div id="bom-container" class="bom-section"></div></div>`;
  $('edit-form').addEventListener('input', markDirty);
  $('edit-form').addEventListener('change', markDirty);
  $('edit-form').addEventListener('submit', save);
  $('specs-tab').addEventListener('click', () => tab('specs'));
  $('sources-tab').addEventListener('click', () => tab('sources'));
  $('threed-tab').addEventListener('click', () => tab('threed'));
  $('validate-button').addEventListener('click', validate);
  $('export-one').addEventListener('click', () => download(d.sku));
  $('upload-button').addEventListener('click', () => $('upload-file').click());
  $('upload-file').addEventListener('change', uploadImage);
  refreshBadge3D();
  tab(activeTab);
}
function tab(name) {
  activeTab = name;
  for (const key of ['specs','sources','threed']) {
    const p = $(key + '-panel'), t = $(key + '-tab');
    if (p) p.hidden = key !== name;
    if (t) {
      t.classList.toggle('active', key === name);
      t.setAttribute('aria-selected', String(key === name));
    }
  }
  if (name === 'threed') load3d();
}
async function refreshBadge3D() {
  if (!selected) return;
  try {
    const status = await json(`/products/${urlSku(selected.draft.sku)}/3d/status`);
    const badge = $('badge-3d');
    if (badge) {
      badge.className = 'badge ' + (status.generated ? 'green' : 'neutral');
      badge.textContent = status.generated ? '已生成 3D 模型' : '尚未建立 3D 模型';
    }
  } catch {}
}
async function load3d() {
  if (!selected) return;
  const sku = selected.draft.sku;
  $('threed-stage').innerHTML = '<p class="muted loading">正在讀取 3D 狀態與模型資產…</p>';
  try {
    const status = await json(`/products/${urlSku(sku)}/3d/status`);
    render3dStage(status);
  } catch (err) {
    $('threed-stage').innerHTML = `<p class="form-error">讀取 3D 狀態失敗：${esc(err.message)}</p>`;
  }
}
function render3dStage(status) {
  if (!selected) return;
  const sku = selected.draft.sku;
  const badge = $('badge-3d');
  if (badge) {
    badge.className = 'badge ' + (status.generated ? 'green' : 'neutral');
    badge.textContent = status.generated ? '已生成 3D 模型' : '尚未建立 3D 模型';
  }

  const assumptions = status.assumptions || [];
  const assumptionsHtml = `
    <div class="assumptions-header">
      <strong>⚠️ 預覽用工程假設與結構推導</strong>
      <span class="assumptions-subtitle">板厚、門縫、無背板等未確認資料，明確標示為預覽用假設。</span>
    </div>
    <div class="assumptions-grid">
      ${assumptions.map(a => `
        <div class="assumption-item">
          <div class="assumption-tag">${esc(a.source)}</div>
          <div class="assumption-field"><strong>${esc(a.label)}</strong>：${esc(a.value)} ${esc(a.unit)}</div>
          <div class="assumption-note">${esc(a.note)}</div>
        </div>
      `).join('') || '<p class="muted">無額外假設，所有幾何均已由規格推導。</p>'}
    </div>
  `;
  $('assumptions-card').innerHTML = assumptionsHtml;

  if (status.generated && status.assets.png) {
    const timestamp = Date.now();
    const renderUrl = `${API}/products/${urlSku(sku)}/3d/render?workspace=${encodeURIComponent(workspace)}&t=${timestamp}`;
    const blendUrl = `${API}/products/${urlSku(sku)}/3d/download/blend?workspace=${encodeURIComponent(workspace)}`;
    const glbUrl = `${API}/products/${urlSku(sku)}/3d/download/glb?workspace=${encodeURIComponent(workspace)}`;
    const pngUrl = `${API}/products/${urlSku(sku)}/3d/download/png?workspace=${encodeURIComponent(workspace)}`;

    $('threed-stage').innerHTML = `
      <div class="preview-layout">
        <div class="preview-viewport">
          <a href="${renderUrl}" target="_blank" rel="noopener" title="點擊在新視窗開啟高畫質圖">
            <img class="preview-img" src="${renderUrl}" alt="${esc(selected.draft.name)} 3D 渲染圖" loading="eager">
          </a>
        </div>
        <div class="preview-meta-col">
          <div class="download-card">
            <h4>下載產出檔案</h4>
            <p class="muted">可下載 Blender 原生工程檔、Web 3D glTF/GLB 模型以及 Cycles OptiX 高解析渲染圖。</p>
            <div class="download-links">
              <a class="download-btn ${status.assets.blend ? 'active' : 'disabled'}" href="${blendUrl}" download>
                <span class="btn-icon">📦</span>
                <span class="btn-text"><strong>下載 .blend 專案檔</strong><small>Blender 原生場景模型</small></span>
              </a>
              <a class="download-btn ${status.assets.glb ? 'active' : 'disabled'}" href="${glbUrl}" download>
                <span class="btn-icon">🌐</span>
                <span class="btn-text"><strong>下載 .glb 3D 模型</strong><small>Web / AR 3D 輕量格式</small></span>
              </a>
              <a class="download-btn ${status.assets.png ? 'active' : 'disabled'}" href="${pngUrl}" download>
                <span class="btn-icon">🖼️</span>
                <span class="btn-text"><strong>下載高解析渲染圖 (PNG)</strong><small>Cycles 物理光影成圖</small></span>
              </a>
            </div>
            <div class="render-spec-info">
              <div><span>渲染引擎：</span><strong>Cycles (${status.renderInfo?.device || 'OptiX'})</strong></div>
              <div><span>光影取樣：</span><strong>${status.renderInfo?.samples || 32} spp</strong></div>
              <div><span>渲染耗時：</span><strong>${status.renderInfo?.renderTimeSec || 0} 秒</strong></div>
              <div><span>更新時間：</span><strong>${status.updatedAt ? new Date(status.updatedAt).toLocaleString('zh-TW') : '剛剛'}</strong></div>
            </div>
          </div>
        </div>
      </div>
    `;
  } else {
    $('threed-stage').innerHTML = `
      <div class="empty-threed">
        <div class="empty-icon">📐</div>
        <h3>尚未生成此商品的 3D 模型與光影渲染</h3>
        <p class="muted">點擊右上方「⚡ 生成 3D 預覽」，系統將讀取此商品的尺寸與格位配置，套用預覽假設並在背景啟動 Blender 進行幾何構建、Cycles 光影渲染與 .blend / .glb 匯出。</p>
      </div>
    `;
  }

  const bom = status.bom;
  if (bom && bom.lines && bom.lines.length) {
    $('bom-container').innerHTML = `
      <div class="section-title">
        <h3>結構板材與元件清單 (BOM)</h3>
        <span class="muted">共 ${bom.totalParts} 件結構板件</span>
      </div>
      <div class="bom-table-wrap">
        <table class="bom-table">
          <thead>
            <tr><th>元件編號</th><th>元件名稱</th><th>結構角色</th><th>長度 (mm)</th><th>寬度 (mm)</th><th>厚度 (mm)</th><th>數量</th><th>材質</th></tr>
          </thead>
          <tbody>
            ${bom.lines.map(line => `
              <tr>
                <td><code>${esc(line.partId)}</code></td>
                <td><strong>${esc(line.partName)}</strong></td>
                <td><span class="role-tag">${esc(line.role)}</span></td>
                <td>${esc(line.lengthMm)}</td>
                <td>${esc(line.widthMm)}</td>
                <td>${esc(line.thicknessMm)}</td>
                <td>${esc(line.quantity)}</td>
                <td>${esc(line.material)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  } else {
    $('bom-container').innerHTML = '';
  }

  const genBtn = $('generate-3d-btn');
  if (genBtn) {
    genBtn.onclick = generate3d;
    genBtn.textContent = status.generated ? '⚡ 重新生成 3D 預覽' : '⚡ 生成 3D 預覽';
  }
}
async function generate3d() {
  if (dirty) { message('請先儲存規格修改，再生成 3D 預覽。', true); return; }
  const genBtn = $('generate-3d-btn');
  if (genBtn) {
    genBtn.disabled = true;
    genBtn.textContent = '正在呼叫 Blender 渲染中…';
  }
  $('threed-stage').innerHTML = `
    <div class="rendering-state">
      <div class="spinner"></div>
      <h3>正在建立 3D 幾何結構與 Cycles 光影渲染…</h3>
      <p class="muted">依據尺寸與格位建立板件，匯出 .blend 與 .glb，並進行 GPU 光影烘焙，請稍候。</p>
    </div>
  `;
  try {
    const sku = selected.draft.sku;
    const res = await json(`/products/${urlSku(sku)}/3d/generate`, {method: 'POST'});
    message('3D 預覽與模型生成完成！已可下載 .blend、.glb 與渲染圖片。');
    render3dStage(res);
  } catch (err) {
    message(`3D 生成失敗：${err.message}`, true);
    load3d();
  } finally {
    if (genBtn) {
      genBtn.disabled = false;
      genBtn.textContent = '⚡ 重新生成 3D 預覽';
    }
  }
}
function sourceCards() {
  const sku = urlSku(selected.draft.sku);
  const cards = selected.sources.map(s => `<article class="source-card">${s.mediaType === 'image/jpeg' ? `<a href="${API}/sources/${sku}/${encodeURIComponent(s.sourceId)}" target="_blank" rel="noopener"><img src="${API}/sources/${sku}/${encodeURIComponent(s.sourceId)}" alt="${esc(selected.draft.name)} · ${esc(s.sourceId)}" loading="lazy"></a>` : ''}<div class="source-info"><strong>${s.mediaType === 'image/jpeg' ? '供應商圖片 · ' + esc(s.sourceId) : '商品頁快照'}</strong><a href="${esc(s.url)}" target="_blank" rel="noopener">查看官網來源 ↗</a><div>擷取：${esc(new Date(s.capturedAt).toLocaleDateString('zh-TW'))}</div><code>SHA-256 ${esc(s.sha256)}</code></div></article>`);
  for (const u of selected.uploads) cards.unshift(`<article class="source-card"><a href="${API}/products/${sku}/images/${u.digest}?workspace=${encodeURIComponent(workspace)}" target="_blank" rel="noopener"><img src="${API}/products/${sku}/images/${u.digest}?workspace=${encodeURIComponent(workspace)}" alt="${esc(u.name)}" loading="lazy"></a><div class="source-info"><strong>${esc(u.name)}</strong><span>自行上傳 · 參考圖片</span><code>SHA-256 ${esc(u.digest)}</code></div></article>`);
  return cards.join('') || '<p class="muted">尚無圖片。可上傳商品照片或尺寸圖，或在規格頁補上商品來源網址。</p>';
}
function collect() {
  const draft = structuredClone(selected.draft);
  draft.name = $('edit-name').value.trim(); draft.pageUrl = $('edit-url').value.trim(); draft.notes = $('edit-notes').value;
  $('edit-form').querySelectorAll('[data-field]').forEach(input => {
    const key = input.dataset.field, unit = fields[key].unit;
    let value = input.value.trim();
    value = value === '' ? null : unit === 'boolean' ? value === 'true' : ['mm','count'].includes(unit) ? Number(value) : value;
    let evidence = $('evidence-' + key).value.trim();
    const original = selected.draft.values[key];
    if (original && value !== original.value && evidence === original.evidence) evidence = '';
    if (!original && value === null && !evidence) delete draft.values[key];
    else draft.values[key] = {value, evidence};
  });
  return draft;
}
async function save(event) {
  event.preventDefault(); if (busy) return;
  busy = true; $('save-button').disabled = true;
  const sku = selected.draft.sku;
  try {
    await json(`/products/${urlSku(sku)}`, {method:'PUT', body:JSON.stringify({expectedRevision:selected.revision,draft:collect()})});
    await load(sku); message('草稿已儲存。修改內容會保留，原始供應商資料仍可在來源頁查看。');
  } catch (error) { message(error.message, true); }
  finally { busy = false; if ($('save-button')) $('save-button').disabled = false; }
}
async function validate() {
  if (dirty) { message('請先儲存修改，再驗證最新草稿。', true); return; }
  try {
    const result = await json(`/products/${urlSku(selected.draft.sku)}/validate`, {method:'POST'});
    $('validation-result').innerHTML = validationMarkup(result, true);
    message(`資料檢查完成：待補 ${result.missingFields.length} 項，待補依據 ${result.unreferencedFields.length} 項，結構問題 ${result.issues.length} 項。`);
    $('validation-result').scrollIntoView({behavior:'smooth',block:'center'});
  } catch (error) { message(error.message, true); }
}
async function download(sku) {
  if (dirty) { message('請先儲存修改，匯出內容才會包含最新草稿。', true); return; }
  try {
    const response = await request('/export' + (sku ? '?sku=' + encodeURIComponent(sku) : ''));
    const blob = await response.blob(), url = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = url; anchor.download = sku ? sku + '-recipe.json' : 'sonaqueen-recipes.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000); message('Recipe JSON 已下載。');
  } catch (error) { message(error.message, true); }
}
async function uploadImage(event) {
  const file = event.target.files[0]; if (!file) return;
  if (dirty) { message('請先儲存規格修改，再上傳圖片。', true); event.target.value = ''; return; }
  if (file.size > 8 * 1024 * 1024) { message('圖片大小不可超過 8 MB。', true); return; }
  const sku = selected.draft.sku, form = new FormData(); form.append('file', file);
  try { await json(`/products/${urlSku(sku)}/images`, {method:'POST',body:form}); await load(sku); message('參考圖片已上傳。'); }
  catch (error) { message(error.message, true); }
}
$('search').addEventListener('input', renderList);
$('family-filter').addEventListener('change', renderList);
$('reload').addEventListener('click', () => { if (allowLeave()) load().then(() => message('商品資料已重新載入。')).catch(error => message(error.message,true)); });
$('export-all').addEventListener('click', () => download());
$('new-button').addEventListener('click', () => { if (!allowLeave()) return; $('new-form').reset(); $('new-error').textContent = ''; $('new-dialog').showModal(); });
for (const id of ['close-new','cancel-new']) $(id).addEventListener('click', () => $('new-dialog').close());
$('new-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = new FormData(event.currentTarget), submit = event.currentTarget.querySelector('[type=submit]');
  const draft = {sku:form.get('sku').trim(),name:form.get('name').trim(),family:form.get('family'),pageUrl:form.get('pageUrl').trim(),values:{},notes:''};
  for (const key of ['widthMm','depthMm','heightMm']) if (form.get(key)) draft.values[key] = {value:Number(form.get(key)),evidence:form.get('evidence').trim()};
  submit.disabled = true;
  try { await json('/products',{method:'POST',body:JSON.stringify({expectedRevision:0,draft})}); dirty = false; activeTab='specs'; $('new-dialog').close(); $('search').value=''; $('family-filter').value=''; await load(draft.sku); message('商品草稿已建立，現在可以補齊規格與參考圖片。'); }
  catch(error) { $('new-error').textContent = error.message; }
  finally { submit.disabled = false; }
});
$('import-button').addEventListener('click', () => { if (allowLeave()) $('import-file').click(); });
$('import-file').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 8 * 1024 * 1024) throw new Error('匯入檔不可超過 8 MB。');
    const payload = JSON.parse(await file.text());
    const result = await json('/import',{method:'POST',body:JSON.stringify(payload)});
    dirty = false; $('search').value=''; $('family-filter').value=''; await load(result.items[0]?.draft.sku); message(`已匯入 ${result.items.length} 款草稿。圖片檔需另外上傳；現有草稿不會被覆寫。`);
  } catch(error) { message(error instanceof SyntaxError ? '檔案不是有效的 JSON，請選擇由本後台匯出的檔案。' : error.message, true); }
  finally { event.target.value=''; }
});
load().catch(error => { $('product-list').innerHTML = '<p class="muted loading">讀取失敗，請按「重新載入」。</p>'; message(error.message,true); });
