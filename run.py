"""Development entry point; packaged builds use the same application."""
from pathlib import Path
import sys

local_dependencies = Path(__file__).parent / ".deps"
if local_dependencies.exists():
    sys.path.insert(0, str(local_dependencies))

from waraq.app import main

if __name__ == "__main__":
    main()
