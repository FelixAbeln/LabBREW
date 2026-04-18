"""test_scenario_scripted_runner.py

Unit tests for the ScriptedRunner and ScenarioRuntime scripted runner path.

Tests are self-contained — no running services required.
All sleep calls in the runner are skipped by patching ctx.sleep on the
RunnerContext instance before blocking.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import zipfile
import io
from pathlib import Path
from typing import Any

import msgpack
import pytest

from Services.scenario_service.scripted_runner import RunnerContext, ScriptedRunner
from Services.scenario_service.repository import JsonScenarioStateStore
from Services.scenario_service.runtime import ScenarioRuntime


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_artifacts(scripts: dict[str, str], extra_files: dict[str, bytes] | None = None) -> list[dict[str, Any]]:
    """Build an artifact list from a dict of path -> text or path -> bytes."""
    artifacts = []
    for path, content in scripts.items():
        blob = content.encode("utf-8") if isinstance(content, str) else content
        artifacts.append({
            "path": path,
            "encoding": "base64",
            "content_b64": base64.b64encode(blob).decode("ascii"),
            "size": len(blob),
        })
    if extra_files:
        for path, blob in extra_files.items():
            artifacts.append({
                "path": path,
                "encoding": "base64",
                "content_b64": base64.b64encode(blob).decode("ascii"),
                "size": len(blob),
            })
    return artifacts


def _fast_runner(artifacts, extra=None) -> ScriptedRunner:
    """Build a ScriptedRunner with a no-op ControlClient."""
    class _CC:
        def write(self, t, v, o): pass
        def request_control(self, t, o): pass
        def release_control(self, t, o): pass

    return ScriptedRunner(
        entrypoint_code=base64.b64decode(
            next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
        ),
        artifacts=artifacts + (extra or []),
        control_client=_CC(),
        owner="test",
    )


def _make_package_payload(runner_kind: str, entrypoint_script: str, extra_artifacts: list | None = None) -> dict:
    """Build a full package manifest payload suitable for ScenarioRuntime.compile_package."""
    artifacts = _make_artifacts({
        "bin/runner.py": entrypoint_script,
        "validation/validation.json": '{"schema": "v1"}',
        "editor/spec.json": '{"schema": "v1"}',
    })
    if extra_artifacts:
        artifacts.extend(extra_artifacts)
    return {
        "id": "test-pkg",
        "name": "Test Package",
        "version": "0.1.0",
        "runner": {"kind": runner_kind},
        "interface": {"kind": "labbrew.scenario-package", "version": "1"},
        "endpoint_code": {"language": "python", "entrypoint": "bin/runner.py"},
        "validation": {"artifact": "validation/validation.json"},
        "editor_spec": {"artifact": "editor/spec.json"},
        "artifacts": artifacts,
        "program": {},
    }


def _make_runtime(*, state_store: JsonScenarioStateStore | None = None) -> ScenarioRuntime:
    class _CC:
        def write(self, t, v, o): pass
        def request_control(self, t, o): pass
        def release_control(self, t, o): pass
        def snapshot(self, targets=None): return {"values": {}}
    class _DC:
        pass
    return ScenarioRuntime(control_client=_CC(), data_client=_DC(), state_store=state_store)


# ---------------------------------------------------------------------------
# RunnerContext
# ---------------------------------------------------------------------------

class TestRunnerContext:
    def _make_ctx(self, script_artifacts: dict[str, str] | None = None):
        writes = []
        class _CC:
            def write(self, t, v, o): writes.append((t, v))
            def request_control(self, t, o): pass
            def release_control(self, t, o): pass

        stop = threading.Event()
        pause = threading.Event()
        logs = []
        ctx = RunnerContext(
            control_client=_CC(),
            data_client=None,
            owner="test",
            artifacts=_make_artifacts(script_artifacts or {}),
            log_fn=logs.append,
            progress_fn=lambda **_kwargs: None,
            consume_nav_fn=lambda: None,
            nav_pending_fn=lambda: False,
            stop_event=stop,
            pause_event=pause,
        )
        return ctx, writes, logs, stop, pause

    def test_write_setpoint_calls_control_client(self):
        ctx, writes, _, _, _ = self._make_ctx()
        ctx.write_setpoint("fermenter.temp", 20.5)
        assert writes == [("fermenter.temp", 20.5)]

    def test_request_and_release_control_tracked(self):
        ctx, _, _, _, _ = self._make_ctx()
        ctx.request_control("agitator.speed")
        assert "agitator.speed" in ctx._owned
        ctx.release_control("agitator.speed")
        assert "agitator.speed" not in ctx._owned

    def test_request_control_pauses_until_available(self):
        class _CC:
            def __init__(self):
                self.calls = 0

            def write(self, t, v, o):
                _ = (t, v, o)

            def request_control(self, t, o):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "ok": False,
                        "current_owner": "operator",
                        "reason": "target owned by safety",
                    }
                return {"ok": True, "current_owner": o}

            def release_control(self, t, o):
                _ = (t, o)

        pause_reason = []
        cc = _CC()
        stop = threading.Event()
        pause = threading.Event()
        ctx = RunnerContext(
            control_client=cc,
            data_client=None,
            owner="test",
            artifacts=[],
            log_fn=lambda *_args: None,
            progress_fn=lambda **_kwargs: None,
            pause_for_reason_fn=lambda reason: (pause_reason.append(reason), pause.set()),
            consume_nav_fn=lambda: None,
            nav_pending_fn=lambda: False,
            stop_event=stop,
            pause_event=pause,
        )

        thread = threading.Thread(target=lambda: ctx.request_control("agitator.speed"))
        thread.start()
        assert pause.wait(1.0)
        assert pause_reason and "current owner: operator" in pause_reason[0]
        assert "target owned by safety" in pause_reason[0]
        pause.clear()
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        assert "agitator.speed" in ctx._owned

    def test_sleep_pauses_immediately_when_owned_target_taken_over(self):
        class _CC:
            def __init__(self):
                self.taken = False

            def write(self, t, v, o):
                _ = (t, v, o)
                return {"ok": True, "current_owner": o}

            def request_control(self, t, o):
                _ = t
                return {"ok": True, "current_owner": o}

            def release_control(self, t, o):
                _ = (t, o)

            def ownership(self):
                owner = "operator" if self.taken else "test"
                return {"x": {"owner": owner}}

        pause_reason = []
        cc = _CC()
        stop = threading.Event()
        pause = threading.Event()
        ctx = RunnerContext(
            control_client=cc,
            data_client=None,
            owner="test",
            artifacts=[],
            log_fn=lambda *_args: None,
            progress_fn=lambda **_kwargs: None,
            pause_for_reason_fn=lambda reason: (pause_reason.append(reason), pause.set()),
            consume_nav_fn=lambda: None,
            nav_pending_fn=lambda: False,
            stop_event=stop,
            pause_event=pause,
        )
        ctx.request_control("x")

        thread = threading.Thread(target=lambda: ctx.sleep(0.6))
        cc.taken = True
        thread.start()
        assert pause.wait(0.5)
        assert pause_reason and "ownership lost for x" in pause_reason[0]
        cc.taken = False
        pause.clear()
        thread.join(timeout=1.0)
        assert not thread.is_alive()

    def test_write_setpoint_non_retryable_failure_raises(self):
        class _CC:
            def write(self, t, v, o):
                _ = (t, v, o)
                return {"ok": False, "blocked": False, "reason": "validation failed"}

            def request_control(self, t, o):
                _ = (t, o)

            def release_control(self, t, o):
                _ = (t, o)

        ctx = RunnerContext(
            control_client=_CC(),
            data_client=None,
            owner="test",
            artifacts=[],
            log_fn=lambda *_args: None,
            progress_fn=lambda **_kwargs: None,
            consume_nav_fn=lambda: None,
            nav_pending_fn=lambda: False,
            stop_event=threading.Event(),
            pause_event=threading.Event(),
        )

        with pytest.raises(RuntimeError, match="validation failed"):
            ctx.write_setpoint("agitator.speed", 100)

    def test_request_control_non_retryable_failure_raises(self):
        class _CC:
            def write(self, t, v, o):
                _ = (t, v, o)

            def request_control(self, t, o):
                _ = (t, o)
                return {"ok": False, "reason": "unknown target"}

            def release_control(self, t, o):
                _ = (t, o)

        ctx = RunnerContext(
            control_client=_CC(),
            data_client=None,
            owner="test",
            artifacts=[],
            log_fn=lambda *_args: None,
            progress_fn=lambda **_kwargs: None,
            consume_nav_fn=lambda: None,
            nav_pending_fn=lambda: False,
            stop_event=threading.Event(),
            pause_event=threading.Event(),
        )

        with pytest.raises(RuntimeError, match="unknown target"):
            ctx.request_control("missing.param")

    def test_ramp_setpoint_non_retryable_failure_raises(self):
        class _CC:
            def write(self, t, v, o):
                _ = (t, v, o)

            def ramp(self, *, target, value, duration_s, owner):
                _ = (target, value, duration_s, owner)
                return {"ok": False, "reason": "duration must be > 0"}

            def request_control(self, t, o):
                _ = (t, o)

            def release_control(self, t, o):
                _ = (t, o)

        ctx = RunnerContext(
            control_client=_CC(),
            data_client=None,
            owner="test",
            artifacts=[],
            log_fn=lambda *_args: None,
            progress_fn=lambda **_kwargs: None,
            consume_nav_fn=lambda: None,
            nav_pending_fn=lambda: False,
            stop_event=threading.Event(),
            pause_event=threading.Event(),
        )

        with pytest.raises(RuntimeError, match="duration must be > 0"):
            ctx.ramp_setpoint("agitator.speed", 100, 0.0)

    def test_release_all_clears_all_owned(self):
        ctx, _, _, _, _ = self._make_ctx()
        ctx.request_control("a")
        ctx.request_control("b")
        ctx.release_all()
        assert ctx._owned == set()

    def test_log_appends_to_log_fn(self):
        ctx, _, logs, _, _ = self._make_ctx()
        ctx.log("hello")
        assert "hello" in logs

    def test_is_stopped_reflects_stop_event(self):
        ctx, _, _, stop, _ = self._make_ctx()
        assert not ctx.is_stopped()
        stop.set()
        assert ctx.is_stopped()

    def test_get_artifact_returns_bytes(self):
        ctx, _, _, _, _ = self._make_ctx({"data/test.csv": "a,b\n1,2"})
        blob = ctx.get_artifact("data/test.csv")
        assert blob == b"a,b\n1,2"

    def test_get_artifact_raises_for_missing(self):
        ctx, _, _, _, _ = self._make_ctx()
        with pytest.raises(FileNotFoundError, match="not found"):
            ctx.get_artifact("nope.csv")

    def test_sleep_returns_immediately_when_stopped(self):
        ctx, _, _, stop, _ = self._make_ctx()
        stop.set()
        start = time.monotonic()
        ctx.sleep(10.0)
        assert time.monotonic() - start < 1.0

    def test_measurement_api_uses_data_client(self):
        class _CC:
            def write(self, t, v, o):
                _ = (t, v, o)

            def request_control(self, t, o):
                _ = (t, o)

            def release_control(self, t, o):
                _ = (t, o)

            def snapshot(self):
                return {"values": {"temp": 20.0}}

        calls = []

        class _DC:
            def status(self):
                calls.append("status")
                return {"ok": True, "recording": False}

            def setup_measurement(self, **payload):
                calls.append(("setup", payload))
                return {"ok": True}

            def measure_start(self):
                calls.append("start")
                return {"ok": True}

            def measure_stop(self):
                calls.append("stop")
                return {"ok": True}

            def take_loadstep(self, **payload):
                calls.append(("loadstep", payload))
                return {"ok": True, "loadstep_name": payload.get("loadstep_name")}

        ctx = RunnerContext(
            control_client=_CC(),
            data_client=_DC(),
            owner="test",
            artifacts=[],
            log_fn=lambda *_args: None,
            progress_fn=lambda **_kwargs: None,
            consume_nav_fn=lambda: None,
            nav_pending_fn=lambda: False,
            stop_event=threading.Event(),
            pause_event=threading.Event(),
        )

        assert ctx.measurement_status().get("ok") is True
        assert ctx.setup_measurement(
            parameters=["temp"],
            hz=5.0,
            output_dir="data/measurements",
            output_format="jsonl",
            session_name="s1",
            include_files=None,
            include_payloads=[
                {
                    "name": "scenario-package.lbpkg",
                    "content_b64": base64.b64encode(b"test-bytes").decode("ascii"),
                    "media_type": "application/octet-stream",
                }
            ],
        ).get("ok") is True
        assert ctx.start_measurement().get("ok") is True
        assert ctx.take_loadstep(duration_seconds=10.0, loadstep_name="ls1", parameters=None).get("ok") is True
        assert ctx.stop_measurement().get("ok") is True

        assert any(call == "start" for call in calls)
        assert any(call == "stop" for call in calls)
        setup_call = next(call for call in calls if isinstance(call, tuple) and call[0] == "setup")
        assert "include_payloads" in setup_call[1]


# ---------------------------------------------------------------------------
# ScriptedRunner — state machine
# ---------------------------------------------------------------------------

TRIVIAL_RUNNER = """\
def run(ctx):
    ctx.log("started")
    ctx.sleep(0.0)
    ctx.log("done")
