import sys
from Supervisor.supervisor import main

if __name__ == "__main__":
    sys.argv += ["--config", "./data/system_topology.yaml"]
    sys.argv += ["--node-id", "01"]
    sys.argv += ["--node-name", "Test"]
    main()