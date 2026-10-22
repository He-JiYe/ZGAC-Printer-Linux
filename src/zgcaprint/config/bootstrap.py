"""Provision from a pinned official campus download, never from release secrets.

No vendor code is executed. Redirects, environment proxies and unknown package
revisions are rejected. Existing user configuration is never auto-replaced.
"""
from pathlib import Path
import hashlib
import io
import tempfile
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import zipfile

from zgcaprint.common.errors import PrintError
from zgcaprint.config.profile import (MAX_ARCHIVE, import_package, load_profile,
    private_dir, private_write, read_private_bytes)

OFFICIAL_URL = 'http://10.1.8.5/xzentprint/Down/MacPrinterClient.zip'
PACKAGE_SHA256 = 'a797f4fcdeb1d302e6e2920e702558d2341ccb5afcbc44d51c15bc810c5e8e32'
BASE_URL = 'http://10.1.8.5:80/xzentprint/services'
QUEUE = 'ZGCAxZGCIprinter'
CACHE_NAME = 'official-mac-5.1.3.12.zip'


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise PrintError('官方下载地址发生跳转，请等待客户端适配；未跟随新地址。')


def verified_package(data):
    """Pin the complete PKG, including its PPD and server configuration."""
    try:
        if len(data) > MAX_ARCHIVE:
            raise ValueError()
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                packages = [item for item in archive.infolist() if item.filename.endswith('.pkg')]
                if len(packages) != 1 or packages[0].file_size > MAX_ARCHIVE:
                    raise ValueError()
                data = archive.read(packages[0])
        if hashlib.sha256(data).hexdigest() != PACKAGE_SHA256:
            raise PrintError('官方安装包版本已变化或校验不符，未导入。请更新本客户端，或联系维护者确认固定版本下载。')
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError):
        raise PrintError('官方安装包格式或大小无效，未导入。') from None


def download(progress=lambda message: None, cancelled=lambda: False, opener=None):
    opener = opener or build_opener(ProxyHandler({}), NoRedirects())
    request = Request(OFFICIAL_URL, headers={'User-Agent': 'ZGCA-Print-Linux/1.0', 'Accept-Encoding': 'identity'})
    started = time.monotonic()
    try:
        with opener.open(request, timeout=10) as response:
            if response.status != 200 or response.geturl() != OFFICIAL_URL:
                raise PrintError('官方下载响应不符合预期，请检查校园网络。')
            declared = response.headers.get('Content-Length')
            if declared and (not declared.isdecimal() or not 0 < int(declared) <= MAX_ARCHIVE):
                raise PrintError('官方安装包大小不符合限制。')
            result = bytearray()
            while True:
                if cancelled():raise PrintError('已取消首次配置。')
                if time.monotonic()-started > 120:raise PrintError('首次下载超时，请检查校园网络后重试。')
                chunk = response.read(64*1024)
                if not chunk:break
                result.extend(chunk)
                if len(result) > MAX_ARCHIVE:raise PrintError('官方安装包超过大小限制。')
                progress(f'正在从学校下载配置来源… {len(result)//1024//1024} MB')
            if declared and len(result) != int(declared):raise PrintError('官方下载未完成，请重试。')
            return bytes(result)
    except PrintError:raise
    except (OSError, ValueError):
        raise PrintError('无法连接学校下载服务，请连接校园内网后重试。') from None


def provision(home, progress=lambda message: None, cancelled=lambda: False, package=None):
    home = private_dir(home)
    if (home/'profile.json').exists():return load_profile(home)
    cache = private_dir(home/'driver-cache')/CACHE_NAME
    if package is not None:
        data = read_private_bytes(package, MAX_ARCHIVE, private=False)
    elif cache.exists():
        progress('正在校验本机缓存…')
        data = read_private_bytes(cache, MAX_ARCHIVE)
        try:verified_package(data)
        except PrintError:
            # A broken cache can be replaced only by a fresh pinned official copy.
            data = download(progress, cancelled)
    else:
        data = download(progress, cancelled)
    verified_package(data)
    if not zipfile.is_zipfile(io.BytesIO(data)):
        wrapped = io.BytesIO()
        name = 'XZPrintClient_{YM10.1.8.5_QDZGCAxZGCIprinter_BBv5_XYhttp_APxzentprint}_5.1.3.12.pkg'
        with zipfile.ZipFile(wrapped, 'w', zipfile.ZIP_DEFLATED) as archive:archive.writestr(name, data)
        data = wrapped.getvalue()
    if cancelled():raise PrintError('已取消首次配置。')
    progress('校验通过，正在配置打印服务…')
    with tempfile.TemporaryDirectory(prefix='.first-run-', dir=home) as temporary:
        stage = Path(temporary)
        source = stage/'MacPrinterClient.zip'
        private_write(source, data)
        import_package(source, stage)
        profile = load_profile(stage)
        if profile['base_url'] != BASE_URL or profile['queue'] != QUEUE:
            raise PrintError('安装包的校园服务配置不匹配，未应用。')
        if cancelled():raise PrintError('已取消首次配置。')
        private_write(cache, data)
        # Publish the profile last: an interrupted first run can retry safely.
        for name in ['printer.ppd', 'printer_param.json', 'profile.json']:
            private_write(home/name, read_private_bytes(stage/name, MAX_ARCHIVE))
    return profile
