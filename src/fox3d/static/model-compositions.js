'use strict';
(() => {
  const $=id=>document.getElementById(id),tenant='sonaqueen-home',base='/api/product-models';
  let master=null,assets=[],epoch=0,dirty=true,masterDirty=false,busy=false,task=null,seen='';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(path,options={}){const r=await fetch(base+path,{...options,headers:{'Content-Type':'application/json','X-Tenant-Id':tenant}});const d=await r.json();if(!r.ok)throw new Error(Array.isArray(d.detail)?d.detail.map(x=>x.msg).join('；'):d.detail||'操作失敗');return d;}
  function message(s){$('composition-state').textContent=s;}
  function clear(){for(const id of ['composition-beauty','composition-front'])$(id).hidden=true;$('composition-downloads').replaceChildren();$('composition-identity').textContent='';}
  function buttons(){$('compose').disabled=!master?.readiness.previewReady||masterDirty||busy||!!task||!$('composition-accept').checked;$('composition-cancel').disabled=!task||busy;}
  function changed(){dirty=true;clear();buttons();message('設定已變更，請生成這一版套圖／情境預覽。');}
  function source(row){const a=assets.find(x=>x.id===row.querySelector('select[data-art]').value),page=row.querySelector('select[data-page]'),img=row.querySelector('img');
    page.innerHTML=(a?.info.pages||[]).map((_,i)=>`<option value="${i}">第 ${i+1} 頁</option>`).join('');img.hidden=!a;
    const show=()=>{if(a)img.src=`/api/print-workspace/assets/${a.id}/preview?workspace=${tenant}&page=${page.value}`;};page.onchange=()=>{show();changed();};show();}
  function fields(s){$('composition-faces').replaceChildren();const old=s.manifest?.draft;
    $('composition-sku').value=old?.sku||master?.draft.variants?.[0]?.sku||master?.draft.name||'';
    $('composition-scene').value=old?.scene||'STUDIO';
    for(const f of s.surfaces){const row=document.createElement('div');row.className='composition-surface';row.dataset.component=f.componentId;
      row.innerHTML=`<strong>${esc(f.label)} · ${f.widthMm} × ${f.heightMm} mm</strong><div class="fields"><label>此面的印刷圖稿<select data-art><option value="">保留示意材質</option>${assets.filter(a=>a.usage.canUseForModel).map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label><label>圖稿頁碼<select data-page></select></label><label>旋轉<select data-rotation><option value="0">0°</option><option value="90">90° 順時針</option><option value="180">180°</option><option value="270">270° 順時針</option></select></label></div><img class="composition-source" hidden alt="此面的來源圖稿">`;
      const previous=old?.placements.find(x=>x.componentId===f.componentId),art=row.querySelector('select[data-art]');
      if(previous){if(!assets.some(a=>a.id===previous.assetId&&a.usage.canUseForModel)){const opt=document.createElement('option');opt.value=previous.assetId;opt.textContent='原圖稿已停用，請重新選擇';opt.disabled=true;art.append(opt);}art.value=previous.assetId;}
      source(row);if(previous){row.querySelector('select[data-page]').value=String(previous.page);row.querySelector('select[data-rotation]').value=String(previous.rotation);const image=row.querySelector('img');if(art.value)image.src=`/api/print-workspace/assets/${art.value}/preview?workspace=${tenant}&page=${previous.page}`;}
      art.onchange=()=>{source(row);changed();};$('composition-faces').append(row);
    }
    $('composition-accept').checked=false;
  }
  async function load(reset=false){if(!master)return;const token=epoch,id=master.id;
    const s=await api('/'+id+'/composition');if(token!==epoch||master.id!==id)return;
    if(reset){const a=await api('/assets');if(token!==epoch)return;assets=a.items;fields(s);dirty=false;}
    task=['queued','running'].includes(s.state)?s.taskId:null;buttons();
    if(!dirty)message(s.error|| (s.stale?'母版已修改，需重新生成。':task?'Blender 正在生成套圖／情境預覽…':s.generated?'套圖／情境預覽完成。':'尚未生成套圖；可先不選圖稿查看母版場景。'));
    if(s.generated&&!s.stale&&!dirty&&!masterDirty){const url=name=>`${base}/${id}/composition/files/${name}?`+new URLSearchParams({workspace:tenant,generation:s.generationId});
      $('composition-beauty').src=url('beauty.png');$('composition-beauty').hidden=false;$('composition-front').src=url('front-closed.png');$('composition-front').hidden=false;
      $('composition-downloads').innerHTML=Object.entries({'beauty.png':'下載情境圖','front-closed.png':'下載正面核對圖','model.glb':'下載 GLB 模型','model.blend':'下載 Blender 母版','geometry.json':'下載尺寸紀錄'}).map(([n,l])=>`<a href="${esc(url(n))}" download>${l}</a>`).join('');
      $('composition-identity').textContent=`母版第 ${s.manifest.sourceRevision} 版 · ${s.scenes[s.manifest.scene]} · 結構識別 ${s.manifest.spec.engineeringHash.slice(0,12)} · ${s.manifest.draft.sku}。尺寸尚待實物核對。`;
      if(seen!==s.generationId){seen=s.generationId;window.dispatchEvent(new Event('product-composition-finished'));}
    }else if(s.stale||!s.generated)clear();
  }
  const safe=fn=>async e=>{e?.preventDefault();try{await fn(e);}catch(err){message(err.message);}};
  window.addEventListener('product-master-selected',safe(async e=>{epoch++;master=e.detail;masterDirty=false;task=null;dirty=true;seen='';clear();$('composition-faces').replaceChildren();buttons();if(master)await load(true);else message('先選母版並補齊尺寸。');}));
  window.addEventListener('product-master-dirty',()=>{masterDirty=true;dirty=true;clear();buttons();});
  window.addEventListener('product-material-changed',()=>{dirty=true;clear();buttons();message('素材用途已更新；請載入上次設定重新核對圖稿。');});
  $('composition-form').addEventListener('input',changed);
  $('composition-accept').onchange=buttons;
  $('composition-form').onsubmit=safe(async()=>{if(!master||masterDirty||busy||task)return;const token=epoch;busy=true;buttons();
    const selection={sku:$('composition-sku').value,scene:$('composition-scene').value,placements:Array.from(document.querySelectorAll('.composition-surface')).filter(r=>r.querySelector('[data-art]').value).map(r=>({componentId:r.dataset.component,assetId:r.querySelector('[data-art]').value,page:Number(r.querySelector('[data-page]').value),rotation:Number(r.querySelector('[data-rotation]').value)}))};
    $('composition-form').inert=true;
    try{const s=await api('/'+master.id+'/composition',{method:'POST',body:JSON.stringify({expectedRevision:master.revision,inputHash:master.inputHash,assumptionsAccepted:$('composition-accept').checked,selection})});if(token!==epoch)return;task=s.taskId;dirty=false;clear();message('已送出套圖／情境生成工作。');}finally{busy=false;$('composition-form').inert=false;buttons();}});
  $('composition-refresh').onclick=safe(()=>load(true));
  $('composition-cancel').onclick=safe(async()=>{if(task)await api('/'+master.id+'/composition/cancel',{method:'POST',body:JSON.stringify({taskId:task})});message('已送出取消要求。');});
  setInterval(()=>{if(task)load().catch(e=>message(e.message));},5000);
})();
