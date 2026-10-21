"""Compile a per-user installer with an explicit non-recursive removal manifest."""
from pathlib import Path
import os,shutil,subprocess,sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from waraq import __version__
distribution=root/'dist'/'WaraqPDF'
if not (distribution/'WaraqPDF.exe').is_file():raise SystemExit('Build the application first.')
for name in ['README.md','LICENSE','THIRD_PARTY_NOTICES.md']:
    shutil.copy2(root/name,distribution/name)
shutil.copytree(root/'licenses',distribution/'licenses',dirs_exist_ok=True)
shutil.copytree(root/'examples',distribution/'examples',dirs_exist_ok=True)
compiler=Path(os.environ.get('NSIS_COMPILER',root/'.tools'/'nsis-3.12'/'makensis.exe'))
if not compiler.is_file():
    detected=shutil.which('makensis')
    if not detected:raise SystemExit('Install NSIS 3.12 or set NSIS_COMPILER to makensis.exe.')
    compiler=Path(detected)
generated=root/'tmp'/'installer';generated.mkdir(parents=True,exist_ok=True)
manifest=generated/'files.nsh'
files=sorted(p for p in distribution.rglob('*') if p.is_file())
def quote(value):return str(value).replace('$','$$').replace('"','$\\"')
install=['!macro WARAQ_INSTALL_FILES']
uninstall=['!macro WARAQ_UNINSTALL_FILES']
directories=set()
for file in files:
    relative=file.relative_to(distribution)
    subfolder=str(relative.parent) if str(relative.parent)!='.' else ''
    install.append('  SetOutPath "$INSTDIR'+('\\'+quote(subfolder) if subfolder else '')+'"')
    install.append(f'  File "/oname={quote(file.name)}" "{quote(file)}"')
    uninstall.append('  Delete "$INSTDIR\\'+quote(relative)+'"')
    directories.update(p for p in relative.parents if str(p)!='.')
for folder in sorted(directories,key=lambda p:len(p.parts),reverse=True):
    uninstall.append('  RMDir "$INSTDIR\\'+quote(folder)+'"')
install.append('!macroend');uninstall.append('!macroend')
manifest.write_text('\n'.join(install+['']+uninstall)+'\n',encoding='utf-8-sig')
script=generated/'WaraqPDF.nsi'
script.write_text((root/'installer'/'WaraqPDF.nsi').read_text(encoding='utf-8'),encoding='utf-8-sig')
out=root/'release'/f'WaraqPDF-{__version__}-Setup-x64.exe';out.parent.mkdir(exist_ok=True)
subprocess.run([str(compiler),'/V2',f'/DPROJECT_ROOT={root}',f'/DAPP_VERSION={__version__}',f'/DSETUP_OUTPUT={out}',f'/DGENERATED_FILES={manifest}',str(script)],check=True)
print(out)
