from __future__ import annotations

from pathlib import Path

from Services._shared.storage_paths import (
    default_measurements_dir,
    default_parameterdb_audit_path,
    default_parameterdb_snapshot_path,
    default_sources_dir,
    storage_path,
    topology_path,
)


def test_storage_defaults_without_override(monkeypatch) -> None:
    monkeypatch.delenv("LABBREW_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("LABBREW_TOPOLOGY_PATH", raising=False)

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

    assert default_parameterdb_snapshot_path() == str((root / "data" / "parameterdb_snapshot.json").resolve())
    assert default_parameterdb_audit_path() == str((root / "data" / "parameterdb_audit.jsonl").resolve())
    assert default_sources_dir() == str((root / "data" / "sources").resolve())
    assert default_measurements_dir() == str((root / "data" / "measurements").resolve())


def test_topology_path_explicit_override(monkeypatch, tmp_path: Path) -> None:
    topology_file = tmp_path / "topology" / "custom.yaml"
    monkeypatch.setenv("LABBREW_TOPOLOGY_PATH", str(topology_file))
    monkeypatch.delenv("LABBREW_STORAGE_ROOT", raising=False)

    assert topology_path() == topology_file.resolve()
