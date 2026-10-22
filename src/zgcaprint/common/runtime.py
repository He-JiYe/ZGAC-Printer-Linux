"""Source/frozen process paths; external tools use the system loader environment."""
import os
from pathlib import Path
import sys


def frozen():
    return bool(getattr(sys,'frozen',False))


def resource_root():
    return Path(sys._MEIPASS) if frozen() else Path(__file__).resolve().parent.parent


def external_env():
    env=os.environ.copy()
    if frozen():
        original=env.get('LD_LIBRARY_PATH_ORIG')
        if original:env['LD_LIBRARY_PATH']=original
        else:env.pop('LD_LIBRARY_PATH',None)
    return env


def pdf_command():
    if frozen():return [sys.executable,'_pdf-worker']
    return [sys.executable,'-I',str(resource_root()/'printing/pdf_worker.py')]


def tray_command():
    if frozen():return ['/usr/bin/python3','-I',str(resource_root()/'system_helpers/tray.py')]
    # The .deb launcher adds /usr/lib/zgcaprint to its own sys.path only.
    # A child started with -m cannot inherit that path; this helper is standalone.
    return [sys.executable,'-I',str(resource_root()/'desktop/tray.py')]


def keyring_command():
    return ['/usr/bin/python3','-I',str(resource_root()/'system_helpers/keyring_entry.py')]


def installation_kind():
    if frozen():return 'standalone'
    if resource_root()==Path('/usr/lib/zgcaprint/zgcaprint'):return 'package'
    return 'source'


def application_name():
    return {'package':'ZGCA Linux 打印驱动','source':'ZGCA Linux 打印驱动（开发版）',
        'standalone':'ZGCA Linux 打印驱动（独立版）'}[installation_kind()]
