// /admin/prototypes — prototype board, unit detail, floor actions.
(function () {
  'use strict';
  var TENANT_KEY = 'fox3d.tenant';
  var DEFAULT_TENANT = 'sonaqueen-home';
  var state = { selected: null, posting: false, confirmSnap: null };
  var activeTenant = DEFAULT_TENANT;

  function $(id) { return document.getElementById(id); }

  function tenant() { return activeTenant; }

  function loadTenant() {
    try {
      var v = localStorage.getItem(TENANT_KEY);
      if (v && $('proto-tenant')) $('proto-tenant').value = v;
    } catch (e) { /* ignore */ }
    activeTenant = ($('proto-tenant') && $('proto-tenant').value.trim()) || DEFAULT_TENANT;
  }

  function saveTenant() {
    try { localStorage.setItem(TENANT_KEY, activeTenant); } catch (e) { /* ignore */ }
  }

  function setBanner(msg) {
    var el = $('proto-banner');
    if (!el) return;
    if (!msg) { el.hidden = true; el.textContent = ''; return; }
    el.hidden = false;
    el.textContent = msg;
  }

  function api(path, options) {
    options = options || {};
    var headers = Object.assign(
      { 'X-Tenant-Id': options.tenant || tenant(), Accept: 'application/json' },
      options.headers || {}
    );
  if (options.json) headers['Content-Type'] = 'application/json';
    return fetch(path, {
      method: options.method || 'GET',
      headers: headers,
      body: options.body ? (options.json ? JSON.stringify(options.body) : options.body) : undefined
    }).then(function (r) {
      return r.text().then(function (t) {
        var body;
        try { body = t ? JSON.parse(t) : null; } catch (e) { body = { detail: t || '無法讀取回覆' }; }
        if (!r.ok) {
          var err = new Error('HTTP ' + r.status + '：' + (body && body.detail ? String(body.detail) : JSON.stringify(body)));
          err.status = r.status;
          err.body = body;
          throw err;
        }
        return body;
      });
    }, function (e) {
      throw new Error('連線失敗，請稍後再試：' + ((e && e.message) || e));
    });
  }

  function isBlockedRow(row) {
    if (!row || typeof row !== 'object') return false;
    var st = String(row.state || row.prototypeStatus || row.unitState || '').toUpperCase();
    if (st === 'HOLD' || st === 'SCRAPPED') return true;
    var launch = String(row.launchDecision || '').toUpperCase();
    return launch === 'HUMAN_NO_GO' || launch.indexOf('HOLD') === 0;
  }

  function sourceLabel(row) {
    var v = row && (row.evidenceSourceLabel || row.evidenceSource || row.truthLabel);
    if (!v) return '—';
    var s = String(v).toUpperCase();
    if (s === 'REAL') return 'REAL_LOGIC（非現場實測）';
    if (s === 'FIXTURE') return 'FIXTURE（測試用）';
    return String(v);
  }

  function renderBoard(rows) {
    var box = $('proto-board');
    if (!box) return;
    box.textContent = '';
    if (!rows || !rows.length) {
      var empty = document.createElement('p');
      empty.className = 'proto-empty';
      empty.textContent = '此組合案尚無候選列。';
      box.appendChild(empty);
      return;
    }
    var table = document.createElement('table');
    table.className = 'proto-table';
    var head = document.createElement('tr');
    [['candidateId', '候選'], ['state', '狀態'], ['launchDecision', '上市決策'], ['evidenceSourceLabel', '證據來源']].forEach(function (c) {
      var th = document.createElement('th');
      th.textContent = c[1];
      head.appendChild(th);
    });
    table.appendChild(head);
    rows.forEach(function (row) {
      var tr = document.createElement('tr');
      [['candidateId'], ['state'], ['launchDecision']].forEach(function (c) {
        var td = document.createElement('td');
        td.textContent = row[c[0]] == null ? '—' : String(row[c[0]]);
        tr.appendChild(td);
      });
      var srcTd = document.createElement('td');
      var lbl = sourceLabel(row);
      srcTd.textContent = lbl;
      if (lbl.indexOf('FIXTURE') >= 0) srcTd.className = 'tag-fixture';
      tr.appendChild(srcTd);
      table.appendChild(tr);
    });
    box.appendChild(table);
  }

  function renderUnits(items) {
    var box = $('proto-units');
    if (!box) return;
    box.textContent = '';
    if (!items || !items.length) {
      var empty = document.createElement('p');
      empty.className = 'proto-empty';
      empty.textContent = '目前沒有原型單元。';
      box.appendChild(empty);
      return;
    }
    var table = document.createElement('table');
    table.className = 'proto-table';
    var head = document.createElement('tr');
    ['單元', '狀態', '證據', '明細'].forEach(function (t) {
      var th = document.createElement('th');
      th.textContent = t;
      head.appendChild(th);
    });
    table.appendChild(head);
    items.forEach(function (item) {
      var tr = document.createElement('tr');
      var idTd = document.createElement('td');
      idTd.textContent = String(item.prototypeUnitId || '');
      tr.appendChild(idTd);
      var stTd = document.createElement('td');
      stTd.textContent = String(item.state || '—');
      tr.appendChild(stTd);
      var srcTd = document.createElement('td');
      srcTd.textContent = sourceLabel(item.matrixRow || item);
      tr.appendChild(srcTd);
      var actTd = document.createElement('td');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'proto-btn secondary';
      btn.textContent = '查看';
      btn.addEventListener('click', function () { selectUnit(item.prototypeUnitId); });
      actTd.appendChild(btn);
      tr.appendChild(actTd);
      table.appendChild(tr);
    });
    box.appendChild(table);
  }

  function setActionLock(on) {
    state.posting = on;
    ['proto-start', 'proto-complete', 'proto-labor', 'proto-refresh'].forEach(function (id) {
      var el = $(id);
      if (el) el.disabled = on || (id !== 'proto-refresh' && !state.selected);
    });
  }

  function showDetail(data) {
    var pre = $('proto-detail');
    if (!pre) return;
    pre.textContent = JSON.stringify(data, null, 2);
  }

  function selectUnit(unitId) {
    if (!unitId || state.posting) return;
    api('/api/prototypes/units/' + encodeURIComponent(unitId))
      .then(function (body) {
        state.selected = body;
        showDetail(body);
        setActionLock(false);
      })
      .catch(function (e) { setBanner(e.message || String(e)); });
  }

  function openConfirm(text, snap, onOk) {
    var dlg = $('proto-confirm');
    if (!dlg) return;
    state.confirmSnap = snap;
    $('proto-confirm-text').textContent = text;
    $('proto-confirm-body').textContent = JSON.stringify(snap.body, null, 2);
    var finished = false;
    var okBtn = $('proto-confirm-ok');
    var cancelBtn = $('proto-confirm-cancel');
    function finish(ok) {
      if (finished) return;
      finished = true;
      dlg.removeEventListener('close', onClose);
      if (okBtn) okBtn.removeEventListener('click', onOkClick);
      if (cancelBtn) cancelBtn.removeEventListener('click', onCancelClick);
      if (ok) onOk(state.confirmSnap);
    }
    function onClose() { finish(dlg.returnValue === 'ok'); }
    function onCancelClick() { dlg.close('cancel'); finish(false); }
    function onOkClick(ev) {
      ev.preventDefault();
      dlg.returnValue = 'ok';
      dlg.close('ok');
      finish(true);
    }
    dlg.addEventListener('close', onClose);
    if (cancelBtn) cancelBtn.addEventListener('click', onCancelClick);
    if (okBtn) okBtn.addEventListener('click', onOkClick);
    dlg.returnValue = '';
    dlg.showModal();
  }

  function postAction(path, body) {
    if (state.posting) return;
    setActionLock(true);
    return api(path, { method: 'POST', body: body, json: true })
      .then(function (res) {
        setBanner('');
        showDetail(res);
        return refreshAll();
      })
      .catch(function (e) {
        setBanner(e.message || String(e));
      })
      .finally(function () { setActionLock(false); });
  }

  function actionPayload(action) {
    var op = ($('proto-operator') && $('proto-operator').value || '').trim();
    var sh = ($('proto-shift') && $('proto-shift').value || '').trim();
    if (!op || !sh) throw new Error('請填寫作業員與班別');
    var idem;
    try { idem = crypto.randomUUID(); } catch (e) { idem = 'idem-' + Date.now(); }
    var body = { operatorId: op, shiftId: sh, idempotencyKey: idem };
    if (action === 'labor') {
      var rawMins = ($('proto-labor-minutes') && $('proto-labor-minutes').value) || '';
      var mins = Number(rawMins);
      var reason = ($('proto-labor-reason') && $('proto-labor-reason').value || '').trim();
      var source = ($('proto-labor-source') && $('proto-labor-source').value || '').trim() || 'MANUAL';
      if (!Number.isFinite(mins) || mins <= 0) throw new Error('請填寫有效工時（分鐘）');
      if (!reason) throw new Error('請填寫工時原因');
      body.minutes = mins;
      body.reason = reason;
      body.source = source;
    }
    return { action: action, body: body, unitId: state.selected && state.selected.prototypeUnitId };
  }

  function bindAction(btnId, action, label) {
    var btn = $(btnId);
    if (!btn) return;
    btn.addEventListener('click', function () {
      if (!state.selected || state.posting) return;
      var snap;
      try { snap = actionPayload(action); } catch (e) { setBanner(e.message); return; }
      openConfirm(label, snap, function (attempt) {
        var uid = attempt.unitId;
        var path = '/api/prototypes/units/' + encodeURIComponent(uid) + '/' + action;
        postAction(path, attempt.body);
      });
    });
  }

  function refreshAll() {
    var portfolio = ($('proto-portfolio') && $('proto-portfolio').value || '').trim();
    setBanner('');
    var unitsP = api('/api/prototypes/units?limit=50').then(function (r) {
      renderUnits(r.items || []);
    });
    var boardP = Promise.resolve();
    if (portfolio) {
      boardP = api('/api/prototypes/board?portfolioId=' + encodeURIComponent(portfolio)).then(function (r) {
        renderBoard(r.rows || []);
      });
    } else {
      renderBoard([]);
    }
    return Promise.all([unitsP, boardP]).catch(function (e) { setBanner(e.message || String(e)); });
  }

  function init() {
    loadTenant();
    $('proto-refresh').addEventListener('click', function () {
      activeTenant = ($('proto-tenant') && $('proto-tenant').value.trim()) || DEFAULT_TENANT;
      saveTenant();
      refreshAll();
    });
    bindAction('proto-start', 'start', '確定要開工此原型單元？');
    bindAction('proto-complete', 'complete', '確定要標記完工？');
    bindAction('proto-labor', 'labor', '確定要登錄工時？');
    refreshAll();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();