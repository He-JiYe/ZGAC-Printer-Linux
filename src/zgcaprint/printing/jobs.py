"""Private, durable PDF outbox. Preparing a job never sends network requests."""
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
import zipfile

from pypdf import PdfReader, __version__ as pdf_version

from zgcaprint.common.errors import PrintError
from zgcaprint.common.runtime import pdf_command
from zgcaprint.printing.completed import completed_ids, remember_completed, locked_index
from zgcaprint.config.profile import json_write, private_dir, private_write, read_private, read_private_bytes

MAX_PDF = 100 * 1024 * 1024
PAPERS = {'A4': (9, 595.276, 841.890), 'A3': (8, 841.890, 1190.551),
          'A5': (11, 419.528, 595.276), 'Letter': (1, 612, 792), 'Legal': (5, 612, 1008)}


def unwrap_cups_pdf(data):
    """The reused PPD may ask cups-filters to surround PDF bytes with PJL."""
    if not data.startswith(b'%PDF-') and data.startswith(b'\x1b%-12345X'):
        pos = data.find(b'%PDF-', 0, 4096)
        end = data.rfind(b'%%EOF')
        if pos >= 0 and end > pos:
            return data[pos:end+5] + b'\n'
    return data


def _inspect_pdf(data):
    if tuple(int(v) for v in pdf_version.split(".")) < (6,21,2):
        raise PrintError("PDF 库版本过旧，请安装 pypdf 6.21.2 或更高的 6.x 版本。")
    if len(data) > MAX_PDF or not data.startswith(b'%PDF-'):
        raise PrintError('仅接收不超过 100 MB 的标准 PDF 文件。')
    try:
        pdf = PdfReader(io.BytesIO(data))
        if pdf.is_encrypted:
            raise PrintError('请先导出没有打开密码的 PDF。')
        count = len(pdf.pages)
        if not 1 <= count <= 2000:
            raise PrintError('PDF 页数须在 1 到 2000 之间。')
        sizes = set()
        for page in pdf.pages:
            w, h = sorted([float(page.mediabox.width), float(page.mediabox.height)])
            if abs(float(page.get('/UserUnit', 1))-1) > 0.001:
                raise PrintError('暂不支持自定义 UserUnit 的 PDF。')
            match = next((k for k, (_, pw, ph) in PAPERS.items() if abs(w-pw)<3 and abs(h-ph)<3), None)
            if not match:
                raise PrintError('目前支持 A3/A4/A5/Letter/Legal 标准纸张。')
            sizes.add(match)
        if len(sizes) != 1:
            raise PrintError('第一版不支持混合纸张尺寸，请分成独立 PDF。')
        paper = sizes.pop()
        first = pdf.pages[0]
        landscape = float(first.mediabox.width) > float(first.mediabox.height)
        if int(first.get('/Rotate', 0)) % 180:
            landscape = not landscape
        return {'total_pages': count, 'page_size': paper, 'page_type': PAPERS[paper][0],
                'orientation': 2 if landscape else 1}
    except PrintError:
        raise
    except Exception:
        raise PrintError('PDF 解析失败，请重新导出后重试。') from None


def inspect_pdf(data):
    if len(data)>MAX_PDF or not data.startswith(b'%PDF-'):
        raise PrintError('仅接收不超过 100 MB 的标准 PDF 文件。')
    try:
        result = subprocess.run(pdf_command(),
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False)
        if result.returncode != 0 or len(result.stdout)>4096:
            raise PrintError('PDF 解析超过资源限制或未能完成，请重新导出后重试。')
        value = json.loads(result.stdout)
        if 'error' in value:raise PrintError(value['error'])
        return value['info']
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        raise PrintError('PDF 解析未完成或超过时限，请重新导出后重试。') from None


def job_dir(home, job_id):
    if not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise PrintError('作业编号格式无效。')
    root = Path(home)/'jobs'/job_id
    if root.is_symlink():
        raise PrintError('作业目录不能是符号链接。')
    return root


def prepare(home, data, title, copies=1, duplex=1, color=1, dedup_token=None, source='manual'):
    if source not in ['manual', 'cups']:
        raise PrintError('不支持的作业来源。')
    if not 1 <= copies <= 99 or duplex not in [1, 2, 3] or color not in [1, 2]:
        raise PrintError('份数或打印选项无效。')
    info = inspect_pdf(data)
    # Strip control characters before displaying titles or placing them in JSON.
    title = ''.join(c for c in title if c.isprintable())[:200].strip() or 'document.pdf'
    root = private_dir(Path(home)/'jobs')
    digest = hashlib.sha256(data).hexdigest()
    job_id = uuid.uuid5(uuid.NAMESPACE_URL, str(dedup_token)+':'+digest).hex if dedup_token else uuid.uuid4().hex
    if (root/job_id/'job.json').exists():
        return load_job(home, job_id)
    target = private_dir(root/job_id)
    private_write(target/'document.pdf', data)
    meta = {'schema': 1, 'id': job_id, 'state': 'prepared', 'source': source, 'created_at': time.time(),
            'doc_name': title, 'file_size': len(data), 'sha256': digest,
            'copies': copies, 'duplex': duplex, 'color': color, 'collate': 1, 'tray': 1000,
            **info}
    json_write(target/'job.json', meta)
    return meta


