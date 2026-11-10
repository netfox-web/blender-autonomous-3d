(() => {
  const el = id => document.getElementById(id);
  const line = (parent, label, value, warning = false) => {
    const p = document.createElement('p');
    const name = document.createElement('span');
    name.className = 'label';
    name.textContent = `${label}：`;
    const content = document.createElement('span');
    content.textContent = value;
    if (warning) content.className = 'warning';
    p.append(name, content);
    parent.append(p);
  };
  const value = v => v === null || v === undefined || v === '' ? 'UNAVAILABLE（無資料）' : String(v);
  const flag = (v, mock) => mock === null ? 'UNAVAILABLE（模式未知）' : mock ? 'MOCK（模擬）' : v === true ? '已偵測' : 'UNAVAILABLE（不可用）';
  const list = (parent, items, render, empty) => {
    if (!Array.isArray(items) || !items.length) { line(parent, '清單', empty); return; }
    const ul = document.createElement('ul');
    items.forEach(item => { const li = document.createElement('li'); li.textContent = render(item); ul.append(li); });
    parent.append(ul);
  };
  async function load() {
    const ids = ['health', 'blender', 'gpu', 'routes'];
    ids.forEach(id => { el(id).textContent = '載入中…'; });
    let tenant = 'sonaqueen-home';
    try { tenant = localStorage.getItem('fox3d.tenant') || tenant; } catch (_) { /* storage may be disabled */ }
    const get = async path => {
      const response = await fetch(path, { headers: { 'X-Tenant-Id': tenant } });
      if (!response.ok) throw new Error('request failed');
      return response.json();
    };
    const [health, probe, routes] = await Promise.allSettled([get('/health'), get('/api/probe'), get('/api/admin/features')]);
    if (health.status === 'fulfilled') {
      const h = health.value; el('health').textContent = '';
      line(el('health'), '服務', h.status === 'ok' ? '可連線（ok）' : value(h.status), h.status !== 'ok');
      line(el('health'), '執行模式', h.mock === true ? 'MOCK（模擬）' : h.mock === false ? '非模擬模式' : 'UNAVAILABLE（無資料）', h.mock !== false);
    } else { el('health').textContent = '無法載入服務健康狀態。'; }
    if (probe.status === 'fulfilled' && probe.value && Object.keys(probe.value).length) {
      const p = probe.value;
      // An unknown execution mode cannot establish that a detection is real.
      const mock = health.status === 'fulfilled' && typeof health.value.mock === 'boolean' ? health.value.mock : null;
      el('blender').textContent = ''; el('gpu').textContent = '';
      line(el('blender'), 'Blender', flag(p.realBlender, mock), mock !== false || p.realBlender !== true);
      line(el('blender'), '版本', value(p.blenderVersion));
      line(el('blender'), 'Cycles', flag(p.realCycles, mock), mock !== false || p.realCycles !== true);
      line(el('blender'), 'OptiX', flag(p.realOptix, mock), mock !== false || p.realOptix !== true);
      line(el('blender'), '運算裝置', '');
      list(el('blender'), p.cyclesDevices, d => typeof d === 'object' && d !== null ? JSON.stringify(d) : String(d), '未提供運算裝置');
      line(el('gpu'), 'GPU', flag(p.realGPU, mock), mock !== false || p.realGPU !== true);
      line(el('gpu'), '名稱', value(p.gpuName));
      line(el('gpu'), '驅動程式', value(p.driver));
      line(el('gpu'), '偵測來源', value(p.discoverySource));
      line(el('gpu'), 'GPU 清單', '');
      list(el('gpu'), p.gpus, d => typeof d === 'object' && d !== null ? JSON.stringify(d) : String(d), '未提供 GPU');
      line(el('gpu'), '阻擋原因', '');
      list(el('gpu'), p.blocked, String, '無阻擋原因');
    } else { el('blender').textContent = 'UNAVAILABLE（無法取得主機偵測資料）'; el('gpu').textContent = 'UNAVAILABLE（無法取得主機偵測資料）'; }
    if (routes.status === 'fulfilled' && Array.isArray(routes.value.unclaimed)) {
      el('routes').textContent = '';
      list(el('routes'), routes.value.unclaimed, r => `${r.methods || ''} ${r.path || ''}`, '目前沒有未認領路由');
    } else { el('routes').textContent = '無法載入未認領路由。'; }
  }
  el('refresh').addEventListener('click', load);
  load();
})();
