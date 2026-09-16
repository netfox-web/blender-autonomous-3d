(() => {
  'use strict';
  const $ = id => document.getElementById(id), tenant = 'sonaqueen-home', base = '/api/product-models';
  const scenes = {STUDIO:'白底棚拍',WARM_ROOM:'暖色簡易背景',COOL_ROOM:'冷色簡易背景',LIVING_ROOM:'客廳',KITCHEN:'廚房'};
  const views={THREE_QUARTER:'右前方',LEFT:'左前方',FRONT:'正前方'},places={AUTO:'自動位置',FLOOR:'地板',SURFACE:'茶几／檯面'};
  const states = {queued:'等待中',running:'生成中',succeeded:'完成',failed:'失敗',cancelled:'已取消',interrupted:'已中斷'};
  const drafts = new Map();
  let master=null, dirty=false, task=null, busy=false, pending=[], offset=0, epoch=0, lastGeneration=null;
  const esc = v => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const message = v => {$('batch-message').textContent=v;};
  async function api(path,options={}) {
    const r=await fetch(base+path,{...options,headers:{'Content-Type':'application/json','X-Tenant-Id':tenant}});
    const d=await r.json(); if(!r.ok)throw Error(Array.isArray(d.detail)?d.detail.map(x=>x.msg).join('；'):d.detail||'操作失敗'); return d;
  }
  function buttons() {
    const blocked=!master?.readiness.previewReady||dirty||busy||!!task;
    $('batch-add').disabled=blocked;
    $('batch-submit').disabled=blocked||!pending.length||!$('batch-accept').checked;
    $('batch-clear').disabled=busy||!!task;
    $('batch-cancel').disabled=!task||busy;
  }
  function drawPending() {
    $('batch-pending').innerHTML=pending.map((s,i)=>`<li>${esc(s.sku)} · ${scenes[s.scene]} · ${views[s.view||"THREE_QUARTER"]} · ${places[s.placement||"AUTO"]} · ${s.placements.length} 個貼圖面 <button type="button" class="secondary" data-remove="${i}">移除</button></li>`).join('');
    $('batch-count').textContent=`待送 ${pending.length} / 24 款`;
    $('batch-pending').querySelectorAll('[data-remove]').forEach(b=>{b.disabled=busy||!!task;b.onclick=()=>{pending.splice(Number(b.dataset.remove),1);$('batch-accept').checked=false;drawPending();};});
    if(master)drafts.set(master.id+master.inputHash,pending);
    buttons();
  }
  async function history() {
    if(!master)return;const token=epoch,id=master.id;
    const d=await api(`/${id}/compositions?offset=${offset}`);if(token!==epoch)return;
    $('batch-history-count').textContent=d.total?`共 ${d.total} 款；目前第 ${offset+1}～${offset+d.items.length} 款`:'尚無已保存成果';
    $('batch-history-prev').disabled=offset===0;$('batch-history-next').disabled=offset+d.items.length>=d.total;
    $('batch-history').innerHTML=d.items.map(row=>{
      const url=n=>`${base}/${id}/composition/files/${n}?`+new URLSearchParams({workspace:tenant,generation:row.generationId});
      return `<article class="variant-card"><h4>${esc(row.sku)}</h4><p>${esc(scenes[row.scene]||row.scene)} · ${esc(views[row.view||"THREE_QUARTER"])} · 母版第 ${esc(row.sourceRevision)} 版</p>`+
        (row.available?`<img loading="lazy" src="${esc(url('beauty.png'))}" alt="${esc(row.sku)}套圖預覽"><div>${Object.entries({'beauty.png':'情境圖','front-closed.png':'正面核對','model.glb':'3D 模型','model.blend':'Blender 母版'}).map(([n,l])=>`<a href="${esc(url(n))}" download>${l}</a>`).join('')}</div>`:`<p>${esc(row.error||'此成果目前不可下載')}</p>`)+`<p class="muted">展示預覽 · 尺寸待實物核對</p></article>`;
    }).join('');
  }
  async function status() {
    if(!master)return;const token=epoch,id=master.id;
    const s=await api(`/${id}/composition`);if(token!==epoch)return;
    const before=task;task=['queued','running'].includes(s.state)?s.taskId:null;
    $('batch-progress').innerHTML=(s.batch?.rows||[]).map(r=>`<li>${esc(r.sku)} · ${esc(scenes[r.scene])} · ${esc(views[r.view||"THREE_QUARTER"])}：${esc(states[r.state]||r.state)}${r.error?' — '+esc(r.error):''}</li>`).join('');
    if(s.batch)message(`${s.batch.name}：${s.batch.rows.filter(r=>r.state==='succeeded').length} / ${s.batch.rows.length} 完成`+(s.error?'；'+s.error:''));
    buttons();
    if((before&&!task)||lastGeneration!==s.generationId){lastGeneration=s.generationId;await history();drawPending();}
  }
  const safe=fn=>async()=>{try{await fn();}catch(e){message(e.message);}};
  $('batch-add').onclick=safe(async()=>{
    const sku=$('composition-sku').value.trim();if(!sku)throw Error('請先在上方填款式名稱');
    const chosen=[...document.querySelectorAll('[name="batch-scene"]:checked')].map(e=>e.value);
    if(!chosen.length)throw Error('至少選一個背景');
    const placements=[...document.querySelectorAll('.composition-surface')].filter(r=>r.querySelector('[data-art]').value).map(r=>({componentId:r.dataset.component,assetId:r.querySelector('[data-art]').value,page:Number(r.querySelector('[data-page]').value),rotation:Number(r.querySelector('[data-rotation]').value)}));
    if(pending.length+chosen.length>24)throw Error('每批最多 24 款，請分批送出');
    const view=$('composition-view').value,place=scene=>['LIVING_ROOM','KITCHEN'].includes(scene)?$('composition-placement').value:'AUTO';
    if(chosen.some(scene=>pending.some(s=>s.sku===sku&&s.scene===scene&&(s.view||'THREE_QUARTER')===view&&(s.placement||'AUTO')===place(scene))))throw Error('此款式、場景、位置與角度已在清單中；換圖時請使用不同款式名稱');
    pending.push(...chosen.map(scene=>({sku,scene,view,placement:place(scene),placements:structuredClone(placements)})));
    $('batch-accept').checked=false;drawPending();message('已加入清單；可以在上方換下一款圖稿再加入。');
  });
  $('batch-clear').onclick=()=>{pending=[];$('batch-accept').checked=false;drawPending();};
  $('batch-accept').onchange=buttons;
  $('batch-submit').onclick=safe(async()=>{
    if(!master||dirty||busy||task||!pending.length)return;
    const token=epoch,id=master.id;busy=true;drawPending();
    try {
      const d=await api(`/${id}/composition/batch`,{method:'POST',body:JSON.stringify({expectedRevision:master.revision,inputHash:master.inputHash,assumptionsAccepted:$('batch-accept').checked,batch:{name:$('batch-name').value,selections:pending}})});
      if(token!==epoch)return;task=d.taskId;pending=[];$('batch-accept').checked=false;
      message('已送出批次，Blender 將逐款生成。關閉頁面後仍會繼續；請保持工作台服務開啟。');
      window.dispatchEvent(new Event('product-batch-submitted'));await status();
    } finally {busy=false;drawPending();}
  });
  $('batch-cancel').onclick=safe(async()=>{if(task)await api(`/${master.id}/composition/cancel`,{method:'POST',body:JSON.stringify({taskId:task})});message('已要求取消；已完成款式仍保留。');});
  $('batch-history-refresh').onclick=safe(async()=>{await status();await history();});
  $('batch-history-prev').onclick=safe(async()=>{offset=Math.max(0,offset-12);await history();});
  $('batch-history-next').onclick=safe(async()=>{offset+=12;await history();});
  window.addEventListener('product-master-selected',e=>{
    epoch++;master=e.detail;dirty=false;task=null;offset=0;lastGeneration=null;pending=master?(drafts.get(master.id+master.inputHash)||[]):[];
    $('batch-history').replaceChildren();$('batch-progress').replaceChildren();$('batch-history-count').textContent='';$('batch-accept').checked=false;
    $('batch-readiness').textContent=master?(master.readiness.previewReady?'此外形可生成展示預覽；實物尺寸仍需核對。':master.readiness.missing):'先選模型。';
    message('');drawPending();safe(async()=>{await status();await history();})();
  });
  window.addEventListener('product-master-dirty',()=>{dirty=true;buttons();message('母版尚未儲存，請先儲存並重新核對清單。');});
  window.addEventListener('product-material-changed',()=>{history().catch(e=>message(e.message));});
  setInterval(()=>{if(master)status().catch(e=>message(e.message));},5000);
})();
