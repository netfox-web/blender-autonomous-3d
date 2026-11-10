'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );

  const state = { selectedJobId: null, selectedTwinId: null, confirmCb: null };

  function tenantId() {
    const el = $('rd-tenant');
    const v = (el && el.value.trim()) || '';
    try {
      const stored = localStorage.getItem('fox3d.tenant');
      if (!v && stored) return stored;
    } catch (e) {
      /* storage blocked */
    }
    return v || 'sonaqueen-home';
  }

  function syncTenantStorage() {
    const el = $('rd-tenant');
    if (!el) return;
    try {
      const stored = localStorage.getItem('fox3d.tenant');
      if (stored) el.value = stored;
    } catch (e) {
      /* storage blocked */
    }
    el.addEventListener('change', () => {
      try {
        localStorage.setItem('fox3d.tenant', el.value.trim());
      } catch (e) {
        /* storage blocked */
      }
    });
  }

  function showBanner(msg, isError) {
    const el = $('rd-banner');
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.textContent = msg;
    el.classList.toggle('error', Boolean(isError));
  }

  async function api(url, options = {}) {
    const headers = { 'X-Tenant-Id': tenantId(), ...(options.headers || {}) };
    if (!(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(url, { ...options, headers });
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

  function statusBadge(job) {
    const st = String(job.status || '');
    const src = String(job.discoverySource || '');
    const err = job.error || '';
    let extra = '';
    if (src === 'MOCK' || st === 'blocked') {
      extra = ' <span class="st-mock" title="模擬環境，非正式渲染輸出">MOCK</span>';
    } else if (String(err).startsWith('BLOCKED_')) {
      extra = ' <span class="st-blocked">BLOCKED</span>';
    } else if (st === 'failed' || st === 'cancelled') {
      extra = ' <span class="st-partial">' + esc(st) + '</span>';
    }
    return esc(st) + extra;
  }

  function openConfirm(dialogId, textId, yesId, noId, message, onYes) {
    const dlg = $(dialogId);
    $(textId).textContent = message;
    dlg.hidden = false;
    state.confirmCb = onYes;
    const yes = $(yesId);
    const no = $(noId);
    const cleanup = () => {
      dlg.hidden = true;
      state.confirmCb = null;
      yes.removeEventListener('click', onYesClick);
      no.removeEventListener('click', onNoClick);
    };
    const onYesClick = async () => {
      cleanup();
      if (onYes) await onYes();
    };
    const onNoClick = () => cleanup();
    yes.addEventListener('click', onYesClick);
    no.addEventListener('click', onNoClick);
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
          return `<tr data-job="${esc(j.jobId)}"${sel}><td><code>${esc(j.jobId.slice(0, 8))}</code></td><td>${esc(j.jobType)}</td><td>${statusBadge(j)}</td><td>${esc(created)}</td></tr>`;
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
          return `<tr data-twin="${esc(t.twinId)}"${sel}><td><code>${esc(t.twinId.slice(0, 8))}</code></td><td>${esc(t.sku)}</td><td>${esc(t.version)}</td></tr>`;
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
    $('rd-twin-preview-wrap').hidden = true;
    try {
      const twin = await api(`/api/digital-twins/${encodeURIComponent(twinId)}`);
      $('rd-twin-detail').textContent = pretty(twin);
      if (twin.previewAssetId) {
        $('rd-twin-preview-img').src = `/api/assets/${encodeURIComponent(twin.previewAssetId)}`;
        $('rd-twin-preview-wrap').hidden = false;
      }
      if (!quiet) showBanner('已載入分身明細。');
    } catch (e) {
      $('rd-twin-detail').textContent = e.message;
      if (!quiet) showBanner(e.message, true);
    }
  }

  function wireJobForms() {
    $('rd-refresh-jobs').addEventListener('click', () => loadJobs());
    $('rd-form-job').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const jobType = $('rd-job-type').value;
      const scene = $('rd-job-scene').value;
      openConfirm(
        'rd-confirm-job',
        'rd-confirm-job-text',
        'rd-confirm-job-yes',
        'rd-confirm-job-no',
        `確定要送出算圖工作？類型：${jobType}，場景：${scene}`,
        async () => {
          try {
            const out = await api('/api/3d/jobs', {
              method: 'POST',
              body: JSON.stringify({ tenantId: tenantId(), jobType, scene }),
            });
            showBanner(`工作已送出，編號 ${out.jobId}，狀態：${out.status || 'queued'}`);
            $('rd-job-detail').hidden = false;
            $('rd-job-detail-empty').hidden = true;
            $('rd-job-actions').hidden = false;
            $('rd-job-detail').textContent = pretty(out);
            state.selectedJobId = out.jobId;
            await loadJobs();
          } catch (e) {
            showBanner(e.message, true);
          }
        }
      );
    });

    $('rd-job-cancel').addEventListener('click', () => {
      const jid = state.selectedJobId;
      if (!jid) return;
      openConfirm(
        'rd-confirm-job',
        'rd-confirm-job-text',
        'rd-confirm-job-yes',
        'rd-confirm-job-no',
        `確定要取消工作 ${jid.slice(0, 8)}…？`,
        async () => {
          try {
            const out = await api(`/api/3d/jobs/${encodeURIComponent(jid)}/cancel`, { method: 'POST', body: '{}' });
            showBanner(`取消結果：${out.status || 'unknown'}`);
            $('rd-job-detail').textContent = pretty(out);
            await loadJobs();
          } catch (e) {
            showBanner(e.message, true);
          }
        }
      );
    });

    const runQuick = (path, label) => {
      const scene = $('rd-quick-scene').value;
      openConfirm(
        'rd-confirm-job',
        'rd-confirm-job-text',
        'rd-confirm-job-yes',
        'rd-confirm-job-no',
        `確定要執行「${label}」？場景：${scene}（會立即算圖）`,
        async () => {
          $('rd-quick-out').hidden = false;
          $('rd-quick-out').textContent = '執行中…';
          try {
            const out = await api(path, {
              method: 'POST',
              body: JSON.stringify({ tenantId: tenantId(), scene }),
            });
            $('rd-quick-out').textContent = pretty(out);
            const hint = out.discoverySource === 'MOCK' ? '（MOCK 模擬輸出）' : '';
            showBanner(`${label}完成，狀態：${out.status || ''}${hint}`);
            state.selectedJobId = out.jobId;
            await loadJobs();
            if (out.jobId) selectJob(out.jobId, true);
          } catch (e) {
            $('rd-quick-out').textContent = e.message;
            showBanner(e.message, true);
          }
        }
      );
    };
    $('rd-quick-preview').addEventListener('click', () => runQuick('/api/render/preview', '預覽算圖'));
    $('rd-quick-final').addEventListener('click', () => runQuick('/api/render/final', '正式算圖'));
  }

  function wireTwinForms() {
    $('rd-refresh-twins').addEventListener('click', () => loadTwins());

    $('rd-form-twin').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const sku = $('rd-twin-sku').value.trim();
      const width = Number($('rd-twin-w').value);
      const height = Number($('rd-twin-h').value);
      const depth = Number($('rd-twin-d').value);
      openConfirm(
        'rd-confirm-twin',
        'rd-confirm-twin-text',
        'rd-confirm-twin-yes',
        'rd-confirm-twin-no',
        `確定要建立數位分身？SKU：${sku}`,
        async () => {
          $('rd-twin-out').hidden = false;
          $('rd-twin-out').textContent = '建立中…';
          try {
            const out = await api('/api/digital-twins', {
              method: 'POST',
              body: JSON.stringify({
                tenantId: tenantId(),
                sku,
                dimensions: { width, height, depth },
              }),
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
        }
      );
    });

    $('rd-form-upload').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const sku = $('rd-upload-sku').value.trim();
      const file = $('rd-upload-file').files && $('rd-upload-file').files[0];
      if (!file) return;
      openConfirm(
        'rd-confirm-twin',
        'rd-confirm-twin-text',
        'rd-confirm-twin-yes',
        'rd-confirm-twin-no',
        `確定要上傳「${file.name}」並建立 SKU ${sku} 的分身？`,
        async () => {
          $('rd-twin-out').hidden = false;
          $('rd-twin-out').textContent = '上傳中…';
          try {
            const fd = new FormData();
            fd.append('sku', sku);
            fd.append('file', file);
            const headers = { 'X-Tenant-Id': tenantId() };
            const res = await fetch('/api/digital-twins/upload', { method: 'POST', headers, body: fd });
            const out = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(typeof out.detail === 'string' ? out.detail : '上傳失敗');
            $('rd-twin-out').textContent = pretty(out);
            const twin = out.twin || {};
            showBanner(`上傳完成，分身 ${twin.twinId || ''}，工作狀態：${(out.job || {}).status || ''}`);
            if (twin.twinId) {
              state.selectedTwinId = twin.twinId;
              await loadTwins();
              selectTwin(twin.twinId, true);
            }
          } catch (e) {
            $('rd-twin-out').textContent = e.message;
            showBanner(e.message, true);
          }
        }
      );
    });

    $('rd-twin-preview').addEventListener('click', () => {
      const tid = state.selectedTwinId;
      if (!tid) return;
      openConfirm(
        'rd-confirm-twin',
        'rd-confirm-twin-text',
        'rd-confirm-twin-yes',
        'rd-confirm-twin-no',
        '確定要為此分身產生預覽算圖？',
        async () => {
          $('rd-twin-out').hidden = false;
          $('rd-twin-out').textContent = '算圖中…';
          try {
            const out = await api(`/api/digital-twins/${encodeURIComponent(tid)}/preview`, {
              method: 'POST',
              body: '{}',
            });
            $('rd-twin-out').textContent = pretty(out);
            const mock = (out.job || {}).discoverySource === 'MOCK' ? '（MOCK）' : '';
            showBanner(`預覽完成${mock}`);
            await selectTwin(tid, true);
            await loadTwins();
          } catch (e) {
            $('rd-twin-out').textContent = e.message;
            showBanner(e.message, true);
          }
        }
      );
    });

    $('rd-twin-360').addEventListener('click', () => {
      const tid = state.selectedTwinId;
      if (!tid) return;
      openConfirm(
        'rd-confirm-twin',
        'rd-confirm-twin-text',
        'rd-confirm-twin-yes',
        'rd-confirm-twin-no',
        '確定要產生 360 環繞？（36 格，可能較久）',
        async () => {
          $('rd-twin-out').hidden = false;
          $('rd-twin-out').textContent = '算圖中…';
          try {
            const out = await api(`/api/digital-twins/${encodeURIComponent(tid)}/360`, {
              method: 'POST',
              body: '{}',
            });
            $('rd-twin-out').textContent = pretty(out);
            showBanner(`360 完成，狀態：${(out.job || {}).status || ''}`);
          } catch (e) {
            $('rd-twin-out').textContent = e.message;
            showBanner(e.message, true);
          }
        }
      );
    });
  }

  function init() {
    syncTenantStorage();
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
