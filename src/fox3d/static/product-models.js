'use strict';
(() => {
  const $=id=>document.getElementById(id), base='/api/product-models', tenant='sonaqueen-home';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const form=$('master-form');
  let selected=null, group=null, dirty=false, offset=0, fileOffset=0, task=null, assets=[], dispose=null, viewId='', busy=false;
  const numeric=['widthMm','depthMm','heightMm','panelMm','backMm','doorMm','gapMm','rows'];
  const labels={idle:'尚未生成',queued:'排隊中',running:'Blender 生成中',succeeded:'生成完成',failed:'生成失敗',cancelled:'已取消'};
  function notice(text,error=false){$('notice').textContent=text;$('notice').className=error?'error':'';}
  async function api(path='',options={}) {
    const r=await fetch(base+path,{...options,headers:{'X-Tenant-Id':tenant,'Content-Type':'application/json'}});
    const data=await r.json();
    if(!r.ok) throw new Error(Array.isArray(data.detail)?data.detail.map(x=>x.msg).join('；'):data.detail||'操作失敗');
    return data;
  }
  const body=x=>JSON.stringify(x);
  function run(fn){return async e=>{if(e)e.preventDefault();try{await fn(e);}catch(err){notice(err.message,true);}};}
  const options=(values,current='')=>Object.entries(values).map(([k,v])=>`<option value="${esc(k)}" ${k===current?'selected':''}>${esc(v)}</option>`).join('');
  function canLeave(){if(busy){notice('正在儲存或送出工作，請稍候。');return false;}return !dirty||window.confirm('有未儲存的修改，確定離開這筆資料？');}
  function staleForm(){dirty=true;$('generate').disabled=true;$('downloads').replaceChildren();$('render-image').hidden=true;$('readiness').textContent='有未儲存修改；請先儲存，再檢查建模條件。';if(dispose){dispose();dispose=null;}$('viewer').replaceChildren();viewId='';}
  async function loadCatalog(append=false){
    if(!append)offset=0;
    const p=new URLSearchParams({q:$('query').value,family:$('family').value,subtype:$('subtype').value,offset:String(offset)});
    const data=await api('/catalog?'+p);
    if(!append)$('groups').replaceChildren();
    for(const g of data.items){const b=document.createElement('button');b.type='button';b.innerHTML=`${esc(g.name)}<small>${esc(data.families[g.family])} · ${g.fileCount} 個檔案 · ${esc(data.subtypes[g.subtype])}</small>`;
      b.onclick=run(async()=>{if(!canLeave())return;group=g;newMaster(g);await loadFiles();});$('groups').append(b);}
    offset+=data.items.length;$('more').hidden=offset>=data.total;
    $('catalog-note').textContent=`${data.total} 個待確認資料夾群組。${data.scannedAt?'掃描時間 '+new Date(data.scannedAt).toLocaleString():'尚未掃描'}。`;
    $('file-count').textContent=data.fileCount.toLocaleString();$('scan').disabled=!data.configured;
    if(!data.configured)notice('尚未設定 NAS 來源，仍可手動建立模型資料。');
    return data;
  }
  async function loadFiles(append=false){
    if(!group)return;if(!append){fileOffset=0;$('source-files').replaceChildren();}
    const gid=group.id;
    const data=await api(`/catalog/${gid}/files?`+new URLSearchParams({q:$('file-query').value,offset:String(fileOffset)}));
    if(group?.id!==gid)return;
    $('sources-panel').hidden=false;$('source-folder').textContent=data.group.folder;$('file-note').textContent=`${data.total} 個檔案；檔名不作為尺寸依據。`;
    for(const f of data.items){const row=document.createElement('div');row.className='file';row.innerHTML=`<strong>${esc(f.name)}</strong><small>${esc(f.path)}</small>`;
      if(['.ai','.pdf','.jpg','.jpeg','.png','.tif','.tiff'].includes(f.extension)){
        const b=document.createElement('button');b.className='secondary';b.type='button';b.textContent='匯入並預覽原稿';
        b.onclick=run(async()=>{b.disabled=true;try{const a=await api(`/files/${f.id}/import`,{method:'POST'});await loadAssets();
          $('source-image').src=`/api/print-workspace/assets/${a.id}/preview?workspace=${encodeURIComponent(tenant)}`;$('source-preview').hidden=false;
          notice('原稿已另存到圖稿庫；可在 SKU 圖稿欄選用。商品尺寸不會自動填入。');}finally{b.disabled=false;}});row.append(b);}
      $('source-files').append(row);}
    fileOffset+=data.items.length;$('files-more').hidden=fileOffset>=data.total;
  }
  async function loadMasters(){const data=await api();$('masters').replaceChildren();$('master-count').textContent=data.items.length;
    for(const item of data.items){const b=document.createElement('button');b.innerHTML=`${esc(item.draft.name)}<small>${item.readiness.previewReady?'可產生外形預覽':'待補建模資料'} · 第 ${item.revision} 版</small>`;
      b.onclick=run(async()=>{if(!canLeave())return;selected=await api('/'+item.id);fill(selected.draft);group=null;$('sources-panel').hidden=true;
        if(selected.draft.sourceGroupId){const info=await api(`/catalog/${selected.draft.sourceGroupId}/files`);group=info.group;await loadFiles();}
        await showStatus();});$('masters').append(b);}
  }
  async function loadAssets(){const r=await fetch('/api/print-workspace/assets',{headers:{'X-Tenant-Id':tenant}});if(!r.ok)throw new Error('圖稿庫讀取失敗');assets=(await r.json()).items;
    document.querySelectorAll('.variant-art').forEach(s=>{const value=s.value;s.innerHTML=assetOptions(value);});}
  function assetOptions(current=''){return '<option value="">尚未選圖稿</option>'+assets.map(a=>`<option value="${esc(a.id)}" ${a.id===current?'selected':''}>${esc(a.name||a.originalName||a.id.slice(0,12))}</option>`).join('');}
  function addVariant(v={}){const row=document.createElement('div');row.className='row variant';row.innerHTML=`<div class="fields"><label>SKU<input class="variant-sku" required maxlength="120" value="${esc(v.sku)}"></label><label>圖稿<select class="variant-art">${assetOptions(v.artworkAssetId)}</select></label></div><label>圖案／版本備註<input class="variant-note" maxlength="1000" value="${esc(v.note)}"></label>`;removeButton(row);$('variants').append(row);}
  function addFace(f={}){const row=document.createElement('div');row.className='row face';row.innerHTML=`<div class="fields"><label>印刷面名稱<input data-key="name" required maxlength="100" value="${esc(f.name)}" placeholder="例如 第一片門板正面"></label><label>面寬（mm）<input data-key="widthMm" type="number" min="0.01" max="6000" step="any" required value="${esc(f.widthMm)}"></label><label>面高（mm）<input data-key="heightMm" type="number" min="0.01" max="6000" step="any" required value="${esc(f.heightMm)}"></label><label>出血（mm）<input data-key="bleedMm" type="number" min="0" max="20" step="any" required value="${esc(f.bleedMm??0)}"></label></div><label>印刷面尺寸依據<input data-key="evidence" required maxlength="1500" value="${esc(f.evidence)}"></label><label>原點／治具方向紀錄<input data-key="originNote" maxlength="1500" value="${esc(f.originNote)}"></label>`;removeButton(row);$('faces').append(row);}
  function removeButton(row){const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent='移除此筆';b.onclick=()=>{row.remove();staleForm();};row.append(b);}
  function fill(d={}){form.reset();for(const [key,value] of Object.entries(d)){const input=form.elements.namedItem(key);if(input)input.value=value??'';}
    $('variants').replaceChildren();(d.variants||[]).forEach(addVariant);$('faces').replaceChildren();(d.printFaces||[]).forEach(addFace);
    dirty=false;task=null;$('accept').checked=false;$('cancel').disabled=true;$('status').disabled=!selected;$('revision').textContent=selected?`第 ${selected.revision} 版`:'新模型資料';
    $('render-image').hidden=true;$('downloads').replaceChildren();$('render-state').textContent='';if(dispose){dispose();dispose=null;}$('viewer').replaceChildren();viewId='';readiness();toggleCabinet();}
  function newMaster(g=null){selected=null;$('file-query').value='';$('source-preview').hidden=true;$('sources-panel').hidden=!g;
    fill({name:g?.name||'',family:g?.family||'coaster',subtype:g?.subtype||'other',geometry:'PENDING'});notice(g?'已選來源群組；請確認名稱、結構與實際尺寸，再儲存。':'請填模型資料；尺寸未知可以先留白儲存。');}
  function toggleCabinet(){$('cabinet-fields').hidden=!form.elements.geometry.value.endsWith('CABINET');}
  function readiness(){const r=selected?.readiness;$('readiness').textContent=r?(r.previewReady?'資料足以生成簡化外形預覽；尚未完成實物／印刷校正。':r.missing):'先儲存商品資料；不確定的尺寸請留白。';
    $('assumptions').innerHTML=(r?.assumptions||[]).map(x=>`<li>${esc(x)}</li>`).join('');$('generate').disabled=dirty||!r?.previewReady||!$('accept').checked||busy;}
  function draft(){const d={};for(const k of ['name','family','subtype','geometry','dimensionEvidence','structureEvidence','notes'])d[k]=form.elements.namedItem(k).value;
    for(const k of numeric){const v=form.elements.namedItem(k).value;d[k]=v===''?null:Number(v);}d.sourceGroupId=group?.id||selected?.draft.sourceGroupId||'';
    d.variants=Array.from(document.querySelectorAll('.variant')).map(r=>({sku:r.querySelector('.variant-sku').value,artworkAssetId:r.querySelector('.variant-art').value,note:r.querySelector('.variant-note').value}));
    d.printFaces=Array.from(document.querySelectorAll('.face')).map(r=>{const f={};r.querySelectorAll('[data-key]').forEach(e=>f[e.dataset.key]=e.type==='number'?Number(e.value):e.value);return f;});return d;}
  async function showStatus(){if(!selected)return;const id=selected.id;const s=await api('/'+id+'/preview');if(selected?.id!==id)return;task=['queued','running'].includes(s.state)?s.taskId:null;
    const active=['queued','running'].includes(s.state);$('cancel').disabled=!active;$('render-state').textContent=`${labels[s.state]||s.state}${s.error?' · '+s.error:''}${s.stale?' · 模型已修改，需重新生成':''}`;
    $('generate').disabled=active||dirty||!selected.readiness.previewReady||!$('accept').checked||busy;
    if(s.generated&&!s.stale&&!dirty){const url=fmt=>`${base}/${id}/files/${fmt}?`+new URLSearchParams({workspace:tenant,generation:s.generationId});
      if(viewId!==s.generationId){if(dispose)dispose();dispose=window.mountRecipeViewer($('viewer'),s.spec);viewId=s.generationId;
        $('render-image').src=url('png');$('render-image').hidden=false;$('downloads').innerHTML=['png','blend','glb','geometry'].map(f=>`<a href="${esc(url(f))}" download>${{png:'下載棚拍預覽',blend:'下載 Blender 模型',glb:'下載 GLB 模型',geometry:'下載尺寸紀錄'}[f]}</a>`).join('');}}
    else{$('downloads').replaceChildren();$('render-image').hidden=true;}}
  $('search-form').onsubmit=run(()=>loadCatalog());$('more').onclick=run(()=>loadCatalog(true));
  $('file-search').onsubmit=run(()=>loadFiles());$('files-more').onclick=run(()=>loadFiles(true));
  $('scan').onclick=run(async()=>{$('scan').disabled=true;notice('正在唯讀掃描已設定的 NAS 商品資料夾…');try{const s=await api('/catalog/refresh',{method:'POST'});await loadCatalog();notice(`掃描完成：${s.fileCount} 個檔案、${s.groupCount} 個待確認群組。`);}finally{$('scan').disabled=false;}});
  $('new').onclick=()=>{if(canLeave()){group=null;newMaster();}};
  form.addEventListener('input',staleForm);form.elements.geometry.addEventListener('change',toggleCabinet);
  $('add-variant').onclick=()=>{addVariant();staleForm();};$('add-face').onclick=()=>{addFace();staleForm();};
  form.onsubmit=run(async()=>{if(busy)return;busy=true;form.inert=true;$('save').disabled=true;try{selected=await api(selected?'/'+selected.id:'',{method:selected?'PUT':'POST',body:body({draft:draft(),expectedRevision:selected?.revision||0})});fill(selected.draft);await loadMasters();await showStatus();notice('模型資料已儲存。'+(selected.readiness.missing||'可確認簡化說明後生成 3D。'));}finally{busy=false;form.inert=false;$('save').disabled=false;readiness();}});
  $('accept').onchange=readiness;
  $('generate').onclick=run(async()=>{if(!selected||dirty)return;busy=true;readiness();try{await api('/'+selected.id+'/preview',{method:'POST',body:body({expectedRevision:selected.revision,inputHash:selected.inputHash,assumptionsAccepted:$('accept').checked})});notice('已送出真實 Blender 生成工作，畫面會更新進度。');}finally{busy=false;await showStatus();}});
  $('status').onclick=run(showStatus);$('cancel').onclick=run(async()=>{await api('/'+selected.id+'/cancel',{method:'POST',body:body({taskId:task})});notice('已送出取消要求。');await showStatus();});
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  setInterval(()=>{if(task)showStatus().catch(err=>notice(err.message,true));},5000);
  run(async()=>{const data=await api('/catalog');$('family').insertAdjacentHTML('beforeend',options(data.families));$('subtype').insertAdjacentHTML('beforeend',options(data.subtypes));$('edit-family').innerHTML=options(data.families);$('edit-subtype').innerHTML=options(data.subtypes,'other');
    await loadAssets();newMaster();await loadCatalog();await loadMasters();notice('先從左側找商品，或手動建立模型。尺寸依據與印刷面會分開保存。');})();
})();
