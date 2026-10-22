"""Package identity, safe legacy launcher cleanup and install result messages."""
from pathlib import Path
import importlib.util
import subprocess
import sys

from zgcaprint.common import runtime
from zgcaprint.desktop import startup


def test_package_and_development_launchers_use_separate_names(monkeypatch,tmp_path):
    monkeypatch.setattr(runtime,'resource_root',lambda:tmp_path/'source')
    assert startup.entry_name()==startup.SOURCE_NAME
    assert '（开发版）' in startup.content(tmp_path)
    monkeypatch.setattr(runtime,'resource_root',lambda:Path('/usr/lib/zgcaprint/zgcaprint'))
    content=startup.content(tmp_path,True)
    assert startup.entry_name()==startup.NAME
    assert 'Exec="/usr/bin/zgcaprint"' in content and 'TryExec=/usr/bin/zgcaprint' in content
    assert '/application/launcher.py' not in content and '开发版' not in content


def test_legacy_source_entries_are_backed_up_without_touching_package_entry_or_data(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    source=startup.directory(False)/startup.NAME
    source.parent.mkdir(parents=True);source.parent.chmod(0o755)
    original=startup.MARKER+'\nExec="/synthetic/.venv/bin/python" "/synthetic/src/zgcaprint/application/launcher.py" gui\n'
    source.write_text(original)
    package=startup.directory(True)/startup.NAME
    package.parent.mkdir(parents=True);package.parent.chmod(0o755)
    package.write_text(startup.MARKER+'\nExec=/usr/bin/python3 /usr/lib/zgcaprint/zgcaprint/application/launcher.py gui\n')
    other=source.with_name('other.desktop');other.write_text('unrelated')
    home=tmp_path/'private';home.mkdir(mode=0o700)
    document=home/'document.pdf';document.write_bytes(b'synthetic document')
    backups=startup.quarantine_legacy_sources(home)
    assert len(backups)==1 and backups[0].read_text()==original
    assert not source.exists() and package.exists() and other.read_text()=='unrelated'
    assert document.read_bytes()==b'synthetic document'
    assert backups[0].stat().st_mode & 0o077==0
    assert startup.quarantine_legacy_sources(home)==[]


def test_install_scripts_verify_files_and_print_clear_results(tmp_path,monkeypatch):
    tools=Path(__file__).resolve().parents[1]/'tools'
    monkeypatch.syspath_prepend(str(tools))
    spec=importlib.util.spec_from_file_location('zgca_deb_build_messages',tools/'build_deb.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    builder.write_maintainer_scripts(tmp_path,'9.9.9')
    for name in ['postinst','postrm']:
        subprocess.run(['/bin/sh','-n',str(tmp_path/name)],check=True)
    entry=tmp_path/'zgcaprint';entry.write_text('#!/bin/sh\necho 9.9.9\n');entry.chmod(0o755)
    launcher=tmp_path/'launcher.py';launcher.touch()
    menu=tmp_path/'app.desktop';menu.touch()
    check=(tmp_path/'postinst').read_text().replace('/usr/bin/zgcaprint',str(entry)).replace('/usr/lib/zgcaprint/launcher.py',str(launcher)).replace('/usr/share/applications/org.zgcaprint.Client.desktop',str(menu))
    script=tmp_path/'check.sh';script.write_text(check)
    result=subprocess.run(['/bin/sh',str(script),'configure'],capture_output=True,text=True)
    assert result.returncode==0 and '客户端安装完成（版本 9.9.9）' in result.stdout
    assert '\\n' not in result.stdout
    entry.write_text('#!/bin/sh\necho WRONG\n')
    result=subprocess.run(['/bin/sh',str(script),'configure'],capture_output=True,text=True)
    assert result.returncode!=0 and '安装完成' not in result.stdout
    result=subprocess.run(['/bin/sh',str(tmp_path/'postrm'),'remove'],capture_output=True,text=True)
    assert result.returncode==0 and '程序已卸载' in result.stdout and '用户数据和系统钥匙串保留' in result.stdout
