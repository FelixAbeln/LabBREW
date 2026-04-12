from __future__ import annotations

from pathlib import Path

from Services._shared.storage_paths import (
    add_network_drive_to_topology,
    configured_network_drives,
    default_measurements_dir,
    default_parameterdb_audit_path,
    default_parameterdb_snapshot_path,
    default_sources_dir,
    storage_root,
    storage_path,
    topology_path,
)
from Services._shared import storage_paths as storage_paths_module
from Services.parameterDB import serviceDB as parameterdb_service
from Services.parameterDB.parameterdb_service import (
    service as parameterdb_legacy_service,
)


def test_storage_defaults_without_override(monkeypatch) -> None:
    monkeypatch.delenv("LABBREW_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("LABBREW_TOPOLOGY_PATH", raising=False)
    monkeypatch.delenv("CONFIG_PATH", raising=False)

    assert default_parameterdb_snapshot_path() == "./data/parameterdb_snapshot.json"
    assert default_parameterdb_audit_path() == "./data/parameterdb_audit.jsonl"
    assert default_sources_dir() == "./data/sources"
    assert default_measurements_dir() == "data/measurements"

    expected_topology = storage_path("system_topology.yaml")
    assert topology_path() == expected_topology


def test_storage_defaults_with_override(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "usb_data"
    monkeypatch.setenv("LABBREW_STORAGE_ROOT", str(root))
    monkeypatch.delenv("LABBREW_TOPOLOGY_PATH", raising=False)
    monkeypatch.delenv("CONFIG_PATH", raising=False)

    assert default_parameterdb_snapshot_path() == str((root / "parameterdb_snapshot.json").resolve())
    assert default_parameterdb_audit_path() == str((root / "parameterdb_audit.jsonl").resolve())
    assert default_sources_dir() == str((root / "sources").resolve())
    assert default_measurements_dir() == str((root / "measurements").resolve())


def test_topology_path_explicit_override(monkeypatch, tmp_path: Path) -> None:
    topology_file = tmp_path / "topology" / "custom.yaml"
    monkeypatch.setenv("LABBREW_TOPOLOGY_PATH", str(topology_file))
    monkeypatch.delenv("LABBREW_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("CONFIG_PATH", raising=False)

    assert topology_path() == topology_file.resolve()


def test_storage_defaults_with_config_path_env(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "deploy" / "system_topology.yaml"
    monkeypatch.delenv("LABBREW_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("LABBREW_TOPOLOGY_PATH", raising=False)
    monkeypatch.setenv("CONFIG_PATH", str(config_path))

    assert default_parameterdb_snapshot_path() == str((config_path.parent / "parameterdb_snapshot.json").resolve())
    assert default_parameterdb_audit_path() == str((config_path.parent / "parameterdb_audit.jsonl").resolve())
    assert default_sources_dir() == str((config_path.parent / "sources").resolve())
    assert default_measurements_dir() == str((config_path.parent / "measurements").resolve())
    assert topology_path() == config_path.resolve()


def test_storage_root_site_packages_prefers_labbrew_like_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LABBREW_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("LABBREW_TOPOLOGY_PATH", raising=False)
    monkeypatch.delenv("CONFIG_PATH", raising=False)

    deploy_root = tmp_path / "labbrew-deploy"
    (deploy_root / "Services").mkdir(parents=True, exist_ok=True)
    (deploy_root / "Supervisor").mkdir(parents=True, exist_ok=True)
    (deploy_root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(deploy_root)

    monkeypatch.setattr(storage_paths_module, "_is_site_packages_install", lambda: True)

    assert storage_root() == (deploy_root / "data").resolve()


def test_storage_root_config_path_precedes_site_packages_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LABBREW_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("LABBREW_TOPOLOGY_PATH", raising=False)

    deploy_root = tmp_path / "labbrew-deploy"
    (deploy_root / "Services").mkdir(parents=True, exist_ok=True)
    (deploy_root / "Supervisor").mkdir(parents=True, exist_ok=True)
    (deploy_root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(deploy_root)

    cfg_path = tmp_path / "usb-storage" / "system_topology.yaml"
    monkeypatch.setenv("CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(storage_paths_module, "_is_site_packages_install", lambda: True)

    assert storage_root() == cfg_path.parent.resolve()


def test_storage_root_env_precedes_config_path_and_site_packages_cwd(
    monkeypatch, tmp_path: Path
) -> None:
    deploy_root = tmp_path / "labbrew-deploy"
    (deploy_root / "Services").mkdir(parents=True, exist_ok=True)
    (deploy_root / "Supervisor").mkdir(parents=True, exist_ok=True)
    (deploy_root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(deploy_root)

    explicit_root = tmp_path / "explicit-storage"
    cfg_path = tmp_path / "config-storage" / "system_topology.yaml"

    monkeypatch.setenv("LABBREW_STORAGE_ROOT", str(explicit_root))
    monkeypatch.setenv("CONFIG_PATH", str(cfg_path))
    monkeypatch.delenv("LABBREW_TOPOLOGY_PATH", raising=False)
    monkeypatch.setattr(storage_paths_module, "_is_site_packages_install", lambda: True)

    assert storage_root() == explicit_root.resolve()
    assert default_measurements_dir() == str((explicit_root / "measurements").resolve())


def test_add_network_drive_updates_topology(monkeypatch, tmp_path: Path) -> None:
    topology_file = tmp_path / "topology" / "custom.yaml"
    topology_file.parent.mkdir(parents=True, exist_ok=True)
    topology_file.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setenv("LABBREW_TOPOLOGY_PATH", str(topology_file))

    added = add_network_drive_to_topology("shared", r"\\server\brewshare")

    assert added == {"name": "shared", "path": r"\\server\brewshare"}
    assert configured_network_drives() == [{"name": "shared", "path": r"\\server\brewshare"}]


def test_parameterdb_build_service_signature_uses_call_time_defaults() -> None:
    kwdefaults = parameterdb_service.build_service.__kwdefaults__ or {}
    assert kwdefaults.get("snapshot_path") is None
    assert kwdefaults.get("audit_log_path") is None


def test_parameterdb_legacy_build_service_signature_uses_call_time_defaults() -> None:
    kwdefaults = parameterdb_legacy_service.build_service.__kwdefaults__ or {}
    assert kwdefaults.get("snapshot_path") is None
    assert kwdefaults.get("audit_log_path") is None
