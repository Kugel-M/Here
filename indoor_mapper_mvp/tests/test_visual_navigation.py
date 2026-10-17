import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from mapper.visual_nav import NavigationGraph,NavigationError,POIManager,RoutePlanner,NavigationInstructionGenerator,NavigationController,ArrowOverlayRenderer
from mapper.visual_nav.instructions import turn
from mapper.visual_nav.authoring import save_configuration,bootstrap,extend_recorded_coverage


def fixture():
    nodes=[dict(node_id=n,name=name,region=region,xyz=p,floor='1',type='poi',references=[]) for n,name,region,p in [
        ('A','入口','A区',[0,0,0]),('B','路口','B区',[4,0,0]),('C','奶茶店','C区',[4,3,0]),('D','支路','B区',[2,-3,0])]]
    return dict(schema_version=1,model_id='0',model_signature='TEST_ONLY',world_up=[0,0,1],meters_per_unit=2,
        field_verified=True,snap_radius_units=.4,arrival_radius_units=.15,nodes=nodes,
        edges=[{'from':'A','to':'B'},{'from':'B','to':'C'},{'from':'A','to':'D'},{'from':'D','to':'B'}],
        pois=[dict(node_id='C',name='C区奶茶店',aliases=['奶茶店','喝奶茶','Milk Tea']),dict(node_id='A',name='A区出口',aliases=['出口'])])


def pose(xyz=(.1,0,0),forward=(1,0,0)):
    return dict(xyz=np.array(xyz,dtype=float),forward=np.array(forward,dtype=float),floor=None)


def result(xyz=(.1,0,0)):
    return dict(status='success',pose=dict(xyz=list(xyz),forward_world=[1,0,0],model_id='0',model_signature='TEST_ONLY'))


