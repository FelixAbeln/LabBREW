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
  scenario_service:
    module: Services.scenario_service.service
    listen:
      host: 0.0.0.0
      port: 8770
      proto: http
      path: /
    backends:
      database.local:
        url_flag: --data-backend-url
    static_args: []
    advertise_as:
      - scenario_service
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
  scenario_service:
    module: Services.scenario_service.service
    listen:
      host: 0.0.0.0
      port: 8770
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
        "Service 'scenario_service'.backends['data_service'] cannot define url_flag together with host_flag/port_flag"
    )


def test_loader_requires_host_and_port_when_url_flag_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
services:
  scenario_service:
    module: Services.scenario_service.service
    listen:
      host: 0.0.0.0
      port: 8770
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
        "Service 'scenario_service'.backends['data_service'].port_flag must be a non-empty string"
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
  scenario_service:
    module: Services.scenario_service.service
    listen:
      host: 0.0.0.0
      port: 8770
      proto: http
      path: /
    backends:
      database.local:
        url_flag: --data-backend-url
""".strip(),
        encoding="utf-8",
    )

    # default agent_port (8780) — external endpoint is on 8769, must raise
    with pytest.raises(ValueError) as exc:
        YamlTopologyLoader().load(config_path)

    assert str(exc.value) == (
        "Service 'scenario_service'.backends['database.local'] uses url_flag with external HTTP capability "
        "that does not target Supervisor Agent port 8780"
    )

    # custom agent_port matching the external endpoint port — must not raise
    YamlTopologyLoader().load(config_path, agent_port=8769)

    # custom agent_port that still doesn't match — error reports the custom port
    with pytest.raises(ValueError) as exc2:
        YamlTopologyLoader().load(config_path, agent_port=9000)

    assert str(exc2.value) == (
      "Service 'scenario_service'.backends['database.local'] uses url_flag with external HTTP capability "
      "that does not target Supervisor Agent port 9000"
    )


def test_loader_maps_postgres_persistence_block_to_service_env(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
services:
  ParameterDB:
    module: Services.parameterDB.serviceDB
    listen:
      host: 127.0.0.1
      port: 8765
      proto: tcp
    persistence:
      kind: postgres
      host: db.internal
      port: 5432
      database: labbrew
      username: brew
      password: secret
      table_prefix: runtime
      sslmode: require
""".strip(),
        encoding="utf-8",
    )

    topology = YamlTopologyLoader().load(config_path)
    service = topology.services[0]
    env = dict(service.env)

    assert env["LABBREW_PARAMETERDB_PERSISTENCE_KIND"] == "postgres"
    assert env["LABBREW_PARAMETERDB_POSTGRES_HOST"] == "db.internal"
    assert env["LABBREW_PARAMETERDB_POSTGRES_PORT"] == "5432"
    assert env["LABBREW_PARAMETERDB_POSTGRES_DATABASE"] == "labbrew"
    assert env["LABBREW_PARAMETERDB_POSTGRES_USERNAME"] == "brew"
    assert env["LABBREW_PARAMETERDB_POSTGRES_PASSWORD"] == "secret"
    assert env["LABBREW_PARAMETERDB_POSTGRES_TABLE_PREFIX"] == "runtime"
    assert env["LABBREW_PARAMETERDB_POSTGRES_SSLMODE"] == "require"


def test_loader_maps_datasource_postgres_persistence_block_to_service_env(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
services:
  ParameterDB_DataSource:
    module: Services.parameterDB.serviceDS
    listen:
      host: 127.0.0.1
      port: 8766
      proto: tcp
    persistence:
      kind: postgres
      host: db.internal
      port: 5432
      database: labbrew
      username: brew
      password: secret
      table_prefix: datasource
      sslmode: require
""".strip(),
        encoding="utf-8",
    )

    topology = YamlTopologyLoader().load(config_path)
    service = topology.services[0]
    env = dict(service.env)

    assert env["LABBREW_PARAMETERDB_DATASOURCE_PERSISTENCE_KIND"] == "postgres"
    assert env["LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_HOST"] == "db.internal"
    assert env["LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_PORT"] == "5432"
    assert env["LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_DATABASE"] == "labbrew"
    assert env["LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_USERNAME"] == "brew"
    assert env["LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_PASSWORD"] == "secret"
    assert env["LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_TABLE_PREFIX"] == "datasource"
    assert env["LABBREW_PARAMETERDB_DATASOURCE_POSTGRES_SSLMODE"] == "require"


def test_loader_rejects_incomplete_postgres_persistence_block(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
services:
  ParameterDB:
    module: Services.parameterDB.serviceDB
    listen:
      host: 127.0.0.1
      port: 8765
      proto: tcp
    persistence:
      kind: postgres
      host: db.internal
      database: labbrew
      username: brew
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        YamlTopologyLoader().load(config_path)

    assert str(exc.value) == (
        "Service 'ParameterDB'.persistence missing required key(s): password"
    )


def test_loader_maps_control_rules_postgres_persistence_block_to_service_env(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
services:
  control_service:
    module: Services.control_service.service
    listen:
      host: 127.0.0.1
      port: 8767
      proto: http
    persistence:
      kind: postgres
      host: db.internal
      port: 5432
      database: labbrew
      username: brew
      password: secret
      table_prefix: control_rules
      sslmode: require
""".strip(),
        encoding="utf-8",
    )

    topology = YamlTopologyLoader().load(config_path)
    service = topology.services[0]
    env = dict(service.env)

    assert env["LABBREW_CONTROL_RULES_PERSISTENCE_KIND"] == "postgres"
    assert env["LABBREW_CONTROL_RULES_POSTGRES_HOST"] == "db.internal"
    assert env["LABBREW_CONTROL_RULES_POSTGRES_PORT"] == "5432"
    assert env["LABBREW_CONTROL_RULES_POSTGRES_DATABASE"] == "labbrew"
    assert env["LABBREW_CONTROL_RULES_POSTGRES_USERNAME"] == "brew"
    assert env["LABBREW_CONTROL_RULES_POSTGRES_PASSWORD"] == "secret"
    assert env["LABBREW_CONTROL_RULES_POSTGRES_TABLE_PREFIX"] == "control_rules"
    assert env["LABBREW_CONTROL_RULES_POSTGRES_SSLMODE"] == "require"


def test_loader_rejects_json_persistence_with_postgres_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "topology.yaml"
    config_path.write_text(
        """
services:
  ParameterDB:
    module: Services.parameterDB.serviceDB
    listen:
      host: 127.0.0.1
      port: 8765
      proto: tcp
    persistence:
      kind: json
      host: db.internal
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        YamlTopologyLoader().load(config_path)

    assert str(exc.value) == (
        "Service 'ParameterDB'.persistence kind 'json' does not support key(s): host"
    )
