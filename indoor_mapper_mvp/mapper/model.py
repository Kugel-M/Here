"""COLMAP text I/O and explicit world/camera coordinate conversions."""
from pathlib import Path
import numpy as np


def rotation(q):
    q = np.asarray(q, dtype=float)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1-2*y*y-2*z*z, 2*x*y-2*w*z, 2*x*z+2*w*y],
        [2*x*y+2*w*z, 1-2*x*x-2*z*z, 2*y*z-2*w*x],
        [2*x*z-2*w*y, 2*y*z+2*w*x, 1-2*x*x-2*y*y]])


def load_model(folder):
    folder = Path(folder)
    cameras, images, points = {}, {}, {}
    for line in (folder/'cameras.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        t = line.split()
        cameras[int(t[0])] = dict(model=t[1], width=int(t[2]), height=int(t[3]),
                                   params=[float(v) for v in t[4:]])
    # Observation rows may be empty; never filter empty lines before pairing.
    with (folder/'images.txt').open(encoding='utf-8') as f:
        while True:
            line = f.readline()
            if not line:
                break
            if line.startswith('#') or not line.strip():
                continue
            t = line.strip().split(maxsplit=9)
            obs = f.readline().split()
            q = np.array([float(v) for v in t[1:5]])
            tr = np.array([float(v) for v in t[5:8]])
            r = rotation(q)
            images[int(t[0])] = dict(id=int(t[0]), name=t[9], camera_id=int(t[8]),
                q=q, t=tr, R=r, center=-r.T@tr,
                xy=np.array([[float(obs[i]), float(obs[i+1])] for i in range(0, len(obs), 3)]).reshape(-1, 2),
                point_ids=np.array([int(obs[i+2]) for i in range(0, len(obs), 3)], dtype=np.int64))
    for line in (folder/'points3D.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        t = line.split()
        points[int(t[0])] = dict(xyz=np.array([float(v) for v in t[1:4]]),
            rgb=np.array([int(v) for v in t[4:7]]), error=float(t[7]))
    return cameras, images, points


def project(camera, xyz_camera):
    p = camera['params']; kind = camera['model']
    xy = xyz_camera[:, :2]/xyz_camera[:, 2:3]
    x, y = xy.T; rr = x*x+y*y
    if kind == 'SIMPLE_RADIAL':
        f, cx, cy, k = p; fx=fy=f
        x, y = x*(1+k*rr), y*(1+k*rr)
    elif kind == 'RADIAL':
        f, cx, cy, k1, k2 = p; fx=fy=f
        x, y = x*(1+k1*rr+k2*rr*rr), y*(1+k1*rr+k2*rr*rr)
    elif kind == 'SIMPLE_PINHOLE':
        f, cx, cy = p; fx=fy=f
    elif kind == 'PINHOLE':
        fx, fy, cx, cy = p
    elif kind == 'OPENCV':
        fx,fy,cx,cy,k1,k2,p1,p2=p
        rad=1+k1*rr+k2*rr*rr
        x,y=x*rad+2*p1*x*y+p2*(rr+2*x*x), y*rad+p1*(rr+2*y*y)+2*p2*x*y
    else:
        raise ValueError(f'暂不支持独立质量检查的相机模型：{kind}')
    return np.column_stack((fx*x+cx, fy*y+cy))


def pose_quality(image, cameras, points):
    keep=np.array([pid in points for pid in image['point_ids']])
    ids=image['point_ids'][keep]
    if not len(ids):
        return dict(num_2d3d=0, positive_depth_ratio=0., median_error_px=None, p90_error_px=None)
    xyz=np.array([points[int(pid)]['xyz'] for pid in ids])
    cam=xyz@image['R'].T+image['t']
    positive=cam[:,2]>1e-8
    error=np.linalg.norm(project(cameras[image['camera_id']],cam[positive])-image['xy'][keep][positive],axis=1)
    return dict(num_2d3d=int(len(ids)),positive_depth_ratio=float(positive.mean()),
        median_error_px=float(np.median(error)) if len(error) else None,
        p90_error_px=float(np.quantile(error,.9)) if len(error) else None)


def pose_record(image, camera, quality):
    rcw=image['R'].T
    twc=np.eye(4);twc[:3,:3]=rcw;twc[:3,3]=image['center']
    return dict(xyz=image['center'].tolist(), rotation_camera_to_world=rcw.tolist(),
        quaternion_world_to_camera_wxyz=image['q'].tolist(),
        translation_world_to_camera=image['t'].tolist(), transform_camera_to_world=twc.tolist(),
        forward_world=(rcw@np.array([0.,0.,1.])).tolist(), camera=camera, quality=quality,
        coordinate_note='模型自身坐标，尺度任意，XYZ不是米。相机轴：X向右、Y向下、Z向前。')
