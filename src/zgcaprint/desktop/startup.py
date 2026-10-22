"""Freedesktop user launcher/autostart; never stores credentials in Exec."""
import os
from pathlib import Path
import sys

from zgcaprint.common.errors import PrintError
from zgcaprint.common.runtime import frozen
from zgcaprint.config.profile import read_private_bytes

NAME = 'org.zgcaprint.Client.desktop'
MARKER = 'X-ZGCAPrint-Managed=true'


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
    command = [sys.executable]
    if not frozen():command.append(str(Path(__file__).resolve().parents[1]/'application/launcher.py'))
    command += ['--home',str(Path(home).resolve()),'gui']
    if allow_http:
        command.append('--allow-http')
    if background:
        command.append('--background')
    return '\n'.join(['[Desktop Entry]', 'Type=Application', 'Version=1.0',
        'Name=ZGCA Linux 打印驱动', 'Comment=接收浏览器打印任务并提交到校园打印服务',
        'Exec='+' '.join(quote_arg(v) for v in command), 'Icon=printer', 'Terminal=false',
        'Categories=Utility;Printing;', 'StartupNotify=false', MARKER, ''])


def managed(path):
    if path.is_symlink():
        raise PrintError('启动入口不能是符号链接。')
    if path.exists():
        data = read_private_bytes(path, 32768, owner=os.getuid(), private=False).decode('utf-8')
        if MARKER not in data.splitlines():
            raise PrintError('已有同名启动入口不属于本工具，未覆盖。')


def enabled():
    path = directory(True)/NAME
    try:
        managed(path)
        return path.is_file()
    except (OSError, PrintError, UnicodeError):
        return False


def install(home, allow_http=False, autostart=False, enable=True):
    path = directory(autostart)/NAME
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
