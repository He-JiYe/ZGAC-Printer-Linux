import argparse
import getpass
import json
import os
from pathlib import Path
import sys

from zgcaprint import __version__
from zgcaprint.common.errors import PrintError
from zgcaprint.printing.jobs import load_job, prepare, remove_job
from zgcaprint.config.profile import default_home, import_package, json_write, load_profile, read_private_bytes
from zgcaprint.protocol.client import V5Client


def parser():
    p = argparse.ArgumentParser(description='Linux 刷卡打印客户端；prepare/preview 均不会联网。')
    p.add_argument('--home', type=Path, default=default_home(), help='私有配置和本地作业目录')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('check-runtime', help='离线检查 PDF 子进程与加密库，不访问学校服务')
    q.add_argument('--gui', action='store_true', help='同时显示短暂的合成界面检查窗口')
    q = sub.add_parser('setup', help='从学校自动下载并校验首次配置，保留已有配置')
    q.add_argument('--allow-http', action='store_true')
    q = sub.add_parser('import-mac', help='从自己的 Mac ZIP/PKG 导入配置，不执行安装包')
    q.add_argument('package', type=Path)
    q = sub.add_parser('prepare', help='离线准备 PDF')
    q.add_argument('pdf', type=Path)
    q.add_argument('--copies', type=int, default=1)
    q.add_argument('--duplex', choices=['off', 'long', 'short'], default='off')
    q.add_argument('--color', choices=['gray', 'color'], default='gray')
    q = sub.add_parser('preview', help='查看本地打印参数')
    q.add_argument('job_id')
    sub.add_parser('list', help='列出本地作业')
    q = sub.add_parser('remove', help='清除本地已完成或尚未提交的作业；不取消服务器作业')
    q.add_argument('job_id')
    q = sub.add_parser('doctor', help='测试客户端令牌和存储配置，不提交文档或用户密码')
    q.add_argument('--allow-http', action='store_true')
    q = sub.add_parser('allow-storage', help='将管理员确认的文件上传主机加入本机允许列表')
    q.add_argument('host')
    q = sub.add_parser('submit', help='提交已准备的作业，需要 --send')
    q.add_argument('job_id')
    q.add_argument('--user', required=True)
    q.add_argument('--send', action='store_true', help='明确发送到服务器，可能占用打印额度')
    q.add_argument('--allow-http', action='store_true')
    q = sub.add_parser('gui', help='打开图形界面；浏览器任务按自动提交设置处理')
    q.add_argument('--allow-http', action='store_true')
    q.add_argument('--background', action='store_true', help='启动后收起到后台')
    q = sub.add_parser('autostart', help='设置当前用户的桌面登录自动启动')
    q.add_argument('action', choices=['enable', 'disable', 'status'])
    q.add_argument('--allow-http', action='store_true')
    q = sub.add_parser('install-cups', help='生成系统打印队列安装脚本，随后由用户审阅和执行')
    q.add_argument('--output', type=Path, default=Path('install-zgcaprint-cups.sh'))
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if os.getuid()==0:raise PrintError('请使用普通桌面用户运行打印驱动，不要使用 sudo 或 root。')
        if args.command == 'check-runtime':
            from zgcaprint.application.diagnostics import check
            print(json.dumps(check(args.gui),ensure_ascii=False,indent=2))
        elif args.command == 'setup':
            if not args.allow_http:raise PrintError('学校首次配置使用 HTTP，请加 --allow-http 明确允许。')
            from zgcaprint.config.bootstrap import provision
            provision(args.home)
            print('首次配置已就绪，已有配置已保留。')
        elif args.command == 'import-mac':
            print(json.dumps(import_package(args.package, args.home), ensure_ascii=False, indent=2))
            print('已导入私有配置。原厂程序未安装，账号和密码未保存。')
        elif args.command == 'prepare':
            from zgcaprint.printing.jobs import MAX_PDF
            job = prepare(args.home, read_private_bytes(args.pdf, MAX_PDF, private=False), args.pdf.name, args.copies,
                          {'off': 1, 'long': 2, 'short': 3}[args.duplex],
                          1 if args.color == 'gray' else 2)
            print(json.dumps(job, ensure_ascii=False, indent=2))
        elif args.command == 'preview':
            print(json.dumps(load_job(args.home, args.job_id), ensure_ascii=False, indent=2))
        elif args.command == 'list':
            from zgcaprint.printing.jobs import adopt_cups_jobs
            adopt_cups_jobs(args.home)
            for p in sorted((args.home/'jobs').glob('*/job.json')):
                try:
                    j = load_job(args.home, p.parent.name)
                    print(f'{j["id"]}  {j["state"]:12}  {j["total_pages"]} 页 × {j["copies"]}  {j["doc_name"]}')
                except PrintError:
                    print('跳过无法验证的作业记录。', file=sys.stderr)
        elif args.command == 'remove':
            remove_job(args.home, args.job_id)
            print('已清除本地作业。服务器上的作业不受影响。')
        elif args.command == 'doctor':
            from zgcaprint.protocol.crypto import twofish
            known = twofish(bytes(16), bytes(16)).hex().upper()
            if known != '9F589F5CF6122C32B6BFEC2F2AE8C35A':
                raise PrintError('系统 Twofish 算法未通过已知向量验证。')
            profile = load_profile(args.home)
            client = V5Client(profile, args.allow_http)
            client.check()
            storage = client.storages()
            safe = [{'storage_id': s.get('ID'), 'equipment_id': s.get('EquipId'), 'type': s.get('StorageType'), 'file_enc_type': s.get('FileEncType', 0),
                     'host': s.get('IP', s.get('Ip', s.get('Host'))), 'port': s.get('Port')} for s in storage]
            print(json.dumps({'client_token': 'ok (not saved)', 'service': 'ok', 'storages': safe}, ensure_ascii=False, indent=2))
        elif args.command == 'allow-storage':
            import re
            if not re.fullmatch(r'[A-Za-z0-9.-]+', args.host):
                raise PrintError('上传主机格式无效。')
            profile = load_profile(args.home)
            profile['storage_allowed_hosts'] = sorted(set(profile['storage_allowed_hosts'] + [args.host]))
            json_write(args.home/'profile.json', profile)
            print('已更新本机上传主机允许列表。')
        elif args.command == 'submit':
            if not args.send:
                raise PrintError('尚未发送。确认参数后加 --send 才会提交打印作业。')
            profile = load_profile(args.home)
            password = getpass.getpass('打印账号密码（不保存）：')
            try:
                job = V5Client(profile, args.allow_http).submit(args.home, args.job_id, args.user, password)
            finally:
                password = None
            print(f'提交成功，服务器作业编号 {job["server_id"]}。请到打印点刷卡查看作业。')
        elif args.command == 'gui':
            from zgcaprint.ui.window import run
            run(args.home, args.allow_http, args.background)
        elif args.command == 'autostart':
            from zgcaprint.desktop import startup
            if args.action != 'status':
                startup.install(args.home,args.allow_http,autostart=True,enable=args.action=='enable')
                if args.action=='enable':startup.install(args.home,args.allow_http)
            print('桌面登录自动启动：'+('已开启' if startup.enabled() else '已关闭'))
        elif args.command == 'install-cups':
            from zgcaprint.cups.installer import generate
            generate(args.home, args.output)
            print(f'已生成安装脚本：{args.output.resolve()}，尚未修改系统打印配置。')
    except (PrintError, OSError, ValueError, KeyError) as exc:
        # Raw low-level exceptions may include private filenames, but never echo
        # request bodies, server error bodies, profiles or encoded passwords.
        if isinstance(exc, PrintError):
            message = str(exc)
        else:
            message = f'操作未完成（{type(exc).__name__}），请检查输入文件和配置。'
        print(message, file=sys.stderr)
        return 2
    return 0
