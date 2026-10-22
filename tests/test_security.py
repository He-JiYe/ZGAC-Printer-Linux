"""Regression checks for duplicate submission, private files and activation."""
import os
from pathlib import Path
import pytest

from zgcaprint.common.errors import PrintError, UncertainSubmission
from zgcaprint.printing.jobs import load_job, prepare
from zgcaprint.config.profile import read_private, private_dir
from zgcaprint.desktop.resident import Instance
from zgcaprint.desktop import startup
from tests.test_client import pdf_bytes, client_for, profile


@pytest.mark.parametrize('code', [True, False, 0.0, None, 'success', 10000, 9999])
def test_malformed_mutation_reply_never_allows_reregistration(tmp_path, profile, code):
    client, server = client_for(profile)
    original = client.transport
    def transport(endpoint, body, token):
        if endpoint == '/print':
            server.calls.append((endpoint, body))
            return {'Code': code, 'SubmitJobId': 123}
        return original(endpoint, body, token)
    client.transport = transport
    job = prepare(tmp_path, pdf_bytes(), 'synthetic.pdf')
    with pytest.raises(UncertainSubmission):client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert load_job(tmp_path, job['id'])['state'] == 'uncertain'
    with pytest.raises(PrintError):client.submit(tmp_path, job['id'], 'test-user', 'user-test-password')
    assert len([x for x in server.calls if x[0]=='/print']) == 1


def test_private_reader_rejects_fifo_and_oversized_json(tmp_path):
    fifo=tmp_path/'fifo'
    os.mkfifo(fifo,0o600)
    with pytest.raises(PrintError):read_private(fifo)
    path=tmp_path/'huge.json';path.write_bytes(b' '*(2*1024*1024+1));path.chmod(0o600)
    with pytest.raises(PrintError):read_private(path)


def test_second_instance_activates_first_without_owning_a_second_lock(tmp_path):
    try:primary=Instance(private_dir(tmp_path))
    except PermissionError:pytest.skip('local socket needs host access outside restricted runner')
    try:
        other=Instance(tmp_path)
        assert primary.primary and not other.primary
        assert primary.activated()
        other.close()
        assert not primary.activated()
    finally:primary.close()
    replacement=Instance(tmp_path)
    assert replacement.primary
    replacement.close()


def test_autostart_is_scoped_and_contains_no_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    other=tmp_path/'config/autostart/other.desktop';other.parent.mkdir(parents=True);other.parent.chmod(0o700);other.write_text('unrelated')
    path=startup.install(tmp_path/'private',True,autostart=True)
    assert startup.enabled() and '--background' in path.read_text()
    assert 'password' not in path.read_text() and path.stat().st_mode & 0o077 == 0
    startup.install(tmp_path/'private',autostart=True,enable=False)
    assert not startup.enabled() and other.read_text()=='unrelated'
    path.write_text('[Desktop Entry]\nName=Unrelated\n')
    with pytest.raises(PrintError):startup.install(tmp_path/'private',autostart=True)
    assert 'Unrelated' in path.read_text()


@pytest.mark.parametrize('encoding',['utf-8','utf-16'])
def test_xar_rejects_entity_declarations_including_alternate_encoding(encoding):
    import struct,zlib
    from zgcaprint.config.profile import xar_payload
    xml='<!DOCTYPE xar [<!ENTITY x "example">]><xar>&x;</xar>'.encode(encoding)
    compressed=zlib.compress(xml)
    data=struct.pack('>IHHQQI',0x78617221,28,1,len(compressed),len(xml),0)+compressed
    with pytest.raises(PrintError):xar_payload(data)


def test_removing_web_annotations_preserves_local_job_and_receipt(tmp_path):
    from zgcaprint.printing.jobs import discard_remote_status, set_state
    j=prepare(tmp_path,pdf_bytes(),'synthetic.pdf')
    set_state(tmp_path,j,'submitted',server_id=123,remote_state='not_pending',remote_status='old',remote_checked_at=1)
    discard_remote_status(tmp_path)
    after=load_job(tmp_path,j['id'])
    assert after['server_id']==123 and after['state']=='submitted' and after['sha256']==j['sha256']
    assert not any(k in after for k in ['remote_state','remote_status','remote_checked_at'])


@pytest.mark.parametrize('uid',[0,500,999])
def test_installer_rejects_unsupported_system_accounts_before_reading_configuration(tmp_path,monkeypatch,uid):
    from zgcaprint.cups.installer import generate
    import zgcaprint.cups.installer as installer
    monkeypatch.setattr(installer.os,'getuid',lambda:uid)
    with pytest.raises(PrintError,match='UID'):generate(tmp_path,tmp_path/'install.sh')
    assert not (tmp_path/'install.sh').exists()


def test_desktop_cli_rejects_root_before_touching_user_data(tmp_path,monkeypatch,capsys):
    import zgcaprint.application.cli as cli
    monkeypatch.setattr(cli.os,'getuid',lambda:0)
    assert cli.main(['--home',str(tmp_path),'list'])==2
    assert 'root' in capsys.readouterr().err and not list(tmp_path.iterdir())


def test_pdf_worker_rejects_root_before_reading_or_parsing_input(monkeypatch,capsys):
    import zgcaprint.printing.pdf_worker as worker
    monkeypatch.setattr(worker.os,'getuid',lambda:0)
    class Input:
        @property
        def buffer(self):raise AssertionError('root must not read the PDF')
    monkeypatch.setattr(worker.sys,'stdin',Input())
    worker.main()
    assert 'root' in capsys.readouterr().out
