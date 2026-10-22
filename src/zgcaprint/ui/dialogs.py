"""Responsive owned dialogs with scrollable content and pinned actions."""
import tkinter as tk
from tkinter import ttk


def display_scale(window):
    return max(1,float(window.tk.call('tk','scaling'))/(96/72))


def fit_size(window,width,height):
    scale=display_scale(window)
    available_width=max(240,window.winfo_screenwidth()-round(64*scale))
    available_height=max(200,window.winfo_screenheight()-round(96*scale))
    return min(round(width*scale),available_width),min(round(height*scale),available_height)


def center(window,owner,width,height):
    owner.update_idletasks()
    width=min(width,window.winfo_screenwidth()-24)
    height=min(height,window.winfo_screenheight()-48)
    x=owner.winfo_rootx()+(owner.winfo_width()-width)//2
    y=owner.winfo_rooty()+(owner.winfo_height()-height)//2
    window.geometry(f'{width}x{height}+{max(0,min(x,window.winfo_screenwidth()-width))}+{max(0,min(y,window.winfo_screenheight()-height-40))}')


class ConfirmDialog:
    def __init__(self,owner,title,document,rows,accept_text,on_accept,on_close):
        self.on_accept,self.on_close=on_accept,on_close
        self.window=tk.Toplevel(owner);w=self.window
        w.withdraw();w.title(title);w.transient(owner);w.resizable(True,True);w.configure(bg='white')
        w.columnconfigure(0,weight=1);w.rowconfigure(1,weight=1)
        minimum=fit_size(w,360,240);w.minsize(*minimum)
        header=ttk.Frame(w,style='Card.TFrame',padding=(24,18,24,8))
        header.grid(row=0,column=0,sticky='ew')
        ttk.Label(header,text=title,style='Title.TLabel').pack(anchor='w')
        viewport=ttk.Frame(w,style='Card.TFrame');viewport.grid(row=1,column=0,sticky='nsew')
        viewport.columnconfigure(0,weight=1);viewport.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(viewport,bg='white',highlightthickness=0,height=1)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        bar=ttk.Scrollbar(viewport,orient='vertical',command=self.canvas.yview)
        bar.grid(row=0,column=1,sticky='ns');self.canvas.configure(yscrollcommand=bar.set)
        self.body=ttk.Frame(self.canvas,style='Card.TFrame',padding=(24,8,24,12))
        self.body.columnconfigure(1,weight=1)
        self.item=self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.document_label=ttk.Label(self.body,text=document,wraplength=380,justify='left')
        self.document_label.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,14))
        self.document_label.bind('<Configure>',self.resize_body)
        self.fields=[]
        for label,value in rows:
            key=ttk.Label(self.body,text=label,style='Muted.TLabel')
            content=ttk.Label(self.body,text=value,wraplength=280,justify='left')
            self.fields.append((key,content))
            key.bind('<Configure>',self.resize_body);content.bind('<Configure>',self.resize_body)
        self.footer=ttk.Frame(w,style='Card.TFrame',padding=(20,12))
        self.footer.grid(row=2,column=0,sticky='ew');self.footer.columnconfigure(0,weight=1)
        self.cancel_button=ttk.Button(self.footer,text='取消',command=self.close,width=-5)
        self.accept_button=ttk.Button(self.footer,text=accept_text,command=self.accept,style='Primary.TButton',width=-7)
        self.cancel_button.grid(row=0,column=0,sticky='e',padx=(0,8))
        self.accept_button.grid(row=0,column=1,sticky='e')
        self.canvas.bind('<Configure>',self.resize_content)
        self.body.bind('<Configure>',self.resize_body)
        self.footer.bind('<Configure>',self.resize_actions)
        w.bind('<Button-4>',lambda e:self.canvas.yview_scroll(-1,'units'))
        w.bind('<Button-5>',lambda e:self.canvas.yview_scroll(1,'units'))
        w.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-1 if e.delta>0 else 1,'units'))
        w.protocol('WM_DELETE_WINDOW',self.close);w.bind('<Escape>',lambda e:self.close())
        width,height=fit_size(w,480,320);w.geometry(f'{width}x{height}');w.update_idletasks()
        natural=header.winfo_reqheight()+self.body.winfo_reqheight()+self.footer.winfo_reqheight()+8
        _,maximum=fit_size(w,480,10000)
        center(w,owner,width,min(maximum,max(height,natural)))
        w.deiconify();w.grab_set();self.accept_button.focus_set()

    def resize_content(self,event):
        self.canvas.itemconfigure(self.item,width=event.width)
        available=max(100,event.width-48)
        self.document_label.configure(wraplength=available)
        label_width=max((key.winfo_reqwidth() for key,_ in self.fields),default=0)
        stacked=available-label_width-20<140*display_scale(self.window)
        for index,(key,value) in enumerate(self.fields):
            key.grid_forget();value.grid_forget()
            if stacked:
                key.grid(row=1+index*2,column=0,columnspan=2,sticky='w',pady=(8,2))
                value.grid(row=2+index*2,column=0,columnspan=2,sticky='ew',pady=(0,4))
                value.configure(wraplength=available)
            else:
                key.grid(row=1+index,column=0,sticky='nw',padx=(0,20),pady=5)
                value.grid(row=1+index,column=1,sticky='ew',pady=5)
                value.configure(wraplength=max(100,available-label_width-20))
        self.resize_body()

    def resize_body(self,event=None):
        height=max(self.body.winfo_reqheight(),self.canvas.winfo_height())
        if int(float(self.canvas.itemcget(self.item,'height') or 0))!=height:
            self.canvas.itemconfigure(self.item,height=height)
        self.canvas.configure(scrollregion=(0,0,self.canvas.winfo_width(),height))

    def resize_actions(self,event):
        compact=event.width<self.accept_button.winfo_reqwidth()+self.cancel_button.winfo_reqwidth()+56
        self.cancel_button.grid_configure(row=0,column=0,columnspan=2 if compact else 1,sticky='ew' if compact else 'e',padx=(0,0 if compact else 8))
        self.accept_button.grid_configure(row=1 if compact else 0,column=0 if compact else 1,columnspan=2 if compact else 1,sticky='ew' if compact else 'e',pady=(6 if compact else 0,0))

    def accept(self):
        callback=self.on_accept;self.close();callback()

    def close(self):
        if not self.window.winfo_exists():return
        self.window.grab_release();self.window.destroy();self.on_close(self)
