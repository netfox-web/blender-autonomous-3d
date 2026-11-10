// /admin/pilot-floor — operator view, stations, dispatch, scan, exceptions.
(function () {
  'use strict';
  var TENANT_KEY = 'fox3d.tenant';
  var state = { operator: null };

  function $(id) { return document.getElementById(id); }

  function tenant() {
    var v = ($('pf-tenant') && $('pf-tenant').value || '').trim();
    return v || 'sonaqueen-home';
  }

  function saveTenant() {
    try { localStorage.setItem(TENANT_KEY, tenant()); } catch (e) { /* ignore */ }
  }

  function loadTenant() {
    try {
      var v = localStorage.getItem(TENANT_KEY);
      if (v && $('pf-tenant')) $('pf-tenant').value = v;
    } catch (e) { /* ignore */ }
  }

  function showDetail(obj, title) {
    var pre = $('pf-detail');
    var hint = $('pf-detail-hint');
    if (!pre) return;
    if (hint) hint.hidden = true;
    var text = typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
    pre.textContent = (title ? title + '\n\n' : '') + text;
  }

  function api(path, options) {
    var opts = options || {};
    var headers = Object.assign({ 'X-Tenant-Id': tenant(), Accept: 'application/json' }, opts.headers || {});
    if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    return fetch(path, { method: opts.method || 'GET', headers: headers, body: opts.body })
      .then(function (r) {
        return r.text().then(function (t) {
          var body;
          try { body = t ? JSON.parse(t) : null; } catch (e) { body = t; }
          return { status: r.status, ok: r.ok, body: body, raw: t };
        });
      });
  }

  function badgePartial(label, value) {
    if (value === true) return '';
    if (value === false) return '';
    var v = String(value || '').toUpperCase();
    if (v === 'PARTIAL' || v === 'MOCK' || v.indexOf('BLOCKED') === 0) {
      return '（' + (label || '狀態') + ' ' + v + '，非正式上線）';
    }
    return '';
  }

  function updateBanner(op) {
    var el = $('pf-banner');
    if (!el || !op) return;
    var parts = [];
    if (op.barcodeHardware && op.barcodeHardware !== 'REAL') parts.push('條碼硬體 ' + op.barcodeHardware);
    if (!op.liveMachineControl) parts.push('未授權實機控制');
    if (parts.length) {
      el.hidden = false;
      el.textContent = '提醒（非正式現場狀態）：' + parts.join('；') + '。';
    } else {
      el.hidden = true;
    }
  }

  // API values (work order ids, station ids, exception messages) are never parsed as HTML.
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function code(v) {
    var c = document.createElement('code');
    c.textContent = v == null ? '' : String(v);
    return c;
  }
  function withTag(text, tag) {
    var span = document.createElement('span');
    span.textContent = text == null ? '' : String(text);
    if (tag) {
      var t = document.createElement('span');
      t.className = 'pf-tag warn';
      t.textContent = tag;
      span.appendChild(document.createTextNode(' '));
      span.appendChild(t);
    }
    return span;
  }
  function rowCells(tr, cells) {
    cells.forEach(function (cell) {
      var td = document.createElement('td');
      if (cell instanceof Node) td.appendChild(cell);
      else td.textContent = cell == null ? '' : String(cell);
      tr.appendChild(td);
    });
  }

  function clearTable(id) {
    var tb = $(id);
    if (tb && tb.tBodies[0]) tb.tBodies[0].textContent = '';
  }

  function renderWorkOrders(items) {
    clearTable('pf-wo-table');
    var tb = $('pf-wo-table').tBodies[0];
    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 4;
      td.className = 'pf-empty';
      td.textContent = '目前沒有待辦工單。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (wo) {
      var tr = document.createElement('tr');
      tr.dataset.json = JSON.stringify(wo);
      rowCells(tr, [
        code(wo.workOrderId),
        withTag(wo.state, wo.qcHold ? '品檢暫停' : ''),
        (wo.openOps || []).join(', ') || '—',
        code((wo.scanToken || ''))
      ]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(wo, '工單');
        if ($('pf-dispatch-form')) {
          var f = $('pf-dispatch-form');
          f.workOrderId.value = wo.workOrderId;
          if ((wo.openOps || []).length) f.operation.value = wo.openOps[0];
        }
      });
      tb.appendChild(tr);
    });
  }

  function renderLots(items) {
    clearTable('pf-lot-table');
    var tb = $('pf-lot-table').tBodies[0];
    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 4;
      td.className = 'pf-empty';
      td.textContent = '沒有料批資料。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (lot) {
      var tr = document.createElement('tr');
      tr.dataset.json = JSON.stringify(lot);
      rowCells(tr, [
        code(lot.lotId),
        lot.material || '—',
        String(lot.available != null ? lot.available : '—'),
        lot.quarantined ? '是' : '否'
      ]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(lot, '料批');
      });
      tb.appendChild(tr);
    });
  }

  function renderStations(items) {
    clearTable('pf-station-table');
    var tb = $('pf-station-table').tBodies[0];
    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 5;
      td.className = 'pf-empty';
      td.textContent = '尚未註冊工作站，可在下方表單新增。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (st) {
      var tr = document.createElement('tr');
      tr.dataset.json = JSON.stringify(st);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pf-btn pf-btn-small';
      btn.textContent = '心跳';
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        heartbeatStation(st.stationId);
      });
      rowCells(tr, [
        code(st.stationId),
        st.status || '—',
        (st.capabilities || []).join(', '),
        st.heartbeatAt || '—',
        btn
      ]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(st, '工作站');
        var df = $('pf-dispatch-form');
        if (df) df.stationId.value = st.stationId;
      });
      tb.appendChild(tr);
    });
  }

  function renderLeases(items) {
    clearTable('pf-lease-table');
    var tb = $('pf-lease-table').tBodies[0];
    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 6;
      td.className = 'pf-empty';
      td.textContent = '沒有進行中的租約。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (lease) {
      var tr = document.createElement('tr');
      tr.dataset.json = JSON.stringify(lease);
      var actions = document.createElement('div');
      actions.className = 'pf-lease-actions';
      ['ack', 'start', 'complete'].forEach(function (action) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'pf-btn pf-btn-small';
        b.textContent = action === 'ack' ? '確認' : action === 'start' ? '開始' : '完成';
        b.addEventListener('click', function (ev) {
          ev.stopPropagation();
          leaseAction(lease.leaseId, action);
        });
        actions.appendChild(b);
      });
      rowCells(tr, [
        code(lease.leaseId),
        code((lease.workOrderId || '')),
        lease.operation || '—',
        lease.status || '—',
        code((lease.stationId || '')),
        actions
      ]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(lease, '租約');
      });
      tb.appendChild(tr);
    });
  }

  function renderExceptions(items) {
    clearTable('pf-exc-table');
    var tb = $('pf-exc-table').tBodies[0];
    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 4;
      td.className = 'pf-empty';
      td.textContent = '沒有未處理異常。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (ex) {
      var tr = document.createElement('tr');
      tr.dataset.json = JSON.stringify(ex);
      rowCells(tr, [
        code((ex.exceptionId || ex.id || '—')),
        ex.kind || ex.code || '—',
        ex.message || ex.summary || '—',
        ex.createdAt || ex.at || '—'
      ]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(ex, '異常');
      });
      tb.appendChild(tr);
    });
  }

  function selectRow(tr) {
    document.querySelectorAll('.pf-table tbody tr.pf-row-on').forEach(function (r) { r.classList.remove('pf-row-on'); });
    tr.classList.add('pf-row-on');
  }

  function setStatus(id, text, isError) {
    var el = $(id);
    if (!el) return;
    el.textContent = text;
    el.style.color = isError ? 'var(--danger)' : '';
  }

  function loadOperator() {
    setStatus('pf-operator-status', '載入中…');
    setStatus('pf-station-status', '載入中…');
    setStatus('pf-lease-status', '載入中…');
  return api('/api/pilot/operator')
      .then(function (res) {
        if (!res.ok) {
          setStatus('pf-operator-status', '載入失敗（HTTP ' + res.status + '）', true);
          setStatus('pf-station-status', '—');
          setStatus('pf-lease-status', '—');
          showDetail(res, '作業員視圖錯誤');
          return;
        }
        state.operator = res.body;
        saveTenant();
        updateBanner(res.body);
        var journal = (res.body.journal || {}).ok ? '日誌驗證通過' : '日誌：' + JSON.stringify(res.body.journal || {});
        setStatus('pf-operator-status', '租戶 ' + res.body.tenantId + '；' + journal + badgePartial('條碼', res.body.barcodeHardware));
        renderWorkOrders(res.body.workOrdersWaiting || []);
        renderLots(res.body.materialLots || []);
        var stations = (res.body.console && res.body.console.stations) || [];
        setStatus('pf-station-status', stations.length + ' 個工作站');
        renderStations(stations);
        setStatus('pf-lease-status', (res.body.stationLeases || []).length + ' 筆租約');
        renderLeases(res.body.stationLeases || []);
      })
      .catch(function (e) {
        setStatus('pf-operator-status', '載入失敗：' + e, true);
      });
  }

  function loadExceptions() {
    setStatus('pf-exc-status', '載入中…');
    return api('/api/pilot/exceptions')
      .then(function (res) {
        if (!res.ok) {
          setStatus('pf-exc-status', '載入失敗（HTTP ' + res.status + '）', true);
          return;
        }
        var items = res.body.items || [];
        setStatus('pf-exc-status', items.length + ' 筆異常');
        renderExceptions(items);
      })
      .catch(function (e) { setStatus('pf-exc-status', '載入失敗：' + e, true); });
  }

  function bindConfirmBlocks(root) {
    (root || document).querySelectorAll('.pf-confirm').forEach(function (block) {
      var box = block.querySelector('.pf-confirm-box');
      var btn = block.querySelector('button[type="submit"], button.pf-btn-primary');
      if (!box || !btn) return;
      box.addEventListener('change', function () { btn.disabled = !box.checked; });
    });
  }

  function heartbeatStation(stationId) {
    var wrap = document.createElement('div');
    wrap.className = 'pf-confirm';
    wrap.innerHTML = '<label><input type="checkbox" class="pf-confirm-box"> 我確認要更新心跳</label><button type="button" class="pf-btn pf-btn-primary" disabled>送出</button>';
    showDetail({ stationId: stationId, step: '請在詳細面板勾選確認後送出' }, '心跳確認');
    var panel = $('pf-detail').parentNode;
    var old = panel.querySelector('.pf-inline-confirm');
    if (old) old.remove();
    wrap.className += ' pf-inline-confirm';
    panel.appendChild(wrap);
    bindConfirmBlocks(wrap);
    wrap.querySelector('button').addEventListener('click', function () {
      var actor = 'floor-admin';
      api('/api/pilot/stations/' + encodeURIComponent(stationId) + '/heartbeat', {
        method: 'POST',
        body: JSON.stringify({ actor: actor })
      }).then(function (res) {
        showDetail(res, '心跳 API 回應');
        wrap.remove();
        if (res.ok) loadOperator();
      });
    });
  }

  function leaseAction(leaseId, action) {
    var labels = { ack: '確認收到派工', start: '開始作業', complete: '完成工序' };
    var wrap = document.createElement('div');
    wrap.className = 'pf-confirm pf-inline-confirm';
    wrap.innerHTML = '<p class="pf-muted">' + esc(labels[action]) + '（租約 ' + esc(leaseId) + '）</p>' +
      '<label><input type="checkbox" class="pf-confirm-box"> 我確認要執行</label>' +
      '<button type="button" class="pf-btn pf-btn-primary" disabled>送出</button>';
    showDetail({ leaseId: leaseId, action: action }, '租約動作');
    var panel = $('pf-detail').parentNode;
    var old = panel.querySelector('.pf-inline-confirm');
    if (old) old.remove();
    panel.appendChild(wrap);
    bindConfirmBlocks(wrap);
    wrap.querySelector('button').addEventListener('click', function () {
      var path = '/api/pilot/leases/' + encodeURIComponent(leaseId) + '/' + action;
      var body = { actor: 'floor-admin' };
      if (action === 'complete') body.confirm = true;
      api(path, { method: 'POST', body: JSON.stringify(body) }).then(function (res) {
        showDetail(res, '租約 ' + action);
        wrap.remove();
        if (res.ok) loadOperator();
      });
    });
  }

  function onTabClick(ev) {
    var btn = ev.target;
    if (!btn.dataset.panel) return;
    document.querySelectorAll('.pf-tabs button').forEach(function (b) {
      b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
    });
    document.querySelectorAll('.pf-panel').forEach(function (p) {
      var on = p.id === 'panel-' + btn.dataset.panel;
      p.hidden = !on;
      p.classList.toggle('pf-hidden', !on);
    });
    if (btn.dataset.panel === 'exceptions') loadExceptions();
  }

  function wireForms() {
    var sf = $('pf-station-form');
    if (sf) {
      sf.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var fd = new FormData(sf);
        var payload = {
          capabilities: [fd.get('capability')],
          status: fd.get('status'),
          actor: fd.get('actor') || 'floor-admin'
        };
        var sid = (fd.get('stationId') || '').toString().trim();
        if (sid) payload.stationId = sid;
        api('/api/pilot/stations', { method: 'POST', body: JSON.stringify(payload) }).then(function (res) {
          showDetail(res, '註冊工作站');
          if (res.ok) {
            sf.reset();
            sf.querySelector('.pf-confirm-box').checked = false;
            sf.querySelector('button[type="submit"]').disabled = true;
            loadOperator();
          }
        });
      });
    }
    var df = $('pf-dispatch-form');
    if (df) {
      df.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var fd = new FormData(df);
        var payload = {
          workOrderId: fd.get('workOrderId'),
          operation: fd.get('operation'),
          stationId: fd.get('stationId'),
          actor: fd.get('actor') || 'floor-admin'
        };
        api('/api/pilot/dispatch', { method: 'POST', body: JSON.stringify(payload) }).then(function (res) {
          showDetail(res, '派工');
          if (res.ok) loadOperator();
        });
      });
    }
    var sc = $('pf-scan-form');
    if (sc) {
      sc.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var token = new FormData(sc).get('token');
        api('/api/pilot/scan', { method: 'POST', body: JSON.stringify({ token: token }) }).then(function (res) {
          showDetail(res, '掃碼');
        });
      });
    }
    var tf = $('pf-token-form');
    if (tf) {
      tf.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var fd = new FormData(tf);
        var kind = fd.get('kind');
        var objectId = fd.get('objectId');
        api('/api/pilot/scan-token/' + encodeURIComponent(kind) + '/' + encodeURIComponent(objectId))
          .then(function (res) {
            showDetail(res, '產生掃碼權杖');
            if (res.ok && res.body && res.body.token && sc) sc.token.value = res.body.token;
          });
      });
    }
  }

  function init() {
    loadTenant();
    bindConfirmBlocks(document);
    document.querySelectorAll('.pf-tabs button').forEach(function (b) { b.addEventListener('click', onTabClick); });
    $('pf-tenant').addEventListener('change', function () { saveTenant(); loadOperator(); loadExceptions(); });
    $('pf-refresh').addEventListener('click', function () { loadOperator(); loadExceptions(); });
    wireForms();
    loadOperator();
    loadExceptions();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
