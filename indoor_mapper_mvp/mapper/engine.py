from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import numpy as np
from PIL import Image, ImageOps
from .model import load_model, pose_quality, pose_record

BASE=Path(__file__).resolve().parents[1]


class PipelineError(RuntimeError):
    pass


def save_json(path, data):
    path=Path(path); tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def model_signature(folder):
    digest=hashlib.sha256()
    for name in ['cameras.bin','images.bin','points3D.bin','rigs.bin','frames.bin']:
        path=Path(folder)/name
        if not path.exists():continue
        digest.update(name.encode())
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def config():
    p=BASE/'config.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def executable_colmap():
    options=[os.environ.get('COLMAP_EXE'), config().get('colmap_exe'), shutil.which('colmap'),
             'D:/colmap-x64-windows-cuda/bin/colmap.exe']
    for value in options:
        if value and Path(value).is_file():
            return Path(value).resolve()
    raise PipelineError('找不到 COLMAP。请在 config.json 设置 colmap_exe 为 colmap.exe 的完整路径。')


def executable_ffmpeg():
    value=config().get('ffmpeg_exe') or shutil.which('ffmpeg')
    if value and Path(value).is_file():
        return Path(value).resolve()
    import imageio_ffmpeg
    return Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()


def environment():
    exe=executable_colmap()
    env=os.environ.copy();env['PATH']=str(exe.parent)+os.pathsep+env.get('PATH','')
    plugins=exe.parent.parent/'plugins'
    if plugins.exists():env['QT_PLUGIN_PATH']=str(plugins)
    return env


class Runner:
    def __init__(self, log=lambda s: None, cancel=None):
        self.log=log; self.cancel=cancel or threading.Event()

    def run(self, args, logfile, label, env=None):
        if self.cancel.is_set():raise PipelineError('操作已取消。')
        logfile=Path(logfile);logfile.parent.mkdir(parents=True,exist_ok=True)
        self.log(label+'…')
        command=[str(a) for a in args]
        with logfile.open('w',encoding='utf-8') as f:
            f.write('COMMAND: '+subprocess.list2cmdline(command)+'\n');f.flush()
            proc=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            started=time.monotonic(); heartbeat=started
            while proc.poll() is None:
                if self.cancel.wait(.2):
                    proc.terminate()
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                    raise PipelineError(f'操作已取消，已保留日志：{logfile}')
                now=time.monotonic()
                if now-heartbeat>15:
                    self.log(f'{label}仍在运行，已用时 {int(now-started)} 秒');heartbeat=now
        if proc.returncode:
            tail=logfile.read_text(encoding='utf-8',errors='replace')[-2500:]
            raise PipelineError(f'{label}失败（退出码 {proc.returncode}）。日志：{logfile}\n{tail}')
        self.log(label+'完成')

    def colmap(self, stage, opts, logfile, label):
        self.run([executable_colmap(),stage,*opts],logfile,label,environment())


