"""CUPS backend: spool PDF to the user's client; never access credentials."""
import json
import os
from pathlib import Path
import pwd
import shlex
import stat
import sys

from zgcaprint.common.errors import PrintError
from zgcaprint.printing.jobs import MAX_PDF, prepare, unwrap_cups_pdf


def options(text):
    result = {}
    for word in shlex.split(text):
        if '=' in word:
            key, value = word.split('=', 1)
            result[key.lower()] = value
    return result


def printing_settings(opts):
    # Browsers often send IPP names; the imported PPD uses legacy option names.
    if 'duplex' in opts:
        duplex={'none':1,'duplexnotumble':2,'duplextumble':3}.get(opts['duplex'].lower())
    else:
        duplex={'one-sided':1,'two-sided-long-edge':2,'two-sided-short-edge':3}.get(opts.get('sides','one-sided').lower())
    mode=opts.get('colormodel',opts.get('print-color-mode',opts.get('output-mode','gray'))).lower()
    color={'gray':1,'grayscale':1,'monochrome':1,'bi-level':1,'auto':1,'rgb':2,'color':2}.get(mode)
    if duplex is None or color is None:
        raise PrintError('浏览器的单双面或颜色设置不受支持。')
    return duplex,color


def run(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) == 1:
        print('direct zgcaprint:/ "ZGCA" "ZGCA PDF review queue"')
        return 0
    if len(argv) not in [6, 7]:
        return 1
    stream = None
    try:
        if os.getuid() != 0:
            raise PrintError('系统打印后端须由 CUPS 按安装配置启动。')
        fd = os.open('/etc/zgcaprint-cups.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > 4096 or st.st_uid != 0 or st.st_mode & 0o022:
                raise PrintError('打印队列配置权限不符合要求。')
            cfg = json.loads(f.read(4097))
        account = pwd.getpwuid(int(cfg['uid']))
        if account.pw_uid < 1000 or argv[2] != account.pw_name:
            raise PrintError('该队列只供安装时指定的本机用户使用。')
        if len(argv) == 7:
            fd = os.open(argv[6], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            stream = os.fdopen(fd, 'rb')
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_PDF:
                raise PrintError('打印输入不是受支持的普通 PDF 文件。')
        else:
            stream = sys.stdin.buffer
        base = Path('/var/spool/zgcaprint')
        st = base.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise PrintError('系统暂存目录权限无效。')
        user_home = base/str(account.pw_uid)
        try:
            user_home.mkdir(mode=0o700)
            os.chown(user_home, account.pw_uid, account.pw_gid)
        except FileExistsError:
            st = user_home.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != account.pw_uid or st.st_mode & 0o077:
                raise PrintError('用户暂存目录权限无效。')
        # Drop privilege before parsing options, reading PDF bytes or writing jobs.
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        opts = options(argv[5])
        unsupported = [k for k in ['staple', 'staplelocation', 'booklet', 'finishings']
                       if opts.get(k, '').lower() not in ['', 'none', 'off', '3']]
        if unsupported:
            raise PrintError('第一版暂不支持装订或小册子选项。')
        duplex,color=printing_settings(opts)
        data = stream.read(MAX_PDF+1)
        data = unwrap_cups_pdf(data)
        job = prepare(user_home, data, argv[3], int(argv[4]), duplex, color,
                      dedup_token=f'{cfg["queue"]}:{argv[1]}', source='cups')
        print('INFO: PDF 已送至本地客户端，由用户设置决定自动或手动提交。', file=sys.stderr)
        print(f'ATTR: zgcaprint-local-job-id={job["id"]}', file=sys.stderr)
        return 0
    except (PrintError, OSError, ValueError, KeyError):
        print('ERROR: 本地 PDF 接收失败；尚未向服务器提交，请检查支持的打印选项和安装配置。', file=sys.stderr)
        return 1
    finally:
        if stream is not None and stream is not sys.stdin.buffer:
            stream.close()
