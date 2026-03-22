#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None


DEFAULT_PREFIX_ROOT = "loadtest"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load-test scan cycle time across parameter counts and plugin mixes.")
    p.add_argument("--repo-root", default=".", help="Repo root containing parameterdb_core")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--kinds",
        default="static,pid,deadband,mixed",
        help="Comma-separated kinds to test: static,pid,deadband,mixed",
    )
    p.add_argument(
        "--counts",
        default="0,50,100,200,500,1000",
        help="Comma-separated target total parameter counts",
    )
    p.add_argument("--settle-s", type=float, default=1.0, help="Seconds to wait after each load change")
    p.add_argument("--sample-s", type=float, default=2.0, help="Seconds to sample stats for each point")
    p.add_argument("--poll-s", type=float, default=0.05, help="Polling interval while sampling")
    p.add_argument("--output-dir", default="load_test_results")
    p.add_argument(
        "--prefix",
        default=None,
        help=(
            "Optional fixed prefix root for temporary parameters. The script will delete existing parameters "
            "whose names start with '<prefix>.' before creating new ones."
        ),
    )
    return p.parse_args()


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return math.nan
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


@dataclass
class SampleSummary:
    observed_cycles: int
    min_ms: float
    avg_ms: float
    p95_ms: float
    max_ms: float


