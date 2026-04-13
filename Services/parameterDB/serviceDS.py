from __future__ import annotations

import signal
import threading
import time
from pathlib import Path
from typing import Any

from .._shared.cli import parse_args
from .._shared.storage_paths import default_sources_dir
from .parameterdb_core.client import SignalClient
from .parameterdb_sources.admin_server import SourceAdminTCPServer
from .parameterdb_sources.loader import DataSourceRegistry, autodiscover_sources
from .parameterdb_sources.runner import SourceRunner


def _builtin_source_root() -> str:
    return str(Path(__file__).resolve().parent / "sourceDefs")


def _default_config_dir() -> str:
    return default_sources_dir()


def main() -> None:
    args = parse_args("Datasource Service")

    base_client = SignalClient(args.backend_host, args.backend_port, timeout=5.0)
    registry = DataSourceRegistry()

    builtin_root = _builtin_source_root()
    loaded_builtin = autodiscover_sources(builtin_root, registry)

    print(f"[INFO] Built-in source root: {builtin_root}")
    print(f"[INFO] Loaded built-in source types: {loaded_builtin}")

    runner = SourceRunner(base_client, registry, config_dir=_default_config_dir())
    records = runner.load_config_dir()

    print(f"[INFO] Loaded source instances: {[r.name for r in records]}")

    runner.start_all()
    admin_server = SourceAdminTCPServer("127.0.0.1", 8766, runner)
    admin_thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
    admin_thread.start()
    print("[INFO] Source admin running on 127.0.0.1:8766")

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


if __name__ == "__main__":
    main()
