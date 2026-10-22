"""Minimal opaque IDs survive receipt cleanup to suppress CUPS retry duplicates."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re

from zgcaprint.common.errors import PrintError
from zgcaprint.config.profile import json_write, private_dir, read_private

MAX_IDS=50000


def completed_ids(home):
    path=Path(home)/'completed-index.json'
    if not os.path.lexists(path):return set()
    value=read_private(path)
    ids=value.get('ids')
    if value.get('schema')!=1 or not isinstance(ids,list) or len(ids)>MAX_IDS or any(not isinstance(v,str) or not re.fullmatch(r'[0-9a-f]{32}',v) for v in ids):
        raise PrintError('本地防重记录格式异常，请先保留任务并检查配置。')
    return set(ids)


@contextmanager
def locked_index(home):
    home=private_dir(home)
    fd=os.open(home/'completed-index.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise PrintError('本地防重记录正在更新，稍后再清理。') from None
        yield
    finally:os.close(fd)


def remember_completed(home,ids):
    home=private_dir(home)
    ids=set(ids)
    if any(not isinstance(v,str) or not re.fullmatch(r'[0-9a-f]{32}',v) for v in ids):raise PrintError('本地作业编号无效。')
    with locked_index(home):
        existing=completed_ids(home)
        if ids<=existing:return
        result=existing|ids
        if len(result)>MAX_IDS:raise PrintError('防重索引已达上限，已暂停自动清理并保留任务。')
        json_write(home/'completed-index.json',{'schema':1,'ids':sorted(result)})

