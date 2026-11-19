(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); }, selected = null, pending = null, exported = null, posting = false, currentCartons = [], currentMismatchHold = null, loadedTenant = 'sonaqueen-home', refreshSeq = 0, cartonLoadSeq = 0, dirtyMeasureFields = {};
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
  function isMismatchResult(out) {
    if (!out || typeof out !== 'object') return false;
    // mismatchHold is the work-order gate; a carton mismatch already signed off is no longer pending.
    if (typeof out.mismatchHold === 'boolean') return out.mismatchHold;
    return out.mismatch === true;
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
  function actionButtons() {
    var nodes = [];
    document.querySelectorAll('#packing-panel button, #actions button, #refresh, form button').forEach(function (el) {
      if (nodes.indexOf(el) < 0) nodes.push(el);
    });
    return nodes;
  }
  function formFields(form, trigger) {
    var nodes = [];
    if (form) form.querySelectorAll('input, select, textarea').forEach(function (el) { nodes.push(el); });
    if (trigger && $('qc-panel') && $('qc-panel').contains(trigger)) {
      $('qc-panel').querySelectorAll('input, select, textarea, button').forEach(function (el) { if (nodes.indexOf(el) < 0) nodes.push(el); });
    }
    if (trigger && $('packing-panel') && $('packing-panel').contains(trigger)) {
      $('packing-panel').querySelectorAll('input, select, textarea').forEach(function (el) {
        if (nodes.indexOf(el) < 0) nodes.push(el);
      });
    }
    if ($('tenant') && nodes.indexOf($('tenant')) < 0) nodes.push($('tenant'));
    return nodes;
  }
  function clearPending() {
    if (pending && pending.fields) setLocked(pending.fields, false);
    pending = null;
    $('confirmation').hidden = true;
  }
  function resetMeasureDirty() {
    dirtyMeasureFields = {};
  }
  ['packing-length', 'packing-width', 'packing-height', 'packing-weight'].forEach(function (id) {
    if ($(id)) {
      $(id).addEventListener('input', function () { dirtyMeasureFields[id] = true; });
      $(id).addEventListener('change', function () { dirtyMeasureFields[id] = true; });
    }
  });
  function fmtDims(d) {
    if (!d || typeof d !== 'object') return '—';
    return String(d.length) + '×' + String(d.width) + '×' + String(d.height) + ' mm / ' + String(d.weightKg) + ' kg';
  }
  function fillMeasureInputs(carton, force) {
    if (!carton || pending || posting) return;
    var src = carton.measured || carton.expected || {};
    if (src.length != null && (force || !dirtyMeasureFields['packing-length'])) $('packing-length').value = String(src.length);
    if (src.width != null && (force || !dirtyMeasureFields['packing-width'])) $('packing-width').value = String(src.width);
    if (src.height != null && (force || !dirtyMeasureFields['packing-height'])) $('packing-height').value = String(src.height);
    if (src.weightKg != null && (force || !dirtyMeasureFields['packing-weight'])) $('packing-weight').value = String(src.weightKg);
  }
  function renderCartons(items, preserveStatus, mismatchHold) {
    currentCartons = Array.isArray(items) ? items : [];
    currentMismatchHold = typeof mismatchHold === 'boolean' ? mismatchHold : null;
    var signedOff = currentMismatchHold === false;
    var box = $('packing-cartons');
    var sel = $('packing-carton-id');
    var prevCid = sel ? sel.value : '';
    if (box) box.textContent = '';
    if (sel && !pending && !posting) sel.textContent = '';
    if (!currentCartons.length) {
      if (box) box.textContent = '尚無紙箱。';
      if (!preserveStatus && !pending && !posting && $('packing-status')) {
        $('packing-status').textContent = '尚無紙箱，請先建立紙箱。';
        $('packing-status').className = '';
      }
      return;
    }
    var wrap = document.createElement('div');
    wrap.className = 'table';
    var t = document.createElement('table');
    var head = document.createElement('tr');
    ['紙箱編號', '預期尺寸重量', '實測尺寸重量', '比對狀態', '操作'].forEach(function (label) {
      var th = document.createElement('th');
      th.textContent = label;
      head.appendChild(th);
    });
    t.appendChild(head);
    var anyMismatch = false;
    currentCartons.forEach(function (c) {
      if (c.mismatch) anyMismatch = true;
      if (sel && !pending && !posting) {
        var opt = document.createElement('option');
        opt.value = String(c.cartonId || '');
        opt.textContent = String(c.cartonId || '');
        sel.appendChild(opt);
      }
      var row = document.createElement('tr');
      var cells = [
        String(c.cartonId || ''),
        fmtDims(c.expected),
        c.measured ? fmtDims(c.measured) : '尚未量測',
        c.mismatch ? (signedOff ? '尺寸不符（已人工確認）' : '尺寸不符待人工確認') : (c.measured ? '正常' : '待量測')
      ];
      cells.forEach(function (val) {
        var td = document.createElement('td');
        td.textContent = val;
        row.appendChild(td);
      });
      var actTd = document.createElement('td');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = '選取回填';
      btn.addEventListener('click', function () {
        if (pending || posting) return;
        resetMeasureDirty();
        if (sel) sel.value = String(c.cartonId || '');
        fillMeasureInputs(c, true);
      });
      actTd.appendChild(btn);
      row.appendChild(actTd);
      t.appendChild(row);
    });
    wrap.appendChild(t);
    if (box) box.appendChild(wrap);
    if (sel && !pending && !posting) {
      var chosen = currentCartons[0];
      for (var i = 0; i < currentCartons.length; i++) {
        if (String(currentCartons[i].cartonId) === prevCid) {
          chosen = currentCartons[i];
          break;
        }
      }
      sel.value = String(chosen.cartonId || '');
      fillMeasureInputs(chosen, false);
    }
    if (anyMismatch && !signedOff && $('packing-status')) {
      $('packing-status').textContent = '尺寸不符待人工確認';
      $('packing-status').className = 'warn';
    } else if (!preserveStatus && !pending && !posting && $('packing-status')) {
      $('packing-status').textContent = '已建立 ' + currentCartons.length + ' 箱。';
      $('packing-status').className = '';
    }
  }
  function loadCartons(workOrderId, preserveStatus) {
    if (!workOrderId) return Promise.resolve();
    var seq = ++cartonLoadSeq;
    if (!preserveStatus && $('packing-status')) {
      $('packing-status').textContent = '載入紙箱中…';
      $('packing-status').className = '';
    }
    return api('/api/pilot/work-orders/' + encodeURIComponent(workOrderId) + '/cartons').then(function (d) {
      if (seq !== cartonLoadSeq || !selected || selected.workOrderId !== workOrderId) return;
      renderCartons(d.items || d.cartons || [], preserveStatus, d.mismatchHold);
    }).catch(function (e) {
      if (seq !== cartonLoadSeq || !selected || selected.workOrderId !== workOrderId) return;
      if ($('packing-status')) {
        $('packing-status').textContent = '紙箱讀取失敗：' + e.message;
        $('packing-status').className = 'warn';
      }
    });
  }
  function loadQc(orderId) {
    $('qc-status').textContent = '載入中…';
    api('/api/pilot/work-orders/' + encodeURIComponent(orderId) + '/qc').then(function (d) {
      if (!selected || selected.workOrderId !== orderId || pending || posting) return;
      var box = $('qc-checks'); box.textContent = '';
      $('qc-status').textContent = d.requiredFinalOk.ok ? '必要最終檢驗通過' : '必要最終檢驗尚未通過';
      (d.plan || []).forEach(function (spec) {
        var form = document.createElement('form'), lastSignature = '', retryKey = '';
        var label = document.createElement('label'); label.textContent = String(spec.checkId) + ' 實測值 ';
        var input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.required = true; label.appendChild(input); form.appendChild(label);
        var nominal = document.createElement('input'); nominal.type = 'number'; nominal.step = 'any'; nominal.required = true; nominal.placeholder = '標稱值';
        if (spec.nominal != null) { nominal.value = String(spec.nominal); nominal.disabled = true; }
        form.appendChild(nominal);
        var button = document.createElement('button'); button.type = 'submit'; button.textContent = '記錄檢驗'; form.appendChild(button); box.appendChild(form);
        form.addEventListener('submit', function (e) {
          e.preventDefault(); if (pending || posting || !selected) return;
          var signature = JSON.stringify([orderId, spec.checkId, input.value, nominal.value]);
          if (signature !== lastSignature || !retryKey) { retryKey = 'qc-' + Date.now() + '-' + Math.random().toString(36).slice(2); lastSignature = signature; }
          var body = {stage:'FINAL', checkId:spec.checkId, measured:Number(input.value), nominal:Number(nominal.value), source:'MANUAL', idempotencyKey:retryKey};
          prepare('記錄檢驗（工單 ' + orderId + '）', '/api/pilot/work-orders/' + encodeURIComponent(orderId) + '/qc', body, button, function () { retryKey = ''; });
        });
      });
    }).catch(function (e) { $('qc-status').textContent = '讀取失敗：' + e.message; });
  }
  if ($('qc-release')) {
    $('qc-release').addEventListener('click', function () {
      if (!selected || pending || posting) return;
      var id = selected.workOrderId;
      prepare('解除 QC_HOLD（工單 ' + id + '）', '/api/pilot/work-orders/' + encodeURIComponent(id) + '/qc/release-hold', {confirm:true}, $('qc-release'));
    });
  }
  function selectOrder(item, preserveStatus, skipLoadCartons) {
    if ((posting && !skipLoadCartons) || pending) return Promise.resolve();
    var prevId = selected && selected.workOrderId;
    selected = item;
    show('detail', item);
    $('actions').hidden = false;
    $('qc-panel').hidden = false;
    loadQc(item.workOrderId);
    if ($('packing-panel')) {
      $('packing-panel').hidden = false;
      if (prevId !== item.workOrderId) {
        resetMeasureDirty();
        currentCartons = [];
        currentMismatchHold = null;
        if ($('packing-cartons')) $('packing-cartons').textContent = '尚無紙箱。';
        if ($('packing-carton-id')) $('packing-carton-id').textContent = '';
        ['packing-length', 'packing-width', 'packing-height', 'packing-weight'].forEach(function (id) {
          if ($(id)) $(id).value = '';
        });
        if ($('packing-idem')) $('packing-idem').value = 'pack-' + String(item.workOrderId || '1');
        if ($('packing-checklist')) $('packing-checklist').textContent = '尚未產生裝箱檢查表。';
      }
      if (!skipLoadCartons) return loadCartons(item.workOrderId, preserveStatus);
    }
    return Promise.resolve();
  }
  function fetchOutcome(path, tid) {
    return api(path, { tenant: tid }).then(
      function (data) { return { ok: true, data: data }; },
      function (err) { return { ok: false, error: err }; }
    );
  }
  function applySection(id, outcome, render) {
    if (outcome.ok) render(outcome.data);
    else if ($(id)) $(id).textContent = '讀取失敗：' + outcome.error.message;
  }
  function refresh(keepOrderId, preserveStatus) {
    if (!posting) clearPending();
    var seq = ++refreshSeq;
    var cSeq = ++cartonLoadSeq;
    var reqTenant = tenant();
    loadedTenant = reqTenant;
    var targetOrderId = keepOrderId !== undefined ? keepOrderId : (selected && selected.workOrderId);
    if (!targetOrderId) {
      selected = null;
      $('detail').textContent = '請選擇工單。';
      $('actions').hidden = true;
      if ($('packing-panel')) $('packing-panel').hidden = true;
      if ($('qc-panel')) $('qc-panel').hidden = true;
    }
    var reqs = [
      fetchOutcome('/api/pilot/console', reqTenant),
      fetchOutcome('/api/pilot/work-orders', reqTenant),
      fetchOutcome('/api/pilot/batches', reqTenant),
      fetchOutcome('/api/pilot/batches/board', reqTenant),
      fetchOutcome('/api/pilot/health', reqTenant),
      targetOrderId ? fetchOutcome('/api/pilot/work-orders/' + encodeURIComponent(targetOrderId) + '/cartons', reqTenant) : Promise.resolve(null)
    ];
    return Promise.all(reqs).then(function (res) {
      if (seq !== refreshSeq) return;
      applySection('overview', res[0], function (d) {
        var badges = Object.keys(d.badges || {}).map(function (k) { return [BADGE_NAMES[k] || k, d.badges[k]]; });
        cards('overview', [['材料批號', (d.lots || []).length + ' 批'], ['放行紀錄', (d.releases || []).length + ' 筆'], ['機台連線控制', d.liveMachineControl ? '已開啟' : '關閉（人工）']].concat(badges), d);
        table('lots', d.lots, [['lotId','批號'],['material','材料'],['available','可用'],['reserved','已預留'],['quarantined','隔離'],['truthLabel','來源']]);
        table('receipts', d.receipts, [['receiptId','收料編號'],['material','材料'],['quantity','數量'],['status','狀態'],['truthLabel','來源']]);
        table('requests', d.purchaseRequests, [['requestId','請購編號'],['material','材料'],['quantity','數量'],['status','狀態']]);
      });
      applySection('orders', res[1], function (d) {
        var list = (d && d.items) || [];
        table('orders', list, [['workOrderId','工單編號'],['state','狀態'],['quantity','數量'],['truthLabel','資料來源']], function (item) { selectOrder(item, false); });
        var matched = null;
        if (targetOrderId) {
          for (var i = 0; i < list.length; i++) {
            if (list[i].workOrderId === targetOrderId) {
              matched = list[i];
              break;
            }
          }
        }
        if (matched) {
          selectOrder(matched, Boolean(preserveStatus), true);
        } else if (targetOrderId) {
          selected = null;
          $('detail').textContent = '請選擇工單。';
          $('actions').hidden = true;
          if ($('packing-panel')) $('packing-panel').hidden = true;
          if ($('qc-panel')) $('qc-panel').hidden = true;
        }
      });
      applySection('batches', res[2], function (d) {
        table('batches', d.items, [['batchId','批次編號'],['state','狀態'],['candidateId','候選編號'],['truthLabel','資料來源']], function (item) { show('batch-detail', item); });
      });
      applySection('board', res[3], function (d) {
        $('board').textContent = '';
        var p = document.createElement('p');
        p.textContent = '整體判定：' + d.decision + '；實體批次驗證：' + (d.physicalPilotBatchValidated ? '是' : '否');
        $('board').appendChild(p);
        var rows = document.createElement('div');
        rows.id = 'board-rows';
        $('board').appendChild(rows);
        table('board-rows', d.rows, [['batchId','批次編號'],['decision','判定']], function (item) { show('batch-detail', item); });
      });
      applySection('health', res[4], function (d) {
        var j = d.journalIntegrity || {};
        cards('health', [['待人工處理', d.queuedManualOperations], ['進行中的站點租約', d.activeStationLeases], ['逾時租約', d.expiredStationLeases], ['預留短缺', d.reservationShortageCount], ['放行被拒（過期）', d.staleReleaseRejects], ['品檢 通過／不合格／重工', [d.qcPass, d.qcFail, d.qcRework].map(function (x) { return x == null ? '—' : x; }).join(' / ')], ['包裝異常', d.packingExceptions], ['作業日誌完整性', (j.ok ? '正常' : '異常') + (j.status ? '（' + j.status + '）' : '')]], d);
      });
      if (res[5] && selected && selected.workOrderId === targetOrderId && cSeq === cartonLoadSeq) {
        if (res[5].ok) {
          renderCartons(res[5].data.items || res[5].data.cartons || [], Boolean(preserveStatus), res[5].data.mismatchHold);
        } else if ($('packing-status')) {
          $('packing-status').textContent = '紙箱讀取失敗：' + res[5].error.message;
          $('packing-status').className = 'warn';
        }
      }
    });
  }
  function prepare(label, path, body, trigger, onDone, isPacking) {
    if (posting || pending) return;
    var tid = tenant();
    var fields = formFields(trigger && trigger.form, trigger);
    pending = { path: path, body: body, tenant: tid, trigger: trigger, fields: fields, onDone: onDone, isPacking: Boolean(isPacking), workOrderId: selected && selected.workOrderId };
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
    var lockedBtns = actionButtons();
    setLocked(lockedBtns, true);
    $('confirm').disabled = true;
    if (task.trigger) task.trigger.disabled = true;
    if (task.isPacking) cartonLoadSeq++;
    $('result').textContent = '處理中…';
    var bodyText;
    try { bodyText = JSON.stringify(task.body); }
    catch (err) {
      posting = false;
      setLocked(lockedBtns, false);
      $('confirm').disabled = false;
      if (task.trigger) task.trigger.disabled = false;
      $('result').textContent = '操作失敗：' + ((err && err.message) || err);
      return;
    }
    function releaseControls() {
      posting = false;
      setLocked(lockedBtns, false);
      $('confirm').disabled = false;
      if (task.trigger) task.trigger.disabled = false;
    }
    api(task.path, { method: 'POST', body: bodyText, tenant: task.tenant }).then(function (d) {
      if (d && d.result === 'FAIL' && /\/qc$/.test(task.path)) {
        $('result').textContent = '品檢未通過或工單仍在 QC_HOLD';
        if ($('qc-status')) $('qc-status').textContent = '品檢未通過或工單仍在 QC_HOLD';
        return refresh(task.workOrderId, true).then(function () {
          releaseControls();
        });
      }
      if (isMismatchResult(d)) {
        return refresh(task.workOrderId, true).then(function () {
          releaseControls();
          if (task.isPacking) renderCartons(currentCartons, true, currentMismatchHold);
          if (typeof task.onDone === 'function') task.onDone(d);
          if ($('packing-status')) {
            $('packing-status').textContent = '尺寸不符待人工確認';
            $('packing-status').className = 'warn';
          }
          $('result').textContent = '尺寸不符待人工確認\n' + JSON.stringify(d, null, 2);
        });
      }
      if (isBlockedResult(d)) {
        releaseControls();
        if (typeof task.onDone === 'function') task.onDone(d);
        if (task.isPacking && $('packing-status')) {
          $('packing-status').textContent = blockedMessage('操作', d);
          $('packing-status').className = 'warn';
        }
        $('result').textContent = blockedMessage('操作', d) + '\n' + JSON.stringify(d, null, 2);
        return;
      }
      return refresh(task.workOrderId, Boolean(task.isPacking)).then(function () {
        releaseControls();
        if (task.isPacking) renderCartons(currentCartons, true, currentMismatchHold);
        if (typeof task.onDone === 'function') task.onDone(d);
        show('result', d);
      });
    }).catch(function (e) {
      releaseControls();
      var msg = (e && e.message) || String(e);
      var outMsg = msg.indexOf('連線失敗') >= 0 ? msg : ('操作失敗：' + msg);
      $('result').textContent = outMsg;
      if (task.trigger && $('qc-panel').contains(task.trigger)) $('qc-status').textContent = outMsg;
      if ((task.isPacking || ($('packing-panel') && !$('packing-panel').hidden)) && $('packing-status')) {
        $('packing-status').textContent = msg.indexOf('尺寸不符待人工確認') >= 0 ? ('尺寸不符待人工確認：' + outMsg) : outMsg;
        $('packing-status').className = 'warn';
      }
    }).finally(function () {
      posting = false;
      setLocked(lockedBtns, false);
      $('confirm').disabled = false;
      if (task.trigger) task.trigger.disabled = false;
    });
  });
  $('cancel').addEventListener('click', function () { if (posting) return; clearPending(); });
  function form(id, path, label, build) { $(id).addEventListener('submit', function (e) { e.preventDefault(); if (posting || pending) return; try { prepare(label, path, build(new FormData(e.target)), e.submitter || e.target.querySelector('button')); } catch (err) { $('result').textContent = '資料格式錯誤：' + err.message; } }); }
  form('receipt','/api/pilot/receipts','收料',function (f) { return {material:f.get('material'), quantity:Number(f.get('quantity')), thickness:Number(f.get('thickness')), supplierLot:f.get('supplierLot'), source:'MANUAL'}; });
  form('purchase','/api/pilot/purchase-requests','建立請購草稿',function (f) { return {material:f.get('material'), quantity:Number(f.get('quantity'))}; });
  form('import','/api/pilot/import','匯入資料',function (f) { var rows = JSON.parse(f.get('rows')); if (!Array.isArray(rows)) throw new Error('資料列必須是陣列'); return {schemaVersion:f.get('schemaVersion'), rows:rows, source:'IMPORTED'}; });
  if ($('packing-carton-id')) {
    $('packing-carton-id').addEventListener('change', function () {
      if (pending || posting) return;
      resetMeasureDirty();
      var cid = $('packing-carton-id').value;
      for (var i = 0; i < currentCartons.length; i++) {
        if (String(currentCartons[i].cartonId) === cid) {
          fillMeasureInputs(currentCartons[i], true);
          break;
        }
      }
    });
  }
  if ($('packing-create')) {
    $('packing-create').addEventListener('submit', function (e) {
      e.preventDefault();
      if (!selected || posting || pending) return;
      var f = new FormData(e.target);
      var qty = Number(f.get('quantity'));
      var idem = String(f.get('idempotencyKey') || '').trim();
      var orderId = selected.workOrderId;
      prepare(
        '建立紙箱（工單 ' + orderId + '）',
        '/api/pilot/work-orders/' + encodeURIComponent(orderId) + '/cartons',
        { quantity: qty, idempotencyKey: idem },
        e.submitter || $('packing-create-btn'),
        function (d) {
          resetMeasureDirty();
          renderCartons(d.items || d.cartons || currentCartons, true, typeof d.mismatchHold === 'boolean' ? d.mismatchHold : currentMismatchHold);
          if ($('packing-status')) {
            $('packing-status').textContent = '已建立 ' + String(d.quantity || (d.items || currentCartons).length) + ' 個紙箱並綁定工單。';
            $('packing-status').className = '';
          }
        },
        true
      );
    });
  }
  if ($('packing-measure')) {
    $('packing-measure').addEventListener('submit', function (e) {
      e.preventDefault();
      if (!selected || posting || pending) return;
      var f = new FormData(e.target);
      var cid = String(f.get('cartonId') || '').trim();
      if (!cid) {
        $('result').textContent = '資料格式錯誤：請先選擇紙箱';
        return;
      }
      var body = {
        length: Number(f.get('length')),
        width: Number(f.get('width')),
        height: Number(f.get('height')),
        weightKg: Number(f.get('weightKg'))
      };
      prepare(
        '回填實測值（紙箱 ' + cid + '）',
        '/api/pilot/cartons/' + encodeURIComponent(cid) + '/measured',
        body,
        e.submitter || $('packing-measure-btn'),
        function (d) {
          resetMeasureDirty();
          if (d && d.cartonId && currentCartons.length) {
            var next = currentCartons.map(function (c) { return String(c.cartonId) === String(d.cartonId) ? d : c; });
            renderCartons(next, true, typeof d.mismatchHold === 'boolean' ? d.mismatchHold : currentMismatchHold);
          }
          if (isMismatchResult(d)) {
            if ($('packing-status')) {
              $('packing-status').textContent = '尺寸不符待人工確認';
              $('packing-status').className = 'warn';
            }
          } else if ($('packing-status')) {
            $('packing-status').textContent = d && d.mismatch ? '實測尺寸重量已回填（尺寸不符已人工確認）。' : '實測尺寸重量已回填（符合預期）。';
            $('packing-status').className = '';
          }
        },
        true
      );
    });
  }
  if ($('packing-checklist-btn')) {
    $('packing-checklist-btn').addEventListener('click', function () {
      if (!selected || posting || pending) return;
      var orderId = selected.workOrderId;
      prepare(
        '產生裝箱檢查表（工單 ' + orderId + '）',
        '/api/pilot/work-orders/' + encodeURIComponent(orderId) + '/packing-checklist',
        {},
        $('packing-checklist-btn'),
        function (d) {
          if ($('packing-checklist')) show('packing-checklist', d);
          if (d && d.mismatchHold) {
            if ($('packing-status')) {
              $('packing-status').textContent = '尺寸不符待人工確認';
              $('packing-status').className = 'warn';
            }
          } else if ($('packing-status')) {
            $('packing-status').textContent = '裝箱檢查表已產生（無尺寸不符，物流商 ' + String((d && d.carrierProvider) || 'BLOCKED/NOT_CONNECTED') + '）。';
            $('packing-status').className = '';
          }
        },
        true
      );
    });
  }
  if ($('packing-resolve-btn')) {
    $('packing-resolve-btn').addEventListener('click', function () {
      if (!selected || posting || pending) return;
      var orderId = selected.workOrderId;
      prepare(
        '人工確認尺寸不符並解除裝箱 hold（工單 ' + orderId + '）',
        '/api/pilot/work-orders/' + encodeURIComponent(orderId) + '/packing-mismatch/resolve',
        { confirm: true },
        $('packing-resolve-btn'),
        function (d) {
          if (d && typeof d.mismatchHold === 'boolean' && currentCartons.length) {
            renderCartons(currentCartons, true, d.mismatchHold);
          }
          if (!$('packing-status')) return;
          if (d && d.mismatchHold === false) {
            $('packing-status').textContent = '尺寸不符已人工確認（紙箱仍標記超差），可進行完工。';
            $('packing-status').className = '';
          } else {
            $('packing-status').textContent = '尺寸不符待人工確認';
            $('packing-status').className = 'warn';
          }
        },
        true
      );
    });
  }
  $('export').addEventListener('click', function () { $('export-result').textContent = '載入中…'; exported = null; $('download').hidden = true; var hash = $('release').value.trim(); api('/api/pilot/export' + (hash ? '?releaseHash=' + encodeURIComponent(hash) : '')).then(function (d) { exported = d; $('download').hidden = false; show('export-result', d); }).catch(function (e) { $('export-result').textContent = '匯出失敗：' + e.message; }); });
  $('download').addEventListener('click', function () { if (!exported) return; var url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], {type:'application/json'})), link = document.createElement('a'); link.href = url; link.download = 'pilot-export.json'; link.click(); URL.revokeObjectURL(url); });
  $('refresh').addEventListener('click', function () { if (posting || pending) return; refresh(null, false); }); $('tenant').addEventListener('change', function () { if (posting || pending) return; var next = tenant(); try { localStorage.setItem('fox3d.tenant', next); } catch (e) { /* storage unavailable */ } if (next !== loadedTenant) refresh(null, false); }); refresh(null, false);
}());