def check_environment():
    result={'python':sys.version,'python_exe':sys.executable}
    for name in ['numpy','Pillow','imageio-ffmpeg','open3d']:
        try:result[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:result[name]='未安装'
    for name, func, flags in [('colmap',executable_colmap,['-h']),('ffmpeg',executable_ffmpeg,['-version'])]:
        try:
            exe=func();p=subprocess.run([str(exe),*flags],capture_output=True,env=environment() if name=='colmap' else None,
                timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            lines=(p.stdout+p.stderr).decode('utf-8',errors='replace').splitlines()
            result[name]={'path':str(exe),'exit_code':p.returncode,'version':lines[:2]}
        except Exception as e:result[name]={'error':str(e)}
    try:
        p=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],
            capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        result['gpu']=p.stdout.decode(errors='replace').strip() or '未发现 NVIDIA GPU，可选择 CPU 模式'
    except (OSError,subprocess.TimeoutExpired):result['gpu']='未发现 NVIDIA GPU，可选择 CPU 模式'
    return result


def video_metadata(video):
    if not Path(video).is_file():raise PipelineError('视频文件不存在。')
    if Path(video).suffix.lower() not in {'.mp4','.mov'}:raise PipelineError('请选择 MP4 或 MOV 视频。')
    p=subprocess.run([str(executable_ffmpeg()),'-hide_banner','-i',str(video)],capture_output=True,
        timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    text=(p.stdout+p.stderr).decode('utf-8',errors='replace')
    duration=re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)',text)
    size=re.search(r'Video:.*?\b(\d{2,5})x(\d{2,5})\b',text)
    if not duration or not size:raise PipelineError('无法读取视频时长或画面尺寸。请确认文件可播放、未损坏。\n'+text[-1500:])
    h,m,s=duration.groups();seconds=int(h)*3600+int(m)*60+float(s)
    if seconds<=0:raise PipelineError('视频时长为零。')
    return {'duration_seconds':seconds,'width':int(size[1]),'height':int(size[2]),'source':str(Path(video).resolve())}


def frame_quality(path):
    with Image.open(path) as image:
        gray=image.convert('L');gray.thumbnail((320,320))
        a=np.asarray(gray,dtype=float)
    lap=-4*a[1:-1,1:-1]+a[:-2,1:-1]+a[2:,1:-1]+a[1:-1,:-2]+a[1:-1,2:]
    return float(lap.var()), np.asarray(gray.resize((48,48)),dtype=float)


def extract_frames(video, project, runner, fps=2., max_frames=400):
    if not .25<=fps<=8 or not 20<=max_frames<=2000:
        raise PipelineError('抽帧频率应为 0.25–8，帧数上限应为 20–2000。')
    meta=video_metadata(video);target=min(fps,max_frames/meta['duration_seconds'])
    candidate_fps=target*2
    candidates=project/'candidates';candidates.mkdir()
    images=project/'images';images.mkdir()
    runner.run([executable_ffmpeg(),'-hide_banner','-i',video,'-an','-vf',
        f"fps={candidate_fps},scale=w='min(1920,iw)':h='min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
        '-q:v','2',candidates/'candidate_%06d.jpg'],project/'logs/extract.log','视频抽帧')
    files=sorted(candidates.glob('*.jpg'))
    if len(files)<3:raise PipelineError('可用视频帧不足三张。请使用更长的视频。')
    scored=[]
    for i,p in enumerate(files):
        if runner.cancel.is_set():raise PipelineError('操作已取消。')
        sharp,gray=frame_quality(p)
        scored.append((i,p,sharp,gray))
    threshold=max(1.,float(np.median([s[2] for s in scored]))*.05)
    kept=[];records=[];previous=None
    for offset in range(0,len(scored),2):
        # Select the sharper candidate in each time bin; avoid deleting entire transitions.
        i,p,sharp,gray=max(scored[offset:offset+2],key=lambda s:s[2])
        reason='保留'
        if sharp<threshold:reason='清晰度过低'
        elif previous is not None and float(np.mean(np.abs(gray-previous)))<.8:reason='近乎重复'
        if reason=='保留':
            name=f'frame_{len(kept)+1:06d}.jpg';shutil.copy2(p,images/name)
            kept.append(name);previous=gray
        records.append(dict(candidate=p.name,time_seconds=(i+.5)/candidate_fps,sharpness=sharp,
            decision=reason,image_name=kept[-1] if reason=='保留' else None))
    save_json(project/'frames.json',dict(video=meta,target_fps=target,candidate_fps=candidate_fps,
        sharpness_threshold=threshold,frames=records,num_kept=len(kept)))
    # Keep only selected frames; candidates are an app-created temporary directory.
    if not candidates.resolve().is_relative_to(project.resolve()):
        raise PipelineError('临时目录超出项目范围，拒绝清理。')
    shutil.rmtree(candidates)
    runner.log(f'抽帧筛选完成，保留 {len(kept)} 张；清晰度阈值仅作初筛，不保证可建图')
    if len(kept)<10:raise PipelineError('筛选后不足10张图片。视频可能过短、严重模糊或大部分原地不动。')
    return meta,len(kept)


def export_model(model, runner, logs, tag):
    text=model/'text';text.mkdir(exist_ok=True)
    runner.colmap('model_converter',['--input_path',model,'--output_path',text,'--output_type','TXT'],
        logs/f'{tag}_text.log','导出模型参数')
    runner.colmap('model_converter',['--input_path',model,'--output_path',model/'points.ply','--output_type','PLY'],
        logs/f'{tag}_ply.log','导出点云')
    _,images,points=load_model(text)
    return dict(id=model.name,registered_images=len(images),points=len(points),
        mean_point_reprojection_error_px=float(np.mean([p['error'] for p in points.values()])) if points else None)


def reconstruct(video, project, runner=None, fps=2., max_frames=400, gpu=True):
    runner=runner or Runner();project=Path(project).resolve()
    if project.exists():raise PipelineError('输出目录已存在。请为每次建图选择新的项目目录。')
    project.mkdir(parents=True);(project/'logs').mkdir();(project/'sparse').mkdir()
    manifest=dict(schema_version=1,status='building',models=[],source_video=str(Path(video).resolve()))
    save_json(project/'project.json',manifest)
    try:
        meta,num=extract_frames(video,project,runner,fps,max_frames)
        db=project/'database.db';g=str(int(gpu))
        runner.colmap('feature_extractor',['--database_path',db,'--image_path',project/'images',
            '--ImageReader.single_camera','1','--FeatureExtraction.use_gpu',g,
            '--FeatureExtraction.num_threads','8','--FeatureExtraction.max_image_size','1920'],
            project/'logs/features.log','SIFT 特征提取')
        # All pairs is reliable for an MVP of a few hundred images; larger maps need retrieval.
        runner.colmap('exhaustive_matcher',['--database_path',db,'--FeatureMatching.use_gpu',g,
            '--FeatureMatching.guided_matching','1','--FeatureMatching.num_threads','8'],
            project/'logs/matching.log','特征匹配与几何验证')
        runner.colmap('mapper',['--database_path',db,'--image_path',project/'images','--output_path',project/'sparse',
            '--Mapper.num_threads','8'],project/'logs/mapper.log','SfM 三维重建')
        models=[export_model(p,runner,project/'logs',f'model_{p.name}') for p in sorted((project/'sparse').iterdir()) if p.is_dir() and (p/'images.bin').exists()]
        if not models:raise PipelineError('未生成有效三维模型。请检查画面重叠、移动视差、白墙比例与模糊情况。')
        manifest.update(status='ready',video=meta,num_input_images=num,models=models,
            gpu=bool(gpu),coordinate_unit='arbitrary',colmap_exe=str(executable_colmap()))
        save_json(project/'project.json',manifest)
        runner.log(f'建图完成，共 {len(models)} 个独立模型。每个模型有自己的坐标系。')
        return manifest
    except Exception as e:
        manifest.update(status='failed',error=str(e));save_json(project/'project.json',manifest);raise


def open_project(project):
    project=Path(project).resolve();path=project/'project.json'
    if not path.exists():raise PipelineError('这不是本程序的地图项目。已有 COLMAP 结果请使用“导入旧结果”。')
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('status')!='ready':raise PipelineError('该地图未完成建图：'+manifest.get('error',manifest.get('status','未知')))
    return manifest


def import_existing(source, project, runner=None):
    runner=runner or Runner();source=Path(source).resolve();project=Path(project).resolve()
    processing=source
    if not (processing/'database.db').exists():
        candidates=[p for p in source.glob('processing*') if (p/'database.db').exists() and (p/'sparse').exists()]
        if len(candidates)>1:raise PipelineError('目录内有多份旧结果，请直接选择要导入的 processing 子目录。')
        if candidates:processing=candidates[0]
    db=processing/'database.db';sparse=processing/'sparse';images=source/'images'
    if not images.exists():images=processing.parent/'images'
    if not db.exists() or not sparse.exists() or not images.exists():
        raise PipelineError('旧结果目录应包含 images，以及 database.db、sparse（后两者可在 processing 内）。')
    if project.exists():raise PipelineError('目标目录已存在，不能覆盖。')
    project.mkdir(parents=True);(project/'logs').mkdir();(project/'sparse').mkdir()
    manifest=dict(schema_version=1,status='building',models=[],imported_from=str(source))
    save_json(project/'project.json',manifest)
    try:
        if Path(str(db)+'-wal').exists() or Path(str(db)+'-journal').exists():
            raise PipelineError('旧数据库可能正在写入，请关闭对应 COLMAP 处理后再导入。')
        with sqlite3.connect(db.as_uri()+'?mode=ro&immutable=1',uri=True) as src, sqlite3.connect(project/'database.db') as dst:src.backup(dst)
        models=[];names=set()
        for p in sorted(sparse.iterdir()):
            if not p.is_dir() or not (p/'images.bin').exists():continue
            target=project/'sparse'/p.name;shutil.copytree(p,target)
            models.append(export_model(target,runner,project/'logs',f'import_{p.name}'))
            names.update(i['name'] for i in load_model(target/'text')[1].values())
        if not models:raise PipelineError('旧结果中没有有效的 images.bin 模型。')
        dstimages=project/'images';dstimages.mkdir()
        for name in names:
            source_image=(images/name).resolve()
            if not source_image.is_relative_to(images.resolve()):raise PipelineError('模型包含越界图片路径，无法导入。')
            if not source_image.exists():raise PipelineError(f'找不到模型引用的原图：{source_image}')
            target=(dstimages/name).resolve()
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source_image,target)
        manifest.update(status='ready',num_input_images=len(names),models=models,coordinate_unit='arbitrary',
                        colmap_exe=str(executable_colmap()))
        save_json(project/'project.json',manifest);return manifest
    except Exception as e:
        manifest.update(status='failed',error=str(e));save_json(project/'project.json',manifest);raise


