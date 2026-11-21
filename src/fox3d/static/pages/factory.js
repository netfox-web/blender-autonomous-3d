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

  var RD_PAGE_LIMIT = 10;
  var RD_TEXT_SOFT_LIMIT = 2000;
  var RD_CONFIRM_PREVIEW_CHARS = 200;
  var rdHistoryReqSeq = 0;
  var rdDetailReqSeq = 0;
  var rdGenerateReqSeq = 0;
  var rdApproveReqSeq = 0;
  var rdGenerateInFlight = false;
  var rdApproveInFlight = false;
  var rdApprovePrepInFlight = false;
  var rdApprovePrepSeq = 0;
  var rdLoadMoreInFlight = false;
  var rdPendingGenerate = null;
  var rdPendingApprove = null;
  var rdSoftLimitWarnActive = false;

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
    selectedRdId: null,
    rdHistory: [],
    rdTotal: 0,
    rdNextCursor: null,
    rdHasMore: false,
    mockBlender: true
  };

  function makeIdempotencyKey(prefix) {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return prefix + '-' + crypto.randomUUID();
    }
    return prefix + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

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

  // Synchronously and via MutationObserver lock controls in the owning card while a confirm box is open.
  function syncConfirmLock(box) {
    if (!box) return;
    var card = box.closest('.fc-card') || box.parentElement;
    if (!card) return;
    var fields = card.querySelectorAll(
      'input, select, textarea, .fc-preset-btn, [id$="-prepare-btn"], [id$="-prepare"]'
    );
    var open = !box.hidden;
    Array.prototype.forEach.call(fields, function (f) {
      if (box.contains(f)) return;
      if (open) {
        if (f.dataset.fcWasDisabled === undefined) {
          f.dataset.fcWasDisabled = f.disabled ? '1' : '';
        }
        f.disabled = true;
      } else if (f.dataset.fcWasDisabled !== undefined) {
        f.disabled = f.dataset.fcWasDisabled === '1';
        delete f.dataset.fcWasDisabled;
      }
    });
  }

  function lockWhileConfirming(box) {
    new MutationObserver(function () {
      syncConfirmLock(box);
    }).observe(box, { attributes: true, attributeFilter: ['hidden'] });
  }
  Array.prototype.forEach.call(document.querySelectorAll('.fc-confirm'), lockWhileConfirming);

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
    rdSoftLimitWarnActive = false;
    var box = $('fc-global-status');
    if (!box) return;
    box.hidden = false;
    box.className = 'fc-alert ' + (kind || 'ok');
    box.textContent = msg;
  }

  function clearRdSoftLimitWarn() {
    if (!rdSoftLimitWarnActive) return;
    rdSoftLimitWarnActive = false;
    var box = $('fc-global-status');
    if (box) box.hidden = true;
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
        if (rdGenerateInFlight || ($('rd-confirm-box') && !$('rd-confirm-box').hidden)) {
          showGlobalAlert('研發確認框開啟或送出中，請先完成或取消目前操作。', 'err');
          return;
        }
        $('rd-text').value =
          '客廳 寬' +
          Math.round((Number(item.defaultWidth) || 800) / 10) +
          'cm 高' +
          Math.round((Number(item.defaultHeight) || 1800) / 10) +
          'cm 白木紋' +
          label +
          ' 雙門';
        updateRdTextHint();
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

  // ---- 5. 商品研發產生與歷史核准 (#rd) -------------------------------------
  function resolveRdJudgeLabel(rd) {
    if (!rd) return 'MOCK';
    if (rd.judgeLabel === 'REAL' || rd.judgeLabel === 'MOCK') return rd.judgeLabel;
    if (rd.scoringStatus === 'REAL' || rd.scoringStatus === 'MOCK') return rd.scoringStatus;
    if (rd.approval && (rd.approval.judgeLabel === 'REAL' || rd.approval.judgeLabel === 'MOCK')) {
      return rd.approval.judgeLabel;
    }
    var top = Array.isArray(rd.top) ? rd.top : [];
    if (top.length) {
      var allReal = top.every(function (r) {
        return r && r.judge && r.judge.label === 'REAL';
      });
      return allReal ? 'REAL' : 'MOCK';
    }
    return 'MOCK';
  }

  function formatRdTime(iso) {
    if (!iso) return '—';
    return String(iso).replace('T', ' ').replace(/\.\d+Z$/, ' UTC').replace(/Z$/, ' UTC');
  }

  function truncateText(value, maxLen) {
    var s = String(value == null ? '' : value).trim();
    if (!maxLen || s.length <= maxLen) return s;
    return s.slice(0, maxLen) + '…';
  }

  function updateRdTextHint() {
    var hintEl = $('rd-text-hint');
    var textEl = $('rd-text');
    if (!hintEl || !textEl) return;
    var len = textEl.value.trim().length;
    if (len > RD_TEXT_SOFT_LIMIT) {
      hintEl.className = 'fc-mute-small fc-field-warn';
      hintEl.textContent =
        '目前 ' +
        len +
        ' 字，已超過建議長度 ' +
        RD_TEXT_SOFT_LIMIT +
        ' 字；系統僅提示不阻擋，確認後將依 API 契約完整送出（歷史清單僅顯示摘要）。';
    } else {
      hintEl.className = 'fc-mute-small';
      hintEl.textContent =
        '目前 ' +
        len +
        ' 字（建議 ' +
        RD_TEXT_SOFT_LIMIT +
        ' 字以內；超過仍可送出，歷史清單僅顯示摘要）。';
    }
  }

  function isBlockedOrFailedPayload(data) {
    if (!data || typeof data !== 'object') return true;
    var st = String(data.status || '').toUpperCase();
    if (st === 'FAILED' || st.indexOf('BLOCKED') === 0) return true;
    var err = String(data.error || '').toUpperCase();
    if (err.indexOf('BLOCKED') === 0) return true;
    return false;
  }

  function extractRdRenderJob(rd) {
    if (!rd || typeof rd !== 'object' || Array.isArray(rd)) return null;
    var pr = rd.parametricRender;
    if (!pr || typeof pr !== 'object' || Array.isArray(pr)) return null;
    if (pr.job && typeof pr.job === 'object' && !Array.isArray(pr.job)) return pr.job;
    if (pr.status !== undefined || pr.error !== undefined) return pr;
    return null;
  }

  // Server sets jobStatusSource=SNAPSHOT when the render job is no longer in the queue,
  // so the status shown is the one saved when the scheme was generated.
  function isRdRenderSnapshot(rd) {
    if (!rd || typeof rd !== 'object' || Array.isArray(rd)) return false;
    var pr = rd.parametricRender;
    return Boolean(pr && typeof pr === 'object' && !Array.isArray(pr) && pr.jobStatusSource === 'SNAPSHOT');
  }

  var RD_RENDER_SNAPSHOT_NOTE = '（產生時快照，目前算圖狀態無法取得）';

  function classifyRdRenderJob(job) {
    if (!job || typeof job !== 'object' || Array.isArray(job)) return null;
    var rawStatus = truncateText(job.status, 64);
    var st = rawStatus.toLowerCase();
    var errText = truncateText(job.error, 120);
    var rawAttempts = Number(job.attemptCount);
    var attempts = Number.isFinite(rawAttempts) && rawAttempts > 0 ? Math.floor(rawAttempts) : 0;
    var rawMax = Number(job.maxAttempts);
    var maxAttempts = Number.isFinite(rawMax) && rawMax > 0 ? Math.floor(rawMax) : 0;
    var rawDelay = Number(job.retryDelaySeconds);
    var retryDelaySeconds = Number.isFinite(rawDelay) && rawDelay > 0 ? rawDelay : 0;
    var attemptText = attempts > 0
      ? (maxAttempts > 0 ? '第 ' + attempts + '/' + maxAttempts + ' 次嘗試' : '第 ' + attempts + ' 次嘗試')
      : '';

    if (
      isBlockedOrFailedPayload(job) ||
      st === 'cancelled' ||
      st === 'cancel_requested' ||
      st === 'expired' ||
      st === 'dead_letter' ||
      st === 'dlq'
    ) {
      return {
        state: 'failed',
        job: job,
        rawStatus: rawStatus || 'failed',
        errorText: errText,
        attemptCount: attempts,
        maxAttempts: maxAttempts,
        attemptText: attemptText,
        detail: errText || rawStatus || 'FAILED'
      };
    }
    if (
      st === 'retry_scheduled' ||
      (st === 'queued' && (Boolean(errText) || attempts > 0 || retryDelaySeconds > 0))
    ) {
      return {
        state: 'retrying',
        job: job,
        rawStatus: rawStatus || 'queued',
        errorText: errText,
        attemptCount: attempts,
        maxAttempts: maxAttempts,
        retryDelaySeconds: retryDelaySeconds,
        attemptText: attemptText,
        detail: errText || attemptText || rawStatus || 'queued'
      };
    }
    if (st === 'succeeded' || st === 'completed') {
      return {
        state: 'completed',
        job: job,
        rawStatus: rawStatus,
        attemptCount: attempts,
        maxAttempts: maxAttempts,
        attemptText: attemptText,
        label: job.realBlender && !job.usedMock ? 'REAL' : 'MOCK'
      };
    }
    if (st === 'skipped') {
      return {
        state: 'skipped',
        job: job,
        rawStatus: rawStatus || 'skipped',
        detail: 'SKIPPED'
      };
    }
    var isRunning = ['reserved', 'dispatched', 'leased', 'running', 'rendering', 'uploading'].indexOf(st) >= 0;
    return {
      state: 'pending',
      job: job,
      rawStatus: rawStatus || 'queued',
      isRunning: isRunning,
      attemptCount: attempts,
      maxAttempts: maxAttempts,
      attemptText: attemptText,
      detail: rawStatus || 'queued'
    };
  }

  function makeRdRenderDetailBadge(renderInfo) {
    if (!renderInfo) return null;
    if (renderInfo.state === 'failed') {
      var failSuffix = renderInfo.attemptText
        ? '（' + renderInfo.attemptText + ' · 算圖失敗）'
        : '（算圖失敗）';
      return el(
        'span',
        { 'class': 'fc-badge err', 'data-render-state': 'failed' },
        '母版 3D 預覽：' + renderInfo.detail + failSuffix
      );
    }
    if (renderInfo.state === 'retrying') {
      var retryParts = [renderInfo.rawStatus || 'queued'];
      if (renderInfo.attemptText) retryParts.push(renderInfo.attemptText);
      if (renderInfo.errorText) retryParts.push(renderInfo.errorText);
      return el(
        'span',
        { 'class': 'fc-badge warn', 'data-render-state': 'retrying' },
        '母版 3D 預覽：排隊重試中（' + retryParts.join(' · ') + '）'
      );
    }
    if (renderInfo.state === 'completed') {
      var rLabel = renderInfo.label;
      return el(
        'span',
        { 'class': 'fc-badge ' + (rLabel === 'REAL' ? 'ok' : 'warn'), 'data-render-state': 'completed' },
        '母版 3D 預覽：' + rLabel + (rLabel === 'MOCK' ? '（模擬算圖已完成）' : '（真實算圖已完成）')
      );
    }
    if (renderInfo.state === 'skipped') {
      return el(
        'span',
        { 'class': 'fc-badge neutral', 'data-render-state': 'skipped' },
        '母版 3D 預覽：SKIPPED（已略過）'
      );
    }
    var pendParts = [renderInfo.detail];
    if (renderInfo.attemptText) pendParts.push(renderInfo.attemptText);
    var pendTitle = renderInfo.isRunning
      ? (renderInfo.attemptCount > 0 ? '重試算圖執行中' : '算圖執行中')
      : '排隊待算圖';
    return el(
      'span',
      { 'class': 'fc-badge neutral', 'data-render-state': 'pending' },
      '母版 3D 預覽：' + pendTitle + '（' + pendParts.join(' · ') + '）'
    );
  }

  function formatRdRenderSummaryText(renderInfo) {
    if (!renderInfo || renderInfo.state === 'skipped') return 'SKIPPED（未算圖）';
    if (renderInfo.state === 'retrying') {
      var parts = [renderInfo.rawStatus || 'queued'];
      if (renderInfo.attemptText) parts.push(renderInfo.attemptText);
      if (renderInfo.errorText) parts.push(renderInfo.errorText);
      return '排隊重試中（' + parts.join(' · ') + '）';
    }
    if (renderInfo.state === 'completed') {
      return '已完成（' + renderInfo.label + '）';
    }
    if (renderInfo.state === 'failed') {
      return '算圖失敗（' + renderInfo.detail + '）';
    }
    return (renderInfo.isRunning ? '算圖執行中' : '排隊待算圖') + '（' + renderInfo.detail + '）';
  }

  function makeRdHistoryRenderBadge(renderInfo) {
    if (!renderInfo || renderInfo.state === 'skipped') {
      return el('span', { 'class': 'fc-badge neutral', 'data-render-state': 'skipped' }, 'SKIPPED（未算圖）');
    }
    if (renderInfo.state === 'retrying') {
      var retryLabel = '排隊重試中（' + (renderInfo.rawStatus || 'queued') +
        (renderInfo.attemptText ? ' · ' + renderInfo.attemptText : '') + '）';
      return el('span', { 'class': 'fc-badge warn', 'data-render-state': 'retrying' }, retryLabel);
    }
    if (renderInfo.state === 'completed') {
      return el(
        'span',
        { 'class': 'fc-badge ' + (renderInfo.label === 'REAL' ? 'ok' : 'warn'), 'data-render-state': 'completed' },
        '已完成 · ' + renderInfo.label
      );
    }
    if (renderInfo.state === 'failed') {
      return el(
        'span',
        { 'class': 'fc-badge err', 'data-render-state': 'failed' },
        '算圖失敗（' + truncateText(renderInfo.detail, 40) + '）'
      );
    }
    var pendLabel = (renderInfo.isRunning ? '算圖執行中' : '排隊待算圖') + '（' + renderInfo.detail + '）';
    return el('span', { 'class': 'fc-badge neutral', 'data-render-state': 'pending' }, pendLabel);
  }

  function resetRdSelectionUI() {
    state.lastRdResult = null;
    state.selectedRdId = null;
    rdPendingApprove = null;
    var appBox = $('rd-approve-confirm');
    if (appBox) {
      appBox.hidden = true;
      syncConfirmLock(appBox);
    }
    if ($('rd-approve-out')) $('rd-approve-out').hidden = true;
    if ($('rd-api-out')) $('rd-api-out').hidden = true;
    if ($('rd-body')) $('rd-body').hidden = true;
    if ($('rd-empty')) {
      $('rd-empty').hidden = false;
      $('rd-empty').className = 'fc-state';
      $('rd-empty').textContent = '請在左側輸入研發需求並點擊「產生商品研發方案…」，或從下方歷史清單選取方案。';
    }
    var gateBadge = $('rd-gate-badge');
    if (gateBadge) {
      gateBadge.className = 'fc-badge neutral';
      gateBadge.textContent = '尚未執行';
    }
  }

  function renderRdResult(rd, apiRes, outBoxId, outTitle) {
    if (!rd || typeof rd !== 'object') return;
    state.lastRdResult = rd;
    state.selectedRdId = rd.rdId || null;
    $('rd-empty').hidden = true;
    $('rd-body').hidden = false;

    var approveConfirm = $('rd-approve-confirm');
    if (approveConfirm && !rdApproveInFlight) {
      approveConfirm.hidden = true;
      syncConfirmLock(approveConfirm);
      rdPendingApprove = null;
    }

    var approval = rd.approval || {};
    var approvalStatus = approval.status || 'WAITING_APPROVAL';
    var approvedAt = approval.approvedAt || rd.approvedAt || null;
    var approvedActor = approval.actor || null;
    var gateInfo = truthBadgeInfo(approvalStatus);
    var gateBadge = $('rd-gate-badge');
    gateBadge.className = 'fc-badge ' + gateInfo.cls;
    gateBadge.textContent = gateInfo.text;

    var badgesBox = $('rd-truth-badges');
    badgesBox.textContent = '';
    var judgeLabel = resolveRdJudgeLabel(rd);
    badgesBox.appendChild(
      el(
        'span',
        { 'class': 'fc-badge ' + (judgeLabel === 'REAL' ? 'ok' : 'warn') },
        '視覺評分來源：' + judgeLabel + (judgeLabel === 'MOCK' ? '（啟發式規則評分）' : '')
      )
    );
    if (approvalStatus === 'APPROVED' && judgeLabel === 'MOCK') {
      badgesBox.appendChild(
        el('span', { 'class': 'fc-badge warn' }, 'MOCK 評分方案（核准後仍為模擬評分）')
      );
    }
    var renderInfo = classifyRdRenderJob(extractRdRenderJob(rd));
    var renderIsSnapshot = Boolean(renderInfo) && isRdRenderSnapshot(rd);
    var renderDetailBadge = makeRdRenderDetailBadge(renderInfo);
    if (renderDetailBadge) {
      if (renderIsSnapshot) {
        renderDetailBadge.textContent += RD_RENDER_SNAPSHOT_NOTE;
        renderDetailBadge.setAttribute('data-render-source', 'snapshot');
      }
      badgesBox.appendChild(renderDetailBadge);
    }

    var intentBox = $('rd-intent-summary');
    intentBox.textContent = '';
    var baseSpec = rd.baseSpec || {};
    var fullTextLen =
      typeof rd.textLength === 'number'
        ? rd.textLength
        : String(rd.text || (rd.intent && rd.intent.notes) || '').length;
    var kvs = [
      ['研發單號', rd.rdId || '—'],
      ['建立時間', formatRdTime(rd.createdAt)],
      [
        '需求字數',
        fullTextLen + ' 字' + (rd.textTruncated ? '（列表摘要，點查看明細載入全文）' : '')
      ],
      ['解析櫃型', (TYPE_LABELS[baseSpec.kind] || baseSpec.kind || '—') + ' (' + (baseSpec.kind || '') + ')'],
      ['母版尺寸 (mm)', (baseSpec.width || '—') + ' × ' + (baseSpec.height || '—') + ' × ' + (baseSpec.depth || '—')],
      ['產生／合格變體數', (rd.variantCount || 0) + ' 組 ／ 合格 ' + (rd.scoredCount || 0) + ' 組'],
      ['工程規則檢核', rd.baseReport && rd.baseReport.ok ? '通過 (OK)' : '有工程警告'],
      ['母版 3D 預覽狀態', formatRdRenderSummaryText(renderInfo) + (renderIsSnapshot ? RD_RENDER_SNAPSHOT_NOTE : '')],
      ['核准狀態', approvalStatus === 'APPROVED' ? 'APPROVED（已核准）' : 'WAITING_APPROVAL（待核准）']
    ];
    if (approvalStatus === 'APPROVED') {
      kvs.push(['核准人員', approvedActor || '—']);
      kvs.push(['核准時間 (approvedAt)', approvedAt || '—']);
    } else {
      kvs.push(['量產放行門檻', rd.HUMAN_APPROVAL_REQUIRED ? '需人工核准' : '標準']);
    }
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
      var rowJudgeLabel = judgeLabel === 'MOCK' ? 'MOCK' : (j.label || judgeLabel);
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
      tdJ.appendChild(makeBadge(rowJudgeLabel));
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

    var btnApprovePrep = $('rd-approve-prepare');
    var actorInput = $('rd-approve-actor');
    if (btnApprovePrep && !rdApproveInFlight && !rdApprovePrepInFlight) {
      if (approvalStatus === 'APPROVED') {
        btnApprovePrep.disabled = true;
        btnApprovePrep.textContent = '此研發方案已核准（APPROVED）';
        if (actorInput) actorInput.disabled = true;
      } else {
        btnApprovePrep.disabled = false;
        btnApprovePrep.textContent = '核准此研發方案…';
        if (actorInput) actorInput.disabled = false;
      }
    }

    renderRdHistory();

    if (apiRes) {
      renderApiAnswer($(outBoxId || 'rd-api-out'), outTitle || '商品研發產生結果', apiRes);
    }
  }

  function renderRdHistory() {
    var emptyEl = $('rd-history-empty');
    var wrapEl = $('rd-history-wrap');
    var tbody = $('rd-history-tbody');
    var moreWrap = $('rd-history-more-wrap');
    var metaEl = $('rd-history-meta');
    if (!emptyEl || !wrapEl || !tbody) return;

    tbody.textContent = '';
    if (metaEl) {
      metaEl.textContent =
        '共 ' + state.rdTotal + ' 筆方案 · 依建立時間由新到舊排列 · GET /api/product-rd/results';
    }

    if (!state.rdHistory.length) {
      emptyEl.hidden = false;
      emptyEl.className = 'fc-state';
      emptyEl.textContent = '尚無歷史研發方案。請由上方表單產生。';
      wrapEl.hidden = true;
      if (moreWrap) moreWrap.hidden = true;
      return;
    }

    emptyEl.hidden = true;
    wrapEl.hidden = false;

    state.rdHistory.forEach(function (item) {
      var tr = el('tr', { 'data-rd-id': item.rdId || '' });
      if (state.selectedRdId && state.selectedRdId === item.rdId) {
        tr.className = 'selected';
      }

      var tdId = el('td');
      tdId.appendChild(el('code', null, item.rdId || '—'));
      tr.appendChild(tdId);

      tr.appendChild(el('td', null, formatRdTime(item.createdAt)));

      var tdSummary = el('td');
      var stack = el('div', { 'class': 'fc-cell-stack' });
      var rawText = String(
        item.textSummary || item.text || (item.intent && item.intent.notes) || ''
      ).trim();
      var summaryText = rawText || '（預設需求）';
      if (summaryText.length > 80) {
        summaryText = summaryText.slice(0, 80) + '…';
      }
      stack.appendChild(el('span', null, summaryText));
      var bs = item.baseSpec || {};
      var itemTextLen =
        typeof item.textLength === 'number' ? item.textLength : String(item.text || '').length;
      var specLine =
        (TYPE_LABELS[bs.kind] || bs.kind || 'CABINET') +
        ' · ' +
        (bs.width || '—') +
        '×' +
        (bs.height || '—') +
        '×' +
        (bs.depth || '—') +
        ' mm' +
        (itemTextLen > 80 ? ' · 需求 ' + itemTextLen + ' 字' : '');
      stack.appendChild(el('span', { 'class': 'fc-mute-small' }, specLine));
      tdSummary.appendChild(stack);
      tr.appendChild(tdSummary);

      tr.appendChild(
        el('td', null, (item.scoredCount || 0) + ' / ' + (item.variantCount || 0) + ' 組')
      );

      var judgeLabel = resolveRdJudgeLabel(item);
      var tdJudge = el('td');
      tdJudge.appendChild(makeBadge(judgeLabel));
      tr.appendChild(tdJudge);

      var itemRenderInfo = classifyRdRenderJob(extractRdRenderJob(item));
      var tdPreview = el('td', { 'data-role': 'rd-preview-status' });
      var itemRenderBadge = makeRdHistoryRenderBadge(itemRenderInfo);
      if (itemRenderInfo && isRdRenderSnapshot(item)) {
        itemRenderBadge.textContent += RD_RENDER_SNAPSHOT_NOTE;
        itemRenderBadge.setAttribute('data-render-source', 'snapshot');
      }
      tdPreview.appendChild(itemRenderBadge);
      tr.appendChild(tdPreview);

      var app = item.approval || {};
      var appStatus = app.status || 'WAITING_APPROVAL';
      var appAt = app.approvedAt || item.approvedAt || '';
      var tdGate = el('td');
      var gateStack = el('div', { 'class': 'fc-cell-stack' });
      gateStack.appendChild(makeBadge(appStatus));
      if (appStatus === 'APPROVED' && (app.actor || appAt)) {
        gateStack.appendChild(
          el(
            'span',
            { 'class': 'fc-mute-small' },
            (app.actor ? app.actor + ' · ' : '') + (appAt || '')
          )
        );
      }
      tdGate.appendChild(gateStack);
      tr.appendChild(tdGate);

      var tdAct = el('td');
      var actWrap = el('div', { 'class': 'fc-actions' });
      var btnView = el(
        'button',
        { type: 'button', 'class': 'fc-btn small primary' },
        appStatus === 'APPROVED' ? '查看明細' : '查看／核准'
      );
      btnView.addEventListener('click', function () {
        loadRdDetail(item.rdId);
      });
      actWrap.appendChild(btnView);
      tdAct.appendChild(actWrap);
      tr.appendChild(tdAct);

      tbody.appendChild(tr);
    });

    if (moreWrap) {
      moreWrap.hidden = !state.rdHasMore;
    }
  }

  function upsertRdHistoryItem(rd) {
    if (!rd || !rd.rdId) return;
    var replaced = false;
    var next = state.rdHistory.map(function (existing) {
      if (existing.rdId === rd.rdId) {
        replaced = true;
        return rd;
      }
      return existing;
    });
    if (!replaced) {
      next.unshift(rd);
      state.rdTotal = Math.max(state.rdTotal + 1, next.length);
    }
    state.rdHistory = next;
  }

  function loadRdDetail(rdId) {
    if (!rdId || rdApproveInFlight) return;
    var reqSeq = ++rdDetailReqSeq;
    var tenantAtReq = currentTenant();
    rdPendingApprove = null;
    // Selecting another scheme cancels an approve-confirm re-read that is still in flight.
    rdApprovePrepSeq++;
    rdApprovePrepInFlight = false;
    var appBox = $('rd-approve-confirm');
    if (appBox) {
      appBox.hidden = true;
      syncConfirmLock(appBox);
    }
    $('rd-empty').hidden = false;
    $('rd-empty').className = 'fc-state';
    $('rd-empty').textContent = '正在讀取研發方案 ' + rdId + ' 明細…';
    $('rd-body').hidden = true;

    return apiFetch('/api/product-rd/results/' + encodeURIComponent(rdId))
      .then(function (res) {
        if (reqSeq !== rdDetailReqSeq || tenantAtReq !== currentTenant()) return;
        if (!res.ok || !res.data || isBlockedOrFailedPayload(res.data)) {
          state.selectedRdId = null;
          state.lastRdResult = null;
          renderRdHistory();
          var gateBadge = $('rd-gate-badge');
          if (gateBadge) {
            gateBadge.className = 'fc-badge err';
            gateBadge.textContent = '查詢失敗';
          }
          $('rd-empty').hidden = false;
          $('rd-empty').className = 'fc-state error';
          $('rd-empty').textContent = '查詢研發方案失敗（HTTP ' + res.status + '）：找不到方案 ' + rdId;
          showGlobalAlert('查詢研發方案失敗（HTTP ' + res.status + '）', 'err');
          return;
        }
        upsertRdHistoryItem(res.data);
        renderRdResult(res.data, res, 'rd-approve-out', '研發方案明細查詢結果');
      })
      .catch(function (err) {
        if (reqSeq !== rdDetailReqSeq || tenantAtReq !== currentTenant()) return;
        state.selectedRdId = null;
        state.lastRdResult = null;
        renderRdHistory();
        $('rd-empty').hidden = false;
        $('rd-empty').className = 'fc-state error';
        $('rd-empty').textContent = '連線失敗，無法讀取研發方案：' + ((err && err.message) || err);
        showGlobalAlert('連線失敗，請稍後再試：' + ((err && err.message) || err), 'err');
      });
  }

  function refreshRdHistory() {
    var reqSeq = ++rdHistoryReqSeq;
    var tenantAtReq = currentTenant();
    var emptyEl = $('rd-history-empty');
    if (emptyEl && !state.rdHistory.length) {
      emptyEl.hidden = false;
      emptyEl.className = 'fc-state';
      emptyEl.textContent = '載入歷史研發方案中…';
    }

    return apiFetch('/api/product-rd/results?offset=0&limit=' + RD_PAGE_LIMIT)
      .then(function (res) {
        if (reqSeq !== rdHistoryReqSeq || tenantAtReq !== currentTenant()) return;
        if (!res.ok || !res.data || !Array.isArray(res.data.items)) {
          state.rdHistory = [];
          state.rdTotal = 0;
          state.rdNextCursor = null;
          state.rdHasMore = false;
          if ($('rd-history-wrap')) $('rd-history-wrap').hidden = true;
          if ($('rd-history-more-wrap')) $('rd-history-more-wrap').hidden = true;
          if (emptyEl) {
            emptyEl.hidden = false;
            emptyEl.className = 'fc-state error';
            emptyEl.textContent = '載入歷史研發方案失敗（HTTP ' + res.status + '）';
          }
          return;
        }
        var d = res.data;
        state.rdHistory = d.items;
        state.rdTotal = typeof d.total === 'number' ? d.total : d.items.length;
        state.rdNextCursor = typeof d.nextCursor === 'string' && d.nextCursor ? d.nextCursor : null;
        state.rdHasMore = Boolean(d.hasMore || state.rdNextCursor);
        renderRdHistory();

        if (state.selectedRdId) {
          var matched = null;
          for (var i = 0; i < state.rdHistory.length; i++) {
            if (state.rdHistory[i].rdId === state.selectedRdId) {
              matched = state.rdHistory[i];
              break;
            }
          }
          if (matched && !rdApproveInFlight) {
            if (
              state.lastRdResult &&
              state.lastRdResult.rdId === matched.rdId &&
              !state.lastRdResult.textTruncated &&
              matched.textTruncated
            ) {
              matched = Object.assign({}, matched, {
                text: state.lastRdResult.text,
                textTruncated: false
              });
            }
            renderRdResult(matched, null);
          }
        } else if (state.rdHistory.length && !rdApproveInFlight) {
          renderRdResult(state.rdHistory[0], null);
        }
      })
      .catch(function (err) {
        if (reqSeq !== rdHistoryReqSeq || tenantAtReq !== currentTenant()) return;
        if ($('rd-history-wrap') && !state.rdHistory.length) $('rd-history-wrap').hidden = true;
        if ($('rd-history-more-wrap')) $('rd-history-more-wrap').hidden = true;
        if (emptyEl && !state.rdHistory.length) {
          emptyEl.hidden = false;
          emptyEl.className = 'fc-state error';
          emptyEl.textContent = '載入歷史研發方案連線失敗：' + ((err && err.message) || err);
        }
      });
  }

  function loadMoreRdHistory() {
    if (rdLoadMoreInFlight || !state.rdHasMore) return;
    var btn = $('rd-history-more-btn');
    var reqSeq = rdHistoryReqSeq;
    var tenantAtReq = currentTenant();
    rdLoadMoreInFlight = true;
    if (btn) btn.disabled = true;

    var offset = state.rdHistory.length;
    var path = '/api/product-rd/results?offset=' + offset + '&limit=' + RD_PAGE_LIMIT;
    if (state.rdNextCursor) {
      path += '&cursor=' + encodeURIComponent(state.rdNextCursor);
    }

    return apiFetch(path)
      .then(function (res) {
        if (reqSeq !== rdHistoryReqSeq || tenantAtReq !== currentTenant()) return;
        if (!res.ok || !res.data || !Array.isArray(res.data.items)) {
          showGlobalAlert('載入更多歷史研發方案失敗（HTTP ' + res.status + '）', 'err');
          return;
        }
        var d = res.data;
        var seen = {};
        state.rdHistory.forEach(function (x) {
          if (x && x.rdId) seen[x.rdId] = true;
        });
        d.items.forEach(function (item) {
          if (item && item.rdId && !seen[item.rdId]) {
            seen[item.rdId] = true;
            state.rdHistory.push(item);
          }
        });
        if (typeof d.total === 'number') state.rdTotal = d.total;
        state.rdNextCursor = typeof d.nextCursor === 'string' && d.nextCursor ? d.nextCursor : null;
        state.rdHasMore = Boolean(d.hasMore || state.rdNextCursor);
        renderRdHistory();
      })
      .catch(function (err) {
        if (reqSeq !== rdHistoryReqSeq || tenantAtReq !== currentTenant()) return;
        showGlobalAlert('載入更多研發方案連線失敗：' + ((err && err.message) || err), 'err');
      })
      .finally(function () {
        rdLoadMoreInFlight = false;
        if (btn) btn.disabled = false;
      });
  }

  // ---- 資料載入 ------------------------------------------------------------
  function refreshAll() {
    $('fc-types-state').hidden = false;
    $('fc-types-state').className = 'fc-state';
    $('fc-types-state').textContent = '載入商品類型與工廠資料中…';

    var rdPromise = refreshRdHistory();
    var corePromise = Promise.all([
      apiFetch('/api/factory/product-types'),
      apiFetch('/api/pages/factory/state'),
      apiFetch('/api/factory/quotes?limit=100')
    ])
      .then(function (results) {
        var typesRes = results[0];
        var stateRes = results[1];
        var quotesRes = results[2];

        if (typesRes.ok && typesRes.data && Array.isArray(typesRes.data.items)) {
          state.productTypeCodes = typesRes.data.items;
        }
        if (stateRes.ok && stateRes.data) {
          var d = stateRes.data;
          state.mockBlender = Boolean(d.mockBlender);
          state.productTypes = d.productTypes || [];
          state.spaces = d.spaces || [];
          state.runs = d.runs || [];
          state.products = d.products || [];
          state.revisions = d.revisions || [];

          if (quotesRes.ok && quotesRes.data && Array.isArray(quotesRes.data.items)) {
            state.quotes = quotesRes.data.items;
          } else {
            state.quotes = d.quotes || [];
          }

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
          loadQuoteDetail(state.quotes[0].quoteId);
        }
      })
      .catch(function (err) {
        $('fc-types-state').hidden = false;
        $('fc-types-state').className = 'fc-state error';
        $('fc-types-state').textContent = '連線失敗：' + err;
      });

    return Promise.all([corePromise, rdPromise]);
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

    $('fc-tenant').addEventListener('input', function () {
      rdGenerateReqSeq++;
      rdApproveReqSeq++;
      rdApprovePrepSeq++;
      rdApprovePrepInFlight = false;
      rdHistoryReqSeq++;
      rdDetailReqSeq++;
      rdPendingGenerate = null;
      var box = $('rd-confirm-box');
      box.hidden = true;
      syncConfirmLock(box);
      state.rdHistory = [];
      state.rdTotal = 0;
      state.rdNextCursor = null;
      state.rdHasMore = false;
      resetRdSelectionUI();
      renderRdHistory();
    });

    $('fc-tenant').addEventListener('change', function (e) {
      rdGenerateReqSeq++;
      rdApproveReqSeq++;
      rdApprovePrepSeq++;
      rdApprovePrepInFlight = false;
      rdPendingGenerate = null;
      var generateBox = $('rd-confirm-box');
      generateBox.hidden = true;
      syncConfirmLock(generateBox);
      var v = e.target.value.trim() || 'sonaqueen-home';
      e.target.value = v;
      try {
        localStorage.setItem('fox3d.tenant', v);
      } catch (x) {
        /* storage blocked */
      }
      state.selectedQuoteId = null;
      state.rdHistory = [];
      state.rdTotal = 0;
      state.rdNextCursor = null;
      state.rdHasMore = false;
      resetRdSelectionUI();
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
        .catch(function (e) {
          showGlobalAlert('連線失敗，請稍後再試：' + ((e && e.message) || e), 'err');
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
        productTypes: checked,
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
        .catch(function (e) {
          showGlobalAlert('連線失敗，請稍後再試：' + ((e && e.message) || e), 'err');
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
        .catch(function (e) {
          showGlobalAlert('連線失敗，請稍後再試：' + ((e && e.message) || e), 'err');
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
        .catch(function (e) {
          showGlobalAlert('連線失敗，請稍後再試：' + ((e && e.message) || e), 'err');
        })
        .finally(function () {
          btn.disabled = false;
        });
    });

    // 5. 商品研發產生與歷史核准 (#rd)
    Array.prototype.forEach.call(document.querySelectorAll('.fc-preset-btn'), function (b) {
      b.addEventListener('click', function () {
        if (rdGenerateInFlight || !$('rd-confirm-box').hidden) return;
        $('rd-text').value = b.getAttribute('data-text') || '';
        updateRdTextHint();
      });
    });

    $('rd-text').addEventListener('input', updateRdTextHint);
    updateRdTextHint();

    $('rd-prepare-btn').addEventListener('click', function () {
      if (rdGenerateInFlight || !$('rd-confirm-box').hidden) return;
      var txt = $('rd-text').value.trim();
      if (!txt) {
        showGlobalAlert('請輸入商品研發需求描述文字。', 'err');
        return;
      }
      var rawCnt = $('rd-count').value.trim();
      var cnt = Number(rawCnt);
      if (!rawCnt || !Number.isInteger(cnt) || cnt < 10 || cnt > 50) {
        showGlobalAlert('候選變體數量須為 10 至 50 的整數。', 'err');
        return;
      }
      var overSoftLimit = txt.length > RD_TEXT_SOFT_LIMIT;
      if (overSoftLimit) {
        showGlobalAlert(
          '提示：需求文字共 ' +
            txt.length +
            ' 字（超過建議長度 ' +
            RD_TEXT_SOFT_LIMIT +
            ' 字），系統僅提示不阻擋，確認後將依 API 契約完整送出。',
          'warn'
        );
        rdSoftLimitWarnActive = true;
      } else {
        clearRdSoftLimitWarn();
      }
      rdPendingGenerate = {
        text: txt,
        tenant: currentTenant(),
        variantCount: cnt,
        idempotencyKey: makeIdempotencyKey('rd-gen')
      };
      var previewText =
        rdPendingGenerate.text.length > RD_CONFIRM_PREVIEW_CHARS
          ? rdPendingGenerate.text.slice(0, RD_CONFIRM_PREVIEW_CHARS) +
            '…（共 ' +
            rdPendingGenerate.text.length +
            ' 字' +
            (overSoftLimit ? '，超過建議 ' + RD_TEXT_SOFT_LIMIT + ' 字，將完整送出' : '') +
            '）'
          : rdPendingGenerate.text;
      $('rd-confirm-msg').textContent =
        '即將為租戶「' + rdPendingGenerate.tenant + '」根據需求「' +
        previewText +
        '」產生 ' +
        rdPendingGenerate.variantCount +
        ' 組研發候選變體並執行工程與視覺評分，請確認：';
      var box = $('rd-confirm-box');
      box.hidden = false;
      syncConfirmLock(box);
    });

    $('rd-confirm-no').addEventListener('click', function () {
      if (rdGenerateInFlight) return;
      rdPendingGenerate = null;
      clearRdSoftLimitWarn();
      var box = $('rd-confirm-box');
      box.hidden = true;
      syncConfirmLock(box);
    });

    $('rd-confirm-yes').addEventListener('click', function () {
      if (rdGenerateInFlight || !rdPendingGenerate || rdPendingGenerate.tenant !== currentTenant()) return;
      var snap = rdPendingGenerate;
      var reqSeq = ++rdGenerateReqSeq;
      rdGenerateInFlight = true;
      var yesBtn = $('rd-confirm-yes');
      var noBtn = $('rd-confirm-no');
      var prepBtn = $('rd-prepare-btn');
      yesBtn.disabled = true;
      noBtn.disabled = true;
      prepBtn.disabled = true;

      var payload = {
        text: rdPendingGenerate.text,
        variantCount: rdPendingGenerate.variantCount,
        idempotencyKey: rdPendingGenerate.idempotencyKey
      };

      apiFetch('/api/product-rd/generate', { method: 'POST', headers: { 'X-Tenant-Id': snap.tenant }, body: payload })
        .then(function (res) {
          if (reqSeq !== rdGenerateReqSeq || snap.tenant !== currentTenant()) return;
          var renderInfo = classifyRdRenderJob(extractRdRenderJob(res.data));
          var renderFailed = Boolean(renderInfo && renderInfo.state === 'failed');
          if (res.ok && res.data && !isBlockedOrFailedPayload(res.data)) {
            rdPendingGenerate = null;
            var box = $('rd-confirm-box');
            box.hidden = true;
            syncConfirmLock(box);
            upsertRdHistoryItem(res.data);
            renderRdResult(
              res.data,
              res,
              'rd-api-out',
              renderFailed ? '商品研發已儲存（母版算圖失敗）' : '商品研發產生結果'
            );
            if (renderFailed) {
              showGlobalAlert(
                '研發方案已儲存（單號 ' +
                  (res.data.rdId || '—') +
                  '），但母版 3D 算圖失敗：' +
                  renderInfo.detail,
                'err'
              );
            } else if (renderInfo && renderInfo.state === 'retrying') {
              showGlobalAlert(
                '研發方案已儲存（單號 ' +
                  (res.data.rdId || '—') +
                  '），但母版 3D 算圖暫時失敗並已排隊重試' +
                  (renderInfo.attemptText ? '（' + renderInfo.attemptText + '）' : '') +
                  '：' +
                  renderInfo.detail,
                'warn'
              );
            } else if (renderInfo && renderInfo.state === 'pending') {
              showGlobalAlert(
                '研發方案已儲存（單號 ' +
                  (res.data.rdId || '—') +
                  '），母版 3D 預覽' +
                  (renderInfo.isRunning ? '算圖執行中' : '排隊待算圖') +
                  '（' +
                  renderInfo.detail +
                  '）。',
                'warn'
              );
            } else {
              showGlobalAlert(
                '商品研發方案產生完成（單號 ' +
                  (res.data.rdId || '—') +
                  '），共評選出前 ' +
                  (res.data.top ? res.data.top.length : 0) +
                  ' 名候選方案。',
                'ok'
              );
            }
            return refreshAll();
          } else {
            var boxErr = $('rd-confirm-box');
            boxErr.hidden = true;
            syncConfirmLock(boxErr);
            rdPendingGenerate = null;
            renderApiAnswer($('rd-api-out'), '商品研發產生失敗', res);
            var errDetail = (res.data && (res.data.detail || res.data.error)) || ('HTTP ' + res.status);
            showGlobalAlert('商品研發產生失敗：' + errDetail, 'err');
          }
        })
        .catch(function (e) {
          if (reqSeq !== rdGenerateReqSeq || snap.tenant !== currentTenant()) return;
          showGlobalAlert('連線失敗，請稍後再試：' + ((e && e.message) || e), 'err');
        })
        .finally(function () {
          rdGenerateInFlight = false;
          yesBtn.disabled = false;
          noBtn.disabled = false;
          if ($('rd-confirm-box').hidden) {
            prepBtn.disabled = false;
          }
        });
    });

    if ($('rd-approve-prepare')) {
      $('rd-approve-prepare').addEventListener('click', function () {
        if (rdApproveInFlight || rdApprovePrepInFlight || !state.selectedRdId || !$('rd-approve-confirm').hidden) {
          return;
        }
        var cached = state.lastRdResult;
        if (cached && cached.approval && cached.approval.status === 'APPROVED') return;
        var actor = ($('rd-approve-actor').value || '').trim();
        if (!actor) {
          showGlobalAlert('請輸入核准人員姓名或工號。', 'err');
          return;
        }
        if (actor.length > 120) {
          showGlobalAlert('核准人員名稱不可超過 120 字。', 'err');
          return;
        }
        // Re-read the scheme so the confirm box shows the current render status, not the one
        // cached when the scheme was listed (a queued retry may have finished or failed since).
        var prepSnap = { rdId: state.selectedRdId, tenant: currentTenant(), actor: actor };
        var prepSeq = ++rdApprovePrepSeq;
        rdApprovePrepInFlight = true;
        var prepBtn = $('rd-approve-prepare');
        var prepActorInput = $('rd-approve-actor');
        prepBtn.disabled = true;
        if (prepActorInput) prepActorInput.disabled = true;

        apiFetch('/api/product-rd/results/' + encodeURIComponent(prepSnap.rdId), {
          headers: { 'X-Tenant-Id': prepSnap.tenant }
        })
          .then(function (res) {
            if (
              prepSeq !== rdApprovePrepSeq ||
              prepSnap.tenant !== currentTenant() ||
              prepSnap.rdId !== state.selectedRdId
            ) {
              return;
            }
            if (!res.ok || !res.data || isBlockedOrFailedPayload(res.data) || res.data.rdId !== prepSnap.rdId) {
              var failDetail = (res.data && (res.data.detail || res.data.error)) || ('HTTP ' + res.status);
              showGlobalAlert('無法讀取研發方案目前狀態，未開啟核准確認：' + failDetail, 'err');
              return;
            }
            var current = res.data;
            rdApprovePrepInFlight = false;
            upsertRdHistoryItem(current);
            renderRdResult(current, null);
            if (current.approval && current.approval.status === 'APPROVED') {
              showGlobalAlert('研發方案 ' + prepSnap.rdId + ' 已是核准狀態（APPROVED），無需再次核准。', 'warn');
              return;
            }
            var judgeLbl = resolveRdJudgeLabel(current);
            var curRenderInfo = classifyRdRenderJob(extractRdRenderJob(current));
            var renderApproveNote = '';
            if (curRenderInfo && curRenderInfo.state === 'retrying') {
              renderApproveNote = '（注意：母版 3D 預覽仍在排隊重試中，尚未完成算圖）';
            } else if (curRenderInfo && curRenderInfo.state === 'failed') {
              renderApproveNote = '（注意：母版 3D 預覽算圖失敗）';
            } else if (curRenderInfo && curRenderInfo.state === 'pending') {
              renderApproveNote = '（注意：母版 3D 預覽尚未完成算圖）';
            }
            if (renderApproveNote && isRdRenderSnapshot(current)) {
              renderApproveNote += RD_RENDER_SNAPSHOT_NOTE;
            }
            rdPendingApprove = {
              rdId: prepSnap.rdId,
              tenant: prepSnap.tenant,
              actor: prepSnap.actor
            };
            $('rd-approve-msg').textContent =
              '確定為租戶「' + rdPendingApprove.tenant + '」由「' +
              rdPendingApprove.actor +
              '」核准研發方案 ' +
              rdPendingApprove.rdId +
              ' 嗎？核准後狀態將改為 APPROVED 並記錄 approvedAt' +
              (judgeLbl === 'MOCK' ? '（視覺評分來源仍維持標示為 MOCK）' : '') +
              renderApproveNote +
              '：';
            var box = $('rd-approve-confirm');
            box.hidden = false;
            syncConfirmLock(box);
          })
          .catch(function (e) {
            if (prepSeq !== rdApprovePrepSeq || prepSnap.tenant !== currentTenant()) return;
            showGlobalAlert('連線失敗，無法讀取研發方案目前狀態：' + ((e && e.message) || e), 'err');
          })
          .finally(function () {
            if (prepSeq !== rdApprovePrepSeq) return;
            rdApprovePrepInFlight = false;
            if ($('rd-approve-confirm').hidden && !rdApproveInFlight) {
              var isApproved =
                state.lastRdResult &&
                state.lastRdResult.approval &&
                state.lastRdResult.approval.status === 'APPROVED';
              prepBtn.disabled = Boolean(isApproved);
              if (prepActorInput) prepActorInput.disabled = Boolean(isApproved);
            }
          });
      });
    }

    if ($('rd-approve-no')) {
      $('rd-approve-no').addEventListener('click', function () {
        if (rdApproveInFlight) return;
        rdPendingApprove = null;
        var box = $('rd-approve-confirm');
        box.hidden = true;
        syncConfirmLock(box);
      });
    }

    if ($('rd-approve-yes')) {
      $('rd-approve-yes').addEventListener('click', function () {
        if (rdApproveInFlight || !rdPendingApprove || rdPendingApprove.tenant !== currentTenant()) return;
        var reqSeq = ++rdApproveReqSeq;
        rdApproveInFlight = true;
        var snap = {
          rdId: rdPendingApprove.rdId,
          tenant: rdPendingApprove.tenant,
          actor: rdPendingApprove.actor
        };
        var yesBtn = $('rd-approve-yes');
        var noBtn = $('rd-approve-no');
        var prepBtn = $('rd-approve-prepare');
        yesBtn.disabled = true;
        noBtn.disabled = true;
        prepBtn.disabled = true;

        apiFetch('/api/product-rd/results/' + encodeURIComponent(snap.rdId) + '/approve', {
          method: 'POST',
          headers: { 'X-Tenant-Id': snap.tenant },
          body: {
            actor: snap.actor,
            confirm: true
          }
        })
          .then(function (res) {
            if (reqSeq !== rdApproveReqSeq || snap.tenant !== currentTenant()) return;
            if (res.ok && res.data && !isBlockedOrFailedPayload(res.data)) {
              rdPendingApprove = null;
              var box = $('rd-approve-confirm');
              box.hidden = true;
              syncConfirmLock(box);
              rdApproveInFlight = false;
              upsertRdHistoryItem(res.data);
              renderRdResult(
                res.data,
                res,
                'rd-approve-out',
                '核准研發方案回應（POST /api/product-rd/results/' + snap.rdId + '/approve）'
              );
              var judgeLbl = resolveRdJudgeLabel(res.data);
              var appRenderInfo = classifyRdRenderJob(extractRdRenderJob(res.data));
              var appRenderWarn = Boolean(
                appRenderInfo &&
                  (appRenderInfo.state === 'retrying' ||
                    appRenderInfo.state === 'failed' ||
                    appRenderInfo.state === 'pending')
              );
              var appAt = (res.data.approval && res.data.approval.approvedAt) || res.data.approvedAt || '';
              showGlobalAlert(
                '研發方案 ' +
                  snap.rdId +
                  ' 已由 ' +
                  ((res.data.approval && res.data.approval.actor) || snap.actor) +
                  ' 核准（APPROVED，approvedAt=' +
                  appAt +
                  '，評分來源：' +
                  judgeLbl +
                  (appRenderInfo ? '，母版預覽：' + formatRdRenderSummaryText(appRenderInfo) : '') +
                  '）。',
                appRenderWarn ? 'warn' : 'ok'
              );
              return refreshRdHistory();
            } else {
              var boxErr = $('rd-approve-confirm');
              boxErr.hidden = true;
              syncConfirmLock(boxErr);
              rdPendingApprove = null;
              renderApiAnswer(
                $('rd-approve-out'),
                '核准研發方案失敗（POST /api/product-rd/results/' + snap.rdId + '/approve）',
                res
              );
              var detail = (res.data && (res.data.detail || res.data.error)) || ('HTTP ' + res.status);
              showGlobalAlert('核准研發方案失敗：' + detail, 'err');
            }
          })
          .catch(function (e) {
            if (reqSeq !== rdApproveReqSeq || snap.tenant !== currentTenant()) return;
            showGlobalAlert('連線失敗，請稍後再試：' + ((e && e.message) || e), 'err');
          })
          .finally(function () {
            rdApproveInFlight = false;
            yesBtn.disabled = false;
            noBtn.disabled = false;
            if ($('rd-approve-confirm').hidden) {
              var isApproved =
                state.lastRdResult &&
                state.lastRdResult.approval &&
                state.lastRdResult.approval.status === 'APPROVED';
              prepBtn.disabled = Boolean(isApproved);
              if ($('rd-approve-actor')) $('rd-approve-actor').disabled = Boolean(isApproved);
            }
          });
      });
    }

    if ($('rd-lookup-btn')) {
      $('rd-lookup-btn').addEventListener('click', function () {
        var rid = ($('rd-lookup-id').value || '').trim();
        if (!rid) {
          showGlobalAlert('請先輸入要查詢的研發單號 rdId。', 'err');
          return;
        }
        loadRdDetail(rid);
      });
    }

    if ($('rd-history-more-btn')) {
      $('rd-history-more-btn').addEventListener('click', function () {
        loadMoreRdHistory();
      });
    }
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
