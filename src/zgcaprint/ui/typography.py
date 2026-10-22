"""Shared readable point sizes, preserving desktop font and DPI preferences."""
from tkinter import font


def configure_fonts(root):
    existing=getattr(root,'_zgca_fonts',None)
    if existing is not None:return existing
    default=font.nametofont('TkDefaultFont',root=root)
    native=default.cget('size')
    if native<0:native=round(-native/root.winfo_fpixels('1p'))
    size=max(12,native)
    for name in ['TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont',
                 'TkCaptionFont','TkSmallCaptionFont','TkIconFont','TkTooltipFont']:
        if name in font.names(root):font.nametofont(name,root=root).configure(size=size)
    family=default.cget('family')
    result={'body':default,
            'bold':font.Font(root=root,family=family,size=size,weight='bold'),
            'section':font.Font(root=root,family=family,size=size+2,weight='bold'),
            'title':font.Font(root=root,family=family,size=size+6,weight='bold')}
    root.option_add('*TCombobox*Listbox.font',str(default))
    root._zgca_fonts=result
    return result
