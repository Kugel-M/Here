"""Build editable navigation candidates from real registered frames, never map-pixel inversion."""
from pathlib import Path
import copy
import json
import time
import numpy as np
from ..model import load_model
from ..engine import model_signature,save_json
from ..navigation import load_layout,estimate_world_up
from .graph import NavigationGraph,NavigationError,vector


def reference_catalog(project,mid='0'):
    project=Path(project);cameras,images,_=load_model(project/'sparse'/str(mid)/'text')
    labels=load_layout(project).get('reference_labels',{}).get(str(mid),{})
    refs=[]
    for im in sorted(images.values(),key=lambda v:v['name']):
        refs.append(dict(image='images/'+im['name'],name=im['name'],label=labels.get(im['name'],''),
            xyz=im['center'].tolist(),forward_world=im['R'].T[:,2].tolist(),
            rotation_camera_to_world=im['R'].T.tolist(),camera=cameras[im['camera_id']]))
    return refs


def bootstrap(project,mid='0',count=8):
    project=Path(project);path=project/'visual_navigation.json'
    if path.exists():return NavigationGraph.load(project).data
    refs=reference_catalog(project,mid)
    if len(refs)<3:raise NavigationError('至少需要3张已注册的真实参考照片')
    # Cover the complete recorded trajectory; never silently truncate at frame 80.
    chosen=refs;indices=np.linspace(0,len(chosen)-1,min(count,len(chosen)),dtype=int)
    layout=load_layout(project);cal=layout.get('heading_calibrations',{}).get(str(mid),{})
    up=cal.get('world_up') if cal.get('model_signature')==model_signature(project/'sparse'/str(mid)) else None
    if up is None:
        matrices=[dict(R=np.array(r['rotation_camera_to_world']).T) for r in chosen]
        up=estimate_world_up(matrices).tolist()
    nodes=[];pois=[];edges=[]
    for i,index in enumerate(indices):
        ref=chosen[index];name=(ref['label'] or '通道')+f'参考点{i+1}'
        node=dict(node_id=f'N{i+1:02d}',name=name,region=ref['label'] or '已建图区域',xyz=ref['xyz'],
            floor='当前楼层',type='poi' if i==len(indices)-1 else 'corridor',references=[ref],
            source='真实已注册视频帧的相机站位，地点名称和通行情况待现场核实')
        nodes.append(node);pois.append(dict(node_id=node['node_id'],name=name,aliases=[f'参考点{i+1}']))
        if i:
            poly=[r['xyz'] for r in chosen[indices[i-1]:index+1]]
            edges.append(dict({'from':nodes[-2]['node_id'],'to':node['node_id']},kind='walk',bidirectional=True,
                enabled=True,polyline=poly,evidence='同一次视频中的连续已注册相机轨迹；候选通路，需现场核实'))
    lengths=[np.linalg.norm(vector(e['polyline'][-1])-vector(e['polyline'][0])) for e in edges]
    typical=float(np.median(lengths));data=dict(schema_version=1,model_id=str(mid),model_signature=model_signature(project/'sparse'/str(mid)),
        world_up=up,meters_per_unit=None,field_verified=False,snap_radius_units=max(.1,typical*.4),
        arrival_radius_units=max(.05,typical*.15),nodes=nodes,edges=edges,pois=pois,
        note='真实轨迹候选导航图，尚未现场核实，非奶茶店场景；原定位地图未修改')
    for node in nodes:
        primary=node['references'][0]
        node['references']=[primary,*[r for r in refs if r['image']!=primary['image'] and np.linalg.norm(vector(r['xyz'])-vector(node['xyz']))<=data['arrival_radius_units']*2]]
    graph=NavigationGraph(data);graph.save(project);return data


