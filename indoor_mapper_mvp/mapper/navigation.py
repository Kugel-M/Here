"""Turn real COLMAP poses into explicitly calibrated floor-plan coordinates."""
from pathlib import Path
import heapq
import json
import math
import uuid
import copy
import numpy as np
from PIL import Image, ImageOps
from .engine import PipelineError, save_json, model_signature, open_project
from .model import load_model


def empty_layout():
    return dict(schema_version=1,width=1200,height=800,image=None,pixels_per_meter=None,
                anchors={},calibrations={},reference_labels={},nodes=[],edges=[],heading_calibrations={})


def load_layout(project):
    p=Path(project)/'site_map.json'
    layout=json.loads(p.read_text(encoding='utf-8')) if p.exists() else empty_layout()
    layout.setdefault('heading_calibrations',{})
    return layout


def save_layout(project,layout):
    save_json(Path(project)/'site_map.json',layout)


def backup_layout(project):
    project=Path(project)
    previous=project/'site_map.json'
    if previous.exists():
        backup=project/'site_map_backups';backup.mkdir(exist_ok=True)
        target=backup/f'{uuid.uuid4().hex}.json'
        target.write_bytes(previous.read_bytes())
        return target


def resize_annotations(layout,width,height):
    """For the SAME uncropped layout only; require a new calibration afterward."""
    sx=width/layout['width'];sy=height/layout['height']
    for controls in layout['anchors'].values():
        for item in controls:item['uv']=[item['uv'][0]*sx,item['uv'][1]*sy]
    for item in layout['nodes']:item['uv']=[item['uv'][0]*sx,item['uv'][1]*sy]
    ppm=layout.get('pixels_per_meter')
    layout['pixels_per_meter']=ppm*sx if ppm and abs(sx-sy)<1e-6 else None
    layout['width']=width;layout['height']=height;layout['calibrations']={};layout['heading_calibrations']={}


def restore_annotations(project,source,include_coordinates=False):
    """Merge missing names without overwriting current names; coordinates opt-in."""
    layout=load_layout(project);old=json.loads(Path(source).read_text(encoding='utf-8'))
    backup_layout(project);count=0
    for mid,labels in old.get('reference_labels',{}).items():
        current=layout['reference_labels'].setdefault(mid,{})
        for name,label in labels.items():
            if label and not current.get(name):current[name]=label;count+=1
    if include_coordinates:
        migrated=copy.deepcopy(old)
        resize_annotations(migrated,layout['width'],layout['height'])
        for key in ['anchors','nodes','edges','pixels_per_meter']:layout[key]=migrated[key]
        layout['calibrations']={}
    save_layout(project,layout)
    return layout,count


def set_floorplan(project,source,preserve_coordinates=False):
    project=Path(project);old=load_layout(project)
    backup_layout(project)
    layout=copy.deepcopy(old) if preserve_coordinates else empty_layout()
    layout['reference_labels']=copy.deepcopy(old['reference_labels'])
    asset=project/'assets';asset.mkdir(exist_ok=True)
    name=f'floorplan_{uuid.uuid4().hex[:8]}.png'
    with Image.open(source) as im:
        im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((2000,2000))
        im.save(asset/name)
        resize_annotations(layout,im.width,im.height)
        layout['image']=f'assets/{name}'
    save_layout(project,layout);return layout


def estimate_world_up(references):
    """Infer up from consistently upright reference images, not an IMU reading."""
    vectors=np.asarray([-im['R'][1] for im in references],dtype=float)
    if len(vectors)<3:raise PipelineError('至少需要3张正常直立拍摄的参考图以检查地图左右方向。')
    mean=vectors.mean(axis=0);strength=np.linalg.norm(mean)
    if strength<.85:raise PipelineError('参考图的画面上下方向不一致，无法确认地图朝向。请选取正常直立、俯仰变化较小的参考图。')
    up=mean/strength
    if np.min(vectors@up)<.65:raise PipelineError('部分参考图倾斜或俯仰变化过大，无法可靠检查地图方向。请换用画面直立的参考图。')
    return up


