"""sine_agitator_runner.py — scripted scenario runner demo.

Reads a CSV setpoint table from the package (data/setpoints.csv) and feeds
each row as an agitator speed setpoint, sleeping for the step's duration.

CSV format:
    duration_s,value,description
    5.0,0.00,Sine step 1
    ...

This file is embedded as ``bin/runner.py`` inside the .lbpkg archive.
It is executed by the LabBREW ScriptedRunner; it must define ``run(ctx)``.
"""
from __future__ import annotations

import csv
import io


def _set_progress(ctx, **kwargs) -> None:
    """Best-effort progress updates for mixed runtime versions."""
    fn = getattr(ctx, "set_progress", None)
    if callable(fn):
        try:
            fn(**kwargs)
        except Exception:
            pass


def run(ctx) -> None:
    # ------------------------------------------------------------------
    # Load the setpoint table bundled in the package
    # ------------------------------------------------------------------
    csv_bytes = ctx.get_artifact("data/setpoints.csv")
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    rows = list(reader)

    target = "agitator.speed.setpoint"
    ctx.request_control(target)
    _set_progress(ctx, phase="plan", step_index=0, step_name="Initialize", wait_message="Running")
    ctx.log(f"Sine agitator demo: {len(rows)} steps on '{target}'")

    try:
        for i, row in enumerate(rows):
            if ctx.is_stopped():
                ctx.log("Run stopped by operator")
                break

            value = float(row["value"])
            duration = float(row["duration_s"])
            description = row.get("description", "")
            step_name = description or f"Sine step {i + 1}"

            _set_progress(
                ctx,
                phase="plan",
                step_index=i,
                step_name=step_name,
                wait_message=f"Sleeping {duration:.1f}s",
            )
            ctx.write_setpoint(target, round(value, 4))
            ctx.log(
                f"Step {i + 1}/{len(rows)}: {target}={value:.3f}  "
                f"duration={duration:.1f}s  {description}"
            )
            ctx.sleep(duration)

    finally:
        _set_progress(ctx, phase="done", wait_message="Completed")
        ctx.release_control(target)
        ctx.log("Sine agitator demo complete")
