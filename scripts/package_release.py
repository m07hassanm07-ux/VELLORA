"""Package only original source and explicitly selected distribution outputs."""
from pathlib import Path
import hashlib,json,platform,shutil,sys,zipfile
from datetime import date

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from waraq import __version__
release=root/'release';release.mkdir(exist_ok=True)
version=__version__
source=release/f'Vellora-{version}-source.zip'
folders=['waraq','tests','scripts','docs','assets','examples','licenses','installer']
files=['run.py','pyproject.toml','requirements.txt','requirements-build.txt','build.ps1','WaraqPDF.spec','README.md','ROADMAP.md','LICENSE','THIRD_PARTY_NOTICES.md','CONTRIBUTING.md','SECURITY.md','.gitignore','.gitattributes']
with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for name in files:
        archive.write(root/name,'Vellora-source/'+name)
    for folder in folders:
        for path in sorted((root/folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                archive.write(path,'Vellora-source/'+path.relative_to(root).as_posix())

distribution=root/'dist'/'Vellora'
if not (distribution/'Vellora.exe').exists():
    raise SystemExit('Build the Windows distribution before packaging the binary archive.')
# Keep notices and basic instructions visible beside the executable, as well as
# bundled inside _internal. No license from the dependency bundle is omitted.
for name in ['README.md','LICENSE','THIRD_PARTY_NOTICES.md']:
    shutil.copy2(root/name,distribution/name)
shutil.copytree(root/'licenses',distribution/'licenses',dirs_exist_ok=True)
shutil.copytree(root/'examples',distribution/'examples',dirs_exist_ok=True)
binary=release/f'Vellora-{version}-windows-x64.zip'
with zipfile.ZipFile(binary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for path in sorted(distribution.rglob('*')):
        if path.is_file():
            archive.write(path,'Vellora/'+path.relative_to(distribution).as_posix())
for path in (source,binary):
    with zipfile.ZipFile(path) as archive:
        invalid=archive.testzip()
        if invalid: raise RuntimeError('Corrupt archive member: '+invalid)
setup=release/f'Vellora-{version}-Setup-x64.exe'
outputs=[source,binary,distribution/'Vellora.exe']+([setup] if setup.is_file() else [])
checksums={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in outputs}
(release/'SHA256SUMS.txt').write_text(''.join(f'{digest}  {name}\n' for name,digest in checksums.items()),encoding='utf-8')
tests=json.loads((root/'docs'/'test-results.json').read_text(encoding='utf-8'))
info={'application':'VELLORA','version':version,'build_date_local':date.today().isoformat(),'platform':platform.platform(),'python':platform.python_version(),'license_for_original_code':'MIT','tests_passed':tests['tests_run'] if tests['passed'] else 0,'archives':{p.name:p.stat().st_size for p in (source,binary)},'sha256':checksums,'native_packaged_check':'See native-check.json and installer-results.json in this directory.'}
(release/'build-info.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
print(json.dumps(info,indent=2))
