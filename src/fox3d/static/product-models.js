'use strict';
(() => {
  const $=id=>document.getElementById(id), base='/api/product-models', tenant='sonaqueen-home';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const form=$('master-form');
  let usageRoles={}, reviewAsset=null, usageLimit=20, draftSourceGroupId='', draftRecipeReference=null, recipeReferences=[];
  let selected=null, group=null, dirty=false, offset=0, fileOffset=0, task=null, assets=[], dispose=null, viewId='', busy=false;
  let masterInventory=[], categoryTree=[], categoryNodes=new Map(), categoryFilter='all', classification=null, classificationDirty=false, pendingNewCategory=null;
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
  function canLeave(){if(busy){notice('正在儲存或送出工作，請稍候。');return false;}return !(dirty||classificationDirty)||window.confirm('有未儲存的修改，確定離開這筆資料？');}
  function staleForm(){window.dispatchEvent(new Event('product-master-dirty'));dirty=true;$('generate').disabled=true;$('downloads').replaceChildren();$('render-image').hidden=true;$('readiness').textContent='有未儲存修改；請先儲存，再檢查建模條件。';if(dispose){dispose();dispose=null;}$('viewer').replaceChildren();viewId='';}
  async function loadCatalog(append=false){
    if(!append)offset=0;
    const p=new URLSearchParams({q:$('query').value,family:$('family').value,subtype:$('subtype').value,offset:String(offset)});
    const data=await api('/catalog?'+p);
    if(!append)$('groups').replaceChildren();
    for(const g of data.items){const b=document.createElement('button');b.type='button';b.innerHTML=`${esc(g.name)}<small>${esc(data.families[g.family])} · ${g.fileCount} 個檔案 · ${esc(data.subtypes[g.subtype])}</small>`;
      b.onclick=run(async()=>{group=g;$('source-preview').hidden=true;await loadFiles();notice('已開啟素材資料夾；不會自動建立或修改模板。');});$('groups').append(b);}
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
        const b=document.createElement('button');b.className='secondary';b.type='button';b.textContent='預覽並分類素材';
        b.onclick=run(async()=>{b.disabled=true;try{const a=await api(`/files/${f.id}/import`,{method:'POST'});await loadAssets();
          $('source-image').src=`/api/print-workspace/assets/${a.id}/preview?workspace=${encodeURIComponent(tenant)}`;$('source-preview').hidden=false;
          review(a.id);notice('素材已另存；請核對用途。待分類與參考圖不能選作套圖原稿，商品尺寸不會自動填入。');}finally{b.disabled=false;}});row.append(b);}
      $('source-files').append(row);}
    fileOffset+=data.items.length;$('files-more').hidden=fileOffset>=data.total;
  }
  function indexCategories(nodes,parents=[]){for(const n of nodes){categoryNodes.set(n.id,{...n,path:[...parents,n.label]});indexCategories(n.children||[],[...parents,n.label]);}}
  function categoryMatches(item,key){if(key==='all')return true;const n=categoryNodes.get(key);return n?.children?n.children.some(c=>categoryMatches(item,c.id)):item.classification.categoryId===key;}
  function renderCategories(){
    const expanded=new Set(Array.from($('category-tree').querySelectorAll('details[open]')).map(e=>e.dataset.category));
    const first=!$('category-tree').children.length;$('category-tree').replaceChildren();
    function count(key){return masterInventory.filter(x=>categoryMatches(x,key)).length;}
    function button(key,label,parent=false){const b=document.createElement('button');b.type='button';b.dataset.category=key;b.className=parent?'category-parent':'';b.setAttribute('aria-current',String(categoryFilter===key));b.innerHTML=`<span>${esc(label)}</span><small>${count(key)}</small>`;b.onclick=()=>{categoryFilter=key;renderCategories();renderInventory();};return b;}
    $('category-tree').append(button('all','全部模型'));
    function list(nodes){const ul=document.createElement('ul');for(const n of nodes){const li=document.createElement('li');if(n.children){const d=document.createElement('details');d.dataset.category=n.id;d.open=(first&&n.id==='wood')||expanded.has(n.id);const summary=document.createElement('summary');summary.textContent=n.label+'（'+count(n.id)+'）';d.append(summary,button(n.id,'查看全部'+n.label,true),list(n.children));li.append(d);}else li.append(button(n.id,n.label));ul.append(li);}return ul;}
    $('category-tree').append(list(categoryTree));
  }
  function renderInventory(){
    const q=$('model-query').value.trim().toLocaleLowerCase(),state=$('model-state').value;
    const found=masterInventory.filter(x=>categoryMatches(x,categoryFilter)&&(!state||x.templateState===state)&&(!q||[x.draft.name,...x.draft.variants.map(v=>v.sku),...x.classification.path].join(' ').toLocaleLowerCase().includes(q)));
    $('category-breadcrumb').textContent=categoryFilter==='all'?'全部模型':categoryNodes.get(categoryFilter).path.join(' › ');
    const generated=found.filter(x=>x.templateState==='PREVIEW_AVAILABLE').length;
    $('model-filter-count').textContent=`此篩選共 ${found.length} 個模型：${generated} 個已生成、${found.length-generated} 個待完成草稿。分類中的數字不包含素材檔案。`;
    $('generated-section').hidden=state==='DRAFT';$('draft-section').hidden=state==='PREVIEW_AVAILABLE';
    $('masters').replaceChildren();$('generated-masters').replaceChildren();
    if(!generated)$('generated-masters').textContent='此篩選尚無已生成模型。';
    if(found.length===generated)$('masters').textContent='此篩選沒有待完成草稿。可選分類後建立新草稿，未知尺寸留白。';
    for(const item of found){const b=document.createElement('button');b.type='button';b.setAttribute('aria-pressed',String(selected?.id===item.id));b.innerHTML=`${esc(item.draft.name)}<small>${esc(item.classification.path.join(' › '))}</small><small>${item.templateState==='PREVIEW_AVAILABLE'?'已生成外形，待實物核對':item.readiness.previewReady?'草稿：待生成或重新核對':'草稿：待補尺寸／結構'} · 第 ${item.revision} 版</small>`;
      b.onclick=run(async()=>{if(!canLeave())return;pendingNewCategory=null;selected=await api('/'+item.id);fill(selected.draft);group=null;$('sources-panel').hidden=true;$('source-preview').hidden=true;
        if(selected.draft.sourceGroupId){const info=await api(`/catalog/${selected.draft.sourceGroupId}/files`);group=info.group;await loadFiles();}
        renderInventory();switchView('models');await showStatus();});$(item.templateState==='PREVIEW_AVAILABLE'?'generated-masters':'masters').append(b);}
  }
  async function loadMasters(){const data=await api();masterInventory=data.items;categoryTree=data.categoryTree;categoryNodes=new Map();indexCategories(categoryTree);
    const generated=data.items.filter(x=>x.templateState==='PREVIEW_AVAILABLE').length;$('generated-count').textContent=generated;$('master-count').textContent=data.items.length-generated;
    renderCategories();renderInventory();
    const old=$('model-category').value;$('model-category').innerHTML=Array.from(categoryNodes.values()).filter(n=>!n.children).map(n=>`<option value="${esc(n.id)}">${esc(n.path.join(' › '))}</option>`).join('');if(categoryNodes.has(old))$('model-category').value=old;
  }
  async function showClassification(){classification=null;classificationDirty=false;$('model-category').disabled=!selected;$('classification-save').disabled=true;$('classification-refresh').disabled=!selected;
    if(!selected){$('model-category').value=pendingNewCategory||'unclassified';$('classification-note').textContent='先儲存模型，再保存所在分類。分類不會替你填入尺寸或建立特殊外形。';return;}
    const mid=selected.id;const c=await api('/'+mid+'/classification');if(selected?.id!==mid)return;classification=c;$('model-category').value=pendingNewCategory||c.categoryId;$('classification-save').disabled=false;
    $('classification-note').textContent=c.path.join(' › ')+' · '+(c.source==='OPERATOR'?'已保存的分類':'依模型欄位暫分，可調整')+' · 分類第 '+c.revision+' 版。';
  }
  $('model-query').oninput=$('model-state').onchange=renderInventory;
  $('model-category').onchange=()=>{classificationDirty=true;};
  $('classification-refresh').onclick=run(showClassification);
  $('classification-form').onsubmit=run(async()=>{if(!selected||!classification)return;const mid=selected.id;const key=$('model-category').value;$('classification-form').inert=true;try{await api('/'+mid+'/classification',{method:'PUT',body:body({categoryId:key,expectedRevision:classification.revision})});pendingNewCategory=null;await showClassification();await loadMasters();notice('分類已儲存；模型尺寸、圖稿與已生成成果保持不變。');}finally{$('classification-form').inert=false;}});
  async function loadAssets(){const data=await api('/assets');assets=data.items;usageRoles=data.roles;
    const filter=$('usage-filter').value;$('usage-filter').innerHTML='<option value="">全部用途</option>'+options(usageRoles,filter);$('usage-role').innerHTML=options(usageRoles,reviewAsset?.usage.role||'UNCLASSIFIED');
    document.querySelectorAll('.variant-art').forEach(s=>{const value=s.value;s.innerHTML=assetOptions(value);});renderUsageList();}
  function assetOptions(current=''){const allowed=assets.filter(a=>a.usage.canUseForModel);return '<option value="">尚未選印刷圖稿</option>'+
    (current&&!allowed.some(a=>a.id===current)?`<option value="${esc(current)}" selected disabled>原關聯素材未確認或已改用途，請重新選擇</option>`:'')+
    allowed.map(a=>`<option value="${esc(a.id)}" ${a.id===current?'selected':''}>${esc(a.name)} · 已確認印刷用途</option>`).join('');}
  function renderUsageList(){const q=$('usage-query').value.toLocaleLowerCase(),role=$('usage-filter').value;
    const found=assets.filter(a=>(!role||a.usage.role===role)&&((a.name||'')+' '+(a.provenance?.relativePath||'')).toLocaleLowerCase().includes(q));
    $('usage-count').textContent=`${found.length} 筆素材；${assets.filter(a=>a.usage.canUseForModel).length} 筆已確認印刷用途。用途由人員核對，不依副檔名自動判定。`;$('usage-list').replaceChildren();
    for(const a of found.slice(0,usageLimit)){const b=document.createElement('button');b.type='button';b.innerHTML=`${esc(a.name)} <span class="usage-badge">${esc(a.usage.label)}</span><small>${esc(a.provenance?.relativePath||a.provenance?.type)} · ${esc(a.id.slice(0,12))}</small>`;b.onclick=()=>review(a.id);$('usage-list').append(b);}
    $('usage-more').hidden=found.length<=usageLimit;}
  function review(id){const a=assets.find(x=>x.id===id);if(!a)return;reviewAsset=a;$('usage-form').hidden=false;$('usage-name').textContent=a.name;$('usage-source').textContent=a.provenance?.relativePath||a.provenance?.type||'';
    $('usage-page').innerHTML=a.info.pages.map((_,i)=>`<option value="${i}">第 ${i+1} 頁／共 ${a.info.pages.length} 頁</option>`).join('');usagePage();$('usage-role').value=a.usage.role;$('usage-note').value=a.usage.note;$('artwork-check').checked=false;$('usage-status').textContent=`目前用途：${a.usage.label} · 第 ${a.usage.revision} 版`;toggleArtworkCheck();}
  function usagePage(){if(reviewAsset)$('usage-image').src=`/api/print-workspace/assets/${reviewAsset.id}/preview?workspace=${encodeURIComponent(tenant)}&page=${$('usage-page').value}`;}
  $('usage-page').onchange=usagePage;
  function toggleArtworkCheck(){const artwork=$('usage-role').value==='ARTWORK';$('artwork-check-label').hidden=!artwork;$('artwork-check').required=artwork;}
  $('usage-role').onchange=()=>{$('artwork-check').checked=false;toggleArtworkCheck();};
  $('usage-filter').onchange=$('usage-query').oninput=()=>{usageLimit=20;renderUsageList();};$('usage-more').onclick=()=>{usageLimit+=20;renderUsageList();};
  $('usage-form').onsubmit=run(async()=>{if(!reviewAsset)return;$('usage-save').disabled=true;$('usage-panel').inert=true;try{const a=await api('/assets/'+reviewAsset.id+'/usage',{method:'PUT',body:body({role:$('usage-role').value,note:$('usage-note').value,expectedRevision:reviewAsset.usage.revision})});await loadAssets();review(a.id);window.dispatchEvent(new Event('product-material-changed'));
    if(selected?.draft.variants?.some(v=>v.artworkAssetId===a.id))staleForm();notice('素材用途已儲存：'+a.usage.label+'。分類不代表已完成精準印刷校正。');}finally{$('usage-save').disabled=false;$('usage-panel').inert=false;}});
  function addVariant(v={}){const row=document.createElement('div');row.className='row variant';row.innerHTML=`<div class="fields"><label>SKU<input class="variant-sku" required maxlength="120" value="${esc(v.sku)}"></label><label>圖稿<select class="variant-art">${assetOptions(v.artworkAssetId)}</select></label></div><label>圖案／版本備註<input class="variant-note" maxlength="1000" value="${esc(v.note)}"></label>`;removeButton(row);$('variants').append(row);}
  function addFace(f={}){const row=document.createElement('div');row.className='row face';row.innerHTML=`<div class="fields"><label>印刷面名稱<input data-key="name" required maxlength="100" value="${esc(f.name)}" placeholder="例如 第一片門板正面"></label><label>面寬（mm）<input data-key="widthMm" type="number" min="0.01" max="6000" step="any" required value="${esc(f.widthMm)}"></label><label>面高（mm）<input data-key="heightMm" type="number" min="0.01" max="6000" step="any" required value="${esc(f.heightMm)}"></label><label>出血（mm）<input data-key="bleedMm" type="number" min="0" max="20" step="any" required value="${esc(f.bleedMm??0)}"></label></div><label>印刷面尺寸依據<input data-key="evidence" required maxlength="1500" value="${esc(f.evidence)}"></label><label>原點／治具方向紀錄<input data-key="originNote" maxlength="1500" value="${esc(f.originNote)}"></label>`;removeButton(row);$('faces').append(row);}
  function removeButton(row){const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent='移除此筆';b.onclick=()=>{row.remove();staleForm();};row.append(b);}
  function fill(d={}){draftRecipeReference=d.recipeReference||null;draftSourceGroupId=d.sourceGroupId||'';form.reset();for(const [key,value] of Object.entries(d)){const input=form.elements.namedItem(key);if(input)input.value=value??'';}
    $('variants').replaceChildren();(d.variants||[]).forEach(addVariant);$('faces').replaceChildren();(d.printFaces||[]).forEach(addFace);
    dirty=false;task=null;showClassification().catch(err=>notice(err.message,true));$('accept').checked=false;$('cancel').disabled=true;$('status').disabled=!selected;$('revision').textContent=selected?`第 ${selected.revision} 版`:'新模型資料';
    $('render-image').hidden=true;$('downloads').replaceChildren();$('render-state').textContent='';if(dispose){dispose();dispose=null;}$('viewer').replaceChildren();viewId='';readiness();toggleCabinet();window.dispatchEvent(new CustomEvent('product-master-selected',{detail:selected}));}
  function newMaster(g=null){selected=null;const category=!g?categoryNodes.get(categoryFilter):null;pendingNewCategory=category?.draftDefaults?.family?category.id:null;$('file-query').value='';$('source-preview').hidden=true;$('sources-panel').hidden=!g;
    fill({name:g?.name||category?.draftDefaults?.family&&category.label||'',family:g?.family||category?.draftDefaults?.family||'coaster',subtype:g?.subtype||category?.draftDefaults?.subtype||'other',rows:category?.draftDefaults?.rows??null,geometry:'PENDING',sourceGroupId:g?.id||''});notice(g?'已選來源群組；請確認名稱、結構與實際尺寸，再儲存。':'請填模型資料；尺寸未知可以先留白儲存。');}
  function toggleCabinet(){$('cabinet-fields').hidden=!form.elements.geometry.value.endsWith('CABINET');for(const key of ['widthMm','depthMm','heightMm'])form.elements.namedItem(key).readOnly=form.elements.geometry.value==='RECIPE_REFERENCE';}
  function readiness(){const r=selected?.readiness;$('readiness').textContent=r?(r.previewReady?'資料足以生成簡化外形預覽；尚未完成實物／印刷校正。':r.missing):'先儲存商品資料；不確定的尺寸請留白。';
    $('assumptions').innerHTML=(r?.assumptions||[]).map(x=>`<li>${esc(x)}</li>`).join('');$('generate').disabled=dirty||!r?.previewReady||!$('accept').checked||busy;}
  function draft(){const d={};for(const k of ['name','family','subtype','geometry','dimensionEvidence','structureEvidence','notes'])d[k]=form.elements.namedItem(k).value;
    for(const k of numeric){const v=form.elements.namedItem(k).value;d[k]=v===''?null:Number(v);}d.sourceGroupId=draftSourceGroupId;d.recipeReference=draftRecipeReference;
    d.variants=Array.from(document.querySelectorAll('.variant')).map(r=>({sku:r.querySelector('.variant-sku').value,artworkAssetId:r.querySelector('.variant-art').value,note:r.querySelector('.variant-note').value}));
    d.printFaces=Array.from(document.querySelectorAll('.face')).map(r=>{const f={};r.querySelectorAll('[data-key]').forEach(e=>f[e.dataset.key]=e.type==='number'?Number(e.value):e.value);return f;});return d;}
  async function showStatus(){if(!selected)return;const id=selected.id;const s=await api('/'+id+'/preview');if(selected?.id!==id)return;task=['queued','running'].includes(s.state)?s.taskId:null;
    const active=['queued','running'].includes(s.state);$('cancel').disabled=!active;$('render-state').textContent=`${labels[s.state]||s.state}${s.error?' · '+s.error:''}${s.stale?' · 模型已修改，需重新生成':''}`;
    $('generate').disabled=active||dirty||!selected.readiness.previewReady||!$('accept').checked||busy;
    if(s.generated&&!s.stale&&!dirty){const url=fmt=>`${base}/${id}/files/${fmt}?`+new URLSearchParams({workspace:tenant,generation:s.generationId});
      if(viewId!==s.generationId){if(dispose)dispose();dispose=window.mountRecipeViewer($('viewer'),s.spec);viewId=s.generationId;
        $('render-image').src=url('png');$('render-image').hidden=false;$('downloads').innerHTML=['png','blend','glb','geometry'].map(f=>`<a href="${esc(url(f))}" download>${{png:'下載棚拍預覽',blend:'下載 Blender 模型',glb:'下載 GLB 模型',geometry:'下載尺寸紀錄'}[f]}</a>`).join('');await loadMasters();}}
    else{$('downloads').replaceChildren();$('render-image').hidden=true;}}
  window.addEventListener('product-composition-finished',()=>loadMasters().catch(err=>notice(err.message,true)));
  $('search-form').onsubmit=run(()=>loadCatalog());$('more').onclick=run(()=>loadCatalog(true));
  $('file-search').onsubmit=run(()=>loadFiles());$('files-more').onclick=run(()=>loadFiles(true));
  $('scan').onclick=run(async()=>{$('scan').disabled=true;notice('正在唯讀掃描已設定的 NAS 商品資料夾…');try{const s=await api('/catalog/refresh',{method:'POST'});await loadCatalog();notice(`掃描完成：${s.fileCount} 個檔案、${s.groupCount} 個待確認群組。`);}finally{$('scan').disabled=false;}});
  $('load-recipe-reference').onclick=()=>{const r=recipeReferences.find(x=>x.sku===$('recipe-reference').value);if(r&&canLeave()){selected=null;pendingNewCategory=null;fill(r.draft);switchView('models');notice('已載入原有 Recipe 快照；保留原尺寸依據與預覽假設。請儲存後生成，不會修改原始配方。');}};
  $('new').onclick=()=>{if(canLeave()){newMaster();switchView('models');}};
  function switchView(view){const models=view==='models';$('library-view').hidden=!models;$('material-view').hidden=models;$('show-models').setAttribute('aria-pressed',String(models));$('show-materials').setAttribute('aria-pressed',String(!models));}
  $('show-models').onclick=()=>switchView('models');$('show-materials').onclick=()=>switchView('materials');
  $('create-from-source').onclick=()=>{if(group&&canLeave()){newMaster(group);switchView('models');}};
  form.addEventListener('input',staleForm);form.elements.geometry.addEventListener('change',toggleCabinet);
  $('add-variant').onclick=()=>{addVariant();staleForm();};$('add-face').onclick=()=>{addFace();staleForm();};
  form.onsubmit=run(async()=>{if(busy)return;busy=true;form.inert=true;$('save').disabled=true;try{selected=await api(selected?'/'+selected.id:'',{method:selected?'PUT':'POST',body:body({draft:draft(),expectedRevision:selected?.revision||0})});if(pendingNewCategory){try{const c=await api('/'+selected.id+'/classification');await api('/'+selected.id+'/classification',{method:'PUT',body:body({categoryId:pendingNewCategory,expectedRevision:c.revision})});pendingNewCategory=null;}catch(err){fill(selected.draft);await loadMasters();throw new Error('模型已儲存；分類尚未完成，請使用「儲存分類」重試：'+err.message);}}fill(selected.draft);await loadMasters();await showStatus();notice('模型資料已儲存。'+(selected.readiness.missing||'可確認簡化說明後生成 3D。'));}finally{busy=false;form.inert=false;$('save').disabled=false;readiness();}});
  $('accept').onchange=readiness;
  $('generate').onclick=run(async()=>{if(!selected||dirty)return;busy=true;readiness();try{await api('/'+selected.id+'/preview',{method:'POST',body:body({expectedRevision:selected.revision,inputHash:selected.inputHash,assumptionsAccepted:$('accept').checked})});notice('已送出真實 Blender 生成工作，畫面會更新進度。');}finally{busy=false;await showStatus();}});
  $('status').onclick=run(showStatus);$('cancel').onclick=run(async()=>{await api('/'+selected.id+'/cancel',{method:'POST',body:body({taskId:task})});notice('已送出取消要求。');await showStatus();});
  window.addEventListener('beforeunload',e=>{if(dirty||classificationDirty){e.preventDefault();e.returnValue='';}});
  setInterval(()=>{if(task)showStatus().catch(err=>notice(err.message,true));},5000);
  run(async()=>{const data=await api('/catalog');$('family').insertAdjacentHTML('beforeend',options(data.families));$('subtype').insertAdjacentHTML('beforeend',options(data.subtypes));$('edit-family').innerHTML=options({...data.families,mat:'地墊／洗漱墊'});$('edit-subtype').innerHTML=options(data.subtypes,'other');
    recipeReferences=(await api('/recipe-references')).items;$('recipe-reference').innerHTML=recipeReferences.map(r=>`<option value="${esc(r.sku)}">${esc(r.draft.name)}</option>`).join('');
    await loadAssets();await loadCatalog();await loadMasters();newMaster();if(window.location.hash==='#usage-panel')switchView('materials');notice('從左側分類找模型。分類可展開到櫃型與層數；歷史圖片請切換「素材資料庫」。');})();
})();