class VisualNavigationTests(unittest.TestCase):
    def test_walking_height_is_not_horizontal_route_error(self):
        g=NavigationGraph(fixture());p=pose((2,.3,.3));snap=g.snap(p['xyz'])
        self.assertGreater(snap['distance'],g.snap_radius)
        self.assertLess(snap['horizontal'],g.snap_radius)
        route=RoutePlanner(g).plan(p,'C')
        self.assertEqual(route['segments'][0]['polyline'][0],p['xyz'].tolist())
        self.assertAlmostEqual(route['total_units'],np.sqrt(.18)+5)
        with self.assertRaises(NavigationError):g.snap([2,0,.5])
        with self.assertRaises(NavigationError):g.snap([2,.5,0])
    def test_confirmed_access_keeps_real_pose_and_is_not_reused(self):
        g=NavigationGraph(fixture());p=pose((3.4,.6,0))
        with self.assertRaises(NavigationError):RoutePlanner(g).plan(p,'C')
        route=RoutePlanner(g).plan(p,'C',confirmed_node='B')
        self.assertEqual(route['segments'][0]['polyline'][0],[3.4,.6,0])
        self.assertEqual(route['connector_method'],'user_confirmed')
        self.assertAlmostEqual(route['total_units'],np.hypot(.6,.6)+3)
        with self.assertRaises(NavigationError):g.confirm_connector([100,100,0],'B')
        with self.assertRaises(NavigationError):g.confirm_connector([4,0,0],'B','2')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,patch('mapper.visual_nav.controller.NavigationGraph.load',return_value=g):
            c=NavigationController(folder);s=c.start(result((3.4,.6,0)),'奶茶店',confirmed_node='B')
            self.assertEqual(c.update(s['id'],result((3.4,.6,0)))['status'],'paused')
    def test_diagnostics_show_limited_actionable_connections(self):
        g=NavigationGraph(fixture());d=g.diagnose([3.4,.6,0])
        self.assertEqual(d['status'],'needs_connection')
        self.assertEqual(d['suggestions'][0]['node_id'],'B')
        self.assertEqual(d['limits']['horizontal'],.4)
        self.assertTrue(d['lines'])
        self.assertFalse(g.diagnose([100,100,0])['suggestions'])
    def test_full_video_coverage_and_preserved_existing_labels(self):
        refs=[dict(image=f'images/frame_{i:06d}.jpg',name=f'frame_{i:06d}.jpg',label='TEST_ONLY',xyz=[i*.1,0,0],forward_world=[1,0,0]) for i in range(142)]
        layout={'heading_calibrations':{'0':{'world_up':[0,0,1],'model_signature':'TEST_ONLY'}}}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,patch('mapper.visual_nav.authoring.model_signature',return_value='TEST_ONLY'),patch('mapper.visual_nav.graph.model_signature',return_value='TEST_ONLY'),patch('mapper.visual_nav.authoring.load_layout',return_value=layout):
            p=Path(folder);(p/'sparse/0').mkdir(parents=True)
            with patch('mapper.visual_nav.authoring.reference_catalog',return_value=refs):
                full=bootstrap(p)
                self.assertEqual(full['nodes'][-1]['references'][0]['image'],refs[-1]['image'])
                self.assertEqual(sum(len(e['polyline'])-1 for e in full['edges']),141)
            # Recreate the old truncated candidate graph only in this temporary test project.
            (p/'visual_navigation.json').unlink()
            with patch('mapper.visual_nav.authoring.reference_catalog',return_value=refs[:80]):old=bootstrap(p)
            old['nodes'][0]['name']='USER_LABEL_TEST_ONLY';old['meters_per_unit']=2
            NavigationGraph(old).save(p)
            with patch('mapper.visual_nav.authoring.reference_catalog',return_value=refs):
                extended=extend_recorded_coverage(p)
                self.assertEqual(extended['nodes'][:8],old['nodes'])
                self.assertEqual(extended['meters_per_unit'],2)
                self.assertEqual(extended['coverage']['last_image'],refs[-1]['image'])
                count=len(extended['nodes']);self.assertEqual(len(extend_recorded_coverage(p)['nodes']),count)
    def test_left_right_uturn_from_world_vectors(self):
        self.assertEqual(turn([1,0,0],[0,1,0],[0,0,1])[0],'left')
        self.assertEqual(turn([1,0,0],[0,-1,0],[0,0,1])[0],'right')
        self.assertEqual(turn([1,0,0],[-1,0,0],[0,0,1])[0],'uturn')
        self.assertEqual(turn([1,0,0],[1,.01,0],[0,0,1])[0],'straight')
    def test_poi_phrases_and_ambiguity(self):
        g=NavigationGraph(fixture());m=POIManager(g)
        for name in ['我要去C区的奶茶店','Milk Tea','喝奶茶','奶茶店']:
            self.assertEqual(m.resolve(name)['node_id'],'C')
        with self.assertRaises(NavigationError):m.resolve('火星基地')
        data=fixture();data['pois'].append(dict(node_id='D',name='另一奶茶店',aliases=['奶茶店']))
        with self.assertRaises(NavigationError):POIManager(NavigationGraph(data)).resolve('奶茶店')
    def test_astar_and_metric_distance(self):
        g=NavigationGraph(fixture());route=RoutePlanner(g).plan(pose(),'C')
        self.assertEqual(route['node_ids'],['B','C']);self.assertAlmostEqual(route['total_units'],6.9)
        self.assertAlmostEqual(g.distance(route['total_units'])['distance_m'],13.8)
        steps=NavigationInstructionGenerator(g).generate(route,pose())
        self.assertEqual(steps[0]['action'],'straight');self.assertEqual(steps[1]['action'],'left')
        self.assertEqual(steps[-1]['action'],'arrive')
    def test_blocked_and_one_way_edges(self):
        data=fixture();data['edges'][0]['enabled']=False
        route=RoutePlanner(NavigationGraph(data)).plan(pose((0,0,0)),'C')
        self.assertIn('D',route['node_ids'])
        data=fixture();data['edges']=[{'from':'A','to':'B','bidirectional':False}]
        with self.assertRaises(NavigationError):RoutePlanner(NavigationGraph(data)).plan(pose((2,0,0)),'A')
    def test_no_cross_wall_or_floor_snap(self):
        g=NavigationGraph(fixture())
        with self.assertRaises(NavigationError):g.snap([2,2,0])
        with self.assertRaises(NavigationError):g.snap([2,0,0],'2')
    def test_disconnected_close_corridors_are_ambiguous(self):
        d=fixture();d['nodes'] += [dict(node_id='E',name='隔壁',region='D',xyz=[0,.1,0],floor='1',references=[]),dict(node_id='F',name='隔壁尽头',region='D',xyz=[4,.1,0],floor='1',references=[])]
        d['edges'].append({'from':'E','to':'F'})
        with self.assertRaises(NavigationError):NavigationGraph(d).snap([2,.05,0])
    def test_multi_floor_requires_connector(self):
        d=fixture();d['nodes'][2]['floor']='2'
        with self.assertRaises(NavigationError):NavigationGraph(d)
        d['nodes'][2]['xyz']=[4,0,3];d['edges'][1]['kind']='stairs'
        g=NavigationGraph(d);route=RoutePlanner(g).plan(pose(),'C')
        steps=NavigationInstructionGenerator(g).generate(route,pose())
        self.assertEqual(steps[1]['action'],'up')
    def test_arbitrary_scale_and_pose_validation(self):
        d=fixture();d['meters_per_unit']=None;g=NavigationGraph(d)
        self.assertIsNone(g.distance(3)['distance_m'])
        r=result();r['pose']['model_signature']='OTHER'
        with self.assertRaises(NavigationError):g.pose(r)
        with self.assertRaises(NavigationError):g.pose({'status':'failed'})
        r=result();r['pose']['xyz']=[float('nan'),0,0]
        with self.assertRaises(NavigationError):g.pose(r)
    def test_relocalization_replans_and_does_not_fake_arrival(self):
        g=NavigationGraph(fixture())
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,patch('mapper.visual_nav.controller.NavigationGraph.load',return_value=g):
            c=NavigationController(folder);s=c.start(result(),'奶茶店')
            self.assertEqual(s['status'],'navigating')
            updated=c.update(s['id'],result((2,-3,0)));self.assertTrue(updated['replanned'])
            paused=c.update(s['id'],{'status':'failed'});self.assertEqual(paused['status'],'paused')
            arrived=c.update(s['id'],result((4,3,0)));self.assertEqual(arrived['status'],'arrived')
    def test_perspective_overlay_and_reference_orientation(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            p=Path(folder);Image.new('RGB',(600,800),'grey').save(p/'real.jpg')
            r=dict(xyz=[0,0,1],forward_world=[0,1,0])
            m=ArrowOverlayRenderer([0,0,1]).render(p/'real.jpg',r,[1,0,0],'straight',p/'overlay.jpg')
            self.assertEqual(m['photo_action'],'right');self.assertEqual(m['mode'],'perspective_schematic')
            self.assertTrue((p/'overlay.jpg').is_file())
            self.assertNotEqual((p/'real.jpg').read_bytes(),(p/'overlay.jpg').read_bytes())
    def test_configuration_scale_and_no_change_to_localization_map(self):
        g=NavigationGraph(fixture())
        refs=[dict(image='images/'+n+'.jpg',xyz=node['xyz']) for n,node in g.nodes.items()]
        nodes=[dict(node_id=n,name=node['name'],region=node['region'],floor='1',type='poi',image='images/'+n+'.jpg',aliases=[]) for n,node in g.nodes.items()]
        body=dict(nodes=nodes,edges=g.data['edges'],scale_measurement=dict(a='A',b='B',meters=8))
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,patch('mapper.visual_nav.authoring.NavigationGraph.load',return_value=g),patch('mapper.visual_nav.authoring.reference_catalog',return_value=refs):
            path=Path(folder)/'site_map.json';path.write_text('TEST_ONLY_SENTINEL')
            saved=save_configuration(folder,body)
            self.assertEqual(saved['meters_per_unit'],2)
            self.assertEqual(path.read_text(),'TEST_ONLY_SENTINEL')
            body['scale_measurement']['meters']=-1
            with self.assertRaises(NavigationError):save_configuration(folder,body)
    def test_first_arrow_uses_actual_localization_photo(self):
        g=NavigationGraph(fixture())
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,patch('mapper.visual_nav.controller.NavigationGraph.load',return_value=g):
            p=Path(folder).resolve();query=p/'queries/TEST_ONLY';(query/'images').mkdir(parents=True)
            Image.new('RGB',(600,800),'grey').save(query/'images/query.jpg')
            r=result();r['session']=str(query)
            r['pose'].update(rotation_camera_to_world=[[0,0,1],[-1,0,0],[0,-1,0]],camera=dict(model='PINHOLE',width=600,height=800,params=[400,400,300,400]))
            session=NavigationController(p).start(r,'奶茶店')
            step=session['steps'][0]
            self.assertEqual(step['reference']['source'],'current_photo')
            self.assertEqual(step['reference']['photo_action'],step['action'])
    def test_measured_ground_projection(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            p=Path(folder);Image.new('RGB',(600,800),'grey').save(p/'real.jpg')
            ref=dict(xyz=[0,0,1],forward_world=[0,1,0],rotation_camera_to_world=[[1,0,0],[0,0,1],[0,-1,0]],camera=dict(model='PINHOLE',width=600,height=800,params=[400,400,300,400]))
            m=ArrowOverlayRenderer([0,0,1]).render(p/'real.jpg',ref,[0,1,0],'straight',p/'overlay.jpg',ground=dict(origin=[0,2,0],arrow_length_units=1))
            self.assertEqual(m['mode'],'surveyed_ground_projection')

if __name__=='__main__':unittest.main()