def fit_calibration(xyz,uv,signature,max_error=20.,world_up=None):
    """Fit a planar uniform-scale similarity; constrain handedness when up is known.

    Controls are camera positions at comparable height on ONE floor. The
    estimated plane is a reference camera plane, not an automatically found floor.
    """
    xyz=np.asarray(xyz,dtype=float);uv=np.asarray(uv,dtype=float)
    if xyz.shape!=(len(uv),3) or uv.shape!=(len(xyz),2) or len(xyz)<3:
        raise PipelineError('至少需要3个已知拍摄位置及其地图对应点。')
    if not np.all(np.isfinite(xyz)) or not np.all(np.isfinite(uv)):
        raise PipelineError('标定点包含无效数值。')
    origin=xyz.mean(axis=0);_,s,basis=np.linalg.svd(xyz-origin,full_matrices=False)
    map_s=np.linalg.svd(uv-uv.mean(axis=0),compute_uv=False)
    if s[0]<1e-8 or s[1]/s[0]<.02 or map_s[0]<1e-8 or map_s[1]/map_s[0]<.02:
        raise PipelineError('标定点接近同一直线，无法可靠确定地图朝向。请增加一个侧向拍摄位置。')
    plane=basis[:2].T
    xy=(xyz-origin)@plane
    a=xy-xy.mean(axis=0);b=uv-uv.mean(axis=0)
    u,d,vt=np.linalg.svd(a.T@b);rot=u@vt
    signs=np.ones(2);mirror_rejected=False
    if world_up is not None:
        up=np.asarray(world_up,dtype=float);norm=np.linalg.norm(up)
        if up.shape!=(3,) or not np.isfinite(up).all() or norm<1e-8:raise PipelineError('楼层上下方向无效。')
        up=up/norm;agreement=float(np.dot(np.cross(plane[:,0],plane[:,1]),up))
        if abs(agreement)<.7:raise PipelineError('拍摄位置形成的平面与直立画面推断的楼层方向不一致，请检查高度变化、重建轨迹或增加参考点。')
        # Map x-right,y-down has a DOWN normal; camera-world up fixes the sign.
        required=-np.sign(agreement)
        if np.linalg.det(rot)*required<0:
            signs[1]=-1.;rot=u@np.diag(signs)@vt;mirror_rejected=True
    scale=float(np.dot(d,signs)/np.sum(a*a))
    offset=uv.mean(axis=0)-scale*xy.mean(axis=0)@rot
    errors=np.linalg.norm(scale*xy@rot+offset-uv,axis=1)
    rms=float(np.sqrt(np.mean(errors**2)))
    if not np.isfinite(scale) or scale<=0 or rms>max_error or float(errors.max())>max_error*2:
        worst=int(np.argmax(errors))
        detail='当前对应点会使无约束拟合左右镜像，程序已拒绝镜像标定。' if mirror_rejected else ''
        raise PipelineError(f'{detail}模型相机位置与底图站位无法一致对齐：均方根误差 {rms:.1f} 像素，最大单点残差 {errors[worst]:.1f} 像素（标定点 {worst+1}）。这是整体拟合后的残差，不代表该站位标错；也需检查重建轨迹、底图比例和投影假设。')
    nonplanarity=float(s[2]/s[1]) if len(s)>2 else 0.
    if nonplanarity>.25:
        raise PipelineError('参考拍摄位置不近似共面。请使用同楼层、相近手机高度的拍摄位置。')
    result=dict(model_signature=signature,origin=origin.tolist(),basis=plane.tolist(),
        rotation=rot.tolist(),scale=scale,offset=offset.tolist(),rms_error_px=rms,
        max_error_px=float(errors.max()),control_errors_px=errors.tolist(),num_controls=len(xyz),
        nonplanarity=nonplanarity,assumption='同楼层、相近相机高度；投影至参考相机平面后与底图对齐')
    if world_up is not None:
        result.update(orientation_version=1,world_up=up.tolist(),
            up_source='根据正常直立拍摄的参考画面推断，非手机IMU测量')
    return result


