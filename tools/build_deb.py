"""Build the installable release without vendor software or user configuration.

The .deb uses Ubuntu's Python/desktop libraries and bundles only our Python
package and audited pypdf. apt resolves dependencies; first-run setup runs as
the logged-in user, never as a package maintainer script.
"""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from release_audit import audit_sources
from zgcaprint import __version__

DEPENDENCIES = ('python3 (>= 3.10), python3-tk, python3-gi, python3-typing-extensions, '
    'gir1.2-secret-1, gir1.2-ayatanaappindicator3-0.1, gnome-keyring, libgcrypt20, '
    'cups (>= 2.2), cups (<< 3.0), cups-client, cups-filters, pkexec | policykit-1, xdg-utils')


def build():
    inputs, secrets = audit_sources()
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    import pypdf
    work = ROOT/'build/deb'
    if work.exists():shutil.rmtree(work)
    app = work/'usr/lib/zgcaprint'
    for source in (ROOT/'src/zgcaprint').rglob('*.py'):
        target = app/'zgcaprint'/source.relative_to(ROOT/'src/zgcaprint')
        target.parent.mkdir(parents=True, exist_ok=True);shutil.copyfile(source, target)
    work.chmod(0o755)
    shutil.copytree(Path(pypdf.__file__).parent, app/'pypdf', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    distribution = metadata.distribution('pypdf')
    record = next(v for v in distribution.files if str(v).endswith('.dist-info/METADATA'))
    metadata_dir = distribution.locate_file(record).parent
    shutil.copytree(metadata_dir, app/metadata_dir.name)
    # Never copy editable-install metadata, local paths or per-user preferences.
    for name in ['direct_url.json', 'INSTALLER', 'REQUESTED']:(app/metadata_dir.name/name).unlink(missing_ok=True)
    shutil.copyfile(ROOT/'LICENCE', app/'LICENCE')
    (app/'launcher.py').write_text('from pathlib import Path\nimport sys\nsys.path.insert(0,str(Path(__file__).resolve().parent))\nfrom zgcaprint.application.cli import main\nraise SystemExit(main(sys.argv[1:] or ["gui","--allow-http"]))\n')
    command = work/'usr/bin/zgcaprint';command.parent.mkdir(parents=True)
    command.write_text('#!/bin/sh\nexec /usr/bin/python3 -I /usr/lib/zgcaprint/launcher.py "$@"\n')
    menu = work/'usr/share/applications/org.zgcaprint.Client.desktop';menu.parent.mkdir(parents=True)
    menu.write_text('[Desktop Entry]\nType=Application\nVersion=1.0\nName=ZGCA Linux 打印驱动\nComment=校园 PDF 与浏览器刷卡打印\nExec=zgcaprint gui --allow-http\nTryExec=zgcaprint\nIcon=printer\nTerminal=false\nCategories=Utility;\nStartupNotify=false\n')
    documentation = work/'usr/share/doc/zgcaprint';documentation.mkdir(parents=True)
    shutil.copyfile(ROOT/'README.md', documentation/'README.md')
    (documentation/'examples').mkdir()
    shutil.copyfile(ROOT/'examples/print-test.pdf', documentation/'examples/print-test.pdf')
    license_file = next(v for v in distribution.files if str(v).endswith('/licenses/LICENSE'))
    pypdf_license = distribution.locate_file(license_file).read_text()
    (documentation/'copyright').write_text('Project: ZGCA Linux print driver\nOriginal code: MIT\n\n'+(ROOT/'LICENCE').read_text()+'\n\nBundled pypdf: BSD-3-Clause\n\n'+pypdf_license)
    info = {'project':'zgcaprint', 'version':__version__, 'format':'deb', 'architecture':'all',
        'runtime':'system Python >=3.10; system CUPS 2.x', 'pypdf':pypdf.__version__,
        'source_sha256':hashes, 'vendor_files_included':False}
    (documentation/'BUILD-INFO.json').write_text(json.dumps(info, indent=2)+'\n')
    for path in work.rglob('*'):
        if path.is_symlink():raise SystemExit('Unexpected symlink in package staging.')
        if path.is_dir():path.chmod(0o755)
        else:
            path.chmod(0o644)
            if any(value in path.read_bytes() for value in secrets):raise SystemExit('Private-data scan failed.')
    command.chmod(0o755)
    control = work/'DEBIAN';control.mkdir(mode=0o755)
    size = sum(p.stat().st_size for p in (work/'usr').rglob('*') if p.is_file())
    (control/'control').write_text(f'Package: zgcaprint\nVersion: {__version__}\nSection: utils\nPriority: optional\nArchitecture: all\nMaintainer: ZGCA Print contributors\nDepends: {DEPENDENCIES}\nInstalled-Size: {(size+1023)//1024}\nHomepage: https://github.com/He-JiYe/ZGAC-Printer-Linux\nDescription: ZGCA Linux PDF and browser print client\n Non-official campus printing adapter with automatic first-run setup.\n No vendor installer, account, password or private profile is bundled.\n')
    (control/'control').chmod(0o644)
    audit_sources()
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=value for name,value in hashes.items()):
        raise SystemExit('Public inputs changed during build; rebuild before releasing.')
    output = ROOT/'dist'/f'zgcaprint_{__version__}_all.deb';output.parent.mkdir(exist_ok=True)
    subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(work), str(output)], check=True)
    output.with_name(output.name+'.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n')
    print(output)
    return output


if __name__ == '__main__':build()
