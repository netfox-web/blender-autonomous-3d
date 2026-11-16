'use strict';
(() => {
  const $ = (id) => document.getElementById(id);

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
  function failureText(e) {
    const msg = (e && e.message) || String(e || '請求失敗');
    if ((e && e.network) || /Failed to fetch|NetworkError|Load failed/i.test(msg)) {
      return msg.indexOf('連線失敗') >= 0 ? msg : `連線失敗，請稍後再試：${msg}`;
    }
    return msg;
  }

  async function api(url, options = {}) {
    const { tenant, ...rest } = options;
    const headers = { ...(rest.headers || {}), 'X-Tenant-Id': tenant || activeTenant };
    if (!(rest.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }
    let res;
    try {
      res = await fetch(url, { ...rest, headers });
    } catch (e) {
      const err = new Error(`連線失敗，請稍後再試：${(e && e.message) || e}`);
      err.network = true;
      throw err;
    }
    let data = {};
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      data = await res.json().catch(() => ({}));
    } else if (!res.ok) {
      data = { detail: await res.text().catch(() => '請求失敗') };
    }
    if (!res.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
      const err = new Error(detail || `HTTP ${res.status}`);
      err.httpStatus = res.status;
      throw err;
    }
    return data;
  }

  function pretty(obj) {
    return JSON.stringify(obj, null, 2);
  }

  // One outcome helper for every POST. HTTP non-2xx, status/label/truthLabel of
  // BLOCKED or FAILED, a BLOCKED_ error, or any safety check with veto=true is a
  // failure. Callers must not show a success / 「完成」 banner for those.
  function tokenBad(v) {
    if (v == null || typeof v === 'boolean' || typeof v === 'object') return false;
    const s = String(v).trim().toUpperCase();
    return s === 'BLOCKED' || s === 'FAILED' || s.startsWith('BLOCKED_') || s.startsWith('FAILED_');
  }

  function checksHaveVeto(out) {
    if (!out || typeof out !== 'object') return false;
    const lists = [];
    if (Array.isArray(out.checks)) lists.push(out.checks);
    if (out.safety && Array.isArray(out.safety.checks)) lists.push(out.safety.checks);
    for (let i = 0; i < lists.length; i += 1) {
      const list = lists[i];
      for (let j = 0; j < list.length; j += 1) {
        if (list[j] && list[j].veto === true) return true;
      }
    }
    return false;
  }

  function isBlockedResult(out) {
    if (!out || typeof out !== 'object') return false;
    if (typeof out.status === 'number') {
      if (out.status < 200 || out.status >= 300) return true;
      return isBlockedResult(out.data);
    }
    const job = out.job && typeof out.job === 'object' ? out.job : null;
    return (
      out.status === 'blocked' ||
      tokenBad(out.status) ||
      tokenBad(out.label) ||
      tokenBad(out.truthLabel) ||
      String(out.error || '').startsWith('BLOCKED_') ||
      out.veto === true ||
      checksHaveVeto(out) ||
      Boolean(
        job &&
          (job.status === 'blocked' ||
            tokenBad(job.status) ||
            tokenBad(job.label) ||
            tokenBad(job.truthLabel) ||
            String(job.error || '').startsWith('BLOCKED_'))
      )
    );
  }

  function blockedMessage(label, out) {
    const job = (out && out.job) || {};
    const code = (out && out.error) || job.error || '';
    if (out && (out.veto === true || checksHaveVeto(out))) {
      return `${label}：已阻擋（安全檢查未通過）`;
    }
    const mark = String((out && (out.label || out.truthLabel || out.status)) || job.label || job.truthLabel || job.status || '');
    const up = mark.trim().toUpperCase();
    if (up === 'FAILED' || up.startsWith('FAILED_')) {
      return `${label}：失敗${code ? `（${code}）` : ''}`;
    }
    return `${label}：${BLOCKED_MSG}${code ? `（${code}）` : ''}`;
  }

  function mockHint(out) {
    const job = (out && out.job) || {};
    const src = (out && out.discoverySource) || job.discoverySource || '';
    return src === 'MOCK' ? '（MOCK 模擬輸出，非正式渲染）' : '';
  }

  // API fields become text nodes. Never assign API data with innerHTML.
  function statusBadge(td, job) {
    const st = String(job.status || '');
    const src = String(job.discoverySource || '');
    const err = String(job.error || '');
    td.appendChild(document.createTextNode(st));
    if (st === 'blocked' || err.startsWith('BLOCKED_')) {
      const badge = document.createElement('span');
      badge.className = 'st-blocked';
      badge.title = err || '沒有真實 Blender／OptiX';
      badge.textContent = 'BLOCKED';
      td.appendChild(document.createTextNode(' '));
      td.appendChild(badge);
    } else if (st === 'failed' || st === 'cancelled') {
      const badge = document.createElement('span');
      badge.className = 'st-partial';
      badge.textContent = st;
      td.appendChild(document.createTextNode(' '));
      td.appendChild(badge);
    }
    if (src === 'MOCK') {
      const badge = document.createElement('span');
      badge.className = 'st-mock';
      badge.title = '模擬環境，非正式渲染輸出';
      badge.textContent = 'MOCK';
      td.appendChild(document.createTextNode(' '));
      td.appendChild(badge);
    }
  }

  function cellText(value) {
    const td = document.createElement('td');
    td.textContent = value == null ? '' : String(value);
    return td;
  }

  // One pending-callback slot; Yes/No listeners are attached once in
  // wireConfirmDialogs(), so re-opening a dialog never stacks handlers.
  // The snapshot (including tenant) is taken when the dialog opens and is what
  // the POST sends. Inputs stay locked until confirm or cancel.
  const confirms = {
    job: { dialog: 'rd-confirm-job', text: 'rd-confirm-job-text', snap: 'rd-confirm-job-snap', yes: 'rd-confirm-job-yes', no: 'rd-confirm-job-no' },
    twin: { dialog: 'rd-confirm-twin', text: 'rd-confirm-twin-text', snap: 'rd-confirm-twin-snap', yes: 'rd-confirm-twin-yes', no: 'rd-confirm-twin-no' },
  };
  let pendingConfirm = null; // { key, onYes, tenant, snapshot, fields, trigger, returnFocus }
  let postLock = false;

  function lockFields(fields, on) {
    (fields || []).forEach((el) => {
      if (!el) return;
      if (on) {
        if (!el.hasAttribute('data-rd-lock')) el.setAttribute('data-rd-lock', el.disabled ? '1' : '0');
        el.disabled = true;
      } else if (el.hasAttribute('data-rd-lock')) {
        el.disabled = el.getAttribute('data-rd-lock') === '1';
        el.removeAttribute('data-rd-lock');
      }
    });
  }

  function fieldsOf(ids) {
    const out = [];
    (ids || []).forEach((id) => {
      const el = $(id);
      if (el && out.indexOf(el) < 0) out.push(el);
    });
    const tenantEl = $('rd-tenant');
    if (tenantEl && out.indexOf(tenantEl) < 0) out.push(tenantEl);
    return out;
  }

  function snapView(snapshot) {
    const view = {};
    Object.keys(snapshot || {}).forEach((k) => {
      const v = snapshot[k];
      if (typeof File !== 'undefined' && v instanceof File) view[k] = { name: v.name, size: v.size, type: v.type };
      else view[k] = v;
    });
    return JSON.stringify(view, null, 2);
  }

  function closeConfirm() {
    const p = pendingConfirm;
    pendingConfirm = null;
    if (!p) return null;
    $(confirms[p.key].dialog).hidden = true;
    lockFields(p.fields, false);
    if (p.returnFocus && typeof p.returnFocus.focus === 'function') {
      try {
        p.returnFocus.focus();
      } catch (e) {
        /* element gone */
      }
    }
    return p;
  }

  async function withPostLock(triggers, confirmBtn, fn) {
    if (postLock) return;
    postLock = true;
    const list = (Array.isArray(triggers) ? triggers : [triggers]).filter(Boolean);
    list.forEach((el) => {
      el.disabled = true;
    });
    if (confirmBtn) confirmBtn.disabled = true;
    try {
      await fn();
    } finally {
      postLock = false;
      list.forEach((el) => {
        el.disabled = false;
      });
      if (confirmBtn) confirmBtn.disabled = false;
    }
  }

  // onYes(tenant) receives the tenant captured at the moment the dialog opened.
  // A second open is ignored until confirm or cancel, so the snapshot cannot change.
  function openConfirm(key, message, snapshot, fieldIds, trigger, onYes) {
    if (postLock || pendingConfirm) return;
    const cfg = confirms[key];
    const fields = fieldsOf(fieldIds);
    $(cfg.text).textContent = message;
    const snapEl = $(cfg.snap);
    if (snapEl) snapEl.textContent = snapView(snapshot);
    pendingConfirm = {
      key,
      onYes,
      tenant: activeTenant,
      snapshot,
      fields,
      trigger,
      returnFocus: document.activeElement,
    };
    lockFields(fields, true);
    $(cfg.dialog).hidden = false;
    $(cfg.no).focus();
  }

  function wireConfirmDialogs() {
    Object.keys(confirms).forEach((key) => {
      const cfg = confirms[key];
      $(cfg.yes).addEventListener('click', () => {
        const p = pendingConfirm;
        if (!p || p.key !== key || postLock) return;
        const trigger = p.trigger;
        const confirmBtn = $(cfg.yes);
        closeConfirm();
        withPostLock(trigger, confirmBtn, () => p.onYes(p.tenant));
      });
      $(cfg.no).addEventListener('click', () => {
        if (pendingConfirm && pendingConfirm.key === key && !postLock) closeConfirm();
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
      tbody.textContent = '';
      items.forEach((j) => {
        const tr = document.createElement('tr');
        if (j.jobId) tr.dataset.job = String(j.jobId);
        if (j.jobId === state.selectedJobId) tr.classList.add('sel');
        const td0 = document.createElement('td');
        const code = document.createElement('code');
        code.textContent = String(j.jobId || '').slice(0, 8);
        td0.appendChild(code);
        const tdStatus = document.createElement('td');
        statusBadge(tdStatus, j);
        tr.appendChild(td0);
        tr.appendChild(cellText(j.jobType));
        tr.appendChild(tdStatus);
        tr.appendChild(cellText(j.createdAt ? String(j.createdAt).slice(0, 19) : ''));
        tr.addEventListener('click', () => selectJob(tr.dataset.job));
        tbody.appendChild(tr);
      });
      $('rd-jobs-table').hidden = false;
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
      tbody.textContent = '';
      items.forEach((t) => {
        const tr = document.createElement('tr');
        if (t.twinId) tr.dataset.twin = String(t.twinId);
        if (t.twinId === state.selectedTwinId) tr.classList.add('sel');
        const td0 = document.createElement('td');
        const code = document.createElement('code');
        code.textContent = String(t.twinId || '').slice(0, 8);
        td0.appendChild(code);
        tr.appendChild(td0);
        tr.appendChild(cellText(t.sku));
        tr.appendChild(cellText(t.version));
        tr.addEventListener('click', () => selectTwin(tr.dataset.twin));
        tbody.appendChild(tr);
      });
      $('rd-twins-table').hidden = false;
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
      if (postLock) return;
      const jobType = $('rd-job-type').value;
      const scene = $('rd-job-scene').value;
      const snapshot = { tenant: activeTenant, jobType, scene };
      const trigger = ev.submitter || $('rd-job-submit');
      openConfirm(
        'job',
        `確定要送出算圖工作？類型：${jobType}，場景：${scene}（租戶：${activeTenant}）`,
        snapshot,
        ['rd-job-type', 'rd-job-scene'],
        trigger,
        async (tenant) => {
          try {
            const out = await api('/api/3d/jobs', {
              method: 'POST',
              tenant,
              body: JSON.stringify({ jobType: snapshot.jobType, scene: snapshot.scene }),
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
            showBanner(failureText(e), true);
          }
        },
      );
    });

    $('rd-job-cancel').addEventListener('click', () => {
      if (postLock) return;
      const jid = state.selectedJobId;
      if (!jid) return;
      const snapshot = { tenant: activeTenant, jobId: jid };
      openConfirm(
        'job',
        `確定要取消工作 ${jid.slice(0, 8)}…？（租戶：${activeTenant}）`,
        snapshot,
        [],
        $('rd-job-cancel'),
        async (tenant) => {
          try {
            const out = await api(`/api/3d/jobs/${encodeURIComponent(snapshot.jobId)}/cancel`, {
              method: 'POST',
              tenant,
              body: '{}',
            });
            $('rd-job-detail').textContent = pretty(out);
            if (isBlockedResult(out)) {
              showBanner(blockedMessage('取消工作', out), 'blocked');
            } else {
              showBanner(`取消結果：${out.status || 'unknown'}`);
            }
            await loadJobs();
          } catch (e) {
            showBanner(failureText(e), true);
          }
        },
      );
    });

    const runQuick = (path, label) => {
      if (postLock) return;
      const scene = $('rd-quick-scene').value;
      const snapshot = { tenant: activeTenant, scene, path, label };
      openConfirm(
        'job',
        `確定要執行「${label}」？場景：${scene}（會立即算圖，租戶：${activeTenant}）`,
        snapshot,
        ['rd-quick-scene'],
        [$('rd-quick-preview'), $('rd-quick-final')],
        async (tenant) => {
          $('rd-quick-out').hidden = false;
          $('rd-quick-out').textContent = '執行中…';
          try {
            const out = await api(snapshot.path, {
              method: 'POST',
              tenant,
              body: JSON.stringify({ scene: snapshot.scene }),
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
            $('rd-quick-out').textContent = failureText(e);
            showBanner(failureText(e), true);
          }
        },
      );
    };
    $('rd-quick-preview').addEventListener('click', () => runQuick('/api/render/preview', '預覽算圖'));
    $('rd-quick-final').addEventListener('click', () => runQuick('/api/render/final', '正式算圖'));
  }

  function wireTwinForms() {
    $('rd-refresh-twins').addEventListener('click', () => reloadFromButton('twins'));

    $('rd-form-twin').addEventListener('submit', (ev) => {
      ev.preventDefault();
      if (postLock) return;
      const sku = $('rd-twin-sku').value.trim();
      const width = Number($('rd-twin-w').value);
      const height = Number($('rd-twin-h').value);
      const depth = Number($('rd-twin-d').value);
      const snapshot = { tenant: activeTenant, sku, width, height, depth };
      openConfirm(
        'twin',
        `確定要建立數位分身？SKU：${sku}（租戶：${activeTenant}）`,
        snapshot,
        ['rd-twin-sku', 'rd-twin-w', 'rd-twin-h', 'rd-twin-d'],
        ev.submitter || $('rd-twin-submit'),
        async (tenant) => {
          $('rd-twin-out').hidden = false;
          $('rd-twin-out').textContent = '建立中…';
          try {
            const out = await api('/api/digital-twins', {
              method: 'POST',
              tenant,
              body: JSON.stringify({
                sku: snapshot.sku,
                dimensions: { width: snapshot.width, height: snapshot.height, depth: snapshot.depth },
              }),
            });
            $('rd-twin-out').textContent = pretty(out);
            if (isBlockedResult(out)) {
              showBanner(blockedMessage('建立分身', out), 'blocked');
              return;
            }
            showBanner(`分身已建立，編號 ${out.twinId}`);
            state.selectedTwinId = out.twinId;
            await loadTwins();
            selectTwin(out.twinId, true);
          } catch (e) {
            $('rd-twin-out').textContent = failureText(e);
            showBanner(failureText(e), true);
          }
        },
      );
    });

    $('rd-form-upload').addEventListener('submit', (ev) => {
      ev.preventDefault();
      if (postLock) return;
      const sku = $('rd-upload-sku').value.trim();
      const file = $('rd-upload-file').files && $('rd-upload-file').files[0];
      if (!file) return;
      const snapshot = { tenant: activeTenant, sku, file, fileName: file.name };
      openConfirm(
        'twin',
        `確定要上傳「${file.name}」並建立 SKU ${sku} 的分身？（租戶：${activeTenant}）`,
        snapshot,
        ['rd-upload-sku', 'rd-upload-file'],
        ev.submitter || $('rd-upload-submit'),
        async (tenant) => {
          $('rd-twin-out').hidden = false;
          $('rd-twin-out').textContent = '上傳中…';
          try {
            const fd = new FormData();
            fd.append('sku', snapshot.sku);
            fd.append('file', snapshot.file);
            const out = await api('/api/digital-twins/upload', { method: 'POST', tenant, body: fd });
            $('rd-twin-out').textContent = pretty(out);
            const twin = out.twin || {};
            if (isBlockedResult(out)) {
              showBanner(blockedMessage('上傳', out), 'blocked');
            } else {
              showBanner(`上傳完成，分身 ${twin.twinId || ''}，工作狀態：${(out.job || {}).status || ''}${mockHint(out)}`);
            }
            if (twin.twinId && !isBlockedResult(out)) {
              state.selectedTwinId = twin.twinId;
              await loadTwins();
              selectTwin(twin.twinId, true);
            }
          } catch (e) {
            $('rd-twin-out').textContent = failureText(e);
            showBanner(failureText(e), true);
          }
        },
      );
    });

    $('rd-twin-preview').addEventListener('click', () => {
      if (postLock) return;
      const tid = state.selectedTwinId;
      if (!tid) return;
      const snapshot = { tenant: activeTenant, twinId: tid };
      openConfirm(
        'twin',
        `確定要為此分身產生預覽算圖？（${tid.slice(0, 8)}…，租戶：${activeTenant}）`,
        snapshot,
        [],
        $('rd-twin-preview'),
        async (tenant) => {
          $('rd-twin-out').hidden = false;
          $('rd-twin-out').textContent = '算圖中…';
          try {
            const out = await api(`/api/digital-twins/${encodeURIComponent(snapshot.twinId)}/preview`, {
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
            await selectTwin(snapshot.twinId, true);
            await loadTwins();
          } catch (e) {
            $('rd-twin-out').textContent = failureText(e);
            showBanner(failureText(e), true);
          }
        },
      );
    });

    $('rd-twin-360').addEventListener('click', () => {
      if (postLock) return;
      const tid = state.selectedTwinId;
      if (!tid) return;
      const snapshot = { tenant: activeTenant, twinId: tid };
      openConfirm(
        'twin',
        `確定要產生 360 環繞？（${tid.slice(0, 8)}…，36 格，可能較久，租戶：${activeTenant}）`,
        snapshot,
        [],
        $('rd-twin-360'),
        async (tenant) => {
          $('rd-twin-out').hidden = false;
          $('rd-twin-out').textContent = '算圖中…';
          try {
            const out = await api(`/api/digital-twins/${encodeURIComponent(snapshot.twinId)}/360`, {
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
            $('rd-twin-out').textContent = failureText(e);
            showBanner(failureText(e), true);
          }
        },
      );
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
