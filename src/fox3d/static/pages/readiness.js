// /admin/readiness — scoped readiness, release, physical OS, commerce.
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  function tenant() {
    var v = ($('rd-tenant') && $('rd-tenant').value.trim()) || 'sonaqueen-home';
    return v;
  }

  function headers() {
    return { 'X-Tenant-Id': tenant(), Accept: 'application/json', 'Content-Type': 'application/json' };
  }

  function showNotice(msg, err) {
    var n = $('rd-notice');
    if (!n) return;
    n.hidden = !msg;
    n.textContent = msg || '';
    n.classList.toggle('err', !!err);
  }

  function fmtJson(obj) {
    try { return JSON.stringify(obj, null, 2); } catch (e) { return String(obj); }
  }

  function api(method, path, body) {
    var opts = { method: method, headers: headers() };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) {
      return r.text().then(function (t) {
        var data;
        try { data = t ? JSON.parse(t) : {}; } catch (e) { data = { raw: t }; }
        return { ok: r.ok, status: r.status, data: data };
      });
    });
  }

  function labelTag(lbl) {
    if (!lbl) return '';
    var u = String(lbl).toUpperCase();
    if (u === 'MOCK' || u === 'BLOCKED' || u === 'PARTIAL' || u === 'REAL' || u.indexOf('CONFIG') >= 0 || u === 'IMPORTED' || u === 'LIVE_PROVIDER') {
      return 'lbl-' + u.replace(/[^A-Z_]/g, '_').replace(/CONFIG.*/, 'CONFIG_ESTIMATE');
    }
    return 'lbl-' + u;
  }

  function boolCell(v) {
    var span = document.createElement('span');
    span.className = 'rd-tag ' + (v ? 'yes' : 'no');
    span.textContent = v ? '就緒' : '未就緒';
    return span;
  }

  function buildTable(rows) {
    var table = document.createElement('table');
    table.className = 'rd-table';
    var thead = document.createElement('thead');
    var trh = document.createElement('tr');
    ['項目', '狀態', '說明'].forEach(function (h) {
      var th = document.createElement('th');
      th.textContent = h;
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    var tb = document.createElement('tbody');
    rows.forEach(function (row) {
      var tr = document.createElement('tr');
      var td0 = document.createElement('td');
      td0.appendChild(document.createElement('code')).textContent = row.key;
      var td1 = document.createElement('td');
      if (row.kind === 'bool') td1.appendChild(boolCell(row.value));
      else if (row.label) {
        var tag = document.createElement('span');
        tag.className = 'rd-tag ' + labelTag(row.label);
        tag.textContent = row.label;
        td1.appendChild(tag);
        if (row.ready === false) td1.appendChild(document.createTextNode(' '));
        if (typeof row.ready === 'boolean') {
          var sub = document.createElement('span');
          sub.className = 'rd-tag ' + (row.ready ? 'yes' : 'no');
          sub.textContent = row.ready ? '就緒' : '未就緒';
          td1.appendChild(sub);
        }
      } else td1.textContent = String(row.value);
      var td2 = document.createElement('td');
      td2.textContent = row.note || '';
      tr.appendChild(td0);
      tr.appendChild(td1);
      tr.appendChild(td2);
      tb.appendChild(tr);
    });
    table.appendChild(tb);
    return table;
  }

  function overviewRows(data) {
    var labels = data.labels || {};
    var skip = { labels: 1, globalProductionReady: 1, humanApprovalGate: 1, liveMachineControl: 1 };
    var rows = [];
    Object.keys(data).forEach(function (k) {
      if (skip[k]) return;
      var v = data[k];
      if (typeof v === 'boolean') {
        var note = labels[k] ? '標籤：' + labels[k] : '';
        if (labels[k] === 'MOCK' || labels[k] === 'BLOCKED' || labels[k] === 'PARTIAL') {
          note += (note ? '；' : '') + '此項非實機就緒';
        }
        rows.push({ key: k, kind: 'bool', value: v, label: labels[k], note: note });
      } else if (v && typeof v === 'object' && !Array.isArray(v) && ('label' in v || 'ready' in v)) {
        rows.push({
          key: k,
          label: v.label,
          ready: v.ready,
          note: v.note || (v.label === 'MOCK' ? '模擬資料' : v.label === 'BLOCKED' ? '已封鎖' : ''),
        });
      }
    });
    rows.sort(function (a, b) { return a.key.localeCompare(b.key); });
    return rows;
  }

  function loadOverview() {
    var st = $('rd-overview-status');
    var wrap = $('rd-overview-table');
    var det = $('rd-overview-detail');
    if (!st) return;
    st.textContent = '載入中…';
    if (wrap) { wrap.hidden = true; wrap.textContent = ''; }
    if (det) det.hidden = true;
    api('GET', '/api/readiness').then(function (r) {
      if (!r.ok) {
        st.textContent = '載入失敗（HTTP ' + r.status + '）';
        return;
      }
      var d = r.data;
      st.textContent = d.globalProductionReady
        ? '警告：globalProductionReady 為 true（請確認是否誤標）'
        : '全域量產就緒：否 · 人工核准閘門：' + (d.humanApprovalGate ? '開啟' : '關閉');
      if (wrap) {
        wrap.appendChild(buildTable(overviewRows(d)));
        wrap.hidden = false;
      }
      if (det) {
        det.textContent = 'liveMachineControl=' + d.liveMachineControl;
        det.hidden = false;
      }
    }).catch(function (e) { st.textContent = '載入失敗：' + e; });
  }

  function loadKpi() {
    var st = $('rd-kpi-status');
    var wrap = $('rd-kpi-table');
    if (!st) return;
    st.textContent = '載入中…';
    if (wrap) { wrap.hidden = true; wrap.textContent = ''; }
    api('GET', '/api/kpi').then(function (r) {
      if (!r.ok) {
        st.textContent = '載入失敗（HTTP ' + r.status + '）';
        return;
      }
      var d = r.data;
      st.textContent = 'liveMachineControl=' + d.liveMachineControl + ' · 核准過期筆數=' + (d.approvalStale || 0);
      var rows = [
        { key: 'availableRemnants', kind: 'bool', value: (d.availableRemnants || 0) > 0, note: '可用餘料：' + (d.availableRemnants || 0) },
        { key: 'remnantReuseCount', kind: 'bool', value: false, note: '已耗用餘料：' + (d.remnantReuseCount || 0) },
        { key: 'trueScrap', kind: 'bool', value: false, note: String(d.trueScrap || '') },
      ];
      var lbl = d.labels || {};
      Object.keys(lbl).forEach(function (cat) {
        (lbl[cat] || []).forEach(function (name) {
          rows.push({
            key: name,
            label: cat,
            note: cat === 'REAL' ? '工程可驗項目' : cat === 'MOCK' ? '模擬，不可當真' : cat === 'BLOCKED' ? '封鎖中' : '',
          });
        });
      });
      if (wrap) {
        wrap.appendChild(buildTable(rows));
        wrap.hidden = false;
      }
    }).catch(function (e) { st.textContent = '載入失敗：' + e; });
  }

  function loadPhysical() {
    var st = $('rd-phys-status');
    var fam = $('rd-families-table');
    var ready = $('rd-phys-ready-table');
    if (!st) return;
    st.textContent = '載入中…';
    if (fam) { fam.hidden = true; fam.textContent = ''; }
    if (ready) { ready.hidden = true; ready.textContent = ''; }
    Promise.all([
      api('GET', '/api/physical-os/families'),
      api('GET', '/api/physical-os/readiness'),
    ]).then(function (res) {
      var fr = res[0];
      var rr = res[1];
      if (!fr.ok || !rr.ok) {
        st.textContent = '載入失敗';
        return;
      }
      var items = fr.data.items || [];
      st.textContent = '產品家族 ' + items.length + ' 筆 · 全域量產就緒：' + (rr.data.globalProductionReady ? '是（請留意）' : '否');
      if (fam) {
        var rows = items.map(function (it) {
          return {
            key: it && (it.name || it.id || it.family) || '—',
            kind: 'bool',
            value: !!(it && it.ready),
            note: (it && it.summary) || (it && it.description) || '',
          };
        });
        if (!rows.length) rows.push({ key: '（無資料）', kind: 'bool', value: false, note: '' });
        fam.appendChild(buildTable(rows));
        fam.hidden = false;
      }
      if (ready) {
        ready.appendChild(buildTable(overviewRows(rr.data)));
        ready.hidden = false;
      }
    }).catch(function (e) { st.textContent = '載入失敗：' + e; });
  }

  function bindConfirm(runId, confirmId, okId, cancelId, onOk) {
    var run = $(runId);
    var box = $(confirmId);
    var ok = $(okId);
    var cancel = $(cancelId);
    if (!run || !box || !ok || !cancel) return;
    run.addEventListener('click', function () { box.hidden = false; });
    cancel.addEventListener('click', function () { box.hidden = true; });
    ok.addEventListener('click', function () {
      box.hidden = true;
      onOk();
    });
  }

  function showOut(id, r) {
    var out = $(id);
    if (!out) return;
    out.hidden = false;
    out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
    showNotice(r.ok ? '操作完成（HTTP ' + r.status + '）' : '操作失敗（HTTP ' + r.status + '）', !r.ok);
  }

  function parseJson(text, fieldName) {
    try {
      return JSON.parse(text || '{}');
    } catch (e) {
      showNotice(fieldName + ' JSON 格式錯誤', true);
      throw e;
    }
  }

  function focusHash() {
    var id = '';
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (e) { return; }
    if (!id) return;
    var el = document.getElementById(id);
    if (el) el.scrollIntoView({ block: 'start' });
  }

  function boot() {
    try {
      var t = localStorage.getItem('fox3d.tenant');
      if (t && $('rd-tenant')) $('rd-tenant').value = t;
    } catch (e) { /* storage blocked */ }
    if ($('rd-tenant')) {
      $('rd-tenant').addEventListener('change', function (e) {
        try { localStorage.setItem('fox3d.tenant', e.target.value.trim()); } catch (x) { /* */ }
        loadOverview();
        loadKpi();
        loadPhysical();
      });
    }
    var reloadBtn = $('rd-reload-overview');
    if (reloadBtn) reloadBtn.addEventListener('click', loadOverview);

    loadOverview();
    loadKpi();
    loadPhysical();

    bindConfirm('rd-evidence-run', 'rd-evidence-confirm', 'rd-evidence-ok', 'rd-evidence-cancel', function () {
      var bundle;
      try { bundle = parseJson($('rd-evidence-json').value, '證據'); } catch (e) { return; }
      api('POST', '/api/evidence/verify', { bundle: bundle }).then(function (r) { showOut('rd-evidence-out', r); });
    });

    (function () {
      var run = $('rd-rel-run');
      var box = $('rd-rel-confirm');
      $('rd-rel-cancel').addEventListener('click', function () { box.hidden = true; });
      run.addEventListener('click', function () {
        var txt = $('rd-rel-confirm-text');
        if (txt) {
          txt.textContent = '將「' + $('rd-rel-entity').value + '」推進至 ' + $('rd-rel-target').value + '？';
        }
        box.hidden = false;
      });
      $('rd-rel-ok').addEventListener('click', function () {
        box.hidden = true;
        var entity;
        try { entity = parseJson($('rd-rel-entity-json').value, '實體'); } catch (e) { return; }
        api('POST', '/api/release/advance', {
          entityId: $('rd-rel-entity').value.trim(),
          target: $('rd-rel-target').value,
          actor: 'readiness-page',
          entity: entity,
          evidenceOk: !!$('rd-rel-evidence').checked,
        }).then(function (r) { showOut('rd-rel-out', r); });
      });
    })();

    bindConfirm('rd-safe-run', 'rd-safe-confirm', 'rd-safe-ok', 'rd-safe-cancel', function () {
      var rec;
      try { rec = parseJson($('rd-safe-json').value, '紀錄'); } catch (e) { return; }
      api('POST', '/api/safety/evaluate', { kind: $('rd-safe-kind').value, record: rec }).then(function (r) {
        showOut('rd-safe-out', r);
      });
    });

    bindConfirm('rd-phys-approve-run', 'rd-phys-confirm', 'rd-phys-approve-ok', 'rd-phys-approve-cancel', function () {
      api('POST', '/api/physical-os/approve', {
        entityId: $('rd-phys-entity').value.trim(),
        kind: $('rd-phys-kind').value.trim(),
        actor: 'readiness-page',
      }).then(function (r) { showOut('rd-phys-out', r); });
    });

    var comRun = $('rd-com-run');
    if (comRun) {
      comRun.addEventListener('click', function () {
        var txt = $('rd-com-confirm-text');
        if (txt) {
          txt.textContent = '將 ' + ($('rd-com-rows').value.match(/^\s*\[/) ? 'JSON 陣列' : '資料') + ' 匯入至 ' + $('rd-com-kind').value + '（來源 ' + $('rd-com-source').value + '）？';
        }
        $('rd-com-confirm').hidden = false;
      });
    }
    $('rd-com-cancel').addEventListener('click', function () { $('rd-com-confirm').hidden = true; });
    $('rd-com-ok').addEventListener('click', function () {
      $('rd-com-confirm').hidden = true;
      var rows;
      try { rows = parseJson($('rd-com-rows').value, '資料列'); } catch (e) { return; }
      if (!Array.isArray(rows)) {
        showNotice('資料列必須是 JSON 陣列', true);
        return;
      }
      api('POST', '/api/commerce/import', {
        kind: $('rd-com-kind').value,
        source: $('rd-com-source').value,
        rows: rows,
      }).then(function (r) { showOut('rd-com-out', r); loadKpi(); });
    });

    window.addEventListener('hashchange', focusHash);
    focusHash();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
