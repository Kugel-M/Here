"""Open3D viewer in its own process so the desktop controls remain responsive."""
from pathlib import Path
import json
import numpy as np
from .engine import open_project, PipelineError, model_signature
from .model import load_model


def frustum(center, rcw, camera, size, color):
    import open3d as o3d
    p=camera['params'];kind=camera['model']
    if kind in {'SIMPLE_RADIAL','SIMPLE_PINHOLE','RADIAL'}:fx=fy=p[0];cx,cy=p[1:3]
    else:fx,fy,cx,cy=p[:4]
    w,h=camera['width'],camera['height']
    # Frusta describe orientation; distortion is omitted from display only.
    corners=np.array([[(u-cx)/fx*size,(v-cy)/fy*size,size] for u,v in [(0,0),(w,0),(w,h),(0,h)]])
    vertices=np.vstack([center,corners@rcw.T+center,center+rcw[:,2]*size*1.8])
    lines=[[0,1],[0,2],[0,3],[0,4],[1,2],[2,3],[3,4],[4,1],[0,5]]
    geom=o3d.geometry.LineSet(o3d.utility.Vector3dVector(vertices),o3d.utility.Vector2iVector(lines))
    geom.paint_uniform_color(color);return geom


def geometries(project, model_id, result_path=None):
    import open3d as o3d
    project=Path(project);manifest=open_project(project)
    if str(model_id) not in [m['id'] for m in manifest['models']]:raise PipelineError('模型编号不存在。')
    cameras,images,points=load_model(project/'sparse'/str(model_id)/'text')
    if not points:raise PipelineError('该模型没有三维点。')
    xyz=np.array([p['xyz'] for p in points.values()]);rgb=np.array([p['rgb'] for p in points.values()])/255
    cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(xyz);cloud.colors=o3d.utility.Vector3dVector(rgb)
    extent=max(float(np.linalg.norm(np.quantile(xyz,.95,axis=0)-np.quantile(xyz,.05,axis=0))),1e-4)
    size=extent*.025
    geoms=[cloud,o3d.geometry.TriangleMesh.create_coordinate_frame(size=extent*.1,origin=np.median(xyz,axis=0))]
    for im in list(images.values())[::max(1,len(images)//100)]:
        geoms.append(frustum(im['center'],im['R'].T,cameras[im['camera_id']],size,[.25,.6,.95]))
    if result_path:
        result=json.loads(Path(result_path).read_text(encoding='utf-8'))
        if result.get('status')!='success':raise PipelineError('该定位未成功，不能显示相机标记。')
        pose=result['pose']
        if str(pose['model_id'])!=str(model_id):raise PipelineError('定位结果与当前模型坐标系不同。')
        if pose.get('model_signature')!=model_signature(project/'sparse'/str(model_id)):
            raise PipelineError('定位结果不属于这份地图模型，不能叠加显示。请使用当前地图重新定位。')
        c=np.array(pose['xyz']);r=np.array(pose['rotation_camera_to_world'])
        geoms.append(frustum(c,r,pose['camera'],size*3,[1.,.15,.1]))
        marker=o3d.geometry.TriangleMesh.create_sphere(radius=size*.25)
        marker.translate(c);marker.paint_uniform_color([1.,.15,.1]);marker.compute_vertex_normals();geoms.append(marker)
        geoms.append(o3d.geometry.TriangleMesh.create_coordinate_frame(size=size*2).transform(np.array(pose['transform_camera_to_world'])))
    return geoms


def show(project,model_id='0',result_path=None,screenshot=None,self_check=False):
    import open3d as o3d
    geoms=geometries(project,model_id,result_path)
    viewer=o3d.visualization.VisualizerWithKeyCallback()
    if not viewer.create_window(window_name=f'Indoor Mapper | Model {model_id} | Blue: map / Red: query | F: focus / R: reset',width=1200,height=800,visible=True):
        raise PipelineError('无法创建 Open3D 图形窗口。请检查显卡驱动或在本地桌面运行。')
    try:
        for geom in geoms:viewer.add_geometry(geom)
        opts=viewer.get_render_option();opts.background_color=np.array([.08,.09,.11]);opts.point_size=3.;opts.line_width=3.
        viewer.reset_view_point(True)
        control=viewer.get_view_control()
        control.set_front([.5,-.3,-.8]);control.set_up([0.,-1.,0.]);control.set_zoom(.8)
        def reset(vis):
            vis.reset_view_point(True)
            c=vis.get_view_control();c.set_front([.5,-.3,-.8]);c.set_up([0.,-1.,0.]);c.set_zoom(.8)
            return False
        viewer.register_key_callback(ord('R'),reset)
        if result_path:
            pose=json.loads(Path(result_path).read_text(encoding='utf-8'))['pose']
            def focus(vis):
                c=vis.get_view_control();c.set_lookat(pose['xyz']);c.set_zoom(1.8)
                return False
            viewer.register_key_callback(ord('F'),focus)
        if screenshot or self_check:
            import time
            for _ in range(15):viewer.poll_events();viewer.update_renderer();time.sleep(.03)
            if screenshot:viewer.capture_screen_image(str(Path(screenshot).resolve()),do_render=True)
        if not self_check:viewer.run()
    finally:viewer.destroy_window()