def stretch_diagnostic(xyz,uv,max_error=20.):
    """Suggest axis compression only if an affine fit predicts withheld controls.

    No coordinate substitution: this is a diagnostic, never a localization fit.
    """
    xyz=np.asarray(xyz,dtype=float);uv=np.asarray(uv,dtype=float)
    if len(xyz)<6:return '检查底图拉伸至少需要6个分布充分的标定点。目前不足，无法估计压缩比例。'
    if xyz.shape!=(len(uv),3) or uv.shape!=(len(xyz),2) or not (np.isfinite(xyz).all() and np.isfinite(uv).all()):
        return '标定数据无效，无法检查底图拉伸。'
    _,s,basis=np.linalg.svd(xyz-xyz.mean(axis=0),full_matrices=False)
    if s[0]<1e-8 or s[1]/s[0]<.02 or s[2]/s[1]>.25:return '拍摄位置分布过窄或高度差较大，无法可靠估计底图压缩比例。'
    xy=(xyz-xyz.mean(axis=0))@basis[:2].T
    design=np.column_stack((xy,np.ones(len(xy))))
    affine=np.linalg.lstsq(design,uv,rcond=None)[0]
    scales=np.linalg.norm(affine[:2],axis=0)
    if min(scales)<1e-8:return '底图对应点分布不足，无法估计压缩比例。'
    cosine=abs(np.dot(affine[:2,0],affine[:2,1])/np.prod(scales))
    cv=[]
    for i in range(len(xy)):
        keep=np.arange(len(xy))!=i
        subset=design[keep]
        if np.linalg.matrix_rank(subset)<3:return '去掉一个点后标定点接近共线，无法可靠检查拉伸。'
        cv.append(float(np.linalg.norm(design[i]@np.linalg.lstsq(subset,uv[keep],rcond=None)[0]-uv[i])))
    correction=np.ones(2);axis=int(np.argmax(scales));correction[axis]=min(scales)/max(scales)
    try:
        corrected=fit_calibration(xyz,uv*correction,'diagnostic',max_error)
    except PipelineError:corrected=None
    if cosine>.1 or max(cv)>max_error*2 or np.sqrt(np.mean(np.square(cv)))>max_error or corrected is None or correction[axis]>.95:
        worst=int(np.argmax(cv))
        return f'现有数据不支持用简单横纵拉伸完成对齐，暂不建议压缩底图。逐点留出检查中，第 {worst+1} 点的预测差异最大；它可能远离其他点、受模型漂移或其他点的偏差影响，不能据此判定该点标错。请比较模型与底图上的相对距离，并检查底图布局。整体缩小图片只会减小像素误差数值，不会修复几何关系。'
    word='宽度' if axis==0 else '高度';other='高度' if axis==0 else '宽度'
    return (f'这些标定点支持底图存在横纵比例差异。可尝试把{word}调为原来的 {correction[axis]*100:.1f}%，{other}保持不变。'
            f'逐点留出检查的均方根误差为 {np.sqrt(np.mean(np.square(cv))):.1f} 像素，按此比例修正后的拟合误差为 {corrected["rms_error_px"]:.1f} 像素。'
            '这是基于当前标定点的建议，也可能反映重建形变；请用建筑已知尺寸和未参与标定的照片核对。程序不会自动修改底图或放宽误差门槛。')


def diagnose_model(project,layout,mid):
    images=load_model(Path(project)/'sparse'/str(mid)/'text')[1]
    byname={im['name']:im for im in images.values()}
    anchors=layout['anchors'].get(str(mid),[])
    if any(a['image'] not in byname for a in anchors):return '部分标定参考图不属于当前模型。'
    return stretch_diagnostic([byname[a['image']]['center'] for a in anchors],[a['uv'] for a in anchors])