def load_job(home, job_id):
    root = job_dir(home, job_id)
    job = read_private(root/'job.json')
    if job.get('id') != job_id:
        raise PrintError('作业记录与编号不一致。')
    try:
        if job['state'] not in ['prepared','submitted','registering','registered','uploading','uploaded','committing','uncertain'] or not isinstance(job['doc_name'],str) or len(job['doc_name'])>200:
            raise ValueError()
        if job['state'] in ['registered','uploading','uploaded','committing','submitted'] and (type(job.get('server_id')) is not int or job['server_id']<=0):raise ValueError()
        for key in ['total_pages','copies','duplex','color','file_size','orientation','page_type','collate','tray']:
            if type(job[key]) is not int:raise ValueError()
        if not 1<=job['total_pages']<=2000 or not 1<=job['copies']<=99 or job['duplex'] not in [1,2,3] or job['color'] not in [1,2] or job['page_size'] not in PAPERS or not re.fullmatch(r'[0-9a-f]{64}',job['sha256']):
            raise ValueError()
    except (KeyError,ValueError,TypeError):
        raise PrintError('本地作业记录格式无效。') from None
    return job


def verified_pdf(home, job):
    root = job_dir(home, job['id'])
    data = read_private_bytes(root/'document.pdf', MAX_PDF)
    if hashlib.sha256(data).hexdigest() != job['sha256']:
        raise PrintError('PDF 已被修改，拒绝提交；请重新创建作业。')
    info = inspect_pdf(data)
    if any(info[k] != job[k] for k in info):
        raise PrintError('PDF 与打印参数不一致。')
    if not 1 <= job['copies'] <= 99 or job['duplex'] not in [1, 2, 3] or job['color'] not in [1, 2]:
        raise PrintError('保存的打印选项无效。')
    return data


def set_state(home, job, state, **extra):
    now=time.time()
    if state=='submitted' and 'submitted_at' not in job:job['submitted_at']=extra.get('submitted_at',now)
    job.update(state=state, updated_at=now, **extra)
    json_write(job_dir(home, job['id'])/'job.json', job)


@contextmanager
def locked(home, job_id):
    root = job_dir(home, job_id)
    fd = os.open(root/'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PrintError('该作业正在由另一个进程处理。') from None
        yield
    finally:
        os.close(fd)


def encode_file(data, enc_type):
    if enc_type == 0:
        return data, 'pdf'
    if enc_type == 1:
        # The observed vendor method ZIP-compresses one document, then overwrites
        # its four-byte local-file signature. This is a format, not secure crypto.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('document.pdf', data)
        result = buf.getvalue()
        return b'\0\0\0\0' + result[4:], 'dat'
    raise PrintError('服务器要求尚未支持的文件加密类型。')


def remove_job(home, job_id, only_submitted=False):
    with locked(home, job_id):
        job = load_job(home, job_id)
        if only_submitted and job['state']!='submitted':return False
        if job['state']=='submitted':remember_completed(home,[job_id])
        if job['state'] in ['registering', 'registered', 'uploading', 'uploaded', 'committing', 'uncertain']:
            raise PrintError('该作业可能已登记到服务器，先在打印管理页面核对，不能直接清除记录。')
        root = job_dir(home, job_id)
        for name in ['document.pdf', 'job.json', 'lock']:
            (root/name).unlink(missing_ok=True)
        root.rmdir()
        return True


def adopt_cups_jobs(home, spool_base=Path('/var/spool/zgcaprint')):
    """Move completed, user-owned backend output into the local outbox."""
    source = Path(spool_base)/str(os.getuid())
    adopted = []
    completed=completed_ids(home)
    for p in (source/'jobs').glob('*/job.json'):
        job_id = p.parent.name
        with locked(source, job_id):
            job = load_job(source, job_id)
            if job['state'] != 'prepared':
                continue
            if job_id in completed:
                for name in ['document.pdf','job.json','lock']:(p.parent/name).unlink(missing_ok=True)
                p.parent.rmdir();continue
            data = verified_pdf(source, job)
            with locked_index(home):
                # A cleanup may have completed while the PDF was being checked.
                if job_id not in completed_ids(home):
                    target = job_dir(home, job_id)
                    if not (target/'job.json').exists():
                        private_dir(target)
                        private_write(target/'document.pdf', data)
                        json_write(target/'job.json', job)
                        adopted.append(job_id)
                    else:
                        existing = load_job(home, job_id)
                        if existing['sha256'] != job['sha256']:
                            raise PrintError('打印队列作业编号冲突。')
            for name in ['document.pdf', 'job.json', 'lock']:
                (p.parent/name).unlink(missing_ok=True)
            p.parent.rmdir()
    return adopted


def discard_remote_status(home):
    """Drop obsolete v0.3 web annotations while retaining every local receipt."""
    for path in (Path(home)/'jobs').glob('*/job.json'):
        try:
            with locked(home,path.parent.name):
                job=load_job(home,path.parent.name)
                if any(key in job for key in ['remote_state','remote_status','remote_checked_at']):
                    for key in ['remote_state','remote_status','remote_checked_at']:job.pop(key,None)
                    json_write(path,job)
        except (PrintError,OSError,ValueError,KeyError):
            continue
