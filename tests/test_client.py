import io
import json
import os
from pathlib import Path
import random
import struct
import zipfile

from pypdf import PdfWriter
import pytest

from zgcaprint.protocol.crypto import decode_password, encode_password, signature, twofish
from zgcaprint.common.errors import PrintError, UncertainSubmission
from zgcaprint.printing.jobs import adopt_cups_jobs, encode_file, inspect_pdf, job_dir, load_job, locked, prepare, remove_job, verified_pdf
from zgcaprint.config.profile import cpio_selected, private_dir, private_write, read_private
from zgcaprint.protocol.client import V5Client


@pytest.fixture
def profile():
    # Synthetic test material only. No original installer or campus secrets.
    return {'base_url': 'http://print.invalid:80/test/services',
            'web_key': 'test-only-key', 'client_id': 'test-client', 'client_secret': 'test-secret',
            'password_key_hex': '00'*16, 'password_mix_indices': [1, 4, 7, 11, 15, 19, 23, 30],
            'storage_allowed_hosts': ['print.invalid']}


def pdf_bytes(pages=1, w=595.276, h=841.890):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(w, h)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_twofish_published_zero_vector():
    assert twofish(bytes(16), bytes(16)).hex() == '9f589f5cf6122c32b6bfec2f2ae8c35a'
    assert twofish(bytes.fromhex('9f589f5cf6122c32b6bfec2f2ae8c35a'), bytes(16), True) == bytes(16)


@pytest.mark.parametrize('password', ['', 'example', 'x'*16, 'x'*17, 'x'*240, '中文密码123'])
def test_password_roundtrip_and_randomization(profile, password):
    a = encode_password(password, profile)
    b = encode_password(password, profile)
    assert a != b
    assert decode_password(a, profile) == password
    assert decode_password(b, profile) == password


@pytest.mark.parametrize('password', ['x'*241, 'contains\0nul'])
def test_password_limits(profile, password):
    with pytest.raises(PrintError):
        encode_password(password, profile)


@pytest.mark.parametrize('value', ['', 'A'*12, 'Z'*80, '../file'])
def test_reject_invalid_password_envelope(profile, value):
    with pytest.raises(PrintError):
        decode_password(value, profile)


def test_pdf_and_private_outbox(tmp_path):
    raw = pdf_bytes(2)
    job = prepare(tmp_path, raw, '测试文档.pdf', copies=2, duplex=2)
    assert job['total_pages'] == 2 and job['page_type'] == 9
    assert job['copies'] == 2 and job['duplex'] == 2
    assert verified_pdf(tmp_path, job) == raw
    for f in [job_dir(tmp_path, job['id'])/'document.pdf', job_dir(tmp_path, job['id'])/'job.json']:
        assert f.stat().st_mode & 0o077 == 0
    assert job_dir(tmp_path, job['id']).stat().st_mode & 0o077 == 0
    private_write(job_dir(tmp_path, job['id'])/'document.pdf', pdf_bytes(3))
    with pytest.raises(PrintError, match='修改'):
        verified_pdf(tmp_path, job)


def test_invalid_and_mixed_pdf():
    with pytest.raises(PrintError):
        inspect_pdf(b'not a PDF')
    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    writer.add_blank_page(842, 1191)
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(PrintError, match='混合'):
        inspect_pdf(out.getvalue())


def test_cups_pjl_wrapper_is_removed_without_losing_pdf_content():
    from zgcaprint.printing.jobs import unwrap_cups_pdf
    raw = pdf_bytes()
    wrapped = b'\x1b%-12345X@PJL JOB\n@PJL ENTER LANGUAGE = PDF\n'+raw+b'\x1b%-12345X@PJL EOJ\n'
    unwrapped = unwrap_cups_pdf(wrapped)
    assert inspect_pdf(unwrapped)['total_pages'] == 1
    assert unwrapped.startswith(b'%PDF-') and unwrapped.rstrip().endswith(b'%%EOF')
    assert unwrap_cups_pdf(raw) == raw


def test_encrypted_pdf_rejected():
    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    writer.encrypt('test')
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(PrintError, match='密码'):
        inspect_pdf(out.getvalue())


