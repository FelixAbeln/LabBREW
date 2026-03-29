from __future__ import annotations

import json
from pathlib import Path

import pytest

from Services.control_service.rules import storage


def test_get_rule_dir_creates_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")

    result = storage.get_rule_dir()

    assert result.exists()
    assert result.is_dir()


def test_save_load_delete_rule_roundtrip(tmp_path, monkeypatch) -> None:
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
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")

    with pytest.raises(ValueError):
        storage.save_rule({"enabled": True})


def test_load_rules_skips_invalid_json_and_cleans_stale_tmp(tmp_path, monkeypatch, capsys) -> None:
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
    monkeypatch.setattr(storage, "RULE_DIR", tmp_path / "Rules")

    assert storage.delete_rule("missing") is False
