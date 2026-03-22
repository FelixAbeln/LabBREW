from __future__ import annotations

from .safety_service.http_api import run_http_server
from .safety_service.runtime import SafetyRuntimeService
from .safety_service.service import SafetyRuleEngine
from .service_bases.core.cli import build_shared_parser
from .shared_service.backend import SignalStoreBackend


def main() -> None:
    parser = build_shared_parser('Safety rules service for shared scheduler stack')
    parser.set_defaults(port=8770)
    parser.add_argument('--poll-interval', type=float, default=0.25)
    args = parser.parse_args()

    engine = SafetyRuleEngine.from_root_data(args.root_data)
    backend = SignalStoreBackend(host=args.backend_host, port=args.backend_port)
    runtime = SafetyRuntimeService(engine, backend, poll_interval_s=args.poll_interval)
    runtime.start_background()

    server = run_http_server(engine, host=args.host, port=args.port)
    service_name = getattr(args, 'service_name', None) or 'Safety rule service'
    print(f'{service_name} listening on http://{args.host}:{args.port}')
    print(f'Rules file: {args.root_data}/safety_rules.json')
    print(f'Backend: {args.backend_host}:{args.backend_port}')
    print('Publishing: safety.block, safety.message, safety.rule_id, safety.active_count')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
