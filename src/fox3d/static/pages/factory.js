// /admin/factory: 工廠報價與改版＋商品研發產生 (#rd)
(function () {
  'use strict';

  var TYPE_LABELS = {
    WARDROBE: '衣櫃',
    SHOE_CABINET: '鞋櫃',
    TV_CABINET: '電視櫃',
    BOOKCASE: '書櫃',
    STORAGE_CABINET: '收納櫃',
    DISPLAY_CABINET: '展示櫃',
    KITCHEN_BASE: '廚下櫃（地櫃）',
    KITCHEN_WALL: '廚房吊櫃',
    CABINET: '標準櫃體'
  };

  var BREAKDOWN_LABELS = {
    SheetCost: ['板材費用', '依排版張數與板材單價計算'],
    SheetWasteCost: ['板材廢料耗損', '不可重用廢料面積折算'],
    RemnantCredit: ['可用餘料折抵', '可回收餘料面積折抵（負項）'],
    EdgeBandingCost: ['封邊材料費', '依封邊總長度計算'],
    HardwareCost: ['五金配件費', '鉸鍊、滑軌、偏心輪、木榫、把手等'],
    CuttingCost: ['裁切加工費', '依板件數量計算'],
    DrillingCost: ['鑽孔加工費', '依排鑽／鉸鍊孔位數計算'],
    ProcessingCost: ['加工費小計', '裁切＋鑽孔＋封邊加工合計'],
    AssemblyCost: ['組裝工時費', '依櫃體體積估算組裝工時'],
    PackagingCost: ['包裝材料費', '基本包材與體積加成'],
    MaterialCost: ['板材與封邊費', '板材面積與封邊合計'],
    ShippingEstimate: ['預估運費', '依體積估算運送費用']
  };

  var state = {
    productTypeCodes: [],
    productTypes: [],
    spaces: [],
    runs: [],
    quotes: [],
    products: [],
    revisions: [],
    selectedQuoteId: null,
    selectedQuoteDetail: null,
    lastRdResult: null,
    mockBlender: true
  };

  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] != null) n.setAttribute(k, String(attrs[k]));
    });
    if (text != null) n.textContent = String(text);
    return n;
  }

  function currentTenant() {
    var input = $('fc-tenant');
    var v = input ? input.value.trim() : '';
    return v || 'sonaqueen-home';
  }

  function apiFetch(path, opts) {
    opts = opts || {};
    var headers = Object.assign(
      {
        'X-Tenant-Id': currentTenant(),
        Accept: 'application/json'
      },
      opts.headers || {}
    );
    var fetchOpts = {
      method: opts.method || 'GET',
      headers: headers
    };
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      fetchOpts.body = JSON.stringify(opts.body);
    }
    return fetch(path, fetchOpts).then(function (r) {
      return r.text().then(function (txt) {
        var parsed = null;
        try {
          parsed = txt ? JSON.parse(txt) : {};
        } catch (e) {
          parsed = { raw: txt };
        }
        return { ok: r.ok, status: r.status, data: parsed, raw: txt };
      });
    });
  }

  function formatMoney(v) {
    if (v == null || isNaN(Number(v))) return '—';
    return 'NT$ ' + Number(v).toLocaleString('zh-TW', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function truthBadgeInfo(label) {
    var s = String(label || '').toUpperCase();
    if (!s || s === 'SKIPPED') {
      return { cls: 'neutral', text: 'SKIPPED（未要求算圖）' };
    }
    if (s === 'MOCK' || s === 'MOCK_READY') {
      return { cls: 'warn', text: s + '（模擬資料，非真實算圖）' };
    }
    if (s.indexOf('BLOCKED') === 0) {
      return { cls: 'err', text: s + '（主機環境受阻）' };
    }
    if (s === 'PARTIAL') {
      return { cls: 'warn', text: 'PARTIAL（部分完成）' };
    }
    if (s === 'WAITING_APPROVAL') {
      return { cls: 'warn', text: 'WAITING_APPROVAL（待人工核准）' };
    }
    if (s === 'APPROVED') {
      return { cls: 'ok', text: 'APPROVED（已核准製造候選）' };
    }
    if (s === 'REAL') {
      return { cls: 'ok', text: 'REAL（真實輸出）' };
    }
    return { cls: 'neutral', text: s };
  }

  function makeBadge(label) {
    var info = truthBadgeInfo(label);
    return el('span', { 'class': 'fc-badge ' + info.cls }, info.text);
  }

  function showGlobalAlert(msg, kind) {
    var box = $('fc-global-status');
    if (!box) return;
    box.hidden = false;
    box.className = 'fc-alert ' + (kind || 'ok');
    box.textContent = msg;
  }

  function renderApiAnswer(box, title, res) {
    if (!box) return;
    box.hidden = false;
    box.textContent = '';
    var head = el('div', { 'class': 'fc-card-top' });
    head.appendChild(el('strong', null, title));
    head.appendChild(
      el(
        'span',
        { 'class': 'fc-badge ' + (res.ok ? 'ok' : 'err') },
        'HTTP ' + res.status
      )
    );
    box.appendChild(head);
    var details = el('details', { 'class': 'fc-details' });
    details.open = !res.ok;
    details.appendChild(el('summary', null, '檢視 API 回應內容（JSON）'));
    var bodyText = '';
    try {
      bodyText = JSON.stringify(res.data, null, 2);
    } catch (e) {
      bodyText = String(res.raw || '');
    }
    if (bodyText.length > 16000) {
      bodyText = bodyText.slice(0, 16000) + '\n…（已截斷）';
    }
    details.appendChild(el('pre', null, bodyText));
    box.appendChild(details);
  }

  // ---- 1. 商品類型清單 ----------------------------------------------------
  function renderProductTypes() {
    var stateEl = $('fc-types-state');
    var wrapEl = $('fc-types-wrap');
    var tbody = $('fc-types-tbody');
    var checkContainer = $('run-types-checks');
    tbody.textContent = '';

    var list = state.productTypes.length
      ? state.productTypes
      : state.productTypeCodes.map(function (c) {
          return {
            code: c,
            label: TYPE_LABELS[c] || c,
            defaultWidth: '—',
            defaultHeight: '—',
            defaultDepth: '—',
            doorCount: 0,
            shelfCount: 0,
            drawerCount: 0,
            legs: false,
            plinthHeight: 0
          };
        });

    if (!list.length) {
      stateEl.hidden = false;
      stateEl.textContent = '目前沒有可用的商品類型資料。';
      wrapEl.hidden = true;
      return;
    }

    stateEl.hidden = true;
    wrapEl.hidden = false;

    var existingChecked = {};
    Array.prototype.forEach.call(
      checkContainer.querySelectorAll('input[type="checkbox"]'),
      function (cb) {
        existingChecked[cb.value] = cb.checked;
      }
    );
    var hasExisting = Object.keys(existingChecked).length > 0;
    checkContainer.textContent = '';

    list.forEach(function (item) {
      var code = item.code;
      var label = item.label || TYPE_LABELS[code] || code;
      var tr = el('tr');
      tr.appendChild(el('td', null, label));
      var tdCode = el('td');
      tdCode.appendChild(el('code', null, code));
      tr.appendChild(tdCode);
      tr.appendChild(
        el(
          'td',
          null,
          item.defaultWidth + ' × ' + item.defaultHeight + ' × ' + item.defaultDepth
        )
      );
      tr.appendChild(
        el(
          'td',
          null,
          '門 ' + item.doorCount + ' / 層 ' + item.shelfCount + ' / 抽 ' + item.drawerCount
        )
      );
      tr.appendChild(
        el(
          'td',
          null,
          (item.legs ? '有腳座' : '無腳座') +
            (item.plinthHeight ? '（高 ' + item.plinthHeight + 'mm）' : '')
        )
      );

      var tdAct = el('td');
      var actWrap = el('div', { 'class': 'fc-actions' });
      var btnRun = el('button', { type: 'button', 'class': 'fc-btn small secondary' }, '加入排櫃');
      btnRun.addEventListener('click', function () {
        var cb = checkContainer.querySelector('input[value="' + code + '"]');
        if (cb) cb.checked = true;
        $('space-run').scrollIntoView({ behavior: 'smooth', block: 'start' });
        showGlobalAlert('已勾選「' + label + ' (' + code + ')」參與空間排櫃。', 'ok');
      });
      var btnRd = el('button', { type: 'button', 'class': 'fc-btn small secondary' }, '帶入研發');
      btnRd.addEventListener('click', function () {
        $('rd-text').value =
          '客廳 寬' +
          Math.round((Number(item.defaultWidth) || 800) / 10) +
          'cm 高' +
          Math.round((Number(item.defaultHeight) || 1800) / 10) +
          'cm 白木紋' +
          label +
          ' 雙門';
        location.hash = 'rd';
        $('rd').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      actWrap.appendChild(btnRun);
      actWrap.appendChild(btnRd);
      tdAct.appendChild(actWrap);
      tr.appendChild(tdAct);
      tbody.appendChild(tr);

      // Checkbox in factory run form
      var chkLabel = el('label', { 'class': 'fc-check-item' });
      var chk = el('input', { type: 'checkbox', value: code });
      chk.checked = hasExisting
        ? Boolean(existingChecked[code])
        : ['STORAGE_CABINET', 'WARDROBE', 'BOOKCASE'].indexOf(code) >= 0;
      chkLabel.appendChild(chk);
      chkLabel.appendChild(el('span', null, label));
      checkContainer.appendChild(chkLabel);
    });
  }

  // ---- 2. 空間清單與排櫃 ---------------------------------------------------
  function renderSpaces() {
    var emptyEl = $('fc-spaces-empty');
    var wrapEl = $('fc-spaces-wrap');
    var tbody = $('fc-spaces-tbody');
    tbody.textContent = '';

    if (!state.spaces.length) {
      emptyEl.hidden = false;
      wrapEl.hidden = true;
      return;
    }

    emptyEl.hidden = true;
    wrapEl.hidden = false;

    state.spaces.forEach(function (sp) {
      var tr = el('tr');
      var tdId = el('td');
      tdId.appendChild(el('code', null, sp.spaceId));
      tr.appendChild(tdId);
      tr.appendChild(el('td', null, sp.width + ' × ' + sp.depth + ' × ' + sp.height));
      tr.appendChild(
        el(
          'td',
          null,
          (sp.walls ? sp.walls.length : 4) + ' 面牆 / ' + (sp.keepOuts ? sp.keepOuts.length : 0) + ' 處避讓'
        )
      );
      var tdSt = el('td');
      tdSt.appendChild(makeBadge(sp.photogrammetryStatus || sp.pipelineStatus || 'MOCK'));
      tr.appendChild(tdSt);

      var tdAct = el('td');
      var btnUse = el('button', { type: 'button', 'class': 'fc-btn small primary' }, '帶入排櫃尺寸');
      btnUse.addEventListener('click', function () {
        $('run-width').value = sp.width;
        $('run-depth').value = sp.depth;
        $('run-height').value = sp.height;
        showGlobalAlert('已將空間 ' + sp.spaceId + ' 尺寸（' + sp.width + '×' + sp.depth + '×' + sp.height + ' mm）帶入排櫃表單。', 'ok');
      });
      tdAct.appendChild(btnUse);
      tr.appendChild(tdAct);
      tbody.appendChild(tr);
    });
  }

  // ---- 3. 報價清單與明細核准 -----------------------------------------------
  function findRunByQuoteId(quoteId) {
    for (var i = 0; i < state.runs.length; i++) {
      var r = state.runs[i];
      if (r.quote && r.quote.quoteId === quoteId) return r;
    }
    return null;
  }

  function renderQuotesList() {
    var emptyEl = $('fc-quotes-empty');
    var wrapEl = $('fc-quotes-wrap');
    var tbody = $('fc-quotes-tbody');
    tbody.textContent = '';

    if (!state.quotes.length) {
      emptyEl.hidden = false;
      wrapEl.hidden = true;
      return;
    }

    emptyEl.hidden = true;
    wrapEl.hidden = false;

    state.quotes.forEach(function (q) {
      var tr = el('tr');
      if (state.selectedQuoteId === q.quoteId) tr.className = 'selected';

      var tdId = el('td');
      tdId.appendChild(el('code', null, q.quoteId));
      tr.appendChild(tdId);

      tr.appendChild(
        el(
          'td',
          null,
          (q.wallName || 'N') + ' 牆 · ' + (q.cabinetCount || 1) + ' 座櫃'
        )
      );
      tr.appendChild(el('td', null, formatMoney(q.estimatedCost)));
      tr.appendChild(el('td', null, formatMoney(q.suggestedPrice)));

      var tdPrev = el('td');
      tdPrev.appendChild(makeBadge(q.previewLabel || 'SKIPPED'));
      tr.appendChild(tdPrev);

      var tdGate = el('td');
      tdGate.appendChild(makeBadge(q.gateStatus || 'WAITING_APPROVAL'));
      tr.appendChild(tdGate);

      var tdAct = el('td');
      var actWrap = el('div', { 'class': 'fc-actions' });
      var btnView = el('button', { type: 'button', 'class': 'fc-btn small primary' }, '查看明細');
      btnView.addEventListener('click', function () {
        loadQuoteDetail(q.quoteId);
      });
      actWrap.appendChild(btnView);
      tdAct.appendChild(actWrap);
      tr.appendChild(tdAct);
      tbody.appendChild(tr);
    });
  }

  function loadQuoteDetail(quoteId) {
    if (!quoteId) return;
    $('qd-empty').hidden = false;
    $('qd-empty').className = 'fc-state';
    $('qd-empty').textContent = '正在讀取報價單 ' + quoteId + ' 明細…';
    $('qd-body').hidden = true;
    $('qd-approve-confirm').hidden = true;

    apiFetch('/api/factory/quotes/' + encodeURIComponent(quoteId)).then(function (res) {
      if (!res.ok) {
        $('qd-empty').hidden = false;
        $('qd-empty').className = 'fc-state error';
        $('qd-empty').textContent = '查詢報價單失敗（HTTP ' + res.status + '）：找不到報價單 ' + quoteId;
        return;
      }
      state.selectedQuoteId = quoteId;
      state.selectedQuoteDetail = res.data;
      renderQuotesList();
      renderQuoteDetailPanel(res.data, res);
    });
  }

  function renderQuoteDetailPanel(quote, apiRes) {
    $('qd-empty').hidden = true;
    $('qd-body').hidden = false;
    $('qd-approve-confirm').hidden = true;

    var run = findRunByQuoteId(quote.quoteId);
    var gateStatus = run && run.gate ? run.gate.status : 'WAITING_APPROVAL';
    var previewLabel = run ? run.previewLabel || 'SKIPPED' : 'SKIPPED';

    var badgeInfo = truthBadgeInfo(gateStatus);
    var badgeEl = $('qd-status-badge');
    badgeEl.className = 'fc-badge ' + badgeInfo.cls;
    badgeEl.textContent = badgeInfo.text;

    var summary = $('qd-summary');
    summary.textContent = '';
    var kvItems = [
      ['報價單號', quote.quoteId],
      ['預估總成本', formatMoney(quote.estimatedCost)],
      ['建議售價', formatMoney(quote.suggestedPrice)],
      ['設定毛利率', Math.round((Number(quote.margin) || 0) * 100) + '%'],
      ['排版張數', (quote.breakdown && quote.breakdown.sheetCount != null ? quote.breakdown.sheetCount : '—') + ' 張'],
      [
        '板材利用率',
        quote.breakdown && quote.breakdown.utilization != null
          ? Math.round(Number(quote.breakdown.utilization) * 1000) / 10 + '%'
          : '—'
      ],
      ['封邊總長', (quote.breakdown && quote.breakdown.edgeBandingLengthM != null ? quote.breakdown.edgeBandingLengthM : '—') + ' m'],
      ['3D 預覽狀態', previewLabel]
    ];
    kvItems.forEach(function (pair) {
      var kv = el('div', { 'class': 'fc-kv' });
      kv.appendChild(el('small', null, pair[0]));
      kv.appendChild(el('b', null, pair[1]));
      summary.appendChild(kv);
    });

    // Breakdown table
    var bTbody = $('qd-breakdown-tbody');
    bTbody.textContent = '';
    var bd = quote.breakdown || {};
    Object.keys(BREAKDOWN_LABELS).forEach(function (k) {
      if (bd[k] === undefined) return;
      var tr = el('tr');
      tr.appendChild(el('td', null, BREAKDOWN_LABELS[k][0] + ' (' + k + ')'));
      tr.appendChild(
        el(
          'td',
          null,
          k === 'RemnantCredit' && Number(bd[k]) > 0 ? '- ' + formatMoney(bd[k]) : formatMoney(bd[k])
        )
      );
      tr.appendChild(el('td', null, BREAKDOWN_LABELS[k][1]));
      bTbody.appendChild(tr);
    });

    // Cabinets in this run
    var runExtra = $('qd-run-extra');
    var cabTbody = $('qd-cabinets-tbody');
    cabTbody.textContent = '';
    if (run && run.assembly && run.assembly.cabinets && run.assembly.cabinets.length) {
      runExtra.hidden = false;
      run.assembly.cabinets.forEach(function (c) {
        var sp = c.spec || {};
        var tr = el('tr');
        var tdCid = el('td');
        tdCid.appendChild(el('code', null, c.cabinetId));
        tr.appendChild(tdCid);
        tr.appendChild(el('td', null, (TYPE_LABELS[c.kind] || c.kind) + ' (' + c.kind + ')'));
        tr.appendChild(el('td', null, c.startMm + ' mm'));
        tr.appendChild(el('td', null, sp.width + ' × ' + sp.height + ' × ' + sp.depth));
        var tdAct = el('td');
        var btnRev = el('button', { type: 'button', 'class': 'fc-btn small secondary' }, '選取改版');
        btnRev.addEventListener('click', function () {
          fillReviseForm({
            productId: c.cabinetId,
            width: sp.width,
            height: sp.height,
            depth: sp.depth,
            doorCount: sp.doorCount,
            shelfCount: sp.shelfCount,
            drawerCount: sp.drawerCount,
            material: sp.material,
            openingStyle: sp.openingStyle,
            topFillerHeight: sp.topFillerHeight,
            sideFillerWidth: sp.sideFillerWidth
          });
          $('revise').scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        tdAct.appendChild(btnRev);
        tr.appendChild(tdAct);
        cabTbody.appendChild(tr);
      });
    } else {
      runExtra.hidden = true;
    }

    // Approve button state
    var btnApprovePrep = $('qd-approve-prepare');
    if (gateStatus === 'APPROVED') {
      btnApprovePrep.disabled = true;
      btnApprovePrep.textContent = '此報價方案已核准（APPROVED）';
    } else {
      btnApprovePrep.disabled = false;
      btnApprovePrep.textContent = '核准此報價方案…';
    }

    if (apiRes) {
      renderApiAnswer($('qd-api-out'), '報價明細查詢結果', apiRes);
    }
  }

  // ---- 4. 櫃體清單與改版 ---------------------------------------------------
  function fillReviseForm(p) {
    if (!p) return;
    $('rv-product-id').value = p.productId || '';
    if (p.width != null) $('rv-width').value = p.width;
    if (p.height != null) $('rv-height').value = p.height;
    if (p.depth != null) $('rv-depth').value = p.depth;
    if (p.doorCount != null) $('rv-doors').value = p.doorCount;
    if (p.shelfCount != null) $('rv-shelves').value = p.shelfCount;
    if (p.drawerCount != null) $('rv-drawers').value = p.drawerCount;
    if (p.material) {
      var mat = String(p.material).toUpperCase();
      if (['WOOD_WHITE', 'WOOD_OAK', 'WOOD_CREAM', 'WOOD_WALNUT', 'WOOD_BLACK'].indexOf(mat) >= 0) {
        $('rv-material').value = mat;
      }
    }
    if (p.openingStyle && ['hinged', 'double'].indexOf(p.openingStyle) >= 0) {
      $('rv-opening').value = p.openingStyle;
    }
    if (p.topFillerHeight != null) $('rv-top-filler').value = p.topFillerHeight;
    if (p.sideFillerWidth != null) $('rv-side-filler').value = p.sideFillerWidth;
    $('rv-confirm-box').hidden = true;
    showGlobalAlert('已載入櫃體 ' + p.productId + ' 至改版表單，請調整尺寸後點擊「送出櫃體改版…」。', 'ok');
  }

  function renderProductsAndRevisions() {
    var pEmpty = $('fc-products-empty');
    var pWrap = $('fc-products-wrap');
    var pTbody = $('fc-products-tbody');
    pTbody.textContent = '';

    if (!state.products.length) {
      pEmpty.hidden = false;
      pWrap.hidden = true;
    } else {
      pEmpty.hidden = true;
      pWrap.hidden = false;
      state.products.forEach(function (p) {
        var tr = el('tr');
        var tdId = el('td');
        tdId.appendChild(el('code', null, p.productId));
        tr.appendChild(tdId);
        tr.appendChild(el('td', null, (p.kindLabel || TYPE_LABELS[p.kind] || p.kind)));
        tr.appendChild(
          el(
            'td',
            null,
            'v' + (p.revision || 1) + (p.parentProductId ? ' (源自 ' + p.parentProductId.slice(0, 8) + '…)' : '')
          )
        );
        tr.appendChild(el('td', null, p.width + ' × ' + p.height + ' × ' + p.depth));
        tr.appendChild(el('td', null, p.doorCount + ' / ' + p.shelfCount + ' / ' + p.drawerCount));
        tr.appendChild(el('td', null, p.material || 'WOOD_WHITE'));
        tr.appendChild(el('td', null, formatMoney(p.estimatedCost)));
        var tdAct = el('td');
        var btnSel = el('button', { type: 'button', 'class': 'fc-btn small primary' }, '選取改版');
        btnSel.addEventListener('click', function () {
          fillReviseForm(p);
        });
        tdAct.appendChild(btnSel);
        tr.appendChild(tdAct);
        pTbody.appendChild(tr);
      });
      if (!$('rv-product-id').value && state.products[0]) {
        $('rv-product-id').value = state.products[0].productId;
      }
    }

    var rEmpty = $('fc-revisions-empty');
    var rWrap = $('fc-revisions-wrap');
    var rTbody = $('fc-revisions-tbody');
    rTbody.textContent = '';

    if (!state.revisions.length) {
      rEmpty.hidden = false;
      rWrap.hidden = true;
    } else {
      rEmpty.hidden = true;
      rWrap.hidden = false;
      state.revisions.forEach(function (rev) {
        var tr = el('tr');
        var tdP = el('td');
        tdP.appendChild(el('code', null, rev.parentProductId));
        tr.appendChild(tdP);
        var tdC = el('td');
        tdC.appendChild(el('code', null, rev.childProductId));
        tr.appendChild(tdC);
        tr.appendChild(el('td', null, 'v' + rev.revision));
        tr.appendChild(
          el(
            'td',
            null,
            String(rev.parentHash || '').slice(0, 8) + ' → ' + String(rev.childHash || '').slice(0, 8)
          )
        );
        rTbody.appendChild(tr);
      });
    }
  }

  // ---- 5. 商品研發產生 (#rd) -----------------------------------------------
  function renderRdResult(rd, apiRes) {
    state.lastRdResult = rd;
    $('rd-empty').hidden = true;
    $('rd-body').hidden = false;

    var approvalStatus = rd.approval && rd.approval.status ? rd.approval.status : 'WAITING_APPROVAL';
    var gateInfo = truthBadgeInfo(approvalStatus);
    var gateBadge = $('rd-gate-badge');
    gateBadge.className = 'fc-badge ' + gateInfo.cls;
    gateBadge.textContent = gateInfo.text;

    var badgesBox = $('rd-truth-badges');
    badgesBox.textContent = '';
    var top0 = rd.top && rd.top[0] ? rd.top[0] : null;
    var judgeLabel = top0 && top0.judge ? top0.judge.label : 'MOCK';
    badgesBox.appendChild(
      el(
        'span',
        { 'class': 'fc-badge ' + (judgeLabel === 'REAL' ? 'ok' : 'warn') },
        '視覺評分來源：' + judgeLabel + (judgeLabel === 'MOCK' ? '（啟發式規則評分）' : '')
      )
    );
    if (rd.parametricRender && rd.parametricRender.job) {
      var pJob = rd.parametricRender.job;
      var rLabel = pJob.realBlender && !pJob.usedMock ? 'REAL' : 'MOCK';
      badgesBox.appendChild(
        el(
          'span',
          { 'class': 'fc-badge ' + (rLabel === 'REAL' ? 'ok' : 'warn') },
          '母版 3D 預覽：' + rLabel + (rLabel === 'MOCK' ? '（模擬算圖）' : '')
        )
      );
    }

    var intentBox = $('rd-intent-summary');
    intentBox.textContent = '';
    var baseSpec = rd.baseSpec || {};
    var kvs = [
      ['研發單號', rd.rdId],
      ['解析櫃型', (TYPE_LABELS[baseSpec.kind] || baseSpec.kind || '—') + ' (' + (baseSpec.kind || '') + ')'],
      ['母版尺寸 (mm)', (baseSpec.width || '—') + ' × ' + (baseSpec.height || '—') + ' × ' + (baseSpec.depth || '—')],
      ['產生／合格變體數', (rd.variantCount || 0) + ' 組 ／ 合格 ' + (rd.scoredCount || 0) + ' 組'],
      ['工程規則檢核', rd.baseReport && rd.baseReport.ok ? '通過 (OK)' : '有工程警告'],
      ['量產放行門檻', rd.HUMAN_APPROVAL_REQUIRED ? '需人工核准' : '標準']
    ];
    kvs.forEach(function (pair) {
      var kv = el('div', { 'class': 'fc-kv' });
      kv.appendChild(el('small', null, pair[0]));
      kv.appendChild(el('b', null, pair[1]));
      intentBox.appendChild(kv);
    });

    var topTbody = $('rd-top-tbody');
    topTbody.textContent = '';
    (rd.top || []).forEach(function (row, idx) {
      var v = row.variant || {};
      var dims = v.dimensions || row.spec || {};
      var q = row.quote || {};
      var j = row.judge || {};
      var tr = el('tr');
      tr.appendChild(el('td', null, '#' + (idx + 1)));
      tr.appendChild(el('td', null, '門 ' + v.door + ' / 層 ' + v.shelf + ' / 抽 ' + v.drawer));
      tr.appendChild(el('td', null, dims.width + ' × ' + dims.height + ' × ' + dims.depth));
      tr.appendChild(el('td', null, (v.material || '') + ' / ' + (v.color || '')));
      tr.appendChild(el('td', null, formatMoney(q.estimatedCost)));
      tr.appendChild(el('td', null, formatMoney(q.suggestedPrice)));
      tr.appendChild(
        el(
          'td',
          null,
          j.overall != null
            ? j.overall + '（視覺 ' + j.visionScore + ' / 工程 ' + j.engineeringScore + '）'
            : '—'
        )
      );
      var tdJ = el('td');
      tdJ.appendChild(makeBadge(j.label || 'MOCK'));
      tr.appendChild(tdJ);
      topTbody.appendChild(tr);
    });

    var actBox = $('rd-base-actions');
    actBox.textContent = '';
    var paramPid =
      rd.parametricRender &&
      rd.parametricRender.parametric &&
      rd.parametricRender.parametric.spec &&
      rd.parametricRender.parametric.spec.productId;
    if (paramPid) {
      var btnToRev = el(
        'button',
        { type: 'button', 'class': 'fc-btn secondary' },
        '將此研發母版（' + paramPid + '）帶入櫃體改版'
      );
      btnToRev.addEventListener('click', function () {
        var sp = rd.parametricRender.parametric.spec;
        fillReviseForm({
          productId: sp.productId,
          width: sp.width,
          height: sp.height,
          depth: sp.depth,
          doorCount: sp.doorCount,
          shelfCount: sp.shelfCount,
          drawerCount: sp.drawerCount,
          material: sp.material
        });
        $('revise').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      actBox.appendChild(btnToRev);
    }

    if (apiRes) {
      renderApiAnswer($('rd-api-out'), '商品研發產生結果', apiRes);
    }
  }

  // ---- 資料載入 ------------------------------------------------------------
  function refreshAll() {
    $('fc-types-state').hidden = false;
    $('fc-types-state').className = 'fc-state';
    $('fc-types-state').textContent = '載入商品類型與工廠資料中…';

    return Promise.all([
      apiFetch('/api/factory/product-types'),
      apiFetch('/api/pages/factory/state')
    ])
      .then(function (results) {
        var typesRes = results[0];
        var stateRes = results[1];

        if (typesRes.ok && typesRes.data && Array.isArray(typesRes.data.items)) {
          state.productTypeCodes = typesRes.data.items;
        }
        if (stateRes.ok && stateRes.data) {
          var d = stateRes.data;
          state.mockBlender = Boolean(d.mockBlender);
          state.productTypes = d.productTypes || [];
          state.spaces = d.spaces || [];
          state.runs = d.runs || [];
          state.quotes = d.quotes || [];
          state.products = d.products || [];
          state.revisions = d.revisions || [];

          var modeBadge = $('fc-mode-badge');
          var blocked = d.probeBlocked || [];
          if (state.mockBlender) {
            modeBadge.className = 'fc-badge warn';
            modeBadge.textContent = '算圖環境：MOCK（模擬預覽模式，非真實 Blender 光追輸出）';
          } else if (blocked.length) {
            modeBadge.className = 'fc-badge warn';
            modeBadge.textContent = '算圖環境：' + blocked.join(', ') + '（排櫃報價與研發計算可正常執行）';
          } else {
            modeBadge.className = 'fc-badge ok';
            modeBadge.textContent = '算圖環境：REAL（Blender／OptiX 就緒）';
          }
        } else if (!typesRes.ok) {
          $('fc-types-state').hidden = false;
          $('fc-types-state').className = 'fc-state error';
          $('fc-types-state').textContent = '載入失敗（HTTP ' + typesRes.status + '）';
          return;
        }

        renderProductTypes();
        renderSpaces();
        renderQuotesList();
        renderProductsAndRevisions();

        if (state.selectedQuoteId) {
          var stillExists = state.quotes.some(function (q) {
            return q.quoteId === state.selectedQuoteId;
          });
          if (stillExists) {
            loadQuoteDetail(state.selectedQuoteId);
          }
        } else if (state.quotes.length) {
          loadQuoteDetail(state.quotes[state.quotes.length - 1].quoteId);
        }
      })
      .catch(function (err) {
        $('fc-types-state').hidden = false;
        $('fc-types-state').className = 'fc-state error';
        $('fc-types-state').textContent = '連線失敗：' + err;
      });
  }

  // ---- Hash 聚焦 (#rd 等) --------------------------------------------------
  function focusHash() {
    var id = '';
    try {
      id = decodeURIComponent(location.hash.slice(1));
    } catch (e) {
      return;
    }
    Array.prototype.forEach.call(document.querySelectorAll('.fc-section.hit'), function (n) {
      n.classList.remove('hit');
    });
    if (!id) return;
    var target = document.getElementById(id);
    if (target) {
      target.classList.add('hit');
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  // ---- 事件綁定 ------------------------------------------------------------
  function bindEvents() {
    try {
      var savedTenant = localStorage.getItem('fox3d.tenant');
      if (savedTenant) $('fc-tenant').value = savedTenant;
    } catch (e) {
      /* storage blocked */
    }

    $('fc-tenant').addEventListener('change', function (e) {
      var v = e.target.value.trim() || 'sonaqueen-home';
      e.target.value = v;
      try {
        localStorage.setItem('fox3d.tenant', v);
      } catch (x) {
        /* storage blocked */
      }
      state.selectedQuoteId = null;
      refreshAll();
    });

    $('fc-reload').addEventListener('click', function () {
      refreshAll();
    });

    window.addEventListener('hashchange', focusHash);

    // 2A. 建立空間確認與送出
    $('sp-prepare-btn').addEventListener('click', function () {
      var w = Number($('sp-width').value) || 3600;
      var d = Number($('sp-depth').value) || 3000;
      var h = Number($('sp-height').value) || 2600;
      $('sp-confirm-msg').textContent =
        '即將為租戶「' +
        currentTenant() +
        '」建立房間空間（寬 ' +
        w +
        ' × 深 ' +
        d +
        ' × 高 ' +
        h +
        ' mm），請確認：';
      $('sp-confirm-box').hidden = false;
    });

    $('sp-confirm-no').addEventListener('click', function () {
      $('sp-confirm-box').hidden = true;
    });

    $('sp-confirm-yes').addEventListener('click', function () {
      var btn = $('sp-confirm-yes');
      btn.disabled = true;
      var payload = {
        width: Number($('sp-width').value) || 3600,
        depth: Number($('sp-depth').value) || 3000,
        height: Number($('sp-height').value) || 2600,
        doors: [
          {
            kind: 'door',
            width: Number($('sp-door-w').value) || 900,
            height: Number($('sp-door-h').value) || 2100,
            startMm: Number($('sp-door-x').value) || 200,
            position: [Number($('sp-door-x').value) || 200, 0]
          }
        ],
        windows: [
          {
            kind: 'window',
            width: Number($('sp-win-w').value) || 1200,
            height: Number($('sp-win-h').value) || 1200,
            sill: Number($('sp-win-sill').value) || 900,
            startMm: 400,
            position: [400, 0]
          }
        ],
        columns: [
          {
            width: Number($('sp-col-w').value) || 200,
            depth: Number($('sp-col-d').value) || 200,
            startMm: 0
          }
        ]
      };

      apiFetch('/api/factory/spaces', { method: 'POST', body: payload })
        .then(function (res) {
          $('sp-confirm-box').hidden = true;
          renderApiAnswer($('sp-result'), '建立空間回應（POST /api/factory/spaces）', res);
          if (res.ok && res.data) {
            $('run-width').value = res.data.width || payload.width;
            $('run-depth').value = res.data.depth || payload.depth;
            $('run-height').value = res.data.height || payload.height;
            showGlobalAlert('已成功建立空間 ' + res.data.spaceId + ' 並同步帶入右側排櫃尺寸。', 'ok');
            return refreshAll();
          } else {
            showGlobalAlert('建立空間失敗（HTTP ' + res.status + '）', 'err');
          }
        })
        .finally(function () {
          btn.disabled = false;
        });
    });

    // 2B. 依空間產生方案與跑報價
    $('run-prepare-btn').addEventListener('click', function () {
      var checked = [];
      Array.prototype.forEach.call(
        $('run-types-checks').querySelectorAll('input[type="checkbox"]:checked'),
        function (cb) {
          checked.push(cb.value);
        }
      );
      if (!checked.length) {
        showGlobalAlert('請至少勾選一項參與排櫃的商品類型。', 'err');
        return;
      }
      var w = Number($('run-width').value) || 3600;
      var d = Number($('run-depth').value) || 3000;
      var h = Number($('run-height').value) || 2600;
      var wall = $('run-wall').value || 'N';
      $('run-confirm-msg').textContent =
        '即將執行工廠排櫃與試算報價：空間 ' +
        w +
        '×' +
        d +
        '×' +
        h +
        ' mm、目標牆面 ' +
        wall +
        '、櫃型 ' +
        checked.join(', ') +
        '。請確認：';
      $('run-confirm-box').hidden = false;
    });

    $('run-confirm-no').addEventListener('click', function () {
      $('run-confirm-box').hidden = true;
    });

    $('run-confirm-yes').addEventListener('click', function () {
      var btn = $('run-confirm-yes');
      btn.disabled = true;
      var checked = [];
      Array.prototype.forEach.call(
        $('run-types-checks').querySelectorAll('input[type="checkbox"]:checked'),
        function (cb) {
          checked.push(cb.value);
        }
      );
      var payload = {
        space: {
          width: Number($('run-width').value) || 3600,
          depth: Number($('run-depth').value) || 3000,
          height: Number($('run-height').value) || 2600
        },
        wallName: $('run-wall').value || 'N',
        productTypes: checked.length ? checked : ['STORAGE_CABINET', 'WARDROBE', 'BOOKCASE'],
        text: $('run-text').value.trim() || undefined,
        render: Boolean($('run-render').checked)
      };

      apiFetch('/api/factory/run', { method: 'POST', body: payload })
        .then(function (res) {
          $('run-confirm-box').hidden = true;
          renderApiAnswer($('run-result'), '排櫃與報價執行結果（POST /api/factory/run）', res);
          if (res.ok && res.data && res.data.quote) {
            state.selectedQuoteId = res.data.quote.quoteId;
            showGlobalAlert(
              '排櫃與報價完成！報價單號：' +
                res.data.quote.quoteId +
                '，建議售價：' +
                formatMoney(res.data.quote.suggestedPrice),
              'ok'
            );
            return refreshAll();
          } else {
            showGlobalAlert('執行排櫃報價失敗（HTTP ' + res.status + '）', 'err');
          }
        })
        .finally(function () {
          btn.disabled = false;
        });
    });

    // 3. 報價單查詢與人工核准
    $('qt-lookup-btn').addEventListener('click', function () {
      var qid = $('qt-lookup-id').value.trim();
      if (!qid) {
        showGlobalAlert('請先輸入要查詢的報價單號 quoteId。', 'err');
        return;
      }
      loadQuoteDetail(qid);
    });

    $('qd-approve-prepare').addEventListener('click', function () {
      if (!state.selectedQuoteId) return;
      var actor = $('qd-actor').value.trim() || 'sales-manager';
      $('qd-approve-msg').textContent =
        '確定由「' +
        actor +
        '」核准報價單 ' +
        state.selectedQuoteId +
        ' 嗎？核准後狀態將改為 APPROVED（僅核准製造候選方案，不啟動實體 CNC）。';
      $('qd-approve-confirm').hidden = false;
    });

    $('qd-approve-no').addEventListener('click', function () {
      $('qd-approve-confirm').hidden = true;
    });

    $('qd-approve-yes').addEventListener('click', function () {
      if (!state.selectedQuoteId) return;
      var btn = $('qd-approve-yes');
      btn.disabled = true;
      var qid = state.selectedQuoteId;
      var actor = $('qd-actor').value.trim() || 'sales-manager';

      apiFetch('/api/factory/quotes/' + encodeURIComponent(qid) + '/approve', {
        method: 'POST',
        body: { actor: actor }
      })
        .then(function (res) {
          $('qd-approve-confirm').hidden = true;
          renderApiAnswer($('qd-api-out'), '核准報價回應（POST /api/factory/quotes/' + qid + '/approve）', res);
          if (res.ok) {
            showGlobalAlert('報價單 ' + qid + ' 已由 ' + actor + ' 核准（APPROVED）。', 'ok');
            return refreshAll();
          } else {
            showGlobalAlert('核准報價單失敗（HTTP ' + res.status + '）', 'err');
          }
        })
        .finally(function () {
          btn.disabled = false;
        });
    });

    // 4. 櫃體改版
    $('rv-prepare-btn').addEventListener('click', function () {
      var pid = $('rv-product-id').value.trim();
      if (!pid) {
        showGlobalAlert('請先選擇或輸入要改版的目標櫃體商品編號 productId。', 'err');
        return;
      }
      var w = Number($('rv-width').value) || 900;
      var h = Number($('rv-height').value) || 1800;
      var d = Number($('rv-depth').value) || 400;
      $('rv-confirm-msg').textContent =
        '確定要將櫃體「' +
        pid +
        '」改版為新尺寸 ' +
        w +
        '×' +
        h +
        '×' +
        d +
        ' mm（板材：' +
        $('rv-material').value +
        '）嗎？將產生新版本商品編號與報價：';
      $('rv-confirm-box').hidden = false;
    });

    $('rv-confirm-no').addEventListener('click', function () {
      $('rv-confirm-box').hidden = true;
    });

    $('rv-confirm-yes').addEventListener('click', function () {
      var pid = $('rv-product-id').value.trim();
      if (!pid) return;
      var btn = $('rv-confirm-yes');
      btn.disabled = true;

      var payload = {
        width: Number($('rv-width').value) || 900,
        height: Number($('rv-height').value) || 1800,
        depth: Number($('rv-depth').value) || 400,
        doorCount: Number($('rv-doors').value || 0),
        shelfCount: Number($('rv-shelves').value || 0),
        drawerCount: Number($('rv-drawers').value || 0),
        material: $('rv-material').value || 'WOOD_WHITE',
        openingStyle: $('rv-opening').value || 'hinged',
        topFillerHeight: Number($('rv-top-filler').value || 0),
        sideFillerWidth: Number($('rv-side-filler').value || 0)
      };

      apiFetch('/api/factory/products/' + encodeURIComponent(pid) + '/revise', {
        method: 'POST',
        body: payload
      })
        .then(function (res) {
          $('rv-confirm-box').hidden = true;
          renderApiAnswer($('rv-result'), '櫃體改版回應（POST /api/factory/products/' + pid + '/revise）', res);
          if (res.ok && res.data && res.data.spec) {
            var newId = res.data.spec.productId;
            $('rv-product-id').value = newId;
            showGlobalAlert(
              '櫃體改版完成！原櫃體 ' +
                pid +
                ' → 新櫃體 ' +
                newId +
                '（v' +
                res.data.spec.revision +
                '），新版建議售價：' +
                formatMoney(res.data.quote && res.data.quote.suggestedPrice),
              'ok'
            );
            return refreshAll();
          } else {
            showGlobalAlert('櫃體改版失敗（HTTP ' + res.status + '）', 'err');
          }
        })
        .finally(function () {
          btn.disabled = false;
        });
    });

    // 5. 商品研發產生 (#rd)
    Array.prototype.forEach.call(document.querySelectorAll('.fc-preset-btn'), function (b) {
      b.addEventListener('click', function () {
        $('rd-text').value = b.getAttribute('data-text') || '';
      });
    });

    $('rd-prepare-btn').addEventListener('click', function () {
      var txt = $('rd-text').value.trim();
      if (!txt) {
        showGlobalAlert('請輸入商品研發需求描述文字。', 'err');
        return;
      }
      var cnt = Number($('rd-count').value) || 12;
      $('rd-confirm-msg').textContent =
        '即將根據需求「' + txt + '」產生 ' + cnt + ' 組研發候選變體並執行工程與視覺評分，請確認：';
      $('rd-confirm-box').hidden = false;
    });

    $('rd-confirm-no').addEventListener('click', function () {
      $('rd-confirm-box').hidden = true;
    });

    $('rd-confirm-yes').addEventListener('click', function () {
      var btn = $('rd-confirm-yes');
      btn.disabled = true;
      var payload = {
        text: $('rd-text').value.trim(),
        variantCount: Number($('rd-count').value) || 12
      };

      apiFetch('/api/product-rd/generate', { method: 'POST', body: payload })
        .then(function (res) {
          $('rd-confirm-box').hidden = true;
          if (res.ok && res.data) {
            renderRdResult(res.data, res);
            showGlobalAlert(
              '商品研發方案產生完成（單號 ' +
                res.data.rdId +
                '），共評選出前 ' +
                (res.data.top ? res.data.top.length : 0) +
                ' 名候選方案。',
              'ok'
            );
            return refreshAll();
          } else {
            renderApiAnswer($('rd-api-out'), '商品研發產生失敗', res);
            showGlobalAlert('商品研發產生失敗（HTTP ' + res.status + '）', 'err');
          }
        })
        .finally(function () {
          btn.disabled = false;
        });
    });
  }

  function boot() {
    bindEvents();
    refreshAll().then(function () {
      focusHash();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
