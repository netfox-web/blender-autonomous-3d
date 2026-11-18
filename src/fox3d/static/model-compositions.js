'use strict';
(() => {
  const $=id=>document.getElementById(id),tenant='sonaqueen-home',base='/api/product-models';
  let master=null,assets=[],epoch=0,dirty=true,masterDirty=false,busy=false,task=null,seen='';
  // API values are only ever placed via DOM nodes / textContent, never parsed as HTML.
  const h=(tag,props={},...kids)=>{const e=document.createElement(tag);for(const [k,v] of Object.entries(props)){if(k==='dataset')Object.assign(e.dataset,v);else e[k]=v;}e.append(...kids);return e;};
  const option=(text,value)=>new Option(String(text),String(value));
  const preview=(assetId,page)=>`/api/print-workspace/assets/${encodeURIComponent(assetId)}/preview?`+new URLSearchParams({workspace:tenant,page:String(page)});
  async function api(path,options={}){const r=await fetch(base+path,{...options,headers:{'Content-Type':'application/json','X-Tenant-Id':tenant}});const d=await r.json();if(!r.ok)throw new Error(Array.isArray(d.detail)?d.detail.map(x=>x.msg).join('；'):d.detail||'操作失敗');return d;}
  function message(s){$('composition-state').textContent=s;}
  function clear(){for(const id of ['composition-beauty','composition-front'])$(id).hidden=true;$('composition-downloads').replaceChildren();$('composition-identity').textContent='';}
  function buttons(){$('compose').disabled=!master?.readiness.previewReady||masterDirty||busy||!!task||!$('composition-accept').checked;$('composition-cancel').disabled=!task||busy;}
  function changed(){dirty=true;clear();buttons();message('設定已變更，請生成這一版套圖／情境預覽。');}
  function source(row){const a=assets.find(x=>x.id===row.querySelector('select[data-art]').value),page=row.querySelector('select[data-page]'),img=row.querySelector('img');
    page.replaceChildren(...(a?.info.pages||[]).map((_,i)=>option(`第 ${i+1} 頁`,i)));img.hidden=!a;
    const show=()=>{if(a)img.src=preview(a.id,page.value);};page.onchange=()=>{show();changed();};show();}
  function fields(s){$('composition-faces').replaceChildren();const old=s.manifest?.draft;
    $('composition-sku').value=old?.sku||master?.draft.variants?.[0]?.sku||master?.draft.name||'';
    $('composition-scene').value=old?.scene||'STUDIO';
    $('composition-placement').value=old?.placement||'AUTO';$('composition-view').value=old?.view||'THREE_QUARTER';
    for(const f of s.surfaces){const row=document.createElement('div');row.className='composition-surface';row.dataset.component=f.componentId;
      row.append(h('strong',{textContent:`${f.label??''} · ${f.widthMm} × ${f.heightMm} mm`}),
        h('div',{className:'fields'},
          h('label',{},'此面的印刷圖稿',h('select',{dataset:{art:''}},option('保留示意材質',''),...assets.filter(a=>a.usage.canUseForModel).map(a=>option(a.name??'',a.id)))),
          h('label',{},'圖稿頁碼',h('select',{dataset:{page:''}})),
          h('label',{},'旋轉',h('select',{dataset:{rotation:''}},option('0°',0),option('90° 順時針',90),option('180°',180),option('270° 順時針',270)))),
        h('img',{className:'composition-source',hidden:true,alt:'此面的來源圖稿'}));
      const previous=old?.placements.find(x=>x.componentId===f.componentId),art=row.querySelector('select[data-art]');
      if(previous){if(!assets.some(a=>a.id===previous.assetId&&a.usage.canUseForModel)){const opt=document.createElement('option');opt.value=previous.assetId;opt.textContent='原圖稿已停用，請重新選擇';opt.disabled=true;art.append(opt);}art.value=previous.assetId;}
      source(row);if(previous){row.querySelector('select[data-page]').value=String(previous.page);row.querySelector('select[data-rotation]').value=String(previous.rotation);const image=row.querySelector('img');if(art.value)image.src=preview(art.value,previous.page);}
      art.onchange=()=>{source(row);changed();};$('composition-faces').append(row);
    }
    $('composition-accept').checked=false;
  }
  const fetchAllPages=path=>(window.fox3dFetchAllPages||globalThis.fox3dFetchAllPages||require('./src/fox3d/static/fox3d-pagination.js').fetchAllPages)(api,path);
  async function load(reset=false){if(!master)return;const token=epoch,id=master.id;
    const s=await api('/'+id+'/composition');if(token!==epoch||master.id!==id)return;
    if(reset){const a=await fetchAllPages('/assets');if(token!==epoch)return;assets=a.items||[];fields(s);dirty=false;}
    task=['queued','running'].includes(s.state)?s.taskId:null;buttons();
    if(!dirty)message(s.error|| (s.stale?'母版已修改，需重新生成。':task?'Blender 正在生成套圖／情境預覽…':s.generated?'套圖／情境預覽完成。':'尚未生成套圖；可先不選圖稿查看母版場景。'));
    if(s.generated&&!s.stale&&!dirty&&!masterDirty){const url=name=>`${base}/${encodeURIComponent(id)}/composition/files/${encodeURIComponent(name)}?`+new URLSearchParams({workspace:tenant,generation:s.generationId});
      $('composition-beauty').src=url('beauty.png');$('composition-beauty').hidden=false;$('composition-front').src=url('front-closed.png');$('composition-front').hidden=false;
      $('composition-downloads').replaceChildren(...Object.entries({'beauty.png':'下載情境圖','front-closed.png':'下載正面核對圖','model.glb':'下載 GLB 模型','model.blend':'下載 Blender 母版','geometry.json':'下載尺寸紀錄'}).map(([n,l])=>h('a',{href:url(n),download:'',textContent:l})));
      $('composition-identity').textContent=`母版第 ${s.manifest.sourceRevision} 版 · ${s.scenes[s.manifest.scene]} · ${s.manifest.draft.view==='LEFT'?'左前方':s.manifest.draft.view==='FRONT'?'正前方':'右前方'} · 結構識別 ${s.manifest.spec.engineeringHash.slice(0,12)} · ${s.manifest.draft.sku}。尺寸尚待實物核對。`;
      if(seen!==s.generationId){seen=s.generationId;window.dispatchEvent(new Event('product-composition-finished'));}
    }else if(s.stale||!s.generated)clear();
  }
  const safe=fn=>async e=>{e?.preventDefault();try{await fn(e);}catch(err){message(err.message);}};
  window.addEventListener('product-master-selected',safe(async e=>{epoch++;master=e.detail;masterDirty=false;task=null;dirty=true;seen='';clear();$('composition-faces').replaceChildren();buttons();if(master)await load(true);else message('先選母版並補齊尺寸。');}));
  window.addEventListener('product-master-dirty',()=>{masterDirty=true;dirty=true;clear();buttons();});
  window.addEventListener('product-material-changed',()=>{dirty=true;clear();buttons();message('素材用途已更新；請載入上次設定重新核對圖稿。');});
  window.addEventListener('product-batch-submitted',safe(async()=>{dirty=false;await load();}));
  $('composition-form').addEventListener('input',changed);
  $('composition-accept').onchange=buttons;
  $('composition-form').onsubmit=safe(async()=>{if(!master||masterDirty||busy||task)return;const token=epoch;busy=true;buttons();
    const selection={sku:$('composition-sku').value,scene:$('composition-scene').value,view:$('composition-view').value,placement:['LIVING_ROOM','KITCHEN'].includes($('composition-scene').value)?$('composition-placement').value:'AUTO',placements:Array.from(document.querySelectorAll('.composition-surface')).filter(r=>r.querySelector('[data-art]').value).map(r=>({componentId:r.dataset.component,assetId:r.querySelector('[data-art]').value,page:Number(r.querySelector('[data-page]').value),rotation:Number(r.querySelector('[data-rotation]').value)}))};
    $('composition-form').inert=true;
    try{const s=await api('/'+master.id+'/composition',{method:'POST',body:JSON.stringify({expectedRevision:master.revision,inputHash:master.inputHash,assumptionsAccepted:$('composition-accept').checked,selection})});if(token!==epoch)return;task=s.taskId;dirty=false;clear();message('已送出套圖／情境生成工作。');}finally{busy=false;$('composition-form').inert=false;buttons();}});
  $('composition-refresh').onclick=safe(()=>load(true));
  $('composition-cancel').onclick=safe(async()=>{if(task)await api('/'+master.id+'/composition/cancel',{method:'POST',body:JSON.stringify({taskId:task})});message('已送出取消要求。');});
  setInterval(()=>{if(task)load().catch(e=>message(e.message));},5000);
})();
