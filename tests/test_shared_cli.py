from __future__ import annotations

from Services._shared import cli


def test_build_shared_parser_defaults() -> None:
    parser = cli.build_shared_parser("demo")

    args = parser.parse_args([])

    assert args.backend_host == "127.0.0.1"
    assert args.backend_port == 8765
    assert args.data_backend_host == "127.0.0.1"
    assert args.data_backend_port == 8769
    assert args.host == "127.0.0.1"
    assert args.port == 8766


def test_build_shared_parser_overrides() -> None:
    parser = cli.build_shared_parser("demo")

    args = parser.parse_args([
        "--backend-host",
        "10.0.0.5",
        "--backend-port",
        "9001",
        "--data-backend-host",
        "10.0.0.6",
        "--data-backend-port",
        "9002",
        "--host",
        "0.0.0.0",
        "--port",
        "9003",
    ])

    assert args.backend_host == "10.0.0.5"
    assert args.backend_port == 9001
    assert args.data_backend_host == "10.0.0.6"
    assert args.data_backend_port == 9002
    assert args.host == "0.0.0.0"
    assert args.port == 9003


def test_parse_args_delegates_to_shared_parser(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeParser:
        def parse_args(self):
            captured["called"] = True
            return {"ok": True}

    def fake_builder(description: str):
        captured["description"] = description
        return FakeParser()

    monkeypatch.setattr(cli, "build_shared_parser", fake_builder)

    result = cli.parse_args("Datasource Service")

    assert captured == {"description": "Datasource Service", "called": True}
    assert result == {"ok": True}
