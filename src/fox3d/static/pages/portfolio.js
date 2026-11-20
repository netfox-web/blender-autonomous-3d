// /admin/portfolio — KD SKU portfolio planning UI
(function () {
  'use strict';
  var DEFAULT_TENANT = 'sonaqueen-home';
  var state = {
    portfolioId: null,
    rankingId: null,
    approvalId: null,
    approvalCandidateId: null,
    selectedCandidate: null,
    confirmOpen: false,
    inflight: {},
  };

  function $(id) { return document.getElementById(id); }

  function tenant() {
    var v = ($('po-tenant') && $('po-tenant').value || '').trim();
    return v || DEFAULT_TENANT;
  }

  function headers(json, tenantId) {
    var tid = (tenantId != null && String(tenantId).trim()) ? String(tenantId).trim() : tenant();
    var h = { 'X-Tenant-Id': tid, Accept: 'application/json' };
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }

  function showBanner(text, ok) {
    var b = $('po-banner');
    if (!b) return;
    if (!text) { b.hidden = true; b.textContent = ''; b.className = 'po-banner'; return; }
    b.hidden = false;
    b.textContent = text;
    b.className = 'po-banner' + (ok ? ' ok' : '');
  }

  function setInflight(key, on) {
    state.inflight[key] = on;
  }

  function api(path, options) {
    var opts = options || {};
    return fetch(path, {
      method: opts.method || 'GET',
      headers: headers(Boolean(opts.body), opts.tenantId),
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      return r.text().then(function (t) {
        var body;
        try { body = t ? JSON.parse(t) : null; } catch (e) { body = t; }
        return { status: r.status, ok: r.ok, body: body, raw: t };
      });
    });
  }

  function fmtMoney(v) {
    if (v == null || v === '') return '—';
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return n.toFixed(0);
  }

  function clearApprovalForSelectionChange() {
    if (!state.approvalId) {
      updateActionButtons();
      return;
    }
    if (state.approvalCandidateId !== state.selectedCandidate) {
      state.approvalId = null;
      state.approvalCandidateId = null;
    }
    updateActionButtons();
  }

  function confirmDialog(title, text) {
    return new Promise(function (resolve) {
      if (state.confirmOpen) { resolve(false); return; }
      var dlg = $('po-confirm');
      if (!dlg || !dlg.showModal) {
        resolve(window.confirm(title + '\n' + text));
        return;
      }
      state.confirmOpen = true;
      dlg.returnValue = '';
      $('po-confirm-title').textContent = title;
      $('po-confirm-text').textContent = text;
      function finish(ok) {
        dlg.removeEventListener('close', onClose);
        $('po-confirm-cancel').removeEventListener('click', onCancel);
        state.confirmOpen = false;
        resolve(ok);
      }
      function onClose() { finish(dlg.returnValue === 'ok'); }
      function onCancel() { dlg.close('cancel'); }
      dlg.addEventListener('close', onClose);
      $('po-confirm-cancel').addEventListener('click', onCancel);
      dlg.showModal();
    });
  }

  function renderCandidates(items) {
    var wrap = $('po-candidates-wrap');
    if (!wrap) return;
    wrap.textContent = '';
    if (!items || !items.length) {
      var p = document.createElement('p');
      p.className = 'po-muted';
      p.textContent = '尚無候選，請先建立需求並產生候選。';
      wrap.appendChild(p);
      return;
    }
    items.forEach(function (c) {
      var card = document.createElement('article');
      card.className = 'po-card';
      card.dataset.id = c.candidateId;
      if (state.selectedCandidate === c.candidateId) card.classList.add('selected');
      var h = document.createElement('h4');
      h.textContent = (c.kind || '?') + ' · ' + (c.candidateId || '').slice(0, 8);
      card.appendChild(h);
      var dfm = (c.dfm || {});
      var comm = (c.commercial || {});
      var lines = [
        'DFM：' + (dfm.ok ? '通過' : '未通過'),
        '利用率：' + (dfm.utilization != null ? Number(dfm.utilization).toFixed(3) : '—'),
        '成本：' + fmtMoney(comm.landedCost) + (comm.stale ? '（過期）' : ''),
        '狀態：' + (c.state || '—'),
      ];
      lines.forEach(function (txt) {
        var p = document.createElement('p');
        p.textContent = txt;
        card.appendChild(p);
      });
      card.addEventListener('click', function () {
        state.selectedCandidate = c.candidateId;
        clearApprovalForSelectionChange();
        Array.prototype.forEach.call(wrap.querySelectorAll('.po-card'), function (el) {
          el.classList.toggle('selected', el.dataset.id === state.selectedCandidate);
        });
        showDetail(c);
      });
      wrap.appendChild(card);
    });
  }

  function renderRanking(ranking) {
    var table = $('po-ranking-table');
    if (!table || !table.tBodies[0]) return;
    var tb = table.tBodies[0];
    tb.textContent = '';
    var rows = (ranking && ranking.top10) || [];
    if (!rows.length) {
      var tr0 = document.createElement('tr');
      var td0 = document.createElement('td');
      td0.colSpan = 8;
      td0.className = 'po-muted';
      td0.textContent = '尚無排名，請先計算排名。';
      tr0.appendChild(td0);
      tb.appendChild(tr0);
      return;
    }
    rows.forEach(function (row, idx) {
      var tr = document.createElement('tr');
      function td(text) {
        var c = document.createElement('td');
        c.textContent = text == null ? '' : String(text);
        tr.appendChild(c);
      }
      td(String(idx + 1));
      td(row.candidateId);
      td(row.kind);
      td(row.score != null ? Number(row.score).toFixed(4) : '—');
      td(row.conservationOk ? 'OK' : '—');
      td(fmtMoney(row.landedCost));
      var stateLabel = row.state || '—';
      if (row.valid === false) stateLabel += '（排除）';
      td(stateLabel);
      var act = document.createElement('td');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'po-btn';
      btn.textContent = '改排';
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        openOverride(row.candidateId);
      });
      act.appendChild(btn);
      tr.appendChild(act);
      tr.addEventListener('click', function () {
        state.selectedCandidate = row.candidateId;
        clearApprovalForSelectionChange();
      });
      tb.appendChild(tr);
    });
    var meta = $('po-ranking-meta');
    if (meta) {
      meta.textContent = ranking.demandReal === false ? '（需求為估計值）' : '';
    }
    var staleHint = $('po-stale-hint');
    var hints = (ranking && ranking.staleCostHints) || [];
    if (staleHint) {
      staleHint.hidden = !hints.length;
      if (hints.length) staleHint.textContent = '部分候選成本快照已過期：' + hints.join(', ');
    }
  }

  function showDetail(obj) {
    var box = $('po-detail');
    var pre = $('po-detail-pre');
    if (!box || !pre) return;
    box.hidden = false;
    try { pre.textContent = JSON.stringify(obj, null, 2); } catch (e) { pre.textContent = String(obj); }
  }

  function updateActionButtons() {
    var hasIntent = Boolean(state.portfolioId);
    $('po-generate').disabled = !hasIntent || state.inflight.generate;
    $('po-plan').disabled = !hasIntent || state.inflight.plan;
    $('po-rank').disabled = !hasIntent || state.inflight.rank;
    $('po-submit-approval').disabled = !state.selectedCandidate || state.inflight.submit;
    var canApprove = Boolean(
      state.approvalId
      && state.approvalCandidateId
      && state.selectedCandidate === state.approvalCandidateId
    );
    $('po-approve').disabled = !canApprove || state.inflight.approve;
    $('po-supersede').disabled = !state.selectedCandidate || state.inflight.supersede;
  }

  function refreshCandidates() {
    if (!state.portfolioId) return Promise.resolve();
    return api('/api/portfolio/intents/' + encodeURIComponent(state.portfolioId) + '/candidates')
      .then(function (res) {
        if (!res.ok) throw new Error((res.body && res.body.detail) || '載入候選失敗');
        renderCandidates(res.body.items || []);
      });
  }

  function openOverride(candidateId) {
    var dlg = $('po-override-dialog');
    if (!dlg) return;
    dlg.returnValue = '';
    $('po-override-candidate').value = candidateId;
    $('po-override-actor').value = 'planner';
    $('po-override-reason').value = '';
    $('po-override-actor').readOnly = false;
    $('po-override-reason').readOnly = false;
    $('po-override-snapshot').hidden = true;
    $('po-override-snapshot').textContent = '';
    dlg.showModal();
  }

  function bindOverrideDialog() {
    var dlg = $('po-override-dialog');
  var form = $('po-override-form');
    if (!dlg || !form) return;
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (!state.rankingId) { showBanner('尚無排名可改排'); return; }
      var actor = $('po-override-actor').value.trim();
      var reason = $('po-override-reason').value.trim();
      if (!actor || !reason) { showBanner('請填寫操作者與原因'); return; }
      var snap = document.createElement('p');
      snap.textContent = '快照：' + actor + ' / ' + reason;
      $('po-override-snapshot').textContent = snap.textContent;
      $('po-override-snapshot').hidden = false;
      $('po-override-actor').readOnly = true;
      $('po-override-reason').readOnly = true;
      var btn = $('po-override-ok');
      btn.disabled = true;
      api('/api/portfolio/rankings/' + encodeURIComponent(state.rankingId) + '/override', {
        method: 'POST',
        body: { actor: actor, reason: reason, candidateId: $('po-override-candidate').value.trim() },
      }).then(function (res) {
        btn.disabled = false;
        dlg.close('ok');
        if (!res.ok) {
          showBanner((res.body && res.body.detail) || '改排失敗');
          return;
        }
        showBanner('排名已依人工改排更新', true);
        renderRanking(res.body);
      }).catch(function () {
        btn.disabled = false;
        showBanner('連線失敗，請重試');
      });
    });
    dlg.addEventListener('close', function () {
      $('po-override-actor').readOnly = false;
      $('po-override-reason').readOnly = false;
    });
    var cancelBtn = $('po-override-cancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        dlg.close('cancel');
      });
    }
  }

  function wire() {
    var intentForm = $('po-intent-form');
    if (intentForm) {
      intentForm.addEventListener('submit', function (ev) {
        ev.preventDefault();
        if (state.inflight.intent) return;
        setInflight('intent', true);
        var btn = $('po-create-intent');
        btn.disabled = true;
        api('/api/portfolio/intents', {
          method: 'POST',
          body: {
            segment: $('po-segment').value,
            demandSource: $('po-demand-source').value,
            actor: 'planner',
          },
        }).then(function (res) {
          setInflight('intent', false);
          btn.disabled = false;
          if (!res.ok) {
            showBanner((res.body && res.body.detail) || '建立需求失敗');
            return;
          }
          state.portfolioId = res.body.portfolioId;
          state.rankingId = null;
          state.approvalId = null;
          state.approvalCandidateId = null;
          state.selectedCandidate = null;
          $('po-intent-status').textContent = '需求 ID：' + state.portfolioId;
          showBanner('已建立組合需求', true);
          updateActionButtons();
          showDetail(res.body);
        }).catch(function () {
          setInflight('intent', false);
          btn.disabled = false;
          showBanner('連線失敗');
        });
      });
    }

    $('po-generate') && $('po-generate').addEventListener('click', function () {
      if (!state.portfolioId || state.inflight.generate) return;
      setInflight('generate', true);
      $('po-generate').disabled = true;
      api('/api/portfolio/intents/' + encodeURIComponent(state.portfolioId) + '/candidates', { method: 'POST' })
        .then(function (res) {
          setInflight('generate', false);
          updateActionButtons();
          if (!res.ok) {
            showBanner((res.body && res.body.detail) || '產生候選失敗');
            return;
          }
          showBanner('已產生 ' + (res.body.count || 0) + ' 個候選', true);
          return refreshCandidates();
        }).catch(function () {
          setInflight('generate', false);
          updateActionButtons();
          showBanner('連線失敗');
        });
    });

    $('po-plan') && $('po-plan').addEventListener('click', function () {
      if (!state.portfolioId || state.inflight.plan) return;
      setInflight('plan', true);
      $('po-plan').disabled = true;
      api('/api/portfolio/intents/' + encodeURIComponent(state.portfolioId) + '/material-plan', {
        method: 'POST',
        body: {},
      }).then(function (res) {
        setInflight('plan', false);
        updateActionButtons();
        if (!res.ok) {
          showBanner((res.body && res.body.detail) || '用料規劃失敗');
          return;
        }
        showBanner('用料規劃完成', true);
        showDetail(res.body);
      }).catch(function () {
        setInflight('plan', false);
        updateActionButtons();
        showBanner('連線失敗');
      });
    });

    $('po-rank') && $('po-rank').addEventListener('click', function () {
      if (!state.portfolioId || state.inflight.rank) return;
      setInflight('rank', true);
      $('po-rank').disabled = true;
      api('/api/portfolio/intents/' + encodeURIComponent(state.portfolioId) + '/rankings', {
        method: 'POST',
        body: {},
      }).then(function (res) {
        setInflight('rank', false);
        updateActionButtons();
        if (!res.ok) {
          showBanner((res.body && res.body.detail) || '排名失敗');
          return;
        }
        state.rankingId = res.body.rankingId;
        if (res.body.demandReal === false) {
          $('po-demand-label').textContent = res.body.demandEstimateLabel || '需求為估計值';
        }
        renderRanking(res.body);
        showBanner('排名完成', true);
        return refreshCandidates();
      }).catch(function () {
        setInflight('rank', false);
        updateActionButtons();
        showBanner('連線失敗');
      });
    });

    $('po-submit-approval') && $('po-submit-approval').addEventListener('click', function () {
      if (!state.selectedCandidate || state.inflight.submit) return;
      var submitSnap = {
        candidateId: state.selectedCandidate,
        portfolioId: state.portfolioId,
        tenant: tenant(),
      };
      setInflight('submit', true);
      $('po-submit-approval').disabled = true;
      api('/api/portfolio/candidates/' + encodeURIComponent(submitSnap.candidateId) + '/submit-approval', {
        method: 'POST',
        body: { actor: 'pm' },
        tenantId: submitSnap.tenant,
      }).then(function (res) {
        setInflight('submit', false);
        updateActionButtons();
        if (!res.ok) {
          showBanner((res.body && res.body.detail) || '送審失敗');
          return;
        }
        if (
          submitSnap.candidateId !== state.selectedCandidate
          || submitSnap.portfolioId !== state.portfolioId
          || submitSnap.tenant !== tenant()
        ) {
          showBanner('送審已完成，但畫面已切換；請在正確候選或需求上重新送審');
          return;
        }
        state.approvalId = res.body.approvalId;
        state.approvalCandidateId = submitSnap.candidateId;
        showBanner('已送審', true);
        updateActionButtons();
        showDetail(res.body);
      }).catch(function () {
        setInflight('submit', false);
        updateActionButtons();
        showBanner('連線失敗');
      });
    });

    $('po-approve') && $('po-approve').addEventListener('click', function () {
      if (!state.approvalId || !state.approvalCandidateId || state.inflight.approve) return;
      if (state.approvalCandidateId !== state.selectedCandidate) {
        showBanner('核准對象與目前選取候選不一致，請重新送審');
        return;
      }
      var approveSnap = {
        approvalId: state.approvalId,
        candidateId: state.approvalCandidateId,
        tenant: tenant(),
      };
      var confirmText = [
        '核准 ID：' + approveSnap.approvalId,
        '候選：' + approveSnap.candidateId,
        '租戶：' + approveSnap.tenant,
        '此操作需要確認，且同一核准只會生效一次。',
      ].join('\n');
      confirmDialog('核准原型', confirmText).then(function (ok) {
        if (!ok) return;
        setInflight('approve', true);
        $('po-approve').disabled = true;
        api('/api/portfolio/approvals/' + encodeURIComponent(approveSnap.approvalId) + '/approve', {
          method: 'POST',
          body: { confirm: true, actor: 'pm', reason: 'ui-approve' },
          tenantId: approveSnap.tenant,
        }).then(function (res) {
          setInflight('approve', false);
          updateActionButtons();
          if (!res.ok) {
            showBanner((res.body && res.body.detail) || '核准失敗');
            return;
          }
          if (res.body.status === 'APPROVED_FOR_PROTOTYPE') {
            showBanner('原型已核准', true);
          } else {
            showBanner('核准未完成');
          }
          showDetail(res.body);
        }).catch(function () {
          setInflight('approve', false);
          updateActionButtons();
          showBanner('連線失敗');
        });
      });
    });

    $('po-supersede') && $('po-supersede').addEventListener('click', function () {
      if (!state.selectedCandidate || state.inflight.supersede) return;
      setInflight('supersede', true);
      $('po-supersede').disabled = true;
      api('/api/portfolio/candidates/' + encodeURIComponent(state.selectedCandidate) + '/supersede', {
        method: 'POST',
      }).then(function (res) {
        setInflight('supersede', false);
        updateActionButtons();
        if (!res.ok) {
          showBanner((res.body && res.body.detail) || '作廢失敗');
          return;
        }
        showBanner('候選已作廢', true);
        refreshCandidates();
      }).catch(function () {
        setInflight('supersede', false);
        updateActionButtons();
        showBanner('連線失敗');
      });
    });

    $('po-refresh') && $('po-refresh').addEventListener('click', function () {
      showBanner('');
      if (state.portfolioId) refreshCandidates();
    });

    bindOverrideDialog();
    updateActionButtons();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();