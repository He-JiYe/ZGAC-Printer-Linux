"""Absolute-file entry point for desktop launchers, independent of working dir."""
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from zgcaprint.application.cli import main
    raise SystemExit(main())
