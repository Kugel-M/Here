import tempfile
import unittest
from pathlib import Path
import numpy as np
from mapper.model import rotation,load_model,pose_quality,pose_record


class PoseTests(unittest.TestCase):
    def test_world_camera_convention(self):
        r=rotation([np.sqrt(.5),0,np.sqrt(.5),0]);center=np.array([2.,3.,4.]);t=-r@center
        image={'R':r,'center':-r.T@t,'t':t,'q':np.array([np.sqrt(.5),0,np.sqrt(.5),0])}
        pose=pose_record(image,{},{});twc=np.array(pose['transform_camera_to_world'])
        np.testing.assert_allclose(twc[:3,3],center,atol=1e-12)
        np.testing.assert_allclose(twc[:3,:3]@r,np.eye(3),atol=1e-12)
        np.testing.assert_allclose(pose['forward_world'],[-1,0,0],atol=1e-12)

    def test_reprojection_quality(self):
        camera=dict(model='SIMPLE_RADIAL',width=640,height=480,params=[100,320,240,0])
        points={1:dict(xyz=np.array([0.,0.,2.])),2:dict(xyz=np.array([1.,0.,2.]))}
        image=dict(R=np.eye(3),t=np.zeros(3),xy=np.array([[320,240],[370,240],[1,1]]),point_ids=np.array([1,2,-1]),camera_id=1)
        quality=pose_quality(image,{1:camera},points)
        self.assertEqual(quality['num_2d3d'],2);self.assertAlmostEqual(quality['median_error_px'],0)
        self.assertEqual(quality['positive_depth_ratio'],1)

    def test_empty_observation_row_and_space_in_filename(self):
        temp_root=Path(__file__).parent/'tmp';temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            p=Path(tmp)
            (p/'cameras.txt').write_text('1 SIMPLE_RADIAL 640 480 100 320 240 0\n')
            (p/'images.txt').write_text('# header\n1 1 0 0 0 0 0 0 1 room one.jpg\n\n2 1 0 0 0 1 0 0 1 b.jpg\n320 240 8\n')
            (p/'points3D.txt').write_text('8 0 0 2 255 0 0 0.5 2 0\n')
            _,images,points=load_model(p)
            self.assertEqual(len(images),2);self.assertEqual(images[1]['name'],'room one.jpg')
            self.assertEqual(images[1]['xy'].shape,(0,2));self.assertEqual(images[2]['point_ids'][0],8)
            self.assertEqual(len(points),1)


if __name__=='__main__':unittest.main()
