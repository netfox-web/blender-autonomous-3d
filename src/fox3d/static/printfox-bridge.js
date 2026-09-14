'use strict';
(() => {
  const $ = id => document.getElementById(id), base = '/api/print-workspace/printfox', tenant = 'sonaqueen-home';
  let connected = false, busy = false, offset = 0, timer = null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const say = (text, error=false) => { $('pf-message').textContent = text; $('pf-message').className = error ? 'error' : ''; };
  const labels = {pending:'排隊中',claimed:'工作機已接單',running:'生圖中',done:'完成',failed:'失敗',canceled:'已取消',rejected:'驗證失敗，未派工',submission_unknown:'送出結果待核對'};
  async function api(path, options={}) {
    const response = await fetch(base + path, {...options, headers:{'Content-Type':'application/json','X-Tenant-Id':tenant}});
    let data; try { data = await response.json(); } catch { throw Error('服務回應無法讀取，請更新狀態核對。'); }
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '請檢查輸入設定。');
    return data;
  }
  function controls() {
    $('pf-work').hidden = !connected;
    $('pf-connect-button').disabled = busy;
    $('pf-disconnect').disabled = busy || !connected;
    $('pf-generate-button').disabled = busy || !connected;
    $('pf-refresh').disabled = busy || !connected;
  }
  async function action(fn) {
    if (busy) return;
    busy = true; controls();
    try { await fn(); } catch (error) { say(error.message, true); }
    finally { busy = false; controls(); }
  }
  async function connection() {
    const r = await api('/connection'); connected = r.connected;
    $('pf-origin').textContent = r.baseUrl;
    $('pf-connection-status').textContent = connected ? `已連接 · 在線工作機 ${r.status?.workers_online ?? '未知'} · 佇列 ${r.status?.queue ?? '未知'}` : '尚未連接';
    controls(); return r;
  }
  async function designs(reset=true) {
    if (reset) { offset=0; $('pf-designs').replaceChildren(); }
    const r = await api('/designs?q='+encodeURIComponent($('pf-query').value)+'&offset='+offset);
    $('pf-count').textContent = `${r.total} 份設計稿`;
    for (const d of r.items) {
      const card = document.createElement('div'); card.className = 'pf-card';
      card.innerHTML = `<img loading="lazy" alt="${esc(d.title)} 的縮圖" src="${base}/designs/${encodeURIComponent(d.id)}/preview?workspace=${tenant}"><strong>${esc(d.title)}</strong><small>${esc(d.source)} · ${esc(d.id)}${d.jobId ? '<br>生圖任務 '+esc(d.jobId) : ''}</small><button type="button">匯入原圖</button>`;
      card.querySelector('img').onerror = event => { event.target.hidden=true; };
      card.querySelector('button').onclick = () => action(async () => {
        say('下載並核對原圖中…');
        const a = await api('/designs/'+encodeURIComponent(d.id)+'/import', {method:'POST'});
        window.dispatchEvent(new CustomEvent('printfox:imported', {detail:{assetId:a.id}}));
        say(`已匯入「${d.title}」。請在下方商品的「原稿」欄選取，核對尺寸後儲存。`);
      });
      $('pf-designs').append(card);
    }
    offset += r.items.length; $('pf-more').disabled = offset >= r.total;
  }
  function renderTasks(items) {
    $('pf-tasks').innerHTML = items.map(task => `<div class="pf-task"><strong>${esc(labels[task.state] || task.state)} · ${esc(task.progress ?? 0)}%</strong><small>${esc(task.params?.styles?.[0]?.desc || '')}<br>${esc(task.remoteJobId || task.requestId)}</small>${task.message ? `<p>${esc(task.message)}</p>` : ''}<button type="button" data-refresh="${task.requestId}">更新狀態</button>${['pending','claimed','running'].includes(task.state) ? `<button class="secondary" type="button" data-cancel="${task.requestId}">取消這筆生圖</button>` : ''}</div>`).join('') || '<p>尚未從此工作台送出生圖。</p>';
    $('pf-tasks').querySelectorAll('[data-refresh]').forEach(button => button.onclick = () => action(async () => {
      const t = await api('/tasks/'+button.dataset.refresh);
      if (t.remoteJobId && sessionStorage.getItem('fox3d-printfox-pending') === t.requestId) sessionStorage.removeItem('fox3d-printfox-pending');
      await tasks(); if (t.state === 'done') await designs();
    }));
    $('pf-tasks').querySelectorAll('[data-cancel]').forEach(button => button.onclick = () => action(async () => {
      await api('/tasks/'+button.dataset.cancel+'/cancel', {method:'POST'}); await tasks();
    }));
  }
  async function tasks() {
    clearTimeout(timer);
    const r = await api('/tasks'); renderTasks(r.items);
    if (r.items.some(t => ['pending','claimed','running'].includes(t.state))) {
      timer = setTimeout(async () => {
        if (!connected) return;
        if (busy) { timer=setTimeout(()=>tasks().catch(e=>say(e.message,true)),10000); return; }
        try {
          let finished=false;
          for (const t of r.items.filter(t=>['pending','claimed','running'].includes(t.state)).slice(0,10)) {
            const next=await api('/tasks/'+t.requestId); if(next.state==='done') finished=true;
          }
          await tasks(); if(finished) { await designs(); say('生圖已完成，請選擇圖稿匯入。'); }
        } catch(error) { say(error.message,true); }
      },10000);
    }
  }
  $('pf-connect').onsubmit = event => { event.preventDefault(); action(async () => {
    const token = $('pf-token').value; $('pf-token').value='';
    await api('/connection', {method:'POST', body:JSON.stringify({token})});
    await connection(); await designs(); await tasks(); say('已連接 PrintFox。可以匯入原圖或送出一次生圖。');
  }); };
  $('pf-disconnect').onclick = () => action(async () => {
    await api('/connection', {method:'DELETE'}); connected=false; clearTimeout(timer); $('pf-designs').replaceChildren(); $('pf-tasks').replaceChildren(); await connection(); say('已中斷連線。已送出的遠端生圖會繼續，可重新連接後管理。');
  });
  $('pf-search').onsubmit = event => {event.preventDefault(); action(()=>designs());};
  $('pf-more').onclick = () => action(()=>designs(false));
  $('pf-refresh').onclick = () => action(async()=>{await connection(); if(connected){await designs();await tasks();}});
  $('pf-generate').onsubmit = event => { event.preventDefault(); action(async () => {
    const requestId = sessionStorage.getItem('fox3d-printfox-pending') || crypto.randomUUID();
    sessionStorage.setItem('fox3d-printfox-pending', requestId);
    const task = await api('/tasks', {method:'POST',body:JSON.stringify({requestId,prompt:$('pf-prompt').value.trim(),negative:$('pf-negative').value.trim(),size:$('pf-size').value,count:Number($('pf-number').value),engine:$('pf-engine').value})});
    if (task.remoteJobId || task.state==='rejected') sessionStorage.removeItem('fox3d-printfox-pending');
    await tasks(); say(task.message || '已送出單次生圖。完成後可從圖庫匯入，尺寸仍需核對。', ['submission_unknown','rejected'].includes(task.state));
  }); };
  action(async () => { await connection(); if (connected) { await designs(); await tasks(); } });
})();
