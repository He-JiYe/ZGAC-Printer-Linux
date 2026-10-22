"""Frozen paths, helper isolation and credential transport contain no shell secrets."""
from pathlib import Path
import json
import subprocess
import sys
import pytest
from zgcaprint.common import runtime
from zgcaprint.desktop import startup
from zgcaprint.config.credentials import CredentialStore
from zgcaprint.common.errors import PrintError


def frozen(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'_MEIPASS',str(tmp_path/'bundle'),raising=False)
    monkeypatch.setattr(sys,'executable',str(tmp_path/'ZGCA-Print'))


def test_frozen_pdf_uses_executable_worker_and_external_helpers_use_system_python(monkeypatch,tmp_path):
    frozen(monkeypatch,tmp_path)
    assert runtime.pdf_command()==[sys.executable,'_pdf-worker']
    assert runtime.tray_command()[:2]==['/usr/bin/python3','-I']
    assert runtime.keyring_command()[-1].endswith('/system_helpers/keyring_entry.py')
    command=startup.content(tmp_path/'private',True,True)
    assert sys.executable in command and 'launcher.py' not in command and '_MEIPASS' not in command
    assert '--background' in command


def test_external_helpers_restore_loader_environment(monkeypatch,tmp_path):
    frozen(monkeypatch,tmp_path)
    monkeypatch.setenv('LD_LIBRARY_PATH','/bundle/internal:/system/custom')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG','/system/custom')
    assert runtime.external_env()['LD_LIBRARY_PATH']=='/system/custom'
    monkeypatch.delenv('LD_LIBRARY_PATH_ORIG')
    assert 'LD_LIBRARY_PATH' not in runtime.external_env()


def test_frozen_password_only_travels_through_stdin(monkeypatch,tmp_path):
    frozen(monkeypatch,tmp_path);calls=[]
    def run(command,**kwargs):
        request=json.loads(kwargs['input']);calls.append((command,kwargs,request))
        return subprocess.CompletedProcess(command,0,b'{"result":true}',b'')
    monkeypatch.setattr(subprocess,'run',run)
    store=CredentialStore('https://synthetic.invalid/services')
    assert store.save('student','synthetic-only') is True
    command,kwargs,request=calls[0]
    assert 'synthetic-only' not in ' '.join(command)
    assert all('synthetic-only' not in str(v) for v in kwargs['env'].values())
    assert request['password']=='synthetic-only' and request['operation']=='store'
    assert kwargs['timeout']==35


@pytest.mark.parametrize('reply',[b'not JSON',b'{"result":[]}',b'{"error":"untrusted message"}'])
def test_frozen_keyring_failure_never_falls_back_to_plaintext(monkeypatch,tmp_path,reply):
    frozen(monkeypatch,tmp_path)
    monkeypatch.setattr(subprocess,'run',lambda command,**kwargs:subprocess.CompletedProcess(command,0,reply,b''))
    with pytest.raises(PrintError) as error:CredentialStore('https://synthetic.invalid').get('student')
    assert 'untrusted message' not in str(error.value)
    assert not list(tmp_path.rglob('preferences.json'))


def test_xar_toc_decompression_is_bounded_to_its_own_limit():
    import struct,zlib
    from zgcaprint.config.profile import MAX_TOC, xar_payload
    data=b'x'*(MAX_TOC+20)
    compressed=zlib.compress(data)
    archive=struct.pack('>IHHQQI',0x78617221,28,1,len(compressed),1,0)+compressed
    with pytest.raises(PrintError):xar_payload(archive)
