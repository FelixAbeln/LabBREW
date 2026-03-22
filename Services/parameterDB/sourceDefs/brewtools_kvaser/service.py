from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from ...parameterdb_core.client import SupportsSignalRequests
from ...parameterdb_sources.base import DataSourceBase, DataSourceSpec


class BrewtoolsCanSourceError(Exception):
    pass


class BrewtoolsFrameEvent:
    def __init__(self, arbitration_id: int, data: bytes, frame: Any, obj: object | None) -> None:
        self.arbitration_id = arbitration_id
        self.data = data
        self.frame = frame
        self.obj = obj


class BrewtoolsKvaserSource(DataSourceBase):
    source_type = "brewtools_kvaser"
    display_name = "Brewtools CAN (Kvaser)"
    description = "Receives Brewtools CAN measurements over Kvaser and mirrors them into parameters, with optional command outputs."

    def __init__(self, name: str, client: SupportsSignalRequests, *, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, client, config=config)
        self._can = None
        self._bus = None
        self._codec_ready = False
        self._last_pwm_by_node: dict[int, int] = {}
        self._last_density_request_s: dict[int, float] = {}
        self._seen_agitator_nodes: set[int] = set()
        self._seen_density_nodes: set[int] = set()
        self._known_parameters: set[str] = set()

    def _prefix(self) -> str:
        return str(self.config.get("parameter_prefix", self.name)).strip() or self.name

    def _status_param(self, key: str) -> str:
        explicit = self.config.get(f"{key}_param")
        if explicit:
            return str(explicit)
        return f"{self._prefix()}.{key}"

    def _measurement_param(self, kind: str, node_id: int) -> str:
        explicit_map = self.config.get("measurement_params") or {}
        if isinstance(explicit_map, dict):
            kind_map = explicit_map.get(kind)
            if isinstance(kind_map, dict) and str(node_id) in kind_map:
                return str(kind_map[str(node_id)])
        return f"{self._prefix()}.{kind}.{int(node_id)}"

    def _pwm_param(self, node_id: int) -> str:
        explicit_map = self.config.get("agitator_pwm_params") or {}
        if isinstance(explicit_map, dict) and str(node_id) in explicit_map:
            return str(explicit_map[str(node_id)])
        return f"{self._prefix()}.agitator.{int(node_id)}.set_pwm"

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _set_status(self, key: str, value: Any) -> None:
        self.client.set_value(self._status_param(key), value)

    def _set_error(self, message: str) -> None:
        self._set_status("connected", False)
        self._set_status("last_error", str(message))

    def _coerce_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _ensure_parameter_once(
        self,
        name: str,
        parameter_type: str,
        *,
        value: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if name in self._known_parameters:
            return
        self.ensure_parameter(name, parameter_type, value=value, metadata=metadata)
        self._known_parameters.add(name)

    def _connect_bus(self):
        if self._bus is not None:
            return self._bus
        try:
            import can
        except ModuleNotFoundError as exc:
            raise BrewtoolsCanSourceError("python-can is required for the brewtools_kvaser datasource") from exc

        self._ensure_codec_ready()
        channel = int(self.config.get("channel", 0))
        bitrate = int(self.config.get("bitrate", 500000))
        interface = str(self.config.get("interface", "kvaser"))
        self._can = can
        self._bus = can.Bus(interface=interface, channel=channel, bitrate=bitrate)
        self._set_status("connected", True)
        self._set_status("last_error", "")
        return self._bus

    def _disconnect_bus(self) -> None:
        bus = self._bus
        self._bus = None
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:
                pass

    def _ensure_codec_ready(self) -> None:
        if self._codec_ready:
            return
        from .brewtools_can import register_default_bodies, register_default_domain_handlers

        register_default_bodies()
        register_default_domain_handlers()
        self._codec_ready = True

    def _build_pwm_frame(self, *, node_id: int, duty_cycle: float) -> tuple[int, bytes]:
        from .brewtools_can import BrewtoolsCanId, CanFrame, MsgType, NodeType, Priority
        from .brewtools_can import RawBody

        pct = max(0, min(100, int(round(float(duty_cycle)))))
        can_id = BrewtoolsCanId(
            priority=Priority.MEDIUM,
            sender_node_type=NodeType.NODE_TYPE_PLC,
            receiver_node_type=NodeType.NODE_TYPE_AGITATOR_ACTUATOR,
            secondary_node_id=int(node_id),
            msg_type=MsgType.MSG_TYPE_PWM,
        )
        frame = CanFrame(can_id=can_id, body=RawBody(subindex=0, raw=bytes([pct & 0xFF])))
        return frame.to_can()

    def _build_start_measurement_frame(self, *, node_id: int, receiver_node_type: int) -> tuple[int, bytes]:
        from .brewtools_can import BrewtoolsCanId, CanFrame, MsgType, NodeType, Priority
        from .brewtools_can import RawBody

        can_id = BrewtoolsCanId(
            priority=Priority.MEDIUM,
            sender_node_type=NodeType.NODE_TYPE_PLC,
            receiver_node_type=receiver_node_type,
            secondary_node_id=int(node_id),
            msg_type=MsgType.MSG_TYPE_START_MEASUREMENT_CMD,
        )
        frame = CanFrame(can_id=can_id, body=RawBody(subindex=0, raw=b""))
        return frame.to_can()

    def ensure_parameters(self) -> None:
        owned = self.build_owned_metadata(device="brewtools_can")
        self._ensure_parameter_once(self._status_param("connected"), "static", value=False, metadata={**owned, "role": "status"})
        self._ensure_parameter_once(self._status_param("last_error"), "static", value="", metadata={**owned, "role": "status"})
        self._ensure_parameter_once(self._status_param("last_frame_utc"), "static", value="", metadata={**owned, "role": "status"})
        self._ensure_parameter_once(self._status_param("last_can_id"), "static", value="", metadata={**owned, "role": "status"})
        self._ensure_parameter_once(self._status_param("last_msg_type"), "static", value="", metadata={**owned, "role": "status"})
        self._ensure_parameter_once(self._status_param("last_node_id"), "static", value=0, metadata={**owned, "role": "status"})

    def _agitator_nodes(self) -> list[int]:
        raw = self.config.get("agitator_nodes") or []
        result: list[int] = []
        if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, dict)):
            for item in raw:
                try:
                    result.append(int(item))
                except (TypeError, ValueError):
                    continue
        return sorted({node for node in result if node >= 0})

    def _density_nodes(self) -> list[int]:
        raw = self.config.get("density_nodes") or []
        result: list[int] = []
        if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, dict)):
            for item in raw:
                try:
                    result.append(int(item))
                except (TypeError, ValueError):
                    continue
        return sorted({node for node in result if node >= 0})

    def _agitator_allowed(self, node_id: int) -> bool:
        allowed = set(self._agitator_nodes())
        return not allowed or int(node_id) in allowed

    def _density_allowed(self, node_id: int) -> bool:
        allowed = set(self._density_nodes())
        return not allowed or int(node_id) in allowed

    def _ensure_agitator_param(self, node_id: int) -> None:
        node_id = int(node_id)
        owned = self.build_owned_metadata(device="brewtools_can")
        self._ensure_parameter_once(
            self._pwm_param(node_id),
            "static",
            value=float(self.config.get("initial_pwm", 0.0)),
            metadata={**owned, "role": "command", "unit": "%", "node_type": "agitator", "node_id": node_id},
        )

    def _note_agitator_node(self, node_id: int) -> None:
        node_id = int(node_id)
        if node_id < 0 or not self._agitator_allowed(node_id):
            return
        if node_id not in self._seen_agitator_nodes:
            self._seen_agitator_nodes.add(node_id)
            self._ensure_agitator_param(node_id)

    def _note_density_node(self, node_id: int) -> None:
        node_id = int(node_id)
        if node_id < 0 or not self._density_allowed(node_id):
            return
        self._seen_density_nodes.add(node_id)

    def _discover_capabilities(self, frame: Any, obj: object | None) -> None:
        node_id = int(getattr(frame.can_id, "secondary_node_id", -1))
        if obj is None:
            return

        cls_name = obj.__class__.__name__
        try:
            obj_node_id = int(getattr(obj, "node_id", node_id))
        except Exception:
            obj_node_id = node_id

        # Capability discovery is driven by traffic we know always appears.
        # - RPM messages identify agitator nodes.
        # - Temperature messages identify density sensor nodes.
        if cls_name == "RpmMeasurement":
            self._note_agitator_node(obj_node_id)
        elif cls_name == "TemperatureMeasurement":
            self._note_density_node(obj_node_id)

    def _apply_outputs(self, bus: Any) -> None:
        for node_id in sorted(self._seen_agitator_nodes):
            desired = max(0, min(100, int(round(self._coerce_float(self.client.get_value(self._pwm_param(node_id), 0.0), 0.0)))))
            if self._last_pwm_by_node.get(node_id) == desired:
                continue
            arb_id, data = self._build_pwm_frame(node_id=node_id, duty_cycle=desired)
            msg = self._can.Message(arbitration_id=int(arb_id), data=data, is_extended_id=True)
            bus.send(msg)
            self._last_pwm_by_node[node_id] = desired

    def _poll_density_requests(self, bus: Any, now_s: float) -> None:
        interval_s = max(0.1, float(self.config.get("density_request_interval_s", 2.0)))
        try:
            from .brewtools_can import NodeType
            receiver_type = int(NodeType.NODE_TYPE_DENSITY_SENSOR)
        except Exception:
            receiver_type = 4

        for node_id in sorted(self._seen_density_nodes):
            last_sent = self._last_density_request_s.get(node_id, 0.0)
            if now_s - last_sent < interval_s:
                continue
            arb_id, data = self._build_start_measurement_frame(node_id=node_id, receiver_node_type=receiver_type)
            msg = self._can.Message(arbitration_id=int(arb_id), data=data, is_extended_id=True)
            bus.send(msg)
            self._last_density_request_s[node_id] = now_s

    def _publish_measurement(self, kind: str, node_id: int, value: Any, *, unit: str | None = None) -> None:
        param_name = self._measurement_param(kind, node_id)
        self._ensure_parameter_once(
            param_name,
            "static",
            value=value,
            metadata={**self.build_owned_metadata(device="brewtools_can"), "role": "measurement", "kind": kind, "node_id": int(node_id), **({"unit": unit} if unit else {})},
        )
        self.client.set_value(param_name, value)

    def _handle_event(self, event: BrewtoolsFrameEvent) -> None:
        frame = event.frame
        obj = event.obj
        self._set_status("connected", True)
        self._set_status("last_error", "")
        self._set_status("last_frame_utc", self._utc_now())
        self._set_status("last_can_id", hex(int(event.arbitration_id)))
        self._set_status("last_msg_type", int(frame.can_id.msg_type))
        self._set_status("last_node_id", int(frame.can_id.secondary_node_id))
        self._discover_capabilities(frame, obj)

        if obj is None:
            return
        cls_name = obj.__class__.__name__
        if cls_name == "TemperatureMeasurement":
            self._publish_measurement("temperature", int(obj.node_id), float(obj.value_c), unit="C")
        elif cls_name == "PressureMeasurement":
            self._publish_measurement("pressure", int(obj.node_id), float(obj.value_bar), unit="bar")
        elif cls_name == "DensityMeasurement":
            self._publish_measurement("density", int(obj.node_id), float(obj.value))
        elif cls_name == "LevelMeasurement":
            self._publish_measurement("level", int(obj.node_id), float(obj.value))
        elif cls_name == "RpmMeasurement":
            self._publish_measurement("rpm", int(obj.node_id), float(obj.value_rpm), unit="rpm")
        elif cls_name == "MinValue":
            self._publish_measurement("min", int(obj.node_id), float(obj.value))
        elif cls_name == "MaxValue":
            self._publish_measurement("max", int(obj.node_id), float(obj.value))

    def _receive_once(self, bus: Any, timeout_s: float) -> BrewtoolsFrameEvent | None:
        msg = bus.recv(timeout=timeout_s)
        if msg is None or getattr(msg, "is_error_frame", False):
            return None

        from .brewtools_can import CanFrame, DomainFactory

        frame = CanFrame.from_can(int(msg.arbitration_id), bytes(msg.data))
        obj = DomainFactory.build(frame)
        return BrewtoolsFrameEvent(arbitration_id=int(msg.arbitration_id), data=bytes(msg.data), frame=frame, obj=obj)

    def run(self) -> None:
        recv_timeout_s = max(0.01, float(self.config.get("recv_timeout_s", 0.1)))
        reconnect_delay_s = max(0.1, float(self.config.get("reconnect_delay_s", 2.0)))
        while not self.should_stop():
            try:
                bus = self._connect_bus()
                self._apply_outputs(bus)
                event = self._receive_once(bus, recv_timeout_s)
                if event is not None:
                    self._handle_event(event)
                self._poll_density_requests(bus, __import__("time").monotonic())
            except Exception as exc:
                self._disconnect_bus()
                self._last_pwm_by_node.clear()
                self._last_density_request_s.clear()
                self._set_error(str(exc))
                if self.sleep(reconnect_delay_s):
                    break

        self._disconnect_bus()
        self._set_status("connected", False)


class BrewtoolsKvaserSourceSpec(DataSourceSpec):
    source_type = BrewtoolsKvaserSource.source_type
    display_name = BrewtoolsKvaserSource.display_name
    description = BrewtoolsKvaserSource.description

    def create(self, name: str, client: SupportsSignalRequests, *, config: dict[str, Any] | None = None) -> DataSourceBase:
        return BrewtoolsKvaserSource(name, client, config=config)

    def default_config(self) -> dict[str, Any]:
        return {
            "interface": "kvaser",
            "channel": 0,
            "bitrate": 500000,
            "recv_timeout_s": 0.1,
            "reconnect_delay_s": 2.0,
            "density_request_interval_s": 2.0,
            "parameter_prefix": "brewcan",
            "density_nodes": [],
            "agitator_nodes": [],
            "initial_pwm": 0.0,
        }


SOURCE = BrewtoolsKvaserSourceSpec()
