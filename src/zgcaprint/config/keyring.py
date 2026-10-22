"""Bounded Secret Service operations; may run under the distribution Python."""
import json
import sys
import threading
from zgcaprint.common.errors import PrintError


def call(operation,base_url,account,password=None):
    try:
        import gi
        gi.require_version('Secret', '1')
        from gi.repository import Secret, Gio
    except (ImportError, ValueError):
        raise PrintError('系统钥匙串不可用。需要 python3-gi、gir1.2-secret-1 和运行中的 Secret Service；密码未保存到文件。') from None
    schema = Secret.Schema.new('org.zgcaprint.Credentials', Secret.SchemaFlags.NONE,
              {'server': Secret.SchemaAttributeType.STRING, 'account': Secret.SchemaAttributeType.STRING})
    attrs = {'server': base_url, 'account': account}
    cancel = Gio.Cancellable()
    timer = threading.Timer(30, cancel.cancel)
    timer.daemon = True
    timer.start()
    try:
        if operation == 'lookup':
            return Secret.password_lookup_sync(schema, attrs, cancel)
        if operation == 'store':
            ok = Secret.password_store_sync(schema, attrs, Secret.COLLECTION_DEFAULT,
                                           'ZGCA Linux 打印账号', password, cancel)
            if not ok:
                raise PrintError('系统钥匙串没有确认保存；密码未保存到配置文件。')
            return True
        if operation == 'clear':
            return Secret.password_clear_sync(schema, attrs, cancel)
        raise ValueError('unknown operation')
    except PrintError:
        raise
    except Exception:
        raise PrintError('系统钥匙串未解锁或访问失败；密码不会退回明文保存。') from None
    finally:
        timer.cancel()


def stdio():
    try:
        raw=sys.stdin.buffer.read(16385)
        if len(raw)>16384:raise PrintError('钥匙串请求过大。')
        request=json.loads(raw)
        if not isinstance(request,dict) or set(request)!={'operation','base_url','account','password'}:
            raise PrintError('钥匙串请求无效。')
        if request['operation'] not in ['lookup','store','clear']:
            raise PrintError('钥匙串操作无效。')
        for field,limit in [('base_url',2048),('account',200)]:
            value=request[field]
            if not isinstance(value,str) or not value or len(value)>limit or any(ord(c)<32 for c in value):
                raise PrintError('钥匙串字段无效。')
        password=request['password']
        if password is not None and (not isinstance(password,str) or len(password.encode('utf-8'))>240 or '\0' in password):
            raise PrintError('钥匙串密码格式无效。')
        result=call(**request)
        if isinstance(result,str) and len(result.encode('utf-8'))>240:
            raise PrintError('钥匙串返回了不支持的凭据长度。')
        reply={'result':result}
    except Exception:
        reply={'error':'系统钥匙串未解锁或访问失败；密码不会退回明文保存。'}
    sys.stdout.write(json.dumps(reply,ensure_ascii=False))
    return 0
