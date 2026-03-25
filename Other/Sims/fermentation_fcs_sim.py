from __future__ import annotations

import argparse
import collections
import math
import os
import random
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover
    tk = None
    ttk = None
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover
    Figure = None
    FigureCanvasTkAgg = None


# Optional CAN support.
CAN_AVAILABLE = False
try:
    import can  # type: ignore
    CAN_AVAILABLE = True
except Exception:
    can = None

BREWTOOLS_AVAILABLE = False
try:
    THIS_DIR = Path(__file__).resolve().parent
    BT_DIR = THIS_DIR / "Sims_unz" / "Sims"
    if BT_DIR.exists() and str(BT_DIR) not in sys.path:
        sys.path.insert(0, str(BT_DIR))
    from brewtools_can import CanFrame, BrewtoolsCanId, Priority, NodeType, MsgType
    from brewtools_can.bodies import FloatBody, RawBody
    from brewtools_can import register_default_bodies, register_default_domain_handlers
    BREWTOOLS_AVAILABLE = True
except Exception:
    CanFrame = BrewtoolsCanId = Priority = NodeType = MsgType = FloatBody = RawBody = None
    register_default_bodies = register_default_domain_handlers = None


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def sg_to_plato(sg: float) -> float:
    return -616.868 + 1111.14 * sg - 630.272 * sg * sg + 135.997 * sg * sg * sg


@dataclass
class PlantState:
    t_real_s: float = 0.0
    cycle_pos: float = 0.0
    temp_c: float = 20.0
    pressure_bar_g: float = 0.03
    gravity_sg: float = 1.055
    agitator_rpm: float = 140.0
    heat_relay: bool = False
    cool_relay: bool = False
    gas_relay: bool = False
    vent_relay: bool = False
    foam_level_m: float = 0.60
    co2_prod_rate: float = 0.0
    gas_inventory: float = 0.0
    temp_request: float = 20.0
    pressure_request: float = 0.05


