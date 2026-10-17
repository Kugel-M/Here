from pathlib import Path
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from .engine import BASE,Runner,check_environment,reconstruct,localize,import_existing,open_project
from .map_ui import MapPanel,MapEditor


class App:
    def __init__(self,root):
        self.root=root;root.title('室内视觉定位与地图导航 · Hackathon MVP');root.geometry('1180x900')
        self.events=queue.Queue();self.cancel=threading.Event();self.busy=False;self.last_result=None
        self.project=tk.StringVar();self.video=tk.StringVar();self.photo=tk.StringVar();self.fps=tk.StringVar(value='2')
        self.maxframes=tk.StringVar(value='400');self.gpu=tk.BooleanVar(value=True);self.model=tk.StringVar(value='auto')
        self.photo.trace_add('write',self.invalidate_result)
        self.project.trace_add('write',self.invalidate_result)
        box=ttk.Frame(root,padding=18);box.pack(fill='both',expand=True)
        ttk.Label(box,text='视频建图、照片定位，在地图上确认位置与方向',font=('Microsoft YaHei',16,'bold')).pack(anchor='w')
        ttk.Label(box,text='先标注参考区域，再把模型标定到底图。未标定时仅展示参考画面；不同模型分别标定。').pack(anchor='w',pady=(6,14))
        self.buttons=[]
        row=ttk.Frame(box);row.pack(fill='x',pady=4)
        self.button(row,'检查环境',self.doctor).pack(side='left')
        self.button(row,'打开地图项目',self.open).pack(side='left',padx=8)
        self.button(row,'导入旧 COLMAP 结果',self.import_old).pack(side='left')
        self.button(row,'地图与区域设置',self.edit_map).pack(side='left',padx=8)
        self.button(row,'实景导航设置',self.open_visual_navigation).pack(side='left')
        self.pathrow(box,'当前地图',self.project,None)
        self.pathrow(box,'建图视频',self.video,self.select_video)
        row=ttk.Frame(box);row.pack(fill='x',pady=5)
        ttk.Label(row,text='每秒保留帧数').pack(side='left');ttk.Entry(row,textvariable=self.fps,width=6).pack(side='left',padx=6)
        ttk.Label(row,text='帧数上限').pack(side='left');ttk.Entry(row,textvariable=self.maxframes,width=7).pack(side='left',padx=6)
        ttk.Checkbutton(row,text='使用 NVIDIA GPU（出错可取消勾选重试）',variable=self.gpu).pack(side='left',padx=10)
        self.button(row,'开始建图',self.build).pack(side='right')
        ttk.Separator(box).pack(fill='x',pady=12)
        self.pathrow(box,'定位照片',self.photo,self.select_photo)
        row=ttk.Frame(box);row.pack(fill='x',pady=5)
        ttk.Label(row,text='定位模型').pack(side='left');self.combo=ttk.Combobox(row,textvariable=self.model,values=['auto'],state='readonly',width=12)
        self.combo.pack(side='left',padx=8)
        self.button(row,'开始定位',self.locate).pack(side='left',padx=8)
        self.button(row,'查看三维场景',self.view).pack(side='left')
        self.button(row,'打开结果目录',self.folder).pack(side='left',padx=8)
        self.button(row,'打开定位结果',self.open_result).pack(side='left')
        self.button(row,'放大地图',self.expand_map).pack(side='left',padx=8)
        ttk.Label(box,text='三维窗口：左键旋转，滚轮缩放，Ctrl+左键平移；F 聚焦定位相机，R 恢复全景。蓝色为建图相机，红色为定位相机。',wraplength=950).pack(anchor='w',pady=6)
        self.status=tk.StringVar(value='请选择视频开始建图，或打开已有地图。')
        ttk.Label(box,textvariable=self.status,wraplength=950,font=('Microsoft YaHei',10,'bold')).pack(anchor='w',pady=8)
        row=ttk.Frame(box);row.pack(fill='x')
        self.bar=ttk.Progressbar(row,mode='indeterminate');self.bar.pack(side='left',fill='x',expand=True)
        self.stop=ttk.Button(row,text='取消当前处理',command=self.cancel.set,state='disabled');self.stop.pack(side='right',padx=8)
        self.tabs=ttk.Notebook(box);self.tabs.pack(fill='both',expand=True,pady=(10,0))
        self.map_panel=MapPanel(self.tabs);self.tabs.add(self.map_panel,text='用户地图与参考画面')
        technical=ttk.Frame(self.tabs);self.tabs.add(technical,text='技术日志与原始坐标')
        self.text=tk.Text(technical,height=16,wrap='word',font=('Microsoft YaHei',10));self.text.pack(fill='both',expand=True)
        root.after(100,self.poll);root.protocol('WM_DELETE_WINDOW',self.close)
        state=BASE/'ui_state.json'
        if state.exists():
            try:self.refresh(Path(json.loads(state.read_text(encoding='utf-8'))['project']))
            except Exception:pass

    def button(self,parent,text,command):
        b=ttk.Button(parent,text=text,command=command);self.buttons.append(b);return b

    def pathrow(self,parent,label,var,command):
        row=ttk.Frame(parent);row.pack(fill='x',pady=4)
        ttk.Label(row,text=label,width=10).pack(side='left')
        ttk.Entry(row,textvariable=var,state='normal' if command else 'readonly').pack(side='left',fill='x',expand=True)
        if command:self.button(row,'选择文件',command).pack(side='right',padx=(8,0))

    def log(self,message):
        self.text.insert('end',message+'\n');self.text.see('end')

    def invalidate_result(self,*args):
        self.last_result=None
        if hasattr(self,'map_panel') and self.project.get() and (Path(self.project.get())/'project.json').exists():
            self.map_panel.load(self.project.get())

    def task(self,func,done):
        if self.busy:return
        self.busy=True;self.cancel.clear();self.bar.start();self.stop['state']='normal'
        for b in self.buttons:b['state']='disabled'
        def work():
            try:self.events.put(('done',done,func(Runner(lambda s:self.events.put(('log',s)),self.cancel))))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        try:
            while True:
                item=self.events.get_nowait()
                if item[0]=='log':self.log(item[1]);self.status.set(item[1])
                else:
                    self.busy=False;self.bar.stop();self.stop['state']='disabled'
                    for b in self.buttons:b['state']='normal'
                    if item[0]=='error':self.status.set('处理失败，详情见日志。');self.log(item[1]);messagebox.showerror('处理失败',item[1][-2500:])
                    else:
                        try:item[1](item[2])
                        except Exception as e:self.log(str(e));messagebox.showerror('无法显示结果',str(e))
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def doctor(self):
        self.task(lambda r:check_environment(),lambda d:self.log(json.dumps(d,ensure_ascii=False,indent=2)))

    def select_video(self):
        p=filedialog.askopenfilename(filetypes=[('手机视频','*.mp4 *.mov'),('所有文件','*.*')])
        if p:self.video.set(p)

    def select_photo(self):
        p=filedialog.askopenfilename(filetypes=[('照片','*.jpg *.jpeg *.png *.bmp *.tif *.tiff'),('所有文件','*.*')])
        if p:self.photo.set(p)

    def refresh(self,project):
        project=Path(project).resolve()
        manifest=open_project(project);self.project.set(str(project));self.last_result=None
        self.combo['values']=['auto']+[m['id'] for m in manifest['models']];self.model.set('auto')
        self.log('模型统计：'+json.dumps(manifest['models'],ensure_ascii=False))
        self.status.set(f'地图已加载，共 {len(manifest["models"])} 个独立模型。')
        (BASE/'ui_state.json').write_text(json.dumps({'project':str(project)},ensure_ascii=False),encoding='utf-8')
        self.map_panel.load(project)
        history=list((project/'queries').glob('*/result.json'))
        if history:
            latest=max(history,key=lambda p:p.stat().st_mtime)
            try:self.present_result(json.loads(latest.read_text(encoding='utf-8')),latest)
            except Exception as e:self.log('已有定位结果未加载：'+str(e))

    def open(self):
        p=filedialog.askdirectory(title='选择包含 project.json 的地图目录')
        if p:
            try:self.refresh(Path(p))
            except Exception as e:messagebox.showerror('无法打开',str(e))

    def new_project(self,prefix):
        return BASE/'projects'/f'{prefix}_{time.strftime("%Y%m%d_%H%M%S")}'

    def build(self):
        if not self.video.get():messagebox.showinfo('需要视频','请先选择 MP4 或 MOV 视频。');return
        try:fps=float(self.fps.get());maximum=int(self.maxframes.get())
        except ValueError:messagebox.showerror('参数错误','帧数设置必须是数字。');return
        project=self.new_project('map');video=self.video.get();gpu=self.gpu.get()
        self.task(lambda r:reconstruct(video,project,r,fps,maximum,gpu),lambda m:self.refresh(project))

    def import_old(self):
        p=filedialog.askdirectory(title='选择包含 images 和 processing/sparse 的旧结果目录')
        if not p:return
        project=self.new_project('import')
        self.task(lambda r:import_existing(p,project,r),lambda m:self.refresh(project))

    def locate(self):
        if not self.project.get() or not self.photo.get():messagebox.showinfo('需要地图和照片','请先加载地图并选择定位照片。');return
        project=self.project.get();photo=self.photo.get();model=self.model.get();gpu=self.gpu.get()
        self.invalidate_result()
        def done(result):
            self.present_result(result,Path(result['session'])/'result.json')
            if result['status']!='success':
                messagebox.showinfo('定位未成功',result['reason'])
        self.task(lambda r:localize(project,photo,r,model,gpu),done)

    def present_result(self,result,path):
        self.photo.set(result.get('source_photo',''))
        self.map_panel.load(self.project.get(),path)
        self.last_result=dict(result,session=str(Path(path).resolve().parent))
        if result['status']=='success':
            self.model.set(result['pose']['model_id'])
            self.status.set('照片定位通过。请在用户地图核对参考区域、位置和方向。')
        else:self.status.set(result.get('reason','定位未通过。'))
        self.log(json.dumps(result,ensure_ascii=False,indent=2));self.tabs.select(self.map_panel)

    def open_result(self):
        if not self.project.get():messagebox.showinfo('需要地图','请先打开地图项目。');return
        p=filedialog.askopenfilename(title='选择已有定位的 result.json',initialdir=str(Path(self.project.get())/'queries'),filetypes=[('定位结果','result.json'),('JSON','*.json')])
        if not p:return
        try:self.present_result(json.loads(Path(p).read_text(encoding='utf-8')),p)
        except Exception as e:messagebox.showerror('无法加载',str(e))

    def open_visual_navigation(self):
        import webbrowser
        from urllib.request import urlopen
        from urllib.parse import urlsplit
        try:
            info=json.loads((BASE/'mobile_connection.json').read_text(encoding='utf-8'))
            if Path(info['project']).resolve()!=Path(self.project.get()).resolve():raise ValueError('手机服务打开的不是当前项目，请先关闭旧服务并重新启动手机端')
            url=info['urls'][0];parts=urlsplit(url)
            with urlopen(f'{parts.scheme}://{parts.netloc}/api/state?{parts.query}',timeout=2) as response:
                if response.status!=200:raise ValueError('手机服务未连接')
            webbrowser.open(f'{parts.scheme}://{parts.netloc}/navigation-admin.html?{parts.query}')
        except Exception as e:messagebox.showinfo('实景导航设置',str(e)+'\n请先双击“启动手机端.cmd”，再点击此入口。')

    def edit_map(self):
        try:
            open_project(self.project.get())
            def saved():self.map_panel.route=None;self.map_panel.refresh()
            MapEditor(self.root,self.project.get(),saved)
        except Exception as e:messagebox.showerror('无法打开设置',str(e))

    def expand_map(self):
        if not self.project.get():return
        win=tk.Toplevel(self.root);win.title('位置、朝向与参考画面');win.geometry('1200x800')
        panel=MapPanel(win);panel.pack(fill='both',expand=True)
        panel.load(self.project.get(),self.map_panel.result_path)

    def view(self):
        try:
            manifest=open_project(self.project.get())
            result=self.last_result
            mid=self.model.get()
            if mid=='auto':
                mid=result['pose']['model_id'] if result and result['status']=='success' else max(manifest['models'],key=lambda m:m['registered_images'])['id']
            args=[sys.executable,str(BASE/'app.py'),'view','--project',self.project.get(),'--model',mid]
            if result and result['status']=='success' and result['pose']['model_id']==mid:
                args+=['--result',str(Path(result['session'])/'result.json')]
            logs=Path(self.project.get())/'logs';logs.mkdir(exist_ok=True)
            with (logs/'viewer.log').open('w',encoding='utf-8') as f:
                subprocess.Popen(args,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            self.log('已启动三维窗口；如果未出现，请查看 logs/viewer.log。')
        except Exception as e:messagebox.showerror('无法显示',str(e))

    def folder(self):
        p=Path(self.last_result['session']) if self.last_result else Path(self.project.get())
        if p.is_dir():os.startfile(p)

    def close(self):
        if self.busy:
            self.cancel.set();self.status.set('正在取消当前处理，完成后可关闭窗口。');return
        self.root.destroy()


def launch():
    root=tk.Tk();App(root);root.mainloop()
