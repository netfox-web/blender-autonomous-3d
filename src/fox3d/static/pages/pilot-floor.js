// /admin/pilot-floor — operator view, stations, dispatch, scan, exceptions.
(function () {
  'use strict';
  var TENANT_KEY = 'fox3d.tenant';
  var DEFAULT_TENANT = 'sonaqueen-home';
  var state = { operator: null };
  // Tenant every API call goes to. Set at page load and when 重新載入 is pressed;
  // editing the header field alone never changes where writes go.
  var activeTenant = DEFAULT_TENANT;
  // Confirm controllers for the station / dispatch / scan forms.
  var formConfirms = {};

  function $(id) { return document.getElementById(id); }

  function fieldTenant() {
    var v = ($('pf-tenant') && $('pf-tenant').value || '').trim();
    return v || DEFAULT_TENANT;
  }

  function tenant() {
    return activeTenant;
  }

  function saveTenant() {
    try { localStorage.setItem(TENANT_KEY, activeTenant); } catch (e) { /* ignore */ }
  }

  function loadTenant() {
    try {
      var v = localStorage.getItem(TENANT_KEY);
      if (v && $('pf-tenant')) $('pf-tenant').value = v;
    } catch (e) { /* ignore */ }
  }

  function updateTenantHint() {
    var hint = $('pf-tenant-hint');
    if (!hint) return;
    var pending = fieldTenant() !== activeTenant;
    hint.hidden = !pending;
    hint.textContent = pending ? '按重新載入後才會切換租戶（目前仍是 ' + activeTenant + '）' : '';
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
    var headers = Object.assign({ 'X-Tenant-Id': opts.tenant || tenant(), Accept: 'application/json' }, opts.headers || {});
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
        prefillDispatch(function (f) {
          f.elements.namedItem('workOrderId').value = wo.workOrderId == null ? '' : String(wo.workOrderId);
          if ((wo.openOps || []).length) f.elements.namedItem('operation').value = String(wo.openOps[0]);
        });
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
        prefillDispatch(function (f) {
          f.elements.namedItem('stationId').value = st.stationId == null ? '' : String(st.stationId);
        });
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

  // Visible notice for every action (heartbeat, lease, register, dispatch, scan, token).
  function notify(text, isError) {
    setStatus('pf-action-status', text, isError);
  }

  function errorText(res) {
    var b = res && res.body;
    var detail = '';
    if (b && typeof b === 'object') detail = b.detail != null ? b.detail : (b.error != null ? b.error : b.message);
    else if (typeof b === 'string') detail = b;
    if (detail != null && typeof detail !== 'string') detail = JSON.stringify(detail);
    detail = String(detail || '').slice(0, 200);
    return 'HTTP ' + (res ? res.status : '?') + (detail ? '：' + detail : '');
  }

  // Runs one API action: disables the triggering controls while in flight, re-enables them
  // afterwards, and always leaves a visible success / failure notice (network errors included).
  function runAction(opts) {
    var busy = (opts.disable || []).filter(Boolean);
    busy.forEach(function (el) { el.disabled = true; });
    notify(opts.label + '：送出中…');
    var p;
    try { p = Promise.resolve(opts.request()); } catch (e) { p = Promise.reject(e); }
    return p.then(function (res) { return { res: res }; }, function (err) { return { err: err }; })
      .then(function (r) {
        busy.forEach(function (el) { el.disabled = false; });
        if (r.err) {
          var msg = (r.err && r.err.message) || String(r.err);
          notify(opts.label + '失敗：網路錯誤（' + msg + '），請確認連線後再試。', true);
          showDetail(String(msg), opts.label + ' 網路錯誤');
          return null;
        }
        showDetail(r.res, opts.label + ' API 回應');
        if (!r.res.ok) {
          notify(opts.label + '失敗（' + errorText(r.res) + '）', true);
          return r.res;
        }
        notify(opts.label + '：完成（HTTP ' + r.res.status + '）');
        if (opts.onOk) opts.onOk(r.res);
        return r.res;
      });
  }

  function loadOperator() {
    var t = activeTenant;
    setStatus('pf-operator-status', '載入中…');
    setStatus('pf-station-status', '載入中…');
    setStatus('pf-lease-status', '載入中…');
    return api('/api/pilot/operator', { tenant: t })
      .then(function (res) {
        if (t !== activeTenant) return; // tenant switched while loading; newer load wins
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
        if (t !== activeTenant) return;
        setStatus('pf-operator-status', '載入失敗：' + e, true);
      });
  }

  function loadExceptions() {
    var t = activeTenant;
    setStatus('pf-exc-status', '載入中…');
    return api('/api/pilot/exceptions', { tenant: t })
      .then(function (res) {
        if (t !== activeTenant) return;
        if (!res.ok) {
          setStatus('pf-exc-status', '載入失敗（HTTP ' + res.status + '）', true);
          return;
        }
        var items = (res.body && res.body.items) || [];
        setStatus('pf-exc-status', items.length + ' 筆異常');
        renderExceptions(items);
      })
      .catch(function (e) {
        if (t !== activeTenant) return;
        setStatus('pf-exc-status', '載入失敗：' + e, true);
      });
  }

  function describePayload(payload) {
    return Object.keys(payload).map(function (k) {
      var v = payload[k];
      if (v && typeof v === 'object' && !Array.isArray(v)) v = JSON.stringify(v);
      return k + '=' + (Array.isArray(v) ? v.join(',') : String(v == null ? '' : v));
    }).join('，');
  }

  // Send = confirmed. Ticking the confirm box snapshots the payload (and the tenant),
  // locks the form inputs, and shows the snapshot next to the box; unticking unlocks.
  // Submitting sends exactly the snapshot, never a re-read of the form.
  function makeConfirm(block, opts) {
    var box = block.querySelector('.pf-confirm-box');
    var btn = block.querySelector('button[type="submit"], button.pf-btn-primary');
    if (!box || !btn) return null;
    var summary = block.querySelector('.pf-confirm-summary');
    if (!summary) {
      summary = document.createElement('p');
      summary.className = 'pf-confirm-summary';
      block.appendChild(summary);
    }
    var form = opts.form || null;
    var ctl = { snapshot: null, box: box, btn: btn };

    function lockInputs(on) {
      if (!form) return;
      form.querySelectorAll('input, select, textarea').forEach(function (el) {
        if (el !== box) el.disabled = on;
      });
    }

    ctl.clear = function () {
      ctl.snapshot = null;
      box.checked = false;
      box.disabled = false;
      lockInputs(false);
      btn.disabled = true;
      summary.textContent = '';
      summary.hidden = true;
    };
    ctl.isLocked = function () { return !!ctl.snapshot; };

    box.addEventListener('change', function () {
      if (!box.checked) { ctl.clear(); return; }
      if (form && !form.checkValidity()) {
        box.checked = false;
        form.reportValidity();
        return;
      }
      var payload = opts.build();
      if (!payload) { box.checked = false; return; }
      ctl.snapshot = { tenant: activeTenant, payload: payload };
      lockInputs(true);
      summary.textContent = '將送出（租戶 ' + ctl.snapshot.tenant + '）：' + describePayload(payload);
      summary.hidden = false;
      btn.disabled = false;
    });

    ctl.clear();
    return ctl;
  }

  function trimmed(fd, name) {
    return (fd.get(name) || '').toString().trim();
  }

  function removeInlineConfirm() {
    document.querySelectorAll('.pf-inline-confirm').forEach(function (el) { el.remove(); });
  }

  function clearPendingConfirms() {
    Object.keys(formConfirms).forEach(function (k) { if (formConfirms[k]) formConfirms[k].clear(); });
    removeInlineConfirm();
  }

  // Row clicks only prefill the dispatch form while it is not confirmed (locked).
  function prefillDispatch(apply) {
    var f = $('pf-dispatch-form');
    if (!f) return;
    var ctl = formConfirms.dispatch;
    if (ctl && ctl.isLocked()) {
      notify('派工表單已勾選確認並鎖定，未帶入點選的資料；要修改請先取消勾選。');
      return;
    }
    apply(f);
  }

  // Inline confirm in the detail panel (heartbeat / lease actions), built without innerHTML.
  function inlineConfirm(title, confirmText, build, send) {
    removeInlineConfirm();
    var wrap = document.createElement('div');
    wrap.className = 'pf-confirm pf-inline-confirm';
    if (title) {
      var p = document.createElement('p');
      p.className = 'pf-muted';
      p.textContent = title;
      wrap.appendChild(p);
    }
    var label = document.createElement('label');
    var box = document.createElement('input');
    box.type = 'checkbox';
    box.className = 'pf-confirm-box';
    label.appendChild(box);
    label.appendChild(document.createTextNode(' ' + confirmText));
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pf-btn pf-btn-primary';
    btn.textContent = '送出';
    btn.disabled = true;
    wrap.appendChild(label);
    wrap.appendChild(btn);
    $('pf-detail').parentNode.appendChild(wrap);
    var ctl = makeConfirm(wrap, { build: build });
    btn.addEventListener('click', function () {
      if (!ctl.snapshot) return;
      send(ctl.snapshot, ctl, wrap);
    });
  }

  function heartbeatStation(stationId) {
    showDetail({ stationId: stationId, step: '請在詳細面板勾選確認後送出' }, '心跳確認');
    inlineConfirm('', '我確認要更新心跳', function () {
      return { stationId: stationId, actor: 'floor-admin' };
    }, function (snap, ctl, wrap) {
      runAction({
        label: '心跳',
        disable: [ctl.btn, ctl.box],
        request: function () {
          return api('/api/pilot/stations/' + encodeURIComponent(snap.payload.stationId) + '/heartbeat', {
            method: 'POST',
            tenant: snap.tenant,
            body: JSON.stringify({ actor: snap.payload.actor })
          });
        },
        onOk: function () { wrap.remove(); loadOperator(); }
      });
    });
  }

  function leaseAction(leaseId, action) {
    var labels = { ack: '確認收到派工', start: '開始作業', complete: '完成工序' };
    showDetail({ leaseId: leaseId, action: action }, '租約動作');
    inlineConfirm(labels[action] + '（租約 ' + leaseId + '）', '我確認要執行', function () {
      var body = { actor: 'floor-admin' };
      if (action === 'complete') body.confirm = true;
      return { leaseId: leaseId, action: action, body: body };
    }, function (snap, ctl, wrap) {
      runAction({
        label: '租約' + labels[action],
        disable: [ctl.btn, ctl.box],
        request: function () {
          var path = '/api/pilot/leases/' + encodeURIComponent(snap.payload.leaseId) + '/' + snap.payload.action;
          return api(path, { method: 'POST', tenant: snap.tenant, body: JSON.stringify(snap.payload.body) });
        },
        onOk: function () { wrap.remove(); loadOperator(); }
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

  function wireConfirmForm(key, form, label, build, path, onOk) {
    var ctl = makeConfirm(form.querySelector('.pf-confirm'), { form: form, build: build });
    formConfirms[key] = ctl;
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (!ctl || !ctl.snapshot) return; // only a confirmed snapshot is ever sent
      var snap = ctl.snapshot;
      runAction({
        label: label,
        disable: [ctl.btn, ctl.box],
        request: function () {
          return api(path, { method: 'POST', tenant: snap.tenant, body: JSON.stringify(snap.payload) });
        },
        onOk: function (res) { onOk(ctl, res); }
      });
    });
  }

  function wireForms() {
    var sf = $('pf-station-form');
    if (sf) {
      wireConfirmForm('station', sf, '註冊工作站', function () {
        var fd = new FormData(sf);
        var payload = {
          capabilities: [trimmed(fd, 'capability')],
          status: trimmed(fd, 'status'),
          actor: trimmed(fd, 'actor') || 'floor-admin'
        };
        var sid = trimmed(fd, 'stationId');
        if (sid) payload.stationId = sid;
        return payload;
      }, '/api/pilot/stations', function (ctl) {
        ctl.clear();
        sf.reset();
        loadOperator();
      });
    }
    var df = $('pf-dispatch-form');
    if (df) {
      wireConfirmForm('dispatch', df, '派工', function () {
        var fd = new FormData(df);
        return {
          workOrderId: trimmed(fd, 'workOrderId'),
          operation: trimmed(fd, 'operation'),
          stationId: trimmed(fd, 'stationId'),
          actor: trimmed(fd, 'actor') || 'floor-admin'
        };
      }, '/api/pilot/dispatch', function (ctl) {
        ctl.clear();
        df.reset();
        loadOperator();
      });
    }
    var sc = $('pf-scan-form');
    if (sc) {
      wireConfirmForm('scan', sc, '掃碼', function () {
        return { token: trimmed(new FormData(sc), 'token') };
      }, '/api/pilot/scan', function (ctl) {
        ctl.clear();
      });
    }
    var tf = $('pf-token-form');
    if (tf) {
      tf.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var fd = new FormData(tf);
        var kind = trimmed(fd, 'kind');
        var objectId = trimmed(fd, 'objectId');
        runAction({
          label: '產生掃碼權杖',
          disable: [tf.querySelector('button[type="submit"]')],
          request: function () {
            return api('/api/pilot/scan-token/' + encodeURIComponent(kind) + '/' + encodeURIComponent(objectId));
          },
          onOk: function (res) {
            if (!(res.body && res.body.token && sc)) return;
            if (formConfirms.scan && formConfirms.scan.isLocked()) {
              notify('產生掃碼權杖：完成；掃碼表單已勾選確認並鎖定，未帶入新權杖。');
              return;
            }
            sc.elements.namedItem('token').value = String(res.body.token);
          }
        });
      });
    }
  }

  function reloadAll() {
    activeTenant = fieldTenant();
    clearPendingConfirms();
    updateTenantHint();
    saveTenant();
    loadOperator();
    loadExceptions();
  }

  function init() {
    loadTenant();
    activeTenant = fieldTenant();
    updateTenantHint();
    document.querySelectorAll('.pf-tabs button').forEach(function (b) { b.addEventListener('click', onTabClick); });
    $('pf-tenant').addEventListener('input', updateTenantHint);
    $('pf-tenant').addEventListener('change', updateTenantHint);
    $('pf-refresh').addEventListener('click', reloadAll);
    wireForms();
    loadOperator();
    loadExceptions();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
