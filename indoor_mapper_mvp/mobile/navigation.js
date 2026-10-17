'use strict';
(()=>{
 let session=null,index=0,updating=false,poseReady=false,diagnosticSeq=0;
 const el=id=>document.getElementById(id);
 function message(text){el('navAvailability').textContent=text;}

 const connection=document.createElement('section');connection.id='navConnection';connection.className='nav-connection';connection.hidden=true;
 el('navForm').after(connection);
 function coverage(data,parent){
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 400 220');svg.setAttribute('role','img');svg.setAttribute('aria-label','独立导航轨迹覆盖图，红点为本次照片位置');
  const up=data.world_up,dot=(a,b)=>a.reduce((v,n,i)=>v+n*b[i],0),cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],seed=Math.abs(up[0])<.9?[1,0,0]:[0,1,0];
  let right=seed.map((n,i)=>n-up[i]*dot(seed,up));const len=Math.hypot(...right);right=right.map(n=>n/len);const down=cross(right,up),xy=p=>[dot(p,right),dot(p,down)];
  const all=[data.xyz,...data.lines.flat()].map(xy);const min=[Math.min(...all.map(p=>p[0])),Math.min(...all.map(p=>p[1]))],max=[Math.max(...all.map(p=>p[0])),Math.max(...all.map(p=>p[1]))];
  const scale=Math.min(350/Math.max(max[0]-min[0],.01),170/Math.max(max[1]-min[1],.01));const point=p=>{const q=xy(p);return [25+(q[0]-min[0])*scale,25+(q[1]-min[1])*scale];};
  function shape(tag,attrs,text){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text)e.textContent=text;svg.append(e);}
  for(const line of data.lines)shape('polyline',{points:line.map(p=>point(p).join(',')).join(' '),fill:'none',stroke:'#809486','stroke-width':2});
  const candidates=new Set(data.suggestions.map(n=>n.node_id));for(const n of data.nodes){const [x,y]=point(n.xyz);shape('circle',{cx:x,cy:y,r:candidates.has(n.node_id)?5:3,fill:candidates.has(n.node_id)?'#355fdb':'#7c8980'});if(candidates.has(n.node_id))shape('text',{x:x+7,y:y-5,'font-size':11,fill:'#355fdb'},n.node_id);}
  const [x,y]=point(data.xyz);shape('circle',{cx:x,cy:y,r:6,fill:'#d64d45',stroke:'#fff','stroke-width':2});shape('text',{x:x+9,y:y+15,'font-size':12,fill:'#ad3934'},'照片位置');parent.append(svg);
 }
 async function diagnose(){
  const expected=jobId,seq=++diagnosticSeq;if(!expected||!poseReady){connection.hidden=true;return;}
  try{const data=await api('/api/navigation/diagnose?job_id='+encodeURIComponent(expected));if(seq!==diagnosticSeq||expected!==jobId)return;
   connection.replaceChildren();connection.hidden=!!session&&session.status!=='paused';
   const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=data.status==='ready'?'当前位置已接入导航 · 查看覆盖范围':'定位已成功，需要确认导航接入点';details.open=data.status!=='ready';details.append(summary);coverage(data,details);
   const note=document.createElement('p');note.textContent='此图来自独立的三维导航轨迹；上方底图的旧通路标注不代表这里已覆盖。';details.append(note);
   const numbers=document.createElement('details'),numbersTitle=document.createElement('summary');numbersTitle.textContent='查看距离检查';numbers.append(numbersTitle);
   const value=v=>data.meters_per_unit?(v*data.meters_per_unit).toFixed(2)+'米':v.toFixed(3)+'模型单位';
   const stats=document.createElement('p');stats.textContent=data.nearest?'水平偏离 '+value(data.nearest.horizontal)+'，上下差 '+value(data.nearest.vertical)+'。允许水平范围 '+value(data.limits.horizontal)+'，高度容差 '+value(data.limits.height)+'。':'';numbers.append(stats);details.append(numbers);
   if(data.status!=='ready'){
    const intro=document.createElement('p');intro.textContent='如果你认得下方站位，并确认可以直接走过去，可手动确认本次接入。程序会保留真实定位坐标，不会把你改到参考点上。';details.append(intro);
    let selected=null;const candidates=document.createElement('div');candidates.className='connection-candidates';
    for(const n of data.suggestions){const label=document.createElement('label'),radio=document.createElement('input');radio.type='radio';radio.name='confirmedConnection';radio.value=n.node_id;label.append(radio);if(n.image?.startsWith('images/')){const img=document.createElement('img');img.src=asset('/api/reference?image='+encodeURIComponent(n.image.slice(7)));img.alt=n.name;label.append(img);}const name=document.createElement('span');name.textContent=n.node_id+' '+n.name;label.append(name);radio.onchange=()=>{selected=n.node_id;button.disabled=!check.checked;};candidates.append(label);}details.append(candidates);
    const confirmed=document.createElement('label');confirmed.className='connection-confirm';const check=document.createElement('input');check.type='checkbox';confirmed.append(check,document.createTextNode('我确认当前位置可直接步行到所选照片的拍摄站位，中间没有墙体、门禁或楼层阻隔。'));details.append(confirmed);
    const button=document.createElement('button');button.className='primary full';button.type='button';button.textContent='按我确认的通路开始导航';button.disabled=true;check.onchange=()=>button.disabled=!check.checked||!selected;button.onclick=()=>{if(check.checked&&selected&&jobId===expected)startNavigation(selected);};details.append(button);
    if(!data.suggestions.length){intro.textContent='附近没有可确认的接入点。请在电脑补充当前位置附近的真实站位与通路，不必反复拍摄同一个位置。';confirmed.hidden=true;button.hidden=true;}
   }
   connection.append(details);
  }catch(e){if(seq!==diagnosticSeq||expected!==jobId)return;connection.hidden=false;connection.textContent=e.message;}
 }

 async function catalog(){
  try{const data=await api('/api/navigation/catalog');el('navStart').disabled=!data.available;
   if(!data.available){message(data.reason);return;}
   message((data.verified?'路线已由维护者核实。':'当前为真实采集轨迹的候选路线，请先在电脑核实节点与通路。')+(data.meters_per_unit?'':' 距离尚未标米。'));
   for(const poi of data.pois){const option=document.createElement('option');option.value=poi.name;el('navDestinations').append(option);const button=document.createElement('button');button.type='button';button.textContent=poi.name;button.onclick=()=>{el('navDestination').value=poi.name;};el('navChoices').append(button);}
  }catch(e){message(e.message);el('navStart').disabled=true;}
 }
 function render(){
  if(!session)return;connection.hidden=session.status!=='paused';document.body.classList.add('navigating');el('navPanel').hidden=false;el('navTarget').textContent=session.destination.name;
  const paused=session.status==='paused';el('navNotice').textContent=(session.preview_only?'路线预览 · ':'')+session.observation_note;
  el('navInstruction').textContent=paused?'导航已暂停，请重新定位':session.steps[0].instruction;
  el('navDistance').textContent=paused?'暂不更新剩余距离':session.distance.distance_m===null?'剩余距离尚未标米':`剩余约 ${session.distance.distance_m.toFixed(1)} 米`;
  el('navProgress').textContent=session.status==='arrived'?(session.historical?'历史到达记录':'已在目的地附近'): `已通过 ${session.completed_waypoints} 个导航点 · 余 ${session.steps.length} 步`;
  el('navReason').textContent=session.reason;
  index=Math.max(0,Math.min(index,session.steps.length-1));const step=session.steps[index];
  el('navFigure').hidden=paused||!step.reference;
  if(step.reference&&!paused){el('navImage').src=asset(step.reference.url);const labels={straight:'直行',left:'左转',right:'右转',uturn:'掉头',up:'上楼',down:'下楼',arrive:'到达'};el('navCaption').textContent=(index?'预览后续步骤，不代表已走到这里。 ':step.reference.source==='current_photo'?'本次定位照片上的方向示意。 ':'当前步骤参考图。 ')+step.reference.caption+'。'+(step.reference.photo_action!==step.action?'照片视角不同，图中显示“'+labels[step.reference.photo_action]+'”；你当前的操作以上方文字为准。':'');}
  el('navPreviewLabel').textContent=`参考 ${index+1} / ${session.steps.length}`;
  el('navPhotoInstruction').textContent=index?'本张参考图所对应的步骤：'+step.instruction:'';
  el('navPrev').disabled=index===0||paused;el('navNext').disabled=index>=session.steps.length-1||paused;
 }
 async function startNavigation(confirmedNode=null){if(updating)return;if(!jobId||!poseReady){message('请先拍照完成一次成功定位，再开始导航；历史照片只能用于路线回放。');return;}
  updating=true;el('navStart').disabled=true;
  try{session=await api('/api/navigation/start',{method:'POST',body:JSON.stringify({job_id:jobId,destination:el('navDestination').value,historical:!!result?.historical,confirmed_node:confirmedNode,confirm_direct_access:!!confirmedNode})});index=0;render();message('已找到目的地。按当前指令行走，移动后拍照更新。');}
  catch(e){message(e.message);await diagnose();}finally{updating=false;el('navStart').disabled=false;}
 };
 el('navForm').onsubmit=event=>{event.preventDefault();startNavigation();};
 window.addEventListener('pose-result',async event=>{
  poseReady=event.detail.result.status==='success';if(!session){await diagnose();return;}
  const id=session.id;
  try{const updated=await api('/api/navigation/update',{method:'POST',body:JSON.stringify({id,job_id:event.detail.jobId,historical:!!event.detail.result.historical})});if(session?.id!==id)return;session=updated;index=0;render();if(session.status==='paused')await diagnose();}
  catch(e){if(session?.id!==id)return;el('navInstruction').textContent='导航暂停：'+e.message;el('navFigure').hidden=true;}
 });
 window.addEventListener('pose-pending',()=>{poseReady=false;diagnosticSeq++;connection.hidden=true;if(session){el('navInstruction').textContent='正在重新定位，请等待新的行走指令';el('navFigure').hidden=true;}});
 el('navPrev').onclick=()=>{index--;render();};el('navNext').onclick=()=>{index++;render();};
 el('navMapToggle').onclick=()=>{document.body.classList.toggle('show-nav-map');el('navMapToggle').textContent=document.body.classList.contains('show-nav-map')?'收起位置地图':'展开位置地图';};
 el('navRelocate').onclick=()=>{if(!busy)el('cameraInput').click();};el('navStop').onclick=()=>{session=null;document.body.classList.remove('navigating','show-nav-map');el('navPanel').hidden=true;message('导航已结束，可以选择新的目的地。');};
 if(['127.0.0.1','localhost'].includes(location.hostname)){el('navSettings').hidden=false;el('navSettings').href=asset('/navigation-admin.html');}
 // The localization script may have finished loading a saved job before this script ran.
 if(typeof result!=='undefined'&&result){poseReady=result.status==='success';diagnose();}
 catalog();
})();
