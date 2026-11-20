// /admin/kd#structures — packaging engineering checks (V2 API).
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var DEFAULT_TENANT = 'sonaqueen-home';

  function tenant() {
    var v = ($('kd-tenant') && $('kd-tenant').value || '').trim();
    return v || DEFAULT_TENANT;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function apiPost(path, body) {
    return fetch(path, {
      method: 'POST',
      headers: {
        'X-Tenant-Id': tenant(),
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = { raw: t }; }
        return { ok: r.ok, status: r.status, json: j };
      });
    }, function () {
      return { ok: false, status: 0, json: { detail: '網路錯誤' } };
    });
  }

  function apiGet(path) {
    return fetch(path, {
      method: 'GET',
      headers: { 'X-Tenant-Id': tenant(), Accept: 'application/json' },
    }).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = { raw: t }; }
        return { ok: r.ok, status: r.status, json: j };
      });
    }, function () {
      return { ok: false, status: 0, json: { detail: '網路錯誤' } };
    });
  }

  function setMsg(id, text, failed) {
    var node = $(id);
    if (!node) return;
    node.textContent = text || '';
    node.classList.toggle('kd-err', !!failed);
  }

  function withButtonLock(btn, form, fn) {
    if (!btn || btn.disabled) return;
    btn.disabled = true;
  if (form) {
      form.querySelectorAll('input, select, textarea, button').forEach(function (c) {
        if (c !== btn) c.disabled = true;
      });
    }
    fn().finally(function () {
      btn.disabled = false;
      if (form) {
        form.querySelectorAll('input, select, textarea, button').forEach(function (c) {
          c.disabled = false;
        });
      }
    });
  }

  function fillGradeSelect(sel) {
    if (!sel) return;
    apiGet('/api/packaging/v2/board-grades').then(function (r) {
      if (!r.ok || !r.json || !r.json.items) {
        setMsg('kdp-compress-msg', '無法載入紙板等級', true);
        return;
      }
      sel.textContent = '';
      r.json.items.forEach(function (row) {
        var opt = document.createElement('option');
        opt.value = row.sku;
        opt.textContent = row.sku + ' (ECT ' + (row.ectLbIn != null ? row.ectLbIn : '?') + ')';
        sel.appendChild(opt);
      });
    });
  }

  function renderCompress(r) {
    var pre = $('kdp-compress-out');
    if (!pre) return;
    if (!r.ok) {
      pre.hidden = true;
      var detail = r.json && r.json.detail;
      setMsg('kdp-compress-msg', '計算失敗：' + (detail ? String(detail) : 'HTTP ' + r.status), true);
      return;
    }
    var comp = r.json.compression || {};
    var stack = r.json.stack;
    var lines = [
      '允許載重 N：' + (comp.allowableNewton != null ? comp.allowableNewton : '—'),
      'BCT N：' + (comp.bctNewton != null ? comp.bctNewton : '—'),
      '來源：' + (comp.source || '—'),
    ];
    if (stack) {
      lines.push('堆疊頂載 N：' + stack.topLoadNewton);
      lines.push('餘裕 N：' + stack.marginNewton);
      lines.push(stack.ok ? '堆疊：通過（工程試算）' : '堆疊：未通過（工程試算）');
    }
    pre.textContent = lines.join('\n');
    pre.hidden = false;
    setMsg('kdp-compress-msg', stack && !stack.ok ? '抗壓計算完成，堆疊未通過' : '抗壓計算完成', stack && !stack.ok);
  }

  function renderDieline(r) {
    var list = $('kdp-dieline-issues');
    if (!list) return;
    list.textContent = '';
    if (!r.ok) {
      list.hidden = true;
      var detail = r.json && r.json.detail;
      setMsg('kdp-dieline-msg', '檢查失敗：' + (detail ? String(detail) : 'HTTP ' + r.status), true);
      return;
    }
    var errs = (r.json && r.json.errors) || [];
    if (r.json && r.json.ok) {
      setMsg('kdp-dieline-msg', '刀模檢查通過', false);
      list.hidden = true;
      return;
    }
    setMsg('kdp-dieline-msg', '刀模檢查未通過', true);
    errs.forEach(function (e) {
      list.appendChild(el('li', 'kdp-fail', String(e)));
    });
    list.hidden = !errs.length;
  }

  function renderOptimize(r) {
    var table = $('kdp-opt-table');
    var tbody = $('kdp-opt-tbody');
    if (!table || !tbody) return;
    tbody.textContent = '';
    if (!r.ok) {
      table.hidden = true;
      var detail = r.json && r.json.detail;
      setMsg('kdp-opt-msg', '最佳化失敗：' + (detail ? String(detail) : 'HTTP ' + r.status), true);
      return;
    }
    var rows = (r.json && r.json.candidates) || [];
    rows.forEach(function (row) {
      var tr = document.createElement('tr');
      tr.appendChild(el('td', null, row.family));
      tr.appendChild(el('td', null, row.boardAreaMm2 != null ? String(row.boardAreaMm2) : '—'));
      tr.appendChild(el('td', null, row.cbm != null ? String(row.cbm) : '—'));
      tr.appendChild(el('td', null, row.compressionMargin != null ? String(row.compressionMargin) : '—'));
      var vetoTd = el('td');
      vetoTd.textContent = row.engineeringVeto ? '是' : '否';
      if (row.engineeringVeto) vetoTd.className = 'kd-err';
      tr.appendChild(vetoTd);
      tr.appendChild(el('td', null, row.score != null ? String(row.score) : '—'));
      tbody.appendChild(tr);
    });
    table.hidden = !rows.length;
    var chosen = r.json && r.json.chosen;
    var hint = chosen && chosen.family ? '建議盒型：' + chosen.family + '（工程試算）' : '無可用候選';
    setMsg('kdp-opt-msg', hint, false);
  }

  function wireForms() {
    var compressForm = $('kdp-compress-form');
    var compressBtn = $('kdp-compress-btn');
    if (compressForm) {
      compressForm.addEventListener('submit', function (ev) {
        ev.preventDefault();
        withButtonLock(compressBtn, compressForm, function () {
          var body = {
            grade: $('kdp-grade').value,
            safetyFactor: parseFloat($('kdp-sf').value) || 3,
            inner: {
              length: parseFloat($('kdp-len').value),
              width: parseFloat($('kdp-wid').value),
              height: parseFloat($('kdp-hgt').value),
            },
            productWeightKg: parseFloat($('kdp-weight').value),
            stackCount: parseInt($('kdp-stack').value, 10),
          };
          return apiPost('/api/packaging/v2/compression', body).then(renderCompress);
        });
      });
    }

    var dieForm = $('kdp-dieline-form');
    var dieBtn = $('kdp-dieline-btn');
    if (dieForm) {
      dieForm.addEventListener('submit', function (ev) {
        ev.preventDefault();
        withButtonLock(dieBtn, dieForm, function () {
          var raw = ($('kdp-dieline-json').value || '').trim();
          var parsed;
          try {
            parsed = JSON.parse(raw || '{}');
          } catch (e) {
            setMsg('kdp-dieline-msg', 'JSON 格式錯誤', true);
            $('kdp-dieline-issues').hidden = true;
            return Promise.resolve();
          }
          return apiPost('/api/packaging/v2/dieline/validate', parsed).then(renderDieline);
        });
      });
    }

    var optForm = $('kdp-opt-form');
    var optBtn = $('kdp-opt-btn');
    if (optForm) {
      optForm.addEventListener('submit', function (ev) {
        ev.preventDefault();
        withButtonLock(optBtn, optForm, function () {
          var body = {
            grade: $('kdp-opt-grade').value,
            product: {
              width: parseFloat($('kdp-opt-w').value),
              height: parseFloat($('kdp-opt-h').value),
              depth: parseFloat($('kdp-opt-d').value),
            },
            weightKg: parseFloat($('kdp-opt-weight').value),
          };
          return apiPost('/api/packaging/v2/carton-optimize', body).then(renderOptimize);
        });
      });
    }
  }

  function boot() {
    fillGradeSelect($('kdp-grade'));
    fillGradeSelect($('kdp-opt-grade'));
    wireForms();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();