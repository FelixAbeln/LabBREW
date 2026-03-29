from __future__ import annotations

from typing import Any

import pytest

from Services.parameterDB.parameterdb_core import client as client_module


class _RecorderClient(client_module._BaseClient):
    def __init__(self):
        super().__init__("h", 1, 2.0)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _request(self, cmd: str, payload: dict[str, Any] | None = None) -> Any:
        data = payload or {}
        self.calls.append((cmd, data))
        return {"cmd": cmd, "payload": data}


class _FakeSocket:
    def __init__(self):
        self.sent: list[bytes] = []
        self.closed = False
        self.file = _FakeFile()

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def makefile(self, _mode: str):
        return self.file

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class _FakeFile:
    def __init__(self):
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_base_client_command_wrappers_and_subscribe_factory() -> None:
    c = _RecorderClient()

    c.ping()
    c.stats()
    c.graph_info()
    c.snapshot()
    c.describe()
    c.list_parameters()
    c.list_parameter_types()
    c.list_parameter_type_ui()
    c.get_parameter_type_ui("pt")
    c.list_source_types_ui()
    c.get_source_type_ui("src", name="n1", mode="m1")
    c.list_sources()
    c.create_source("s", "type", config={"a": 1})
    c.update_source("s", config={"b": 2})
    c.delete_source("s")
    c.create_parameter("p", "static", value=1, config={"x": 1}, metadata={"m": 2})
    c.delete_parameter("p")
    c.get_value("p", default=3)
    c.set_value("p", 4)
    c.update_config("p", a=1)
    c.update_metadata("p", b=2)
    c.load_parameter_type_folder("folder")

    sub = c.subscribe(names=["a"], send_initial=False, max_queue=0)
    assert isinstance(sub, client_module.Subscription)
    assert sub.max_queue == 1

    commands = [name for name, _payload in c.calls]
    assert "ping" in commands
    assert "get_source_type_ui" in commands
    assert "create_parameter" in commands
    assert "load_parameter_type_folder" in commands


def test_subscription_enter_iter_exit_and_error_paths(monkeypatch) -> None:
    fake_socket = _FakeSocket()
    read_messages = iter([
        {"ok": True},
        {"event": "tick"},
        None,
    ])

    monkeypatch.setattr(client_module.socket, "create_connection", lambda *_args, **_kwargs: fake_socket)
    monkeypatch.setattr(client_module, "encode_message", lambda _req: b"msg")
    monkeypatch.setattr(client_module, "make_request", lambda cmd, payload: {"cmd": cmd, "payload": payload})
    monkeypatch.setattr(client_module, "read_message", lambda _file: next(read_messages))
    monkeypatch.setattr(client_module, "validate_response_envelope", lambda _ack: (True, "1", {"sub": "ok"}, None))

    with client_module.Subscription("h", 1, 1.0, names=["x"], send_initial=True, max_queue=5) as sub:
        events = list(sub)

    assert sub.subscription_info == {"sub": "ok"}
    assert events == [{"event": "tick"}]
    assert fake_socket.closed is True
    assert fake_socket.file.closed is True

    monkeypatch.setattr(client_module, "read_message", lambda _file: None)
    with pytest.raises(RuntimeError):
        client_module.Subscription("h", 1, 1.0).__enter__()

    monkeypatch.setattr(client_module, "read_message", lambda _file: {"ack": False})
    monkeypatch.setattr(client_module, "validate_response_envelope", lambda _ack: (False, "1", None, {"message": "denied"}))
    with pytest.raises(RuntimeError):
        client_module.Subscription("h", 1, 1.0).__enter__()


def test_signal_session_request_once_and_reconnect_paths(monkeypatch) -> None:
    session = client_module.SignalSession(reconnect_attempts=1)

    fake_socket = _FakeSocket()
    session.sock = fake_socket
    session.file = fake_socket.file
    monkeypatch.setattr(session, "connect", lambda: session)
    monkeypatch.setattr(client_module, "encode_message", lambda _req: b"msg")

    monkeypatch.setattr(client_module, "read_message", lambda _file: None)
    with pytest.raises(ConnectionError):
        session._request_once({"cmd": "ping"})

    monkeypatch.setattr(client_module, "read_message", lambda _file: {"ok": False})
    monkeypatch.setattr(client_module, "validate_response_envelope", lambda _resp: (False, "1", None, None))
    with pytest.raises(RuntimeError):
        session._request_once({"cmd": "ping"})

    monkeypatch.setattr(client_module, "validate_response_envelope", lambda _resp: (False, "1", None, {"type": "Bad", "message": "boom"}))
    with pytest.raises(RuntimeError):
        session._request_once({"cmd": "ping"})

    monkeypatch.setattr(client_module, "validate_response_envelope", lambda _resp: (True, "1", {"ok": True}, None))
    monkeypatch.setattr(client_module, "read_message", lambda _file: {"ok": True})
    assert session._request_once({"cmd": "ping"}) == {"ok": True}

    attempts = {"n": 0}

    def _flaky_once(_req):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("drop")
        return "ok"

    monkeypatch.setattr(session, "_request_once", _flaky_once)
    monkeypatch.setattr(client_module, "make_request", lambda cmd, payload: {"cmd": cmd, "payload": payload})
    assert session._request("ping", {}) == "ok"

    monkeypatch.setattr(session, "_request_once", lambda _req: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(RuntimeError):
        session._request("ping", {})


def test_signal_client_request_and_session_factory(monkeypatch) -> None:
    fake_socket = _FakeSocket()
    monkeypatch.setattr(client_module.socket, "create_connection", lambda *_args, **_kwargs: fake_socket)
    monkeypatch.setattr(client_module, "encode_message", lambda _req: b"msg")
    monkeypatch.setattr(client_module, "make_request", lambda cmd, payload: {"cmd": cmd, "payload": payload})

    c = client_module.SignalClient("h", 1, 2.0)

    monkeypatch.setattr(client_module, "read_message", lambda _file: None)
    with pytest.raises(RuntimeError):
        c._request("ping", {})

    monkeypatch.setattr(client_module, "read_message", lambda _file: {"ok": False})
    monkeypatch.setattr(client_module, "validate_response_envelope", lambda _resp: (False, "1", None, None))
    with pytest.raises(RuntimeError):
        c._request("ping", {})

    monkeypatch.setattr(client_module, "validate_response_envelope", lambda _resp: (False, "1", None, {"type": "X", "message": "bad"}))
    with pytest.raises(RuntimeError):
        c._request("ping", {})

    monkeypatch.setattr(client_module, "validate_response_envelope", lambda _resp: (True, "1", {"ok": True}, None))
    assert c._request("ping", {}) == {"ok": True}

    sess = c.session(reconnect_attempts=3)
    assert isinstance(sess, client_module.SignalSession)
    assert sess.reconnect_attempts == 3
