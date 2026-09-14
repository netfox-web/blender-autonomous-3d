'use strict';
(() => {
  const $=id=>document.getElementById(id), tenant='sonaqueen-home';
  let current=null, generation=null, serial=0, statusSerial=0, timer=null, busy=false, lastRendered=null, disposeViewer=null;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const base=sku=>'/api/recipe-library/golden/'+encodeURIComponent(sku);
  async function api(url,options={}) {
    const r=await fetch(url,{...options,headers:{'X-Tenant-Id':tenant,'Content-Type':'application/json'}});
    const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'操作失敗，請重新確認設定');return data;
  }
  function controls(){ $('generate').disabled=busy||!current?.ready||!current?.blenderAvailable||!$('accept').checked; }
  function download(sku,gid,fmt,inline=false){return base(sku)+'/download/'+fmt+'?workspace='+encodeURIComponent(tenant)+'&generation='+encodeURIComponent(gid)+(inline?'&inline=true':'');}
  function showStatus(s,sku){
    generation=s;busy=['queued','running'].includes(s.state);controls();$('cancel').hidden=!busy;
    const labels={idle:'尚未生成',queued:'等待生成',running:'Blender 生成中',succeeded:'REAL Blender 預覽完成 · 圖稿 FIXTURE',cancelled:'已取消生成',failed:'生成失敗'};
    $('progress').textContent=s.error||`${labels[s.state]||s.state}${busy?' · '+s.progress+'%':''}`;
    if(s.state==='cancelled' && $('notice').textContent.startsWith('已提出取消'))$('notice').textContent='生成已取消。';
    $('stale').hidden=!s.stale||!s.generated;
    if(s.generated && lastRendered!==s.generationId){
      lastRendered=s.generationId;
      const views=[['png','HERO_45 · 立體視角'],['front','FRONT_CLOSED · 正面'],['detail','DOOR_DETAIL · 門片細節']];
      $('results').innerHTML='<div class="golden-views">'+views.map(([fmt,label])=>`<figure><img src="${download(sku,s.generationId,fmt,true)}" alt="${label}"><figcaption>${label}</figcaption></figure>`).join('')+'</div><div class="golden-downloads">'+[['png','PNG 圖片'],['glb','GLB 模型'],['blend','Blender 原檔'],['manifest','驗證紀錄 JSON']].map(([fmt,label])=>`<a href="${download(sku,s.generationId,fmt)}">下載 ${label} ↓</a>`).join('')+'</div>';
      $('lineage').innerHTML=`<p>Blender ${esc(s.renderInfo.blenderVersion)} · ${esc(s.renderInfo.device)} · 圖稿 FIXTURE</p><p class="hash">EngineeringHash：${esc(s.manifest.engineeringHash)}</p><p class="hash">ArtworkHash：${esc(s.manifest.package.artworkHash)}</p><p>三門均已核對實際 UV、原圖 SHA-256 與獨立裁圖。印刷出血與五金避讓仍待驗證。</p>`;
      $('results').insertAdjacentHTML('beforeend','<p>門片裁圖（校驗用，尚非正式印刷稿）： '+[1,2,3].map(i=>`<a href="${download(sku,s.generationId,'trim'+i)}">門片 ${i} ↓</a>`).join(' · ')+'</p>');
    }else if(!s.generated){
      lastRendered=null;$('results').textContent=busy?'生成中，完成後顯示圖片與下載。':'尚無通過驗證的成果。';
      $('lineage').textContent='尚無通過驗證的成果。';
    }
  }
  async function poll(token,sku,version){
    const request=++statusSerial;
    try{const s=await api(base(sku)+'/status?version='+encodeURIComponent(version));if(token!==serial||request!==statusSerial)return;showStatus(s,sku);}
    catch(e){if(token===serial&&request===statusSerial)$('notice').textContent=e.message;}
    if(token===serial&&request===statusSerial){clearTimeout(timer);timer=setTimeout(()=>poll(token,sku,version),3000);}
  }
  async function select(){
    const token=++serial,sku=$('sku').value,version=$('version').value;clearTimeout(timer);
    current=null;generation=null;busy=false;lastRendered=null;$('cancel').hidden=true;$('accept').checked=false;controls();
    $('notice').textContent='讀取配方…';$('results').innerHTML='';$('lineage').textContent='尚無本次驗證成果';$('stale').hidden=true;
    try{
      const p=await api(base(sku)+'/plan?version='+encodeURIComponent(version));if(token!==serial)return;current=p;
      $('truth').innerHTML=[['CONFIG','外尺寸 424 × 295 × 900 mm；來源 Issue #4'],['ESTIMATED','側／橫／門板 15 mm、背板 3 mm'],['CONFIG','門隙 2 mm、安全區 5 mm、出血 3 mm'],[p.package.truth,'Artwork：'+(p.ready?'校驗圖，非歷史原稿':'歷史原稿尚待提供')],['BLOCKED','五金、孔位、開合與製造尚未驗證']].map(([tag,t])=>`<div class="truth-row"><strong>${esc(tag)}</strong>${esc(t)}</div>`).join('');
      if(disposeViewer)disposeViewer();disposeViewer=window.mountRecipeViewer($('viewer'),p.golden.spec);
      $('boards').innerHTML='<table><thead><tr><th>板件</th><th>長 × 寬 × 厚（mm）</th></tr></thead><tbody>'+p.golden.spec.components.map(c=>`<tr><td>${esc(c.partName)}</td><td>${c.sizeMm.map(esc).join(' × ')}</td></tr>`).join('')+'</tbody></table>';
      $('notice').textContent=p.ready?(p.blenderAvailable?'':'找不到真實 Blender，請檢查本機安裝'):p.package.reason;controls();await poll(token,sku,version);
    }catch(e){if(token===serial)$('notice').textContent=e.message;}
  }
  $('sku').addEventListener('change',select);$('version').addEventListener('change',select);$('accept').addEventListener('change',controls);
  $('generate').addEventListener('click',async()=>{
    if(!current||busy)return;const token=serial,sku=$('sku').value,version=$('version').value,hash=current.planHash;
    ++statusSerial;clearTimeout(timer);busy=true;controls();$('notice').textContent='';
    try{await api(base(sku)+'/generate',{method:'POST',body:JSON.stringify({version,planHash:hash,assumptionsAccepted:$('accept').checked})});if(token===serial){clearTimeout(timer);await poll(token,sku,version);}}
    catch(e){if(token===serial){busy=false;controls();$('notice').textContent=e.message;}}
  });
  $('cancel').addEventListener('click',async()=>{
    if(!generation?.taskId)return;const token=serial,sku=$('sku').value;
    try{await api(base(sku)+'/cancel',{method:'POST',body:JSON.stringify({taskId:generation.taskId})});if(token===serial)$('notice').textContent='已提出取消，等待 Blender 停止。';}catch(e){if(token===serial)$('notice').textContent=e.message;}
  });
  api('/api/recipe-library/golden').then(c=>{
    $('sku').innerHTML=c.skus.map(s=>`<option>${esc(s)}</option>`).join('');
    $('version').innerHTML=c.versions.map(v=>`<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('');select();
  }).catch(e=>$('notice').textContent=e.message);
})();
