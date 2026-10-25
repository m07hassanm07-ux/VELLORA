"""Development entry point; packaged builds use the same application."""
from pathlib import Path
import sys

local_dependencies = Path(__file__).parent / ".deps"
if local_dependencies.exists():
    sys.path.insert(0, str(local_dependencies))
    import site
    site.addsitedir(str(local_dependencies))

if len(sys.argv) == 4 and sys.argv[1] == '--convert-office':
    from waraq.conversion import office_worker
    raise SystemExit(office_worker(sys.argv[2], sys.argv[3]))

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