def calibrated_position(calibration,xyz,forward):
    origin=np.array(calibration['origin']);basis=np.array(calibration['basis']);r=np.array(calibration['rotation'])
    pos=calibration['scale']*(np.array(xyz)-origin)@basis@r+np.array(calibration['offset'])
    heading=np.array(forward)@basis@r
    norm=np.linalg.norm(heading)
    return pos,heading/norm if norm>.1 else None


MAP_DIRECTIONS={'北':[0,-1],'东北':[1,-1],'东':[1,0],'东南':[1,1],
                '南':[0,1],'西南':[-1,1],'西':[-1,0],'西北':[-1,-1]}


def fit_heading(forward,world_up,map_direction,signature,source):
    """One known viewing bearing fixes yaw; positions are NOT changed by it."""
    up=np.asarray(world_up,dtype=float)
    if up.shape!=(3,) or not np.isfinite(up).all() or np.linalg.norm(up)<1e-8:raise PipelineError('参考上下方向无效。')
    up=up/np.linalg.norm(up)
    f=np.asarray(forward,dtype=float);f=f-np.dot(f,up)*up
    if not np.isfinite(f).all() or np.linalg.norm(f)<.15:raise PipelineError('参考镜头接近竖直，无法用它标定平面方向。')
    f=f/np.linalg.norm(f);right=np.cross(f,up)
    h=np.asarray(map_direction,dtype=float)
    if h.shape!=(2,) or not np.isfinite(h).all() or np.linalg.norm(h)<1e-8:raise PipelineError('地图方向无效。')
    h=h/np.linalg.norm(h);map_right=np.array([-h[1],h[0]])
    transform=np.outer(f,h)+np.outer(right,map_right)
    return dict(model_signature=signature,transform=transform.tolist(),world_up=up.tolist(),
        reference_direction=h.tolist(),source=source,
        assumption='已知照片朝向固定模型与底图的水平旋转；参考画面直立，方向与位置分别标定')


def heading_position(calibration,forward):
    heading=np.asarray(forward)@np.asarray(calibration['transform'])
    norm=np.linalg.norm(heading)
    return (heading/norm).tolist() if norm>.15 else None


def save_heading_reference(project,layout,mid,reference_image,direction):
    images=load_model(Path(project)/'sparse'/str(mid)/'text')[1]
    byname={im['name']:im for im in images.values()}
    if reference_image not in byname:raise PipelineError('参考图不属于当前模型。')
    return save_heading_pose(project,layout,mid,byname[reference_image]['R'][2],direction,
        dict(type='reference',image=reference_image,direction=direction))


def save_heading_pose(project,layout,mid,forward,direction,source):
    if direction not in MAP_DIRECTIONS:raise PipelineError('请选择北、东北、东、东南、南、西南、西或西北。')
    images=load_model(Path(project)/'sparse'/str(mid)/'text')[1]
    byname={im['name']:im for im in images.values()}
    refs=[byname[a['image']] for a in layout['anchors'].get(str(mid),[]) if a['image'] in byname]
    if len(refs)<3:refs=list(images.values())
    up=estimate_world_up(refs)
    calibration=fit_heading(forward,up,MAP_DIRECTIONS[direction],model_signature(Path(project)/'sparse'/str(mid)),source)
    backup_layout(project)
    layout.setdefault('heading_calibrations',{})[str(mid)]=calibration
    save_layout(project,layout);return calibration


def save_query_heading(project,layout,result_path,direction):
    result=json.loads(Path(result_path).read_text(encoding='utf-8'))
    if result.get('status')!='success':raise PipelineError('定位失败的照片不能用来标定方向。')
    pose=result['pose'];mid=pose['model_id']
    if pose.get('model_signature')!=model_signature(Path(project)/'sparse'/mid):raise PipelineError('照片结果与模型不对应。')
    return save_heading_pose(project,layout,mid,pose['forward_world'],direction,
        dict(type='query',result_path=str(Path(result_path).resolve()),direction=direction,
             note='该照片的方向由用户提供，用于标定，不能作为独立方向验收'))


