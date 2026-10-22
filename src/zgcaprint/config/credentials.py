"""Passwords live in Linux Secret Service; local preferences contain no secret."""
from pathlib import Path

from zgcaprint.common.errors import PrintError
from zgcaprint.config.profile import json_write, read_private


class CredentialStore:
    def __init__(self, base_url, backend=None):
        self.base_url = base_url
        self.backend = backend

    def _call(self, operation, account, password=None):
        if self.backend is not None:
            return self.backend(operation, self.base_url, account, password)
        from zgcaprint.common.runtime import frozen, keyring_command, external_env
        if not frozen():
            from zgcaprint.config.keyring import call
            return call(operation,self.base_url,account,password)
        import json
        import subprocess
        body=json.dumps({'operation':operation,'base_url':self.base_url,'account':account,'password':password}).encode('utf-8')
        if len(body)>16384:raise PrintError('钥匙串请求格式无效。')
        try:
            result=subprocess.run(keyring_command(),input=body,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,env=external_env(),timeout=35,check=False)
            if result.returncode!=0 or len(result.stdout)>16384:raise ValueError()
            reply=json.loads(result.stdout)
            if not isinstance(reply,dict) or 'result' not in reply:raise ValueError()
            value=reply['result']
            if operation=='lookup' and value is not None and (not isinstance(value,str) or len(value.encode('utf-8'))>240):raise ValueError()
            if operation!='lookup' and type(value) is not bool:raise ValueError()
            return value
        except (OSError,ValueError,subprocess.TimeoutExpired):
            raise PrintError('系统钥匙串不可用或未解锁；请检查系统 Python 和 libsecret，密码未保存到文件。') from None

    def get(self, account):
        return self._call('lookup', account)

    def save(self, account, password):
        return self._call('store', account, password)

    def clear(self, account):
        return self._call('clear', account)


def preferences(home, base_url):
    path = Path(home)/'preferences.json'
    if not path.exists():
        return {'account': '', 'remember': False, 'auto_login': False}
    prefs = read_private(path)
    if prefs.get('server') != base_url:
        return {'account': '', 'remember': False, 'auto_login': False}
    account = prefs.get('account', '')
    if not isinstance(account, str) or len(account) > 200 or any(ord(c)<32 for c in account):
        raise PrintError('保存的账号格式无效。')
    remember = prefs.get('remember') is True
    return {'account': account, 'remember': remember, 'auto_login': remember and prefs.get('auto_login') is True}


def remember_login(home, store, account, password, auto_login=False):
    old = preferences(home, store.base_url)
    store.save(account, password)
    json_write(Path(home)/'preferences.json', {'server': store.base_url, 'account': account,
                'remember': True, 'auto_login': bool(auto_login)})
    if old['account'] and old['account'] != account:
        store.clear(old['account'])


def forget_login(home, store):
    old = preferences(home, store.base_url)
    # Disable automatic lookup even if the keyring is currently unavailable.
    json_write(Path(home)/'preferences.json', {'server': store.base_url, 'account': '',
                'remember': False, 'auto_login': False})
    if old['account']:
        store.clear(old['account'])
