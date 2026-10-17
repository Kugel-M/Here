"""Read-only analysis of real controls; output is NOT an accepted calibration."""
import sys,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapper.navigation import load_layout,fit_calibration
from mapper.model import load_model

project=Path(sys.argv[1]).resolve();layout=load_layout(project);mid=sys.argv[2] if len(sys.argv)>2 else '0'
if len(sys.argv)>3:layout=json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
controls=layout['anchors'][mid]
byname={im['name']:im for im in load_model(project/'sparse'/mid/'text')[1].values()}
xyz=np.array([byname[a['image']]['center'] for a in controls]);uv=np.array([a['uv'] for a in controls])
# Deliberately relaxed ONLY to inspect residuals. Never save as site_map calibration.
cal=fit_calibration(xyz,uv,'DIAGNOSTIC_ONLY_NOT_ACCEPTED',max_error=1e12)
basis=np.array(cal['basis']);xy=(xyz-cal['origin'])@basis
pred=cal['scale']*xy@np.array(cal['rotation'])+cal['offset']
report=dict(purpose='诊断用整体拟合，不是定位结果，不是通过验收的标定',project=str(project),
    model_id=mid,rms_px=cal['rms_error_px'],nonplanarity=cal['nonplanarity'],
    controls=[dict(index=i+1,image=a['image'],manual_uv=a['uv'],diagnostic_uv=pred[i].tolist(),
                   residual_px=cal['control_errors_px'][i]) for i,a in enumerate(controls)])
if len(controls)>=2:
    a,b=[byname[controls[i]['image']] for i in [0,1]]
    report['first_two_controls']=dict(map_distance_px=float(np.linalg.norm(uv[0]-uv[1])),
        model_projected_distance_scaled_px=float(cal['scale']*np.linalg.norm(xy[0]-xy[1])),
        shared_3d_points=len(set(a['point_ids'][a['point_ids']!=-1])&set(b['point_ids'][b['point_ids']!=-1])))
folder=project/'diagnostics';folder.mkdir(exist_ok=True)
(folder/'alignment_analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
with Image.open(project/layout['image']) as im:canvas=Image.new('RGB',(im.width,im.height+160),'white');canvas.paste(im.convert('RGB'),(0,160))
draw=ImageDraw.Draw(canvas);font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',23)
small=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',20)
draw.text((24,12),'蓝圈：你标注的站位    红点：整体拟合的诊断位置    连线：残差',fill='#243247',font=font)
draw.text((24,49),'红点未通过标定，不是你的实际位置。偏差可能来自模型、底图或对应关系。',fill='#243247',font=small)
draw.text((24,84),'各点残差：'+ '   '.join(f'{i+1}号 {v:.1f}px' for i,v in enumerate(cal['control_errors_px'])),fill='#243247',font=small)
for i,(manual,estimate) in enumerate(zip(uv,pred),1):
    x,y=manual;y+=160;ex,ey=estimate;ey+=160
    draw.line((x,y,ex,ey),fill='#dc2626',width=3)
    draw.ellipse((x-9,y-9,x+9,y+9),outline='#2563eb',width=4)
    draw.ellipse((ex-5,ey-5,ex+5,ey+5),fill='#dc2626')
    draw.text((x+12,y+5),str(i),fill='#2563eb',font=font)
canvas.save(folder/'alignment_residuals.png')
print(json.dumps(report,ensure_ascii=True,indent=2));print(folder/'alignment_residuals.png')
