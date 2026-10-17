import numpy as np
from .graph import NavigationError,vector,unit


def turn(forward,direction,up):
    up=unit(up);a=vector(forward);b=vector(direction)
    a=a-np.dot(a,up)*up;b=b-np.dot(b,up)*up
    if min(np.linalg.norm(a),np.linalg.norm(b))<1e-8:return 'straight',0.
    a=unit(a);b=unit(b)
    # Right-handed WORLD up: positive angle is LEFT, independent of image/map axes.
    angle=float(np.degrees(np.arctan2(np.dot(up,np.cross(a,b)),np.dot(a,b))))
    action='uturn' if abs(angle)>=150 else 'straight' if abs(angle)<=30 else 'left' if angle>0 else 'right'
    return action,angle


LABELS={'straight':'直行','left':'左转','right':'右转','uturn':'掉头','up':'上楼','down':'下楼','arrive':'到达'}


def tangent(poly,at_end=False):
    pairs=list(zip(poly,poly[1:]))
    if at_end:pairs.reverse()
    for a,b in pairs:
        v=vector(b)-vector(a)
        if np.linalg.norm(v)>1e-7:return v
    return None


class NavigationInstructionGenerator:
    def __init__(self,graph):self.graph=graph

    def generate(self,route,pose):
        g=self.graph;steps=[];incoming=pose['forward'];remaining=route['total_units']
        for segment in route['segments']:
            if segment['length']<1e-6:continue
            outgoing=tangent(segment['polyline'])
            if outgoing is None:continue
            action,angle=turn(incoming,outgoing,g.up)
            if segment['kind'] in ('stairs','elevator','escalator'):
                height=float(np.dot(vector(segment['polyline'][-1])-vector(segment['polyline'][0]),g.up))
                if abs(height)>1e-6:action='up' if height>0 else 'down'
            target=g.nodes[segment['to_id']]
            distance=g.distance(segment['length']);metric=distance['distance_m']
            text=f'{LABELS[action]}，沿通路前往{target["name"]}'
            text+=f'，约 {metric:.1f} 米。' if metric is not None else '。'
            steps.append(dict(node_id=segment['from_id'],next_node_id=segment['to_id'],action=action,
                angle_degrees=angle,instruction=text,travel_vector=outgoing.tolist(),incoming_forward=np.asarray(incoming).tolist(),connector_method=segment.get('connector_method','automatic'),
                from_xyz=segment['polyline'][0],to_xyz=segment['polyline'][-1],polyline=segment['polyline'],
                remaining_units=remaining,**distance))
            incoming=tangent(segment['polyline'],True);remaining-=segment['length']
        dest=g.nodes[route['destination']]
        steps.append(dict(node_id=dest['node_id'],next_node_id=None,action='arrive',angle_degrees=0,
            instruction='到达核对点：'+dest['name']+'。请重新拍照确认实际到达。',travel_vector=None,
            from_xyz=dest['xyz'],to_xyz=dest['xyz'],polyline=[dest['xyz']],remaining_units=0.,**g.distance(0.)))
        for i,step in enumerate(steps):step.update(step_number=i+1,total_steps=len(steps))
        return steps