def test_spool_deduplicates_backend_retry(tmp_path):
    a = prepare(tmp_path, pdf_bytes(), 'one.pdf', dedup_token='queue:1')
    b = prepare(tmp_path, pdf_bytes(), 'one.pdf', dedup_token='queue:1')
    assert a['id'] == b['id']


def test_job_path_and_symlink_rejection(tmp_path):
    with pytest.raises(PrintError):
        job_dir(tmp_path, '../../outside')
    target = tmp_path/'real'
    target.mkdir()
    link = tmp_path/'link'
    link.symlink_to(target)
    with pytest.raises(PrintError):
        private_dir(link)
    f = tmp_path/'profile.json'
    f.write_text('{}')
    os.chmod(f, 0o644)
    with pytest.raises(PrintError):
        read_private(f)


def test_concurrent_submission_lock(tmp_path):
    job = prepare(tmp_path, pdf_bytes(), 'one.pdf')
    with locked(tmp_path, job['id']):
        with pytest.raises(PrintError, match='另一个'):
            with locked(tmp_path, job['id']):
                pass


def test_vendor_file_container_is_reversible(tmp_path):
    raw = pdf_bytes()
    assert encode_file(raw, 0) == (raw, 'pdf')
    encoded, suffix = encode_file(raw, 1)
    assert suffix == 'dat' and encoded[:4] == bytes(4)
    with zipfile.ZipFile(io.BytesIO(b'PK\x03\x04'+encoded[4:])) as z:
        assert z.namelist() == ['document.pdf']
        assert z.read('document.pdf') == raw
    with pytest.raises(PrintError):
        encode_file(raw, 99)


class MockServer:
    def __init__(self, profile):
        self.profile = profile
        self.calls = []
        self.error = None

    def __call__(self, endpoint, body, token):
        self.calls.append((endpoint, dict(body)))
        if endpoint == '/getToken':
            return {'Code': '00', 'data': 'test-bearer-token'}
        assert token == 'test-bearer-token'
        if endpoint == '/login':
            assert body['type'] == 1 and body['ischeckpwd'] == 1
            assert decode_password(body['pwd'], self.profile) == 'user-test-password'
            assert body['signature'] == signature(f'type=1&code={body["code"]}&pwd={body["pwd"]}', self.profile['web_key'])
            return {'Code': '00'}
        if endpoint == '/filestorage':
            return {'Code': '00', 'List': [{'ID': 1, 'EquipId': 2, 'StorageType': 2, 'IP': 'print.invalid',
                     'Port': 21, 'UserName': 'storage-test', 'Password': encode_password('ftp-test', self.profile),
                     'FileEncType': 0}]}
        if endpoint == '/print':
            assert body['type'] == 4 and body['ischeckpwd'] == 1 and body['directprintid'] == 0
            expected_fields = {'type', 'code', 'pwd', 'ischeckpwd', 'ip', 'mac', 'host', 'filename',
                'projectid', 'directprintid', 'count', 'iscollate', 'direction', 'doubleprint', 'color',
                'papersize', 'papertype', 'filesize', 'papersource', 'pagetotal', 'a3pagecount',
                'a4pagecount', 'otherpagecount', 'hbpages', 'colorpages', 'jobtype', 'comment', 'signature'}
            assert set(body) == expected_fields
            assert body['ip'] == '192.0.2.10'
            assert decode_password(body['pwd'], self.profile) == 'user-test-password'
            assert body['signature'] == signature(f'type=4&code={body["code"]}&pwd={body["pwd"]}', self.profile['web_key'])
            if self.error == 'reject':
                return {'Code': '02', 'Mess': 'must-not-echo-user-test-password'}
            if self.error == 'registration_timeout':
                raise UncertainSubmission('registration outcome unknown')
            return {'Code': '00', 'SubmitJobId': 123}
        if endpoint == '/printfile':
            assert body['submitjobid'] == 123 and body['state'] == 1
            assert body['filestorageid'] == 1  # Storage ID, not equipment ID 2.
            if self.error == 'bad_storage':
                return {'Code': '04'}
            if self.error == 'commit_timeout':
                raise UncertainSubmission('commit outcome unknown')
            return {'Code': '00'}
        return {'Code': '00'}


def client_for(profile):
    mock = MockServer(profile)
    client = V5Client(profile, True, mock)
    client.local_ip = lambda: '192.0.2.10'
    client.upload = lambda storage, path, data: None
    return client, mock


