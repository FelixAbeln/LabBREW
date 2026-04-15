"""excel_program_runner.py

Builder-owned entrypoint for Excel-imported packages.

Execution behavior is shared and supplied by scenario service helpers so
packages follow a single scripted runtime path.
"""
from __future__ import annotations

from Services.scenario_service.scripted_helpers import load_program_artifact, run_program


def run(ctx):
    ctx.log("Excel program runner started")
    run_program(ctx, load_program_artifact(ctx))
    ctx.log("Excel program runner completed")
