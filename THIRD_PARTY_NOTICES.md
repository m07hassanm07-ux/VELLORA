# Third-party notices

The MIT license in LICENSE applies to original Waraq PDF application code. It does not replace the licenses of the dependencies or grant rights to Adobe software. No Adobe software is included.

Runtime dependencies:

| Component | Version used | License information | Upstream |
|---|---|---|---|
| PySide6 Essentials / Qt | 6.10.3 | LGPL-3.0 / GPL / commercial alternatives; the application uses Qt Core, GUI and Widgets under the applicable open-source terms | https://code.qt.io/pyside/pyside-setup.git |
| Shiboken6 | 6.10.3 | LGPL-3.0 / GPL / commercial alternatives | https://code.qt.io/pyside/pyside-setup.git |
| pypdf | 6.10.0 | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| pypdfium2 | 5.14.0 | Apache-2.0 or BSD-3-Clause wrapper; bundled PDFium and its dependencies carry additional notices | https://github.com/pypdfium2-team/pypdfium2 |
| PDFium | bundled by pypdfium2 | BSD-style and component-specific notices | https://pdfium.googlesource.com/pdfium/ |
| Pillow | 12.3.0 | MIT-CMU and bundled library notices | https://github.com/python-pillow/Pillow |
| cryptography | 50.0.2 | Apache-2.0 or BSD-3-Clause, plus bundled cryptographic-library notices | https://github.com/pyca/cryptography |
| cffi | 2.1.1 | MIT and bundled libffi notices | https://foss.heptapod.net/pypy/cffi |
| pycparser | 3.11 | BSD-3-Clause | https://github.com/eliben/pycparser |
| CPython | 3.12 runtime | PSF License and included third-party notices | https://www.python.org/ |

The `licenses/` directory contains license and notice files collected from the installed distributions. PDFium-specific third-party notices are copied there from its wheel. `dependency-versions.json` records installed versions. Source references are included for identifying matching upstream releases; they are not a promise that all dependencies use MIT.

Qt libraries are dynamically linked in the Windows distribution. Users may replace compatible Qt/PySide libraries and debug modifications as permitted by their licenses; this project imposes no additional restriction on doing so. Preserve the notices and comply with the applicable LGPL source-distribution obligations when redistributing Qt binaries. Matching unmodified Qt Base, Qt SVG, and PySide/Shiboken source archives are retained alongside the release in `release/dependency-sources/`; keep them accessible with redistributed binaries and the application source. The official URLs and hashes are recorded there. Qt source license texts and third-party attribution files are also copied into `licenses/Qt-source-notices/`.

PyInstaller is a build tool under GPL with its application-distribution exception. Its bootloader exception permits bundling non-GPL application code. See the copied PyInstaller license files for the exact terms.
