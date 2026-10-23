'use strict';
(async function () {
  const byId = id => document.getElementById(id);
  try {
    const response = await fetch('cases/corridor/case.json');
    if (!response.ok) throw new Error('Saved case unavailable');
    const data = await response.json();
    const stages = [
      {label:'Input photo',title:'Start with the surroundings.',description:'The first saved input looks into the kitchen passage. This mapping photo was submitted to the working localization engine.',image:'input.jpg',kind:'ORIGINAL INPUT / OBSERVATION 1',caption:'Original query image, shown uncropped. This is a replay of a registered mapping photo.',status:'Recorded input',result:'One photo in a mapped space',detail:'No live upload or new processing takes place on this page.',pose:0,route:false,capture:'app-localized.png'},
      {label:'Computed pose',title:'A photo becomes a camera pose.',description:'COLMAP registration matched the photo against the existing scene model and returned its position and camera orientation.',image:'input.jpg',kind:'LOCALIZATION INPUT / OBSERVATION 1',caption:'The computed pose belongs to this photo, at the moment it was captured.',status:'Localization succeeded',result:'Position and heading recovered',detail:'1,529 valid 2D–3D correspondences in this recorded run.',pose:0,route:false,capture:'app-localized.png'},
      {label:'Saved route',title:'Connect the pose to a destination.',description:'The recorded destination is T002, the kitchen–corridor waypoint. A* produced a route along the candidate navigation graph.',image:'input.jpg',kind:'ROUTE START / OBSERVATION 1',caption:'The start photo faces along the selected passage. The diagram uses the independent 3D navigation graph.',status:'Route generated',result:'T001 to T002',detail:'Destination: kitchen–corridor waypoint · map scale uncalibrated.',pose:0,route:true,capture:'app-guidance.png'},
      {label:'Photo guidance',title:'See the direction in the scene.',description:'The saved instruction is “Go straight”. The arrow was rendered on the same query photo, using its own camera heading.',image:'straight.jpg',kind:'SAVED APPLICATION OUTPUT / REVISION 1',caption:'Original engine-generated overlay. The forward arrow points along the passage, matching the saved straight-ahead instruction.',status:'Go straight',result:data.navigation.instruction_en,detail:'Relative turn angle: '+data.navigation.relative_angle_degrees.toFixed(2)+'° · static photo guidance.',pose:0,route:true,capture:'app-guidance.png'},
      {label:'Photo update',title:'Another photo checks the position.',description:'A second saved mapping photo was processed by the localization engine. Its new pose was supplied to the same navigation session.',image:'update.jpg',kind:'ORIGINAL INPUT / OBSERVATION 2',caption:'Second query image, shown uncropped. Its camera faces back along the corridor; the heading changes accordingly.',status:'Second localization succeeded',result:'A new observation near T002',detail:'942 valid 2D–3D correspondences · saved navigation revision 2.',pose:1,route:true,capture:'app-arrival.png'},
      {label:'Arrival match',title:'The updated route reaches its endpoint.',description:'The saved navigation result changed from “navigating” to “arrived” after the second successful localization near T002.',image:'arrival.jpg',kind:'SAVED APPLICATION OUTPUT / REVISION 2',caption:'Original destination marker on the second query photo. This indicates the saved near-waypoint match, not a newly verified physical arrival.',status:'Arrival matched in the recorded run',result:data.navigation.arrival_en,detail:'Same session · revision 1: navigating · revision 2: arrived.',pose:1,route:true,capture:'app-arrival.png'}
    ];
    let selected = 0;
    const nav = byId('stage-nav');
    stages.forEach((stage,i) => {
      const button = document.createElement('button');
      button.type='button';button.id='stage-'+i;
      const number=document.createElement('span');number.textContent=String(i+1).padStart(2,'0');
      button.append(number,document.createTextNode(stage.label));
      button.addEventListener('click',()=>show(i));nav.append(button);
    });
    const ns='http://www.w3.org/2000/svg';
    function svgEl(tag,attrs={},text){const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));if(text!==undefined)el.textContent=text;return el;}
    function drawMap(stage){
      const svg=byId('route-map');svg.querySelectorAll('g').forEach(e=>e.remove());
      const g=svgEl('g');svg.append(g);
      const pts=data.projection.nodes.map(n=>n.point), xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);
      const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
      const scale=Math.min(390/Math.max(.001,maxX-minX),230/Math.max(.001,maxY-minY));
      const map=p=>[300+(p[0]-(minX+maxX)/2)*scale,160-(p[1]-(minY+maxY)/2)*scale];
      const line=points=>points.map(p=>map(p).join(',')).join(' ');
      data.projection.edges.forEach(e=>g.append(svgEl('polyline',{points:line(e.points),fill:'none',stroke:'#d0d5ca','stroke-width':3,'stroke-linejoin':'round'})));
      if(stage.route)g.append(svgEl('polyline',{points:line(data.projection.route),fill:'none',stroke:'#486c5d','stroke-width':5,'stroke-linejoin':'round','stroke-linecap':'round'}));
      data.projection.nodes.forEach(n=>{const [x,y]=map(n.point);g.append(svgEl('circle',{cx:x,cy:y,r:n.id==='T002'?6:3.5,fill:n.id==='T002'?'#486c5d':'#aab5a8'}));if(n.id==='T001'||n.id==='T002')g.append(svgEl('text',{x:x+12,y:y+(n.id==='T001'?18:-12),class:'map-label'},n.id==='T001'?'T001 · Start':'T002 · Destination'));});
      if(selected>0){const pose=data.projection.poses[stage.pose],[x,y]=map(pose.point);let [dx,dy]=pose.heading;const norm=Math.hypot(dx,dy)||1;dx=dx/norm*28;dy=-dy/norm*28;
        g.append(svgEl('line',{x1:x,y1:y,x2:x+dx,y2:y+dy,stroke:'#b7623d','stroke-width':4,'stroke-linecap':'round'}));
        const a=Math.atan2(dy,dx);g.append(svgEl('path',{d:`M ${x+dx-9*Math.cos(a-.45)} ${y+dy-9*Math.sin(a-.45)} L ${x+dx} ${y+dy} L ${x+dx-9*Math.cos(a+.45)} ${y+dy-9*Math.sin(a+.45)}`,fill:'none',stroke:'#b7623d','stroke-width':3}));
        g.append(svgEl('circle',{cx:x,cy:y,r:7,fill:'#b7623d',stroke:'#fff','stroke-width':2}));}
      g.append(svgEl('text',{x:18,y:302,class:'map-small'},'Model horizontal plane · no north or metre scale'));
    }
    function show(index,focus=false){
      selected=Math.max(0,Math.min(stages.length-1,index));const s=stages[selected],obs=data.observations[s.pose],q=obs.pose.quality;
      nav.querySelectorAll('button').forEach((b,i)=>{if(i===selected)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
      ['stage-title','stage-description','photo-kind','photo-caption','result-status','result-title','result-detail'].forEach((id,i)=>byId(id).textContent=[s.title,s.description,s.kind,s.caption,s.status,s.result,s.detail][i]);
      byId('stage-counter').textContent='RECORDED JOURNEY / '+String(selected+1).padStart(2,'0');
      byId('case-photo').src='cases/corridor/'+s.image;byId('case-photo').alt=s.caption;byId('original-photo').href='cases/corridor/'+s.image;
      byId('map-state').textContent=selected===0?'Scene graph only':s.pose===0?'Observation 1':'Observation 2';
      byId('page-count').textContent=(selected+1)+' / '+stages.length;
      byId('previous').disabled=selected===0;
      byId('next').textContent=selected===5?'Restart journey':'Next: '+stages[selected+1].label.toLowerCase();
      byId('app-capture').href='cases/corridor/'+s.capture;
      const metrics=selected===0?[['Reference cameras','141'],['Sparse 3D points','35,040'],['Navigation graph','13 nodes / 12 edges']]:[['2D–3D matches',q.num_2d3d.toLocaleString('en')],['Median reprojection error',q.median_error_px.toFixed(2)+' px'],['Navigation result',selected<2?'Not started':selected<4?'Navigating':selected===4?'Update saved':'Arrived']];
      ['one','two','three'].forEach((k,i)=>{byId('metric-'+k+'-label').textContent=metrics[i][0];byId('metric-'+k).textContent=metrics[i][1];});
      byId('evidence-explanation').textContent='These values are exported from saved application outputs. Reprojection error checks image geometry; it is not a measured physical position error. The navigation graph remains a candidate graph and has no measured metre scale.';
      const fields=[['Observation ID',obs.id],['XYZ (model units)',obs.pose.xyz.map(n=>n.toFixed(6)).join(', ')],['Camera forward',obs.pose.forward_world.map(n=>n.toFixed(6)).join(', ')],['Model ID',obs.pose.model_id],['Photo source','Registered mapping-photo replay'],['Navigation session',data.navigation.session],['Saved revisions','1: navigating; 2: arrived'],['Field verification','Pending; original field_verified = false']];
      const dl=byId('evidence-fields');dl.replaceChildren();fields.forEach(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;dl.append(dt,dd);});
      drawMap(s);if(focus)byId('stage-title').focus({preventScroll:true});
    }
    byId('previous').addEventListener('click',()=>show(selected-1,true));
    byId('next').addEventListener('click',()=>show(selected===5?0:selected+1,true));
    byId('walkthrough').hidden=false;show(0);
    document.title='HERE · Recorded photo-to-navigation journey';
  } catch(error) {byId('load-error').hidden=false;console.error('Recorded case could not be displayed:',error);}
})();
