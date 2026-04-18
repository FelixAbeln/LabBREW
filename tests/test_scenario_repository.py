from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from Services.scenario_service.repository import JsonScenarioStateStore


def test_replace_with_retry_succeeds_after_transient_permission_error(
    monkeypatch, tmp_path
) -> None:
    store = JsonScenarioStateStore(tmp_path / "scenario_state.json")
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

    monkeypatch.setattr("Services.scenario_service.repository.os.replace", _flaky_replace)
    monkeypatch.setattr("Services.scenario_service.repository.time.sleep", lambda _s: None)

    store._replace_with_retry(str(tmp_file), destination)

    assert destination.read_text(encoding="utf-8") == "payload"
    assert calls["count"] == 3


def test_save_falls_back_to_in_place_write_on_replace_permission_error(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "scenario_state.json"
    store = JsonScenarioStateStore(path)

    monkeypatch.setattr(
        store,
        "_replace_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")),
    )

    payload = {"state": "running"}
    store.save(payload)

    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_save_cleans_tmp_and_raises_on_replace_failure(monkeypatch, tmp_path) -> None:
    path = tmp_path / "scenario_state.json"
    store = JsonScenarioStateStore(path)

    tmp_seen: list[str] = []
    import tempfile

    real_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, tmp_name = real_mkstemp(*args, **kwargs)
        tmp_seen.append(tmp_name)
        return fd, tmp_name

    monkeypatch.setattr(
        "Services.scenario_service.repository.tempfile.mkstemp", tracking_mkstemp
    )
    monkeypatch.setattr(
        "Services.scenario_service.repository.os.replace",
        lambda _src, _dst: (_ for _ in ()).throw(RuntimeError("replace failed")),
    )

    with pytest.raises(RuntimeError, match="replace failed"):
        store.save({"state": "bad"})

    assert tmp_seen
    assert not Path(tmp_seen[0]).exists()