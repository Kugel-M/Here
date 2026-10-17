"use strict";
(()=>{
 const $=id=>document.getElementById(id),token=new URLSearchParams(location.search).get('token')||'';
 let graph=null,refs=[];
 async function request(body){const r=await fetch('/api/navigation/config?token='+encodeURIComponent(token),{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'保存失败');return d;}
 function input(label,value,parent){const box=document.createElement('label');box.textContent=label;const el=document.createElement('input');el.value=value||'';box.append(el);parent.append(box);return el;}
 function select(options,value){const s=document.createElement('select');for(const [v,t] of options){const o=document.createElement('option');o.value=v;o.textContent=t;s.append(o);}s.value=value;return s;}
 function checkbox(label,value,parent){const l=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.checked=value;l.append(c,document.createTextNode(label));parent.append(l);return c;}
 function options(){return graph.nodes.map(n=>[n.node_id,n.node_id+' '+n.name]);}
 function render(){
  $('nodes').replaceChildren();$('edges').replaceChildren();
  for(const node of graph.nodes){
   const row=document.createElement('article');row.className='admin-node';const img=document.createElement('img');img.alt='导航节点真实参考照片';const photo=()=>'/api/reference?token='+encodeURIComponent(token)+'&image='+encodeURIComponent(node.references[0].image.replace('images/',''));img.src=photo();row.append(img);
   const fields=document.createElement('div');fields.className='admin-fields';const id=document.createElement('code');const coords=()=>node.node_id+' XYZ: '+node.xyz.map(n=>n.toFixed(3)).join(', ');id.textContent=coords();fields.append(id);
   input('节点名称',node.name,fields).oninput=e=>node.name=e.target.value;input('所属区域',node.region,fields).oninput=e=>node.region=e.target.value;
   input('楼层',node.floor,fields).oninput=e=>node.floor=e.target.value;
   const type=select([['corridor','走廊'],['junction','路口'],['door','门口'],['poi','目的地'],['stairs','楼梯'],['elevator','电梯'],['escalator','扶梯']],node.type);type.onchange=()=>node.type=type.value;fields.append(type);
   const poi=graph.pois.find(p=>p.node_id===node.node_id);node._destination=node._destination??!!poi;node._aliases=node._aliases??(poi?.aliases||[]);
   input('别名（逗号分隔）',node._aliases.join('，'),fields).oninput=e=>node._aliases=e.target.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean);
   checkbox('作为目的地',node._destination,fields).onchange=e=>node._destination=e.target.checked;
   const label=document.createElement('label');label.className='wide';label.textContent='参考照片与站位';const ref=select(refs.map(r=>[r.image,r.name+' '+r.label]),node.references[0].image);ref.onchange=()=>{const r=refs.find(r=>r.image===ref.value);node.references=[r];node.xyz=r.xyz;img.src=photo();id.textContent=coords();};label.append(ref);fields.append(label);
   const del=document.createElement('button');del.type='button';del.textContent='移除此点';del.onclick=()=>{graph.nodes=graph.nodes.filter(n=>n!==node);graph.edges=graph.edges.filter(e=>e.from!==node.node_id&&e.to!==node.node_id);render();};fields.append(del);row.append(fields);$('nodes').append(row);
  }
  for(const edge of graph.edges){const row=document.createElement('div');row.className='admin-edge';const a=select(options(),edge.from),b=select(options(),edge.to),kind=select([['walk','普通通路'],['stairs','楼梯'],['elevator','电梯'],['escalator','扶梯']],edge.kind||'walk');a.onchange=()=>edge.from=a.value;b.onchange=()=>edge.to=b.value;kind.onchange=()=>edge.kind=kind.value;row.append(a,document.createTextNode('至'),b,kind);checkbox('双向',edge.bidirectional!==false,row).onchange=e=>edge.bidirectional=e.target.checked;checkbox('可通行',edge.enabled!==false,row).onchange=e=>edge.enabled=e.target.checked;const del=document.createElement('button');del.textContent='删除';del.onclick=()=>{graph.edges=graph.edges.filter(e=>e!==edge);render();};row.append(del);$('edges').append(row);}
  for(const key of ['scaleA','scaleB']){const replacement=select(options(),graph.nodes[key==='scaleA'?0:Math.max(0,graph.nodes.length-1)]?.node_id);replacement.id=key;$(key).replaceWith(replacement);}
  $('snapRadius').value=graph.snap_radius_units;$('heightTolerance').value=graph.height_tolerance_units||graph.snap_radius_units;
  $('currentScale').textContent=graph.meters_per_unit?'现有比例：1 模型单位 = '+graph.meters_per_unit.toFixed(4)+' 米':'尚未标米。';
 }
 $('add').onclick=()=>{if(!graph||!refs.length)return;const r=refs[0];let i=graph.nodes.length+1;while(graph.nodes.some(n=>n.node_id==='N'+String(i).padStart(2,'0')))i++;graph.nodes.push({node_id:'N'+String(i).padStart(2,'0'),name:'新导航点',region:'',xyz:r.xyz,floor:'当前楼层',type:'corridor',references:[r]});render();};
 $('addEdge').onclick=()=>{if(graph.nodes.length<2)return;graph.edges.push({from:graph.nodes[0].node_id,to:graph.nodes[1].node_id,kind:'walk',enabled:true,bidirectional:true});render();};
 $('save').onclick=async()=>{if(!graph)return;$('save').disabled=true;try{const body={nodes:graph.nodes.map(n=>({node_id:n.node_id,name:n.name,region:n.region,floor:n.floor,type:n.type,image:n.references[0].image,extra_images:n.references.slice(1).map(r=>r.image),destination:n._destination,aliases:n._aliases})),edges:graph.edges,field_verified:$('verified').checked,snap_radius_units:Number($('snapRadius').value),height_tolerance_units:Number($('heightTolerance').value)};if($('scaleMeters').value)body.scale_measurement={a:$('scaleA').value,b:$('scaleB').value,meters:Number($('scaleMeters').value)};const d=await request(body);graph=d.graph;$('scaleMeters').value='';render();$('saveMessage').textContent='已保存独立导航配置，并备份上一版。手机刷新后可用；进行中的导航需要重新开始。';}catch(e){$('saveMessage').textContent=e.message;}finally{$('save').disabled=false;}};
 $('extend').onclick=async()=>{if(!graph)return;$('extend').disabled=true;try{const r=await fetch('/api/navigation/extend?token='+encodeURIComponent(token),{method:'POST',body:'{}'});const d=await r.json();if(!r.ok)throw Error(d.error);graph=d.graph;$('verified').checked=!!graph.field_verified;render();$('saveMessage').textContent='已保留原节点与名称，并补充缺失的视频后续轨迹。新通路为候选，需现场核实。';}catch(e){$('saveMessage').textContent=e.message;}finally{$('extend').disabled=false;}};
 $('back').href='/?token='+encodeURIComponent(token);
 request().then(d=>{graph=d.graph;refs=d.references;$('verified').checked=!!graph.field_verified;render();$('saveMessage').textContent='请核实照片对应的站位、名称和通行情况。';}).catch(e=>$('saveMessage').textContent=e.message);
})();
