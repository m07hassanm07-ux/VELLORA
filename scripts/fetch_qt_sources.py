"""Retain matching upstream Qt sources and their original licensing notices.

This optional maintainer operation downloads source archives only. It never
executes downloaded code or extracts source files to arbitrary archive paths.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,tarfile,urllib.request

root=Path(__file__).resolve().parents[1]
folder=root/'release'/'dependency-sources';folder.mkdir(parents=True,exist_ok=True)
urls=[
 'https://download.qt.io/official_releases/qt/6.10/6.10.3/submodules/qtbase-everywhere-src-6.10.3.tar.xz',
 'https://download.qt.io/official_releases/qt/6.10/6.10.3/submodules/qtsvg-everywhere-src-6.10.3.tar.xz',
 'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.3-src/pyside-setup-everywhere-src-6.10.3.tar.xz',
]

def fetch(url):
    path=folder/url.rsplit('/',1)[-1]
    if not path.exists():
        temporary=path.with_suffix(path.suffix+'.partial')
        with urllib.request.urlopen(url,timeout=45) as response, temporary.open('wb') as out:
            while data:=response.read(1024*1024):out.write(data)
        temporary.replace(path)
    count=0
    # Copy only ordinary notice/license text, and sanitize every member name.
    with tarfile.open(path,'r:xz') as archive:
        for member in archive:
            parts=Path(member.name).parts
            lower=member.name.lower()
            if not member.isfile() or member.size>2*1024*1024 or '..' in parts:continue
            if not (any(part.lower()=='licenses' for part in parts) or Path(member.name).name.lower().startswith(('license','copying','copyright','notice')) or lower.endswith('qt_attribution.json')):continue
            target=root/'licenses'/'Qt-source-notices'/path.stem/Path(*parts[1:])
            target.parent.mkdir(parents=True,exist_ok=True)
            source=archive.extractfile(member)
            if source is not None:target.write_bytes(source.read());count+=1
    return {'file':path.name,'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'notice_files':count}

with ThreadPoolExecutor(max_workers=3) as executor:
    records=list(executor.map(fetch,urls))
(folder/'SOURCES.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
(folder/'README.md').write_text('# Corresponding upstream source archives\n\nUnmodified Qt Base, Qt SVG and PySide/Shiboken 6.10.3 source archives obtained from the official Qt release server. They include their build scripts and notices. SOURCES.json records the download URLs and SHA-256 hashes. Keep these sources accessible together with a redistributed Windows binary, along with the Waraq application source. No source archive is executed by the application.\n',encoding='utf-8')
print(json.dumps(records,indent=2))
