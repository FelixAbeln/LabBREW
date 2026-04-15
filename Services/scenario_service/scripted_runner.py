"""scripted_runner.py — executes a package-embedded Python runner script.

The runner script must define a single function::

    def run(ctx: RunnerContext) -> None: ...

The context provides the full API the script can call: write_setpoint,
read_value, request_control, release_control, sleep, is_stopped, log,
get_artifact, and set_progress.  The script runs in a daemon thread; pause/stop/resume
are signalled via threading events that ctx.sleep() honours.
"""
from __future__ import annotations

import base64
from collections import deque
import threading
import time
import types
from typing import Any


# ---------------------------------------------------------------------------
# RunnerContext — the API handed to every runner script
# ---------------------------------------------------------------------------

class RunnerContext:
    """Passed as the sole argument to the script's ``run(ctx)`` function."""

    def __init__(
        self,
        *,
        control_client: Any,
        data_client: Any | None,
        owner: str,
        artifacts: list[dict[str, Any]],
        log_fn,
        progress_fn,
        consume_nav_fn,
        nav_pending_fn,
        stop_event: threading.Event,
        pause_event: threading.Event,
    ) -> None:
        self._cc = control_client
        self._dc = data_client
        self._owner = owner
        self._artifact_map: dict[str, dict[str, Any]] = {
            str(a.get("path", "")).strip(): a
            for a in artifacts
            if str(a.get("path", "")).strip()
        }
        self._log = log_fn
        self._progress = progress_fn
        self._consume_nav = consume_nav_fn
        self._nav_pending = nav_pending_fn
        self._stop = stop_event
        self._pause = pause_event  # set → runner is paused
        self._owned: set[str] = set()

    # -- setpoint API --------------------------------------------------------

    def write_setpoint(self, target: str, value: Any) -> None:
        try:
            self._cc.write(target, value, self._owner)
        except Exception as exc:  # noqa: BLE001
            self._log(f"write_setpoint({target}={value!r}) failed: {exc}")

    def ramp_setpoint(self, target: str, value: Any, duration_s: float) -> None:
        """Delegate ramp execution to control service when supported.

        Falls back to direct write if the control client does not expose ramp.
        """
        ramp_fn = getattr(self._cc, "ramp", None)
        if callable(ramp_fn):
            try:
                ramp_fn(
                    target=target,
                    value=value,
                    duration_s=float(duration_s),
                    owner=self._owner,
                )
                return
            except Exception as exc:  # noqa: BLE001
                self._log(f"ramp_setpoint({target}={value!r}, {duration_s}s) failed: {exc}")
                return
        self.write_setpoint(target, value)

    def read_value(self, target: str) -> Any:
        try:
            return self._cc.read(target).get("value")
        except Exception:  # noqa: BLE001
            return None

    def snapshot_values(self) -> dict[str, Any]:
        snapshot_fn = getattr(self._cc, "snapshot", None)
        if not callable(snapshot_fn):
            return {}
        try:
            payload = snapshot_fn()
            values = payload.get("values") if isinstance(payload, dict) else {}
            return dict(values) if isinstance(values, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def request_control(self, target: str) -> None:
        try:
            self._cc.request_control(target, self._owner)
            self._owned.add(target)
        except Exception as exc:  # noqa: BLE001
            self._log(f"request_control({target}) failed: {exc}")

    def release_control(self, target: str) -> None:
        try:
            self._cc.release_control(target, self._owner)
            self._owned.discard(target)
        except Exception as exc:  # noqa: BLE001
            self._log(f"release_control({target}) failed: {exc}")

    def release_all(self) -> None:
        for t in list(self._owned):
            self.release_control(t)

    # -- timing API ----------------------------------------------------------

    def sleep(self, seconds: float) -> None:
        """Sleep for *seconds*, honouring pause and stop signals."""
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            if self._stop.is_set():
                return
            # Block while paused (stop still unblocks us)
            while self._pause.is_set() and not self._stop.is_set():
                time.sleep(0.05)
            if self._nav_pending() and not self._pause.is_set():
                return
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.05, remaining))

    def is_stopped(self) -> bool:
        return self._stop.is_set()

    def is_paused(self) -> bool:
        return self._pause.is_set()

    def consume_navigation(self) -> str | None:
        return self._consume_nav()

    # -- utility API ---------------------------------------------------------

    def log(self, message: str) -> None:
        self._log(str(message))

    def get_artifact(self, path: str) -> bytes:
        """Return the raw bytes of a named artifact from the package."""
        item = self._artifact_map.get(path)
        if item is None:
            raise FileNotFoundError(f"Artifact not found in package: {path!r}")
        content_b64 = item.get("content_b64", "")
        if not content_b64:
            return b""
        return base64.b64decode(content_b64)

    def set_progress(
        self,
        *,
        phase: str | None = None,
        step_index: int | None = None,
        step_name: str | None = None,
        wait_message: str | None = None,
    ) -> None:
        """Publish run progress fields for dashboard/status consumers."""
        self._progress(
            phase=phase,
            step_index=step_index,
            step_name=step_name,
            wait_message=wait_message,
        )

    # -- measurement API -----------------------------------------------------

    def _require_data_client(self) -> Any:
        if self._dc is None:
            raise RuntimeError("data client not configured")
        return self._dc

    def measurement_status(self) -> dict[str, Any]:
        try:
            return self._require_data_client().status()
        except Exception as exc:  # noqa: BLE001
            self._log(f"measurement_status failed: {exc}")
            return {"ok": False, "recording": False, "error": str(exc)}

    def setup_measurement(
        self,
        *,
        parameters: list[str],
        hz: float,
        output_dir: str,
        output_format: str,
        session_name: str,
        include_files: list[str] | None = None,
        include_payloads: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            data = self._require_data_client()
            setup_fn = getattr(data, "setup_measurement", None)
            if not callable(setup_fn):
                raise RuntimeError("data client missing setup_measurement")
            payload: dict[str, Any] = {
                "parameters": parameters,
                "hz": float(hz),
                "output_dir": output_dir,
                "output_format": output_format,
                "session_name": session_name,
                "include_files": include_files,
            }
            if include_payloads is not None:
                payload["include_payloads"] = include_payloads
            return setup_fn(**payload)
        except Exception as exc:  # noqa: BLE001
            self._log(f"setup_measurement failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def start_measurement(self) -> dict[str, Any]:
        try:
            return self._require_data_client().measure_start()
        except Exception as exc:  # noqa: BLE001
            self._log(f"start_measurement failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def stop_measurement(self) -> dict[str, Any]:
        try:
            return self._require_data_client().measure_stop()
        except Exception as exc:  # noqa: BLE001
            self._log(f"stop_measurement failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def take_loadstep(
        self,
        *,
        duration_seconds: float,
        loadstep_name: str,
        parameters: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._require_data_client().take_loadstep(
                duration_seconds=float(duration_seconds),
                loadstep_name=loadstep_name,
                parameters=parameters,
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"take_loadstep failed: {exc}")
            return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# ScriptedRunner — loads + runs the entrypoint script in a thread
# ---------------------------------------------------------------------------

class ScriptedRunner:
    """Runs a package-embedded Python script as a scenario runner.

    The script is executed via ``exec`` in an isolated module namespace.
    It must expose ``run(ctx)``.
    """

    def __init__(
        self,
        *,
        entrypoint_code: bytes,
        artifacts: list[dict[str, Any]],
        control_client: Any,
        data_client: Any | None = None,
        owner: str,
    ) -> None:
        self._entrypoint_code = entrypoint_code
        self._artifacts = artifacts
        self._cc = control_client
        self._dc = data_client
        self._owner = owner

        self._lock = threading.RLock()
        self._state = "idle"
        self._wait_message = "Idle"
        self._pause_reason: str | None = None
        self._phase: str | None = None
        self._current_step_index: int | None = None
        self._current_step_name: str | None = None
        self._owned_targets: list[str] = []
        self._event_log: list[str] = []
        self._navigation_queue: deque[str] = deque()

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._ctx: RunnerContext | None = None

    # -- lifecycle -----------------------------------------------------------

    def start_background(self) -> None:
        """No background tick; noop for API compatibility."""

    def shutdown(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3.0)

    # -- run control ---------------------------------------------------------

    def start_run(self) -> dict[str, Any]:
        with self._lock:
            if self._state == "running":
                return {"ok": False, "error": "Already running"}
            self._stop_event.clear()
            self._pause_event.clear()
            self._state = "running"
            self._wait_message = "Running"
            self._pause_reason = None
            self._phase = "run"
            self._current_step_index = None
            self._current_step_name = None
            t = threading.Thread(target=self._run_thread, daemon=True, name="scripted-runner")
            self._thread = t
            self._log("Run started")
        t.start()
        return {"ok": True}

    def pause_run(self) -> dict[str, Any]:
        with self._lock:
            if self._state != "running":
                return {"ok": False, "error": "Not running"}
            self._pause_event.set()
            self._state = "paused"
            self._wait_message = "Paused"
            self._pause_reason = "manual"
            self._log("Run paused")
        return {"ok": True}

    def resume_run(self) -> dict[str, Any]:
        with self._lock:
            if self._state != "paused":
                return {"ok": False, "error": "Not paused"}
            self._pause_event.clear()
            self._state = "running"
            self._wait_message = "Running"
            self._pause_reason = None
            self._log("Run resumed")
        return {"ok": True}

    def stop_run(self) -> dict[str, Any]:
        with self._lock:
            self._stop_event.set()
            self._pause_event.clear()
            prev = self._state
            self._state = "stopped"
            self._wait_message = "Stopped"
            self._pause_reason = None
            self._log("Run stop requested")
        if prev in ("running", "paused"):
            t = self._thread
            if t and t.is_alive():
                t.join(timeout=3.0)
        return {"ok": True}

    def next_step(self) -> dict[str, Any]:
        """Queue a next-step action for runner scripts that support navigation."""
        with self._lock:
            state = self._state
        if state == "idle":
            return self.start_run()
        if state == "paused":
            self._queue_navigation("next")
            self._log("Next step requested")
            return {"ok": True, "queued": True}
        if state == "running":
            self._queue_navigation("next")
            self._log("Next step requested")
            return {"ok": True, "queued": True}
        return {"ok": False, "error": f"Cannot advance from state '{state}'"}

    def previous_step(self) -> dict[str, Any]:
        """Queue a previous-step action for runner scripts that support navigation."""
        with self._lock:
            state = self._state
        if state == "paused":
            self._queue_navigation("previous")
            self._log("Previous step requested")
            return {"ok": True, "queued": True}
        if state == "running":
            self._queue_navigation("previous")
            self._log("Previous step requested")
            return {"ok": True, "queued": True}
        return {"ok": False, "error": f"Cannot go previous from state '{state}'"}

    def status(self) -> dict[str, Any]:
        with self._lock:
            ctx = self._ctx
            owned = list(ctx._owned) if ctx else []
            return {
                "state": self._state,
                "phase": self._phase,
                "current_step_index": self._current_step_index,
                "current_step_name": self._current_step_name,
                "wait_message": self._wait_message,
                "pause_reason": self._pause_reason,
                "owned_targets": owned,
                "event_log": list(self._event_log[-20:]),
                "navigation_pending": list(self._navigation_queue),
            }

    # -- internals -----------------------------------------------------------

    def _log(self, message: str) -> None:
        with self._lock:
            self._event_log.append(str(message))
            if len(self._event_log) > 100:
                self._event_log = self._event_log[-100:]

    def _set_progress(
        self,
        *,
        phase: str | None = None,
        step_index: int | None = None,
        step_name: str | None = None,
        wait_message: str | None = None,
    ) -> None:
        with self._lock:
            if phase is not None:
                self._phase = str(phase)
            if step_index is not None:
                self._current_step_index = int(step_index)
            if step_name is not None:
                self._current_step_name = str(step_name)
            if wait_message is not None:
                self._wait_message = str(wait_message)

    def _queue_navigation(self, action: str) -> None:
        with self._lock:
            self._navigation_queue.append(str(action))

    def _consume_navigation(self) -> str | None:
        with self._lock:
            if not self._navigation_queue:
                return None
            return self._navigation_queue.popleft()

    def _navigation_pending(self) -> bool:
        with self._lock:
            return bool(self._navigation_queue)

    def _run_thread(self) -> None:
        ctx = RunnerContext(
            control_client=self._cc,
            data_client=self._dc,
            owner=self._owner,
            artifacts=self._artifacts,
            log_fn=self._log,
            progress_fn=self._set_progress,
            consume_nav_fn=self._consume_navigation,
            nav_pending_fn=self._navigation_pending,
            stop_event=self._stop_event,
            pause_event=self._pause_event,
        )
        with self._lock:
            self._ctx = ctx
        try:
            module = types.ModuleType("_labbrew_runner")
            exec(  # noqa: S102
                compile(self._entrypoint_code, "<package_entrypoint>", "exec"),
                module.__dict__,
            )
            run_fn = getattr(module, "run", None)
            if run_fn is None:
                raise RuntimeError("Runner script must define a `run(ctx)` function")
            run_fn(ctx)
            with self._lock:
                if self._state == "running":
                    self._state = "completed"
                    self._wait_message = "Completed"
                    self._phase = "done"
                    self._log("Run completed")
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._state = "faulted"
                self._wait_message = f"Fault: {exc}"
                self._phase = "faulted"
            self._log(f"Runner faulted: {exc}")
        finally:
            try:
                ctx.release_all()
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                self._ctx = None
