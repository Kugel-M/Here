"""GUI by default; command line entry points for repeatable pipeline tests."""
from pathlib import Path
import argparse
import json
import sys
from mapper.engine import Runner, check_environment, reconstruct, localize, import_existing


def main():
    parser=argparse.ArgumentParser(description='室内三维重建与视觉定位 MVP')
    sub=parser.add_subparsers(dest='command')
    sub.add_parser('doctor')
    p=sub.add_parser('reconstruct');p.add_argument('--video',required=True);p.add_argument('--project',required=True)
    p.add_argument('--fps',type=float,default=2.);p.add_argument('--max-frames',type=int,default=400);p.add_argument('--cpu',action='store_true')
    p=sub.add_parser('localize');p.add_argument('--project',required=True);p.add_argument('--photo',required=True)
    p.add_argument('--model',default='auto');p.add_argument('--cpu',action='store_true')
    p=sub.add_parser('import-existing');p.add_argument('--source',required=True);p.add_argument('--project',required=True)
    p=sub.add_parser('view');p.add_argument('--project',required=True);p.add_argument('--model',default='0')
    p.add_argument('--result');p.add_argument('--screenshot');p.add_argument('--self-check',action='store_true')
    args=parser.parse_args();runner=Runner(log=lambda s:print(s,flush=True))
    if not args.command:
        from mapper.ui import launch
        launch();return 0
    if args.command=='doctor':out=check_environment()
    elif args.command=='reconstruct':out=reconstruct(args.video,args.project,runner,args.fps,args.max_frames,not args.cpu)
    elif args.command=='localize':
        out=localize(args.project,args.photo,runner,args.model,not args.cpu)
        print(json.dumps(out,ensure_ascii=False,indent=2));return 0 if out['status']=='success' else 2
    elif args.command=='import-existing':out=import_existing(args.source,args.project,runner)
    elif args.command=='view':
        from mapper.viewer import show
        show(args.project,args.model,args.result,args.screenshot,args.self_check);return 0
    print(json.dumps(out,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:
        print('错误：'+str(e),file=sys.stderr)
        sys.exit(1)
