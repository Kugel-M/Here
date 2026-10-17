import unittest,tempfile,json,threading,io,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from PIL import Image
from mobile_server import MobileService,make_handler,MobileHTTPServer,persistent_token
from mapper.navigation import empty_layout

class MobileTests(unittest.TestCase):
    def setUp(self):
        folder=Path(__file__).parent/'tmp';folder.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=folder);self.project=Path(self.tmp.name)
        (self.project/'project.json').write_text(json.dumps({'status':'ready','models':[]}),encoding='utf-8')
        (self.project/'images').mkdir();Image.new('RGB',(400,400),'white').save(self.project/'images/ref.jpg')
        (self.project/'site_map.json').write_text(json.dumps(empty_layout()),encoding='utf-8')
        self.service=MobileService(self.project)
        self.server=MobileHTTPServer(('127.0.0.1',0),make_handler(self.service))
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def request(self,path,data=None,auth=True):
        req=Request(self.url+path,data=data,headers={'X-Access-Token':self.service.token} if auth else {})
        try:
            with urlopen(req,timeout=10) as response:return response.status,response.read()
        except HTTPError as e:return e.code,e.read()
    def test_auth_and_scoped_files(self):
        self.assertEqual(self.request('/api/state',auth=False)[0],401)
        status,body=self.request('/api/state');self.assertEqual(status,200)
        self.assertNotIn(str(self.project),body.decode())
        self.assertEqual(self.request('/api/reference?image=../project.json')[0],404)
        self.assertEqual(self.request('/api/reference?image=ref.jpg')[0],200)
        self.assertEqual(self.request('/api/state?token='+self.service.token,auth=False)[0],200)
    def test_second_server_cannot_share_port(self):
        with self.assertRaises(OSError):
            MobileHTTPServer(('127.0.0.1',self.server.server_port),make_handler(self.service))
    def test_access_code_survives_restart(self):
        path=self.project/'access.json'
        first=persistent_token(path)
        self.assertEqual(first,persistent_token(path))
        self.assertEqual(MobileService(self.project,first).token,first)
    def test_app_shell_is_public_but_map_requires_access_code(self):
        status,body=self.request('/app.webmanifest',auth=False)
        self.assertEqual(status,200)
        manifest=json.loads(body)
        self.assertEqual(manifest['display'],'standalone')
        self.assertNotIn('token',manifest['start_url'])
        for icon in manifest['icons']:
            self.assertEqual(self.request(icon['src'],auth=False)[0],200)
        self.assertEqual(self.request('/sw.js',auth=False)[0],200)
        self.assertEqual(self.request('/api/state',auth=False)[0],401)
    def test_navigation_requires_existing_localization_job(self):
        status,body=self.request('/api/navigation/catalog')
        self.assertEqual(status,200);self.assertFalse(json.loads(body)['available'])
        status,body=self.request('/api/navigation/start',json.dumps({'job_id':'not_a_real_job','destination':'出口','xyz':[0,0,0]}).encode())
        self.assertEqual(status,400)
        self.assertFalse(self.service.navigation.sessions)
    def test_recalled_pose_stays_marked_as_history(self):
        self.service.pose_results['TEST_ONLY']={'status':'success'}
        self.service.jobs['known']={'result':{'pose_key':'TEST_ONLY','historical':False}}
        with patch.object(self.service.navigation,'start',return_value={'status':'TEST_ONLY'}) as start:
            self.assertEqual(self.request('/api/navigation/start',json.dumps({'job_id':'known','destination':'出口','historical':True}).encode())[0],200)
            self.assertTrue(start.call_args.args[2])
            self.service.jobs['known']['result']['historical']=True
            self.request('/api/navigation/start',json.dumps({'job_id':'known','destination':'出口','historical':False}).encode())
            self.assertTrue(start.call_args.args[2])
    def test_manual_connector_requires_explicit_confirmation(self):
        self.service.pose_results['TEST_ONLY']={'status':'success'}
        self.service.jobs['known']={'result':{'pose_key':'TEST_ONLY'}}
        body={'job_id':'known','destination':'出口','confirmed_node':'B'}
        with patch.object(self.service.navigation,'start',return_value={'status':'TEST_ONLY'}) as start:
            self.assertEqual(self.request('/api/navigation/start',json.dumps(body).encode())[0],400)
            start.assert_not_called()
            body['confirm_direct_access']=True
            self.assertEqual(self.request('/api/navigation/start',json.dumps(body).encode())[0],200)
            self.assertEqual(start.call_args.kwargs['confirmed_node'],'B')
    def test_invalid_image_and_failed_location_have_no_coordinates(self):
        self.assertEqual(self.request('/api/localize',b'not an image')[0],400)
        self.assertFalse(self.service.lock.locked())
        event=threading.Event()
        def fake_failure(*args,**kwargs):
            event.wait(5);folder=self.project/'queries/TEST_ONLY';folder.mkdir(parents=True)
            (folder/'result.json').write_text(json.dumps({'status':'failed','reason':'特征不足'}),encoding='utf-8')
            return {'status':'failed','session':str(folder)}
        out=io.BytesIO();Image.new('RGB',(400,400),'white').save(out,format='JPEG')
        with patch('mobile_server.localize',side_effect=fake_failure):
            status,body=self.request('/api/localize',out.getvalue());self.assertEqual(status,202)
            job_id=json.loads(body)['id']
            self.assertEqual(self.request('/api/localize',out.getvalue())[0],400)
            event.set()
            for _ in range(100):
                if self.service.jobs[job_id]['status']=='done':break
                time.sleep(.02)
            result=json.loads(self.request('/api/job?id='+job_id)[1])['result']
            self.assertEqual(result['status'],'failed');self.assertNotIn('position',result)
    def test_route_uses_requested_job_and_rejects_estimated_positions(self):
        layout=empty_layout();layout['nodes']=[{'id':'a','name':'入口','uv':[0,0]},{'id':'b','name':'目标','uv':[100,0]}];layout['edges']=[['a','b']]
        (self.project/'site_map.json').write_text(json.dumps(layout),encoding='utf-8')
        self.service.jobs={'good':{'result':{'status':'success','position':{'status':'ready','uv':[20,0]}}},
                           'estimate':{'result':{'status':'success','position':{'status':'approximate','uv':[20,0]}}}}
        self.assertEqual(self.request('/api/route',json.dumps({'job_id':'estimate','destination':'b'}).encode())[0],400)
        status,body=self.request('/api/route',json.dumps({'job_id':'good','destination':'b'}).encode())
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['length_pixels'],80)

if __name__=='__main__':unittest.main()
