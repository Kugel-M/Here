"""A* with Euclidean admissible heuristic; attach pose to an edge, including directionality."""
import heapq
import itertools
import numpy as np
from .graph import NavigationError,vector


class RoutePlanner:
    def __init__(self,graph):self.graph=graph

    def plan(self,pose,destination,confirmed_node=None):
        g=self.graph
        if destination not in g.nodes:raise NavigationError('目的地不存在')
        snap=None
        if confirmed_node:
            join_distance=g.confirm_connector(pose['xyz'],confirmed_node,pose.get('floor'))
            connectors=[(confirmed_node,0.)]
        else:
            snap=g.snap(pose['xyz'],pose.get('floor'));e=snap['edge'];a,b=e['from'],e['to']
            join_distance=snap['distance'];connectors=[(b,e['length']-snap['along'])]
            if e.get('bidirectional',True):connectors.append((a,snap['along']))
            # At the from node itself, joining its other outgoing edges is valid.
            elif snap['along']<1e-6:connectors.append((a,0.))
        costs={};parents={};heap=[];counter=itertools.count()
        target=vector(g.nodes[destination]['xyz'])
        for node,cost in connectors:
            cost+=join_distance;costs[node]=cost;parents[node]=None
            heapq.heappush(heap,(cost+np.linalg.norm(vector(g.nodes[node]['xyz'])-target),next(counter),node,cost))
        while heap:
            _,_,node,cost=heapq.heappop(heap)
            if cost>costs[node]+1e-9:continue
            if node==destination:break
            for nxt,edge,reverse in g.neighbors(node):
                candidate=cost+edge['length']
                if candidate<costs.get(nxt,float('inf')):
                    costs[nxt]=candidate;parents[nxt]=(node,edge,reverse)
                    heapq.heappush(heap,(candidate+np.linalg.norm(vector(g.nodes[nxt]['xyz'])-target),next(counter),nxt,candidate))
        else:raise NavigationError('当前位置与目的地之间没有可通行路线')
        chain=[];edges=[];node=destination
        while node is not None:
            chain.append(node);parent=parents[node]
            if parent is None:break
            prev,edge,rev=parent;edges.append((edge,rev));node=prev
        chain.reverse();edges.reverse();first=chain[0]
        if confirmed_node:
            poly=[pose['xyz'].tolist(),g.nodes[first]['xyz']];length=join_distance;kind='walk'
        else:
            poly=[pose['xyz'].tolist(),snap['point'].tolist()]
            if first==a:poly+=list(reversed(e['polyline'][:snap['index']+1]))
            else:poly+=e['polyline'][snap['index']+1:]
            length=join_distance+(snap['along'] if first==a else e['length']-snap['along']);kind=e.get('kind','walk')
        method='user_confirmed' if confirmed_node else 'automatic'
        segments=[dict(from_id='CURRENT',to_id=first,kind=kind,polyline=poly,length=length,connector_method=method)]
        for i,(edge,rev) in enumerate(edges):
            segments.append(dict(from_id=chain[i],to_id=chain[i+1],kind=edge.get('kind','walk'),
                polyline=list(reversed(edge['polyline'])) if rev else edge['polyline'],length=edge['length']))
        return dict(node_ids=chain,segments=segments,total_units=float(costs[destination]),snap_distance=join_distance,
                    start_node=first,destination=destination,connector_method=method)
