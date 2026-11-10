// /admin/kd — KD catalog, readiness, structure generation.
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  function tenant() {
    var v = ($('kd-tenant').value || '').trim();
    return v || 'sonaqueen-home';
  }

  function headers(json) {
    var h = { 'X-Tenant-Id': tenant(), Accept: 'application/json' };
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

  function api(method, path, body) {
    var opts = { method: method, headers: headers(body != null) };
    if (body != null) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = { raw: t }; }
        return { ok: r.ok, status: r.status, json: j };
      });
    });
  }

  function loadTenantFromStorage() {
    try {
      var t = localStorage.getItem('fox3d.tenant');
      if (t) $('kd-tenant').value = t;
    } catch (e) { /* storage blocked */ }
    $('kd-tenant').addEventListener('change', function (e) {
      try { localStorage.setItem('fox3d.tenant', e.target.value.trim()); } catch (x) { /* */ }
    });
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
      var noteCell = el('td');
      if (matrix.requiredChecks && matrix.requiredChecks[k]) {
        noteCell.textContent = (matrix.requiredChecks[k] || []).join('；');
      } else {
        noteCell.textContent = matrix.commercialCostModelScope && k.indexOf('Cost') >= 0 ? matrix.commercialCostModelScope : '—';
      }
      tr.appendChild(noteCell);
      tbody.appendChild(tr);
    });
    table.hidden = false;
    var scope = el('p', 'kd-muted kd-readiness-scope', '範圍：' + (matrix.productionReadyScope || '—') + '；正式量產就緒：' + (matrix.productionReady ? '是' : '否'));
    panel.insertBefore(scope, table.parentNode);
  }

  function loadOverview() {
    $('kd-readiness-msg').textContent = '載入中…';
    $('kd-types-msg').textContent = '載入中…';
    api('GET', '/api/kd/readiness').then(function (r) {
      if (!r.ok) {
        $('kd-readiness-msg').textContent = '就緒狀態載入失敗（HTTP ' + r.status + '）';
        $('kd-readiness-msg').className = 'kd-err';
        return;
      }
      renderReadiness(r.json);
    }).catch(function (e) {
      $('kd-readiness-msg').textContent = '就緒狀態載入失敗：' + e;
    });

    api('GET', '/api/kd/product-types').then(function (r) {
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
      $('kd-types-msg').textContent = '類型載入失敗：' + e;
    });
  }

  function wireConfirmForm(formId, confirmId, payloadId, goId, cancelId, buildPayload, onSuccess) {
    var form = $(formId);
    var confirm = $(confirmId);
    var pending = null;

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      pending = buildPayload();
      $(payloadId).textContent = JSON.stringify(pending, null, 2);
      confirm.hidden = false;
    });

    $(cancelId).addEventListener('click', function () {
      confirm.hidden = true;
      pending = null;
    });

    $(goId).addEventListener('click', function () {
      if (!pending) return;
      var btn = $(goId);
      btn.disabled = true;
      api('POST', pending._path, pending.body).then(function (r) {
        confirm.hidden = true;
        onSuccess(r, pending);
        pending = null;
      }).catch(function (e) {
        onSuccess({ ok: false, status: 0, json: { error: String(e) } }, pending);
      }).then(function () { btn.disabled = false; });
    });
  }

  function wireStructureForm(formId, confirmId, resultId, path, buildBody) {
    var form = $(formId);
    var confirm = $(confirmId);
    var result = $(resultId);
    var pending = null;

    if (!confirm.querySelector('.kd-confirm-actions')) {
      confirm.innerHTML = '<p>確定要送出？會寫入工程試算資料。</p><pre class="kd-out kd-payload"></pre><div class="kd-confirm-actions"><button type="button" class="kd-btn kd-go">確定送出</button><button type="button" class="kd-btn ghost kd-cancel">取消</button></div>';
    }
    var payloadPre = confirm.querySelector('.kd-payload');
    var go = confirm.querySelector('.kd-go');
    var cancel = confirm.querySelector('.kd-cancel');

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      pending = buildBody();
      payloadPre.textContent = JSON.stringify(pending, null, 2);
      confirm.hidden = false;
    });
    cancel.addEventListener('click', function () { confirm.hidden = true; pending = null; });
    go.addEventListener('click', function () {
      if (!pending) return;
      go.disabled = true;
      api('POST', path, pending).then(function (r) {
        confirm.hidden = true;
        showJson(result, r.json, r.status);
        if (!r.ok) result.classList.add('kd-err');
        else result.classList.remove('kd-err');
        pending = null;
      }).catch(function (e) {
        showJson(result, { error: String(e) }, null);
      }).then(function () { go.disabled = false; });
    });
  }

  function boot() {
    loadTenantFromStorage();
    $('kd-refresh').addEventListener('click', loadOverview);
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
        tr.appendChild(el('td', null, row.landedCost != null ? String(row.landedCost) : '—'));
        tr.appendChild(el('td', null, row.suggestedPrice != null ? String(row.suggestedPrice) : '—'));
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
