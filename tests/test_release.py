"""Public release input validation uses synthetic private values only."""
from pathlib import Path
import importlib.util
import pytest
from zgcaprint.config.profile import json_write

spec=importlib.util.spec_from_file_location('zgca_release_audit',Path(__file__).resolve().parents[1]/'tools/release_audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


@pytest.fixture
def public_tree(tmp_path,monkeypatch):
    monkeypatch.setattr(audit,'default_home',lambda:tmp_path/'unused-home')
    for name in ['README.md','LICENCE','pyproject.toml','.gitignore','run-client.sh','examples/print-test.pdf','.github/workflows/release.yml']:
        (tmp_path/name).parent.mkdir(parents=True,exist_ok=True)
        (tmp_path/name).write_text('public text')
    (tmp_path/'src/zgcaprint/printing').mkdir(parents=True)
    (tmp_path/'src/zgcaprint/printing/jobs.py').write_text('print("public")')
    json_write(tmp_path/'.local/profile.json',{'web_key':'PRIVATE_EXAMPLE_12345','client_id':'PRIVATE_CLIENT_12345',
        'client_secret':'PRIVATE_SECRET_12345','password_key_hex':'ab'*16})
    return tmp_path


def test_release_allowlist_excludes_private_files(public_tree):
    (public_tree/'.local/private.pdf').write_bytes(b'private')
    files,_=audit.audit_sources(public_tree)
    assert public_tree/'src/zgcaprint/printing/jobs.py' in files
    assert not any('.local' in path.parts for path in files)


def test_release_rejects_private_constant_in_public_source(public_tree):
    (public_tree/'src/zgcaprint/printing/jobs.py').write_text('key="PRIVATE_EXAMPLE_12345"')
    with pytest.raises(SystemExit):audit.audit_sources(public_tree)


def test_release_rejects_symlinked_public_input(public_tree):
    path=public_tree/'README.md';path.unlink();path.symlink_to(public_tree/'.local/profile.json')
    with pytest.raises(SystemExit):audit.audit_sources(public_tree)
