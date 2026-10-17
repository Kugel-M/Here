from pathlib import Path
import numpy as np
from .graph import NavigationError,unit,vector


class ReferenceImageManager:
    def __init__(self,project,graph):self.project=Path(project).resolve();self.graph=graph

    def path(self,reference):
        path=(self.project/reference['image']).resolve()
        if not path.is_relative_to(self.project) or not path.is_file():raise NavigationError('参考照片不存在或超出项目目录')
        return path

    def select(self,step,pose):
        node_id=step['node_id']
        if node_id=='CURRENT':
            if step.get('connector_method')=='user_confirmed':node_id=step['next_node_id']
            else:
                edge=self.graph.snap(pose['xyz'],pose.get('floor'))['edge']
                node_id=min((edge['from'],edge['to']),key=lambda n:np.linalg.norm(vector(self.graph.nodes[n]['xyz'])-pose['xyz']))
        refs=self.graph.nodes[node_id].get('references',[])
        if not refs:return None
        desired=vector(step['incoming_forward']) if step.get('incoming_forward') else pose['forward']
        desired=desired-self.graph.up*np.dot(desired,self.graph.up)
        if np.linalg.norm(desired)<1e-8:desired=pose['forward']
        best=max(refs,key=lambda r:float(np.dot(unit(r['forward_world']),unit(desired))))
        self.path(best)
        return best