def calibrate_model(project,layout,mid,max_error=20.):
    project=Path(project);mid=str(mid)
    _,images,_=load_model(project/'sparse'/mid/'text')
    byname={im['name']:im for im in images.values()}
    anchors=layout['anchors'].get(mid,[])
    if any(a['image'] not in byname for a in anchors):raise PipelineError('标定参考图不属于此模型，请重新选择。')
    xyz=[byname[a['image']]['center'] for a in anchors];uv=[a['uv'] for a in anchors]
    world_up=estimate_world_up([byname[a['image']] for a in anchors])
    cal=fit_calibration(xyz,uv,model_signature(project/'sparse'/mid),max_error,world_up=world_up)
    cal['anchors']=anchors
    layout['calibrations'][mid]=cal
    save_layout(project,layout);return cal


def reference_matches(project,result_path,limit=3):
    project=Path(project).resolve();result_path=Path(result_path).resolve()
    result=json.loads(result_path.read_text(encoding='utf-8'))
    if result.get('status')!='success':return []
    pose=result['pose'];mid=pose['model_id']
    if pose.get('model_signature')!=model_signature(project/'sparse'/mid):
        raise PipelineError('结果与当前模型不对应，请打开生成该结果的地图项目。')
    _,references,_=load_model(project/'sparse'/mid/'text')
    session=result_path.parent
    text=session/f'model_{mid}/text'
    if not text.exists():raise PipelineError('找不到定位后的模型参数，无法读取参考图关联。')
    registered=load_model(text)[1]
    qnames=(session/'query_list.txt').read_text(encoding='utf-8').strip().splitlines()
    query=next((i for i in registered.values() if i['name'] in qnames),None)
    if query is None:raise PipelineError('定位模型中找不到对应的查询照片。')
    ids=set(int(p) for p in query['point_ids'] if p!=-1)
    layout=load_layout(project);times={}
    if (project/'frames.json').exists():
        times={f['image_name']:f['time_seconds'] for f in json.loads((project/'frames.json').read_text(encoding='utf-8'))['frames'] if f['image_name']}
    refs=[]
    for im in references.values():
        shared=len(ids.intersection(int(p) for p in im['point_ids'] if p!=-1))
        if not shared:continue
        path=(project/'images'/im['name']).resolve()
        if not path.is_relative_to(project/'images'):raise PipelineError('参考图路径越界。')
        refs.append(dict(image=im['name'],path=str(path),shared_points=shared,time_seconds=times.get(im['name']),
            distance_in_model_units=float(np.linalg.norm(im['center']-np.array(pose['xyz']))),
            region=layout['reference_labels'].get(mid,{}).get(im['name'],'')))
    refs.sort(key=lambda i:(-i['shared_points'],i['distance_in_model_units']))
    return refs[:limit]


