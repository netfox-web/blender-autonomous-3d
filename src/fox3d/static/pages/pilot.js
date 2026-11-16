(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); }, selected = null, pending = null, exported = null, posting = false;
  try { $('tenant').value = localStorage.getItem('fox3d.tenant') || 'sonaqueen-home'; } catch (e) { /* storage unavailable */ }
  function tenant() { return $('tenant').value.trim() || 'sonaqueen-home'; }
  function api(path, options) {
    options = options || {};
    var tid = options.tenant || tenant();
    var opts = { method: options.method, body: options.body, headers: { 'X-Tenant-Id': tid, 'Content-Type': 'application/json', Accept: 'application/json' } };
    return fetch(path, opts).then(function (r) {
      return r.text().then(function (s) {
        var data; try { data = JSON.parse(s); } catch (e) { data = { message: '無法讀取回覆' }; }
        if (!r.ok) throw new Error('HTTP ' + r.status + '：' + JSON.stringify(data));
        return data;
      });
    }, function (e) { throw new Error('連線失敗，請稍後再試：' + ((e && e.message) || e)); });
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
      for (var j = 0; j < lists[i].length; j++) if (lists[i][j] && lists[i][j].veto === true) return true;
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
    return out.status === 'blocked' || tokenBad(out.status) || tokenBad(out.label) || tokenBad(out.truthLabel) || String(out.error || '').indexOf('BLOCKED_') === 0 || out.veto === true || checksHaveVeto(out) || Boolean(job && (job.status === 'blocked' || tokenBad(job.status) || tokenBad(job.label) || tokenBad(job.truthLabel) || String(job.error || '').indexOf('BLOCKED_') === 0));
  }
  function blockedMessage(label, out) {
    var code = (out && (out.error || out.status || out.label || out.truthLabel)) || '';
    if (out && (out.veto === true || checksHaveVeto(out))) return label + '：已阻擋（安全檢查未通過）';
    var up = String((out && (out.label || out.truthLabel || out.status)) || '').toUpperCase();
    if (up === 'FAILED' || up.indexOf('FAILED_') === 0) return label + '：失敗' + (code ? '（' + code + '）' : '');
    return label + '：已阻擋' + (code ? '（' + code + '）' : '');
  }
  function show(id, value) { $(id).textContent = JSON.stringify(value, null, 2); }
  function table(id, items, fields, onSelect) {
    var target = $(id); target.textContent = '';
    if (!items || !items.length) { target.textContent = '目前沒有資料。'; return; }
    var wrap = document.createElement('div'), t = document.createElement('table'), head = document.createElement('tr'); wrap.className = 'table';
    fields.forEach(function (f) { var th = document.createElement('th'); th.textContent = f[1]; head.appendChild(th); }); if (onSelect) { var th = document.createElement('th'); th.textContent = '明細'; head.appendChild(th); } t.appendChild(head);
    items.forEach(function (item) { var row = document.createElement('tr'); fields.forEach(function (f) { var td = document.createElement('td'), v = item[f[0]]; td.textContent = v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v); row.appendChild(td); }); if (onSelect) { var cell = document.createElement('td'), b = document.createElement('button'); b.textContent = '查看'; b.addEventListener('click', function () { onSelect(item); }); cell.appendChild(b); row.appendChild(cell); } t.appendChild(row); }); wrap.appendChild(t); target.appendChild(wrap);
  }
  function load(id, path, render) { $(id).textContent = '載入中…'; return api(path).then(render).catch(function (e) { $(id).textContent = '讀取失敗：' + e.message; }); }
  var BADGE_NAMES = {LIVE_CNC: 'CNC 連線', LIVE_LASER: '雷射連線', Vision: '視覺辨識', Demand: '需求預測', quotes: '報價資料', receipts: '收料資料', sandbox: '沙盒隔離'};
  // readable status cards; the raw API answer stays one click away for engineers
  function cards(id, rows, raw) {
    var box = $(id); box.textContent = '';
    var grid = document.createElement('div'); grid.className = 'cards';
    rows.forEach(function (r) {
      var c = document.createElement('div'); c.className = 'card';
      var v = r[1] == null ? '—' : String(r[1]);
      if (/^(BLOCKED|MOCK|PARTIAL)/.test(v)) c.classList.add('warn');
      var k = document.createElement('span'); k.textContent = r[0];
      var b = document.createElement('b'); b.textContent = v;
      c.appendChild(k); c.appendChild(b); grid.appendChild(c);
    });
    box.appendChild(grid);
    var det = document.createElement('details'); var sum = document.createElement('summary'); sum.textContent = '顯示原始資料';
    var pre = document.createElement('pre'); pre.textContent = JSON.stringify(raw, null, 2);
    det.appendChild(sum); det.appendChild(pre); box.appendChild(det);
  }
  function setLocked(nodes, on) {
    (nodes || []).forEach(function (el) {
      if (!el) return;
      if (on) {
        if (!el.hasAttribute('data-pilot-lock')) el.setAttribute('data-pilot-lock', el.disabled ? '1' : '0');
        el.disabled = true;
      } else if (el.hasAttribute('data-pilot-lock')) {
        el.disabled = el.getAttribute('data-pilot-lock') === '1';
        el.removeAttribute('data-pilot-lock');
      }
    });
  }
  function formFields(form) {
    var nodes = [];
    if (form) form.querySelectorAll('input, select, textarea').forEach(function (el) { nodes.push(el); });
    if ($('tenant') && nodes.indexOf($('tenant')) < 0) nodes.push($('tenant'));
    return nodes;
  }
  function clearPending() {
    if (pending && pending.fields) setLocked(pending.fields, false);
    pending = null;
    $('confirmation').hidden = true;
  }
  function refresh() {
    if (!posting) clearPending();
    selected = null; $('detail').textContent = '請選擇工單。'; $('actions').hidden = true;
    load('overview', '/api/pilot/console', function (d) { var badges = Object.keys(d.badges || {}).map(function (k) { return [BADGE_NAMES[k] || k, d.badges[k]]; }); cards('overview', [['材料批號', (d.lots || []).length + ' 批'], ['放行紀錄', (d.releases || []).length + ' 筆'], ['機台連線控制', d.liveMachineControl ? '已開啟' : '關閉（人工）']].concat(badges), d); table('lots', d.lots, [['lotId','批號'],['material','材料'],['available','可用'],['reserved','已預留'],['quarantined','隔離'],['truthLabel','來源']]); table('receipts', d.receipts, [['receiptId','收料編號'],['material','材料'],['quantity','數量'],['status','狀態'],['truthLabel','來源']]); table('requests', d.purchaseRequests, [['requestId','請購編號'],['material','材料'],['quantity','數量'],['status','狀態']]); });
    load('orders', '/api/pilot/work-orders', function (d) { table('orders', d.items, [['workOrderId','工單編號'],['state','狀態'],['quantity','數量'],['truthLabel','資料來源']], function (item) { selected = item; show('detail', item); $('actions').hidden = false; }); });
    load('batches', '/api/pilot/batches', function (d) { table('batches', d.items, [['batchId','批次編號'],['state','狀態'],['candidateId','候選編號'],['truthLabel','資料來源']], function (item) { show('batch-detail', item); }); });
    load('board', '/api/pilot/batches/board', function (d) { $('board').textContent = ''; var p = document.createElement('p'); p.textContent = '整體判定：' + d.decision + '；實體批次驗證：' + (d.physicalPilotBatchValidated ? '是' : '否'); $('board').appendChild(p); var rows = document.createElement('div'); rows.id = 'board-rows'; $('board').appendChild(rows); table('board-rows', d.rows, [['batchId','批次編號'],['decision','判定']], function (item) { show('batch-detail', item); }); });
    load('health', '/api/pilot/health', function (d) { var j = d.journalIntegrity || {}; cards('health', [['待人工處理', d.queuedManualOperations], ['進行中的站點租約', d.activeStationLeases], ['逾時租約', d.expiredStationLeases], ['預留短缺', d.reservationShortageCount], ['放行被拒（過期）', d.staleReleaseRejects], ['品檢 通過／不合格／重工', [d.qcPass, d.qcFail, d.qcRework].map(function (x) { return x == null ? '—' : x; }).join(' / ')], ['包裝異常', d.packingExceptions], ['作業日誌完整性', (j.ok ? '正常' : '異常') + (j.status ? '（' + j.status + '）' : '')]], d); });
  }
  function prepare(label, path, body, trigger) {
    if (posting || pending) return;
    var tid = tenant();
    var fields = formFields(trigger && trigger.form);
    pending = { path: path, body: body, tenant: tid, trigger: trigger, fields: fields };
    $('confirm-text').textContent = '請確認要' + label + '（租戶 ' + tid + '）。';
    show('confirm-data', { tenant: tid, body: body });
    setLocked(fields, true);
    $('confirmation').hidden = false;
    $('confirmation').scrollIntoView();
  }
  document.querySelectorAll('[data-action]').forEach(function (b) { b.addEventListener('click', function () { if (!selected || posting || pending) return; var action = b.dataset.action; var orderId = selected.workOrderId; prepare(b.textContent + '（工單 ' + orderId + '）', '/api/pilot/work-orders/' + encodeURIComponent(orderId) + '/' + action, {confirm:true}, b); }); });
  $('confirm').addEventListener('click', function () {
    if (!pending || posting) return;
    var task = pending;
    pending = null;
    setLocked(task.fields, false);
    $('confirmation').hidden = true;
    posting = true;
    $('confirm').disabled = true;
    if (task.trigger) task.trigger.disabled = true;
    $('result').textContent = '處理中…';
    var bodyText;
    try { bodyText = JSON.stringify(task.body); }
    catch (err) {
      posting = false;
      $('confirm').disabled = false;
      if (task.trigger) task.trigger.disabled = false;
      $('result').textContent = '操作失敗：' + ((err && err.message) || err);
      return;
    }
    api(task.path, { method: 'POST', body: bodyText, tenant: task.tenant }).then(function (d) {
      if (isBlockedResult(d)) { $('result').textContent = blockedMessage('操作', d) + '\n' + JSON.stringify(d, null, 2); return; }
      show('result', d);
      refresh();
    }).catch(function (e) {
      var msg = (e && e.message) || String(e);
      $('result').textContent = msg.indexOf('連線失敗') >= 0 ? msg : ('操作失敗：' + msg);
    }).finally(function () {
      posting = false;
      $('confirm').disabled = false;
      if (task.trigger) task.trigger.disabled = false;
    });
  });
  $('cancel').addEventListener('click', function () { if (posting) return; clearPending(); });
  function form(id, path, label, build) { $(id).addEventListener('submit', function (e) { e.preventDefault(); if (posting || pending) return; try { prepare(label, path, build(new FormData(e.target)), e.submitter || e.target.querySelector('button')); } catch (err) { $('result').textContent = '資料格式錯誤：' + err.message; } }); }
  form('receipt','/api/pilot/receipts','收料',function (f) { return {material:f.get('material'), quantity:Number(f.get('quantity')), thickness:Number(f.get('thickness')), supplierLot:f.get('supplierLot'), source:'MANUAL'}; });
  form('purchase','/api/pilot/purchase-requests','建立請購草稿',function (f) { return {material:f.get('material'), quantity:Number(f.get('quantity'))}; });
  form('import','/api/pilot/import','匯入資料',function (f) { var rows = JSON.parse(f.get('rows')); if (!Array.isArray(rows)) throw new Error('資料列必須是陣列'); return {schemaVersion:f.get('schemaVersion'), rows:rows, source:'IMPORTED'}; });
  $('export').addEventListener('click', function () { $('export-result').textContent = '載入中…'; exported = null; $('download').hidden = true; var hash = $('release').value.trim(); api('/api/pilot/export' + (hash ? '?releaseHash=' + encodeURIComponent(hash) : '')).then(function (d) { exported = d; $('download').hidden = false; show('export-result', d); }).catch(function (e) { $('export-result').textContent = '匯出失敗：' + e.message; }); });
  $('download').addEventListener('click', function () { if (!exported) return; var url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], {type:'application/json'})), link = document.createElement('a'); link.href = url; link.download = 'pilot-export.json'; link.click(); URL.revokeObjectURL(url); });
  $('refresh').addEventListener('click', refresh); $('tenant').addEventListener('change', function () { try { localStorage.setItem('fox3d.tenant', tenant()); } catch (e) { /* storage unavailable */ } refresh(); }); refresh();
}());
