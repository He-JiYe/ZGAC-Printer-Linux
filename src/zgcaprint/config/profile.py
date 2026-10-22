"""Import selected data from the user's own supported Mac installer.

Archive contents are read as data only. No installer is executed, no arbitrary
paths are extracted, and no vendor executable is installed or redistributed.
"""
import base64
import configparser
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
import zipfile
import zlib

from zgcaprint.common.errors import PrintError

MAX_ARCHIVE = 128 * 1024 * 1024
MAX_TOC = 2*1024*1024
CLIENT = 'Applications/XZPrintClient.app/Contents/MacOS/XZPrintClient'
LIBRARY = 'Applications/XZPrintClient.app/Contents/Frameworks/libXZCmmLib.dylib'
CONFIG = 'Library/Printers/xzvp/config.ini'
PARAMS = 'Library/Printers/xzvp/printer_param.json'
PPD = 'Library/Printers/PPDs/Contents/Resources/XZVPrinter.ppd'
# Offsets are accepted only for these exact known inputs, never arbitrary versions.
CLIENT_SHA = 'a261b39f448ef39f20ab0ce4c24d322a2c42d2c5160f47d6d06c3fde6d2ee5cf'
LIBRARY_SHA = '294002c6014f72c238e743ac415cd9e90e751d56ae0728b13acfd85687b621ed'


def default_home():
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'zgcaprint'


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise PrintError('拒绝使用符号链接作为私有目录。')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.stat()
    if st.st_uid != os.getuid():
        raise PrintError('私有目录不属于当前用户。')
    os.chmod(path, 0o700)
    return path


def private_write(path, data):
    """Replace atomically, without following an existing destination symlink."""
    import tempfile
    path = Path(path)
    private_dir(path.parent)
    if isinstance(data, str):
        data = data.encode('utf-8')
    fd, tmp = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def json_write(path, data):
    private_write(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def read_private_bytes(path, limit, owner=None, private=True):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or (owner is not None and st.st_uid != owner) or (private and (st.st_uid != os.getuid() or st.st_mode & 0o077)):
            raise PrintError('文件类型、所有者或私有文件权限无效。')
        if st.st_size > limit:
            raise PrintError('文件大小超过限制。')
        data = f.read(limit+1)
        if len(data) > limit:
            raise PrintError('文件大小超过限制。')
        return data


def read_private(path):
    value = json.loads(read_private_bytes(path, 2*1024*1024))
    if not isinstance(value, dict):
        raise PrintError('私有记录须为 JSON 对象。')
    return value


def bounded_gzip(data):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
        result = f.read(MAX_ARCHIVE + 1)
    if len(result) > MAX_ARCHIVE:
        raise PrintError('安装包展开大小超过限制。')
    return result


def xar_payload(data):
    if len(data) < 28:
        raise PrintError('安装包头部不完整。')
    magic, header, version, compressed, expanded, _ = struct.unpack_from('>IHHQQI', data)
    if magic != 0x78617221 or version != 1 or not 28 <= header <= len(data) or header+compressed > len(data) or max(compressed, expanded) > MAX_TOC:
        raise PrintError('不支持的 XAR 安装包。')
    dec = zlib.decompressobj()
    toc = dec.decompress(data[header:header+compressed], MAX_TOC + 1)
    if len(toc) != expanded or not dec.eof:
        raise PrintError('XAR 目录长度不符合预期。')
    # XAR needs no DTD/entities. Reject them before the standard XML parser.
    try:toc_text = toc.decode('utf-8-sig')
    except UnicodeError:raise PrintError('安装包目录必须使用 UTF-8 编码。') from None
    if '\0' in toc_text or '<!DOCTYPE' in toc_text.upper() or '<!ENTITY' in toc_text.upper():
        raise PrintError('安装包目录不能包含 XML DTD、实体或空字符。')
    try:root = ET.fromstring(toc_text)
    except ET.ParseError:raise PrintError('安装包目录 XML 格式无效。') from None
    for entry in root.iter('file'):
        if entry.findtext('name') == 'Payload':
            item = entry.find('data')
            start = header + compressed + int(item.findtext('offset'))
            size = int(item.findtext('length'))
            if not 0 <= size <= MAX_ARCHIVE or start < header+compressed or start+size > len(data):
                raise PrintError('XAR 文件范围无效。')
            return data[start:start+size]
    raise PrintError('安装包缺少 Payload。')


def cpio_selected(data):
    """Read Portable ASCII (odc) CPIO, selecting only five regular files."""
    wanted = {CLIENT, LIBRARY, CONFIG, PARAMS, PPD}
    result = {}
    pos = 0
    while pos + 76 <= len(data):
        head = data[pos:pos+76]
        if head[:6] != b'070707':
            raise PrintError('不支持的 CPIO 格式。')
        mode = int(head[18:24], 8)
        namesize, size = int(head[59:65], 8), int(head[65:76], 8)
        if not 1 <= namesize <= 4096 or size > MAX_ARCHIVE:
            raise PrintError('无效的 CPIO 文件长度。')
        pos += 76
        if pos+namesize > len(data) or data[pos+namesize-1] != 0:
            raise PrintError('CPIO 文件名不完整。')
        name = data[pos:pos+namesize-1].decode('utf-8')
        pos += namesize
        if name == 'TRAILER!!!':
            break
        if pos+size > len(data):
            raise PrintError('CPIO 文件不完整。')
        normalized = name[2:] if name.startswith('./') else name
        if normalized in wanted:
            if not stat.S_ISREG(mode) or normalized in result:
                raise PrintError('安装包中的目标文件不是唯一普通文件。')
            result[normalized] = data[pos:pos+size]
        pos += size
    if set(result) != wanted:
        raise PrintError('安装包缺少必要文件。')
    return result


def macho_reader(data):
    if data[:4] != b'\xcf\xfa\xed\xfe':
        raise PrintError('不支持的 Mac 二进制格式。')
    segments = []
    pos = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, pos)
        if cmd == 0x19:
            va, _, off, length = struct.unpack_from('<QQQQ', data, pos+24)
            segments.append((va, off, length))
        pos += size

    def read(va, count):
        for start, offset, length in segments:
            if start <= va and va+count <= start+length:
                return data[offset+va-start:offset+va-start+count]
        raise PrintError('安装包的二进制布局不符合预期。')
    return read


