import re
import unicodedata
from .graph import NavigationError


def normalize(text):
    text=unicodedata.normalize('NFKC',text).casefold()
    for word in ['我想去','我要去','带我去','请带我到','我想找','导航到','前往','我要','我想','请问','在哪里','怎么走','的位置']:
        text=text.replace(word,'')
    return re.sub(r'[\W_]+','',text)


class POIManager:
    def __init__(self,graph):self.graph=graph

    def resolve(self,text):
        q=normalize(text)
        if not q:raise NavigationError('请输入目的地名称')
        exact=[];partial=[]
        for poi in self.graph.data.get('pois',[]):
            node=self.graph.nodes[poi['node_id']]
            names=[poi['name'],node['name'],node.get('region','')+poi['name'],*poi.get('aliases',[])]
            aliases=[normalize(n) for n in names if n]
            if q in aliases:exact.append(poi)
            elif any(a and (a in q or q in a) for a in aliases):partial.append(poi)
        found=exact or partial
        regions={normalize(n.get('region','')) for n in self.graph.nodes.values() if n.get('region')}
        mentioned=[region for region in regions if region and region in q]
        if mentioned:
            found=[p for p in found if any(region in normalize(self.graph.nodes[p['node_id']].get('region','')) for region in mentioned)]
        if len(found)>1:raise NavigationError('目的地不唯一，请补充区域或从列表选择：'+'、'.join(p['name'] for p in found))
        if not found:raise NavigationError('未找到该目的地。请使用已设置的名称或别名，不会自动虚构地点')
        return found[0]
