import argparse
import os
import sys

from Services.scenario_service.service import main


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-host", default="127.0.0.1")
    parser.add_argument("--backend-port", type=int, default=8767)
    parser.add_argument("--data-backend-host", default="127.0.0.1")
    parser.add_argument("--data-backend-port", type=int, default=8764)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args, unknown = parser.parse_known_args()

    sys.argv = [sys.argv[0]]
    sys.argv += ["--backend-host", args.backend_host, "--backend-port", str(args.backend_port)]
    sys.argv += ["--data-backend-host", args.data_backend_host, "--data-backend-port", str(args.data_backend_port)]
    sys.argv += ["--host", args.host, "--port", str(args.port)]
    sys.argv += unknown

    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