def matching_diagnostics(db, query_name, refids):
    with sqlite3.connect(db) as con:
        row=con.execute('SELECT image_id FROM images WHERE name=?',(query_name,)).fetchone()
        if not row:return dict(query_features=0,verified_pairs=0,max_pair_inliers=0)
        qid=row[0]
        keys=con.execute('SELECT rows FROM keypoints WHERE image_id=?',(qid,)).fetchone()
        counts=[]
        for rid in refids:
            a,b=sorted([qid,rid]);pid=a*2147483647+b
            r=con.execute('SELECT rows FROM two_view_geometries WHERE pair_id=?',(pid,)).fetchone()
            if r and r[0]>0:counts.append(r[0])
    return dict(query_features=keys[0] if keys else 0,verified_pairs=len(counts),
                max_pair_inliers=max(counts,default=0))


def localize(project, photo, runner=None, model_id='auto', gpu=True):
    runner=runner or Runner();project=Path(project).resolve();manifest=open_project(project)
    photo=Path(photo).resolve()
    if not photo.is_file():raise PipelineError('照片不存在。')
    session=project/'queries'/f'{time.strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:6]}'
    session.mkdir(parents=True);(session/'logs').mkdir();(session/'images').mkdir()
    result=dict(status='failed',source_photo=str(photo),map_project=str(project),session=str(session),attempts=[])
    try:
        # Normalize EXIF orientation; each query gets independent intrinsics.
        with Image.open(photo) as im:
            im=ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((2400,2400));im.save(session/'images/query.jpg',quality=97)
        name='query.jpg';db=session/'database.db'
        with sqlite3.connect((project/'database.db').as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(db) as dst:src.backup(dst)
        chosen=[m for m in manifest['models'] if model_id=='auto' or m['id']==str(model_id)]
        if not chosen:raise PipelineError('指定模型不存在。')
        references={}
        for m in chosen:
            references[m['id']]=load_model(project/'sparse'/m['id']/'text')[1]
        with sqlite3.connect(db) as con:
            existing_names={r[0] for r in con.execute('SELECT name FROM images')}
        if name in existing_names:
            name=f'query_{uuid.uuid4().hex[:8]}.jpg';(session/'images/query.jpg').rename(session/'images'/name)
        (session/'query_list.txt').write_text(name+'\n',encoding='utf-8')
        allrefs={i['name'] for imgs in references.values() for i in imgs.values()}
        if any(any(c.isspace() for c in n) for n in allrefs):
            raise PipelineError('参考图文件名含空白字符，COLMAP 匹配列表无法解析。请使用本程序从视频建图。')
        (session/'pairs.txt').write_text(''.join(f'{name} {n}\n' for n in sorted(allrefs)),encoding='utf-8')
        g=str(int(gpu))
        runner.colmap('feature_extractor',['--database_path',db,'--image_path',session/'images',
            '--image_list_path',session/'query_list.txt','--ImageReader.single_camera','0',
            '--ImageReader.camera_model','SIMPLE_RADIAL','--FeatureExtraction.use_gpu',g,
            '--FeatureExtraction.max_image_size','1920','--FeatureExtraction.num_threads','8'],
            session/'logs/features.log','新照片特征提取')
        runner.colmap('matches_importer',['--database_path',db,'--match_list_path',session/'pairs.txt',
            '--match_type','pairs','--FeatureMatching.use_gpu',g,'--FeatureMatching.guided_matching','1',
            '--FeatureMatching.num_threads','8'],session/'logs/matching.log','新照片与地图匹配')
        candidates=[]
        for m in chosen:
            mid=m['id'];out=session/f'model_{mid}';out.mkdir()
            diag=matching_diagnostics(db,name,list(references[mid]))
            attempt=dict(model_id=mid,diagnostics=diag);result['attempts'].append(attempt)
            if diag['query_features']<30:
                attempt['reason']='照片特征不足30个，可能是白墙、模糊或曝光问题。';continue
            if not diag['verified_pairs']:
                attempt['reason']='与该模型没有通过几何验证的匹配，可能不在覆盖区域、视角差异过大或画面缺少细节。';continue
            runner.colmap('image_registrator',['--database_path',db,'--input_path',project/'sparse'/mid,
                '--output_path',out,'--Mapper.abs_pose_min_num_inliers','30',
                '--Mapper.abs_pose_min_inlier_ratio','0.25','--Mapper.abs_pose_max_error','8',
                '--Mapper.structure_less_registration_fallback','0','--Mapper.fix_existing_frames','1',
                '--Mapper.num_threads','8'],session/'logs'/f'register_{mid}.log',f'模型 {mid} 的二维到三维定位')
            text=out/'text';text.mkdir()
            runner.colmap('model_converter',['--input_path',out,'--output_path',text,'--output_type','TXT'],
                session/'logs'/f'export_{mid}.log','读取定位结果')
            cameras,imgs,points=load_model(text)
            query=next((im for im in imgs.values() if im['name']==name),None)
            if query is None:
                attempt['reason']='有二维匹配，但不足以建立可靠的二维到三维对应或通过 PnP 位姿验证。';continue
            # Ensure existing coordinate frame has actually been preserved.
            for iid,ref in references[mid].items():
                new=imgs.get(iid)
                if new is None or not np.allclose(new['center'],ref['center'],rtol=1e-8,atol=1e-8) or not np.allclose(new['R'],ref['R'],atol=1e-8):
                    raise PipelineError('注册改变了原地图坐标，拒绝输出位姿。请查看注册日志。')
            quality=pose_quality(query,cameras,points);attempt['quality']=quality
            if quality['num_2d3d']<30 or quality['positive_depth_ratio']<.95 or quality['median_error_px'] is None or quality['median_error_px']>4 or quality['p90_error_px']>12:
                attempt['reason']='注册产生了候选位姿，但未通过独立的对应数量、正深度或重投影误差检查。';continue
            pose=pose_record(query,cameras[query['camera_id']],quality)
            candidates.append(dict(model_id=mid,model_signature=model_signature(project/'sparse'/mid),**pose))
            attempt['reason']='注册与质量检查通过'
        candidates.sort(key=lambda c:c['quality']['num_2d3d'],reverse=True)
        if not candidates:
            result['reason']='所有候选模型均未通过定位。详情见 attempts；未输出 XYZ 或朝向。'
        elif len(candidates)>1 and candidates[1]['quality']['num_2d3d']>=.8*candidates[0]['quality']['num_2d3d']:
            result.update(status='ambiguous',reason='多个独立模型获得相近的定位支持，无法唯一确定坐标系。请选择已知区域对应的模型后重试。',
                candidate_model_ids=[c['model_id'] for c in candidates])
        else:
            result.update(status='success',pose=candidates[0],reason='COLMAP 注册与独立质量检查通过；仍需真实场景验证。')
        save_json(session/'result.json',result)
        runner.log(result['reason']);return result
    except Exception as e:
        result['reason']=str(e);save_json(session/'result.json',result);raise
