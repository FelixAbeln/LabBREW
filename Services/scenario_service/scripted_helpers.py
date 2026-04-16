from __future__ import annotations

import json
import time
from typing import Any

POLL_S = 0.1
WAIT_UPDATE_S = 1.0

OPS = {
    "==": lambda a, b: a == b,
    "=": lambda a, b: a == b,
    "eq": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "neq": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "gt": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "gte": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "lt": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "lte": lambda a, b: a <= b,
}


def set_progress_safe(ctx=None, **kwargs):
    if ctx is None:
        return
    fn = getattr(ctx, "set_progress", None)
    if callable(fn):
        try:
            fn(**kwargs)
        except Exception:
            pass


def to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def iter_program_steps(program: dict[str, Any]):
    for key in ("setup_steps", "plan_steps"):
        for step in (program.get(key) or []):
            if not isinstance(step, dict):
                continue
            if step.get("enabled", True) is False:
                continue
            yield key, step


def consume_navigation(ctx):
    fn = getattr(ctx, "consume_navigation", None)
    if not callable(fn):
        return None
    try:
        value = fn()
    except Exception:
        return None
    if value is None:
        return None
    text = str(value).strip().lower()
    return text if text in {"next", "previous"} else None


def is_paused(ctx):
    fn = getattr(ctx, "is_paused", None)
    if not callable(fn):
        return False
    try:
        return bool(fn())
    except Exception:
        return False


def format_scalar(value):
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def eval_condition(ctx, condition):
    source = str(condition.get("source") or "").strip()
    op = str(condition.get("operator") or "==").strip().lower()
    threshold = condition.get("threshold")
    if not source:
        return False

    value = ctx.read_value(source)
    if value is None:
        return False

    try:
        lhs = float(value)
        rhs = float(threshold)
    except Exception:
        lhs = value
        rhs = threshold

    fn = OPS.get(op)
    if fn is None:
        return False
    return bool(fn(lhs, rhs))


def eval_condition_debug(ctx, condition):
    source = str(condition.get("source") or "").strip()
    op = str(condition.get("operator") or "==").strip().lower()
    threshold = condition.get("threshold")
    if not source:
        return False, "condition: missing source"

    value = ctx.read_value(source)
    if value is None:
        return False, f"condition {source} {op} {format_scalar(threshold)} (current: n/a)"

    try:
        lhs = float(value)
        rhs = float(threshold)
    except Exception:
        lhs = value
        rhs = threshold

    fn = OPS.get(op)
    if fn is None:
        return False, f"condition {source} {op} {format_scalar(threshold)} (unsupported operator)"

    matched = bool(fn(lhs, rhs))
    status = "met" if matched else "waiting"
    return matched, (
        f"condition {source} {op} {format_scalar(threshold)} "
        f"(current: {format_scalar(value)}, {status})"
    )


def wait_for_navigation_if_paused(ctx, *, step_name):
    last_emit = 0.0
    while is_paused(ctx) and not ctx.is_stopped():
        nav = consume_navigation(ctx)
        if nav in {"next", "previous"}:
            ctx.log(f"Navigation while paused: {nav}")
            return nav
        now = time.monotonic()
        if now - last_emit >= WAIT_UPDATE_S:
            set_progress_safe(ctx, wait_message=f"Paused at {step_name} (Resume / Next / Previous)")
            last_emit = now
        time.sleep(POLL_S)
    return None


def evaluate_wait_child(ctx, child, *, started):
    kind = str((child or {}).get("kind") or "none").strip().lower()
    if kind in ("", "none"):
        return True, "none"
    if kind == "elapsed":
        duration_s = max(0.0, to_float((child or {}).get("duration_s"), 0.0))
        elapsed = max(0.0, time.monotonic() - started)
        done = elapsed >= duration_s
        return done, f"elapsed {min(elapsed, duration_s):.1f}/{duration_s:.1f}s"
    if kind == "condition":
        matched, detail = eval_condition_debug(ctx, (child or {}).get("condition") or {})
        return matched, detail
    return False, f"unsupported wait child '{kind}'"


def summarize_wait_statuses(statuses, *, limit=3):
    if not statuses:
        return ""
    return " | ".join(statuses[:limit])


