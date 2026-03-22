from Services.data_service.service import main
import sys

if __name__ == "__main__":
    sys.argv += ["--backend-host", "127.0.0.1"]
    sys.argv += ["--backend-port", "8765"]
    sys.argv += ["--host", "127.0.0.1"]
    sys.argv += ["--port", "8700"]
    main()
