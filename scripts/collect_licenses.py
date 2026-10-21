"""Copy dependency notices without changing the upstream distributions."""
from pathlib import Path
import importlib.metadata as metadata
import json
import shutil
import sys

root = Path(__file__).resolve().parents[1]
if (root / ".deps").exists():
    sys.path.insert(0, str(root / ".deps"))
destination = root / "licenses"
destination.mkdir(exist_ok=True)
packages = ['PySide6-Essentials', 'shiboken6', 'pypdf', 'pypdfium2', 'Pillow', 'cryptography', 'cffi', 'pycparser', 'pyinstaller', 'pywin32']
versions = {}
for package in packages:
    dist = metadata.distribution(package)
    versions[package] = dist.version
    for item in dist.files or []:
        lowered = str(item).lower()
        if any(word in lowered for word in ('license', 'copyright', 'notice', 'copying')) and not lowered.endswith(('.pyc', '.py')):
            source = Path(dist.locate_file(item))
            if not source.is_file():
                continue
            # Keep original relative filenames so component-specific notices remain identifiable.
            target = destination / package / Path(*[p for p in Path(item).parts if p not in ('..', '.')])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

runtime_license = Path(sys.base_prefix) / 'LICENSE.txt'
if runtime_license.exists():
    shutil.copy2(runtime_license, destination / 'CPython-LICENSE.txt')
(destination / 'dependency-versions.json').write_bytes(json.dumps(versions, indent=2).encode('utf-8'))
(destination / 'DEPENDENCY_SOURCES.md').write_text('''# Matching dependency source references

- PySide / Shiboken 6.10.3: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.3-src/
- Qt 6.10.3: https://download.qt.io/official_releases/qt/6.10/6.10.3/submodules/
- pypdf 6.10.0: https://github.com/py-pdf/pypdf/tree/6.10.0
- pypdfium2 5.14.0: https://pypi.org/project/pypdfium2/5.14.0/#files (source distribution and PDFium build version information)
- PDFium: https://pdfium.googlesource.com/pdfium/ (use the build revision identified in the bundled pypdfium2 notices/version data)
- Pillow 12.3.0: https://pypi.org/project/pillow/12.3.0/#files
- cryptography 50.0.2: https://pypi.org/project/cryptography/50.0.2/#files
- cffi 2.1.1: https://pypi.org/project/cffi/2.1.1/#files
- pycparser 3.11: https://pypi.org/project/pycparser/3.11/#files
- pywin32 311: https://github.com/mhammond/pywin32/tree/b311
- NSIS 3.12: https://sourceforge.net/projects/nsis/files/NSIS%203/3.12/
- CPython 3.12: https://www.python.org/downloads/source/ (match the exact runtime version in build-info.json)

These references identify upstream source locations. Review and meet each dependency's redistribution requirements when publishing binaries. The application source itself is MIT licensed and is provided with this release.
''',encoding='utf-8')
print('Collected licenses for', ', '.join(versions))
nsis_license=root/'.tools'/'nsis-3.12'/'COPYING'
if nsis_license.is_file():
    (destination/'NSIS').mkdir(exist_ok=True)
    shutil.copy2(nsis_license,destination/'NSIS'/'COPYING')
