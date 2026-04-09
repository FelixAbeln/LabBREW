import sys

from Services._shared.storage_paths import topology_path
from Supervisor.supervisor import main

if __name__ == "__main__":
    sys.argv += ["--config", str(topology_path())]
    sys.argv += ["--node-id", "01"]
    sys.argv += ["--node-name", "Test"]
    main()
