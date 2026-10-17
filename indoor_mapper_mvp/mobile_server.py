"""LAN mobile client for the existing Windows localization engine. No cloud."""
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
import argparse,json,secrets,threading,socket,time,io,uuid,webbrowser,ssl
from PIL import Image,ImageOps
from mapper.engine import BASE,Runner,localize,open_project
from mapper.navigation import load_layout,mapped_pose,reference_matches,route_to
from mapper.visual_nav import NavigationController,NavigationError
from mapper.visual_nav.authoring import reference_catalog,save_configuration,bootstrap,extend_recorded_coverage

class MobileHTTPServer(ThreadingHTTPServer):
    allow_reuse_address=False
    daemon_threads=True

    def server_bind(self):
        # Windows SO_REUSEADDR permits two servers to bind the same port.
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()

def persistent_token(path):
    path=Path(path)
    if path.exists():
        token=json.loads(path.read_text(encoding='utf-8'))['token']
        if not isinstance(token,str) or len(token)<12:raise ValueError('手机访问码配置无效')
        return token
    token=secrets.token_urlsafe(12)
    try:
        with path.open('x',encoding='utf-8') as file:json.dump({'token':token},file)
    except FileExistsError:return persistent_token(path)
    return token

class MobileService:
    def __init__(self,project,token=None):
        self.project=Path(project).resolve();self.manifest=open_project(self.project)
        self.token=token or secrets.token_urlsafe(12);self.jobs={};self.lock=threading.Lock();self.latest=None
        self.uploads=self.project/'mobile_uploads';self.uploads.mkdir(exist_ok=True)
        self.navigation=NavigationController(self.project);self.pose_results={}

    def state(self):
        layout=load_layout(self.project)
        return dict(place=self.project.name,width=layout['width'],height=layout['height'],
            floorplan='/api/floorplan' if layout.get('image') else None,
            nodes=layout['nodes'],edges=layout['edges'],visual_navigation=self.navigation.catalog())

    def result_view(self,path):
        result=json.loads(Path(path).read_text(encoding='utf-8'))
        pose_key=Path(path).parent.name;self.pose_results[pose_key]=result
        if result.get('status')!='success':return dict(status='failed',pose_key=pose_key,reason=result.get('reason','照片未通过几何定位，请换一个角度重拍。'))
        refs=reference_matches(self.project,path,3);votes={}
        for ref in refs:
            if ref['region']:votes[ref['region']]=votes.get(ref['region'],0)+ref['shared_points']
        position=mapped_pose(self.project,result)
        quality=result['pose']['quality']
        return dict(status='success',pose_key=pose_key,position=position,region=max(votes,key=votes.get) if votes else '区域尚未命名',
            matched_points=quality['num_2d3d'],
            references=[dict(name=r['region'] or '参考画面',url='/api/reference?image='+r['image']) for r in refs],
            photo='/api/query?session='+Path(path).parent.name,
            note='位置与方向对应照片拍摄时刻，移动后请重新拍照。')

    def submit(self,data):
        if not self.lock.acquire(blocking=False):raise ValueError('电脑正在处理另一张照片，请稍后重试。')
        try:
            with Image.open(io.BytesIO(data)) as im:
                if im.width*im.height>40000000:raise ValueError('照片尺寸过大，请使用普通照片模式。')
                im=ImageOps.exif_transpose(im).convert('RGB')
                if min(im.size)<320:raise ValueError('照片分辨率过低，请使用原始照片。')
                im.thumbnail((2400,2400))
                job_id=uuid.uuid4().hex;path=self.uploads/f'{job_id}.jpg';im.save(path,quality=95)
            self.jobs[job_id]=dict(status='processing',stage='照片已收到，准备提取特征',started=time.time())
            threading.Thread(target=self.run,args=(job_id,path),daemon=True).start()
            return job_id
        except Exception:
            self.lock.release();raise

    def run(self,job_id,path):
        def log(text):
            # Only stage labels, never commands or private filesystem paths.
            if not text.startswith('>') and '启动' not in text:self.jobs[job_id]['stage']=text[:160]
        try:
            result=localize(self.project,path,Runner(log=log))
            view=self.result_view(Path(result['session'])/'result.json')
            self.jobs[job_id]=dict(status='done',result=view)
            self.latest=view
        except Exception as e:
            (self.uploads/f'{job_id}.error.txt').write_text(str(e),encoding='utf-8')
            self.jobs[job_id]=dict(status='done',result=dict(status='failed',reason='定位处理出错，未产生位置。请检查电脑上的手机服务日志，或重新拍摄清晰照片。'))
        finally:self.lock.release()

    def navigation_pose(self,job_id):
        view=self.jobs.get(job_id,{}).get('result')
        if not view:raise NavigationError('请先拍照完成定位，再开始导航')
        result=self.pose_results.get(view.get('pose_key'))
        if not result:raise NavigationError('该定位记录不可用，请重新拍照')
        return result,bool(view.get('historical'))

