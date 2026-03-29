from __future__ import annotations

import Services.schedule_service.control_client as control_client_module
import Services.schedule_service.data_client as data_client_module
from Services.schedule_service.control_client import ControlClient
from Services.schedule_service.data_client import DataClient


class DummyResponse:
    def __init__(self, payload: dict, *, should_raise: bool = False) -> None:
        self._payload = payload
        self._should_raise = should_raise

    def raise_for_status(self) -> None:
        if self._should_raise:
            raise RuntimeError("http error")

    def json(self) -> dict:
        return dict(self._payload)


class DummySession:
    def __init__(self) -> None:
        self.mounted: list[tuple[str, object]] = []
        self.calls: list[tuple[str, str, dict | None, float | None]] = []
        self.headers: dict[str, str] = {}
        self.closed = False

    def mount(self, prefix: str, adapter: object) -> None:
        self.mounted.append((prefix, adapter))

    def get(self, url: str, timeout: float | None = None):
        self.calls.append(("GET", url, None, timeout))
        return DummyResponse({"url": url, "method": "GET"})

    def post(self, url: str, json: dict | None = None, timeout: float | None = None):
        self.calls.append(("POST", url, json, timeout))
        return DummyResponse({"url": url, "method": "POST", "json": json or {}})

    def close(self) -> None:
        self.closed = True


def test_control_client_builds_expected_requests(monkeypatch) -> None:
    session = DummySession()
    monkeypatch.setattr(control_client_module.requests, "Session", lambda: session)

    client = ControlClient(base_url="http://host:1234/", timeout_s=7.0)

    assert client.request_control("t1", "schedule")["json"] == {"target": "t1", "owner": "schedule"}
    assert client.release_control("t1", "schedule")["json"] == {"target": "t1", "owner": "schedule"}
    assert client.write("t1", 3.14, "schedule")["json"] == {"target": "t1", "value": 3.14, "owner": "schedule"}
    assert client.ramp(target="t1", value=6.0, duration_s=10.0, owner="schedule")["json"] == {
        "target": "t1",
        "value": 6.0,
        "duration": 10.0,
        "owner": "schedule",
    }
    assert client.release_manual()["json"] == {}
    assert client.release_manual(["t1", "t2"])["json"] == {"targets": ["t1", "t2"]}

    client.read("abc")
    client.ownership()
    client.snapshot()
    client.snapshot(["a", "b"])

    get_urls = [url for method, url, _, _ in session.calls if method == "GET"]
    assert "http://host:1234/control/read/abc" in get_urls
    assert "http://host:1234/control/ownership" in get_urls
    assert "http://host:1234/system/snapshot" in get_urls
    assert "http://host:1234/system/snapshot?targets=a,b" in get_urls

    client.close()
    assert session.closed is True
    assert len(session.mounted) == 2


def test_data_client_builds_expected_requests_and_headers(monkeypatch) -> None:
    session = DummySession()
    monkeypatch.setattr(data_client_module.requests, "Session", lambda: session)

    client = DataClient(base_url="http://data:9999/", timeout_s=9.0)

    setup = client.setup_measurement(
        parameters=["p1"],
        hz=5.0,
        output_dir="out",
        output_format="jsonl",
        session_name="run1",
    )
    setup_with_files = client.setup_measurement(
        parameters=["p1"],
        include_files=["a.txt", "b.txt"],
    )
    client.measure_start()
    client.measure_stop()
    client.take_loadstep(duration_seconds=4.0, loadstep_name="ls", parameters=["p1"])
    client.status()

    assert setup["json"] == {
        "parameters": ["p1"],
        "hz": 5.0,
        "output_dir": "out",
        "output_format": "jsonl",
        "session_name": "run1",
    }
    assert setup_with_files["json"]["include_files"] == ["a.txt", "b.txt"]
    assert session.headers["Connection"] == "keep-alive"
    assert len(session.mounted) == 2

    post_calls = [item for item in session.calls if item[0] == "POST"]
    assert any(call[1].endswith("/measurement/start") for call in post_calls)
    assert any(call[1].endswith("/measurement/stop") for call in post_calls)
    assert any(call[1].endswith("/loadstep/take") for call in post_calls)

    get_calls = [item for item in session.calls if item[0] == "GET"]
    assert any(call[1].endswith("/status") for call in get_calls)

    client.close()
    assert session.closed is True
