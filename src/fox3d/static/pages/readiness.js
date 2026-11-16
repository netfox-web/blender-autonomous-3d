// /admin/readiness — scoped readiness, release, physical OS, commerce.
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  function tenant() {
    var v = ($('rd-tenant') && $('rd-tenant').value.trim()) || 'sonaqueen-home';
    return v;
  }

  function headers(pinned) {
    return { 'X-Tenant-Id': pinned || tenant(), Accept: 'application/json', 'Content-Type': 'application/json' };
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

  function api(method, path, body, pinnedTenant) {
    var opts = { method: method, headers: headers(pinnedTenant) };
    if (body !== undefined) opts.body = JSON.stringify(body);
    var call = fetch(path, opts).then(function (r) {
      return r.text().then(function (t) {
        var data;
        try { data = t ? JSON.parse(t) : {}; } catch (e) { data = { raw: t }; }
        return { ok: r.ok, status: r.status, data: data };
      });
    });
    if (method === 'GET') return call;  // loaders handle their own errors
    return call.catch(function (e) {
      showNotice('連線失敗，請稍後再試：' + ((e && e.message) || e), true);
      return { ok: false, status: 0, data: { error: '連線失敗', detail: String((e && e.message) || e) } };
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


  // Outcome helper shared with the render page: HTTP non-2xx, status/label/truthLabel
  // of BLOCKED or FAILED, a BLOCKED_ error, or any safety check veto=true is a failure.
  // /api/evidence/verify stays HTTP 200 and puts a failed bundle in ok:false plus errors[].
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
      var list = lists[i];
      for (var j = 0; j < list.length; j++) {
        if (list[j] && list[j].veto === true) return true;
      }
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
    return (
      out.ok === false ||
      out.status === 'blocked' ||
      tokenBad(out.status) ||
      tokenBad(out.label) ||
      tokenBad(out.truthLabel) ||
      String(out.error || '').indexOf('BLOCKED_') === 0 ||
      out.veto === true ||
      checksHaveVeto(out) ||
      Boolean(job && (
        job.status === 'blocked' ||
        tokenBad(job.status) ||
        tokenBad(job.label) ||
        tokenBad(job.truthLabel) ||
        String(job.error || '').indexOf('BLOCKED_') === 0
      ))
    );
  }

  function validationReasons(out) {
    var reasons = [];
    var errs = out && out.errors;
    if (!Array.isArray(errs)) return reasons;
    for (var i = 0; i < errs.length; i++) {
      if (errs[i] == null) continue;
      var text = String(errs[i]).trim();
      if (text) reasons.push(text);
    }
    return reasons;
  }

  function blockedMessage(label, out) {
    if (out && out.ok === false) {
      var reasons = validationReasons(out);
      return label + '：驗證失敗' + (reasons.length ? '（' + reasons.join('、') + '）' : '');
    }
    var code = (out && (out.error || out.status || out.label || out.truthLabel)) || '';
    if (out && (out.veto === true || checksHaveVeto(out))) return label + '：已阻擋（安全檢查未通過）';
    var mark = String((out && (out.label || out.truthLabel || out.status)) || '');
    var up = mark.toUpperCase();
    if (up === 'FAILED' || up.indexOf('FAILED_') === 0) return label + '：失敗' + (code ? '（' + code + '）' : '');
    return label + '：已阻擋' + (code ? '（' + code + '）' : '');
  }

  // Snapshot is taken when the confirm box opens. Inputs (including tenant) stay
  // locked until confirm or cancel; the POST sends the snapshot, not a later read.
  var postBusy = false;

  function readFields(ids) {
    var raw = {};
    ids.forEach(function (id) {
      var el = $(id);
      if (!el) return;
      raw[id] = el.type === 'checkbox' ? !!el.checked : el.value;
    });
    return raw;
  }

  function lockIds(ids, on) {
    var els = [];
    ids.forEach(function (id) {
      var el = $(id);
      if (el && els.indexOf(el) < 0) els.push(el);
    });
    var tenantEl = $('rd-tenant');
    if (tenantEl && els.indexOf(tenantEl) < 0) els.push(tenantEl);
    els.forEach(function (el) {
      if (on) {
        if (!el.hasAttribute('data-rd-lock')) el.setAttribute('data-rd-lock', el.disabled ? '1' : '0');
        el.disabled = true;
      } else if (el.hasAttribute('data-rd-lock')) {
        el.disabled = el.getAttribute('data-rd-lock') === '1';
        el.removeAttribute('data-rd-lock');
      }
    });
  }

  function showOut(id, r, label) {
    var out = $(id);
    if (!out || !r) return;
    out.hidden = false;
    out.textContent = 'HTTP ' + r.status + '\n' + fmtJson(r.data);
    if (r.status === 0 || (r.data && r.data.error === '連線失敗')) {
      showNotice('連線失敗，請稍後再試：' + ((r.data && r.data.detail) || ''), true);
      return;
    }
    if (!r.ok || isBlockedResult(r) || isBlockedResult(r.data)) {
      if (!r.ok) showNotice('操作失敗（HTTP ' + r.status + '）', true);
      else showNotice(blockedMessage(label || '操作', r.data), true);
      return;
    }
    showNotice('操作完成（HTTP ' + r.status + '）', false);
  }

  function bindPost(cfg) {
    var run = $(cfg.run);
    var box = $(cfg.box);
    var ok = $(cfg.ok);
    var cancel = $(cfg.cancel);
    if (!run || !box || !ok || !cancel) return;
    var snapEl = cfg.snap ? $(cfg.snap) : null;
    var textEl = cfg.text ? $(cfg.text) : null;
    var held = null;

    run.addEventListener('click', function () {
      if (postBusy || held) return;
      var raw = readFields(cfg.fields);
      raw.tenant = tenant();
      var body;
      try { body = cfg.build(raw); } catch (e) { return; }
      held = { tenant: raw.tenant, body: body, raw: raw };
      if (textEl) textEl.textContent = cfg.summary(body, raw);
      if (snapEl) snapEl.textContent = JSON.stringify({ tenant: raw.tenant, body: body }, null, 2);
      lockIds(cfg.fields, true);
      box.hidden = false;
    });
    cancel.addEventListener('click', function () {
      if (postBusy) return;
      held = null;
      box.hidden = true;
      lockIds(cfg.fields, false);
    });
    ok.addEventListener('click', function () {
      if (!held || postBusy) return;
      var shot = held;
      held = null;
      box.hidden = true;
      lockIds(cfg.fields, false);
      postBusy = true;
      run.disabled = true;
      ok.disabled = true;
      var finish = function () {
        postBusy = false;
        run.disabled = false;
        ok.disabled = false;
      };
      var request;
      try {
        request = api('POST', cfg.path, shot.body, shot.tenant);
      } catch (e) {
        showNotice('操作失敗：' + ((e && e.message) || e), true);
        finish();
        return;
      }
      request.then(function (r) {
        showOut(cfg.out, r, cfg.label);
        if (cfg.after && r && r.ok && !isBlockedResult(r) && !isBlockedResult(r.data)) cfg.after();
      }).finally(finish);
    });
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

    bindPost({
      run: 'rd-evidence-run', box: 'rd-evidence-confirm', ok: 'rd-evidence-ok', cancel: 'rd-evidence-cancel',
      out: 'rd-evidence-out', snap: 'rd-evidence-snap', text: 'rd-evidence-text', label: '證據驗證',
      path: '/api/evidence/verify', fields: ['rd-evidence-json'],
      summary: function (body, raw) {
        return '確定送出證據驗證（租戶 ' + raw.tenant + '）？此操作僅查驗資料，不會改動後端狀態。';
      },
      build: function (raw) { return { bundle: parseJson(raw['rd-evidence-json'], '證據') }; },
    });

    bindPost({
      run: 'rd-rel-run', box: 'rd-rel-confirm', ok: 'rd-rel-ok', cancel: 'rd-rel-cancel',
      out: 'rd-rel-out', snap: 'rd-rel-snap', text: 'rd-rel-confirm-text', label: '放行推進',
      path: '/api/release/advance', fields: ['rd-rel-entity', 'rd-rel-target', 'rd-rel-evidence', 'rd-rel-entity-json'],
      summary: function (body, raw) {
        return '將「' + body.entityId + '」推進至 ' + body.target + '（租戶 ' + raw.tenant + '）？';
      },
      build: function (raw) {
        return {
          entityId: String(raw['rd-rel-entity'] || '').trim(),
          target: raw['rd-rel-target'],
          actor: 'readiness-page',
          entity: parseJson(raw['rd-rel-entity-json'], '實體'),
          evidenceOk: !!raw['rd-rel-evidence'],
        };
      },
    });

    bindPost({
      run: 'rd-safe-run', box: 'rd-safe-confirm', ok: 'rd-safe-ok', cancel: 'rd-safe-cancel',
      out: 'rd-safe-out', snap: 'rd-safe-snap', text: 'rd-safe-text', label: '安全評估',
      path: '/api/safety/evaluate', fields: ['rd-safe-kind', 'rd-safe-json'],
      summary: function (body, raw) {
        return '確定執行安全評估（類型 ' + body.kind + '，租戶 ' + raw.tenant + '）？結果僅供參考，不代表已通過認證。';
      },
      build: function (raw) { return { kind: raw['rd-safe-kind'], record: parseJson(raw['rd-safe-json'], '紀錄') }; },
    });

    bindPost({
      run: 'rd-phys-approve-run', box: 'rd-phys-confirm', ok: 'rd-phys-approve-ok', cancel: 'rd-phys-approve-cancel',
      out: 'rd-phys-out', snap: 'rd-phys-snap', text: 'rd-phys-text', label: '核准申請',
      path: '/api/physical-os/approve', fields: ['rd-phys-entity', 'rd-phys-kind'],
      summary: function (body, raw) {
        return '確定送出核准申請（' + body.entityId + ' / ' + body.kind + '，租戶 ' + raw.tenant + '）？狀態為 WAITING_APPROVAL，不會啟動現場機台。';
      },
      build: function (raw) {
        return {
          entityId: String(raw['rd-phys-entity'] || '').trim(),
          kind: String(raw['rd-phys-kind'] || '').trim(),
          actor: 'readiness-page',
        };
      },
    });

    bindPost({
      run: 'rd-com-run', box: 'rd-com-confirm', ok: 'rd-com-ok', cancel: 'rd-com-cancel',
      out: 'rd-com-out', snap: 'rd-com-snap', text: 'rd-com-confirm-text', label: '匯入',
      path: '/api/commerce/import', fields: ['rd-com-kind', 'rd-com-source', 'rd-com-rows'],
      summary: function (body, raw) {
        return '將 ' + body.rows.length + ' 列匯入至 ' + body.kind + '（來源 ' + body.source + '，租戶 ' + raw.tenant + '）？';
      },
      build: function (raw) {
        var rows = parseJson(raw['rd-com-rows'], '資料列');
        if (!Array.isArray(rows)) {
          showNotice('資料列必須是 JSON 陣列', true);
          throw new Error('rows');
        }
        return { kind: raw['rd-com-kind'], source: raw['rd-com-source'], rows: rows };
      },
      after: loadKpi,
    });

    window.addEventListener('hashchange', focusHash);
    focusHash();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
