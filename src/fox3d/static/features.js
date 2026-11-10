// /admin/features: searchable directory of every feature. Data from /api/admin/features.
(function () {
  'use strict';
  var KIND = { page: '有畫面', api: '只有 API', blocked: '待資料' };
  var data = null, kind = '', q = '';
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }
  function matches(f) {
    if (kind && f.kind !== kind) return false;
    var h = [f.title, f.summary, f.keywords, f.waitingFor, (f.routes || []).map(function (r) { return r.path; }).join(' ')].join(' ').toLowerCase();
    return q.split(/\s+/).filter(Boolean).every(function (w) { return h.indexOf(w) >= 0; });
  }

  function readable(path, methods) { return methods.split(',').indexOf('GET') >= 0 && path.indexOf('{') < 0 && path.indexOf('/api/') === 0; }

  function look(path, out, btn) {
    btn.disabled = true; out.hidden = false; out.textContent = '讀取中…';
    fetch(path, { headers: { 'X-Tenant-Id': $('fd-tenant').value.trim() || 'sonaqueen-home', Accept: 'application/json' } })
      .then(function (r) { return r.text().then(function (t) { return { s: r.status, t: t }; }); })
      .then(function (r) {
        var body = r.t;
        try { body = JSON.stringify(JSON.parse(r.t), null, 2); } catch (e) { /* not JSON */ }
        if (body.length > 20000) body = body.slice(0, 20000) + '\n…（只顯示前 20,000 字）';
        out.textContent = 'HTTP ' + r.s + '\n' + body;
      })
      .catch(function (e) { out.textContent = '讀取失敗：' + e; })
      .then(function () { btn.disabled = false; });
  }

  function routeList(routes) {
    var ul = el('ul', { 'class': 'fd-routes' });
    routes.forEach(function (r) {
      var li = el('li');
      li.appendChild(el('span', { 'class': 'fd-m' }, r.methods.replace(/,/g, '/')));
      li.appendChild(el('code', null, r.path));
      ul.appendChild(li);
      if (readable(r.path, r.methods)) {
        var b = el('button', { type: 'button' }, '查看');
        var out = el('pre', { 'class': 'fd-out' }); out.hidden = true;
        b.addEventListener('click', function () { look(r.path, out, b); });
        li.appendChild(b);
        ul.appendChild(out);
      }
    });
    return ul;
  }

  function card(f) {
    var c = el('article', { 'class': 'fd-card', id: f.id });
    var top = el('div', { 'class': 'fd-top' });
    top.appendChild(el('h3', null, f.title));
    top.appendChild(el('span', { 'class': 'fd-tag ' + f.kind }, KIND[f.kind]));
    c.appendChild(top);
    c.appendChild(el('p', null, f.summary));
    if (f.waitingFor) c.appendChild(el('p', { 'class': 'fd-wait' }, '等待：' + f.waitingFor));
    if (f.href) c.appendChild(el('a', { 'class': 'fd-open', href: f.href }, '開啟'));
    var routes = f.routes || [];
    if (routes.length && f.kind === 'api') c.appendChild(routeList(routes));
    else if (routes.length) {
      var d = el('details', { 'class': 'fd-more' });
      d.appendChild(el('summary', null, '後端 API（' + routes.length + '）'));
      d.appendChild(routeList(routes));
      c.appendChild(d);
    }
    return c;
  }

  function render() {
    var list = $('fd-list'); list.textContent = '';
    if (!data) return;
    var all = data.features;
    $('fd-n-all').textContent = all.length;
    ['page', 'api', 'blocked'].forEach(function (k) { $('fd-n-' + k).textContent = all.filter(function (f) { return f.kind === k; }).length; });
    var any = false;
    data.groups.forEach(function (g) {
      var items = all.filter(function (f) { return f.group === g.id && matches(f); });
      if (!items.length) return;
      any = true;
      var sec = el('section', { 'class': 'fd-group' });
      sec.appendChild(el('h2', null, g.title));
      var grid = el('div', { 'class': 'fd-grid' });
      items.forEach(function (f) { grid.appendChild(card(f)); });
      sec.appendChild(grid); list.appendChild(sec);
    });
    if (data.unclaimed && data.unclaimed.length && !kind) {
      any = true;
      var sec = el('section', { 'class': 'fd-group' });
      sec.appendChild(el('h2', null, '其他未歸類 API'));
      var grid = el('div', { 'class': 'fd-grid' });
      grid.appendChild(card({ id: 'unclaimed', kind: 'api', title: '未歸類', summary: '還沒有分到任何功能群組的路由。', routes: data.unclaimed }));
      sec.appendChild(grid); list.appendChild(sec);
    }
    if (!any) list.appendChild(el('p', { 'class': 'fd-empty' }, '找不到符合的功能。'));
    focusHash();
  }

  function focusHash() {
    var id = '';
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (e) { return; }
    if (!id) return;
    var c = document.getElementById(id);
    if (!c) { if (kind || q) { kind = ''; q = ''; $('fd-q').value = ''; setChip(''); render(); } return; }
    Array.prototype.forEach.call(document.querySelectorAll('.fd-card.hit'), function (n) { n.classList.remove('hit'); });
    c.classList.add('hit');
    c.scrollIntoView({ block: 'center' });
  }
  function setChip(k) {
    Array.prototype.forEach.call(document.querySelectorAll('.fd-chips button'), function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-kind') === k)); });
  }

  function boot() {
    $('fd-q').addEventListener('input', function (e) { q = e.target.value.trim().toLowerCase(); render(); });
    Array.prototype.forEach.call(document.querySelectorAll('.fd-chips button'), function (b) {
      b.addEventListener('click', function () { kind = b.getAttribute('data-kind'); setChip(kind); render(); });
    });
    try { var t = localStorage.getItem('fox3d.tenant'); if (t) $('fd-tenant').value = t; } catch (e) { /* storage blocked */ }
    $('fd-tenant').addEventListener('change', function (e) { try { localStorage.setItem('fox3d.tenant', e.target.value.trim()); } catch (x) { /* storage blocked */ } });
    window.addEventListener('hashchange', focusHash);
    fetch('/api/admin/features', { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (d) { data = d; render(); })
      .catch(function (e) { $('fd-list').textContent = '功能清單載入失敗：' + e; });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
