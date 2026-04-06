from __future__ import annotations

import argparse
import statistics
import threading
import time

from Services.parameterDB.parameterdb_core.client import SignalClient
from Services.parameterDB.sourceDefs.modbus_relay.service import RelayBoard


class _DummyPlant:
    def set_relay(self, name: str, value: bool) -> None:
        return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure ParameterDB-to-relay actuation latency.")
    parser.add_argument("--parameter", default="relay.ch1", help="ParameterDB relay command parameter to toggle")
    parser.add_argument("--status-parameter", default="", help="Optional connected-status parameter; default derives from parameter prefix")
    parser.add_argument("--host", default="127.0.0.1", help="Relay board host")
    parser.add_argument("--port", type=int, default=4196, help="Relay board Modbus TCP port")
    parser.add_argument("--unit-id", type=int, default=1, help="Modbus unit id")
    parser.add_argument("--channels", type=int, default=8, help="Relay board channel count")
    parser.add_argument("--channel", type=int, default=1, help="Relay channel number to observe")
    parser.add_argument("--trials", type=int, default=5, help="Number of ON/OFF timing trials")
    parser.add_argument("--timeout", type=float, default=5.0, help="Timeout waiting for source connect or coil changes")
    parser.add_argument("--poll-sleep", type=float, default=0.0005, help="Sleep between board polls in seconds")
    parser.add_argument("--spawn-sim", action="store_true", help="Start a local Modbus relay simulator in-process before measuring")
    return parser


def _derive_status_parameter(parameter_name: str, explicit: str) -> str:
    if explicit:
        return explicit
    prefix, _, _tail = parameter_name.rpartition(".")
    if not prefix:
        raise ValueError(f"Cannot derive status parameter from {parameter_name!r}")
    return f"{prefix}.connected"


def _status_family(status_parameter: str) -> tuple[str, str, str]:
    prefix, _, _tail = status_parameter.rpartition(".")
    if not prefix:
        return status_parameter, status_parameter, status_parameter
    return (
        f"{prefix}.connected",
        f"{prefix}.last_error",
        f"{prefix}.last_sync",
    )


def _wait_for_value(client: SignalClient, name: str, expected: object, timeout_s: float) -> object:
    start = time.perf_counter()
    last = None
    while True:
        last = client.get_value(name, None)
        if last == expected:
            return last
        if (time.perf_counter() - start) > timeout_s:
            raise TimeoutError(f"Timed out waiting for {name}={expected!r}; last={last!r}")
        time.sleep(0.05)


def _wait_for_channel(board: RelayBoard, channel: int, target: bool, timeout_s: float, poll_sleep_s: float) -> tuple[float, int]:
    start = time.perf_counter()
    polls = 0
    while True:
        polls += 1
        actual = bool(board.all_states()[channel])
        if actual == target:
            return (time.perf_counter() - start) * 1000.0, polls
        if (time.perf_counter() - start) > timeout_s:
            raise TimeoutError(f"Timed out waiting for relay channel {channel}={target}; last={actual}")
        time.sleep(poll_sleep_s)


def main() -> int:
    args = _build_parser().parse_args()
    client = SignalClient()
    board = RelayBoard(args.host, port=args.port, channel_count=args.channels, unit_id=args.unit_id, timeout=0.75)
    status_parameter = _derive_status_parameter(args.parameter, args.status_parameter)
    connected_param, error_param, sync_param = _status_family(status_parameter)

    simulator = None
    simulator_thread = None
    if args.spawn_sim:
        from Other.Sims.fermentation_fcs_sim import RelaySimulator

        simulator = RelaySimulator(_DummyPlant(), host=args.host, port=args.port, unit_id=args.unit_id, channel_count=max(args.channels, 8))
        simulator_thread = threading.Thread(target=simulator.serve_forever, daemon=True, name="relay-latency-sim")
        simulator_thread.start()

    try:
        print(f"status parameter: {status_parameter}")
        print(f"command parameter: {args.parameter}")
        print(f"relay target: {args.host}:{args.port} channel {args.channel}")
        _wait_for_value(client, status_parameter, True, args.timeout)
        print(f"{status_parameter} = {client.get_value(status_parameter, None)!r}")

        client.set_value(args.parameter, False)
        settle_ms, settle_polls = _wait_for_channel(board, args.channel, False, args.timeout, args.poll_sleep)
        print(f"settle OFF: {settle_ms:.3f} ms ({settle_polls} polls)")

        on_results: list[float] = []
        off_results: list[float] = []
        failures = 0

        for trial in range(1, args.trials + 1):
            try:
                started = time.perf_counter()
                client.set_value(args.parameter, True)
                on_ms, on_polls = _wait_for_channel(board, args.channel, True, args.timeout, args.poll_sleep)
                on_total_ms = (time.perf_counter() - started) * 1000.0
                on_results.append(on_ms)
                print(f"trial {trial} ON : observed={on_ms:.3f} ms total={on_total_ms:.3f} ms polls={on_polls}")

                started = time.perf_counter()
                client.set_value(args.parameter, False)
                off_ms, off_polls = _wait_for_channel(board, args.channel, False, args.timeout, args.poll_sleep)
                off_total_ms = (time.perf_counter() - started) * 1000.0
                off_results.append(off_ms)
                print(f"trial {trial} OFF: observed={off_ms:.3f} ms total={off_total_ms:.3f} ms polls={off_polls}")
            except TimeoutError as exc:
                failures += 1
                print(f"trial {trial} FAILED: {exc}")
                print(f"  {args.parameter} = {client.get_value(args.parameter, None)!r}")
                print(f"  {connected_param} = {client.get_value(connected_param, None)!r}")
                print(f"  {error_param} = {client.get_value(error_param, None)!r}")
                print(f"  {sync_param} = {client.get_value(sync_param, None)!r}")
                break

        print("summary")
        print(f"  completed_on_trials = {len(on_results)}")
        print(f"  completed_off_trials = {len(off_results)}")
        print(f"  failures = {failures}")
        if on_results:
            print(f"  ON  min/avg/max = {min(on_results):.3f} / {statistics.mean(on_results):.3f} / {max(on_results):.3f} ms")
        if off_results:
            print(f"  OFF min/avg/max = {min(off_results):.3f} / {statistics.mean(off_results):.3f} / {max(off_results):.3f} ms")
        return 0
    finally:
        try:
            client.set_value(args.parameter, False)
        except Exception:
            pass
        try:
            board.close()
        except Exception:
            pass
        if simulator is not None:
            stop = getattr(simulator, "stop", None)
            shutdown = getattr(simulator, "shutdown", None)
            if callable(stop):
                stop()
            elif callable(shutdown):
                shutdown()
        if simulator_thread is not None:
            simulator_thread.join(timeout=1.0)


if __name__ == "__main__":
    raise SystemExit(main())