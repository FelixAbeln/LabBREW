from __future__ import annotations

import json

import pytest

from Services.control_service.rules import repository as repository_module
from Services.control_service.rules import storage


def test_get_rule_dir_creates_directory(tmp_path, monkeypatch) -> None:
    storage.set_rule_repository(None)
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")

    result = storage.get_rule_dir()

    assert result.exists()
    assert result.is_dir()


def test_save_load_delete_rule_roundtrip(tmp_path, monkeypatch) -> None:
    storage.set_rule_repository(None)
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")
    rule = {
        "id": "r1",
        "enabled": True,
        "condition": {"source": "temp", "operator": ">", "params": {"threshold": 20}},
        "actions": [{"type": "set", "target": "heater", "value": 1}],
    }

    saved_path = storage.save_rule(rule)
    loaded = storage.load_rules()

    assert saved_path.exists()
    assert saved_path.name == "r1.json"
    assert loaded == [rule]

    deleted = storage.delete_rule("r1")
    loaded_after_delete = storage.load_rules()

    assert deleted is True
    assert loaded_after_delete == []


def test_save_rule_requires_id(tmp_path, monkeypatch) -> None:
    storage.set_rule_repository(None)
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")

    with pytest.raises(ValueError):
        storage.save_rule({"enabled": True})


def test_load_rules_skips_invalid_json_and_cleans_stale_tmp(tmp_path, monkeypatch, capsys) -> None:
    storage.set_rule_repository(None)
    rules_dir = tmp_path / "Rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(storage, "RULE_DIR", rules_dir)

    valid = {"id": "ok", "enabled": True}
    (rules_dir / "ok.json").write_text(json.dumps(valid), encoding="utf-8")
    (rules_dir / "broken.json").write_text("{ not valid json", encoding="utf-8")
    stale_tmp = rules_dir / "ok.json.xyz.tmp"
    stale_tmp.write_text("stale", encoding="utf-8")

    loaded = storage.load_rules()
    captured = capsys.readouterr()

    assert loaded == [valid]
    assert "Failed to load rule file" in captured.out
    assert not stale_tmp.exists()


def test_delete_rule_returns_false_for_missing_rule(tmp_path, monkeypatch) -> None:
    storage.set_rule_repository(None)
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")

    assert storage.delete_rule("missing") is False


def test_cleanup_stale_rule_tmp_files_ignores_unlink_oserror(tmp_path) -> None:
    _ = tmp_path
    class FakeTmpPath:
        def is_file(self) -> bool:
            return True

        def unlink(self) -> None:
            raise OSError("locked")

    class FakeRuleDir:
        def glob(self, pattern: str):
            assert pattern == "*.json.*.tmp"
            return [FakeTmpPath()]

    storage._cleanup_stale_rule_tmp_files(FakeRuleDir())  # type: ignore[arg-type]


def test_save_rule_runs_directory_fsync_when_supported(tmp_path, monkeypatch) -> None:
    storage.set_rule_repository(None)
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")

    fsync_calls: list[int] = []
    close_calls: list[int] = []
    original_open = repository_module.os.open

    def fake_fsync(fd: int) -> None:
        fsync_calls.append(fd)

    def fake_open(path, flags, mode=0o777):
        if str(path) == str(tmp_path / "Rules"):
            return 999
        return original_open(path, flags, mode)

    monkeypatch.setattr(repository_module.os, "fsync", fake_fsync)
    monkeypatch.setattr(repository_module.os, "open", fake_open)
    monkeypatch.setattr(repository_module.os, "close", lambda fd: close_calls.append(fd))

    saved_path = storage.save_rule({"id": "dirsync", "enabled": True})

    assert saved_path.name == "dirsync.json"
    assert 999 in fsync_calls
    assert close_calls == [999]


def test_save_rule_cleanup_tolerates_unlink_failure(tmp_path, monkeypatch) -> None:
    storage.set_rule_repository(None)
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")

    temp_paths: list[str] = []
    original_mkstemp = repository_module.tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, tmp_name = original_mkstemp(*args, **kwargs)
        temp_paths.append(tmp_name)
        return fd, tmp_name

    def fail_replace(_src: str, _dst) -> None:
        raise RuntimeError("replace failed")

    def fail_unlink(path: str) -> None:
        assert path == temp_paths[0]
        raise OSError("busy")

    monkeypatch.setattr(repository_module.tempfile, "mkstemp", tracking_mkstemp)
    monkeypatch.setattr(repository_module.Path, "replace", fail_replace)
    monkeypatch.setattr(repository_module.Path, "exists", lambda self: str(self) == temp_paths[0])
    monkeypatch.setattr(repository_module.Path, "unlink", lambda self: fail_unlink(str(self)))

    with pytest.raises(RuntimeError, match="replace failed"):
        storage.save_rule({"id": "cleanup", "enabled": True})

    assert temp_paths
