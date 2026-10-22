"""Retention applies only to confirmed submitted local receipts, never pending PDFs."""
import math
from pathlib import Path
import time

from zgcaprint.printing.completed import remember_completed
from zgcaprint.common.errors import PrintError
from zgcaprint.printing.jobs import load_job, remove_job
from zgcaprint.config.profile import read_private

POLICIES={'day':'保留一天','startup':'每次启动清理','forever':'一直保留'}


def read_policy(home,server):
    try:
        value=read_private(Path(home)/'ui-settings.json')
        if value.get('server')==server and value.get('completed_retention') in POLICIES:
            return value['completed_retention']
    except (PrintError,OSError,ValueError,TypeError):pass
    return 'day'


def prune(home,policy,on_start=False,now=None):
    if policy=='forever' or policy=='startup' and not on_start:return 0
    if policy not in POLICIES:raise PrintError('缓存保留选项无效。')
    now=time.time() if now is None else now
    candidates=[]
    for path in (Path(home)/'jobs').glob('*/job.json'):
        try:job=load_job(home,path.parent.name)
        except (PrintError,OSError,ValueError,KeyError):continue
        if job['state']!='submitted':continue
        submitted=job.get('submitted_at',job.get('updated_at',job.get('created_at')))
        if policy=='day' and (type(submitted) not in [int,float] or not math.isfinite(submitted) or now-submitted<86400):continue
        candidates.append(job['id'])
    if not candidates:return 0
    # Persist the duplicate guard before deleting any visible receipts.
    remember_completed(home,candidates)
    count=0
    for job_id in candidates:
        try:count+=bool(remove_job(home,job_id,only_submitted=True))
        except (PrintError,OSError,ValueError):continue
    return count