def test_plain_http_requires_opt_in(profile):
    with pytest.raises(PrintError, match='HTTP'):
        V5Client(profile)


def test_login_verifies_credentials_without_registering_any_job(profile):
    client, mock = client_for(profile)
    client.authenticate_client()
    client.verify_user('test-user', 'user-test-password')
    assert [c[0] for c in mock.calls] == ['/getToken', '/login']


def test_successful_submission_keeps_receipt_not_pdf_or_password(tmp_path, profile):
    job = prepare(tmp_path, pdf_bytes(2), 'one.pdf', copies=2)
    client, mock = client_for(profile)
    result = client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert result['state'] == 'submitted' and result['server_id'] == 123
    assert not (job_dir(tmp_path, job['id'])/'document.pdf').exists()
    receipt = (job_dir(tmp_path, job['id'])/'job.json').read_text()
    assert 'user-test-password' not in receipt and 'pwd' not in receipt and 'test-bearer-token' not in receipt
    assert [x[0] for x in mock.calls] == ['/getToken', '/filestorage', '/print', '/printfile']
    with pytest.raises(PrintError, match='重复'):
        client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')


@pytest.mark.parametrize('where', ['registration_timeout', 'commit_timeout'])
def test_uncertain_request_is_never_automatically_reregistered(tmp_path, profile, where):
    job = prepare(tmp_path, pdf_bytes(), 'one.pdf')
    client, mock = client_for(profile)
    mock.error = where
    with pytest.raises(UncertainSubmission):
        client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert load_job(tmp_path, job['id'])['state'] == 'uncertain'
    with pytest.raises(PrintError):
        client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert len([c for c in mock.calls if c[0] == '/print']) == 1


def test_failed_upload_resumes_same_server_id(tmp_path, profile):
    job = prepare(tmp_path, pdf_bytes(), 'one.pdf')
    client, mock = client_for(profile)
    def fail(*args):
        raise PrintError('test upload failure')
    client.upload = fail
    with pytest.raises(PrintError):
        client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    saved = load_job(tmp_path, job['id'])
    assert saved['state'] == 'uploading' and saved['server_id'] == 123
    path = saved['remote_path']
    with pytest.raises(PrintError):
        client.submit(tmp_path, job['id'], 'different-user', 'user-test-password')
    client.upload = lambda *args: None
    result = client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert result['remote_path'] == path
    assert len([c for c in mock.calls if c[0] == '/print']) == 1


def test_explicit_commit_rejection_preserves_uploaded_state(tmp_path, profile):
    from zgcaprint.common.errors import ServerRejected
    job = prepare(tmp_path, pdf_bytes(), 'one.pdf')
    client, mock = client_for(profile)
    mock.error = 'bad_storage'
    with pytest.raises(ServerRejected):
        client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert load_job(tmp_path, job['id'])['state'] == 'uploaded'
    mock.error = None
    client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert len([x for x in mock.calls if x[0] == '/print']) == 1


def test_invalid_password_rejection_can_be_retried_without_leaking_server_message(tmp_path, profile):
    job = prepare(tmp_path, pdf_bytes(), 'one.pdf')
    client, mock = client_for(profile)
    mock.error = 'reject'
    with pytest.raises(PrintError) as e:
        client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert 'user-test-password' not in str(e.value)
    assert load_job(tmp_path, job['id'])['state'] == 'prepared'
    assert 'account' not in load_job(tmp_path, job['id'])


def test_ftp_upload_stays_on_allowed_host_and_remote_path(profile, monkeypatch):
    import zgcaprint.protocol.client as protocol
    calls = []
    class FTP:
        def __init__(self, **kw): pass
        def connect(self, host, port): calls.append(('connect', host, port))
        def login(self, user, password): calls.append(('login', user))
        def cwd(self, part): calls.append(('cwd', part))
        def storbinary(self, command, stream): calls.append(('upload', command, stream.read()))
        def quit(self): calls.append(('quit',))
        def close(self): pass
    monkeypatch.setattr(protocol.ftplib, 'FTP', FTP)
    client = V5Client(profile, True)
    storage = {'StorageType': 2, 'host': 'print.invalid', 'Port': 21,
               'UserName': 'test', 'password': 'test-storage-password'}
    client.upload(storage, '/PrintDir/20260101/test.pdf', b'test-pdf')
    assert ('connect', 'print.invalid', 21) in calls
    assert ('upload', 'STOR test.pdf', b'test-pdf') in calls
    with pytest.raises(PrintError):
        client.upload(storage, '/PrintDir/test\r\nDELE file.pdf', b'test-pdf')
    with pytest.raises(PrintError):
        client.upload({**storage, 'host': 'unapproved.invalid'}, '/test.pdf', b'test-pdf')


