// /admin/materials — materials, remnants, nesting benchmarks
(function () {
  'use strict';

  var DEFAULT_TENANT = 'sonaqueen-home';
  var idSeq = 0;
  var loadSeq = 0;
  var state = {
    materials: null,
    remnants: null,
    selectedLot: null,
    selectedRem: null,
    loading: false,
    confirmOpen: false,
    lotSubmitting: false,
    reserveSubmitting: false,
    benchSubmitting: false,
    ccSubmitting: false,
    ccActionId: null,
    cycleCounts: null,
    lotDetail: null,
    quarantineSubmitting: false,
    remOpsSubmitting: false,
    lastLotAttempt: null,
    lastReserveAttempt: null,
    lastCcAttempt: null,
  };

  function $(id) { return document.getElementById(id); }

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }

  function makeIdempotencyKey() {
    if (typeof crypto !== 'undefined' && crypto && typeof crypto.randomUUID === 'function') {
      try {
        var u = crypto.randomUUID();
        if (u) return String(u);
      } catch (e) { /* fallback below */ }
    }
    idSeq += 1;
    return 'mt-' + Date.now().toString(36) + '-' + idSeq.toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  function tenant() {
    var v = ($('mt-tenant') && $('mt-tenant').value || '').trim();
    return v || DEFAULT_TENANT;
  }

  function headers(json, pinnedTenant) {
    var h = { 'X-Tenant-Id': pinnedTenant || tenant(), Accept: 'application/json' };
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }

  function fmtJson(obj) {
    try { return JSON.stringify(obj, null, 2); } catch (e) { return String(obj); }
  }

  function tokenBad(v) {
    if (v == null || typeof v === 'boolean' || typeof v === 'object') return false;
    var s = String(v).trim().toUpperCase();
    return s === 'BLOCKED' || s === 'FAILED' || s.indexOf('BLOCKED_') === 0 || s.indexOf('FAILED_') === 0;
  }

  function checksHaveVeto(out) {
    if (!out || typeof out !== 'object') return false;
    var lists = [];
    if (Array.isArray(out.checks)) lists.push(out.checks);
    if (out.safety && Array.isArray(out.safety.checks)) lists.push(out.safety.checks);
    for (var i = 0; i < lists.length; i++) {
      for (var j = 0; j < lists[i].length; j++) {
        if (lists[i][j] && lists[i][j].veto === true) return true;
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
    var job = out.job && typeof out.job === 'object' ? out.job : null;
    return (
      out.ok === false ||
      out.status === 'blocked' ||
      tokenBad(out.status) ||
      tokenBad(out.label) ||
      tokenBad(out.truthLabel) ||
      String(out.error || '').indexOf('BLOCKED_') === 0 ||
      out.veto === true ||
      checksHaveVeto(out) ||
      Boolean(
        job &&
          (job.status === 'blocked' ||
            tokenBad(job.status) ||
            tokenBad(job.label) ||
            tokenBad(job.truthLabel) ||
            String(job.error || '').indexOf('BLOCKED_') === 0)
      )
    );
  }

  function blockedMessage(label, out) {
    var code = (out && (out.error || out.status || out.label || out.truthLabel)) || '';
    return label + '失敗：已阻擋' + (code ? '（' + code + '）' : '');
  }

  function setLocked(nodes, on) {
    (nodes || []).forEach(function (node) {
      if (!node) return;
      if (on) {
        if (!node.hasAttribute('data-mt-lock')) {
          node.setAttribute('data-mt-lock', node.disabled ? '1' : '0');
        }
        node.disabled = true;
      } else if (node.hasAttribute('data-mt-lock')) {
        node.disabled = node.getAttribute('data-mt-lock') === '1';
        node.removeAttribute('data-mt-lock');
      }
    });
  }

  function formFields(form) {
    var nodes = [];
    if (form) {
      Array.prototype.forEach.call(form.querySelectorAll('input, select, textarea'), function (n) {
        nodes.push(n);
      });
    }
    var t = $('mt-tenant');
    if (t && nodes.indexOf(t) < 0) nodes.push(t);
    return nodes;
  }

  function lotSubmitBtn() {
    return $('mt-lot-submit') || ($('mt-lot-form') && $('mt-lot-form').querySelector('button[type="submit"]'));
  }

  function ensureRetryBtn(formId, btnId, onClick) {
    var btn = $(btnId);
    if (!btn) {
      var form = $(formId);
      if (!form) return null;
      btn = el('button', { type: 'button', id: btnId, 'class': 'mt-btn' }, '重送');
      btn.hidden = true;
      form.appendChild(btn);
    }
    btn.addEventListener('click', onClick);
    return btn;
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

  function confirmDialog(title, body, lockNodes, onConfirm) {
    return new Promise(function (resolve) {
      if (state.confirmOpen) { resolve(false); return; }
      var dlg = $('mt-confirm');
      setLocked(lockNodes, true);
      if (!dlg || !dlg.showModal) {
        var confirmed = window.confirm(title + '\n' + body);
        setLocked(lockNodes, false);
        if (confirmed && onConfirm) onConfirm();
        resolve(confirmed);
        return;
      }
      state.confirmOpen = true;
      $('mt-confirm-title').textContent = title;
      $('mt-confirm-text').textContent = body;
      var finished = false;
      var okBtn = $('mt-confirm-ok');
      function done(ok) {
        if (finished) return;
        finished = true;
        dlg.removeEventListener('close', onClose);
        $('mt-confirm-cancel').removeEventListener('click', onCancel);
        if (okBtn) okBtn.removeEventListener('click', onOk);
        state.confirmOpen = false;
        setLocked(lockNodes, false);
        if (ok && onConfirm) onConfirm();
        resolve(ok);
      }
      function onClose() { done(dlg.returnValue === 'ok'); }
      function onCancel() { dlg.close('cancel'); done(false); }
      function onOk(ev) {
        ev.preventDefault();
        dlg.returnValue = 'ok';
        dlg.close('ok');
        done(true);
      }
      dlg.addEventListener('close', onClose);
      $('mt-confirm-cancel').addEventListener('click', onCancel);
      if (okBtn) okBtn.addEventListener('click', onOk);
      // Esc closes a <dialog> without changing returnValue: reset it so a previous 'ok' cannot confirm this one
      dlg.returnValue = '';
      dlg.showModal();
    });
  }

  function api(path, opts) {
    opts = opts || {};
    return fetch(path, {
      method: opts.method || 'GET',
      headers: headers(opts.json, opts.tenant),
      body: opts.body != null ? JSON.stringify(opts.body) : undefined,
    }).then(
      function (r) {
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
      },
      function (e) {
        var netErr = new Error('連線失敗，請稍後再試：' + ((e && e.message) || e));
        netErr.network = true;
        throw netErr;
      }
    );
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

  function lotAvailable(lot) {
    if (!lot) return '—';
    if (lot.remainingSheets != null) return String(lot.remainingSheets);
    if (lot.quantity != null) return String(lot.quantity);
    return '—';
  }

  function fmtQuarantineAt(value) {
    if (value == null || String(value).trim() === '') return '—';
    var d = new Date(value);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleString('zh-TW');
  }

  function renderLotDetail(data) {
    var body = $('mt-lot-detail-body');
    if (!body) return;
    body.textContent = '';
    if (!data) {
      body.appendChild(el('p', { 'class': 'mt-empty' }, '無法載入批次明細。'));
      return;
    }
    var q = data.quantities || {};
    var lot = data.lot || {};
    var summary = el('dl', { 'class': 'mt-dl' });
    [
      ['批次', data.lotId || lot.lotId || '—'],
      ['材料', String(lot.material || '—')],
      ['可用', String(q.available != null ? q.available : '—')],
      ['預留', String(q.reserved != null ? q.reserved : '—')],
      ['已耗', String(q.consumed != null ? q.consumed : '—')],
      ['隔離', lot.quarantined ? '是' : '否'],
      ['版本', String(data.version != null ? data.version : lot.version || '—')],
    ].forEach(function (pair) {
      var row = el('div');
      row.appendChild(el('dt', null, pair[0]));
      row.appendChild(el('dd', null, pair[1]));
      summary.appendChild(row);
    });
    body.appendChild(summary);
    if (data.sourceReceipt) {
      var rec = el('p', { 'class': 'mt-hint' });
      rec.appendChild(document.createTextNode('來源收料：'));
      rec.appendChild(el('code', null, data.sourceReceipt.receiptId || '—'));
      body.appendChild(rec);
    }
    var resv = data.reservations || [];
    if (resv.length) {
      var rh = el('h4', null, '預留清單（' + resv.length + '）');
      body.appendChild(rh);
      var tbl = el('table', { 'class': 'mt-table' });
      var hr = el('tr');
      ['預留 ID', '工單', '張數', '狀態'].forEach(function (h) { hr.appendChild(el('th', null, h)); });
      tbl.appendChild(el('thead')).appendChild(hr);
      var tbody = el('tbody');
      resv.forEach(function (item) {
        var tr = el('tr');
        tr.appendChild(el('td', null, item.reservationId || '—'));
        tr.appendChild(el('td', null, item.workOrderId || '—'));
        tr.appendChild(el('td', null, String(item.quantity != null ? item.quantity : '—')));
        tr.appendChild(el('td', null, item.state || '—'));
        tbody.appendChild(tr);
      });
      tbl.appendChild(tbody);
      body.appendChild(tbl);
    }
    var qh = data.quarantineHistory || [];
    if (qh.length) {
      body.appendChild(el('h4', null, '隔離歷史'));
      var ul = el('ul', { 'class': 'mt-list' });
      qh.forEach(function (ev) {
        var li = el('li');
        li.textContent = (ev.eventType || '?') + ' · ' + (ev.actor || '—') + ' · ' + (ev.reason || '')
          + ' · ' + fmtQuarantineAt(ev.at);
        ul.appendChild(li);
      });
      body.appendChild(ul);
    }
    var verInput = $('mt-quarantine-version');
    if (verInput && !state.quarantineSubmitting && !state.confirmOpen) {
      verInput.value = String(data.version != null ? data.version : lot.version || '');
    }
    var qBtn = $('mt-quarantine-btn');
    var relBtn = $('mt-release-quarantine-btn');
    var isQ = Boolean(lot.quarantined);
    if (qBtn) {
      qBtn.hidden = isQ;
      qBtn.disabled = state.quarantineSubmitting;
    }
    if (relBtn) {
      relBtn.hidden = !isQ;
      relBtn.disabled = state.quarantineSubmitting;
    }
  }

  function loadLotDetail(lot) {
    if (!lot || !lot.lotId) return Promise.resolve();
    state.selectedLot = lot;
    var detail = $('mt-lot-detail');
    if (detail) detail.hidden = false;
    var counted = $('mt-cc-counted');
    var reason = $('mt-cc-reason');
    if (counted && !state.ccSubmitting && !state.confirmOpen) {
      counted.value = lotAvailable(lot);
    }
    if (reason && !state.ccSubmitting && !state.confirmOpen) reason.value = '';
    if ($('mt-cc-lot-result')) {
      $('mt-cc-lot-result').hidden = true;
      $('mt-cc-lot-result').textContent = '';
    }
    var body = $('mt-lot-detail-body');
    if (body) {
      body.textContent = '';
      body.appendChild(el('p', { 'class': 'mt-hint' }, '載入明細中…'));
    }
    return api('/api/materials/lots/' + encodeURIComponent(lot.lotId))
      .then(function (r) {
        state.lotDetail = r.data;
        if (state.selectedLot && state.selectedLot.lotId === lot.lotId) {
          renderLotDetail(r.data);
        }
        return r.data;
      })
      .catch(function (e) {
        if (body) {
          body.textContent = '';
          body.appendChild(el('p', { 'class': 'mt-empty' }, '明細載入失敗：' + errorDetail(e)));
        }
      });
  }

  function selectLot(lot) {
    loadLotDetail(lot);
  }

  function lotRow(lot) {
    var tr = el('tr', { 'data-selectable': '1' });
    var id = lot.lotId || lot.materialLotId || lot.id || '—';
    tr.appendChild(el('td', null, id));
    tr.appendChild(el('td', null, String(lot.material || lot.materialCode || '—')));
    tr.appendChild(el('td', null, String(lot.quantity != null ? lot.quantity : lot.sheetCount || '—')));
    tr.appendChild(el('td', null, String(lot.thickness != null ? lot.thickness : '—')));
    var act = el('td');
    var ccBtn = el('button', { type: 'button', 'class': 'mt-btn mt-btn-small', 'data-cc-lot': id }, '盤點');
    ccBtn.addEventListener('click', function (ev) {
      ev.stopPropagation();
      Array.prototype.forEach.call(tr.parentNode.querySelectorAll('tr'), function (r) { r.classList.remove('sel'); });
      tr.classList.add('sel');
      selectLot(lot);
    });
    act.appendChild(ccBtn);
    tr.appendChild(act);
    tr.addEventListener('click', function () {
      Array.prototype.forEach.call(tr.parentNode.querySelectorAll('tr'), function (r) { r.classList.remove('sel'); });
      tr.classList.add('sel');
      selectLot(lot);
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
    ['批次 ID', '材料', '張數', '厚度', ''].forEach(function (h) { hr.appendChild(el('th', null, h)); });
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

  function clearSelectedRemnant() {
    clearReserveRetry();
    state.selectedRem = null;
    if ($('mt-rem-pick')) $('mt-rem-pick').hidden = false;
    if ($('mt-rem-detail')) $('mt-rem-detail').hidden = true;
    if ($('mt-rem-detail-body')) $('mt-rem-detail-body').textContent = '';
    if ($('mt-reserve-btn')) {
      $('mt-reserve-btn').disabled = true;
      $('mt-reserve-btn').title = '';
    }
  }

  function updateRemnantOpsButtons(rem) {
    var releaseBtn = $('mt-rem-release-btn');
    var consumeBtn = $('mt-rem-consume-btn');
    var reserveBtn = $('mt-reserve-btn');
    if (!rem) {
      if (releaseBtn) releaseBtn.disabled = true;
      if (consumeBtn) consumeBtn.disabled = true;
      if (reserveBtn) reserveBtn.disabled = true;
      return;
    }
    var st = String(rem.status || '').toLowerCase();
    var avail = st === 'available';
    var reserved = st === 'reserved';
    var consumable = avail || reserved;
    if (reserveBtn) {
      reserveBtn.disabled = state.reserveSubmitting || state.remOpsSubmitting || !avail;
      reserveBtn.title = avail ? '' : '僅可用餘料可預留';
    }
    if (releaseBtn) {
      releaseBtn.disabled = state.remOpsSubmitting || !reserved;
    }
    if (consumeBtn) {
      consumeBtn.disabled = state.remOpsSubmitting || state.confirmOpen || !consumable;
    }
  }

  function selectRemnant(rem) {
    clearReserveRetry();
    state.selectedRem = rem;
    $('mt-rem-pick').hidden = true;
    var detail = $('mt-rem-detail');
    detail.hidden = false;
    $('mt-rem-detail-body').textContent = fmtJson(rem);
    if ($('mt-rem-ops-result')) {
      $('mt-rem-ops-result').hidden = true;
      $('mt-rem-ops-result').textContent = '';
    }
    updateRemnantOpsButtons(rem);
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
    var currentId = state.selectedRem && state.selectedRem.remnantId;
    var matchedRem = null;
    if (!items.length) {
      if (currentId && !state.reserveSubmitting) clearSelectedRemnant();
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
      if (currentId && rem.remnantId === currentId) {
        tr.classList.add('sel');
        matchedRem = rem;
      }
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
    if (currentId) {
      if (matchedRem) {
        state.selectedRem = matchedRem;
        $('mt-rem-detail-body').textContent = fmtJson(matchedRem);
        updateRemnantOpsButtons(matchedRem);
      } else if (!state.reserveSubmitting) {
        clearSelectedRemnant();
      }
    }
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

  function fetchAllPagesHelper() {
    return window.fox3dFetchAllPages || globalThis.fox3dFetchAllPages;
  }

  function materialsPageFetcher(path) {
    return api(path).then(function (res) {
      var data = res.data || {};
      return {
        items: Array.isArray(data.lots) ? data.lots : [],
        total: Number(data.total),
        offset: Number(data.offset) || 0,
        limit: Number(data.limit) || 100,
        catalog: data,
      };
    });
  }

  function fetchAllMaterials() {
    var fetchAll = fetchAllPagesHelper();
    if (!fetchAll) {
      return api('/api/materials').then(function (res) { return res.data; });
    }
    return fetchAll(materialsPageFetcher, '/api/materials').then(function (page) {
      var catalog = page.catalog || {};
      return Object.assign({}, catalog, {
        lots: page.items || [],
        total: page.total,
        offset: 0,
        limit: page.limit,
      });
    });
  }

  function cycleCountPageFetcher(path) {
    return api(path).then(function (res) {
      var data = res.data || {};
      return {
        items: Array.isArray(data.items) ? data.items : [],
        total: Number(data.total),
        offset: Number(data.offset) || 0,
        limit: Number(data.limit) || 100,
      };
    });
  }

  function loadCycleCounts() {
    var base = '/api/materials/cycle-counts?status=WAITING_HUMAN_APPROVAL';
    var fetchAll = fetchAllPagesHelper();
    if (!fetchAll) {
      return api(base + '&limit=100').then(function (res) {
        state.cycleCounts = res.data;
        renderCycleCounts((res.data && res.data.items) || []);
        return res.data;
      });
    }
    return fetchAll(cycleCountPageFetcher, base).then(function (page) {
      var data = {
        items: page.items || [],
        total: page.total,
        offset: 0,
        limit: page.limit,
      };
      state.cycleCounts = data;
      renderCycleCounts(data.items);
      return data;
    });
  }

  function renderCycleCounts(items) {
    var wrap = $('mt-cc-wrap');
    if (!wrap) return;
    wrap.textContent = '';
    if (!items.length) {
      wrap.appendChild(el('p', { 'class': 'mt-empty' }, '目前沒有待核准盤點。'));
      return;
    }
    var tbl = el('table', { 'class': 'mt-table' });
    var hr = el('tr');
    ['盤點單', '批次', '快照可用', '盤點數', '差異', ''].forEach(function (h) { hr.appendChild(el('th', null, h)); });
    tbl.appendChild(el('thead')).appendChild(hr);
    var tbody = el('tbody');
    items.forEach(function (cc) {
      var tr = el('tr');
      tr.appendChild(el('td', null, cc.cycleCountId || '—'));
      tr.appendChild(el('td', null, cc.lotId || '—'));
      tr.appendChild(el('td', null, String(cc.systemAvailable != null ? cc.systemAvailable : '—')));
      tr.appendChild(el('td', null, String(cc.counted != null ? cc.counted : '—')));
      tr.appendChild(el('td', null, String(cc.variance != null ? cc.variance : '—')));
      var act = el('td');
      var approveBtn = el('button', {
        type: 'button',
        'class': 'mt-btn mt-btn-primary mt-btn-small',
        'data-cc-approve': cc.cycleCountId || '',
      }, '核准');
      var rejectBtn = el('button', {
        type: 'button',
        'class': 'mt-btn mt-btn-small',
        'data-cc-reject': cc.cycleCountId || '',
      }, '駁回');
      approveBtn.addEventListener('click', function () { onCycleCountApprove(cc); });
      rejectBtn.addEventListener('click', function () { onCycleCountReject(cc); });
      act.appendChild(approveBtn);
      act.appendChild(document.createTextNode(' '));
      act.appendChild(rejectBtn);
      tr.appendChild(act);
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
  }

  function loadAll() {
    loadSeq += 1;
    var seq = loadSeq;
    state.loading = true;
    showBanner('');
    $('mt-refresh').disabled = true;
    Promise.all([
      fetchAllMaterials(),
      api('/api/remnants'),
      loadCycleCounts(),
    ])
      .then(function (res) {
        if (seq !== loadSeq) return;
        state.materials = res[0];
        state.remnants = res[1].data;
        renderSheets(state.materials);
        renderLots(state.materials.lots || []);
        renderRemnants(state.remnants);
      })
      .catch(function (e) {
        if (seq !== loadSeq) return;
        showBanner('載入失敗：' + (e.message || e), 'err');
      })
      .then(function () {
        if (seq !== loadSeq) return;
        state.loading = false;
        $('mt-refresh').disabled = false;
      });
  }

  function errorDetail(e) {
    if (!e) return '未知錯誤';
    if (e.network) return e.message || '連線失敗';
    if (e.body && typeof e.body === 'object') {
      if (typeof e.body.detail === 'string') return e.body.detail;
      if (typeof e.body.message === 'string') return e.body.message;
      if (typeof e.body.error === 'string') return e.body.error;
    }
    return e.message || String(e);
  }

  function clearLotRetry() {
    state.lastLotAttempt = null;
    var btn = $('mt-lot-retry');
    if (btn) btn.hidden = true;
  }

  function clearReserveRetry() {
    state.lastReserveAttempt = null;
    var btn = $('mt-reserve-retry');
    if (btn) btn.hidden = true;
  }

  function clearCcRetry() {
    state.lastCcAttempt = null;
    var btn = $('mt-cc-retry');
    if (btn) btn.hidden = true;
  }

  function lotAttemptMatchesCurrent(attempt) {
    if (!attempt || !attempt.body) return false;
    var material = $('mt-lot-material') ? $('mt-lot-material').value : '';
    var thickness = parseFloat($('mt-lot-thickness') && $('mt-lot-thickness').value, 10);
    var qty = parseInt($('mt-lot-qty') && $('mt-lot-qty').value, 10);
    var supplier = ($('mt-lot-supplier') && $('mt-lot-supplier').value || '').trim();
    var actor = ($('mt-lot-actor') && $('mt-lot-actor').value || '').trim() || 'warehouse';
    return (
      tenant() === attempt.tenant &&
      material === attempt.body.material &&
      thickness === attempt.body.thickness &&
      qty === attempt.body.sheetCount &&
      actor === attempt.body.actor &&
      (supplier || undefined) === attempt.body.supplierLot
    );
  }

  function reserveAttemptMatchesCurrent(attempt) {
    if (!attempt || !attempt.body) return false;
    var rem = state.selectedRem;
    if (!rem || rem.remnantId !== attempt.remnantId) return false;
    if (String(rem.status || '').toLowerCase() !== 'available') return false;
    var by = ($('mt-reserve-by') && $('mt-reserve-by').value || '').trim() || 'manual';
    var leaseRaw = ($('mt-reserve-lease') && $('mt-reserve-lease').value || '').trim();
    var leaseVal = leaseRaw ? parseFloat(leaseRaw, 10) : undefined;
    return (
      tenant() === attempt.tenant &&
      by === attempt.body.by &&
      leaseVal === attempt.body.leaseSeconds
    );
  }

  function ccAttemptMatchesCurrent(attempt) {
    if (!attempt || !attempt.body || !attempt.lotId) return false;
    var lot = state.selectedLot;
    if (!lot || lot.lotId !== attempt.lotId) return false;
    var counted = parseInt($('mt-cc-counted') && $('mt-cc-counted').value, 10);
    var reason = ($('mt-cc-reason') && $('mt-cc-reason').value || '').trim();
    if (!Number.isFinite(counted) || counted < 0 || !reason) return false;
    return (
      tenant() === attempt.tenant &&
      counted === attempt.body.counted &&
      reason === attempt.body.reason
    );
  }

  function sendLotAttempt(attempt) {
    if (!attempt || state.lotSubmitting) return;
    state.lotSubmitting = true;
    var submitBtn = lotSubmitBtn();
    var retryBtn = $('mt-lot-retry');
    var okBtn = $('mt-confirm-ok');
    if (submitBtn) submitBtn.disabled = true;
    if (retryBtn) {
      retryBtn.disabled = true;
      retryBtn.hidden = true;
    }
    if (okBtn) okBtn.disabled = true;
    var out = $('mt-lot-result');
    out.hidden = false;
    out.classList.remove('err');
    out.textContent = '送出中…';
    api('/api/materials/lots', { method: 'POST', body: attempt.body, json: true, tenant: attempt.tenant })
      .then(function (r) {
        if (isBlockedResult(r.data)) {
          var bmsg = blockedMessage('入庫', r.data);
          out.classList.add('err');
          out.textContent = bmsg + '\n' + fmtJson(r.data);
          showBanner(bmsg, 'err');
          if (state.lastLotAttempt === attempt && lotAttemptMatchesCurrent(attempt)) {
            if (retryBtn) retryBtn.hidden = false;
          } else {
            clearLotRetry();
          }
          return;
        }
        if (state.lastLotAttempt === attempt) clearLotRetry();
        out.classList.remove('err');
        out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
        loadAll();
      })
      .catch(function (e) {
        out.classList.add('err');
        if (e && e.network) {
          out.textContent = '失敗：' + e.message;
          showBanner('入庫失敗：' + e.message, 'err');
        } else {
          out.textContent = '失敗：HTTP ' + (e.status || '?') + '\n' + fmtJson(e.body || e.message);
          showBanner('入庫失敗（HTTP ' + (e.status || '?') + '）：' + errorDetail(e), 'err');
        }
        if (state.lastLotAttempt === attempt && lotAttemptMatchesCurrent(attempt)) {
          if (retryBtn) retryBtn.hidden = false;
        } else {
          clearLotRetry();
        }
      })
      .then(function () {
        state.lotSubmitting = false;
        if (submitBtn) submitBtn.disabled = false;
        if (retryBtn) retryBtn.disabled = false;
        if (okBtn) okBtn.disabled = false;
      });
  }

  function onLotSubmit(ev) {
    ev.preventDefault();
    if (state.lotSubmitting || state.confirmOpen) return;
    clearLotRetry();
    var snapTenant = tenant();
    var material = $('mt-lot-material').value;
    var thickness = parseFloat($('mt-lot-thickness').value, 10);
    var qty = parseInt($('mt-lot-qty').value, 10);
    var supplier = $('mt-lot-supplier').value.trim();
    var actor = $('mt-lot-actor').value.trim() || 'warehouse';
    var msg = '將入庫 ' + qty + ' 張 · 材料 ' + material + ' · 厚度 ' + thickness + ' mm · 租戶 ' + snapTenant;
    var fields = formFields($('mt-lot-form'));
    confirmDialog('確認新增入庫批次', msg, fields, function () {
      if (state.lotSubmitting) return;
      var body = {
        material: material,
        thickness: thickness,
        sheetCount: qty,
        actor: actor,
        source: 'MANUAL',
        idempotencyKey: makeIdempotencyKey(),
      };
      if (supplier) body.supplierLot = supplier;
      state.lastLotAttempt = { body: body, tenant: snapTenant };
      sendLotAttempt(state.lastLotAttempt);
    });
  }

  function sendReserveAttempt(attempt) {
    if (!attempt || state.reserveSubmitting) return;
    state.reserveSubmitting = true;
    var reserveBtn = $('mt-reserve-btn');
    var retryBtn = $('mt-reserve-retry');
    var okBtn = $('mt-confirm-ok');
    if (reserveBtn) reserveBtn.disabled = true;
    if (retryBtn) {
      retryBtn.disabled = true;
      retryBtn.hidden = true;
    }
    if (okBtn) okBtn.disabled = true;
    var out = $('mt-reserve-result');
    out.hidden = false;
    out.classList.remove('err');
    out.textContent = '送出中…';
    api('/api/remnants/' + encodeURIComponent(attempt.remnantId) + '/reserve', {
      method: 'POST',
      body: attempt.body,
      json: true,
      tenant: attempt.tenant,
    })
      .then(function (r) {
        if (isBlockedResult(r.data)) {
          var bmsg = blockedMessage('預留餘料', r.data);
          out.classList.add('err');
          out.textContent = bmsg + '\n' + fmtJson(r.data);
          showBanner(bmsg, 'err');
          if (state.lastReserveAttempt === attempt && reserveAttemptMatchesCurrent(attempt)) {
            if (retryBtn) retryBtn.hidden = false;
          } else {
            clearReserveRetry();
          }
          return;
        }
        if (state.lastReserveAttempt === attempt) clearReserveRetry();
        out.classList.remove('err');
        out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
        loadAll();
      })
      .catch(function (e) {
        out.classList.add('err');
        if (e && e.network) {
          out.textContent = '失敗：' + e.message;
          showBanner('預留失敗：' + e.message, 'err');
        } else {
          out.textContent = '失敗：HTTP ' + (e.status || '?') + '\n' + fmtJson(e.body || e.message);
          showBanner('預留失敗（HTTP ' + (e.status || '?') + '）：' + errorDetail(e), 'err');
        }
        if (state.lastReserveAttempt === attempt && reserveAttemptMatchesCurrent(attempt)) {
          if (retryBtn) retryBtn.hidden = false;
        } else {
          clearReserveRetry();
        }
      })
      .then(function () {
        state.reserveSubmitting = false;
        updateRemnantOpsButtons(state.selectedRem);
        if (retryBtn) retryBtn.disabled = false;
        if (okBtn) okBtn.disabled = false;
      });
  }

  function onReserveSubmit(ev) {
    ev.preventDefault();
    if (state.reserveSubmitting || state.confirmOpen) return;
    clearReserveRetry();
    var rem = state.selectedRem;
    if (!rem || String(rem.status).toLowerCase() !== 'available') return;
    var snapTenant = tenant();
    var remnantId = rem.remnantId;
    var version = rem.version;
    var by = $('mt-reserve-by').value.trim() || 'manual';
    var leaseRaw = $('mt-reserve-lease').value.trim();
    var msg = '預留餘料 ' + remnantId + ' 給「' + by + '」（版本 ' + version + ' · 租戶 ' + snapTenant + '）';
    var fields = formFields($('mt-reserve-form'));
    confirmDialog('確認預留餘料', msg, fields, function () {
      if (state.reserveSubmitting) return;
      var body = { by: by, version: version, idempotencyKey: makeIdempotencyKey() };
      if (leaseRaw) body.leaseSeconds = parseFloat(leaseRaw, 10);
      state.lastReserveAttempt = { remnantId: remnantId, body: body, tenant: snapTenant };
      sendReserveAttempt(state.lastReserveAttempt);
    });
  }

  function sendCycleCountAttempt(attempt) {
    if (!attempt || state.ccSubmitting) return;
    state.ccSubmitting = true;
    var submitBtn = $('mt-cc-submit');
    var retryBtn = $('mt-cc-retry');
    var okBtn = $('mt-confirm-ok');
    var fields = formFields($('mt-cc-form'));
    setLocked(fields, true);
    if (submitBtn) submitBtn.disabled = true;
    if (retryBtn) {
      retryBtn.disabled = true;
      retryBtn.hidden = true;
    }
    if (okBtn) okBtn.disabled = true;
    var out = $('mt-cc-lot-result');
    if (out) {
      out.hidden = false;
      out.classList.remove('err');
      out.textContent = '送出中…';
    }
    var path = '/api/materials/lots/' + encodeURIComponent(attempt.lotId) + '/cycle-counts';
    api(path, { method: 'POST', body: attempt.body, json: true, tenant: attempt.tenant })
      .then(function (r) {
        if (isBlockedResult(r.data)) {
          var bmsg = blockedMessage('盤點', r.data);
          if (out) {
            out.classList.add('err');
            out.textContent = bmsg + '\n' + fmtJson(r.data);
          }
          showBanner(bmsg, 'err');
          if (state.lastCcAttempt === attempt && ccAttemptMatchesCurrent(attempt)) {
            if (retryBtn) retryBtn.hidden = false;
          } else {
            clearCcRetry();
          }
          return;
        }
        if (state.lastCcAttempt === attempt) clearCcRetry();
        if (out) {
          out.classList.remove('err');
          out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
        }
        loadAll();
      })
      .catch(function (e) {
        if (out) {
          out.classList.add('err');
          if (e && e.network) {
            out.textContent = '失敗：' + e.message;
            showBanner('盤點失敗：' + e.message, 'err');
          } else if (e && e.status === 409) {
            out.textContent = '帳面已變動：' + errorDetail(e);
            showBanner('帳面已變動，請重新盤點', 'err');
          } else {
            out.textContent = '失敗：HTTP ' + (e.status || '?') + '\n' + fmtJson(e.body || e.message);
            showBanner('盤點失敗（HTTP ' + (e.status || '?') + '）：' + errorDetail(e), 'err');
          }
        }
        if (state.lastCcAttempt === attempt && ccAttemptMatchesCurrent(attempt)) {
          if (retryBtn) retryBtn.hidden = false;
        } else {
          clearCcRetry();
        }
      })
      .then(function () {
        state.ccSubmitting = false;
        state.ccActionId = null;
        setLocked(fields, false);
        if (submitBtn) submitBtn.disabled = false;
        if (retryBtn) retryBtn.disabled = false;
        if (okBtn) okBtn.disabled = false;
      });
  }

  function onCycleCountSubmit(ev) {
    ev.preventDefault();
    if (state.ccSubmitting || state.confirmOpen) return;
    var lot = state.selectedLot;
    if (!lot || !lot.lotId) return;
    var snapTenant = tenant();
    var counted = parseInt($('mt-cc-counted') && $('mt-cc-counted').value, 10);
    var reason = ($('mt-cc-reason') && $('mt-cc-reason').value || '').trim();
    if (!Number.isFinite(counted) || counted < 0 || !reason) return;
    var snapCounted = counted;
    var snapReason = reason;
    var fields = formFields($('mt-cc-form'));
    var msg = '批次 ' + lot.lotId + ' · 盤點數 ' + snapCounted + ' · 原因「' + snapReason + '」· 租戶 ' + snapTenant;
    confirmDialog('確認送出盤點', msg, fields, function () {
      if (state.ccSubmitting) return;
      var previous = state.lastCcAttempt;
      if (previous && previous.lotId === lot.lotId && previous.tenant === snapTenant &&
          previous.body.counted === snapCounted && previous.body.reason === snapReason) {
        sendCycleCountAttempt(previous);
        return;
      }
      clearCcRetry();
      var body = {
        counted: snapCounted,
        reason: snapReason,
        idempotencyKey: makeIdempotencyKey(),
        actor: 'warehouse',
      };
      state.lastCcAttempt = { lotId: lot.lotId, body: body, tenant: snapTenant };
      sendCycleCountAttempt(state.lastCcAttempt);
    });
  }

  function postCycleCountAction(cc, action) {
    if (!cc || !cc.cycleCountId || state.ccActionId) return;
    state.ccActionId = cc.cycleCountId;
    var snapTenant = tenant();
    var path = '/api/materials/cycle-counts/' + encodeURIComponent(cc.cycleCountId) + '/' + action;
    var wrap = $('mt-cc-wrap');
    var buttons = wrap ? wrap.querySelectorAll('button') : [];
    setLocked(buttons, true);
  }

  function finishCycleCountAction() {
    state.ccActionId = null;
    var wrap = $('mt-cc-wrap');
    if (wrap) setLocked(wrap.querySelectorAll('button'), false);
    if ($('mt-confirm-ok')) $('mt-confirm-ok').disabled = false;
  }

  function onCycleCountApprove(cc) {
    if (state.ccActionId || state.confirmOpen) return;
    var snap = {
      available: cc.systemAvailable,
      reserved: cc.systemReserved,
      consumed: cc.systemConsumed,
      counted: cc.counted,
      variance: cc.variance,
    };
    var snapTenant = tenant();
    var lockNodes = [$('mt-tenant')];
    var msg = (
      '快照可用 ' + snap.available + ' / 預留 ' + snap.reserved + ' / 已耗 ' + snap.consumed +
      '\n盤點數 ' + snap.counted + '（差異 ' + snap.variance + '）\n租戶 ' + snapTenant
    );
    confirmDialog('確認核准盤點', msg, lockNodes, function () {
      if (state.ccActionId) return;
      postCycleCountAction(cc, 'approve');
      var okBtn = $('mt-confirm-ok');
      if (okBtn) okBtn.disabled = true;
      api(
        '/api/materials/cycle-counts/' + encodeURIComponent(cc.cycleCountId) + '/approve',
        { method: 'POST', body: { confirm: true, actor: 'supervisor' }, json: true, tenant: snapTenant }
      )
        .then(function (r) {
          if (isBlockedResult(r.data)) {
            showBanner(blockedMessage('核准盤點', r.data), 'err');
            return;
          }
          showBanner('盤點已核准', '');
          loadAll();
        })
        .catch(function (e) {
          if (e && e.network) {
            showBanner('核准失敗：' + e.message, 'err');
          } else if (e && e.status === 409) {
            showBanner('帳面已變動，請重新盤點', 'err');
          } else {
            showBanner('核准失敗：' + errorDetail(e), 'err');
          }
        })
        .then(function () { finishCycleCountAction(); });
    });
  }

  function onCycleCountReject(cc) {
    if (state.ccActionId || state.confirmOpen) return;
    var snapTenant = tenant();
    confirmDialog('確認駁回盤點', '駁回盤點單 ' + cc.cycleCountId + ' · 租戶 ' + snapTenant, [$('mt-tenant')], function () {
      if (state.ccActionId) return;
      postCycleCountAction(cc, 'reject');
      api(
        '/api/materials/cycle-counts/' + encodeURIComponent(cc.cycleCountId) + '/reject',
        { method: 'POST', body: { actor: 'supervisor' }, json: true, tenant: snapTenant }
      )
        .then(function () {
          showBanner('盤點已駁回', '');
          loadAll();
        })
        .catch(function (e) {
          showBanner('駁回失敗：' + errorDetail(e), 'err');
        })
        .then(function () { finishCycleCountAction(); });
    });
  }

  function sendQuarantineAttempt(path, attempt) {
    if (!attempt || state.quarantineSubmitting) return;
    state.quarantineSubmitting = true;
    var qBtn = $('mt-quarantine-btn');
    var relBtn = $('mt-release-quarantine-btn');
    var okBtn = $('mt-confirm-ok');
    var fields = formFields($('mt-quarantine-form'));
    setLocked(fields, true);
    if (qBtn) qBtn.disabled = true;
    if (relBtn) relBtn.disabled = true;
    if (okBtn) okBtn.disabled = true;
    var out = $('mt-quarantine-result');
    if (out) {
      out.hidden = false;
      out.classList.remove('err');
      out.textContent = '送出中…';
    }
    api(path, { method: 'POST', body: attempt.body, json: true, tenant: attempt.tenant })
      .then(function (r) {
        if (isBlockedResult(r.data)) {
          var bmsg = blockedMessage('隔離', r.data);
          if (out) {
            out.classList.add('err');
            out.textContent = bmsg + '\n' + fmtJson(r.data);
          }
          showBanner(bmsg, 'err');
          return;
        }
        if (out) {
          out.classList.remove('err');
          out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
        }
        return loadAll();
      })
      .then(function () {
        if (state.selectedLot && state.selectedLot.lotId === attempt.lotId) {
          loadLotDetail(state.selectedLot);
        }
      })
      .catch(function (e) {
        if (out) {
          out.classList.add('err');
          if (e && e.network) {
            out.textContent = '失敗：' + e.message;
            showBanner('隔離失敗：' + e.message, 'err');
          } else if (e && e.status === 409) {
            out.textContent = '版本衝突：' + errorDetail(e);
            showBanner('版本衝突，請重新載入明細', 'err');
          } else {
            out.textContent = '失敗：HTTP ' + (e.status || '?') + '\n' + fmtJson(e.body || e.message);
            showBanner('隔離失敗（HTTP ' + (e.status || '?') + '）：' + errorDetail(e), 'err');
          }
        }
      })
      .then(function () {
        state.quarantineSubmitting = false;
        setLocked(fields, false);
        if (okBtn) okBtn.disabled = false;
        if (state.selectedLot) {
          renderLotDetail(state.lotDetail);
        }
      });
  }

  function onQuarantineSubmit(ev) {
    ev.preventDefault();
    var target = ev.submitter || ev.target;
    var action = target && target.getAttribute('data-quarantine-action');
    if (!action) return;
    onQuarantineAction(action);
  }

  function onQuarantineAction(action) {
    if (state.quarantineSubmitting || state.confirmOpen) return;
    var lot = state.selectedLot;
    if (!lot || !lot.lotId) return;
    var snapTenant = tenant();
    var reasonEl = $('mt-quarantine-reason');
    var reason = reasonEl ? reasonEl.value.trim() : '';
    if (!reason) return;
    var snapReason = reason;
    var verRaw = $('mt-quarantine-version') && $('mt-quarantine-version').value.trim();
    var verVal = verRaw ? parseInt(verRaw, 10) : undefined;
    var fields = formFields($('mt-quarantine-form'));
    var label = action === 'quarantine' ? '隔離批次' : '解除隔離';
    var path = action === 'quarantine'
      ? '/api/materials/lots/' + encodeURIComponent(lot.lotId) + '/quarantine'
      : '/api/materials/lots/' + encodeURIComponent(lot.lotId) + '/release-quarantine';
    var msg = label + ' ' + lot.lotId + ' · 原因「' + snapReason + '」· 租戶 ' + snapTenant;
    confirmDialog('確認' + label, msg, fields, function () {
      if (state.quarantineSubmitting) return;
      var body = { confirm: true, reason: snapReason, actor: 'warehouse' };
      if (Number.isFinite(verVal) && verVal >= 1) body.expectedVersion = verVal;
      sendQuarantineAttempt(path, { lotId: lot.lotId, body: body, tenant: snapTenant });
    });
  }

  function sendRemnantOp(path, body, label) {
    if (state.remOpsSubmitting) return;
    state.remOpsSubmitting = true;
    var fields = formFields($('mt-rem-ops-form'));
    var releaseBtn = $('mt-rem-release-btn');
    var consumeBtn = $('mt-rem-consume-btn');
    var okBtn = $('mt-confirm-ok');
    setLocked(fields, true);
    updateRemnantOpsButtons(state.selectedRem);
    if (okBtn) okBtn.disabled = true;
    var out = $('mt-rem-ops-result');
    if (out) {
      out.hidden = false;
      out.classList.remove('err');
      out.textContent = '送出中…';
    }
    api(path, { method: 'POST', body: body, json: true, tenant: tenant() })
      .then(function (r) {
        if (isBlockedResult(r.data)) {
          var bmsg = blockedMessage(label, r.data);
          if (out) {
            out.classList.add('err');
            out.textContent = bmsg + '\n' + fmtJson(r.data);
          }
          showBanner(bmsg, 'err');
          return;
        }
        if (out) {
          out.classList.remove('err');
          out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
        }
        loadAll();
      })
      .catch(function (e) {
        if (out) {
          out.classList.add('err');
          out.textContent = e && e.network
            ? ('失敗：' + e.message)
            : ('失敗：HTTP ' + (e.status || '?') + '\n' + fmtJson(e.body || e.message));
        }
        showBanner(label + '失敗：' + errorDetail(e), 'err');
      })
      .then(function () {
        state.remOpsSubmitting = false;
        setLocked(fields, false);
        if (okBtn) okBtn.disabled = false;
        updateRemnantOpsButtons(state.selectedRem);
      });
  }

  function onRemnantRelease() {
    if (state.remOpsSubmitting || state.confirmOpen) return;
    var rem = state.selectedRem;
    if (!rem || String(rem.status || '').toLowerCase() !== 'reserved') return;
    var by = ($('mt-rem-ops-by') && $('mt-rem-ops-by').value.trim()) || 'manual';
    var snapBy = by;
    var snapVer = rem.version;
    var fields = formFields($('mt-rem-ops-form'));
    confirmDialog(
      '確認取消預留',
      '取消餘料 ' + rem.remnantId + ' 的預留（操作者 ' + snapBy + '）',
      fields,
      function () {
        sendRemnantOp(
          '/api/remnants/' + encodeURIComponent(rem.remnantId) + '/release-reservation',
          { by: snapBy, version: snapVer },
          '取消預留'
        );
      }
    );
  }

  function onRemnantConsume() {
    if (state.remOpsSubmitting || state.confirmOpen) return;
    var rem = state.selectedRem;
    if (!rem) return;
    var st = String(rem.status || '').toLowerCase();
    if (st !== 'available' && st !== 'reserved') return;
    var by = ($('mt-rem-ops-by') && $('mt-rem-ops-by').value.trim()) || 'manual';
    var snapBy = by;
    var snapVer = rem.version;
    var fields = formFields($('mt-rem-ops-form'));
    confirmDialog(
      '確認消耗餘料',
      '消耗餘料 ' + rem.remnantId + '（操作者 ' + snapBy + '）',
      fields,
      function () {
        sendRemnantOp(
          '/api/remnants/' + encodeURIComponent(rem.remnantId) + '/consume',
          { by: snapBy, version: snapVer, idempotencyKey: makeIdempotencyKey() },
          '消耗餘料'
        );
      }
    );
  }

  function onBenchRun() {
    if (state.benchSubmitting || state.confirmOpen) return;
    var snapTenant = tenant();
    var lockNodes = [$('mt-bench-run'), $('mt-tenant')];
    confirmDialog('確認執行排版基準', '將執行多組家具的排版基準測試，可能需要數秒。租戶 ' + snapTenant, lockNodes, function () {
      if (state.benchSubmitting) return;
      state.benchSubmitting = true;
      $('mt-bench-status').textContent = '執行中…';
      $('mt-bench-run').disabled = true;
      if ($('mt-confirm-ok')) $('mt-confirm-ok').disabled = true;
      api('/api/nesting/benchmarks', { method: 'POST', body: {}, json: true, tenant: snapTenant })
        .then(function (r) {
          if (isBlockedResult(r.data)) {
            var bmsg = blockedMessage('排版基準', r.data);
            $('mt-bench-status').textContent = bmsg;
            $('mt-bench-raw').hidden = false;
            $('mt-bench-raw').textContent = fmtJson(r.data);
            showBanner(bmsg, 'err');
            return;
          }
          $('mt-bench-status').textContent = '完成（HTTP ' + r.status + '）';
          renderBenchmark(r.data);
        })
        .catch(function (e) {
          $('mt-bench-status').textContent = e && e.network ? ('失敗：' + e.message) : '失敗';
          $('mt-bench-raw').hidden = false;
          $('mt-bench-raw').textContent = fmtJson((e && e.body) || (e && e.message) || e);
        })
        .then(function () {
          state.benchSubmitting = false;
          $('mt-bench-run').disabled = false;
          if ($('mt-confirm-ok')) $('mt-confirm-ok').disabled = false;
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
    function onTenantEdit() {
      clearLotRetry();
      clearReserveRetry();
      clearCcRetry();
      if (!state.confirmOpen) {
        clearSelectedRemnant();
        state.selectedLot = null;
        if ($('mt-lot-detail')) $('mt-lot-detail').hidden = true;
      }
    }
    $('mt-tenant').addEventListener('input', onTenantEdit);
    $('mt-tenant').addEventListener('change', function (e) {
      onTenantEdit();
      try { localStorage.setItem('fox3d.tenant', e.target.value.trim()); } catch (x) { /* blocked */ }
      loadAll();
    });
    $('mt-refresh').addEventListener('click', loadAll);
    Array.prototype.forEach.call(document.querySelectorAll('.mt-tabs button'), function (b) {
      b.addEventListener('click', function () { setTabs(b.getAttribute('data-panel')); });
    });
    $('mt-lot-form').addEventListener('submit', onLotSubmit);
    $('mt-lot-form').addEventListener('input', clearLotRetry);
    $('mt-lot-form').addEventListener('change', clearLotRetry);
    $('mt-reserve-form').addEventListener('submit', onReserveSubmit);
    $('mt-reserve-form').addEventListener('input', clearReserveRetry);
    $('mt-reserve-form').addEventListener('change', clearReserveRetry);
    ensureRetryBtn('mt-lot-form', 'mt-lot-retry', function () {
      if (!lotAttemptMatchesCurrent(state.lastLotAttempt)) {
        clearLotRetry();
        return;
      }
      sendLotAttempt(state.lastLotAttempt);
    });
    ensureRetryBtn('mt-reserve-form', 'mt-reserve-retry', function () {
      if (!reserveAttemptMatchesCurrent(state.lastReserveAttempt)) {
        clearReserveRetry();
        return;
      }
      sendReserveAttempt(state.lastReserveAttempt);
    });
    ensureRetryBtn('mt-cc-form', 'mt-cc-retry', function () {
      if (!ccAttemptMatchesCurrent(state.lastCcAttempt)) {
        clearCcRetry();
        return;
      }
      sendCycleCountAttempt(state.lastCcAttempt);
    });
    $('mt-bench-run').addEventListener('click', onBenchRun);
    if ($('mt-quarantine-form')) {
      $('mt-quarantine-form').addEventListener('submit', onQuarantineSubmit);
    }
    if ($('mt-rem-release-btn')) {
      $('mt-rem-release-btn').addEventListener('click', onRemnantRelease);
    }
    if ($('mt-rem-consume-btn')) {
      $('mt-rem-consume-btn').addEventListener('click', onRemnantConsume);
    }
    if ($('mt-cc-form')) {
      $('mt-cc-form').addEventListener('submit', onCycleCountSubmit);
      function updateCcRetryVisibility() {
        var retry = $('mt-cc-retry');
        if (retry) retry.hidden = !ccAttemptMatchesCurrent(state.lastCcAttempt);
      }
      $('mt-cc-form').addEventListener('input', updateCcRetryVisibility);
      $('mt-cc-form').addEventListener('change', updateCcRetryVisibility);
    }
    loadAll();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
