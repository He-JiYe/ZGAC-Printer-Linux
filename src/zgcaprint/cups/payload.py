"""Explicit backend subset, shared by the CUPS installer and binary builder.

The system backend only prepares local jobs. It must not ship credentials,
the network client or the desktop UI to its privileged installation directory.
"""
from pathlib import Path
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
