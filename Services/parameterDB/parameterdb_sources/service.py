from __future__ import annotations

import argparse
import signal
import threading
import time
from pathlib import Path
from typing import Any

from parameterdb_core.client import SignalClient

from .admin_server import SourceAdminTCPServer
from .loader import DataSourceRegistry, autodiscover_sources
from .runner import SourceRunner


def _builtin_source_root() -> str:
    return str(Path(__file__).resolve().parent)


def _default_config_dir() -> str:
    return "./sources"


def main() -> None:
    parser = argparse.ArgumentParser(description="ParameterDB Data-Source Service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--admin-host", default="127.0.0.1")
    parser.add_argument("--admin-port", type=int, default=8766)
    parser.add_argument(
        "--source-root",
        default=None,
        help="Optional extra folder containing custom source type folders.",
    )
    parser.add_argument(
        "--config-dir",
        default=_default_config_dir(),
        help="Load all *.json source configs from this folder.",
    )
    args = parser.parse_args()

    base_client = SignalClient(args.host, args.port, timeout=5.0)
    registry = DataSourceRegistry()

    builtin_root = _builtin_source_root()
    loaded_builtin = autodiscover_sources(builtin_root, registry)
    loaded_custom: list[str] = []
    if args.source_root:
        loaded_custom = autodiscover_sources(args.source_root, registry)

    runner = SourceRunner(base_client, registry, config_dir=args.config_dir)
    records = runner.load_config_dir()

    print(f"[INFO] Built-in source root: {builtin_root}")
    print(f"[INFO] Loaded built-in source types: {loaded_builtin}")
    if args.source_root:
        print(f"[INFO] Extra source root: {args.source_root}")
        print(f"[INFO] Loaded extra source types: {loaded_custom}")
    print(f"[INFO] Loaded source instances: {[r.name for r in records]}")

    runner.start_all()
    admin_server = SourceAdminTCPServer(args.admin_host, args.admin_port, runner)
    admin_thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
    admin_thread.start()
    print(f"[INFO] Source admin running on {args.admin_host}:{args.admin_port}")

    def shutdown(*_args: Any) -> None:
        print("[INFO] Stopping data sources...")
        admin_server.shutdown()
        admin_server.server_close()
        runner.stop_all()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()
