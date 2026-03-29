from __future__ import annotations

from Services._shared.parameterDB import paremeterDB as backend_module
from Services._shared.parameterDB.paremeterDB import SignalStoreBackend


class _FakeClient:
    def __init__(self):
        self.values = {"a": 1}
        self.raise_ping = False
        self.raise_set = False
        self.raise_get = False
        self.raise_snapshot = False
        self.raise_describe = False
        self.raise_create = False
        self.last_created = None

    def ping(self):
        if self.raise_ping:
            raise RuntimeError("ping failed")
        return "pong"

    def set_value(self, name, value):
        if self.raise_set:
            raise RuntimeError("set failed")
        self.values[name] = value
        return True

    def get_value(self, name, default=None):
        if self.raise_get:
            raise RuntimeError("get failed")
        return self.values.get(name, default)

    def create_parameter(self, name, parameter_type, *, value=None, config=None, metadata=None):
        if self.raise_create:
            raise RuntimeError("create failed")
        self.last_created = (name, parameter_type, value, config, metadata)

    def snapshot(self):
        if self.raise_snapshot:
            raise RuntimeError("snapshot failed")
        return dict(self.values)

    def describe(self):
        if self.raise_describe:
            raise RuntimeError("describe failed")
        return {"items": len(self.values)}


def test_backend_handles_missing_client_gracefully(monkeypatch) -> None:
    monkeypatch.setattr(backend_module, "SignalSession", None)
    backend = SignalStoreBackend()

    assert backend.connected() is False
    assert backend.ping() == "parameterdb_core not importable"
    assert backend.ensure("x", 1) is False
    assert backend.get_value("x", default=7) == 7
    assert backend.set_value("x", 3) is False
    assert backend.full_snapshot() == {}
    assert backend.describe() == {}


def test_backend_success_paths_with_client(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(backend_module, "SignalSession", lambda **_kwargs: fake)
    backend = SignalStoreBackend()

    assert backend.connected() is True
    assert backend.ping() == "pong"
    assert backend.ensure("b", 2) is True
    assert backend.ensure_parameter("x", value=5, config={"c": 1}, metadata={"m": 2}) is None
    assert fake.last_created == ("x", "static", 5, {"c": 1}, {"m": 2})
    assert backend.get_value("b") == 2
    assert backend.set_value("c", 3) is True
    assert backend.snapshot(["a", "b", "missing"]) == {"a": 1, "b": 2, "missing": None}
    assert backend.full_snapshot()["c"] == 3
    assert backend.describe() == {"items": 3}


def test_backend_tolerates_client_exceptions(monkeypatch) -> None:
    fake = _FakeClient()
    fake.raise_ping = True
    fake.raise_set = True
    fake.raise_get = True
    fake.raise_snapshot = True
    fake.raise_describe = True
    fake.raise_create = True

    monkeypatch.setattr(backend_module, "SignalSession", lambda **_kwargs: fake)
    backend = SignalStoreBackend()

    assert backend.connected() is False
    assert backend.ensure("a", 1) is False
    assert backend.get_value("a", default="fallback") == "fallback"
    assert backend.set_value("a", 2) is False
    backend.ensure_parameter("x")
    assert backend.full_snapshot() == {}
    assert backend.describe() == {}
