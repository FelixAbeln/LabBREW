from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from .enums import MsgType
from .frame import CanFrame
from .bodies import FloatBody, NodeIdBody, CalibrationAckBody
from .domain_factory import DomainFactory


# -------------------------
# Domain objects
# -------------------------

@dataclass(frozen=True)
class TemperatureMeasurement:
    node_id: int
    value_c: float
    subindex: int


@dataclass(frozen=True)
class PressureMeasurement:
    node_id: int
    value_bar: float
    subindex: int


@dataclass(frozen=True)
class DensityMeasurement:
    node_id: int
    value: float
    subindex: int


@dataclass(frozen=True)
class LevelMeasurement:
    node_id: int
    value: float
    subindex: int


@dataclass(frozen=True)
class RpmMeasurement:
    node_id: int
    value_rpm: float
    subindex: int


@dataclass(frozen=True)
class MinValue:
    node_id: int
    value: float
    subindex: int


@dataclass(frozen=True)
class MaxValue:
    node_id: int
    value: float
    subindex: int


@dataclass(frozen=True)
class NodeIdUpdate:
    old_node_id: int
    new_node_id: int
    subindex: int


@dataclass(frozen=True)
class CalibrationAck:
    node_id: int
    ack_type: int
    subindex: int
    extra: bytes = b""


DomainObject = Union[
    TemperatureMeasurement,
    PressureMeasurement,
    DensityMeasurement,
    LevelMeasurement,
    RpmMeasurement,
    MinValue,
    MaxValue,
    NodeIdUpdate,
    CalibrationAck,
]


# -------------------------
# Handlers (msg_type specific)
# -------------------------

def _node_id(frame: CanFrame) -> int:
    return int(frame.can_id.secondary_node_id)


def handle_temperature(frame: CanFrame) -> Optional[TemperatureMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return TemperatureMeasurement(_node_id(frame), frame.body.value, frame.body.subindex)


def handle_pressure(frame: CanFrame) -> Optional[PressureMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return PressureMeasurement(_node_id(frame), frame.body.value, frame.body.subindex)


def handle_density(frame: CanFrame) -> Optional[DensityMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return DensityMeasurement(_node_id(frame), frame.body.value, frame.body.subindex)


def handle_level(frame: CanFrame) -> Optional[LevelMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return LevelMeasurement(_node_id(frame), frame.body.value, frame.body.subindex)


def handle_rpm(frame: CanFrame) -> Optional[RpmMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return RpmMeasurement(_node_id(frame), frame.body.value, frame.body.subindex)


def handle_min(frame: CanFrame) -> Optional[MinValue]:
    if not isinstance(frame.body, FloatBody):
        return None
    return MinValue(_node_id(frame), frame.body.value, frame.body.subindex)


def handle_max(frame: CanFrame) -> Optional[MaxValue]:
    if not isinstance(frame.body, FloatBody):
        return None
    return MaxValue(_node_id(frame), frame.body.value, frame.body.subindex)


def handle_node_id(frame: CanFrame) -> Optional[NodeIdUpdate]:
    if not isinstance(frame.body, NodeIdBody):
        return None
    return NodeIdUpdate(old_node_id=_node_id(frame), new_node_id=frame.body.new_node_id, subindex=frame.body.subindex)


def handle_calibration_ack(frame: CanFrame) -> Optional[CalibrationAck]:
    if not isinstance(frame.body, CalibrationAckBody):
        return None
    return CalibrationAck(node_id=_node_id(frame), ack_type=frame.body.ack_type, subindex=frame.body.subindex, extra=frame.body.extra)


# -------------------------
# Registration
# -------------------------

def register_default_domain_handlers() -> None:
    """
    Register standard frame->domain mappings.
    Call once at startup (similar to register_default_bodies()).
    """
    DomainFactory.register(MsgType.MSG_TYPE_TEMPERATURE, handle_temperature)
    DomainFactory.register(MsgType.MSG_TYPE_PRESSURE, handle_pressure)
    DomainFactory.register(MsgType.MSG_TYPE_DENSITY, handle_density)
    DomainFactory.register(MsgType.MSG_TYPE_LEVEL, handle_level)
    DomainFactory.register(MsgType.MSG_TYPE_RPM, handle_rpm)
    DomainFactory.register(MsgType.MSG_TYPE_MIN, handle_min)
    DomainFactory.register(MsgType.MSG_TYPE_MAX, handle_max)

    DomainFactory.register(MsgType.MSG_TYPE_NODE_ID, handle_node_id)
    DomainFactory.register(MsgType.MSG_TYPE_CALIBRATION_ACK, handle_calibration_ack)


# Keep the Level-2 API as a convenience wrapper (optional)
def frame_to_object(frame: CanFrame) -> Optional[DomainObject]:
    obj = DomainFactory.build(frame)
    return obj  # type: ignore[return-value]


