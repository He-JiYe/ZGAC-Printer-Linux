"""Code-drawn checkbox artwork with native ttk keyboard/variable semantics."""
from functools import lru_cache
import math
import struct
import tkinter as tk
import zlib


def rgb(value):
    return tuple(int(value[i:i+2],16) for i in (1,3,5))


def rounded(x,y,left,top,right,bottom,radius):
    cx=max(left+radius,min(x,right-radius))
    cy=max(top+radius,min(y,bottom-radius))
    return (x-cx)**2+(y-cy)**2<=radius**2


def segment_distance(x,y,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(x-a[0]-t*dx,y-a[1]-t*dy)


@lru_cache(maxsize=64)
def checkbox_png(selected,active,focused,disabled,scale):
    width,height=round(34*scale),round(28*scale)
    border=rgb('#d9e0e9' if disabled else '#1d4ed8' if active or focused else '#2563eb' if selected else '#b8c4d4')
    fill=rgb('#e8edf4' if disabled and selected else '#f5f7fa' if disabled else '#1d4ed8' if active and selected else '#2563eb' if selected else '#f2f6ff' if active else '#ffffff')
    tick=rgb('#a6b2c3' if disabled else '#ffffff')
    white,halo=rgb('#ffffff'),rgb('#dbeafe')
    def color(x,y):
        value=halo if focused and not disabled and rounded(x,y,1,1,27,27,8) else white
        if rounded(x,y,4,4,24,24,5):
            value=fill if rounded(x,y,5.3,5.3,22.7,22.7,3.7) else border
        if selected and min(segment_distance(x,y,(8.5,14),(12.2,17.5)),segment_distance(x,y,(12.2,17.5),(19.8,10)))<=1.15:
            value=tick
        return value
    raw=bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            samples=[color((x+(sx+.5)/4)/scale,(y+(sy+.5)/4)/scale) for sy in range(4) for sx in range(4)]
            raw.extend(round(sum(v[channel] for v in samples)/16) for channel in range(3))
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def checkbox_style(root,style):
    scale=round(max(1,float(root.tk.call('tk','scaling'))/(96/72)),2)
    images={}
    for name,flags in {'off':(False,False,False,False),'on':(True,False,False,False),
        'off_hover':(False,True,False,False),'on_hover':(True,True,False,False),
        'off_focus':(False,False,True,False),'on_focus':(True,False,True,False),
        'off_disabled':(False,False,False,True),'on_disabled':(True,False,False,True)}.items():
        images[name]=tk.PhotoImage(master=root,data=checkbox_png(*flags,scale),format='png')
    name='ZGCA.Check.indicator'
    # Styles are scoped to this Tcl interpreter; retain images for its lifetime.
    if name not in style.element_names():
        style.element_create(name,'image',images['off'],
            ('disabled','selected',images['on_disabled']),('disabled',images['off_disabled']),
            ('selected','focus',images['on_focus']),('focus',images['off_focus']),
            ('selected','active',images['on_hover']),('active',images['off_hover']),
            ('selected',images['on']))
        root._zgca_checkbox_images=images
    style.layout('TCheckbutton',[('Checkbutton.padding',{'sticky':'nswe','children':[
        (name,{'side':'left','sticky':''}),('Checkbutton.label',{'side':'left','sticky':'w'})]})])
    style.configure('TCheckbutton',background='white',foreground='#17243b',font=('sans',11),padding=(2,6))
    style.map('TCheckbutton',background=[('active','white')],foreground=[('disabled','#98a4b5')])


def responsive_row(frame,widgets,gap=8,right_last=False,two_columns=False):
    """Reflow controls when their measured text widths no longer fit."""
    layout={'compact':None}
    def arrange(event):
        compact=event.width<sum(w.winfo_reqwidth() for w in widgets)+gap*(len(widgets)-1)
        if compact==layout['compact']:return
        layout['compact']=compact
        for widget in widgets:widget.grid_forget()
        for column in range(len(widgets)+1):frame.columnconfigure(column,weight=0)
        if compact:
            columns=2 if two_columns else 1
            for column in range(columns):frame.columnconfigure(column,weight=1)
            for index,widget in enumerate(widgets):
                widget.grid(row=index//columns,column=index%columns,sticky='e' if right_last and index==len(widgets)-1 else 'w',padx=(0,gap if index%columns==0 and columns==2 else 0),pady=(0,6))
        else:
            frame.columnconfigure(len(widgets)-1 if right_last else len(widgets),weight=1)
            for index,widget in enumerate(widgets):
                widget.grid(row=0,column=index,sticky='e' if right_last and index==len(widgets)-1 else 'w',padx=(0,gap if index<len(widgets)-1 else 0))
    frame.bind('<Configure>',arrange)
