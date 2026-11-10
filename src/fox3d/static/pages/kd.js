// /admin/kd — KD catalog, readiness, structure generation.
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var DEFAULT_TENANT = 'sonaqueen-home';
  var ESTIMATE_SCOPE = 'CONFIG_ESTIMATE_ONLY';

  // The tenant every API call goes to. It is frozen at page load and only
  // changes when the user presses 重新載入概況; typing in #kd-tenant alone
  // does not redirect writes (a confirm opened for tenant A can never be
  // sent as tenant B).
  var activeTenant = DEFAULT_TENANT;
  // Callbacks that close and clear every open confirm panel (run on reload).
  var confirmResets = [];
  // Guards against an older overview response landing after a reload.
  var overviewSeq = 0;

  function fieldTenant() {
    var v = ($('kd-tenant').value || '').trim();
    return v || DEFAULT_TENANT;
  }

  function headers(json, tenantId) {
    var h = { 'X-Tenant-Id': tenantId || activeTenant, Accept: 'application/json' };
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function truthyLabel(label) {
    if (!label) return { text: '未知', cls: 'warn' };
    var u = String(label).toUpperCase();
    if (u === 'REAL' || u === 'TRUE') return { text: label, cls: 'ok' };
    if (u.indexOf('MOCK') >= 0 || u.indexOf('BLOCKED') >= 0 || u === 'PARTIAL') return { text: label, cls: 'mock' };
    if (u.indexOf('CONFIG') >= 0 || u.indexOf('ESTIMATE') >= 0) return { text: label, cls: 'warn' };
    return { text: label, cls: 'warn' };
  }

  function tagSpan(label) {
    var t = truthyLabel(label);
    return el('span', 'kd-tag ' + t.cls, t.text);
  }

  function showJson(pre, data, status) {
    pre.hidden = false;
    var head = status != null ? 'HTTP ' + status + '\n' : '';
    try {
      pre.textContent = head + JSON.stringify(data, null, 2);
    } catch (e) {
      pre.textContent = head + String(data);
    }
  }

  function truncateJson(obj, max) {
    var s = JSON.stringify(obj, null, 2);
    if (s.length <= max) return s;
    return s.slice(0, max) + '\n…（已截斷）';
  }

  function api(method, path, body, tenantId) {
    var opts = { method: method, headers: headers(body != null, tenantId) };
    if (body != null) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = { raw: t }; }
        return { ok: r.ok, status: r.status, json: j };
      });
    });
  }

  function previewText(tenantId, path, body) {
    return '租戶：' + tenantId + '\nPOST ' + path + '\n' + JSON.stringify(body, null, 2);
  }

  function syncTenantHint() {
    $('kd-tenant-active').textContent = activeTenant;
    $('kd-tenant-hint').hidden = fieldTenant() === activeTenant;
  }

  // Adopt the field value as the active tenant and drop any open confirm,
  // so nothing prepared for the previous tenant can still be sent.
  function applyTenant() {
    activeTenant = fieldTenant();
    try { localStorage.setItem('fox3d.tenant', activeTenant); } catch (e) { /* storage blocked */ }
    confirmResets.forEach(function (reset) { reset(); });
    syncTenantHint();
  }

  function loadTenantFromStorage() {
    try {
      var t = localStorage.getItem('fox3d.tenant');
      if (t) $('kd-tenant').value = t;
    } catch (e) { /* storage blocked */ }
    $('kd-tenant').addEventListener('input', syncTenantHint);
  }

  function readinessNote(matrix, k) {
    var checks = matrix.requiredChecks && matrix.requiredChecks[k];
    var note = checks && checks.length ? checks.join('；') : '—';
    if (k.indexOf('CostModel') >= 0 && matrix.commercialCostModelScope) {
      note += '（範圍：' + matrix.commercialCostModelScope + '）';
    }
    return note;
  }

  function readinessScopeLine(matrix) {
    var p = el('p', 'kd-muted kd-readiness-scope');
    var scope = typeof matrix.productionReadyScope === 'string' && matrix.productionReadyScope
      ? matrix.productionReadyScope : '未回傳';
    var ready = typeof matrix.productionReady === 'boolean'
      ? (matrix.productionReady ? '是' : '否') : '未回傳';
    p.appendChild(document.createTextNode('正式量產就緒：' + ready + '（判定範圍：' + scope + '）'));
    if (typeof matrix.fullAutonomousFactoryReady === 'boolean') {
      p.appendChild(document.createTextNode('；全自動工廠：' + (matrix.fullAutonomousFactoryReady ? '是' : '否')));
    }
    if (matrix.commercialCostModelScope) {
      p.appendChild(document.createTextNode('；成本模型：'));
      p.appendChild(tagSpan(matrix.commercialCostModelScope));
    }
    return p;
  }

  function estimateCell(value) {
    var td = el('td');
    if (value == null) {
      td.textContent = '—';
      return td;
    }
    td.appendChild(document.createTextNode(String(value) + ' '));
    var tag = el('span', 'kd-tag warn', '估算');
    tag.title = ESTIMATE_SCOPE;
    td.appendChild(tag);
    return td;
  }

  function renderReadiness(matrix) {
    var panel = $('kd-readiness');
    var msg = $('kd-readiness-msg');
    var table = $('kd-readiness-table');
    var tbody = table.querySelector('tbody');
    tbody.textContent = '';
    msg.textContent = '';
    msg.className = 'kd-muted';
    panel.querySelectorAll('.kd-readiness-scope').forEach(function (n) { n.remove(); });
    var keys = Object.keys(matrix || {}).filter(function (k) {
      return typeof matrix[k] === 'boolean';
    });
    if (!keys.length) {
      msg.textContent = '沒有就緒矩陣資料。';
      table.hidden = true;
      return;
    }
    keys.forEach(function (k) {
      var tr = document.createElement('tr');
      tr.appendChild(el('td', null, k));
      var ready = matrix[k];
      tr.appendChild(el('td', null, ready ? '就緒' : '尚未'));
      tr.appendChild(el('td', null, readinessNote(matrix, k)));
      tbody.appendChild(tr);
    });
    table.hidden = false;
    panel.insertBefore(readinessScopeLine(matrix), table.parentNode);
  }

  function loadOverview() {
    var seq = ++overviewSeq;
    $('kd-readiness-msg').textContent = '載入中…';
    $('kd-readiness-msg').className = 'kd-muted';
    $('kd-types-msg').textContent = '載入中…';
    api('GET', '/api/kd/readiness').then(function (r) {
      if (seq !== overviewSeq) return;
      if (!r.ok) {
        $('kd-readiness-msg').textContent = '就緒狀態載入失敗（HTTP ' + r.status + '）';
        $('kd-readiness-msg').className = 'kd-err';
        return;
      }
      renderReadiness(r.json);
    }).catch(function (e) {
      if (seq !== overviewSeq) return;
      $('kd-readiness-msg').textContent = '就緒狀態載入失敗：' + e;
      $('kd-readiness-msg').className = 'kd-err';
    });

    api('GET', '/api/kd/product-types').then(function (r) {
      if (seq !== overviewSeq) return;
      if (!r.ok) {
        $('kd-types-msg').textContent = '類型載入失敗（HTTP ' + r.status + '）';
        return;
      }
      var items = r.json.items || [];
      var tbody = $('kd-types-table').querySelector('tbody');
      var sel = $('kd-sku-kind');
      tbody.textContent = '';
      sel.textContent = '';
      if (!items.length) {
        $('kd-types-msg').textContent = '尚無商品類型。';
        return;
      }
      items.forEach(function (kind) {
        var tr = el('tr');
        tr.appendChild(el('td', null, kind));
        tbody.appendChild(tr);
        var opt = document.createElement('option');
        opt.value = kind;
        opt.textContent = kind;
        sel.appendChild(opt);
      });
      $('kd-types-msg').textContent = '共 ' + items.length + ' 種。';
      $('kd-types-table').hidden = false;
    }).catch(function (e) {
      if (seq !== overviewSeq) return;
      $('kd-types-msg').textContent = '類型載入失敗：' + e;
    });
  }

  function reloadOverview() {
    applyTenant();
    loadOverview();
  }

  function wireConfirmForm(formId, confirmId, payloadId, goId, cancelId, buildPayload, onSuccess) {
    var form = $(formId);
    var confirm = $(confirmId);
    var go = $(goId);
    var pending = null;

    function reset() {
      confirm.hidden = true;
      $(payloadId).textContent = '';
      pending = null;
    }
    confirmResets.push(reset);

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      pending = buildPayload();
      pending.tenant = activeTenant;
      $(payloadId).textContent = previewText(pending.tenant, pending._path, pending.body);
      confirm.hidden = false;
    });

    $(cancelId).addEventListener('click', reset);

    go.addEventListener('click', function () {
      if (!pending) return;
      var req = pending;
      go.disabled = true;
      api('POST', req._path, req.body, req.tenant).then(function (r) {
        if (pending === req) reset();
        onSuccess(r, req);
      }).catch(function (e) {
        onSuccess({ ok: false, status: 0, json: { error: String(e) } }, req);
      }).then(function () { go.disabled = false; });
    });
  }

  function button(cls, text) {
    var b = el('button', cls, text);
    b.type = 'button';
    return b;
  }

  function wireStructureForm(formId, confirmId, resultId, path, buildBody) {
    var form = $(formId);
    var confirm = $(confirmId);
    var result = $(resultId);
    var pending = null;

    if (!confirm.querySelector('.kd-confirm-actions')) {
      confirm.textContent = '';
      confirm.appendChild(el('p', null, '確定要送出？會寫入工程試算資料。'));
      confirm.appendChild(el('pre', 'kd-out kd-payload'));
      var actions = el('div', 'kd-confirm-actions');
      actions.appendChild(button('kd-btn kd-go', '確定送出'));
      actions.appendChild(button('kd-btn ghost kd-cancel', '取消'));
      confirm.appendChild(actions);
    }
    var payloadPre = confirm.querySelector('.kd-payload');
    var go = confirm.querySelector('.kd-go');
    var cancel = confirm.querySelector('.kd-cancel');

    function reset() {
      confirm.hidden = true;
      payloadPre.textContent = '';
      pending = null;
    }
    confirmResets.push(reset);

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      pending = { tenant: activeTenant, body: buildBody() };
      payloadPre.textContent = previewText(pending.tenant, path, pending.body);
      confirm.hidden = false;
    });
    cancel.addEventListener('click', reset);
    go.addEventListener('click', function () {
      if (!pending) return;
      var req = pending;
      go.disabled = true;
      api('POST', path, req.body, req.tenant).then(function (r) {
        if (pending === req) reset();
        showJson(result, r.json, r.status);
        if (!r.ok) result.classList.add('kd-err');
        else result.classList.remove('kd-err');
      }).catch(function (e) {
        showJson(result, { error: String(e) }, null);
        result.classList.add('kd-err');
      }).then(function () { go.disabled = false; });
    });
  }

  function boot() {
    loadTenantFromStorage();
    applyTenant();
    $('kd-refresh').addEventListener('click', reloadOverview);
    loadOverview();

    wireConfirmForm('kd-sku-form', 'kd-sku-confirm', 'kd-sku-payload', 'kd-sku-go', 'kd-sku-cancel', function () {
      return {
        _path: '/api/kd/skus',
        body: { kind: $('kd-sku-kind').value, render: $('kd-sku-render').checked },
      };
    }, function (r) {
      showJson($('kd-sku-result'), r.json, r.status);
    });

    wireConfirmForm('kd-catalog-form', 'kd-catalog-confirm', 'kd-catalog-payload', 'kd-catalog-go', 'kd-catalog-cancel', function () {
      return {
        _path: '/api/kd/catalog',
        body: { count: parseInt($('kd-catalog-count').value, 10) || 12, render: $('kd-catalog-render').checked },
      };
    }, function (r) {
      var summary = $('kd-catalog-summary');
      var table = $('kd-catalog-table');
      var tbody = table.querySelector('tbody');
      tbody.textContent = '';
      showJson($('kd-catalog-result'), r.json, r.status);
      $('kd-catalog-raw').hidden = false;
      if (!r.ok) {
        summary.hidden = false;
        summary.textContent = '型錄產生失敗（HTTP ' + r.status + '）';
        summary.className = 'kd-err';
        table.hidden = true;
        return;
      }
      var rows = (r.json && r.json.catalog) || [];
      summary.hidden = false;
      summary.className = 'kd-muted';
      summary.textContent = '已產生 ' + (r.json.generated || 0) + ' 筆，列入排名 ' + (r.json.ranked || 0) + ' 筆；需求標籤：';
      summary.appendChild(tagSpan(r.json.demandLabel || 'MOCK'));
      summary.appendChild(document.createTextNode('；到岸成本與建議售價皆為估算（' + ESTIMATE_SCOPE + '），不是供應商實價。'));
      if (!rows.length) {
        table.hidden = true;
        return;
      }
      rows.slice(0, 20).forEach(function (row) {
        var tr = document.createElement('tr');
        tr.appendChild(el('td', null, row.productId));
        tr.appendChild(el('td', null, row.kind));
        var d = row.dimensions || {};
        tr.appendChild(el('td', null, d.width + '×' + d.height + '×' + d.depth));
        tr.appendChild(el('td', null, row.approvalState || '—'));
        var demandTd = el('td');
        demandTd.appendChild(tagSpan(row.demandDataConfidence || 'MOCK'));
        tr.appendChild(demandTd);
        tr.appendChild(estimateCell(row.landedCost));
        tr.appendChild(estimateCell(row.suggestedPrice));
        tbody.appendChild(tr);
      });
      table.hidden = false;
    });

    wireConfirmForm('kd-cand-form', 'kd-cand-confirm', 'kd-cand-payload', 'kd-cand-go', 'kd-cand-cancel', function () {
      return {
        _path: '/api/kd/candidates',
        body: { count: parseInt($('kd-cand-count').value, 10) || 6 },
      };
    }, function (r) {
      showJson($('kd-cand-result'), r.json, r.status);
      $('kd-cand-raw').hidden = false;
      var table = $('kd-cand-table');
      var tbody = table.querySelector('tbody');
      tbody.textContent = '';
      if (!r.ok || !r.json) { table.hidden = true; return; }
      (r.json.candidates || []).forEach(function (row) {
        var tr = document.createElement('tr');
        tr.appendChild(el('td', null, row.kind));
        tr.appendChild(el('td', null, row.before && row.before.waste != null ? String(row.before.waste) : '—'));
        tr.appendChild(el('td', null, row.after && row.after.waste != null ? String(row.after.waste) : '—'));
        tr.appendChild(el('td', null, row.redesignTriggered ? '有' : '無'));
        var dTd = el('td');
        dTd.appendChild(tagSpan(row.demand || 'MOCK'));
        tr.appendChild(dTd);
        tbody.appendChild(tr);
      });
      table.hidden = !(r.json.candidates || []).length;
    });

    wireStructureForm('kd-retail-form', 'kd-retail-confirm', 'kd-retail-result', '/api/retail/fixtures', function () {
      return {
        family: $('kd-retail-family').value,
        facing: parseInt($('kd-retail-facing').value, 10) || 2,
        render: false,
      };
    });

    wireStructureForm('kd-pack-form', 'kd-pack-confirm', 'kd-pack-result', '/api/packaging/structures', function () {
      return {
        family: $('kd-pack-family').value,
        productDims: {
          width: parseFloat($('kd-pack-w').value) || 120,
          height: parseFloat($('kd-pack-h').value) || 80,
          depth: parseFloat($('kd-pack-d').value) || 40,
        },
        render: false,
      };
    });

    wireStructureForm('kd-acr-form', 'kd-acr-confirm', 'kd-acr-result', '/api/acrylic/products', function () {
      return {
        kind: $('kd-acr-kind').value,
        sheetSku: $('kd-acr-sheet').value.trim() || 'ACR_CLEAR_5',
        render: false,
      };
    });

    if (location.hash === '#structures') {
      var s = $('structures');
      if (s) s.scrollIntoView({ block: 'start' });
    }
    window.addEventListener('hashchange', function () {
      if (location.hash === '#structures' && $('structures')) $('structures').scrollIntoView({ block: 'start' });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
