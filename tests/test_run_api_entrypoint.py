from __future__ import annotations

from BrewSupervisor import run_api


def test_run_api_main_calls_uvicorn(monkeypatch) -> None:
    captured = {}

    def _fake_run(app, host, port):
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(run_api.uvicorn, "run", _fake_run)

    run_api.main()

    assert captured["app"] is run_api.app
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8782
