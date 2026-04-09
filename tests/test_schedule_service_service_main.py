from __future__ import annotations

from types import SimpleNamespace

from Services.schedule_service import service


class _DummyRuntime:
    def __init__(self, *, control_client, data_client) -> None:
        self.control_client = control_client
        self.data_client = data_client

    def start_background(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


class _FakeThread:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


class _DummyClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def close(self) -> None:
        return None


def test_schedule_service_prefers_url_backends(monkeypatch) -> None:
    args = SimpleNamespace(
        host="127.0.0.1",
        port=9000,
        backend_host="127.0.0.1",
        backend_port=8767,
        backend_url="http://10.10.0.10:8780/control",
        data_backend_host="127.0.0.1",
        data_backend_port=8769,
        data_backend_url="http://10.10.0.20:8780/data",
    )

    created: dict[str, object] = {}

    monkeypatch.setattr(service, "parse_args", lambda _name: args)
    monkeypatch.setattr(service.threading, "Thread", lambda *, target, daemon: _FakeThread(target=target, daemon=daemon))
    monkeypatch.setattr(service, "ControlClient", lambda *, base_url: created.setdefault("control_client", _DummyClient(base_url)))
    monkeypatch.setattr(service, "DataClient", lambda *, base_url: created.setdefault("data_client", _DummyClient(base_url)))
    monkeypatch.setattr(service, "ScheduleRuntime", lambda *, control_client, data_client: created.setdefault("runtime", _DummyRuntime(control_client=control_client, data_client=data_client)))
    monkeypatch.setattr(service, "set_runtime", lambda runtime: created.setdefault("set_runtime", runtime))
    monkeypatch.setattr(service.uvicorn, "run", lambda _app, host, port: created.setdefault("uvicorn", {"host": host, "port": port}))

    service.main()

    control_client = created["control_client"]
    data_client = created["data_client"]
    assert isinstance(control_client, _DummyClient)
    assert isinstance(data_client, _DummyClient)
    assert control_client.base_url == "http://10.10.0.10:8780/control"
    assert data_client.base_url == "http://10.10.0.20:8780/data"
