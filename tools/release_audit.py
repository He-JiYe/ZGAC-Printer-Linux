"""Shared allowlist and known-private-value checks; never accesses the keyring."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
from zgcaprint.config.profile import default_home, read_private


def public_files(root=ROOT):
    names=['README.md','LICENCE','pyproject.toml','.gitignore','run-client.sh','examples/print-test.pdf','.github/workflows/release.yml']
    files=[root/name for name in names]
    for folder in ['src/zgcaprint','tests','tools']:files+=sorted((root/folder).rglob('*.py'))
    return files


def sensitive_values(root=ROOT):
    values=[]
    for path in {root/'.local/profile.json',default_home()/'profile.json'}:
        if path.exists():
            profile=read_private(path)
            values += [profile[key].encode() for key in ['web_key','client_id','client_secret','password_key_hex']]
            values.append(bytes.fromhex(profile['password_key_hex']))
            prefs=path.with_name('preferences.json')
            if prefs.exists():
                account=read_private(prefs).get('account','')
                if isinstance(account,str) and len(account)>=4:values.append(account.encode())
    return values


def audit_sources(root=ROOT):
    files=public_files(root);values=sensitive_values(root)
    for path in files:
        components=[path,*[parent for parent in path.parents if root in parent.parents]]
        if any(part.is_symlink() for part in components) or not path.is_file() or any(value in path.read_bytes() for value in values):
            raise SystemExit('Public-source scan failed; no release should be created.')
    return files,values