class LoadBuilder:
    def __init__(self, client, prefix: str) -> None:
        self.client = client
        self.prefix = prefix
        self.created: list[str] = []

    def _name(self, suffix: str) -> str:
        return f"{self.prefix}.{suffix}"

    def create(self, name: str, parameter_type: str, *, value=None, config=None, metadata=None) -> None:
        self.client.create_parameter(name, parameter_type, value=value, config=config or {}, metadata=metadata or {})
        self.created.append(name)

    def clear(self) -> None:
        for name in reversed(self.created):
            try:
                self.client.delete_parameter(name)
            except Exception:
                pass
        self.created.clear()

    def build_static(self, target_count: int) -> int:
        for i in range(target_count):
            self.create(self._name(f"static_{i:05d}"), "static", value=0)
        return len(self.created)

    def build_pid(self, target_count: int) -> int:
        controllers = max(0, target_count // 3)
        for i in range(controllers):
            pv = self._name(f"pid_{i:05d}.pv")
            sp = self._name(f"pid_{i:05d}.sp")
            out = self._name(f"pid_{i:05d}.out")
            self.create(pv, "static", value=0.0)
            self.create(sp, "static", value=1.0)
            self.create(
                out,
                "pid",
                value=0.0,
                config={
                    "pv": pv,
                    "sp": sp,
                    "kp": 1.0,
                    "ki": 0.0,
                    "kd": 0.0,
                    "bias": 0.0,
                    "out_min": 0.0,
                    "out_max": 100.0,
                    "enable_param": "",
                    "mode_param": "",
                    "manual_out_param": "",
                    "manual_out": 0.0,
                },
            )
        return len(self.created)

    def build_deadband(self, target_count: int) -> int:
        controllers = max(0, target_count // 3)
        for i in range(controllers):
            pv = self._name(f"deadband_{i:05d}.pv")
            sp = self._name(f"deadband_{i:05d}.sp")
            out = self._name(f"deadband_{i:05d}.out")
            self.create(pv, "static", value=0.0)
            self.create(sp, "static", value=1.0)
            self.create(
                out,
                "deadband",
                value=False,
                config={
                    "pv": pv,
                    "sp": sp,
                    "direction": "above" if i % 2 else "below",
                    "on_offset": 1.0,
                    "off_offset": 0.5,
                    "enable_param": "",
                },
            )
        return len(self.created)

    def build_mixed(self, target_count: int) -> int:
        static_target = max(0, round(target_count * 0.50))
        pid_param_target = max(0, round(target_count * 0.25))
        deadband_param_target = max(0, target_count - static_target - pid_param_target)

        pid_controllers = pid_param_target // 3
        deadband_controllers = deadband_param_target // 3
        static_count = max(0, target_count - (pid_controllers * 3 + deadband_controllers * 3))

        self.build_static(static_count)

        for i in range(pid_controllers):
            pv = self._name(f"mix_pid_{i:05d}.pv")
            sp = self._name(f"mix_pid_{i:05d}.sp")
            out = self._name(f"mix_pid_{i:05d}.out")
            self.create(pv, "static", value=float(i % 10))
            self.create(sp, "static", value=float((i % 10) + 1))
            self.create(
                out,
                "pid",
                value=0.0,
                config={
                    "pv": pv,
                    "sp": sp,
                    "kp": 1.0,
                    "ki": 0.05,
                    "kd": 0.0,
                    "bias": 0.0,
                    "out_min": 0.0,
                    "out_max": 100.0,
                    "enable_param": "",
                    "mode_param": "",
                    "manual_out_param": "",
                    "manual_out": 0.0,
                },
            )

        for i in range(deadband_controllers):
            pv = self._name(f"mix_deadband_{i:05d}.pv")
            sp = self._name(f"mix_deadband_{i:05d}.sp")
            out = self._name(f"mix_deadband_{i:05d}.out")
            self.create(pv, "static", value=float(i % 10))
            self.create(sp, "static", value=5.0)
            self.create(
                out,
                "deadband",
                value=False,
                config={
                    "pv": pv,
                    "sp": sp,
                    "direction": "above" if i % 2 else "below",
                    "on_offset": 2.0,
                    "off_offset": 1.0,
                    "enable_param": "",
                },
            )
        return len(self.created)


def wait_for_new_cycles(client, duration_s: float, poll_s: float) -> SampleSummary:
    deadline = time.time() + duration_s
    samples_ms: list[float] = []
    last_cycle = None
    while time.time() < deadline:
        stats = client.stats()
        cycle = int(stats.get("cycle_count", 0) or 0)
        dur_s = float(stats.get("last_scan_duration_s", 0.0) or 0.0)
        if cycle != last_cycle and cycle > 0:
            samples_ms.append(dur_s * 1000.0)
            last_cycle = cycle
        time.sleep(poll_s)

    if not samples_ms:
        return SampleSummary(observed_cycles=0, min_ms=math.nan, avg_ms=math.nan, p95_ms=math.nan, max_ms=math.nan)

    samples_ms.sort()
    return SampleSummary(
        observed_cycles=len(samples_ms),
        min_ms=samples_ms[0],
        avg_ms=statistics.fmean(samples_ms),
        p95_ms=percentile(samples_ms, 0.95),
        max_ms=samples_ms[-1],
    )


def make_builder_fn(kind: str) -> Callable[[LoadBuilder, int], int]:
    mapping = {
        "static": LoadBuilder.build_static,
        "pid": LoadBuilder.build_pid,
        "deadband": LoadBuilder.build_deadband,
        "mixed": LoadBuilder.build_mixed,
    }
    if kind not in mapping:
        raise ValueError(f"Unsupported kind: {kind}")
    return mapping[kind]


def ensure_client(repo_root: str, host: str, port: int):
    repo_root = os.path.abspath(repo_root)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from parameterdb_core.client import SignalClient

    return SignalClient(host=host, port=port)


def cleanup_existing_test_parameters(client, prefix_root: str) -> list[str]:
    marker = f"{prefix_root}."
    try:
        names = client.list_parameters()
    except Exception as exc:
        raise RuntimeError(f"Unable to list parameters for cleanup: {exc}") from exc

    to_delete = sorted((name for name in names if name.startswith(marker)), reverse=True)
    deleted: list[str] = []
    for name in to_delete:
        try:
            client.delete_parameter(name)
            deleted.append(name)
        except Exception:
            # Keep going so one bad parameter does not block cleanup of the rest.
            pass
    return deleted


def run_one_kind(client, kind: str, counts: Iterable[int], settle_s: float, sample_s: float, poll_s: float, output_dir: Path, prefix: str) -> Path:
    builder = LoadBuilder(client, prefix=f"{prefix}.{kind}")
    build_fn = make_builder_fn(kind)
    rows: list[dict[str, object]] = []
    csv_path = output_dir / f"cycle_curve_{kind}.csv"

    try:
        for count in counts:
            builder.clear()
            actual_count = build_fn(builder, int(count))
            time.sleep(settle_s)
            summary = wait_for_new_cycles(client, duration_s=sample_s, poll_s=poll_s)
            row = {
                "kind": kind,
                "target_parameter_count": int(count),
                "actual_parameter_count": actual_count,
                "observed_cycles": summary.observed_cycles,
                "min_cycle_ms": round(summary.min_ms, 6),
                "avg_cycle_ms": round(summary.avg_ms, 6),
                "p95_cycle_ms": round(summary.p95_ms, 6),
                "max_cycle_ms": round(summary.max_ms, 6),
            }
            rows.append(row)
            print(f"[{kind}] target={count:>5} actual={actual_count:>5} avg={summary.avg_ms:8.4f} ms p95={summary.p95_ms:8.4f} ms max={summary.max_ms:8.4f} ms")
    finally:
        builder.clear()

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "kind",
                "target_parameter_count",
                "actual_parameter_count",
                "observed_cycles",
                "min_cycle_ms",
                "avg_cycle_ms",
                "p95_cycle_ms",
                "max_cycle_ms",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def plot_kind(csv_path: Path, output_dir: Path) -> Path | None:
    if plt is None:
        return None
    rows = read_csv_rows(csv_path)
    if not rows:
        return None
    xs = [int(r["actual_parameter_count"]) for r in rows]
    avg = [float(r["avg_cycle_ms"]) for r in rows]
    p95 = [float(r["p95_cycle_ms"]) for r in rows]
    title_kind = rows[0]["kind"]

    fig = plt.figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    ax.plot(xs, avg, marker="o", label="avg")
    ax.plot(xs, p95, marker="s", linestyle="--", label="p95")
    ax.set_xlabel("Actual parameter count")
    ax.set_ylabel("Cycle time (ms)")
    ax.set_title(f"Cycle time vs parameter count ({title_kind})")
    ax.grid(True, alpha=0.3)
    ax.legend()
    out = output_dir / f"cycle_curve_{title_kind}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def plot_combined(csv_paths: list[Path], output_dir: Path) -> Path | None:
    if plt is None or not csv_paths:
        return None
    fig = plt.figure(figsize=(9, 6))
    ax = fig.add_subplot(111)
    for csv_path in csv_paths:
        rows = read_csv_rows(csv_path)
        if not rows:
            continue
        kind = rows[0]["kind"]
        xs = [int(r["actual_parameter_count"]) for r in rows]
        avg = [float(r["avg_cycle_ms"]) for r in rows]
        p95 = [float(r["p95_cycle_ms"]) for r in rows]
        ax.plot(xs, avg, marker="o", label=f"{kind} avg")
        ax.plot(xs, p95, marker=".", linestyle="--", label=f"{kind} p95")
    ax.set_xlabel("Actual parameter count")
    ax.set_ylabel("Cycle time (ms)")
    ax.set_title("Cycle time vs parameter count (all kinds)")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2)
    out = output_dir / "cycle_curve_all_kinds.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def main() -> int:
    args = parse_args()
    counts = [int(part.strip()) for part in args.counts.split(",") if part.strip()]
    kinds = [part.strip() for part in args.kinds.split(",") if part.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = ensure_client(args.repo_root, args.host, args.port)
    print(f"Connected: {client.ping()}")

    prefix_root = args.prefix or DEFAULT_PREFIX_ROOT
    deleted = cleanup_existing_test_parameters(client, prefix_root)
    if deleted:
        print(f"Deleted {len(deleted)} leftover test parameters for prefix root '{prefix_root}'")

    run_id = uuid.uuid4().hex[:8]
    base_prefix = f"{prefix_root}.{run_id}"
    print(f"Using prefix: {base_prefix}")

    csv_paths: list[Path] = []
    for kind in kinds:
        csv_path = run_one_kind(
            client,
            kind=kind,
            counts=counts,
            settle_s=args.settle_s,
            sample_s=args.sample_s,
            poll_s=args.poll_s,
            output_dir=output_dir,
            prefix=base_prefix,
        )
        csv_paths.append(csv_path)
        png_path = plot_kind(csv_path, output_dir)
        print(f"Saved: {csv_path}")
        if png_path is not None:
            print(f"Saved: {png_path}")

    combined_path = plot_combined(csv_paths, output_dir)
    if combined_path is not None:
        print(f"Saved: {combined_path}")
    elif plt is None:
        print("matplotlib not available; skipped PNG output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
