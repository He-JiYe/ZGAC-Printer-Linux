"""Frozen entry point; child PDF parsing reuses the executable explicitly."""
import sys


def main():
    if sys.argv[1:]==['_pdf-worker']:
        from zgcaprint.printing.pdf_worker import main as worker
        worker()
        return 0
    from zgcaprint.application.cli import main as cli
    return cli(sys.argv[1:] or ['gui','--allow-http'])


if __name__=='__main__':
    raise SystemExit(main())
