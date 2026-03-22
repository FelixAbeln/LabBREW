from brewtools_can import CanFrame, BrewtoolsCanId, Priority, NodeType, MsgType
from brewtools_can.bodies import FloatBody, RawBody

from brewtools_can import (
    register_default_bodies,
    register_default_domain_handlers,
)

import argparse
import can
import time


AGITATOR_NODE_TYPE = NodeType.NODE_TYPE_AGITATOR_ACTUATOR


def make_examples(agitator_nodes: list[int], default_rpm: float) -> list[CanFrame]:
    frames = []

    # Temperatures
    frames.append(CanFrame(
        BrewtoolsCanId(Priority.MEDIUM, NodeType.NODE_TYPE_DENSITY_SENSOR,
                       NodeType.NODE_TYPE_PLC, 0, MsgType.MSG_TYPE_TEMPERATURE),
        FloatBody(0, 20.5)
    ))

    # Pressure
    frames.append(CanFrame(
        BrewtoolsCanId(Priority.MEDIUM, NodeType.NODE_TYPE_PRESSURE_SENSOR,
                       NodeType.NODE_TYPE_PLC, 0, MsgType.MSG_TYPE_PRESSURE),
        FloatBody(0, 1.25)
    ))

    # Density
    frames.append(CanFrame(
        BrewtoolsCanId(Priority.MEDIUM, NodeType.NODE_TYPE_DENSITY_SENSOR,
                       NodeType.NODE_TYPE_PLC, 0, MsgType.MSG_TYPE_DENSITY),
        FloatBody(0, 1.0442)
    ))

    # Agitator RPM example(s)
    for node_id in agitator_nodes:
        frames.append(CanFrame(
            BrewtoolsCanId(Priority.MEDIUM, AGITATOR_NODE_TYPE,
                           NodeType.NODE_TYPE_PLC, node_id, MsgType.MSG_TYPE_RPM),
            FloatBody(0, default_rpm)
        ))

    return frames


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def decode_pwm_percent(raw: bytes) -> float | None:
    """Decode the agitator PWM command payload.

    The Brewtools docs show PWM being sent as an unsigned integer 0-100.
    To stay compatible with slightly different senders, also accept a single byte.
    """
    if len(raw) >= 4:
        return float(int.from_bytes(raw[:4], byteorder="big", signed=False))
    if len(raw) >= 1:
        return float(raw[0])
    return None


