from pathlib import Path
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from BrewSupervisor.run_api import main

if __name__ == "__main__":
    main()