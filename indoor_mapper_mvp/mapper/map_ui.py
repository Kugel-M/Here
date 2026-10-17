"""Floor-plan editing and a user-facing location panel, integrated with Tk."""
from pathlib import Path
import json
import uuid
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
import numpy as np
from PIL import Image,ImageOps,ImageTk
from .engine import PipelineError,open_project,save_json
from .model import load_model
from .navigation import (load_layout,save_layout,set_floorplan,calibrate_model,restore_annotations,diagnose_model,
                         mapped_pose,reference_matches,route_to,calibrated_position,
                         MAP_DIRECTIONS,save_heading_reference,save_query_heading)


class PlanCanvas(ttk.Frame):
    def __init__(self,parent,clicked=None):
        super().__init__(parent);self.project=None;self.layout=None;self.position=None;self.route=None;self.mid=None
        self.clicked=clicked;self.scale=1.;self.offset=(0,0);self.bg=None
        self.canvas=tk.Canvas(self,background='#eef1f5',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Button-1>',self.click)

    def click(self,event):
        if not self.layout or not self.clicked:return
        x=(event.x-self.offset[0])/self.scale;y=(event.y-self.offset[1])/self.scale
        if 0<=x<=self.layout['width'] and 0<=y<=self.layout['height']:self.clicked([x,y])

    def screen(self,p):return (self.offset[0]+p[0]*self.scale,self.offset[1]+p[1]*self.scale)

    def set(self,project,layout,position=None,route=None,mid=None):
        self.project=Path(project);self.layout=layout;self.position=position;self.route=route;self.mid=mid;self.draw()

    def draw(self):
        c=self.canvas;c.delete('all')
        if not self.layout:return
        width=max(c.winfo_width(),200);height=max(c.winfo_height(),180)
        w,h=self.layout['width'],self.layout['height'];self.scale=min((width-24)/w,(height-24)/h)
        self.offset=((width-w*self.scale)/2,(height-h*self.scale)/2)
        x,y=self.offset
        c.create_rectangle(x,y,x+w*self.scale,y+h*self.scale,fill='white',outline='#cbd5e1')
        if self.layout.get('image'):
            path=(self.project/self.layout['image']).resolve()
            if path.is_relative_to(self.project.resolve()) and path.exists():
                with Image.open(path) as im:
                    self.bg=ImageTk.PhotoImage(im.resize((max(1,int(w*self.scale)),max(1,int(h*self.scale))),Image.Resampling.LANCZOS))
                c.create_image(x,y,anchor='nw',image=self.bg)
        else:c.create_text(x+10,y+10,anchor='nw',text='空白示意图，请按实际布局标注；没有自动生成墙面。',fill='#64748b',font=('Microsoft YaHei',9))
        nodes={n['id']:n for n in self.layout['nodes']}
        for a,b in self.layout['edges']:
            if a in nodes and b in nodes:c.create_line(*self.screen(nodes[a]['uv']),*self.screen(nodes[b]['uv']),fill='#94a3b8',width=3)
        if self.route:
            path=[v for p in self.route['points'] for v in self.screen(p)]
            if len(path)>=4:c.create_line(*path,fill='#2563eb',width=5)
        for n in nodes.values():
            px,py=self.screen(n['uv']);c.create_oval(px-5,py-5,px+5,py+5,fill='#334155',outline='white')
            c.create_text(px+8,py-10,anchor='sw',text=n['name'],fill='#334155',font=('Microsoft YaHei',10))
        if self.mid:
            for i,a in enumerate(self.layout['anchors'].get(self.mid,[])):
                px,py=self.screen(a['uv']);c.create_rectangle(px-5,py-5,px+5,py+5,outline='#d97706',width=2)
                c.create_text(px+7,py+6,anchor='nw',text=f'标定{i+1}',fill='#92400e')
        if self.position and self.position.get('status')=='direction_only':
            px=x+85;py=y+95;heading=self.position['heading']
            c.create_rectangle(x+10,y+10,x+170,y+165,fill='white',outline='#94a3b8')
            c.create_text(px,y+30,text='拍摄方向（图上为北）',fill='#334155')
            c.create_line(px,py,px+heading[0]*42,py+heading[1]*42,fill='#dc2626',width=4,arrow='last')
            c.create_text(px,y+145,text='位置尚未标定',fill='#64748b')
        if self.position and self.position.get('status') in ('ready','approximate'):
            px,py=self.screen(self.position['uv']);heading=self.position['heading']
            if heading is not None:
                end=(px+heading[0]*40,py+heading[1]*40)
                c.create_line(px,py,*end,fill='#dc2626',width=4,arrow='last',arrowshape=(12,14,6))
            approximate=self.position['status']=='approximate'
            c.create_oval(px-8,py-8,px+8,py+8,fill='#d97706' if approximate else '#dc2626',outline='white',width=2)
            c.create_text(px,py+17,anchor='n',text='估计位置' if approximate else '你在这里',fill='#b91c1c',font=('Microsoft YaHei',11,'bold'))


class MapPanel(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent);self.project=None;self.result_path=None;self.result=None;self.route=None
        self.photos=[];self.dest_ids={};self.message=tk.StringVar(value='加载地图后可标注区域、底图和通路。')
        ttk.Label(self,textvariable=self.message,wraplength=950,font=('Microsoft YaHei',10,'bold')).pack(anchor='w',padx=8,pady=6)
        bar=ttk.Frame(self);bar.pack(fill='x',padx=8)
        ttk.Label(bar,text='目的地').pack(side='left');self.destination=tk.StringVar()
        self.dest=ttk.Combobox(bar,textvariable=self.destination,state='readonly',width=25);self.dest.pack(side='left',padx=8)
        self.dest.bind('<<ComboboxSelected>>',lambda e:self.clear_route())
        ttk.Button(bar,text='显示路线',command=self.plan_route).pack(side='left')
        ttk.Button(bar,text='清除路线',command=self.clear_route).pack(side='left',padx=8)
        ttk.Button(bar,text='导出位置与路线',command=self.export).pack(side='left')
        ttk.Button(bar,text='刷新地图',command=self.clear_route).pack(side='left',padx=8)
        ttk.Button(bar,text='校准本照片方向',command=self.calibrate_query_heading).pack(side='left')
        self.distance=ttk.Label(bar,text='');self.distance.pack(side='left')
        body=ttk.Frame(self);body.pack(fill='both',expand=True,pady=6)
        self.plan=PlanCanvas(body);self.plan.pack(side='left',fill='both',expand=True)
        self.cards=ttk.Frame(body,width=225);self.cards.pack(side='right',fill='y',padx=8);self.cards.pack_propagate(False)

    def clear_route(self):self.route=None;self.refresh()

    def load(self,project,result_path=None):
        self.project=Path(project).resolve();self.result_path=Path(result_path) if result_path else None
        self.result=json.loads(self.result_path.read_text(encoding='utf-8')) if self.result_path else None
        self.route=None;self.refresh()

    def refresh(self):
        if not self.project:return
        if not self.route:self.distance.configure(text='')
        self.layout=load_layout(self.project);self.position=mapped_pose(self.project,self.result,self.layout) if self.result else dict(status='unavailable',reason='请先选择照片定位，或打开已有定位结果。')
        refs=reference_matches(self.project,self.result_path,2) if self.result and self.result.get('status')=='success' else []
        votes={}
        for ref in refs:
            if ref['region']:votes[ref['region']]=votes.get(ref['region'],0)+ref['shared_points']
        region=max(votes,key=votes.get) if votes else None
        msg=f'参考区域：{region}附近。' if region else '参考区域尚未命名。'
        if self.position['status']=='ready':msg+='已显示地图位置与拍摄方向。' if self.position['heading'] else '已显示地图位置；镜头接近垂直，暂不显示平面朝向。'
        else:msg+=self.position['reason']
        if self.position.get('heading') is not None:
            h=np.asarray(self.position['heading'])
            bearing=max(MAP_DIRECTIONS,key=lambda name:np.dot(h,np.asarray(MAP_DIRECTIONS[name])/np.linalg.norm(MAP_DIRECTIONS[name])))
            msg+=f' 拍摄方向：{bearing}（底图上方为北）。'
        self.message.set(msg)
        self.dest_ids={f'{n["name"]} [{i+1}]':n['id'] for i,n in enumerate(self.layout['nodes'])}
        self.dest['values']=list(self.dest_ids)
        if self.destination.get() not in self.dest_ids:self.destination.set('')
        self.plan.set(self.project,self.layout,self.position,self.route)
        for widget in self.cards.winfo_children():widget.destroy()
        self.photos=[]
        if self.result_path:
            images=list((self.result_path.parent/'images').glob('*'))
            if images:self.card(images[0],'本次定位照片')
        for i,ref in enumerate(refs):
            label=ref['region'] or f'参考画面 {i+1}'
            self.card(ref['path'],f'{label} · 共同点 {ref["shared_points"]}')

    def card(self,path,label):
        ttk.Label(self.cards,text=label,wraplength=220).pack(anchor='w',pady=(5,2))
        try:
            with Image.open(path) as im:photo=ImageTk.PhotoImage(ImageOps.contain(im.convert('RGB'),(210,105)))
            self.photos.append(photo);ttk.Label(self.cards,image=photo).pack(anchor='center')
        except OSError:ttk.Label(self.cards,text='图片不可用').pack()

    def calibrate_query_heading(self):
        if not self.result_path or not self.result or self.result.get('status')!='success':
            messagebox.showinfo('需要定位结果','请先成功定位一张已知拍摄方向的照片。');return
        direction=simpledialog.askstring('已知拍摄方向',
            '输入这张照片拍摄时镜头朝向：北、东北、东、东南、南、西南、西、西北。\n'
            '方向以底图上方为北。这张照片将用于方向标定；之后请另拍一张验证。',parent=self)
        if not direction:return
        try:
            self.layout=load_layout(self.project)
            save_query_heading(self.project,self.layout,self.result_path,direction.strip())
            self.clear_route()
        except Exception as e:messagebox.showerror('无法标定方向',str(e),parent=self)

    def plan_route(self):
        try:
            if self.position.get('status')=='approximate':raise PipelineError('当前显示旧标定的估计位置。方向箭头可使用，路线需先通过位置标定。')
            if self.position.get('status')!='ready':raise PipelineError('请先完成成功定位和地图位置标定。')
            nid=self.dest_ids.get(self.destination.get())
            if not nid:raise PipelineError('请选择目的地。')
            self.route=route_to(self.layout,self.position['uv'],nid)
            self.refresh()
            names='，再到 '.join(self.route['node_names'])
            length=self.route['length_meters']
            self.distance.configure(text=f'约 {length:.1f} 米（底图标尺换算）' if length is not None else '底图未标米制尺度')
            self.message.set(self.route['start_note']+' 按蓝线经过：'+names)
        except Exception as e:messagebox.showinfo('无法规划路线',str(e))

    def export(self):
        if not self.result_path:messagebox.showinfo('没有结果','请先定位或打开已有定位结果。');return
        data=dict(position=self.position,route=self.route,references=reference_matches(self.project,self.result_path),
                  map_image=self.layout.get('image'),pixels_per_meter=self.layout.get('pixels_per_meter'))
        path=self.result_path.parent/'user_view.json';save_json(path,data)
        messagebox.showinfo('已导出',str(path))


class MapEditor:
    def __init__(self,parent,project,on_saved=lambda:None):
        self.project=Path(project).resolve();self.layout=load_layout(project);self.on_saved=on_saved;self.edge_start=None
        self.win=tk.Toplevel(parent);self.win.title('地图与区域设置');self.win.geometry('1280x900')
        self.mid=tk.StringVar();self.mode=tk.StringVar(value='标定点');self.region=tk.StringVar();self.scale=tk.StringVar(value=str(self.layout.get('pixels_per_meter') or ''))
        top=ttk.Frame(self.win,padding=10);top.pack(fill='x')
        ttk.Label(top,text='使用真实底图或自己绘制的示意布局。每个模型单独标定；选择参考图后，在底图点击手机当时所在位置。',wraplength=1200).pack(anchor='w')
        row=ttk.Frame(top);row.pack(fill='x',pady=6)
        ttk.Button(row,text='导入/更换底图',command=self.import_plan).pack(side='left')
        ttk.Button(row,text='恢复备份标注',command=self.restore_backup).pack(side='left',padx=6)
        ttk.Button(row,text='查看标定说明',command=self.help).pack(side='left',padx=8)
        ttk.Label(row,text='操作模式').pack(side='left');ttk.Combobox(row,textvariable=self.mode,values=['标定点','地点/路口','连接通路'],state='readonly',width=12).pack(side='left',padx=8)
        ttk.Label(row,text='底图像素/米（可留空）').pack(side='left');ttk.Entry(row,textvariable=self.scale,width=8).pack(side='left',padx=6)
        ttk.Button(row,text='保存标尺',command=self.save_scale).pack(side='left')
        body=ttk.Frame(self.win);body.pack(fill='both',expand=True,padx=10)
        sidebar=ttk.Frame(body,width=340);sidebar.pack(side='left',fill='y',padx=(0,10));sidebar.pack_propagate(False)
        sidebar_canvas=tk.Canvas(sidebar,width=315,highlightthickness=0)
        sidebar_scroll=ttk.Scrollbar(sidebar,orient='vertical',command=sidebar_canvas.yview)
        sidebar_scroll.pack(side='right',fill='y');sidebar_canvas.pack(side='left',fill='both',expand=True)
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        left=ttk.Frame(sidebar_canvas)
        interior=sidebar_canvas.create_window(0,0,anchor='nw',window=left)
        left.bind('<Configure>',lambda e:sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox('all')))
        sidebar_canvas.bind('<Configure>',lambda e:sidebar_canvas.itemconfigure(interior,width=e.width))
        ttk.Label(left,text='模型编号').pack(anchor='w')
        ids=[m['id'] for m in open_project(project)['models']]
        combo=ttk.Combobox(left,textvariable=self.mid,values=ids,state='readonly');combo.pack(fill='x')
        combo.bind('<<ComboboxSelected>>',lambda e:self.model_changed())
        list_frame=ttk.Frame(left);list_frame.pack(fill='x',pady=5)
        self.list=tk.Listbox(list_frame,height=9,exportselection=False,selectmode='extended');self.list.pack(side='left',fill='x',expand=True);self.list.bind('<<ListboxSelect>>',lambda e:self.reference_selected())
        scroll=ttk.Scrollbar(list_frame,orient='vertical',command=self.list.yview);scroll.pack(side='right',fill='y');self.list.configure(yscrollcommand=scroll.set)
        ttk.Label(left,text='Shift 连选，Ctrl 多选；标定时仅选一张。').pack(anchor='w')
        self.selection_note=tk.StringVar(value='已选择 0 张')
        selection_bar=ttk.Frame(left);selection_bar.pack(fill='x')
        ttk.Label(selection_bar,textvariable=self.selection_note).pack(side='left')
        ttk.Button(selection_bar,text='全选此模型',command=self.select_all).pack(side='right')
        self.preview=ttk.Label(left);self.preview.pack(pady=4)
        ttk.Label(left,text='所选参考图的区域名称').pack(anchor='w')
        self.region_entry=ttk.Combobox(left,textvariable=self.region);self.region_entry.pack(fill='x')
        ttk.Button(left,text='批量保存所选图片的区域名称',command=self.label_reference).pack(fill='x',pady=5)
        ttk.Label(left,text='标定点（至少3个，须有侧向分布）').pack(anchor='w',pady=(8,0))
        self.anchor_list=tk.Listbox(left,height=5,exportselection=False);self.anchor_list.pack(fill='x')
        ttk.Button(left,text='删除选中标定点',command=self.remove_anchor).pack(fill='x',pady=3)
        ttk.Button(left,text='计算并保存此模型标定',command=self.calibrate).pack(fill='x',pady=3)
        ttk.Label(left,text='所选参考图的已知拍摄方向').pack(anchor='w',pady=(8,0))
        self.bearing=tk.StringVar(value='北')
        ttk.Combobox(left,textvariable=self.bearing,values=list(MAP_DIRECTIONS),state='readonly').pack(fill='x')
        ttk.Button(left,text='用所选参考图标定方向',command=self.calibrate_reference_heading).pack(fill='x',pady=3)
        ttk.Label(left,text='地点与路口').pack(anchor='w',pady=(8,0))
        self.node_list=tk.Listbox(left,height=5,exportselection=False);self.node_list.pack(fill='x')
        ttk.Button(left,text='删除选中地点及其连接',command=self.remove_node).pack(fill='x',pady=3)
        self.plan=PlanCanvas(body,self.clicked);self.plan.pack(side='left',fill='both',expand=True)
        self.note=tk.StringVar(value='选择参考图，然后在地图上标出实际拍摄位置。')
        ttk.Label(self.win,textvariable=self.note,wraplength=1200,padding=10).pack(fill='x')
        self.mid.set(ids[0]);self.model_changed()

    def persist(self):save_layout(self.project,self.layout);self.redraw();self.on_saved()

    def redraw(self):
        self.region_entry['values']=sorted({label for labels in self.layout['reference_labels'].values() for label in labels.values() if label})
        self.plan.set(self.project,self.layout,mid=self.mid.get())
        self.anchor_list.delete(0,'end')
        for i,a in enumerate(self.layout['anchors'].get(self.mid.get(),[])):self.anchor_list.insert('end',f'{i+1}. {a["image"]}')
        self.node_list.delete(0,'end')
        for n in self.layout['nodes']:self.node_list.insert('end',n['name'])

    def model_changed(self):
        self.references=sorted(load_model(self.project/'sparse'/self.mid.get()/'text')[1].values(),key=lambda i:i['name'])
        self.list.delete(0,'end')
        times={}
        if (self.project/'frames.json').exists():
            times={f['image_name']:f['time_seconds'] for f in json.loads((self.project/'frames.json').read_text(encoding='utf-8'))['frames'] if f['image_name']}
        self.frame_times=times
        self.refresh_reference_list()
        if self.references:self.list.selection_set(0);self.reference_selected()
        self.edge_start=None;self.redraw()

    def selected_reference(self):
        idx=self.list.curselection()
        return self.references[idx[0]] if idx else None

    def reference_selected(self):
        selected=self.list.curselection();self.selection_note.set(f'已选择 {len(selected)} 张')
        ref=self.selected_reference()
        if not ref:return
        try:
            with Image.open(self.project/'images'/ref['name']) as im:self.photo=ImageTk.PhotoImage(ImageOps.contain(im.convert('RGB'),(260,165)))
            self.preview.configure(image=self.photo)
        except OSError:self.preview.configure(image='',text='参考图不可用')
        labels=self.layout['reference_labels'].get(self.mid.get(),{})
        names={labels.get(self.references[i]['name'],'') for i in selected}
        self.region.set(next(iter(names)) if len(names)==1 else '')
        if len(names)>1:self.note.set('所选图片的名称不同。输入或选择一个名称后，可统一保存。')

    def refresh_reference_list(self):
        selected=self.list.curselection();view=self.list.yview()
        self.list.delete(0,'end');labels=self.layout['reference_labels'].get(self.mid.get(),{})
        for ref in self.references:
            name=ref['name'];t=self.frame_times.get(name)
            text=f'{t:.2f}秒 · {name}' if t is not None else name
            self.list.insert('end',text+'  ['+labels.get(name,'未命名')+']')
        for i in selected:self.list.selection_set(i)
        if view:self.list.yview_moveto(view[0])

    def select_all(self):
        self.list.selection_set(0,'end');self.reference_selected()

    def clicked(self,uv):
        mode=self.mode.get();mid=self.mid.get()
        if mode=='标定点':
            if len(self.list.curselection())!=1:self.note.set('标定点必须对应一张图片，请先只选择一张参考图。');return
            ref=self.selected_reference()
            if not ref:self.note.set('请先选择一张参考图。');return
            anchors=self.layout['anchors'].setdefault(mid,[])
            anchors[:]=[a for a in anchors if a['image']!=ref['name']]
            anchors.append(dict(image=ref['name'],uv=uv));self.layout['calibrations'].pop(mid,None)
            self.persist();self.note.set(f'已记录 {ref["name"]} 的拍摄位置。修改标定点后需要重新计算标定。')
        elif mode=='地点/路口':
            name=simpledialog.askstring('地点名称','输入实际地点或路口名称：',parent=self.win)
            if name and name.strip():
                self.layout['nodes'].append(dict(id=uuid.uuid4().hex[:8],name=name.strip(),uv=uv));self.persist()
        else:
            nodes=self.layout['nodes']
            if not nodes:self.note.set('请先添加地点/路口。');return
            nearest=min(nodes,key=lambda n:np.linalg.norm(np.array(n['uv'])-uv))
            if np.linalg.norm(np.array(nearest['uv'])-uv)>30/self.plan.scale:self.note.set('请点击地点圆点。');return
            if not self.edge_start:self.edge_start=nearest['id'];self.note.set('已选择 '+nearest['name']+'，再点击可直接通行的另一地点。');return
            pair=[self.edge_start,nearest['id']];self.edge_start=None
            if pair[0]==pair[1]:self.note.set('连接已取消。');return
            existing=next((e for e in self.layout['edges'] if set(e)==set(pair)),None)
            if existing:self.layout['edges'].remove(existing);self.note.set('已删除这段通路。')
            else:self.layout['edges'].append(pair);self.note.set('已添加实际可通行连接。再次连接相同两点可删除。')
            self.persist()

    def label_reference(self):
        selected=self.list.curselection();name=self.region.get().strip()
        if not selected:self.note.set('请先选择要命名的参考图。');return
        if not name and not messagebox.askyesno('清空名称',f'确定清空所选 {len(selected)} 张图片的区域名称吗？',parent=self.win):return
        labels=self.layout['reference_labels'].setdefault(self.mid.get(),{})
        for i in selected:labels[self.references[i]['name']]=name
        self.persist();self.refresh_reference_list();self.note.set(f'已为 {len(selected)} 张图片保存区域名称：{name or "（空）"}。')

    def remove_anchor(self):
        idx=self.anchor_list.curselection()
        if idx:
            self.layout['anchors'][self.mid.get()].pop(idx[0]);self.layout['calibrations'].pop(self.mid.get(),None);self.persist()

    def calibrate_reference_heading(self):
        if len(self.list.curselection())!=1:self.note.set('方向标定请只选择一张已知镜头朝向的参考图。');return
        try:
            ref=self.selected_reference()
            save_heading_reference(self.project,self.layout,self.mid.get(),ref['name'],self.bearing.get())
            self.persist();self.note.set('方向标定已保存。请使用另一张照片验证方向。方向标定不会更改位置坐标。')
        except Exception as e:messagebox.showerror('无法标定方向',str(e),parent=self.win)

    def remove_node(self):
        idx=self.node_list.curselection()
        if idx:
            nid=self.layout['nodes'].pop(idx[0])['id'];self.layout['edges']=[e for e in self.layout['edges'] if nid not in e];self.persist()

    def calibrate(self):
        try:
            cal=calibrate_model(self.project,self.layout,self.mid.get());self.persist()
            self.note.set(f'标定已保存，使用 {cal["num_controls"]} 点，均方根误差 {cal["rms_error_px"]:.2f} 像素。请再用未参与标定的照片核对。')
        except Exception as e:
            try:
                diagnostic=('左右镜像不能通过压缩底图修复。请用正常直立拍摄的参考图核对楼层方向、参考站位的相对位置及重建轨迹；不要为了降低误差而移动确认准确的站位。'
                    if '镜像' in str(e) else diagnose_model(self.project,self.layout,self.mid.get()))
            except Exception:diagnostic='当前数据无法完成底图比例检查。'
            controls='\n'.join(f'{i+1}. {a["image"]}' for i,a in enumerate(self.layout['anchors'].get(self.mid.get(),[])))
            self.note.set(str(e)+' '+diagnostic)
            messagebox.showerror('无法标定',str(e)+'\n\n'+diagnostic+'\n\n标定点对应图片：\n'+controls,parent=self.win)

    def save_scale(self):
        try:
            value=float(self.scale.get()) if self.scale.get().strip() else None
            if value is not None and (not np.isfinite(value) or value<=0):raise ValueError()
            self.layout['pixels_per_meter']=value;self.persist()
        except ValueError:messagebox.showerror('标尺无效','请输入大于0的像素/米，或留空。',parent=self.win)

    def import_plan(self):
        p=filedialog.askopenfilename(parent=self.win,filetypes=[('底图图片','*.png *.jpg *.jpeg *.bmp')])
        if not p:return
        keep=False
        if self.layout['anchors'] or self.layout['nodes']:
            keep=messagebox.askyesnocancel('如何处理地图坐标',
                '区域名称始终保留，旧设置会备份。\n\n'
                '如果是同一布局，仅宽高尺寸改变，选“是”：按新尺寸迁移标定点和通路。\n'
                '如果有裁剪、旋转、留白改变或换了布局，选“否”：重新标点，保留区域名称。\n'
                '选“取消”放弃更换。迁移后仍需重新计算标定。',parent=self.win)
            if keep is None:return
        try:
            self.layout=set_floorplan(self.project,p,preserve_coordinates=keep);self.scale.set(str(self.layout.get('pixels_per_meter') or ''));self.persist();self.reference_selected()
            self.note.set('底图已更换，区域名称已保留。'+('标定点和通路已按尺寸迁移，请重新计算标定。' if keep else '请在新底图上重新标定拍摄位置。'))
        except Exception as e:messagebox.showerror('无法导入',str(e),parent=self.win)

    def restore_backup(self):
        folder=self.project/'site_map_backups'
        p=filedialog.askopenfilename(parent=self.win,initialdir=str(folder),title='选择旧标注备份',filetypes=[('标注备份','*.json')])
        if not p:return
        try:
            old=json.loads(Path(p).read_text(encoding='utf-8'))
            keep=False
            if old.get('anchors') or old.get('nodes'):
                keep=messagebox.askyesnocancel('恢复哪些标注',
                    f'备份底图尺寸 {old["width"]} × {old["height"]}，当前 {self.layout["width"]} × {self.layout["height"]}。\n\n'
                    '选“是”：补回缺失名称，并用备份标定点、地点和通路替换当前坐标，按尺寸迁移。仅适用于同一布局且没有裁剪、旋转或留白变化。\n'
                    '选“否”：只补回缺失名称，保留当前坐标。\n选“取消”：不恢复。现有名称不会被覆盖，恢复前会备份当前设置。',parent=self.win)
                if keep is None:return
            self.layout,count=restore_annotations(self.project,p,include_coordinates=keep)
            self.scale.set(str(self.layout.get('pixels_per_meter') or ''));self.persist();self.refresh_reference_list();self.reference_selected()
            self.note.set(f'已补回 {count} 个缺失名称。'+('已迁移备份坐标，请重新计算标定。' if keep else '当前标定点和通路已保留。'))
        except Exception as e:messagebox.showerror('无法恢复',str(e),parent=self.win)

    def help(self):
        messagebox.showinfo('标定与路线说明',
            '1. 准备真实平面图，或在空白示意图按实际布局标注。\n'
            '2. 选择同一模型的至少3张参考图，明确手机当时的位置，在底图点击对应位置。\n'
            '3. 使用同楼层、相近手机高度的拍摄位置；标定点不能都在一条直线上，建议4个以上并增加侧向点。\n'
            '4. 点击计算标定。不同模型分别标定，不能直接混用坐标。\n'
            '5. 切换地点/路口模式添加目标。连接通路模式依次点击两个地点，仅连接实际可通行线段。\n'
            '6. 底图像素/米需要实际测量：在导入后底图上量出的像素长度除以实际米数；不知道就留空。\n'
            '7. 区域命名可用 Ctrl/Shift 多选；标定位置时只选一张。更换底图保留名称，同布局可按尺寸迁移坐标。\n'
            '标定点是手机拍摄位置，不是照片中门框、桌子等物体的位置。',parent=self.win)
