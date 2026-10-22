"""Exercise process boundaries that can break when source packages move."""
from pathlib import Path
import json
import subprocess
import sys

from zgcaprint import __version__
from zgcaprint.application import launcher
from zgcaprint.cups import installer
from tests.test_client import pdf_bytes


def test_desktop_launcher_runs_from_an_unrelated_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, '-I', str(Path(launcher.__file__)), '--version'],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == __version__


def test_generated_backend_is_self_contained_and_has_no_upload_or_credentials(tmp_path, monkeypatch):
    home = tmp_path/'private'
    home.mkdir(mode=0o700)
    (home/'printer.ppd').write_text('*PPD-Adobe: "4.3"\n')
    monkeypatch.setattr(installer, 'load_profile', lambda _: {'queue': 'TEST'})
    script = installer.generate(home, tmp_path/'install.sh')
    bundle = script.with_name('install.files')
    subprocess.run(['/bin/sh', '-n', str(script)], check=True, timeout=10)
    assert not (bundle/'zgcaprint/protocol').exists()
    assert not (bundle/'zgcaprint/config/credentials.py').exists()
    assert not (bundle/'profile.json').exists()
    assert (bundle/'typing_extensions.py').is_file()
    assert (bundle/'typing_extensions-LICENSE').is_file()
    # Isolated system Python cannot fall back to the editable source install.
    command = (
        'import sys; sys.path.insert(0,sys.argv[1]); '
        'from zgcaprint.cups.backend import run; raise SystemExit(run(["backend"]))'
    )
    result = subprocess.run(['/usr/bin/python3', '-I', '-c', command, str(bundle)],
                            cwd=tmp_path, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert b'zgcaprint:/' in result.stdout
    result = subprocess.run(
        ['/usr/bin/python3', '-I', str(bundle/'zgcaprint/printing/pdf_worker.py')],
        cwd=tmp_path, input=pdf_bytes(), capture_output=True, timeout=25,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['info']['total_pages'] == 1
