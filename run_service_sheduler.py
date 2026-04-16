import sys

from Services.scenario_service.service import main

if __name__ == "__main__":
    # Legacy filename kept for compatibility; launches scenario_service.
    sys.argv += ["--backend-host", "127.0.0.1"]
    sys.argv += ["--backend-port", "8767"]
    sys.argv += ["--data-backend-host", "127.0.0.1"]
    sys.argv += ["--data-backend-port", "8764"]
    sys.argv += ["--host", "127.0.0.1"]
    sys.argv += ["--port", "8770"]
    main()
