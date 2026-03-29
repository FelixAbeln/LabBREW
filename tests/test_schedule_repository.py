from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from Services.schedule_service.repository import JsonScheduleStateStore
from Services.schedule_service.models import ScheduleDefinition
from Services.schedule_service.repository import InMemoryScheduleRepository


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


def test_save_fallback_ignores_tmp_unlink_oserror(monkeypatch, tmp_path) -> None:
    path = tmp_path / "schedule_state.json"
    store = JsonScheduleStateStore(path)

    tmp_seen: list[str] = []
    import tempfile

    real_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, tmp_name = real_mkstemp(*args, **kwargs)
        tmp_seen.append(tmp_name)
        return fd, tmp_name

    monkeypatch.setattr("Services.schedule_service.repository.tempfile.mkstemp", tracking_mkstemp)
    monkeypatch.setattr(store, "_replace_with_retry", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr("Services.schedule_service.repository.os.path.exists", lambda p: str(p) == tmp_seen[0])
    monkeypatch.setattr("Services.schedule_service.repository.os.unlink", lambda _p: (_ for _ in ()).throw(OSError("busy")))

    store.save({"state": "running"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "running"}


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


def test_in_memory_schedule_repository_get_save_clear() -> None:
    repo = InMemoryScheduleRepository()

    assert repo.get_current() is None

    schedule = ScheduleDefinition(id="s1", name="S1", setup_steps=(), plan_steps=())
    repo.save(schedule)
    assert repo.get_current() is schedule

    repo.clear()
    assert repo.get_current() is None


def test_save_runs_directory_fsync_close_and_cleanup_error_path(tmp_path, monkeypatch) -> None:
    path = tmp_path / "schedule_state.json"
    store = JsonScheduleStateStore(path)

    fsync_calls: list[int] = []
    close_calls: list[int] = []
    original_open = os.open

    def fake_fsync(fd: int) -> None:
        fsync_calls.append(fd)

    def fake_open(open_path, flags, mode=0o777):
        if str(open_path) == str(path.parent):
            return 777
        return original_open(open_path, flags, mode)

    monkeypatch.setattr("Services.schedule_service.repository.os.fsync", fake_fsync)
    monkeypatch.setattr("Services.schedule_service.repository.os.open", fake_open)
    monkeypatch.setattr("Services.schedule_service.repository.os.close", lambda fd: close_calls.append(fd))

    store.save({"state": "ok"})

    assert 777 in fsync_calls
    assert close_calls == [777]

    tmp_seen: list[str] = []
    original_mkstemp = os.mkstemp if hasattr(os, "mkstemp") else None
    original_repo_mkstemp = __import__("tempfile").mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, tmp_name = original_repo_mkstemp(*args, **kwargs)
        tmp_seen.append(tmp_name)
        return fd, tmp_name

    def fail_replace(_src, _dst):
        raise RuntimeError("replace failed")

    def fail_unlink(unlink_path):
        assert str(unlink_path) == tmp_seen[0]
        raise OSError("busy")

    monkeypatch.setattr("Services.schedule_service.repository.tempfile.mkstemp", tracking_mkstemp)
    monkeypatch.setattr("Services.schedule_service.repository.os.replace", fail_replace)
    monkeypatch.setattr("Services.schedule_service.repository.os.path.exists", lambda p: str(p) == tmp_seen[0])
    monkeypatch.setattr("Services.schedule_service.repository.os.unlink", fail_unlink)

    with pytest.raises(RuntimeError, match="replace failed"):
        store.save({"state": "bad"})

    assert tmp_seen