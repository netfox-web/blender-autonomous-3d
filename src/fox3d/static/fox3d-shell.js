// Shared admin shell: injects the sidebar on every admin page and a Ctrl+K / "/" search
// over every feature (pages, API-only groups, items waiting on data). The list comes from
// /api/admin/features (fox3d/features.py), cached per tab so the sidebar paints instantly.
(function () {
  'use strict';
  var CACHE = 'fox3d.features.v1';
  var KIND = { page: '有畫面', api: '只有 API', blocked: '待資料' };
  var here = location.pathname.replace(/\/+$/, '') || '/admin';
  var data = null;

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }
  function target(f) { return f.href || '/admin/features#' + f.id; }

  function renderSide(d) {
    var old = document.querySelector('.fx-side');
    if (old) old.remove();
    var side = el('aside', { 'class': 'fx-side', 'aria-label': '功能選單' });
    var brand = el('a', { 'class': 'fx-brand', href: '/admin/features' });
    brand.appendChild(el('b', null, '3D'));
    var name = el('span', null, 'Autonomous 3D');
    name.appendChild(el('small', null, '商品 3D 研發工作站'));
    brand.appendChild(name);
    side.appendChild(brand);
    var search = el('button', { 'class': 'fx-search', type: 'button' }, '搜尋功能…');
    search.appendChild(el('kbd', null, 'Ctrl K'));
    search.addEventListener('click', openPalette);
    side.appendChild(search);
    var nav = el('nav', { 'class': 'fx-nav' });
    d.groups.forEach(function (g) {
      // items waiting on data stay in /admin/features and the search, not the sidebar
      var items = d.features.filter(function (f) { return f.group === g.id && f.kind !== 'blocked'; });
      if (!items.length) return;
      nav.appendChild(el('div', { 'class': 'fx-group' }, g.title));
      items.forEach(function (f) {
        var a = el('a', { 'class': 'fx-link', href: target(f) });
        if (f.href && f.href === here) a.setAttribute('aria-current', 'page');
        a.appendChild(el('i', { 'aria-hidden': 'true' }, f.icon || '•'));
        a.appendChild(el('span', null, f.title));
        if (f.kind !== 'page') a.appendChild(el('em', null, KIND[f.kind]));
        nav.appendChild(a);
      });
    });
    side.appendChild(nav);
    side.appendChild(el('div', { 'class': 'fx-foot' }, '按 Ctrl K 或 / 隨時搜尋'));
    document.body.prepend(side);
  }

  // ---- palette ---------------------------------------------------------------------------
  var pal, input, list, sel = 0, shown = [];
  function buildPalette() {
    pal = el('div', { 'class': 'fx-pal', role: 'dialog', 'aria-modal': 'true', 'aria-label': '搜尋功能' });
    pal.hidden = true;
    var box = el('div', { 'class': 'fx-pal-box' });
    input = el('input', { type: 'search', placeholder: '輸入功能、用途或 API 路徑，例如「報價」「打樣」「/api/kd」', 'aria-label': '搜尋功能' });
    list = el('ul', { 'class': 'fx-pal-list', role: 'listbox' });
    box.appendChild(input); box.appendChild(list); pal.appendChild(box);
    document.body.appendChild(pal);
    pal.addEventListener('click', function (e) { if (e.target === pal) closePalette(); });
    input.addEventListener('input', function () { sel = 0; fill(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, shown.length - 1); paint(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); paint(); e.preventDefault(); }
      else if (e.key === 'Enter' && shown[sel]) { go(shown[sel]); }
      else if (e.key === 'Escape') { closePalette(); }
    });
  }
  function haystack(f) {
    return [f.title, f.summary, f.keywords, f.waitingFor, (f.routes || []).map(function (r) { return r.path; }).join(' ')]
      .join(' ').toLowerCase();
  }
  function fill() {
    var q = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    shown = (data ? data.features : []).filter(function (f) {
      var h = haystack(f);
      return q.every(function (w) { return h.indexOf(w) >= 0; });
    });
    list.textContent = '';
    if (!shown.length) { list.appendChild(el('li', { 'class': 'fx-pal-empty' }, '找不到符合的功能')); return; }
    shown.forEach(function (f, i) {
      var li = el('li', { role: 'option' });
      li.appendChild(el('b', null, f.title));
      li.appendChild(el('small', null, f.summary));
      li.appendChild(el('span', { 'class': 'fx-tag ' + f.kind }, KIND[f.kind]));
      li.addEventListener('mouseenter', function () { sel = i; paint(); });
      li.addEventListener('click', function () { go(f); });
      list.appendChild(li);
    });
    paint();
  }
  function paint() {
    Array.prototype.forEach.call(list.children, function (li, i) { li.setAttribute('aria-selected', String(i === sel)); });
    var cur = list.children[sel];
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
  }
  function go(f) {
    closePalette();
    var t = target(f);
    if (t.indexOf('/admin/features#') === 0 && here === '/admin/features') {
      location.hash = f.id;
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    } else location.href = t;
  }
  function openPalette() {
    if (!pal) buildPalette();
    document.documentElement.classList.remove('fx-open');
    pal.hidden = false; input.value = ''; sel = 0; fill(); input.focus();
  }
  function closePalette() { if (pal) pal.hidden = true; }

  document.addEventListener('keydown', function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || '') || (e.target && e.target.isContentEditable);
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); openPalette(); }
    else if (e.key === '/' && !typing) { e.preventDefault(); openPalette(); }
  });

  function boot() {
    document.documentElement.classList.add('fx-shell');
    var t = el('button', { 'class': 'fx-toggle', type: 'button', 'aria-label': '開啟功能選單' }, '☰');
    t.addEventListener('click', function () { document.documentElement.classList.toggle('fx-open'); });
    document.body.appendChild(t);
    try { var c = sessionStorage.getItem(CACHE); if (c) { data = JSON.parse(c); renderSide(data); } } catch (e) { /* storage blocked */ }
    fetch('/api/admin/features', { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (d) {
        data = d; renderSide(d);
        try { sessionStorage.setItem(CACHE, JSON.stringify(d)); } catch (e) { /* storage blocked */ }
        window.dispatchEvent(new CustomEvent('fox3d:features', { detail: d }));
      })
      .catch(function () { if (!data) renderSide({ groups: [], features: [] }); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.fox3dShell = { open: openPalette, data: function () { return data; } };
})();
