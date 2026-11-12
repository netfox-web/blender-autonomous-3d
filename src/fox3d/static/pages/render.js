'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );

  const state = { selectedJobId: null, selectedTwinId: null };
  const DEFAULT_TENANT = 'sonaqueen-home';
  const BLOCKED_MSG = '已封鎖：沒有真實 Blender／OptiX，未產生成品';
  const TENANT_HINT = '按重新載入後才會切換租戶';

  // Tenant used for every API call. Set once at page load and again only when a
  // reload button is pressed; editing the input alone never redirects writes.
  let activeTenant = DEFAULT_TENANT;
  let previewBlobUrl = null;

  function storedTenant() {
    try {
      return (localStorage.getItem('fox3d.tenant') || '').trim();
    } catch (e) {
      return '';
    }
  }

  function tenantInputValue() {
    const el = $('rd-tenant');
    return (el && el.value.trim()) || '';
  }

  function updateTenantHint() {
    const hint = $('rd-tenant-hint');
    if (!hint) return;
    const typed = tenantInputValue();
    if (typed && typed !== activeTenant) {
      hint.hidden = false;
      hint.textContent = `目前租戶：${activeTenant}。${TENANT_HINT}`;
    } else {
      hint.hidden = true;
      hint.textContent = '';
    }
  }

  function initTenant() {
    const el = $('rd-tenant');
    const stored = storedTenant();
    if (el && stored) el.value = stored;
    activeTenant = tenantInputValue() || stored || DEFAULT_TENANT;
    if (el) el.addEventListener('input', updateTenantHint);
    updateTenantHint();
  }

  // Called by the reload buttons: adopt the typed tenant. Returns true when it changed.
  function applyTenantFromInput() {
    const next = tenantInputValue() || DEFAULT_TENANT;
    const changed = next !== activeTenant;
    activeTenant = next;
    try {
      localStorage.setItem('fox3d.tenant', next);
    } catch (e) {
      /* storage blocked */
    }
    if (changed) {
      state.selectedJobId = null;
      state.selectedTwinId = null;
      resetJobDetail();
      resetTwinDetail();
      showBanner(`已切換租戶：${next}`);
    }
    updateTenantHint();
    return changed;
  }

  function resetJobDetail() {
    $('rd-job-detail-empty').hidden = false;
    $('rd-job-detail').hidden = true;
    $('rd-job-actions').hidden = true;
  }

  function resetTwinDetail() {
    $('rd-twin-detail-empty').hidden = false;
    $('rd-twin-detail').hidden = true;
    $('rd-twin-actions').hidden = true;
    clearPreviewImage();
  }

  function showBanner(msg, kind) {
    // kind: falsy = success, true / 'error' = error, 'blocked' = production gate blocked.
    const el = $('rd-banner');
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.textContent = msg;
    el.classList.toggle('error', kind === true || kind === 'error');
    el.classList.toggle('blocked', kind === 'blocked');
  }

  // options.tenant pins the tenant (captured when a confirm dialog opened);
  // otherwise activeTenant is used. The X-Tenant-Id header is the only tenant source.
  async function api(url, options = {}) {
    const { tenant, ...rest } = options;
    const headers = { ...(rest.headers || {}), 'X-Tenant-Id': tenant || activeTenant };
    if (!(rest.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(url, { ...rest, headers });
    let data = {};
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      data = await res.json().catch(() => ({}));
    } else if (!res.ok) {
      data = { detail: await res.text().catch(() => '請求失敗') };
    }
    if (!res.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return data;
  }

  function pretty(obj) {
    return JSON.stringify(obj, null, 2);
  }

  // Production gate (no real Blender / OptiX) answers 200 with
  // {status: "blocked", error: "BLOCKED_..."} and no twin/job; a job can also end blocked.
  function isBlockedResult(out) {
    if (!out || typeof out !== 'object') return false;
    const job = out.job && typeof out.job === 'object' ? out.job : null;
    return (
      out.status === 'blocked' ||
      String(out.error || '').startsWith('BLOCKED_') ||
      Boolean(job && (job.status === 'blocked' || String(job.error || '').startsWith('BLOCKED_')))
    );
  }

  function blockedMessage(label, out) {
    const job = (out && out.job) || {};
    const code = (out && out.error) || job.error || '';
    return `${label}：${BLOCKED_MSG}${code ? `（${code}）` : ''}`;
  }

  function mockHint(out) {
    const job = (out && out.job) || {};
    const src = (out && out.discoverySource) || job.discoverySource || '';
    return src === 'MOCK' ? '（MOCK 模擬輸出，非正式渲染）' : '';
  }

  function statusBadge(job) {
    const st = String(job.status || '');
    const src = String(job.discoverySource || '');
    const err = String(job.error || '');
    let extra = '';
    if (st === 'blocked' || err.startsWith('BLOCKED_')) {
      extra += ' <span class="st-blocked" title="' + esc(err || '沒有真實 Blender／OptiX') + '">BLOCKED</span>';
    } else if (st === 'failed' || st === 'cancelled') {
      extra += ' <span class="st-partial">' + esc(st) + '</span>';
    }
    if (src === 'MOCK') {
      extra += ' <span class="st-mock" title="模擬環境，非正式渲染輸出">MOCK</span>';
    }
    return esc(st) + extra;
  }

  // One pending-callback slot; Yes/No listeners are attached once in
  // wireConfirmDialogs(), so re-opening a dialog never stacks handlers.
  const confirms = {
    job: { dialog: 'rd-confirm-job', text: 'rd-confirm-job-text', yes: 'rd-confirm-job-yes', no: 'rd-confirm-job-no' },
    twin: { dialog: 'rd-confirm-twin', text: 'rd-confirm-twin-text', yes: 'rd-confirm-twin-yes', no: 'rd-confirm-twin-no' },
  };
  let pendingConfirm = null; // { key, onYes, tenant, returnFocus }

  function closeConfirm() {
    const p = pendingConfirm;
    pendingConfirm = null;
    if (!p) return null;
    $(confirms[p.key].dialog).hidden = true;
    if (p.returnFocus && typeof p.returnFocus.focus === 'function') {
      try {
        p.returnFocus.focus();
      } catch (e) {
        /* element gone */
      }
    }
    return p;
  }

  // onYes(tenant) receives the tenant captured at the moment the dialog opened.
  function openConfirm(key, message, onYes) {
    if (pendingConfirm) closeConfirm();
    const cfg = confirms[key];
    $(cfg.text).textContent = message;
    pendingConfirm = { key, onYes, tenant: activeTenant, returnFocus: document.activeElement };
    $(cfg.dialog).hidden = false;
    $(cfg.no).focus();
  }

  function wireConfirmDialogs() {
    Object.keys(confirms).forEach((key) => {
      const cfg = confirms[key];
      $(cfg.yes).addEventListener('click', async () => {
        if (!pendingConfirm || pendingConfirm.key !== key) return;
        const p = closeConfirm();
        if (p && p.onYes) await p.onYes(p.tenant);
      });
      $(cfg.no).addEventListener('click', () => {
        if (pendingConfirm && pendingConfirm.key === key) closeConfirm();
      });
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && pendingConfirm) {
        ev.preventDefault();
        closeConfirm();
      }
    });
  }

  function clearPreviewImage() {
    const img = $('rd-twin-preview-img');
    if (img) img.removeAttribute('src');
    $('rd-twin-preview-wrap').hidden = true;
    if (previewBlobUrl) {
      URL.revokeObjectURL(previewBlobUrl);
      previewBlobUrl = null;
    }
  }

  // <img> cannot carry X-Tenant-Id, so fetch the asset with the required
  // header and show it as a blob URL.
  async function loadPreviewImage(twinId, assetId) {
    const tenant = activeTenant;
    try {
      const res = await fetch(`/api/assets/${encodeURIComponent(assetId)}`, {
        headers: { 'X-Tenant-Id': tenant },
      });
      if (!res.ok) throw new Error(`預覽圖載入失敗（HTTP ${res.status}）`);
      const blob = await res.blob();
      if (state.selectedTwinId !== twinId || activeTenant !== tenant) return; // stale
      const url = URL.createObjectURL(blob);
      if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
      previewBlobUrl = url;
      $('rd-twin-preview-img').src = url;
      $('rd-twin-preview-wrap').hidden = false;
    } catch (e) {
      if (state.selectedTwinId === twinId) showBanner(e.message, true);
    }
  }

  async function loadJobs() {
    $('rd-jobs-loading').hidden = false;
    $('rd-jobs-empty').hidden = true;
    $('rd-jobs-error').hidden = true;
    $('rd-jobs-table').hidden = true;
    try {
      const data = await api('/api/3d/jobs');
      const items = data.items || [];
      $('rd-jobs-loading').hidden = true;
      if (!items.length) {
        $('rd-jobs-empty').hidden = false;
        return;
      }
      const tbody = $('rd-jobs-body');
      tbody.innerHTML = items
        .map((j) => {
          const created = j.createdAt ? String(j.createdAt).slice(0, 19) : '';
          const sel = j.jobId === state.selectedJobId ? ' class="sel"' : '';
          return `<tr data-job="${esc(j.jobId)}"${sel}><td><code>${esc(String(j.jobId || '').slice(0, 8))}</code></td><td>${esc(j.jobType)}</td><td>${statusBadge(j)}</td><td>${esc(created)}</td></tr>`;
        })
        .join('');
      $('rd-jobs-table').hidden = false;
      tbody.querySelectorAll('[data-job]').forEach((row) => {
        row.addEventListener('click', () => selectJob(row.dataset.job));
      });
      if (state.selectedJobId) selectJob(state.selectedJobId, true);
    } catch (e) {
      $('rd-jobs-loading').hidden = true;
      $('rd-jobs-error').hidden = false;
      $('rd-jobs-error').textContent = e.message;
    }
  }

  async function selectJob(jobId, quiet) {
    state.selectedJobId = jobId;
    document.querySelectorAll('#rd-jobs-body tr').forEach((r) => {
      r.classList.toggle('sel', r.dataset.job === jobId);
    });
    $('rd-job-detail-empty').hidden = true;
    $('rd-job-detail').hidden = false;
    $('rd-job-actions').hidden = false;
    $('rd-job-detail').textContent = '載入中…';
    try {
      const job = await api(`/api/3d/jobs/${encodeURIComponent(jobId)}`);
      $('rd-job-detail').textContent = pretty(job);
      if (!quiet) showBanner('已載入工作明細。');
    } catch (e) {
      $('rd-job-detail').textContent = e.message;
      if (!quiet) showBanner(e.message, true);
    }
  }

  async function loadTwins() {
    $('rd-twins-loading').hidden = false;
    $('rd-twins-empty').hidden = true;
    $('rd-twins-error').hidden = true;
    $('rd-twins-table').hidden = true;
    try {
      const data = await api('/api/pages/render/twins');
      const items = data.items || [];
      $('rd-twins-loading').hidden = true;
      if (!items.length) {
        $('rd-twins-empty').hidden = false;
        return;
      }
      const tbody = $('rd-twins-body');
      tbody.innerHTML = items
        .map((t) => {
          const sel = t.twinId === state.selectedTwinId ? ' class="sel"' : '';
          return `<tr data-twin="${esc(t.twinId)}"${sel}><td><code>${esc(String(t.twinId || '').slice(0, 8))}</code></td><td>${esc(t.sku)}</td><td>${esc(t.version)}</td></tr>`;
        })
        .join('');
      $('rd-twins-table').hidden = false;
      tbody.querySelectorAll('[data-twin]').forEach((row) => {
        row.addEventListener('click', () => selectTwin(row.dataset.twin));
      });
      if (state.selectedTwinId) selectTwin(state.selectedTwinId, true);
    } catch (e) {
      $('rd-twins-loading').hidden = true;
      $('rd-twins-error').hidden = false;
      $('rd-twins-error').textContent = e.message;
    }
  }

  async function selectTwin(twinId, quiet) {
    state.selectedTwinId = twinId;
    document.querySelectorAll('#rd-twins-body tr').forEach((r) => {
      r.classList.toggle('sel', r.dataset.twin === twinId);
    });
    $('rd-twin-detail-empty').hidden = true;
    $('rd-twin-detail').hidden = false;
    $('rd-twin-actions').hidden = false;
    $('rd-twin-detail').textContent = '載入中…';
    clearPreviewImage();
    try {
      const twin = await api(`/api/digital-twins/${encodeURIComponent(twinId)}`);
      $('rd-twin-detail').textContent = pretty(twin);
      if (twin.previewAssetId) await loadPreviewImage(twinId, twin.previewAssetId);
      if (!quiet) showBanner('已載入分身明細。');
    } catch (e) {
      $('rd-twin-detail').textContent = e.message;
      if (!quiet) showBanner(e.message, true);
    }
  }

  // Reload buttons are the only place the tenant switches; a switch reloads both lists.
  function reloadFromButton(which) {
    if (applyTenantFromInput()) {
      loadJobs();
      loadTwins();
    } else if (which === 'jobs') {
      loadJobs();
    } else {
      loadTwins();
    }
  }

  function wireJobForms() {
    $('rd-refresh-jobs').addEventListener('click', () => reloadFromButton('jobs'));
    $('rd-form-job').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const jobType = $('rd-job-type').value;
      const scene = $('rd-job-scene').value;
      openConfirm('job', `確定要送出算圖工作？類型：${jobType}，場景：${scene}（租戶：${activeTenant}）`, async (tenant) => {
        try {
          const out = await api('/api/3d/jobs', {
            method: 'POST',
            tenant,
            body: JSON.stringify({ jobType, scene }),
          });
          $('rd-job-detail').hidden = false;
          $('rd-job-detail-empty').hidden = true;
          $('rd-job-actions').hidden = false;
          $('rd-job-detail').textContent = pretty(out);
          if (isBlockedResult(out)) {
            showBanner(blockedMessage('送出工作', out), 'blocked');
          } else {
            showBanner(`工作已送出，編號 ${out.jobId}，狀態：${out.status || 'queued'}${mockHint(out)}`);
          }
          if (out.jobId) state.selectedJobId = out.jobId;
          await loadJobs();
        } catch (e) {
          showBanner(e.message, true);
        }
      });
    });

    $('rd-job-cancel').addEventListener('click', () => {
      const jid = state.selectedJobId;
      if (!jid) return;
      openConfirm('job', `確定要取消工作 ${jid.slice(0, 8)}…？`, async (tenant) => {
        try {
          const out = await api(`/api/3d/jobs/${encodeURIComponent(jid)}/cancel`, { method: 'POST', tenant, body: '{}' });
          showBanner(`取消結果：${out.status || 'unknown'}`);
          $('rd-job-detail').textContent = pretty(out);
          await loadJobs();
        } catch (e) {
          showBanner(e.message, true);
        }
      });
    });

    const runQuick = (path, label) => {
      const scene = $('rd-quick-scene').value;
      openConfirm('job', `確定要執行「${label}」？場景：${scene}（會立即算圖）`, async (tenant) => {
        $('rd-quick-out').hidden = false;
        $('rd-quick-out').textContent = '執行中…';
        try {
          const out = await api(path, {
            method: 'POST',
            tenant,
            body: JSON.stringify({ scene }),
          });
          $('rd-quick-out').textContent = pretty(out);
          if (isBlockedResult(out)) {
            showBanner(blockedMessage(label, out), 'blocked');
          } else {
            showBanner(`${label}完成，狀態：${out.status || ''}${mockHint(out)}`);
          }
          if (out.jobId) state.selectedJobId = out.jobId;
          await loadJobs();
          if (out.jobId) selectJob(out.jobId, true);
        } catch (e) {
          $('rd-quick-out').textContent = e.message;
          showBanner(e.message, true);
        }
      });
    };
    $('rd-quick-preview').addEventListener('click', () => runQuick('/api/render/preview', '預覽算圖'));
    $('rd-quick-final').addEventListener('click', () => runQuick('/api/render/final', '正式算圖'));
  }

  function wireTwinForms() {
    $('rd-refresh-twins').addEventListener('click', () => reloadFromButton('twins'));

    $('rd-form-twin').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const sku = $('rd-twin-sku').value.trim();
      const width = Number($('rd-twin-w').value);
      const height = Number($('rd-twin-h').value);
      const depth = Number($('rd-twin-d').value);
      openConfirm('twin', `確定要建立數位分身？SKU：${sku}（租戶：${activeTenant}）`, async (tenant) => {
        $('rd-twin-out').hidden = false;
        $('rd-twin-out').textContent = '建立中…';
        try {
          const out = await api('/api/digital-twins', {
            method: 'POST',
            tenant,
            body: JSON.stringify({ sku, dimensions: { width, height, depth } }),
          });
          $('rd-twin-out').textContent = pretty(out);
          showBanner(`分身已建立，編號 ${out.twinId}`);
          state.selectedTwinId = out.twinId;
          await loadTwins();
          selectTwin(out.twinId, true);
        } catch (e) {
          $('rd-twin-out').textContent = e.message;
          showBanner(e.message, true);
        }
      });
    });

    $('rd-form-upload').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const sku = $('rd-upload-sku').value.trim();
      const file = $('rd-upload-file').files && $('rd-upload-file').files[0];
      if (!file) return;
      openConfirm('twin', `確定要上傳「${file.name}」並建立 SKU ${sku} 的分身？（租戶：${activeTenant}）`, async (tenant) => {
        $('rd-twin-out').hidden = false;
        $('rd-twin-out').textContent = '上傳中…';
        try {
          const fd = new FormData();
          fd.append('sku', sku);
          fd.append('file', file);
          const out = await api('/api/digital-twins/upload', { method: 'POST', tenant, body: fd });
          $('rd-twin-out').textContent = pretty(out);
          const twin = out.twin || {};
          if (isBlockedResult(out)) {
            showBanner(blockedMessage('上傳', out), 'blocked');
          } else {
            showBanner(`上傳完成，分身 ${twin.twinId || ''}，工作狀態：${(out.job || {}).status || ''}${mockHint(out)}`);
          }
          if (twin.twinId) {
            state.selectedTwinId = twin.twinId;
            await loadTwins();
            selectTwin(twin.twinId, true);
          }
        } catch (e) {
          $('rd-twin-out').textContent = e.message;
          showBanner(e.message, true);
        }
      });
    });

    $('rd-twin-preview').addEventListener('click', () => {
      const tid = state.selectedTwinId;
      if (!tid) return;
      openConfirm('twin', '確定要為此分身產生預覽算圖？', async (tenant) => {
        $('rd-twin-out').hidden = false;
        $('rd-twin-out').textContent = '算圖中…';
        try {
          const out = await api(`/api/digital-twins/${encodeURIComponent(tid)}/preview`, {
            method: 'POST',
            tenant,
            body: '{}',
          });
          $('rd-twin-out').textContent = pretty(out);
          if (isBlockedResult(out)) {
            showBanner(blockedMessage('預覽', out), 'blocked');
            return;
          }
          showBanner(`預覽完成，狀態：${(out.job || {}).status || ''}${mockHint(out)}`);
          await selectTwin(tid, true);
          await loadTwins();
        } catch (e) {
          $('rd-twin-out').textContent = e.message;
          showBanner(e.message, true);
        }
      });
    });

    $('rd-twin-360').addEventListener('click', () => {
      const tid = state.selectedTwinId;
      if (!tid) return;
      openConfirm('twin', '確定要產生 360 環繞？（36 格，可能較久）', async (tenant) => {
        $('rd-twin-out').hidden = false;
        $('rd-twin-out').textContent = '算圖中…';
        try {
          const out = await api(`/api/digital-twins/${encodeURIComponent(tid)}/360`, {
            method: 'POST',
            tenant,
            body: '{}',
          });
          $('rd-twin-out').textContent = pretty(out);
          if (isBlockedResult(out)) {
            showBanner(blockedMessage('360 環繞', out), 'blocked');
            return;
          }
          showBanner(`360 完成，狀態：${(out.job || {}).status || ''}${mockHint(out)}`);
        } catch (e) {
          $('rd-twin-out').textContent = e.message;
          showBanner(e.message, true);
        }
      });
    });
  }

  function init() {
    initTenant();
    wireConfirmDialogs();
    wireJobForms();
    wireTwinForms();
    loadJobs();
    loadTwins();
    if (location.hash === '#twins') {
      const el = $('twins');
      if (el) el.scrollIntoView({ behavior: 'smooth' });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
