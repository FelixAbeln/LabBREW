from __future__ import annotations

import json
from pathlib import Path

import pytest

from Services.parameterDB.parameterdb_service.persistence.audit_log import AuditLogger
from Services.parameterDB.parameterdb_service.persistence.snapshots import (
    SNAPSHOT_FORMAT_VERSION,
    SnapshotManager,
    build_snapshot_payload,
    cleanup_stale_snapshot_tmp_files,
    load_snapshot_file,
    load_snapshot_into_store,
    write_snapshot_file,
)
from Services.parameterDB.parameterdb_service.plugin_api import ParameterBase, PluginSpec
from Services.parameterDB.parameterdb_service.store import ParameterStore


class FakeParameter(ParameterBase):
    parameter_type = "fake"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.added = False

    def on_added(self, store: ParameterStore) -> None:
        self.added = True

    def scan(self, ctx) -> None:
        return None


class FakeSpec(PluginSpec):
    parameter_type = "fake"

    def create(self, name: str, *, config=None, value=None, metadata=None) -> ParameterBase:
        return FakeParameter(name, config=config, value=value, metadata=metadata)


class FakeRegistry:
    def __init__(self) -> None:
        self.spec = FakeSpec()

    def get(self, parameter_type: str) -> PluginSpec:
        if parameter_type != "fake":
            raise ValueError("unknown parameter type")
        return self.spec



def test_snapshot_payload_write_and_load_roundtrip(tmp_path: Path) -> None:
    store = ParameterStore()
    store.add(FakeParameter("reactor.temp", value=21.0, config={"unit": "C"}, metadata={"owner": "pytest"}))
    payload = build_snapshot_payload(store)

    assert payload["format_version"] == SNAPSHOT_FORMAT_VERSION
    assert payload["store_revision"] == store.revision()
    assert "reactor.temp" in payload["parameters"]

    snapshot_file = tmp_path / "snapshot.json"
    write_snapshot_file(snapshot_file, payload)
    loaded = load_snapshot_file(snapshot_file)

    assert isinstance(loaded, dict)
    assert loaded["parameters"]["reactor.temp"]["value"] == 21.0



def test_load_snapshot_file_missing_and_invalid_shape(tmp_path: Path) -> None:
    missing = load_snapshot_file(tmp_path / "missing.json")
    assert missing is None

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_snapshot_file(bad)



def test_cleanup_stale_snapshot_tmp_files_removes_orphans(tmp_path: Path) -> None:
    snapshot_file = tmp_path / "parameterdb_snapshot.json"
    orphan_1 = tmp_path / "parameterdb_snapshot.json.abc.tmp"
    orphan_2 = tmp_path / "parameterdb_snapshot.json.xyz.tmp"
    unrelated = tmp_path / "other.tmp"

    orphan_1.write_text("x", encoding="utf-8")
    orphan_2.write_text("x", encoding="utf-8")
    unrelated.write_text("x", encoding="utf-8")

    cleanup_stale_snapshot_tmp_files(snapshot_file)

    assert not orphan_1.exists()
    assert not orphan_2.exists()
    assert unrelated.exists()



def test_load_snapshot_into_store_restores_valid_entries_only(tmp_path: Path) -> None:
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_payload = {
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "parameters": {
            "ok.param": {
                "parameter_type": "fake",
                "value": 5,
                "config": {"unit": "bar"},
                "metadata": {"seed": 1},
                "state": {"connected": True},
            },
            "missing_type": {
                "value": 9,
            },
            "123": {
                "parameter_type": "fake",
                "value": 1,
            },
        },
    }
    snapshot_file.write_text(json.dumps(snapshot_payload), encoding="utf-8")

    store = ParameterStore()
    restored = load_snapshot_into_store(store, FakeRegistry(), snapshot_file)

    assert restored == 2
    assert store.get_value("ok.param") == 5
    assert store.get_value("123") == 1
    rec = store.get_record("ok.param")
    assert rec.config == {"unit": "bar"}
    assert rec.metadata == {"seed": 1}
    assert rec.state == {"connected": True}



def test_load_snapshot_into_store_rejects_wrong_format_version(tmp_path: Path) -> None:
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps({"format_version": 999, "parameters": {}}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_snapshot_into_store(ParameterStore(), FakeRegistry(), snapshot_file)



def test_snapshot_manager_save_now_and_force_behaviors(tmp_path: Path) -> None:
    store = ParameterStore()
    store.add(FakeParameter("a", value=1))
    manager = SnapshotManager(store, tmp_path / "snap.json", interval_s=0.1, enabled=True)

    first = manager.save_now()
    second = manager.save_now()
    forced = manager.save_now(force=True)

    assert first is True
    assert second is False
    assert forced is True
    stats = manager.stats()
    assert stats["last_saved_revision"] == store.revision()
    assert stats["last_saved_at"] is not None



def test_snapshot_manager_stop_with_final_save_writes_file(tmp_path: Path) -> None:
    store = ParameterStore()
    store.add(FakeParameter("a", value=1))
    path = tmp_path / "final.json"
    manager = SnapshotManager(store, path, enabled=True)

    manager.stop(save_final=True)

    assert path.exists()



def test_snapshot_manager_disabled_does_not_save(tmp_path: Path) -> None:
    store = ParameterStore()
    store.add(FakeParameter("a", value=1))
    manager = SnapshotManager(store, tmp_path / "disabled.json", enabled=False)

    assert manager.save_now() is False
    manager.start()
    manager.stop(save_final=True)
    assert not (tmp_path / "disabled.json").exists()



def test_audit_logger_enabled_writes_jsonl_and_disabled_is_noop(tmp_path: Path) -> None:
    enabled_path = tmp_path / "audit_enabled.jsonl"
    disabled_path = tmp_path / "audit_disabled.jsonl"

    logger = AuditLogger(enabled_path, enabled=True)
    logger.log(category="change", action="value_written", name="x", value=1)

    disabled = AuditLogger(disabled_path, enabled=False)
    disabled.log(category="change", action="value_written", name="y", value=2)

    lines = enabled_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["category"] == "change"
    assert payload["action"] == "value_written"
    assert payload["name"] == "x"
    assert payload["value"] == 1
    assert not disabled_path.exists()
