"""Read real saved results and initialize the integrated windows without altering maps."""
from pathlib import Path
import sys
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapper.ui import App
from mapper.map_ui import MapEditor
from mapper.navigation import reference_matches,mapped_pose,load_layout
import json

base=Path(__file__).resolve().parents[1]
project=base/'projects/map_20261010_224219'
result_path=project/'queries/20261010_224257_e151de/result.json'
result=json.loads(result_path.read_text(encoding='utf-8'))
refs=reference_matches(project,result_path)
assert refs[0]['shared_points']==131 and refs[0]['image']=='frame_000001.jpg'
position=mapped_pose(project,result)
assert position['status']=='uncalibrated' and 'uv' not in position
assert not (project/'site_map.json').exists(), 'This test expects the untouched original project.'
root=tk.Tk();root.withdraw();app=App(root);app.refresh(project);root.update()
app.present_result(result,result_path);root.update()
assert len(app.map_panel.photos)==3
assert app.map_panel.position['status']=='uncalibrated'
editor=MapEditor(root,project);root.update()
assert len(editor.references)>0
assert not (project/'site_map.json').exists()
editor.win.destroy();root.destroy()
print('Real result reference matching, uncalibrated no-marker behavior, main UI and map editor passed.')
