from __future__ import annotations

from pathlib import Path

from .._shared.storage_paths import (
    default_parameterdb_audit_path,
    default_parameterdb_snapshot_path,
)
from .parameterdb_service.engine import ScanEngine
from .parameterdb_service.event_broker import EventBroker
from .parameterdb_service.loader import PluginRegistry, autodiscover_plugins
from .parameterdb_service.persistence import (
    AuditLogger,
    SnapshotManager,
    load_snapshot_into_store,
)
from .parameterdb_service.server import SignalTCPServer
from .parameterdb_service.store import ParameterStore


def build_service(
    host: str = "127.0.0.1",
    port: int = 8765,
    period_s: float = 0.05,
    plugin_root: str = "./plugins",
    *,
    scan_mode: str = "fixed",
    target_utilization: float = 0.7,
    min_period_s: float = 0.002,
    max_period_s: float = 0.05,
    snapshot_path: str | None = None,
    snapshot_interval_s: float = 5.0,
    restore_snapshot: bool = True,
    enable_snapshot_persistence: bool = True,
    audit_log_path: str | None = None,
    enable_audit_log: bool = True,
    audit_external_writes: bool = False,
):
    if snapshot_path is None:
        snapshot_path = default_parameterdb_snapshot_path()
    if audit_log_path is None:
        audit_log_path = default_parameterdb_audit_path()

    registry = PluginRegistry()
    loaded = autodiscover_plugins(plugin_root, registry)
    broker = EventBroker()
    store = ParameterStore(event_broker=broker)

    restored_count = 0
    if restore_snapshot and enable_snapshot_persistence:
        restored_count = load_snapshot_into_store(store, registry, snapshot_path)

    engine = ScanEngine(
        period_s=period_s,
        store=store,
        mode=scan_mode,
        target_utilization=target_utilization,
        min_period_s=min_period_s,
        max_period_s=max_period_s,
    )
    audit_logger = AuditLogger(
        audit_log_path,
        enabled=enable_audit_log,
        audit_external_writes=audit_external_writes,
    )
    server = SignalTCPServer(
        host, port, engine, registry, broker, audit_logger=audit_logger
    )
    snapshots = SnapshotManager(
        store,
        snapshot_path,
        interval_s=snapshot_interval_s,
        enabled=enable_snapshot_persistence,
    )
    server.snapshot_manager = snapshots
    return engine, server, registry, loaded, snapshots, restored_count, audit_logger


def main() -> None:
    import argparse
    import signal
    import threading
    import time

    parser = argparse.ArgumentParser(description="ParameterDB Service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--period", type=float, default=0.05)
    parser.add_argument("--scan-mode", choices=["fixed", "adaptive"], default="fixed")
    parser.add_argument("--target-utilization", type=float, default=0.7)
    parser.add_argument("--min-period", type=float, default=0.002)
    parser.add_argument("--max-period", type=float, default=0.05)
    parser.add_argument(
        "--plugin-root", default=str(Path(__file__).resolve().parent / "plugins")
    )
    parser.add_argument("--snapshot-path", default=default_parameterdb_snapshot_path())
    parser.add_argument("--snapshot-interval", type=float, default=5.0)
    parser.add_argument("--no-restore-snapshot", action="store_true")
    parser.add_argument("--no-snapshot-persistence", action="store_true")
    parser.add_argument("--audit-log-path", default=default_parameterdb_audit_path())
    parser.add_argument("--no-audit-log", action="store_true")
    parser.add_argument("--audit-external-writes", action="store_true")
    args = parser.parse_args()

    plugin_root = Path(args.plugin_root).resolve()
    plugin_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = Path(args.snapshot_path).resolve()
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    audit_log_path = Path(args.audit_log_path).resolve()
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    engine, server, _registry, loaded, snapshots, restored_count, _audit_logger = (
        build_service(
            args.host,
            args.port,
            args.period,
            str(plugin_root),
            scan_mode=args.scan_mode,
            target_utilization=args.target_utilization,
            min_period_s=args.min_period,
            max_period_s=args.max_period,
            snapshot_path=str(snapshot_path),
            snapshot_interval_s=args.snapshot_interval,
            restore_snapshot=not args.no_restore_snapshot,
            enable_snapshot_persistence=not args.no_snapshot_persistence,
            audit_log_path=str(audit_log_path),
            enable_audit_log=not args.no_audit_log,
            audit_external_writes=args.audit_external_writes,
        )
    )
    print(f"[INFO] Plugin root: {plugin_root}")
    print(f"[INFO] Loaded parameter types: {loaded}")
    print(
        f"[INFO] Scan mode: {args.scan_mode} | "
        f"target_utilization={args.target_utilization:.2f} | "
        f"min_period={args.min_period:.4f}s | max_period={args.max_period:.4f}s"
    )
    if not args.no_snapshot_persistence:
        print(f"[INFO] Snapshot path: {snapshot_path}")
        print(f"[INFO] Restored parameters from snapshot: {restored_count}")
    if not args.no_audit_log:
        print(f"[INFO] Audit log path: {audit_log_path}")

    engine.start()
    snapshots.start()
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[INFO] Service running on {args.host}:{args.port}")

    def shutdown(*_):
        print("[INFO] Shutting down...")
        server.shutdown()
        server.server_close()
        snapshots.stop(save_final=True)
        engine.stop()
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