def test_unapproved_upload_host_is_rejected(profile):
    client, mock = client_for(profile)
    profile['storage_allowed_hosts'] = ['different.invalid']
    client.authenticate_client()
    with pytest.raises(PrintError, match='存储'):
        client.choose_storage()


def test_remove_refuses_ambiguous_server_jobs(tmp_path):
    from zgcaprint.printing.jobs import set_state
    job = prepare(tmp_path, pdf_bytes(), 'one.pdf')
    set_state(tmp_path, job, 'uncertain')
    with pytest.raises(PrintError):
        remove_job(tmp_path, job['id'])


def test_adopt_cups_job_without_network(tmp_path):
    spool, home = tmp_path/'spool', tmp_path/'home'
    job = prepare(spool/str(os.getuid()), pdf_bytes(), 'system-print.pdf')
    adopt_cups_jobs(home, spool)
    assert load_job(home, job['id'])['state'] == 'prepared'
    assert not (spool/str(os.getuid())/'jobs'/job['id']).exists()


def test_invalid_archive_is_not_extracted():
    with pytest.raises(PrintError):
        cpio_selected(b'not a cpio archive')


def test_cli_requires_send_and_never_prompts_or_uses_network(tmp_path, capsys):
    from zgcaprint.application.cli import main
    result = main(['--home', str(tmp_path), 'submit', '0'*32, '--user', 'test'])
    assert result == 2 and '--send' in capsys.readouterr().err


def test_remembered_credentials_are_keyring_only_and_forget_is_scoped(tmp_path):
    from zgcaprint.config.credentials import CredentialStore, forget_login, preferences, remember_login
    database = {}
    def backend(op, server, account, password):
        key = (server, account)
        if op == 'store': database[key] = password; return True
        if op == 'lookup': return database.get(key)
        if op == 'clear': return database.pop(key, None) is not None
    store = CredentialStore('https://test.invalid/services', backend)
    unrelated = CredentialStore('https://other.invalid/services', backend)
    unrelated.save('someone', 'unrelated-secret')
    remember_login(tmp_path, store, 'student', 'remembered-test-password', True)
    assert store.get('student') == 'remembered-test-password'
    prefs = preferences(tmp_path, store.base_url)
    assert prefs == {'account': 'student', 'remember': True, 'auto_login': True}
    for file in tmp_path.rglob('*'):
        if file.is_file(): assert b'remembered-test-password' not in file.read_bytes()
    assert preferences(tmp_path, unrelated.base_url)['account'] == ''
    forget_login(tmp_path, store)
    assert store.get('student') is None
    assert unrelated.get('someone') == 'unrelated-secret'
    assert not preferences(tmp_path, store.base_url)['auto_login']


def test_keyring_failure_does_not_fall_back_to_file(tmp_path):
    from zgcaprint.config.credentials import CredentialStore, remember_login
    def failed(*args): raise PrintError('keyring locked')
    store = CredentialStore('https://test.invalid/services', failed)
    with pytest.raises(PrintError):
        remember_login(tmp_path, store, 'student', 'must-not-be-written', True)
    assert not (tmp_path/'preferences.json').exists()


def test_forget_disables_auto_login_even_when_keyring_is_unavailable(tmp_path):
    from zgcaprint.config.credentials import CredentialStore, forget_login, preferences
    from zgcaprint.config.profile import json_write
    base = 'https://test.invalid/services'
    json_write(tmp_path/'preferences.json', {'server': base, 'account': 'student', 'remember': True, 'auto_login': True})
    def failed(*args): raise PrintError('keyring locked')
    with pytest.raises(PrintError): forget_login(tmp_path, CredentialStore(base, failed))
    assert preferences(tmp_path, base) == {'account': '', 'remember': False, 'auto_login': False}
