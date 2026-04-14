from __future__ import annotations

import json
import runpy
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from Services.parameterDB import serviceDS
from Services.parameterDB.parameterdb_sources import loader
from Services.parameterDB.parameterdb_sources import repository as repository_module


class FakeSession:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True

    def describe(self):
        return self.owner.describe_payload

    def delete_parameter(self, name: str):
        self.owner.deleted_parameters.append(name)
        return True


class FakeClient:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []
        self.describe_payload: dict[str, Any] = {}
        self.deleted_parameters: list[str] = []

    def session(self) -> FakeSession:
        session = FakeSession(self)
        self.sessions.append(session)
        return session


class FakeThread:
    def __init__(self, target=None, name: str = "", daemon: bool = False) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self._alive = False

    def start(self) -> None:
        self._alive = True

    def join(self, timeout: float | None = None) -> None:
        _ = timeout
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive


class FakeSource:
    def __init__(self, name: str, client: FakeSession, *, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.client = client
        self.config = dict(config or {})
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def run(self) -> None:
        return


class FakeSpec:
    source_type = "fake"
    display_name = "Fake"
    description = "Fake Source"

    def __init__(self) -> None:
        self.created: list[FakeSource] = []

    def create(self, name: str, client: FakeSession, *, config: dict[str, Any] | None = None) -> FakeSource:
        source = FakeSource(name, client, config=config)
        self.created.append(source)
        return source


def _build_runner(tmp_path: Path, monkeypatch) -> tuple[serviceDS.SourceRunner, loader.DataSourceRegistry, FakeSpec]:
    monkeypatch.setattr(serviceDS.threading, "Thread", FakeThread)
    registry = loader.DataSourceRegistry()
    spec = FakeSpec()
    registry.register(spec)
    runner = serviceDS.SourceRunner(FakeClient(), registry, config_dir=str(tmp_path / "sources"))
    return runner, registry, spec


def test_source_runner_rejects_invalid_payload_and_unknown_type(tmp_path: Path, monkeypatch) -> None:
    runner, registry, _ = _build_runner(tmp_path, monkeypatch)

    with pytest.raises(ValueError):
        runner._record_from_payload({"name": "", "source_type": "fake"}, storage_ref=str(runner._config_path_for_name("x")))

    with pytest.raises(KeyError):
        runner._record_from_payload({"name": "alpha", "source_type": "missing"}, storage_ref=str(runner._config_path_for_name("x")))

    registry.get("fake")


def test_source_runner_load_start_update_delete_lifecycle(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    cfg_path = runner._config_path_for_name("alpha")
    cfg_path.write_text(
        json.dumps({"name": "alpha", "source_type": "fake", "config": {"interval": 1}}),
        encoding="utf-8",
    )

    loaded = runner.load_config_dir()
    assert [item.name for item in loaded] == ["alpha"]

    runner.start_all()
    listed = runner.list_sources()
    assert listed["alpha"]["running"] is True

    runner.update_source("alpha", config={"interval": 2})
    info = runner.get_source_record("alpha")
    assert info["config"] == {"interval": 2}

    on_disk = json.loads(Path(info["config_path"]).read_text(encoding="utf-8"))
    assert on_disk["config"] == {"interval": 2}

    runner.create_source("beta", "fake", config={"mode": "fast"})
    assert set(runner.list_sources()) == {"alpha", "beta"}

    with pytest.raises(ValueError):
        runner.create_source("beta", "fake", config={})

    runner.delete_source("beta")
    with pytest.raises(KeyError):
        runner.get_source_record("beta")

    with pytest.raises(KeyError):
        runner.delete_source("missing")

    runner.stop_all()
    assert runner.instances == {}


def test_source_runner_write_record_cleans_tmp_on_failure(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    record = serviceDS.SourceRecord(
        name="alpha",
        source_type="fake",
        config={"k": 1},
        storage_ref="",
    )

    original_replace = repository_module.Path.replace

    def boom_replace(self: Path, target: Path) -> None:
        _ = self, target
        raise RuntimeError("replace failed")

    monkeypatch.setattr(repository_module.Path, "replace", boom_replace)

    with pytest.raises(RuntimeError):
        runner._write_record(record)

    assert list(runner.config_dir.glob("*.tmp")) == []


def test_source_runner_cleans_stale_tmp_files(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    stale = runner.config_dir / "alpha.json.123.tmp"
    keep = runner.config_dir / "alpha.json"
    stale.write_text("tmp", encoding="utf-8")
    keep.write_text("{}", encoding="utf-8")

    runner._cleanup_stale_config_tmp_files()

    assert stale.exists() is False
    assert keep.exists() is True


def test_registry_ui_resolution_and_type_errors() -> None:
    registry = loader.DataSourceRegistry()
    spec = FakeSpec()

    def ui_with_kwargs(*, record=None, mode=None):
        return {
            "display_name": f"{record['name']}:{mode}" if record else "none",
            "description": "ok",
        }

    registry.register(spec, ui_with_kwargs)

    ui = registry.list_ui()
    assert ui["fake"]["display_name"] == "none"

    detail = registry.get_ui_spec("fake", record={"name": "alpha"}, mode="edit")
    assert detail["display_name"] == "alpha:edit"

    bad_registry = loader.DataSourceRegistry()
    bad_registry.register(spec, lambda: "not-a-dict")
    with pytest.raises(TypeError):
        bad_registry.get_ui_spec("fake")


def test_registry_ui_provider_typeerror_fallback() -> None:
    registry = loader.DataSourceRegistry()
    spec = FakeSpec()

    def ui_without_kwargs():
        return {"display_name": "fallback", "description": "ok"}

    registry.register(spec, ui_without_kwargs)
    assert registry.get_ui_spec("fake")["display_name"] == "fallback"


def test_extract_ui_spec_and_autodiscover(monkeypatch, tmp_path: Path) -> None:
    class UiWithFunction:
        @staticmethod
        def get_ui_spec(*, _record=None, _mode=None):
            return {"display_name": "fn", "description": "x"}

    class UiWithConst:
        UI_SPEC: ClassVar[dict[str, str]] = {"display_name": "const", "description": "y"}

    assert callable(loader._extract_ui_spec(UiWithFunction))
    assert loader._extract_ui_spec(UiWithConst) == {"display_name": "const", "description": "y"}
    assert loader._extract_ui_spec(object()) is None

    root = tmp_path / "defs"
    (root / "good").mkdir(parents=True)
    (root / "bad").mkdir(parents=True)
    (root / "_hidden").mkdir(parents=True)

    def fake_load_source_folder(folder: str | Path, _registry: loader.DataSourceRegistry):
        folder_name = Path(folder).name
        if folder_name == "bad":
            raise RuntimeError("bad source")
        return loader.LoadedSourceType(source_type=f"{folder_name}_type", folder=str(folder))

    monkeypatch.setattr(loader, "load_source_folder", fake_load_source_folder)

    registry = loader.DataSourceRegistry()
    loaded = loader.autodiscover_sources(root, registry)
    assert loaded == ["good_type"]
    assert loader.autodiscover_sources(root / "missing", registry) == []


def test_load_source_folder_imports_service_and_ui(monkeypatch, tmp_path: Path) -> None:
    folder = tmp_path / "Services" / "parameterDB" / "sourceDefs" / "demo"
    folder.mkdir(parents=True)
    (folder / "service.py").write_text("# marker", encoding="utf-8")
    (folder / "ui.py").write_text("# marker", encoding="utf-8")

    class ServiceModule:
        SOURCE = FakeSpec()

    class UiModule:
        @staticmethod
        def get_ui_spec(*, _record=None, _mode=None):
            return {"display_name": "Demo", "description": "Demo source"}

    def fake_import(name: str):
        if name.endswith(".service"):
            return ServiceModule
        if name.endswith(".ui"):
            return UiModule
        raise AssertionError(name)

    monkeypatch.setattr(loader.importlib, "import_module", fake_import)

    registry = loader.DataSourceRegistry()
    info = loader.load_source_folder(folder, registry)
    assert info.source_type == "fake"
    assert "fake" in registry.list_types()
    assert registry.list_ui()["fake"]["display_name"] == "Demo"


def test_load_source_folder_requires_service_file(tmp_path: Path) -> None:
    folder = tmp_path / "missing_service"
    folder.mkdir(parents=True)
    registry = loader.DataSourceRegistry()

    with pytest.raises(FileNotFoundError):
        loader.load_source_folder(folder, registry)


def test_source_runner_write_record_tolerates_dir_fsync_open_error(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    record = serviceDS.SourceRecord(
        name="alpha",
        source_type="fake",
        config={"k": 1},
        storage_ref="",
    )

    config_path = runner._config_path_for_name("alpha")

    original_open = repository_module.os.open

    def selective_open(path, flags, *args, **kwargs):
        if str(path) == str(config_path.parent) and flags == repository_module.os.O_RDONLY:
            raise OSError("no dir fd")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(repository_module.os, "open", selective_open)

    runner._write_record(record)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["name"] == "alpha"


def test_source_runner_delete_source_unlink_typeerror_fallback(tmp_path: Path, monkeypatch) -> None:
    repo = repository_module.FileSourceConfigRepository(tmp_path / "sources")

    class FakePath:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def unlink(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            if kwargs:
                raise TypeError("missing_ok unsupported")

        def exists(self):
            return True

    fake_path = FakePath()
    monkeypatch.setattr(repo, "_config_path_for_name", lambda _name: fake_path)

    repo.delete_record("alpha")

    assert fake_path.calls[0][1] == {"missing_ok": True}
    assert fake_path.calls[1] == ((), {})


def test_source_runner_delete_source_can_remove_owned_parameters(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    runner.create_source("alpha", "fake", config={"interval": 1})

    fake_client = runner.base_client
    fake_client.describe_payload = {
        "alpha.keep": {
            "metadata": {
                "created_by": "data_source",
                "owner": "alpha",
                "source_type": "fake",
            }
        },
        "alpha.no_source_type": {
            "metadata": {
                "created_by": "data_source",
                "owner": "alpha",
            }
        },
        "alpha.other_type": {
            "metadata": {
                "created_by": "data_source",
                "owner": "alpha",
                "source_type": "other",
            }
        },
        "beta.keep": {
            "metadata": {
                "created_by": "data_source",
                "owner": "beta",
                "source_type": "fake",
            }
        },
        "operator.manual": {
            "metadata": {
                "created_by": "manual",
                "owner": "alpha",
                "source_type": "fake",
            }
        },
    }

    runner.delete_source("alpha", delete_owned_parameters=True)

    assert sorted(fake_client.deleted_parameters) == ["alpha.keep", "alpha.no_source_type"]
    with pytest.raises(KeyError):
        runner.get_source_record("alpha")


def test_service_ds_main_wires_runner_admin_and_shutdown(monkeypatch, tmp_path: Path) -> None:
    args = SimpleNamespace(
        backend_host="127.0.0.1",
        backend_port=8765,
        host="127.0.0.1",
        port=8766,
    )

    captured: dict[str, Any] = {
        "signal_calls": [],
    }

    class FakeRunner:
        def __init__(self, base_client, registry, *, repository=None, config_dir=None) -> None:
            captured["runner_repository"] = repository
            captured["runner_config_dir"] = config_dir
            self.base_client = base_client
            self.registry = registry
            self.stop_all_calls = 0

        def load_config_dir(self):
            return [SimpleNamespace(name="alpha")]

        def start_all(self):
            captured["runner_started"] = True

        def stop_all(self):
            self.stop_all_calls += 1
            captured["runner_stopped"] = self.stop_all_calls

    class FakeAdminServer:
        def __init__(self, host: str, port: int, runner: FakeRunner) -> None:
            captured["admin_host"] = host
            captured["admin_port"] = port
            self.runner = runner
            self.shutdown_calls = 0
            self.close_calls = 0

        def serve_forever(self):
            captured["served"] = True

        def shutdown(self):
            self.shutdown_calls += 1
            captured["admin_shutdown"] = self.shutdown_calls

        def server_close(self):
            self.close_calls += 1
            captured["admin_closed"] = self.close_calls

    class MainThread:
        def __init__(self, target=None, daemon: bool = False, name: str = "") -> None:
            self.target = target
            self.daemon = daemon
            self.name = name
            self.started = False

        def start(self):
            self.started = True
            captured["thread_started"] = True

    monkeypatch.setattr(serviceDS, "parse_args", lambda _desc: args)
    monkeypatch.setattr(serviceDS, "SignalClient", lambda host, port, timeout: (host, port, timeout))
    monkeypatch.setattr(serviceDS, "DataSourceRegistry", lambda: "registry")
    monkeypatch.setattr(serviceDS, "autodiscover_sources", lambda _root, _registry: ["system_time"])
    monkeypatch.setattr(serviceDS, "SourceRunner", FakeRunner)
    monkeypatch.setattr(serviceDS, "SourceAdminTCPServer", FakeAdminServer)
    monkeypatch.setattr(serviceDS.threading, "Thread", MainThread)
    monkeypatch.setattr(serviceDS, "_default_config_dir", lambda: str(tmp_path / "sources"))
    monkeypatch.setattr(serviceDS, "_build_source_repository", lambda *, config_dir: SimpleNamespace(stats=lambda: {"backend": "json"}))

    def fake_signal(sig, handler):
        captured["signal_calls"].append(sig)
        captured["shutdown_handler"] = handler

    monkeypatch.setattr(serviceDS.signal, "signal", fake_signal)
    monkeypatch.setattr(serviceDS.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(SystemExit) as exc:
        serviceDS.main()

    assert exc.value.code == 0
    assert captured["runner_started"] is True
    assert captured["thread_started"] is True
    assert captured["admin_host"] == "127.0.0.1"
    assert captured["admin_port"] == 8766
    assert captured["admin_shutdown"] == 1
    assert captured["admin_closed"] == 1
    assert captured["runner_stopped"] == 1
    assert captured["signal_calls"]


def test_service_ds_paths_helpers() -> None:
    assert serviceDS._default_config_dir() == "./data/sources"
    assert serviceDS._builtin_source_root().replace("\\", "/").endswith("Services/parameterDB/sourceDefs")


def test_source_runner_write_record_dir_fsync_inner_error_path(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    record = serviceDS.SourceRecord(
        name="alpha-dirfsync",
        source_type="fake",
        config={"k": 1},
        storage_ref="",
    )

    config_path = runner._config_path_for_name("alpha-dirfsync")

    fake_dir_fd = 4242
    closed_fds: list[int] = []
    original_open = repository_module.os.open
    original_fsync = repository_module.os.fsync

    def selective_open(path, flags, *args, **kwargs):
        if str(path) == str(config_path.parent) and flags == repository_module.os.O_RDONLY:
            return fake_dir_fd
        return original_open(path, flags, *args, **kwargs)

    def selective_fsync(fd):
        if fd == fake_dir_fd:
            raise OSError("dir fsync unsupported")
        return original_fsync(fd)

    monkeypatch.setattr(repository_module.os, "open", selective_open)
    monkeypatch.setattr(repository_module.os, "fsync", selective_fsync)
    monkeypatch.setattr(repository_module.os, "close", lambda fd: closed_fds.append(fd))

    runner._write_record(record)

    assert fake_dir_fd in closed_fds
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["name"] == "alpha-dirfsync"


def test_source_runner_write_record_cleanup_ignores_unlink_oserror(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    record = serviceDS.SourceRecord(
        name="alpha-cleanup",
        source_type="fake",
        config={"k": 1},
        storage_ref="",
    )

    monkeypatch.setattr(repository_module.Path, "replace", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("replace failed")))
    monkeypatch.setattr(repository_module.Path, "exists", lambda _self: True)
    monkeypatch.setattr(repository_module.Path, "unlink", lambda _self: (_ for _ in ()).throw(OSError("busy")))

    with pytest.raises(RuntimeError, match="replace failed"):
        runner._write_record(record)


def test_source_runner_cleanup_stale_tmp_ignores_unlink_oserror(tmp_path: Path, monkeypatch) -> None:
    import pathlib

    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    stale = runner.config_dir / "alpha.json.111.tmp"
    stale.write_text("tmp", encoding="utf-8")

    original_unlink = pathlib.Path.unlink

    def selective_unlink(self, *args, **kwargs):
        if self.name.endswith(".tmp"):
            raise OSError("cannot unlink")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", selective_unlink)

    runner._cleanup_stale_config_tmp_files()
    assert stale.exists() is True


def test_source_runner_start_instance_locked_rejects_duplicate(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)
    runner.instances["alpha"] = SimpleNamespace(record=None, source=None, session=None, thread=None)
    record = serviceDS.SourceRecord(
        name="alpha",
        source_type="fake",
        config={},
        storage_ref=str(runner._config_path_for_name("alpha")),
    )

    with pytest.raises(ValueError, match="already running"):
        runner._start_instance_locked(record)


def test_source_runner_update_source_unknown_name_raises(tmp_path: Path, monkeypatch) -> None:
    runner, _, _ = _build_runner(tmp_path, monkeypatch)

    with pytest.raises(KeyError):
        runner.update_source("missing-source", config={"x": 1})


def test_service_ds_module_main_guard_executes_main(monkeypatch, tmp_path: Path) -> None:
    from Services._shared import cli as cli_module
    from Services.parameterDB.parameterdb_core import client as client_module
    from Services.parameterDB.parameterdb_sources import (
        admin_server as admin_server_module,
    )
    from Services.parameterDB.parameterdb_sources import loader as loader_module

    args = SimpleNamespace(
        backend_host="127.0.0.1",
        backend_port=8765,
        host="127.0.0.1",
        port=8766,
    )
    captured: dict[str, Any] = {"signals": []}

    class FakeRunner:
        def __init__(self, _base_client, _registry, *, config_dir: str) -> None:
            captured["config_dir"] = config_dir

        def load_config_dir(self):
            return []

        def start_all(self):
            captured["started"] = True

        def stop_all(self):
            captured["stopped"] = True

    class FakeAdminServer:
        def __init__(self, host: str, port: int, _runner) -> None:
            captured["admin"] = (host, port)

        def serve_forever(self):
            return None

        def shutdown(self):
            captured["shutdown"] = True

        def server_close(self):
            captured["closed"] = True

    class FakeThread:
        def __init__(self, target=None, daemon: bool = False, name: str = "") -> None:
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            captured["thread_started"] = True

    monkeypatch.setattr(cli_module, "parse_args", lambda _desc: args)
    monkeypatch.setattr(client_module, "SignalClient", lambda host, port, timeout: (host, port, timeout))
    monkeypatch.setattr(loader_module, "DataSourceRegistry", loader.DataSourceRegistry)
    monkeypatch.setattr(loader_module, "autodiscover_sources", lambda _root, _registry: ["demo"])
    monkeypatch.setattr(admin_server_module, "SourceAdminTCPServer", FakeAdminServer)
    monkeypatch.setattr(serviceDS.threading, "Thread", FakeThread)
    monkeypatch.setattr(serviceDS.signal, "signal", lambda sig, _handler: captured["signals"].append(sig))
    monkeypatch.setattr(serviceDS.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.chdir(tmp_path)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"'Services\.parameterDB\.serviceDS' found in sys\.modules",
            category=RuntimeWarning,
        )
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("Services.parameterDB.serviceDS", run_name="__main__")

    assert exc.value.code == 0
    assert captured["thread_started"] is True
    assert captured["admin"] == ("127.0.0.1", 8766)
    assert captured["shutdown"] is True
    assert captured["closed"] is True
