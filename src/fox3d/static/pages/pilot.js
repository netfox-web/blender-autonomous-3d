(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); }, selected = null, pending = null, exported = null;
  try { $('tenant').value = localStorage.getItem('fox3d.tenant') || 'sonaqueen-home'; } catch (e) { /* storage unavailable */ }
  function tenant() { return $('tenant').value.trim() || 'sonaqueen-home'; }
  function api(path, options) {
    options = options || {}; options.headers = { 'X-Tenant-Id': tenant(), 'Content-Type': 'application/json', Accept: 'application/json' };
    return fetch(path, options).then(function (r) { return r.text().then(function (s) { var data; try { data = JSON.parse(s); } catch (e) { data = { message: '無法讀取回覆' }; } if (!r.ok) throw new Error('HTTP ' + r.status + '：' + JSON.stringify(data)); return data; }); });
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
  function refresh() {
    pending = null; $('confirmation').hidden = true; selected = null; $('detail').textContent = '請選擇工單。'; $('actions').hidden = true;
    load('overview', '/api/pilot/console', function (d) { var badges = Object.keys(d.badges || {}).map(function (k) { return [BADGE_NAMES[k] || k, d.badges[k]]; }); cards('overview', [['材料批號', (d.lots || []).length + ' 批'], ['放行紀錄', (d.releases || []).length + ' 筆'], ['機台連線控制', d.liveMachineControl ? '已開啟' : '關閉（人工）']].concat(badges), d); table('lots', d.lots, [['lotId','批號'],['material','材料'],['available','可用'],['reserved','已預留'],['quarantined','隔離'],['truthLabel','來源']]); table('receipts', d.receipts, [['receiptId','收料編號'],['material','材料'],['quantity','數量'],['status','狀態'],['truthLabel','來源']]); table('requests', d.purchaseRequests, [['requestId','請購編號'],['material','材料'],['quantity','數量'],['status','狀態']]); });
    load('orders', '/api/pilot/work-orders', function (d) { table('orders', d.items, [['workOrderId','工單編號'],['state','狀態'],['quantity','數量'],['truthLabel','資料來源']], function (item) { selected = item; show('detail', item); $('actions').hidden = false; }); });
    load('batches', '/api/pilot/batches', function (d) { table('batches', d.items, [['batchId','批次編號'],['state','狀態'],['candidateId','候選編號'],['truthLabel','資料來源']], function (item) { show('batch-detail', item); }); });
    load('board', '/api/pilot/batches/board', function (d) { $('board').textContent = ''; var p = document.createElement('p'); p.textContent = '整體判定：' + d.decision + '；實體批次驗證：' + (d.physicalPilotBatchValidated ? '是' : '否'); $('board').appendChild(p); var rows = document.createElement('div'); rows.id = 'board-rows'; $('board').appendChild(rows); table('board-rows', d.rows, [['batchId','批次編號'],['decision','判定']], function (item) { show('batch-detail', item); }); });
    load('health', '/api/pilot/health', function (d) { var j = d.journalIntegrity || {}; cards('health', [['待人工處理', d.queuedManualOperations], ['進行中的站點租約', d.activeStationLeases], ['逾時租約', d.expiredStationLeases], ['預留短缺', d.reservationShortageCount], ['放行被拒（過期）', d.staleReleaseRejects], ['品檢 通過／不合格／重工', [d.qcPass, d.qcFail, d.qcRework].map(function (x) { return x == null ? '—' : x; }).join(' / ')], ['包裝異常', d.packingExceptions], ['作業日誌完整性', (j.ok ? '正常' : '異常') + (j.status ? '（' + j.status + '）' : '')]], d); });
  }
  function prepare(label, path, body) { pending = {path:path, body:body}; $('confirm-text').textContent = '請確認要' + label + '。'; show('confirm-data', body); $('confirmation').hidden = false; $('confirmation').scrollIntoView(); }
  document.querySelectorAll('[data-action]').forEach(function (b) { b.addEventListener('click', function () { if (!selected) return; var action = b.dataset.action; prepare(b.textContent + '（工單 ' + selected.workOrderId + '）', '/api/pilot/work-orders/' + encodeURIComponent(selected.workOrderId) + '/' + action, {confirm:true}); }); });
  $('confirm').addEventListener('click', function () { if (!pending) return; var task = pending; pending = null; $('confirmation').hidden = true; $('result').textContent = '處理中…'; api(task.path, {method:'POST', body:JSON.stringify(task.body)}).then(function (d) { show('result', d); refresh(); }).catch(function (e) { $('result').textContent = '操作失敗：' + e.message; }); });
  $('cancel').addEventListener('click', function () { pending = null; $('confirmation').hidden = true; });
  function form(id, path, label, build) { $(id).addEventListener('submit', function (e) { e.preventDefault(); try { prepare(label, path, build(new FormData(e.target))); } catch (err) { $('result').textContent = '資料格式錯誤：' + err.message; } }); }
  form('receipt','/api/pilot/receipts','收料',function (f) { return {material:f.get('material'), quantity:Number(f.get('quantity')), thickness:Number(f.get('thickness')), supplierLot:f.get('supplierLot'), source:'MANUAL'}; });
  form('purchase','/api/pilot/purchase-requests','建立請購草稿',function (f) { return {material:f.get('material'), quantity:Number(f.get('quantity'))}; });
  form('import','/api/pilot/import','匯入資料',function (f) { var rows = JSON.parse(f.get('rows')); if (!Array.isArray(rows)) throw new Error('資料列必須是陣列'); return {schemaVersion:f.get('schemaVersion'), rows:rows, source:'IMPORTED'}; });
  $('export').addEventListener('click', function () { $('export-result').textContent = '載入中…'; exported = null; $('download').hidden = true; var hash = $('release').value.trim(); api('/api/pilot/export' + (hash ? '?releaseHash=' + encodeURIComponent(hash) : '')).then(function (d) { exported = d; $('download').hidden = false; show('export-result', d); }).catch(function (e) { $('export-result').textContent = '匯出失敗：' + e.message; }); });
  $('download').addEventListener('click', function () { if (!exported) return; var url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], {type:'application/json'})), link = document.createElement('a'); link.href = url; link.download = 'pilot-export.json'; link.click(); URL.revokeObjectURL(url); });
  $('refresh').addEventListener('click', refresh); $('tenant').addEventListener('change', function () { try { localStorage.setItem('fox3d.tenant', tenant()); } catch (e) { /* storage unavailable */ } refresh(); }); refresh();
}());
