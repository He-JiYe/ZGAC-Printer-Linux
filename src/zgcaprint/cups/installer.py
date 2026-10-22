"""Generate a reviewable, offline CUPS installation bundle. Do not execute it."""
import json
import importlib.metadata
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil

from zgcaprint.common.errors import PrintError
from zgcaprint.config.profile import load_profile
from zgcaprint.common.runtime import frozen, resource_root
from zgcaprint.cups.payload import BACKEND_FILES, copy_backend_package


def generate(home, output):
    if os.getuid() < 1000:
        raise PrintError('打印队列仅支持 UID 不小于 1000 的普通桌面用户，请勿以 root 或系统账号生成安装脚本。')
    output = Path(output).resolve()
    if not output.parent.is_dir():
        raise PrintError('安装脚本的输出目录不存在。')
    profile = load_profile(home)
    queue = profile['queue']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', queue):
        raise PrintError('打印队列名称不受支持。')
    bundle = output.parent/(output.stem+'.files')
    bundle.mkdir(mode=0o700, exist_ok=False)
    payload=resource_root()/'backend_payload' if frozen() else None
    source=payload/'zgcaprint' if payload else Path(__file__).resolve().parents[1]
    pkg = bundle/'zgcaprint'
    copy_backend_package(source,pkg)
    shutil.copyfile(Path(home)/'printer.ppd', bundle/'printer.ppd')
    if payload:
        shutil.copytree(payload/'pypdf',bundle/'pypdf')
        shutil.copyfile(payload/'pypdf-LICENSE',bundle/'pypdf-LICENSE')
        shutil.copyfile(payload/'LICENCE',bundle/'LICENCE')
    else:
        import pypdf
        if tuple(int(v) for v in pypdf.__version__.split('.')) < (6,21,2):
            raise PrintError('请先更新应用环境中的 pypdf 到 6.21.2 或以上版本。')
        shutil.copytree(Path(pypdf.__file__).parent,bundle/'pypdf',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        distribution=importlib.metadata.distribution('pypdf')
        license_file=next(v for v in distribution.files if str(v).endswith('/licenses/LICENSE'))
        shutil.copyfile(distribution.locate_file(license_file),bundle/'pypdf-LICENSE')
        package_root=Path(__file__).resolve().parents[1]
        own_license=package_root.parent/'LICENCE'
        if not own_license.is_file():own_license=package_root.parent.parent/'LICENCE'
        if not own_license.is_file():
            distribution=importlib.metadata.distribution('zgcaprint')
            license_file=next(v for v in distribution.files if str(v).endswith('/LICENCE'))
            own_license=distribution.locate_file(license_file)
        shutil.copyfile(own_license,bundle/'LICENCE')
    account = pwd.getpwuid(os.getuid())
    (bundle/'cups.json').write_text(json.dumps({'uid': os.getuid(), 'queue': queue})+'\n')
    (bundle/'backend_runner.py').write_text("import sys\nsys.path.insert(0, '/usr/local/lib/zgcaprint-cups')\nfrom zgcaprint.cups.backend import run\nraise SystemExit(run())\n")
    # Neutral discovery/preview queue: never loads a profile, password or token.
    (bundle/'backend').write_text('#!/bin/sh\nexec /usr/bin/python3 -I /usr/local/lib/zgcaprint-cups/backend_runner.py "$@"\n')
    q = shlex.quote
    script = f'''#!/bin/sh
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# Generated for local UID {os.getuid()}. Review before running with sudo.
# Requires system packages: cups cups-client cups-filters python3.
# A checked PDF library and its BSD license are copied from this app's environment.
# This creates the browser/system print entry. The desktop client handles upload.
[ "$(id -u)" -eq 0 ] || {{ echo "请使用 sudo 执行此安装脚本。" >&2; exit 1; }}
/usr/bin/python3 -I -c 'import sys; sys.version_info >= (3,10) or sys.exit("系统 Python 须为 3.10 或以上，尚未修改打印入口。")'
/usr/bin/python3 -I - <<'PYCOMPAT'
import sys
if sys.version_info < (3,11):
    try:
        from typing_extensions import Self
    except ImportError:
        raise SystemExit('系统 Python 3.10 需要 python3-typing-extensions，尚未修改打印入口。')
PYCOMPAT
command -v lpadmin >/dev/null
test -f /etc/cups/cupsd.conf
grep -Eq '<Policy[[:space:]]+authenticated>' /etc/cups/cupsd.conf || {{ echo "缺少 authenticated 打印策略，停止安装。" >&2; exit 1; }}
src={q(str(bundle))}
[ -d "$src/zgcaprint" ]
/usr/bin/python3 -I - <<'PREFLIGHT'
import os,stat
from pathlib import Path
paths=[Path(p) for p in ['/usr','/usr/local','/usr/local/lib','/usr/lib','/usr/lib/cups','/usr/lib/cups/backend','/var/spool','/etc','/usr/local/lib/zgcaprint-cups','/etc/zgcaprint-cups.json','/usr/lib/cups/backend/zgcaprint','/var/spool/zgcaprint']]
application=Path('/usr/local/lib/zgcaprint-cups')
if application.exists() and not application.is_symlink():
    paths.extend(application.rglob('*'))
for path in paths:
    if not os.path.lexists(path):continue
    info=path.lstat()
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or info.st_uid!=0 or info.st_mode & 0o022:
        raise SystemExit('安装路径的类型、所有者或权限不安全，已停止。')
PREFLIGHT
if [ -e /etc/zgcaprint-cups.json ]; then
  previous_queue=$(/usr/bin/python3 -I -c 'import json,os,stat,sys; p="/etc/zgcaprint-cups.json"; s=os.lstat(p); assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and not s.st_mode & 0o022; d=json.load(open(p)); assert d.get("uid")==int(sys.argv[1]) and d.get("queue") in (sys.argv[2],sys.argv[2]+"_Linux"); print(d["queue"])' {os.getuid()} {q(queue)})
  if [ "$previous_queue" != {q(queue)} ] && lpstat -p {q(queue)} >/dev/null 2>&1; then
    echo "目标名称已被其他队列使用，停止。" >&2; exit 1
  fi
else
  previous_queue=''
  [ ! -e /usr/local/lib/zgcaprint-cups ] || {{ echo "存在未识别的安装，停止。" >&2; exit 1; }}
  [ ! -e /usr/lib/cups/backend/zgcaprint ]
  if lpstat -p {q(queue)} >/dev/null 2>&1; then
    echo "同名队列已存在，停止安装。" >&2; exit 1
  fi
fi
install -d -m 0755 /usr/local/lib/zgcaprint-cups
rm -rf /usr/local/lib/zgcaprint-cups/zgcaprint
for relative in {' '.join(q(name) for name in BACKEND_FILES)}; do
  install -d -o root -g root -m 0755 "/usr/local/lib/zgcaprint-cups/zgcaprint/$(dirname "$relative")"
  install -o root -g root -m 0644 "$src/zgcaprint/$relative" "/usr/local/lib/zgcaprint-cups/zgcaprint/$relative"
done
rm -rf /usr/local/lib/zgcaprint-cups/pypdf
cp -R "$src/pypdf" /usr/local/lib/zgcaprint-cups/pypdf
chown -R root:root /usr/local/lib/zgcaprint-cups/pypdf
find /usr/local/lib/zgcaprint-cups/pypdf -type d -exec chmod 0755 {{}} \\;
find /usr/local/lib/zgcaprint-cups/pypdf -type f -exec chmod 0644 {{}} \\;
install -o root -g root -m 0644 "$src/pypdf-LICENSE" /usr/local/lib/zgcaprint-cups/pypdf-LICENSE
install -o root -g root -m 0644 "$src/LICENCE" /usr/local/lib/zgcaprint-cups/LICENCE
install -o root -g root -m 0644 "$src/backend_runner.py" /usr/local/lib/zgcaprint-cups/backend_runner.py
install -o root -g root -m 0644 "$src/cups.json" /etc/zgcaprint-cups.json
install -o root -g root -m 0500 "$src/backend" /usr/lib/cups/backend/zgcaprint
install -d -o root -g root -m 0711 /var/spool/zgcaprint
lpadmin -p {q(queue)} -E -P "$src/printer.ppd" -v zgcaprint:/ \\
  -D {q(queue)} -o printer-is-shared=false -o ColorModel=Gray \\
  -o job-sheets-default=none,none -o printer-error-policy=stop-printer \\
  -o printer-op-policy=authenticated -u allow:{q(account.pw_name)}
if [ -n "$previous_queue" ] && [ "$previous_queue" != {q(queue)} ]; then
  pending_jobs=$(lpstat -W not-completed -o "$previous_queue")
  if [ -z "$pending_jobs" ]; then
    lpadmin -x "$previous_queue"
  else
    echo "旧队列尚有未完成任务，已保留，避免丢失。"
  fi
fi
echo "已添加本地队列 {queue}；不会修改默认打印机。"
echo "保持客户端运行并登录，浏览器选择此队列打印后按客户端设置自动提交。"
'''
    output.write_text(script)
    os.chmod(output, 0o700)
    return output
