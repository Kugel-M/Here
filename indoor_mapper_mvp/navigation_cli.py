"""Navigation CLI; consumes existing result.json without running reconstruction."""
from pathlib import Path
import argparse,json
from mapper.visual_nav import NavigationController
from mapper.visual_nav.authoring import bootstrap

def main():
    p=argparse.ArgumentParser(description='室内视觉导航：读取已有定位结果')
    p.add_argument('--project',required=True);p.add_argument('--bootstrap',action='store_true')
    p.add_argument('--result');p.add_argument('--destination');args=p.parse_args()
    if args.bootstrap:
        data=bootstrap(args.project);print('已准备真实参考帧导航候选图，共',len(data['nodes']),'个节点；待现场核实')
    if args.result:
        if not args.destination:p.error('--result 需要 --destination')
        result=json.loads(Path(args.result).read_text(encoding='utf-8'))
        out=NavigationController(args.project).start(result,args.destination,historical=True)
        print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
