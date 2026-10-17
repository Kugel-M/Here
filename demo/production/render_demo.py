"""Render an edited walkthrough from genuine browser captures and local SAPI audio.
Run with the indoor_mapper_mvp virtual-environment Python; no network required.
"""
from pathlib import Path
import sys, json, wave, re, subprocess, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parents[1]
PROJECT = WORK / 'indoor_mapper_mvp'
MAP = PROJECT / 'projects/map_20261011_035045'
sys.path.insert(0, str(PROJECT))
from mapper.model import load_model

W,H,FPS = 1920,1080,24
BG='#F4F1E9'; INK='#242E2A'; MUTED='#66736A'; LIME='#D8E69D'; BLUE='#466CD4'
FONTS = Path('C:/Windows/Fonts')
def font(size,bold=False):
    return ImageFont.truetype(str(FONTS/('segoeuib.ttf' if bold else 'segoeui.ttf')),size)
def text(d,xy,s,size=26,fill=INK,bold=False):
    d.text(xy,s,font=font(size,bold),fill=fill,spacing=8)
def lines(d,s,width,size):
    result=[]; cur=''
    for word in s.split():
        candidate=(cur+' '+word).strip()
        if d.textlength(candidate,font=font(size))>width and cur:
            result.append(cur);cur=word
        else:cur=candidate
    if cur:result.append(cur)
    return result

