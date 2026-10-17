import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from mapper.navigation import (fit_calibration,calibrated_position,route_to,mapped_pose,empty_layout,
    stretch_diagnostic,set_floorplan,save_layout,restore_annotations,estimate_world_up,
    fit_heading,heading_position)
from PIL import Image
from mapper.engine import PipelineError


class MapTests(unittest.TestCase):
    def test_known_bearing_transfers_rotations_to_other_photos(self):
        cal=fit_heading([0,0,1],[0,-1,0],[-1,-1],'s',{'type':'test'})
        np.testing.assert_allclose(heading_position(cal,[0,0,1]),[-2**-.5,-2**-.5])
        # Another photo turned right by 90 degrees must face NE, not fixed NW.
        np.testing.assert_allclose(heading_position(cal,[1,0,0]),[2**-.5,-2**-.5])
        self.assertIsNone(heading_position(cal,[0,-1,0]))
        with self.assertRaises(PipelineError):fit_heading([0,-1,0],[0,-1,0],[-1,-1],'s',{})

    @patch('mapper.navigation.model_signature',return_value='s')
    def test_direction_only_without_a_position_calibration(self,mock):
        layout=empty_layout();layout['heading_calibrations']['0']=fit_heading([0,0,1],[0,-1,0],[-1,-1],'s',{})
        result={'status':'success','pose':{'model_id':'0','model_signature':'s','forward_world':[1,0,0]}}
        position=mapped_pose('project',result,layout)
        self.assertEqual(position['status'],'direction_only');self.assertNotIn('uv',position)
        np.testing.assert_allclose(position['heading'],[2**-.5,-2**-.5])

    @patch('mapper.navigation.model_signature',return_value='s')
    def test_legacy_position_is_labelled_estimated_when_heading_is_calibrated(self,mock):
        layout=empty_layout();xyz=np.array([[0,1,0],[4,1,0],[0,1,3],[4,1,3]],float)
        layout['calibrations']['0']=fit_calibration(xyz,xyz[:,[0,2]]*100+[100,100],'s')
        layout['heading_calibrations']['0']=fit_heading([0,0,1],[0,-1,0],[-1,-1],'s',{})
        result={'status':'success','pose':{'model_id':'0','model_signature':'s','xyz':[1,1,1],'forward_world':[0,0,1]}}
        position=mapped_pose('project',result,layout)
        self.assertEqual(position['status'],'approximate');self.assertEqual(position['heading_source'],'known_reference')
        np.testing.assert_allclose(position['uv'],[200,200]);np.testing.assert_allclose(position['heading'],[-2**-.5,-2**-.5])

    def test_floor_handedness_and_compass_directions(self):
        xyz=np.array([[0,1,0],[4,1,0],[0,1,3],[4,1,3]],dtype=float)
        uv=xyz[:,[0,2]]*[100,-100]+[100,400]
        cal=fit_calibration(xyz,uv,'s',world_up=[0,-1,0])
        for x,z in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1)]:
            _,heading=calibrated_position(cal,[1,1,1],[x,0,z])
            expected=np.array([x,-z])/np.hypot(x,z)
            np.testing.assert_allclose(heading,expected,atol=1e-9)
        self.assertEqual(cal['orientation_version'],1)
        # These coordinates would fit perfectly ONLY by accepting a mirror.
        mirrored=xyz[:,[0,2]]*[100,100]+[100,100]
        with self.assertRaisesRegex(PipelineError,'左右镜像'):
            fit_calibration(xyz,mirrored,'s',world_up=[0,-1,0])

    def test_upright_reference_assumption_is_checked(self):
        refs=[{'R':np.eye(3)} for _ in range(3)]
        np.testing.assert_allclose(estimate_world_up(refs),[0,-1,0])
        refs[-1]={'R':np.diag([-1,-1,1])}
        with self.assertRaises(PipelineError):estimate_world_up(refs)

    @patch('mapper.navigation.model_signature',return_value='current')
    def test_legacy_calibration_without_mirror_check_is_not_displayed(self,mock):
        layout=empty_layout();layout['calibrations']['0']={'model_signature':'current'}
        result=mapped_pose('project',{'status':'success','pose':{'model_id':'0','model_signature':'current'}},layout)
        self.assertEqual(result['status'],'uncalibrated');self.assertNotIn('uv',result)
        self.assertIn('左右镜像',result['reason'])

    def test_floorplan_replacement_keeps_names_and_optional_coordinates(self):
        folder=Path(__file__).parent/'tmp';folder.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            project=Path(tmp);source=project/'input.png';Image.new('RGB',(600,400)).save(source)
            layout=empty_layout();layout['reference_labels']={'0':{'frame.jpg':'入户门'}}
            layout['anchors']={'0':[{'image':'frame.jpg','uv':[300,200]}]}
            layout['nodes']=[{'id':'a','name':'入口','uv':[600,400]}];layout['calibrations']={'0':{'old':True}}
            layout['pixels_per_meter']=100;save_layout(project,layout)
            new=set_floorplan(project,source,True)
            self.assertEqual(new['reference_labels'],layout['reference_labels'])
            self.assertEqual(new['anchors']['0'][0]['uv'],[150,100])
            self.assertEqual(new['nodes'][0]['uv'],[300,200]);self.assertEqual(new['pixels_per_meter'],50)
            self.assertEqual(new['calibrations'],{})
            new=set_floorplan(project,source,False)
            self.assertEqual(new['reference_labels'],layout['reference_labels']);self.assertEqual(new['anchors'],{})
            self.assertEqual(len(list((project/'site_map_backups').glob('*.json'))),2)

    def test_restore_names_does_not_overwrite_current_and_migrates_only_on_request(self):
        folder=Path(__file__).parent/'tmp';folder.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            project=Path(tmp);old=empty_layout()
            old['reference_labels']={'0':{'a':'旧名','b':'恢复名'}};old['anchors']={'0':[{'image':'a','uv':[300,200]}]}
            save_layout(project,old);backup=project/'old.json';backup.write_bytes((project/'site_map.json').read_bytes())
            current=empty_layout();current.update(width=600,height=800)
            current['reference_labels']={'0':{'a':'新名'}};save_layout(project,current)
            new,count=restore_annotations(project,backup)
            self.assertEqual(count,1);self.assertEqual(new['reference_labels']['0'],{'a':'新名','b':'恢复名'})
            self.assertEqual(new['anchors'],{})
            new,count=restore_annotations(project,backup,True)
            self.assertEqual(count,0);self.assertEqual(new['anchors']['0'][0]['uv'],[150,200])

    def test_stretch_diagnostic_requires_evidence(self):
        xy=np.array([[0,0],[3,0],[0,4],[3,4],[1,2],[2,3],[1,3]],dtype=float)
        xyz=np.column_stack((xy,np.zeros(len(xy))))
        angle=.4;r=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        uv=(xy@r)*[200,100]+[400,400]
        message=stretch_diagnostic(xyz,uv)
        self.assertIn('宽度调为原来的 50.0%',message)
        self.assertIn('至少需要6个',stretch_diagnostic(xyz[:4],uv[:4]))
        bad=uv.copy();bad[-1]+=[500,-350]
        self.assertIn('暂不建议压缩',stretch_diagnostic(xyz,bad))
        shear=xy@np.array([[200,100],[0,100]])+[400,400]
        self.assertIn('暂不建议压缩',stretch_diagnostic(xyz,shear))

    def test_tilted_plane_position_and_heading(self):
        xy=np.array([[0.,0.],[4,0],[0,3],[4,3]])
        e1=np.array([1.,0.,1.])/np.sqrt(2);e2=np.array([0.,1.,0.]);basis=np.column_stack((e1,e2))
        origin=np.array([8.,-3.,12.]);xyz=xy@basis.T+origin
        r=np.array([[0.,1.],[1.,0.]]) # includes image Y-down reflection
        uv=xy@r*50+np.array([100,200])
        cal=fit_calibration(xyz,uv,'signature',max_error=1.)
        pos,heading=calibrated_position(cal,np.array([2.,1.])@basis.T+origin,e1)
        np.testing.assert_allclose(pos,[150,300],atol=1e-8)
        np.testing.assert_allclose(heading,[0,1],atol=1e-8)
        _,vertical=calibrated_position(cal,xyz[0],np.cross(e1,e2))
        self.assertIsNone(vertical)

    def test_collinear_controls_rejected(self):
        with self.assertRaises(PipelineError):fit_calibration([[0,0,0],[1,0,0],[2,0,0]],[[0,0],[100,0],[200,0]],'s')

    def test_inconsistent_controls_rejected(self):
        with self.assertRaisesRegex(PipelineError,'不代表该站位标错'):fit_calibration([[0,0,0],[1,0,0],[0,1,0],[1,1,0]],[[0,0],[100,0],[0,100],[250,120]],'s',max_error=1.)

    def test_route_stays_on_annotated_edges_and_reports_units(self):
        layout=empty_layout();layout['pixels_per_meter']=10
        layout['nodes']=[dict(id='a',name='入口',uv=[0,0]),dict(id='b',name='转角',uv=[100,0]),dict(id='c',name='目标',uv=[100,100])]
        layout['edges']=[['a','b'],['b','c']]
        route=route_to(layout,[40,5],'c')
        np.testing.assert_allclose(route['points'],[[40,0],[100,0],[100,100]])
        self.assertEqual(route['length_meters'],16)
        self.assertNotEqual(route['points'][0],[40,5]) # no invented cross-wall connector
        with self.assertRaises(PipelineError):route_to(layout,[500,500],'c')
        layout['edges']=[['a','b']]
        with self.assertRaises(PipelineError):route_to(layout,[40,5],'c')

    def test_failed_pose_has_no_map_coordinates(self):
        result=mapped_pose('missing-project',{'status':'failed'},empty_layout())
        self.assertEqual(result['status'],'unavailable');self.assertNotIn('uv',result)

    @patch('mapper.navigation.model_signature',return_value='current')
    def test_stale_calibration_has_no_map_coordinates(self,mock):
        layout=empty_layout();layout['calibrations']['0']={'model_signature':'old'}
        result=mapped_pose('project',{'status':'success','pose':{'model_id':'0','model_signature':'current'}},layout)
        self.assertEqual(result['status'],'uncalibrated');self.assertNotIn('uv',result)


if __name__=='__main__':unittest.main()
