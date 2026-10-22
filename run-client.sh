#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
client_python=python3
if [ -x .venv/bin/python ]; then client_python=.venv/bin/python; fi
if [ -f .local/profile.json ]; then
    client_home=.local
else
    client_home=$("$client_python" -c 'from zgcaprint.config.profile import default_home; print(default_home())')
fi
if [ ! -f "$client_home/profile.json" ]; then
    if [ -f MacPrinterClient.zip ]; then
        "$client_python" -m zgcaprint --home "$client_home" import-mac MacPrinterClient.zip
    else
        echo "请先用 import-mac 命令导入自己的 Mac 安装包。" >&2
        exit 1
    fi
fi
# Campus compatibility: explicit opt-in to the deployed HTTP/FTP service.
exec "$client_python" -m zgcaprint --home "$client_home" gui --allow-http "$@"
