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

    with pytest.raises(ValueError, match="cannot define url_flag together with host_flag/port_flag"):
        YamlTopologyLoader().load(config_path)
