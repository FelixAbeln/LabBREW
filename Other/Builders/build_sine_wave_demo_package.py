"""build_sine_wave_demo_package.py

Builds ``data/scenario_packages/SineWave_Agitator_Demo.lbpkg`` — a scripted
scenario package that ramps agitator speed through a sine wave.

The package contains:
  scenario.package.msgpack  — binary MessagePack manifest (runner.kind=scripted)
  bin/runner.py             — the sine_agitator_runner source
  data/setpoints.csv        — generated sine-wave setpoint table
  validation/validation.json
  editor/spec.json

Usage::

    cd <workspace root>
    python Other/Builders/build_sine_wave_demo_package.py [--steps N] [--cycles C]
                                                  [--period-s T] [--amplitude A]
                                                  [--offset B] [--target NAME]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import zipfile
from pathlib import Path

import msgpack


ROOT = Path(__file__).resolve().parent.parent.parent
RUNNER_SRC = Path(__file__).parent / "demo_sources" / "sine_agitator_runner.py"
OUT_DIR = ROOT / "data" / "scenario_packages"


def build_setpoints_csv(
    *,
    steps: int,
    cycles: float,
    period_s: float,
    amplitude: float,
    offset: float,
    target: str,
) -> str:
    """Return CSV text with ``duration_s,value,description`` rows."""
    lines = ["duration_s,value,description"]
    duration_s = (period_s * cycles) / steps
    for i in range(steps):
        angle = 2.0 * math.pi * cycles * (i / steps)
        value = offset + amplitude * math.sin(angle)
        desc = f"sine i={i} angle={math.degrees(angle):.1f}deg {target}"
        lines.append(f"{duration_s:.3f},{value:.6f},{desc}")
    return "\n".join(lines)


def build_package(
    *,
    steps: int = 60,
    cycles: float = 2.0,
    period_s: float = 30.0,
    amplitude: float = 0.4,
    offset: float = 0.5,
    target: str = "agitator.speed.setpoint",
) -> Path:
    csv_text = build_setpoints_csv(
        steps=steps,
        cycles=cycles,
        period_s=period_s,
        amplitude=amplitude,
        offset=offset,
        target=target,
    )

    manifest = {
        "id": "sine-wave-agitator-demo",
        "name": "Sine Wave Agitator Demo",
        "version": "0.1.0",
        "description": (
            "Ramps agitator speed through a sine wave using a scripted runner. "
            "Demonstrates package-embedded execution with no service-side conditions."
        ),
        "runner": {"kind": "scripted"},
        "interface": {"kind": "labbrew.scenario-package", "version": "1"},
        "endpoint_code": {"language": "python", "entrypoint": "bin/runner.py"},
        "validation": {"artifact": "validation/validation.json"},
        "editor_spec": {"artifact": "editor/spec.json"},
        "metadata": {
            "steps": steps,
            "cycles": cycles,
            "period_s": period_s,
            "amplitude": amplitude,
            "offset": offset,
            "target": target,
        },
    }

    validation_json = json.dumps({
        "schema": "labbrew-validation-v1",
        "required_fields": [],
        "description": "No additional fields required for this scripted package.",
    }, indent=2)

    editor_spec_json = json.dumps({
        "schema": "labbrew-editor-spec-v1",
        "fields": [],
        "description": "Sine wave agitator demo — no user-editable fields.",
    }, indent=2)

    runner_src = RUNNER_SRC.read_text(encoding="utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("scenario.package.msgpack", msgpack.packb(manifest, use_bin_type=True))
        zf.writestr("bin/runner.py", runner_src.encode("utf-8"))
        zf.writestr("data/setpoints.csv", csv_text.encode("utf-8"))
        zf.writestr("validation/validation.json", validation_json.encode("utf-8"))
        zf.writestr("editor/spec.json", editor_spec_json.encode("utf-8"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "SineWave_Agitator_Demo.lbpkg"
    out_path.write_bytes(buf.getvalue())
    print(f"Built: {out_path}")
    print(f"  steps={steps}  cycles={cycles}  period_s={period_s}")
    print(f"  amplitude={amplitude}  offset={offset}  target={target!r}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build SineWave Agitator Demo .lbpkg")
    parser.add_argument("--steps", type=int, default=60, help="Number of CSV steps (default 60)")
    parser.add_argument("--cycles", type=float, default=2.0, help="Sine cycles (default 2)")
    parser.add_argument("--period-s", type=float, default=30.0, help="Seconds per cycle (default 30)")
    parser.add_argument("--amplitude", type=float, default=0.4, help="Sine amplitude (default 0.4)")
    parser.add_argument("--offset", type=float, default=0.5, help="Midpoint offset (default 0.5)")
    parser.add_argument("--target", type=str, default="agitator.speed.setpoint", help="Control target")
    args = parser.parse_args()
    build_package(
        steps=args.steps,
        cycles=args.cycles,
        period_s=args.period_s,
        amplitude=args.amplitude,
        offset=args.offset,
        target=args.target,
    )
