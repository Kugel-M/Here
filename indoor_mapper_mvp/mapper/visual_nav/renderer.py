"""Separate static-photo overlay renderer. No live AR tracking is implied."""
from pathlib import Path
import math
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from ..model import project
from .graph import unit,vector
from .instructions import turn


class ArrowOverlayRenderer:
    def __init__(self,up):self.up=unit(up)

    def render(self,image_path,reference,travel_vector,action,output,ground=None):
        with Image.open(image_path) as original:im=original.convert('RGB');im.thumbnail((1200,1600))
        w,h=im.size;layer=Image.new('RGBA',im.size);draw=ImageDraw.Draw(layer)
        scene_action=action
        if travel_vector is not None and action not in ('up','down','arrive'):
            scene_action,_=turn(reference['forward_world'],travel_vector,self.up)
        mode='perspective_schematic';polygon=None
        # Ground projection is only allowed with surveyed ground geometry, not a guessed floor.
        if ground and travel_vector is not None and scene_action!='arrive':
            f=vector(travel_vector);f=f-self.up*np.dot(f,self.up)
            if np.linalg.norm(f)>1e-6:
                f=unit(f);right=unit(np.cross(f,self.up));origin=vector(ground['origin'])
                length=float(ground['arrow_length_units']);width=length*.23
                shape=[(-width*.35,0),(width*.35,0),(width*.35,.65),(width,.65),(0,1),(-width,.65),(-width*.35,.65)]
                xyz=np.array([origin+right*x+f*(y*length) for x,y in shape])
                rcw=np.asarray(reference['rotation_camera_to_world'],dtype=float)
                cam=(xyz-vector(reference['xyz']))@rcw
                if np.min(cam[:,2])>1e-5:
                    uv=project(reference['camera'],cam)*np.array([w/reference['camera']['width'],h/reference['camera']['height']])
                    if np.isfinite(uv).all() and ((uv[:,0]>=0)&(uv[:,0]<=w)&(uv[:,1]>=0)&(uv[:,1]<=h)).all():
                        polygon=[tuple(p) for p in uv];mode='surveyed_ground_projection'
        if action=='arrive':
            cx,cy=w*.5,h*.68;r=w*.075
            draw.ellipse((cx-r,cy-r*2,cx+r,cy),fill=(210,237,119,235),outline=(20,44,36,255),width=max(2,w//300))
            draw.polygon([(cx-r*.75,cy-r*.3),(cx+r*.75,cy-r*.3),(cx,cy+r)],fill=(210,237,119,235))
            draw.ellipse((cx-r*.3,cy-r*1.3,cx+r*.3,cy-r*.7),fill=(30,65,50,255))
        else:
            if polygon is None:
                shapes={
                    'straight':[(-.15,1),(.15,1),(.12,.42),(.4,.42),(0,0),(-.4,.42),(-.12,.42)],
                    'right':[(-.25,1),(.02,1),(.02,.42),(.34,.42),(.34,.66),(.68,.27),(.34,-.08),(.34,.15),(-.25,.15)],
                    'left':[(.25,1),(-.02,1),(-.02,.42),(-.34,.42),(-.34,.66),(-.68,.27),(-.34,-.08),(-.34,.15),(.25,.15)],
                    'uturn':[(-.35,1),(-.1,1),(-.1,.24),(.16,.24),(.16,.65),(-.02,.65),(.28,1),(.58,.65),(.4,.65),(.4,0),(-.35,0)]}
                shape=shapes.get(scene_action,shapes['straight'])
                # A tapered ground-style graphic; deliberately labelled as a schematic.
                polygon=[(w*(.5+x*(.45+.18*y)),h*(.57+y*.20)) for x,y in shape]
            shadow=[(x+w*.009,y+h*.006) for x,y in polygon]
            draw.polygon(shadow,fill=(0,0,0,100));draw.polygon(polygon,fill=(210,237,119,230))
            draw.line(polygon+[polygon[0]],fill=(30,66,46,240),width=max(2,w//250),joint='curve')
        labels={'straight':'GO STRAIGHT','left':'TURN LEFT','right':'TURN RIGHT','uturn':'TURN AROUND','up':'GO UP','down':'GO DOWN','arrive':'DESTINATION'}
        label=labels.get(scene_action,'FOLLOW ROUTE')
        fontpath=Path('C:/Windows/Fonts/arial.ttf')
        font=ImageFont.truetype(str(fontpath),max(18,int(w*.043))) if fontpath.exists() else ImageFont.load_default()
        box=draw.textbbox((0,0),label,font=font);tw=box[2]-box[0];y=h*.84
        draw.rounded_rectangle((w*.5-tw*.5-15,y-10,w*.5+tw*.5+15,y+font.size+14),radius=7,fill=(22,39,32,220))
        draw.text((w*.5-tw*.5,y),label,font=font,fill=(255,255,245,255))
        output=Path(output);output.parent.mkdir(exist_ok=True,parents=True)
        Image.alpha_composite(im.convert('RGBA'),layer).convert('RGB').save(output,quality=93)
        return dict(mode=mode,photo_action=scene_action,caption='参考场景方向示意，非实时摄像头 AR' if mode=='perspective_schematic' else '基于已测地面的投影箭头，非实时 AR')
