from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from Services.schedule_service.repository import JsonScheduleStateStore


def test_json_schedule_state_store_roundtrip_and_clear(tmp_path) -> None:
    path = tmp_path / "schedule_state.json"
    store = JsonScheduleStateStore(path)
    payload = {"state": "running", "current_step_index": 2}

    store.save(payload)

    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert store.load() == payload

    store.clear()
    assert store.load() is None


def test_json_schedule_state_store_returns_none_for_invalid_json(tmp_path) -> None:
    path = tmp_path / "schedule_state.json"
    path.write_text("{ not valid json", encoding="utf-8")
    store = JsonScheduleStateStore(path)

    assert store.load() is None


def test_json_schedule_state_store_default_path_branch() -> None:
    store = JsonScheduleStateStore()

    assert store.path.name == "schedule_state.json"


def test_replace_with_retry_succeeds_after_transient_permission_error(monkeypatch, tmp_path) -> None:
    store = JsonScheduleStateStore(tmp_path / "state.json")
    destination = tmp_path / "dest.json"
    tmp_file = tmp_path / "temp.tmp"
    tmp_file.write_text("payload", encoding="utf-8")

    real_replace = os.replace
    calls = {"count": 0}

    def _flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr("Services.schedule_service.repository.os.replace", _flaky_replace)
    monkeypatch.setattr("Services.schedule_service.repository.time.sleep", lambda _s: None)

    store._replace_with_retry(str(tmp_file), destination)

    assert destination.read_text(encoding="utf-8") == "payload"
    assert calls["count"] == 3


def test_replace_with_retry_raises_after_all_attempts(monkeypatch, tmp_path) -> None:
    store = JsonScheduleStateStore(tmp_path / "state.json")

    monkeypatch.setattr("Services.schedule_service.repository.os.replace", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr("Services.schedule_service.repository.time.sleep", lambda _s: None)

    with pytest.raises(PermissionError):
        store._replace_with_retry("tmp", tmp_path / "dest.json")


def test_cleanup_stale_tmp_files_deletes_old_and_ignores_unlink_error(monkeypatch, tmp_path) -> None:
    store = JsonScheduleStateStore(tmp_path / "schedule_state.json")
    stale = tmp_path / "schedule_state.json.a.tmp"
    stale.write_text("x", encoding="utf-8")
    now = int(os.path.getmtime(stale))
    os.utime(stale, (now - 3600, now - 3600))

    real_unlink = Path.unlink

    def _flaky_unlink(self, *args, **kwargs):
        if self.name.endswith(".a.tmp"):
            raise OSError("cannot delete")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _flaky_unlink)

    # Should not raise even when unlink fails.
    store._cleanup_stale_tmp_files()


def test_save_falls_back_to_in_place_write_on_replace_permission_error(monkeypatch, tmp_path) -> None:
    path = tmp_path / "schedule_state.json"
    store = JsonScheduleStateStore(path)

    monkeypatch.setattr(store, "_replace_with_retry", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")))

    payload = {"state": "running"}
    store.save(payload)

    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_save_cleans_tmp_and_raises_on_write_exception(monkeypatch, tmp_path) -> None:
    path = tmp_path / "schedule_state.json"
    store = JsonScheduleStateStore(path)

    original_replace = os.replace

    def _boom_replace(_src, _dst):
        raise RuntimeError("replace failed")

    monkeypatch.setattr("Services.schedule_service.repository.os.replace", _boom_replace)

    with pytest.raises(RuntimeError):
        store.save({"state": "x"})

    # Restore to avoid impacting other tests that may rely on os.replace afterwards.
    monkeypatch.setattr("Services.schedule_service.repository.os.replace", original_replace)


def test_clear_is_noop_when_file_missing(tmp_path) -> None:
    path = tmp_path / "schedule_state.json"
    store = JsonScheduleStateStore(path)

    store.clear()

    assert not path.exists()