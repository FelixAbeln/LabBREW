import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from Services._shared.storage_paths import topology_path
from Supervisor.supervisor import main

if __name__ == "__main__":
    sys.argv += ["--config", str(topology_path())]
    sys.argv += ["--node-id", "01"]
    sys.argv += ["--node-name", "Test"]
    main()
