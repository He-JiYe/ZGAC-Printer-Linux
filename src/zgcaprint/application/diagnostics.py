"""Offline runtime smoke check without campus profiles, credentials or spool data."""
import io
import platform
import tempfile
from pathlib import Path

from zgcaprint import __version__
from zgcaprint.protocol.crypto import twofish
from zgcaprint.common.errors import PrintError
from zgcaprint.printing.jobs import inspect_pdf


def check(gui=False):
    if twofish(bytes(16),bytes(16)).hex()!='9f589f5cf6122c32b6bfec2f2ae8c35a':
        raise PrintError('系统 Twofish 运行检查失败。')
    from pypdf import PdfWriter
    writer=PdfWriter();writer.add_blank_page(595.276,841.890)
    stream=io.BytesIO();writer.write(stream)
    info=inspect_pdf(stream.getvalue())
    result={'version':__version__,'python':platform.python_version(),'pdf':'ok','twofish':'ok','gui':'not checked'}
    if info['total_pages']!=1:raise PrintError('PDF 子进程运行检查失败。')
    if gui:
        from zgcaprint.ui import window as desktop
        old=desktop.queue_installed
        desktop.queue_installed=lambda profile:False
        app=None
        try:
            with tempfile.TemporaryDirectory(prefix='zgcaprint-runtime-check-') as directory:
                home=Path(directory)
                app=desktop.PrintClientApp(home,profile={'base_url':'https://runtime-check.invalid/services','queue':'TEST'},
                    spool_base=home/'isolated-spool',auto_start=False)
                app.root.update();app.open_settings();app.root.update();app.close_settings()
                from zgcaprint.ui.dialogs import ConfirmDialog
                dialog=ConfirmDialog(app.root,'界面检查','synthetic.pdf',[('页数','1')],'完成',lambda:None,lambda d:None)
                app.root.update();dialog.close();app.close();app=None
                result['gui']='ok'
        finally:
            desktop.queue_installed=old
            if app is not None:
                app.busy=False;app.close()
    return result
