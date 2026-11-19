// /admin/pilot-shipping — pallets, shipment drafts, carrier quotes, carton labels, manual handoff.
(function () {
  'use strict';
  var TENANT_KEY = 'fox3d.tenant';
  var DEFAULT_TENANT = 'sonaqueen-home';
  var activeTenant = DEFAULT_TENANT;
  var actionInFlight = false;
  var loadSeq = 0;
  var formConfirms = {};
  var state = {
    cartons: [],
    selectedCartons: [],
    pallets: [],
    shipments: [],
    shipTotal: 0,
    shipOffset: 0,
    shipLimit: 10,
    shipStatus: '',
    quotes: []
  };

  function $(id) { return document.getElementById(id); }

  function fieldTenant() {
    var v = ($('ps-tenant') && $('ps-tenant').value || '').trim();
    return v || DEFAULT_TENANT;
  }

  function tenant() {
    return activeTenant;
  }

  function saveTenant() {
    try { localStorage.setItem(TENANT_KEY, activeTenant); } catch (e) { /* storage blocked */ }
  }

  function loadTenant() {
    try {
      var v = localStorage.getItem(TENANT_KEY);
      if (v && $('ps-tenant')) $('ps-tenant').value = v;
    } catch (e) { /* storage blocked */ }
  }

  function updateTenantHint() {
    var hint = $('ps-tenant-hint');
    if (!hint) return;
    var pending = fieldTenant() !== activeTenant;
    hint.hidden = !pending;
    hint.textContent = pending ? '按重新載入後才會切換租戶（目前仍是 ' + activeTenant + '）' : '';
  }

  function showDetail(obj, title) {
    var pre = $('ps-detail');
    var hint = $('ps-detail-hint');
    if (!pre) return;
    if (hint) hint.hidden = true;
    var text = typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
    pre.textContent = (title ? title + '\n\n' : '') + text;
  }

  function setStatus(id, text, isError) {
    var el = $(id);
    if (!el) return;
    el.textContent = text;
    el.style.color = isError ? 'var(--danger)' : '';
  }

  function setResult(id, text, level) {
    var el = $(id);
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = '';
      el.className = 'ps-result';
      return;
    }
    el.hidden = false;
    el.textContent = text;
    el.className = 'ps-result' + (level ? ' ' + level : '');
  }

  function notify(text, isError) {
    setStatus('ps-action-status', text, isError);
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

  function code(v) {
    var c = document.createElement('code');
    c.textContent = v == null ? '' : String(v);
    return c;
  }

  function makeTag(text, kind) {
    var span = document.createElement('span');
    span.className = 'ps-tag' + (kind ? ' ' + kind : '');
    span.textContent = text == null ? '' : String(text);
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

  function selectRow(tr) {
    document.querySelectorAll('.ps-table tbody tr.ps-row-on').forEach(function (r) { r.classList.remove('ps-row-on'); });
    tr.classList.add('ps-row-on');
  }

  function parseCartonIds(text) {
    return String(text || '')
      .split(/[\s,，;；]+/)
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function syncSelectedCartonsToForms() {
    var joined = state.selectedCartons.join(', ');
    if (!joined) return;
    if (!formConfirms.pallet || !formConfirms.pallet.isLocked()) {
      if ($('ps-pallet-carton-ids')) $('ps-pallet-carton-ids').value = joined;
    }
    if (!formConfirms.shipment || !formConfirms.shipment.isLocked()) {
      if ($('ps-ship-carton-ids')) $('ps-ship-carton-ids').value = joined;
    }
  }

  function renderCartons(items) {
    clearTable('ps-cartons-table');
    var tb = $('ps-cartons-table').tBodies[0];
    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 5;
      td.className = 'ps-empty';
      td.textContent = '目前尚無紙箱資料，也可直接在下方欄位輸入紙箱編號。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (c) {
      var tr = document.createElement('tr');
      var chk = document.createElement('input');
      chk.type = 'checkbox';
      chk.className = 'ps-carton-check';
      chk.value = String(c.cartonId || '');
      chk.checked = state.selectedCartons.indexOf(String(c.cartonId || '')) !== -1;
      chk.setAttribute('aria-label', '選取紙箱 ' + String(c.cartonId || ''));
      chk.addEventListener('click', function (ev) { ev.stopPropagation(); });
      chk.addEventListener('change', function () {
        var cid = String(c.cartonId || '');
        var idx = state.selectedCartons.indexOf(cid);
        if (chk.checked && idx === -1) state.selectedCartons.push(cid);
        if (!chk.checked && idx !== -1) state.selectedCartons.splice(idx, 1);
        syncSelectedCartonsToForms();
      });

      var d = c.measured || c.expected || {};
      var dimsText = (d.length || '?') + '×' + (d.width || '?') + '×' + (d.height || '?') + ' mm / ' + (d.weightKg || '?') + ' kg';
      var dimSpan = document.createElement('span');
      dimSpan.textContent = dimsText + ' ';
      dimSpan.appendChild(makeTag(c.measured ? 'MEASURED' : 'EXPECTED', c.mismatch ? 'warn' : 'mock'));

      var labelBtn = document.createElement('button');
      labelBtn.type = 'button';
      labelBtn.className = 'ps-btn ps-btn-small ps-label-trigger';
      labelBtn.textContent = '查標籤';
      labelBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        if ($('ps-label-carton-id')) $('ps-label-carton-id').value = String(c.cartonId || '');
        fetchCartonLabel(String(c.cartonId || ''), labelBtn);
      });

      var woBatch = (c.workOrderId || '—') + (c.batchId ? ' / ' + c.batchId : '');
      rowCells(tr, [chk, code(c.cartonId), woBatch, dimSpan, labelBtn]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(c, '紙箱明細');
      });
      tb.appendChild(tr);
    });
  }

  function renderPallets(items) {
    clearTable('ps-pallets-table');
    var tb = $('ps-pallets-table').tBodies[0];
    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 5;
      td.className = 'ps-empty';
      td.textContent = '尚無棧板規劃。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (pal) {
      var tr = document.createElement('tr');
      var cids = pal.cartonIds || [];
      var stWrap = document.createElement('span');
      var isHold = pal.status === 'NEEDS_HUMAN' || pal.oversize;
      stWrap.appendChild(makeTag(isHold ? 'NEEDS_HUMAN（超規待確認）' : 'PLANNING（規劃試算）', isHold ? 'warn' : 'mock'));

      var useBtn = document.createElement('button');
      useBtn.type = 'button';
      useBtn.className = 'ps-btn ps-btn-small';
      useBtn.textContent = '帶入出貨草稿';
      useBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        if (formConfirms.shipment && formConfirms.shipment.isLocked()) {
          notify('出貨草稿表單已勾選確認並鎖定，請先取消勾選再帶入。', true);
          return;
        }
        if ($('ps-ship-carton-ids')) $('ps-ship-carton-ids').value = cids.join(', ');
        notify('已將棧板 ' + pal.palletPlanId + ' 的紙箱帶入出貨草稿表單。');
      });

      rowCells(tr, [
        code(pal.palletPlanId),
        String(pal.palletCount != null ? pal.palletCount : (pal.pallets || []).length),
        String(cids.length) + (pal.heldCartonIds && pal.heldCartonIds.length ? '（超規保留 ' + pal.heldCartonIds.length + '）' : ''),
        stWrap,
        useBtn
      ]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(pal, '棧板規劃');
      });
      tb.appendChild(tr);
    });
  }

  function renderQuoteBadge(q) {
    if (!q) return makeTag('尚未綁定報價', '');
    var isStale = !!(q.stale || q.quoteStale || q.status === 'QUOTE_STALE' || q.usable === false);
    if (isStale) {
      return makeTag('報價過期（quote_stale，不可用）', 'warn');
    }
    return makeTag('參考報價（' + (q.source || 'MANUAL') + '，未連線物流商）', 'mock');
  }

  function renderShipments(items) {
    clearTable('ps-shipments-table');
    var tb = $('ps-shipments-table').tBodies[0];
    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 9;
      td.className = 'ps-empty';
      td.textContent = '尚無符合條件的出貨單。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (sh) {
      var tr = document.createElement('tr');
      var stTag = sh.status === 'HANDED_OFF_MANUAL'
        ? makeTag('HANDED_OFF_MANUAL（人工交運）', 'mock')
        : makeTag('SHIPMENT_DRAFT（出貨草稿）', 'warn');

      var quoteCell = document.createElement('span');
      if (sh.quote) {
        quoteCell.appendChild(renderQuoteBadge(sh.quote));
      } else if (sh.quoteStale) {
        quoteCell.appendChild(makeTag('報價過期（quote_stale，不可用）', 'warn'));
      } else {
        quoteCell.appendChild(makeTag(sh.quoteStatusLabel || '尚未綁定報價', ''));
      }

      var trackingText = (sh.handoff && sh.handoff.tracking) ? sh.handoff.tracking : '—';
      var actions = document.createElement('div');
      actions.className = 'ps-row-actions';

      var detailBtn = document.createElement('button');
      detailBtn.type = 'button';
      detailBtn.className = 'ps-btn ps-btn-small';
      detailBtn.textContent = '明細';
      detailBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        fetchShipmentDetail(String(sh.shipmentId || ''), detailBtn);
      });
      actions.appendChild(detailBtn);

      var handoffBtn = document.createElement('button');
      handoffBtn.type = 'button';
      handoffBtn.className = 'ps-btn ps-btn-small ps-prefill-handoff';
      handoffBtn.textContent = '帶入交運';
      handoffBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        if (formConfirms.handoff && formConfirms.handoff.isLocked()) {
          notify('人工交運表單已勾選確認並鎖定，請先取消勾選再帶入。', true);
          return;
        }
        if ($('ps-handoff-shipment-id')) $('ps-handoff-shipment-id').value = String(sh.shipmentId || '');
        notify('已帶入出貨單 ' + sh.shipmentId + ' 至人工交運表單。');
      });
      actions.appendChild(handoffBtn);

      rowCells(tr, [
        code(sh.shipmentId),
        (sh.origin || '—') + ' → ' + (sh.destination || '—'),
        sh.service || 'ground',
        String(sh.pieces != null ? sh.pieces : (sh.cartonIds || []).length),
        stTag,
        quoteCell,
        trackingText === '—' ? '—' : code(trackingText),
        sh.createdAt || '—',
        actions
      ]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(sh, '出貨單');
      });
      tb.appendChild(tr);
    });
  }

  function updateShipmentPager() {
    var total = state.shipTotal;
    var limit = state.shipLimit;
    var offset = state.shipOffset;
    var page = Math.floor(offset / limit) + 1;
    var maxPage = Math.max(1, Math.ceil(total / limit));
    if ($('ps-ship-page-info')) {
      $('ps-ship-page-info').textContent = '第 ' + page + ' / ' + maxPage + ' 頁（共 ' + total + ' 筆）';
    }
    if ($('ps-ship-prev')) $('ps-ship-prev').disabled = actionInFlight || offset <= 0;
    if ($('ps-ship-next')) $('ps-ship-next').disabled = actionInFlight || (offset + limit >= total);
  }

  function renderQuotes(items) {
    clearTable('ps-quotes-table');
    var tb = $('ps-quotes-table').tBodies[0];
    var sel = $('ps-ship-quote-id');
    if (sel && (!formConfirms.shipment || !formConfirms.shipment.isLocked())) {
      var prevVal = sel.value;
      sel.textContent = '';
      var opt0 = document.createElement('option');
      opt0.value = '';
      opt0.textContent = '不指定（自動比對現有報價）';
      sel.appendChild(opt0);
      (items || []).forEach(function (q) {
        var opt = document.createElement('option');
        opt.value = String(q.quoteId || '');
        var isStale = !!(q.stale || q.quoteStale);
        opt.textContent = (q.carrier || 'carrier') + ' · ' + (q.service || 'ground') + ' · ' + (q.charge != null ? q.charge : 0) + ' ' + (q.currency || 'TWD') + (isStale ? '（報價已過期不可用）' : '（僅供參考）');
        sel.appendChild(opt);
      });
      sel.value = prevVal;
    }

    if (!items || !items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 8;
      td.className = 'ps-empty';
      td.textContent = '尚未匯入運費報價。';
      tr.appendChild(td);
      tb.appendChild(tr);
      return;
    }
    items.forEach(function (q) {
      var tr = document.createElement('tr');
      var srcTag = makeTag(q.source || 'MANUAL', 'mock');
      var stTag = renderQuoteBadge(q);
      rowCells(tr, [
        code(q.quoteId),
        q.carrier || '—',
        q.service || 'ground',
        String(q.charge != null ? q.charge : 0) + ' ' + (q.currency || 'TWD'),
        String(q.dimDivisor != null ? q.dimDivisor : 6000),
        q.validUntil || '9999-12-31',
        srcTag,
        stTag
      ]);
      tr.addEventListener('click', function () {
        selectRow(tr);
        showDetail(q, '運費報價');
      });
      tb.appendChild(tr);
    });
  }

  function renderLabelPayload(label) {
    var box = $('ps-label-result');
    if (!box) return;
    box.textContent = '';
    if (!label) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    var head = document.createElement('div');
    var title = document.createElement('strong');
    title.textContent = '紙箱標籤內容 ';
    head.appendChild(title);
    var bLabel = (label.barcode && label.barcode.label) || label.truthLabel || 'PARTIAL';
    head.appendChild(makeTag('條碼／列印狀態：' + bLabel + '（未連接實體印表機）', 'warn'));
    box.appendChild(head);

    var dl = document.createElement('dl');
    var pairs = [
      ['紙箱編號', label.cartonId || '—'],
      ['批次／序號', ((label.text && label.text.batchId) || '—') + ' / #' + ((label.text && label.text.index != null) ? label.text.index : '0')],
      ['條碼制式', (label.barcode && label.barcode.symbology) || 'CODE128'],
      ['條碼內容', (label.barcode && label.barcode.payload) || '—'],
      ['QR 內容', (label.qr && label.qr.payload) || '—'],
      ['印表機路徑', label.printerPath || '未設定（PARTIAL）']
    ];
    pairs.forEach(function (pair) {
      var dt = document.createElement('dt');
      dt.textContent = pair[0];
      var dd = document.createElement('dd');
      dd.textContent = String(pair[1]);
      dl.appendChild(dt);
      dl.appendChild(dd);
    });
    box.appendChild(dl);
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

  function responseFailed(res) {
    if (!res || !res.ok) return true;
    var b = res.body;
    if (!b || typeof b !== 'object') return false;
    var st = String(b.status != null ? b.status : b.state != null ? b.state : '').toUpperCase();
    return st === 'BLOCKED' || st === 'REJECTED' || st === 'FAILED' || st === 'SUBMISSION_UNKNOWN';
  }

  function restoreFormConfirmStates() {
    Object.keys(formConfirms).forEach(function (k) {
      var ctl = formConfirms[k];
      if (!ctl) return;
      if (ctl.snapshot) {
        ctl.box.disabled = false;
        ctl.btn.disabled = false;
      } else {
        ctl.box.disabled = false;
        ctl.btn.disabled = true;
      }
    });
  }

  function lockPeerActions(busy) {
    var skip = (busy || []).filter(Boolean);
    function isBusy(el) { return skip.indexOf(el) !== -1; }
    Object.keys(formConfirms).forEach(function (k) {
      var ctl = formConfirms[k];
      if (!ctl) return;
      if (!isBusy(ctl.btn)) ctl.btn.disabled = true;
      if (!isBusy(ctl.box)) ctl.box.disabled = true;
    });
    ['ps-refresh', 'ps-ship-prev', 'ps-ship-next', 'ps-quote-check-btn', 'ps-label-submit'].forEach(function (id) {
      var el = $(id);
      if (el && !isBusy(el)) el.disabled = true;
    });
    document.querySelectorAll('.ps-table button').forEach(function (b) {
      if (!isBusy(b)) b.disabled = true;
    });
  }

  function unlockPeerActions() {
    ['ps-refresh', 'ps-quote-check-btn', 'ps-label-submit'].forEach(function (id) {
      var el = $(id);
      if (el) el.disabled = false;
    });
    document.querySelectorAll('.ps-table button').forEach(function (b) {
      b.disabled = false;
    });
    restoreFormConfirmStates();
    updateShipmentPager();
  }

  function runAction(opts) {
    if (actionInFlight) {
      notify('上一個操作仍在送出中，請稍候再試。', true);
      return Promise.resolve(null);
    }
    actionInFlight = true;
    var busy = (opts.disable || []).filter(Boolean);
    busy.forEach(function (el) { el.disabled = true; });
    lockPeerActions(busy);
    notify(opts.label + '：送出中…');
    var p;
    try { p = Promise.resolve(opts.request()); } catch (e) { p = Promise.reject(e); }
    return p.then(function (res) { return { res: res }; }, function (err) { return { err: err }; })
      .then(function (r) {
        actionInFlight = false;
        busy.forEach(function (el) { el.disabled = false; });
        unlockPeerActions();
        if (r.err) {
          var msg = (r.err && r.err.message) || String(r.err);
          var netMsg = opts.label + '失敗：連線失敗／網路錯誤（' + msg + '），請確認網路後重試。';
          notify(netMsg, true);
          if (opts.resultId) setResult(opts.resultId, netMsg, 'error');
          showDetail(String(msg), opts.label + ' 網路錯誤');
          if (opts.onFail) opts.onFail();
          return null;
        }
        showDetail(r.res, opts.label + ' API 回應');
        if (responseFailed(r.res)) {
          var errMsg = opts.label + '失敗（' + errorText(r.res) + '）';
          notify(errMsg, true);
          if (opts.resultId) setResult(opts.resultId, errMsg, 'error');
          if (opts.onFail) opts.onFail(r.res);
          return r.res;
        }
        notify(opts.label + '：完成（HTTP ' + r.res.status + '）');
        if (opts.onOk) opts.onOk(r.res);
        return r.res;
      });
  }

  function describePayload(payload) {
    return Object.keys(payload).map(function (k) {
      var v = payload[k];
      if (v && typeof v === 'object' && !Array.isArray(v)) v = JSON.stringify(v);
      return k + '=' + (Array.isArray(v) ? v.join(',') : String(v == null ? '' : v));
    }).join('，');
  }

  function makeConfirm(block, opts) {
    if (!block) return null;
    var box = block.querySelector('.ps-confirm-box');
    var btn = block.querySelector('button[type="submit"], button.ps-btn-primary');
    if (!box || !btn) return null;
    var summary = block.querySelector('.ps-confirm-summary');
    if (!summary) {
      summary = document.createElement('p');
      summary.className = 'ps-confirm-summary';
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
      var built = opts.build();
      if (!built || !built.payload) {
        box.checked = false;
        return;
      }
      ctl.snapshot = {
        tenant: activeTenant,
        path: built.path,
        payload: built.payload
      };
      lockInputs(true);
      summary.textContent = '將送出（租戶 ' + ctl.snapshot.tenant + '）：' + describePayload(built.payload);
      summary.hidden = false;
      btn.disabled = false;
    });

    ctl.clear();
    return ctl;
  }

  function wireConfirmForm(key, form, label, resultId, build, onOk) {
    if (!form) return;
    var ctl = makeConfirm(form.querySelector('.ps-confirm'), { form: form, build: build });
    formConfirms[key] = ctl;
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (!ctl || !ctl.snapshot) return;
      if (actionInFlight) {
        notify('上一個操作仍在送出中，請稍候再試。', true);
        return;
      }
      var snap = ctl.snapshot;
      runAction({
        label: label,
        resultId: resultId,
        disable: [ctl.btn, ctl.box],
        request: function () {
          return api(snap.path, {
            method: 'POST',
            tenant: snap.tenant,
            body: JSON.stringify(snap.payload)
          });
        },
        onOk: function (res) { onOk(ctl, res, snap); },
        onFail: function () { ctl.clear(); }
      });
    });
  }

  function loadCartons(seq, t) {
    setStatus('ps-cartons-status', '載入中…');
    return api('/api/pilot/cartons', { tenant: t })
      .then(function (res) {
        if (seq !== loadSeq || t !== activeTenant) return;
        if (!res.ok) {
          setStatus('ps-cartons-status', '紙箱載入失敗（' + errorText(res) + '）', true);
          renderCartons([]);
          return;
        }
        var items = (res.body && res.body.items) || [];
        state.cartons = items;
        setStatus('ps-cartons-status', items.length ? ('共 ' + items.length + ' 個紙箱') : '尚無紙箱');
        renderCartons(items);
      })
      .catch(function (err) {
        if (seq !== loadSeq || t !== activeTenant) return;
        setStatus('ps-cartons-status', '紙箱載入失敗：' + err, true);
        renderCartons([]);
      });
  }

  function loadPallets(seq, t) {
    setStatus('ps-pallets-status', '載入中…');
    return api('/api/pilot/pallets', { tenant: t })
      .then(function (res) {
        if (seq !== loadSeq || t !== activeTenant) return;
        if (!res.ok) {
          setStatus('ps-pallets-status', '棧板規劃載入失敗（' + errorText(res) + '）', true);
          renderPallets([]);
          return;
        }
        var items = (res.body && res.body.items) || [];
        state.pallets = items;
        setStatus('ps-pallets-status', items.length ? ('共 ' + items.length + ' 筆棧板規劃') : '尚無棧板規劃');
        renderPallets(items);
      })
      .catch(function (err) {
        if (seq !== loadSeq || t !== activeTenant) return;
        setStatus('ps-pallets-status', '棧板規劃載入失敗：' + err, true);
        renderPallets([]);
      });
  }

  function loadShipments(seq, t) {
    setStatus('ps-shipments-status', '載入中…');
    var qs = '?offset=' + encodeURIComponent(state.shipOffset) + '&limit=' + encodeURIComponent(state.shipLimit);
    if (state.shipStatus) qs += '&status=' + encodeURIComponent(state.shipStatus);
    return api('/api/pilot/shipments' + qs, { tenant: t })
      .then(function (res) {
        if (seq !== loadSeq || t !== activeTenant) return;
        if (!res.ok) {
          setStatus('ps-shipments-status', '出貨單載入失敗（' + errorText(res) + '）', true);
          renderShipments([]);
          return;
        }
        var b = res.body || {};
        var items = b.items || [];
        state.shipments = items;
        state.shipTotal = b.total != null ? b.total : items.length;
        setStatus(
          'ps-shipments-status',
          state.shipTotal ? ('共 ' + state.shipTotal + ' 筆出貨單（目前顯示 ' + items.length + ' 筆）') : '尚無出貨單'
        );
        renderShipments(items);
        updateShipmentPager();
      })
      .catch(function (err) {
        if (seq !== loadSeq || t !== activeTenant) return;
        setStatus('ps-shipments-status', '出貨單載入失敗：' + err, true);
        renderShipments([]);
      });
  }

  function loadQuotes(seq, t) {
    setStatus('ps-quotes-status', '載入中…');
    var chkSvc = ($('ps-quote-check-service') && $('ps-quote-check-service').value || '').trim();
    var chkDiv = ($('ps-quote-check-divisor') && $('ps-quote-check-divisor').value || '').trim();
    var params = [];
    if (chkSvc) params.push('service=' + encodeURIComponent(chkSvc));
    if (chkDiv && Number(chkDiv) > 0) params.push('dimDivisor=' + encodeURIComponent(chkDiv));
    var qs = params.length ? ('?' + params.join('&')) : '';
    return api('/api/pilot/carrier-quotes' + qs, { tenant: t })
      .then(function (res) {
        if (seq !== loadSeq || t !== activeTenant) return;
        if (!res.ok) {
          setStatus('ps-quotes-status', '運費報價載入失敗（' + errorText(res) + '）', true);
          renderQuotes([]);
          return;
        }
        var b = res.body || {};
        var items = b.items || [];
        state.quotes = items;
        var staleCount = items.filter(function (q) { return q.stale || q.quoteStale; }).length;
        var statusMsg = items.length
          ? ('共 ' + items.length + ' 筆報價' + (staleCount ? '（其中 ' + staleCount + ' 筆已過期 quote_stale 不可用）' : '（僅供試算參考）'))
          : '尚未匯入運費報價';
        setStatus('ps-quotes-status', statusMsg, staleCount > 0);
        renderQuotes(items);
      })
      .catch(function (err) {
        if (seq !== loadSeq || t !== activeTenant) return;
        setStatus('ps-quotes-status', '運費報價載入失敗：' + err, true);
        renderQuotes([]);
      });
  }

  function fetchShipmentDetail(shipmentId, btn) {
    if (!shipmentId) return;
    runAction({
      label: '查詢出貨單明細',
      disable: [btn],
      request: function () {
        return api('/api/pilot/shipments/' + encodeURIComponent(shipmentId));
      },
      onOk: function (res) {
        showDetail(res.body, '出貨單明細 ' + shipmentId);
      }
    });
  }

  function fetchCartonLabel(cartonId, btn) {
    if (!cartonId) return;
    runAction({
      label: '查詢紙箱標籤',
      disable: [btn],
      request: function () {
        return api('/api/pilot/cartons/' + encodeURIComponent(cartonId) + '/label');
      },
      onOk: function (res) {
        renderLabelPayload(res.body);
        showDetail(res.body, '紙箱標籤 ' + cartonId);
      },
      onFail: function () {
        renderLabelPayload(null);
      }
    });
  }

  function clearPendingConfirms() {
    Object.keys(formConfirms).forEach(function (k) {
      if (formConfirms[k]) formConfirms[k].clear();
    });
  }

  function reloadAll() {
    if (actionInFlight) {
      notify('上一個操作仍在送出中，請稍候再重新載入。', true);
      return Promise.resolve();
    }
    activeTenant = fieldTenant();
    clearPendingConfirms();
    updateTenantHint();
    saveTenant();
    loadSeq += 1;
    var seq = loadSeq;
    var t = activeTenant;
    return Promise.all([
      loadCartons(seq, t),
      loadPallets(seq, t),
      loadShipments(seq, t),
      loadQuotes(seq, t)
    ]);
  }

  function wireForms() {
    var pf = $('ps-pallet-form');
    wireConfirmForm('pallet', pf, '建立棧板規劃', 'ps-pallet-result', function () {
      var ids = parseCartonIds($('ps-pallet-carton-ids') && $('ps-pallet-carton-ids').value);
      if (!ids.length) {
        notify('請至少輸入或勾選一個紙箱編號。', true);
        return null;
      }
      return {
        path: '/api/pilot/pallets',
        payload: { cartonIds: ids }
      };
    }, function (ctl, res, snap) {
      ctl.clear();
      var b = res.body || {};
      var isHold = b.status === 'NEEDS_HUMAN' || b.oversize;
      var msg = '棧板規劃已建立：' + (b.palletPlanId || '') + '（棧板數 ' + (b.palletCount != null ? b.palletCount : 0) + '，狀態：' + (b.status || 'PLANNING') + (isHold ? ' — 超規需人工確認' : ' — 規劃試算未經物流商認證') + '）';
      setResult('ps-pallet-result', msg, isHold ? 'warn' : '');
      if (!formConfirms.shipment || !formConfirms.shipment.isLocked()) {
        if ($('ps-ship-carton-ids')) $('ps-ship-carton-ids').value = (snap.payload.cartonIds || []).join(', ');
      }
      loadPallets(loadSeq, activeTenant);
    });

    var sf = $('ps-shipment-form');
    wireConfirmForm('shipment', sf, '建立出貨草稿', 'ps-shipment-result', function () {
      var origin = ($('ps-ship-origin') && $('ps-ship-origin').value || '').trim();
      var destination = ($('ps-ship-destination') && $('ps-ship-destination').value || '').trim();
      var ids = parseCartonIds($('ps-ship-carton-ids') && $('ps-ship-carton-ids').value);
      var service = ($('ps-ship-service') && $('ps-ship-service').value || 'ground').trim();
      var divRaw = ($('ps-ship-divisor') && $('ps-ship-divisor').value || '').trim();
      var quoteId = ($('ps-ship-quote-id') && $('ps-ship-quote-id').value || '').trim();
      if (!origin || !destination || !ids.length) {
        notify('請填寫起運地、目的地與至少一個紙箱編號。', true);
        return null;
      }
      var payload = {
        origin: origin,
        destination: destination,
        cartonIds: ids,
        service: service
      };
      if (divRaw) payload.dimDivisor = Number(divRaw);
      if (quoteId) payload.quoteId = quoteId;
      return {
        path: '/api/pilot/shipments',
        payload: payload
      };
    }, function (ctl, res) {
      ctl.clear();
      var b = res.body || {};
      var quoteWarn = b.quoteStale ? '；注意：所選運費報價已過期（quote_stale，不可用）' : '';
      var msg = '出貨草稿已建立：' + (b.shipmentId || '') + '（狀態：' + (b.status || 'SHIPMENT_DRAFT') + '，箱數：' + (b.pieces || 0) + '，未向真實物流商下單' + quoteWarn + '）';
      setResult('ps-shipment-result', msg, b.quoteStale ? 'warn' : '');
      if (!formConfirms.handoff || !formConfirms.handoff.isLocked()) {
        if ($('ps-handoff-shipment-id') && b.shipmentId) {
          $('ps-handoff-shipment-id').value = String(b.shipmentId);
        }
      }
      state.shipOffset = 0;
      loadShipments(loadSeq, activeTenant);
    });

    var hf = $('ps-handoff-form');
    wireConfirmForm('handoff', hf, '人工交運', 'ps-handoff-result', function () {
      var sid = ($('ps-handoff-shipment-id') && $('ps-handoff-shipment-id').value || '').trim();
      var carrier = ($('ps-handoff-carrier') && $('ps-handoff-carrier').value || '').trim();
      var tracking = ($('ps-handoff-tracking') && $('ps-handoff-tracking').value || '').trim();
      var actor = ($('ps-handoff-actor') && $('ps-handoff-actor').value || '').trim() || 'shipping-ops';
      if (!sid || !carrier || !tracking) {
        notify('請填寫出貨單編號、物流商與追蹤碼。', true);
        return null;
      }
      return {
        path: '/api/pilot/shipments/' + encodeURIComponent(sid) + '/handoff',
        payload: {
          carrier: carrier,
          tracking: tracking,
          actor: actor
        }
      };
    }, function (ctl, res) {
      ctl.clear();
      var b = res.body || {};
      var ho = b.handoff || {};
      var msg = '人工交運已記錄：出貨單 ' + (b.shipmentId || '') + ' · 交運編號 ' + (ho.handoffId || '') + ' · 物流商 ' + (ho.carrier || '') + ' · 追蹤碼 ' + (ho.tracking || '') + '（狀態：' + (b.status || 'HANDED_OFF_MANUAL') + '，非即時物流商連線）';
      setResult('ps-handoff-result', msg, '');
      loadShipments(loadSeq, activeTenant);
    });

    var qf = $('ps-quote-form');
    wireConfirmForm('quoteManual', qf, '匯入手動報價', null, function () {
      var carrier = ($('ps-quote-carrier') && $('ps-quote-carrier').value || '').trim();
      var service = ($('ps-quote-service') && $('ps-quote-service').value || 'ground').trim();
      var charge = Number($('ps-quote-charge') && $('ps-quote-charge').value);
      var currency = ($('ps-quote-currency') && $('ps-quote-currency').value || 'TWD').trim();
      var dimDivisor = Number($('ps-quote-divisor') && $('ps-quote-divisor').value || 6000);
      var validUntil = ($('ps-quote-valid-until') && $('ps-quote-valid-until').value || '9999-12-31').trim();
      return {
        path: '/api/pilot/carrier-quotes',
        payload: {
          carrier: carrier,
          service: service,
          charge: charge,
          currency: currency,
          dimDivisor: dimDivisor,
          validUntil: validUntil,
          source: 'MANUAL'
        }
      };
    }, function (ctl) {
      ctl.clear();
      loadQuotes(loadSeq, activeTenant);
      loadShipments(loadSeq, activeTenant);
    });

    var qff = $('ps-quote-file-form');
    var fileInput = $('ps-quote-file');
    if (fileInput) {
      fileInput.addEventListener('change', function () {
        var f = fileInput.files && fileInput.files[0];
        if (!f) return;
        if (f.name.toLowerCase().endsWith('.json') && $('ps-quote-format')) {
          $('ps-quote-format').value = 'json';
        } else if (f.name.toLowerCase().endsWith('.csv') && $('ps-quote-format')) {
          $('ps-quote-format').value = 'csv';
        }
        var reader = new FileReader();
        reader.onload = function () {
          if (formConfirms.quoteFile && formConfirms.quoteFile.isLocked()) return;
          if ($('ps-quote-content')) $('ps-quote-content').value = String(reader.result || '');
        };
        reader.readAsText(f);
      });
    }

    wireConfirmForm('quoteFile', qff, '匯入檔案報價', null, function () {
      var fmt = ($('ps-quote-format') && $('ps-quote-format').value || 'csv').trim();
      var content = ($('ps-quote-content') && $('ps-quote-content').value || '').trim();
      if (!content) {
        notify('請貼上或選擇 JSON／CSV 報價內容。', true);
        return null;
      }
      return {
        path: '/api/pilot/carrier-quotes',
        payload: {
          format: fmt,
          content: content,
          source: 'IMPORTED'
        }
      };
    }, function (ctl) {
      ctl.clear();
      loadQuotes(loadSeq, activeTenant);
      loadShipments(loadSeq, activeTenant);
    });

    var lf = $('ps-label-form');
    if (lf) {
      lf.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var cid = ($('ps-label-carton-id') && $('ps-label-carton-id').value || '').trim();
        if (!cid) return;
        fetchCartonLabel(cid, $('ps-label-submit'));
      });
    }
  }

  function wireFilters() {
    if ($('ps-ship-status-filter')) {
      $('ps-ship-status-filter').addEventListener('change', function () {
        state.shipStatus = ($('ps-ship-status-filter').value || '').trim();
        state.shipOffset = 0;
        loadShipments(loadSeq, activeTenant);
      });
    }
    if ($('ps-ship-limit')) {
      $('ps-ship-limit').addEventListener('change', function () {
        state.shipLimit = Number($('ps-ship-limit').value) || 10;
        state.shipOffset = 0;
        loadShipments(loadSeq, activeTenant);
      });
    }
    if ($('ps-ship-prev')) {
      $('ps-ship-prev').addEventListener('click', function () {
        if (state.shipOffset <= 0) return;
        state.shipOffset = Math.max(0, state.shipOffset - state.shipLimit);
        loadShipments(loadSeq, activeTenant);
      });
    }
    if ($('ps-ship-next')) {
      $('ps-ship-next').addEventListener('click', function () {
        if (state.shipOffset + state.shipLimit >= state.shipTotal) return;
        state.shipOffset += state.shipLimit;
        loadShipments(loadSeq, activeTenant);
      });
    }
    if ($('ps-quote-check-btn')) {
      $('ps-quote-check-btn').addEventListener('click', function () {
        loadQuotes(loadSeq, activeTenant);
      });
    }
    if ($('ps-quote-check-service')) {
      $('ps-quote-check-service').addEventListener('change', function () {
        loadQuotes(loadSeq, activeTenant);
      });
    }
  }

  function init() {
    loadTenant();
    activeTenant = fieldTenant();
    updateTenantHint();
    if ($('ps-tenant')) {
      $('ps-tenant').addEventListener('input', updateTenantHint);
      $('ps-tenant').addEventListener('change', updateTenantHint);
    }
    if ($('ps-refresh')) {
      $('ps-refresh').addEventListener('click', reloadAll);
    }
    wireForms();
    wireFilters();
    reloadAll();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