def wait_elapsed(ctx, wait):
    duration_s = to_float(wait.get("duration_s"), 0.0)
    ctx.log(f"Waiting elapsed {duration_s:.1f}s")
    started = time.monotonic()
    last_emit = 0.0
    while not ctx.is_stopped():
        nav = consume_navigation(ctx)
        if nav in {"next", "previous"}:
            return nav
        elapsed = max(0.0, time.monotonic() - started)
        remaining = max(0.0, duration_s - elapsed)
        now = time.monotonic()
        if now - last_emit >= WAIT_UPDATE_S:
            set_progress_safe(
                ctx,
                wait_message=f"Waiting elapsed {elapsed:.1f}/{duration_s:.1f}s (remaining {remaining:.1f}s)",
            )
            last_emit = now
        if elapsed >= duration_s:
            return "ok"
        ctx.sleep(min(POLL_S, remaining))
    return "stop"


def wait_condition(ctx, wait):
    condition = wait.get("condition") or {}
    source = str(condition.get("source") or "?").strip()
    op = str(condition.get("operator") or "==").strip()
    threshold = condition.get("threshold")
    ctx.log(f"Waiting for condition {source} {op} {threshold}")
    last_emit = 0.0
    while not ctx.is_stopped():
        nav = consume_navigation(ctx)
        if nav in {"next", "previous"}:
            return nav
        matched, detail = eval_condition_debug(ctx, condition)
        now = time.monotonic()
        if now - last_emit >= WAIT_UPDATE_S:
            set_progress_safe(ctx, wait_message=detail)
            last_emit = now
        if matched:
            ctx.log(f"Condition met: {source} {op} {threshold}")
            return "ok"
        ctx.sleep(POLL_S)
    return "stop"


def wait_any_of(ctx, wait):
    ctx.log("Waiting any_of")
    children = [c for c in (wait.get("children") or []) if isinstance(c, dict)]
    started = time.monotonic()
    last_emit = 0.0

    while not ctx.is_stopped():
        nav = consume_navigation(ctx)
        if nav in {"next", "previous"}:
            return nav
        statuses = []
        for child in children:
            matched, detail = evaluate_wait_child(ctx, child, started=started)
            statuses.append(("met" if matched else "wait") + ": " + detail)
            if matched:
                set_progress_safe(ctx, wait_message=f"any_of satisfied: {detail}")
                return "ok"
        now = time.monotonic()
        if now - last_emit >= WAIT_UPDATE_S:
            set_progress_safe(
                ctx,
                wait_message="any_of waiting: " + summarize_wait_statuses(statuses),
            )
            last_emit = now
        ctx.sleep(POLL_S)
    return "stop"


def run_wait(ctx, wait):
    if not isinstance(wait, dict):
        return "ok"

    kind = str(wait.get("kind") or "none").strip().lower()
    if kind in ("none", ""):
        set_progress_safe(ctx, wait_message="No wait")
        nav = consume_navigation(ctx)
        if nav in {"next", "previous"}:
            return nav
        return "ok"
    if kind == "elapsed":
        return wait_elapsed(ctx, wait)
    if kind == "condition":
        return wait_condition(ctx, wait)
    if kind == "all_of":
        children = [c for c in (wait.get("children") or []) if isinstance(c, dict)]
        if not children:
            return "ok"
        started = time.monotonic()
        last_emit = 0.0
        while not ctx.is_stopped():
            nav = consume_navigation(ctx)
            if nav in {"next", "previous"}:
                return nav

            statuses = []
            all_matched = True
            for child in children:
                matched, detail = evaluate_wait_child(ctx, child, started=started)
                statuses.append(("met" if matched else "wait") + ": " + detail)
                all_matched = all_matched and matched

            now = time.monotonic()
            if now - last_emit >= WAIT_UPDATE_S:
                set_progress_safe(
                    ctx,
                    wait_message="all_of waiting: " + summarize_wait_statuses(statuses),
                )
                last_emit = now

            if all_matched:
                set_progress_safe(
                    ctx,
                    wait_message="all_of satisfied: " + summarize_wait_statuses(statuses),
                )
                return "ok"

            ctx.sleep(POLL_S)
        return "stop"
    if kind == "any_of":
        return wait_any_of(ctx, wait)

    ctx.log(f"Unsupported wait.kind '{kind}', continuing")
    return "ok"


