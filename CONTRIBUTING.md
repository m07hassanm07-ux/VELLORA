# Contributing

Waraq PDF is an independent MIT-licensed project. Contributions must be original or compatible with the project's licenses; do not contribute proprietary Acrobat code or activation patches.

Use Python 3.11+, install `requirements.txt`, and run `python -m unittest discover -s tests -v`. Keep transformations in `waraq/core.py` independent of Qt. Keep Arabic UI strings readable and preserve right-to-left layout. Test output by reopening it with a separate reader and rendering it with PDFium.

Original input files must never be changed until the user explicitly chooses an output destination and confirms any overwrite. Avoid logging passwords or document content. Document any PDF features a transformation cannot preserve.

There is no hosted repository yet. When publishing your fork, keep LICENSE and third-party notices and choose a contact for issues and security reports.
