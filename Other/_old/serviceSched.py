from __future__ import annotations

from .schedule_service.discovery import MdnsAdvertiser
from .schedule_service.http_api import run_http_server
from .schedule_service.runtime import FcsRuntimeService
from .shared_service.backend import SignalStoreBackend
from .service_bases.core.cli import build_shared_parser


def main() -> None:
    parser = build_shared_parser('Schedule Service for ParameterDB')
    args = parser.parse_args()

    backend = SignalStoreBackend(host=args.backend_host, port=args.backend_port)
    runtime = FcsRuntimeService(backend)
    runtime.start_background()
    server = run_http_server(runtime, host=args.host, port=args.port)

    service_label = args.service_name or 'FCS Scheduler'
    advertiser = MdnsAdvertiser(service_label=service_label, port=args.port, path='/status')
    discovery_enabled = advertiser.start()
    print(f'{service_label} listening on http://{args.host}:{args.port}')
    if discovery_enabled:
        print('mDNS discovery enabled for _fcs._tcp.local.')
    else:
        print('mDNS discovery unavailable (install zeroconf to enable it).')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        advertiser.close()
        server.server_close()
        runtime.shutdown()


if __name__ == '__main__':
    main()
