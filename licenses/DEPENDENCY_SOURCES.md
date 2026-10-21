# Matching dependency source references

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
