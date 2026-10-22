"""Build a local Linux executable directory from an explicit, private-data-free input set.

Run in an isolated build environment with the project's pinned PyInstaller extra.
System GTK/Secret Service stay external, accessed by isolated system-Python helpers.
"""
from pathlib import Path
import ast
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
from release_audit import audit_sources
from zgcaprint import __version__
from zgcaprint.config.profile import default_home, read_private
from zgcaprint.cups.payload import copy_backend_package, copy_pdf_dependencies


def license_file(distribution,suffix):
    package=metadata.distribution(distribution)
    item=next(v for v in package.files if str(v).endswith(suffix))
    return package.locate_file(item)


def source_entries(value):
    if isinstance(value,(list,tuple)):
        if len(value)==3 and all(isinstance(x,str) for x in value) and value[2] in ['BINARY','EXTENSION']:
            yield (value[0],value[1])
        else:
            for item in value:yield from source_entries(item)


def native_notices(analysis,output):
    """Keep exact distribution copyright notices for native bundled libraries."""
    packages={};unmapped=[]
    paths=sorted(set(source_entries(ast.literal_eval(analysis.read_text()))))
    for destination,name in paths:
        if not (output.parent/'_internal'/destination).exists():continue
        path=Path(name)
        if not str(path).startswith(('/usr/','/lib/')):continue
        query=subprocess.run(['dpkg-query','-S',str(path)],capture_output=True,text=True)
        if query.returncode:
            query=subprocess.run(['dpkg-query','-S',str(path.resolve())],capture_output=True,text=True)
        if query.returncode:unmapped.append(path.name);continue
        for line in query.stdout.splitlines():
            package=line.split(': ',1)[0]
            if package in packages:continue
            fields=subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}',package],text=True).split('\t')
            notice=Path('/usr/share/doc')/package.split(':')[0]/'copyright'
            if not notice.is_file():unmapped.append(path.name);continue
            target=package.replace(':','_')+'-copyright.txt'
            shutil.copyfile(notice,output/target)
            packages[package]={'package':fields[0],'version':fields[1],'source_package':fields[2],
                'source_version':fields[3],'notice':target,'source_location':'https://archive.ubuntu.com/ubuntu/pool/'}
    if unmapped:raise SystemExit('Missing native-library notices: '+', '.join(sorted(set(unmapped))))
    return list(packages.values())


