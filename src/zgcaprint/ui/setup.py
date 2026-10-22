"""First-run setup: bounded background download, retry and optional local import."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from zgcaprint.common.errors import PrintError
from zgcaprint.config.bootstrap import provision
from zgcaprint.ui.dialogs import fit_size


class SetupWindow:
    def __init__(self, home, provisioner=provision):
        self.home, self.provisioner = home, provisioner
        self.root = tk.Tk();self.root.title('ZGCA Linux 打印驱动 - 首次配置')
        self.root.configure(bg='#f3f5f9')
        self.root.geometry('%dx%d' % fit_size(self.root, 600, 390))
        self.root.minsize(*fit_size(self.root, 420, 300))
        self.events, self.cancelled = queue.Queue(), threading.Event()
        self.busy = self.success = self.closed = False
        self.root.columnconfigure(0, weight=1);self.root.rowconfigure(0, weight=1)
        body = ttk.Frame(self.root, padding=28);body.grid(row=0, column=0, sticky='nsew')
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text='欢迎使用 ZGCA Linux 打印驱动', font=('', 17, 'bold')).grid(row=0, sticky='w', pady=(0, 16))
        self.explanation = ttk.Label(body, text='请连接校园内网。客户端将从学校下载已验证的官方安装包，读取必要配置，不运行原厂程序。', justify='left', wraplength=500)
        self.explanation.grid(row=1, sticky='ew', pady=(0, 18))
        self.message = tk.StringVar(value='正在准备首次配置…')
        self.status = ttk.Label(body, textvariable=self.message, wraplength=500, justify='left')
        self.status.grid(row=2, sticky='ew', pady=(0, 14))
        self.progress = ttk.Progressbar(body, mode='indeterminate');self.progress.grid(row=3, sticky='ew')
        body.rowconfigure(4, weight=1)
        self.note = ttk.Label(body, text='仅首次需要下载。已验证的版本会在本机缓存；学校当前使用 HTTP 服务。', wraplength=500, justify='left')
        self.note.grid(row=4, sticky='ew', pady=18)
        footer = ttk.Frame(self.root, padding=(24, 14));footer.grid(row=1, column=0, sticky='ew')
        footer.columnconfigure(0, weight=1)
        self.local = ttk.Button(footer, text='选择已有安装包', command=self.choose)
        self.local.grid(row=0, column=0, sticky='w')
        self.retry = ttk.Button(footer, text='重试', command=self.start);self.retry.grid(row=0, column=1, padx=8)
        ttk.Button(footer, text='关闭', command=self.close).grid(row=0, column=2)
        body.bind('<Configure>', self.resize)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(150, self.start);self.root.after(100, self.poll)

    def resize(self, event):
        for label in [self.explanation, self.status, self.note]:label.configure(wraplength=max(200, event.width-56))

    def choose(self):
        path = filedialog.askopenfilename(parent=self.root, title='选择已验证的官方安装包',
            filetypes=[('安装包', '*.zip *.pkg'), ('所有文件', '*')])
        if path:self.start(Path(path))

    def start(self, package=None):
        if self.busy or self.closed:return
        self.busy = True
        self.retry.state(['disabled']);self.local.state(['disabled']);self.progress.start(12)
        self.message.set('正在连接学校下载服务…')
        def worker():
            try:
                self.provisioner(self.home, progress=lambda text:self.events.put(('progress', text)),
                    cancelled=self.cancelled.is_set, package=package)
                self.events.put(('done', '首次配置完成。'))
            except (PrintError, OSError, ValueError) as error:
                message = str(error) if isinstance(error, PrintError) else '配置未完成，请检查校园网络、磁盘空间或文件权限后重试。'
                self.events.put(('error', message))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:return
        try:
            while True:
                kind, text = self.events.get_nowait();self.message.set(text)
                if kind in ['done', 'error']:
                    self.busy = False;self.progress.stop()
                    self.retry.state(['!disabled']);self.local.state(['!disabled'])
                    if kind == 'done':self.success = True;self.close();return
        except queue.Empty:pass
        self.root.after(100, self.poll)

    def close(self):
        self.closed = True;self.cancelled.set();self.root.destroy()


def configure(home):
    window = SetupWindow(home)
    window.root.mainloop()
    return window.success
