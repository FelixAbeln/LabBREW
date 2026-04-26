from __future__ import annotations

from types import SimpleNamespace

import pytest

import Services.parameterDB.parameterdb_service.service as service_module


class FakeEngine:
    def __init__(self, period_s, store, transducers, mode, target_utilization, min_period_s, max_period_s):
        self.period_s = period_s
        self.store = store
        self.transducers = transducers
        self.mode = mode
        self.target_utilization = target_utilization
        self.min_period_s = min_period_s
        self.max_period_s = max_period_s
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeServer:
    def __init__(self, host, port, engine, registry, broker, *, audit_logger=None):
        self.host = host
        self.port = port
        self.engine = engine
        self.registry = registry
        self.broker = broker
        self.audit_logger = audit_logger
        self.shutdown_called = False
        self.closed = False

    def serve_forever(self):
        return None

    def shutdown(self):
        self.shutdown_called = True

    def server_close(self):
        self.closed = True


class FakeSnapshotManager:
    def __init__(self, store, path, *, persistence_kind="json", postgres_config=None, interval_s=5.0, enabled=True):
        self.store = store
        self.path = path
        self.persistence_kind = persistence_kind
        self.postgres_config = postgres_config
        self.interval_s = interval_s
        self.enabled = enabled
        self.started = False
        self.stopped = False
        self.last_save_final = None

    def start(self):
        self.started = True

    def stop(self, *, save_final=True):
        self.stopped = True
        self.last_save_final = save_final

    def stats(self):
        return {
            "enabled": self.enabled,
            "backend": self.persistence_kind,
            "path": self.path,
            "postgres": None
            if self.postgres_config is None
            else {
                "host": self.postgres_config.host,
                "port": self.postgres_config.port,
                "database": self.postgres_config.database,
                "table_prefix": self.postgres_config.table_prefix,
            },
            "last_save_ok": True,
            "last_success_at": 123.0,
            "last_error": None,
            "last_error_at": None,
        }


class FakeAuditLogger:
    def __init__(self, path, *, enabled=True, audit_external_writes=False):
        self.path = path
        self.enabled = enabled
        self.audit_external_writes = audit_external_writes


class FakeThread:
    def __init__(self, *, target, daemon=False):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True



def test_build_service_wires_components_and_restores_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(service_module, "ScanEngine", FakeEngine)
    monkeypatch.setattr(service_module, "SignalTCPServer", FakeServer)
    monkeypatch.setattr(service_module, "SnapshotManager", FakeSnapshotManager)
    monkeypatch.setattr(service_module, "AuditLogger", FakeAuditLogger)

    seen = {"autodiscover": None, "restore": None}

    def _fake_autodiscover(root, _registry):
        seen["autodiscover"] = root
        return ["fake_type"]

    def _fake_restore(_store, _registry, path, *, persistence_kind="json", postgres_config=None):
        seen["restore"] = (path, persistence_kind, postgres_config)
        return 4

    monkeypatch.setattr(service_module, "autodiscover_plugins", _fake_autodiscover)
    monkeypatch.setattr(service_module, "restore_snapshot_into_store", _fake_restore)

    engine, server, _registry, loaded, snapshots, restored_count, audit_logger = service_module.build_service(
        host="0.0.0.0",
        port=9876,
        period_s=0.2,
        plugin_root="./Services/parameterDB/plugins",
        scan_mode="adaptive",
        target_utilization=0.8,
        min_period_s=0.01,
        max_period_s=0.3,
        snapshot_path="./data/test_snapshot.json",
        snapshot_interval_s=2.5,
        restore_snapshot=True,
        enable_snapshot_persistence=True,
        audit_log_path="./data/test_audit.jsonl",
        enable_audit_log=True,
        audit_external_writes=True,
        persistence_kind="postgres",
        postgres_host="db.internal",
        postgres_port=5432,
        postgres_database="labbrew",
        postgres_username="brew",
        postgres_password="secret",
        postgres_table_prefix="parameterdb",
        postgres_sslmode="require",
    )

    assert isinstance(engine, FakeEngine)
    assert isinstance(server, FakeServer)
    assert isinstance(snapshots, FakeSnapshotManager)
    assert isinstance(audit_logger, FakeAuditLogger)
    assert loaded == ["fake_type"]
    assert restored_count == 4
    assert seen["autodiscover"] == "./Services/parameterDB/plugins"
    restore_path, restore_kind, restore_config = seen["restore"]
    assert restore_path == "./data/test_snapshot.json"
    assert restore_kind == "postgres"
    assert restore_config.host == "db.internal"
    assert restore_config.database == "labbrew"
    assert restore_config.table_prefix == "parameterdb"
    assert type(engine.transducers).__name__ == "PostgresTransducerCatalog"
    assert server.host == "0.0.0.0"
    assert server.port == 9876
    assert engine.mode == "adaptive"
    assert snapshots.enabled is True
    assert snapshots.persistence_kind == "postgres"
    assert snapshots.postgres_config.host == "db.internal"
    assert server.snapshot_manager is snapshots
    assert audit_logger.audit_external_writes is True



