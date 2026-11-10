// /admin/materials — materials, remnants, nesting benchmarks
(function () {
  'use strict';

  var DEFAULT_TENANT = 'sonaqueen-home';
  var state = { materials: null, remnants: null, selectedLot: null, selectedRem: null, loading: false };

  function $(id) { return document.getElementById(id); }

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }

  function tenant() {
    var v = ($('mt-tenant') && $('mt-tenant').value || '').trim();
    return v || DEFAULT_TENANT;
  }

  function headers(json) {
    var h = { 'X-Tenant-Id': tenant(), Accept: 'application/json' };
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }

  function fmtJson(obj) {
    try { return JSON.stringify(obj, null, 2); } catch (e) { return String(obj); }
  }

  function statusTag(label) {
    if (!label) return null;
    var u = String(label).toUpperCase();
    if (u === 'REAL') return el('span', { 'class': 'mt-tag ok' }, 'REAL');
    if (u === 'MOCK' || u.indexOf('BLOCKED') === 0 || u === 'PARTIAL') {
      return el('span', { 'class': 'mt-tag mock' }, label);
    }
    if (u === 'CONFIG') return el('span', { 'class': 'mt-tag wait' }, 'CONFIG');
    return el('span', { 'class': 'mt-tag wait' }, label);
  }

  function showBanner(text, kind) {
    var b = $('mt-banner');
    if (!b) return;
    if (!text) { b.hidden = true; b.textContent = ''; b.className = 'mt-banner'; return; }
    b.hidden = false;
    b.textContent = text;
    b.className = 'mt-banner ' + (kind || '');
  }

  function confirmDialog(title, body) {
    return new Promise(function (resolve) {
      var dlg = $('mt-confirm');
      if (!dlg || !dlg.showModal) { resolve(window.confirm(title + '\n' + body)); return; }
      $('mt-confirm-title').textContent = title;
      $('mt-confirm-text').textContent = body;
      function done(ok) {
        dlg.removeEventListener('close', onClose);
        $('mt-confirm-cancel').removeEventListener('click', onCancel);
        resolve(ok);
      }
      function onClose() { done(dlg.returnValue === 'ok'); }
      function onCancel() { dlg.close('cancel'); }
      dlg.addEventListener('close', onClose);
      $('mt-confirm-cancel').addEventListener('click', onCancel);
      dlg.showModal();
    });
  }

  function api(path, opts) {
    opts = opts || {};
    return fetch(path, {
      method: opts.method || 'GET',
      headers: headers(opts.json),
      body: opts.body != null ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      return r.text().then(function (t) {
        var data;
        try { data = t ? JSON.parse(t) : null; } catch (e) { data = t; }
        if (!r.ok) {
          var err = new Error('HTTP ' + r.status);
          err.status = r.status;
          err.body = data;
          throw err;
        }
        return { status: r.status, data: data };
      });
    });
  }

  function setTabs(name) {
    Array.prototype.forEach.call(document.querySelectorAll('.mt-tabs button'), function (b) {
      var on = b.getAttribute('data-panel') === name;
      b.setAttribute('aria-selected', String(on));
    });
    ['sheets', 'remnants', 'nesting'].forEach(function (p) {
      var panel = $('panel-' + p);
      if (panel) panel.hidden = p !== name;
    });
  }

  function renderSheets(data) {
    var wrap = $('mt-sheets-wrap');
    wrap.textContent = '';
    var skus = (data.sheets || []).concat();
    if (!skus.length) {
      wrap.appendChild(el('p', { 'class': 'mt-empty' }, '沒有板材規格資料。'));
      return;
    }
    var tbl = el('table', { 'class': 'mt-table' });
    var thead = el('thead');
    var hr = el('tr');
    hr.appendChild(el('th', null, '料號 SKU'));
    hr.appendChild(el('th', null, '說明'));
    thead.appendChild(hr);
    tbl.appendChild(thead);
    var tbody = el('tbody');
    skus.forEach(function (sku) {
      var tr = el('tr');
      var td0 = el('td');
      td0.appendChild(el('code', null, sku));
      tr.appendChild(td0);
      tr.appendChild(el('td', null, '內建規格（見 API 成本來源）'));
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    if (data.costSource) {
      var note = el('p', { 'class': 'mt-hint' });
      note.appendChild(document.createTextNode('成本來源：'));
      note.appendChild(statusTag(data.costSource) || document.createTextNode(data.costSource));
      wrap.appendChild(note);
    }
  }

  function lotRow(lot) {
    var tr = el('tr', { 'data-selectable': '1' });
    var id = lot.lotId || lot.materialLotId || lot.id || '—';
    tr.appendChild(el('td', null, id));
    tr.appendChild(el('td', null, String(lot.material || lot.materialCode || '—')));
    tr.appendChild(el('td', null, String(lot.quantity != null ? lot.quantity : lot.sheetCount || '—')));
    tr.appendChild(el('td', null, String(lot.thickness != null ? lot.thickness : '—')));
    tr.addEventListener('click', function () {
      state.selectedLot = lot;
      Array.prototype.forEach.call(tr.parentNode.querySelectorAll('tr'), function (r) { r.classList.remove('sel'); });
      tr.classList.add('sel');
      var detail = $('mt-lot-detail');
      var body = $('mt-lot-detail-body');
      detail.hidden = false;
      body.textContent = fmtJson(lot);
    });
    return tr;
  }

  function renderLots(lots) {
    var wrap = $('mt-lots-wrap');
    wrap.textContent = '';
    if (!lots || !lots.length) {
      wrap.appendChild(el('p', { 'class': 'mt-empty' }, '目前沒有入庫批次。可用下方表單新增。'));
      return;
    }
    var tbl = el('table', { 'class': 'mt-table' });
    var hr = el('tr');
    ['批次 ID', '材料', '張數', '厚度'].forEach(function (h) { hr.appendChild(el('th', null, h)); });
    tbl.appendChild(el('thead')).appendChild(hr);
    var tbody = el('tbody');
    lots.forEach(function (lot) { tbody.appendChild(lotRow(lot)); });
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
  }

  function remnantStatusTag(st) {
    var s = String(st || '').toLowerCase();
    if (s === 'available') return el('span', { 'class': 'mt-tag ok' }, '可用');
    if (s === 'reserved') return el('span', { 'class': 'mt-tag wait' }, '已預留');
    if (s === 'consumed') return el('span', { 'class': 'mt-tag' }, '已耗用');
    return el('span', { 'class': 'mt-tag' }, st || '—');
  }

  function selectRemnant(rem) {
    state.selectedRem = rem;
    $('mt-rem-pick').hidden = true;
    var detail = $('mt-rem-detail');
    detail.hidden = false;
    $('mt-rem-detail-body').textContent = fmtJson(rem);
    var btn = $('mt-reserve-btn');
    var ok = String(rem.status || '').toLowerCase() === 'available';
    btn.disabled = !ok;
    btn.title = ok ? '' : '僅可用餘料可預留';
  }

  function renderRemnants(snap) {
    var wrap = $('mt-remnants-wrap');
    var meta = $('mt-remnant-meta');
    wrap.textContent = '';
    meta.textContent = '';
    if (!snap) {
      meta.textContent = '載入失敗';
      wrap.appendChild(el('p', { 'class': 'mt-empty' }, '無法讀取餘料。'));
      return;
    }
    meta.appendChild(document.createTextNode('可用 ' + (snap.availableCount || 0) + ' 筆 · 資料標籤 '));
    meta.appendChild(statusTag(snap.label) || document.createTextNode(snap.label || '—'));
    meta.appendChild(document.createTextNode(' · 持久化 ' + (snap.persistence || '—')));
    if (snap.label === 'MOCK') {
      showBanner('餘料為 MOCK 資料（非持久化真實帳本），請勿當成現場庫存。', 'mock');
    }
    var items = snap.items || [];
    if (!items.length) {
      wrap.appendChild(el('p', { 'class': 'mt-empty' }, '沒有餘料記錄。'));
      return;
    }
    var tbl = el('table', { 'class': 'mt-table' });
    var hr = el('tr');
    ['ID', '尺寸 mm', '材料', '狀態'].forEach(function (h) { hr.appendChild(el('th', null, h)); });
    tbl.appendChild(el('thead')).appendChild(hr);
    var tbody = el('tbody');
    items.forEach(function (rem) {
      var tr = el('tr', { 'data-selectable': '1' });
      tr.appendChild(el('td', null, rem.remnantId || '—'));
      tr.appendChild(el('td', null, (rem.w || '?') + ' × ' + (rem.h || '?')));
      tr.appendChild(el('td', null, String(rem.materialCode || rem.material || '—')));
      var st = el('td');
      st.appendChild(remnantStatusTag(rem.status));
      tr.appendChild(st);
      tr.addEventListener('click', function () {
        Array.prototype.forEach.call(tbody.querySelectorAll('tr'), function (r) { r.classList.remove('sel'); });
        tr.classList.add('sel');
        selectRemnant(rem);
      });
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
  }

  function renderBenchmark(data) {
    $('mt-bench-wrap').hidden = false;
    var wrap = $('mt-bench-wrap');
    wrap.textContent = '';
    var summary = el('p', { 'class': 'mt-hint' });
    summary.textContent = 'V3 較少板材：' + (data.v3SheetWins || 0) + ' 案 · 較多：' + (data.v3SheetLosses || 0) + ' 案';
    if (data.liveMachineControl === false) {
      summary.appendChild(document.createTextNode(' · 非即時機台控制'));
    }
    wrap.appendChild(summary);
    if (data.note) {
      wrap.appendChild(el('p', { 'class': 'mt-hint' }, data.note));
    }
    var cases = data.cases || [];
    if (!cases.length) {
      wrap.appendChild(el('p', { 'class': 'mt-empty' }, '沒有測試案例。'));
      return;
    }
    var tbl = el('table', { 'class': 'mt-table' });
    var hr = el('tr');
    ['名稱', '數量', '基線板材', 'V3 板材', 'V3 較佳?'].forEach(function (h) { hr.appendChild(el('th', null, h)); });
    tbl.appendChild(el('thead')).appendChild(hr);
    var tbody = el('tbody');
    cases.forEach(function (c) {
      var tr = el('tr');
      tr.appendChild(el('td', null, c.name || c.kind || '—'));
      tr.appendChild(el('td', null, String(c.qty != null ? c.qty : '—')));
      var bl = c.baseline || {};
      var v3 = c.v3 || {};
      tr.appendChild(el('td', null, String(bl.sheetCount != null ? bl.sheetCount : '—')));
      tr.appendChild(el('td', null, String(v3.sheetCount != null ? v3.sheetCount : '—')));
      var win = c.v3BetterSheets ? '是' : (c.v3WorseSheets ? '否' : '—');
      tr.appendChild(el('td', null, win));
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    $('mt-bench-raw').hidden = false;
    $('mt-bench-raw').textContent = fmtJson(data);
  }

  function loadAll() {
    if (state.loading) return;
    state.loading = true;
    showBanner('');
    $('mt-refresh').disabled = true;
    Promise.all([
      api('/api/materials'),
      api('/api/remnants'),
    ])
      .then(function (res) {
        state.materials = res[0].data;
        state.remnants = res[1].data;
        renderSheets(state.materials);
        renderLots(state.materials.lots || []);
        renderRemnants(state.remnants);
      })
      .catch(function (e) {
        showBanner('載入失敗：' + (e.message || e), 'err');
      })
      .then(function () {
        state.loading = false;
        $('mt-refresh').disabled = false;
      });
  }

  function onLotSubmit(ev) {
    ev.preventDefault();
    var material = $('mt-lot-material').value;
    var thickness = parseFloat($('mt-lot-thickness').value, 10);
    var qty = parseInt($('mt-lot-qty').value, 10);
    var supplier = $('mt-lot-supplier').value.trim();
    var actor = $('mt-lot-actor').value.trim() || 'warehouse';
    var msg = '將入庫 ' + qty + ' 張 · 材料 ' + material + ' · 厚度 ' + thickness + ' mm · 租戶 ' + tenant();
    confirmDialog('確認新增入庫批次', msg).then(function (ok) {
      if (!ok) return;
      var body = { material: material, thickness: thickness, sheetCount: qty, actor: actor, source: 'MANUAL' };
      if (supplier) body.supplierLot = supplier;
      var out = $('mt-lot-result');
      out.hidden = false;
      out.textContent = '送出中…';
      api('/api/materials/lots', { method: 'POST', body: body, json: true })
        .then(function (r) {
          out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
          loadAll();
        })
        .catch(function (e) {
          out.textContent = '失敗：HTTP ' + (e.status || '?') + '\n' + fmtJson(e.body || e.message);
        });
    });
  }

  function onReserveSubmit(ev) {
    ev.preventDefault();
    var rem = state.selectedRem;
    if (!rem || String(rem.status).toLowerCase() !== 'available') return;
    var by = $('mt-reserve-by').value.trim() || 'manual';
    var leaseRaw = $('mt-reserve-lease').value.trim();
    var msg = '預留餘料 ' + rem.remnantId + ' 給「' + by + '」（版本 ' + rem.version + '）';
    confirmDialog('確認預留餘料', msg).then(function (ok) {
      if (!ok) return;
      var body = { by: by, version: rem.version };
      if (leaseRaw) body.leaseSeconds = parseFloat(leaseRaw, 10);
      var out = $('mt-reserve-result');
      out.hidden = false;
      out.textContent = '送出中…';
      api('/api/remnants/' + encodeURIComponent(rem.remnantId) + '/reserve', { method: 'POST', body: body, json: true })
        .then(function (r) {
          out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
          loadAll();
        })
        .catch(function (e) {
          out.textContent = '失敗：HTTP ' + (e.status || '?') + '\n' + fmtJson(e.body || e.message);
        });
    });
  }

  function onBenchRun() {
    confirmDialog('確認執行排版基準', '將執行多組家具的排版基準測試，可能需要數秒。租戶 ' + tenant()).then(function (ok) {
      if (!ok) return;
      $('mt-bench-status').textContent = '執行中…';
      $('mt-bench-run').disabled = true;
      api('/api/nesting/benchmarks', { method: 'POST', body: {}, json: true })
        .then(function (r) {
          $('mt-bench-status').textContent = '完成（HTTP ' + r.status + '）';
          renderBenchmark(r.data);
        })
        .catch(function (e) {
          $('mt-bench-status').textContent = '失敗';
          $('mt-bench-raw').hidden = false;
          $('mt-bench-raw').textContent = fmtJson(e.body || e.message);
        })
        .then(function () {
          $('mt-bench-run').disabled = false;
        });
    });
  }

  function boot() {
    try {
      var t = localStorage.getItem('fox3d.tenant');
      $('mt-tenant').value = t || DEFAULT_TENANT;
    } catch (e) {
      $('mt-tenant').value = DEFAULT_TENANT;
    }
    $('mt-tenant').addEventListener('change', function (e) {
      try { localStorage.setItem('fox3d.tenant', e.target.value.trim()); } catch (x) { /* blocked */ }
      loadAll();
    });
    $('mt-refresh').addEventListener('click', loadAll);
    Array.prototype.forEach.call(document.querySelectorAll('.mt-tabs button'), function (b) {
      b.addEventListener('click', function () { setTabs(b.getAttribute('data-panel')); });
    });
    $('mt-lot-form').addEventListener('submit', onLotSubmit);
    $('mt-reserve-form').addEventListener('submit', onReserveSubmit);
    $('mt-bench-run').addEventListener('click', onBenchRun);
    loadAll();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
