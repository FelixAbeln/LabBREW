from __future__ import annotations

import os

from .schedule_service.discovery import MdnsAdvertiser
from .schedule_service.http_api import run_http_server
from .schedule_service.runtime import FcsRuntimeService
from .schedule_service.signalstore_backend import SignalStoreBackend


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Schedule Service for ParameterDB')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--backend-host', default='127.0.0.1')
    parser.add_argument('--backend-port', type=int, default=8765)
    args = parser.parse_args()

    backend_host = args.backend_host
    backend_port = args.backend_port
    service_host = args.host
    service_port = args.port

    backend = SignalStoreBackend(host=backend_host, port=backend_port)
    runtime = FcsRuntimeService(backend)
    runtime.start_background()
    server = run_http_server(runtime, host=service_host, port=service_port)

    advertiser = MdnsAdvertiser(service_label="FCS Scheduler", port=service_port, path="/status")
    discovery_enabled = advertiser.start()
    print(f"FCS runtime service listening on http://{service_host}:{service_port}")
    if discovery_enabled:
        print("mDNS discovery enabled for _fcs._tcp.local.")
    else:
        print("mDNS discovery unavailable (install zeroconf to enable it).")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        advertiser.close()
        server.server_close()
        runtime.shutdown()


if __name__ == "__main__":
    main()
