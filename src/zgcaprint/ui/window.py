"""Compact local outbox with optional settings and a four-action tray menu."""
import os
from pathlib import Path
import queue
import subprocess
import time
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from zgcaprint.desktop import startup
from zgcaprint.printing import cache
from zgcaprint.printing.automation import AutoSubmitQueue
from zgcaprint.config.credentials import CredentialStore, forget_login, preferences, remember_login
from zgcaprint.desktop.integration import install_queue, preview_pdf, queue_installed, queue_name
from zgcaprint.ui.dialogs import ConfirmDialog, center, fit_size
from zgcaprint.common.errors import PrintError
from zgcaprint.printing.jobs import MAX_PDF, adopt_cups_jobs, discard_remote_status, job_dir, load_job, prepare, remove_job
from zgcaprint.config.profile import json_write, load_profile, private_dir, read_private, read_private_bytes
from zgcaprint.protocol.client import V5Client
from zgcaprint.desktop.resident import Instance
from zgcaprint.common.runtime import tray_command, external_env
from zgcaprint.desktop.tray import MENU_ACTIONS
from zgcaprint.ui.widgets import checkbox_style, responsive_row

BG, CARD, INK, MUTED, ACCENT = '#f3f5f9', '#ffffff', '#17243b', '#64748b', '#2563eb'
STATES = {'prepared':'待提交', 'submitted':'已提交', 'registering':'需核对登记',
          'registered':'可恢复提交', 'uploading':'可恢复上传', 'uploaded':'等待确认',
          'committing':'需核对状态', 'uncertain':'请核对网页'}
SENDABLE = {'prepared','registered','uploading','uploaded'}


