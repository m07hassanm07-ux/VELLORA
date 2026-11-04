"""Development entry point; packaged builds use the same application."""
from pathlib import Path
import os, sys

local_dependencies = Path(__file__).parent / ".deps"
if local_dependencies.exists():
    sys.path.insert(0, str(local_dependencies))
    import site
    site.addsitedir(str(local_dependencies))

# Frozen builds ship their own CA bundle.  Point OpenSSL at it before importing
# pyHanko/aiohttp; otherwise their eager TLS setup can look for the developer
# Python installation's certificate file, which does not exist on another PC.
if getattr(sys, 'frozen', False):
    try:
        import certifi
        ca_bundle = certifi.where()
        if Path(ca_bundle).is_file():
            # PyInstaller/OpenSSL may inherit a stale SSL_CERT_FILE pointing at
            # the build-time Python runtime, so this must deliberately replace it.
            os.environ['SSL_CERT_FILE'] = ca_bundle
            os.environ.pop('SSL_CERT_DIR', None)
    except ImportError:
        pass

if len(sys.argv) == 4 and sys.argv[1] == '--convert-office':
    from waraq.conversion import office_worker
    raise SystemExit(office_worker(sys.argv[2], sys.argv[3]))

if len(sys.argv) == 6 and sys.argv[1] == '--export-office':
    from waraq.conversion import office_export_worker
    raise SystemExit(office_export_worker(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]))

if len(sys.argv) == 3 and sys.argv[1] == '--job':
    from waraq.worker import run_job
    raise SystemExit(run_job(sys.argv[2]))

if len(sys.argv) == 3 and sys.argv[1] == '--render-server':
    from waraq.render_service import render_server
    raise SystemExit(render_server(sys.argv[2]))

if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
    from waraq.diagnostics import self_test
    raise SystemExit(self_test(sys.argv[2]))

from waraq.app import main

if __name__ == "__main__":
    main()
