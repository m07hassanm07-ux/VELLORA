from pathlib import Path
import os, sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
datas = [(str(ROOT / name), '.') for name in ('LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md')]
if (ROOT / 'licenses').exists():
    datas.append((str(ROOT / 'licenses'), 'licenses'))
datas += collect_data_files('pypdfium2_raw')
datas += collect_data_files('certifi')
# The bundled Codex Python runtime hardens ssl.SSLContext with this local deny
# list.  ssl.py loads it by filename at runtime, so frozen builds must carry it.
rejected_cas = Path(sys.base_prefix) / 'Lib' / 'codex-rejected-cas.pem'
if rejected_cas.is_file():
    datas.append((str(rejected_cas), '.'))
datas.append((str(ROOT / 'assets' / 'ocr'), 'ocr-data'))
datas.append((str(ROOT / 'assets' / 'waraqa-icon.png'), '.'))

a = Analysis(
    [str(ROOT / 'run.py')],
    pathex=[str(ROOT), str(ROOT / '.deps'), str(ROOT / '.deps' / 'win32'), str(ROOT / '.deps' / 'win32' / 'lib')],
    binaries=[], datas=datas,
    hiddenimports=['pypdf._crypt_providers._cryptography', 'pythoncom', 'pywintypes', 'win32timezone']
        + collect_submodules('pyhanko') + collect_submodules('pyhanko_certvalidator'),
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'IPython', 'PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
)
# Windows Qt uses the OS ICU ABI (unversioned C exports). A developer machine's
# PATH can contain a different icuuc.dll, e.g. Poppler's version-suffixed ABI.
# Do not accidentally ship that unrelated runtime in place of Windows ICU.
if os.name == 'nt':
    a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icuin.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Waraqa', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, icon=str(ROOT / 'assets' / 'waraq.ico') if (ROOT / 'assets' / 'waraq.ico').exists() else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Waraqa')
