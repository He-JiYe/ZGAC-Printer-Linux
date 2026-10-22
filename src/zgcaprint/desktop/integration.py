"""Browser preview and OS-managed installation of the local printing queue."""
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import webbrowser

from zgcaprint.common.errors import PrintError
from zgcaprint.common.runtime import frozen, external_env
from zgcaprint.cups.installer import generate
from zgcaprint.printing.jobs import MAX_PDF, inspect_pdf
from zgcaprint.config.profile import private_dir, read_private_bytes


def preview_pdf(path, opener=None):
    try:
        path = Path(path).expanduser().resolve(strict=True)
        if not path.is_file() or path.stat().st_size > MAX_PDF:
            raise PrintError('请选择不超过 100 MB 的 PDF。')
        inspect_pdf(read_private_bytes(path, MAX_PDF, private=False))
    except FileNotFoundError:
        raise PrintError('本地 PDF 已不存在；已提交任务只保留回执，请打开原始 PDF 预览。') from None
    except OSError:
        raise PrintError('本地 PDF 无法读取，请检查文件路径和权限。') from None
    try:
        if opener:opened=opener(path.as_uri())
        elif frozen():
            result=subprocess.run(['/usr/bin/xdg-open',path.as_uri()],env=external_env(),
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,check=False)
            opened=result.returncode==0
        else:opened=webbrowser.open(path.as_uri())
    except (OSError,webbrowser.Error,subprocess.TimeoutExpired):opened=False
    if not opened:raise PrintError('无法启动默认浏览器，请手动在浏览器中打开这份 PDF。')


def queue_name(profile):
    return profile['queue']


def queue_installed(profile):
    try:
        r = subprocess.run(['/usr/bin/lpstat', '-v', queue_name(profile)], capture_output=True, text=True, timeout=5,env=external_env())
        return r.returncode == 0 and 'zgcaprint:/' in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def install_queue(home):
    """The desktop authentication agent handles the administrator password."""
    if not os.access('/usr/bin/pkexec',os.X_OK):
        raise PrintError('系统缺少管理员授权入口，请按使用说明运行生成的安装脚本。')
    folder = private_dir(Path(home)/'setup'/uuid.uuid4().hex)
    script = generate(home, folder/'install.sh')
    try:
        r = subprocess.run(['/usr/bin/pkexec', '/bin/sh', str(script)], capture_output=True, text=True, timeout=180,env=external_env())
    except (OSError, subprocess.TimeoutExpired):
        raise PrintError('打印入口安装未完成，请检查系统授权提示后重试。') from None
    if r.returncode != 0:
        raise PrintError('打印入口安装未完成。请检查系统授权；若更新中途失败，请重新运行更新或请管理员核对现有配置。')
    return True