"""

WRITE_RUNNER = """\
def run(ctx):
    ctx.request_control("out")
    ctx.write_setpoint("out", 1.23)
    ctx.release_control("out")
"""

PROGRESS_RUNNER = """\
def run(ctx):
    ctx.set_progress(phase="plan", step_index=2, step_name="Step C", wait_message="Holding")
    ctx.sleep(60.0)
"""

SLEEP_RUNNER = """\
def run(ctx):
    ctx.sleep(60.0)
"""

FAULT_RUNNER = """\
def run(ctx):
    raise RuntimeError("intentional fault")
"""

MISSING_RUN_FN = """\
def not_run(ctx):
    pass
"""


class TestScriptedRunnerStateMachine:
    def _runner(self, script: str, extra: list | None = None) -> ScriptedRunner:
        return _fast_runner(_make_artifacts({"bin/runner.py": script}), extra)

    def test_initial_state_is_idle(self):
        r = self._runner(TRIVIAL_RUNNER)
        assert r.status()["state"] == "idle"

    def test_start_run_transitions_to_running(self):
        r = self._runner(SLEEP_RUNNER)
        result = r.start_run()
        assert result["ok"] is True
        assert r.status()["state"] == "running"
        r.stop_run()

    def test_trivial_runner_completes(self):
        r = self._runner(TRIVIAL_RUNNER)
        r.start_run()
        r._thread.join(timeout=3.0)
        assert r.status()["state"] == "completed"

    def test_pause_and_resume(self):
        r = self._runner(SLEEP_RUNNER)
        r.start_run()
        result = r.pause_run()
        assert result["ok"] is True
        assert r.status()["state"] == "paused"
        result = r.resume_run()
        assert result["ok"] is True
        assert r.status()["state"] == "running"
        r.stop_run()

    def test_stop_from_running(self):
        r = self._runner(SLEEP_RUNNER)
        r.start_run()
        result = r.stop_run()
        assert result["ok"] is True
        assert r.status()["state"] == "stopped"

    def test_stop_from_paused(self):
        r = self._runner(SLEEP_RUNNER)
        r.start_run()
        r.pause_run()
        r.stop_run()
        assert r.status()["state"] == "stopped"

    def test_double_start_returns_error(self):
        r = self._runner(SLEEP_RUNNER)
        r.start_run()
        result = r.start_run()
        assert result["ok"] is False
        r.stop_run()

    def test_pause_when_not_running_returns_error(self):
        r = self._runner(TRIVIAL_RUNNER)
        result = r.pause_run()
        assert result["ok"] is False

    def test_resume_when_not_paused_returns_error(self):
        r = self._runner(TRIVIAL_RUNNER)
        r.start_run()
        result = r.resume_run()
        assert result["ok"] is False
        r.stop_run()

    def test_faulted_script_sets_faulted_state(self):
        r = self._runner(FAULT_RUNNER)
        r.start_run()
        r._thread.join(timeout=3.0)
        st = r.status()
        assert st["state"] == "faulted"
        assert "intentional fault" in st["wait_message"]

    def test_missing_run_function_faults(self):
        r = self._runner(MISSING_RUN_FN)
        r.start_run()
        r._thread.join(timeout=3.0)
        assert r.status()["state"] == "faulted"

    def test_runner_writes_setpoints(self):
        writes = []
        class _CC:
            def write(self, t, v, o): writes.append((t, v))
            def request_control(self, t, o): pass
            def release_control(self, t, o): pass

        artifacts = _make_artifacts({"bin/runner.py": WRITE_RUNNER})
        runner = ScriptedRunner(
            entrypoint_code=base64.b64decode(
                next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
            ),
            artifacts=artifacts,
            control_client=_CC(),
            owner="test",
        )
        runner.start_run()
        runner._thread.join(timeout=3.0)
        assert runner.status()["state"] == "completed"
        assert writes == [("out", 1.23)]

    def test_runner_releases_control_on_fault(self):
        releases = []
        class _CC:
            def write(self, t, v, o): pass
            def request_control(self, t, o): pass
            def release_control(self, t, o): releases.append(t)

        script = "def run(ctx):\n    ctx.request_control('x')\n    raise RuntimeError('boom')\n"
        artifacts = _make_artifacts({"bin/runner.py": script})
        runner = ScriptedRunner(
            entrypoint_code=base64.b64decode(
                next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
            ),
            artifacts=artifacts,
            control_client=_CC(),
            owner="test",
        )
        runner.start_run()
        runner._thread.join(timeout=3.0)
        assert "x" in releases

    def test_runner_pauses_when_control_request_is_denied(self):
        class _CC:
            def request_control(self, t, o):
                return {"ok": False, "current_owner": "operator"}

            def write(self, t, v, o):
                return {"ok": True}

            def release_control(self, t, o):
                _ = (t, o)

        script = "def run(ctx):\n    ctx.request_control('x')\n    ctx.write_setpoint('x', 1.0)\n"
        artifacts = _make_artifacts({"bin/runner.py": script})
        runner = ScriptedRunner(
            entrypoint_code=base64.b64decode(
                next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
            ),
            artifacts=artifacts,
            control_client=_CC(),
            owner="test",
        )
        runner.start_run()

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            status = runner.status()
            if status["state"] == "paused":
                break
            time.sleep(0.01)

        st = runner.status()
        assert st["state"] == "paused"
        assert st["pause_reason"].startswith("control_lost:")
        assert "operator" in st["pause_reason"]
        runner.stop_run()

    def test_runner_pauses_on_blocked_write_until_resume(self):
        writes = []

        class _CC:
            def __init__(self):
                self.write_calls = 0

            def request_control(self, t, o):
                return {"ok": True, "current_owner": o}

            def write(self, t, v, o):
                self.write_calls += 1
                if self.write_calls == 1:
                    return {"ok": False, "blocked": True, "current_owner": "schedule_service"}
                writes.append((t, v, o))
                return {"ok": True, "current_owner": o}

            def release_control(self, t, o):
                _ = (t, o)

        script = "def run(ctx):\n    ctx.request_control('x')\n    ctx.write_setpoint('x', 1.0)\n"
        artifacts = _make_artifacts({"bin/runner.py": script})
        cc = _CC()
        runner = ScriptedRunner(
            entrypoint_code=base64.b64decode(
                next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
            ),
            artifacts=artifacts,
            control_client=cc,
            owner="test",
        )
        runner.start_run()

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if runner.status()["state"] == "paused":
                break
            time.sleep(0.01)

        assert runner.status()["state"] == "paused"
        result = runner.resume_run()
        assert result["ok"] is True
        runner._thread.join(timeout=2.0)
        assert runner.status()["state"] == "completed"
        assert writes == [("x", 1.0, "test")]

    def test_runner_pauses_on_operator_takeover_during_write(self):
        class _CC:
            def request_control(self, t, o):
                return {"ok": True, "current_owner": o}

            def write(self, t, v, o):
                _ = (t, v, o)
                return {"ok": False, "blocked": True, "current_owner": "operator"}

            def release_control(self, t, o):
                _ = (t, o)

        script = "def run(ctx):\n    ctx.request_control('x')\n    ctx.write_setpoint('x', 1.0)\n"
        artifacts = _make_artifacts({"bin/runner.py": script})
        runner = ScriptedRunner(
            entrypoint_code=base64.b64decode(
                next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
            ),
            artifacts=artifacts,
            control_client=_CC(),
            owner="test",
        )
        runner.start_run()

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if runner.status()["state"] == "paused":
                break
            time.sleep(0.01)

        st = runner.status()
        assert st["state"] == "paused"
        assert st["pause_reason"].startswith("control_lost:")
        assert "operator" in st["pause_reason"]
        runner.stop_run()

    def test_runner_faults_on_non_retryable_write_failure(self):
        class _CC:
            def request_control(self, t, o):
                return {"ok": True, "current_owner": o}

            def write(self, t, v, o):
                _ = (t, v, o)
                return {"ok": False, "blocked": False, "reason": "backend write failed"}

            def release_control(self, t, o):
                _ = (t, o)

        script = "def run(ctx):\n    ctx.request_control('x')\n    ctx.write_setpoint('x', 1.0)\n"
        artifacts = _make_artifacts({"bin/runner.py": script})
        runner = ScriptedRunner(
            entrypoint_code=base64.b64decode(
                next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
            ),
            artifacts=artifacts,
            control_client=_CC(),
            owner="test",
        )
        runner.start_run()
        runner._thread.join(timeout=2.0)
        st = runner.status()
        assert st["state"] == "faulted"
        assert "backend write failed" in str(st["wait_message"])

    def test_runner_faults_on_non_retryable_ramp_failure(self):
        class _CC:
            def request_control(self, t, o):
                return {"ok": True, "current_owner": o}

            def write(self, t, v, o):
                _ = (t, v, o)
                return {"ok": True}

            def ramp(self, *, target, value, duration_s, owner):
                _ = (target, value, duration_s, owner)
                return {"ok": False, "reason": "duration must be > 0"}

            def release_control(self, t, o):
                _ = (t, o)

        script = "def run(ctx):\n    ctx.request_control('x')\n    ctx.ramp_setpoint('x', 1.0, 0.0)\n"
        artifacts = _make_artifacts({"bin/runner.py": script})
        runner = ScriptedRunner(
            entrypoint_code=base64.b64decode(
                next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
            ),
            artifacts=artifacts,
            control_client=_CC(),
            owner="test",
        )
        runner.start_run()
        runner._thread.join(timeout=2.0)
        st = runner.status()
        assert st["state"] == "faulted"
        assert "duration must be > 0" in str(st["wait_message"])

    def test_get_artifact_accessible_from_script(self):
        received = []
        class _CC:
            def write(self, t, v, o): pass
            def request_control(self, t, o): pass
            def release_control(self, t, o): pass

        extra_csv = b"a,b\n1,2\n"
        script = "def run(ctx):\n    ctx.log(ctx.get_artifact('data/test.csv').decode())\n"
        artifacts = _make_artifacts({"bin/runner.py": script, "data/test.csv": extra_csv.decode()})
        runner = ScriptedRunner(
            entrypoint_code=base64.b64decode(
                next(a["content_b64"] for a in artifacts if a["path"] == "bin/runner.py")
            ),
            artifacts=artifacts,
            control_client=_CC(),
            owner="test",
        )
        runner.start_run()
        runner._thread.join(timeout=3.0)
        assert runner.status()["state"] == "completed"
        log = runner._event_log
        assert any("a,b" in entry for entry in log)

    def test_runner_exposes_progress_fields(self):
        r = self._runner(PROGRESS_RUNNER)
        r.start_run()
        time.sleep(0.15)
        st = r.status()
        assert st["phase"] == "plan"
        assert st["current_step_index"] == 2
        assert st["current_step_name"] == "Step C"
        assert st["wait_message"] == "Holding"
        r.stop_run()


# ---------------------------------------------------------------------------
# ScenarioRuntime — scripted runner integration
# ---------------------------------------------------------------------------

class TestScenarioRuntimeScriptedRunner:
    def test_compile_package_accepts_scripted_kind(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)
        result = rt.compile_package(payload)
        assert result["ok"] is True
        assert result["runner"] == "scripted"
        assert result["errors"] == []

    def test_compile_package_rejects_missing_entrypoint_artifact(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)
        # Remove the runner artifact
        payload["artifacts"] = [a for a in payload["artifacts"] if a["path"] != "bin/runner.py"]
        result = rt.compile_package(payload)
        assert result["ok"] is False
        assert any(e["code"] == "entrypoint_not_found" for e in result["errors"])

    def test_compile_package_rejects_blank_entrypoint(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)
        payload["endpoint_code"]["entrypoint"] = ""
        result = rt.compile_package(payload)
        assert result["ok"] is False
        assert any(e["code"] == "entrypoint_missing" for e in result["errors"])

    def test_compile_package_unknown_runner_kind_is_rejected(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)
        payload["runner"]["kind"] = "does_not_exist"
        result = rt.compile_package(payload)
        assert result["ok"] is False
        assert any(e["code"] == "runner_kind_unsupported" for e in result["errors"])

    def test_load_package_sets_active_runner_kind(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)
        result = rt.load_package(payload)
        assert result["ok"] is True
        assert rt._active_runner_kind == "scripted"
        assert isinstance(rt._scripted_runner, ScriptedRunner)

    def test_start_stop_via_runtime(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", SLEEP_RUNNER)
        rt.load_package(payload)
        start_result = rt.start_run()
        assert start_result["ok"] is True
        st = rt.status()
        assert st["runner_status"]["state"] == "running"
        rt.stop_run()
        assert rt.status()["runner_status"]["state"] == "stopped"

    def test_runtime_pauses_immediately_on_ownership_loss_during_wait(self):
        script = (
            "def run(ctx):\n"
            "    ctx.request_control('x')\n"
            "    ctx.sleep(5.0)\n"
            "    ctx.write_setpoint('x', 1.0)\n"
        )
        payload = _make_package_payload("scripted", script)

        class _CC:
            def __init__(self):
                self.owner = "scenario_service"
                self.writes = []

            def write(self, t, v, o):
                self.writes.append((t, v, o))
                return {"ok": True, "current_owner": o}

            def request_control(self, t, o):
                _ = t
                self.owner = o
                return {"ok": True, "current_owner": o}

            def release_control(self, t, o):
                _ = (t, o)

            def ownership(self):
                return {"x": {"owner": self.owner}}

        class _DC:
            pass

        cc = _CC()
        rt = ScenarioRuntime(control_client=cc, data_client=_DC())
        assert rt.load_package(payload)["ok"] is True
        assert rt.start_run()["ok"] is True

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            owned_targets = rt.status()["runner_status"].get("owned_targets") or []
            if "x" in owned_targets:
                break
            time.sleep(0.01)

        assert "x" in (rt.status()["runner_status"].get("owned_targets") or [])
        cc.owner = "operator"
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            state = rt.status()["runner_status"]["state"]
            if state == "paused":
                break
            time.sleep(0.01)

        status = rt.status()["runner_status"]
        assert status["state"] == "paused"
        assert str(status.get("pause_reason") or "").startswith("control_lost:")
        assert "operator" in str(status.get("pause_reason") or "")
        assert cc.writes == []
        rt.stop_run()

    def test_clear_package_shuts_down_scripted_runner(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", SLEEP_RUNNER)
        rt.load_package(payload)
        rt.start_run()
        rt.clear_package()
        assert rt._scripted_runner is None
        assert rt._active_runner_kind == "scripted"

    def test_tune_package_updates_artifact_and_reloads(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)
        assert rt.load_package(payload)["ok"] is True

        updated_program = b'{"setup_steps": [], "plan_steps": [{"name": "patched"}]}'
        result = rt.tune_package(
            {
                "artifact_updates": [
                    {
                        "path": "data/program.json",
                        "content_b64": base64.b64encode(updated_program).decode("ascii"),
                        "media_type": "application/json",
                    }
                ]
            }
        )

        assert result["ok"] is True
        package = rt.get_package()["package"]
        artifacts = {item["path"]: item for item in package.get("artifacts", [])}
        assert "data/program.json" in artifacts
        decoded = base64.b64decode(artifacts["data/program.json"]["content_b64"])
        assert b"patched" in decoded

    def test_tune_package_rejects_active_run(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", SLEEP_RUNNER)
        assert rt.load_package(payload)["ok"] is True
        assert rt.start_run()["ok"] is True

        result = rt.tune_package({"artifact_updates": []})

        assert result["ok"] is False
        assert "active" in str(result.get("error", "")).lower()
        rt.stop_run()

    def test_next_step_queues_when_paused(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", SLEEP_RUNNER)
        rt.load_package(payload)
        rt.start_run()
        rt.pause_run()
        result = rt.next_step()
        assert result["ok"] is True
        assert result.get("queued") is True
        assert rt.status()["runner_status"]["state"] == "paused"
        rt.stop_run()

    def test_previous_step_queues_when_running(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", SLEEP_RUNNER)
        rt.load_package(payload)
        rt.start_run()
        result = rt.previous_step()
        assert result["ok"] is True
        assert result.get("queued") is True
        assert rt.status()["runner_status"]["state"] == "running"
        rt.stop_run()

    def test_tune_package_applies_package_patch(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)
        payload["program"] = {"setup_steps": [], "plan_steps": []}
        assert rt.load_package(payload)["ok"] is True

        result = rt.tune_package(
            {
                "package_patch": {
                    "name": "Patched package",
                    "program": {
                        "plan_steps": [
                            {
                                "name": "Edited Step",
                                "actions": [],
                                "wait": {"kind": "none"},
                            }
                        ]
                    },
                }
            }
        )

        assert result["ok"] is True
        package = rt.get_package()["package"]
        assert package["name"] == "Patched package"
        assert package["program"]["plan_steps"][0]["name"] == "Edited Step"

    def test_runtime_completes_trivial_script(self):
        rt = _make_runtime()
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)
        rt.load_package(payload)
        rt.start_run()
        rt._scripted_runner._thread.join(timeout=3.0)
        st = rt.status()
        assert st["runner_status"]["state"] == "completed"

    def test_non_scripted_runner_kind_is_rejected(self):
        rt = _make_runtime()
        payload = _make_package_payload("declarative", TRIVIAL_RUNNER)
        result = rt.compile_package(payload)
        assert result["ok"] is False
        assert any(e["code"] == "runner_kind_unsupported" for e in result["errors"])

    def test_scripted_package_is_restored_after_restart(self, tmp_path: Path):
        state_store = JsonScenarioStateStore(path=tmp_path / "scenario_state.json")
        payload = _make_package_payload("scripted", TRIVIAL_RUNNER)

        rt1 = _make_runtime(state_store=state_store)
        assert rt1.load_package(payload)["ok"] is True

        rt2 = _make_runtime(state_store=state_store)
        status = rt2.status()
        assert status["ok"] is True
        assert status["status"]["runner_kind"] == "scripted"
        assert status["runner_status"]["state"] == "idle"
        assert rt2.start_run()["ok"] is True
        rt2.stop_run()

    def test_measurement_auto_start_for_non_excel_custom_script(self, tmp_path: Path):
        custom_script = "def run(ctx):\n    ctx.log('custom runner active')\n"
        payload = _make_package_payload("scripted", custom_script)
        payload["id"] = "custom-script-pkg"
        payload["program"] = {
            "id": "custom-script-program",
            "measurement_config": {
                "hz": 7.5,
                "output_dir": "data/measurements",
                "output_format": "jsonl",
                "session_name": "custom-session",
                "parameters": ["temp", "pressure"],
            },
        }

        class _CC:
            def __init__(self):
                self.snapshots = 0

            def write(self, t, v, o):
                _ = (t, v, o)

            def request_control(self, t, o):
                _ = (t, o)

            def release_control(self, t, o):
                _ = (t, o)

            def read(self, target):
                _ = target
                return {"value": 0.0}

            def snapshot(self, targets=None):
                _ = targets
                self.snapshots += 1
                return {"values": {"temp": 20.0, "pressure": 1.0}}

        class _DC:
            def __init__(self):
                self.recording = False
                self.calls = []

            def status(self):
                return {"ok": True, "recording": self.recording}

            def setup_measurement(self, **payload):
                self.calls.append(("setup", payload))
                return {"ok": True}

            def measure_start(self):
                self.calls.append(("start", {}))
                self.recording = True
                return {"ok": True}

            def measure_stop(self):
                self.calls.append(("stop", {}))
                self.recording = False
                return {"ok": True, "archive_file": str(tmp_path / "x.zip")}

            def take_loadstep(self, **payload):
                self.calls.append(("loadstep", payload))
                return {"ok": True}

        rt = ScenarioRuntime(
            control_client=_CC(),
            data_client=_DC(),
            state_store=JsonScenarioStateStore(path=tmp_path / "scenario_state.json"),
        )
        assert rt.load_package(payload)["ok"] is True
        assert rt.start_run()["ok"] is True
        runner = rt._scripted_runner
        assert runner is not None
        runner._thread.join(timeout=3.0)
        status = rt.status()
        assert status["runner_status"]["state"] == "completed"

        calls = rt._data_client.calls
        assert any(name == "setup" for name, _ in calls)
        assert any(name == "start" for name, _ in calls)
        assert any(name == "stop" for name, _ in calls)
        setup_payload = next(payload for name, payload in calls if name == "setup")
        include_files = list(setup_payload.get("include_files") or [])
        include_payloads = list(setup_payload.get("include_payloads") or [])

        assert any(
            item.endswith("custom-session.run.log")
            or (item.endswith(".run.log") and "custom-session_" in item)
            for item in include_files
        )
        package_payload = next(
            item for item in include_payloads
            if str(item.get("name", "")).endswith(".lbpkg")
        )
        package_blob = base64.b64decode(package_payload["content_b64"])
        with zipfile.ZipFile(io.BytesIO(package_blob), "r") as archive:
            manifest = msgpack.unpackb(
                archive.read("scenario.package.msgpack"),
                raw=False,
            )
            assert manifest.get("id") == "custom-script-pkg"
            assert manifest.get("runner", {}).get("kind") == "scripted"
            assert manifest.get("endpoint_code", {}).get("entrypoint") == "bin/runner.py"
            assert manifest.get("validation", {}).get("artifact") == "validation/validation.json"
            assert manifest.get("editor_spec", {}).get("artifact") == "editor/spec.json"
            assert manifest.get("program", {}).get("id") == "custom-script-program"
            assert "bin/runner.py" in archive.namelist()
            assert "validation/validation.json" in archive.namelist()
            assert "editor/spec.json" in archive.namelist()


# ---------------------------------------------------------------------------
# Sine wave demo package (integration test against the real built .lbpkg)
# ---------------------------------------------------------------------------

def _load_real_lbpkg(path: str) -> dict:
    """Load a .lbpkg and return the manifest + artifacts as a payload dict."""
    with open(path, "rb") as fh:
        raw = fh.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        manifest = msgpack.unpackb(zf.read("scenario.package.msgpack"), raw=False)
        artifacts = []
        for info in zf.infolist():
            if info.is_dir() or info.filename == "scenario.package.msgpack":
                continue
            blob = zf.read(info.filename)
            artifacts.append({
                "path": info.filename,
                "encoding": "base64",
                "content_b64": base64.b64encode(blob).decode("ascii"),
                "size": len(blob),
            })
    manifest["artifacts"] = artifacts
    return manifest


class TestSineWaveDemoPackage:
    PKG = "data/scenario_packages/SineWave_Agitator_Demo.lbpkg"

    def test_compile_passes(self):
        payload = _load_real_lbpkg(self.PKG)
        rt = _make_runtime()
        result = rt.compile_package(payload)
        assert result["ok"] is True
        assert result["runner"] == "scripted"

    def test_runner_writes_agitator_setpoints(self, tmp_path: Path):
        """Start the demo runner, let it run for up to 0.5s, check writes."""
        payload = _load_real_lbpkg(self.PKG)
        writes = []

        class _CC:
            def write(self, t, v, o): writes.append((t, v))
            def request_control(self, t, o): pass
            def release_control(self, t, o): pass

        class _DC:
            pass

        rt = ScenarioRuntime(
            control_client=_CC(),
            data_client=_DC(),
            state_store=JsonScenarioStateStore(path=tmp_path / "scenario_state.json"),
        )
        rt.load_package(payload)
        rt.start_run()
        time.sleep(0.4)
        rt.stop_run()

        assert len(writes) >= 1
        targets = {t for t, _ in writes}
        assert "agitator.speed.setpoint" in targets

    def test_setpoint_values_are_in_sine_range(self, tmp_path: Path):
        """All written values should be within [offset-amplitude, offset+amplitude]."""
        payload = _load_real_lbpkg(self.PKG)
        meta = payload.get("metadata", {})
        amplitude = float(meta.get("amplitude", 0.4))
        offset = float(meta.get("offset", 0.5))
        lo, hi = offset - amplitude - 0.01, offset + amplitude + 0.01

        writes = []
        class _CC:
            def write(self, t, v, o): writes.append(v)
            def request_control(self, t, o): pass
            def release_control(self, t, o): pass

        class _DC:
            pass

        rt = ScenarioRuntime(
            control_client=_CC(),
            data_client=_DC(),
            state_store=JsonScenarioStateStore(path=tmp_path / "scenario_state.json"),
        )
        rt.load_package(payload)
        rt.start_run()
        time.sleep(0.4)
        rt.stop_run()

        assert all(lo <= v <= hi for v in writes), f"Out-of-range values: {[v for v in writes if not (lo <= v <= hi)]}"
