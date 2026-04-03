
from __future__ import annotations

import argparse
from pathlib import Path

from .application.supervisor import TopologySupervisor
from .infrastructure.config_loader import YamlTopologyLoader


def main() -> None:
    parser = argparse.ArgumentParser(description='Topology-driven supervisor')
    parser.add_argument('--config', required=True, help='Path to topology YAML')
    parser.add_argument('--root-dir', default='.', help='Working directory for launched services')
    parser.add_argument('--log-dir', default='./logs', help='Directory for service logs')
    parser.add_argument('--advertise-host', default='0.0.0.0', help='Host/IP clients should use for managed service endpoints')
    parser.add_argument('--node-id', required=True, help='Stable fermenter node id for mDNS and UI')
    parser.add_argument('--node-name', required=True, help='Display name for this fermenter node')
    parser.add_argument('--agent-host', default='0.0.0.0', help='Host/IP for the local fermenter agent API')
    parser.add_argument('--agent-port', type=int, default=8780, help='Port for the local fermenter agent API')
    parser.add_argument('--check-interval', type=float, default=2.0)
    args = parser.parse_args()

    topology = YamlTopologyLoader().load(args.config, agent_port=args.agent_port)
    supervisor = TopologySupervisor(
        topology=topology,
        root_dir=Path(args.root_dir),
        log_dir=Path(args.log_dir),
        advertise_host=args.advertise_host,
        node_id=args.node_id,
        node_name=args.node_name,
        agent_host=args.agent_host,
        agent_port=args.agent_port,
        check_interval_s=args.check_interval,
    )
    supervisor.run()


if __name__ == '__main__':
    main()
