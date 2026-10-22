"""PDF parser child with CPU/address-space limits; inherits the caller's UID."""
from pathlib import Path
import json
import os
import resource
import sys


def main():
    if os.getuid()==0:
        print(json.dumps({'error':'PDF 解析拒绝以 root 身份运行，请使用普通用户。'}));return
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (1024*1024*1024, 1024*1024*1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from zgcaprint.printing.jobs import MAX_PDF, _inspect_pdf
    from zgcaprint.common.errors import PrintError
    try:
        info = _inspect_pdf(sys.stdin.buffer.read(MAX_PDF+1))
        print(json.dumps({'info': info}))
    except PrintError as exc:
        print(json.dumps({'error': str(exc)}))
    except Exception:
        print(json.dumps({'error': 'PDF 无法解析，请重新导出后重试。'}))


if __name__ == '__main__':
    main()