def mapped_pose(project,result,layout=None):
    layout=layout or load_layout(project)
    if result.get('status')!='success':return dict(status='unavailable',reason='照片未通过定位，不显示地图位置。')
    pose=result['pose'];mid=pose['model_id'];sig=model_signature(Path(project)/'sparse'/mid)
    if pose.get('model_signature')!=sig:return dict(status='unavailable',reason='定位结果与地图模型不一致。')
    heading_cal=layout.get('heading_calibrations',{}).get(mid)
    independent_heading=(heading_position(heading_cal,pose['forward_world'])
                         if heading_cal and heading_cal.get('model_signature')==sig else None)
    cal=layout['calibrations'].get(mid)
    if not cal:
        if independent_heading is not None:return dict(status='direction_only',heading=independent_heading,reason='拍摄方向已标定；地图位置尚未标定，箭头显示在方向框中。')
        return dict(status='uncalibrated',reason=f'模型 {mid} 尚未标定到平面图，暂不显示地图位置。')
    if cal.get('model_signature')!=sig:
        if independent_heading is not None:return dict(status='direction_only',heading=independent_heading,reason='方向已标定；位置标定对应旧模型，箭头显示在方向框中。')
        return dict(status='uncalibrated',reason='模型已改变，请重新标定平面图。')
    if cal.get('orientation_version')!=1 and independent_heading is None:
        return dict(status='uncalibrated',reason='旧标定未检查左右镜像，请在地图与区域设置中重新计算标定。区域识别仍可使用。')
    pos,heading=calibrated_position(cal,pose['xyz'],pose['forward_world'])
    if not (0<=pos[0]<=layout['width'] and 0<=pos[1]<=layout['height']):
        if independent_heading is not None:return dict(status='direction_only',heading=independent_heading,reason='方向已标定；估计位置超出底图，箭头显示在方向框中。')
        return dict(status='outside',reason='定位投影超出底图范围，请核对标定点或补充地图覆盖。')
    if independent_heading is not None:heading=independent_heading
    return dict(status='ready' if cal.get('orientation_version')==1 else 'approximate',
                reason='方向已单独标定；位置来自旧标定，仅供估计，暂不用于规划路线。',
                heading_source='known_reference' if independent_heading is not None else 'position_calibration',
                uv=pos.tolist(),heading=np.asarray(heading).tolist() if heading is not None else None,
                calibration_rms_px=cal['rms_error_px'],model_id=mid)


def route_to(layout,uv,destination,max_snap=45.):
    """Route on explicitly annotated walkable edges; never infer free space."""
    nodes={n['id']:n for n in layout['nodes']}
    if destination not in nodes:raise PipelineError('目的地不存在。')
    graph={nid:[] for nid in nodes};segments=[]
    for edge in layout['edges']:
        a,b=edge
        if a not in nodes or b not in nodes or a==b:continue
        pa=np.array(nodes[a]['uv']);pb=np.array(nodes[b]['uv']);delta=pb-pa
        length=float(np.linalg.norm(delta))
        if length<1e-8:continue
        graph[a].append((b,length));graph[b].append((a,length))
        t=float(np.clip(np.dot(np.array(uv)-pa,delta)/(length*length),0,1));q=pa+t*delta
        segments.append((float(np.linalg.norm(q-np.array(uv))),a,b,q,t,length))
    if not segments:raise PipelineError('尚未标注可通行路线。请在地图设置中连接实际可通行的地点。')
    distance,a,b,q,t,length=min(segments,key=lambda s:s[0])
    if distance>max_snap:raise PipelineError('当前位置离已标注通路较远，无法确定路线起点。请补充通路或核对标定。')
    graph['__start__']=[(a,t*length),(b,(1-t)*length)]
    heap=[(0.,'__start__')];cost={'__start__':0.};prev={}
    while heap:
        d,u=heapq.heappop(heap)
        if d!=cost[u]:continue
        if u==destination:break
        for v,w in graph[u]:
            nd=d+w
            if nd<cost.get(v,math.inf):cost[v]=nd;prev[v]=u;heapq.heappush(heap,(nd,v))
    if destination not in cost:raise PipelineError('当前位置与目的地之间没有已标注的连通路线。')
    chain=[];current=destination
    while current!='__start__':chain.append(current);current=prev[current]
    chain.reverse();path=[q.tolist()]+[nodes[n]['uv'] for n in chain]
    # Display begins ON the known route; do not invent a segment across a wall.
    ppm=layout.get('pixels_per_meter')
    return dict(points=path,node_names=[nodes[n]['name'] for n in chain],length_pixels=cost[destination],
        length_meters=cost[destination]/ppm if ppm and ppm>0 else None,
        distance_to_route_px=distance,start_note='路线从附近已标注通路开始，请确认自己位于该通路。')