def test_build_service_skips_restore_when_snapshot_persistence_disabled(monkeypatch) -> None:
    monkeypatch.setattr(service_module, "ScanEngine", FakeEngine)
    monkeypatch.setattr(service_module, "SignalTCPServer", FakeServer)
    monkeypatch.setattr(service_module, "SnapshotManager", FakeSnapshotManager)
    monkeypatch.setattr(service_module, "AuditLogger", FakeAuditLogger)
    monkeypatch.setattr(service_module, "autodiscover_plugins", lambda *_: [])

    called = {"restore": 0}

    def _fake_restore(*_args, **_kwargs):
        called["restore"] += 1
        return 99

    monkeypatch.setattr(service_module, "restore_snapshot_into_store", _fake_restore)

    _engine, _server, _registry, loaded, snapshots, restored_count, audit_logger = service_module.build_service(
        restore_snapshot=True,
        enable_snapshot_persistence=False,
        enable_audit_log=False,
    )

    assert loaded == []
    assert restored_count == 0
    assert snapshots.enabled is False
    assert audit_logger.enabled is False
    assert called["restore"] == 0


def test_build_service_defaults_transducer_path_to_storage_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_module, "ScanEngine", FakeEngine)
    monkeypatch.setattr(service_module, "SignalTCPServer", FakeServer)
    monkeypatch.setattr(service_module, "SnapshotManager", FakeSnapshotManager)
    monkeypatch.setattr(service_module, "AuditLogger", FakeAuditLogger)
    monkeypatch.setattr(service_module, "autodiscover_plugins", lambda *_: [])
    monkeypatch.setattr(service_module, "restore_snapshot_into_store", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(service_module, "storage_root", lambda: tmp_path)

    engine, _server, _registry, _loaded, _snapshots, _restored_count, _audit_logger = service_module.build_service(
        restore_snapshot=False,
        enable_snapshot_persistence=False,
    )

    expected_path = (tmp_path / "parameterdb_transducers.json").resolve()
    assert type(engine.transducers).__name__ == "TransducerCatalog"
    assert engine.transducers.path == expected_path



def test_main_boots_then_shutdowns_on_keyboard_interrupt(monkeypatch) -> None:
    fake_engine = FakeEngine(0.05, store=None, transducers=None, mode="fixed", target_utilization=0.7, min_period_s=0.002, max_period_s=0.05)
    fake_server = FakeServer("127.0.0.1", 8765, fake_engine, registry=None, broker=None)
    fake_snapshots = FakeSnapshotManager(store=None, path="x.json")
    fake_audit = FakeAuditLogger("audit.jsonl")

    monkeypatch.setattr(
        service_module,
        "build_service",
        lambda *_args, **_kwargs: (fake_engine, fake_server, object(), ["pid", "static"], fake_snapshots, 3, fake_audit),
    )

    def _fake_parse_args(_self):
        return SimpleNamespace(
            host="127.0.0.1",
            port=8765,
            period=0.05,
            scan_mode="fixed",
            target_utilization=0.7,
            min_period=0.002,
            max_period=0.05,
            plugin_root="./plugins",
            snapshot_path="./data/snapshot.json",
            transducers_path="./data/transducers.json",
            snapshot_interval=5.0,
            no_restore_snapshot=False,
            no_snapshot_persistence=False,
            audit_log_path="./data/audit.jsonl",
            no_audit_log=False,
            audit_external_writes=False,
        )

    import argparse
    import signal
    import threading
    import time

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", _fake_parse_args)
    monkeypatch.setattr(threading, "Thread", lambda *_args, **kwargs: FakeThread(target=kwargs["target"], daemon=kwargs.get("daemon", False)))
    monkeypatch.setattr(signal, "signal", lambda *_args, **_kwargs: None)

    sleep_calls = {"count": 0}

    def _fake_sleep(_seconds):
        sleep_calls["count"] += 1
        raise KeyboardInterrupt()

    monkeypatch.setattr(time, "sleep", _fake_sleep)

    with pytest.raises(SystemExit):
        service_module.main()

    assert fake_engine.started is True
    assert fake_engine.stopped is True
    assert fake_snapshots.started is True
    assert fake_snapshots.stopped is True
    assert fake_snapshots.last_save_final is True
    assert fake_server.shutdown_called is True
    assert fake_server.closed is True
    assert sleep_calls["count"] == 1
