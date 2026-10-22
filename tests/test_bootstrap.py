"""First-run provisioning uses synthetic packages and never contacts the school."""
from io import BytesIO
from pathlib import Path
import hashlib
import zipfile
import pytest

from zgcaprint.common.errors import PrintError
from zgcaprint.config import bootstrap
from zgcaprint.config.profile import json_write, private_write, read_private
from tests.test_client import profile


def zipped(raw):
    result=BytesIO()
    with zipfile.ZipFile(result,'w') as archive:archive.writestr('synthetic.pkg',raw)
    return result.getvalue()


@pytest.fixture
def source(monkeypatch,profile):
    raw=b'synthetic official package, contains no campus data'
    monkeypatch.setattr(bootstrap,'PACKAGE_SHA256',hashlib.sha256(raw).hexdigest())
    def importer(package,home):
        assert Path(package).read_bytes().startswith(b'PK')
        json_write(Path(home)/'profile.json',{**profile,'base_url':bootstrap.BASE_URL,'queue':bootstrap.QUEUE})
        private_write(Path(home)/'printer.ppd','synthetic PPD')
        private_write(Path(home)/'printer_param.json','{}')
    monkeypatch.setattr(bootstrap,'import_package',importer)
    return zipped(raw)


def test_provision_caches_pinned_package_and_does_not_replace_existing_configuration(tmp_path,monkeypatch,source):
    calls=[]
    monkeypatch.setattr(bootstrap,'download',lambda *args:calls.append(1) or source)
    bootstrap.provision(tmp_path)
    assert calls==[1] and (tmp_path/'driver-cache'/bootstrap.CACHE_NAME).read_bytes()==source
    before=(tmp_path/'profile.json').read_bytes()
    monkeypatch.setattr(bootstrap,'download',lambda *args:pytest.fail('must not fetch an update'))
    bootstrap.provision(tmp_path)
    assert (tmp_path/'profile.json').read_bytes()==before
    for path in [tmp_path/'profile.json',tmp_path/'driver-cache'/bootstrap.CACHE_NAME]:
        assert path.stat().st_mode & 0o077 == 0


def test_known_cache_allows_first_configuration_without_network(tmp_path,monkeypatch,source):
    private_write(tmp_path/'driver-cache'/bootstrap.CACHE_NAME,source)
    monkeypatch.setattr(bootstrap,'download',lambda *args:pytest.fail('must use the known cache'))
    assert bootstrap.provision(tmp_path)['queue']==bootstrap.QUEUE


def test_unknown_official_update_never_publishes_profile_or_cache(tmp_path,monkeypatch,source):
    monkeypatch.setattr(bootstrap,'download',lambda *args:zipped(b'unknown new version'))
    with pytest.raises(PrintError,match='校验'):bootstrap.provision(tmp_path)
    assert not (tmp_path/'profile.json').exists()
    assert not (tmp_path/'driver-cache'/bootstrap.CACHE_NAME).exists()


def test_changed_server_configuration_never_reaches_user_home(tmp_path,monkeypatch,source):
    original=bootstrap.import_package
    def wrong(package,home):
        original(package,home)
        data=read_private(Path(home)/'profile.json');data['queue']='OTHER'
        json_write(Path(home)/'profile.json',data)
    monkeypatch.setattr(bootstrap,'import_package',wrong)
    with pytest.raises(PrintError,match='不匹配'):bootstrap.provision(tmp_path,package=write(tmp_path/'sample.zip',source))
    assert not (tmp_path/'profile.json').exists() and not (tmp_path/'printer.ppd').exists()


def write(path,data):
    private_write(path,data);return path


def test_local_raw_pkg_is_wrapped_and_validated_before_import(tmp_path,monkeypatch,source):
    with zipfile.ZipFile(BytesIO(source)) as archive:raw=archive.read('synthetic.pkg')
    bootstrap.provision(tmp_path,package=write(tmp_path/'synthetic.pkg',raw))
    assert (tmp_path/'profile.json').is_file()


class Response(BytesIO):
    status=200
    headers={}
    def geturl(self):return bootstrap.OFFICIAL_URL


class Opener:
    def __init__(self,response):self.response=response
    def open(self,request,timeout):
        assert request.full_url==bootstrap.OFFICIAL_URL and timeout==10
        return self.response


@pytest.mark.parametrize('case',['offsite','oversized','truncated','cancelled'])
def test_download_rejects_untrusted_or_incomplete_responses(case):
    response=Response(b'abc')
    if case=='offsite':response.geturl=lambda:'http://other.invalid/package.zip'
    if case=='oversized':response.headers={'Content-Length':str(bootstrap.MAX_ARCHIVE+1)}
    if case=='truncated':response.headers={'Content-Length':'100'}
    with pytest.raises(PrintError):bootstrap.download(opener=Opener(response),cancelled=lambda:case=='cancelled')


def test_official_redirect_is_never_followed():
    with pytest.raises(PrintError):bootstrap.NoRedirects().redirect_request(None,None,302,'redirect',{},'http://other.invalid')