class FermentationPlant:
    """Fast, intentionally exaggerated fermentation simulator for control testing.

    The dynamics are inspired by the older simulator's key behaviors:
    - temperature responds to heat/cool and fermentation heat
    - pressure responds to CO2 generation, venting, and gas addition
    - gravity falls through the cycle
    - agitation accepts a PWM-like target and ramps toward it
    """

    def __init__(self, cycle_seconds: float = 3600.0, history_seconds: float = 3600.0):
        self.lock = threading.RLock()
        self.state = PlantState()
        self.running = False
        self.cycle_seconds = max(120.0, float(cycle_seconds))
        self.history_seconds = max(120.0, float(history_seconds))
        self.time_scale = 1.0
        self.last_monotonic = time.monotonic()
        self.og = 1.055
        self.fg = 1.010
        self.state.gravity_sg = self.og
        self.state.temp_c = 20.0
        self.state.pressure_bar_g = 0.03
        self.state.temp_request = 20.0
        self.state.pressure_request = 0.05
        self.gas_inventory = 0.02
        self.agitator_target_rpm = 140.0
        self.agitator_max_rpm = 350.0
        self.temp_ambient_c = 19.0
        self.heater_power = 3.2      # exaggerated for fast response
        self.cooler_power = 5.0
        self.temp_loss = 0.12
        self.pressure_leak = 0.015
        self.vent_power = 0.45
        self.gas_power = 0.30
        self.base_ferm_heat = 1.4
        self.base_ferm_pressure = 0.045
        self.foam_base = 0.60
        self.foam_gain = 0.16
        self.noise_temp = 0.015
        self.noise_pressure = 0.0025
        self.noise_gravity = 0.00003
        self.history: Deque[Tuple[float, float, float, float]] = collections.deque()
        self.status_listeners: List = []

    def set_relay(self, name: str, value: bool) -> None:
        with self.lock:
            if name == "heat":
                self.state.heat_relay = bool(value)
            elif name == "cool":
                self.state.cool_relay = bool(value)
            elif name == "gas":
                self.state.gas_relay = bool(value)
            elif name == "vent":
                self.state.vent_relay = bool(value)

    def set_agitator_pwm(self, pwm_pct: float) -> None:
        with self.lock:
            pwm_pct = clamp(float(pwm_pct), 0.0, 100.0)
            self.agitator_target_rpm = self.agitator_max_rpm * pwm_pct / 100.0

    def reset(self) -> None:
        with self.lock:
            self.state = PlantState(
                temp_c=20.0,
                pressure_bar_g=0.03,
                gravity_sg=self.og,
                agitator_rpm=140.0,
                foam_level_m=self.foam_base,
                temp_request=20.0,
                pressure_request=0.05,
            )
            self.gas_inventory = 0.02
            self.agitator_target_rpm = 140.0
            self.history.clear()
            self.last_monotonic = time.monotonic()

    def snapshot(self) -> PlantState:
        with self.lock:
            return PlantState(**self.state.__dict__)

    def _activity(self, x: float) -> float:
        # Bell curve with tail so pressure/temperature keep moving.
        peak = math.exp(-((x - 0.33) / 0.18) ** 2)
        tail = 0.20 + 0.20 * math.sin(2.0 * math.pi * x + 0.3)
        return clamp(0.10 + 0.95 * peak + tail, 0.0, 1.35)

    def step(self, real_dt: float) -> None:
        with self.lock:
            dt = max(0.001, real_dt) * self.time_scale
            st = self.state
            st.t_real_s += real_dt
            st.cycle_pos = (st.t_real_s % self.cycle_seconds) / self.cycle_seconds
            x = st.cycle_pos
            activity = self._activity(x)

            # Gravity target over the one-hour cycle, intentionally fast and smooth.
            gravity_target = self.og - (self.og - self.fg) * (1.0 / (1.0 + math.exp(-8.0 * (x - 0.42))))
            gravity_rate = clamp((gravity_target - st.gravity_sg) * 1.8, -0.0006, 0.0006)
            st.gravity_sg = clamp(st.gravity_sg + gravity_rate * dt, self.fg, self.og)

            # Ambient disturbance so controllers always have something to regulate.
            amb = self.temp_ambient_c + 0.7 * math.sin(2 * math.pi * x * 1.7) + 0.3 * math.sin(2 * math.pi * x * 5.0)
            ferm_heat = self.base_ferm_heat * activity
            heat_term = self.heater_power if st.heat_relay else 0.0
            cool_term = self.cooler_power if st.cool_relay else 0.0
            agitation_coupling = 0.0007 * max(0.0, st.agitator_rpm - 120.0)
            dtemp = (
                ferm_heat
                + heat_term
                - cool_term
                - self.temp_loss * (st.temp_c - amb)
                + 0.16 * math.sin(2 * math.pi * x * 3.0)
                + agitation_coupling
            )
            st.temp_c = clamp(st.temp_c + dtemp * dt / 60.0, 14.0, 32.0)

            # Pressure dynamics: generated CO2, natural leak, vent, gas add.
            ferm_pressure = self.base_ferm_pressure * activity * (1.0 + max(0.0, (21.0 - st.temp_c)) * 0.04)
            self.gas_inventory += ferm_pressure * dt / 15.0
            self.gas_inventory += (self.gas_power * dt / 10.0) if st.gas_relay else 0.0
            self.gas_inventory -= (self.vent_power * dt / 10.0) if st.vent_relay else 0.0
            self.gas_inventory -= self.pressure_leak * max(0.0, self.gas_inventory) * dt / 10.0
            self.gas_inventory += 0.0025 * math.sin(2 * math.pi * x * 2.5) * dt / 5.0
            self.gas_inventory = max(0.0, self.gas_inventory)
            st.pressure_bar_g = clamp(0.018 + self.gas_inventory, 0.0, 1.2)
            st.co2_prod_rate = ferm_pressure

            # Foam tracks activity and venting.
            foam_target = self.foam_base + self.foam_gain * activity - (0.04 if st.vent_relay else 0.0)
            st.foam_level_m += (foam_target - st.foam_level_m) * clamp(dt / 20.0, 0.0, 0.7)

            # Agitator ramp.
            ramp_per_s = 220.0
            error = self.agitator_target_rpm - st.agitator_rpm
            step = clamp(error, -ramp_per_s * real_dt, ramp_per_s * real_dt)
            st.agitator_rpm = clamp(st.agitator_rpm + step, 0.0, self.agitator_max_rpm)

            # Keep target hints on screen.
            st.temp_request = 20.5 + 0.8 * math.sin(2 * math.pi * x)
            st.pressure_request = 0.09 + 0.04 * math.sin(2 * math.pi * x * 0.7)

            self.history.append((st.t_real_s, st.temp_c, st.pressure_bar_g, st.gravity_sg))
            while self.history and (st.t_real_s - self.history[0][0]) > self.history_seconds:
                self.history.popleft()

    def get_measured_values(self) -> Dict[str, float]:
        with self.lock:
            return {
                "temp_c": self.state.temp_c + random.gauss(0.0, self.noise_temp),
                "pressure_bar_g": self.state.pressure_bar_g + random.gauss(0.0, self.noise_pressure),
                "gravity_sg": self.state.gravity_sg + random.gauss(0.0, self.noise_gravity),
                "agitator_rpm": self.state.agitator_rpm,
                "foam_level_m": self.state.foam_level_m,
            }