def make_rpm_frame(node_id: int, rpm: float) -> CanFrame:
    return CanFrame(
        BrewtoolsCanId(Priority.MEDIUM, AGITATOR_NODE_TYPE,
                       NodeType.NODE_TYPE_PLC, node_id, MsgType.MSG_TYPE_RPM),
        FloatBody(0, rpm)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Cycle Brewtools example CAN frames (Kvaser via python-can), with optional agitator simulation."
    )
    parser.add_argument("--channel", type=int, default=2, help="Kvaser channel number (default: 2)")
    parser.add_argument("--bitrate", type=int, default=1000000, help="CAN bitrate (default: 1000000)")
    parser.add_argument("--period-ms", type=int, default=100, help="Delay between frames (default: 100ms)")
    parser.add_argument("--once", action="store_true", help="Send the example frames once and exit")
    parser.add_argument(
        "--agitator-nodes",
        default="0",
        help="Comma-separated agitator node IDs to simulate (default: 0)",
    )
    parser.add_argument(
        "--agitator-default-rpm",
        type=float,
        default=120.0,
        help="Initial RPM for agitator example frames before any PWM is received (default: 120.0)",
    )
    parser.add_argument(
        "--agitator-max-rpm",
        type=float,
        default=300.0,
        help="RPM produced at 100%% PWM (default: 300.0)",
    )
    parser.add_argument(
        "--agitator-ramp-rpm-per-sec",
        type=float,
        default=600.0,
        help="How fast the simulated RPM ramps toward its target (default: 600 RPM/s)",
    )
    args = parser.parse_args()

    register_default_bodies()
    register_default_domain_handlers()

    agitator_nodes = [int(part.strip()) for part in args.agitator_nodes.split(",") if part.strip() != ""]
    if not agitator_nodes:
        agitator_nodes = [0]

    frames = make_examples(agitator_nodes, args.agitator_default_rpm)

    agitator_state = {
        node_id: {
            "pwm": clamp((args.agitator_default_rpm / args.agitator_max_rpm) * 100.0 if args.agitator_max_rpm > 0 else 0.0, 0.0, 100.0),
            "rpm": float(args.agitator_default_rpm),
            "target_rpm": float(args.agitator_default_rpm),
        }
        for node_id in agitator_nodes
    }

    bus = can.Bus(interface="kvaser",
                  channel=args.channel,
                  bitrate=args.bitrate,
                  receive_own_messages=False,
                  seperate_handle=True)

    last_step = time.monotonic()
    last_agitator_tx = 0.0

    try:
        idx = 0
        print(
            f"TX: {len(frames)} base frames on kvaser:{args.channel} @ {args.bitrate}bps, "
            f"period={args.period_ms}ms; agitator nodes={agitator_nodes}"
        )
        while True:
            now = time.monotonic()
            dt = max(0.0, now - last_step)
            last_step = now

            # Receive commands to simulated agitator(s)
            rx = bus.recv(timeout=0.0)
            while rx is not None:
                try:
                    frame = CanFrame.from_can(rx.arbitration_id, bytes(rx.data))
                    can_id = frame.can_id
                    if (
                        int(can_id.sender_node_type) == int(NodeType.NODE_TYPE_PLC)
                        and int(can_id.receiver_node_type) == int(AGITATOR_NODE_TYPE)
                        and int(can_id.msg_type) == int(MsgType.MSG_TYPE_PWM)
                        and int(can_id.secondary_node_id) in agitator_state
                        and isinstance(frame.body, RawBody)
                    ):
                        pwm = decode_pwm_percent(frame.body.raw)
                        if pwm is not None:
                            pwm = clamp(pwm, 0.0, 100.0)
                            state = agitator_state[int(can_id.secondary_node_id)]
                            state["pwm"] = pwm
                            state["target_rpm"] = args.agitator_max_rpm * (pwm / 100.0)
                            print(
                                f"RX PWM: agitator node {can_id.secondary_node_id} <- {pwm:.1f}% "
                                f"target={state['target_rpm']:.1f} RPM"
                            )
                except Exception as exc:
                    print(f"Ignored RX frame: {exc}")
                rx = bus.recv(timeout=0.0)

            # Keep agitator RPM moving smoothly toward target
            max_step = args.agitator_ramp_rpm_per_sec * dt
            for state in agitator_state.values():
                error = state["target_rpm"] - state["rpm"]
                if abs(error) <= max_step:
                    state["rpm"] = state["target_rpm"]
                elif error > 0:
                    state["rpm"] += max_step
                else:
                    state["rpm"] -= max_step

            # Send the original example frames the way the script already does
            frame = frames[idx]
            arb_id, data = frame.to_can()
            msg = can.Message(arbitration_id=int(arb_id), data=data, is_extended_id=True)
            bus.send(msg)
            print(msg)

            idx += 1
            if idx >= len(frames):
                if args.once:
                    break
                idx = 0

            # Also continuously send current simulated agitator RPM values
            if now - last_agitator_tx >= (args.period_ms / 1000.0):
                for node_id, state in agitator_state.items():
                    rpm_frame = make_rpm_frame(node_id, state["rpm"])
                    arb_id, data = rpm_frame.to_can()
                    rpm_msg = can.Message(arbitration_id=int(arb_id), data=data, is_extended_id=True)
                    bus.send(rpm_msg)
                    print(f"AGITATOR RPM node {node_id}: {state['rpm']:.1f}")
                last_agitator_tx = now

            time.sleep(args.period_ms / 1000.0)

    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
