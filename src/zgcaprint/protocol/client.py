"""XZ v5 requests, transport and a conservative, resumable submission workflow."""
from datetime import datetime
import ftplib
import http.client
import io
import ipaddress
import json
import re
from pathlib import PurePosixPath
import socket
import ssl
from urllib.parse import quote, urlsplit
import uuid

from zgcaprint.protocol.crypto import decode_password, encode_password, signature
from zgcaprint.common.errors import PrintError, ServerRejected, UncertainSubmission
from zgcaprint.printing.jobs import encode_file, load_job, locked, set_state, verified_pdf

MAX_RESPONSE = 2 * 1024 * 1024


class V5Client:
    def __init__(self, profile, allow_http=False, transport=None):
        self.profile = profile
        self.allow_http = allow_http
        self.token = ''
        self.transport = transport
        self.base = urlsplit(profile['base_url'])
        if self.base.scheme not in ['http', 'https'] or not self.base.hostname or self.base.username or self.base.password or self.base.query or self.base.fragment:
            raise PrintError('服务器地址不受支持。')
        if self.base.scheme == 'http' and not allow_http:
            raise PrintError('当前服务器使用 HTTP。确认位于可信校园网络后，使用 --allow-http 明确启用。')

    def post(self, endpoint, body, mutation=False):
        if self.transport:
            reply = self.transport(endpoint, body, self.token)
        else:
            conn = (http.client.HTTPSConnection if self.base.scheme == 'https' else http.client.HTTPConnection)(
                self.base.hostname, self.base.port, timeout=20)
            try:
                raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                headers = {'Content-Type': 'application/json;charset=UTF-8', 'User-Agent': 'ZGCA Linux Print Client/0.1'}
                if self.token:
                    headers['Authorization'] = 'Bearer ' + self.token
                conn.request('POST', self.base.path.rstrip('/')+endpoint, raw, headers)
                resp = conn.getresponse()
                raw = resp.read(MAX_RESPONSE+1)
                if resp.status != 200 or len(raw) > MAX_RESPONSE:
                    raise PrintError('打印服务器返回了异常响应；未跟随任何重定向。')
                reply = json.loads(raw.decode('utf-8-sig'))
            except (OSError, http.client.HTTPException, ValueError, PrintError):
                if mutation:
                    raise UncertainSubmission('服务器可能已经收到作业操作，请先核对作业列表，勿重复登记。') from None
                raise PrintError('打印服务连接或响应异常，请检查校园网络和服务器配置。') from None
            finally:
                conn.close()
        if not isinstance(reply, dict) or 'Code' not in reply:
            if mutation:
                raise UncertainSubmission('作业响应格式异常，请先核对服务器作业列表。')
            raise PrintError('打印服务响应格式不受支持。')
        value = reply['Code']
        if not (type(value) is int and 0 <= value <= 9999 or isinstance(value, str) and re.fullmatch(r'[0-9]{1,4}', value)):
            if mutation:
                raise UncertainSubmission('作业状态码异常，请先核对网页，勿重复登记。')
            raise PrintError('打印服务状态码格式不受支持。')
        code = int(value)
        reply['Code'] = code
        if code not in [0, 21]:
            # Do not echo server messages that might contain supplied credentials.
            known = {1: '账号不存在', 2: '密码错误', 5: '账号已过期', 6: '账号已停用',
                     14: '页数超过限额', 15: '文档超过大小限制', 18: '打印额度不足',
                     70: '接口参数缺失', 71: '接口参数格式错误', 72: '请求签名未通过',
                     73: '服务器要求 POST 请求'}
            if endpoint == '/printfile' and code == 4:
                known[4] = '服务器未找到文件存储编号'
            if mutation and code > 73:
                raise UncertainSubmission('服务器返回未知作业状态，请先核对网页。')
            raise ServerRejected(code, endpoint, f'服务器拒绝请求（代码 {code}）：{known.get(code, "请联系打印管理员核对")}。')
        return reply

    def authenticate_client(self):
        p = self.profile
        reply = self.post('/getToken', {'type': 0, 'client_id': p['client_id'],
                         'client_secret': p['client_secret'], 'signature': signature('type=0', p['web_key'])})
        token = reply.get('data')
        if not isinstance(token, str) or not 1 <= len(token) <= 8192 or any(not 33 <= ord(c) <= 126 for c in token):
            raise PrintError('服务器没有返回支持的客户端令牌。')
        self.token = token

    def check(self):
        self.authenticate_client()
        return self.post('/test', {})

    def storages(self):
        reply = self.post('/filestorage', {'type': 7, 'signature': signature('type=7', self.profile['web_key'])})
        items = reply.get('List')
        if not isinstance(items, list) or not items:
            raise PrintError('服务器没有返回文件存储配置。')
        return items

    def verify_user(self, username, password):
        if not username or len(username) > 200 or any(c in username for c in '\r\n\0'):
            raise PrintError('账号格式无效。')
        encoded = encode_password(password, self.profile)
        return self.post('/login', {'type': 1, 'code': username, 'pwd': encoded, 'ischeckpwd': 1,
            'signature': signature(f'type=1&code={username}&pwd={encoded}', self.profile['web_key'])})

    def local_ip(self):
        # UDP connect chooses the route without sending a document or datagram.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((self.base.hostname, self.base.port or 80))
                address = sock.getsockname()[0]
            if address == '0.0.0.0':
                raise OSError('no route')
            return address
        except OSError:
            raise PrintError('无法确定连接打印服务器的本机 IP，请检查校园网络。') from None

    def choose_storage(self):
        for item in self.storages():
            if not isinstance(item, dict):
                continue
            # V5 enum: 2 FTP, 6 HTTP WebDAV, 7 HTTPS WebDAV.
            if item.get('StorageType') not in [2, 6, 7] or item.get('FileEncType', 0) not in [0, 1]:
                continue
            host = item.get('IP', item.get('Ip', item.get('Host', '')))
            if host not in self.profile.get('storage_allowed_hosts', []):
                continue
            try:
                port = int(item['Port'])
                storage_id = int(item['ID'])
                if not 1 <= port <= 65535 or storage_id <= 0:
                    continue
                password = decode_password(item['Password'], self.profile)
                return {**item, 'host': host, 'Port': port, 'password': password}
            except (KeyError, TypeError, ValueError, PrintError):
                continue
        raise PrintError('未找到已允许且受支持的文件存储。使用 doctor 查看脱敏诊断后配置允许的上传主机。')

    def registration(self, job, username, password):
        if not username or len(username) > 200 or any(c in username for c in '\r\n\0'):
            raise PrintError('账号格式无效。')
        encoded = encode_password(password, self.profile)
        body = {'type': 4, 'code': username, 'pwd': encoded, 'ischeckpwd': 1,
                'ip': self.local_ip(), 'mac': f'{uuid.getnode():012X}', 'host': socket.gethostname(),
                'filename': job['doc_name'], 'projectid': 0, 'directprintid': 0,
                'count': job['copies'], 'iscollate': job['collate'],
                'direction': job['orientation'], 'doubleprint': job['duplex'],
                'color': job['color'], 'papersize': job['page_type'],
                'papertype': job['page_size'], 'filesize': job['file_size'],
                'papersource': job['tray'], 'pagetotal': job['total_pages'],
                'a3pagecount': 0, 'a4pagecount': 0, 'otherpagecount': 0,
                'hbpages': 0, 'colorpages': 0, 'jobtype': 0, 'comment': ''}
        body['signature'] = signature(f'type=4&code={username}&pwd={encoded}', self.profile['web_key'])
        return body

    def upload(self, storage, remote_path, data):
        if not isinstance(remote_path, str) or not re.fullmatch(r'/PrintDir/[0-9]{8}/[A-Za-z0-9{}_-]{1,64}\.(pdf|dat)', remote_path):
            raise PrintError('上传路径无效。')
        kind = storage['StorageType']
        host, port = storage['host'], storage['Port']
        if host not in self.profile.get('storage_allowed_hosts', []):
            raise PrintError('上传主机不在允许列表。')
        if kind in [2, 6] and not self.allow_http:
            raise PrintError('未允许校园明文传输。')
        username, password = storage['UserName'], storage['password']
        if any(c in username+password for c in '\r\n\0'):
            raise PrintError('上传凭据格式无效。')
        if kind == 2:
            ftp = ftplib.FTP(timeout=30)
            try:
                ftp.connect(host, port)
                ftp.login(username, password)
                # Restrict data connections to the control peer (ftplib default).
                ftp.trust_server_pasv_ipv4_address = False
                for part in PurePosixPath(remote_path).parent.parts:
                    if part == '/':
                        ftp.cwd('/')
                        continue
                    try:
                        ftp.cwd(part)
                    except ftplib.error_perm:
                        ftp.mkd(part)
                        ftp.cwd(part)
                ftp.storbinary('STOR '+PurePosixPath(remote_path).name, io.BytesIO(data))
                ftp.quit()
            except (OSError, ftplib.Error):
                raise PrintError('文件上传未确认完成，可使用同一作业编号恢复，勿重新登记。') from None
            finally:
                ftp.close()
        else:
            import base64
            conn = (http.client.HTTPSConnection if kind == 7 else http.client.HTTPConnection)(host, port, timeout=30)
            prefix = str(storage.get('VirtualDirectory', '')).strip('/')
            if prefix and (not re.fullmatch(r'[A-Za-z0-9_./-]{1,200}', prefix) or any(v in ['.', '..', ''] for v in prefix.split('/'))):
                raise PrintError('服务器上传目录格式无效。')
            target = '/' + '/'.join(x.strip('/') for x in [prefix, remote_path] if x.strip('/'))
            headers = {'Authorization': 'Basic '+base64.b64encode((username+':'+password).encode()).decode(),
                       'Content-Type': 'application/octet-stream'}
            try:
                # Create parent collections in order; never follow redirects.
                parts = target.strip('/').split('/')
                for i in range(1, len(parts)):
                    conn.request('MKCOL', quote('/'+'/'.join(parts[:i])), headers=headers)
                    response = conn.getresponse()
                    response.read(MAX_RESPONSE)
                    if response.status not in [200, 201, 204, 405]:
                        raise PrintError('服务器拒绝创建上传目录。')
                conn.request('PUT', quote(target), data, headers)
                response = conn.getresponse()
                response.read(MAX_RESPONSE)
                if response.status not in [200, 201, 204]:
                    raise PrintError('服务器没有确认文件上传。')
            except (OSError, http.client.HTTPException):
                raise PrintError('文件上传未确认完成，可使用同一作业编号恢复。') from None
            finally:
                conn.close()

    def submit(self, home, job_id, username, password):
        with locked(home, job_id):
            job = load_job(home, job_id)
            if job['state'] == 'submitted':
                raise PrintError('该作业已经提交，拒绝重复提交。')
            if job['state'] not in ['prepared', 'registered', 'uploading', 'uploaded']:
                raise PrintError('该作业的服务器状态需要人工核对，不能自动重新登记。')
            if job['state'] != 'prepared' and job.get('account') and job['account'] != username:
                raise PrintError('恢复作业时必须使用最初提交的账号。')
            data = verified_pdf(home, job)
            self.authenticate_client()
            storage = self.choose_storage()
            sid = int(storage['ID'])
            enc = int(storage.get('FileEncType', 0))
            payload, suffix = encode_file(data, enc)
            if job['state'] == 'prepared':
                body = self.registration(job, username, password)
                set_state(home, job, 'registering', account=username)
                try:
                    response = self.post('/print', body, mutation=True)
                except UncertainSubmission:
                    set_state(home, job, 'uncertain', uncertain_step='registration')
                    raise
                except ServerRejected:
                    job.pop('account', None)
                    set_state(home, job, 'prepared')
                    raise
                server_id = response.get('SubmitJobId')
                if type(server_id) is not int or server_id <= 0:
                    set_state(home, job, 'uncertain', uncertain_step='registration')
                    raise UncertainSubmission('登记响应没有有效作业编号，请核对服务器作业列表。')
                path = f'/PrintDir/{datetime.now():%Y%m%d}/{{{uuid.uuid4()}}}.{suffix}'
                set_state(home, job, 'registered', server_id=server_id, remote_path=path,
                          storage_id=sid, file_enc_type=enc, pending_review=response['Code'] == 21)
            if job['storage_id'] != sid or job['file_enc_type'] != enc:
                raise PrintError('文件存储配置已变化，停止恢复并请管理员核对作业。')
            if job['state'] in ['registered', 'uploading']:
                set_state(home, job, 'uploading')
                self.upload(storage, job['remote_path'], payload)
                set_state(home, job, 'uploaded')
            body = {'type': 6, 'submitjobid': job['server_id'], 'filestorageid': sid,
                    'jobpath': job['remote_path'], 'state': 1, 'upload_tip': '',
                    'code': username, 'filename': job['doc_name'], 'fileenctype': enc,
                    'signature': signature(f'type=6&submitjobid={job["server_id"]}', self.profile['web_key'])}
            set_state(home, job, 'committing')
            try:
                self.post('/printfile', body, mutation=True)
            except ServerRejected as exc:
                set_state(home, job, 'uploaded', last_error_code=exc.code)
                raise
            except PrintError:
                set_state(home, job, 'uncertain', uncertain_step='commit')
                raise
            set_state(home, job, 'submitted')
            # Remove the document after confirmed server acceptance; keep receipt.
            from zgcaprint.printing.jobs import job_dir
            (job_dir(home, job_id)/'document.pdf').unlink(missing_ok=True)
            return job