def _import_package(package, home):
    package = Path(package)
    raw = read_private_bytes(package, MAX_ARCHIVE, private=False)
    name = package.name
    if zipfile.is_zipfile(io.BytesIO(raw)):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            members = [x for x in z.infolist() if x.filename.endswith('.pkg')]
            if len(members) != 1 or members[0].file_size > MAX_ARCHIVE:
                raise PrintError('ZIP 中必须只有一个支持的 PKG 安装包。')
            name = Path(members[0].filename).name
            raw = z.read(members[0])
    files = cpio_selected(bounded_gzip(xar_payload(raw)))
    if hashlib.sha256(files[CLIENT]).hexdigest() != CLIENT_SHA or hashlib.sha256(files[LIBRARY]).hexdigest() != LIBRARY_SHA:
        raise PrintError('尚未支持此版本安装包；拒绝套用其他版本的认证布局。')
    client, lib = macho_reader(files[CLIENT]), macho_reader(files[LIBRARY])
    # Read private protocol constants from the user's installer, not this source.
    mask = bytes(lib(0x9f9e0 + i*4, 1)[0] for i in range(11))
    encoded = client(0x1000100f7, 8) + client(0x1000100e9, 8) + client(0x100010106, 4)
    decoded = base64.b64decode(encoded, validate=True)
    web_key = bytes(v ^ mask[i % len(mask)] for i, v in enumerate(decoded)).decode('utf-8')
    cfg = configparser.ConfigParser()
    cfg.read_string(files[CONFIG].decode('utf-8-sig'))
    match = re.search(r'\{([^}]+)\}', name)
    if not match:
        raise PrintError('安装包文件名缺少服务器和队列配置。')
    tags = {v[:2]: v[2:] for v in match.group(1).split('_')}
    if tags.get('BB') != 'v5':
        raise PrintError('目前仅支持 v5 打印系统。')
    host = tags.get('YM', cfg['ClientConfig']['SvrHost'])
    port = int(tags.get('DK', cfg['ClientConfig']['SvrPort']))
    scheme = tags.get('XY', 'http')
    app = tags.get('AP', 'xzentprint')
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host) or scheme not in ['http', 'https'] or not 1 <= port <= 65535 or not re.fullmatch(r'[A-Za-z0-9_-]+', app):
        raise PrintError('安装包服务器配置不受支持。')
    profile = {
        'schema': 1, 'vendor_version': '5.1.3.12',
        'base_url': f'{scheme}://{host}:{port}/{app}/services',
        'queue': tags.get('QD', 'XZVPrinter'), 'web_key': web_key,
        'client_id': client(0x1001a3181, 8).decode(),
        'client_secret': client(0x1001a3194, 44).decode(),
        'password_key_hex': client(0x1001a19d0, 16).hex(),
        'password_mix_indices': list(client(0x1001c1090, 8)),
        'package_sha256': hashlib.sha256(raw).hexdigest(),
        'storage_allowed_hosts': [host], 'allow_plain_http': False,
    }
    home = private_dir(home)
    private_write(home/'printer.ppd', files[PPD])
    private_write(home/'printer_param.json', files[PARAMS])
    json_write(home/'profile.json', profile)
    return {k: profile[k] for k in ['vendor_version', 'base_url', 'queue']}


def import_package(package, home):
    try:
        return _import_package(package, home)
    except PrintError:
        raise
    except (ValueError, OSError, EOFError, struct.error, zlib.error, ET.ParseError,
            zipfile.BadZipFile, KeyError, IndexError, TypeError, configparser.Error):
        raise PrintError('安装包不完整、格式无效或不受支持，未执行任何原厂程序。') from None


def load_profile(home):
    profile = read_private(Path(home)/'profile.json')
    validate_profile(profile)
    u = urlsplit(profile['base_url'])
    if u.scheme not in ['http', 'https'] or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise PrintError('服务器 URL 配置无效。')
    return profile


def validate_profile(profile):
    try:
        u = urlsplit(profile['base_url'])
        if u.scheme not in ['http', 'https'] or not u.hostname or u.username or u.password or u.query or u.fragment or not re.fullmatch(r'/[A-Za-z0-9_/-]+', u.path):
            raise ValueError()
        if u.port is not None and not 1 <= u.port <= 65535:
            raise ValueError()
        for key in ['web_key', 'client_id', 'client_secret']:
            value = profile[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c)<32 for c in value):
                raise ValueError()
        if not re.fullmatch(r'[0-9a-fA-F]{32}', profile['password_key_hex']):
            raise ValueError()
        mix = profile['password_mix_indices']
        if not isinstance(mix, list) or len(mix) != 8 or any(type(v) is not int or not 0 <= v < 32 for v in mix):
            raise ValueError()
        hosts = profile['storage_allowed_hosts']
        if not isinstance(hosts, list) or not 1 <= len(hosts) <= 32 or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', v) for v in hosts):
            raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', profile['queue']):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise PrintError('本机服务器配置格式无效，请重新导入支持的安装包。') from None
