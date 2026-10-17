from pathlib import Path
import json
import uuid
import threading
import numpy as np
from .graph import NavigationGraph,NavigationError,vector
from .poi import POIManager
from .planner import RoutePlanner
from .instructions import NavigationInstructionGenerator
from .reference import ReferenceImageManager
from .renderer import ArrowOverlayRenderer


class NavigationController:
    def __init__(self,project):
        self.project=Path(project);self.sessions={};self.lock=threading.RLock()

    def catalog(self):
        try:
            g=NavigationGraph.load(self.project)
            return dict(available=True,pois=g.data.get('pois',[]),nodes=list(g.nodes.values()),
                meters_per_unit=g.scale,verified=g.data.get('field_verified',False),
                notice='请核实路线通行情况；未标米时不显示米数。')
        except NavigationError as e:return dict(available=False,reason=str(e),pois=[])

    def start(self,result,text,historical=False,confirmed_node=None):
        with self.lock:
            g=NavigationGraph.load(self.project);poi=POIManager(g).resolve(text)
            sid=uuid.uuid4().hex
            session=dict(id=sid,destination=poi,graph_data=g.data,revision=0,historical=bool(historical),initial_nodes=None)
            self._update(session,result,g,confirmed_node)
            self.sessions[sid]=session
            return self.view(sid)

    def update(self,sid,result,historical=False):
        with self.lock:
            s=self._session(sid)
            try:
                g=NavigationGraph.load(self.project)
                if g.data!=s['graph_data']:raise NavigationError('导航数据已改变，请重新选择目的地开始导航')
                s['historical']=bool(historical);self._update(s,result,g)
            except NavigationError as e:s.update(status='paused',reason=str(e))
            return self.view(sid)

    def _session(self,sid):
        if sid not in self.sessions:raise NavigationError('导航会话不存在或服务已重启，请重新选择目的地')
        return self.sessions[sid]

    def _update(self,s,result,g,confirmed_node=None):
        pose=g.pose(result);route=RoutePlanner(g).plan(pose,s['destination']['node_id'],confirmed_node)
        off_route=False
        if s.get('route'):
            distances=[]
            for seg in s['route']['segments']:
                for a,b in zip(seg['polyline'],seg['polyline'][1:]):
                    a,b=vector(a),vector(b);v=b-a;n=np.dot(v,v)
                    if n>1e-12:distances.append(np.linalg.norm(pose['xyz']-(a+np.clip(np.dot(pose['xyz']-a,v)/n,0,1)*v)))
            off_route=bool(distances and min(distances)>g.snap_radius)
        dest=g.nodes[s['destination']['node_id']]
        arrived=(np.linalg.norm(pose['xyz']-vector(dest['xyz']))<=g.arrival_radius and route['total_units']<=g.arrival_radius*2)
        steps=NavigationInstructionGenerator(g).generate(route,pose)
        if arrived:steps=steps[-1:];steps[0].update(step_number=1,total_steps=1,instruction='已匹配到目的地附近：'+dest['name']+'。请核对现场标识。')
        if s['initial_nodes'] is None or off_route:s['initial_nodes']=route['node_ids']
        initial=s['initial_nodes'];current=route['node_ids'][0]
        completed=initial.index(current) if current in initial else 0
        s.update(status='arrived' if arrived else 'navigating',pose={k:(v.tolist() if hasattr(v,'tolist') else v) for k,v in pose.items()},
            route=route,steps=steps,revision=s['revision']+1,replanned=off_route,
            completed_waypoints=completed,reason='你已确认当前站位可以直接走到接入点，位置仍来自原定位结果' if confirmed_node else '偏离原路线，已重新规划' if off_route else '已根据最新照片更新路线')
        refs=ReferenceImageManager(self.project,g);renderer=ArrowOverlayRenderer(g.up)
        folder=self.project/'navigation_runs'/s['id']/str(s['revision']);folder.mkdir(parents=True,exist_ok=True)
        current_ref=None
        raw_pose=result.get('pose',{})
        query_folder=Path(result.get('session','')).resolve()
        if query_folder.is_relative_to((self.project/'queries').resolve()) and all(k in raw_pose for k in ('rotation_camera_to_world','camera')):
            files=sorted((query_folder/'images').glob('*.jpg'))
            if files:
                current_ref=dict(image=files[0].relative_to(self.project.resolve()).as_posix(),xyz=raw_pose['xyz'],
                    forward_world=raw_pose['forward_world'],rotation_camera_to_world=raw_pose['rotation_camera_to_world'],camera=raw_pose['camera'])
        for i,step in enumerate(steps):
            ref=current_ref if i==0 and current_ref else refs.select(step,pose)
            step['reference']=None
            if ref:
                filename=f'{i}.jpg';metadata=renderer.render(refs.path(ref),ref,step.get('travel_vector'),step['action'],folder/filename)
                step['reference']=dict(image=ref['image'],xyz=ref['xyz'],forward_world=ref['forward_world'],
                    source='current_photo' if ref is current_ref else 'stored_reference',
                    url=f'/api/navigation/image?id={s["id"]}&revision={s["revision"]}&step={i}',**metadata)
        public=self.view_data(s,g)
        (folder/'route.json').write_text(json.dumps(public,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

    def view_data(self,s,g):
        return {key:s[key] for key in ('id','destination','revision','status','steps','replanned','reason','historical','completed_waypoints')} | dict(
            route=s['route'],distance=g.distance(s['route']['total_units']),
            preview_only=s['historical'] or not g.data.get('field_verified',False),
            distance_notice=None if g.scale else '尚未标米，距离暂以模型单位保存，不显示为米',
            observation_note='历史照片路线回放，不代表当前实时位置' if s['historical'] else '位置对应最后一次成功拍照，移动后请重新拍照确认')

    def view(self,sid):
        s=self._session(sid);return self.view_data(s,NavigationGraph(s['graph_data']))

    def diagnose(self,result):
        g=NavigationGraph.load(self.project);pose=g.pose(result)
        return g.diagnose(pose['xyz'],pose.get('floor'))

    def image_path(self,sid,revision,step):
        s=self._session(sid)
        if not str(revision).isdigit() or not str(step).isdigit():raise NavigationError('导航图片编号无效')
        path=self.project/'navigation_runs'/s['id']/str(int(revision))/f'{int(step)}.jpg'
        if not path.is_file():raise NavigationError('该步骤没有参考照片')
        return path
