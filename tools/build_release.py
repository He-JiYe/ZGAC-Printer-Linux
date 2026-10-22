"""Create only the audited source allowlist, never an archive of the workspace."""
from pathlib import Path
import re
import zipfile
from release_audit import ROOT,audit_sources


def main():
    files,_=audit_sources()
    version=re.search(r'__version__ = "([^"]+)"',(ROOT/'src/zgcaprint/__init__.py').read_text()).group(1)
    output=ROOT/f'dist/zgcaprint-{version}-source.zip';output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:archive.write(path,Path('zgcaprint-'+version)/path.relative_to(ROOT))
    print(output)
    print(f'Allowlist: {len(files)} public files including the sample PDF; no private profiles, vendor files or user documents.')


if __name__=='__main__':main()
