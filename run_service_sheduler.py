import sys
from Services.schedule_service.service import main

if __name__ == "__main__":

    sys.argv += ["--backend-host", "127.0.0.1"]
    sys.argv += ["--backend-port", "8767"]
    sys.argv += ["--data-backend-host", "127.0.0.1"]
    sys.argv += ["--data-backend-port", "8769"]
    sys.argv += ["--host", "127.0.0.1"]
    sys.argv += ["--port", "8768"]
    main()