def extend_recorded_coverage(project):
    """Append the missing video tail, preserving existing names, POIs, edges and scale."""
    project=Path(project);old=NavigationGraph.load(project);data=copy.deepcopy(old.data)
    refs=reference_catalog(project,data['model_id']);lookup={r['image']:i for i,r in enumerate(refs)}
    known=[(lookup[r['image']],n['node_id']) for n in data['nodes'] for r in n.get('references',[])[:1] if r['image'] in lookup]
    if not known:raise NavigationError('导航图没有可对应的视频参考帧，请人工选择通路')
    start,previous=max(known)
    if start>=len(refs)-1:return data
    indices=list(range(start+14,len(refs),14))
    if not indices or indices[-1]!=len(refs)-1:indices.append(len(refs)-1)
    floor=old.nodes[previous]['floor'];last=start
    existing=set(old.nodes)
    for index in indices:
        suffix=1
        while f'T{suffix:03d}' in existing:suffix+=1
        node_id=f'T{suffix:03d}';existing.add(node_id);ref=refs[index]
        name=(ref['label'] or '通道')+f'扩展点{suffix}'
        nearby=[r for r in refs if r['image']!=ref['image'] and np.linalg.norm(vector(r['xyz'])-vector(ref['xyz']))<=old.arrival_radius*2]
        data['nodes'].append(dict(node_id=node_id,name=name,region=ref['label'] or '已建图区域',floor=floor,type='corridor',xyz=ref['xyz'],references=[ref,*nearby],source='补全原视频后续已注册相机轨迹，待现场核实'))
        data['pois'].append(dict(node_id=node_id,name=name,aliases=[f'扩展点{suffix}']))
        trajectory=refs[last:index+1]
        data['edges'].append(dict({'from':previous,'to':node_id},kind='walk',enabled=True,bidirectional=True,
            polyline=[r['xyz'] for r in trajectory],evidence='同一原始视频后续的真实注册轨迹，连接仍需现场核实'))
        previous=node_id;last=index
    data['field_verified']=False
    data['coverage']=dict(registered_images=len(refs),last_image=refs[-1]['image'],source='original_registered_video',expanded_from_index=start)
    graph=NavigationGraph(data);backup=project/'navigation_backups';backup.mkdir(exist_ok=True)
    save_json(backup/f'{time.time_ns()}_before_coverage_extension.json',old.data);graph.save(project)
    return data


def save_configuration(project,body):
    project=Path(project);old=NavigationGraph.load(project);data=copy.deepcopy(old.data)
    refs={r['image']:r for r in reference_catalog(project,data['model_id'])}
    nodes=[];pois=[]
    for item in body['nodes']:
        image=item['image']
        if image not in refs:raise NavigationError('只能选择该模型已注册的真实参考照片')
        node_id=str(item['node_id'])
        if not node_id or not node_id.replace('_','').isalnum():raise NavigationError('导航点编号只能使用字母、数字和下划线')
        if not item['name'].strip():raise NavigationError('导航点名称不能为空')
        selected=[image,*item.get('extra_images',[])]
        if any(name not in refs for name in selected):raise NavigationError('附加参考照片不在当前模型中')
        node=dict(node_id=node_id,name=item['name'].strip(),region=item.get('region',''),floor=item.get('floor','当前楼层'),
            type=item.get('type','corridor'),xyz=refs[image]['xyz'],references=[refs[name] for name in dict.fromkeys(selected)])
        nodes.append(node)
        if item.get('destination',True):pois.append(dict(node_id=node_id,name=node['name'],aliases=item.get('aliases',[])))
    data.update(nodes=nodes,pois=pois,field_verified=bool(body.get('field_verified',False)))
    nodes_by_id={n['node_id']:n for n in nodes};edges=[]
    for item in body['edges']:
        a,b=item['from'],item['to']
        if a not in nodes_by_id or b not in nodes_by_id:raise NavigationError('通路引用了未设置的节点')
        before=next((e for e in old.edges if e['from']==a and e['to']==b),None)
        preserve=before and np.allclose(before['polyline'][0],nodes_by_id[a]['xyz']) and np.allclose(before['polyline'][-1],nodes_by_id[b]['xyz'])
        poly=before['polyline'] if preserve else [nodes_by_id[a]['xyz'],nodes_by_id[b]['xyz']]
        edges.append(dict({'from':a,'to':b},kind=item.get('kind','walk'),enabled=bool(item.get('enabled',True)),
            bidirectional=bool(item.get('bidirectional',True)),polyline=poly,evidence='用户维护的可通行导航连接'))
    data['edges']=edges
    # A changed node invalidates a previous scale measurement involving that node.
    measurement=data.get('scale_measurement')
    if measurement and not body.get('scale_measurement'):
        for key in ('a','b'):
            node=nodes_by_id.get(measurement[key]);oldnode=old.nodes.get(measurement[key])
            if node is None or oldnode is None or not np.allclose(node['xyz'],oldnode['xyz']):
                data['meters_per_unit']=None;data.pop('scale_measurement',None);break
    if body.get('scale_measurement'):
        m=body['scale_measurement'];distance=float(m['meters'])
        if not np.isfinite(distance) or distance<=0:raise NavigationError('实测直线距离必须大于零')
        length=np.linalg.norm(vector(nodes_by_id[m['a']]['xyz'])-vector(nodes_by_id[m['b']]['xyz']))
        if length<1e-6:raise NavigationError('两个标尺节点不能处于同一站位')
        data['meters_per_unit']=float(distance/length);data['scale_measurement']=m
    for key in ('snap_radius_units','arrival_radius_units','height_tolerance_units','manual_join_max_units'):
        if key in body:data[key]=float(body[key])
    new=NavigationGraph(data)
    if len(new.nodes)>100:raise NavigationError('MVP 一次最多100个节点')
    backup=project/'navigation_backups';backup.mkdir(exist_ok=True)
    save_json(backup/f'{time.time_ns()}.json',old.data);new.save(project);return new.data
