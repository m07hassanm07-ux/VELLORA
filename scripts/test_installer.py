"""Exercise setup/uninstall only inside a fresh project-local test directory.

/TESTMODE deliberately suppresses registry, default-app and shortcut changes.
The user-created sentinel must survive uninstallation.
"""
from pathlib import Path
import json,os,subprocess,sys,time,uuid,winreg
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from waraq import __version__
setup=root/'release'/f'Vellora-{__version__}-Setup-x64.exe'
target=(root/'tmp'/('installer-test-'+uuid.uuid4().hex[:8])).resolve()
assert target.is_relative_to(root.resolve()/'tmp')
target.mkdir(parents=True)
sentinel=target/'user-created-document.pdf';sentinel.write_bytes(b'user-created-test-document-must-survive')
keys=[r'Software\VelloraPDF',r'Software\Classes\VelloraPDF.Document',r'Software\Classes\Applications\Vellora.exe',r'Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF']
def registry_state():
    result={}
    for name in keys:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,name,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
                values=[]
                for i in range(winreg.QueryInfoKey(key)[1]):values.append(winreg.EnumValue(key,i))
                result[name]=repr(values)
        except FileNotFoundError:result[name]=None
    return result
before=registry_state()
completed=subprocess.run([str(setup),'/S','/TESTMODE',f'/D={target}'],timeout=180)
assert completed.returncode==0,completed.returncode
exe=target/'Vellora.exe';uninstaller=target/'Uninstall.exe'
assert exe.is_file() and exe.read_bytes()[:2]==b'MZ'
assert (target/'_internal'/'PySide6'/'QtPrintSupport.pyd').is_file()
assert (target/'.waraq-install').read_text().strip()=='1'
subprocess.run([str(exe),'--self-test',str(target/'diagnostics')],timeout=90,check=True)
assert json.loads((target/'diagnostics'/'result.json').read_text(encoding='utf-8'))['passed']
subprocess.run([str(uninstaller),'/S'],timeout=120,check=True)
deadline=time.monotonic()+40
while (exe.exists() or (target/'_internal').exists()) and time.monotonic()<deadline:time.sleep(0.2)
assert not exe.exists(),'Installed executable remains after uninstall'
assert not (target/'_internal').exists(),'Runtime files remain after uninstall'
assert sentinel.read_bytes()==b'user-created-test-document-must-survive'
assert registry_state()==before,'Test mode changed application registry keys'
report={'version':__version__,'silent_test_install':True,'installed_executable_self_test':True,'uninstall':True,'user_document_preserved':True,'registry_unchanged_in_test_mode':True,'notes':'Registry registration source was reviewed; test mode intentionally does not apply real file associations or shortcuts.'}
(root/'docs'/'installer-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