def run_actions(ctx, actions):
    for action in actions or []:
        if ctx.is_stopped():
            return "stop"
        nav = consume_navigation(ctx)
        if nav in {"next", "previous"}:
            return nav
        if not isinstance(action, dict):
            continue

        kind = str(action.get("kind") or "write").strip().lower()
        target = str(action.get("target") or "").strip()
        value = action.get("value")

        if kind == "write":
            if not target:
                continue
            ctx.log(f"Write action {target}={value}")
            ctx.request_control(target)
            ctx.write_setpoint(target, value)
            continue

        if kind == "ramp":
            if not target:
                continue
            ctx.request_control(target)
            duration_s = max(0.0, to_float(action.get("duration_s"), 0.0))
            if duration_s <= 0.0:
                ctx.log(f"Ramp action {target} immediate to {value}")
                ctx.write_setpoint(target, value)
                continue
            ctx.log(f"Ramp action {target} delegated over {duration_s:.1f}s to {value}")
            ctx.ramp_setpoint(target, value, duration_s)
            continue

        if kind == "take_loadstep":
            params = action.get("params") if isinstance(action.get("params"), dict) else {}
            timing = str(params.get("timing") or "on_enter").strip().lower()
            if timing in {"before_next", "on_exit", "on_trigger"}:
                continue

            duration_seconds = to_float(
                params.get("duration_seconds", action.get("duration_s", 30.0)),
                30.0,
            )
            loadstep_name = str(
                params.get("loadstep_name")
                or action.get("name")
                or f"loadstep-{int(time.time())}"
            ).strip()
            loadstep_parameters = params.get("parameters")
            parsed_parameters = None
            if isinstance(loadstep_parameters, list):
                parsed_parameters = [
                    str(item).strip()
                    for item in loadstep_parameters
                    if str(item).strip()
                ] or None

            result = ctx.take_loadstep(
                duration_seconds=duration_seconds,
                loadstep_name=loadstep_name,
                parameters=parsed_parameters,
            )
            if result.get("ok", False):
                ctx.log(
                    f"Loadstep started: {result.get('loadstep_name') or loadstep_name} "
                    f"({duration_seconds:.1f}s)"
                )
            else:
                ctx.log(f"Loadstep failed: {result}")
            continue

        ctx.log(f"Unsupported action.kind '{kind}', skipping")
    return "ok"


def apply_navigation(index, total_steps, nav):
    if nav == "next":
        return min(index + 1, total_steps)
    if nav == "previous":
        return max(index - 1, 0)
    return index


def run_program(ctx, program: dict[str, Any]) -> None:
    steps = list(iter_program_steps(program))
    total_steps = len(steps)
    step_index = 0

    while step_index < total_steps:
        phase_name, step = steps[step_index]
        step_name = str(step.get("name") or f"Step {step_index + 1}")

        paused_nav = wait_for_navigation_if_paused(ctx, step_name=step_name)
        if paused_nav in {"next", "previous"}:
            step_index = apply_navigation(step_index, total_steps, paused_nav)
            continue

        ctx.log(f"Starting {phase_name} step {step_index + 1}/{total_steps}: {step_name}")
        set_progress_safe(
            ctx,
            phase="setup" if phase_name == "setup_steps" else "plan",
            step_index=step_index,
            step_name=step_name,
            wait_message="Running",
        )

        action_result = run_actions(ctx, step.get("actions") or [])
        if action_result == "stop":
            ctx.log("Run stopped during action execution")
            return
        if action_result in {"next", "previous"}:
            ctx.log(f"Navigation command during actions: {action_result}")
            step_index = apply_navigation(step_index, total_steps, action_result)
            continue

        wait_result = run_wait(ctx, step.get("wait") or {"kind": "none"})
        if wait_result == "stop":
            ctx.log("Run stopped during wait")
            return
        if wait_result in {"next", "previous"}:
            ctx.log(f"Navigation command during wait: {wait_result}")
            step_index = apply_navigation(step_index, total_steps, wait_result)
            continue

        ctx.log(f"Completed step {step_index + 1}/{total_steps}: {step_name}")
        step_index += 1

    set_progress_safe(ctx, phase="done", wait_message="Completed")


def load_program_artifact(ctx, path: str = "data/program.json") -> dict[str, Any]:
    return json.loads(ctx.get_artifact(path).decode("utf-8"))
