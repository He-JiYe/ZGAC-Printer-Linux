"""Freedesktop user launcher/autostart; never stores credentials in Exec."""
import os
from pathlib import Path
import sys
import shlex
import stat
import uuid

from zgcaprint.common.errors import PrintError
from zgcaprint.common.runtime import frozen, installation_kind, application_name
from zgcaprint.config.profile import read_private_bytes, private_dir, private_write

NAME = 'org.zgcaprint.Client.desktop'
MARKER = 'X-ZGCAPrint-Managed=true'
SOURCE_NAME = 'org.zgcaprint.Development.desktop'
BINARY_NAME = 'org.zgcaprint.Standalone.desktop'


def entry_name():
    return {'package':NAME,'source':SOURCE_NAME,'standalone':BINARY_NAME}[installation_kind()]


def directory(autostart):
    if autostart:
        return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'autostart'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'applications'


def quote_arg(value):
    value = str(value)
    if any(ord(c)<32 for c in value):
        raise PrintError('启动入口路径含不支持的字符。')
    return '"' + ''.join('\\'+c if c in '\\"`$' else '%%' if c == '%' else c for c in value) + '"'


def content(home, allow_http=False, background=False):
    kind=installation_kind()
    command=['/usr/bin/zgcaprint'] if kind=='package' else [sys.executable]
    if kind=='source':command.append(str(Path(__file__).resolve().parents[1]/'application/launcher.py'))
    command += ['--home',str(Path(home).resolve()),'gui']
    if allow_http:
        command.append('--allow-http')
    if background:
        command.append('--background')
    return '\n'.join(['[Desktop Entry]', 'Type=Application', 'Version=1.0',
        'Name='+application_name(), 'Comment=接收浏览器打印任务并提交到校园打印服务',
        'Exec='+' '.join(quote_arg(v) for v in command), 'TryExec='+command[0].replace('\\','\\\\'), 'Icon=printer', 'Terminal=false',
        'Categories=Utility;', 'StartupNotify=false', MARKER, 'X-ZGCAPrint-InstallKind='+kind, ''])


def managed(path):
    if path.is_symlink():
        raise PrintError('启动入口不能是符号链接。')
    if path.exists():
        data = read_private_bytes(path, 32768, owner=os.getuid(), private=False).decode('utf-8')
        if MARKER not in data.splitlines():
            raise PrintError('已有同名启动入口不属于本工具，未覆盖。')


def enabled():
    path = directory(True)/entry_name()
    try:
        managed(path)
        return path.is_file()
    except (OSError, PrintError, UnicodeError):
        return False


def install(home, allow_http=False, autostart=False, enable=True):
    path = directory(autostart)/entry_name()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o022:
        raise PrintError('启动目录所有者或权限无效。')
    managed(path)
    if enable:
        # Preserve permissions of the user's shared applications/autostart dir.
        import tempfile
        fd, temporary = tempfile.mkstemp(prefix='.zgcaprint-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(content(home, allow_http, background=autostart))
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    else:
        path.unlink(missing_ok=True)
    return path


def legacy_source_entry(text):
    lines=text.splitlines()
    if MARKER not in lines:return False
    value=next((line[5:] for line in lines if line.startswith('Exec=')), '')
    try:args=shlex.split(value)
    except ValueError:return False
    if any(arg.startswith('/usr/lib/zgcaprint/') for arg in args):return False
    return any(arg.endswith('/src/zgcaprint/application/launcher.py') or
        arg.endswith('/zgcaprint/launcher.py') for arg in args) or any(
        args[index:index+2]==['-m','zgcaprint'] for index in range(len(args)))


def quarantine_legacy_sources(home):
    """Back up only obsolete managed source launchers sharing the package ID."""
    moved=[]
    for auto in [False,True]:
        path=directory(auto)/NAME
        if not path.exists() or path.is_symlink():continue
        info=path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o022:
            raise PrintError('旧启动入口所在目录权限无效，未修改。')
        data=read_private_bytes(path,32768,owner=os.getuid(),private=False)
        if not legacy_source_entry(data.decode('utf-8')):continue
        backup=private_dir(Path(home)/'launcher-backups')/(('autostart-' if auto else 'menu-')+uuid.uuid4().hex+'.desktop.bak')
        private_write(backup,data)
        path.unlink();moved.append(backup)
    return moved


def refresh_package_entries(home,allow_http):
    """Old per-user package entries gain TryExec so uninstall hides them."""
    if installation_kind()!='package':return
    for auto in [False,True]:
        path=directory(auto)/NAME
        if path.is_file():
            managed(path)
            install(home,allow_http,autostart=auto)
