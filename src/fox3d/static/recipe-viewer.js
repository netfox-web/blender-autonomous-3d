'use strict';
// The same explicit box geometry is passed to Blender and this structural view.
window.mountRecipeViewer = function(host, spec) {
  host.innerHTML = '<canvas tabindex="0" role="img" aria-label="可旋轉的商品結構預覽，方向鍵旋轉，加減鍵縮放"></canvas><div class="viewer-tools"><button type="button" class="secondary">重設視角</button><label><input type="checkbox"> 隱藏門片查看內部</label><span>拖曳旋轉 · 滾輪縮放 · 方向鍵也可操作</span></div>';
  const canvas = host.querySelector('canvas'), ctx = canvas.getContext('2d');
  let yaw = -.45, elevation = .22, zoom = 1, start = null;
  const hide = host.querySelector('input');
  const faces = [[0,1,3,2],[4,6,7,5],[0,4,5,1],[2,3,7,6],[0,2,6,4],[1,5,7,3]];
  const colors = ['#b4a18a','#eee4cf','#caba9f','#e8ddc4','#dbcbb0','#f6edd9'];
  function draw() {
    if (!canvas.isConnected) return;
    const width = Math.max(260, host.clientWidth), height = 430, ratio = window.devicePixelRatio || 1;
    canvas.width = width*ratio; canvas.height = height*ratio;
    canvas.style.width = width+'px'; canvas.style.height = height+'px';
    ctx.scale(ratio,ratio); ctx.fillStyle='#f5f3ed'; ctx.fillRect(0,0,width,height);
    const extent = Math.hypot(spec.width,spec.depth,spec.height)/1000;
    const scale = Math.min(width*.8,height*.82)/extent*zoom;
    const transformed = ([x,y,z]) => {
      z -= spec.height/2000;
      const u=x*Math.cos(yaw)-y*Math.sin(yaw), v=x*Math.sin(yaw)+y*Math.cos(yaw);
      const depth=v*Math.cos(elevation)-z*Math.sin(elevation);
      const perspective=4*extent/(4*extent+depth);
      return [width/2+u*scale*perspective,height/2-(z*Math.cos(elevation)+v*Math.sin(elevation))*scale*perspective,depth];
    };
    const polygons=[];
    for (const part of spec.components) {
      if(hide.checked && part.role==='door') continue;
      const vertices=Array.from({length:8},(_,i)=>transformed(part.location.map((v,k)=>v+((i>>k)&1?1:-1)*part.size[k]/2)));
      faces.forEach((face,i)=>polygons.push({points:face.map(v=>vertices[v]),color:part.role==='door'?'#d4b58b':colors[i],depth:face.reduce((s,v)=>s+vertices[v][2],0)/4}));
    }
    polygons.sort((a,b)=>b.depth-a.depth).forEach(p=>{
      ctx.beginPath(); p.points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();
      ctx.fillStyle=p.color;ctx.fill();ctx.strokeStyle='#746b5c';ctx.lineWidth=.6;ctx.stroke();
    });
    ctx.fillStyle='#61695e';ctx.font='13px sans-serif';ctx.fillText(`${spec.width} × ${spec.depth} × ${spec.height} mm`,16,height-17);
  }
  canvas.onpointerdown=e=>{start=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);};
  canvas.onpointermove=e=>{if(!start)return;yaw+=(e.clientX-start[0])*.009;elevation=Math.max(-1.2,Math.min(1.2,elevation+(e.clientY-start[1])*.007));start=[e.clientX,e.clientY];draw();};
  canvas.onpointerup=canvas.onpointercancel=()=>{start=null;};
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.4,Math.min(3,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
  canvas.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','='].includes(e.key))return;e.preventDefault();if(e.key==='ArrowLeft')yaw-=.1;if(e.key==='ArrowRight')yaw+=.1;if(e.key==='ArrowUp')elevation+=.1;if(e.key==='ArrowDown')elevation-=.1;if(['+','='].includes(e.key))zoom=Math.min(3,zoom*1.1);if(e.key==='-')zoom=Math.max(.4,zoom/1.1);elevation=Math.max(-1.2,Math.min(1.2,elevation));draw();};
  host.querySelector('button').onclick=()=>{yaw=-.45;elevation=.22;zoom=1;draw();};hide.onchange=draw;
  const observer=new ResizeObserver(draw);observer.observe(host);draw();
  return ()=>observer.disconnect();
};
