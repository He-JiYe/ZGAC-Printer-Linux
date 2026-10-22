"""Roomy native Tk PDF picker with a private, persistent last directory."""
from pathlib import Path
import os
import tkinter as tk
from tkinter import filedialog

from zgcaprint.common.errors import PrintError
from zgcaprint.config.profile import json_write, read_private
from zgcaprint.ui.dialogs import fit_size


def initial_directory(home):
    try:
        value=read_private(Path(home)/'file-dialog.json').get('last_directory')
        if isinstance(value,str) and 0<len(value)<=4096 and '\0' not in value:
            path=Path(value).expanduser()
            if path.is_dir() and os.access(path,os.R_OK|os.X_OK):return path
    except (PrintError,OSError,ValueError):pass
    documents=Path.home()/'Documents'
    return documents if documents.is_dir() and os.access(documents,os.R_OK|os.X_OK) else Path.home()


def remember_directory(home,selected):
    path=Path(selected).expanduser().absolute().parent
    if path.is_dir():json_write(Path(home)/'file-dialog.json',{'last_directory':str(path)})


def enlarge_file_dialog(parent):
    """Use the dialog's Tk class, never resize other application windows."""
    for window in parent.tk.splitlist(parent.tk.call('winfo','children',parent._root()._w)):
        if parent.tk.call('winfo','class',window)!='TkFDialog':continue
        width,height=fit_size(parent,1200,800)
        minimum=fit_size(parent,800,520)
        x=max(0,(parent.winfo_screenwidth()-width)//2)
        y=max(0,(parent.winfo_screenheight()-height)//2-20)
        parent.tk.call('wm','minsize',window,*minimum)
        parent.tk.call('wm','geometry',window,f'{width}x{height}+{x}+{y}')
        return True
    return False


def choose_pdf(parent,directory):
    timers=set();resized=False
    def resize():
        nonlocal resized
        if not resized:
            try:resized=enlarge_file_dialog(parent)
            except tk.TclError:pass
    for delay in [40,120,300]:timers.add(parent.after(delay,resize))
    try:
        return filedialog.askopenfilename(parent=parent,title='选择 PDF',
            initialdir=str(directory),filetypes=[('PDF 文件','*.pdf'),('所有文件','*')])
    finally:
        for timer in timers:
            try:parent.after_cancel(timer)
            except tk.TclError:pass
