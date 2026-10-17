"""Synthetic UI workflow test ONLY; never writes controls into a real map."""
from pathlib import Path
import sys,json,uuid
from unittest.mock import patch
import tkinter as tk
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapper.engine import save_json,model_signature
from mapper.map_ui import MapEditor,MapPanel
from mapper.navigation import load_layout,mapped_pose,route_to

base=Path(__file__).resolve().parents[1]
project=base/'test_artifacts'/f'TEST_ONLY_map_workflow_{uuid.uuid4().hex[:6]}'
text=project/'sparse/0/text';text.mkdir(parents=True)
(project/'images').mkdir()
save_json(project/'project.json',dict(status='ready',models=[dict(id='0',registered_images=4,points=1)]))
for name in ['cameras.bin','images.bin','points3D.bin']:(text.parent/name).write_bytes(b'TEST ONLY: synthetic calibration fixture, not a COLMAP reconstruction')
(text/'cameras.txt').write_text('1 SIMPLE_RADIAL 100 100 100 50 50 0\n')
centers=[[0,1.5,0],[4,1.5,0],[0,1.5,3],[4,1.5,3]]
lines=[]
for i,c in enumerate(centers,1):
    name=f'ref_{i}.jpg';Image.new('RGB',(100,100),(i*40,100,100)).save(project/'images'/name)
    lines.extend([f'{i} 1 0 0 0 {-c[0]} {-c[1]} {-c[2]} 1 {name}','50 50 1'])
(text/'images.txt').write_text('\n'.join(lines)+'\n')
(text/'points3D.txt').write_text('1 1 1 4 255 0 0 0.1 1 0\n')
session=project/'queries/TEST_ONLY';qtext=session/'model_0/text';qtext.mkdir(parents=True)
(session/'images').mkdir();Image.new('RGB',(100,100),'gray').save(session/'images/query.jpg')
(session/'query_list.txt').write_text('query.jpg\n')
for f in ['cameras.txt','points3D.txt']:(qtext/f).write_bytes((text/f).read_bytes())
q=np.sqrt(.5)
(qtext/'images.txt').write_text('\n'.join(lines+[f'5 {q} 0 {-q} 0 1 -1.5 -1 1 query.jpg','50 50 1'])+'\n')
result=dict(status='success',source_photo='TEST ONLY',session=str(session),pose=dict(model_id='0',model_signature=model_signature(text.parent),xyz=[1,1.5,1],forward_world=[1,0,0]))
save_json(session/'result.json',result)
root=tk.Tk();root.withdraw()
with patch('mapper.map_ui.messagebox.showerror',side_effect=lambda *a,**k:(_ for _ in ()).throw(AssertionError(a))):
    editor=MapEditor(root,project);root.update()
    for i,uv in enumerate([[100,400],[500,400],[100,100],[500,100]]):
        editor.list.selection_clear(0,'end');editor.list.selection_set(i);editor.clicked(uv)
    editor.calibrate()
    editor.region.set('仅测试区域');editor.label_reference()
    editor.select_all();editor.region.set('批量测试区域');editor.label_reference()
    assert len(load_layout(project)['reference_labels']['0'])==4
    assert set(load_layout(project)['reference_labels']['0'].values())=={'批量测试区域'}
    before=len(editor.layout['anchors']['0']);editor.clicked([300,300])
    assert len(editor.layout['anchors']['0'])==before # Multi-selection cannot silently bind a single control.
    editor.list.selection_clear(0,'end');editor.list.selection_set(0)
    editor.mode.set('地点/路口')
    with patch('mapper.map_ui.simpledialog.askstring',side_effect=['测试入口','测试路口','测试目的地']):
        for uv in [[100,300],[500,300],[500,100]]:editor.clicked(uv)
    editor.mode.set('连接通路')
    for uv in [[100,300],[500,300],[500,300],[500,100]]:editor.clicked(uv)
    editor.scale.set('100');editor.save_scale()
    layout=load_layout(project);position=mapped_pose(project,result,layout)
    np.testing.assert_allclose(position['uv'],[200,300],atol=1e-9);np.testing.assert_allclose(position['heading'],[1,0],atol=1e-9)
    route=route_to(layout,position['uv'],layout['nodes'][-1]['id']);assert abs(route['length_meters']-5)<1e-6
    panel=MapPanel(root);panel.load(project,session/'result.json');root.update()
    assert panel.position['status']=='ready'
    editor.win.destroy()
root.destroy()
print('Synthetic workflow passed: UI controls saved; calibration projected pose and heading; manually annotated route returned 5 TEST meters.')
print('Fixture stays outside real projects:',project)
