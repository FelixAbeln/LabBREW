from __future__ import annotations

import runpy
import warnings
from types import SimpleNamespace

from Services.data_service import service


class _DummyRuntime:
    def __init__(self, *, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.run_calls = 0

    def run(self) -> None:
        self.run_calls += 1


class _FakeThread:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


def test_data_service_main_wires_runtime_router_and_uvicorn(monkeypatch) -> None:
    args = SimpleNamespace(host="127.0.0.1", port=9001, backend_host="127.0.0.1", backend_port=9100)

    thread_holder = {}
    runtime_holder = {}
    uvicorn_holder = {}
    set_runtime_holder = {}

    def _fake_parse_args(_name):
        return args

    def _fake_runtime_ctor(*, host, port):
        runtime = _DummyRuntime(host=host, port=port)
        runtime_holder["runtime"] = runtime
        return runtime

    def _fake_thread_ctor(*, target, daemon):
        thread = _FakeThread(target=target, daemon=daemon)
        thread_holder["thread"] = thread
        return thread

    def _fake_set_runtime(runtime):
        set_runtime_holder["runtime"] = runtime

    def _fake_uvicorn_run(app, host, port):
        uvicorn_holder["app"] = app
        uvicorn_holder["host"] = host
        uvicorn_holder["port"] = port

    monkeypatch.setattr(service, "parse_args", _fake_parse_args)
    monkeypatch.setattr(service, "DataRecordingRuntime", _fake_runtime_ctor)
    monkeypatch.setattr(service.threading, "Thread", _fake_thread_ctor)
    monkeypatch.setattr(service, "set_runtime", _fake_set_runtime)
    monkeypatch.setattr(service.uvicorn, "run", _fake_uvicorn_run)

    service.main()

    runtime = runtime_holder["runtime"]
    thread = thread_holder["thread"]

    assert runtime.host == "127.0.0.1"
    assert runtime.port == 9100
    assert thread.target == runtime.run
    assert thread.daemon is True
    assert thread.started is True
    assert set_runtime_holder["runtime"] is runtime
    assert uvicorn_holder["host"] == "127.0.0.1"
    assert uvicorn_holder["port"] == 9001


def test_data_service_main_module_entrypoint(monkeypatch) -> None:
    args = SimpleNamespace(host="127.0.0.1", port=9002, backend_host="127.0.0.1", backend_port=9101)

    thread_holder = {}
    runtime_holder = {}
    uvicorn_holder = {}

    def _fake_parse_args(_name):
        return args

    def _fake_runtime_ctor(*, host, port):
        runtime = _DummyRuntime(host=host, port=port)
        runtime_holder["runtime"] = runtime
        return runtime

    def _fake_thread_ctor(*, target, daemon):
        thread = _FakeThread(target=target, daemon=daemon)
        thread_holder["thread"] = thread
        return thread

    monkeypatch.setattr("Services._shared.cli.parse_args", _fake_parse_args)
    monkeypatch.setattr("Services.data_service.runtime.DataRecordingRuntime", _fake_runtime_ctor)
    monkeypatch.setattr("threading.Thread", _fake_thread_ctor)
    monkeypatch.setattr("Services.data_service.api.routes.set_runtime", lambda _runtime: None)
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: uvicorn_holder.update({"host": host, "port": port}))

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=RuntimeWarning,
            message=r".*Services\.data_service\.service.*",
        )
        runpy.run_module("Services.data_service.service", run_name="__main__")

    assert runtime_holder["runtime"].port == 9101
    assert thread_holder["thread"].started is True
    assert uvicorn_holder == {"host": "127.0.0.1", "port": 9002}
