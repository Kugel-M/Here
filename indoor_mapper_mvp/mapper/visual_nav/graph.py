"""Independent, versioned navigation data in the ORIGINAL COLMAP world frame."""
from pathlib import Path
import copy
import numpy as np
from ..engine import model_signature, save_json


class NavigationError(ValueError):
    pass


def vector(value, name='坐标'):
    a=np.asarray(value,dtype=float)
    if a.shape!=(3,) or not np.isfinite(a).all():raise NavigationError(name+'必须是3个有限数值')
    return a


def unit(value):
    a=vector(value);n=np.linalg.norm(a)
    if n<1e-9:raise NavigationError('方向向量不能为零')
    return a/n


class NavigationGraph:
    def __init__(self,data):
        self.data=copy.deepcopy(data)
        if data.get('schema_version')!=1:raise NavigationError('不支持的导航数据版本')
        self.up=unit(data['world_up']);self.nodes={}
        for n in data['nodes']:
            if n['node_id'] in self.nodes:raise NavigationError('导航点编号重复')
            vector(n['xyz']);self.nodes[n['node_id']]=n
        if not self.nodes:raise NavigationError('尚未设置导航点')
        self.scale=data.get('meters_per_unit')
        if self.scale is not None and (not np.isfinite(self.scale) or self.scale<=0):raise NavigationError('米制比例必须为正数')
        self.edges=[];self.adj={k:[] for k in self.nodes}
        for original in data['edges']:
            e=copy.deepcopy(original);a,b=e['from'],e['to']
            if a not in self.nodes or b not in self.nodes or a==b:raise NavigationError('通路端点无效')
            if self.nodes[a]['floor']!=self.nodes[b]['floor'] and e.get('kind') not in ('stairs','elevator','escalator'):
                raise NavigationError('跨楼层通路必须注明楼梯、电梯或扶梯')
            poly=e.get('polyline') or [self.nodes[a]['xyz'],self.nodes[b]['xyz']]
            points=[vector(p) for p in poly]
            if len(points)<2 or np.linalg.norm(points[0]-vector(self.nodes[a]['xyz']))>1e-5 or np.linalg.norm(points[-1]-vector(self.nodes[b]['xyz']))>1e-5:
                raise NavigationError('通路折线必须与两端导航点坐标一致')
            e['polyline']=[p.tolist() for p in points]
            e['length']=float(sum(np.linalg.norm(q-p) for p,q in zip(points,points[1:])))
            if e['length']<1e-8:raise NavigationError('通路长度为零')
            self.edges.append(e)
            if e.get('enabled',True):
                self.adj[a].append((b,e,False))
                if e.get('bidirectional',True):self.adj[b].append((a,e,True))
        for p in data.get('pois',[]):
            if p['node_id'] not in self.nodes:raise NavigationError('目的地绑定了不存在的导航点')
        self.snap_radius=float(data.get('snap_radius_units',.5))
        self.arrival_radius=float(data.get('arrival_radius_units',.2))
        self.height_tolerance=float(data.get('height_tolerance_units',self.snap_radius))
        self.manual_join_max=float(data.get('manual_join_max_units',self.snap_radius*4))
        if not np.isfinite([self.snap_radius,self.arrival_radius,self.height_tolerance,self.manual_join_max]).all() or min(self.snap_radius,self.arrival_radius,self.height_tolerance,self.manual_join_max)<=0:raise NavigationError('导航接入距离和高度容差必须为正数')

    @classmethod
    def load(cls,project):
        path=Path(project)/'visual_navigation.json'
        if not path.exists():raise NavigationError('尚未配置视觉导航，请先在电脑打开导航点设置')
        graph=cls(__import__('json').loads(path.read_text(encoding='utf-8')))
        model=Path(project)/'sparse'/str(graph.data['model_id'])
        if not model.is_dir() or model_signature(model)!=graph.data['model_signature']:
            raise NavigationError('导航图与当前三维模型不一致，请重新配置导航点')
        return graph

    def distance(self,length):
        return dict(distance_units=float(length),distance_m=float(length*self.scale) if self.scale else None)

    def neighbors(self,node):return self.adj[node]

    def save(self,project):save_json(Path(project)/'visual_navigation.json',self.data)

    def pose(self,result):
        if result.get('status')!='success':raise NavigationError('照片定位未通过，不能更新导航位置')
        p=result['pose']
        if str(p['model_id'])!=str(self.data['model_id']) or p.get('model_signature')!=self.data['model_signature']:
            raise NavigationError('定位与导航使用不同三维模型，拒绝混用坐标')
        xyz=vector(p['xyz']);forward=unit(p['forward_world'])
        if np.linalg.norm(forward-self.up*np.dot(forward,self.up))<.1:raise NavigationError('手机镜头接近竖直，请水平拍摄以确认行走方向')
        return dict(xyz=xyz,forward=forward,floor=result.get('floor'))

    def _candidates(self,xyz,floor=None):
        xyz=vector(xyz);candidates=[]
        for e in self.edges:
            if not e.get('enabled',True):continue
            floors={self.nodes[e['from']]['floor'],self.nodes[e['to']]['floor']}
            if floor is not None and floor not in floors:continue
            along=0.
            for i,(p,q) in enumerate(zip(e['polyline'],e['polyline'][1:])):
                p,q=vector(p),vector(q);v=q-p;length=np.linalg.norm(v)
                if length<1e-9:continue
                horizontal_v=v-self.up*np.dot(v,self.up)
                horizontal_delta=xyz-p-self.up*np.dot(xyz-p,self.up)
                walk=e.get('kind','walk')=='walk'
                denom=np.dot(horizontal_v,horizontal_v) if walk else length*length
                t=float(np.clip(np.dot(horizontal_delta,horizontal_v)/denom,0,1)) if walk and denom>1e-12 else float(np.clip(np.dot(xyz-p,v)/(length*length),0,1))
                point=p+t*v;delta=xyz-point;distance=float(np.linalg.norm(delta))
                vertical=abs(float(np.dot(delta,self.up)));horizontal=float(np.linalg.norm(delta-self.up*np.dot(delta,self.up)))
                candidates.append(dict(edge=e,index=i,t=t,point=point,distance=distance,horizontal=horizontal,vertical=vertical,
                    deviation=horizontal if walk else distance,walk=walk,along=along+t*length))
                along+=length
        return candidates

    def snap(self,xyz,floor=None):
        """Walking corridors use horizontal distance plus an independent height gate."""
        candidates=self._candidates(xyz,floor)
        if not candidates:raise NavigationError('该楼层没有可通行的导航路线')
        candidates=[c for c in candidates if not c['walk'] or c['vertical']<=self.height_tolerance]
        if not candidates:raise NavigationError('定位高度与导航轨迹不一致，请核对楼层或拍摄高度，并查看接入诊断')
        candidates.sort(key=lambda c:c['deviation']);best=candidates[0]
        if best['deviation']>self.snap_radius:raise NavigationError('已定位成功，但超出导航轨迹的接入范围。请查看下方覆盖图，或确认可直接走到的参考站位')
        near=[c for c in candidates if c['deviation']<=best['deviation']+self.snap_radius*.1]
        for c in near:
            if c['edge'] is best['edge']:continue
            if {c['edge']['from'],c['edge']['to']}.isdisjoint({best['edge']['from'],best['edge']['to']}):
                raise NavigationError('当前位置靠近两条未连通通路，无法判断所在通道，请换一个位置重拍或注明楼层')
        return best

    def confirm_connector(self,xyz,node_id,floor=None):
        if node_id not in self.nodes:raise NavigationError('接入参考站位不存在')
        node=self.nodes[node_id]
        if floor is not None and floor!=node['floor']:raise NavigationError('不能手动接入其他楼层的普通站位')
        delta=vector(xyz)-vector(node['xyz']);distance=float(np.linalg.norm(delta))
        if abs(float(delta@self.up))>self.height_tolerance:raise NavigationError('该参考站位高度差过大，请核对楼层')
        if distance>self.manual_join_max:raise NavigationError('参考站位过远，需先补充真实通路，不能直接接入')
        if not any(e.get('enabled',True) and node_id in (e['from'],e['to']) for e in self.edges):raise NavigationError('该站位没有可通行连接')
        return distance

    def diagnose(self,xyz,floor=None):
        xyz=vector(xyz);candidates=self._candidates(xyz,floor)
        eligible=[c for c in candidates if not c['walk'] or c['vertical']<=self.height_tolerance]
        best=min(eligible or candidates,key=lambda c:c['deviation']) if candidates else None
        try:self.snap(xyz,floor);status='ready';reason='当前位置可以自动接入导航通路'
        except NavigationError as e:status='needs_connection';reason=str(e)
        suggestions=[]
        for node_id,node in self.nodes.items():
            try:distance=self.confirm_connector(xyz,node_id,floor)
            except NavigationError:continue
            ref=next(iter(node.get('references',[])),None)
            suggestions.append(dict(node_id=node_id,name=node['name'],distance_units=distance,
                image=ref['image'] if ref else None,floor=node['floor']))
        suggestions.sort(key=lambda n:n['distance_units'])
        return dict(status=status,reason=reason,xyz=xyz.tolist(),world_up=self.up.tolist(),
            nearest=dict(horizontal=best['horizontal'],vertical=best['vertical'],edge=[best['edge']['from'],best['edge']['to']]) if best else None,
            limits=dict(horizontal=self.snap_radius,height=self.height_tolerance,manual=self.manual_join_max),
            meters_per_unit=self.scale,nodes=[dict(node_id=n['node_id'],name=n['name'],xyz=n['xyz']) for n in self.nodes.values()],
            lines=[e['polyline'] for e in self.edges if e.get('enabled',True)],suggestions=suggestions[:3])
