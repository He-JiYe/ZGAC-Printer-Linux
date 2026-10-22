"""Explicit backend subset, shared by the CUPS installer and binary builder.

The system backend only prepares local jobs. It must not ship credentials,
the network client or the desktop UI to its privileged installation directory.
"""
from pathlib import Path
import importlib.metadata as metadata
import shutil

BACKEND_FILES = (
    '__init__.py',
    'common/__init__.py', 'common/errors.py', 'common/runtime.py',
    'config/__init__.py', 'config/profile.py',
    'printing/__init__.py', 'printing/jobs.py', 'printing/completed.py',
    'printing/pdf_worker.py', 'cups/__init__.py', 'cups/backend.py',
)


def copy_backend_package(source, destination):
    """Copy only the reviewed backend files, preserving the package layout."""
    source, destination = Path(source), Path(destination)
    for name in BACKEND_FILES:
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/name, target)


def copy_pdf_dependencies(destination):
    """Bundle the parser and modern typing support, including on Ubuntu 22.04."""
    import pypdf
    import typing_extensions
    destination=Path(destination)
    shutil.copytree(Path(pypdf.__file__).parent,destination/'pypdf',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    distribution=metadata.distribution('pypdf')
    notice=next(item for item in distribution.files if str(item).endswith('/licenses/LICENSE'))
    shutil.copyfile(distribution.locate_file(notice),destination/'pypdf-LICENSE')
    typing_path=Path(typing_extensions.__file__)
    shutil.copyfile(typing_path,destination/'typing_extensions.py')
    notice=typing_path.with_name('typing_extensions-LICENSE')
    if not notice.is_file():
        distribution=metadata.distribution('typing_extensions')
        matches=[item for item in distribution.files or [] if str(item).endswith('/licenses/LICENSE')]
        notice=distribution.locate_file(matches[0]) if matches else Path('/usr/share/doc/python3-typing-extensions/copyright')
    if not notice.is_file():raise RuntimeError('Missing typing_extensions license.')
    shutil.copyfile(notice,destination/'typing_extensions-LICENSE')