def main():
    inputs,secrets=audit_sources()
    source_hashes={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    if platform.system()!='Linux':raise SystemExit('Build on the target Linux platform.')
    if metadata.version('pyinstaller')!='6.22.3':raise SystemExit('Use the pinned PyInstaller 6.22.3 build extra.')
    work=ROOT/'build/binary';work.mkdir(parents=True,exist_ok=True)
    stage=work/'inputs'
    if stage.exists():shutil.rmtree(stage)
    source=ROOT/'src/zgcaprint'
    payload=stage/'backend_payload';package=payload/'zgcaprint'
    copy_backend_package(source,package)
    import pypdf
    copy_pdf_dependencies(payload)
    shutil.copyfile(ROOT/'LICENCE',payload/'LICENCE')
    helpers=stage/'system_helpers';helper_package=helpers/'zgcaprint'
    for name in ['__init__.py','common/__init__.py','common/errors.py','config/__init__.py','config/keyring.py']:
        (helper_package/name).parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,helper_package/name)
    shutil.copyfile(source/'desktop/tray.py',helpers/'tray.py')
    (helpers/'keyring_entry.py').write_text("from pathlib import Path\nimport sys\nsys.path.insert(0,str(Path(__file__).resolve().parent))\nfrom zgcaprint.config.keyring import stdio\nraise SystemExit(stdio())\n")
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','ZGCA-Print',
        '--distpath',str(work/'dist'),'--workpath',str(work/'pyinstaller'),'--specpath',str(work),
        '--paths',str(ROOT/'src'),'--copy-metadata','pypdf']
    for module in ['gi','cryptography','Crypto','pytest','numpy','matplotlib','PIL','IPython','readline','dbm','tkinter.test','fontTools','lxml','brotli','lz4','zopfli','unicodedata2']:
        command+=['--exclude-module',module]
    for path,name in [(payload,'backend_payload'),(helpers,'system_helpers')]:command+=['--add-data',str(path)+':'+name]
    command.append(str(source/'application/entry.py'))
    subprocess.run(command,check=True)
    distribution=work/'dist/ZGCA-Print'
    # Use the distribution's LGPL crypto library instead of embedding a copy.
    for path in (distribution/'_internal').glob('libgcrypt.so*'):path.unlink()
    for path in (distribution/'_internal').glob('libgpg-error.so*'):path.unlink()
    for name in ['README.md','LICENCE']:
        shutil.copyfile(ROOT/name,distribution/name)
    (distribution/'examples').mkdir()
    shutil.copyfile(ROOT/'examples/print-test.pdf',distribution/'examples/print-test.pdf')
    notices=distribution/'licenses';notices.mkdir()
    shutil.copyfile(license_file('pyinstaller','/COPYING.txt'),notices/'PyInstaller-COPYING.txt')
    shutil.copyfile(license_file('pypdf','/licenses/LICENSE'),notices/'pypdf-LICENSE')
    common=Path('/usr/share/common-licenses')
    for path in common.iterdir():
        if path.is_file():shutil.copyfile(path,notices/('common-'+path.name+'.txt'))
    native=native_notices(work/'pyinstaller/ZGCA-Print/Analysis-00.toc',notices)
    from PyInstaller.archive.readers import CArchiveReader
    reader=CArchiveReader(str(distribution/'ZGCA-Print'))
    python_archive=reader.open_embedded_archive(next(name for name in reader.toc if name.endswith('.pyz')))
    roots={name.split('.')[0] for name in python_archive.toc}
    unexpected={name for name in roots-set(sys.stdlib_module_names)-{'zgcaprint','pypdf','typing_extensions'} if not name.startswith('_sysconfigdata_')}
    if unexpected:raise SystemExit('Review additional Python dependencies before release: '+', '.join(sorted(unexpected)))
    python_packages=[{'package':'pypdf','version':pypdf.__version__,'notice':'pypdf-LICENSE'}]
    if 'typing_extensions' in roots:
        try:typing_notice=license_file('typing_extensions','/licenses/LICENSE')
        except (StopIteration,TypeError):typing_notice=Path('/usr/share/doc/python3-typing-extensions/copyright')
        if not typing_notice.is_file():raise SystemExit('Missing typing_extensions license notice.')
        shutil.copyfile(typing_notice,notices/'typing_extensions-LICENSE')
        python_packages.append({'package':'typing_extensions','version':metadata.version('typing_extensions'),'notice':'typing_extensions-LICENSE'})
    info={'project':'zgcaprint','version':__version__,'system':platform.system(),'machine':platform.machine(),
        'build_os':platform.freedesktop_os_release().get('PRETTY_NAME'),'glibc':platform.libc_ver(),
        'python':platform.python_version(),'pyinstaller':metadata.version('pyinstaller'),'pypdf':pypdf.__version__,
        'status':'experimental; validated only on the build host','native_packages':native,'python_packages':python_packages,'source_sha256':source_hashes,
        'external_dependencies':['system Python >=3.10','CUPS 2.x','libgcrypt','python3-gi and libsecret for remembered passwords',
            'GTK3 and Ayatana AppIndicator for tray','xdg-utils for browser preview']}
    (distribution/'BUILD-INFO.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n')
    audit_sources()
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=value for name,value in source_hashes.items()):
        raise SystemExit('Public inputs changed during the build; rebuild before releasing.')
    forbidden={'profile.json','preferences.json','printer.ppd','completed-index.json','MacPrinterClient.zip','Setup_Client.exe'}
    for path in distribution.rglob('*'):
        if path.is_symlink():
            if not path.resolve().is_relative_to(distribution.resolve()):raise SystemExit('Bundle contains an external symlink.')
            continue
        if not path.is_file():continue
        if path.name in forbidden or any(value in path.read_bytes() for value in secrets):raise SystemExit('Private-data scan failed.')
    tag='linux-'+platform.machine()+'-ubuntu'+platform.freedesktop_os_release().get('VERSION_ID','unknown')
    output=ROOT/'dist'/f'zgcaprint-{__version__}-{tag}'
    if output.exists():
        marker=output/'BUILD-INFO.json'
        if not marker.is_file() or json.loads(marker.read_text()).get('project')!='zgcaprint':raise SystemExit('Unrecognized existing output directory.')
        shutil.rmtree(output)
    output.parent.mkdir(exist_ok=True);shutil.copytree(distribution,output,symlinks=True)
    archive=output.with_name(output.name+'.tar.gz')
    def archive_metadata(info):
        info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
        return info
    with tarfile.open(archive,'w:gz') as tar:tar.add(output,arcname=output.name,filter=archive_metadata)
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name+'.sha256').write_text(checksum+'  '+archive.name+'\n')
    print(output/'ZGCA-Print');print(archive)


if __name__=='__main__':main()
