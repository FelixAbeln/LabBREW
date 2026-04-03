from __future__ import annotations

from pathlib import Path

import pytest

from Supervisor.infrastructure.config_loader import YamlTopologyLoader


def test_loader_supports_url_flag_backend_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
advertise_service_type: _fcs._tcp.local.
external_capabilities:
  database.local:
    endpoint:
      host: 10.10.0.20
      port: 8780
      proto: http
      path: /data
services:
  schedule_service:
    module: Services.schedule_service.service
    listen:
      host: 0.0.0.0
      port: 8768
      proto: http
      path: /
    backends:
      database.local:
        url_flag: --data-backend-url
    static_args: []
    advertise_as:
      - schedule_service
""".strip(),
        encoding="utf-8",
    )

    topology = YamlTopologyLoader().load(config_path)
    service = topology.services[0]

    assert service.requires == ("database.local",)
    assert len(service.capability_arg_rules) == 1
    rule = service.capability_arg_rules[0]
    assert rule.capability == "database.local"
    assert rule.mode == "url"
    assert rule.url_flag == "--data-backend-url"


def test_loader_rejects_mixed_url_and_host_port_backend_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
services:
  schedule_service:
    module: Services.schedule_service.service
    listen:
      host: 0.0.0.0
      port: 8768
      proto: http
      path: /
    backends:
      data_service:
        url_flag: --data-backend-url
        host_flag: --data-backend-host
        port_flag: --data-backend-port
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        YamlTopologyLoader().load(config_path)

    assert str(exc.value) == (
        "Service 'schedule_service'.backends['data_service'] cannot define url_flag together with host_flag/port_flag"
    )


def test_loader_requires_host_and_port_when_url_flag_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
services:
  schedule_service:
    module: Services.schedule_service.service
    listen:
      host: 0.0.0.0
      port: 8768
      proto: http
      path: /
    backends:
      data_service:
        host_flag: --data-backend-host
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        YamlTopologyLoader().load(config_path)

    assert str(exc.value) == (
        "Service 'schedule_service'.backends['data_service'].port_flag must be a non-empty string"
    )


def test_loader_rejects_url_flag_external_http_non_agent_port(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
external_capabilities:
  database.local:
    endpoint:
      host: 10.10.0.20
      port: 8769
      proto: http
      path: /data
services:
  schedule_service:
    module: Services.schedule_service.service
    listen:
      host: 0.0.0.0
      port: 8768
      proto: http
      path: /
    backends:
      database.local:
        url_flag: --data-backend-url
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        YamlTopologyLoader().load(config_path)

    assert str(exc.value) == (
        "Service 'schedule_service'.backends['database.local'] uses url_flag with external HTTP capability "
        "that does not target Supervisor Agent port 8780"
    )