class PrintClientApp:
    def __init__(self, home, allow_http=False, root=None, profile=None, store=None,
                 client_factory=V5Client, spool_base=Path('/var/spool/zgcaprint'),
                 auto_start=True, background=False, instance=None):
        self.home, self.allow_http = Path(home), allow_http
        self.profile = profile or load_profile(self.home)
        self.store = store or CredentialStore(self.profile['base_url'])
        self.client_factory, self.spool_base = client_factory, spool_base
        self.root = root or tk.Tk()
        self.instance, self.tray, self.tray_ready = instance, None, False
        self.tray_buffer = b''
        self.settings_window, self.dialog = None, None
        self.settings_body, self.settings_canvas = None, None
        self.prefs = preferences(self.home, self.profile['base_url'])
        self.cached = {'account':'', 'password':None}
        self.busy = self.logged_in = self.closed = self.importing = False
        self.events, self.controls, self.timers = queue.Queue(), [], set()
        self.table_snapshot = None
        self.jobs = self.read_jobs()
        existing = {j['id'] for j in self.jobs}
        existing.update(p.parent.name for p in (Path(spool_base)/str(os.getuid())/'jobs').glob('*/job.json'))
        self.automation = AutoSubmitQueue(existing)
        def string(value=''):return tk.StringVar(master=self.root, value=value)
        def boolean(value=False):return tk.BooleanVar(master=self.root, value=value)
        self.file_var, self.user, self.password = string(), string(self.prefs['account']), string()
        self.remember, self.auto_login = boolean(self.prefs['remember']), boolean(self.prefs['auto_login'])
        self.boot_login = boolean(startup.enabled())
        self.auto_submit = boolean(self.read_auto_setting())
        self.retention=string(cache.POLICIES[cache.read_policy(self.home,self.profile['base_url'])])
        self.next_cleanup=time.monotonic()+600
        self.copies, self.duplex, self.color = string('1'), string('单面'), string('黑白')
        self.status, self.summary, self.badge = string(''), string('请选择待提交任务'), string('未登录')
        self.settings_status, self.queue_status = string(''), string('正在检查打印入口…')
        self.build_ui();self.refresh()
        self.status.trace_add('write',self.status_changed)
        self.status_changed()
        self.user.trace_add('write', self.account_changed)
        self.file_var.trace_add('write',self.file_changed)
        self.schedule(100, self.poll);self.schedule(1200, self.watch)
        self.schedule(300, self.check_queue)
        if auto_start:
            self.start_tray();self.schedule(150, self.resident_poll)
            if background:self.schedule(1200, self.hide)
            if self.prefs['remember'] and self.prefs['auto_login'] and self.prefs['account']:
                self.schedule(250, self.login)

    def schedule(self, delay, callback):
        if self.closed:return
        def invoke():
            self.timers.discard(timer);callback()
        timer = self.root.after(delay, invoke);self.timers.add(timer)

    def read_auto_setting(self):
        try:
            value = read_private(self.home/'ui-settings.json')
            if value.get('server') == self.profile['base_url']:
                return value.get('auto_submit_cups') is True
        except (PrintError,OSError,ValueError):pass
        return True

    def save_auto_setting(self):
        json_write(self.home/'ui-settings.json', {'server':self.profile['base_url'],
                    'auto_submit_cups':self.auto_submit.get(),
                    'completed_retention':self.retention_policy()})

    def control(self, widget):
        self.controls.append(widget)
        if self.busy:widget.state(['disabled'])
        return widget

    def button(self, parent, text, command, style='TButton'):
        return self.control(ttk.Button(parent,text=text,command=command,style=style,width=-7))

    def set_busy(self, value):
        self.busy = value
        alive = []
        for widget in self.controls:
            if widget.winfo_exists():
                widget.state(['disabled' if value else '!disabled']);alive.append(widget)
        self.controls = alive
        if value:self.progress.grid();self.progress.start(12)
        else:self.progress.stop();self.progress.grid_remove()
        self.selection_changed()

    def styles(self):
        s = ttk.Style(self.root)
        if 'clam' in s.theme_names():s.theme_use('clam')
        s.configure('Card.TFrame',background=CARD)
        s.configure('TLabel',background=CARD,foreground=INK,font=('sans',10))
        s.configure('Muted.TLabel',foreground=MUTED)
        s.configure('Title.TLabel',font=('sans',15,'bold'))
        s.configure('Section.TLabel',font=('sans',11,'bold'))
        s.configure('TButton',padding=(12,7),font=('sans',10),background='#eef2f8',foreground=INK)
        s.map('TButton',background=[('active','#dce7f8')])
        s.configure('Primary.TButton',padding=(18,9),background=ACCENT,foreground='white',font=('sans',10,'bold'))
        s.map('Primary.TButton',background=[('disabled','#b7c4d7'),('active','#1d4ed8')],foreground=[('disabled','white')])
        s.configure('Gear.TButton',font=('DejaVu Sans',19),padding=(9,2))
        s.configure('TEntry',padding=6)
        s.configure('TCombobox',padding=4)
        checkbox_style(self.root,s)
        s.configure('Treeview',rowheight=31,font=('sans',10),background=CARD,fieldbackground=CARD,borderwidth=0)
        s.configure('Treeview.Heading',font=('sans',10,'bold'),padding=(8,7),background='#eef2f8')
        s.map('Treeview',background=[('selected','#dbeafe')],foreground=[('selected',INK)])

    def scroll_area(self, parent, row):
        viewport = tk.Frame(parent,bg=BG);viewport.grid(row=row,column=0,sticky='nsew')
        viewport.rowconfigure(0,weight=1);viewport.columnconfigure(0,weight=1)
        canvas = tk.Canvas(viewport,bg=BG,highlightthickness=0)
        canvas.grid(row=0,column=0,sticky='nsew')
        bar = ttk.Scrollbar(viewport,orient='vertical',command=canvas.yview)
        bar.grid(row=0,column=1,sticky='ns');canvas.configure(yscrollcommand=bar.set)
        body = tk.Frame(canvas,bg=BG);body.columnconfigure(0,weight=1)
        item = canvas.create_window(0,0,window=body,anchor='nw')
        def resize(event):
            canvas.itemconfigure(item,width=event.width,height=max(body.winfo_reqheight(),event.height))
        canvas.bind('<Configure>',resize)
        def body_resize(event):
            height=max(body.winfo_reqheight(),canvas.winfo_height())
            if int(float(canvas.itemcget(item,'height') or 0))!=height:canvas.itemconfigure(item,height=height)
            canvas.configure(scrollregion=(0,0,canvas.winfo_width(),height))
        body._fit_scroll=body_resize
        body.bind('<Configure>',body_resize)
        return canvas, body

    def card(self, parent, row, title):
        shell = tk.Frame(parent,bg=CARD,highlightthickness=1,highlightbackground='#e0e6ef')
        shell.grid(row=row,column=0,sticky='nsew',padx=18,pady=(14,0))
        if hasattr(parent,'_fit_scroll'):shell.bind('<Configure>',parent._fit_scroll)
        inner = ttk.Frame(shell,style='Card.TFrame',padding=14);inner.pack(fill='both',expand=True)
        if title:ttk.Label(inner,text=title,style='Section.TLabel').pack(anchor='w',pady=(0,10))
        return inner

    def build_ui(self):
        r = self.root;r.title('ZGCA 打印驱动');r.configure(bg=BG)
        width,height=fit_size(r,920,660);r.geometry(f'{width}x{height}')
        r.minsize(*fit_size(r,560,420));r.resizable(True,True);r.columnconfigure(0,weight=1);r.rowconfigure(1,weight=1)
        self.styles()
        header = ttk.Frame(r,style='Card.TFrame',padding=(20,12));header.grid(row=0,column=0,sticky='ew')
        header.columnconfigure(0,weight=1)
        ttk.Label(header,text='ZGCA 打印驱动',style='Title.TLabel').grid(row=0,column=0,sticky='w')
        self.badge_label = ttk.Label(header,textvariable=self.badge,style='Muted.TLabel',cursor='hand2')
        self.badge_label.grid(row=0,column=1,padx=12)
        self.badge_label.bind('<Button-1>',lambda e:self.open_settings())
        self.settings_button = ttk.Button(header,text='⚙',style='Gear.TButton',command=self.open_settings,takefocus=True,width=2)
        self.settings_button.grid(row=0,column=2)
        self.canvas, self.body = self.scroll_area(r,1);self.body.rowconfigure(1,weight=1)
        pdf = self.card(self.body,0,'添加 PDF')
        path_row = ttk.Frame(pdf,style='Card.TFrame');path_row.pack(fill='x')
        self.control(ttk.Entry(path_row,textvariable=self.file_var)).pack(side='left',fill='x',expand=True,padx=(0,8))
        self.button(path_row,'选择 PDF',self.choose_file).pack(side='right')
        options = ttk.Frame(pdf,style='Card.TFrame');options.pack(fill='x',pady=(10,0))
        copies_row=ttk.Frame(options,style='Card.TFrame')
        self.control(ttk.Spinbox(copies_row,from_=1,to=99,width=3,textvariable=self.copies)).pack(side='left')
        ttk.Label(copies_row,text='份').pack(side='left',padx=(5,4))
        option_widgets=[copies_row]
        for var,values,width in [(self.duplex,['单面','双面长边','双面短边'],10),(self.color,['黑白','彩色'],6)]:
            option_widgets.append(self.control(ttk.Combobox(options,textvariable=var,values=values,width=width,state='readonly')))
        option_widgets.append(self.button(options,'添加',self.prepare_file))
        responsive_row(options,option_widgets,right_last=True,two_columns=True)
        jobs = self.card(self.body,1,'')
        title = ttk.Frame(jobs,style='Card.TFrame');title.pack(fill='x',pady=(0,10))
        ttk.Label(title,text='打印任务',style='Section.TLabel').pack(side='left')
        self.button(title,'清除',self.remove_selected).pack(side='right')
        self.preview_button=self.button(title,'预览',self.preview)
        self.preview_button.pack(side='right',padx=6)
        table = ttk.Frame(jobs,style='Card.TFrame');table.pack(fill='both',expand=True)
        table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
        self.tree = ttk.Treeview(table,columns=('title','pages','options','state'),show='headings',height=5,selectmode='browse')
        for field,label,width,minimum in [('title','文档',290,140),('pages','页数',48,48),('options','打印设置',190,190),('state','状态',120,120)]:
            self.tree.heading(field,text=label);self.tree.column(field,width=width,minwidth=minimum,stretch=field=='title')
        self.tree.grid(row=0,column=0,sticky='nsew')
        sy = ttk.Scrollbar(table,orient='vertical',command=self.tree.yview);sy.grid(row=0,column=1,sticky='ns')
        sx = ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview);sx.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.tree.bind('<<TreeviewSelect>>',lambda e:self.selection_changed())
        self.tree.bind('<Delete>',lambda e:self.remove_selected())
        self.footer = tk.Frame(r,bg=CARD,highlightthickness=1,highlightbackground='#e0e6ef')
        self.footer.grid(row=2,column=0,sticky='ew',pady=(12,0));self.footer.columnconfigure(0,weight=1)
        self.status_label = tk.Label(self.footer,textvariable=self.status,bg=CARD,fg=MUTED,anchor='w',justify='left',font=('sans',10),height=2,wraplength=800)
        self.status_label.grid(row=0,column=0,columnspan=2,sticky='ew',padx=20,pady=(5,2))
        self.summary_label = tk.Label(self.footer,textvariable=self.summary,bg=CARD,fg=INK,anchor='w',justify='left',font=('sans',10),height=2,wraplength=500)
        self.summary_label.grid(row=1,column=0,sticky='ew',padx=20,pady=(0,10))
        self.submit_button = self.button(self.footer,'提交任务',self.send,'Primary.TButton')
        self.submit_button.grid(row=1,column=1,sticky='e',padx=20,pady=(0,10))
        self.progress = ttk.Progressbar(r,mode='indeterminate')
        self.progress.grid(row=3,column=0,sticky='ew');self.progress.grid_remove()
        self.context_menu = tk.Menu(r,tearoff=False)
        for label,command in MENU_ACTIONS:
            self.context_menu.add_command(label=label,command=lambda c=command:self.dispatch_action(c))
        r.bind('<Button-3>',self.popup_menu)
        r.bind('<Configure>',self.resize_footer)
        r.bind_all('<MouseWheel>',self.mousewheel);r.bind_all('<Button-4>',self.mousewheel);r.bind_all('<Button-5>',self.mousewheel)
        r.protocol('WM_DELETE_WINDOW',self.hide)

    def resize_footer(self,event):
        if event.widget is self.root:
            self.status_label.configure(wraplength=max(280,event.width-44))
            self.summary_label.configure(wraplength=max(160,event.width-220))

    def mousewheel(self,event):
        if isinstance(event.widget,(ttk.Treeview,ttk.Combobox,ttk.Spinbox)):return
        for body,canvas in [(self.body,self.canvas),(self.settings_body,self.settings_canvas)]:
            if body is None:continue
            widget = event.widget
            while widget is not None and widget is not body:widget=getattr(widget,'master',None)
            if widget is body or event.widget is canvas:
                amount = -1 if getattr(event,'num',None)==4 else 1 if getattr(event,'num',None)==5 else (-1 if event.delta>0 else 1)
                canvas.yview_scroll(amount,'units');return

    def popup_menu(self,event):
        try:self.context_menu.tk_popup(event.x_root,event.y_root)
        finally:self.context_menu.grab_release()
        return 'break'

    def dispatch_action(self,command):
        if command=='show':self.show()
        elif command=='settings':self.open_settings()
        elif command=='logout':self.logout()
        elif command=='quit':self.close()

    def open_settings(self):
        self.show()
        if self.dialog:self.dialog.close()
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.deiconify();self.settings_window.lift();return
        w = tk.Toplevel(self.root);self.settings_window=w
        w.withdraw();w.title('设置');w.transient(self.root);w.configure(bg=BG)
        w.columnconfigure(0,weight=1);w.rowconfigure(1,weight=1);w.minsize(*fit_size(w,420,420));w.resizable(True,True)
        head = ttk.Frame(w,style='Card.TFrame',padding=(18,14));head.grid(row=0,column=0,sticky='ew')
        ttk.Label(head,text='设置',style='Title.TLabel').pack(anchor='w')
        self.settings_canvas,self.settings_body=self.scroll_area(w,1)
        account = self.card(self.settings_body,0,'账号')
        fields = ttk.Frame(account,style='Card.TFrame');fields.pack(fill='x');fields.columnconfigure(1,weight=1)
        for i,(label,var,secret) in enumerate([('账号',self.user,False),('密码',self.password,True)]):
            ttk.Label(fields,text=label,style='Muted.TLabel').grid(row=i,column=0,sticky='w',padx=(0,14),pady=5)
            entry=self.control(ttk.Entry(fields,textvariable=var,show='●' if secret else ''))
            entry.grid(row=i,column=1,sticky='ew',pady=5)
            if secret:self.password_entry=entry
        checks = ttk.Frame(account,style='Card.TFrame');checks.pack(fill='x',pady=(8,0))
        remember=self.control(ttk.Checkbutton(checks,text='记住密码',variable=self.remember,command=self.toggle_remember))
        auto=self.control(ttk.Checkbutton(checks,text='自动登录',variable=self.auto_login,command=self.toggle_login))
        responsive_row(checks,[remember,auto],gap=18)
        actions=ttk.Frame(account,style='Card.TFrame');actions.pack(fill='x',pady=(8,0))
        self.button(actions,'登录',self.login,'Primary.TButton').pack(side='left')
        self.button(actions,'注销',self.logout).pack(side='left',padx=8)
        behavior=self.card(self.settings_body,1,'启动与打印')
        for label,var,callback in [('自动启动',self.boot_login,self.toggle_startup),('自动提交任务',self.auto_submit,self.toggle_submission)]:
            self.control(ttk.Checkbutton(behavior,text=label,variable=var,command=callback)).pack(anchor='w')
        retention_row=ttk.Frame(behavior,style='Card.TFrame');retention_row.pack(fill='x',pady=(8,0))
        retention_label=ttk.Label(retention_row,text='已提交记录')
        retention=self.control(ttk.Combobox(retention_row,textvariable=self.retention,values=list(cache.POLICIES.values()),state='readonly',width=15))
        responsive_row(retention_row,[retention_label,retention],gap=12);retention.bind('<<ComboboxSelected>>',lambda e:self.change_retention())
        self.button(behavior,'更新打印机',self.setup_queue).pack(anchor='w',pady=(12,0))
        self.queue_label=ttk.Label(behavior,textvariable=self.queue_status,style='Muted.TLabel',wraplength=380)
        self.queue_label.pack(anchor='w',pady=(8,0))
        behavior.bind('<Configure>',lambda e:self.queue_label.configure(wraplength=max(160,e.width)))
        bottom=ttk.Frame(w,style='Card.TFrame',padding=(18,10));bottom.grid(row=2,column=0,sticky='ew');bottom.columnconfigure(0,weight=1)
        settings_message=tk.Label(bottom,textvariable=self.settings_status,wraplength=300,justify='left',anchor='w',height=3,bg=CARD,fg=INK,font=('sans',10))
        settings_message.grid(row=0,column=0,sticky='ew',padx=(0,10))
        self.settings_done=ttk.Button(bottom,text='完成',command=self.close_settings)
        self.settings_done.grid(row=0,column=1,sticky='e')
        def resize_settings(event):
            if event.widget is w:settings_message.configure(wraplength=max(140,event.width-self.settings_done.winfo_reqwidth()-54))
        w.bind('<Configure>',resize_settings)
        w.protocol('WM_DELETE_WINDOW',self.close_settings);w.bind('<Escape>',lambda e:self.close_settings())
        center(w,self.root,*fit_size(w,520,700));w.deiconify()

    def close_settings(self):
        if self.settings_window is not None:
            self.settings_window.destroy();self.settings_window=None
            self.settings_body=self.settings_canvas=None
            self.controls=[w for w in self.controls if w.winfo_exists()]

    def status_changed(self,*args):
        if self.status.get():self.status_label.grid()
        else:self.status_label.grid_remove()

    def notify(self,text,error=False,settings=False):
        self.status.set(text);self.status_label.configure(fg='#b42318' if error else MUTED)
        if settings:self.settings_status.set(text)

    def read_jobs(self):
        result=[]
        for path in (self.home/'jobs').glob('*/job.json'):
            try:result.append(load_job(self.home,path.parent.name))
            except (PrintError,OSError,ValueError,KeyError):pass
        return sorted(result,key=lambda j:j.get('created_at',0),reverse=True)

    @staticmethod
    def job_status(job):return STATES.get(job['state'],job['state'])

    def refresh(self):
        self.jobs=self.read_jobs()
        snapshot=[(j['id'],j['state'],j.get('updated_at'),j.get('copies')) for j in self.jobs]
        if snapshot!=self.table_snapshot:
            selected=self.tree.selection();self.tree.delete(*self.tree.get_children())
            for job in self.jobs:
                side={1:'单面',2:'长边双面',3:'短边双面'}.get(job['duplex'],'未知')
                self.tree.insert('','end',iid=job['id'],values=(job['doc_name'],job['total_pages'],
                    f'{job["copies"]} 份 · {"黑白" if job["color"]==1 else "彩色"} · {side}',self.job_status(job)))
            for item in selected:
                if self.tree.exists(item):self.tree.selection_set(item)
            self.table_snapshot=snapshot
        self.selection_changed()

    def selection_changed(self):
        selected=self.tree.selection()
        job=next((j for j in self.jobs if selected and j['id']==selected[0]),None)
        has_pdf=bool(job and (job_dir(self.home,job['id'])/'document.pdf').is_file())
        if job:self.summary.set(f'{job["total_pages"]} 页 × {job["copies"]} 份 · {self.job_status(job)}'+(' · 仅回执' if not has_pdf else ''))
        else:self.summary.set('请选择待提交任务' if self.jobs else '暂无任务')
        self.submit_button.state(['!disabled' if job and job['state'] in SENDABLE and not self.busy else 'disabled'])
        can_preview=has_pdf if job else bool(self.file_var.get().strip())
        self.preview_button.state(['!disabled' if can_preview and not self.busy else 'disabled'])

    def file_changed(self,*args):
        selected=self.tree.selection()
        if selected:self.tree.selection_remove(*selected)
        self.selection_changed()

    def account_changed(self,*args):
        if self.logged_in and self.user.get().strip()!=self.cached['account']:
            self.logged_in=False;self.cached.update(account='',password=None);self.badge.set('未登录')
            self.automation.arm(self.read_jobs())

    def persist_login_options(self):
        if self.busy:return
        if not self.remember.get():
            def clear():
                forget_login(self.home,self.store);return {'message':'已停止记住密码。'}
            self.start(clear,'正在更新密码设置…',kind='settings');return
        if not self.logged_in or self.cached['account']!=self.user.get().strip():
            self.settings_status.set('登录后保存这些选项。');return
        account,secret=self.cached['account'],self.cached['password']
        save,automatic=self.remember.get(),self.auto_login.get()
        def work():
            if save:remember_login(self.home,self.store,account,secret,automatic)
            else:forget_login(self.home,self.store)
            return {'message':'登录选项已保存。'}
        self.start(work,'正在保存登录选项…',kind='settings')

    def toggle_remember(self):
        if not self.remember.get():self.auto_login.set(False)
        self.persist_login_options()

    def toggle_login(self):
        if self.auto_login.get():self.remember.set(True)
        self.persist_login_options()

    def toggle_submission(self):
        self.automation.arm(self.read_jobs())
        try:self.save_auto_setting();self.notify('自动提交已开启。' if self.auto_submit.get() else '自动提交已关闭。',settings=True)
        except (OSError,PrintError):self.notify('自动提交设置未能保存。',True,True)

    def retention_policy(self):
        return next((key for key,value in cache.POLICIES.items() if value==self.retention.get()),'day')

    def change_retention(self):
        try:
            self.save_auto_setting()
            if self.retention_policy()=='day':
                cache.prune(self.home,'day');self.refresh()
            self.notify('已保存；仅清理已提交记录。' if self.retention_policy()!='startup' else '下次启动时清理已提交记录。',settings=True)
        except (OSError,PrintError):self.notify('缓存设置或清理未完成，已有任务已保留。',True,True)

    def toggle_startup(self):
        try:
            startup.install(self.home,self.allow_http,autostart=True,enable=self.boot_login.get())
            startup.install(self.home,self.allow_http)
            self.notify('已开启自动启动。' if self.boot_login.get() else '已关闭自动启动。',settings=True)
        except (OSError,PrintError):
            self.boot_login.set(startup.enabled());self.notify('启动设置未更新，请检查用户目录权限。',True,True)

    def start(self,work,message,automatic=False,kind='operation'):
        if self.busy:return False
        self.set_busy(True);self.notify(message,settings=kind in ['login','settings'])
        def worker():
            try:result=work()
            except Exception as exc:
                if not isinstance(exc,PrintError):
                    import traceback
                    frames=' → '.join(f'{Path(f.filename).name}:{f.lineno}' for f in traceback.extract_tb(exc.__traceback__))
                    print(f'内部操作异常：{type(exc).__name__}（{frames}）',flush=True)
                result={'error':str(exc) if isinstance(exc,PrintError) else '操作未完成，请检查任务记录后重试。'}
            self.events.put({**result,'automatic':automatic,'kind':kind})
        threading.Thread(target=worker,daemon=True).start();return True

    def resolve_secret(self,account,supplied):
        secret=supplied
        if not secret and self.cached['account']==account:secret=self.cached['password']
        if not secret:secret=self.store.get(account)
        if not secret:raise PrintError('请输入密码，或解锁保存密码的系统钥匙串。')
        return secret

    def authenticate(self,account,supplied,save,automatic):
        if not account:raise PrintError('请填写打印账号。')
        secret=self.resolve_secret(account,supplied)
        client=self.client_factory(self.profile,self.allow_http)
        client.authenticate_client();client.verify_user(account,secret)
        note='已登录。'
        try:
            if save:remember_login(self.home,self.store,account,secret,automatic)
            else:forget_login(self.home,self.store)
        except PrintError as exc:note+=' '+str(exc)
        return client,secret,note

    def login(self):
        if self.busy:return
        account,supplied=self.user.get().strip(),self.password.get()
        save,automatic=self.remember.get(),self.auto_login.get();self.password.set('')
        def work():
            _,secret,note=self.authenticate(account,supplied,save,automatic)
            return {'account':account,'password':secret,'message':note}
        self.start(work,'正在登录…',kind='login')

    def logout(self):
        if self.busy:
            self.show();self.notify('请等待当前操作完成后再注销。');return
        if self.dialog:self.dialog.close()
        self.cached.update(account='',password=None);self.password.set('')
        self.logged_in=False;self.badge.set('未登录');self.auto_login.set(False)
        self.automation.arm(self.read_jobs())
        try:
            prefs=preferences(self.home,self.profile['base_url'])
            json_write(self.home/'preferences.json',{'server':self.profile['base_url'],**prefs,'auto_login':False})
            self.notify('',settings=True)
        except (PrintError,OSError,ValueError):self.notify('下次自动登录设置未能保存，请检查本地配置。',True,True)

    def choose_file(self):
        path=filedialog.askopenfilename(parent=self.root,title='选择 PDF',filetypes=[('PDF 文件','*.pdf'),('所有文件','*')])
        if path:self.file_var.set(path)

    def prepare_file(self):
        if self.busy:return
        try:
            path=Path(self.file_var.get());copies=int(self.copies.get())
            duplex={'单面':1,'双面长边':2,'双面短边':3}[self.duplex.get()]
            color=1 if self.color.get()=='黑白' else 2
            if not self.file_var.get().strip():raise PrintError('请先选择 PDF。')
        except (ValueError,KeyError,PrintError) as exc:
            self.notify(str(exc) if isinstance(exc,PrintError) else '请检查份数和打印设置。',True);return
        def work():
            job=prepare(self.home,read_private_bytes(path,MAX_PDF,private=False),path.name,copies,duplex,color)
            return {'prepared':job['id'],'message':'已添加到待提交任务。'}
        self.start(work,'正在读取 PDF…',kind='prepare')

    def preview(self):
        selected=self.tree.selection()
        path=job_dir(self.home,selected[0])/'document.pdf' if selected else self.file_var.get()
        if selected and not path.is_file():
            self.notify('该任务仅保留提交回执，本地 PDF 已清理。请重新选择原始 PDF 预览。');return
        if not path:self.notify('请先选择 PDF 或任务。');return
        def work():
            preview_pdf(path);return {'message':'已在浏览器打开 PDF。'}
        self.start(work,'正在打开预览…')

    def confirm(self,title,job,rows,accept_text,callback):
        self.close_settings()
        if self.dialog is not None:
            self.dialog.window.lift();return
        self.dialog=ConfirmDialog(self.root,title,job['doc_name'],rows,accept_text,callback,
                                  lambda dialog:setattr(self,'dialog',None))

    def send(self,job_id=None,automatic=False):
        if self.busy:return
        if job_id is None:
            selected=self.tree.selection()
            if not selected:self.notify('请选择待提交任务。');return
            job_id=selected[0]
        try:job=load_job(self.home,job_id)
        except (PrintError,OSError,ValueError):self.refresh();self.notify('任务记录已变化，请重新选择。',True);return
        if job['state'] not in SENDABLE:
            self.notify('任务已提交。' if job['state']=='submitted' else '请先在网页核对该任务的服务器状态。');return
        if not self.logged_in or self.cached['account']!=self.user.get().strip() or not self.cached['password']:
            self.open_settings();self.settings_status.set('请先登录，再提交选中的任务。');self.password_entry.focus_set();return
        if automatic:return self.begin_submission(job_id,True)
        side={1:'单面',2:'双面长边',3:'双面短边'}[job['duplex']]
        self.confirm('确认提交',job,[('纸张与页数',f'{job["page_size"]} · {job["total_pages"]} 页'),
            ('打印设置',f'{"黑白" if job["color"]==1 else "彩色"} · {side}'),('份数',str(job['copies']))],
            '确认提交',lambda:self.begin_submission(job_id,False))

    def begin_submission(self,job_id,automatic):
        if self.busy:return
        if not self.logged_in or not self.cached['password']:
            self.notify('请先登录。',True);return
        account,secret=self.cached['account'],self.cached['password']
        def work():
            result=self.client_factory(self.profile,self.allow_http).submit(self.home,job_id,account,secret)
            return {'message':f'提交成功 · 作业 {result["server_id"]}，可刷卡取件。'}
        return self.start(work,'正在提交任务…',automatic,kind='submit')

    def remove_selected(self):
        if self.busy:return
        selected=self.tree.selection()
        if not selected:self.notify('请选择要清除的本地记录。');return
        try:job=load_job(self.home,selected[0])
        except (PrintError,OSError,ValueError):self.refresh();return
        if job['state'] not in ['prepared','submitted']:
            self.notify('请先核对服务器状态，暂不能清除该记录。',True);return
        def remove():
            try:remove_job(self.home,job['id']);self.refresh();self.notify('本地记录已清除。')
            except (PrintError,OSError):self.notify('本地记录未能清除。',True)
        self.confirm('清除本地记录',job,[('影响范围','仅清除本机记录，不取消服务器任务。')],'清除',remove)

    def check_queue(self):
        installed=queue_installed(self.profile)
        self.queue_status.set(('已就绪 · ' if installed else '未安装 · ')+queue_name(self.profile))

    def setup_queue(self):
        def work():
            install_queue(self.home);return {'message':'打印机配置已更新。','queue_changed':True}
        self.start(work,'请在系统授权窗口完成管理员验证…',kind='settings')

    def poll(self):
        for _ in range(20):
            try:result=self.events.get_nowait()
            except queue.Empty:break
            if 'spool_imported' in result:
                self.importing=False;self.refresh();self.automation.observe(self.jobs,self.auto_submit.get())
                if result.get('spool_error'):self.notify(result['spool_error'],True)
                continue
            self.set_busy(False)
            login_success='password' in result and result.get('kind')=='login'
            if 'password' in result:
                self.cached.update(account=result['account'],password=result.pop('password'))
                self.logged_in=True;self.badge.set('已登录')
            text=result.get('error',result.get('message','操作完成。'))
            if login_success:text=text.removeprefix('已登录。').strip()
            if result.get('automatic'):
                self.automation.finished('error' not in result)
                if 'error' in result:
                    self.auto_submit.set(False)
                    try:self.save_auto_setting()
                    except (OSError,PrintError):pass
                    text+=' 自动提交已暂停。'
            self.notify(text,error='error' in result,settings=result.get('kind') in ['login','settings'])
            self.refresh()
            if result.get('prepared'):
                self.automation.observe(self.jobs,self.auto_submit.get())
                self.tree.selection_set(result['prepared']);self.tree.see(result['prepared'])
            if result.get('queue_changed'):self.check_queue()
        self.schedule(200,self.poll)

    def watch(self):
        if not self.importing:
            self.importing=True
            def import_spool():
                error=None
                try:adopt_cups_jobs(self.home,self.spool_base)
                except PrintError as exc:error=str(exc)
                except (OSError,ValueError):error='本地打印任务读取失败，暂存文档已保留。'
                finally:self.events.put({'spool_imported':True,'spool_error':error})
            threading.Thread(target=import_spool,daemon=True).start()
        self.refresh();self.automation.observe(self.jobs,self.auto_submit.get())
        logged=self.logged_in and self.user.get().strip()==self.cached['account'] and bool(self.cached['password'])
        job_id=self.automation.take(logged,self.busy or self.dialog is not None)
        if job_id:
            if not self.send(job_id,automatic=True):
                self.automation.finished(False);self.auto_submit.set(False)
                try:self.save_auto_setting()
                except (OSError,PrintError):pass
        elif self.automation.pending and not logged and not self.busy:self.notify('有新打印任务，请从设置中登录。')
        if not self.busy and self.dialog is None and time.monotonic()>=self.next_cleanup:
            self.next_cleanup=time.monotonic()+600
            try:
                if cache.prune(self.home,self.retention_policy()):self.refresh()
            except (PrintError,OSError,ValueError):self.notify('缓存清理未完成，请保留记录后检查本地配置。',True)
        self.schedule(1500,self.watch)

    def start_tray(self):
        try:
            self.tray=subprocess.Popen(tray_command(),env=external_env(),
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            os.set_blocking(self.tray.stdout.fileno(),False)
        except OSError:self.tray=None

    def resident_poll(self):
        if self.instance and self.instance.activated():self.show()
        if self.tray is not None:
            try:
                self.tray_buffer=(self.tray_buffer+os.read(self.tray.stdout.fileno(),4096))[-4096:]
                while b'\n' in self.tray_buffer:
                    command,self.tray_buffer=self.tray_buffer.split(b'\n',1)
                    if command==b'ready':self.tray_ready=True
                    else:self.dispatch_action(command.decode('ascii',errors='ignore'))
                    if self.closed:return
                if self.tray.poll() is not None:
                    self.tray_ready=False
                    if self.root.state()=='withdrawn':self.show()
            except BlockingIOError:pass
        self.schedule(200,self.resident_poll)

    def show(self):
        self.root.deiconify();self.root.lift();self.root.focus_force()

    def hide(self):
        if self.dialog:self.dialog.close()
        self.close_settings()
        if self.tray_ready:self.root.withdraw()
        else:self.root.iconify()

    def close(self):
        if self.busy:
            self.show();self.notify('请等待当前操作完成后再退出。');return
        if self.dialog:self.dialog.close()
        self.close_settings()
        self.closed=True;self.cached.update(account='',password=None);self.password.set('')
        if self.tray is not None:
            self.tray.stdin.close()
            try:self.tray.wait(timeout=1)
            except subprocess.TimeoutExpired:self.tray.terminate()
            self.tray.stdout.close()
        for timer in list(self.timers):
            try:self.root.after_cancel(timer)
            except tk.TclError:pass
        self.root.unbind_all('<MouseWheel>');self.root.unbind_all('<Button-4>');self.root.unbind_all('<Button-5>')
        self.root.destroy()


def run(home,allow_http=False,background=False):
    home=private_dir(Path(home).resolve());instance=Instance(home)
    try:
        if not instance.primary:return
        first_run=not (home/'profile.json').exists()
        if first_run:
            if not allow_http:raise PrintError('首次配置需要连接学校 HTTP 服务，请使用 gui --allow-http。')
            from zgcaprint.ui.setup import configure
            if not configure(home):return
            background=False
        profile=load_profile(home)
        discard_remote_status(home)
        cleanup_error=False
        try:cache.prune(home,cache.read_policy(home,profile['base_url']),on_start=True)
        except (PrintError,OSError,ValueError):cleanup_error=True
        app=PrintClientApp(home,allow_http,profile=profile,background=background,instance=instance)
        if first_run:app.schedule(200,app.open_settings)
        if cleanup_error:app.notify('缓存清理未完成，已有任务已保留。',True)
        app.root.mainloop()
    finally:instance.close()