class RelaySimulator:
    """Modbus TCP relay board.

    Coil mapping:
      0 heat
      1 cool
      2 gas add
      3 vent
    """

    def __init__(self, plant: FermentationPlant, host: str = "127.0.0.1", port: int = 502, unit_id: int = 1, channel_count: int = 8):
        self.plant = plant
        self.host = host
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.channel_count = int(channel_count)
        self._states: List[bool] = [False] * self.channel_count
        self._lock = threading.RLock()
        self._server_socket: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass

    def get_states(self) -> List[bool]:
        with self._lock:
            return list(self._states)

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(20)
            server.settimeout(0.5)
            self._server_socket = server
            print(f"Relay simulator listening on {self.host}:{self.port} (unit_id={self.unit_id})")
            while not self._stop_event.is_set():
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()

    def _set_coil(self, address: int, value: bool) -> None:
        with self._lock:
            self._states[address] = value
        if address == 0:
            self.plant.set_relay("heat", value)
        elif address == 1:
            self.plant.set_relay("cool", value)
        elif address == 2:
            self.plant.set_relay("gas", value)
        elif address == 3:
            self.plant.set_relay("vent", value)
        print(f"Relay {address + 1} -> {'ON' if value else 'off'}")

    def _handle_client(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        print(f"Modbus client connected: {addr[0]}:{addr[1]}")
        with conn:
            conn.settimeout(2.0)
            while not self._stop_event.is_set():
                try:
                    header = self._recv_exact(conn, 7)
                except (OSError, TimeoutError, ConnectionError):
                    break
                if not header:
                    break
                tx_id, protocol_id, length, unit_id = struct.unpack(">HHHB", header)
                if protocol_id != 0:
                    break
                try:
                    pdu = self._recv_exact(conn, length - 1)
                except (OSError, TimeoutError, ConnectionError):
                    break
                if not pdu:
                    break
                function_code = pdu[0]
                payload = pdu[1:]
                if unit_id != self.unit_id:
                    response_pdu = bytes([function_code | 0x80, 0x0B])
                else:
                    response_pdu = self._process_request(function_code, payload)
                response = struct.pack(">HHHB", tx_id, 0, len(response_pdu) + 1, unit_id) + response_pdu
                try:
                    conn.sendall(response)
                except OSError:
                    break
        print(f"Modbus client disconnected: {addr[0]}:{addr[1]}")

    @staticmethod
    def _recv_exact(conn: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = conn.recv(length - len(data))
            if not chunk:
                raise ConnectionError("Socket closed")
            data.extend(chunk)
        return bytes(data)

    def _process_request(self, function_code: int, payload: bytes) -> bytes:
        try:
            if function_code == 0x01:
                return self._read_coils(payload)
            if function_code == 0x05:
                return self._write_single_coil(payload)
            if function_code == 0x0F:
                return self._write_multiple_coils(payload)
            return bytes([function_code | 0x80, 0x01])
        except ValueError:
            return bytes([function_code | 0x80, 0x02])

    def _read_coils(self, payload: bytes) -> bytes:
        if len(payload) != 4:
            raise ValueError("Bad payload")
        start_address, count = struct.unpack(">HH", payload)
        if count <= 0:
            raise ValueError("Bad count")
        with self._lock:
            if start_address + count > self.channel_count:
                raise ValueError("Address out of range")
            values = self._states[start_address:start_address + count]
        byte_count = (count + 7) // 8
        packed = bytearray(byte_count)
        for i, state in enumerate(values):
            if state:
                packed[i // 8] |= 1 << (i % 8)
        return bytes([0x01, byte_count]) + bytes(packed)

    def _write_single_coil(self, payload: bytes) -> bytes:
        if len(payload) != 4:
            raise ValueError("Bad payload")
        address, raw_value = struct.unpack(">HH", payload)
        if address >= self.channel_count:
            raise ValueError("Address out of range")
        if raw_value not in (0xFF00, 0x0000):
            raise ValueError("Bad value")
        self._set_coil(address, raw_value == 0xFF00)
        return bytes([0x05]) + payload

    def _write_multiple_coils(self, payload: bytes) -> bytes:
        if len(payload) < 5:
            raise ValueError("Bad payload")
        start_address, count, byte_count = struct.unpack(">HHB", payload[:5])
        packed = payload[5:]
        if len(packed) != byte_count or start_address + count > self.channel_count:
            raise ValueError("Bad payload")
        for i in range(count):
            bit = (packed[i // 8] >> (i % 8)) & 0x01
            self._set_coil(start_address + i, bool(bit))
        return bytes([0x0F]) + struct.pack(">HH", start_address, count)


class BrewtoolsCANSimulator:
    def __init__(self, plant: FermentationPlant, interface: str = "virtual", channel: str = "fcs-sim", bitrate: int = 1_000_000, plc_node_id: int = 0, agitator_node_id: int = 0, period_s: float = 0.20):
        self.plant = plant
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.plc_node_id = plc_node_id
        self.agitator_node_id = agitator_node_id
        self.period_s = period_s
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.bus = None
        self.enabled = CAN_AVAILABLE and BREWTOOLS_AVAILABLE

    def start(self) -> None:
        if not self.enabled:
            print("CAN simulator disabled: python-can or brewtools_can not available.")
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                pass

    def _make_float_frame(self, sender_node_type, msg_type, value: float):
        return CanFrame(
            BrewtoolsCanId(Priority.MEDIUM, sender_node_type, NodeType.NODE_TYPE_PLC, self.plc_node_id, msg_type),
            FloatBody(0, float(value)),
        )

    def _make_rpm_frame(self, rpm: float):
        return CanFrame(
            BrewtoolsCanId(Priority.MEDIUM, NodeType.NODE_TYPE_AGITATOR_ACTUATOR, NodeType.NODE_TYPE_PLC, self.agitator_node_id, MsgType.MSG_TYPE_RPM),
            FloatBody(0, float(rpm)),
        )

    @staticmethod
    def _decode_pwm_percent(raw: bytes) -> Optional[float]:
        if len(raw) >= 4:
            return float(int.from_bytes(raw[:4], byteorder="big", signed=False))
        if len(raw) >= 1:
            return float(raw[0])
        return None

    def _run(self) -> None:
        register_default_bodies()
        register_default_domain_handlers()
        bus_kwargs = dict(interface=self.interface, channel=self.channel)
        if self.interface != "virtual":
            bus_kwargs["bitrate"] = self.bitrate
        try:
            self.bus = can.Bus(**bus_kwargs)
        except Exception as exc:
            print(f"Failed to open CAN bus: {exc}")
            return
        print(f"CAN simulator running on interface={self.interface}, channel={self.channel}")
        next_tx = time.monotonic()
        while not self.stop_event.is_set():
            now = time.monotonic()
            # Receive agitator PWM requests.
            try:
                rx = self.bus.recv(timeout=0.0)
            except Exception:
                rx = None
            while rx is not None:
                try:
                    frame = CanFrame.from_can(rx.arbitration_id, bytes(rx.data))
                    can_id = frame.can_id
                    if (
                        int(can_id.sender_node_type) == int(NodeType.NODE_TYPE_PLC)
                        and int(can_id.receiver_node_type) == int(NodeType.NODE_TYPE_AGITATOR_ACTUATOR)
                        and int(can_id.msg_type) == int(MsgType.MSG_TYPE_PWM)
                        and int(can_id.secondary_node_id) == int(self.agitator_node_id)
                        and isinstance(frame.body, RawBody)
                    ):
                        pwm = self._decode_pwm_percent(frame.body.raw)
                        if pwm is not None:
                            self.plant.set_agitator_pwm(pwm)
                            print(f"RX agitator PWM -> {pwm:.1f}%")
                except Exception:
                    pass
                try:
                    rx = self.bus.recv(timeout=0.0)
                except Exception:
                    rx = None

            if now >= next_tx:
                meas = self.plant.get_measured_values()
                frames = [
                    self._make_float_frame(NodeType.NODE_TYPE_DENSITY_SENSOR, MsgType.MSG_TYPE_TEMPERATURE, meas["temp_c"]),
                    self._make_float_frame(NodeType.NODE_TYPE_PRESSURE_SENSOR, MsgType.MSG_TYPE_PRESSURE, meas["pressure_bar_g"]),
                    self._make_float_frame(NodeType.NODE_TYPE_DENSITY_SENSOR, MsgType.MSG_TYPE_DENSITY, meas["gravity_sg"]),
                    self._make_rpm_frame(meas["agitator_rpm"]),
                ]
                for frame in frames:
                    try:
                        arb_id, data = frame.to_can()
                        msg = can.Message(arbitration_id=int(arb_id), data=data, is_extended_id=True)
                        self.bus.send(msg)
                    except Exception as exc:
                        print(f"CAN TX error: {exc}")
                        break
                next_tx = now + self.period_s
            time.sleep(0.01)


class SimulatorApp:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.plant = FermentationPlant(cycle_seconds=args.cycle_seconds, history_seconds=max(args.cycle_seconds, 900.0))
        self.relay = RelaySimulator(self.plant, host=args.modbus_host, port=args.modbus_port, unit_id=args.modbus_unit, channel_count=max(8, args.modbus_channels))
        self.can_sim = BrewtoolsCANSimulator(
            self.plant,
            interface=args.can_interface,
            channel=args.can_channel,
            bitrate=args.can_bitrate,
            plc_node_id=args.plc_node_id,
            agitator_node_id=args.agitator_node_id,
            period_s=args.can_period,
        )
        self.stop_event = threading.Event()
        self.plant_thread = threading.Thread(target=self._run_plant, daemon=True)
        self.root = None
        self.figure = None
        self.canvas = None
        self.ax_temp = None
        self.ax_pressure = None
        self.ax_gravity = None
        self.status_labels: Dict[str, tk.StringVar] = {}
        self.relay_vars: Dict[str, tk.StringVar] = {}
        self.info_var = None

    def start(self) -> None:
        self.relay.start()
        self.can_sim.start()
        self.plant_thread.start()
        if self.args.no_gui:
            self._run_console()
        else:
            self._run_gui()

    def _run_plant(self) -> None:
        last = time.monotonic()
        while not self.stop_event.is_set():
            now = time.monotonic()
            self.plant.step(now - last)
            last = now
            time.sleep(0.05)

    def _run_console(self) -> None:
        print("Running without GUI. Press Ctrl+C to stop.")
        try:
            while True:
                st = self.plant.snapshot()
                print(
                    f"t={st.t_real_s:6.1f}s temp={st.temp_c:5.2f}C pressure={st.pressure_bar_g:5.3f}barg "
                    f"gravity={st.gravity_sg:.4f} rpm={st.agitator_rpm:5.1f} "
                    f"relays H={int(st.heat_relay)} C={int(st.cool_relay)} G={int(st.gas_relay)} V={int(st.vent_relay)}"
                )
                time.sleep(1.0)
        except KeyboardInterrupt:
            self.shutdown()

    def _run_gui(self) -> None:
        if tk is None or Figure is None or FigureCanvasTkAgg is None:
            raise RuntimeError("GUI dependencies not available. Use --no-gui.")
        self.root = tk.Tk()
        self.root.title("Fermentation FCS Simulator")
        self.root.geometry("1200x860")
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(top)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(top, width=310)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        self.figure = Figure(figsize=(9, 8), dpi=100)
        self.ax_temp = self.figure.add_subplot(311)
        self.ax_pressure = self.figure.add_subplot(312)
        self.ax_gravity = self.figure.add_subplot(313)
        self.figure.tight_layout(pad=2.0)
        self.canvas = FigureCanvasTkAgg(self.figure, master=left)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        info_frame = ttk.LabelFrame(right, text="Live values", padding=10)
        info_frame.pack(fill=tk.X, pady=5)
        for key in ["temp", "pressure", "gravity", "agitator", "cycle"]:
            var = tk.StringVar(value=f"{key}: --")
            self.status_labels[key] = var
            ttk.Label(info_frame, textvariable=var, anchor="w").pack(fill=tk.X, pady=2)

        relay_frame = ttk.LabelFrame(right, text="Relay mapping", padding=10)
        relay_frame.pack(fill=tk.X, pady=5)
        mapping = [
            ("heat", "Relay 1: Heater"),
            ("cool", "Relay 2: Cooling"),
            ("gas", "Relay 3: Gas add"),
            ("vent", "Relay 4: Vent"),
        ]
        for key, title in mapping:
            var = tk.StringVar(value=f"{title}: off")
            self.relay_vars[key] = var
            ttk.Label(relay_frame, textvariable=var, anchor="w").pack(fill=tk.X, pady=2)

        manual_frame = ttk.LabelFrame(right, text="Manual override", padding=10)
        manual_frame.pack(fill=tk.X, pady=5)
        for key, title in mapping:
            ttk.Button(manual_frame, text=f"Toggle {title}", command=lambda k=key: self._toggle_relay(k)).pack(fill=tk.X, pady=2)
        ttk.Button(manual_frame, text="Reset simulation", command=self.plant.reset).pack(fill=tk.X, pady=8)
        ttk.Button(manual_frame, text="Agitator 0%", command=lambda: self.plant.set_agitator_pwm(0)).pack(fill=tk.X, pady=2)
        ttk.Button(manual_frame, text="Agitator 40%", command=lambda: self.plant.set_agitator_pwm(40)).pack(fill=tk.X, pady=2)
        ttk.Button(manual_frame, text="Agitator 75%", command=lambda: self.plant.set_agitator_pwm(75)).pack(fill=tk.X, pady=2)

        comms_frame = ttk.LabelFrame(right, text="Interfaces", padding=10)
        comms_frame.pack(fill=tk.X, pady=5)
        can_status = "enabled" if self.can_sim.enabled else "disabled"
        self.info_var = tk.StringVar(
            value=(
                f"Modbus TCP: {self.args.modbus_host}:{self.args.modbus_port}\n"
                f"Unit ID: {self.args.modbus_unit}\n"
                f"CAN: {can_status} ({self.args.can_interface}:{self.args.can_channel})\n"
                f"Cycle length: {int(self.args.cycle_seconds)} s"
            )
        )
        ttk.Label(comms_frame, textvariable=self.info_var, justify=tk.LEFT).pack(fill=tk.X)

        self._refresh_gui()
        self.root.mainloop()

    def _toggle_relay(self, key: str) -> None:
        st = self.plant.snapshot()
        current = {
            "heat": st.heat_relay,
            "cool": st.cool_relay,
            "gas": st.gas_relay,
            "vent": st.vent_relay,
        }[key]
        self.plant.set_relay(key, not current)
        mapping = {"heat": 0, "cool": 1, "gas": 2, "vent": 3}
        self.relay._set_coil(mapping[key], not current)

    def _refresh_gui(self) -> None:
        if self.root is None:
            return
        st = self.plant.snapshot()
        self.status_labels["temp"].set(f"Temperature: {st.temp_c:0.2f} °C")
        self.status_labels["pressure"].set(f"Pressure: {st.pressure_bar_g:0.3f} bar(g)")
        self.status_labels["gravity"].set(f"Gravity: {st.gravity_sg:0.4f} SG")
        self.status_labels["agitator"].set(f"Agitator: {st.agitator_rpm:0.1f} RPM")
        self.status_labels["cycle"].set(f"Cycle position: {100.0 * st.cycle_pos:0.1f}%")
        self.relay_vars["heat"].set(f"Relay 1: Heater: {'ON' if st.heat_relay else 'off'}")
        self.relay_vars["cool"].set(f"Relay 2: Cooling: {'ON' if st.cool_relay else 'off'}")
        self.relay_vars["gas"].set(f"Relay 3: Gas add: {'ON' if st.gas_relay else 'off'}")
        self.relay_vars["vent"].set(f"Relay 4: Vent: {'ON' if st.vent_relay else 'off'}")

        hist = list(self.plant.history)
        if hist:
            t0 = hist[0][0]
            xs = [h[0] - t0 for h in hist]
            temps = [h[1] for h in hist]
            press = [h[2] for h in hist]
            grav = [h[3] for h in hist]
            for ax in [self.ax_temp, self.ax_pressure, self.ax_gravity]:
                ax.clear()
                ax.grid(True, alpha=0.3)
            self.ax_temp.plot(xs, temps)
            self.ax_temp.set_ylabel("Temp [°C]")
            self.ax_temp.set_title("Temperature")
            self.ax_pressure.plot(xs, press)
            self.ax_pressure.set_ylabel("Pressure [bar(g)]")
            self.ax_pressure.set_title("Pressure")
            self.ax_gravity.plot(xs, grav)
            self.ax_gravity.set_ylabel("Gravity [SG]")
            self.ax_gravity.set_xlabel("Elapsed time [s]")
            self.ax_gravity.set_title("Gravity")
            self.figure.tight_layout(pad=2.0)
            self.canvas.draw_idle()

        self.root.after(250, self._refresh_gui)

    def shutdown(self) -> None:
        self.stop_event.set()
        self.can_sim.stop()
        self.relay.stop()
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fast fermentation simulator with Modbus relays, optional Brewtools CAN, and live plots.")
    parser.add_argument("--cycle-seconds", type=float, default=3600.0, help="Length of one simulated fermentation cycle in real seconds. Default: 3600")
    parser.add_argument("--no-gui", action="store_true", help="Run headless and print live values to the console")
    parser.add_argument("--modbus-host", default="127.0.0.1", help="Modbus TCP listen host")
    parser.add_argument("--modbus-port", type=int, default=502, help="Modbus TCP listen port. Matches Z_relay_simulator.py default")
    parser.add_argument("--modbus-unit", type=int, default=1, help="Modbus unit id")
    parser.add_argument("--modbus-channels", type=int, default=8, help="Number of Modbus relay channels")
    parser.add_argument("--can-interface", default="kvaser", help="python-can interface. Matches Z_Brewtools_Simulator.py default")
    parser.add_argument("--can-channel", default="2", help="CAN channel name or number. Matches Z_Brewtools_Simulator.py default")
    parser.add_argument("--can-bitrate", type=int, default=1_000_000, help="CAN bitrate")
    parser.add_argument("--can-period", type=float, default=0.20, help="Sensor transmit period in seconds")
    parser.add_argument("--plc-node-id", type=int, default=0, help="PLC node id in Brewtools CAN frames")
    parser.add_argument("--agitator-node-id", type=int, default=0, help="Agitator node id in Brewtools CAN frames")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    app = SimulatorApp(args)
    try:
        app.start()
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()