def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,data,content_type='application/json; charset=utf-8',code=200):
            if isinstance(data,dict):data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(code);self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
            self.end_headers();self.wfile.write(data)
        def authorized(self,query):
            token=self.headers.get('X-Access-Token') or query.get('token',[''])[0]
            return secrets.compare_digest(token,service.token)
        def file(self,path,root):
            path=Path(path).resolve();root=Path(root).resolve()
            if not path.is_relative_to(root) or not path.is_file():self.send({'error':'图片不存在'},code=404);return
            # Re-encode references to remove EXIF and keep phone transfers small.
            with Image.open(path) as im:
                im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((2000,2000))
                output=io.BytesIO();im.save(output,format='JPEG',quality=88)
            self.send(output.getvalue(),'image/jpeg')
        def do_GET(self):
            url=urlsplit(self.path);query=parse_qs(url.query)
            public_files={
                '/':('index.html','text/html; charset=utf-8'),
                '/mobile.js':('mobile.js','text/javascript; charset=utf-8'),
                '/mobile.css':('mobile.css','text/css; charset=utf-8'),
                '/app.webmanifest':('app.webmanifest','application/manifest+json; charset=utf-8'),
                '/sw.js':('sw.js','text/javascript; charset=utf-8'),
                '/icons/app.svg':('icons/app.svg','image/svg+xml'),
                '/icons/app-192.png':('icons/app-192.png','image/png'),
                '/icons/app-512.png':('icons/app-512.png','image/png')}
            for name in ('navigation.js','navigation.css','navigation-admin.html','navigation-admin.js'):
                if name.startswith('navigation-admin') and self.client_address[0] not in ('127.0.0.1','::1'):continue
                kind='text/html; charset=utf-8' if name.endswith('.html') else 'text/css; charset=utf-8' if name.endswith('.css') else 'text/javascript; charset=utf-8'
                public_files['/'+name]=(name,kind)
            if url.path in public_files:
                name,kind=public_files[url.path]
                self.send((BASE/'mobile'/name).read_bytes(),kind);return
            if not self.authorized(query):self.send({'error':'访问码无效，请使用电脑显示的完整手机链接。'},code=401);return
            try:
                if url.path=='/api/state':self.send(service.state())
                elif url.path=='/api/job':
                    job=service.jobs.get(query.get('id',[''])[0]);self.send(job or {'error':'任务不存在'},code=200 if job else 404)
                elif url.path=='/api/history':
                    session=query.get('session',[''])[0]
                    if session and any(c not in '0123456789_abcdef' for c in session):raise ValueError('历史定位编号无效')
                    files=[service.project/'queries'/session/'result.json'] if session else sorted((service.project/'queries').glob('*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                    if not files:raise ValueError('还没有历史定位')
                    job_id=uuid.uuid4().hex;view=service.result_view(files[0]);view['historical']=True
                    job=dict(status='done',result=view);service.jobs[job_id]=job
                    self.send(dict(id=job_id,**job))
                elif url.path=='/api/navigation/catalog':self.send(service.navigation.catalog())
                elif url.path=='/api/navigation/diagnose':
                    result,_=service.navigation_pose(query.get('job_id',[''])[0])
                    self.send(service.navigation.diagnose(result))
                elif url.path=='/api/navigation/session':self.send(service.navigation.view(query.get('id',[''])[0]))
                elif url.path=='/api/navigation/image':
                    path=service.navigation.image_path(query.get('id',[''])[0],query.get('revision',[''])[0],query.get('step',[''])[0])
                    self.file(path,service.project/'navigation_runs')
                elif url.path=='/api/navigation/config':
                    if self.client_address[0] not in ('127.0.0.1','::1'):self.send({'error':'导航配置仅允许在电脑本机操作'},code=403);return
                    data=bootstrap(service.project)
                    self.send(dict(graph=data,references=reference_catalog(service.project,data['model_id'])))
                elif url.path=='/api/floorplan':
                    image=load_layout(service.project).get('image')
                    if not image:self.send({'error':'未导入底图'},code=404)
                    else:self.file(service.project/image,service.project/'assets')
                elif url.path=='/api/reference':self.file(service.project/'images'/query.get('image',[''])[0],service.project/'images')
                elif url.path=='/api/query':
                    session=query.get('session',[''])[0]
                    if not session or any(c not in '0123456789_abcdef' for c in session):raise ValueError('照片编号无效')
                    folder=service.project/'queries'/session/'images';files=list(folder.glob('*.jpg'))
                    if not files:raise ValueError('查询照片不存在')
                    self.file(files[0],folder)
                else:self.send({'error':'接口不存在'},code=404)
            except NavigationError as e:self.send({'error':str(e)},code=400)
            except Exception:self.send({'error':'无法读取地图或照片，请检查电脑上的地图设置。'},code=400)
        def do_POST(self):
            url=urlsplit(self.path)
            if not self.authorized(parse_qs(url.query)):self.send({'error':'访问码无效'},code=401);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16000000:self.send({'error':'照片为空或超过16MB，请使用普通照片模式。'},code=413);return
                data=self.rfile.read(size)
                if url.path=='/api/localize':self.send({'id':service.submit(data)},code=202)
                elif url.path=='/api/navigation/start':
                    body=json.loads(data);result,historical=service.navigation_pose(body['job_id'])
                    confirmed=body.get('confirmed_node')
                    if confirmed and body.get('confirm_direct_access') is not True:raise NavigationError('请先确认现场可直接步行到该参考站位')
                    if confirmed:self.send(service.navigation.start(result,body['destination'],historical or bool(body.get('historical')),confirmed_node=confirmed))
                    else:self.send(service.navigation.start(result,body['destination'],historical or bool(body.get('historical'))))
                elif url.path=='/api/navigation/update':
                    body=json.loads(data);result,historical=service.navigation_pose(body['job_id'])
                    self.send(service.navigation.update(body['id'],result,historical or bool(body.get('historical'))))
                elif url.path=='/api/navigation/config':
                    if self.client_address[0] not in ('127.0.0.1','::1'):self.send({'error':'导航配置仅允许在电脑本机操作'},code=403);return
                    self.send({'graph':save_configuration(service.project,json.loads(data))})
                elif url.path=='/api/navigation/extend':
                    if self.client_address[0] not in ('127.0.0.1','::1'):self.send({'error':'导航配置仅允许在电脑本机操作'},code=403);return
                    self.send({'graph':extend_recorded_coverage(service.project)})
                elif url.path=='/api/route':
                    body=json.loads(data);view=service.jobs.get(body.get('job_id'),{}).get('result')
                    if not view or view.get('status')!='success' or view['position']['status']!='ready':
                        raise ValueError('当前位置尚为估计或没有通过标定，可查看地点与已标通路，暂不能生成从当前位置出发的路线。')
                    self.send(route_to(load_layout(service.project),view['position']['uv'],body['destination']))
                else:self.send({'error':'接口不存在'},code=404)
            except ValueError as e:self.send({'error':str(e)},code=400)
            except Exception:self.send({'error':'照片格式不支持或请求无效。请使用 JPG、PNG 或普通照片模式。'},code=400)
    return Handler

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project');parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',default='0.0.0.0');parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--cert',help='PEM certificate trusted by the phone')
    parser.add_argument('--key',help='PEM private key for the certificate');args=parser.parse_args()
    if bool(args.cert)!=bool(args.key):parser.error('--cert 和 --key 必须同时提供')
    tls=None
    if args.cert:
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:tls.load_cert_chain(args.cert,args.key)
        except (OSError,ssl.SSLError) as e:parser.error('无法加载 HTTPS 证书或私钥：'+str(e))
    project=args.project or json.loads((BASE/'ui_state.json').read_text(encoding='utf-8'))['project']
    service=MobileService(project,persistent_token(BASE/'mobile_access.json'))
    try:server=MobileHTTPServer((args.host,args.port),make_handler(service))
    except OSError as e:
        print(f'手机服务端口 {args.port} 已被占用，未启动第二份服务。请使用已打开的手机服务窗口中的完整链接。\n如需更换地图，请先关闭旧服务再重新启动。',flush=True)
        if not args.no_browser:input('按回车关闭此窗口。')
        return
    if tls:server.socket=tls.wrap_socket(server.socket,server_side=True)
    scheme='https' if tls else 'http'
    urls=[f'{scheme}://127.0.0.1:{args.port}/?token={service.token}']
    for ip in sorted(set(socket.gethostbyname_ex(socket.gethostname())[2])):
        if not ip.startswith('127.'):urls.append(f'{scheme}://{ip}:{args.port}/?token={service.token}')
    info=dict(project=str(service.project),urls=urls,started=time.strftime('%Y-%m-%d %H:%M:%S'))
    (BASE/'mobile_connection.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print('电脑预览及手机链接（手机与电脑使用同一 Wi-Fi）：',flush=True)
    for url in urls:print(url,flush=True)
    print('关闭本窗口即可停止服务。手机上传照片仅在这台电脑处理。',flush=True)
    if not args.no_browser:webbrowser.open(urls[0])
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
