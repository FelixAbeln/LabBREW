from __future__ import annotations

from pathlib import Path

from ..._shared.storage_paths import (
    default_parameterdb_audit_path,
    default_parameterdb_snapshot_path,
    default_parameterdb_transducers_path,
)
from .engine import ScanEngine
from .event_broker import EventBroker
from .loader import PluginRegistry, autodiscover_plugins
from .persistence import (
    AuditLogger,
    SnapshotManager,
    resolve_snapshot_persistence_settings,
    restore_snapshot_into_store,
)
from .server import SignalTCPServer
from .store import ParameterStore
from .transducers import (
    DEFAULT_SHARED_TRANSDUCERS_TABLE,
    PostgresTransducerCatalog,
    TransducerCatalog,
)


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
    transducers_path: str | None = None,
    persistence_kind: str | None = None,
    postgres_host: str | None = None,
    postgres_port: int | None = None,
    postgres_database: str | None = None,
    postgres_username: str | None = None,
    postgres_password: str | None = None,
    postgres_table_prefix: str | None = None,
    postgres_sslmode: str | None = None,
):
    if snapshot_path is None:
        snapshot_path = default_parameterdb_snapshot_path()
    if audit_log_path is None:
        audit_log_path = default_parameterdb_audit_path()
    if transducers_path is None:
        transducers_path = default_parameterdb_transducers_path()

    resolved_persistence_kind, postgres_config = (
        resolve_snapshot_persistence_settings(
            kind=persistence_kind,
            postgres_host=postgres_host,
            postgres_port=postgres_port,
            postgres_database=postgres_database,
            postgres_username=postgres_username,
            postgres_password=postgres_password,
            postgres_table_prefix=postgres_table_prefix,
            postgres_sslmode=postgres_sslmode,
        )
    )

    registry = PluginRegistry()
    loaded = autodiscover_plugins(plugin_root, registry)
    broker = EventBroker()
    store = ParameterStore(event_broker=broker)
    if resolved_persistence_kind == "postgres" and postgres_config is not None:
        transducers = PostgresTransducerCatalog(
            postgres_config,
            table_name=DEFAULT_SHARED_TRANSDUCERS_TABLE,
        )
    else:
        transducers = TransducerCatalog(transducers_path)

    restored_count = 0
    if restore_snapshot and enable_snapshot_persistence:
        restored_count = restore_snapshot_into_store(
            store,
            registry,
            snapshot_path,
            persistence_kind=resolved_persistence_kind,
            postgres_config=postgres_config,
        )

    engine = ScanEngine(
        period_s=period_s,
        store=store,
        transducers=transducers,
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
        persistence_kind=resolved_persistence_kind,
        postgres_config=postgres_config,
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
    parser.add_argument("--plugin-root", default="./plugins")
    parser.add_argument("--snapshot-path", default=default_parameterdb_snapshot_path())
    parser.add_argument("--transducers-path", default=default_parameterdb_transducers_path())
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
    transducers_path = Path(args.transducers_path).resolve()
    transducers_path.parent.mkdir(parents=True, exist_ok=True)
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
            transducers_path=str(transducers_path),
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
        snapshot_stats = snapshots.stats()
        print(f"[INFO] Snapshot backend: {snapshot_stats['backend']}")
        if snapshot_stats["backend"] == "json":
            print(f"[INFO] Snapshot path: {snapshot_path}")
        else:
            postgres_stats = snapshot_stats.get("postgres") or {}
            print(
                "[INFO] Snapshot Postgres target: "
                f"{postgres_stats.get('host')}:{postgres_stats.get('port')} "
                f"db={postgres_stats.get('database')} "
                f"prefix={postgres_stats.get('table_prefix')}"
            )
        print(f"[INFO] Restored parameters from snapshot: {restored_count}")
    if not args.no_audit_log:
        print(f"[INFO] Audit log path: {audit_log_path}")
    if snapshots.persistence_kind == "postgres":
        print(f"[INFO] Transducer catalog backend: postgres")
        print(
            "[INFO] Transducer shared table: "
            f"{DEFAULT_SHARED_TRANSDUCERS_TABLE}"
        )
    else:
        print(f"[INFO] Transducer catalog backend: json")
        print(f"[INFO] Transducer catalog path: {transducers_path}")

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