scenes=json.loads((ROOT/'source/scenes.json').read_text(encoding='utf-8-sig'))
# These labels describe the observed application, rather than claiming a field walk.
scenes[3]['title']='Position and heading.\nIn the model frame.'
scenes[7]['step']='REAL APPLICATION / EDITED PHOTO REPLAY'
graph=json.loads((MAP/'visual_navigation.json').read_text(encoding='utf-8'))
pose_result=json.loads((MAP/'queries/20261017_132450_6a6eaa/result.json').read_text(encoding='utf-8'))
arrival_result=json.loads((MAP/'queries/20261017_132813_3d89e9/result.json').read_text(encoding='utf-8'))
evidence={'localization':pose_result,'arrival':arrival_result,'note':'Arrival uses original registered frame_000001.jpg, not a new field-walking photo.'}
(ROOT/'source/localization_evidence.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False),encoding='utf-8')

cams,images,points=load_model(MAP/'sparse/0/text')
pts=np.array([p['xyz'] for p in points.values()]); rgb=np.array([p['rgb'] for p in points.values()])
up=np.array(graph['world_up']);up/=np.linalg.norm(up)
u=np.cross(up,[0,0,1]);u/=np.linalg.norm(u);v=np.cross(up,u)
origin=np.median(pts,axis=0)
def project(p):
    p=np.atleast_2d(p)-origin
    xx=p@u; yy=p@v; zz=p@up
    return np.column_stack((.9*xx+.44*yy,.32*xx-.58*yy-.9*zz))
p=project(pts); lo,hi=np.quantile(p,[.02,.98],axis=0)
keep=((p>lo)&(p<hi)).all(axis=1)
scale=min(920/(hi[0]-lo[0]),265/(hi[1]-lo[1]))
center=(lo+hi)/2
def screen(p):return (project(p)-center)*scale+np.array([580,640])
map_image=Image.new('RGB',(1160,850),BG); md=ImageDraw.Draw(map_image)
for (x,y),color in zip(screen(pts[keep]),rgb[keep]):
    c=tuple(int(z*.55+100*.45) for z in color)
    md.ellipse((x-1,y-1,x+1,y+1),fill=c)
trajectory=sorted(images.values(),key=lambda c:c['name'])
camxy=screen(np.array([c['center'] for c in trajectory]))
md.line([tuple(c) for c in camxy],fill=BLUE,width=3)
for x,y in camxy[::5]:md.ellipse((x-3,y-3,x+3,y+3),fill=BLUE)
map_image.save(ROOT/'captures/02_sparse_map.png')

def phone(im,name):
    d=ImageDraw.Draw(im)
    x,y=1350,82;w,h=430,900
    d.rounded_rectangle((x-13,y-13,x+w+13,y+h+13),34,fill='#DBDCD3')
    shot=Image.open(ROOT/'captures'/f'{name}.jpg').convert('RGB')
    shot=ImageOps.contain(shot,(w,h),Image.Resampling.LANCZOS)
    im.paste(shot,(x+(w-shot.width)//2,y+(h-shot.height)//2))
    text(d,(1350,1010),'ACTUAL APP CAPTURE',18,MUTED,True)

def diagram(d,labels,y=616):
    n=len(labels); cell=300 if n==3 else 220
    for i,label in enumerate(labels):
        x=96+i*(cell+34)
        d.rounded_rectangle((x,y,x+cell,y+108),16,fill=LIME if i==n-1 else '#E6E8DF')
        for j,line in enumerate(label.split('\n')):text(d,(x+20,y+20+j*32),line,24,bold=i==n-1)
        if i<n-1:
            a=x+cell+7;d.line((a,y+54,a+18,y+54),fill=MUTED,width=3)
            d.polygon([(a+18,y+54),(a+10,y+48),(a+10,y+60)],fill=MUTED)

def graph_diagram(d):
    nodes={n['node_id']:n for n in graph['nodes']}
    raw=np.array([n['xyz'] for n in nodes.values()]); q=np.column_stack((raw@u,raw@v))
    low=q.min(0);high=q.max(0); fac=min(920/(high[0]-low[0]),185/(high[1]-low[1]))
    q=(q-(low+high)/2)*fac+np.array([585,660]);xy=dict(zip(nodes,q))
    for edge in graph['edges']:
        # Graph schema stores named endpoints.
        a=edge.get('source',edge.get('from',edge.get('a')));b=edge.get('target',edge.get('to',edge.get('b')))
        if a in xy and b in xy:d.line((*xy[a],*xy[b]),fill='#B3BEAC',width=5)
    for key,(x,y) in xy.items():
        d.ellipse((x-7,y-7,x+7,y+7),fill=BLUE if key!='N01' else '#799835')
        text(d,(x+9,y-25),key,18,MUTED)
    text(d,(96,790),'13 waypoints  /  12 connections  /  original 3D coordinates',21,MUTED)

def base(idx,shot):
    s=scenes[idx]; im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
    d.line((96,108,1240,108),fill='#CDD1C5',width=2)
    text(d,(96,40),'HERE',35,bold=True);text(d,(225,50),'INDOOR VISUAL NAVIGATION',18,MUTED)
    d.ellipse((1184,43,1226,85),fill=LIME);text(d,(1193,43),'↗',27)
    text(d,(96,151),s['step'],20,MUTED,True)
    text(d,(92,200),s['title'],66,bold=True)
    for j,b in enumerate(s['body']):
        d.ellipse((99,414+j*49,106,421+j*49),fill='#83916D')
        text(d,(124,400+j*49),b,27)
    if idx==1:
        im.paste(map_image.crop((0,490,1160,815)),(30,540))
        d=ImageDraw.Draw(im)
        text(d,(96,815),f'{len(points):,} sparse points   /   {len(images)} registered reference cameras',21,MUTED)
    elif idx==2:diagram(d,['IMAGE\nFEATURES','2D–3D\nCORRESPONDENCES','CAMERA\nREGISTRATION'])
    elif idx==3:
        d.rounded_rectangle((96,584,1220,820),20,fill='#E4E8DD')
        p=pose_result['pose'];xyz=p['xyz'];q=p['quality']
        text(d,(128,606),'ACTUAL LOCALIZATION OUTPUT',19,MUTED,True)
        text(d,(128,648),'XYZ   '+',  '.join(f'{x:.4f}' for x in xyz),36,bold=True)
        text(d,(128,706),f"{q['num_2d3d']} 2D–3D correspondences  /  median reprojection error {q['median_error_px']:.2f} px",24)
        text(d,(128,760),'Model units · physical scale has not yet been measured',21,MUTED)
    elif idx==4:graph_diagram(d)
    elif idx==5:diagram(d,['CAMERA\nHEADING','NEXT SEGMENT\nDIRECTION','RELATIVE\nTURN'])
    elif idx==6:diagram(d,['NEW PHOTO','NEW POSE','ROUTE UPDATE'])
    elif idx==7:
        d.rounded_rectangle((96,592,1220,808),20,fill=LIME)
        text(d,(128,618),'PHOTO  →  POSE  →  ROUTE  →  VISUAL STEP',35,bold=True)
        text(d,(128,685),'Localization + A* planning + reference-image arrows',25)
        text(d,(128,733),'Controlled arrival confirmed by re-localization',25)
    else:
        diagram(d,['PHONE VIDEO','3D MAP','PHOTO → ROUTE'])
    phone(im,shot)
    return im

# Multiple observed states keep the edited walkthrough faithful to the actual flow.
shots=[[(0,'01_home')],[(0,'01_home')],[(0,'02_capture_guide'),(.45,'04_pose_result_take2')],
       [(0,'04_pose_result_take2')],[(0,'05_destination_take2'),(.46,'06_navigation')],
       [(0,'06_navigation'),(.55,'07_reference_preview')],
       [(0,'08_relocalizing'),(.48,'09_arrival')],[(0,'09_arrival')]]

audio=[]; timeline=[]; cursor=0; rate=22050
for idx,s in enumerate(scenes):
    with wave.open(str(ROOT/'audio'/f"{s['id']}.wav"),'rb') as w:
        assert w.getframerate()==rate and w.getnchannels()==1 and w.getsampwidth()==2
        voice=w.readframes(w.getnframes());vd=w.getnframes()/rate
    lead=.35; duration=math.ceil((vd+.85)*FPS)/FPS
    samples=int(round(duration*rate)); track=b'\0\0'*int(lead*rate)+voice
    track+=b'\0\0'*(samples-len(track)//2);audio.append(track)
    sentences=re.split(r'(?<=[.!?])\s+',s['voice']); weight=sum(len(t) for t in sentences)
    caps=[];t=cursor+lead
    for sentence in sentences:
        length=vd*len(sentence)/weight;caps.append((t,t+length,sentence));t+=length
    timeline.append(dict(index=idx,start=cursor,duration=duration,captions=caps));cursor+=duration
with wave.open(str(ROOT/'audio/narration.wav'),'wb') as w:
    w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(b''.join(audio))
def stamp(t):
    ms=round(t*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'
srt=[];counter=1
for scene in timeline:
    for a,b,c in scene['captions']:
        srt.append(f'{counter}\n{stamp(a)} --> {stamp(b)}\n{c}\n');counter+=1
(ROOT/'English_Subtitles.srt').write_text('\n'.join(srt),encoding='utf-8')
(ROOT/'source/timeline.json').write_text(json.dumps(timeline,indent=2),encoding='utf-8')
(ROOT/'English_Narration.md').write_text('# HERE · Indoor visual navigation\n\n'+'\n\n'.join(s['step']+'\n\n'+s['voice'] for s in scenes),encoding='utf-8')

def caption_frame(baseim,caption,progress):
    im=baseim.copy();d=ImageDraw.Draw(im)
    d.rounded_rectangle((80,873,1235,1008),16,fill=INK)
    if caption:
        for j,line in enumerate(lines(d,caption,1080,29)):
            text(d,(108,891+j*40),line,29,'#F4F1E9')
    text(d,(96,1033),'REAL APP · EDITED PHOTO REPLAY · ENGLISH NARRATION',17,MUTED)
    d.rectangle((0,H-5,int(W*progress),H),fill=BLUE)
    return im

ff=imageio_ffmpeg.get_ffmpeg_exe()
out=ROOT/'HERE_Indoor_Visual_Navigation_Demo_EN.mp4'
cmd=[ff,'-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}',
     '-r',str(FPS),'-i','-','-i',str(ROOT/'audio/narration.wav'),'-c:v','libx264',
     '-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k',
     '-movflags','+faststart','-shortest',str(out)]
with (ROOT/'qa/encoding.log').open('w',encoding='utf-8') as log:
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=log,stderr=log)
    for scene in timeline:
        idx=scene['index']; duration=scene['duration']; frames=round(duration*FPS)
        cache={name:base(idx,name) for _,name in shots[idx]};last=None;static=None
        for f in range(frames):
            local=f/FPS;now=scene['start']+local
            shot=next(name for frac,name in reversed(shots[idx]) if local/duration>=frac)
            cap=next((c for a,b,c in scene['captions'] if a<=now<b),'')
            key=(shot,cap)
            if key!=last:
                static=caption_frame(cache[shot],cap,0);last=key
            im=static.copy();ImageDraw.Draw(im).rectangle((0,H-5,int(W*now/cursor),H),fill=BLUE)
            process.stdin.write(im.tobytes())
        preview=caption_frame(cache[shots[idx][-1][1]],scene['captions'][0][2],(scene['start']+duration/2)/cursor)
        preview.save(ROOT/'qa'/f'scene_{idx+1:02}.jpg',quality=92)
        print(f'Rendered scene {idx+1}/8',flush=True)
    process.stdin.close();code=process.wait()
    if code:raise RuntimeError(f'FFmpeg exit {code}; see qa/encoding.log')
poster=Image.open(ROOT/'qa/scene_06.jpg');poster.save(ROOT/'Demo_Preview.jpg',quality=94)
contact=Image.new('RGB',(1280,1440),'white')
for i in range(8):
    thumb=Image.open(ROOT/'qa'/f'scene_{i+1:02}.jpg').resize((640,360))
    contact.paste(thumb,((i%2)*640,(i//2)*360))
contact.save(ROOT/'qa/contact_sheet.jpg',quality=90)
print(json.dumps({'output':str(out),'seconds':cursor,'size_mb':out.stat().st_size/1048576,'fps':FPS}))
